#!/usr/bin/env python3
"""Build sliding-window index for visibility caches."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np


def parse_args() -> argparse.Namespace:
    base = Path("/Users/gabe/Github/Pocky")
    p = argparse.ArgumentParser(
        description="Build sliding-window index for vis_cache events.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--cache",
        default=str(base / "ML_FFT" / "vis_cache"),
        help="Folder with per-event vis_cache .npz files.",
    )
    p.add_argument(
        "--flare-cache",
        default=str(base / "flare_cache.tsv"),
        help="flare_cache.tsv with GOES start times.",
    )
    p.add_argument(
        "--output",
        default=str(base / "ML_FFT" / "vis_index.npz"),
        help="Output index file.",
    )
    p.add_argument("--window-min", type=float, default=15.0, help="Window length in minutes.")
    p.add_argument("--stride-min", type=float, default=1.0, help="Stride in minutes.")
    p.add_argument("--horizon-min", type=float, default=5.0, help="Prediction horizon in minutes.")
    p.add_argument("--preflare-only", action="store_true", help="Exclude windows that include post-onset frames.")
    p.add_argument(
        "--min-class",
        default="C5.0",
        help="Minimum GOES class to include (e.g., C1.0, C5.0, M1.0).",
    )
    return p.parse_args()


def parse_goes_class(value: str) -> Tuple[int, float] | None:
    value = value.strip().upper()
    if not value:
        return None
    letter = value[0]
    try:
        mag = float(value[1:])
    except ValueError:
        return None
    order = {"A": 0, "B": 1, "C": 2, "M": 3, "X": 4}
    if letter not in order:
        return None
    return order[letter], mag


def parse_flare_cache(path: Path, min_class: str) -> Dict[str, datetime]:
    # Map event_name -> flare start time (filtered by class)
    out: Dict[str, datetime] = {}
    min_key = parse_goes_class(min_class)
    if min_key is None:
        raise ValueError(f"Invalid min-class: {min_class}")
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            cls = row.get("flare_class", "").strip()
            start = row.get("start", "").strip()
            if not cls or not start:
                continue
            cls_key = parse_goes_class(cls)
            if cls_key is None or cls_key < min_key:
                continue
            try:
                dt = datetime.fromisoformat(start.replace("Z", ""))
            except ValueError:
                continue
            event = f"{cls}_{dt.strftime('%Y%m%d_%H%M%S')}"
            out[event] = dt
    return out


def main() -> int:
    args = parse_args()
    cache_dir = Path(args.cache)
    flare_cache = Path(args.flare_cache)
    out_path = Path(args.output)

    if not cache_dir.exists():
        print(f"Cache folder not found: {cache_dir}")
        return 1
    if not flare_cache.exists():
        print(f"flare_cache not found: {flare_cache}")
        return 1

    t0_map = parse_flare_cache(flare_cache, args.min_class)
    cache_files = sorted(cache_dir.glob("*.npz"))
    if not cache_files:
        print(f"No cache files in {cache_dir}")
        return 1

    events: List[str] = []
    start_idx: List[int] = []
    end_idx: List[int] = []
    labels: List[int] = []

    for cf in cache_files:
        event = cf.stem
        if event not in t0_map:
            continue
        data = np.load(cf, allow_pickle=False)
        times = data["times"].astype(str).tolist()
        if len(times) < 2:
            continue
        # parse times
        dt_list = []
        for t in times:
            try:
                dt_list.append(datetime.strptime(t, "%Y-%m-%dT%H%M%S"))
            except ValueError:
                dt_list.append(datetime.strptime(t, "%Y-%m-%dT%H:%M"))
        # estimate cadence
        deltas = np.diff([t.timestamp() for t in dt_list])
        dt_sec = float(np.median(deltas)) if len(deltas) else 60.0
        if dt_sec <= 0:
            continue
        win_frames = int(round(args.window_min * 60.0 / dt_sec))
        stride_frames = int(round(args.stride_min * 60.0 / dt_sec))
        if win_frames < 2 or stride_frames < 1:
            continue
        t0 = t0_map[event]
        horizon = timedelta(minutes=args.horizon_min)

        for end in range(win_frames - 1, len(dt_list), stride_frames):
            t_end = dt_list[end]
            if args.preflare_only and t_end > t0:
                break
            t_start = dt_list[end - win_frames + 1]
            if t_start > t_end:
                continue
            y = 1 if (t0 > t_end and t0 <= (t_end + horizon)) else 0
            events.append(event)
            start_idx.append(end - win_frames + 1)
            end_idx.append(end)
            labels.append(y)

    np.savez_compressed(
        out_path,
        event=np.array(events),
        start=np.array(start_idx, dtype=np.int32),
        end=np.array(end_idx, dtype=np.int32),
        label=np.array(labels, dtype=np.int8),
        window_min=np.array(args.window_min, dtype=np.float32),
        stride_min=np.array(args.stride_min, dtype=np.float32),
        horizon_min=np.array(args.horizon_min, dtype=np.float32),
    )
    ones = int(np.sum(labels))
    zeros = int(len(labels) - ones)
    print(f"Saved index to {out_path} | ones={ones} zeros={zeros} windows={len(labels)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
