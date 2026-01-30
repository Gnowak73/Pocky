#!/usr/bin/env python3
"""Remove AIA event folders missing data in required wavelengths."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
from typing import List


def parse_args() -> argparse.Namespace:
    base = Path(__file__).resolve().parent
    p = argparse.ArgumentParser(
        description="Prune AIA event folders missing data in required wavelengths.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--input",
        default=str(base / "data_aia_lvl1"),
        help="Root directory containing event folders.",
    )
    p.add_argument(
        "--channels",
        default="94,131,171,193,211",
        help="Comma list of required wavelength folders.",
    )
    p.add_argument(
        "--exts",
        default=".fits,.npy",
        help="Comma list of file extensions to count as data.",
    )
    p.add_argument(
        "--delete",
        action="store_true",
        help="Actually delete folders (default is dry-run).",
    )
    return p.parse_args()


def parse_list(value: str, cast) -> List:
    return [cast(v.strip()) for v in value.split(",") if v.strip()]


def has_data(path: Path, exts: List[str]) -> bool:
    for p in path.iterdir():
        if p.is_file() and p.suffix.lower() in exts:
            return True
    return False


def main() -> int:
    args = parse_args()
    root = Path(args.input)
    if not root.exists():
        print(f"Input not found: {root}")
        return 1

    channels = parse_list(args.channels, int)
    exts = [e.lower() for e in parse_list(args.exts, str)]
    to_remove = []

    for event_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        missing = []
        for ch in channels:
            ch_dir = event_dir / str(ch)
            if not ch_dir.is_dir() or not has_data(ch_dir, exts):
                missing.append(str(ch))
        if missing:
            to_remove.append((event_dir, missing))

    for event_dir, missing in to_remove:
        if args.delete:
            shutil.rmtree(event_dir)
            print(f"Deleted {event_dir.name} (missing {','.join(missing)})")
        else:
            print(f"Would delete {event_dir.name} (missing {','.join(missing)})")

    print(f"Checked {len(list(root.iterdir()))} folders. Marked {len(to_remove)} for removal.")
    if not args.delete:
        print("Dry-run only. Re-run with --delete to remove.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
