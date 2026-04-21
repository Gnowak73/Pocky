import argparse
import json
import os
import sys

import numpy as np
import torch


def _json_write(payload):
    sys.stdout.write(json.dumps(payload, allow_nan=False) + "\n")
    sys.stdout.flush()


def _softmax_np(logits):
    z = logits - np.max(logits, axis=1, keepdims=True)
    ez = np.exp(z)
    return ez / np.sum(ez, axis=1, keepdims=True)


def _load_runtime(model_path, repo_root):
    ml_fft_dir = os.path.join(repo_root, "ML_FFT")
    if ml_fft_dir not in sys.path:
        sys.path.insert(0, ml_fft_dir)

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
        return None, None
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
        return None, None
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
    return risk, prob.tolist()


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
            risk, prob = _infer(np.asarray(data["vis"], dtype=np.float32), runtime)
            _json_write({"ok": True, "risk": risk, "probabilities": prob})
        except Exception as exc:
            _json_write({"ok": False, "error": str(exc)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
