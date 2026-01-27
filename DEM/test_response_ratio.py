#!/usr/bin/env python3
"""Estimate proxy bias Kbar/K(T0) for a Gaussian DEM in logT."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List

import numpy as np


def parse_args() -> argparse.Namespace:
    dem_dir = Path(__file__).resolve().parent
    p = argparse.ArgumentParser(
        description="Estimate Kbar/K(T0) ratio for a Gaussian DEM in logT.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--response-npz",
        default=str(dem_dir / "aia_temp_response.npz"),
        help="Path to saved response .npz (logt, channels, response).",
    )
    p.add_argument(
        "--channels",
        default="94,131,171,193,211",
        help="Comma list of channels to use.",
    )
    p.add_argument(
        "--weights-file",
        default="",
        help="Optional weights file (single or multi) to compute proxy ratio.",
    )
    p.add_argument("--logt0", type=float, default=6.6, help="Proxy reference logT.")
    p.add_argument("--mu", type=float, default=6.3, help="Gaussian center in logT.")
    p.add_argument("--sigma", type=float, default=0.15, help="Gaussian sigma in logT.")
    p.add_argument(
        "--dem-per-t",
        action="store_true",
        help="Treat the Gaussian as DEM per dT (default is per dlogT).",
    )
    p.add_argument(
        "--save",
        nargs="?",
        const=str(dem_dir / "test_ratios.txt"),
        default="",
        help="Save per-channel ratios to a file (optional path).",
    )
    return p.parse_args()


def parse_list(value: str, cast) -> List:
    return [cast(v.strip()) for v in value.split(",") if v.strip()]


def load_response_table(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    data = np.load(path)
    logt = np.asarray(data["logt"], dtype=float)
    channels = np.asarray(data["channels"], dtype=int)
    response = np.asarray(data["response"], dtype=float)
    if response.ndim != 2 or response.shape[0] != logt.size:
        raise ValueError("Response table has unexpected shape.")
    return logt, channels, response


def gaussian(logt: np.ndarray, mu: float, sigma: float) -> np.ndarray:
    if sigma <= 0:
        raise ValueError("sigma must be > 0")
    z = (logt - mu) / sigma
    return np.exp(-0.5 * z * z)


def prepare_response(
    logt: np.ndarray, response: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    # Ensure ascending logT for interpolation/integration.
    if logt.size == 0:
        raise ValueError("Empty logT grid.")
    if np.all(np.diff(logt) > 0):
        return logt, response
    order = np.argsort(logt)
    return logt[order], response[order, :]


def load_weights_file(path: Path) -> Tuple[List[int], dict[float, List[float]]]:
    channels: List[int] = []
    logt_list: List[float] = []
    single_weights: List[float] = []
    multi_rows: List[Tuple[float, int, float]] = []
    file_logt: float | None = None

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("logt_list="):
            logt_list = [float(v) for v in line.split("=", 1)[1].split(",") if v]
            continue
        if line.startswith("logt="):
            try:
                file_logt = float(line.split("=", 1)[1].strip())
            except ValueError:
                pass
            continue
        if line.startswith("channels="):
            channels = [int(v) for v in line.split("=", 1)[1].split(",") if v]
            continue
        if line.startswith("channels,weights"):
            continue
        if line.startswith("logt,channel,weight"):
            continue
        if any(line.startswith(k) for k in ("delta_logt=", "dem_per_logt=", "ridge=", "scale=")):
            continue

        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 2 and parts[0].isdigit():
            try:
                single_weights.append(float(parts[1]))
            except ValueError:
                continue
        elif len(parts) == 3:
            try:
                multi_rows.append((float(parts[0]), int(parts[1]), float(parts[2])))
            except ValueError:
                continue

    weights_by_logt: dict[float, List[float]] = {}
    if multi_rows:
        if not channels:
            channels = sorted({ch for _, ch, _ in multi_rows})
        if not logt_list:
            logt_list = sorted({lt for lt, _, _ in multi_rows})
        ch_index = {ch: i for i, ch in enumerate(channels)}
        for lt in logt_list:
            weights_by_logt[lt] = [0.0 for _ in channels]
        for lt, ch, w in multi_rows:
            if lt in weights_by_logt and ch in ch_index:
                weights_by_logt[lt][ch_index[ch]] = w
    elif single_weights:
        if not channels:
            raise ValueError("Weights file missing channels list.")
        if len(single_weights) != len(channels):
            raise ValueError("Weights count does not match channels.")
        lt = file_logt if file_logt is not None else 0.0
        weights_by_logt[lt] = single_weights
    else:
        raise ValueError(f"No weights found in {path}")

    return channels, weights_by_logt


def main() -> int:
    args = parse_args()
    resp_path = Path(args.response_npz)
    if not resp_path.exists():
        print(f"Response table not found: {resp_path}")
        return 1

    logt, resp_channels, response = load_response_table(resp_path)
    logt, response = prepare_response(logt, response)
    selected = parse_list(args.channels, int)
    weight_channels: List[int] | None = None
    weights_by_logt: dict[float, List[float]] | None = None
    if args.weights_file:
        weight_channels, weights_by_logt = load_weights_file(Path(args.weights_file))
        selected = weight_channels
    idx = []
    for ch in selected:
        if ch not in resp_channels:
            raise ValueError(f"Channel {ch} not in response table.")
        idx.append(int(np.where(resp_channels == ch)[0][0]))

    dem_logt = gaussian(logt, args.mu, args.sigma)
    if args.dem_per_t:
        # DEM is dEM/dT. Convert to dEM/dlogT for integration on logT grid.
        dem_logt = dem_logt * np.log(10.0) * (10 ** logt)

    denom = np.trapezoid(dem_logt, x=logt)
    if denom == 0:
        raise ValueError("DEM normalization is zero.")

    print(f"logT0={args.logt0}  mu={args.mu}  sigma={args.sigma}")
    print("DEM weighting:", "per dT" if args.dem_per_t else "per dlogT")
    print("Channels:", ",".join(str(c) for c in selected))

    ratios = []
    kbar_list = []
    kt0_list = []
    for ch, j in zip(selected, idx):
        r_t0 = float(np.interp(args.logt0, logt, response[:, j]))
        kbar = float(np.trapezoid(response[:, j] * dem_logt, x=logt) / denom)
        ratio = kbar / r_t0 if r_t0 != 0 else float("inf")
        ratios.append(ratio)
        kbar_list.append(kbar)
        kt0_list.append(r_t0)
        print(f"{ch}: Kbar={kbar:.3e}  K(T0)={r_t0:.3e}  ratio={ratio:.3e}")

    ratios = np.array(ratios, dtype=float)
    finite = ratios[np.isfinite(ratios)]
    if finite.size:
        print("Median ratio:", f"{np.median(finite):.3e}")

    if args.save:
        out = Path(args.save)
        lines = [
            f"# logt0={args.logt0}",
            f"# mu={args.mu}",
            f"# sigma={args.sigma}",
            f"# dem_per_t={args.dem_per_t}",
            f"# channels={','.join(str(c) for c in selected)}",
            "# channel,ratio",
        ]
        for ch, ratio in zip(selected, ratios):
            lines.append(f"{ch},{ratio:.8e}")
        out.write_text("\n".join(lines), encoding="utf-8")
        print(f"Saved ratios to {out}")

    if weights_by_logt is not None:
        print("Weighted proxy ratios (Kbar_w / Kt0_w):")
        kbar_arr = np.array(kbar_list, dtype=float)
        kt0_arr = np.array(kt0_list, dtype=float)
        for lt, w in weights_by_logt.items():
            w_arr = np.array(w, dtype=float)
            if w_arr.shape[0] != kbar_arr.shape[0]:
                continue
            num = float(np.dot(w_arr, kbar_arr))
            den = float(np.dot(w_arr, kt0_arr))
            ratio = num / den if den != 0 else float("inf")
            label = f"{lt}" if lt != 0.0 else "file"
            print(f"  logT={label}: ratio={ratio:.3e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
