import drms
from urllib.request import urlretrieve
from urllib.error import URLError, HTTPError
import os
from sunpy.map import Map
import datetime
from datetime import timedelta

from aiapy.calibrate import register, correct_degradation
import time

from sunpy.coordinates import frames

import csv
import re

import astropy
from astropy.coordinates import SkyCoord
import astropy.units as u

import numpy as np
import torch
import torch.nn as nn

# from torchvision.transforms import Resize
# import torch

import glob
from concurrent.futures import ThreadPoolExecutor, as_completed

from paramiko import SSHClient
from scp import SCPClient
# import dem_rml

import pytz

from urllib.request import urlopen

import pandas as pd

import json
import io

from dateutil import tz

import matplotlib
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import matplotlib.colors as colors

import shutil

from PIL import Image

# **********************************************************

_TZ_CACHE = {}
_VIS_OP_CACHE = {}
_SUVI_URL_CACHE = {}
_SUVI_IMAGE_CACHE = {}


def mkdir(a_dir):
    """
    Function creating a folder if it does not exists

    Parameters
        ----------
        a_dir: string
            path of the folder to be created
    """

    if not os.path.exists(a_dir):
        os.makedirs(a_dir)


# **********************************************************


def normalize_exposure(aia_map):
    """
    Normalize map data by exposure time (DN -> DN/s).
    Replacement for removed aiapy.calibrate.normalize_exposure in newer aiapy.
    """
    exptime = aia_map.exposure_time.to_value("s")
    if exptime <= 0:
        return aia_map

    meta = aia_map.meta.copy()
    meta["exptime"] = 1.0
    return Map(aia_map.data / exptime, meta)


# **********************************************************


class GRUMultiRegressor(nn.Module):
    def __init__(self, in_dim, hidden, layers, out_dim):
        super().__init__()
        self.gru = nn.GRU(in_dim, hidden, num_layers=layers, batch_first=True)
        self.fc = nn.Linear(hidden, out_dim)

    def forward(self, x):
        out, _ = self.gru(x)
        last = out[:, -1, :]
        return self.fc(last)


class CentroidGRUReg(nn.Module):
    def __init__(self, hidden, layers):
        super().__init__()
        self.gru = nn.GRU(1, hidden, num_layers=layers, batch_first=True)
        self.fc = nn.Linear(hidden, 1)

    def forward(self, x):
        out, _ = self.gru(x)
        return self.fc(out[:, -1, :]).squeeze(-1)


def _safe_expm1(x):
    return np.expm1(np.clip(x, -50.0, 50.0))


def _maybe_log(feats):
    out = {}
    for k, v in feats.items():
        if v >= 0:
            out[k] = float(np.log1p(v))
        else:
            out[k] = float(v)
    return out


def _load_uv_grid(uv_grid_path):
    uv = np.load(uv_grid_path)
    return np.array(uv["u_vals"], dtype=np.float64), np.array(
        uv["v_vals"], dtype=np.float64
    )


def _radial_bins_fft(h, w, num_bins):
    ky = np.fft.fftfreq(h)[:, None]
    kx = np.fft.rfftfreq(w)[None, :]
    r = np.sqrt(kx * kx + ky * ky)
    edges = np.linspace(0.0, float(r.max()), num_bins + 1)
    idx = np.clip(
        np.digitize(r.ravel(), edges, right=False) - 1, 0, num_bins - 1
    ).astype(np.int64)
    centers = 0.5 * (edges[:-1] + edges[1:])
    return idx, centers.astype(np.float32)


def _profile_from_vis_cube(vis_cube, radial_bin_idx, num_bins):
    amp = np.abs(vis_cube).astype(np.float64, copy=False)
    x_mean = amp.mean(axis=0)
    p = np.abs(np.fft.rfft2(x_mean, norm="ortho")) ** 2
    prof = np.bincount(radial_bin_idx, weights=p.ravel(), minlength=num_bins).astype(
        np.float64
    )
    prof /= float(prof.sum() + 1e-12)
    return prof.astype(np.float32)


def _centroid_from_profile(profile, radial_centers):
    return float((profile * radial_centers).sum())


def _tilt_profile_to_centroid(profile, radial_centers, target_centroid):
    lo, hi = -80.0, 80.0
    p = profile.astype(np.float64) + 1e-12
    r = radial_centers.astype(np.float64)
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        w = np.exp(mid * r)
        q = p * w
        q /= q.sum()
        c = float((q * r).sum())
        if c < target_centroid:
            lo = mid
        else:
            hi = mid
    w = np.exp(0.5 * (lo + hi) * r)
    q = p * w
    q /= q.sum()
    return q.astype(np.float32)


def load_centroid_forecast_checkpoint(model_path):
    ckpt = torch.load(model_path, map_location="cpu", weights_only=False)
    args = ckpt.get("args", {})
    hidden = int(args.get("hidden", 48))
    layers = int(args.get("layers", 1))
    num_bins = int(ckpt.get("num_bins", args.get("num_bins", 20)))
    horizon = float(args.get("horizon", 5.0))
    seq_min = int(args.get("seq_min", 12))
    x_mean = float(ckpt["x_mean"])
    x_std = float(ckpt["x_std"]) if float(ckpt["x_std"]) > 0 else 1.0
    y_mean = float(ckpt["y_mean"])
    y_std = float(ckpt["y_std"]) if float(ckpt["y_std"]) > 0 else 1.0
    model = CentroidGRUReg(hidden, layers)
    model.load_state_dict(ckpt["state_dict"])
    model.eval()
    return {
        "model": model,
        "x_mean": x_mean,
        "x_std": x_std,
        "y_mean": y_mean,
        "y_std": y_std,
        "num_bins": num_bins,
        "seq_min": seq_min,
        "horizon": horizon,
    }


def predict_centroid_seq_from_history(model_data, centroid_history, seq_len):
    seq = np.array(centroid_history[-seq_len:], dtype=np.float32)
    seq = ((seq - model_data["x_mean"]) / model_data["x_std"]).astype(np.float32)[
        :, None
    ]
    xb = torch.from_numpy(seq).unsqueeze(0)
    with torch.no_grad():
        yhat_n = float(model_data["model"](xb).cpu().numpy()[0])
    return yhat_n * model_data["y_std"] + model_data["y_mean"]


def _expand_alert_features(z, target_keys, feature_map, recip_eps):
    z = z.astype(np.float32, copy=False)
    blocks = [z]
    names = list(target_keys)
    if feature_map in {"nonlinear", "physics"}:
        z_neg = -z
        z_log = np.sign(z) * np.log1p(np.abs(z))
        z_sq = z * z
        blocks.extend([z_neg, z_log, z_sq])
        names.extend([f"neg_{k}" for k in target_keys])
        names.extend([f"log_{k}" for k in target_keys])
        names.extend([f"sq_{k}" for k in target_keys])
    if feature_map == "physics":
        eps = float(max(recip_eps, 1e-6))
        z_recip = np.clip(np.sign(z) / (np.abs(z) + eps), -8.0, 8.0)
        z_pow_half = np.sign(z) * np.sqrt(np.abs(z))
        z_pow_1p5 = np.sign(z) * (np.abs(z) ** 1.5)
        z_pow_2p5 = np.sign(z) * (np.abs(z) ** 2.5)
        blocks.extend([z_recip, z_pow_half, z_pow_1p5, z_pow_2p5])
        names.extend([f"recip_{k}" for k in target_keys])
        names.extend([f"pow0p5_{k}" for k in target_keys])
        names.extend([f"pow1p5_{k}" for k in target_keys])
        names.extend([f"pow2p5_{k}" for k in target_keys])
    return np.concatenate(blocks, axis=1), names


def _get_vis_operators(nx, ny, pixel_arcsec, u_vals, v_vals, x0=0.0, y0=0.0):
    key = (
        nx,
        ny,
        float(pixel_arcsec),
        float(x0),
        float(y0),
        tuple(u_vals.tolist()),
        tuple(v_vals.tolist()),
    )
    if key in _VIS_OP_CACHE:
        return _VIS_OP_CACHE[key]

    x = (np.arange(nx, dtype=np.float64) - (nx - 1) / 2.0) * float(pixel_arcsec)
    y = (np.arange(ny, dtype=np.float64) - (ny - 1) / 2.0) * float(pixel_arcsec)
    ex = np.exp(2j * np.pi * (u_vals[:, None] * (x[None, :] - float(x0))))
    ey = np.exp(2j * np.pi * (v_vals[:, None] * (y[None, :] - float(y0))))
    iu0 = int(np.argmin(np.abs(u_vals)))
    iv0 = int(np.argmin(np.abs(v_vals)))

    _VIS_OP_CACHE[key] = (ex, ey, iu0, iv0)
    return _VIS_OP_CACHE[key]


def compute_sparse_vis_cube_from_aia(
    aia_img_hwc,
    u_vals,
    v_vals,
    pixel_arcsec=0.6,
    x0=0.0,
    y0=0.0,
    normalize=True,
    remove_dc=True,
):
    img = np.asarray(aia_img_hwc, dtype=np.float64)
    img = np.nan_to_num(img, nan=0.0, posinf=0.0, neginf=0.0)
    ny, nx, nchan = img.shape

    ex, ey, iu0, iv0 = _get_vis_operators(
        nx, ny, pixel_arcsec, u_vals, v_vals, x0=x0, y0=y0
    )
    vis_cube = np.zeros((nchan, len(u_vals), len(v_vals)), dtype=np.complex64)

    for ci in range(nchan):
        this_img = img[:, :, ci]
        if normalize:
            total = float(this_img.sum())
            if total != 0.0:
                this_img = this_img / total
        vuv = (ex @ this_img.T @ ey.T).T * (float(pixel_arcsec) * float(pixel_arcsec))
        vuv = vuv.T
        if remove_dc:
            vuv[iu0, iv0] = 0.0 + 0.0j
        vis_cube[ci] = vuv.astype(np.complex64, copy=False)

    return vis_cube


def _spectral_features_2d(x):
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
    low = float(power[r <= 0.33].sum())
    mid = float(power[(r > 0.33) & (r <= 0.66)].sum())
    high = float(power[r > 0.66].sum())
    ratio_hl = float(high / (low + 1e-9))
    vhigh = float(power[r > 0.8].sum() / total)
    spec_slope = float(np.log(high + 1e-9) - np.log(low + 1e-9))
    return entropy, centroid, bandwidth, low, mid, high, ratio_hl, vhigh, spec_slope


def compute_ml_fft_features_from_vis(vis, prev_vis=None):
    vis_c = vis
    prev_c = prev_vis

    amp = np.abs(vis_c)
    amp_mean = float(amp.mean())
    amp_std = float(amp.std())

    x_mean = amp.mean(axis=0)
    entropy, centroid, bandwidth, low, mid, high, ratio_hl, vhigh, spec_slope = (
        _spectral_features_2d(x_mean)
    )

    gx = np.diff(x_mean, axis=1, append=x_mean[:, -1:])
    gy = np.diff(x_mean, axis=0, append=x_mean[-1:, :])
    grad = np.sqrt(gx * gx + gy * gy + 1e-9)
    grad_mean = float(grad.mean())
    grad_std = float(grad.std())

    xpad = np.pad(x_mean, ((1, 1), (1, 1)), mode="edge")
    lap = (
        xpad[1:-1, 2:]
        + xpad[1:-1, :-2]
        + xpad[2:, 1:-1]
        + xpad[:-2, 1:-1]
        - 4.0 * x_mean
    )
    lap_energy = float(np.mean(lap * lap))

    feats = {
        "amp_mean": amp_mean,
        "amp_std": amp_std,
        "amp_skew": float(np.mean((amp - amp_mean) ** 3) / (amp_std**3 + 1e-9)),
        "amp_kurt": float(np.mean((amp - amp_mean) ** 4) / (amp_std**4 + 1e-9)),
        "spec_entropy": float(entropy),
        "spec_centroid": float(centroid),
        "spec_bandwidth": float(bandwidth),
        "spec_low": float(low),
        "spec_mid": float(mid),
        "spec_high": float(high),
        "spec_vhigh": float(vhigh),
        "spec_hilo": float(ratio_hl),
        "spec_slope": float(spec_slope),
        "grad_mean": grad_mean,
        "grad_std": grad_std,
        "lap_energy": lap_energy,
    }

    if prev_c is not None:
        delta = vis_c - prev_c
        feats["delta_energy"] = float(np.mean(np.abs(delta)))
        feats["max_delta"] = float(np.max(np.abs(delta)))
    else:
        feats["delta_energy"] = 0.0
        feats["max_delta"] = 0.0

    phase = np.angle(vis_c)
    mean_cos = float(np.mean(np.cos(phase)))
    mean_sin = float(np.mean(np.sin(phase)))
    phase_coh = np.sqrt(mean_cos * mean_cos + mean_sin * mean_sin)
    phase_var = 1.0 - phase_coh
    phase_std = float(np.sqrt(max(0.0, -2.0 * np.log(phase_coh + 1e-9))))
    feats["phase_coh"] = float(phase_coh)
    feats["phase_var"] = float(phase_var)
    feats["phase_std"] = phase_std

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


def load_ml_fft_checkpoint(model_path):
    ckpt = torch.load(model_path, map_location="cpu", weights_only=False)

    feature_keys = list(ckpt["feature_keys"])
    target_keys = list(ckpt["target_keys"])
    mean = np.array(ckpt["mean"], dtype=np.float32)
    std = np.array(ckpt["std"], dtype=np.float32)
    std_safe = np.where(std > 0, std, 1.0).astype(np.float32)
    y_stats = ckpt["y_stats"]
    target_scale = ckpt.get("target_scale", "none")
    log_scale = bool(ckpt.get("log_scale", False))
    learned_alert = ckpt.get("learned_alert", {})

    model = GRUMultiRegressor(
        in_dim=len(feature_keys),
        hidden=int(ckpt.get("hidden", 64)),
        layers=int(ckpt.get("layers", 1)),
        out_dim=len(target_keys),
    )
    model.load_state_dict(ckpt["model_state"])
    model.eval()

    return {
        "model": model,
        "feature_keys": feature_keys,
        "target_keys": target_keys,
        "mean": mean,
        "std": std_safe,
        "y_stats": y_stats,
        "target_scale": target_scale,
        "log_scale": log_scale,
        "learned_alert": learned_alert,
    }


def compute_ml_alert_scores(ml_model_data, pred_map, true_map):
    learned = ml_model_data.get("learned_alert", {})
    if not learned:
        return np.nan, np.nan

    target_keys = ml_model_data["target_keys"]
    y_stats = ml_model_data["y_stats"]
    feature_map = str(learned.get("__feature_map", "nonlinear"))
    recip_eps = float(learned.get("__recip_eps", 0.25))

    def _one_alert(feat_map):
        z_vals = []
        for k in target_keys:
            stats = y_stats[k]
            y_std = float(stats["y_std"]) if float(stats["y_std"]) > 0 else 1.0
            y_mean = float(stats["y_mean"])
            z_vals.append((float(feat_map[k]) - y_mean) / y_std)
        z_base = np.array(z_vals, dtype=np.float32).reshape(1, -1)
        z_exp, exp_keys = _expand_alert_features(
            z_base, target_keys, feature_map, recip_eps
        )
        w = np.array(
            [float(learned.get("w_" + k, 0.0)) for k in exp_keys], dtype=np.float32
        )
        b = float(learned.get("bias", 0.0))
        logit = float(np.dot(w, z_exp[0]) + b)
        prob = 1.0 / (1.0 + np.exp(-logit))
        return float(prob * 100.0)

    return _one_alert(pred_map), _one_alert(true_map)


def _spectral_centroid_per_channel_from_vis(vis_cube):
    amp = np.abs(vis_cube).astype(np.float64, copy=False)
    c, h, w = amp.shape
    ys = np.linspace(-1.0, 1.0, h)[:, None]
    xs = np.linspace(0.0, 1.0, w)[None, :]
    r = np.sqrt(xs * xs + ys * ys)
    out = np.zeros(c, dtype=np.float32)
    for i in range(c):
        power = amp[i] * amp[i]
        total = float(power.sum()) + 1e-12
        out[i] = float((power * r).sum() / total)
    return out


def _parse_csv_floats(spec):
    vals = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            vals.append(float(part))
        except ValueError:
            continue
    return vals


def _resolve_score_channels(channel_names, chan_csv, weight_csv):
    chan_names = [s.strip() for s in chan_csv.split(",") if s.strip()]
    weights = _parse_csv_floats(weight_csv)
    out_idx = []
    out_w = []
    for i_name, name in enumerate(chan_names):
        if i_name >= len(weights):
            break
        if name in channel_names:
            out_idx.append(channel_names.index(name))
            out_w.append(weights[i_name])
    if out_w:
        sw = float(np.sum(np.abs(np.array(out_w, dtype=np.float64))))
        if sw > 0:
            out_w = [w / sw for w in out_w]
    return out_idx, out_w


def _build_dual_score_configs():
    return [
        {
            "name": "gradual",
            "bwin": 10,
            "lwin": 20,
            "llg": 4,
            "ts": 4,
            "tl": 16,
            "w_change": 0.55,
            "w_level": 0.30,
            "w_trend": 0.15,
        },
        {
            "name": "impulsive",
            "bwin": 8,
            "lwin": 20,
            "llg": 0,
            "ts": 4,
            "tl": 16,
            "w_change": 0.60,
            "w_level": 0.40,
            "w_trend": 0.00,
        },
    ]


