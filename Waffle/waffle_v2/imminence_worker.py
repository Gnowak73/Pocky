import argparse
import json
import os
import sys
from typing import Dict, List, Tuple

import numpy as np
import torch
import torch.nn as nn


def _json_write(payload):
    sys.stdout.write(json.dumps(payload, allow_nan=False) + "\n")
    sys.stdout.flush()


def _softmax_np(logits):
    z = logits - np.max(logits, axis=1, keepdims=True)
    ez = np.exp(z)
    return ez / np.sum(ez, axis=1, keepdims=True)


def _spectral_features(x: np.ndarray) -> Tuple[float, float, float, float, float, float, float]:
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


def _frame_features(
    vis: np.ndarray,
    prev: np.ndarray | None,
    re_idx: List[int],
    im_idx: List[int],
    mag_idx: List[int],
    ph_idx: List[int],
) -> Dict[str, float]:
    vis_c = _reconstruct_complex(vis, re_idx, im_idx, mag_idx, ph_idx)
    prev_c = _reconstruct_complex(prev, re_idx, im_idx, mag_idx, ph_idx) if prev is not None else None
    amp = np.abs(vis_c) if vis_c is not None else np.abs(vis)
    amp_mean = float(amp.mean())
    amp_std = float(amp.std())

    x_mean = amp.mean(axis=0)
    entropy, centroid, bandwidth, low, mid, high, ratio_hl = _spectral_features(x_mean)
    nested_fft = np.fft.rfft2(x_mean, norm="ortho")
    nested_power = np.abs(nested_fft) ** 2
    nh, nwr = nested_power.shape
    nky = np.fft.fftfreq(nh)[:, None]
    nkx = np.fft.rfftfreq((nwr - 1) * 2)[None, :]
    nr_exact = np.sqrt(nkx * nkx + nky * nky)
    nested_total = float(nested_power.sum()) + 1e-12
    nested_centroid_exact = float((nested_power * nr_exact).sum() / nested_total)
    nested_bandwidth_exact = float((nested_power * (nr_exact - nested_centroid_exact) ** 2).sum() / nested_total)
    nys = np.linspace(-1.0, 1.0, nh)[:, None]
    nxs = np.linspace(0.0, 1.0, nwr)[None, :]
    nr_legacy = np.sqrt(nxs * nxs + nys * nys)
    nested_centroid_legacy = float((nested_power * nr_legacy).sum() / nested_total)
    nested_bandwidth_legacy = float((nested_power * (nr_legacy - nested_centroid_legacy) ** 2).sum() / nested_total)
    nested_low = float(nested_power[nr_legacy <= 0.33].sum())
    nested_mid = float(nested_power[(nr_legacy > 0.33) & (nr_legacy <= 0.66)].sum())
    nested_high = float(nested_power[nr_legacy > 0.66].sum())
    nested_ratio_hl = float(nested_high / (nested_low + 1e-9))

    q995 = float(np.quantile(x_mean, 0.995))
    q999 = float(np.quantile(x_mean, 0.999))
    near_sat_mask = x_mean >= q995
    yy, xx = np.where(near_sat_mask)
    if len(yy) >= 2:
        diff_bloom_ratio = float((yy.max() - yy.min() + 1) / max(float(xx.max() - xx.min() + 1), 1.0))
    else:
        diff_bloom_ratio = 1.0
    p_shift = np.fft.fftshift(nested_power, axes=0)
    ph, _ = p_shift.shape
    cy = ph // 2
    hband = p_shift[max(0, cy - 1) : min(ph, cy + 2), :]
    diff_spike_ratio = float(hband.sum() / (nested_total + 1e-12))

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

    ch_centroids = [_spectral_features(amp[c])[1] for c in range(amp.shape[0])]
    ch_arr = np.array(ch_centroids, dtype=np.float64)
    fft = np.fft.rfft2(x_mean, norm="ortho")
    power = np.abs(fft) ** 2
    h, w = power.shape
    ys = np.linspace(-1.0, 1.0, h)[:, None]
    xs = np.linspace(0.0, 1.0, w)[None, :]
    r = np.sqrt(xs * xs + ys * ys)
    vhigh = power[r > 0.8].sum() / (power.sum() + 1e-9)
    spec_slope = float(np.log(high + 1e-9) - np.log(low + 1e-9))

    gx = np.diff(x_mean, axis=1, append=x_mean[:, -1:])
    gy = np.diff(x_mean, axis=0, append=x_mean[-1:, :])
    grad = np.sqrt(gx * gx + gy * gy + 1e-9)
    lap = (
        np.pad(x_mean, ((1, 1), (1, 1)), mode="edge")[1:-1, 2:]
        + np.pad(x_mean, ((1, 1), (1, 1)), mode="edge")[1:-1, :-2]
        + np.pad(x_mean, ((1, 1), (1, 1)), mode="edge")[2:, 1:-1]
        + np.pad(x_mean, ((1, 1), (1, 1)), mode="edge")[:-2, 1:-1]
        - 4.0 * x_mean
    )

    feats = {
        "amp_mean": amp_mean,
        "amp_std": amp_std,
        "amp_skew": float(np.mean((amp - amp_mean) ** 3) / (amp_std**3 + 1e-9)),
        "amp_kurt": float(np.mean((amp - amp_mean) ** 4) / (amp_std**4 + 1e-9)),
        "spec_entropy": entropy,
        "spec_centroid": centroid,
        "spec_centroid_ch_mean": float(np.mean(ch_arr)),
        "spec_centroid_ch_std": float(np.std(ch_arr)),
        "spec_centroid_ch_max": float(np.max(ch_arr)),
        "spec_centroid_ch_min": float(np.min(ch_arr)),
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
        "diff_sat_frac": float(np.mean(x_mean >= q999)),
        "diff_near_sat_frac": float(np.mean(near_sat_mask)),
        "diff_bloom_ratio": diff_bloom_ratio,
        "diff_spike_ratio": diff_spike_ratio,
        "diff_aniso": diff_aniso,
        "diff_fringe_ratio": diff_fringe_ratio,
        "grad_mean": float(grad.mean()),
        "grad_std": float(grad.std()),
        "lap_energy": float(np.mean(lap * lap)),
    }

    if prev is not None:
        delta = vis_c - prev_c if vis_c is not None and prev_c is not None else vis - prev
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
        feats["phase_coh"] = float(phase_coh)
        feats["phase_var"] = float(1.0 - phase_coh)
        feats["phase_std"] = float(np.sqrt(max(0.0, -2.0 * np.log(phase_coh + 1e-9))))
        pgx = np.diff(phase, axis=1, append=phase[:, -1:])
        pgy = np.diff(phase, axis=0, append=phase[-1:, :])
        feats["phase_grad_mean"] = float(np.sqrt(pgx * pgx + pgy * pgy + 1e-9).mean())
        if prev_c is not None:
            dot = vis_c * np.conj(prev_c)
            coh_num = np.abs(dot.mean())
            coh_den = np.mean(np.abs(vis_c) * np.abs(prev_c)) + 1e-9
            delta_phase = np.angle(dot)
            feats["temp_coh"] = float(coh_num / coh_den)
            feats["phase_delta_mean"] = float(np.mean(np.abs(delta_phase)))
            feats["phase_jump"] = float(np.mean(np.abs(delta_phase) > (0.5 * np.pi)))
        else:
            feats["temp_coh"] = 0.0
            feats["phase_delta_mean"] = 0.0
            feats["phase_jump"] = 0.0
    return feats


