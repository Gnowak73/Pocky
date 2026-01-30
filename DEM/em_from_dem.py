#!/usr/bin/env python3
"""Compute EM maps from DEM maps using a flare-focused temperature bin."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable, Tuple

import numpy as np
from astropy.io import fits


LOGT_MIN = 6.6
LOGT_MAX = 7.2
DELTA_LOGT = 0.1
T_REP_K = 1.0e7
DELTA_T = np.log(10.0) * T_REP_K * DELTA_LOGT
ARCSEC_TO_RAD = np.deg2rad(1.0 / 3600.0)
AU_CM = 1.495978707e13


def parse_args() -> argparse.Namespace:
    base = Path(__file__).resolve().parent.parent
    p = argparse.ArgumentParser(
        description="Compute EM maps from DEM maps using a flare-focused bin.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--input",
        default=str(base / "dem_maps_512x512"),
        help="Root DEM map directory.",
    )
    p.add_argument(
        "--output",
        default=str(base / "em_maps_512x512"),
        help="Output directory for EM maps.",
    )
    p.add_argument(
        "--format", choices=["fits", "npy"], default="fits", help="Output format."
    )
    p.add_argument(
        "--volume",
        action="store_true",
        help="Output volume EM per pixel (cm^-3) instead of column EM (cm^-5).",
    )
    p.add_argument(
        "--pixel-arcsec",
        type=float,
        default=0.6,
        help="Pixel scale in arcsec/pixel when header scale is unavailable.",
    )
    p.add_argument(
        "--use-header-scale",
        action="store_true",
        help="Use CDELT1/CDELT2 from FITS header for pixel scale if available.",
    )
    return p.parse_args()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def iter_events(root: Path) -> Iterable[Path]:
    return sorted(p for p in root.iterdir() if p.is_dir())


def read_dem(path: Path) -> Tuple[np.ndarray, fits.Header | None]:
    if path.suffix.lower() == ".npy":
        data = np.load(path)
        return np.asarray(data, dtype=float), None
    data, header = fits.getdata(path, header=True)
    return np.asarray(data, dtype=float), header


def write_em(path: Path, data: np.ndarray, header, fmt: str) -> None:
    if fmt == "npy":
        np.save(path.with_suffix(".npy"), data)
        return
    if header is not None and "BLANK" in header:
        del header["BLANK"]
    hdu = fits.PrimaryHDU(data, header=header)
    hdu.header["HISTORY"] = "EM = DEM * DeltaT (flare bin approximation)"
    hdu.header["HISTORY"] = f"logT range {LOGT_MIN}-{LOGT_MAX}, dlogT={DELTA_LOGT}"
    hdu.header["HISTORY"] = f"Trep={T_REP_K:.2e}K, DeltaT={DELTA_T:.3e}K"
    hdu.header["HISTORY"] = "Units recorded in EM_UNITS"
    hdu.writeto(path.with_suffix(".fits"), overwrite=True)


def main() -> None:
    args = parse_args()
    in_root = Path(args.input)
    out_root = Path(args.output)
    ensure_dir(out_root)

    for event_dir in iter_events(in_root):
        out_event = out_root / event_dir.name
        ensure_dir(out_event)
        for p in sorted(event_dir.iterdir()):
            if (
                not p.is_file()
                or p.suffix.lower() not in (".fits", ".npy")
                or not p.name.startswith("dem_")
            ):
                continue
            dem, header = read_dem(p)
            em_col = dem * DELTA_T
            em_units = "cm^-5"
            if args.volume:
                pixel_area = None
                if args.use_header_scale and header is not None:
                    cdelt1 = header.get("CDELT1")
                    cdelt2 = header.get("CDELT2")
                    if cdelt1 and cdelt2:
                        scale1 = float(cdelt1)
                        scale2 = float(cdelt2)
                        cunit1 = str(header.get("CUNIT1", "")).lower()
                        cunit2 = str(header.get("CUNIT2", "")).lower()
                        if "deg" in cunit1 or "deg" in cunit2:
                            scale1 *= 3600.0
                            scale2 *= 3600.0
                        elif abs(scale1) < 0.05 and abs(scale2) < 0.05:
                            scale1 *= 3600.0
                            scale2 *= 3600.0
                        pixel_area = abs(scale1 * scale2)
                if pixel_area is None:
                    pixel_area = args.pixel_arcsec * args.pixel_arcsec
                pixel_area_cm2 = (ARCSEC_TO_RAD * AU_CM) ** 2 * pixel_area
                em_col = em_col * pixel_area_cm2
                em_units = "cm^-3 pixel^-1"
            if header is not None:
                header["EM_UNITS"] = em_units
                if args.volume:
                    header["HISTORY"] = "Converted to volume EM using pixel area"
            write_em(out_event / p.stem, em_col, header, args.format)


if __name__ == "__main__":
    main()
