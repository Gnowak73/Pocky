#!/usr/bin/env python3
"""Crop AIA FITS files around flare coordinates into fixed arcsec boxes."""

from __future__ import annotations

import argparse
import datetime as dt
import re
from pathlib import Path
from typing import Dict, Tuple

import numpy as np
from astropy.io import fits


EVENT_RE = re.compile(r"^([A-Z]\d+(?:\.\d+)?)_(\d{8})_(\d{6})$")


def parse_args() -> argparse.Namespace:
    base = Path("/Users/gabe/Github/Pocky")
    p = argparse.ArgumentParser(
        description="Crop all AIA FITS files to a fixed arcsec box around flare coordinates.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--input", default=str(base / "data_aia_lvl1"), help="Input AIA tree.")
    p.add_argument("--output", default=str(base / "data_aia_cropped"), help="Output cropped tree.")
    p.add_argument("--flare-cache", default=str(base / "flare_cache.tsv"), help="flare_cache.tsv path.")
    p.add_argument("--size-arcsec", type=float, default=400.0, help="Crop box size (arcsec).")
    p.add_argument(
        "--force-pixels",
        type=int,
        default=0,
        help="Force crop to N x N pixels (overrides size-arcsec when >0).",
    )
    p.add_argument("--tolerance-sec", type=float, default=120.0, help="Match tolerance to flare_cache start time.")
    p.add_argument("--ext", default=".fits", help="File extension to crop.")
    p.add_argument("--workers", type=int, default=0, help="Parallel workers (0 = serial).")
    p.add_argument("--chunk", type=int, default=10, help="Tasks per worker chunk.")
    p.add_argument("--dry-run", action="store_true", help="Only report matched coordinates; do not crop.")
    p.add_argument(
        "--preview",
        action="store_true",
        help="Show a preview plot for matched events and exit (no cropping).",
    )
    p.add_argument(
        "--interactive",
        action="store_true",
        help="For each event, click the flare center to override HEK coords (serial only).",
    )
    p.add_argument(
        "--interactive-wave",
        default="131",
        help="Wavelength folder to use for interactive preview (e.g., 131).",
    )
    p.add_argument(
        "--preview-limit",
        type=int,
        default=2,
        help="Max number of events to preview.",
    )
    default_picked = str(Path("/Users/gabe/Github/Pocky") / "flare_coords_picked.tsv")
    p.add_argument(
        "--picked-tsv",
        nargs="?",
        const=default_picked,
        default="",
        help="Save picked coords (optional path; default flare_coords_picked.tsv).",
    )
    p.add_argument(
        "--picked-tsv-in",
        default="",
        help="Use picked coords from TSV (event\\tcoord_x\\tcoord_y) instead of HEK.",
    )
    return p.parse_args()


def parse_event_meta(name: str) -> Tuple[str, dt.datetime] | None:
    m = EVENT_RE.match(name)
    if not m:
        return None
    cls, date_str, time_str = m.groups()
    try:
        t = dt.datetime.strptime(f"{date_str}_{time_str}", "%Y%m%d_%H%M%S")
    except ValueError:
        return None
    return cls, t


def load_flare_cache(path: Path) -> Dict[Tuple[str, dt.datetime], Tuple[float, float]]:
    rows: Dict[Tuple[str, dt.datetime], Tuple[float, float]] = {}
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("description"):
            continue
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        flare_class = parts[1].strip()
        try:
            start = dt.datetime.strptime(parts[2].strip(), "%Y-%m-%dT%H:%M:%S.%f")
        except ValueError:
            continue
        coord = parts[4].strip()
        try:
            x_str, y_str = coord.strip("()").split(",")
            x = float(x_str)
            y = float(y_str)
        except Exception:
            continue
        rows[(flare_class, start)] = (x, y)
    return rows