def _init_dual_score_state(score_indices, score_w, imp_indices, imp_w):
    st = {}
    for cfg in _build_dual_score_configs():
        if cfg["name"] == "gradual":
            idxs, ws = score_indices, score_w
        else:
            idxs, ws = imp_indices, imp_w
        st[cfg["name"]] = {
            "indices": idxs,
            "weights": ws,
            "pred_hist": {idx: [] for idx in idxs},
            "delta_hist": {idx: [] for idx in idxs},
            "trend_hist": {idx: [] for idx in idxs},
        }
    return st


def _update_profile_score(pred_vec, cfg, st):
    z_terms_change = []
    z_terms_level = []
    z_terms_trend = []
    w_terms = []
    bwin = cfg["bwin"]
    lwin = cfg["lwin"]
    llg = cfg["llg"]
    ts = cfg["ts"]
    tl = cfg["tl"]

    for idx, w in zip(st["indices"], st["weights"]):
        ph = st["pred_hist"][idx]
        ph.append(float(pred_vec[idx]))
        keep = max(3, bwin, lwin + llg + 2, tl + ts + 2)
        if len(ph) > keep:
            ph[:] = ph[-keep:]

        base = float(np.mean(ph[-bwin:])) if ph else float(pred_vec[idx])
        d = float(pred_vec[idx] - base)
        dh = st["delta_hist"][idx]
        dh.append(d)
        if len(dh) > bwin:
            dh[:] = dh[-bwin:]

        th = st["trend_hist"][idx]
        have_term = False
        zc = 0.0
        zl = 0.0
        zt = 0.0
        if len(dh) >= 3:
            mu = float(np.mean(dh))
            sd = float(np.std(dh))
            zc = (d - mu) / (sd + 1e-6)
            have_term = True
        if len(ph) >= (lwin + llg):
            if llg > 0:
                level_slice = ph[-(lwin + llg) : -llg]
            else:
                level_slice = ph[-lwin:]
            pmu = float(np.mean(level_slice))
            psd = float(np.std(level_slice))
            zl = (float(pred_vec[idx]) - pmu) / (psd + 1e-6)
            have_term = True
        if len(ph) >= (tl + ts):
            short_mean = float(np.mean(ph[-ts:]))
            long_mean = float(np.mean(ph[-(tl + ts) : -ts]))
            trend = short_mean - long_mean
            th.append(trend)
            if len(th) > lwin:
                th[:] = th[-lwin:]
            if len(th) >= 3:
                tmu = float(np.mean(th))
                tsd = float(np.std(th))
                zt = (trend - tmu) / (tsd + 1e-6)
                have_term = True
        if have_term:
            z_terms_change.append(zc)
            z_terms_level.append(zl)
            z_terms_trend.append(zt)
            w_terms.append(w)

    if not w_terms:
        return np.nan

    n = len(w_terms)
    c = (
        np.array(z_terms_change, dtype=np.float64)
        if z_terms_change
        else np.zeros(n, dtype=np.float64)
    )
    l = (
        np.array(z_terms_level, dtype=np.float64)
        if z_terms_level
        else np.zeros(n, dtype=np.float64)
    )
    t = (
        np.array(z_terms_trend, dtype=np.float64)
        if z_terms_trend
        else np.zeros(n, dtype=np.float64)
    )
    wv = np.array(w_terms, dtype=np.float64)
    c_score = float(np.sum(c * wv))
    l_score = float(np.sum(l * wv))
    t_score = float(np.sum(t * wv))
    w_sum = cfg["w_change"] + cfg["w_level"] + cfg["w_trend"]
    if w_sum <= 0:
        w_sum = 1.0
    return float(
        (
            cfg["w_change"] * c_score
            + cfg["w_level"] * l_score
            + cfg["w_trend"] * t_score
        )
        / w_sum
    )


def update_dual_scores(pred_vec, score_state):
    cfgs = _build_dual_score_configs()
    g_cfg = cfgs[0]
    i_cfg = cfgs[1]
    g_score = _update_profile_score(pred_vec, g_cfg, score_state["gradual"])
    i_score = _update_profile_score(pred_vec, i_cfg, score_state["impulsive"])
    return g_score, i_score


def load_centroid_seq_checkpoint(model_path):
    ckpt = torch.load(model_path, map_location="cpu", weights_only=False)
    channel_names = [str(x) for x in ckpt["channel_names"]]
    mean = np.array(ckpt["mean"], dtype=np.float32)
    std = np.array(ckpt["std"], dtype=np.float32)
    std_safe = np.where(std > 0, std, 1.0).astype(np.float32)
    y_mean = np.array(ckpt["y_mean"], dtype=np.float32)
    y_std = np.array(ckpt["y_std"], dtype=np.float32)
    y_std = np.where(y_std > 0, y_std, 1.0).astype(np.float32)
    horizon = float(ckpt.get("horizon", 5.0))
    model = GRUMultiRegressor(
        in_dim=len(channel_names),
        hidden=int(ckpt.get("hidden", 64)),
        layers=int(ckpt.get("layers", 1)),
        out_dim=len(channel_names),
    )
    model.load_state_dict(ckpt["model_state"])
    model.eval()
    return {
        "model": model,
        "channel_names": channel_names,
        "mean": mean,
        "std": std_safe,
        "y_mean": y_mean,
        "y_std": y_std,
        "horizon": horizon,
    }


def predict_centroid_seq(ml_model_data, window_stack):
    x = (window_stack - ml_model_data["mean"]) / ml_model_data["std"]
    xb = torch.from_numpy(x.astype(np.float32)).unsqueeze(0)
    with torch.no_grad():
        pred_z = ml_model_data["model"](xb).cpu().numpy()[0]
    return pred_z * ml_model_data["y_std"] + ml_model_data["y_mean"]


def predict_ml_fft_targets(ml_model_data, window_stack):
    x = (window_stack - ml_model_data["mean"]) / ml_model_data["std"]
    xb = torch.from_numpy(x.astype(np.float32)).unsqueeze(0)
    with torch.no_grad():
        pred_z = ml_model_data["model"](xb).cpu().numpy()[0]

    target_keys = ml_model_data["target_keys"]
    y_stats = ml_model_data["y_stats"]
    target_scale = ml_model_data["target_scale"]

    out = {}
    for i, k in enumerate(target_keys):
        stats = y_stats[k]
        if target_scale == "quantile":
            y_ref = np.array(stats["y_ref"], dtype=np.float32)
            q = float(np.clip(pred_z[i], 0.0, 1.0))
            pred = float(np.interp(q, np.linspace(0.0, 1.0, len(y_ref)), y_ref))
        elif target_scale == "p5p95":
            p5 = float(stats["p5"])
            p95 = float(stats["p95"])
            pred = float(np.clip(pred_z[i], 0.0, 1.0) * (p95 - p5) + p5)
        else:
            pred = float(pred_z[i] * float(stats["y_std"]) + float(stats["y_mean"]))
            if target_scale == "log" and pred >= 0:
                pred = float(_safe_expm1(pred))
        out[k] = pred
    return out


def plot_ml_feature_trends(
    plots_folder,
    label,
    arnum,
    ar_index,
    time_array,
    pred_feature_series,
    true_feature_series,
    alert_pred_series,
    alert_true_series,
    timezone="US/Central",
):
    if len(time_array) == 0:
        return

    target_keys = list(pred_feature_series.keys())
    if len(target_keys) == 0:
        return

    n_feat = len(target_keys) + 1
    fig, axes = plt.subplots(1, n_feat, figsize=(3.2 * n_feat, 2.8), sharex=True)
    if n_feat == 1:
        axes = [axes]

    latest_time = time_array[-1]
    min_time = latest_time - timedelta(minutes=60)
    max_time = latest_time
    mask = np.array(time_array) >= min_time
    t = np.array(time_array)[mask]

    for idx, k in enumerate(target_keys):
        ax = axes[idx]
        y_pred = np.array(pred_feature_series[k], dtype=np.float64)[mask]
        y_true = np.array(true_feature_series[k], dtype=np.float64)[mask]
        if len(y_pred) == 0 or len(y_true) == 0:
            continue

        ymin = float(min(np.min(y_true), np.min(y_pred)))
        ymax = float(max(np.max(y_true), np.max(y_pred)))
        pad = 0.08 * (ymax - ymin + 1e-12)

        ax.plot(t, y_true, color="tab:blue", linewidth=1.4, label="realtime")
        ax.plot(
            t, y_pred, color="tab:orange", linewidth=1.4, linestyle="--", label="pred"
        )
        ax.scatter([t[-1]], [y_true[-1]], color="tab:blue", s=10, zorder=3)
        ax.scatter([t[-1]], [y_pred[-1]], color="tab:orange", s=10, zorder=3)
        ax.set_title(k, fontsize=8)
        ax.set_ylim(ymin - pad, ymax + pad)
        ax.set_xlim(min_time, max_time)
        ax.grid(True, alpha=0.25)
        ax.tick_params(axis="y", labelsize=7)
        ax.tick_params(axis="x", labelsize=7)
        ax.xaxis.set_major_formatter(
            mdates.DateFormatter("%H:%M", tz=tz.gettz(timezone))
        )
        if idx == 0:
            ax.legend(fontsize=7, loc="upper left")

    ax_alert = axes[-1]
    y_pred_alert = np.array(alert_pred_series, dtype=np.float64)[mask]
    y_true_alert = np.array(alert_true_series, dtype=np.float64)[mask]
    if len(y_pred_alert) > 0 and len(y_true_alert) > 0:
        ymin = float(min(np.nanmin(y_true_alert), np.nanmin(y_pred_alert)))
        ymax = float(max(np.nanmax(y_true_alert), np.nanmax(y_pred_alert)))
        pad = 0.08 * (ymax - ymin + 1e-12)
        ax_alert.plot(
            t, y_true_alert, color="tab:blue", linewidth=1.4, label="realtime"
        )
        ax_alert.plot(
            t,
            y_pred_alert,
            color="tab:orange",
            linewidth=1.4,
            linestyle="--",
            label="pred",
        )
        ax_alert.scatter([t[-1]], [y_true_alert[-1]], color="tab:blue", s=10, zorder=3)
        ax_alert.scatter(
            [t[-1]], [y_pred_alert[-1]], color="tab:orange", s=10, zorder=3
        )
        ax_alert.set_ylim(ymin - pad, ymax + pad)
    ax_alert.set_title("alert", fontsize=8)
    ax_alert.set_xlim(min_time, max_time)
    ax_alert.grid(True, alpha=0.25)
    ax_alert.tick_params(axis="y", labelsize=7)
    ax_alert.tick_params(axis="x", labelsize=7)
    ax_alert.xaxis.set_major_formatter(
        mdates.DateFormatter("%H:%M", tz=tz.gettz(timezone))
    )
    ax_alert.legend(fontsize=7, loc="upper left")

    fig.suptitle(f"{label} {arnum} ML feature trends (realtime vs pred)", fontsize=11)
    fig.tight_layout(rect=[0, 0, 1, 0.90])
    plt.savefig(
        os.path.join(plots_folder, "aia_ml_" + str(ar_index)),
        dpi=95,
        bbox_inches="tight",
    )
    plt.close(fig)


def plot_ml_gi_scores(
    plots_folder,
    label,
    arnum,
    ar_index,
    time_array,
    g_series,
    i_series,
    timezone="US/Central",
    file_prefix="aia_gi_",
):
    if len(time_array) == 0 or len(g_series) == 0 or len(i_series) == 0:
        return

    latest_time = time_array[-1]
    min_time = latest_time - timedelta(minutes=150)
    max_time = latest_time
    mask = np.array(time_array) >= min_time
    t = np.array(time_array)[mask]
    g = np.array(g_series, dtype=np.float64)[mask]
    i = np.array(i_series, dtype=np.float64)[mask]
    valid = np.isfinite(g) | np.isfinite(i)
    has_finite = bool(np.any(valid))
    if has_finite:
        t_plot = t[valid]
        g_plot = g[valid]
        i_plot = i[valid]
        ymin = float(
            np.nanmin(
                np.concatenate(
                    [g_plot[np.isfinite(g_plot)], i_plot[np.isfinite(i_plot)]]
                )
            )
        )
        ymax = float(
            np.nanmax(
                np.concatenate(
                    [g_plot[np.isfinite(g_plot)], i_plot[np.isfinite(i_plot)]]
                )
            )
        )
        pad = 0.08 * (ymax - ymin + 1e-12)
    else:
        t_plot = t
        g_plot = g
        i_plot = i
        ymin, ymax, pad = -1.0, 1.0, 0.1

    fig, ax = plt.subplots(1, 1, figsize=(9.0, 2.8))
    ax.plot(t_plot, g_plot, color="tab:blue", linewidth=1.5, label="g")
    ax.plot(t_plot, i_plot, color="tab:orange", linewidth=1.5, label="i")
    if has_finite and len(t_plot) > 0:
        ax.scatter([t_plot[-1]], [g_plot[-1]], color="tab:blue", s=12, zorder=3)
        ax.scatter([t_plot[-1]], [i_plot[-1]], color="tab:orange", s=12, zorder=3)
    ax.set_xlim(min_time, max_time)
    ax.set_ylim(ymin - pad, ymax + pad)
    ax.grid(True, alpha=0.25)
    ax.tick_params(axis="y", labelsize=8)
    ax.tick_params(axis="x", labelsize=8)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=tz.gettz(timezone)))
    ax.set_title(f"{label} {arnum} dual scores", fontsize=10)
    ax.set_xlabel(f"Time ({timezone})", fontsize=8)
    ax.set_ylabel("Score (z-weighted)", fontsize=8)
    ax.legend(fontsize=8, loc="upper left")
    if not has_finite:
        ax.text(
            0.5,
            0.55,
            "Warming up score windows...",
            transform=ax.transAxes,
            ha="center",
            va="center",
            fontsize=9,
            alpha=0.8,
        )
    fig.tight_layout()
    plt.savefig(
        os.path.join(plots_folder, file_prefix + str(ar_index)),
        dpi=95,
        bbox_inches="tight",
    )
    plt.close(fig)


def plot_centroid_forecast_for_ar(
    plots_folder,
    label,
    arnum,
    ar_index,
    current_time_array,
    current_centroid_series,
    current_profile_series,
    pred_target_time_array,
    pred_centroid_series,
    pred_profile_series,
    horizon_min=5.0,
    timezone="US/Central",
):
    if len(current_time_array) == 0:
        return

    # Realtime-only display for centroid/radial organization (no prediction overlay).
    full_tc = np.array(current_time_array)
    full_yc = np.array(current_centroid_series, dtype=np.float64)
    if len(full_tc) == 0:
        return

    latest_time = full_tc[-1]
    min_time = latest_time - timedelta(minutes=150)
    max_time = latest_time

    mask_cur = full_tc >= min_time
    tc = full_tc[mask_cur]
    yc = full_yc[mask_cur]
    if len(tc) == 0:
        return

    valid_y = yc[np.isfinite(yc)]
    if valid_y.size == 0:
        return
    ymin = float(np.nanmin(valid_y))
    ymax = float(np.nanmax(valid_y))
    pad = 0.08 * (ymax - ymin + 1e-12)

    fig, ax = plt.subplots(1, 3, figsize=(15.5, 3.2), constrained_layout=True)
    ax[0].plot(
        tc, yc, color="tab:blue", linewidth=1.4, alpha=0.85, label="current centroid"
    )
    ax[0].scatter([tc[-1]], [yc[-1]], color="tab:blue", s=12, zorder=3)
    ax[0].set_title("Current Centroid")
    ax[0].set_xlabel(f"Time ({timezone})", fontsize=8)
    ax[0].set_ylabel("Centroid (FFT radial freq.)", fontsize=8)
    ax[0].set_ylim(ymin - pad, ymax + pad)
    ax[0].set_xlim(min_time, max_time)
    ax[0].grid(alpha=0.2)
    ax[0].legend(fontsize=8, loc="best")
    ax[0].tick_params(axis="x", labelsize=8)
    ax[0].tick_params(axis="y", labelsize=8)
    ax[0].xaxis.set_major_formatter(
        mdates.DateFormatter("%H:%M", tz=tz.gettz(timezone))
    )

    if len(current_profile_series) == 0:
        plt.close(fig)
        return
    profile_mat = np.array(current_profile_series, dtype=np.float32).T
    if profile_mat.shape[1] != len(full_tc):
        ncol = min(profile_mat.shape[1], len(full_tc))
        profile_mat = profile_mat[:, -ncol:]
        tc = tc[-ncol:]
        yc = yc[-ncol:]
        mask_cur = full_tc[-ncol:] >= min_time
    pcur_m = np.ma.masked_invalid(profile_mat[:, mask_cur])
    im = ax[1].imshow(pcur_m, origin="lower", aspect="auto", cmap="viridis")
    ax[1].set_title("Current Radial Profile Bins")
    ax[1].set_xlabel(f"Time ({timezone})", fontsize=8)
    ax[1].set_ylabel("Radial Bin", fontsize=8)
    ax[1].tick_params(axis="x", labelsize=8)
    ax[1].tick_params(axis="y", labelsize=8)
    xt = np.linspace(0, len(tc) - 1, num=min(6, len(tc)), dtype=int)
    ax[1].set_xticks(xt)
    ax[1].set_xticklabels(
        [tc[ii].strftime("%H:%M") for ii in xt], rotation=45, ha="right"
    )
    fig.colorbar(im, ax=ax[1], fraction=0.046, pad=0.02)

    latest_prof = np.array(current_profile_series[-1], dtype=np.float64)
    rbins = np.arange(len(latest_prof))
    ax[2].plot(rbins, latest_prof, color="tab:green", linewidth=1.6)
    ax[2].scatter([rbins[-1]], [latest_prof[-1]], color="tab:green", s=10, zorder=3)
    ax[2].set_title("Current Radial Bin Profile")
    ax[2].set_xlabel("Radial Bin", fontsize=8)
    ax[2].set_ylabel("Normalized Power", fontsize=8)
    ax[2].grid(alpha=0.2)
    ax[2].tick_params(axis="x", labelsize=8)
    ax[2].tick_params(axis="y", labelsize=8)

    fig.suptitle(f"{label} {arnum}", fontsize=11)
    plt.savefig(
        os.path.join(plots_folder, "aia_ml_" + str(ar_index)),
        dpi=100,
        bbox_inches="tight",
    )
    plt.close(fig)


