#!/usr/bin/env python3
"""Rebin all AIA images in data_aia_lvl1 by block size."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np


def parse_args() -> argparse.Namespace:
    base = Path("/Users/gabe/Github/Pocky")
    p = argparse.ArgumentParser(
        description="Rebin all AIA images under data_aia_lvl1.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--input",
        default=str(base / "data_aia_lvl1"),
        help="Root folder with event/wavelength/*.fits.",
    )
    p.add_argument(
        "--output",
        default=str(base / "data_aia_lvl1_binned"),
        help="Output root for rebinned .npy files.",
    )
    p.add_argument("--block", type=int, default=10, help="Block size in pixels.")
    p.add_argument(
        "--crop-center",
        action="store_true",
        help="Center-crop to nearest size divisible by block.",
    )
    p.add_argument(
        "--exts",
        default=".fits,.npy",
        help="Comma list of file extensions to process.",
    )
    p.add_argument("--workers", type=int, default=0, help="Parallel workers (0 = serial).")
    p.add_argument("--chunk", type=int, default=20, help="Tasks per worker chunk.")
    p.add_argument("--progress", type=int, default=500, help="Print progress every N files (0 disables).")
    p.add_argument("--skip-existing", action="store_true", help="Skip if output file already exists.")
    return p.parse_args()


def crop_to_block(img: np.ndarray, block: int) -> np.ndarray:
    ny, nx = img.shape
    ny2 = (ny // block) * block
    nx2 = (nx // block) * block
    if ny2 == 0 or nx2 == 0:
        raise ValueError(f"Image shape {img.shape} too small for block {block}.")
    if ny2 == ny and nx2 == nx:
        return img
    y0 = (ny - ny2) // 2
    x0 = (nx - nx2) // 2
    return img[y0 : y0 + ny2, x0 : x0 + nx2]


def rebin_mean(img: np.ndarray, block: int, crop_center: bool) -> np.ndarray:
    if block <= 1:
        return img
    ny, nx = img.shape
    if ny % block != 0 or nx % block != 0:
        if crop_center:
            img = crop_to_block(img, block)
            ny, nx = img.shape
        else:
            raise ValueError(f"Image shape {img.shape} not divisible by block {block}.")
    by = ny // block
    bx = nx // block
    return img.reshape(by, block, bx, block).mean(axis=(1, 3))


def load_image(path: Path) -> np.ndarray:
    if path.suffix.lower() == ".npy":
        return np.load(path)
    from astropy.io import fits

    return fits.getdata(path)


def _worker(task: tuple[Path, Path, int, bool, bool]) -> None:
    p, out_dir, block, crop_center, skip_existing = task
    out_path = out_dir / f"{p.stem}_bin{block}.npy"
    if skip_existing and out_path.exists():
        return
    img = load_image(p)
    out = rebin_mean(np.asarray(img, dtype=float), block, crop_center)
    np.save(out_path, out)


def main() -> int:
    args = parse_args()
    in_root = Path(args.input)
    out_root = Path(args.output)
    exts = [e.strip().lower() for e in args.exts.split(",") if e.strip()]
    if not in_root.exists():
        print(f"Input not found: {in_root}")
        return 1

    def iter_tasks():
        for p in in_root.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in exts:
                continue
            rel = p.relative_to(in_root)
            out_dir = out_root / rel.parent
            out_dir.mkdir(parents=True, exist_ok=True)
            yield (p, out_dir, args.block, args.crop_center, args.skip_existing)

    if args.workers and args.workers > 1:
        from concurrent.futures import ProcessPoolExecutor

        chunk = max(1, args.chunk)
        done = 0
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            batch = []
            for task in iter_tasks():
                batch.append(task)
                if len(batch) >= chunk:
                    list(ex.map(_worker, batch))
                    done += len(batch)
                    batch.clear()
                    if args.progress and done % args.progress == 0:
                        print(f"Processed {done}")
            if batch:
                list(ex.map(_worker, batch))
                done += len(batch)
        if args.progress:
            print(f"Processed {done}")
    else:
        done = 0
        for task in iter_tasks():
            _worker(task)
            done += 1
            if args.progress and done % args.progress == 0:
                print(f"Processed {done}")
    print(f"Done. Rebinned files into {out_root}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
