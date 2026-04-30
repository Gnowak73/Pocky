"""Runtime model helpers for WAFFLE imminence inference.

This is the minimal subset of the training modules required to reconstruct the
saved PyTorch model and engineer runtime inputs for both the legacy multiclass
MLP checkpoints and the newer binary GRU checkpoints.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np
import torch
import torch.nn as nn


def engineer_feature_table(
    feats_list: List[Dict[str, float]],
    warmup: int,
    feature_mode: str,
    lookback: int = 10,
) -> Tuple[np.ndarray, List[str], np.ndarray]:
    if not feats_list:
        return np.zeros((0, 0), dtype=np.float32), [], np.zeros((0,), dtype=np.int64)
    keys = sorted(feats_list[0].keys())
    F = np.stack([[float(f[k]) for k in keys] for f in feats_list], axis=0).astype(np.float64)
    T, _ = F.shape
    rows: List[np.ndarray] = []
    idx: List[int] = []
    names: List[str] = []
    for k in keys:
        names.append(k)
    if feature_mode == "raw":
        for i in range(T):
            if i < max(1, warmup):
                continue
            rows.append(F[i].astype(np.float32))
            idx.append(i)
        if not rows:
            return np.empty((0, len(names)), dtype=np.float32), names, np.asarray(idx, dtype=np.int64)
        return np.stack(rows).astype(np.float32), names, np.asarray(idx, dtype=np.int64)

    lookback = max(6, int(lookback))
    derived_suffixes = ["d1", "d3", "d5", "slope3", "slope5", "z5", "z10"]
    if lookback not in (5, 10):
        derived_suffixes.extend([f"d{lookback}", f"slope{lookback}", f"z{lookback}"])
    for suffix in derived_suffixes:
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
        wL = F[max(0, i - (lookback - 1)) : i + 1]
        prev1 = F[i - 1]
        prev3_mean = np.mean(w3[:-1], axis=0) if len(w3) > 1 else prev1
        prev5_mean = np.mean(w5[:-1], axis=0) if len(w5) > 1 else prev1
        d1 = cur - prev1
        d3 = cur - prev3_mean
        d5 = cur - prev5_mean
        slope3 = (cur - w3[0]) / max(len(w3) - 1, 1)
        slope5 = (cur - w5[0]) / max(len(w5) - 1, 1)
        mu5 = np.mean(w5, axis=0)
        sd5 = np.std(w5, axis=0) + 1e-8
        z5 = (cur - mu5) / sd5
        mu10 = np.mean(w10, axis=0)
        sd10 = np.std(w10, axis=0) + 1e-8
        z10 = (cur - mu10) / sd10
        parts = [cur, d1, d3, d5, slope3, slope5, z5, z10]
        if lookback not in (5, 10):
            prevL_mean = np.mean(wL[:-1], axis=0) if len(wL) > 1 else prev1
            dL = cur - prevL_mean
            slopeL = (cur - wL[0]) / max(len(wL) - 1, 1)
            muL = np.mean(wL, axis=0)
            sdL = np.std(wL, axis=0) + 1e-8
            zL = (cur - muL) / sdL
            parts.extend([dL, slopeL, zL])
        x = np.concatenate(parts, axis=0)
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


class GRUBinary(nn.Module):
    def __init__(self, in_dim: int, hidden: int, out_dim: int, layers: int, dropout: float) -> None:
        super().__init__()
        gru_dropout = dropout if layers > 1 else 0.0
        self.gru = nn.GRU(in_dim, hidden, num_layers=layers, batch_first=True, dropout=gru_dropout)
        self.drop = nn.Dropout(dropout)
        self.out = nn.Linear(hidden, out_dim)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        _, h = self.gru(x)
        z = self.drop(h[-1])
        return self.out(z)


def make_model(
    in_dim: int,
    out_dim: int,
    model_type: str,
    hidden: int,
    dropout: float,
    layers: int = 1,
) -> nn.Module:
    if model_type == "linear":
        return nn.Linear(in_dim, out_dim)
    if model_type == "gru":
        return GRUBinary(in_dim, hidden, out_dim, layers, dropout)
    return MLP(in_dim, out_dim, hidden, dropout)


def softmax_np(x: np.ndarray) -> np.ndarray:
    z = x - np.max(x, axis=1, keepdims=True)
    e = np.exp(z)
    return e / np.maximum(e.sum(axis=1, keepdims=True), 1e-12)


__all__ = ["engineer_feature_table", "make_model", "softmax_np"]
