#!/usr/bin/env python3
"""Plot an EM map with fixed log colorbar like the reference."""

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
        help="Path to EM map (.npy/.fits) or a folder to pick from.",
    )
    p.add_argument(
        "--pick",
        choices=["random", "last-in-event"],
        default="last-in-event",
        help="How to choose a file when no path is given.",
    )
    p.add_argument(
        "--column",
        action="store_true",
        help="Use column-EM scaling (cm^-5) instead of volume EM.",
    )
    return p.parse_args()


def load_data(path: Path) -> tuple[np.ndarray, str, fits.Header | None]:
    if path.suffix.lower() == ".npy":
        return np.load(path), "", None
    from astropy.io import fits

    data, header = fits.getdata(path, header=True)
    unit = ""
    if header is not None:
        unit = str(header.get("EM_UNITS", "")).strip()
    return data, unit, header


def pick_random_em(root: Path) -> Path | None:
    candidates = sorted(root.rglob("em_*.npy")) + sorted(root.rglob("em_*.fits"))
    if not candidates:
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
            print(f"Path not found: {path}")
            return 1
        if path.is_dir():
            root = path
            if args.pick == "last-in-event":
                event_dirs = [p for p in root.iterdir() if p.is_dir()]
                event_dirs = [
                    p
                    for p in event_dirs
                    if list(p.glob("em_*.npy"))
                    or list(p.glob("em_*.fits"))
                    or list(p.glob("dem_*.npy"))
                    or list(p.glob("dem_*.fits"))
                ]
                if not event_dirs:
                    # fall back to any files under root
                    path = pick_random_em(root)
                    if path is None:
                        print(f"No EM maps found under {root}")
                        return 1
                else:
                    event_dir = Path(np.random.default_rng().choice(event_dirs))
                    candidates = sorted(event_dir.glob("em_*.npy")) + sorted(
                        event_dir.glob("em_*.fits")
                    )
                    if not candidates:
                        candidates = sorted(event_dir.glob("dem_*.npy")) + sorted(
                            event_dir.glob("dem_*.fits")
                        )
                    if not candidates:
                        print(f"No EM maps found under {event_dir}")
                        return 1
                    path = candidates[-1]
            else:
                path = pick_random_em(root)
                if path is None:
                    print(f"No EM maps found under {root}")
                    return 1
            print(f"Selected {path}")
        else:
            # file path provided
            pass
    else:
        root = Path(__file__).resolve().parent.parent / "em_maps"
        if args.pick == "last-in-event":
            event_dirs = [p for p in root.iterdir() if p.is_dir()]
            event_dirs = [
                p
                for p in event_dirs
                if list(p.glob("em_*.npy"))
                or list(p.glob("em_*.fits"))
                or list(p.glob("dem_*.npy"))
                or list(p.glob("dem_*.fits"))
            ]
            if not event_dirs:
                print(f"No EM maps found under {root}")
                return 1
            event_dir = Path(np.random.default_rng().choice(event_dirs))
            candidates = sorted(event_dir.glob("em_*.npy")) + sorted(event_dir.glob("em_*.fits"))
            if not candidates:
                candidates = sorted(event_dir.glob("dem_*.npy")) + sorted(event_dir.glob("dem_*.fits"))
            if not candidates:
                print(f"No EM maps found under {event_dir}")
                return 1
            path = candidates[-1]
        else:
            path = pick_random_em(root)
            if path is None:
                print(f"No EM maps found under {root}")
                return 1
        print(f"Selected {path}")

    data, unit, header = load_data(path)
    data = np.asarray(data, dtype=float)
    data = np.where(np.isfinite(data), data, np.nan)

    import matplotlib

    matplotlib.use("TkAgg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LogNorm
    from matplotlib.ticker import LogFormatterMathtext, NullLocator

    fig, ax = plt.subplots(figsize=(6, 6))
    vmin, vmax = (1e22, 1e28) if args.column else (1e42, 1e46)
    im = ax.imshow(
        data,
        origin="lower",
        cmap="magma",
        norm=LogNorm(vmin=vmin, vmax=vmax, clip=True),
    )
    cbar = fig.colorbar(im, ax=ax, format=LogFormatterMathtext())
    cbar.set_ticks(
        [1e22, 1e24, 1e26, 1e28] if args.column else [1e42, 1e43, 1e44, 1e45, 1e46]
    )
    cbar.ax.yaxis.set_minor_locator(NullLocator())
    label = "EM"
    if unit:
        label = f"EM [{unit}]"
    elif args.column:
        label = "EM [cm$^{-5}$]"
    else:
        label = "EM [cm$^{-3}$ pixel$^{-1}$]"
    cbar.set_label(label)
    ax.set_title("AIA Emission Measure" + (" (column)" if args.column else " (volume)"))
    ax.set_xlabel("Solar X [arcsec]")
    ax.set_ylabel("Solar Y [arcsec]")

    # Fixed pixel scale for box size.
    pixel_scale_x = 0.6
    pixel_scale_y = 0.6

    # Interactive box selection.
    from matplotlib.widgets import RectangleSelector

    total_all = float(np.nansum(np.where(np.isfinite(data) & (data > 0), data, 0.0)))
    unit_label = unit or "EM"
    info = ax.text(
        0.5,
        1.12,
        f"Total={total_all:.3e} {unit_label} | Drag to select a box",
        transform=ax.transAxes,
        ha="center",
        va="bottom",
        fontsize=10,
    )

    def onselect(eclick, erelease) -> None:
        if eclick.xdata is None or erelease.xdata is None:
            return
        if eclick.ydata is None or erelease.ydata is None:
            return
        x1, x2 = sorted([eclick.xdata, erelease.xdata])
        y1, y2 = sorted([eclick.ydata, erelease.ydata])
        ny, nx = data.shape
        x1i = max(0, int(np.floor(x1)))
        x2i = min(nx, int(np.ceil(x2)))
        y1i = max(0, int(np.floor(y1)))
        y2i = min(ny, int(np.ceil(y2)))
        if x2i <= x1i or y2i <= y1i:
            return
        region = data[y1i:y2i, x1i:x2i]
        region = np.where(np.isfinite(region) & (region > 0), region, 0.0)
        total = float(np.nansum(region))
        width_arcsec = (x2i - x1i) * pixel_scale_x
        height_arcsec = (y2i - y1i) * pixel_scale_y
        info.set_text(
            f'Box {width_arcsec:.2f}" × {height_arcsec:.2f}" | '
            f"total={total:.3e} {unit_label}"
        )
        fig.canvas.draw_idle()

    selector = RectangleSelector(
        ax,
        onselect,
        useblit=False,
        button=[1],
        minspanx=5,
        minspany=5,
        spancoords="pixels",
        interactive=True,
    )
    # Keep a reference so it doesn't get garbage-collected.
    ax._rect_selector = selector

    plt.show(block=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
