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


def _load_runtime(model_path: str) -> dict:
    worker_dir = os.path.dirname(__file__)
    if worker_dir not in sys.path:
        sys.path.insert(0, worker_dir)

    from runtime_vis_features import frame_features
    from runtime_imminence_model import engineer_feature_table, make_model

    checkpoint = torch.load(model_path, map_location="cpu", weights_only=False)
    bins = [float(x) for x in checkpoint["bins"]]
    n_cls = len(bins) + 1
    args = checkpoint.get("args", {})
    feature_names = list(checkpoint["feature_names"])

    net = make_model(
        len(feature_names),
        n_cls,
        str(args.get("model", "mlp")),
        int(args.get("hidden", 256)),
        float(args.get("dropout", 0.2)),
    ).to(torch.device("cpu"))
    net.load_state_dict(checkpoint["state_dict"])
    net.eval()

    return {
        "model": net,
        "frame_features": frame_features,
        "engineer_feature_table": engineer_feature_table,
        "warmup": int(args.get("warmup", 10)),
        "feature_mode": str(args.get("feature_mode", "all")),
        "feature_names": feature_names,
        "x_mean": np.asarray(checkpoint["x_mean"], dtype=np.float32).reshape(-1),
        "x_std": np.asarray(checkpoint["x_std"], dtype=np.float32).reshape(-1),
        "bins": bins,
        "risk_weights": np.asarray(
            checkpoint.get("risk_weights", [1.0, 0.7, 0.4, 0.0][:n_cls]),
            dtype=np.float32,
        ),
    }


def _infer(vis_history: np.ndarray, runtime: dict) -> tuple[float | None, list[float] | None, str]:
    if len(vis_history) <= runtime["warmup"]:
        return None, None, f"warmup {len(vis_history)}/{runtime['warmup'] + 1}"

    feats_list = []
    prev = None
    re_idx = list(range(5))
    im_idx = list(range(5, 10))
    for vis in vis_history:
        feats_list.append(runtime["frame_features"](vis, prev, re_idx, im_idx, [], []))
        prev = vis

    X, names, _ = runtime["engineer_feature_table"](
        feats_list,
        warmup=runtime["warmup"],
        feature_mode=runtime["feature_mode"],
    )
    if X.size == 0:
        return None, None, "empty feature table"
    if names != runtime["feature_names"]:
        return None, None, (
            f"feature mismatch generated={len(names)} "
            f"expected={len(runtime['feature_names'])}"
        )

    x = np.asarray(X[-1], dtype=np.float32).reshape(-1)
    x_norm = ((x - runtime["x_mean"]) / runtime["x_std"]).astype(np.float32)
    with torch.no_grad():
        logits = runtime["model"](torch.from_numpy(x_norm).unsqueeze(0)).cpu().numpy()
    prob = _softmax_np(logits)[0].astype(np.float32)
    risk = float(np.sum(prob * runtime["risk_weights"]))
    return risk, prob.tolist(), "ok"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    # Kept for launcher/API compatibility; runtime files are packaged next to this worker.
    parser.add_argument("--repo-root", required=True)
    args = parser.parse_args()

    try:
        runtime = _load_runtime(os.path.abspath(args.model))
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
            risk, prob, status = _infer(np.asarray(data["vis"], dtype=np.float32), runtime)
            _json_write(
                {"ok": True, "risk": risk, "probabilities": prob, "status": status}
            )
        except Exception as exc:
            _json_write({"ok": False, "error": str(exc)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