def plot_psf_reconstruction_comparison(
    plots_folder,
    label,
    arnum,
    ar_index,
    orig_img,
    recon_result,
    wavelength,
):
    if recon_result is None:
        return
    orig = np.asarray(orig_img, dtype=np.float64)
    recon = np.asarray(recon_result["reconstructed"], dtype=np.float64)
    ps_mask = np.asarray(
        recon_result.get("ps_mask", np.zeros_like(orig, dtype=bool)), dtype=bool
    )
    sat_mask = np.asarray(
        recon_result.get("sat_mask", np.zeros_like(orig, dtype=bool)), dtype=bool
    )
    fringe_mask = np.asarray(
        recon_result.get("fringe_mask", np.zeros_like(orig, dtype=bool)), dtype=bool
    )
    delta = recon - orig

    vmax = (
        float(np.nanpercentile(orig[np.isfinite(orig)], 99.7))
        if np.any(np.isfinite(orig))
        else 1.0
    )
    dlim = (
        float(np.nanpercentile(np.abs(delta[np.isfinite(delta)]), 99.5))
        if np.any(np.isfinite(delta))
        else 1.0
    )
    dlim = max(dlim, 1e-6)

    fig, ax = plt.subplots(2, 3, figsize=(11.5, 6.2), constrained_layout=True)
    im0 = ax[0, 0].imshow(orig, origin="lower", cmap="magma", vmax=vmax)
    ax[0, 0].set_title(f"Original {wavelength}A")
    im1 = ax[0, 1].imshow(recon, origin="lower", cmap="magma", vmax=vmax)
    ax[0, 1].set_title(f"Reconstructed {wavelength}A")
    im2 = ax[0, 2].imshow(delta, origin="lower", cmap="coolwarm", vmin=-dlim, vmax=dlim)
    ax[0, 2].set_title("Delta (Recon - Orig)")

    ax[1, 0].imshow(sat_mask.astype(float), origin="lower", cmap="gray")
    ax[1, 0].set_title("Saturated Mask")
    ax[1, 1].imshow(ps_mask.astype(float), origin="lower", cmap="gray")
    ax[1, 1].set_title("Primary Saturation Mask")
    ax[1, 2].imshow(fringe_mask.astype(float), origin="lower", cmap="gray")
    ax[1, 2].set_title("Fringe Mask")

    for a in ax.ravel():
        a.set_xlabel("X pixel", fontsize=8)
        a.set_ylabel("Y pixel", fontsize=8)
        a.tick_params(axis="x", labelsize=7)
        a.tick_params(axis="y", labelsize=7)
    for a, im in ((ax[0, 0], im0), (ax[0, 1], im1), (ax[0, 2], im2)):
        fig.colorbar(im, ax=a, fraction=0.046, pad=0.02)

    sat_frac = float(np.mean(sat_mask))
    ps_frac = float(np.mean(ps_mask))
    fringe_frac = float(np.mean(fringe_mask))
    fig.suptitle(
        f"{label} {arnum} PSF recon ({wavelength}A) | sat={sat_frac:.4f} ps={ps_frac:.4f} fringe={fringe_frac:.4f}",
        fontsize=10,
    )
    plt.savefig(
        os.path.join(plots_folder, "aia_psf_" + str(ar_index)),
        dpi=95,
        bbox_inches="tight",
    )
    plt.close(fig)


def plot_reconstructed_em_map_only(plots_folder, label, arnum, ar_index, em_map_recon):
    if em_map_recon is None:
        return
    fig = plt.figure(figsize=(7.2, 6.4))
    ax = plt.subplot(1, 1, 1, projection=em_map_recon)
    title = "PSF-Reconstructed Emission Measure \n (T $\\geq 10^{6.6}$ K)"
    em_map_recon.plot_settings["norm"] = colors.LogNorm(vmin=1e42, vmax=1e45, clip=True)
    em_map_recon.plot_settings["cmap"] = matplotlib.cm.get_cmap("CMRmap")
    im = em_map_recon.plot(axes=ax)
    ax.grid(False)
    ax.set_title(title, fontsize=12)
    ax.set_xlabel("Solar X [arcsec]", fontsize=10)
    ax.set_ylabel("Solar Y [arcsec]", fontsize=10)
    ax.tick_params(axis="x", labelsize=9)
    ax.tick_params(axis="y", labelsize=9)
    cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.02)
    cbar.ax.set_ylabel("EM [cm$^{-3}$ pixel$^{-1}$]", fontsize=10)
    cbar.ax.tick_params(labelsize=9)
    fig.suptitle(f"{label} {arnum}", fontsize=11)
    plt.savefig(
        os.path.join(plots_folder, "aia_psf_" + str(ar_index)),
        dpi=95,
        bbox_inches="tight",
    )
    plt.close(fig)


def plot_psf_diffraction_metrics(
    plots_folder,
    label,
    arnum,
    ar_index,
    time_history,
    sat_frac_history,
    ps_frac_history,
    fringe_frac_history,
    corr_strength_history,
    fringe_energy_ratio_history,
    timezone="US/Central",
    file_prefix="aia_psfdiag_",
):
    if len(time_history) == 0:
        return
    t = np.array(time_history)
    sat = np.array(sat_frac_history, dtype=np.float64)
    ps = np.array(ps_frac_history, dtype=np.float64)
    fringe = np.array(fringe_frac_history, dtype=np.float64)
    corr = np.array(corr_strength_history, dtype=np.float64)
    fer = np.array(fringe_energy_ratio_history, dtype=np.float64)

    latest_time = t[-1]
    min_time = latest_time - timedelta(minutes=60)
    mask = t >= min_time
    if not np.any(mask):
        return

    fig, ax = plt.subplots(2, 1, figsize=(10.0, 5.6), constrained_layout=True)
    ax[0].plot(t[mask], sat[mask], label="sat_frac", color="tab:red", linewidth=1.4)
    ax[0].plot(t[mask], ps[mask], label="ps_frac", color="tab:orange", linewidth=1.4)
    ax[0].plot(
        t[mask], fringe[mask], label="fringe_frac", color="tab:purple", linewidth=1.4
    )
    ax[0].set_ylabel("Fraction of pixels")
    ax[0].set_xlabel(f"Time ({timezone})")
    ax[0].set_title("PSF Diffraction/Saturation Fractions (131A)")
    ax[0].grid(alpha=0.2)
    ax[0].legend(fontsize=8, loc="best")
    ax[0].xaxis.set_major_formatter(
        mdates.DateFormatter("%H:%M", tz=tz.gettz(timezone))
    )

    ax[1].plot(
        t[mask], corr[mask], label="corr_ps_strength", color="tab:blue", linewidth=1.4
    )
    ax[1].plot(
        t[mask],
        fer[mask],
        label="fringe_energy_ratio",
        color="tab:green",
        linewidth=1.4,
    )
    ax[1].set_ylabel("Score / ratio")
    ax[1].set_xlabel(f"Time ({timezone})")
    ax[1].set_title("Diffraction Signal Metrics")
    ax[1].grid(alpha=0.2)
    ax[1].legend(fontsize=8, loc="best")
    ax[1].xaxis.set_major_formatter(
        mdates.DateFormatter("%H:%M", tz=tz.gettz(timezone))
    )

    fig.suptitle(f"{label} {arnum} PSF flare diagnostics", fontsize=11)
    plt.savefig(
        os.path.join(plots_folder, file_prefix + str(ar_index)),
        dpi=95,
        bbox_inches="tight",
    )
    plt.close(fig)


# **********************************************************


def configure_jsoc_server():
    """
    Function configuring a JSOC server (to be used for quering AIA data throgh drms)

    Returns
        -------
        client: drms client server
    """

    # Use current default DRMS server configuration.
    client = drms.Client()

    return client


# **********************************************************


def download_aia_data(
    wav, t_rec, segments, data_folder, timezone="US/Central", silent=False
):
    """

    Function for downloading near real time AIA data


    Parameters
        ----------
        wav: numpy array (integer)
            array containing the wavelength number of the AIA data to be downloaded

        t_rec: numpy array (string)
            array containing the recorded time of the AIA data to be downloaded

        segments: numpy array (string)
            array containing the path of the AIA data to be downloaded

        data_folder: string
            path of the folder where the downloaded AIA data are saved

        timezone: string
            timezone w.r.t. the times are expressed. Default, 'US/Central'

        silent: boolean
            if True, no text is printed

    Returns
        -------
        aia_maps: list
            list containing the downloaded full-disk AIA maps

        full_disk_maps_folder: string
            path of the folder where the full-disk AIA maps are downloaded

        error: bool
            True if an error occurred while downloading the data

    """

    # Create download folder
    full_disk_maps_folder = os.path.join(data_folder, t_rec[0].replace(":", ""))
    mkdir(full_disk_maps_folder)

    # Get fits file url
    website_url = "https://jsoc1.stanford.edu/"

    idx = np.argsort(wav)
    wav = wav[idx]
    t_rec = t_rec[idx]
    segments = segments[idx]

    this_datetime_timezone = convert_utc_to_timezone(
        datetime.datetime.strptime(t_rec[0], "%Y-%m-%dT%H:%M:%SZ"), timezone=timezone
    )

    if not silent:
        print(
            "\nStart download AIA data recorded at "
            + this_datetime_timezone.strftime("%m-%d-%YT%H:%M:%S")
            + " "
            + timezone
        )

    aia_maps = [None] * len(wav)

    # Error will be true if it is not possible to download a file
    error = False

    def _download_one(i):
        fits_file_url = website_url + segments[i]
        filename = os.path.join(
            full_disk_maps_folder,
            "aia_lev1_nrt2_" + t_rec[i] + "_" + str(wav[i]) + ".fits",
        ).replace(":", "")
        try:
            urlretrieve(fits_file_url, filename)
            return i, filename, False
        except (HTTPError, URLError):
            return i, None, True

    # Network I/O bound: parallelize downloads with a small bounded pool.
    n_workers = min(5, len(wav))
    with ThreadPoolExecutor(max_workers=n_workers) as executor:
        futures = [executor.submit(_download_one, i) for i in range(len(wav))]
        for future in as_completed(futures):
            i, filename, this_error = future.result()
            if this_error:
                error = True
                continue
            try:
                aia_maps[i] = Map(filename)
            except Exception:
                error = True

    # Drop failed downloads while preserving wavelength-sorted order.
    aia_maps = [this_map for this_map in aia_maps if this_map is not None]

    if not silent:
        print("Download completed!")
    return aia_maps, full_disk_maps_folder, error


# **********************************************************


def calibrate_full_disk_maps(aia_maps):
    """

    Function for calibrating (i.e., registering) the downloaded full-disk AIA maps


    Parameters
        ----------
        aia_maps: list
            list containing the full-disk AIA maps to be calibrated

    Returns
        -------
        calibrated_aia_maps: list
            list containing the calibrated full-disk AIA maps

    """
    calibrated_aia_maps = []

    for this_map in aia_maps:
        calibrated_aia_maps.append(register(this_map))

    return calibrated_aia_maps


# **********************************************************


