#!/usr/bin/env python3
"""Scan vis_cache features and report AUC for flare prediction."""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Scan vis_cache features for flare prediction AUC.")
    p.add_argument("--cache", default="ML_FFT/vis_cache", help="vis_cache folder")
    p.add_argument("--flare-cache", default="flare_cache.tsv")
    p.add_argument("--min-class", default="C3.0")
    p.add_argument("--horizons", default="2,5,10,15")
    p.add_argument("--max-events", type=int, default=0, help="Limit events (0 = all)")
    p.add_argument("--log-scale", action="store_true", help="Apply log1p to positive features")
    p.add_argument("--print-top", type=int, default=12)
    p.add_argument("--pre-min", type=float, default=0.0, help="Minutes before flare to include (0 = all)")
    p.add_argument("--post-min", type=float, default=0.0, help="Minutes after flare to include (0 = none)")
    return p.parse_args()


def goes_to_float(cls: str) -> float:
    cls = cls.strip().upper()
    if not cls:
        return -1.0
    letter = cls[0]
    try:
        magnitude = float(cls[1:])
    except ValueError:
        return -1.0
    mult = {"A": 1e-8, "B": 1e-7, "C": 1e-6, "M": 1e-5, "X": 1e-4}.get(letter)
    if mult is None:
        return -1.0
    return mult * magnitude


def load_flare_info(path: Path, min_class: str) -> Dict[str, dt.datetime]:
    out: Dict[str, dt.datetime] = {}
    if not path.exists():
        return out
    min_val = goes_to_float(min_class)
    with path.open("r", encoding="utf-8") as f:
        header = f.readline().strip().split("\t")
        if "flare_class" not in header or "start" not in header:
            return out
        idx_cls = header.index("flare_class")
        idx_start = header.index("start")
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) <= max(idx_cls, idx_start):
                continue
            cls = parts[idx_cls].strip()
            if goes_to_float(cls) < min_val:
                continue
            start = parts[idx_start].strip()
            if not start:
                continue
            try:
                t0 = dt.datetime.fromisoformat(start.replace("Z", ""))
            except ValueError:
                continue
            ev = f"{cls}_{t0:%Y%m%d_%H%M%S}"
            out[ev] = t0
    return out


def parse_times(times: np.ndarray) -> List[dt.datetime]:
    out = []
    for t in times.astype(str).tolist():
        try:
            out.append(dt.datetime.strptime(t, "%Y-%m-%dT%H%M%S"))
        except ValueError:
            out.append(dt.datetime.strptime(t, "%Y-%m-%dT%H:%M"))
    return out


