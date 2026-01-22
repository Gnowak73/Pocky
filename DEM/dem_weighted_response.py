#!/usr/bin/env python3
"""Build DEM-weighted maps using fixed weights and a saved response table."""

from __future__ import annotations

import argparse
import datetime as dt
import re
from bisect import bisect_left
from pathlib import Path
from typing import Iterable, List, Tuple

import numpy as np
from astropy.io import fits


TIME_RE = re.compile(r"\.(\d{4}-\d{2}-\d{2}T\d{6})Z\.")
DEFAULT_WAVELENGTHS = "94,131,171,193,211"
DEFAULT_WEIGHTS = "1.20196640e-04,2.12817313e-05,-7.33613022e-07,1.83818002e-07,-1.90719161e-06"


def parse_args() -> argparse.Namespace:
    base = Path(__file__).resolve().parent.parent
    dem_dir = Path(__file__).resolve().parent
    p = argparse.ArgumentParser(
        description="Build DEM weighted maps using fixed weights and response normalization.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
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
        default=DEFAULT_WAVELENGTHS,
        help="Comma list of wavelengths to use (order matches weights).",
    )
    p.add_argument(
        "--weights",
        default=DEFAULT_WEIGHTS,
        help="Paolo's Weights",
    )
    p.add_argument(
        "--fits-root",
        default=str(base / "data_aia_lvl1"),
        help="Root directory for original FITS headers (EXPTIME).",
    )
    p.add_argument(
        "--fits-fallback-root",
        default="",
        help="Optional fallback root for FITS headers if not found under --fits-root.",
    )
    p.add_argument(
        "--logt",
        type=float,
        default=6.6,
        help="Representative log10(T/K) for response normalization.",
    )
    p.add_argument(
        "--response-npz",
        default=str(dem_dir / "aia_temp_response.npz"),
        help="Path to saved response .npz (logt, channels, response).",
    )
    p.add_argument(
        "--no-calibrate",
        action="store_true",
        help="Skip EXPTIME/response normalization.",
    )
    p.add_argument(
        "--no-exptime",
        action="store_true",
        help="Skip EXPTIME normalization only.",
    )
    p.add_argument(
        "--use-fits-input",
        action="store_true",
        help="Load pixel data from FITS headers instead of .npy files.",
    )
    p.add_argument(
        "--format", choices=["fits", "npy"], default="npy", help="Output format."
    )
    p.add_argument(
        "--show-exptime",
        action="store_true",
        help="Print EXPTIME values used for normalization.",
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


def read_header(path: Path) -> fits.Header | None:
    try:
        return fits.getheader(path)
    except Exception:
        return None


def find_header_path(
    data_path: Path,
    fits_root: Path,
    fallback_root: Path | None,
    event_dir: Path,
    wavelength: int,
) -> Path | None:
    if data_path.suffix.lower() == ".fits":
        return data_path
    stem = data_path.stem
    candidates = []
    primary = fits_root / event_dir.name / str(wavelength) / f"{stem}.fits"
    if primary.exists():
        return primary
    candidates.extend((fits_root / event_dir.name / str(wavelength)).glob(f"{stem}*.fits"))
    if fallback_root:
        fallback = fallback_root / event_dir.name / str(wavelength) / f"{stem}.fits"
        if fallback.exists():
            return fallback
        candidates.extend((fallback_root / event_dir.name / str(wavelength)).glob(f"{stem}*.fits"))
    if candidates:
        return sorted(candidates)[0]
    return None


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def load_response_table(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    data = np.load(path)
    logt = np.asarray(data["logt"], dtype=float)
    channels = np.asarray(data["channels"], dtype=int)
    response = np.asarray(data["response"], dtype=float)
    if response.ndim != 2 or response.shape[0] != logt.size:
        raise ValueError("Response table has unexpected shape.")
    return logt, channels, response


def response_at_logt(
    logt: float, channels: List[int], table: tuple[np.ndarray, np.ndarray, np.ndarray]
) -> dict[int, float]:
    logt_grid, channel_grid, response = table
    resp_map: dict[int, float] = {}
    for ch in channels:
        if ch not in channel_grid:
            raise ValueError(f"Channel {ch} not found in response table.")
        idx = int(np.where(channel_grid == ch)[0][0])
        resp_map[ch] = float(np.interp(logt, logt_grid, response[:, idx]))
    return resp_map


def build_dem_for_event(
    event_dir: Path,
    out_dir: Path,
    wavelengths: List[int],
    weights: List[float],
    ref_wave: int,
    tolerance: float,
    fmt: str,
    fits_root: Path,
    fits_fallback_root: Path | None,
    logt: float,
    calibrate: bool,
    ref_index: int,
    response_table: tuple[np.ndarray, np.ndarray, np.ndarray] | None,
    show_exptime: bool,
    use_fits_input: bool,
    use_exptime: bool,
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

    response_cache = None
    if calibrate and response_table is not None:
        response_cache = response_at_logt(logt, wavelengths, response_table)

    for ref_time, _ in zip(ref_times, ref_paths):
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
            data_path = matched[w]
            data, hdr = read_array(data_path)
            if calibrate:
                header_path = find_header_path(
                    data_path, fits_root, fits_fallback_root, event_dir, w
                )
                if header_path is not None:
                    if use_fits_input:
                        data, hdr = read_array(header_path)
                    else:
                        hdr = hdr or read_header(header_path)
                if use_exptime:
                    if hdr is None:
                        raise SystemExit(
                            f"Missing FITS header for EXPTIME: {event_dir.name} {w}"
                        )
                    if "EXPTIME" not in hdr:
                        raise SystemExit(
                            f"EXPTIME not found in FITS header: {event_dir.name} {w}"
                        )
                    exptime = float(hdr.get("EXPTIME") or 0.0)
                    if exptime <= 0:
                        raise SystemExit(
                            f"Invalid EXPTIME={exptime} for {event_dir.name} {w}"
                        )
                    if show_exptime:
                        print(f"{event_dir.name} {w} EXPTIME={exptime}")
                    data = data / exptime
                if response_cache is not None:
                    resp_val = response_cache.get(w, 0.0)
                    if resp_val > 0:
                        data = data / resp_val
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
            if calibrate:
                hdu.header["HISTORY"] = "Normalized by EXPTIME and AIA response"
                hdu.header["HISTORY"] = f"logT={logt}"
            hdu.writeto(out_dir / f"{out_name}.fits", overwrite=True)


def parse_list(value: str, cast) -> List:
    return [cast(v.strip()) for v in value.split(",") if v.strip()]


def main() -> None:
    args = parse_args()
    in_root = Path(args.input)
    out_root = Path(args.output)
    fits_root = Path(args.fits_root)
    fits_fallback_root = Path(args.fits_fallback_root) if args.fits_fallback_root else None
    wavelengths = parse_list(args.wavelengths, int)
    weights = parse_list(args.weights, float)
    if len(wavelengths) != len(weights):
        raise SystemExit("Wavelengths and weights must have the same length.")
    if args.weights == DEFAULT_WEIGHTS and args.wavelengths != DEFAULT_WAVELENGTHS:
        raise SystemExit("Default weights require wavelengths ordered as 94,131,171,193,211.")

    response_table = None
    if not args.no_calibrate:
        response_path = Path(args.response_npz)
        if response_path.exists():
            response_table = load_response_table(response_path)
        else:
            raise SystemExit(f"Response table not found: {response_path}")

    for event_dir in sorted(p for p in in_root.iterdir() if p.is_dir()):
        if event_dir.name.isdigit():
            continue
        if not any(child.is_dir() for child in event_dir.iterdir()):
            continue
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
            fits_root,
            fits_fallback_root,
            args.logt,
            not args.no_calibrate,
            args.index,
            response_table,
            args.show_exptime,
            args.use_fits_input,
            not args.no_exptime,
        )


if __name__ == "__main__":
    main()