# def extract_submap(aia_map, ar_lon, ar_lat, n_pix_x = 500, n_pix_y = 500): ###  previous (working) version
def extract_submap(aia_map, ar_lon, ar_lat, n_pix_x=700, n_pix_y=700):
    """

    Function for extracting submap around an active region from AIA map


    Parameters
        ----------
        aia_map: AIA map structure
            AIA map from which the submap is extracted

        ar_lon: float
            longitude of center of the active region (Heliographic Stonyhurst coordinates)

        ar_lat: float
            latitude of center of the active region (Heliographic Stonyhurst coordinates)

        n_pix_x: integer
            number of pixels of the submap to be extracted; horizontal axis. Default, 500

        n_pix_y: integer
            number of pixels of the submap to be extracted; vertical axis. Default, 500


    Returns
        -------
        submap: AIA map structure
            submap around active region extracted from the AIA map provided as input

    """
    this_coord = SkyCoord(
        ar_lon * u.deg, ar_lat * u.deg, frame=frames.HeliographicStonyhurst
    )  # frame=aia_map.coordinate_frame; x*u.arcsec and y*u.arcsec in helioprojected

    pix_x = aia_map.world_to_pixel(this_coord).x.value
    pix_y = aia_map.world_to_pixel(this_coord).y.value

    top_right = aia_map.pixel_to_world(
        (pix_x + n_pix_x // 2 - 1) * u.pix, (pix_y + n_pix_y // 2 - 1) * u.pix
    )
    bottom_left = aia_map.pixel_to_world(
        (pix_x - n_pix_x // 2) * u.pix, (pix_y - n_pix_y // 2) * u.pix
    )

    submap = aia_map.submap(bottom_left, top_right=top_right)
    submap = Map(submap.data.astype(np.int16), submap.meta)

    return submap


# **********************************************************


##n_pix_x=w/0.6, n_pix_y=h/0.6
def crop_full_disk_maps(
    aia_maps,
    ar_lon,
    ar_lat,
    arnum,
    cropped_maps_folder,
    n_pix_x=1000,
    n_pix_y=1000,
    save_submaps=False,
):
    """

    Function for cropping AIA maps around an active region. The submaps are saved as fits files


    Parameters
        ----------
        aia_maps: list
            list of AIA maps from which the submaps are extracted

        ar_lon: float
            longitude coordinate of the center of the active region (Heliographic Stonyhurst coordinates)

        ar_lat: float
            latitude coordinate of the center of the active region (Heliographic Stonyhurst coordinates)

        arnum: integer
            number of the active region to be extracted

        n_pix_x: integer
            number of pixels of the submap to be extracted; horizontal axis. Default, 1000

        n_pix_y: integer
            number of pixels of the submap to be extracted; vertical axis. Default, 1000


    Returns
        -------
        aia_submaps: list
            list of submaps cropped an around active region which are extracted from the AIA map provided as input

    """
    aia_submaps = []
    for aia_map in aia_maps:
        aia_submap = extract_submap(
            aia_map, ar_lon, ar_lat, n_pix_x=n_pix_x, n_pix_y=n_pix_y
        )
        wav = aia_submap.meta["wavelnth"]

        if save_submaps:
            fitsname = os.path.join(
                cropped_maps_folder,
                "aia_lev1_nrt2_" + str(wav) + "_ar" + str(arnum) + ".fits",
            )
            astropy.io.fits.writeto(
                fitsname,
                aia_submap.data,
                aia_submap.fits_header,
                output_verify="exception",
                overwrite=True,
                checksum=False,
            )

        aia_submaps.append(aia_submap)

    return aia_submaps


# **********************************************************


def write_csv_em(file_name, time_em, total_em, function_csv="a"):
    """

    Function for saving the total EM values in a csv file (row by row)


    Parameters
        ----------
        file_name: string
            filename of teh csv file where the total EM values are saved

        time_em: string
            time corresponding to the total EM value to be saved

        total_em: float
            total EM value to be saved

        function_csv: string
            If function_csv=='w' a new file is created, otherwise a new row is appended into the existing file

    """

    header_csv = ["time_em", "total_em"]

    data = [time_em, total_em]

    with open(file_name, function_csv, encoding="UTF8", newline="") as file_csv:
        writer = csv.writer(file_csv)
        if function_csv == "w":
            writer.writerow(header_csv)
        else:
            writer.writerow(data)


# **********************************************************


def load_em_series(file_name_em_csv, timezone="US/Central", em_cache=None):
    """
    Load total EM time series from CSV with optional file-level cache.

    Parameters
        ----------
        file_name_em_csv: string
            Path of the CSV file containing time_em and total_em columns

        timezone: string
            Name of the timezone used for plotting

        em_cache: dict or None
            Optional cache dictionary keyed by file path
    """
    if em_cache is not None:
        cached = em_cache.get(file_name_em_csv)
        if cached is not None and cached["timezone"] == timezone:
            return cached["time_em_array"], cached["total_em"]

    em_csv = pd.read_csv(file_name_em_csv)
    total_em = np.array(em_csv["total_em"])
    time_em_utc = pd.to_datetime(
        em_csv["time_em"], format="%Y-%m-%dT%H:%M:%SZ", utc=True
    )
    # Convert once with pandas; avoids repeated per-row strptime calls.
    time_em_array = np.array(time_em_utc.dt.tz_convert(timezone).dt.to_pydatetime())

    if em_cache is not None:
        em_cache[file_name_em_csv] = {
            "timezone": timezone,
            "time_em_array": time_em_array,
            "total_em": total_em,
        }

    return time_em_array, total_em


# **********************************************************


def append_em_cache(
    file_name_em_csv, time_em, total_em, timezone="US/Central", em_cache=None
):
    """
    Append one EM sample to in-memory cache to avoid full CSV re-read each cycle.
    """
    if em_cache is None:
        return

    dt_utc = datetime.datetime.strptime(time_em, "%Y-%m-%dT%H:%M:%SZ")
    dt_local = convert_utc_to_timezone(dt_utc, timezone=timezone)
    total_em_val = float(total_em)

    cached = em_cache.get(file_name_em_csv)
    if cached is None or cached.get("timezone") != timezone:
        em_cache[file_name_em_csv] = {
            "timezone": timezone,
            "time_em_array": np.array([dt_local]),
            "total_em": np.array([total_em_val], dtype=float),
        }
        return

    cached["time_em_array"] = np.append(cached["time_em_array"], dt_local)
    cached["total_em"] = np.append(cached["total_em"], total_em_val)


# **********************************************************


def convert_utc_to_timezone(this_datetime, timezone="US/Central"):
    """

    Function for converting input time to a specific time zone


    Parameters
        ----------
        this_datetime: datetime
            Time to be converted to a specific time zone

        timezone: string
            String containing the name of the refernce of the time zone to be used for the discussion

    Returns
        -------
        this_time_new_timezone: datetime
            Time converted to the refernce of the time zone

    """

    utc = _TZ_CACHE.setdefault("UTC", pytz.timezone("UTC"))
    new_timezone = _TZ_CACHE.setdefault(timezone, pytz.timezone(timezone))
    # Accept both naive UTC datetimes and timezone-aware datetimes.
    if this_datetime.tzinfo is None:
        this_time_utc = utc.localize(this_datetime)
    else:
        this_time_utc = this_datetime.astimezone(utc)
    this_time_new_timezone = this_time_utc.astimezone(new_timezone)

    return this_time_new_timezone


# **********************************************************


def prepare_goes_plot_arrays(xrsa_current, xrsb_current, timezone="US/Central"):
    """
    Build GOES plotting arrays once per cycle and reuse across plot functions.
    """
    xrsab_time = xrsa_current["time_tag"]
    goes_time_array = np.array(
        [
            convert_utc_to_timezone(this_time.to_pydatetime(), timezone=timezone)
            for this_time in xrsab_time
        ]
    )
    goes_xrsa_flux = np.array(xrsa_current["flux"])
    goes_xrsb_flux = np.array(xrsb_current["flux"])
    return goes_time_array, goes_xrsa_flux, goes_xrsb_flux


# **********************************************************


def define_ssh_client():
    """

    Function for defining an ssh client object

    Returns
        ----------
        ssh_client: SSHClient object
            ssh client object used for uploading files via scp

    """

    ssh_host = "physics.wku.edu"
    ssh_user = "massa"
    ssh_password = "FF_Proj"  #'waffle!'

    ssh_client = SSHClient()
    ssh_client.load_system_host_keys()
    ssh_client.connect(
        ssh_host, username=ssh_user, password=ssh_password, look_for_keys=True
    )

    return ssh_client


# **********************************************************


def ssh_scp_files(ssh_client, source_volume, destination_volume):
    """

    Function used for uploding files using via scp


    Parameters
        ----------
        ssh_client: SSHClient object
            ssh client object connected to the server

        source_volume: string
            path of the folder to be uploaded via scp

        destination_volume: string
            path of the folder where the files are uploaded via scp

    """

    with SCPClient(ssh_client.get_transport()) as scp:
        scp.put(source_volume, recursive=True, remote_path=destination_volume)


# **********************************************************


def _suvi_wav_path(wav):
    return "094" if int(wav) == 94 else "131"


def resolve_suvi_day_url(day_utc, wavelength=131, spacecraft="primary"):
    """
    Resolve SUVI flare-location image URL for a UTC day by scanning SWPC directory listing.
    Uses the nearest available file on or before the requested day.
    Returns None if no dated file can be resolved.
    """
    wav_dir = _suvi_wav_path(wavelength)
    base = f"https://services.swpc.noaa.gov/images/flares/hgs/{spacecraft}/{wav_dir}/"
    day_key = str(day_utc) if day_utc is not None else ""
    cache_key = (spacecraft, wav_dir, day_key)
    if cache_key in _SUVI_URL_CACHE:
        return _SUVI_URL_CACHE[cache_key]

    # If no day is provided, just use latest.
    if not day_key:
        _SUVI_URL_CACHE[cache_key] = None
        return None

    try:
        dt = datetime.datetime.strptime(day_key, "%Y-%m-%d")
    except ValueError:
        _SUVI_URL_CACHE[cache_key] = None
        return None

    target_day = dt.strftime("%Y%m%d")
    try:
        with urlopen(base, timeout=8) as r:
            html = r.read().decode("utf-8", errors="ignore")
        # Keep pngs with parseable YYYYMMDD token and pick nearest <= target day.
        hrefs = re.findall(r'href="([^"]+\.png)"', html)
        dated = []
        for h in hrefs:
            if not h.lower().endswith(".png"):
                continue
            m = re.search(r"(\d{8})", h)
            if not m:
                continue
            d = m.group(1)
            if d <= target_day:
                dated.append((d, h))
        if dated:
            # latest available at or before requested day
            pick = sorted(dated, key=lambda x: (x[0], x[1]))[-1][1]
            if pick.startswith("http"):
                resolved = pick
            else:
                resolved = base + pick.lstrip("./")
            _SUVI_URL_CACHE[cache_key] = resolved
            return resolved
    except Exception:
        pass

    _SUVI_URL_CACHE[cache_key] = None
    return None


# **********************************************************


def fetch_suvi_image_for_panel(
    suvi_top_wavelength=131,
    suvi_day_utc=None,
    suvi_use_realtime=False,
):
    """
    Fetch SUVI flare-location image for embedding in the full-disk panel figure.
    Returns (image_array_or_none, title_string).
    """
    suvi_wav = 94 if int(suvi_top_wavelength) == 94 else 131
    wav_dir = _suvi_wav_path(suvi_wav)

    if suvi_use_realtime:
        suvi_src = f"https://services.swpc.noaa.gov/images/flares/hgs/primary/{wav_dir}/latest.png"
        title = f"SUVI {suvi_wav}Å"
    else:
        suvi_src = resolve_suvi_day_url(
            suvi_day_utc,
            wavelength=suvi_wav,
            spacecraft="primary",
        )
        title = f"SUVI {suvi_wav}Å"

    if not suvi_src:
        return None, title + " - not available"

    cached = _SUVI_IMAGE_CACHE.get(suvi_src)
    if cached is not None:
        return cached, title

    try:
        with urlopen(suvi_src, timeout=12) as r:
            img_bytes = r.read()
        with Image.open(io.BytesIO(img_bytes)) as im:
            arr = np.asarray(im.convert("RGB"))
        _SUVI_IMAGE_CACHE.clear()
        _SUVI_IMAGE_CACHE[suvi_src] = arr
        return arr, title
    except Exception:
        return None, title + " - unavailable"


# **********************************************************


def publish_local_files(
    source_volume,
    destination_volume,
    suvi_top_wavelength=131,
    suvi_day_utc=None,
    suvi_use_realtime=False,
):
    """
    Publish latest output files to a local folder (e.g., local web root).

    The destination folder is replaced each cycle to mirror source contents.
    """
    mkdir(destination_volume)
    latest_plots_dir = os.path.join(destination_volume, "latest_plots")
    mkdir(latest_plots_dir)

    source_names = set(os.listdir(source_volume))
    dest_names = set(os.listdir(latest_plots_dir))

    # Remove stale files that are no longer produced.
    for stale_name in dest_names - source_names:
        stale_path = os.path.join(latest_plots_dir, stale_name)
        if os.path.isdir(stale_path):
            shutil.rmtree(stale_path)
        else:
            os.remove(stale_path)

    # Copy only new/changed files.
    for name in source_names:
        src = os.path.join(source_volume, name)
        dst = os.path.join(latest_plots_dir, name)
        if os.path.isdir(src):
            if os.path.exists(dst):
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
        else:
            if (
                os.path.exists(dst)
                and os.path.getsize(src) == os.path.getsize(dst)
                and int(os.path.getmtime(src)) == int(os.path.getmtime(dst))
            ):
                continue
            shutil.copy2(src, dst)

    index_html = ""
    template_path = os.path.join(os.getcwd(), "wku_template.html")
    if os.path.exists(template_path):
        with open(template_path, "r", encoding="utf-8") as f:
            index_html = f.read()
    else:
        index_html = """<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no"><title>WAFFLE v1</title></head><body><center><img id="image0" src="./latest_plots/full_disk_maps.gif" style="max-width:100%;height:auto;"><br><img id="image1" src="./latest_plots/em_goes_plot.png" style="max-width:100%;height:auto;"><script>setInterval(function(){var t=new Date().getTime();document.getElementById("image0").src="./latest_plots/full_disk_maps.gif?t="+t;document.getElementById("image1").src="./latest_plots/em_goes_plot.png?t="+t;},15000);</script></center></body></html>"""

    suvi_wav = 94 if int(suvi_top_wavelength) == 94 else 131
    wav_dir = _suvi_wav_path(suvi_wav)
    if suvi_use_realtime:
        suvi_src = f"https://services.swpc.noaa.gov/images/flares/hgs/primary/{wav_dir}/latest.png"
    else:
        suvi_src = resolve_suvi_day_url(
            suvi_day_utc,
            wavelength=suvi_wav,
            spacecraft="primary",
        )
        if not suvi_src:
            suvi_src = ""
    index_html = index_html.replace("__SUVI_TOP_WAVELENGTH__", str(suvi_wav))
    index_html = index_html.replace("__SUVI_TOP_SRC__", suvi_src)

    with open(
        os.path.join(destination_volume, "index.html"), "w", encoding="utf-8"
    ) as f:
        f.write(index_html)


# **********************************************************


def select_data_to_download(
    start_time_series, grouped_wav, current_time_ut, wavelengths_needed
):
    """

    Function used for selecting the latest AIA data to be downloaded


    Parameters
        ----------
        start_time_series: list
            list containing the start time of each cycle of AIA data that has been queried

        grouped_wav: list
            list containing the wavelength numbers of the AIA data in each 12s cycle

        current_time_ut: datetime
            Time of the latest data that have already been downloaded. It is used for donwloading only new data

        wavelengths_needed: list
            List containing the wavelengths of the AIA data that need to be downloaded


    Returns
        ----------
        idx: index of the 12s cycle of AIA data to be downloaded

    """

    if len(start_time_series) == 0:
        return -1

    # Pick the earliest valid cycle strictly after the current reference time.
    for idx in range(len(start_time_series)):
        this_start_time = start_time_series[idx]
        this_grouped_wav = grouped_wav[idx]
        cond = (this_start_time > current_time_ut) and np.all(
            np.isin(wavelengths_needed, this_grouped_wav)
        )
        if cond:
            return idx

    return -1


# **********************************************************


def create_animation_from_images(
    folder_name, animation_filename="animation.gif", fps=2
):
    """

    Function used for creating a gif animation from the plots of the full-disk AIA images


    Parameters
        ----------
        folder_name: string
            path of the folder containing the png files that are used for creating the gif file

        animation_filename: string
            File name of the gif file to be created

         fps: integer
             number of frames per second for the gif

    """

    # Use only full-disk frames used by this animation.
    image_files = sorted(glob.glob(os.path.join(folder_name, "aia_full_disk_*.png")))

    if not image_files:
        raise ValueError("No image files found in the folder.")

    image_files = image_files[-10:]
    image_files.append(image_files[-1])
    image_files.append(image_files[-1])
    image_files.append(image_files[-1])

    duration_ms = max(1, int(1000 / max(1, fps)))
    frames = []
    for file_name in image_files:
        with Image.open(file_name) as img:
            frames.append(img.convert("P", palette=Image.Palette.ADAPTIVE))

    animation_path = os.path.join(animation_filename)
    frames[0].save(
        animation_path,
        save_all=True,
        append_images=frames[1:],
        duration=duration_ms,
        loop=0,
        optimize=False,
    )

    # Explicitly release image buffers.
    for frame in frames:
        try:
            frame.close()
        except Exception:
            pass
    del frames


# **********************************************************


def prune_full_disk_images(plots_folder, keep_last=30):
    """
    Keep only the latest full-disk PNG files to avoid unbounded folder growth.

    Parameters
        ----------
        plots_folder: string
            Path of the folder containing full-disk plots

        keep_last: integer
            Number of latest files to keep
    """
    if keep_last <= 0:
        return

    image_files = sorted(glob.glob(os.path.join(plots_folder, "aia_full_disk_*.png")))
    if len(image_files) <= keep_last:
        return

    for old_file in image_files[:-keep_last]:
        try:
            os.remove(old_file)
        except OSError:
            continue


# **********************************************************


def em_scale(y):
    """

    Function for scaling the high temperature EM maps


    Parameters
        ----------
        y: numpy array containing the high temperature EM map


    Returns
        ----------
        Scaled high temperature EM map

    """
    return y / 1e50


# **********************************************************


def em_unscale(y):
    """

    Function for unscaling the high temperature EM maps


    Parameters
        ----------
        y: numpy array containing the high temperature EM maps


    Returns
        ----------
        Unscaled high temperature EM maps

    """

    return 1e50 * y


# **********************************************************


def img_scale(x):
    """

    Function for scaling the AIA maps to be used for computing the high temperature EM maps by means of a linear combination of
    the AIA channels


    Parameters
        ----------
        x: numpy array containing the AIA images to be scaled


    Returns
        ----------
        Scaled AIA maps

    """
    x2 = x
    bad = np.where(x2 <= 0.0)
    if len(bad[0]) > 0:
        x2[bad] = 0.0
    return x2 / 2e4


# **********************************************************


def img_unscale(x):
    """

    Function for unscaling the AIA maps to be used for computing the high temperature EM maps by means of a linear combination of
    the AIA channels


    Parameters
        ----------
        x: numpy array containing the AIA images to be unscaled


    Returns
        ----------
        Unscaled AIA maps

    """
    return x * 2e4


# **********************************************************


def compute_em_map(aia_img, metadata, weights):
    """

    Function for computing the high temperature EM maps by means of a linear combination of the different AIA channels

    Parameters
        ----------
        aia_img: numpy array containing the AIA images to be used for computing the high temperature EM maps

        metadata: sunpy.util.metadata.MetaDict. Metadata to be used for making an EM map

        weights: list of floats to be used for computing the EM map by means of a linear combination of the AIA images

    Returns
        ----------
        High temperature EM map

    """

    dim = aia_img.shape

    em_map = np.zeros((dim[0], dim[1]))

    for i in range(len(weights)):
        em_map += img_scale(aia_img[:, :, i]) * weights[i]

    return Map(em_unscale(em_map), metadata)


# **********************************************************
# def plot_results(plots_folder, aia_submaps, em_map, xrsa_current, xrsb_current, arnum, i, file_name_em_csv,
#                  timezone='US/Central'):
#     """

#     Function for plotting the high temperature EM map and the evolution of the high temperature total EM
#     of a specific active region

#     Parameters
#         ----------
#         plots_folder: string
#             path of the folder where the plots are saved

#         aia_submaps: list
#             list containing the AIA submaps (around the considered active region) to be plotted

#         em_map: map
#             high temperature emission measure map to be plotted

#         xrsa_current:
#             latest GOES XRSA data to be plotted

#         xrsb_current:
#             latest GOES XRSB data to be plotted

#         arnum: int,
#             number of the considered active region

#         i: integer
#             index of the considered active region (1, 2, or 3). Used for defining the filename of the AR plot

#         file_name_em_csv: string
#             path of the csv file containing the total EM values for the considered AR

#         timezone: string
#             Name of the time zone considered for printing the time of the considered data

#     """

#     # Order aia maps with respect to temperature response
#     ordered_wav = [171,193,211,131,94]

#     wav_maps = []
#     for jj in range(5):
#         wav_maps.append(aia_submaps[jj].meta['wavelnth'])
#     wav_maps = np.array(wav_maps)

#     ordered_aia_maps = []
#     for jj in range(5):
#         idx = np.where(wav_maps == ordered_wav[jj])
#         ordered_aia_maps.append(aia_submaps[idx[0][0]])

#     xrsab_time = xrsa_current['time_tag']
#     goes_time_array  = []

#     for j in range(len(xrsab_time)):

#         this_utc_time        = xrsab_time[j].to_pydatetime()#datetime.fromtimestamp(xrsab_time[j])
#         this_new_timezone_time = convert_utc_to_timezone(this_utc_time)
#         goes_time_array.append(this_new_timezone_time)

#     goes_time_array = np.array(goes_time_array)
#     goes_xrsa_flux  = xrsa_current['flux']
#     goes_xrsb_flux  = xrsb_current['flux']

#     # Plot AIA submaps
#     fig, ax = plt.subplots(figsize=(22,10))

#     ax1 = plt.subplot2grid((2,5), (0,0), colspan=1, projection=ordered_aia_maps[0])
#     ax2 = plt.subplot2grid((2,5), (0,1), colspan=1, projection=ordered_aia_maps[1])
#     ax3 = plt.subplot2grid((2,5), (0,2), colspan=1, projection=ordered_aia_maps[2])
#     ax4 = plt.subplot2grid((2,5), (0,3), colspan=1, projection=ordered_aia_maps[3])
#     ax5 = plt.subplot2grid((2,5), (0,4), colspan=1, projection=ordered_aia_maps[4])
#     ax6 = plt.subplot2grid((2,5), (1,0), colspan=2, projection=em_map)
#     ax7 = plt.subplot2grid((2,5), (1,2), colspan=3)

#     plt.subplots_adjust(left=0.1,
#                     bottom=0.1,
#                     right=0.9,
#                     top=0.9,
#                     wspace=0.4,
#                     hspace=0.4)

#     # Define axes list
#     ax = [ax1, ax2, ax3, ax4, ax5]

#     labelsize = 15
#     ticksize  = 15
#     chsize  = 15
#     legsize = 15
#     xlabel = "Solar X [arcsec]"
#     ylabel = "Solar Y [arcsec]"
#     for jj in range(5):

#         ordered_aia_maps[jj].plot(axes=ax[jj])

#         ax[jj].set_title('AIA ' + str(ordered_aia_maps[jj].meta['wavelnth']) + 'Å', fontsize=labelsize)
#         ax[jj].set_xlabel(xlabel,fontsize=labelsize)
#         ax[jj].set_ylabel(ylabel,fontsize=labelsize)
#         ax[jj].tick_params(axis='x', labelsize=ticksize)
#         ax[jj].tick_params(axis='y', labelsize=ticksize)

#     # Plot EM map
#     title  = 'AIA Emission Measure \n (T $\geq 10^{6.6}$ K)'
#     em_map.plot_settings['norm'] = colors.LogNorm(vmin=1e42, vmax=1e45, clip=True)
#     em_map.plot_settings['cmap'] = matplotlib.cm.get_cmap('CMRmap')

#     im = em_map.plot(axes=ax6)

#     ax6.grid(False)
#     ax6.set_title(title,fontsize=labelsize)
#     ax6.set_xlabel(xlabel,fontsize=labelsize)
#     ax6.set_ylabel(ylabel,fontsize=labelsize)
#     ax6.tick_params(axis='x', labelsize=ticksize)
#     ax6.tick_params(axis='y', labelsize=ticksize)

#     cax = fig.add_axes([ax6.get_position().x1+0.01,ax6.get_position().y0,0.01,ax6.get_position().height])
#     cbar = fig.colorbar(im,cax=cax)#,ticks=cbarticks)
#     cbar.ax.tick_params(labelsize=labelsize)
#     cbar.ax.set_ylabel('EM [cm$^{-3}$ pixel$^{-1}$]',fontsize=labelsize)

#     # Plot total EM and GOES
#     em_csv   = pd.read_csv(file_name_em_csv)
#     time_em  = np.array(em_csv['time_em'])
#     total_em = np.array(em_csv['total_em'])

#     # Define time array
#     time_em_array = []
#     for j in range(len(time_em)):
#         this_ut_time   = datetime.datetime.strptime(time_em[j], '%Y-%m-%dT%H:%M:%SZ')
#         this_new_timezone_time = convert_utc_to_timezone(this_ut_time, timezone=timezone)
#         time_em_array.append(this_new_timezone_time)

#     time_em_array      = np.array(time_em_array)

#     # Minimum and maximum times to be displayed in the plots
#     min_time = np.max(np.array([time_em_array[-1] - timedelta(minutes=25), np.min(goes_time_array)]))
#     max_time = np.max(goes_time_array)

#     # Make plot
#     ax7.plot(goes_time_array,goes_xrsa_flux, 'gray', label='GOES XRSA', linestyle='-.')
#     ax7.plot(goes_time_array,goes_xrsb_flux, 'black', label='GOES XRSB', linestyle='dashed')
#     ax7.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M', tz=tz.gettz(timezone)))
#     ax7.xaxis.set_major_locator(mdates.MinuteLocator(interval=5))
#     ax7.set_yscale('log')
#     ax7.tick_params(axis="x", labelsize=chsize)
#     ax7.tick_params(axis="y", labelsize=chsize)
#     ax7.set(xlabel='Time (' + time_em_array[-1].strftime("%d-%m-%Y") + ')')
#     ax7.set(ylabel='GOES level')#
#     # ax7.set_title('AIA data time - ' + time_em_array[-1].strftime("%H:%M:%S") + ' ' + timezone, fontsize=chsize*2)
#     ax7.xaxis.label.set_size(chsize)
#     # ax7.set_xticks(goes_time_array[::2])
#     # ax7.set_xticklabels(goes_time_array[::2], rotation=45)
#     ax7.yaxis.label.set_size(chsize)
#     ax7.set_xlim((min_time,max_time))
#     ax7.set_ylim(1e-8, 1e-4)
#     ax7.set_yticks([1e-8, 1e-7, 1e-6, 1e-5, 1e-4])
#     ax7.set_yticklabels(["A", "B", "C", "M", "X"])
#     #ax7.yticks(ticks=[1e-8, 1e-7, 1e-6, 1e-5, 1e-4], labels=["A", "B", "C", "M", "X"])
#     ax7.grid(True)


#     color = 'black'
#     ax7.tick_params(axis='y', labelcolor=color)
#     ax7.yaxis.label.set_color(color)

#     ax8 = ax7.twinx()
#     ax8.plot(time_em_array,total_em, 'r', label='AIA EM')
#     ax8.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M', tz=tz.gettz(timezone)))
#     ax8.set_yscale('log')
#     ax8.set_ylim(1e46, 1e50)
#     ax8.set_xlim((min_time,max_time))
#     ax8.tick_params(axis="x", labelsize=chsize)
#     ax8.set(ylabel='EM [cm$^{-3}$]')
#     ax8.tick_params(axis="y", labelsize=chsize)
#     ax8.yaxis.label.set_size(chsize)
#     color = 'red'
#     ax8.tick_params(axis='y', labelcolor=color)
#     ax8.yaxis.label.set_color(color)
#     ax8.spines['right'].set_color(color)
#     #ax8.spines['left'].set_color('blue')

#     fig.legend(bbox_to_anchor=(0.09, 0.05, 0.45, 0.38), fontsize=legsize)

#     fig.suptitle('AR ' + str(arnum) + ' - ' + time_em_array[-1].strftime("%H:%M:%S") + ' ' + timezone, fontsize=25)


#     plt.savefig(os.path.join(plots_folder, 'aia_em_' + str(i))  , dpi=100,bbox_inches='tight')
def plot_results(
    plots_folder,
    aia_submaps,
    em_map,
    xrsa_current,
    xrsb_current,
    arnum,
    label,
    i,
    file_name_em_csv,
    timezone="US/Central",
    em_cache=None,
    ar_color="red",
    goes_plot_data=None,
    output_prefix="aia_em_",
    em_label_suffix="",
):
    """

    Function for plotting the high temperature EM map and the evolution of the high temperature total EM
    of a specific active region

    Parameters
        ----------
        plots_folder: string
            path of the folder where the plots are saved

        aia_submaps: list
            list containing the AIA submaps (around the considered active region) to be plotted

        em_map: map
            high temperature emission measure map to be plotted

        xrsa_current:
            latest GOES XRSA data to be plotted

        xrsb_current:
            latest GOES XRSB data to be plotted

        arnum: int,
            number of the considered active region

        i: integer
            index of the considered active region (1, 2, or 3). Used for defining the filename of the AR plot

        file_name_em_csv: string
            path of the csv file containing the total EM values for the considered AR

        timezone: string
            Name of the time zone considered for printing the time of the considered data

    """

    # Order aia maps with respect to temperature response
    ordered_wav = [171, 193, 211, 131, 94]

    wav_maps = []
    for jj in range(5):
        wav_maps.append(aia_submaps[jj].meta["wavelnth"])
    wav_maps = np.array(wav_maps)

    ordered_aia_maps = []
    for jj in range(5):
        idx = np.where(wav_maps == ordered_wav[jj])
        ordered_aia_maps.append(aia_submaps[idx[0][0]])

    if goes_plot_data is None:
        goes_time_array, goes_xrsa_flux, goes_xrsb_flux = prepare_goes_plot_arrays(
            xrsa_current, xrsb_current, timezone=timezone
        )
    else:
        goes_time_array, goes_xrsa_flux, goes_xrsb_flux = goes_plot_data

    # Plot AIA submaps
    fig = plt.figure(figsize=(22, 10))

    ax1 = plt.subplot2grid((2, 5), (0, 0), colspan=1, projection=ordered_aia_maps[0])
    ax2 = plt.subplot2grid((2, 5), (0, 1), colspan=1, projection=ordered_aia_maps[1])
    ax3 = plt.subplot2grid((2, 5), (0, 2), colspan=1, projection=ordered_aia_maps[2])
    ax4 = plt.subplot2grid((2, 5), (0, 3), colspan=1, projection=ordered_aia_maps[3])
    ax5 = plt.subplot2grid((2, 5), (0, 4), colspan=1, projection=ordered_aia_maps[4])
    ax6 = plt.subplot2grid((2, 5), (1, 0), colspan=2, projection=em_map)
    ax7 = plt.subplot2grid((2, 5), (1, 2), colspan=3)

    plt.subplots_adjust(
        left=0.1, bottom=0.1, right=0.9, top=0.9, wspace=0.4, hspace=0.4
    )

    # Define axes list
    ax = [ax1, ax2, ax3, ax4, ax5]

    labelsize = 15
    ticksize = 15
    chsize = 15
    legsize = 15
    xlabel = "Solar X [arcsec]"
    ylabel = "Solar Y [arcsec]"
    for jj in range(5):
        ordered_aia_maps[jj].plot(axes=ax[jj])

        ax[jj].set_title(
            "AIA " + str(ordered_aia_maps[jj].meta["wavelnth"]) + "Å",
            fontsize=labelsize,
        )
        ax[jj].set_xlabel(xlabel, fontsize=labelsize)
        ax[jj].set_ylabel(ylabel, fontsize=labelsize)
        ax[jj].tick_params(axis="x", labelsize=ticksize)
        ax[jj].tick_params(axis="y", labelsize=ticksize)

    # Plot EM map
    title = "AIA Emission Measure"
    if em_label_suffix:
        title += f" ({em_label_suffix})"
    title += " \n (T $\\geq 10^{6.6}$ K)"
    em_map.plot_settings["norm"] = colors.LogNorm(vmin=1e42, vmax=1e45, clip=True)
    em_map.plot_settings["cmap"] = matplotlib.cm.get_cmap("CMRmap")

    im = em_map.plot(axes=ax6)

    ax6.grid(False)
    ax6.set_title(title, fontsize=labelsize)
    ax6.set_xlabel(xlabel, fontsize=labelsize)
    ax6.set_ylabel(ylabel, fontsize=labelsize)
    ax6.tick_params(axis="x", labelsize=ticksize)
    ax6.tick_params(axis="y", labelsize=ticksize)

    cax = fig.add_axes(
        [
            ax6.get_position().x1 + 0.01,
            ax6.get_position().y0,
            0.01,
            ax6.get_position().height,
        ]
    )
    cbar = fig.colorbar(im, cax=cax)  # ,ticks=cbarticks)
    cbar.ax.tick_params(labelsize=labelsize)
    cbar.ax.set_ylabel("EM [cm$^{-3}$ pixel$^{-1}$]", fontsize=labelsize)

    # Plot total EM and GOES
    time_em_array, total_em = load_em_series(
        file_name_em_csv, timezone=timezone, em_cache=em_cache
    )

    # Detailed-analysis view: 2.5 hour history anchored to the latest EM point.
    min_time = time_em_array[-1] - timedelta(minutes=150)
    max_time = time_em_array[-1]
    if len(goes_time_array) > 0:
        goes_mask = (goes_time_array >= min_time) & (goes_time_array <= max_time)
        goes_time_array = goes_time_array[goes_mask]
        goes_xrsa_flux = np.array(goes_xrsa_flux)[goes_mask]
        goes_xrsb_flux = np.array(goes_xrsb_flux)[goes_mask]

    # Make plot
    if len(goes_time_array) > 0:
        ax7.plot(
            goes_time_array, goes_xrsa_flux, "gray", label="GOES XRSA", linestyle="-."
        )
        ax7.plot(
            goes_time_array,
            goes_xrsb_flux,
            "black",
            label="GOES XRSB",
            linestyle="dashed",
        )
    ax7.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=tz.gettz(timezone)))
    ax7.xaxis.set_major_locator(mdates.MinuteLocator(interval=20))
    ax7.set_yscale("log")
    ax7.tick_params(axis="x", labelsize=chsize)
    ax7.tick_params(axis="y", labelsize=chsize)
    ax7.set(xlabel="Time (" + time_em_array[-1].strftime("%m/%d/%Y") + ")")
    ax7.set(ylabel="GOES level")  #
    # ax7.set_title('AIA data time - ' + time_em_array[-1].strftime("%H:%M:%S") + ' ' + timezone, fontsize=chsize*2)
    ax7.xaxis.label.set_size(chsize)
    # ax7.set_xticks(goes_time_array[::2])
    # ax7.set_xticklabels(goes_time_array[::2], rotation=45)
    ax7.yaxis.label.set_size(chsize)
    ax7.set_xlim((min_time, max_time))
    ax7.set_ylim(1e-8, 1e-4)
    ax7.set_yticks([1e-8, 1e-7, 1e-6, 1e-5, 1e-4])
    ax7.set_yticklabels(["A", "B", "C", "M", "X"])
    # ax7.yticks(ticks=[1e-8, 1e-7, 1e-6, 1e-5, 1e-4], labels=["A", "B", "C", "M", "X"])
    ax7.grid(True)

    color = "black"
    ax7.tick_params(axis="y", labelcolor=color)
    ax7.yaxis.label.set_color(color)

    ax8 = ax7.twinx()
    em_mask = time_em_array >= min_time
    ax8.plot(time_em_array[em_mask], total_em[em_mask], color=ar_color, label="AIA EM")
    ax8.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=tz.gettz(timezone)))
    ax8.set_yscale("log")
    ax8.set_ylim(1e46, 1e50)
    ax8.set_xlim((min_time, max_time))
    ax8.tick_params(axis="x", labelsize=chsize)
    ax8.set(ylabel="EM [cm$^{-3}$]")
    ax8.tick_params(axis="y", labelsize=chsize)
    ax8.yaxis.label.set_size(chsize)
    color = ar_color
    ax8.tick_params(axis="y", labelcolor=color)
    ax8.yaxis.label.set_color(color)
    ax8.spines["right"].set_color(color)
    # ax8.spines['left'].set_color('blue')

    fig.legend(bbox_to_anchor=(0.09, 0.05, 0.45, 0.38), fontsize=legsize)

    fig.suptitle(
        label
        + " "
        + str(arnum)
        + " - "
        + time_em_array[-1].strftime("%H:%M:%S")
        + " "
        + timezone,
        fontsize=25,
    )

    plt.savefig(
        os.path.join(plots_folder, output_prefix + str(i)), dpi=85, bbox_inches="tight"
    )
    plt.close(fig)


