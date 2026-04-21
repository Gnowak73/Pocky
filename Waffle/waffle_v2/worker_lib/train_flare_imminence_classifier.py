#!/usr/bin/env python3
"""Train a multi-class imminence model for flare onset lead time."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

from scan_vis_features import frame_features, goes_to_float, load_flare_info, parse_times


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Multi-class flare imminence classifier.")
    p.add_argument("--cache", default="ML_FFT/vis_cache_shifted_unnorm")
    p.add_argument("--flare-cache", default="flare_cache.tsv")
    p.add_argument("--min-class", default="C1.0")
    p.add_argument("--max-class", default="")
    p.add_argument(
        "--label-source",
        choices=("goes", "em-proxy", "em-peak"),
        default="goes",
        help="Use official GOES onset, WAFFLE EM-proxy threshold crossing, or WAFFLE EM-proxy peak labels.",
    )
    p.add_argument("--em-threshold-class", default="C6.0", help="WAFFLE EM-proxy threshold class used when --label-source em-proxy.")
    p.add_argument("--em-min-class", default="", help="Minimum WAFFLE EM-proxy peak class used when --label-source em-peak. Defaults to --min-class.")
    p.add_argument("--bins", default="5,10,20", help="Minute bin edges for imminence classes.")
    p.add_argument("--pre-min", type=float, default=0.0)
    p.add_argument("--warmup", type=int, default=10)
    p.add_argument("--feature-mode", choices=("raw", "all"), default="all")
    p.add_argument("--aux-csv", default="", help="Optional CSV of extra per-event per-timestamp features (must include event,timestamp columns).")
    p.add_argument("--aux-prefix", default="aux", help="Prefix applied to extra feature column names loaded from --aux-csv.")
    p.add_argument("--log-scale", action="store_true")
    p.add_argument("--model", choices=("linear", "mlp"), default="mlp")
    p.add_argument("--hidden", type=int, default=256)
    p.add_argument("--dropout", type=float, default=0.2)
    p.add_argument("--epochs", type=int, default=80)
    p.add_argument("--patience", type=int, default=12)
    p.add_argument("--batch-size", type=int, default=256)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--save", default="", help="Checkpoint path.")
    p.add_argument("--load", default="", help="Load checkpoint and only run event printing.")
    p.add_argument("--print-event", default="")
    p.add_argument("--infer-event", default="", help="Inference-only event id (no flare label required).")
    p.add_argument("--infer-file", default="", help="Inference-only path to a single .npz file (no flare label required).")
    p.add_argument("--print-n", type=int, default=50, help="Rows to print for --print-event (0=all).")
    p.add_argument("--alert-threshold", type=float, default=0.50, help="Risk threshold for event-level alert metric.")
    p.add_argument("--risk-weights", default="1.0,0.7,0.4,0.0", help="Class weights for risk score.")
    p.add_argument("--max-events", type=int, default=0)
    p.add_argument("--exclude-events", default="", help="Comma-separated event ids to exclude from train/val/test.")
    p.add_argument("--exclude-file", default="", help="Text file with one event id per line to exclude.")
    return p.parse_args()


def maybe_log(feats: Dict[str, float]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for k, v in feats.items():
        out[k] = float(np.log1p(v)) if v >= 0 else float(v)
    return out


def parse_aux_timestamp(value: str) -> dt.datetime:
    s = value.strip().replace("Z", "")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H%M%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return dt.datetime.strptime(s, fmt)
        except ValueError:
            pass
    return dt.datetime.fromisoformat(s)


def load_aux_features(path: Path, prefix: str) -> Tuple[Dict[Tuple[str, dt.datetime], Dict[str, float]], List[str]]:
    if not path.exists():
        raise SystemExit(f"Aux feature CSV not found: {path}")
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None or "event" not in reader.fieldnames or "timestamp" not in reader.fieldnames:
            raise SystemExit("--aux-csv must include event and timestamp columns.")
        skip = {"event", "timestamp", "folder", "complete"}
        base_cols = [c for c in reader.fieldnames if c not in skip]
        aux_cols = [f"{prefix}_{c}" for c in base_cols]
        table: Dict[Tuple[str, dt.datetime], Dict[str, float]] = {}
        for row in reader:
            ev = row.get("event", "").strip()
            ts = row.get("timestamp", "").strip()
            if not ev or not ts:
                continue
            try:
                when = parse_aux_timestamp(ts)
            except ValueError:
                continue
            vals: Dict[str, float] = {}
            ok = True
            for src, dst in zip(base_cols, aux_cols):
                raw = row.get(src, "").strip()
                if not raw:
                    ok = False
                    break
                try:
                    vals[dst] = float(raw)
                except ValueError:
                    ok = False
                    break
            if ok:
                table[(ev, when.replace(microsecond=0))] = vals
    return table, aux_cols


def augment_with_aux_features(
    event_id: str,
    times: List[dt.datetime],
    feats_list: List[Dict[str, float]],
    aux_table: Dict[Tuple[str, dt.datetime], Dict[str, float]],
    aux_cols: List[str],
) -> List[Dict[str, float]]:
    if not feats_list or not aux_cols:
        return feats_list
    out: List[Dict[str, float]] = []
    for t, feats in zip(times, feats_list):
        row = dict(feats)
        vals = aux_table.get((event_id, t.replace(microsecond=0)))
        for col in aux_cols:
            row[col] = 0.0 if vals is None else float(vals.get(col, 0.0))
            row[f"{col}_present"] = 0.0 if vals is None else 1.0
        out.append(row)
    return out


def split_events(events: List[str], seed: int) -> Tuple[List[str], List[str], List[str]]:
    rng = np.random.default_rng(seed)
    evs = events[:]
    rng.shuffle(evs)
    n = len(evs)
    ntr = int(0.7 * n)
    nva = int(0.15 * n)
    return evs[:ntr], evs[ntr : ntr + nva], evs[ntr + nva :]


def load_exclude_set(args: argparse.Namespace) -> set[str]:
    out: set[str] = set()
    if args.exclude_events.strip():
        out.update([x.strip() for x in args.exclude_events.split(",") if x.strip()])
    if args.exclude_file.strip():
        p = Path(args.exclude_file)
        if not p.exists():
            raise SystemExit(f"Exclude file not found: {p}")
        for line in p.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s and not s.startswith("#"):
                out.add(s)
    return out


def load_flare_windows(path: Path, min_class: str) -> Dict[str, Tuple[dt.datetime, dt.datetime | None]]:
    out: Dict[str, Tuple[dt.datetime, dt.datetime | None]] = {}
    if not path.exists():
        return out
    min_val = goes_to_float(min_class)
    with path.open("r", encoding="utf-8") as f:
        header = f.readline().strip().split("\t")
        if "flare_class" not in header or "start" not in header:
            return out
        i_cls = header.index("flare_class")
        i_start = header.index("start")
        i_end = header.index("end") if "end" in header else -1
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) <= max(i_cls, i_start):
                continue
            cls = parts[i_cls].strip()
            if goes_to_float(cls) < min_val:
                continue
            s = parts[i_start].strip()
            if not s:
                continue
            try:
                t0 = dt.datetime.fromisoformat(s.replace("Z", ""))
            except ValueError:
                continue
            t1: dt.datetime | None = None
            if i_end >= 0 and len(parts) > i_end:
                e = parts[i_end].strip()
                if e:
                    try:
                        t1 = dt.datetime.fromisoformat(e.replace("Z", ""))
                    except ValueError:
                        t1 = None
            ev = f"{cls}_{t0:%Y%m%d_%H%M%S}"
            out[ev] = (t0, t1)
    return out


def proxy_class_to_em(value: str) -> float:
    text = value.strip().upper()
    if len(text) < 2:
        raise ValueError(f"Invalid EM proxy class: {value}")
    letter = text[0]
    mag = float(text[1:])
    exponent = {"A": 46, "B": 47, "C": 48, "M": 49, "X": 50}.get(letter)
    if exponent is None:
        raise ValueError(f"Invalid EM proxy class: {value}")
    return mag * (10.0 ** exponent)


def load_em_proxy_onsets(cache_dir: Path, threshold: float) -> Dict[str, dt.datetime]:
    out: Dict[str, dt.datetime] = {}
    for fp in sorted(cache_dir.glob("*.npz")):
        try:
            with np.load(fp) as d:
                if "em_total" not in d:
                    continue
                em_total = np.asarray(d["em_total"], dtype=np.float64)
                times = parse_times(d["times"])
        except Exception:
            continue
        if len(em_total) != len(times):
            continue
        hit = np.where(np.isfinite(em_total) & (em_total >= float(threshold)))[0]
        if len(hit) == 0:
            continue
        out[fp.stem] = times[int(hit[0])]
    return out


def load_em_peak_times(cache_dir: Path, min_peak: float) -> Dict[str, dt.datetime]:
    out: Dict[str, dt.datetime] = {}
    for fp in sorted(cache_dir.glob("*.npz")):
        try:
            with np.load(fp) as d:
                if "em_total" not in d:
                    continue
                em_total = np.asarray(d["em_total"], dtype=np.float64)
                times = parse_times(d["times"])
        except Exception:
            continue
        if len(em_total) != len(times):
            continue
        finite = np.where(np.isfinite(em_total))[0]
        if len(finite) == 0:
            continue
        peak_idx = int(finite[int(np.argmax(em_total[finite]))])
        peak_val = float(em_total[peak_idx])
        if peak_val < float(min_peak):
            continue
        out[fp.stem] = times[peak_idx]
    return out


def event_rows(
    fp: Path,
    flare_start: dt.datetime,
    pre_min: float,
    log_scale: bool,
) -> Tuple[List[dt.datetime], List[Dict[str, float]]]:
    with np.load(fp) as d:
        vis = d["vis"]
        times = parse_times(d["times"])
        raw = d["channels"] if "channels" in d else None
        channels = [c.decode() if isinstance(c, (bytes, np.bytes_)) else str(c) for c in raw] if raw is not None else []
    re_idx = [i for i, c in enumerate(channels) if c.endswith("_re")]
    im_idx = [i for i, c in enumerate(channels) if c.endswith("_im")]
    mag_idx = [i for i, c in enumerate(channels) if c.endswith("_mag")]
    ph_idx = [i for i, c in enumerate(channels) if c.endswith("_ph")]

    prev = None
    out_t: List[dt.datetime] = []
    out_f: List[Dict[str, float]] = []
    for i, t in enumerate(times):
        dtm = (flare_start - t).total_seconds() / 60.0
        if dtm <= 0:
            continue
        if pre_min > 0 and dtm > pre_min:
            prev = vis[i]
            continue
        feats = frame_features(vis[i], prev, re_idx, im_idx, mag_idx, ph_idx)
        if log_scale:
            feats = maybe_log(feats)
        out_t.append(t)
        out_f.append(feats)
        prev = vis[i]
    return out_t, out_f


def event_rows_unlabeled(
    fp: Path,
    log_scale: bool,
) -> Tuple[List[dt.datetime], List[Dict[str, float]]]:
    with np.load(fp) as d:
        vis = d["vis"]
        times = parse_times(d["times"])
        raw = d["channels"] if "channels" in d else None
        channels = [c.decode() if isinstance(c, (bytes, np.bytes_)) else str(c) for c in raw] if raw is not None else []
    re_idx = [i for i, c in enumerate(channels) if c.endswith("_re")]
    im_idx = [i for i, c in enumerate(channels) if c.endswith("_im")]
    mag_idx = [i for i, c in enumerate(channels) if c.endswith("_mag")]
    ph_idx = [i for i, c in enumerate(channels) if c.endswith("_ph")]
    prev = None
    out_t: List[dt.datetime] = []
    out_f: List[Dict[str, float]] = []
    for i, t in enumerate(times):
        feats = frame_features(vis[i], prev, re_idx, im_idx, mag_idx, ph_idx)
        if log_scale:
            feats = maybe_log(feats)
        out_t.append(t)
        out_f.append(feats)
        prev = vis[i]
    return out_t, out_f


def engineer_feature_table(
    feats_list: List[Dict[str, float]],
    warmup: int,
    feature_mode: str,
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
        mu5 = np.mean(w5, axis=0)
        sd5 = np.std(w5, axis=0) + 1e-8
        z5 = (cur - mu5) / sd5
        mu10 = np.mean(w10, axis=0)
        sd10 = np.std(w10, axis=0) + 1e-8
        z10 = (cur - mu10) / sd10
        x = np.concatenate([cur, d1, d3, d5, slope3, slope5, z5, z10], axis=0)
        if valid_pairs:
            extras = [cur[key_to_idx[a]] * cur[key_to_idx[b]] for a, b in valid_pairs]
            x = np.concatenate([x, np.asarray(extras, dtype=np.float64)], axis=0)
        rows.append(x.astype(np.float32))
        idx.append(i)
    if not rows:
        return np.empty((0, len(names)), dtype=np.float32), names, np.asarray(idx, dtype=np.int64)
    return np.stack(rows).astype(np.float32), names, np.asarray(idx, dtype=np.int64)


def minutes_to_label(mins: float, bins: List[float]) -> int:
    for i, b in enumerate(bins):
        if mins <= b:
            return i
    return len(bins)


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


def make_model(in_dim: int, out_dim: int, model_type: str, hidden: int, dropout: float) -> nn.Module:
    if model_type == "linear":
        return nn.Linear(in_dim, out_dim)
    return MLP(in_dim, out_dim, hidden, dropout)


def softmax_np(x: np.ndarray) -> np.ndarray:
    z = x - np.max(x, axis=1, keepdims=True)
    e = np.exp(z)
    return e / np.maximum(e.sum(axis=1, keepdims=True), 1e-12)


def macro_f1(y_true: np.ndarray, y_pred: np.ndarray, ncls: int) -> float:
    f1s: List[float] = []
    for c in range(ncls):
        tp = np.sum((y_true == c) & (y_pred == c))
        fp = np.sum((y_true != c) & (y_pred == c))
        fn = np.sum((y_true == c) & (y_pred != c))
        p = tp / max(tp + fp, 1)
        r = tp / max(tp + fn, 1)
        f1 = 0.0 if (p + r) <= 0 else (2 * p * r / (p + r))
        f1s.append(float(f1))
    return float(np.mean(f1s))


def gather_split(
    events: List[str],
    cache_dir: Path,
    flare_info: Dict[str, dt.datetime],
    pre_min: float,
    warmup: int,
    log_scale: bool,
    feature_mode: str,
    bins: List[float],
    feat_ref: List[str],
    aux_table: Dict[Tuple[str, dt.datetime], Dict[str, float]],
    aux_cols: List[str],
) -> Tuple[List[np.ndarray], List[int], List[int], List[float], List[dt.datetime], List[str]]:
    X: List[np.ndarray] = []
    y: List[int] = []
    g: List[int] = []
    mins_all: List[float] = []
    issued_all: List[dt.datetime] = []
    ev_all: List[str] = []
    for gi, ev in enumerate(events):
        fp = cache_dir / f"{ev}.npz"
        if not fp.exists() or ev not in flare_info:
            continue
        times_evt, feats_evt = event_rows(fp, flare_info[ev], pre_min, log_scale)
        if not feats_evt:
            continue
        feats_evt = augment_with_aux_features(ev, times_evt, feats_evt, aux_table, aux_cols)
        X_evt, feat_names, row_idx = engineer_feature_table(feats_evt, warmup, feature_mode)
        if X_evt.size == 0:
            continue
        if not feat_ref:
            feat_ref[:] = feat_names
        if feat_names != feat_ref:
            raise SystemExit("Feature schema mismatch across events.")
        for k, i in enumerate(row_idx):
            mins = (flare_info[ev] - times_evt[int(i)]).total_seconds() / 60.0
            X.append(X_evt[k])
            y.append(minutes_to_label(float(mins), bins))
            g.append(gi)
            mins_all.append(float(mins))
            issued_all.append(times_evt[int(i)])
            ev_all.append(ev)
    return X, y, g, mins_all, issued_all, ev_all


def event_alert_summary(
    events: List[str],
    ev_rows: List[str],
    mins: np.ndarray,
    risk: np.ndarray,
    threshold: float,
) -> Tuple[float, float, float]:
    leads: List[float] = []
    early_false: List[float] = []
    for ev in events:
        idx = np.where(np.asarray(ev_rows) == ev)[0]
        if len(idx) == 0:
            continue
        r = risk[idx]
        m = mins[idx]
        hit = np.where(r >= threshold)[0]
        if len(hit) == 0:
            continue
        lead = float(m[int(hit[0])])
        leads.append(lead)
        early_false.append(1.0 if lead > 20.0 else 0.0)
    if not leads:
        return 0.0, 0.0, 0.0
    return float(len(leads) / max(len(events), 1)), float(np.median(leads)), float(np.mean(early_false))


def main() -> None:
    args = parse_args()
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)

    bins = [float(x) for x in args.bins.split(",") if x.strip()]
    bins = sorted(bins)
    n_cls = len(bins) + 1
    risk_weights = np.asarray([float(x) for x in args.risk_weights.split(",") if x.strip()], dtype=np.float32)
    if len(risk_weights) != n_cls:
        raise SystemExit(f"--risk-weights must provide {n_cls} values for bins {bins}.")

    cache_dir = Path(args.cache)
    if args.label_source == "em-proxy":
        em_threshold = proxy_class_to_em(args.em_threshold_class)
        flare_info = load_em_proxy_onsets(cache_dir, em_threshold)
        flare_windows = {ev: (t0, None) for ev, t0 in flare_info.items()}
        print(
            f"Using WAFFLE EM-proxy labels: {args.em_threshold_class} -> {em_threshold:.6e}; "
            f"{len(flare_info)} events cross threshold."
        )
    elif args.label_source == "em-peak":
        em_min_class = args.em_min_class.strip() or args.min_class
        em_min_peak = proxy_class_to_em(em_min_class)
        flare_info = load_em_peak_times(cache_dir, em_min_peak)
        flare_windows = {ev: (t0, None) for ev, t0 in flare_info.items()}
        print(
            f"Using WAFFLE EM-peak labels: min peak {em_min_class} -> {em_min_peak:.6e}; "
            f"{len(flare_info)} events retained."
        )
    else:
        flare_info = load_flare_info(Path(args.flare_cache), args.min_class)
        flare_windows = load_flare_windows(Path(args.flare_cache), args.min_class)
    aux_table: Dict[Tuple[str, dt.datetime], Dict[str, float]] = {}
    aux_cols: List[str] = []
    if args.aux_csv.strip():
        aux_table, aux_cols = load_aux_features(Path(args.aux_csv), args.aux_prefix.strip() or "aux")
    max_val = goes_to_float(args.max_class) if args.max_class else None
    files = sorted(cache_dir.glob("*.npz"))
    if args.max_events > 0:
        files = files[: args.max_events]
    events = [fp.stem for fp in files if fp.stem in flare_info]
    if max_val is not None and args.label_source == "goes":
        events = [ev for ev in events if goes_to_float(ev.split("_", 1)[0]) <= max_val]
    exclude = load_exclude_set(args)
    if exclude:
        before = len(events)
        events = [ev for ev in events if ev not in exclude]
        print(f"Excluded events: {before - len(events)}")
    if len(events) < 8 and not (args.load and (args.infer_event or args.infer_file) and not args.print_event):
        raise SystemExit("Not enough events.")

    tr_e, va_e, te_e = split_events(events, args.seed)
    feat_ref: List[str] = []

    if args.load:
        ck = torch.load(args.load, map_location="cpu", weights_only=False)
        bins = [float(x) for x in ck["bins"]]
        n_cls = len(bins) + 1
        risk_weights = np.asarray(ck.get("risk_weights", [1.0, 0.7, 0.4, 0.0][:n_cls]), dtype=np.float32)
        feat_ref = list(ck["feature_names"])
        tr_e, va_e, te_e = split_events(events, int(ck["args"]["seed"]))
        args.feature_mode = str(ck["args"].get("feature_mode", args.feature_mode))
        args.warmup = int(ck["args"].get("warmup", args.warmup))
        args.log_scale = bool(ck["args"].get("log_scale", args.log_scale))
        args.model = str(ck["args"].get("model", args.model))
        args.hidden = int(ck["args"].get("hidden", args.hidden))
        args.dropout = float(ck["args"].get("dropout", args.dropout))

        if (args.infer_event or args.infer_file) and not args.print_event:
            if args.infer_file:
                fp = Path(args.infer_file)
                ev = fp.stem
            else:
                ev = args.infer_event
                fp = cache_dir / f"{ev}.npz"
            if not fp.exists():
                raise SystemExit(f"Event not found: {ev}")
            times_evt, feats_evt = event_rows_unlabeled(fp, args.log_scale)
            feats_evt = augment_with_aux_features(ev, times_evt, feats_evt, aux_table, aux_cols)
            X_evt, feat_evt, row_idx_evt = engineer_feature_table(feats_evt, args.warmup, args.feature_mode)
            if X_evt.size == 0:
                raise SystemExit(f"No usable rows for event: {ev}")
            if feat_evt != feat_ref:
                raise SystemExit(f"Feature schema mismatch for event: {ev}")
            xm = np.asarray(ck["x_mean"], dtype=np.float32)
            xs = np.asarray(ck["x_std"], dtype=np.float32)
            dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            net = make_model(X_evt.shape[1], n_cls, args.model, args.hidden, args.dropout).to(dev)
            net.load_state_dict(ck["state_dict"])
            net.eval()
            X_evt_n = ((X_evt - xm) / xs).astype(np.float32)
            with torch.no_grad():
                logits_evt = net(torch.from_numpy(X_evt_n).to(dev)).cpu().numpy()
            prob_evt = softmax_np(logits_evt)
            pred_evt = np.argmax(prob_evt, axis=1)
            n = len(row_idx_evt) if args.print_n <= 0 else min(args.print_n, len(row_idx_evt))
            print(f"\nEvent imminence inference: {ev}")
            if ev in flare_windows:
                s, e = flare_windows[ev]
                if e is not None:
                    print(f"flare_start={s.isoformat()} flare_end={e.isoformat()}")
                else:
                    print(f"flare_start={s.isoformat()} flare_end=NA")
            else:
                print("flare_start=NA flare_end=NA")
            for kk, i in enumerate(row_idx_evt[:n]):
                risk_evt = float(np.sum(prob_evt[kk] * risk_weights))
                parts = [f"p<= {b:g}m={float(prob_evt[kk, bi]):.3f}" for bi, b in enumerate(bins)]
                parts.append(f"p> {bins[-1]:g}m={float(prob_evt[kk, len(bins)]):.3f}")
                print(f"{times_evt[int(i)].isoformat()} risk={risk_evt:.4f} cls={int(pred_evt[kk])} {' '.join(parts)}")
            return

    Xtr_l, ytr_l, _, _, _, _ = gather_split(tr_e, cache_dir, flare_info, args.pre_min, args.warmup, args.log_scale, args.feature_mode, bins, feat_ref, aux_table, aux_cols)
    Xva_l, yva_l, _, _, _, _ = gather_split(va_e, cache_dir, flare_info, args.pre_min, args.warmup, args.log_scale, args.feature_mode, bins, feat_ref, aux_table, aux_cols)
    Xte_l, yte_l, _, mins_te_l, issued_te, ev_te = gather_split(te_e, cache_dir, flare_info, args.pre_min, args.warmup, args.log_scale, args.feature_mode, bins, feat_ref, aux_table, aux_cols)

    if not Xtr_l or not Xva_l or not Xte_l:
        raise SystemExit("Insufficient rows.")

    Xtr = np.stack(Xtr_l).astype(np.float32)
    ytr = np.asarray(ytr_l, dtype=np.int64)
    Xva = np.stack(Xva_l).astype(np.float32)
    yva = np.asarray(yva_l, dtype=np.int64)
    Xte = np.stack(Xte_l).astype(np.float32)
    yte = np.asarray(yte_l, dtype=np.int64)
    mins_te = np.asarray(mins_te_l, dtype=np.float32)

    xm = Xtr.mean(axis=0, keepdims=True)
    xs = Xtr.std(axis=0, keepdims=True) + 1e-8
    if args.load:
        xm = np.asarray(ck["x_mean"], dtype=np.float32)
        xs = np.asarray(ck["x_std"], dtype=np.float32)
    Xtrn = (Xtr - xm) / xs
    Xvan = (Xva - xm) / xs
    Xten = (Xte - xm) / xs

    dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    net = make_model(Xtrn.shape[1], n_cls, args.model, args.hidden, args.dropout).to(dev)

    if args.load:
        net.load_state_dict(ck["state_dict"])
    else:
        counts = np.bincount(ytr, minlength=n_cls).astype(np.float32)
        cls_w = (counts.sum() / np.maximum(counts, 1.0)).astype(np.float32)
        cls_w = cls_w / np.mean(cls_w)
        loss_fn = nn.CrossEntropyLoss(weight=torch.from_numpy(cls_w).to(dev))
        opt = torch.optim.AdamW(net.parameters(), lr=args.lr)
        dl_tr = DataLoader(TensorDataset(torch.from_numpy(Xtrn), torch.from_numpy(ytr)), batch_size=args.batch_size, shuffle=True)
        dl_va = DataLoader(TensorDataset(torch.from_numpy(Xvan), torch.from_numpy(yva)), batch_size=args.batch_size, shuffle=False)
        best = {"epoch": 0, "val_f1": -1.0, "state": None}
        bad = 0
        for ep in range(1, args.epochs + 1):
            net.train()
            tr_losses: List[float] = []
            for xb, yb in dl_tr:
                xb = xb.to(dev)
                yb = yb.to(dev)
                opt.zero_grad()
                logits = net(xb)
                loss = loss_fn(logits, yb)
                loss.backward()
                opt.step()
                tr_losses.append(float(loss.detach().cpu().item()))
            net.eval()
            va_logits: List[np.ndarray] = []
            va_y: List[np.ndarray] = []
            va_losses: List[float] = []
            with torch.no_grad():
                for xb, yb in dl_va:
                    logits = net(xb.to(dev))
                    va_losses.append(float(loss_fn(logits, yb.to(dev)).detach().cpu().item()))
                    va_logits.append(logits.cpu().numpy())
                    va_y.append(yb.numpy())
            va_prob = softmax_np(np.concatenate(va_logits, axis=0))
            va_pred = np.argmax(va_prob, axis=1)
            va_true = np.concatenate(va_y).astype(np.int64)
            va_f1 = macro_f1(va_true, va_pred, n_cls)
            if va_f1 > best["val_f1"]:
                best = {"epoch": ep, "val_f1": va_f1, "state": {k: v.cpu().clone() for k, v in net.state_dict().items()}}
                bad = 0
            else:
                bad += 1
            if ep == 1 or ep % 10 == 0 or ep == args.epochs:
                print(
                    f"epoch {ep:03d} train_loss={float(np.mean(tr_losses)):.4f} "
                    f"val_loss={float(np.mean(va_losses)):.4f} val_macro_f1={va_f1:.4f}"
                )
            if bad >= args.patience:
                print(f"early stop at epoch {ep} (best_epoch={best['epoch']})")
                break
        if best["state"] is not None:
            net.load_state_dict(best["state"])

    net.eval()
    with torch.no_grad():
        te_logits = net(torch.from_numpy(Xten).to(dev)).cpu().numpy()
    te_prob = softmax_np(te_logits)
    te_pred = np.argmax(te_prob, axis=1)
    acc = float(np.mean(te_pred == yte))
    f1m = macro_f1(yte, te_pred, n_cls)
    risk = (te_prob * risk_weights[None, :]).sum(axis=1)
    cov, med_lead, early_false = event_alert_summary(te_e, ev_te, mins_te, risk, args.alert_threshold)
    print(f"\nTest: acc={acc:.4f} macro_f1={f1m:.4f}")
    print(
        f"Event alert summary (threshold={args.alert_threshold:.2f}): "
        f"coverage={cov:.3f} median_lead_min={med_lead:.2f} early_false_rate={early_false:.3f}"
    )

    if args.infer_event:
        ev = args.infer_event
        fp = cache_dir / f"{ev}.npz"
        if not fp.exists():
            print(f"\nEvent not found: {ev}")
        else:
            times_evt, feats_evt = event_rows_unlabeled(fp, args.log_scale)
            feats_evt = augment_with_aux_features(ev, times_evt, feats_evt, aux_table, aux_cols)
            X_evt, feat_evt, row_idx_evt = engineer_feature_table(feats_evt, args.warmup, args.feature_mode)
            if X_evt.size == 0:
                print(f"\nNo usable rows for event: {ev}")
            elif feat_evt != feat_ref:
                print(f"\nFeature schema mismatch for event: {ev}")
            else:
                X_evt_n = ((X_evt - xm) / xs).astype(np.float32)
                with torch.no_grad():
                    logits_evt = net(torch.from_numpy(X_evt_n).to(dev)).cpu().numpy()
                prob_evt = softmax_np(logits_evt)
                pred_evt = np.argmax(prob_evt, axis=1)
                n = len(row_idx_evt) if args.print_n <= 0 else min(args.print_n, len(row_idx_evt))
                print(f"\nEvent imminence inference: {ev}")
                if ev in flare_windows:
                    s, e = flare_windows[ev]
                    if e is not None:
                        print(f"flare_start={s.isoformat()} flare_end={e.isoformat()}")
                    else:
                        print(f"flare_start={s.isoformat()} flare_end=NA")
                else:
                    print("flare_start=NA flare_end=NA")
                for kk, i in enumerate(row_idx_evt[:n]):
                    risk_evt = float(np.sum(prob_evt[kk] * risk_weights))
                    parts = [f"p<= {b:g}m={float(prob_evt[kk, bi]):.3f}" for bi, b in enumerate(bins)]
                    print(
                        f"{times_evt[int(i)].isoformat()} risk={risk_evt:.4f} cls={int(pred_evt[kk])} {' '.join(parts)}"
                    )

    if args.print_event:
        ev = args.print_event
        fp = cache_dir / f"{ev}.npz"
        if ev not in flare_info or not fp.exists():
            print(f"\nEvent not found: {ev}")
        else:
            times_evt, feats_evt = event_rows(fp, flare_info[ev], args.pre_min, args.log_scale)
            feats_evt = augment_with_aux_features(ev, times_evt, feats_evt, aux_table, aux_cols)
            X_evt, feat_evt, row_idx_evt = engineer_feature_table(feats_evt, args.warmup, args.feature_mode)
            if X_evt.size == 0:
                print(f"\nNo usable rows for event: {ev}")
            elif feat_evt != feat_ref:
                print(f"\nFeature schema mismatch for event: {ev}")
            else:
                X_evt_n = ((X_evt - xm) / xs).astype(np.float32)
                with torch.no_grad():
                    logits_evt = net(torch.from_numpy(X_evt_n).to(dev)).cpu().numpy()
                prob_evt = softmax_np(logits_evt)
                pred_evt = np.argmax(prob_evt, axis=1)
                n = len(row_idx_evt) if args.print_n <= 0 else min(args.print_n, len(row_idx_evt))
                print(f"\nEvent imminence: {ev}")
                if ev in flare_windows:
                    s, e = flare_windows[ev]
                    if e is not None:
                        print(f"flare_start={s.isoformat()} flare_end={e.isoformat()}")
                    else:
                        print(f"flare_start={s.isoformat()} flare_end=NA")
                else:
                    print("flare_start=NA flare_end=NA")
                for kk, i in enumerate(row_idx_evt[:n]):
                    mins = float((flare_info[ev] - times_evt[int(i)]).total_seconds() / 60.0)
                    risk_evt = float(np.sum(prob_evt[kk] * risk_weights))
                    parts = [f"p<= {b:g}m={float(prob_evt[kk, bi]):.3f}" for bi, b in enumerate(bins)]
                    parts.append(f"p> {bins[-1]:g}m={float(prob_evt[kk, len(bins)]):.3f}")
                    print(
                        f"{times_evt[int(i)].isoformat()} risk={risk_evt:.4f} cls={int(pred_evt[kk])} "
                        f"{' '.join(parts)} mins_to_onset={mins:.2f}"
                    )

    if args.save and not args.load:
        out = Path(args.save)
        out.parent.mkdir(parents=True, exist_ok=True)
        torch.save(
            {
                "state_dict": net.state_dict(),
                "x_mean": xm.astype(np.float32),
                "x_std": xs.astype(np.float32),
                "feature_names": feat_ref,
                "bins": bins,
                "risk_weights": risk_weights.astype(np.float32),
                "args": vars(args),
            },
            out,
        )
        print(f"Saved: {out}")


if __name__ == "__main__":
    main()
