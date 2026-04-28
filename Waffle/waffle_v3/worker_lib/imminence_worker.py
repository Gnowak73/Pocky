"""Isolated PyTorch worker for WAFFLE imminence inference.

The legacy Windows launcher runs this process from the small ``Waffle_Torch``
environment so the main WAFFLE process never imports Torch. The worker reads
JSON commands from stdin and writes one JSON response per line to stdout.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
import torch


def _json_write(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, allow_nan=False) + "\n")
    sys.stdout.flush()


def _softmax_np(logits: np.ndarray) -> np.ndarray:
    z = logits - np.max(logits, axis=1, keepdims=True)
    exp_z = np.exp(z)
    return exp_z / np.sum(exp_z, axis=1, keepdims=True)


def _append_em_proxy_change_features(feats_list, em_vals):
    if not feats_list or not em_vals:
        return feats_list
    series = np.asarray(em_vals, dtype=np.float64)
    if len(series) < len(feats_list):
        pad = np.full(len(feats_list) - len(series), np.nan, dtype=np.float64)
        series = np.concatenate([pad, series], axis=0)
    else:
        series = series[-len(feats_list):]
    series = np.where(np.isfinite(series), np.maximum(series, 0.0), np.nan)
    log_series = np.log10(1.0 + series)

    def safe_at(i):
        i = max(0, min(len(log_series) - 1, i))
        v = float(log_series[i])
        if np.isfinite(v):
            return v
        finite = log_series[np.isfinite(log_series)]
        return float(finite[-1]) if len(finite) else 0.0

    out = []
    for idx, feats in enumerate(feats_list):
        cur = safe_at(idx)
        prev1 = safe_at(idx - 1)
        prev2 = safe_at(idx - 2)
        w3 = np.asarray([safe_at(j) for j in range(max(0, idx - 2), idx + 1)], dtype=np.float64)
        w5 = np.asarray([safe_at(j) for j in range(max(0, idx - 4), idx + 1)], dtype=np.float64)
        d1 = cur - prev1
        d2 = cur - (2.0 * prev1) + prev2
        d3 = cur - float(np.mean(w3[:-1])) if len(w3) > 1 else d1
        slope3 = (cur - float(w3[0])) / max(len(w3) - 1, 1)
        slope5 = (cur - float(w5[0])) / max(len(w5) - 1, 1)
        prev_slope3 = (prev1 - safe_at(idx - 3)) / 2.0 if idx >= 2 else d1
        accel3 = slope3 - prev_slope3
        diffs5 = np.diff(w5) if len(w5) > 1 else np.asarray([], dtype=np.float64)
        row = dict(feats)
        row["emlog_d1"] = float(d1)
        row["emlog_d2"] = float(d2)
        row["emlog_d3"] = float(d3)
        row["emlog_slope3"] = float(slope3)
        row["emlog_slope5"] = float(slope5)
        row["emlog_accel3"] = float(accel3)
        row["emlog_slope3_minus_slope5"] = float(slope3 - slope5)
        row["emlog_up_steps5"] = float(np.sum(diffs5 > 0.0))
        row["emlog_down_steps5"] = float(np.sum(diffs5 < 0.0))
        out.append(row)
    return out


def _load_runtime(model_path: str, state_model_path: str = "") -> dict:
    worker_dir = os.path.dirname(__file__)
    if worker_dir not in sys.path:
        sys.path.insert(0, worker_dir)

    from runtime_vis_features import frame_features
    from runtime_imminence_model import engineer_feature_table, make_model

    checkpoint = torch.load(model_path, map_location="cpu", weights_only=False)
    args = checkpoint.get("args", {})
    is_binary_horizon = "horizon_min" in checkpoint and "bins" not in checkpoint
    if is_binary_horizon:
        bins = [float(checkpoint["horizon_min"])]
        n_cls = 2
        risk_weights = np.asarray([0.0, 1.0], dtype=np.float32)
        model_type = str(args.get("model", "gru"))
    else:
        bins = [float(x) for x in checkpoint["bins"]]
        n_cls = len(bins) + 1
        risk_weights = np.asarray(
            checkpoint.get("risk_weights", [1.0, 0.7, 0.4, 0.0][:n_cls]),
            dtype=np.float32,
        )
        model_type = str(args.get("model", "mlp"))
    feature_names = list(checkpoint["feature_names"])

    net = make_model(
        len(feature_names),
        n_cls,
        model_type,
        int(args.get("hidden", 256)),
        float(args.get("dropout", 0.2)),
        int(args.get("layers", 1)),
    ).to(torch.device("cpu"))
    net.load_state_dict(checkpoint["state_dict"])
    net.eval()

    state_runtime = None
    if state_model_path:
        state_ck = torch.load(state_model_path, map_location="cpu", weights_only=False)
        state_args = state_ck.get("args", {})
        state_net = make_model(
            len(state_ck["feature_names"]),
            3,
            str(state_args.get("model", "mlp")),
            int(state_args.get("hidden", 256)),
            float(state_args.get("dropout", 0.2)),
            int(state_args.get("layers", 1)),
        ).to(torch.device("cpu"))
        state_net.load_state_dict(state_ck["state_dict"])
        state_net.eval()
        state_runtime = {
            "model": state_net,
            "feature_names": list(state_ck["feature_names"]),
            "x_mean": np.asarray(state_ck["x_mean"], dtype=np.float32).reshape(-1),
            "x_std": np.asarray(state_ck["x_std"], dtype=np.float32).reshape(-1),
            "warmup": int(state_args.get("warmup", 10)),
            "lookback": int(state_args.get("lookback", 10)),
            "feature_mode": str(state_args.get("feature_mode", "all")),
        }

    return {
        "model": net,
        "frame_features": frame_features,
        "engineer_feature_table": engineer_feature_table,
        "warmup": int(args.get("warmup", 10)),
        "lookback": int(args.get("lookback", 10)),
        "seq_len": int(args.get("seq_len", 1)),
        "is_binary_horizon": bool(is_binary_horizon),
        "feature_mode": str(args.get("feature_mode", "all")),
        "feature_names": feature_names,
        "x_mean": np.asarray(checkpoint["x_mean"], dtype=np.float32).reshape(-1),
        "x_std": np.asarray(checkpoint["x_std"], dtype=np.float32).reshape(-1),
        "bins": bins,
        "risk_weights": risk_weights,
        "include_em_proxy_change_features": bool(args.get("include_em_proxy_change_features", False)),
        "include_state_prob_features": bool(args.get("include_state_prob_features", False)),
        "state_runtime": state_runtime,
    }


def _infer(vis_history: np.ndarray, runtime: dict, em_history: list[float] | None = None) -> tuple[float | None, list[float] | None, str]:
    required_frames = int(runtime["warmup"]) + int(runtime.get("seq_len", 1))
    if len(vis_history) < required_frames:
        return None, None, f"warmup {len(vis_history)}/{required_frames}"

    feats_list = []
    prev = None
    re_idx = list(range(5))
    im_idx = list(range(5, 10))
    for vis in vis_history:
        feats_list.append(runtime["frame_features"](vis, prev, re_idx, im_idx, [], []))
        prev = vis

    state_runtime = runtime.get("state_runtime")
    if state_runtime and runtime.get("include_state_prob_features"):
        Xs, state_names, state_idx = runtime["engineer_feature_table"](
            feats_list,
            warmup=state_runtime["warmup"],
            feature_mode=state_runtime["feature_mode"],
            lookback=state_runtime["lookback"],
        )
        if Xs.size == 0 or state_names != state_runtime["feature_names"]:
            return None, None, "state feature mismatch"
        xs_norm = ((Xs - state_runtime["x_mean"]) / state_runtime["x_std"]).astype(np.float32)
        with torch.no_grad():
            state_logits = state_runtime["model"](torch.from_numpy(xs_norm)).cpu().numpy()
        state_prob = _softmax_np(state_logits).astype(np.float32)
        state_by_idx = {int(idx): state_prob[k] for k, idx in enumerate(state_idx)}
        augmented = []
        for i, feats in enumerate(feats_list):
            row = dict(feats)
            p = state_by_idx.get(i)
            if p is None:
                row["state_rising"] = 0.0
                row["state_preflare"] = 0.0
                row["state_postflare"] = 0.0
            else:
                row["state_rising"] = float(p[0])
                row["state_preflare"] = float(p[1])
                row["state_postflare"] = float(p[2])
            augmented.append(row)
        feats_list = augmented
    if runtime.get("include_em_proxy_change_features"):
        feats_list = _append_em_proxy_change_features(feats_list, em_history or [])

    X, names, _ = runtime["engineer_feature_table"](
        feats_list,
        warmup=runtime["warmup"],
        feature_mode=runtime["feature_mode"],
        lookback=runtime.get("lookback", 10),
    )
    if X.size == 0:
        return None, None, "empty feature table"
    if names != runtime["feature_names"]:
        return None, None, (
            f"feature mismatch generated={len(names)} "
            f"expected={len(runtime['feature_names'])}"
        )

    if runtime.get("seq_len", 1) > 1:
        seq_len = int(runtime["seq_len"])
        if X.shape[0] < seq_len:
            return None, None, f"sequence warmup {X.shape[0]}/{seq_len}"
        x = np.asarray(X[-seq_len:], dtype=np.float32)
        x_norm = ((x - runtime["x_mean"].reshape(1, -1)) / runtime["x_std"].reshape(1, -1)).astype(np.float32)
        tensor_in = torch.from_numpy(x_norm).unsqueeze(0)
    else:
        x = np.asarray(X[-1], dtype=np.float32).reshape(-1)
        x_norm = ((x - runtime["x_mean"]) / runtime["x_std"]).astype(np.float32)
        tensor_in = torch.from_numpy(x_norm).unsqueeze(0)
    with torch.no_grad():
        logits = runtime["model"](tensor_in).cpu().numpy()
    prob = _softmax_np(logits)[0].astype(np.float32)
    risk = float(prob[1]) if runtime.get("is_binary_horizon") else float(np.sum(prob * runtime["risk_weights"]))
    return risk, prob.tolist(), "ok"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--state-model", default="")
    # Kept for launcher/API compatibility; runtime files are packaged next to this worker.
    parser.add_argument("--repo-root", required=True)
    args = parser.parse_args()

    try:
        runtime = _load_runtime(os.path.abspath(args.model), os.path.abspath(args.state_model) if args.state_model else "")
    except Exception as exc:
        _json_write({"ok": False, "error": str(exc)})
        return 1

    _json_write(
        {
            "ok": True,
            "cmd": "ready",
            "warmup": runtime["warmup"],
            "bins": runtime["bins"],
        }
    )
    for line in sys.stdin:
        try:
            req = json.loads(line)
            cmd = req.get("cmd")
            if cmd == "shutdown":
                break
            if cmd != "infer":
                _json_write({"ok": False, "error": f"unknown command: {cmd}"})
                continue

            data = np.load(req.get("path"))
            em_hist = np.asarray(data["em"], dtype=np.float64).tolist() if "em" in data else None
            risk, prob, status = _infer(np.asarray(data["vis"], dtype=np.float32), runtime, em_hist)
            _json_write(
                {"ok": True, "risk": risk, "probabilities": prob, "status": status}
            )
        except Exception as exc:
            _json_write({"ok": False, "error": str(exc)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
