#!/usr/bin/env python3
"""Event-sequence CNN+GRU early-warning model on visibility windows."""

from __future__ import annotations

import argparse
import math
import random
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset


def parse_args() -> argparse.Namespace:
    base = Path("/Users/gabe/Github/Pocky")
    p = argparse.ArgumentParser(
        description="Train event-sequence CNN+GRU on vis_cache windows.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--cache", default=str(base / "ML_FFT" / "vis_cache"), help="vis_cache folder.")
    p.add_argument("--index", default=str(base / "ML_FFT" / "vis_index.npz"), help="Index .npz file.")
    p.add_argument("--device", default="mps", help="Device (cpu/cuda/mps).")
    p.add_argument("--epochs", type=int, default=10, help="Number of training epochs.")
    p.add_argument("--batch-size", type=int, default=4, help="Events per batch.")
    p.add_argument("--lr", type=float, default=3e-4, help="Learning rate.")
    p.add_argument("--num-workers", type=int, default=0, help="DataLoader workers.")
    p.add_argument("--pos-weight", type=float, default=0.0, help="Override pos_weight.")
    p.add_argument("--auto-pos-weight", action="store_true", help="Use neg/pos ratio for pos_weight.")
    p.add_argument("--split", default="0.7,0.2,0.1", help="Train/val/test split by event.")
    p.add_argument("--threshold", type=float, default=0.5, help="Decision threshold for metrics.")
    return p.parse_args()


def load_index(path: Path):
    idx = np.load(path, allow_pickle=False)
    return idx["event"], idx["start"], idx["end"], idx["label"]


def split_events(events: List[str], split: str):
    parts = [float(p) for p in split.split(",")]
    if len(parts) != 3:
        raise ValueError("split must be train,val,test")
    s = sum(parts)
    parts = [p / s for p in parts]
    n = len(events)
    events = list(events)
    random.shuffle(events)
    n_train = int(n * parts[0])
    n_val = int(n * parts[1])
    return events[:n_train], events[n_train : n_train + n_val], events[n_train + n_val :]


class EventSequenceDataset(Dataset):
    def __init__(
        self,
        cache_dir: Path,
        event_windows: Dict[str, List[Tuple[int, int, int]]],
        event_list: List[str],
    ):
        self.cache_dir = cache_dir
        self.event_windows = event_windows
        self.event_list = event_list

    def __len__(self) -> int:
        return len(self.event_list)

    def __getitem__(self, i: int):
        event = self.event_list[i]
        windows = self.event_windows[event]
        data = np.load(self.cache_dir / f"{event}.npz", allow_pickle=False)["vis"]

        frames = []
        labels = []
        for start, end, y in windows:
            frames.append(data[start : end + 1])  # (T, C, Nv, Nu)
            labels.append(y)
        x = torch.from_numpy(np.asarray(frames, dtype=np.float32))
        y = torch.from_numpy(np.asarray(labels, dtype=np.float32))
        return x, y, event


def collate_events(batch):
    # batch: list of (x, y, event)
    max_w = max(item[0].shape[0] for item in batch)
    t, c, h, w = batch[0][0].shape[1:]
    xs = torch.zeros(len(batch), max_w, t, c, h, w, dtype=torch.float32)
    ys = torch.zeros(len(batch), max_w, dtype=torch.float32)
    mask = torch.zeros(len(batch), max_w, dtype=torch.bool)
    events = []
    for i, (x, y, event) in enumerate(batch):
        n = x.shape[0]
        xs[i, :n] = x
        ys[i, :n] = y
        mask[i, :n] = True
        events.append(event)
    return xs, ys, mask, events


