#!/usr/bin/env python3
"""Compute DEM proxy weights from the AIA temperature response table."""

from __future__ import annotations

import argparse
import math
import re
from pathlib import Path
from typing import List

import numpy as np


def parse_args() -> argparse.Namespace:
    dem_dir = Path(__file__).resolve().parent
    p = argparse.ArgumentParser(
        description="Compute DEM proxy weights from response functions.",
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
    p.add_argument("--logt", type=float, default=6.6, help="Target log10(T/K).")
    p.add_argument(
        "--multi",
        action="store_true",
        help="Compute weights for logT bins 6.4,6.6,6.8,7.0.",
    )
    p.add_argument(
        "--logt-list",
        default="",
        help="Comma list of logT bin centers (overrides --logt/--multi).",
    )
    p.add_argument(
        "--gaussian",
        action="store_true",
        help="Fit weights using a Gaussian DEM basis (joint regression).",
    )
    p.add_argument(
        "--gauss-min",
        type=float,
        default=None,
        help="Minimum logT center for Gaussian basis (default: min(logt_list)-0.4).",
    )
    p.add_argument(
        "--gauss-max",
        type=float,
        default=None,
        help="Maximum logT center for Gaussian basis (default: max(logt_list)+0.4).",
    )
    p.add_argument(
        "--gauss-step",
        type=float,
        default=None,
        help="Step in logT for Gaussian basis centers (default: 0.1).",
    )
    p.add_argument(
        "--sigmas",
        default="0.1",
        help="Comma list of Gaussian sigmas in logT (default: 0.1).",
    )
    p.add_argument(
        "--normalize",
        choices=["max", "area", "none"],
        default="max",
        help="Normalize Gaussian basis functions by peak (max), area, or none.",
    )
    p.add_argument(
        "--ratios",
        default="",
        help="Comma list of per-channel ratios aligned with --channels (applied as w/ratio).",
    )
    p.add_argument(
        "--ratio-file",
        default="",
        help="Path to a file with per-channel ratios (e.g. from test_response_ratio).",
    )
    p.add_argument(
        "--nonneg",
        action="store_true",
        help="Force nonnegative weights.",
    )
    p.add_argument(
        "--delta-logt",
        type=float,
        default=0.0,
        help="Bin width in log10(T/K); 0 uses grid median spacing.",
    )
    p.add_argument(
        "--dem-per-logt",
        action="store_true",
        help="Assume DEM is per dlogT (default is per dT).",
    )
    p.add_argument(
        "--ridge",
        type=float,
        default=0.0,
        help="Ridge strength (0 disables).",
    )
    p.add_argument(
        "--save",
        nargs="?",
        const="__AUTO__",
        default="",
        help="Save weights to a file (optional path, default DEM/dem_weights.txt).",
    )
    return p.parse_args()


def parse_list(value: str, cast) -> List:
    return [cast(v.strip()) for v in value.split(",") if v.strip()]


RATIO_PAIR_RE = re.compile(r"^\s*(\d+)\s*[, \t]\s*([-+0-9.eE]+)")
RATIO_INLINE_RE = re.compile(
    r"(?P<ch>\d+).*?ratio\s*=\s*(?P<ratio>[-+0-9.eE]+)", re.IGNORECASE
)


def load_ratio_file(path: Path) -> dict[int, float]:
    ratios: dict[int, float] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = RATIO_INLINE_RE.search(line)
        if m:
            ratios[int(m.group("ch"))] = float(m.group("ratio"))
            continue
        m = RATIO_PAIR_RE.match(line)
        if m:
            ratios[int(m.group(1))] = float(m.group(2))
    return ratios


def load_response_table(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    data = np.load(path)
    logt = np.asarray(data["logt"], dtype=float)
    channels = np.asarray(data["channels"], dtype=int)
    response = np.asarray(data["response"], dtype=float)
    if response.ndim != 2 or response.shape[0] != logt.size:
        raise ValueError("Response table has unexpected shape.")
    return logt, channels, response


def derive_weights(
    logt: np.ndarray,
    channels: np.ndarray,
    response: np.ndarray,
    selected: List[int],
    logt0: float,
    delta_logt: float,
    dem_per_logt: bool,
    ridge: float,
) -> tuple[np.ndarray, float]:
    idx = []
    for ch in selected:
        if ch not in channels:
            raise ValueError(f"Channel {ch} not in response table.")
        idx.append(int(np.where(channels == ch)[0][0]))

    r = np.array([np.interp(logt0, logt, response[:, j]) for j in idx], dtype=float)
    if delta_logt <= 0:
        if logt.size < 2:
            raise ValueError("Need at least 2 logT points to infer delta_logt.")
        delta_logt = float(np.median(np.diff(logt)))

    if dem_per_logt:
        scale = delta_logt
    else:
        t0 = 10.0 ** logt0
        scale = math.log(10.0) * t0 * delta_logt

    if ridge > 0:
        rmat = response[:, idx].T  # (n_ch, n_t)
        if dem_per_logt:
            quad = np.full(logt.shape, delta_logt, dtype=float)
        else:
            quad = np.log(10.0) * (10.0 ** logt) * delta_logt
        rr = (rmat * quad[None, :]) @ rmat.T
        lam = ridge * np.trace(rr) / max(len(selected), 1)
        w = np.linalg.solve(rr + lam * np.eye(len(selected)), r)
    else:
        denom = float(r @ r)
        if denom == 0.0:
            raise ValueError("Response vector is zero at this logT.")
        w = r / denom

    norm = scale * float(w @ r)
    if norm == 0.0:
        raise ValueError("Normalization failed (w·r = 0).")
    w = w / norm
    return w, scale


def resolve_logt_bins(args: argparse.Namespace) -> List[float]:
    if args.logt_list:
        return parse_list(args.logt_list, float)
    if args.multi or args.gaussian:
        return [6.4, 6.6, 6.8, 7.0]
    return [args.logt]


def gaussian_basis(
    logt: np.ndarray,
    centers: List[float],
    sigmas: List[float],
    normalize: str,
    dem_per_logt: bool,
    delta_logt: float,
) -> np.ndarray:
    dem_list = []
    logt = np.asarray(logt, dtype=float)
    if dem_per_logt:
        scale = delta_logt
    else:
        t_vals = 10.0 ** logt
        scale = np.log(10.0) * t_vals * delta_logt
    for mu in centers:
        for sigma in sigmas:
            g = np.exp(-0.5 * ((logt - mu) / sigma) ** 2)
            if normalize == "max":
                peak = float(np.max(g))
                if peak > 0:
                    g = g / peak
            elif normalize == "area":
                area = float(np.sum(g * scale))
                if area > 0:
                    g = g / area
            dem_list.append(g)
    return np.stack(dem_list, axis=0)


def gaussian_weights(
    logt: np.ndarray,
    channels: np.ndarray,
    response: np.ndarray,
    selected: List[int],
    logt_bins: List[float],
    delta_logt: float,
    dem_per_logt: bool,
    ridge: float,
    gauss_min: float | None,
    gauss_max: float | None,
    gauss_step: float | None,
    sigmas: List[float],
    normalize: str,
    nonneg: bool,
) -> np.ndarray:
    idx = []
    for ch in selected:
        if ch not in channels:
            raise ValueError(f"Channel {ch} not in response table.")
        idx.append(int(np.where(channels == ch)[0][0]))

    if delta_logt <= 0:
        if logt.size < 2:
            raise ValueError("Need at least 2 logT points to infer delta_logt.")
        delta_logt = float(np.median(np.diff(logt)))

    logt_bins = sorted(logt_bins)
    min_bin = min(logt_bins)
    max_bin = max(logt_bins)
    if gauss_min is None:
        gauss_min = min_bin - 0.4
    if gauss_max is None:
        gauss_max = max_bin + 0.4
    if gauss_step is None:
        gauss_step = 0.1

    centers = np.arange(gauss_min, gauss_max + 1e-6, gauss_step).tolist()

    dem_stack = gaussian_basis(
        logt, centers, sigmas, normalize, dem_per_logt, delta_logt
    )  # (m, n_t)

    response_sel = response[:, idx]  # (n_t, n_ch)
    if dem_per_logt:
        factor = np.full(logt.shape, delta_logt, dtype=float)
    else:
        factor = np.log(10.0) * (10.0 ** logt) * delta_logt

    weighted_response = response_sel * factor[:, None]
    intensities = dem_stack @ weighted_response  # (m, n_ch)

    targets = np.vstack(
        [np.interp(logt_bins, logt, dem) for dem in dem_stack]
    )  # (m, n_bins)

    gram = intensities.T @ intensities
    lam = ridge * np.trace(gram) / max(len(selected), 1) if ridge > 0 else 0.0

    if nonneg:
        w_list = []
        for j in range(targets.shape[1]):
            w_j = nnls_ridge(intensities, targets[:, j], lam)
            w_list.append(w_j)
        return np.stack(w_list, axis=0)

    if ridge > 0:
        w = np.linalg.solve(gram + lam * np.eye(len(selected)), intensities.T @ targets)
    else:
        w, *_ = np.linalg.lstsq(intensities, targets, rcond=None)
    return w.T  # (n_bins, n_ch)


def nnls_ridge(
    a: np.ndarray,
    y: np.ndarray,
    lam: float,
    max_iter: int = 1000,
    tol: float = 1e-8,
) -> np.ndarray:
    a = np.asarray(a, dtype=float)
    y = np.asarray(y, dtype=float)
    if a.size == 0:
        return np.zeros(a.shape[1], dtype=float)
    w, *_ = np.linalg.lstsq(a, y, rcond=None)
    w = np.maximum(0.0, w)
    l = float(np.linalg.norm(a, 2) ** 2 + lam)
    if l <= 0:
        return w
    step = 1.0 / l
    for _ in range(max_iter):
        grad = a.T @ (a @ w - y) + lam * w
        w_new = w - step * grad
        w_new = np.maximum(0.0, w_new)
        if np.linalg.norm(w_new - w) <= tol * (np.linalg.norm(w) + 1e-12):
            w = w_new
            break
        w = w_new
    return w


def apply_ratio_correction(
    weights: List[np.ndarray] | np.ndarray, ratios: List[float]
) -> tuple[List[np.ndarray] | np.ndarray, List[np.ndarray] | np.ndarray]:
    if isinstance(weights, np.ndarray):
        old = weights.copy()
        ratios_arr = np.asarray(ratios, dtype=float)
        if ratios_arr.shape != (weights.shape[1],):
            raise ValueError("Ratio count does not match channel count.")
        new = weights / ratios_arr[None, :]
        return old, new
    old_list = [w.copy() for w in weights]
    new_list = []
    for w in weights:
        ratios_arr = np.asarray(ratios, dtype=float)
        if ratios_arr.shape != (w.shape[0],):
            raise ValueError("Ratio count does not match channel count.")
        new_list.append(w / ratios_arr)
    return old_list, new_list


def main() -> int:
    args = parse_args()
    default_save = str(Path(__file__).resolve().parent / "dem_weights.txt")
    response_path = Path(args.response_npz)
    if not response_path.exists():
        print(f"Response table not found: {response_path}")
        return 1

    logt, resp_channels, response = load_response_table(response_path)
    selected = parse_list(args.channels, int)
    logt_vals = resolve_logt_bins(args)

    weights_by_logt = []
    scales = []
    if args.gaussian:
        sigmas = parse_list(args.sigmas, float)
        weights_by_logt = gaussian_weights(
            logt,
            resp_channels,
            response,
            selected,
            logt_vals,
            args.delta_logt,
            args.dem_per_logt,
            args.ridge,
            args.gauss_min,
            args.gauss_max,
            args.gauss_step,
            sigmas,
            args.normalize,
            args.nonneg,
        )
    else:
        for logt0 in logt_vals:
            w, scale = derive_weights(
                logt,
                resp_channels,
                response,
                selected,
                logt0,
                args.delta_logt,
                args.dem_per_logt,
                args.ridge,
            )
            weights_by_logt.append(w)
            scales.append(scale)

    if args.nonneg and not args.gaussian:
        idx = [int(np.where(resp_channels == ch)[0][0]) for ch in selected]
        new_weights = []
        for logt0, w, scale in zip(logt_vals, weights_by_logt, scales):
            w_pos = np.maximum(0.0, np.asarray(w, dtype=float))
            r = np.array([np.interp(logt0, logt, response[:, j]) for j in idx], dtype=float)
            norm = scale * float(w_pos @ r)
            if norm == 0.0:
                raise ValueError("Nonnegative weights collapsed to zero.")
            w_pos = w_pos / norm
            new_weights.append(w_pos)
        weights_by_logt = new_weights

    ratios = None
    if args.ratios or args.ratio_file:
        ratio_map: dict[int, float] = {}
        if args.ratio_file:
            ratio_map.update(load_ratio_file(Path(args.ratio_file)))
        if args.ratios:
            ratio_values = parse_list(args.ratios, float)
            if len(ratio_values) != len(selected):
                raise ValueError("Ratio list length must match --channels.")
            ratio_map.update({ch: r for ch, r in zip(selected, ratio_values)})
        ratios = []
        for ch in selected:
            if ch not in ratio_map:
                raise ValueError(f"Missing ratio for channel {ch}.")
            ratio = float(ratio_map[ch])
            if ratio <= 0:
                raise ValueError(f"Invalid ratio for channel {ch}: {ratio}")
            ratios.append(ratio)
        old_weights, weights_by_logt = apply_ratio_correction(weights_by_logt, ratios)

    print("Channels:", ",".join(str(c) for c in selected))
    if len(logt_vals) > 1:
        print("logT bins:", ",".join(f"{v:.1f}" for v in logt_vals))
    else:
        print("logT:", logt_vals[0])
    print("delta_logT:", args.delta_logt if args.delta_logt > 0 else "auto")
    print("DEM per logT:" if args.dem_per_logt else "DEM per T")
    if args.ridge:
        print("Ridge:", args.ridge)
    if args.nonneg:
        print("Nonnegative weights: enabled")
    if ratios is not None:
        print("Ratio correction: w_new = w_old / ratio")
        for ch, ratio in zip(selected, ratios):
            print(f"  ratio {ch}: {ratio:.8e}")
    if args.gaussian:
        sigmas = parse_list(args.sigmas, float)
        print("Gaussian basis:", f"sigmas={','.join(str(s) for s in sigmas)}")
        if args.gauss_min is not None:
            print("Gaussian min:", args.gauss_min)
        if args.gauss_max is not None:
            print("Gaussian max:", args.gauss_max)
        if args.gauss_step is not None:
            print("Gaussian step:", args.gauss_step)
        print("Gaussian normalize:", args.normalize)
        for i, (logt0, weights) in enumerate(zip(logt_vals, weights_by_logt)):
            print(f"Weights logT={logt0}:")
            if ratios is not None:
                old = old_weights[i]
                for ch, w_old, w_new in zip(selected, old, weights):
                    print(f"  {ch}: {w_old:.8e} -> {w_new:.8e}")
            else:
                for ch, w in zip(selected, weights):
                    print(f"  {ch}: {w:.8e}")
    else:
        for logt0, scale, weights in zip(logt_vals, scales, weights_by_logt):
            print(f"Scale (bin width) logT={logt0}:", f"{scale:.3e}")
            print("Weights:")
            if ratios is not None:
                old = old_weights[logt_vals.index(logt0)]
                for ch, w_old, w_new in zip(selected, old, weights):
                    print(f"  {ch}: {w_old:.8e} -> {w_new:.8e}")
            else:
                for ch, w in zip(selected, weights):
                    print(f"  {ch}: {w:.8e}")

    if args.save:
        save_path = args.save
        if save_path == "__AUTO__":
            if args.gaussian:
                save_path = str(Path(__file__).resolve().parent / "dem_weights_gaussian.txt")
            elif len(logt_vals) > 1:
                save_path = str(Path(__file__).resolve().parent / "dem_weights_multi.txt")
            else:
                save_path = default_save
        out = Path(save_path)
        if args.gaussian or len(logt_vals) > 1:
            lines = [
                f"logt_list={','.join(str(v) for v in logt_vals)}",
                f"delta_logt={args.delta_logt if args.delta_logt > 0 else 'auto'}",
                f"dem_per_logt={args.dem_per_logt}",
                f"ridge={args.ridge}",
                f"nonneg={args.nonneg}",
                f"channels={','.join(str(c) for c in selected)}",
            ]
            if args.gaussian:
                lines.extend(
                    [
                        "mode=gaussian",
                        f"normalize={args.normalize}",
                        f"sigmas={args.sigmas}",
                        f"gauss_min={args.gauss_min if args.gauss_min is not None else ''}",
                        f"gauss_max={args.gauss_max if args.gauss_max is not None else ''}",
                        f"gauss_step={args.gauss_step if args.gauss_step is not None else ''}",
                    ]
                )
            if ratios is not None:
                lines.append(f"ratio_mode=per-channel")
                lines.append(
                    "ratios=" + ",".join(f"{ch}:{r:.8e}" for ch, r in zip(selected, ratios))
                )
            lines.append("logt,channel,weight")
            if args.gaussian:
                for logt0, weights in zip(logt_vals, weights_by_logt):
                    for ch, w in zip(selected, weights):
                        lines.append(f"{logt0},{ch},{w:.8e}")
            else:
                for logt0, weights in zip(logt_vals, weights_by_logt):
                    for ch, w in zip(selected, weights):
                        lines.append(f"{logt0},{ch},{w:.8e}")
        else:
            weights = weights_by_logt[0]
            scale = scales[0]
            lines = [
                f"logt={args.logt}",
                f"delta_logt={args.delta_logt if args.delta_logt > 0 else 'auto'}",
                f"dem_per_logt={args.dem_per_logt}",
                f"ridge={args.ridge}",
                f"nonneg={args.nonneg}",
                f"scale={scale:.8e}",
                "channels,weights",
            ]
            lines += [f"{ch},{w:.8e}" for ch, w in zip(selected, weights)]
        out.write_text("\n".join(lines), encoding="utf-8")
        print(f"Saved weights to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
