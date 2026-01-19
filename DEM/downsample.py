#!/usr/bin/env python3
"""Downsample AIA FITS stacks to 64x64, optionally via Fourier-domain crop."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable, Tuple

import numpy as np
from astropy.io import fits


def parse_args() -> argparse.Namespace:
    base = Path(__file__).resolve().parent.parent
    p = argparse.ArgumentParser(description="Downsample AIA FITS to 64x64.")
    p.add_argument(
        "--input",
        default=str(base / "data_aia_lvl1"),
        help="Root AIA download directory.",
    )
    p.add_argument(
        "--output",
        default="",
        help="Output root (default: <input>_64x64).",
    )
    p.add_argument("--size", type=int, default=64, help="Output grid size.")
    p.add_argument("--fft", action="store_true", help="Use Fourier-domain crop.")
    p.add_argument(
        "--fft-mode",
        choices=["ifft", "magnitude", "complex"],
        default="ifft",
        help="FFT output mode when --fft is set.",
    )
    p.add_argument(
        "--format",
        choices=["npy", "fits"],
        default="npy",
        help="Output file format.",
    )
    return p.parse_args()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def center_crop_or_pad(arr: np.ndarray, size: int) -> np.ndarray:
    h, w = arr.shape
    if h >= size and w >= size:
        y0 = (h - size) // 2
        x0 = (w - size) // 2
        return arr[y0 : y0 + size, x0 : x0 + size]
    out = np.zeros((size, size), dtype=arr.dtype)
    y0 = max((size - h) // 2, 0)
    x0 = max((size - w) // 2, 0)
    out[y0 : y0 + h, x0 : x0 + w] = arr
    return out


def downsample_mean(arr: np.ndarray, size: int) -> np.ndarray:
    h, w = arr.shape
    if h < size or w < size:
        return center_crop_or_pad(arr, size)
    factor_h = h // size
    factor_w = w // size
    if factor_h == 0 or factor_w == 0:
        return center_crop_or_pad(arr, size)
    new_h = size * factor_h
    new_w = size * factor_w
    y0 = (h - new_h) // 2
    x0 = (w - new_w) // 2
    cropped = arr[y0 : y0 + new_h, x0 : x0 + new_w]
    reshaped = cropped.reshape(size, factor_h, size, factor_w)
    return reshaped.mean(axis=(1, 3))


def fft_crop(arr: np.ndarray, size: int) -> np.ndarray:
    freq = np.fft.fftshift(np.fft.fft2(arr))
    cropped = center_crop_or_pad(freq, size)
    return cropped


def process_array(arr: np.ndarray, size: int, use_fft: bool, fft_mode: str) -> Tuple[np.ndarray, np.ndarray | None]:
    if not use_fft:
        return downsample_mean(arr, size), None
    cropped = fft_crop(arr, size)
    if fft_mode == "magnitude":
        return np.abs(cropped), None
    if fft_mode == "complex":
        return cropped.real, cropped.imag
    spatial = np.fft.ifft2(np.fft.ifftshift(cropped))
    return spatial.real, None


def write_output(path: Path, data: np.ndarray, header, fmt: str) -> None:
    if fmt == "npy":
        np.save(path.with_suffix(".npy"), data)
        return
    if header is not None and "BLANK" in header:
        del header["BLANK"]
    hdu = fits.PrimaryHDU(data, header=header)
    hdu.header["HISTORY"] = "Downsampled to 64x64 by Pocky"
    hdu.writeto(path.with_suffix(".fits"), overwrite=True)


def iter_events(root: Path) -> Iterable[Path]:
    return sorted(p for p in root.iterdir() if p.is_dir())


def main() -> None:
    args = parse_args()
    in_root = Path(args.input)
    out_root = Path(args.output) if args.output else in_root.parent / f"{in_root.name}_{size}x{size}"
    size = args.size

    for event_dir in iter_events(in_root):
        for wave_dir in sorted(p for p in event_dir.iterdir() if p.is_dir()):
            fits_files = sorted(p for p in wave_dir.iterdir() if p.is_file() and p.suffix.lower() == ".fits")
            if not fits_files:
                continue
            if args.fft and args.fft_mode == "complex":
                out_event_re = out_root / f"RE_{event_dir.name}" / wave_dir.name
                out_event_im = out_root / f"IM_{event_dir.name}" / wave_dir.name
                ensure_dir(out_event_re)
                ensure_dir(out_event_im)
            else:
                out_wave = out_root / event_dir.name / wave_dir.name
                ensure_dir(out_wave)

            for fpath in fits_files:
                data, header = fits.getdata(fpath, header=True)
                data = np.asarray(data, dtype=float)
                real_part, imag_part = process_array(
                    data, size, args.fft, args.fft_mode
                )
                stem = fpath.stem
                if args.fft and args.fft_mode == "complex":
                    write_output(out_event_re / stem, real_part, header, args.format)
                    write_output(out_event_im / stem, imag_part, header, args.format)
                else:
                    write_output(out_wave / stem, real_part, header, args.format)


if __name__ == "__main__":
    main()
