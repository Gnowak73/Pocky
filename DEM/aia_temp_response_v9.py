#!/usr/bin/env python3
"""Compute AIA temperature response from precomputed emissivity tables."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np


def parse_list(value: str) -> List[int]:
    return [int(v.strip()) for v in value.split(",") if v.strip()]


def parse_args() -> argparse.Namespace:
    base = Path(__file__).resolve().parent
    p = argparse.ArgumentParser(
        description="Compute AIA temperature response using precomputed emissivity tables.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--emissivity",
        default=str(base / "response_data" / "aia_V9_fullemiss.genx"),
        help="Path to emissivity table (.nc or .genx).",
    )
    p.add_argument(
        "--channels",
        default="94,131,171,193,211",
        help="Comma-separated AIA channels in angstroms.",
    )
    p.add_argument(
        "--obstime",
        default=None,
        help="Observation time (ISO-8601) for response degradation correction.",
    )
    p.add_argument(
        "--save-response",
        default=None,
        help="Optional path to save response data as a .npz file.",
    )
    p.add_argument(
        "--plot",
        action="store_true",
        help="Show the response plot.",
    )
    return p.parse_args()


def ensure_env_dir(var_name: str, fallback: Path) -> None:
    if os.environ.get(var_name):
        return
    fallback.mkdir(parents=True, exist_ok=True)
    os.environ[var_name] = str(fallback)


def load_emissivity(path: Path) -> Tuple[np.ndarray, np.ndarray, np.ndarray, str]:
    if path.suffix.lower() == ".nc":
        import xarray as xr

        ds = xr.load_dataset(path)
        if "total" not in ds:
            raise ValueError("Expected 'total' variable in emissivity dataset.")
        logte = np.asarray(ds["logte"].data, dtype=float)
        wave = np.asarray(ds["wave"].data, dtype=float)
        total = np.asarray(ds["total"].data, dtype=float)
        unit = str(ds["total"].attrs.get("units", ""))
        return logte, wave, total, unit

    from sunpy.io.special import read_genx

    data = read_genx(str(path))
    if "TOTAL" in data and isinstance(data["TOTAL"], dict | object):
        total_block = data["TOTAL"]
        if all(k in total_block for k in ("WAVE", "LOGTE", "EMISSIVITY")):
            logte = np.asarray(total_block["LOGTE"], dtype=float)
            wave = np.asarray(total_block["WAVE"], dtype=float)
            total = np.asarray(total_block["EMISSIVITY"], dtype=float)
            unit = str(total_block.get("UNITS", ""))
            return logte, wave, total, unit

    keys = {k.lower(): k for k in data.keys()}
    for k in ("logte", "logt", "logte_k"):
        if k in keys:
            logte = np.asarray(data[keys[k]], dtype=float)
            break
    else:
        raise ValueError("Could not locate logTe array in .genx emissivity table.")
    for k in ("wave", "wavelength"):
        if k in keys:
            wave = np.asarray(data[keys[k]], dtype=float)
            break
    else:
        raise ValueError("Could not locate wavelength array in .genx emissivity table.")
    for k in ("total", "emiss", "emissivity"):
        if k in keys:
            total = np.asarray(data[keys[k]], dtype=float)
            break
    else:
        raise ValueError(
            "Could not locate emissivity matrix in .genx emissivity table."
        )
    return logte, wave, total, ""


def interp_matrix(
    wave: np.ndarray, emiss: np.ndarray, new_wave: np.ndarray
) -> np.ndarray:
    out = np.empty((emiss.shape[0], new_wave.size), dtype=float)
    for i in range(emiss.shape[0]):
        out[i, :] = np.interp(new_wave, wave, emiss[i, :], left=0.0, right=0.0)
    return out


def main() -> int:
    args = parse_args()
    base_dir = Path(__file__).resolve().parent
    ensure_env_dir("SUNPY_CONFIGDIR", base_dir / ".sunpy")
    ensure_env_dir("MPLCONFIGDIR", base_dir / ".mplconfig")

    emiss_path = Path(args.emissivity).expanduser().resolve()
    if not emiss_path.exists():
        print(f"Emissivity table not found: {emiss_path}")
        return 1

    logte, wave, total, total_unit = load_emissivity(emiss_path)
    channels = parse_list(args.channels)

    import astropy.units as u
    from aiapy.response import Channel

    tresp = []
    for ch in channels:
        channel = Channel(ch * u.angstrom)
        emiss_matrix = interp_matrix(
            wave, total, channel.wavelength.to_value(u.angstrom)
        )
        dlambda = float(np.mean(np.diff(channel.wavelength.to_value(u.angstrom))))
        wr = channel.wavelength_response(obstime=args.obstime)
        resp_vals = wr.to_value(wr.unit)
        pixel_solid_angle = channel.plate_scale.to_value(u.steradian / u.pixel)
        tresp.append(emiss_matrix @ resp_vals * dlambda * pixel_solid_angle)
    tresp = np.stack(tresp).T

    if args.save_response:
        np.savez(
            args.save_response,
            logt=logte,
            temperature=10**logte,
            channels=np.array(channels, dtype=int),
            response=tresp,
        )
        print(f"Saved response to {args.save_response}")

    if args.plot:
        import matplotlib

        matplotlib.use("TkAgg")
        import matplotlib.pyplot as plt

        labels = [r"{0:d} $\AA$".format(ch) for ch in channels]
        plt.figure(figsize=(10, 6))
        plt.plot(logte, tresp, linewidth=2, label=labels)
        plt.title("AIA Temperature Response Functions", fontsize=20)
        plt.xticks(fontsize=20)
        plt.yticks(fontsize=20)
        plt.yscale("log")
        plt.ylim(1e-28, 1e-23)
        plt.xlim(5.0, 7.8)
        plt.xlabel("log10(T / K)", fontsize=20)
        ylabel = "Response"
        if total_unit:
            ylabel = total_unit
        plt.ylabel(ylabel, fontsize=20)
        plt.legend(fontsize=20)
        plt.show(block=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