def _engineer_feature_table(
    feats_list: List[Dict[str, float]],
    warmup: int,
    feature_mode: str,
) -> Tuple[np.ndarray, List[str], np.ndarray]:
    if not feats_list:
        return np.zeros((0, 0), dtype=np.float32), [], np.zeros((0,), dtype=np.int64)
    keys = sorted(feats_list[0].keys())
    F = np.stack([[float(f[k]) for k in keys] for f in feats_list], axis=0).astype(np.float64)
    T, _ = F.shape
    rows = []
    idx = []
    names = list(keys)
    if feature_mode == "raw":
        for i in range(T):
            if i >= max(1, warmup):
                rows.append(F[i].astype(np.float32))
                idx.append(i)
        if not rows:
            return np.empty((0, len(names)), dtype=np.float32), names, np.asarray(idx, dtype=np.int64)
        return np.stack(rows).astype(np.float32), names, np.asarray(idx, dtype=np.int64)

    for suffix in ("d1", "d3", "d5", "slope3", "slope5", "z5", "z10"):
        for k in keys:
            names.append(f"{k}_{suffix}")
    extra_pairs = [
        ("nested_centroid_legacy_x2", "nested_hilo"),
        ("phase_delta_mean", "phase_jump"),
        ("delta_energy", "max_delta"),
        ("spec_centroid", "spec_hilo"),
    ]
    valid_pairs = [(a, b) for a, b in extra_pairs if a in keys and b in keys]
    for a, b in valid_pairs:
        names.append(f"{a}_x_{b}")
    key_to_idx = {k: i for i, k in enumerate(keys)}

    for i in range(T):
        if i < max(1, warmup):
            continue
        cur = F[i]
        w3 = F[max(0, i - 2) : i + 1]
        w5 = F[max(0, i - 4) : i + 1]
        w10 = F[max(0, i - 9) : i + 1]
        prev1 = F[i - 1]
        prev3_mean = np.mean(w3[:-1], axis=0) if len(w3) > 1 else prev1
        prev5_mean = np.mean(w5[:-1], axis=0) if len(w5) > 1 else prev1
        d1 = cur - prev1
        d3 = cur - prev3_mean
        d5 = cur - prev5_mean
        slope3 = (cur - w3[0]) / max(len(w3) - 1, 1)
        slope5 = (cur - w5[0]) / max(len(w5) - 1, 1)
        z5 = (cur - np.mean(w5, axis=0)) / (np.std(w5, axis=0) + 1e-8)
        z10 = (cur - np.mean(w10, axis=0)) / (np.std(w10, axis=0) + 1e-8)
        x = np.concatenate([cur, d1, d3, d5, slope3, slope5, z5, z10], axis=0)
        if valid_pairs:
            extras = [cur[key_to_idx[a]] * cur[key_to_idx[b]] for a, b in valid_pairs]
            x = np.concatenate([x, np.asarray(extras, dtype=np.float64)], axis=0)
        rows.append(x.astype(np.float32))
        idx.append(i)
    if not rows:
        return np.empty((0, len(names)), dtype=np.float32), names, np.asarray(idx, dtype=np.int64)
    return np.stack(rows).astype(np.float32), names, np.asarray(idx, dtype=np.int64)


