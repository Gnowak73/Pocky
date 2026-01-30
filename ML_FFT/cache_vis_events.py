#!/usr/bin/env python3
"""Cache visibility maps into per-event tensors for ML."""

from __future__ import annotations

import argparse
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import numpy as np

TIME_RE = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{6})")


def parse_args() -> argparse.Namespace:
    base = Path("/Users/gabe/Github/Pocky")
    p = argparse.ArgumentParser(
        description="Build per-event visibility tensors from vis_maps.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--root",
        default=str(base / "vis_maps"),
        help="Root vis_maps folder (event/wavelength/*.npy).",
    )
    p.add_argument(
        "--output",
        default=str(base / "ML_FFT" / "vis_cache"),
        help="Output folder for cached .npz per event.",
    )
    p.add_argument(
        "--channels",
        default="94,131,171,193,211",
        help="Comma list of wavelength folders to use.",
    )
    p.add_argument(
        "--bin",
        type=int,
        default=4,
        help="Bin size to select from filenames (e.g., *_bin4_vis.npy).",
    )
    p.add_argument(
        "--dtype",
        choices=["float16", "float32"],
        default="float32",
        help="Output dtype for cached tensors.",
    )
    p.add_argument(
        "--min-frames",
        type=int,
        default=10,
        help="Minimum number of aligned frames per event.",
    )
    p.add_argument("--log-scale", action="store_true", help="Apply log1p to magnitudes.")
    p.add_argument(
        "--time-round",
        choices=["none", "minute"],
        default="minute",
        help="Round timestamps for channel alignment (minute recommended).",
    )
    p.add_argument(
        "--tolerance",
        type=float,
        default=60.0,
        help="Tolerance in seconds for minute rounding (0 disables filter).",
    )
    p.add_argument("--verbose", action="store_true")
    return p.parse_args()


def parse_channels(value: str) -> List[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def extract_time(path: Path) -> str | None:
    match = TIME_RE.search(path.name)
    if not match:
        return None
    return match.group(1)


def round_time(ts: str, mode: str, tolerance: float) -> tuple[str | None, float]:
    if mode == "none":
        return ts, 0.0
    dt = datetime.strptime(ts, "%Y-%m-%dT%H%M%S")
    if mode == "minute":
        dt_round = dt.replace(second=0)
        delta = abs((dt - dt_round).total_seconds())
        if tolerance > 0 and delta > tolerance:
            return None, delta
        return dt_round.strftime("%Y-%m-%dT%H:%M"), delta
    return ts, 0.0


def load_amp(path: Path, log_scale: bool) -> np.ndarray:
    vis = np.load(path)
    if np.iscomplexobj(vis):
        vis = np.abs(vis)
    elif vis.ndim == 3 and vis.shape[-1] == 2:
        vis = np.sqrt(vis[..., 0] ** 2 + vis[..., 1] ** 2)
    if log_scale:
        vis = np.log1p(vis)
    return vis


def build_time_map(folder: Path, bin_size: int, time_round: str, tolerance: float) -> Dict[str, Path]:
    out: Dict[str, tuple[Path, float]] = {}
    pattern = f"_bin{bin_size}_vis.npy"
    for p in sorted(folder.glob(f"*{pattern}")):
        ts = extract_time(p)
        if ts:
            key, delta = round_time(ts, time_round, tolerance)
            if key is None:
                continue
            # keep closest-to-minute frame for each key
            if key not in out or delta < out[key][1]:
                out[key] = (p, delta)
    return {k: v[0] for k, v in out.items()}


def cache_event(
    event_dir: Path,
    channels: List[str],
    bin_size: int,
    log_scale: bool,
    time_round: str,
    tolerance: float,
) -> Tuple[str, np.ndarray, List[str]]:
    channel_maps: List[Dict[str, Path]] = []
    for ch in channels:
        ch_dir = event_dir / ch
        if not ch_dir.exists():
            return event_dir.name, np.empty((0,)), []
        channel_maps.append(build_time_map(ch_dir, bin_size, time_round, tolerance))

    if not channel_maps:
        return event_dir.name, np.empty((0,)), []

    common_times = set(channel_maps[0].keys())
    for m in channel_maps[1:]:
        common_times &= set(m.keys())
    times = sorted(common_times)
    if not times:
        return event_dir.name, np.empty((0,)), []

    frames: List[np.ndarray] = []
    for ts in times:
        chans: List[np.ndarray] = []
        for ch_map in channel_maps:
            arr = load_amp(ch_map[ts], log_scale)
            chans.append(arr)
        frame = np.stack(chans, axis=0)
        frames.append(frame)

    vis = np.stack(frames, axis=0)  # (T, C, Nv, Nu)
    return event_dir.name, vis, times


def main() -> int:
    args = parse_args()
    root = Path(args.root)
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    channels = parse_channels(args.channels)
    dtype = np.float16 if args.dtype == "float16" else np.float32

    event_dirs = [p for p in sorted(root.iterdir()) if p.is_dir()]
    if not event_dirs:
        print(f"No events found under {root}")
        return 1

    kept = 0
    for event_dir in event_dirs:
        name, vis, times = cache_event(
            event_dir,
            channels,
            args.bin,
            args.log_scale,
            args.time_round,
            args.tolerance,
        )
        if vis.size == 0 or len(times) < args.min_frames:
            if args.verbose:
                print(f"Skipped {name} (insufficient frames)")
            continue
        vis = vis.astype(dtype, copy=False)
        out_path = out_dir / f"{name}.npz"
        np.savez_compressed(out_path, vis=vis, times=np.array(times), channels=np.array(channels))
        kept += 1
        if args.verbose:
            print(f"Cached {name} ({len(times)} frames)")

    print(f"Saved {kept} events to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