# **********************************************************


def load_realtime_XRS(goes_folder, reference_time_ut=None):
    """

    Function for loading the latest GOES XRS data (taken from https://github.com/pet00184/flarepred)

    Parameters
        ----------
        goes_folder: string
            path of the folder where the goes data are saved

    """

    # SWPC-only mode: use the same corrected `flux` values as the original method.
    # reference_time_ut is intentionally ignored in this mode.
    json_url = "https://services.swpc.noaa.gov/json/goes/primary/xrays-7-day.json"
    with urlopen(json_url, timeout=15) as r:
        payload = r.read().decode("utf-8", errors="strict")
    df = pd.DataFrame(json.loads(payload))

    xrsa_current = df[df.energy == "0.05-0.4nm"][["time_tag", "flux", "energy"]].copy()
    xrsb_current = df[df.energy == "0.1-0.8nm"][["time_tag", "flux", "energy"]].copy()
    xrsa_current["time_tag"] = pd.to_datetime(
        xrsa_current["time_tag"], format="%Y-%m-%dT%H:%M:%SZ", utc=True
    )
    xrsb_current["time_tag"] = pd.to_datetime(
        xrsb_current["time_tag"], format="%Y-%m-%dT%H:%M:%SZ", utc=True
    )
    xrsa_current["flux"] = pd.to_numeric(xrsa_current["flux"], errors="coerce")
    xrsb_current["flux"] = pd.to_numeric(xrsb_current["flux"], errors="coerce")
    xrsa_current = xrsa_current.dropna(subset=["time_tag", "flux"])
    xrsb_current = xrsb_current.dropna(subset=["time_tag", "flux"])

    # Align channels by common timestamps so plotting masks always match.
    merged = xrsa_current[["time_tag", "flux"]].merge(
        xrsb_current[["time_tag", "flux"]],
        on="time_tag",
        how="inner",
        suffixes=("_a", "_b"),
    )
    xrsa_current = pd.DataFrame(
        {
            "time_tag": merged["time_tag"],
            "flux": merged["flux_a"],
            "energy": "0.05-0.4nm",
        }
    ).reset_index(drop=True)
    xrsb_current = pd.DataFrame(
        {
            "time_tag": merged["time_tag"],
            "flux": merged["flux_b"],
            "energy": "0.1-0.8nm",
        }
    ).reset_index(drop=True)

    return xrsa_current.iloc[-100:].reset_index(drop=True), xrsb_current.iloc[
        -100:
    ].reset_index(drop=True)


# **********************************************************
# def plot_em_maps_and_curves(em_maps, total_em_folder,xrsa_current, xrsb_current,arnum,plots_folder,color_arr,ar_lon,ar_lat,
#                             timezone='US/Central'):
#     """

#     Function for plotting the high temperature EM maps and the evolution of the high temperature total EM
#     curves for the considered active regions

#     Parameters
#         ----------
#         em_maps: list
#             list containing the high temperature EM maps to be plotted

#         total_em_folder: string
#             path of the folder containing the cvs files with the time evolution of the total EM of the different ARs

#         xrsa_current:
#             latest GOES XRSA data to be plotted

#         xrsb_current:
#             latest GOES XRSB data to be plotted

#         arnum: list
#             list containing the number of the considered ARs

#         plots_folder: string
#             path of the folder where the plots are saved

#         color_arr: list of strings
#             colors that are used for plotting the boxes and the corresponnding lightcurves

#         timezone: string
#             Name of the time zone considered for printing the time of the considered data

#     """

#     xrsab_time = xrsa_current['time_tag']
#     goes_time_array  = []

#     for j in range(len(xrsab_time)):

#             this_utc_time        = xrsab_time[j].to_pydatetime()#datetime.fromtimestamp(xrsab_time[j])
#             this_new_timezone_time = convert_utc_to_timezone(this_utc_time)
#             goes_time_array.append(this_new_timezone_time)

#     goes_time_array = np.array(goes_time_array)
#     goes_xrsa_flux  = xrsa_current['flux']
#     goes_xrsb_flux  = xrsb_current['flux']

