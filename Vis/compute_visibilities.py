#!/usr/bin/env python3
"""Compute sparse visibilities on the paper's (u,v) grid (DFT, not FFT-sampled)."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Compute sparse visibility magnitudes on a paper-style (u,v) grid.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "input",
        nargs="?",
        default="/Users/gabe/Github/Pocky/data_aia_lvl1_binned",
        help="Path to input .npy/.fits image or a folder.",
    )
    p.add_argument("--uv-grid", default="uv_grid.npz", help="Path to uv_grid.npz from gen_uv_grid.py.")
    p.add_argument("--pixel-arcsec", type=float, default=0.6, help="Pixel size in arcsec.")
    p.add_argument("--log-scale", action="store_true", help="Apply log1p to visibility magnitudes.")
    p.add_argument("--x0", type=float, default=0.0, help="Phase center x0 in arcsec.")
    p.add_argument("--y0", type=float, default=0.0, help="Phase center y0 in arcsec.")
    p.add_argument("--remove-dc", action="store_true", help="Zero out V(0,0) in output.")
    p.add_argument(
        "--normalize",
        action="store_true",
        help="Normalize image by total intensity before computing visibilities.",
    )
    p.add_argument(
        "--complex",
        action="store_true",
        help="Save complex visibilities instead of magnitudes.",
    )
    p.add_argument(
        "--output",
        default="/Users/gabe/Github/Pocky/vis_maps",
        help="Output .npy path (file mode) or output folder (dir mode).",
    )
    p.add_argument(
        "--exts",
        default=".npy,.fits",
        help="Comma list of file extensions to process when input is a folder.",
    )
    p.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip files whose output already exists (dir mode only).",
    )
    return p.parse_args()


def load_image(path: Path) -> np.ndarray:
    if path.suffix.lower() == ".npy":
        return np.load(path)
    from astropy.io import fits

    return fits.getdata(path)


def sample_visibilities(
    img: np.ndarray,
    u_vals: np.ndarray,
    v_vals: np.ndarray,
    pixel_arcsec: float,
    x0: float,
    y0: float,
    log_scale: bool,
    complex_mode: bool,
    normalize: bool,
    remove_dc: bool,
) -> np.ndarray:
    img = np.asarray(img, dtype=float)
    img = np.squeeze(img)
    if img.ndim != 2:
        raise ValueError(f"Expected 2D image, got shape {img.shape}")
    img = np.nan_to_num(img, nan=0.0, posinf=0.0, neginf=0.0)
    ny, nx = img.shape
    if ny == 0 or nx == 0:
        raise ValueError(f"Invalid image shape {img.shape}")
    if normalize:
        total = float(img.sum())
        if total != 0.0:
            img = img / total
    x = (np.arange(nx) - (nx - 1) / 2.0) * pixel_arcsec
    y = (np.arange(ny) - (ny - 1) / 2.0) * pixel_arcsec
    ex = np.exp(2j * np.pi * (u_vals[:, None] * (x[None, :] - x0)))
    ey = np.exp(2j * np.pi * (v_vals[:, None] * (y[None, :] - y0)))
    # V(u,v) = sum_y sum_x I(y,x) * exp(2pi i (u(x-x0)+v(y-y0))) * dx*dy
    vuv = (ex @ img.T @ ey.T).T * (pixel_arcsec * pixel_arcsec)  # (Nv, Nu)
    vuv = vuv.T  # (Nu, Nv)
    if remove_dc:
        iu0 = int(np.argmin(np.abs(u_vals)))
        iv0 = int(np.argmin(np.abs(v_vals)))
        vuv[iu0, iv0] = 0.0 + 0.0j
    if complex_mode:
        return vuv
    mag = np.abs(vuv)
    if log_scale:
        mag = np.log1p(mag)
    return mag


def main() -> int:
    args = parse_args()
    if args.complex and args.log_scale:
        raise SystemExit("log-scale is not compatible with --complex (magnitudes only).")
    uv = np.load(args.uv_grid)
    u_vals = uv["u_vals"]
    v_vals = uv["v_vals"]

    in_path = Path(args.input)
    exts = [e.strip().lower() for e in args.exts.split(",") if e.strip()]
    if in_path.is_dir():
        out_dir = Path(args.output)
        out_dir.mkdir(parents=True, exist_ok=True)
        files = [p for p in sorted(in_path.rglob("*")) if p.is_file() and p.suffix.lower() in exts]
        skipped = 0
        for p in files:
            rel = p.relative_to(in_path)
            out_path = out_dir / rel.parent
            out_file = out_path / f"{p.stem}_vis.npy"
            if args.skip_existing and out_file.exists():
                skipped += 1
                continue
            try:
                img = load_image(p)
                vis = sample_visibilities(
                    img,
                    u_vals,
                    v_vals,
                    args.pixel_arcsec,
                    args.x0,
                    args.y0,
                    args.log_scale,
                    args.complex,
                    args.normalize,
                    args.remove_dc,
                )
            except Exception as exc:
                skipped += 1
                print(f"Skip {p}: {exc}")
                continue
            out_path.mkdir(parents=True, exist_ok=True)
            np.save(out_file, vis)
        print(f"Saved visibilities for {len(files) - skipped} files to {out_dir} (skipped {skipped})")
    else:
        img = load_image(in_path)
        vis = sample_visibilities(
            img,
            u_vals,
            v_vals,
            args.pixel_arcsec,
            args.x0,
            args.y0,
            args.log_scale,
            args.complex,
            args.normalize,
            args.remove_dc,
        )
        np.save(args.output, vis)
        print(f"Saved {args.output} shape={vis.shape}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
