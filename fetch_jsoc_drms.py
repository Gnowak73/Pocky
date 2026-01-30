#!/usr/bin/env python3
"""Download AIA FITS from JSOC windows listed in a TSV cache.

Expects a TSV with columns:
  description  flare_class  start  end  coordinates  wavelength
Times in TSV are ISO (with T/Z). Wavelength may be a comma list.
"""

import argparse
import csv
import datetime as dt
import logging
import os
import re
import sys
import time
import shutil
from pathlib import Path
from typing import List, Dict

try:
  import drms
  from parfive import Downloader
except ImportError:
  sys.exit(
    "Missing dependency: drms/parfive. Install with "
    "'pip install -r requirements.txt' or 'conda install -c conda-forge drms parfive'."
  )

logging.getLogger("drms").setLevel(logging.WARNING)
logging.getLogger("parfive").setLevel(logging.WARNING)

def parse_args() -> argparse.Namespace:
  p = argparse.ArgumentParser(description="Download AIA FITS from JSOC using a flare cache TSV.")
  p.add_argument("--tsv", default="flare_cache.tsv", help="Path to TSV produced by Pocky.")
  p.add_argument("--out", default="data_aia_lvl1", help="Output directory for downloads.")
  p.add_argument("--email", default=os.environ.get("JSOC_EMAIL"), help="JSOC email (env JSOC_EMAIL honored).")
  p.add_argument("--max-conn", type=int, default=6, help="Downloader max connections.")
  p.add_argument("--max-splits", type=int, default=3, help="Downloader max splits.")
  p.add_argument("--attempts", type=int, default=5, help="Max attempts per window/wavelength.")
  p.add_argument("--cadence", default="12s", help="Cadence string for JSOC query.")
  p.add_argument("--pad-before", type=float, default=0.0, help="Minutes to include before event start.")
  p.add_argument("--pad-after", type=float, default=None, help="Minutes to include after event start (blank = through event end).")
  p.add_argument("--series", default="aia.lev1_euv_12s", help="JSOC series (fixed per caller).")
  p.add_argument("--aia-scale", action="store_true", help="Apply aia_scale_aialev1 processing (for level 1.5).")
  return p.parse_args()


def parse_iso(s: str) -> dt.datetime | None:
  if not s:
    return None
  return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def time_range(a: dt.datetime, b: dt.datetime, cadence: str | None = None) -> str:
  s = f"{a:%Y.%m.%d_%H:%M:%S}-{b:%Y.%m.%d_%H:%M:%S}"
  return f"{s}@{cadence}" if cadence else s


def parse_cadence_seconds(cadence: str | None) -> float | None:
  if not cadence:
    return None
  m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)([smhd])\s*", cadence)
  if not m:
    return None
  value = float(m.group(1))
  unit = m.group(2)
  if unit == "s":
    return value
  if unit == "m":
    return value * 60.0
  if unit == "h":
    return value * 3600.0
  if unit == "d":
    return value * 86400.0
  return None