class MLP(nn.Module):
    def __init__(self, in_dim: int, out_dim: int, hidden: int, dropout: float) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(in_dim, hidden),
            nn.ReLU(inplace=True),
            nn.Dropout(dropout),
            nn.Linear(hidden, hidden // 2),
            nn.ReLU(inplace=True),
            nn.Dropout(dropout),
            nn.Linear(hidden // 2, out_dim),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


def _make_model(in_dim: int, out_dim: int, model_type: str, hidden: int, dropout: float) -> nn.Module:
    if model_type == "linear":
        return nn.Linear(in_dim, out_dim)
    return MLP(in_dim, out_dim, hidden, dropout)


def _load_runtime(model_path, repo_root):
    worker_lib = os.path.join(os.path.dirname(__file__), "worker_lib")
    if worker_lib not in sys.path:
        sys.path.insert(0, worker_lib)

    from scan_vis_features import frame_features
    from train_flare_imminence_classifier import engineer_feature_table, make_model

    ck = torch.load(model_path, map_location="cpu", weights_only=False)
    bins = [float(x) for x in ck["bins"]]
    n_cls = len(bins) + 1
    risk_weights = np.asarray(
        ck.get("risk_weights", [1.0, 0.7, 0.4, 0.0][:n_cls]), dtype=np.float32
    )
    args = ck.get("args", {})
    feature_names = list(ck["feature_names"])
    x_mean = np.asarray(ck["x_mean"], dtype=np.float32).reshape(-1)
    x_std = np.asarray(ck["x_std"], dtype=np.float32).reshape(-1)
    dev = torch.device("cpu")
    net = make_model(
        len(feature_names),
        n_cls,
        str(args.get("model", "mlp")),
        int(args.get("hidden", 256)),
        float(args.get("dropout", 0.2)),
    ).to(dev)
    net.load_state_dict(ck["state_dict"])
    net.eval()
    return {
        "torch": torch,
        "device": dev,
        "model": net,
        "frame_features": frame_features,
        "engineer_feature_table": engineer_feature_table,
        "warmup": int(args.get("warmup", 10)),
        "feature_mode": str(args.get("feature_mode", "all")),
        "feature_names": feature_names,
        "x_mean": x_mean,
        "x_std": x_std,
        "bins": bins,
        "risk_weights": risk_weights,
    }


def _infer(vis_history, runtime):
    if len(vis_history) <= runtime["warmup"]:
        return None, None, f"warmup {len(vis_history)}/{runtime['warmup'] + 1}"
    feats_list = []
    prev = None
    re_idx = list(range(5))
    im_idx = list(range(5, 10))
    mag_idx = []
    ph_idx = []
    for vis in vis_history:
        feats = runtime["frame_features"](vis, prev, re_idx, im_idx, mag_idx, ph_idx)
        feats_list.append(feats)
        prev = vis
    X, names, _ = runtime["engineer_feature_table"](
        feats_list,
        warmup=runtime["warmup"],
        feature_mode=runtime["feature_mode"],
    )
    if X.size == 0 or names != runtime["feature_names"]:
        if names != runtime["feature_names"]:
            return None, None, (
                f"feature mismatch generated={len(names)} "
                f"expected={len(runtime['feature_names'])}"
            )
        return None, None, "empty feature table"
    x = np.asarray(X[-1], dtype=np.float32).reshape(-1)
    x_norm = ((x - runtime["x_mean"]) / runtime["x_std"]).astype(np.float32)
    with torch.no_grad():
        logits = (
            runtime["model"](
                torch.from_numpy(x_norm).unsqueeze(0).to(runtime["device"])
            )
            .cpu()
            .numpy()
        )
    prob = _softmax_np(logits)[0].astype(np.float32)
    risk = float(np.sum(prob * runtime["risk_weights"]))
    return risk, prob.tolist(), "ok"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--repo-root", required=True)
    args = parser.parse_args()

    try:
        runtime = _load_runtime(os.path.abspath(args.model), os.path.abspath(args.repo_root))
    except Exception as exc:
        _json_write({"ok": False, "error": str(exc)})
        return 1

    _json_write({"ok": True, "cmd": "ready", "warmup": runtime["warmup"], "bins": runtime["bins"]})
    for line in sys.stdin:
        try:
            req = json.loads(line)
            cmd = req.get("cmd")
            if cmd == "shutdown":
                break
            if cmd != "infer":
                _json_write({"ok": False, "error": f"unknown command: {cmd}"})
                continue
            path = req.get("path")
            data = np.load(path)
            risk, prob, status = _infer(np.asarray(data["vis"], dtype=np.float32), runtime)
            _json_write({"ok": True, "risk": risk, "probabilities": prob, "status": status})
        except Exception as exc:
            _json_write({"ok": False, "error": str(exc)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
