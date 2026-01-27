#!/usr/bin/env python3
"""Find overlapping timestamps across event folders."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Dict, List, Tuple


TIME_RE = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{6})")


def parse_args() -> argparse.Namespace:
    base = Path(__file__).resolve().parent.parent
    p = argparse.ArgumentParser(
        description="Report timestamps that appear in multiple event folders.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "root",
        nargs="?",
        default=str(base / "data_aia_lvl1"),
        help="Root directory containing event folders.",
    )
    p.add_argument(
        "--pattern",
        default="*.npy,*.fits",
        help="Comma list of glob patterns to scan.",
    )
    p.add_argument(
        "--min-count",
        type=int,
        default=2,
        help="Minimum number of events sharing a timestamp to report.",
    )
    p.add_argument(
        "--max-per-ts",
        type=int,
        default=10,
        help="Max number of event names to show per timestamp.",
    )
    return p.parse_args()


def extract_timestamp(name: str) -> str | None:
    m = TIME_RE.search(name)
    if not m:
        return None
    return m.group(1)


def main() -> int:
    args = parse_args()
    root = Path(args.root)
    if not root.exists():
        print(f"Path not found: {root}")
        return 1

    patterns = [p.strip() for p in args.pattern.split(",") if p.strip()]
    seen: Dict[str, set[str]] = {}

    for event_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        if event_dir.name.isdigit():
            continue
        # walk all files under this event
        files = []
        for pat in patterns:
            files.extend(event_dir.rglob(pat))
        if not files:
            continue
        for f in files:
            ts = extract_timestamp(f.name)
            if ts is None:
                continue
            seen.setdefault(ts, set()).add(event_dir.name)

    overlaps: List[Tuple[str, List[str]]] = []
    for ts, events in seen.items():
        if len(events) >= args.min_count:
            overlaps.append((ts, sorted(events)))

    overlaps.sort(key=lambda x: (-len(x[1]), x[0]))
    if not overlaps:
        print("No overlaps found.")
        return 0

    for ts, events in overlaps:
        shown = events[: args.max_per_ts]
        suffix = "" if len(events) <= args.max_per_ts else f" (+{len(events)-args.max_per_ts} more)"
        print(f"{ts}  count={len(events)}  {', '.join(shown)}{suffix}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
