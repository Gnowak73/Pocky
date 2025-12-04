#!/usr/bin/env python3
"""Download AIA FITS using SunPy Fido (JSOC or VSO) from flare_cache.tsv (level 1 only)."""

import argparse
import csv
import datetime as dt
import logging
import os
import sys
import time
from pathlib import Path

import astropy.units as u
from sunpy.net import Fido, attrs as a

logging.getLogger("sunpy.net.jsoc").setLevel(logging.WARNING)


def parse_args() -> argparse.Namespace:
  p = argparse.ArgumentParser(description="Download AIA FITS with Fido using a flare cache TSV.")
  p.add_argument("--tsv", default="flare_cache.tsv", help="Path to TSV produced by Pocky.")
  p.add_argument("--out", default="data_aia_lvl1", help="Output directory for downloads.")
  p.add_argument("--email", default=os.environ.get("JSOC_EMAIL"), help="JSOC email (env JSOC_EMAIL honored).")
  p.add_argument("--provider", choices=["jsoc", "vso"], default="jsoc", help="Data provider (JSOC or VSO).")
  p.add_argument("--pad-before", type=float, default=0.0, help="Minutes to include before event start.")
  p.add_argument("--pad-after", type=float, default=None, help="Minutes after start (blank = to event end).")
  p.add_argument("--cadence", type=float, default=12.0, help="Cadence in seconds.")
  p.add_argument("--series", default="aia.lev1_euv_12s", help="JSOC series to query (default level 1).")
  p.add_argument("--max-conn", type=int, default=6, help="Downloader max connections.")
  p.add_argument("--max-splits", type=int, default=3, help="Downloader max splits.")
  p.add_argument("--attempts", type=int, default=3, help="Fetch attempts per event.")
  return p.parse_args()


def parse_iso(s: str) -> dt.datetime | None:
  if not s:
    return None
  return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


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
      if not waves:
        continue
      rows.append({
        "start": start,
        "end": end,
        "class": r.get("flare_class", "").strip(),
        "waves": waves,
        "desc": r.get("description", "").strip(),
      })
  return rows


def main() -> None:
  args = parse_args()
  if args.provider == "jsoc" and not args.email:
    sys.exit("Set JSOC email via --email or JSOC_EMAIL.")

  rows = load_rows(Path(args.tsv))
  if not rows:
    sys.exit("No usable rows found in TSV.")

  out_root = Path(args.out)
  out_root.mkdir(parents=True, exist_ok=True)

  total_files = 0

  for idx, row in enumerate(rows, 1):
    start, end = row["start"], row["end"]
    start_pad = start - dt.timedelta(minutes=args.pad_before)
    end_pad = end if args.pad_after is None else start + dt.timedelta(minutes=args.pad_after)
    if start_pad >= end_pad:
      print(f"[{idx}] skip invalid interval {start_pad} >= {end_pad}")
      continue

    waves = row["waves"]
    cls = row["class"] or "flare"
    desc = row["desc"] or f"{cls}_{start:%Y%m%d_%H%M%S}"
    print(f"[{idx}] {desc}")

    combined = []
    for w in waves:
      if args.provider == "jsoc":
        atrs = [
          a.Time(start_pad, end_pad),
          a.jsoc.Series(args.series),
          a.jsoc.Notify(args.email),
          a.jsoc.Segment("image"),
          a.jsoc.PrimeKey("WAVELNTH", int(w)),
        ]
      else:  # VSO
        atrs = [
          a.Time(start_pad, end_pad),
          a.Instrument("AIA"),
          a.Wavelength(w * u.angstrom),
          a.Sample(args.cadence * u.s),
        ]

      try:
        res = Fido.search(*atrs)
      except Exception as e:
        print(f"  [{desc}] {w}A search failed: {e}")
        continue

      if len(res) == 0:
        print(f"  [{desc}] {w}A search returned no records.")
        continue

      combined.append(res)
      print(f"  [{desc}] {w}A search found {len(res)} record(s)")

    if not combined:
      continue

    dest = out_root / f"{cls}_{start:%Y%m%d_%H%M%S}"
    dest.mkdir(parents=True, exist_ok=True)

    got = 0
    for attempt in range(1, args.attempts + 1):
      try:
        files = Fido.fetch(
          *combined,
          path=str(dest / "{file}"),
          downloader_kwargs={"max_conn": args.max_conn, "max_splits": args.max_splits},
          progress=True,
        )
        got = len(files or [])
        if got:
          break
      except Exception as e:
        print(f"  [{desc}] fetch attempt {attempt} failed: {e}")
        time.sleep(min(10, 2 * attempt))

    total_files += got
    print(f"  [{desc}] total → {got} file(s)")
    time.sleep(0.5)

  print(f"Done. Total FITS fetched: {total_files}")


if __name__ == "__main__":
  main()
