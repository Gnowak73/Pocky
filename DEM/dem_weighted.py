#!/usr/bin/env python3
"""Build DEM-weighted maps from AIA FITS folders.

Expects a directory layout like:
  data_aia_lvl1/<event_id>/<wavelength>/<fits files>
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
from bisect import bisect_left
from pathlib import Path
from typing import Iterable, List, Tuple

import numpy as np
from astropy.io import fits


TIME_RE = re.compile(r"\.(\d{4}-\d{2}-\d{2}T\d{6})Z\.")
DEFAULT_WEIGHTS = "1.20196640e-04,2.12817313e-05,-7.33613022e-07,1.83818002e-07,-1.90719161e-06"


def parse_args() -> argparse.Namespace:
    base = Path(__file__).resolve().parent.parent

    class _HelpFormatter(argparse.ArgumentDefaultsHelpFormatter):
        def _get_help_string(self, action):  # type: ignore[override]
            if action.dest == "weights":
                return f"{action.help} (default: Paolo's Weights)"
            return super()._get_help_string(action)

    p = argparse.ArgumentParser(
        description="Build DEM weighted maps from AIA FITS downloads.",
        formatter_class=_HelpFormatter,
    )
    p.add_argument(
        "--input",
        default=str(base / "data_aia_lvl1_512x512"),
        help="Root AIA download directory.",
    )
    p.add_argument(
        "--output",
        default=str(base / "dem_maps_512x512"),
        help="Output directory for DEM maps.",
    )
    p.add_argument("--event", default="", help="Process a single event directory name.")
    p.add_argument(
        "--index",
        type=int,
        default=-1,
        help="Process only one reference frame index (0-based).",
    )
    p.add_argument(
        "--tolerance", type=float, default=12.0, help="Max time delta in seconds."
    )
    p.add_argument(
        "--ref", type=int, default=171, help="Reference wavelength for timestamps."
    )
    p.add_argument(
        "--wavelengths",
        default="94,131,171,193,211",
        help="Comma list of wavelengths to use (order matches weights).",
    )
    p.add_argument(
        "--weights",
        default=DEFAULT_WEIGHTS,
        help="Paolo's Weights",
    )
    p.add_argument(
        "--format", choices=["fits", "npy"], default="npy", help="Output format."
    )
    return p.parse_args()


def parse_time_from_name(name: str) -> dt.datetime | None:
    m = TIME_RE.search(name)
    if not m:
        return None
    return dt.datetime.strptime(m.group(1), "%Y-%m-%dT%H%M%S")


def list_wave_files(path: Path, exts: Tuple[str, ...]) -> List[Tuple[dt.datetime, Path]]:
    items: List[Tuple[dt.datetime, Path]] = []
    for p in path.iterdir():
        if p.is_file() and p.suffix.lower() in exts:
            t = parse_time_from_name(p.name)
            if t is not None:
                items.append((t, p))
    items.sort(key=lambda x: x[0])
    return items


def split_times(
    items: List[Tuple[dt.datetime, Path]],
) -> Tuple[List[dt.datetime], List[Path]]:
    times = [t for t, _ in items]
    paths = [p for _, p in items]
    return times, paths


def nearest_file(
    target: dt.datetime, times: List[dt.datetime], paths: List[Path]
) -> Tuple[dt.datetime, Path] | None:
    if not times:
        return None
    idx = bisect_left(times, target)
    candidates: List[Tuple[dt.datetime, Path]] = []
    if idx < len(times):
        candidates.append((times[idx], paths[idx]))
    if idx > 0:
        candidates.append((times[idx - 1], paths[idx - 1]))
    return min(candidates, key=lambda x: abs((x[0] - target).total_seconds()))


def read_array(path: Path) -> Tuple[np.ndarray, fits.Header | None]:
    if path.suffix.lower() == ".npy":
        data = np.load(path)
        return np.asarray(data, dtype=float), None
    data, header = fits.getdata(path, header=True)
    return np.asarray(data, dtype=float), header


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def build_dem_for_event(
    event_dir: Path,
    out_dir: Path,
    wavelengths: List[int],
    weights: List[float],
    ref_wave: int,
    tolerance: float,
    fmt: str,
    ref_index: int,
) -> None:
    wave_files = {}
    exts = (".fits", ".npy")
    for w in wavelengths:
        wave_path = event_dir / str(w)
        if not wave_path.is_dir():
            continue
        items = list_wave_files(wave_path, exts)
        times, paths = split_times(items)
        wave_files[w] = (times, paths)

    if ref_wave not in wave_files:
        return

    ensure_dir(out_dir)
    ref_times, ref_paths = wave_files[ref_wave]
    if ref_index >= 0:
        if ref_index >= len(ref_times):
            return
        ref_times = [ref_times[ref_index]]
        ref_paths = [ref_paths[ref_index]]

    for ref_time, ref_path in zip(ref_times, ref_paths):
        matched = {}
        for w in wavelengths:
            pair = wave_files.get(w)
            if pair is None:
                matched = {}
                break
            times, paths = pair
            nearest = nearest_file(ref_time, times, paths)
            if nearest is None:
                matched = {}
                break
            t, p = nearest
            if abs((t - ref_time).total_seconds()) > tolerance:
                matched = {}
                break
            matched[w] = p
        if not matched:
            continue

        arrays = []
        header = None
        for w, weight in zip(wavelengths, weights):
            data, hdr = read_array(matched[w])
            arrays.append(weight * data)
            if header is None:
                header = hdr
        dem = np.sum(arrays, axis=0)
        stamp = ref_time.strftime("%Y-%m-%dT%H%M%S")
        out_name = f"dem_{stamp}"
        if fmt == "npy":
            np.save(out_dir / f"{out_name}.npy", dem)
        else:
            if header is not None and "BLANK" in header:
                del header["BLANK"]
            hdu = fits.PrimaryHDU(dem, header=header)
            hdu.header["HISTORY"] = "DEM weighted sum from Pocky"
            hdu.header["HISTORY"] = (
                f"WAVELENGTHS={','.join(str(w) for w in wavelengths)}"
            )
            hdu.header["HISTORY"] = f"WEIGHTS={','.join(f'{w:.8e}' for w in weights)}"
            hdu.writeto(out_dir / f"{out_name}.fits", overwrite=True)


def parse_list(value: str, cast) -> List:
    return [cast(v.strip()) for v in value.split(",") if v.strip()]


def main() -> None:
    args = parse_args()
    in_root = Path(args.input)
    out_root = Path(args.output)
    wavelengths = parse_list(args.wavelengths, int)
    weights = parse_list(args.weights, float)
    if len(wavelengths) != len(weights):
        raise SystemExit("Wavelengths and weights must have the same length.")

    for event_dir in sorted(p for p in in_root.iterdir() if p.is_dir()):
        if args.event and event_dir.name != args.event:
            continue
        out_dir = out_root / event_dir.name
        build_dem_for_event(
            event_dir,
            out_dir,
            wavelengths,
            weights,
            args.ref,
            args.tolerance,
            args.format,
            args.index,
        )


if __name__ == "__main__":
    main()