def auc_from_scores(scores: np.ndarray, labels: np.ndarray) -> float:
    labels = labels.astype(np.int64)
    pos = labels == 1
    n_pos = int(pos.sum())
    n_neg = int((labels == 0).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    # rank-based AUC (Mann–Whitney)
    order = np.argsort(scores)
    ranks = np.empty_like(order, dtype=np.float64)
    ranks[order] = np.arange(1, len(scores) + 1, dtype=np.float64)
    pos_ranks = ranks[pos]
    auc = (pos_ranks.sum() - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)
    return float(auc)


def spectral_features(x: np.ndarray) -> Tuple[float, float, float, float, float, float]:
    # x: (H, W) amplitude
    fft = np.fft.rfft2(x, norm="ortho")
    power = np.abs(fft) ** 2
    total = power.sum() + 1e-9
    p = power / total
    entropy = -np.sum(p * np.log(p + 1e-12))

    h, w = power.shape
    ys = np.linspace(-1.0, 1.0, h)[:, None]
    xs = np.linspace(0.0, 1.0, w)[None, :]
    r = np.sqrt(xs * xs + ys * ys)
    centroid = float((power * r).sum() / total)
    bandwidth = float((power * (r - centroid) ** 2).sum() / total)

    # low/mid/high radial bins
    low = power[r <= 0.33].sum()
    mid = power[(r > 0.33) & (r <= 0.66)].sum()
    high = power[r > 0.66].sum()
    ratio_hl = float(high / (low + 1e-9))
    return float(entropy), centroid, bandwidth, float(low), float(mid), float(high), ratio_hl


def _reconstruct_complex(
    vis: np.ndarray,
    re_idx: List[int],
    im_idx: List[int],
    mag_idx: List[int],
    ph_idx: List[int],
) -> np.ndarray | None:
    if vis.dtype.kind == "c":
        return vis
    if mag_idx and ph_idx and len(mag_idx) == len(ph_idx):
        mag = vis[mag_idx]
        ph = vis[ph_idx]
        return mag * (np.cos(ph) + 1j * np.sin(ph))
    if re_idx and im_idx and len(re_idx) == len(im_idx):
        real = vis[re_idx]
        imag = vis[im_idx]
        return real + 1j * imag
    return None


def frame_features(
    vis: np.ndarray,
    prev: np.ndarray | None,
    re_idx: List[int],
    im_idx: List[int],
    mag_idx: List[int],
    ph_idx: List[int],
) -> Dict[str, float]:
    # vis: (C,H,W) float32 or complex
    vis_c = _reconstruct_complex(vis, re_idx, im_idx, mag_idx, ph_idx)
    prev_c = _reconstruct_complex(prev, re_idx, im_idx, mag_idx, ph_idx) if prev is not None else None
    amp = np.abs(vis_c) if vis_c is not None else np.abs(vis)
    amp_mean = float(amp.mean())
    amp_std = float(amp.std())

    # average over channels for spectral features
    x_mean = amp.mean(axis=0)
    entropy, centroid, bandwidth, low, mid, high, ratio_hl = spectral_features(x_mean)
    # Nested spectrum on visibility-amplitude map: rfft2(mean(|V|)) -> radial moments.
    nested_fft = np.fft.rfft2(x_mean, norm="ortho")
    nested_power = np.abs(nested_fft) ** 2
    nh, nwr = nested_power.shape
    # Exact fftfreq/rfftfreq radius (used by centroid_forecast internals).
    nky = np.fft.fftfreq(nh)[:, None]
    nkx = np.fft.rfftfreq((nwr - 1) * 2)[None, :]
    nr_exact = np.sqrt(nkx * nkx + nky * nky)
    nested_total = float(nested_power.sum()) + 1e-12
    nested_centroid_exact = float((nested_power * nr_exact).sum() / nested_total)
    nested_bandwidth_exact = float((nested_power * (nr_exact - nested_centroid_exact) ** 2).sum() / nested_total)
    # Legacy display radius grid (matches older ~0.4 nested centroid plots).
    nys = np.linspace(-1.0, 1.0, nh)[:, None]
    nxs = np.linspace(0.0, 1.0, nwr)[None, :]
    nr_legacy = np.sqrt(nxs * nxs + nys * nys)
    nested_centroid_legacy = float((nested_power * nr_legacy).sum() / nested_total)
    nested_bandwidth_legacy = float((nested_power * (nr_legacy - nested_centroid_legacy) ** 2).sum() / nested_total)
    nested_low = float(nested_power[nr_legacy <= 0.33].sum())
    nested_mid = float(nested_power[(nr_legacy > 0.33) & (nr_legacy <= 0.66)].sum())
    nested_high = float(nested_power[nr_legacy > 0.66].sum())
    nested_ratio_hl = float(nested_high / (nested_low + 1e-9))
    # Diffraction/saturation proxies computed directly from visibility-amplitude maps.
    # These are instrument-artifact indicators, not physical flare labels.
    q995 = float(np.quantile(x_mean, 0.995))
    q999 = float(np.quantile(x_mean, 0.999))
    sat_mask = x_mean >= q999
    near_sat_mask = x_mean >= q995
    diff_sat_frac = float(np.mean(sat_mask))
    diff_near_sat_frac = float(np.mean(near_sat_mask))
    yy, xx = np.where(near_sat_mask)
    if len(yy) >= 2:
        yspan = float(yy.max() - yy.min() + 1)
        xspan = float(xx.max() - xx.min() + 1)
        diff_bloom_ratio = float(yspan / max(xspan, 1.0))
    else:
        diff_bloom_ratio = 1.0
    # Proxy for diffraction-arm power concentration near axis-aligned bands.
    p_shift = np.fft.fftshift(nested_power, axes=0)
    ph, pw = p_shift.shape
    cy = ph // 2
    hband = p_shift[max(0, cy - 1) : min(ph, cy + 2), :]
    diff_spike_ratio = float(hband.sum() / (nested_total + 1e-12))
    # High-frequency anisotropy: 0 isotropic, 1 highly directional.
    high_mask = nr_exact > (0.75 * float(np.max(nr_exact)))
    w_an = nested_power * high_mask
    w_sum = float(w_an.sum())
    if w_sum > 1e-12:
        kx_m = float((w_an * nkx).sum() / w_sum)
        ky_m = float((w_an * nky).sum() / w_sum)
        cxx = float((w_an * (nkx - kx_m) ** 2).sum() / w_sum)
        cyy = float((w_an * (nky - ky_m) ** 2).sum() / w_sum)
        cxy = float((w_an * (nkx - kx_m) * (nky - ky_m)).sum() / w_sum)
        tr = cxx + cyy
        det = cxx * cyy - cxy * cxy
        disc = max(0.0, tr * tr - 4.0 * det)
        l1 = 0.5 * (tr + np.sqrt(disc))
        l2 = 0.5 * (tr - np.sqrt(disc))
        diff_aniso = float((l1 - l2) / (l1 + l2 + 1e-12))
    else:
        diff_aniso = 0.0
    diff_fringe_ratio = float(nested_high / (nested_total + 1e-12))
    # Channel-wise centroid summaries preserve cross-channel structure that can be lost in x_mean.
    ch_centroids: List[float] = []
    for c in range(amp.shape[0]):
        _, c_centroid, _, _, _, _, _ = spectral_features(amp[c])
        ch_centroids.append(float(c_centroid))
    if ch_centroids:
        ch_arr = np.array(ch_centroids, dtype=np.float64)
        centroid_ch_mean = float(np.mean(ch_arr))
        centroid_ch_std = float(np.std(ch_arr))
        centroid_ch_max = float(np.max(ch_arr))
        centroid_ch_min = float(np.min(ch_arr))
    else:
        centroid_ch_mean = centroid
        centroid_ch_std = 0.0
        centroid_ch_max = centroid
        centroid_ch_min = centroid
    # very high band
    fft = np.fft.rfft2(x_mean, norm="ortho")
    power = np.abs(fft) ** 2
    h, w = power.shape
    ys = np.linspace(-1.0, 1.0, h)[:, None]
    xs = np.linspace(0.0, 1.0, w)[None, :]
    r = np.sqrt(xs * xs + ys * ys)
    vhigh = power[r > 0.8].sum() / (power.sum() + 1e-9)
    spec_slope = float(np.log(high + 1e-9) - np.log(low + 1e-9))

    # spatial texture (grad + laplacian)
    gx = np.diff(x_mean, axis=1, append=x_mean[:, -1:])
    gy = np.diff(x_mean, axis=0, append=x_mean[-1:, :])
    grad = np.sqrt(gx * gx + gy * gy + 1e-9)
    grad_mean = float(grad.mean())
    grad_std = float(grad.std())
    lap = (
        np.pad(x_mean, ((1, 1), (1, 1)), mode="edge")[1:-1, 2:]
        + np.pad(x_mean, ((1, 1), (1, 1)), mode="edge")[1:-1, :-2]
        + np.pad(x_mean, ((1, 1), (1, 1)), mode="edge")[2:, 1:-1]
        + np.pad(x_mean, ((1, 1), (1, 1)), mode="edge")[:-2, 1:-1]
        - 4.0 * x_mean
    )
    lap_energy = float(np.mean(lap * lap))

    feats = {
        "amp_mean": amp_mean,
        "amp_std": amp_std,
        "amp_skew": float(np.mean((amp - amp_mean) ** 3) / (amp_std**3 + 1e-9)),
        "amp_kurt": float(np.mean((amp - amp_mean) ** 4) / (amp_std**4 + 1e-9)),
        "spec_entropy": entropy,
        "spec_centroid": centroid,
        "spec_centroid_ch_mean": centroid_ch_mean,
        "spec_centroid_ch_std": centroid_ch_std,
        "spec_centroid_ch_max": centroid_ch_max,
        "spec_centroid_ch_min": centroid_ch_min,
        "spec_bandwidth": bandwidth,
        "spec_low": low,
        "spec_mid": mid,
        "spec_high": high,
        "spec_vhigh": float(vhigh),
        "spec_hilo": ratio_hl,
        "spec_slope": spec_slope,
        "nested_centroid_exact": nested_centroid_exact,
        "nested_centroid_legacy": nested_centroid_legacy,
        "nested_centroid_legacy_x2": float(2.0 * nested_centroid_exact),
        "nested_bandwidth_exact": nested_bandwidth_exact,
        "nested_bandwidth_legacy": nested_bandwidth_legacy,
        "nested_low": nested_low,
        "nested_mid": nested_mid,
        "nested_high": nested_high,
        "nested_hilo": nested_ratio_hl,
        "diff_sat_frac": diff_sat_frac,
        "diff_near_sat_frac": diff_near_sat_frac,
        "diff_bloom_ratio": diff_bloom_ratio,
        "diff_spike_ratio": diff_spike_ratio,
        "diff_aniso": diff_aniso,
        "diff_fringe_ratio": diff_fringe_ratio,
        "grad_mean": grad_mean,
        "grad_std": grad_std,
        "lap_energy": lap_energy,
    }

    if prev is not None:
        if vis_c is not None and prev_c is not None:
            delta = vis_c - prev_c
        else:
            delta = vis - prev
        feats["delta_energy"] = float(np.mean(np.abs(delta)))
        feats["max_delta"] = float(np.max(np.abs(delta)))
    else:
        feats["delta_energy"] = 0.0
        feats["max_delta"] = 0.0

    if vis_c is not None:
        phase = np.angle(vis_c)
        mean_cos = float(np.mean(np.cos(phase)))
        mean_sin = float(np.mean(np.sin(phase)))
        phase_coh = np.sqrt(mean_cos * mean_cos + mean_sin * mean_sin)
        phase_var = 1.0 - phase_coh
        phase_std = float(np.sqrt(max(0.0, -2.0 * np.log(phase_coh + 1e-9))))
        feats["phase_coh"] = float(phase_coh)
        feats["phase_var"] = float(phase_var)
        feats["phase_std"] = phase_std
        # phase gradient
        pgx = np.diff(phase, axis=1, append=phase[:, -1:])
        pgy = np.diff(phase, axis=0, append=phase[-1:, :])
        pgrad = np.sqrt(pgx * pgx + pgy * pgy + 1e-9)
        feats["phase_grad_mean"] = float(pgrad.mean())

        if prev_c is not None:
            dot = vis_c * np.conj(prev_c)
            coh_num = np.abs(dot.mean())
            coh_den = np.mean(np.abs(vis_c) * np.abs(prev_c)) + 1e-9
            feats["temp_coh"] = float(coh_num / coh_den)
            delta_phase = np.angle(dot)
            feats["phase_delta_mean"] = float(np.mean(np.abs(delta_phase)))
            feats["phase_jump"] = float(np.mean(np.abs(delta_phase) > (0.5 * np.pi)))
        else:
            feats["temp_coh"] = 0.0
            feats["phase_delta_mean"] = 0.0
            feats["phase_jump"] = 0.0

    return feats


def maybe_log(feats: Dict[str, float]) -> Dict[str, float]:
    out = {}
    for k, v in feats.items():
        if v >= 0:
            out[k] = float(np.log1p(v))
        else:
            out[k] = v
    return out


def main() -> None:
    args = parse_args()
    cache_dir = Path(args.cache)
    flare_info = load_flare_info(Path(args.flare_cache), args.min_class)
    horizons = [float(x) for x in args.horizons.split(",") if x.strip()]

    files = sorted(cache_dir.glob("*.npz"))
    if args.max_events:
        files = files[: args.max_events]

    # Collect per-feature scores and labels per horizon
    feat_scores: Dict[str, List[float]] = {}
    feat_labels: Dict[float, List[int]] = {h: [] for h in horizons}
    feat_scores_by_h: Dict[float, Dict[str, List[float]]] = {h: {} for h in horizons}

    re_idx: List[int] = []
    im_idx: List[int] = []
    mag_idx: List[int] = []
    ph_idx: List[int] = []
    for fp in files:
        ev = fp.stem
        if ev not in flare_info:
            continue
        with np.load(fp) as d:
            vis = d["vis"]
            times = parse_times(d["times"])
            if "channels" in d and not re_idx and not mag_idx:
                raw = d["channels"]
                channels = [c.decode() if isinstance(c, (bytes, np.bytes_)) else str(c) for c in raw]
                re_idx = [i for i, c in enumerate(channels) if c.endswith("_re")]
                im_idx = [i for i, c in enumerate(channels) if c.endswith("_im")]
                mag_idx = [i for i, c in enumerate(channels) if c.endswith("_mag")]
                ph_idx = [i for i, c in enumerate(channels) if c.endswith("_ph")]
        t0 = flare_info[ev]

        prev = None
        for i, t in enumerate(times):
            dt_min = (t0 - t).total_seconds() / 60.0
            if args.pre_min > 0 and dt_min > args.pre_min:
                continue
            if dt_min < 0:
                if args.post_min <= 0 or (-dt_min) > args.post_min:
                    continue
            feats = frame_features(
                vis[i],
                prev,
                re_idx,
                im_idx,
                mag_idx,
                ph_idx,
            )
            if args.log_scale:
                feats = maybe_log(feats)
            prev = vis[i]

            # init feature buckets
            for k, v in feats.items():
                feat_scores.setdefault(k, [])

            # horizons labels
            for h in horizons:
                label = 1 if dt_min <= h else 0
                feat_labels[h].append(label)
                for k, v in feats.items():
                    feat_scores_by_h[h].setdefault(k, []).append(v)

    # compute AUCs
    aucs: Dict[str, List[float]] = {k: [] for k in feat_scores_by_h[horizons[0]].keys()}
    for h in horizons:
        labels = np.array(feat_labels[h], dtype=np.int64)
        for k, vals in feat_scores_by_h[h].items():
            scores = np.array(vals, dtype=np.float64)
            aucs[k].append(auc_from_scores(scores, labels))

    # average AUC across horizons
    avg = {k: float(np.nanmean(v)) for k, v in aucs.items()}
    ranked = sorted(avg.items(), key=lambda x: (-(x[1] if np.isfinite(x[1]) else -1e9), x[0]))

    print("Feature AUCs (avg across horizons)")
    for k, v in ranked[: args.print_top]:
        h_str = ", ".join(f"h{int(h)}={aucs[k][i]:.3f}" for i, h in enumerate(horizons))
        print(f"{k:16s} avg={v:.3f}  {h_str}")


if __name__ == "__main__":
    main()