class WindowEncoder(nn.Module):
    def __init__(self, in_ch: int):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(in_ch, 32, 3, padding=1),
            nn.ReLU(),
            nn.MaxPool2d(2),
            nn.Conv2d(32, 64, 3, padding=1),
            nn.ReLU(),
            nn.MaxPool2d(2),
            nn.Conv2d(64, 128, 3, padding=1),
            nn.ReLU(),
            nn.AdaptiveAvgPool2d(1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.conv(x).flatten(1)


class EarlyWarnModel(nn.Module):
    def __init__(self, in_ch: int, hidden: int = 128, window_hidden: int = 128):
        super().__init__()
        self.enc = WindowEncoder(in_ch)
        self.window_gru = nn.GRU(128, window_hidden, batch_first=True)
        self.seq_gru = nn.GRU(window_hidden, hidden, batch_first=True)
        self.fc = nn.Linear(hidden, 1)

    def forward(self, x: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
        # x: (B, W, T, C, H, W)
        b, w, t, c, h, w2 = x.shape
        x = x.view(b * w * t, c, h, w2)
        feats = self.enc(x).view(b * w, t, -1)
        win_out, _ = self.window_gru(feats)  # (B*W, T, D)
        win_emb = win_out[:, -1].view(b, w, -1)
        seq_out, _ = self.seq_gru(win_emb)
        logits = self.fc(seq_out).squeeze(-1)  # (B, W)
        logits = logits.masked_fill(~mask, 0.0)
        return logits


def metrics_from_logits(logits: np.ndarray, labels: np.ndarray, thr: float):
    probs = 1 / (1 + np.exp(-logits))
    preds = (probs >= thr).astype(int)
    tp = int(((preds == 1) & (labels == 1)).sum())
    fp = int(((preds == 1) & (labels == 0)).sum())
    tn = int(((preds == 0) & (labels == 0)).sum())
    fn = int(((preds == 0) & (labels == 1)).sum())
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) else 0.0
    acc = (tp + tn) / max(tp + tn + fp + fn, 1)
    return acc, prec, rec, f1, tp, fp, tn, fn


def main() -> int:
    args = parse_args()
    cache_dir = Path(args.cache)
    events, starts, ends, labels = load_index(Path(args.index))

    event_windows: Dict[str, List[Tuple[int, int, int]]] = defaultdict(list)
    for ev, s, e, y in zip(events, starts, ends, labels):
        event_windows[str(ev)].append((int(s), int(e), int(y)))
    # sort windows by end time per event
    for ev in event_windows:
        event_windows[ev].sort(key=lambda x: x[1])

    event_list = sorted(event_windows.keys())
    if not event_list:
        print("No events in index.")
        return 1

    train_events, val_events, test_events = split_events(event_list, args.split)
    train_ds = EventSequenceDataset(cache_dir, event_windows, train_events)
    val_ds = EventSequenceDataset(cache_dir, event_windows, val_events)
    test_ds = EventSequenceDataset(cache_dir, event_windows, test_events)

    train_loader = DataLoader(
        train_ds,
        batch_size=args.batch_size,
        shuffle=True,
        num_workers=args.num_workers,
        collate_fn=collate_events,
    )
    val_loader = DataLoader(val_ds, batch_size=args.batch_size, shuffle=False, num_workers=args.num_workers, collate_fn=collate_events)
    test_loader = DataLoader(test_ds, batch_size=args.batch_size, shuffle=False, num_workers=args.num_workers, collate_fn=collate_events)

    # infer channels
    sample_x, _, _ = train_ds[0]
    in_ch = sample_x.shape[2]

    # class weighting
    y_train = np.concatenate([np.array([y for _, _, y in event_windows[e]]) for e in train_events])
    pos = float(np.sum(y_train))
    neg = float(len(y_train) - pos)
    if args.pos_weight > 0:
        pos_weight = args.pos_weight
    elif args.auto_pos_weight:
        pos_weight = neg / max(pos, 1.0)
    else:
        pos_weight = 1.0

    device = torch.device(args.device)
    model = EarlyWarnModel(in_ch).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr)
    loss_fn = nn.BCEWithLogitsLoss(reduction="none", pos_weight=torch.tensor([pos_weight], device=device))

    print(f"Counts: train ones={int(pos)} zeros={int(neg)} | val events={len(val_events)} test events={len(test_events)}")
    print(f"Device: {device}")
    if args.pos_weight > 0:
        print(f"Using pos_weight={pos_weight:.3f} (override)")
    elif args.auto_pos_weight:
        print(f"Using pos_weight={pos_weight:.3f} (neg/pos)")
    else:
        print("Using pos_weight=1.0 (no class weighting)")

    for epoch in range(1, args.epochs + 1):
        model.train()
        total = 0.0
        for x, yb, mask, _ in train_loader:
            x = x.to(device)
            yb = yb.to(device)
            mask = mask.to(device)
            opt.zero_grad(set_to_none=True)
            logits = model(x, mask)
            loss = loss_fn(logits, yb)
            loss = (loss * mask.float()).sum() / mask.float().sum().clamp_min(1.0)
            loss.backward()
            opt.step()
            total += float(loss.item())

        # validation
        model.eval()
        v_logits = []
        v_labels = []
        v_masks = []
        with torch.no_grad():
            for x, yb, mask, _ in val_loader:
                logits = model(x.to(device), mask.to(device)).cpu().numpy()
                v_logits.append(logits)
                v_labels.append(yb.numpy())
                v_masks.append(mask.numpy())
        v_logits = np.concatenate([l[m] for l, m in zip(v_logits, v_masks)])
        v_labels = np.concatenate([y[m] for y, m in zip(v_labels, v_masks)])
        acc, prec, rec, f1, *_ = metrics_from_logits(v_logits, v_labels, args.threshold)
        print(f"Epoch {epoch:02d} loss={total/ max(len(train_loader),1):.4f} val_acc={acc:.3f} val_f1={f1:.3f}")

    # test
    model.eval()
    t_logits = []
    t_labels = []
    t_masks = []
    with torch.no_grad():
        for x, yb, mask, _ in test_loader:
            logits = model(x.to(device), mask.to(device)).cpu().numpy()
            t_logits.append(logits)
            t_labels.append(yb.numpy())
            t_masks.append(mask.numpy())
    t_logits = np.concatenate([l[m] for l, m in zip(t_logits, t_masks)])
    t_labels = np.concatenate([y[m] for y, m in zip(t_labels, t_masks)])
    acc, prec, rec, f1, tp, fp, tn, fn = metrics_from_logits(t_logits, t_labels, args.threshold)
    print(f"Test metrics acc={acc:.3f} prec={prec:.3f} rec={rec:.3f} f1={f1:.3f}")
    print(f"Confusion matrix (test): TP={tp} FP={fp} TN={tn} FN={fn}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
