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


def load_rows(tsv_path: Path) -> list[dict]:
  if not tsv_path.exists():
    sys.exit(f"TSV not found: {tsv_path}")
  rows = []
  seen = set()
  with tsv_path.open("r", encoding="utf-8") as f:
    reader = csv.DictReader(f, delimiter="\t")
    for r in reader:
      start = parse_iso(r.get("start", ""))
      end = parse_iso(r.get("end", ""))
      if not start or not end:
        continue
      waves = [int(w) for w in r.get("wavelength", "").split(",") if w.strip().isdigit()]
      key = (start, end, tuple(sorted(waves)), r.get("flare_class", "").strip(), r.get("description", "").strip())
      if key in seen:
        continue
      seen.add(key)
      rows.append({
        "start": start,
        "end": end,
        "class": r.get("flare_class", "").strip(),
        "waves": waves or [],
        "desc": r.get("description", "").strip(),
      })
  return rows


def filter_existing(urls: list[str], dest_dir: Path) -> tuple[list[str], list[str]]:
  pending = []
  skipped: list[str] = []
  for u in urls:
    fname = u.rsplit("/", 1)[-1]
    if (dest_dir / fname).exists():
      skipped.append(str(dest_dir / fname))
      continue
    pending.append(u)
  return pending, skipped


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
      ok = req.wait(timeout=None, sleep=15, retries_notfound=5)
      if ok and req.urls is not None and not req.urls.empty:
        urls = [r.url for r in req.urls.itertuples(index=False)]
        break
    except Exception as e:
      logging.warning("Export error attempt %s: %s", attempt, e)
    # mild backoff between staging attempts
    delay = min(10, 2 * attempt)
    if attempt < attempts:
      time.sleep(delay)
  return urls


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

  base_fits = count_all_fits(out_root)
  total_files = 0          # new files this run
  skipped_existing = set() # file paths seen as already present
  event_results: List[Dict] = []
  total_events = len(events)

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

  for idx, row in enumerate(events, 1):
    render_status(idx - 1, total_events)
    start, end, cls, desc = row["start"], row["end"], row["class"], row["desc"]
    start_padded = start - dt.timedelta(minutes=args.pad_before)
    if args.pad_after is None:
      end_padded = end
    else:
      end_padded = start + dt.timedelta(minutes=args.pad_after)
    waves = row["waves"] or []
    if start_padded >= end_padded:
      print(f"\n[{idx}] Skip invalid window: {start_padded} >= {end_padded}")
      render_status(idx, total_events)
      continue
    if not waves:
      print(f"\n[{idx}] No wavelengths listed; skipping window {start}–{end}")
      render_status(idx, total_events)
      continue

    win_id = f"{cls or 'flare'}_{start:%Y%m%d_%H%M%S}"
    print(f"\n[{idx}] {desc or win_id}")
    win_downloaded = 0
    win_failed = []
    process = {"aia_scale_aialev1": {None: None}} if args.aia_scale else None

    for w in waves:
      record = f'{args.series}[{time_range(start_padded, end_padded, args.cadence)}][? WAVELNTH={w} ?]{{image}}'
      dest_dir = out_root / win_id / str(w)
      dest_dir.mkdir(parents=True, exist_ok=True)
      pre_count = count_fits(dest_dir)

      staged_urls = stage_urls(client, record, process, attempts=3)
      if not staged_urls:
        print(f"  [{win_id}] {w}A export returned no URLs.")
        render_status(idx - 1, total_events, win_id)
        continue

      attempt = 0
      pending_urls, skipped = filter_existing(staged_urls, dest_dir)
      skipped_existing.update(skipped)
      if not pending_urls:
        if skipped:
          print(f"  [{win_id}] {w}A already downloaded ({len(skipped)} file(s) present).")
        render_status(idx - 1, total_events, win_id)
        continue

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

        total_files += len(files)
        win_downloaded += len(files)
        render_status(idx - 1, total_events, win_id)

        # If errors persist and we used https, fall back to new export once mid-way
        pending_urls = errors
        if pending_urls and attempt == (args.attempts // 2):
          restaged = stage_urls(client, record, process, attempts=2)
          if restaged:
            pending_urls, skipped = filter_existing(restaged, dest_dir)
            skipped_existing.update(skipped)

        if pending_urls:
          backoff = min(30, 4 * attempt)
          time.sleep(backoff)
      if pending_urls:
        # Final serial try with fresh staging and HTTP
        restaged = stage_urls(client, record, process, attempts=1)
        if restaged:
          pending_urls, skipped = filter_existing(restaged, dest_dir)
          skipped_existing.update(skipped)
          if pending_urls:
            dl = Downloader(max_conn=1, max_splits=1)
            for u in pending_urls:
              dl.enqueue_file(u, path=str(dest_dir))
            res = dl.download()
            errors = [e.url for e in getattr(res, "errors", [])] if res else pending_urls
            files = list(getattr(res, "files", [])) if res else []

            total_files += len(files)
            win_downloaded += len(files)
            pending_urls = errors
            render_status(idx - 1, total_events, win_id)

        if pending_urls:
          print(f"  [{win_id}] {w}A — failed to fetch {len(pending_urls)} file(s) after all retries")
          win_failed.append((w, len(pending_urls)))
      render_status(idx - 1, total_events, win_id)
    event_results.append({"id": win_id, "downloaded": win_downloaded, "failed": win_failed})
    render_status(idx, total_events, win_id)

  print()  # newline after progress bar
  for res in event_results:
    msg = f"{res['id']}: {res['downloaded']} files"
    if res["failed"]:
      fails = ", ".join(f"{w}A:{n}fail" for w, n in res["failed"])
      msg += f" (failed {fails})"
    print(msg)

  print(f"Done. New FITS files: {total_files}. Skipped existing: {len(skipped_existing)}.")


if __name__ == "__main__":
  main()