def expected_fits_count(start: dt.datetime, end: dt.datetime, cadence_s: float) -> int:
  if cadence_s <= 0:
    return 0
  if end < start:
    return 0
  total = (end - start).total_seconds()
  return int(total // cadence_s) + 1


def prune_incomplete_event_dirs(out_root: Path, events: list[dict]) -> int:
  removed = 0
  for row in events:
    if row.get("complete_event"):
      continue
    start = row["start"]
    win_id = f"{row['class'] or 'flare'}_{start:%Y%m%d_%H%M%S}"
    edir = out_root / win_id
    if edir.exists():
      shutil.rmtree(edir)
      removed += 1
  return removed


def clean_event_dir(out_root: Path, win_id: str) -> None:
  edir = out_root / win_id
  if edir.exists():
    shutil.rmtree(edir)


def load_rows(tsv_path: Path) -> list[dict]:
  if not tsv_path.exists():
    sys.exit(f"TSV not found: {tsv_path}")
  rows = []
  with tsv_path.open("r", encoding="utf-8") as f:
    reader = csv.DictReader(f, delimiter="\t")
    for r in reader:
      start = parse_iso(r.get("start", ""))
      end = parse_iso(r.get("end", ""))
      if not start or not end:
        continue
      waves = [int(w) for w in r.get("wavelength", "").split(",") if w.strip().isdigit()]
      desc = " ".join(r.get("description", "").split())
      fclass = " ".join(r.get("flare_class", "").split())
      coords = " ".join(r.get("coordinates", "").split())
      rows.append({
        "start": start,
        "end": end,
        "class": fclass,
        "waves": waves or [],
        "desc": desc,
      })
  return rows


def filter_existing(urls: list[str], dest_dir: Path) -> tuple[list[str], list[str]]:
  pending = []
  skipped: list[str] = []
  for u in urls:
    fname = u.rsplit("/", 1)[-1]
    fpath = dest_dir / fname
    if fpath.exists():
      skipped.append(str(fpath))
      continue
    pending.append(u)
  return pending, skipped


def inspect_download(
  files: list[Path],
  urls: list[str],
  dest_dir: Path,
) -> tuple[int, int, int, set[str]]:
  downloaded_files = 0
  downloaded_bytes = 0
  empty_files = 0
  empty_urls: set[str] = set()
  url_by_name = {u.rsplit("/", 1)[-1]: u for u in urls}
  if not files:
    files = [dest_dir / u.rsplit("/", 1)[-1] for u in urls]
  for fpath in files:
    if not isinstance(fpath, Path):
      fpath = Path(fpath)
    try:
      size = fpath.stat().st_size
    except OSError:
      size = 0
    if size == 0:
      empty_files += 1
    downloaded_files += 1
    downloaded_bytes += size
  return downloaded_files, downloaded_bytes, empty_files, empty_urls


def count_fits(dest_dir: Path) -> int:
  if not dest_dir.exists():
    return 0
  return sum(1 for p in dest_dir.iterdir() if p.is_file() and p.suffix.lower() == ".fits")


def count_all_fits(root: Path) -> int:
  if not root.exists():
    return 0
  return sum(1 for p in root.rglob("*.fits") if p.is_file())


def stage_urls(client: drms.Client, record: str, process: dict | None, attempts: int = 3) -> list[str]:
  urls: list[str] = []
  for attempt in range(1, attempts + 1):
    try:
      req = client.export(record, method="url", protocol="fits", process=process)
      ok = req.wait(timeout=None, sleep=8, retries_notfound=3)
      if ok and req.urls is not None and not req.urls.empty:
        urls = [r.url for r in req.urls.itertuples(index=False)]
        break
    except Exception as e:
      logging.warning("Export error attempt %s: %s", attempt, e)
    # mild backoff between staging attempts
    delay = min(8, 2 * attempt)
    if attempt < attempts:
      time.sleep(delay)
  return urls


def wave_from_url(url: str, waves: set[int]) -> int | None:
  fname = url.rsplit("/", 1)[-1]
  m = re.search(r"\.(\d{2,3})\.image", fname)
  if m:
    try:
      w = int(m.group(1))
      if w in waves:
        return w
    except ValueError:
      pass
  for part in fname.split("."):
    if part.isdigit():
      try:
        w = int(part)
      except ValueError:
        continue
      if w in waves:
        return w
  return None


def main() -> None:
  args = parse_args()
  if not args.email:
    sys.exit("Set JSOC email via --email or JSOC_EMAIL.")

  tsv_path = Path(args.tsv)
  events = load_rows(tsv_path)
  if not events:
    sys.exit("No usable rows found in TSV.")

  client = drms.Client(email=args.email)
  out_root = Path(args.out)
  out_root.mkdir(parents=True, exist_ok=True)
  stage_attempts = 3
  restage_attempts = 1

  base_fits = count_all_fits(out_root)
  total_files = 0          # new files this run
  skipped_existing = set() # file paths seen as already present
  event_results: List[Dict] = []
  download_tsv = Path("download_tries.tsv")
  download_fh = download_tsv.open("a", encoding="utf-8", newline="")
  download_writer = csv.DictWriter(
    download_fh,
    fieldnames=[
      "event_id",
      "flare_class",
      "start",
      "end",
      "wavelengths",
      "attempted_urls",
      "downloaded_files",
      "downloaded_bytes",
      "empty_files",
      "failed_files",
    ],
    delimiter="\t",
  )
  if download_tsv.stat().st_size == 0:
    download_writer.writeheader()
  total_events = len(events)
  total_events_all = total_events
  complete_events = 0

  def status_line(cur: int, total: int, current_id: str = "") -> str:
    term_width = shutil.get_terminal_size((80, 20)).columns
    bar_width = max(20, min(50, term_width - 50))
    done = int((cur / total) * bar_width) if total else bar_width
    bar = "#" * done + "-" * (bar_width - done)
    current_total = count_all_fits(out_root)
    new_count = max(0, current_total - base_fits)
    summary = f"[{bar}] {cur}/{total} events | new:{new_count} | skipped:{len(skipped_existing)}"
    if current_id:
      summary += f" | {current_id}"
    if len(summary) > term_width:
      summary = summary[: term_width - 3] + "..."
    return summary

  def render_status(cur: int, total: int, current_id: str = "") -> None:
    line = status_line(cur, total, current_id)
    sys.stdout.write("\r\033[2K" + line)
    sys.stdout.flush()

  # Seed skipped count from existing files on disk.
  if out_root.exists():
    skipped_existing.update(str(p) for p in out_root.rglob("*.fits") if p.is_file())

  cadence_s = parse_cadence_seconds(args.cadence)
  if cadence_s is None:
    print(f"Precheck disabled: unrecognized cadence '{args.cadence}'.")
    for row in events:
      row["complete_event"] = False
  else:
    for row in events:
      start, end = row["start"], row["end"]
      start_padded = start - dt.timedelta(minutes=args.pad_before)
      if args.pad_after is None:
        end_padded = end
      else:
        end_padded = start + dt.timedelta(minutes=args.pad_after)
      row["start_padded"] = start_padded
      row["end_padded"] = end_padded

      waves = row["waves"] or []
      row["expected_counts"] = {}
      row["complete_event"] = False
      if not waves or start_padded >= end_padded:
        continue

      win_id = f"{row['class'] or 'flare'}_{start:%Y%m%d_%H%M%S}"
      total_expected = 0
      total_have = 0
      all_complete = True
      for w in waves:
        expected = expected_fits_count(start_padded, end_padded, cadence_s)
        row["expected_counts"][w] = expected
        total_expected += expected
        dest_dir = out_root / win_id / str(w)
        have = count_fits(dest_dir)
        total_have += have
        if expected <= 0 or have < expected:
          all_complete = False
      missing_total = max(0, total_expected - total_have)
      if all_complete or missing_total <= 10:
        row["complete_event"] = True
        complete_events += 1
      render_status(complete_events, total_events, "precheck")
    render_status(complete_events, total_events, "precheck")
    print()
    print(f"Precheck: {complete_events}/{total_events} events complete.")
    removed = prune_incomplete_event_dirs(out_root, events)
    print(f"Precheck cleanup: removed {removed} incomplete event folder(s).")

  pending_events = [row for row in events if not row.get("complete_event")]
  print(f"Starting downloads for {len(pending_events)}/{total_events_all} incomplete events.")
  total_events = len(pending_events)

  for idx, row in enumerate(pending_events, 1):
    cur_base = complete_events + idx - 1
    cur_done = complete_events + idx
    render_status(cur_base, total_events_all)
    start, end, cls, desc = row["start"], row["end"], row["class"], row["desc"]
    start_padded = row.get("start_padded") or (start - dt.timedelta(minutes=args.pad_before))
    if "end_padded" in row:
      end_padded = row["end_padded"]
    elif args.pad_after is None:
      end_padded = end
    else:
      end_padded = start + dt.timedelta(minutes=args.pad_after)
    waves = row["waves"] or []
    if start_padded >= end_padded:
      print(f"\n[{idx}] Skip invalid window: {start_padded} >= {end_padded}")
      render_status(cur_done, total_events_all)
      continue
    if not waves:
      print(f"\n[{idx}] No wavelengths listed; skipping window {start}–{end}")
      render_status(cur_done, total_events_all)
      continue

    win_id = f"{cls or 'flare'}_{start:%Y%m%d_%H%M%S}"
    print(f"\n[{idx}] {desc or win_id}")
    expected_counts = row.get("expected_counts", {})
    if row.get("complete_event"):
      counts = []
      for ww in sorted(waves):
        wdir = out_root / win_id / str(ww)
        counts.append(f"{ww}A={count_fits(wdir)}/{expected_counts.get(ww, 0)}")
      print(f"  [{win_id}] already complete ({', '.join(counts)}).")
      render_status(cur_done, total_events_all, win_id)
      event_results.append({"id": win_id, "downloaded": 0, "failed": []})
      continue
    clean_event_dir(out_root, win_id)
    win_downloaded = 0
    win_failed = []
    event_attempted = 0
    event_downloaded_files = 0
    event_downloaded_bytes = 0
    event_empty_files = 0
    process = {"aia_scale_aialev1": {None: None}} if args.aia_scale else None
    wave_set = {int(w) for w in waves}
    combined_urls = []
    if wave_set:
      wave_clause = ",".join(str(w) for w in sorted(wave_set))
      record = f'{args.series}[{time_range(start_padded, end_padded, args.cadence)}][? WAVELNTH in ({wave_clause}) ?]{{image}}'
      combined_urls = stage_urls(client, record, process, attempts=stage_attempts)
    staged_by_wave = None
    if combined_urls:
      staged_by_wave = {w: [] for w in wave_set}
      unmatched = 0
      for u in combined_urls:
        w = wave_from_url(u, wave_set)
        if w is None:
          unmatched += 1
          continue
        staged_by_wave[w].append(u)
      if unmatched:
        staged_by_wave = None

    for w in waves:
      dest_dir = out_root / win_id / str(w)
      dest_dir.mkdir(parents=True, exist_ok=True)
      pre_count = count_fits(dest_dir)

      if staged_by_wave is not None:
        staged_urls = staged_by_wave.get(int(w), [])
      else:
        record = f'{args.series}[{time_range(start_padded, end_padded, args.cadence)}][? WAVELNTH={w} ?]{{image}}'
        staged_urls = stage_urls(client, record, process, attempts=stage_attempts)
      if not staged_urls:
        print(f"  [{win_id}] {w}A export returned no URLs.")
        render_status(cur_base, total_events_all, win_id)
        continue

      attempt = 0
      pending_urls = list(staged_urls)

      while pending_urls and attempt < args.attempts:
        attempt += 1

        # lighten load on later attempts
        factor = min(4, 2 ** (attempt - 1))
        max_conn = max(1, args.max_conn // factor)
        max_splits = max(1, args.max_splits // factor)
        urls_to_fetch = pending_urls

        dl = Downloader(max_conn=max_conn, max_splits=max_splits)
        for u in urls_to_fetch:
          dl.enqueue_file(u, path=str(dest_dir))
        res = dl.download()

        errors = [e.url for e in getattr(res, "errors", [])] if res else urls_to_fetch
        files = list(getattr(res, "files", [])) if res else []
        event_attempted += len(urls_to_fetch)
        got_files, got_bytes, empty_files, empty_urls = inspect_download(
          files,
          urls_to_fetch,
          dest_dir,
        )
        event_downloaded_files += got_files
        event_downloaded_bytes += got_bytes
        event_empty_files += empty_files

        total_files += len(files)
        win_downloaded += len(files)
        render_status(cur_base, total_events_all, win_id)

        # If errors persist, fall back to new export after all attempts
        pending_urls = list(errors)

        if pending_urls:
          backoff = min(30, 4 * attempt)
          time.sleep(backoff)
      if pending_urls:
        # Final serial try with fresh staging and HTTP
        restaged = stage_urls(client, record, process, attempts=restage_attempts)
        if restaged:
          pending_urls = list(restaged)
          if pending_urls:
            dl = Downloader(max_conn=1, max_splits=1)
            for u in pending_urls:
              dl.enqueue_file(u, path=str(dest_dir))
            res = dl.download()
            errors = [e.url for e in getattr(res, "errors", [])] if res else pending_urls
            files = list(getattr(res, "files", [])) if res else []
            event_attempted += len(pending_urls)
            got_files, got_bytes, empty_files, empty_urls = inspect_download(
              files,
              pending_urls,
              dest_dir,
            )
            event_downloaded_files += got_files
            event_downloaded_bytes += got_bytes
            event_empty_files += empty_files

            total_files += len(files)
            win_downloaded += len(files)
            pending_urls = list(errors)
            render_status(cur_base, total_events_all, win_id)

      if pending_urls:
        print(f"  [{win_id}] {w}A — failed to fetch {len(pending_urls)} file(s) after all retries")
        win_failed.append((w, len(pending_urls)))
      render_status(cur_base, total_events_all, win_id)
    event_results.append({"id": win_id, "downloaded": win_downloaded, "failed": win_failed})
    render_status(cur_done, total_events_all, win_id)
    download_writer.writerow({
      "event_id": win_id,
      "flare_class": cls,
      "start": start.isoformat(),
      "end": end.isoformat(),
      "wavelengths": ",".join(str(w) for w in waves),
      "attempted_urls": event_attempted,
      "downloaded_files": event_downloaded_files,
      "downloaded_bytes": event_downloaded_bytes,
      "empty_files": event_empty_files,
      "failed_files": sum(n for _, n in win_failed),
    })
    download_fh.flush()

  print()  # newline after progress bar
  for res in event_results:
    msg = f"{res['id']}: {res['downloaded']} files"
    if res["failed"]:
      fails = ", ".join(f"{w}A:{n}fail" for w, n in res["failed"])
      msg += f" (failed {fails})"
    print(msg)

  download_fh.close()
  print(f"Done. New FITS files: {total_files}. Skipped existing: {len(skipped_existing)}.")


if __name__ == "__main__":
  main()