def load_picked_coords(path: Path) -> Dict[str, Tuple[float, float]]:
    if not path or not path.exists():
        return {}
    rows: Dict[str, Tuple[float, float]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("event"):
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        name = parts[0].strip()
        try:
            x = float(parts[1])
            y = float(parts[2])
        except ValueError:
            continue
        rows[name] = (x, y)
    return rows


def match_coords(
    cache: Dict[Tuple[str, dt.datetime], Tuple[float, float]],
    cls: str,
    t: dt.datetime,
    tol: float,
) -> Tuple[float, float] | None:
    best = None
    for (c, ts), xy in cache.items():
        if c != cls:
            continue
        dt_sec = abs((ts - t).total_seconds())
        if dt_sec <= tol and (best is None or dt_sec < best[0]):
            best = (dt_sec, xy)
    if best is None:
        return None
    return best[1]


def match_coords_with_offset(
    cache: Dict[Tuple[str, dt.datetime], Tuple[float, float]],
    cls: str,
    t: dt.datetime,
    tol: float,
) -> Tuple[float, float, float] | None:
    best = None
    best_dt = None
    for (c, ts), xy in cache.items():
        if c != cls:
            continue
        dt_sec = abs((ts - t).total_seconds())
        if dt_sec <= tol and (best is None or dt_sec < best_dt):
            best = xy
            best_dt = dt_sec
    if best is None:
        return None
    return best[0], best[1], float(best_dt)


def arcsec_to_pixel(header: fits.Header, x_arc: float, y_arc: float) -> Tuple[float, float]:
    # Use simple linear WCS: xpix = CRPIX + (x - CRVAL)/CDELT
    crpix1 = float(header.get("CRPIX1", 0.0))
    crpix2 = float(header.get("CRPIX2", 0.0))
    crval1 = float(header.get("CRVAL1", 0.0))
    crval2 = float(header.get("CRVAL2", 0.0))
    cdelt1 = float(header.get("CDELT1", 1.0))
    cdelt2 = float(header.get("CDELT2", 1.0))
    # If CUNIT is in degrees, convert to arcsec
    cunit1 = str(header.get("CUNIT1", "")).lower()
    cunit2 = str(header.get("CUNIT2", "")).lower()
    if "deg" in cunit1:
        crval1 *= 3600.0
        cdelt1 *= 3600.0
    if "deg" in cunit2:
        crval2 *= 3600.0
        cdelt2 *= 3600.0
    x_pix = crpix1 + (x_arc - crval1) / cdelt1
    y_pix = crpix2 + (y_arc - crval2) / cdelt2
    return x_pix, y_pix


def crop_image(
    data: np.ndarray,
    header: fits.Header,
    x_arc: float,
    y_arc: float,
    size_arc: float,
    force_pixels: int,
) -> np.ndarray:
    x_pix, y_pix = arcsec_to_pixel(header, x_arc, y_arc)
    cdelt1 = float(header.get("CDELT1", 1.0))
    cdelt2 = float(header.get("CDELT2", 1.0))
    cunit1 = str(header.get("CUNIT1", "")).lower()
    cunit2 = str(header.get("CUNIT2", "")).lower()
    if "deg" in cunit1:
        cdelt1 *= 3600.0
    if "deg" in cunit2:
        cdelt2 *= 3600.0
    if force_pixels and force_pixels > 0:
        half_x = force_pixels // 2
        half_y = force_pixels // 2
    else:
        half_x = int(round((size_arc / 2.0) / abs(cdelt1)))
        half_y = int(round((size_arc / 2.0) / abs(cdelt2)))
    cx = int(round(x_pix - 1))  # CRPIX is 1-based
    cy = int(round(y_pix - 1))
    x0 = max(cx - half_x, 0)
    x1 = min(cx + half_x, data.shape[1])
    y0 = max(cy - half_y, 0)
    y1 = min(cy + half_y, data.shape[0])
    return data[y0:y1, x0:x1]


def _crop_event(task: Tuple[Path, Tuple[float, float], float, int, str, Path]) -> str:
    event_dir, coords, size_arcsec, force_pixels, ext, out_root = task
    x_arc, y_arc = coords
    for wave_dir in sorted(p for p in event_dir.iterdir() if p.is_dir()):
        out_wave = out_root / event_dir.name / wave_dir.name
        out_wave.mkdir(parents=True, exist_ok=True)
        for f in sorted(wave_dir.glob(f"*{ext}")):
            data, header = fits.getdata(f, header=True)
            cropped = crop_image(
                np.asarray(data), header, x_arc, y_arc, size_arcsec, force_pixels
            )
            fits.writeto(out_wave / f.name, cropped, header, overwrite=True)
    return f"Cropped {event_dir.name}"


def _preview_event(
    event_dir: Path,
    coords: Tuple[float, float],
    size_arcsec: float,
    ext: str,
    wave_hint: str | None = None,
) -> None:
    try:
        import matplotlib.pyplot as plt
    except Exception as exc:  # pragma: no cover - optional dependency
        print(f"Matplotlib not available for preview: {exc}")
        return

    x_arc, y_arc = coords
    wave_dirs = [p for p in event_dir.iterdir() if p.is_dir()]
    if not wave_dirs:
        print(f"Preview skip {event_dir.name}: no wavelength folders.")
        return
    wave_dir = None
    if wave_hint:
        for w in wave_dirs:
            if w.name == wave_hint:
                wave_dir = w
                break
    if wave_dir is None:
        wave_dir = sorted(wave_dirs)[0]
    files = sorted(wave_dir.glob(f"*{ext}"))
    if not files:
        print(f"Preview skip {event_dir.name}: no files under {wave_dir.name}.")
        return
    f = files[0]
    data, header = fits.getdata(f, header=True)
    x_pix, y_pix = arcsec_to_pixel(header, x_arc, y_arc)
    size_arc = size_arcsec
    cdelt1 = float(header.get("CDELT1", 1.0))
    cdelt2 = float(header.get("CDELT2", 1.0))
    if "deg" in str(header.get("CUNIT1", "")).lower():
        cdelt1 *= 3600.0
    if "deg" in str(header.get("CUNIT2", "")).lower():
        cdelt2 *= 3600.0
    if args.force_pixels and args.force_pixels > 0:
        half_x = args.force_pixels / 2.0
        half_y = args.force_pixels / 2.0
    else:
        half_x = (size_arc / 2.0) / abs(cdelt1)
        half_y = (size_arc / 2.0) / abs(cdelt2)
    cx = x_pix - 1
    cy = y_pix - 1

    fig, ax = plt.subplots(figsize=(6, 6))
    ax.imshow(data, origin="lower", cmap="gray")
    ax.scatter([cx], [cy], s=40, c="red", marker="+")
    rect = plt.Rectangle(
        (cx - half_x, cy - half_y),
        2 * half_x,
        2 * half_y,
        edgecolor="yellow",
        facecolor="none",
        linewidth=1.5,
    )
    ax.add_patch(rect)
    ax.set_title(f"{event_dir.name} | {wave_dir.name} | {f.name}")
    ax.set_xlabel("X [pix]")
    ax.set_ylabel("Y [pix]")
    print(
        f"Preview {event_dir.name}: coord=({x_arc:.3f},{y_arc:.3f}) "
        f"pix=({cx:.1f},{cy:.1f}) file={f.name}"
    )
    plt.show()


def _interactive_pick(
    event_dir: Path,
    coords: Tuple[float, float],
    size_arcsec: float,
    ext: str,
    wave_hint: str,
) -> Tuple[float, float] | None:
    try:
        import matplotlib.pyplot as plt
    except Exception as exc:  # pragma: no cover - optional dependency
        print(f"Matplotlib not available for interactive mode: {exc}")
        return None

    wave_dirs = [p for p in event_dir.iterdir() if p.is_dir()]
    if not wave_dirs:
        print(f"Interactive skip {event_dir.name}: no wavelength folders.")
        return None
    wave_dir = None
    for w in wave_dirs:
        if w.name == wave_hint:
            wave_dir = w
            break
    if wave_dir is None:
        wave_dir = sorted(wave_dirs)[0]
    files = sorted(wave_dir.glob(f"*{ext}"))
    if not files:
        print(f"Interactive skip {event_dir.name}: no files under {wave_dir.name}.")
        return None
    f = files[0]
    data, header = fits.getdata(f, header=True)
    x_arc, y_arc = coords
    x_pix, y_pix = arcsec_to_pixel(header, x_arc, y_arc)
    cdelt1 = float(header.get("CDELT1", 1.0))
    cdelt2 = float(header.get("CDELT2", 1.0))
    if "deg" in str(header.get("CUNIT1", "")).lower():
        cdelt1 *= 3600.0
    if "deg" in str(header.get("CUNIT2", "")).lower():
        cdelt2 *= 3600.0
    if args.force_pixels and args.force_pixels > 0:
        half_x = args.force_pixels / 2.0
        half_y = args.force_pixels / 2.0
    else:
        half_x = (size_arcsec / 2.0) / abs(cdelt1)
        half_y = (size_arcsec / 2.0) / abs(cdelt2)
    cx = x_pix - 1
    cy = y_pix - 1

    fig, ax = plt.subplots(figsize=(6, 6))
    ax.imshow(data, origin="lower", cmap="gray")
    ax.scatter([cx], [cy], s=40, c="red", marker="+")
    rect = plt.Rectangle(
        (cx - half_x, cy - half_y),
        2 * half_x,
        2 * half_y,
        edgecolor="yellow",
        facecolor="none",
        linewidth=1.5,
    )
    ax.add_patch(rect)
    ax.set_title(f"Click flare center: {event_dir.name} | {wave_dir.name}")
    ax.set_xlabel("X [pix]")
    ax.set_ylabel("Y [pix]")
    pts = plt.ginput(1, timeout=0)
    plt.close(fig)
    if not pts:
        print(f"Interactive skip {event_dir.name}: no click.")
        return None
    px, py = pts[0]
    # Convert pixel back to arcsec using header WCS
    crpix1 = float(header.get("CRPIX1", 0.0))
    crpix2 = float(header.get("CRPIX2", 0.0))
    crval1 = float(header.get("CRVAL1", 0.0))
    crval2 = float(header.get("CRVAL2", 0.0))
    if "deg" in str(header.get("CUNIT1", "")).lower():
        crval1 *= 3600.0
    if "deg" in str(header.get("CUNIT2", "")).lower():
        crval2 *= 3600.0
    x_arc_new = (px + 1 - crpix1) * cdelt1 + crval1
    y_arc_new = (py + 1 - crpix2) * cdelt2 + crval2
    print(
        f"Picked {event_dir.name}: pix=({px:.1f},{py:.1f}) arcsec=({x_arc_new:.2f},{y_arc_new:.2f})"
    )
    return x_arc_new, y_arc_new


def main() -> int:
    args = parse_args()
    in_root = Path(args.input)
    out_root = Path(args.output)
    if not in_root.exists():
        print(f"Input not found: {in_root}")
        return 1

    cache = load_flare_cache(Path(args.flare_cache))
    if not cache:
        print("flare_cache.tsv not found or empty.")
        return 1
    picked = load_picked_coords(Path(args.picked_tsv_in)) if args.picked_tsv_in else {}

    tasks = []
    previews = 0
    picked_rows = []
    for event_dir in sorted(p for p in in_root.iterdir() if p.is_dir()):
        meta = parse_event_meta(event_dir.name)
        if meta is None:
            continue
        cls, t = meta
        if picked and event_dir.name in picked:
            x_arc, y_arc = picked[event_dir.name]
            dt_sec = 0.0
            print(f"Match {event_dir.name}: picked coord=({x_arc:.3f},{y_arc:.3f})")
        else:
            match = match_coords_with_offset(cache, cls, t, args.tolerance_sec)
            if match is None:
                print(f"Skip {event_dir.name}: no coords match in cache.")
                continue
            x_arc, y_arc, dt_sec = match
            print(f"Match {event_dir.name}: coord=({x_arc:.3f},{y_arc:.3f}) dt={dt_sec:.1f}s")
        if args.preview:
            _preview_event(
                event_dir,
                (x_arc, y_arc),
                args.size_arcsec,
                args.ext,
                args.interactive_wave,
            )
            previews += 1
            if previews >= args.preview_limit:
                return 0
        if args.interactive:
            picked = _interactive_pick(
                event_dir,
                (x_arc, y_arc),
                args.size_arcsec,
                args.ext,
                args.interactive_wave,
            )
            if picked is None:
                continue
            x_arc, y_arc = picked
            if args.picked_tsv:
                picked_rows.append(f"{event_dir.name}\t{x_arc:.6f}\t{y_arc:.6f}")
        if args.dry_run:
            continue
        tasks.append(
            (event_dir, (x_arc, y_arc), args.size_arcsec, args.force_pixels, args.ext, out_root)
        )

    if args.picked_tsv and picked_rows:
        out = Path(args.picked_tsv)
        header = "event\tcoord_x\tcoord_y"
        out.write_text(header + "\n" + "\n".join(picked_rows) + "\n", encoding="utf-8")
        print(f"Saved picked coords to {out}")

    if args.dry_run or args.preview:
        return 0

    if args.workers and args.workers > 1:
        if args.interactive:
            print("Interactive mode forces serial processing.")
            return 1
        from concurrent.futures import ProcessPoolExecutor

        chunk = max(1, args.chunk)
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            for i in range(0, len(tasks), chunk):
                list(ex.map(_crop_event, tasks[i : i + chunk]))
    else:
        for task in tasks:
            _crop_event(task)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