#     # Plot AIA submaps
#     fig, ax = plt.subplots(figsize=(25,8))

#     ax1 = plt.subplot2grid((10,20), (0,0), rowspan=4, colspan=3, projection=em_maps[0])
#     ax2 = plt.subplot2grid((10,20), (0,4), rowspan=4, colspan=3, projection=em_maps[1])
#     ax3 = plt.subplot2grid((10,20), (0,8), rowspan=4, colspan=3, projection=em_maps[2])

#     ax4 = plt.subplot2grid((10,20), (5,0), rowspan=4, colspan=3, projection=em_maps[3])
#     ax5 = plt.subplot2grid((10,20), (5,4), rowspan=4, colspan=3, projection=em_maps[4])
#     ax6 = plt.subplot2grid((10,20), (5,8), rowspan=4, colspan=3, projection=em_maps[5])


#     ax7 = plt.subplot2grid((10,20), (1,13), rowspan=5, colspan=7)

#     plt.subplots_adjust(left=0.1,
#                         bottom=0.1,
#                         right=0.9,
#                         top=0.9,
#                         wspace=0.5,
#                         hspace=0.4)

#     # Define axes list
#     ax = [ax1, ax2, ax3, ax4, ax5, ax6, ax7]

#     labelsize = 15
#     ticksize  = 15
#     chsize  = 15
#     legsize = 15
#     xlabel = " "
#     ylabel = " "

#     for jj in range(len(arnum)):

#         #title  = 'AIA EM - AR ' + str(arnum[jj]) #+ ' \n (T $\geq 10^{6.6}$ K)'
#         title = 'AR ' + str(arnum[jj]) + ' ('+str(int(ar_lon[jj]))+','+str(int(ar_lat[jj]))+')'
#         em_maps[jj].plot_settings['norm'] = colors.LogNorm(vmin=1e42, vmax=1e45, clip=True)
#         em_maps[jj].plot_settings['cmap'] = matplotlib.cm.get_cmap('CMRmap')

#         im = em_maps[jj].plot(axes=ax[jj])

#         ax[jj].grid(False)
#         ax[jj].set_title(title,fontsize=labelsize, color=color_arr[jj])
#         ax[jj].set_xlabel(xlabel,fontsize=labelsize)
#         ax[jj].set_ylabel(ylabel,fontsize=labelsize)
#         ax[jj].tick_params(axis='x', labelsize=ticksize)
#         ax[jj].tick_params(axis='y', labelsize=ticksize)

#         if jj==2 or jj==5:

#             cax = fig.add_axes([ax[jj].get_position().x1+0.01,ax[jj].get_position().y0,0.01,ax[jj].get_position().height])
#             cbar = fig.colorbar(im,cax=cax)#,ticks=cbarticks)
#             cbar.ax.tick_params(labelsize=labelsize)
#             cbar.ax.set_ylabel('EM [cm$^{-3}$ pixel$^{-1}$]',fontsize=labelsize)


#     # Plot EM and GOES curves
#     em_csv   = pd.read_csv(os.path.join(total_em_folder,'total_em_'+str(arnum[0])+'.csv'))
#     time_em  = np.array(em_csv['time_em'])
#     total_em = np.array(em_csv['total_em'])

#     # Define time array
#     time_em_array = []
#     for j in range(len(time_em)):
#         this_ut_time   = datetime.datetime.strptime(time_em[j], '%Y-%m-%dT%H:%M:%SZ')
#         this_new_timezone_time = convert_utc_to_timezone(this_ut_time, timezone=timezone)
#         time_em_array.append(this_new_timezone_time)

#     time_em_array = np.array(time_em_array)

#     # Minimum and maximum times to be displayed in the plots
#     min_time = np.max(np.array([time_em_array[-1] - timedelta(minutes=25), np.min(goes_time_array)]))
#     max_time = np.max(goes_time_array)

#     ax7.plot(goes_time_array,goes_xrsa_flux, 'gray', label='GOES XRSA', linestyle='-.')
#     ax7.plot(goes_time_array,goes_xrsb_flux, 'black', label='GOES XRSB', linestyle='dashed')
#     ax7.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M', tz=tz.gettz(timezone)))
#     ax7.xaxis.set_major_locator(mdates.MinuteLocator(interval=5))
#     ax7.set_yscale('log')
#     ax7.tick_params(axis="x", labelsize=chsize)
#     ax7.tick_params(axis="y", labelsize=chsize)
#     ax7.set_title('Latest AIA data: - ' + time_em_array[-1].strftime("%H:%M:%S") + ' ' + timezone, fontsize=chsize*1.5)
#     ax7.set(xlabel='Time (' + time_em_array[-1].strftime("%d-%m-%Y") + ')')
#     ax7.set(ylabel='GOES level')
#     ax7.xaxis.label.set_size(chsize)
#     ax7.yaxis.label.set_size(chsize)
#     ax7.set_xlim((min_time,max_time))
#     ax7.set_ylim(1e-8, 1e-4)
#     ax7.set_yticks([1e-8, 1e-7, 1e-6, 1e-5, 1e-4])
#     ax7.set_yticklabels(["A", "B", "C", "M", "X"])
#     ax7.grid(True)


#     color = 'black'
#     ax7.tick_params(axis='y', labelcolor=color)
#     ax7.yaxis.label.set_color(color)

#     ax8 = ax7.twinx()


#     for i in range(len(arnum)):
#         em_csv   = pd.read_csv(os.path.join(total_em_folder,'total_em_'+str(arnum[i])+'.csv'))
#         total_em = np.array(em_csv['total_em'])
#         time_em  = np.array(em_csv['time_em'])
#         # Define time array
#         time_em_array = []
#         for j in range(len(time_em)):
#             this_ut_time   = datetime.datetime.strptime(time_em[j], '%Y-%m-%dT%H:%M:%SZ')
#             this_new_timezone_time = convert_utc_to_timezone(this_ut_time, timezone=timezone)
#             time_em_array.append(this_new_timezone_time)


#         ax8.plot(time_em_array,total_em, color_arr[i], label='EM AR '+str(arnum[i]))

#     ax8.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M', tz=tz.gettz(timezone)))
#     ax8.set_yscale('log')
#     ax8.set_ylim(1e46, 1e50)
#     ax8.set_xlim((min_time,max_time))
#     ax8.tick_params(axis="x", labelsize=chsize)
#     ax8.set(ylabel='EM [cm$^{-3}$]')
#     ax8.tick_params(axis="y", labelsize=chsize)
#     ax8.yaxis.label.set_size(chsize)
#     color = 'red'
#     ax8.tick_params(axis='y', labelcolor=color)
#     ax8.yaxis.label.set_color(color)
#     ax8.spines['right'].set_color(color)
#     #ax8.spines['left'].set_color('blue')

#     fig.legend(bbox_to_anchor=(0.4, -0.05, 0.45, 0.38), fontsize=legsize, ncol=2)

#     #plt.show()

#     plt.savefig(os.path.join(plots_folder, 'em_goes_plot')  , dpi=100,bbox_inches='tight')


def plot_em_maps_and_curves(
    em_maps,
    total_em_folder,
    xrsa_current,
    xrsb_current,
    arnum,
    label,
    plots_folder,
    color_arr,
    ar_lon,
    ar_lat,
    timezone="US/Central",
    em_cache=None,
    goes_plot_data=None,
):
    """

    Function for plotting the high temperature EM maps and the evolution of the high temperature total EM
    curves for the considered active regions

    Parameters
        ----------
        em_maps: list
            list containing the high temperature EM maps to be plotted

        total_em_folder: string
            path of the folder containing the cvs files with the time evolution of the total EM of the different ARs

        xrsa_current:
            latest GOES XRSA data to be plotted

        xrsb_current:
            latest GOES XRSB data to be plotted

        arnum: list
            list containing the number of the considered ARs

        plots_folder: string
            path of the folder where the plots are saved

        color_arr: list of strings
            colors that are used for plotting the boxes and the corresponnding lightcurves

        timezone: string
            Name of the time zone considered for printing the time of the considered data

    """

    if goes_plot_data is None:
        goes_time_array, goes_xrsa_flux, goes_xrsb_flux = prepare_goes_plot_arrays(
            xrsa_current, xrsb_current, timezone=timezone
        )
    else:
        goes_time_array, goes_xrsa_flux, goes_xrsb_flux = goes_plot_data

    # Plot AIA submaps
    fig = plt.figure(figsize=(25, 8))

    ax1 = plt.subplot2grid(
        (10, 20), (0, 0), rowspan=4, colspan=3, projection=em_maps[0]
    )
    ax2 = plt.subplot2grid(
        (10, 20), (0, 4), rowspan=4, colspan=3, projection=em_maps[1]
    )
    ax3 = plt.subplot2grid(
        (10, 20), (0, 8), rowspan=4, colspan=3, projection=em_maps[2]
    )

    ax4 = plt.subplot2grid(
        (10, 20), (5, 0), rowspan=4, colspan=3, projection=em_maps[3]
    )
    ax5 = plt.subplot2grid(
        (10, 20), (5, 4), rowspan=4, colspan=3, projection=em_maps[4]
    )
    ax6 = plt.subplot2grid(
        (10, 20), (5, 8), rowspan=4, colspan=3, projection=em_maps[5]
    )

    ax7 = plt.subplot2grid((10, 20), (1, 13), rowspan=5, colspan=7)

    plt.subplots_adjust(
        left=0.1, bottom=0.1, right=0.9, top=0.9, wspace=0.5, hspace=0.4
    )

    # Define axes list
    ax = [ax1, ax2, ax3, ax4, ax5, ax6, ax7]

    labelsize = 15
    ticksize = 15
    chsize = 15
    legsize = 15
    xlabel = " "
    ylabel = " "

    for jj in range(len(arnum)):
        # title  = 'AIA EM - AR ' + str(arnum[jj]) #+ ' \n (T $\geq 10^{6.6}$ K)'
        title = (
            label[jj]
            + " "
            + str(arnum[jj])
            + " ("
            + str(int(ar_lon[jj]))
            + ","
            + str(int(ar_lat[jj]))
            + ")"
        )
        em_maps[jj].plot_settings["norm"] = colors.LogNorm(
            vmin=1e42, vmax=1e45, clip=True
        )
        em_maps[jj].plot_settings["cmap"] = matplotlib.cm.get_cmap("CMRmap")

        im = em_maps[jj].plot(axes=ax[jj])

        ax[jj].grid(False)
        ax[jj].set_title(title, fontsize=labelsize, color=color_arr[jj])
        ax[jj].set_xlabel(xlabel, fontsize=labelsize)
        ax[jj].set_ylabel(ylabel, fontsize=labelsize)
        ax[jj].tick_params(axis="x", labelsize=ticksize)
        ax[jj].tick_params(axis="y", labelsize=ticksize)

        if jj == 2 or jj == 5:
            cax = fig.add_axes(
                [
                    ax[jj].get_position().x1 + 0.01,
                    ax[jj].get_position().y0,
                    0.01,
                    ax[jj].get_position().height,
                ]
            )
            cbar = fig.colorbar(im, cax=cax)  # ,ticks=cbarticks)
            cbar.ax.tick_params(labelsize=labelsize)
            cbar.ax.set_ylabel("EM [cm$^{-3}$ pixel$^{-1}$]", fontsize=labelsize)

    # Plot EM and GOES curves
    time_em_array, total_em = load_em_series(
        os.path.join(total_em_folder, "total_em_" + str(arnum[0]) + ".csv"),
        timezone=timezone,
        em_cache=em_cache,
    )

    # Original-style hourly view anchored to the latest EM point.
    min_time = time_em_array[-1] - timedelta(minutes=60)
    max_time = time_em_array[-1]
    if len(goes_time_array) > 0:
        goes_mask = (goes_time_array >= min_time) & (goes_time_array <= max_time)
        goes_time_array = goes_time_array[goes_mask]
        goes_xrsa_flux = np.array(goes_xrsa_flux)[goes_mask]
        goes_xrsb_flux = np.array(goes_xrsb_flux)[goes_mask]

    if len(goes_time_array) > 0:
        ax7.plot(
            goes_time_array, goes_xrsa_flux, "gray", label="GOES XRSA", linestyle="-."
        )
        ax7.plot(
            goes_time_array,
            goes_xrsb_flux,
            "black",
            label="GOES XRSB",
            linestyle="dashed",
        )
    ax7.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=tz.gettz(timezone)))
    ax7.xaxis.set_major_locator(mdates.MinuteLocator(interval=10))
    ax7.set_yscale("log")
    ax7.tick_params(axis="x", labelsize=chsize)
    ax7.tick_params(axis="y", labelsize=chsize)
    ax7.set_title(
        "Latest AIA data: - " + time_em_array[-1].strftime("%H:%M:%S") + " " + timezone,
        fontsize=chsize * 1.5,
    )
    ax7.set(xlabel="Time (" + time_em_array[-1].strftime("%m/%d/%Y") + ")")
    ax7.set(ylabel="GOES level")
    ax7.xaxis.label.set_size(chsize)
    ax7.yaxis.label.set_size(chsize)
    ax7.set_xlim((min_time, max_time))
    ax7.set_ylim(1e-8, 1e-4)
    ax7.set_yticks([1e-8, 1e-7, 1e-6, 1e-5, 1e-4])
    ax7.set_yticklabels(["A", "B", "C", "M", "X"])
    ax7.grid(True)

    color = "black"
    ax7.tick_params(axis="y", labelcolor=color)
    ax7.yaxis.label.set_color(color)

    ax8 = ax7.twinx()

    for i in range(len(arnum)):
        time_em_array, total_em = load_em_series(
            os.path.join(total_em_folder, "total_em_" + str(arnum[i]) + ".csv"),
            timezone=timezone,
            em_cache=em_cache,
        )

        em_mask = time_em_array >= min_time
        ax8.plot(
            time_em_array[em_mask],
            total_em[em_mask],
            color_arr[i],
            label="EM " + label[i] + " " + str(arnum[i]),
        )

    ax8.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=tz.gettz(timezone)))
    ax8.set_yscale("log")
    ax8.set_ylim(1e46, 1e50)
    ax8.set_xlim((min_time, max_time))
    ax8.tick_params(axis="x", labelsize=chsize)
    ax8.set(ylabel="EM [cm$^{-3}$]")
    ax8.tick_params(axis="y", labelsize=chsize)
    ax8.yaxis.label.set_size(chsize)
    color = "red"
    ax8.tick_params(axis="y", labelcolor=color)
    ax8.yaxis.label.set_color(color)
    ax8.spines["right"].set_color(color)
    # ax8.spines['left'].set_color('blue')

    fig.legend(bbox_to_anchor=(0.4, -0.05, 0.45, 0.38), fontsize=legsize, ncol=2)

    # plt.show()

    plt.savefig(os.path.join(plots_folder, "em_goes_plot"), dpi=85, bbox_inches="tight")
    plt.close(fig)


# **********************************************************


