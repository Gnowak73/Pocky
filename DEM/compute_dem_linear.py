#!/usr/bin/env python3
"""Compute DEM proxy maps using a fixed set of weights."""

from __future__ import annotations

import argparse
import datetime as dt
import re
from bisect import bisect_left
from pathlib import Path
from typing import List, Tuple

import numpy as np
from astropy.io import fits


TIME_RE = re.compile(r"\.(\d{4}-\d{2}-\d{2}T\d{6})Z\.")


def parse_args() -> argparse.Namespace:
    base = Path(__file__).resolve().parent.parent
    p = argparse.ArgumentParser(
        description="Compute DEM proxy maps using fixed weights.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--input", default=str(base / "data_aia_lvl1"), help="Input root.")
    p.add_argument("--output", default=str(base / "dem_maps"), help="Output root.")
    p.add_argument("--event", default="", help="Process a single event directory name.")
    p.add_argument("--index", type=int, default=-1, help="Process one reference index.")
    p.add_argument("--tolerance", type=float, default=12.0, help="Max time delta in seconds.")
    p.add_argument("--ref", type=int, default=94, help="Reference wavelength for timestamps.")
    p.add_argument(
        "--channels",
        default="94,131,171,193,211",
        help="Comma list of channels to use.",
    )
    p.add_argument(
        "--weights",
        default="",
        help="Comma list of weights matching channels.",
    )
    p.add_argument(
        "--weights-file",
        default=str(Path(__file__).resolve().parent / "dem_weights.txt"),
        help="Path to weights text file from compute_dem_weights.py.",
    )
    p.add_argument(
        "--fits-root",
        default=str(base / "data_aia_lvl1"),
        help="Root directory for original FITS headers (EXPTIME).",
    )
    p.add_argument(
        "--fits-fallback-root",
        default="",
        help="Optional fallback root for FITS headers.",
    )
    p.add_argument("--no-exptime", action="store_true", help="Skip EXPTIME normalization.")
    p.add_argument("--use-fits-input", action="store_true", help="Read pixels from FITS.")
    p.add_argument("--format", choices=["fits", "npy"], default="npy", help="Output format.")
    p.add_argument("--scale", type=float, default=1.0, help="Scale factor on DEM output.")
    p.add_argument(
        "--clip-input",
        action="store_true",
        help="Clip negative or non-finite input pixels to 0 before weighting.",
    )
    p.add_argument("--workers", type=int, default=0, help="Parallel workers (0 = serial).")
    p.add_argument("--chunk", type=int, default=10, help="Tasks per worker chunk.")
    return p.parse_args()


def parse_list(value: str, cast) -> List:
    return [cast(v.strip()) for v in value.split(",") if v.strip()]


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


def load_weights_file(path: Path) -> Tuple[List[int], List[float]]:
    channels = []
    weights = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or line.startswith("logt=") or line.startswith("delta_"):
            continue
        if line.startswith("dem_per_logt=") or line.startswith("ridge=") or line.startswith("scale="):
            continue
        if line.startswith("channels,weights"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 2:
            continue
        try:
            channels.append(int(parts[0]))
            weights.append(float(parts[1]))
        except ValueError:
            continue
    if not channels or not weights or len(channels) != len(weights):
        raise ValueError(f"No weights found in {path}")
    return channels, weights


def build_dem_for_event(
    event_dir: Path,
    out_dir: Path,
    channels: List[int],
    weights: List[float],
    ref_wave: int,
    tolerance: float,
    fmt: str,
    fits_root: Path,
    fits_fallback_root: Path | None,
    ref_index: int,
    use_fits_input: bool,
    use_exptime: bool,
    scale: float,
    workers: int,
    chunk: int,
) -> None:
    wave_files = {}
    exts = (".fits", ".npy")
    for w in channels:
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

    tasks = []
    for ref_time, _ in zip(ref_times, ref_paths):
        matched = {}
        for w in channels:
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

        stamp = ref_time.strftime("%Y-%m-%dT%H%M%S")
        paths = [matched[w] for w in channels]
        tasks.append(
            (
                event_dir,
                out_dir,
                channels,
                weights,
                paths,
                stamp,
                fits_root,
                fits_fallback_root,
                use_fits_input,
                use_exptime,
                fmt,
                scale,
                args.clip_input,
            )
        )

    if not tasks:
        return

    if workers and workers > 1:
        from concurrent.futures import ProcessPoolExecutor

        chunk = max(1, chunk)
        with ProcessPoolExecutor(max_workers=workers) as ex:
            for i in range(0, len(tasks), chunk):
                list(ex.map(process_frame, tasks[i : i + chunk]))
    else:
        for task in tasks:
            process_frame(task)


def process_frame(task: Tuple) -> None:
    (
        event_dir,
        out_dir,
        channels,
        weights,
        paths,
        stamp,
        fits_root,
        fits_fallback_root,
        use_fits_input,
        use_exptime,
        fmt,
        scale,
        clip_input,
    ) = task
    arrays = []
    header = None
    for w, data_path in zip(channels, paths):
        data, hdr = read_array(data_path)
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
            data = data / exptime
        if clip_input:
            data = np.where(np.isfinite(data) & (data > 0), data, 0.0)
        arrays.append(np.asarray(data, dtype=float))
        if header is None:
            header = hdr

    stack = np.stack(arrays, axis=0)
    dem = np.tensordot(weights, stack, axes=(0, 0))
    if scale != 1.0:
        dem = dem * scale
    out_name = f"dem_{stamp}"
    if fmt == "npy":
        np.save(out_dir / f"{out_name}.npy", dem)
    else:
        if header is not None and "BLANK" in header:
            del header["BLANK"]
        hdu = fits.PrimaryHDU(dem, header=header)
        hdu.header["HISTORY"] = "DEM proxy (fixed weights) from Pocky"
        hdu.header["HISTORY"] = f"WAVELENGTHS={','.join(str(w) for w in channels)}"
        hdu.header["HISTORY"] = f"WEIGHTS={','.join(f'{w:.8e}' for w in weights)}"
        hdu.writeto(out_dir / f"{out_name}.fits", overwrite=True)


def main() -> None:
    args = parse_args()
    in_root = Path(args.input)
    out_root = Path(args.output)
    fits_root = Path(args.fits_root)
    fits_fallback_root = Path(args.fits_fallback_root) if args.fits_fallback_root else None

    if args.weights_file:
        channels, weights = load_weights_file(Path(args.weights_file))
    else:
        if not args.weights:
            raise SystemExit("Provide --weights or --weights-file.")
        channels = parse_list(args.channels, int)
        weights = parse_list(args.weights, float)
        if len(channels) != len(weights):
            raise SystemExit("Channels and weights must have the same length.")

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
            channels,
            weights,
            args.ref,
            args.tolerance,
            args.format,
            fits_root,
            fits_fallback_root,
            args.index,
            args.use_fits_input,
            not args.no_exptime,
            args.scale,
            args.workers,
            args.chunk,
        )


if __name__ == "__main__":
    main()
