#!/usr/bin/env python3
"""Plot visibility amplitude or red/blue difference maps (Massa & Emslie style)."""

from __future__ import annotations

import argparse
import random
from pathlib import Path

import numpy as np


def parse_args() -> argparse.Namespace:
    base = Path("/Users/gabe/Github/Pocky")
    p = argparse.ArgumentParser(
        description="Plot visibility amplitude or difference maps.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "paths",
        nargs="*",
        help="One .npy file (amplitude) or two .npy files (difference).",
    )
    p.add_argument(
        "--root",
        default=str(base / "vis_maps"),
        help="Root folder for visibility maps.",
    )
    p.add_argument(
        "--uv-grid",
        default=str(base / "Vis" / "uv_grid.npz"),
        help="uv_grid.npz with u_vals/v_vals for axis scaling.",
    )
    p.add_argument(
        "--pick",
        choices=["random", "last-in-event"],
        default="random",
        help="How to choose files when no paths are given.",
    )
    p.add_argument(
        "--wavelength",
        type=str,
        default="",
        help="Restrict to a specific wavelength folder (e.g., 94,131).",
    )
    p.add_argument("--log-scale", action="store_true", help="Apply log1p before plotting.")
    p.add_argument(
        "--vmin",
        type=float,
        default=0.0,
        help="Lower color scale bound (values below are black).",
    )
    p.add_argument(
        "--vmax",
        type=float,
        default=0.0,
        help="Upper color scale bound (0 = auto).",
    )
    p.add_argument(
        "--cmap",
        default="hot",
        help="Matplotlib colormap for amplitude map.",
    )
    p.add_argument(
        "--floor",
        type=float,
        default=0.0,
        help="Mask values <= floor to black (0 disables).",
    )
    return p.parse_args()


def pick_file(root: Path, mode: str, wavelength: str) -> Path | None:
    events = [p for p in root.iterdir() if p.is_dir()]
    if not events:
        return None
    event = random.choice(events)
    wave_dirs = [p for p in event.iterdir() if p.is_dir()]
    if wavelength:
        wave_dirs = [p for p in wave_dirs if p.name == str(wavelength)]
    if not wave_dirs:
        return None
    wave_dir = random.choice(wave_dirs)
    files = sorted(wave_dir.glob("*.npy"))
    if not files:
        return None
    return files[-1] if mode == "last-in-event" else random.choice(files)


def load_amp(path: Path, log_scale: bool) -> np.ndarray:
    vis = np.load(path)
    # Accept complex arrays or real/imag stacked in last dim
    if np.iscomplexobj(vis):
        vis = np.abs(vis)
    elif vis.ndim == 3 and vis.shape[-1] == 2:
        vis = np.sqrt(vis[..., 0] ** 2 + vis[..., 1] ** 2)
    if log_scale:
        vis = np.log1p(vis)
    return vis


def main() -> int:
    args = parse_args()

    if len(args.paths) == 0:
        root = Path(args.root)
        p1 = pick_file(root, args.pick, args.wavelength)
        if p1 is None:
            print(f"No visibility maps found under {root}")
            return 1
        paths = [p1]
    else:
        paths = [Path(p) for p in args.paths]

    if len(paths) > 1:
        print(f"Using first file only: {paths[0]}")
        paths = [paths[0]]
    print(f"Plotting: {paths[0]}")

    amps = [load_amp(p, args.log_scale) for p in paths]

    uv = np.load(args.uv_grid)
    u_vals = uv["u_vals"]
    v_vals = uv["v_vals"]
    extent = [u_vals.min(), u_vals.max(), v_vals.min(), v_vals.max()]

    import matplotlib.pyplot as plt
    from matplotlib.colors import TwoSlopeNorm

    fig, ax = plt.subplots(figsize=(5, 5))
    ax.set_facecolor("black")

    from matplotlib.colors import Normalize

    data = amps[0]
    if args.floor > 0:
        data = np.ma.masked_less_equal(data, args.floor)
    vmax = args.vmax if args.vmax > 0 else float(np.max(data)) if data.size else 1.0
    norm = Normalize(vmin=args.vmin, vmax=vmax)
    im = ax.imshow(
        data,
        origin="lower",
        cmap=args.cmap,
        norm=norm,
        aspect="equal",
        extent=extent,
    )
    event_name = paths[0].parent.parent.name if paths[0].parent.parent.exists() else paths[0].name
    goes_level = event_name.split("_", 1)[0] if "_" in event_name else event_name
    ax.set_title(goes_level)
    ax.set_xlabel("u (arcsec$^{-1}$)")
    ax.set_ylabel("v (arcsec$^{-1}$)")
    plt.tight_layout()
    plt.show()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
