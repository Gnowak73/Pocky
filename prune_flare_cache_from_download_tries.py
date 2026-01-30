#!/usr/bin/env python3
"""Prune flare_cache.tsv using download_tries.tsv (event-level)."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
from pathlib import Path


def parse_iso(s: str) -> dt.datetime | None:
  if not s:
    return None
  return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def parse_event_id(event_id: str) -> tuple[str, dt.datetime] | None:
  if "_" not in event_id:
    return None
  fclass, ts = event_id.split("_", 1)
  try:
    when = dt.datetime.strptime(ts, "%Y%m%d_%H%M%S")
  except ValueError:
    return None
  return fclass, when


def main() -> None:
  p = argparse.ArgumentParser(description="Prune flare_cache.tsv using download_tries.tsv.")
  p.add_argument("--flare-cache", default="flare_cache.tsv", help="Path to flare_cache TSV.")
  p.add_argument("--download-tries", default="download_tries.tsv", help="Path to download_tries TSV.")
  p.add_argument("--in-place", action="store_true", help="Overwrite flare_cache.tsv.")
  p.add_argument(
    "--mode",
    default="empty_only",
    choices=["empty_only", "any_empty", "zero_bytes"],
    help="Prune rule.",
  )
  args = p.parse_args()

  flare_path = Path(args.flare_cache)
  tries_path = Path(args.download_tries)
  if not flare_path.exists():
    raise SystemExit(f"flare_cache.tsv not found: {flare_path}")
  if not tries_path.exists():
    raise SystemExit(f"download_tries.tsv not found: {tries_path}")

  bad_events: set[tuple[str, dt.datetime]] = set()
  with tries_path.open("r", encoding="utf-8") as f:
    reader = csv.DictReader(f, delimiter="\t")
    for row in reader:
      ev = row.get("event_id", "")
      parsed = parse_event_id(ev)
      if not parsed:
        continue
      fclass, when = parsed
      try:
        downloaded_files = int(row.get("downloaded_files", "0"))
      except ValueError:
        downloaded_files = 0
      try:
        downloaded_bytes = int(row.get("downloaded_bytes", "0"))
      except ValueError:
        downloaded_bytes = 0
      try:
        empty_files = int(row.get("empty_files", "0"))
      except ValueError:
        empty_files = 0

      if args.mode == "any_empty":
        if empty_files > 0:
          bad_events.add((fclass, when))
      elif args.mode == "zero_bytes":
        if downloaded_bytes == 0:
          bad_events.add((fclass, when))
      else:  # empty_only
        if downloaded_files == 0 and empty_files > 0:
          bad_events.add((fclass, when))

  with flare_path.open("r", encoding="utf-8") as f:
    reader = csv.DictReader(f, delimiter="\t")
    fieldnames = reader.fieldnames or []
    rows = list(reader)

  kept = []
  removed = 0
  for row in rows:
    start = parse_iso(row.get("start", ""))
    if not start:
      kept.append(row)
      continue
    fclass = " ".join((row.get("flare_class", "") or "").split())
    if (fclass, start) in bad_events:
      removed += 1
      continue
    kept.append(row)

  out_path = flare_path if args.in_place else flare_path.with_suffix(".pruned.tsv")
  with out_path.open("w", encoding="utf-8", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
    writer.writeheader()
    writer.writerows(kept)

  print(f"Removed {removed} rows. Wrote {len(kept)} rows to {out_path}.")


if __name__ == "__main__":
  main()
