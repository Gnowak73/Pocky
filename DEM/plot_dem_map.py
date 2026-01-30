#!/usr/bin/env python3
"""Quick-look plot for a DEM map file (.npy or .fits)."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Plot a DEM map from a .npy or .fits file.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Path to DEM map (.npy/.fits) or a folder to pick from.",
    )
    p.add_argument(
        "--vmin-percentile",
        type=float,
        default=1.0,
        help="Lower percentile for color scale.",
    )
    p.add_argument(
        "--vmax-percentile",
        type=float,
        default=99.0,
        help="Upper percentile for color scale.",
    )
    p.add_argument(
        "--vmin",
        type=float,
        default=1e22,
        help="Lower bound for linear color scale.",
    )
    p.add_argument(
        "--vmax",
        type=float,
        default=1e25,
        help="Upper bound for linear color scale.",
    )
    p.add_argument(
        "--pick",
        choices=["random", "last-in-event"],
        default="last-in-event",
        help="How to choose a file when no path is given.",
    )
    return p.parse_args()


def load_data(path: Path) -> np.ndarray:
    if path.suffix.lower() == ".npy":
        return np.load(path)
    from astropy.io import fits

    return fits.getdata(path)

def pick_random_dem(root: Path) -> Path | None:
    candidates = sorted(root.rglob("dem_*.npy")) + sorted(root.rglob("dem_*.fits"))
    if not candidates:
        candidates = sorted(root.rglob("*.npy")) + sorted(root.rglob("*.fits"))
    if not candidates:
        return None
    return Path(np.random.default_rng().choice(candidates))


def main() -> int:
    args = parse_args()
    if args.path:
        path = Path(args.path)
        if not path.exists():
            print(f"File not found: {path}")
            return 1
        if path.is_dir():
            root = path
            if args.pick == "last-in-event":
                event_dirs = [p for p in root.iterdir() if p.is_dir()]
                event_dirs = [
                    p
                    for p in event_dirs
                    if list(p.glob("dem_*.npy")) or list(p.glob("dem_*.fits"))
                ]
                if not event_dirs:
                    path = pick_random_dem(root)
                    if path is None:
                        print(f"No DEM maps found under {root}")
                        return 1
                else:
                    event_dir = Path(np.random.default_rng().choice(event_dirs))
                    candidates = sorted(event_dir.glob("dem_*.npy")) + sorted(
                        event_dir.glob("dem_*.fits")
                    )
                    if not candidates:
                        print(f"No DEM maps found under {event_dir}")
                        return 1
                    path = candidates[-1]
            else:
                path = pick_random_dem(root)
                if path is None:
                    print(f"No DEM maps found under {root}")
                    return 1
            print(f"Selected {path}")
    else:
        root = Path(__file__).resolve().parent.parent / "dem_maps"
        if args.pick == "last-in-event":
            event_dirs = [p for p in root.iterdir() if p.is_dir()]
            event_dirs = [
                p for p in event_dirs
                if list(p.glob("dem_*.npy")) or list(p.glob("dem_*.fits"))
            ]
            if not event_dirs:
                print(f"No DEM maps found under {root}")
                return 1
            event_dir = Path(np.random.default_rng().choice(event_dirs))
            candidates = sorted(event_dir.glob("dem_*.npy")) + sorted(event_dir.glob("dem_*.fits"))
            if not candidates:
                print(f"No DEM maps found under {event_dir}")
                return 1
            path = candidates[-1]
        else:
            candidates = sorted(root.rglob("dem_*.npy")) + sorted(root.rglob("dem_*.fits"))
            if not candidates:
                print(f"No DEM maps found under {root}")
                return 1
            path = np.random.default_rng().choice(candidates)
        print(f"Selected {path}")

    data = np.asarray(load_data(path), dtype=float)
    data = np.where(np.isfinite(data), data, np.nan)

    display = data
    vmin = args.vmin
    vmax = args.vmax

    import matplotlib

    matplotlib.use("TkAgg")
    import matplotlib.pyplot as plt

    plt.figure(figsize=(6, 6))
    im = plt.imshow(display, origin="lower", vmin=vmin, vmax=vmax, cmap="magma")
    plt.colorbar(im, label="DEM")
    plt.title(path.name)
    plt.tight_layout()
    plt.show(block=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
