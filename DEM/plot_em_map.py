#!/usr/bin/env python3
"""Quick-look plot for an EM map file (.npy or .fits)."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Plot an EM map from a .npy or .fits file.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Path to EM map (.npy or .fits). If omitted, pick a random map.",
    )
    p.add_argument(
        "--vmin",
        type=float,
        default=1e42,
        help="Lower bound for linear color scale.",
    )
    p.add_argument(
        "--vmax",
        type=float,
        default=5e46,
        help="Upper bound for linear color scale.",
    )
    return p.parse_args()


def load_data(path: Path) -> np.ndarray:
    if path.suffix.lower() == ".npy":
        return np.load(path)
    from astropy.io import fits

    return fits.getdata(path)


def main() -> int:
    args = parse_args()
    if args.path:
        path = Path(args.path)
        if not path.exists():
            print(f"File not found: {path}")
            return 1
    else:
        root = Path(__file__).resolve().parent.parent / "em_maps_512x512"
        candidates = sorted(root.rglob("em_*.npy")) + sorted(root.rglob("em_*.fits"))
        if not candidates:
            candidates = sorted(root.rglob("*.npy")) + sorted(root.rglob("*.fits"))
        if not candidates:
            print(f"No EM maps found under {root}")
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
    plt.colorbar(im, label="EM")
    plt.title(path.name)
    plt.tight_layout()
    plt.show(block=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