def plot_full_disk_images(
    calibrated_aia_maps,
    plots_folder,
    t_rec,
    arnum,
    ar_lon,
    ar_lat,
    color_arr,
    timezone="US/Central",
    n_pix_x=1000,
    n_pix_y=1000,
    suvi_image=None,
    suvi_title="SUVI",
):
    # def plot_full_disk_images(calibrated_aia_maps, plots_folder, t_rec, arnum, ar_lon, ar_lat, color_arr,
    #                        timezone='US/Central', n_pix_x=1400, n_pix_y=1400): #### new suggested version to make boxes bigger
    """

    Function for plotting the full-disk AIA images and the rectangles around the considered active regions


    Parameters
        ----------
        calibrated_aia_maps: list
            List of the calibrated full-disk AIA maps to be plotted

        plots_folder: string
            Path of the folder where the plots are saved

        t_rec: list
            List containing the times at which the AIA maps have been recorded

        arnum: list
            List of the number of the selected active regions

        ar_lon: float
            Longitude coordinates of the considered active regions (Heliographic Stonyhurst coordinates)

        ar_lat: float
            Latitude coordinates of the considered active regions (Heliographic Stonyhurst coordinates)

        timezone: string
            Name of the time zone w.r.t. the time are expressed

        n_pix_x: integer
            number of pixels of the submap to be extracted; horizontal axis. Default, 1000

        n_pix_y: integer
            number of pixels of the submap to be extracted; vertical axis. Default, 1000
            both used for plotting a rectangle around active regions

        color_arr: list of strings
            colors that are used for plotting the boxes and the corresponnding lightcurves

    """

    ordered_wav = [171, 193, 211, 131, 94]

    wav_maps = []
    for jj in range(5):
        wav_maps.append(calibrated_aia_maps[jj].meta["wavelnth"])
    wav_maps = np.array(wav_maps)

    ordered_aia_maps = []
    for jj in range(5):
        idx = np.where(wav_maps == ordered_wav[jj])
        ordered_aia_maps.append(calibrated_aia_maps[idx[0][0]])

    fig = plt.figure(figsize=(32.0, 6.4))
    gs = fig.add_gridspec(
        1, 6, width_ratios=[1.0, 1.0, 1.0, 1.0, 1.0, 1.2], wspace=0.23
    )

    ax1 = fig.add_subplot(gs[0, 0], projection=ordered_aia_maps[0])
    ax2 = fig.add_subplot(gs[0, 1], projection=ordered_aia_maps[1])
    ax3 = fig.add_subplot(gs[0, 2], projection=ordered_aia_maps[2])
    ax4 = fig.add_subplot(gs[0, 3], projection=ordered_aia_maps[3])
    ax5 = fig.add_subplot(gs[0, 4], projection=ordered_aia_maps[4])
    ax6 = fig.add_subplot(gs[0, 5])
    fig.subplots_adjust(left=0.03, right=0.995, top=0.85, bottom=0.08, wspace=0.21)

    # Reduce only the gap between panel 5 and panel 6 (keep panel 5 fixed).
    panel56_tighten = 0.0215
    p5 = ax5.get_position()
    p6 = ax6.get_position()
    if panel56_tighten:
        ax6.set_position([p6.x0 - panel56_tighten, p6.y0, p6.width, p6.height])
    ax5.set_position([p5.x0, p5.y0, p5.width, p5.height])

    # Plot AIA submaps
    ax = [ax1, ax2, ax3, ax4, ax5]

    labelsize = 16
    ticksize = 14
    chsize = 10
    legsize = 10
    xlabel = "Solar X [arcsec]"
    ylabel = "Solar Y [arcsec]"

    transparent_white = (1, 1, 1, 0.5)
    for jj in range(5):
        this_map = ordered_aia_maps[jj]
        this_map = normalize_exposure(this_map)

        vmin = 0.3
        vmax = 16000.0 / 2.9
        this_map.plot_settings["norm"] = colors.LogNorm(vmin=vmin, vmax=vmax, clip=True)
        this_map.plot_settings["cmap"] = matplotlib.cm.get_cmap("gray")

        this_map.plot(axes=ax[jj])

        ax[jj].set_title(
            "AIA " + str(this_map.meta["wavelnth"]) + "Å", fontsize=labelsize
        )
        ax[jj].set_xlabel(xlabel, fontsize=14)
        ax[jj].set_ylabel(ylabel, fontsize=14, labelpad=-0.5)
        ax[jj].tick_params(axis="x", labelsize=ticksize)
        ax[jj].tick_params(axis="y", labelsize=ticksize, pad=0)

        for ii in range(len(ar_lon)):
            this_coord = SkyCoord(
                ar_lon[ii] * u.deg,
                ar_lat[ii] * u.deg,
                frame=frames.HeliographicStonyhurst,
            )

            pix_x = this_map.world_to_pixel(this_coord).x.value
            pix_y = this_map.world_to_pixel(this_coord).y.value

            top_right = this_map.pixel_to_world(
                (pix_x + n_pix_x // 2 - 1) * u.pix, (pix_y + n_pix_y // 2 - 1) * u.pix
            )
            bottom_left = this_map.pixel_to_world(
                (pix_x - n_pix_x // 2) * u.pix, (pix_y - n_pix_y // 2) * u.pix
            )

            new_bl = SkyCoord(
                bottom_left.Tx, bottom_left.Ty, frame=this_map.coordinate_frame
            )
            new_tr = SkyCoord(
                top_right.Tx, top_right.Ty, frame=this_map.coordinate_frame
            )

            this_map.draw_quadrangle(
                new_bl,
                axes=ax[jj],
                top_right=new_tr,
                color=color_arr[ii],
                linewidth=2,
            )

    # SUVI panel integrated in the same top block (no HTML overlay positioning).
    current_time_utc = datetime.datetime.strptime(
        t_rec[0], "%Y-%m-%dT%H:%M:%SZ"
    ).replace(tzinfo=datetime.timezone.utc)
    current_time_local = convert_utc_to_timezone(current_time_utc, timezone=timezone)
    suvi_panel_title = (
        f"{suvi_title} | {current_time_local.strftime('%H:%M:%S')} {timezone}"
    )
    ax6.set_title(suvi_panel_title, fontsize=16, pad=6)
    if suvi_image is None:
        ax6.text(
            0.5, 0.5, "SUVI data not available", ha="center", va="center", fontsize=10
        )
        ax6.set_facecolor("black")
    else:
        # Preserve native image aspect ratio (no stretch/squish).
        ax6.imshow(suvi_image, interpolation="nearest")
    ax6.set_anchor("N")
    ax6.set_xticks([])
    ax6.set_yticks([])
    for spine in ax6.spines.values():
        spine.set_visible(False)

    # Align only the top edge with AIA panels; keep SUVI's own height/aspect behavior.
    pos_aia = ax1.get_position()
    pos_suvi = ax6.get_position()
    y1 = pos_aia.y1
    y0 = y1 - pos_suvi.height
    ax6.set_position([pos_suvi.x0, y0, pos_suvi.width, pos_suvi.height])

    current_time = current_time_local

    fig.suptitle(
        "AIA data " + current_time.strftime("%m/%d/%Y - %H:%M:%S") + " " + timezone,
        fontsize=40,
    )

    plt.savefig(
        os.path.join(
            plots_folder,
            "aia_full_disk_" + current_time.strftime("%Y-%m-%dT%H%M%S") + ".png",
        ),
        dpi=130,
        bbox_inches="tight",
    )
    plt.close(fig)
    prune_full_disk_images(plots_folder, keep_last=30)


# **********************************************************


def calibrate_aia_data(aia_maps, correction_table):
    """

    Function for calibrating the AIA maps to be used for computing the high temperature total EM map
    The AIA mas are normalized by the exposure time and corrected for the degration of the instrument

    Parameters
        ----------
        aia_maps: list
            list containing the high temperature EM maps to be plotted

        correction_table: table to be used for correcting the degradation of the instrument.
                          Created with the module correct_degradation from aiapy.calibrate

    Returns
        ----------
        Calibrated AIA maps

    """

    aia_img = []
    for aia_map in aia_maps:
        aia_map = correct_degradation(
            normalize_exposure(aia_map), correction_table=correction_table
        )
        aia_img.append(aia_map.data)

    # Some channels can differ by ~1 pixel after map operations; stack on the
    # common overlap region so EM math still runs on aligned shapes.
    if len(aia_img) == 0:
        return np.empty((0, 0, 0))
    min_ny = min(img.shape[0] for img in aia_img)
    min_nx = min(img.shape[1] for img in aia_img)
    aia_img = [img[:min_ny, :min_nx] for img in aia_img]

    aia_img = np.stack(aia_img, axis=0)
    aia_img = np.transpose(aia_img, (1, 2, 0))

    return aia_img


# **********************************************************
# def stream_aia_data(duration_stream, data_folder, ar_lon, ar_lat, arnum,
#                     correction_table, timezone='US/Central', n_pix=1000, latency=10,
#                     reference_wav=193, th_tot_em=0,
#                     weights = [1.20196640e-04,  2.12817313e-05, -7.33613022e-07,  1.83818002e-07, -1.90719161e-06], save_maps=False):
#     """

#     Function for downloading near real time AIA data, computing the high temperature EM maps and plot the results on the WKU website

#     Parameters
#         ----------

#         duration_stream: int. Duration of the data stream in minutes

#         data_folder: string. Path of the folder where the data are saved

#         ar_lon: list of float numbers. It contains the longitude coordinates (degrees) of center of each active region

#         ar_lat: list of float numbers. It contains the latitude coordinates (degrees) of center of each active region

#         arnum: list of integers. It contains the ID number of the considered active regions

#         correction_table: table to be used for correcting the degradation of the instrument.
#                           Created with the module correct_degradation from aiapy.calibrate

#     Keywords
#         ----------

#         timezone: string. Name of the timezone with respect to which the time is expressed. Default, 'US/Central'

#         n_pix: int. Number of pixels of the submaps that are extracted around each AR from the (near-realtime) full-disk AIA maps. Default, 1000 [pixels]

#         latency: int. Number of minutes of past data that we query at every iteration of the pipeline (to be sure to get the latest data). Default, 10 [minutes]

#         reference_wav: int. Reference wavelength to be considered for determining the 12s "cycles" of AIA data. Default, 193 [A]

#         th_tot_em: float. Threshold value that is considered for computing the total high temperature EM curves from the corresponding maps.
#                    Before summing, the pixel values below the threshold are set to 0. Default, 0 [cm^-3]

#         weights: list, weights that are used for performing the linear combination of the AIA channels to obtain the
#                  high temperature EM maps. Default, [1.20196640e-04,  2.12817313e-05, -7.33613022e-07,  1.83818002e-07, -1.90719161e-06]

#         ssh_host: string, name of the server where the plots are uploaded via scp

#         ssh_user: string, name of the user on the server where the plots are uploaded via scp

#         ssh_password: string, password of the user on the server where the plots are uploaded via scp

#         destination_volume: string, path of the folder on the server where the plots are uploaded via scp

#     """

#     ############ INITIALIZE PARAMETERS AND MAKE FOLDERS

#     # Number of the considered active regions (ARs).
#     # The pipeline has been implemented so that it considers 3 ARs at the same time
#     n_ar = 6

#     # Check that the number of parameters is correct
#     if len(ar_lon) < n_ar:
#         raise Exception("The number of elements in ar_lon is less than " + str(n_ar))

#     if len(ar_lat) < n_ar:
#         raise Exception("The number of elements in ar_lat is less than " + str(n_ar))

#     if len(arnum) < n_ar:
#         raise Exception("The number of elements in arnum is less than " + str(n_ar))

#     # Define colors that will be used for plotting the boxes and the corresponding curves
#     color_arr=['red','gold','blue', 'lime', 'cyan', 'magenta']

#     # Define JSOC server client
#     client = configure_jsoc_server()

#     # Plots folder
#     plots_folder = os.path.join(data_folder, 'all_plots')
#     mkdir(plots_folder)

#     # Latest results folder
#     latest_plots_folder = os.path.join(data_folder, 'latest_plots')
#     mkdir(latest_plots_folder)

#     # AIA data folder
#     aia_data_folder = os.path.join(data_folder, 'aia_data_folder')
#     mkdir(aia_data_folder)

#     # GOES folder
#     goes_folder = os.path.join(data_folder, 'goes_data_folder')
#     mkdir(goes_folder)

#     # Total EM folder
#     total_em_folder = os.path.join(data_folder, 'total_em')
#     mkdir(total_em_folder)
#     for i in range(len(arnum)):
#         file_name_csv = os.path.join(total_em_folder, 'total_em_' + str(arnum[i]) + '.csv')
#         if not os.path.exists(file_name_csv):
#             write_csv_em(file_name_csv, 0, 0, function_csv='w')

#     # Array containing the wavelengths needed to compute the high temperature EM maps
#     wavelengths_needed = np.array([94, 131, 171, 193, 211])

#     # Initialize start time, current time and difference between start time and current time (zero at the beginning of the stream)
#     start_time_ut    = datetime.datetime.now(datetime.timezone.utc) - timedelta(minutes = latency)
#     start_time_ut_time_diff = datetime.datetime.now(datetime.timezone.utc)
#     current_time_ut  = start_time_ut
#     time_diff = 0

#     # Define utc time zone
#     utc = pytz.timezone('UTC')

#     # Define ssh client to be used for uploading data
#     destination_volume='/server/html/waffle/'
#     ssh_client = define_ssh_client()

#     ############ START STREAM

#     while time_diff <= duration_stream:

#         # Query data
#         query, segments = client.query('aia.lev1_nrt2[' + current_time_ut.strftime("%Y.%m.%d_%H:%M:%S") + '_UT/' + str(latency) + 'm]',  key='T_REC, WAVELNTH', seg='image_lev1')

#         # Extract wavelengths, time of the measurement, segment link
#         wavelnth = np.array(query['WAVELNTH'])
#         t_rec    = np.array(query['T_REC'])
#         segments = np.squeeze(np.array(segments))

#         # Check if reference wavelength is present in the set of data that have been queried
#         idx = np.where(wavelnth == reference_wav)
#         idx = idx[0]

#         if len(idx) == 0:
#             print("Reference wavelength not found. Wait 15 s.")
#             time.sleep(15)
#             time_diff = datetime.datetime.now(datetime.timezone.utc) - start_time_ut_time_diff
#             time_diff = time_diff.seconds/60
#             continue

#         # Divide data into cycles
#         grouped_wav       = []
#         grouped_t_rec     = []
#         grouped_segments  = []
#         start_time_series = []

#         # Divide data into 12s cycles
#         for start, end in zip(idx, idx[1:]):

#             this_wav   = wavelnth[start:end]
#             this_t_rec = t_rec[start:end]
#             this_segments = segments[start:end]
#             this_start_time = datetime.datetime.strptime(this_t_rec[0], '%Y-%m-%dT%H:%M:%SZ')
#             start_time_series.append(utc.localize(this_start_time))

#             # Remove 335 A, 304 A, 1600 A, 1700 A and 4500 A
#             idx_remove = np.where((this_wav == 304) | (this_wav == 335) | (this_wav == 1600) | (this_wav == 1700) | (this_wav == 4500))
#             idx_remove = idx_remove[0]
#             if len(idx_remove) > 0:
#                 this_wav      = np.delete(this_wav, idx_remove)
#                 this_t_rec    = np.delete(this_t_rec, idx_remove)
#                 this_segments = np.delete(this_segments, idx_remove)

#             grouped_wav.append(this_wav)
#             grouped_t_rec.append(this_t_rec)
#             grouped_segments.append(this_segments)


#         start_time_series = np.array(start_time_series)

#         # Select latest complete 12s cycle to be downloaded
#         idx = select_data_to_download(start_time_series, grouped_wav, current_time_ut, wavelengths_needed)

#         if idx >= 0:

#             # Take the last 12s AIA data cycle
#             grouped_wav       = grouped_wav[idx]
#             grouped_t_rec     = grouped_t_rec[idx]
#             grouped_segments  = grouped_segments[idx]
#             start_time_series = start_time_series[idx]

#             # Keep track of the elapsed time
#             t = time.time()

#             # Download and calibrate full-disk near real time AIA maps
#             aia_maps, dowloaded_data_folder, error = download_aia_data(grouped_wav, grouped_t_rec, grouped_segments, aia_data_folder, timezone=timezone)
#             calibrated_aia_maps = calibrate_full_disk_maps(aia_maps)

#             if error:
#                 print("Error in downloading data. Continue..")
#                 time.sleep(30)
#                 continue

#             # Crop images around ARs and compute EM of the "hottest region"
#             cropped_maps_folder = dowloaded_data_folder + "_crop"
#             if save_maps:
#                 mkdir(cropped_maps_folder)

#             # Plot full-disk maps
#             plot_full_disk_images(calibrated_aia_maps,plots_folder,grouped_t_rec,arnum,ar_lon,ar_lat,color_arr,timezone=timezone, n_pix=n_pix)

#             # Create gif animation
#             create_animation_from_images(plots_folder, animation_filename=os.path.join(latest_plots_folder,'full_disk_maps.gif'), fps=2)

#             # Download latest GOES data
#             xrsa_current, xrsb_current = load_realtime_XRS(goes_folder)

#             em_maps = []
#             for i in range(n_ar):
#                 # Crop images around active regions ##
#                 aia_submaps = crop_full_disk_maps(calibrated_aia_maps, ar_lon[i], ar_lat[i], arnum[i], cropped_maps_folder, n_pix=n_pix, save_submaps=save_maps)

#                 metadata = aia_submaps[0].meta
#                 # Calibrate AIA maps (correct degradation and normalize exposure)
#                 aia_img = calibrate_aia_data(aia_submaps, correction_table)

#                 # Compute high temperature EM maps
#                 em_map = compute_em_map(aia_img, metadata, weights)
#                 if save_maps:
#                     fitsname = os.path.join(cropped_maps_folder, 'em_map_ar' + str(arnum[i]) + '.fits')
#                     astropy.io.fits.writeto(fitsname, em_map.data, em_map.fits_header, output_verify='exception', overwrite=True, checksum=False)
#                 em_maps.append(em_map)

#                 # Save EM values in csv
#                 file_name_em_csv = os.path.join(total_em_folder, 'total_em_' + str(arnum[i]) + '.csv')
#                 em_map_th = em_map.data
#                 idx = np.where(em_map_th < th_tot_em) # set values below the treshold equal to 0
#                 em_map_th[idx] = 0
#                 write_csv_em(file_name_em_csv, grouped_t_rec[0], np.sum(em_map_th))

#                 plot_results(latest_plots_folder, aia_submaps, em_map, xrsa_current, xrsb_current, arnum[i], i+1, file_name_em_csv,
#                              timezone=timezone)


#             # Plot GOES and AIA curves
#             plot_em_maps_and_curves(em_maps,total_em_folder,xrsa_current, xrsb_current,arnum,latest_plots_folder,color_arr,ar_lon,ar_lat,timezone=timezone)

#             print("Upload data...")
#             ssh_scp_files(ssh_client, latest_plots_folder, destination_volume)
#             print("Upload completed!")

#             if not save_maps:
#                 shutil.rmtree(dowloaded_data_folder)

#             elapsed = time.time() - t
#             print('Elapsed time: ' + str(round(elapsed)) + ' s')
#             time_diff = datetime.datetime.now(datetime.timezone.utc) - start_time_ut_time_diff
#             time_diff = time_diff.seconds/60
#             # Reset 'current_time_ut'
#             current_time_ut = start_time_series

#         else:
#             print("No new data series. Wait 15 s.")
#             time.sleep(15)
#             time_diff = datetime.datetime.now(datetime.timezone.utc) - start_time_ut_time_diff
#             time_diff = time_diff.seconds/60
#             continue


def stream_aia_data(
    duration_stream,
    data_folder,
    ar_lon,
    ar_lat,
    arnum,
    label,
    correction_table,
    timezone="US/Central",
    n_pix_x=1000,
    n_pix_y=1000,
    latency=10,
    reference_wav=193,
    th_tot_em=0,
    weights=[
        1.20196640e-04,
        2.12817313e-05,
        -7.33613022e-07,
        1.83818002e-07,
        -1.90719161e-06,
    ],
    save_maps=False,
    publish_mode="scp",
    local_publish_dir=None,
    drms_series="aia.lev1_nrt2",
    drms_segment="image_lev1",
    query_start_ut=None,
    time_step_minutes=None,
    ml_model_path="./ml_fft_assets/models/centroid_seq.pt",
    ml_seq_len=12,
    ml_uv_grid_path="/Users/gabe/Github/Pocky/Vis/uv_grid.npz",
    ml_vis_pixel_arcsec=0.6,
    use_psf_reconstruction=False,
    use_psf_flare_metrics=True,
    psf_dir="./ml_fft_assets/PSFs",
    psf_recon_plot_wavelength=131,
    suvi_top_wavelength=131,
    suvi_use_realtime=False,
    ml_score_channels="131,193,94,171,211",
    ml_score_weights="-0.30,-0.20,0.20,0.20,0.10",
    ml_impulse_channels="131,193,94,211",
    ml_impulse_weights="0.60,0.30,0.10,0.20",
):
    """

    Function for downloading near real time AIA data, computing the high temperature EM maps and plot the results on the WKU website

    Parameters
        ----------

        duration_stream: int. Duration of the data stream in minutes

        data_folder: string. Path of the folder where the data are saved

        ar_lon: list of float numbers. It contains the longitude coordinates (degrees) of center of each active region

        ar_lat: list of float numbers. It contains the latitude coordinates (degrees) of center of each active region

        arnum: list of integers. It contains the ID number of the considered active regions

        correction_table: table to be used for correcting the degradation of the instrument.
                          Created with the module correct_degradation from aiapy.calibrate

    Keywords
        ----------

        timezone: string. Name of the timezone with respect to which the time is expressed. Default, 'US/Central'

        n_pix_x: int. Number of pixels of the submaps that are extracted around each AR from the (near-realtime) full-disk AIA maps in the x-direction. Default, 1000 [pixels]

        n_pix_y: int. Number of pixels of the submaps that are extracted around each AR from the (near-realtime) full-disk AIA maps in the y-direction. Default, 1000 [pixels]

        latency: int. Number of minutes of past data that we query at every iteration of the pipeline (to be sure to get the latest data). Default, 10 [minutes]

        reference_wav: int. Reference wavelength to be considered for determining the 12s "cycles" of AIA data. Default, 193 [A]

        th_tot_em: float. Threshold value that is considered for computing the total high temperature EM curves from the corresponding maps.
                   Before summing, the pixel values below the threshold are set to 0. Default, 0 [cm^-3]

        weights: list, weights that are used for performing the linear combination of the AIA channels to obtain the
                 high temperature EM maps. Default, [1.20196640e-04,  2.12817313e-05, -7.33613022e-07,  1.83818002e-07, -1.90719161e-06]

        ssh_host: string, name of the server where the plots are uploaded via scp

        ssh_user: string, name of the user on the server where the plots are uploaded via scp

        ssh_password: string, password of the user on the server where the plots are uploaded via scp

        destination_volume: string, path of the folder on the server where the plots are uploaded via scp

        publish_mode: string. Either 'scp' (remote upload) or 'local' (publish to local folder). Default, 'scp'

        local_publish_dir: string. Destination folder used when publish_mode='local'. If None, defaults to
                          <data_folder>/local_web

        drms_series: string. DRMS series queried for AIA data. Default, 'aia.lev1_nrt2'

        drms_segment: string. Segment name to download FITS paths from. Default, 'image_lev1'

        query_start_ut: datetime (UTC-aware) or None. If provided, the stream query starts from this
                        reference time (minus latency). If None, current UTC time is used.

        time_step_minutes: int/float or None. Minutes added to the selected frame time to advance
                          the stream cursor. If None, defaults to latency.

        ml_model_path: string. Path of the ML_FFT GRU checkpoint to use for per-AR feature trend plots.

        ml_seq_len: int. Sequence length used for ML model inference.

        ml_uv_grid_path: string. Path to Pocky/Vis uv_grid.npz used for visibility sampling.

        ml_vis_pixel_arcsec: float. Pixel scale used in visibility DFT sampling.

        use_psf_reconstruction: bool. Legacy toggle for diffraction-aware PSF reconstruction.
                               The live pipeline currently disables reconstruction use and keeps code for later.

        use_psf_flare_metrics: bool. If True, compute lightweight PSF/diffraction diagnostics (no reconstruction)
                              for flare-detection analysis.

        psf_dir: string. Folder containing exported AIA PSF .npy files.

        psf_recon_plot_wavelength: int. Wavelength (among processed channels) used for regular-vs-reconstructed diagnostic plot.

        suvi_top_wavelength: int. SUVI wavelength used for the top-row remote image in generated website (94 or 131).

        suvi_use_realtime: bool. If True, force SUVI top image to use realtime latest.png;
                           if False, resolve a day-specific SUVI image from the stream day.

        ml_score_channels: string. Gradual profile channel list for g score.

        ml_score_weights: string. Gradual profile weights aligned with ml_score_channels.

        ml_impulse_channels: string. Impulsive profile channel list for i score.

        ml_impulse_weights: string. Impulsive profile weights aligned with ml_impulse_channels.

    """

    ############ INITIALIZE PARAMETERS AND MAKE FOLDERS

    # Number of the considered active regions (ARs).
    # The pipeline has been implemented so that it considers 3 ARs at the same time
    n_ar = 6

    # Check that the number of parameters is correct
    if len(ar_lon) < n_ar:
        raise Exception("The number of elements in ar_lon is less than " + str(n_ar))

    if len(ar_lat) < n_ar:
        raise Exception("The number of elements in ar_lat is less than " + str(n_ar))

    if len(arnum) < n_ar:
        raise Exception("The number of elements in arnum is less than " + str(n_ar))

    # Define colors that will be used for plotting the boxes and the corresponding curves
    color_arr = ["red", "gold", "blue", "lime", "cyan", "magenta"]

    # Define JSOC server client
    client = configure_jsoc_server()

    # Plots folder
    plots_folder = os.path.join(data_folder, "all_plots")
    mkdir(plots_folder)

    # Latest results folder
    latest_plots_folder = os.path.join(data_folder, "latest_plots")
    mkdir(latest_plots_folder)

    # AIA data folder
    aia_data_folder = os.path.join(data_folder, "aia_data_folder")
    mkdir(aia_data_folder)

    # GOES folder
    goes_folder = os.path.join(data_folder, "goes_data_folder")
    mkdir(goes_folder)

    # Total EM folder
    total_em_folder = os.path.join(data_folder, "total_em")
    mkdir(total_em_folder)
    for i in range(len(arnum)):
        file_name_csv = os.path.join(
            total_em_folder, "total_em_" + str(arnum[i]) + ".csv"
        )
        if not os.path.exists(file_name_csv):
            write_csv_em(file_name_csv, 0, 0, function_csv="w")

    # Cache to avoid repeated CSV reads/parsing in plotting calls.
    em_cache = {}
    # Cache GOES data per UTC day to avoid repeated network fetches in the loop.
    goes_cache = {}
    # v1: no ML/scores/PSF diagnostics in runtime path.

    # Array containing the wavelengths needed to compute the high temperature EM maps
    wavelengths_needed = np.array([94, 131, 171, 193, 211])

    # Initialize start time, current time and difference between start time and current time (zero at the beginning of the stream)
    if query_start_ut is None:
        query_start_ut = datetime.datetime.now(datetime.timezone.utc)
    start_time_ut = query_start_ut - timedelta(minutes=latency)
    start_time_ut_time_diff = datetime.datetime.now(datetime.timezone.utc)
    current_time_ut = start_time_ut
    time_diff = 0

    # Define utc time zone
    utc = pytz.timezone("UTC")

    # Independent cursor step control (defaults to latency for backward compatibility).
    if time_step_minutes is None:
        time_step_minutes = latency

    # Define publishing destination.
    destination_volume = "/server/html/waffle/"
    ssh_client = None
    if publish_mode == "scp":
        ssh_client = define_ssh_client()
    elif publish_mode == "local":
        if local_publish_dir is None:
            local_publish_dir = os.path.join(data_folder, "local_web")
        mkdir(local_publish_dir)
    else:
        raise ValueError("publish_mode must be either 'scp' or 'local'")

    ############ START STREAM

    while time_diff <= duration_stream:
        # Query data
        query, segments = client.query(
            drms_series
            + "["
            + current_time_ut.strftime("%Y.%m.%d_%H:%M:%S")
            + "_UT/"
            + str(latency)
            + "m]",
            key="T_REC, WAVELNTH",
            seg=drms_segment,
        )

        # Extract wavelengths, time of the measurement, segment link
        wavelnth = np.array(query["WAVELNTH"])
        t_rec = np.array(query["T_REC"])
        segments = np.squeeze(np.array(segments))

        # Check if reference wavelength is present in the set of data that have been queried
        idx = np.where(wavelnth == reference_wav)
        idx = idx[0]

        if len(idx) == 0:
            print("Reference wavelength not found. Wait 15 s.")
            time.sleep(15)
            time_diff = (
                datetime.datetime.now(datetime.timezone.utc) - start_time_ut_time_diff
            )
            time_diff = time_diff.seconds / 60
            continue

        # Divide data into cycles
        grouped_wav = []
        grouped_t_rec = []
        grouped_segments = []
        start_time_series = []

        # Divide data into 12s cycles
        for start, end in zip(idx, idx[1:]):
            this_wav = wavelnth[start:end]
            this_t_rec = t_rec[start:end]
            this_segments = segments[start:end]
            this_start_time = datetime.datetime.strptime(
                this_t_rec[0], "%Y-%m-%dT%H:%M:%SZ"
            )
            start_time_series.append(utc.localize(this_start_time))

            # Remove 335 A, 304 A, 1600 A, 1700 A and 4500 A
            idx_remove = np.where(
                (this_wav == 304)
                | (this_wav == 335)
                | (this_wav == 1600)
                | (this_wav == 1700)
                | (this_wav == 4500)
            )
            idx_remove = idx_remove[0]
            if len(idx_remove) > 0:
                this_wav = np.delete(this_wav, idx_remove)
                this_t_rec = np.delete(this_t_rec, idx_remove)
                this_segments = np.delete(this_segments, idx_remove)

            grouped_wav.append(this_wav)
            grouped_t_rec.append(this_t_rec)
            grouped_segments.append(this_segments)

        start_time_series = np.array(start_time_series)

        # Select latest complete 12s cycle to be downloaded
        idx = select_data_to_download(
            start_time_series,
            grouped_wav,
            current_time_ut,
            wavelengths_needed,
        )

        if idx >= 0:
            # Take the last 12s AIA data cycle
            grouped_wav = grouped_wav[idx]
            grouped_t_rec = grouped_t_rec[idx]
            grouped_segments = grouped_segments[idx]
            start_time_series = start_time_series[idx]

            # Keep one sample for each required wavelength in a fixed order.
            selected_wav = []
            selected_t_rec = []
            selected_segments = []
            for req_wav in wavelengths_needed:
                req_idx = np.where(grouped_wav == req_wav)[0]
                if len(req_idx) == 0:
                    selected_wav = []
                    break
                j = req_idx[0]
                selected_wav.append(grouped_wav[j])
                selected_t_rec.append(grouped_t_rec[j])
                selected_segments.append(grouped_segments[j])

            if len(selected_wav) != len(wavelengths_needed):
                print("Selected cycle missing required wavelengths. Wait 15 s.")
                time.sleep(15)
                time_diff = (
                    datetime.datetime.now(datetime.timezone.utc)
                    - start_time_ut_time_diff
                )
                time_diff = time_diff.seconds / 60
                continue

            grouped_wav = np.array(selected_wav)
            grouped_t_rec = np.array(selected_t_rec)
            grouped_segments = np.array(selected_segments)

            # Keep track of the elapsed time
            t = time.time()

            # Download and calibrate full-disk near real time AIA maps
            aia_maps, dowloaded_data_folder, error = download_aia_data(
                grouped_wav,
                grouped_t_rec,
                grouped_segments,
                aia_data_folder,
                timezone=timezone,
            )
            calibrated_aia_maps = calibrate_full_disk_maps(aia_maps)

            if error:
                print("Error in downloading data. Continue..")
                time.sleep(30)
                continue

            # Crop images around ARs and compute EM of the "hottest region"
            cropped_maps_folder = dowloaded_data_folder + "_crop"
            if save_maps:
                mkdir(cropped_maps_folder)

            # Plot full-disk maps
            suvi_day_key = start_time_series.astimezone(datetime.timezone.utc).strftime(
                "%Y-%m-%d"
            )
            suvi_img, suvi_title = fetch_suvi_image_for_panel(
                suvi_top_wavelength=suvi_top_wavelength,
                suvi_day_utc=suvi_day_key,
                suvi_use_realtime=suvi_use_realtime,
            )
            plot_full_disk_images(
                calibrated_aia_maps,
                plots_folder,
                grouped_t_rec,
                arnum,
                ar_lon,
                ar_lat,
                color_arr,
                timezone=timezone,
                n_pix_x=n_pix_x,
                n_pix_y=n_pix_y,
                suvi_image=suvi_img,
                suvi_title=suvi_title,
            )

            # Create gif animation
            create_animation_from_images(
                plots_folder,
                animation_filename=os.path.join(
                    latest_plots_folder, "full_disk_maps.gif"
                ),
                fps=2,
            )

            # Download latest GOES data
            goes_day_key = start_time_series.astimezone(datetime.timezone.utc).strftime(
                "%Y-%m-%d"
            )
            if goes_day_key in goes_cache:
                xrsa_current, xrsb_current = goes_cache[goes_day_key]
            else:
                xrsa_current, xrsb_current = load_realtime_XRS(
                    goes_folder, reference_time_ut=start_time_series
                )
                goes_cache[goes_day_key] = (xrsa_current, xrsb_current)
            goes_plot_data = prepare_goes_plot_arrays(
                xrsa_current, xrsb_current, timezone=timezone
            )

            em_maps = []
            for i in range(n_ar):
                # Crop images around active regions
                # n_pix_x = w/0.6, n_pix_y = h/0.6 ##1 pixel = 0.6 arcseconds
                # aia_submaps = crop_full_disk_maps(calibrated_aia_maps, ar_lon[i], ar_lat[i], arnum[i], cropped_maps_folder, n_pix_x=n_pix_x, n_pix_y=n_pix_y, save_submaps=save_maps)
                aia_submaps = crop_full_disk_maps(
                    calibrated_aia_maps,
                    ar_lon[i],
                    ar_lat[i],
                    arnum[i],
                    cropped_maps_folder,
                    n_pix_x=n_pix_x,
                    n_pix_y=n_pix_y,
                    save_submaps=save_maps,
                )

                metadata = aia_submaps[0].meta
                # Calibrate AIA maps (correct degradation and normalize exposure)
                aia_img = calibrate_aia_data(aia_submaps, correction_table)
                em_map_recon_plot = None

                # Compute high temperature EM maps (raw only for pipeline calculations)
                em_map_raw = compute_em_map(aia_img, metadata, weights)
                em_map = em_map_raw
                if save_maps:
                    fitsname = os.path.join(
                        cropped_maps_folder, "em_map_ar" + str(arnum[i]) + ".fits"
                    )
                    astropy.io.fits.writeto(
                        fitsname,
                        em_map.data,
                        em_map.fits_header,
                        output_verify="exception",
                        overwrite=True,
                        checksum=False,
                    )
                # Keep top summary products on raw EM maps.
                em_maps.append(em_map_raw)

                # Save EM values in csv
                file_name_em_csv = os.path.join(
                    total_em_folder, "total_em_" + str(arnum[i]) + ".csv"
                )
                em_map_th = em_map_raw.data.copy()
                idx = np.where(
                    em_map_th < th_tot_em
                )  # set values below the treshold equal to 0
                em_map_th[idx] = 0
                total_em_current = np.sum(em_map_th)
                write_csv_em(file_name_em_csv, grouped_t_rec[0], total_em_current)
                append_em_cache(
                    file_name_em_csv,
                    grouped_t_rec[0],
                    total_em_current,
                    timezone=timezone,
                    em_cache=em_cache,
                )

                # v1: no detailed-analysis plot generation.

            # Plot GOES and AIA curves
            plot_em_maps_and_curves(
                em_maps,
                total_em_folder,
                xrsa_current,
                xrsb_current,
                arnum,
                label,
                latest_plots_folder,
                color_arr,
                ar_lon,
                ar_lat,
                timezone=timezone,
                em_cache=em_cache,
                goes_plot_data=goes_plot_data,
            )

            print("Publish data...")
            if publish_mode == "scp":
                ssh_scp_files(ssh_client, latest_plots_folder, destination_volume)
            else:
                publish_local_files(
                    latest_plots_folder,
                    local_publish_dir,
                    suvi_top_wavelength=suvi_top_wavelength,
                    suvi_day_utc=start_time_series.astimezone(
                        datetime.timezone.utc
                    ).strftime("%Y-%m-%d"),
                    suvi_use_realtime=suvi_use_realtime,
                )
            print("Publish completed!")

            if not save_maps:
                shutil.rmtree(dowloaded_data_folder)

            # Ensure no matplotlib figures accumulate across loop iterations.
            plt.close("all")

            elapsed = time.time() - t
            print("Elapsed time: " + str(round(elapsed)) + " s")
            time_diff = (
                datetime.datetime.now(datetime.timezone.utc) - start_time_ut_time_diff
            )
            time_diff = time_diff.seconds / 60
            # Advance by the configured cursor step to control cadence.
            current_time_ut = start_time_series + timedelta(minutes=time_step_minutes)

        else:
            print("No new data series. Wait 15 s.")
            time.sleep(15)
            time_diff = (
                datetime.datetime.now(datetime.timezone.utc) - start_time_ut_time_diff
            )
            time_diff = time_diff.seconds / 60
            continue
