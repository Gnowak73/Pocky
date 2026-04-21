import drms
from drms import ServerConfig
from urllib.request import urlretrieve
from urllib.error import URLError, HTTPError
import os
import sys
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
import atexit
import subprocess
import tempfile
import threading

from dateutil import tz

import matplotlib
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import matplotlib.colors as colors

import shutil

from PIL import Image

# **********************************************************

_TZ_CACHE = {}
_SUVI_URL_CACHE = {}
_SUVI_IMAGE_CACHE = {}
_GIF_FRAME_CACHE = {}
_IMMINENCE_RUNTIME = None
_IMMINENCE_WORKER_LOCK = threading.Lock()


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


def _safe_timestamp_for_path(timestamp):
    return str(timestamp).replace(":", "")


def _repo_root():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _bin_image_mean(img, factor):
    if factor <= 1:
        return np.asarray(img, dtype=np.float32)
    arr = np.asarray(img, dtype=np.float32)
    ny, nx = arr.shape
    ny2 = (ny // factor) * factor
    nx2 = (nx // factor) * factor
    if ny2 <= 0 or nx2 <= 0:
        return arr
    arr = arr[:ny2, :nx2]
    arr = arr.reshape(ny2 // factor, factor, nx2 // factor, factor)
    return arr.mean(axis=(1, 3))


def _load_imminence_runtime(model_path):
    global _IMMINENCE_RUNTIME
    if _IMMINENCE_RUNTIME is not None:
        return _IMMINENCE_RUNTIME
    if not model_path:
        _IMMINENCE_RUNTIME = False
        return _IMMINENCE_RUNTIME

    repo_root = _repo_root()
    ml_fft_dir = os.path.join(repo_root, "ML_FFT")
    vis_dir = os.path.join(repo_root, "Vis")
    for path in (ml_fft_dir, vis_dir):
        if path not in sys.path:
            sys.path.insert(0, path)

    try:
        from compute_visibilities import sample_visibilities
    except Exception as exc:
        print(f"Imminence visibility import failed: {exc}")
        print("Imminence model disabled for this run.")
        _IMMINENCE_RUNTIME = False
        return _IMMINENCE_RUNTIME

    model_path = os.path.abspath(model_path)
    if not os.path.exists(model_path):
        print(f"Imminence model not found: {model_path}")
        print("Imminence model disabled for this run.")
        _IMMINENCE_RUNTIME = False
        return _IMMINENCE_RUNTIME

    uv = np.load(os.path.join(vis_dir, "uv_grid.npz"))
    base_runtime = {
        "sample_visibilities": sample_visibilities,
        "u_vals": uv["u_vals"],
        "v_vals": uv["v_vals"],
        "pixel_arcsec": 0.6,
    }

    if os.environ.get("WAFFLE_USE_TORCH_WORKER") == "1":
        worker_runtime = _start_imminence_worker(model_path, base_runtime)
        if not worker_runtime:
            _IMMINENCE_RUNTIME = False
            return _IMMINENCE_RUNTIME
        _IMMINENCE_RUNTIME = worker_runtime
        return _IMMINENCE_RUNTIME

    try:
        import torch

        from scan_vis_features import frame_features
        from train_flare_imminence_classifier import (
            engineer_feature_table,
            make_model,
            softmax_np,
        )
    except Exception as exc:
        print(f"Imminence imports failed: {exc}")
        print("Imminence model disabled for this run.")
        _IMMINENCE_RUNTIME = False
        return _IMMINENCE_RUNTIME

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
    dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    net = make_model(
        len(feature_names),
        n_cls,
        str(args.get("model", "mlp")),
        int(args.get("hidden", 256)),
        float(args.get("dropout", 0.2)),
    ).to(dev)
    net.load_state_dict(ck["state_dict"])
    net.eval()

    _IMMINENCE_RUNTIME = {
        **base_runtime,
        "torch": torch,
        "device": dev,
        "model": net,
        "frame_features": frame_features,
        "engineer_feature_table": engineer_feature_table,
        "softmax_np": softmax_np,
        "warmup": int(args.get("warmup", 10)),
        "feature_mode": str(args.get("feature_mode", "all")),
        "feature_names": feature_names,
        "x_mean": x_mean,
        "x_std": x_std,
        "bins": bins,
        "risk_weights": risk_weights,
    }
    print(
        "Imminence model enabled: "
        f"{model_path} (warmup={_IMMINENCE_RUNTIME['warmup']}, bins={bins})"
    )
    return _IMMINENCE_RUNTIME


def _drain_worker_stderr(proc):
    try:
        for line in proc.stderr:
            text = line.rstrip()
            if text:
                print(f"Imminence worker: {text}")
    except Exception:
        pass


def _stop_imminence_worker(proc):
    if not proc or proc.poll() is not None:
        return
    try:
        proc.stdin.write(json.dumps({"cmd": "shutdown"}) + "\n")
        proc.stdin.flush()
        proc.wait(timeout=3)
    except Exception:
        try:
            proc.terminate()
        except Exception:
            pass


def _start_imminence_worker(model_path, base_runtime):
    conda = os.environ.get("WAFFLE_TORCH_CONDA", "conda")
    torch_env = os.environ.get("WAFFLE_TORCH_ENV", "Waffle_Torch")
    worker_path = os.path.join(os.path.dirname(__file__), "imminence_worker.py")
    if not os.path.exists(worker_path):
        print(f"Imminence worker not found: {worker_path}")
        print("Imminence model disabled for this run.")
        return False

    cmd = [
        conda,
        "run",
        "-n",
        torch_env,
        "python",
        worker_path,
        "--model",
        model_path,
        "--repo-root",
        _repo_root(),
    ]
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        threading.Thread(target=_drain_worker_stderr, args=(proc,), daemon=True).start()
        ready_line = proc.stdout.readline()
        ready = json.loads(ready_line) if ready_line else {}
        if not ready.get("ok"):
            raise RuntimeError(ready.get("error", "worker did not report ready"))
    except Exception as exc:
        print(f"Imminence worker failed to start: {exc}")
        print("Imminence model disabled for this run.")
        try:
            if proc:
                proc.terminate()
        except Exception:
            pass
        return False

    runtime = {
        **base_runtime,
        "external_worker": True,
        "worker_proc": proc,
        "warmup": int(ready.get("warmup", 10)),
        "bins": [float(x) for x in ready.get("bins", [])],
    }
    atexit.register(_stop_imminence_worker, proc)
    print(
        "Imminence model enabled through external Torch worker: "
        f"{model_path} (env={torch_env}, warmup={runtime['warmup']}, bins={runtime['bins']})"
    )
    return runtime


def _dirty_image_from_vis(v2d_centered):
    img = np.fft.ifft2(np.fft.ifftshift(v2d_centered), norm="ortho")
    return np.abs(np.fft.fftshift(img))


def _bright_region_centroid_masked(img, percentile=99.5, min_pixels=3):
    thr = float(np.percentile(img, percentile))
    mask = img >= thr
    if not np.any(mask):
        y0, x0 = np.unravel_index(int(np.argmax(img)), img.shape)
        return float(y0), float(x0)

    h, w = mask.shape
    visited = np.zeros_like(mask, dtype=bool)
    best = []
    for y in range(h):
        for x in range(w):
            if visited[y, x] or not mask[y, x]:
                continue
            stack = [(y, x)]
            visited[y, x] = True
            comp = []
            while stack:
                cy, cx = stack.pop()
                comp.append((cy, cx))
                for ny in range(max(0, cy - 1), min(h - 1, cy + 1) + 1):
                    for nx in range(max(0, cx - 1), min(w - 1, cx + 1) + 1):
                        if not visited[ny, nx] and mask[ny, nx]:
                            visited[ny, nx] = True
                            stack.append((ny, nx))
            if len(comp) > len(best):
                best = comp

    if len(best) < max(1, int(min_pixels)):
        y0, x0 = np.unravel_index(int(np.argmax(img)), img.shape)
        return float(y0), float(x0)

    ys = np.array([p[0] for p in best], dtype=np.float64)
    xs = np.array([p[1] for p in best], dtype=np.float64)
    ws = np.array([img[p[0], p[1]] for p in best], dtype=np.float64)
    s = float(ws.sum())
    if s <= 0.0:
        y0, x0 = np.unravel_index(int(np.argmax(img)), img.shape)
        return float(y0), float(x0)
    return float(np.sum(ys * ws) / s), float(np.sum(xs * ws) / s)


def _uv_coords_centered(h, w):
    cy = (h - 1) / 2.0
    cx = (w - 1) / 2.0
    v = ((np.arange(h, dtype=np.float64) - cy) / float(h))[:, None]
    u = ((np.arange(w, dtype=np.float64) - cx) / float(w))[None, :]
    return u, v


def _shift_complex_vis_to_brightspot(v3d, percentile=99.5, min_pixels=3):
    vmean = np.mean(v3d, axis=0)
    img = _dirty_image_from_vis(vmean)
    h, w = img.shape
    y0, x0 = _bright_region_centroid_masked(
        img, percentile=percentile, min_pixels=min_pixels
    )
    cy = (h - 1) / 2.0
    cx = (w - 1) / 2.0
    dy = float(y0 - cy)
    dx = float(x0 - cx)
    u, v = _uv_coords_centered(h, w)
    phase = np.exp(2j * np.pi * (u * dx + v * dy))
    return (v3d * phase[None, :, :]).astype(np.complex64)


def _visibility_frame_to_complex(vis_frame):
    arr = np.asarray(vis_frame, dtype=np.float32)
    if arr.shape[0] != 10:
        raise ValueError(f"Expected visibility frame shape (10,H,W), got {arr.shape}")
    return arr[:5].astype(np.float32) + 1j * arr[5:].astype(np.float32)


def _visibility_brightspot_offset(vis_frame):
    vis_complex = _visibility_frame_to_complex(vis_frame)
    img = _dirty_image_from_vis(np.mean(vis_complex, axis=0))
    h, w = img.shape
    y0, x0 = _bright_region_centroid_masked(img, percentile=99.5, min_pixels=3)
    cy = (h - 1) / 2.0
    cx = (w - 1) / 2.0
    return float(x0 - cx), float(y0 - cy)


def _save_box_visibility_frame(
    vis_frame,
    output_root,
    timestamp_utc,
    box_label,
    arnum,
    em_total,
    risk=np.nan,
    prob=None,
):
    stamp_dir = os.path.join(output_root, _safe_timestamp_for_path(timestamp_utc))
    mkdir(stamp_dir)
    box_dir = os.path.join(stamp_dir, str(box_label))
    mkdir(box_dir)
    channels = np.array(
        ["94_re", "131_re", "171_re", "193_re", "211_re", "94_im", "131_im", "171_im", "193_im", "211_im"]
    )
    dx, dy = _visibility_brightspot_offset(vis_frame)
    np.savez_compressed(
        os.path.join(box_dir, f"{box_label}_vis.npz"),
        vis=np.asarray(vis_frame, dtype=np.float32),
        channels=channels,
        timestamp=np.array(timestamp_utc),
        box_label=np.array(str(box_label)),
        arnum=np.array(int(arnum)),
        em_total=np.array(float(em_total), dtype=np.float64),
        risk=np.array(float(risk), dtype=np.float32),
        probabilities=np.asarray([] if prob is None else prob, dtype=np.float32),
        brightspot_dx_pix=np.array(dx, dtype=np.float32),
        brightspot_dy_pix=np.array(dy, dtype=np.float32),
        centered_brightspot=np.array(abs(dx) < 1.0 and abs(dy) < 1.0),
    )


def _extract_box_visibility_frame(aia_img, runtime, recenter=True, bin_factor=4):
    cube = np.asarray(aia_img, dtype=np.float32)
    if cube.ndim != 3:
        raise ValueError(f"Expected 3D cube, got shape {cube.shape}")
    if cube.shape[-1] == 5:
        cube = np.transpose(cube, (2, 0, 1))
    elif cube.shape[0] != 5:
        raise ValueError(f"Expected 5 channels, got shape {cube.shape}")

    pixel_arcsec = runtime["pixel_arcsec"] * max(int(bin_factor), 1)
    vis_complex = []
    for img in cube:
        img2 = _bin_image_mean(img, max(int(bin_factor), 1))
        vis = runtime["sample_visibilities"](
            img2,
            runtime["u_vals"],
            runtime["v_vals"],
            pixel_arcsec,
            0.0,
            0.0,
            False,
            True,
            False,
            False,
        )
        vis_complex.append(vis.astype(np.complex64))

    vis_complex = np.stack(vis_complex, axis=0)

    # Old runtime path: image-space centroiding before visibility computation.
    # Kept here for reference because it is not what the trained cache used.
    #
    # base = np.nanmean(cube, axis=0)
    # base = np.nan_to_num(base, nan=0.0, posinf=0.0, neginf=0.0)
    # x0 = 0.0
    # y0 = 0.0
    # if recenter and np.any(base > 0):
    #     work = _bin_image_mean(base, max(int(bin_factor), 1))
    #     yy, xx = np.indices(work.shape)
    #     w = np.clip(work, 0.0, None)
    #     denom = float(w.sum())
    #     if denom > 0.0:
    #         cx = float((w * xx).sum() / denom)
    #         cy = float((w * yy).sum() / denom)
    #         x0 = (cx - (work.shape[1] - 1) / 2.0) * pixel_arcsec
    #         y0 = (cy - (work.shape[0] - 1) / 2.0) * pixel_arcsec

    if recenter:
        vis_complex = _shift_complex_vis_to_brightspot(vis_complex)

    re_list = [np.real(v).astype(np.float32) for v in vis_complex]
    im_list = [np.imag(v).astype(np.float32) for v in vis_complex]
    return np.stack(re_list + im_list, axis=0)


def _infer_imminence_risk_from_history(vis_history, runtime):
    if len(vis_history) <= runtime["warmup"]:
        return np.nan, None
    if runtime.get("external_worker"):
        proc = runtime.get("worker_proc")
        if not proc or proc.poll() is not None:
            return np.nan, None
        tmp_path = ""
        try:
            with tempfile.NamedTemporaryFile(
                suffix=".npz", prefix="waffle_vis_", delete=False
            ) as tmp:
                tmp_path = tmp.name
            np.savez_compressed(
                tmp_path, vis=np.asarray(vis_history, dtype=np.float32)
            )
            with _IMMINENCE_WORKER_LOCK:
                proc.stdin.write(json.dumps({"cmd": "infer", "path": tmp_path}) + "\n")
                proc.stdin.flush()
                line = proc.stdout.readline()
            resp = json.loads(line) if line else {}
            if not resp.get("ok"):
                return np.nan, None
            risk = resp.get("risk")
            prob = resp.get("probabilities")
            return (
                float(risk) if risk is not None else np.nan,
                None if prob is None else np.asarray(prob, dtype=np.float32),
            )
        except Exception as exc:
            print(f"Imminence worker inference failed: {exc}")
            return np.nan, None
        finally:
            if tmp_path:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

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
        return np.nan, None
    x = np.asarray(X[-1], dtype=np.float32).reshape(-1)
    x_norm = ((x - runtime["x_mean"]) / runtime["x_std"]).astype(np.float32)
    torch = runtime["torch"]
    with torch.no_grad():
        logits = (
            runtime["model"](
                torch.from_numpy(x_norm).unsqueeze(0).to(runtime["device"])
            )
            .cpu()
            .numpy()
        )
    prob = runtime["softmax_np"](logits)[0]
    risk = float(np.sum(prob * runtime["risk_weights"]))
    return risk, prob


def plot_imminence_risk_history(
    latest_plots_folder,
    risk_history,
    color_arr,
    label,
    alert_threshold,
    focus_label=None,
):
    fig, ax = plt.subplots(figsize=(11, 3.5))
    plotted = False
    for i, lab in enumerate(label):
        if focus_label is not None and lab != focus_label:
            continue
        vals = [float(x) for x in risk_history.get(lab, []) if np.isfinite(x)]
        if not vals:
            continue
        xs = np.arange(len(vals))
        ax.plot(xs, vals, color=color_arr[i], linewidth=2, label=lab)
        plotted = True
    ax.axhline(alert_threshold, color="black", linestyle="--", linewidth=1)
    ax.set_ylim(-0.02, 1.02)
    ax.set_ylabel("Risk")
    ax.set_xlabel("Recent frames")
    if focus_label is None:
        ax.set_title("Imminence Risk History")
    else:
        ax.set_title(f"Imminence Risk History - Box {focus_label}")
    if plotted:
        ax.legend(loc="upper left", ncol=min(6, len(label)))
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    plt.savefig(
        os.path.join(latest_plots_folder, "imminence_risk.png"),
        dpi=160,
        bbox_inches="tight",
    )
    plt.close(fig)


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


def configure_jsoc_server(use_nrt2_server=True):
    """
    Function configuring a JSOC server (to be used for quering AIA data throgh drms)

    Returns
        -------
        client: drms client server
    """

    if use_nrt2_server:
        server = ServerConfig(
            name="JSOC",
            cgi_baseurl="http://jsoc2.stanford.edu/cgi-bin/ajax/",
            cgi_show_series="show_series",
            cgi_jsoc_info="jsoc_info",
            cgi_jsoc_fetch="jsoc_fetch",
            cgi_check_address="checkAddress.sh",
            cgi_show_series_wrapper="showextseries",
            show_series_wrapper_dbhost="hmidb2",
            http_download_baseurl="http://jsoc2.stanford.edu/",
        )
        client = drms.Client(server=server)
    else:
        # Public JSOC path for archive/public series.
        client = drms.Client()

    return client


# **********************************************************


def download_aia_data(
    wav,
    t_rec,
    segments,
    data_folder,
    timezone="US/Central",
    silent=False,
    worker_count=5,
    executor=None,
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
    if executor is None:
        n_workers = max(1, min(int(worker_count), len(wav)))
        with ThreadPoolExecutor(max_workers=n_workers) as local_executor:
            futures = [local_executor.submit(_download_one, i) for i in range(len(wav))]
            for future in as_completed(futures):
                i, filename, this_error = future.result()
                if this_error:
                    error = True
                    continue
                try:
                    aia_maps[i] = Map(filename)
                except Exception:
                    error = True
    else:
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


def calibrate_full_disk_maps(aia_maps, workers=1, executor=None):
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
    if len(aia_maps) == 0:
        return []

    if workers is None:
        workers = 1
    workers = max(1, min(int(workers), len(aia_maps)))

    if workers == 1:
        calibrated_aia_maps = [register(this_map) for this_map in aia_maps]
    elif executor is not None:
        calibrated_aia_maps = list(executor.map(register, aia_maps))
    else:
        # Register maps in parallel; preserves order by consuming map(...) directly.
        with ThreadPoolExecutor(max_workers=workers) as ex:
            calibrated_aia_maps = list(ex.map(register, aia_maps))

    return calibrated_aia_maps


# **********************************************************


def normalize_full_disk_maps(aia_maps, workers=1, executor=None):
    """
    Apply exposure normalization (DN -> DN/s) on full-disk maps once per cycle.
    """
    if len(aia_maps) == 0:
        return []

    if workers is None:
        workers = 1
    workers = max(1, min(int(workers), len(aia_maps)))

    if workers == 1:
        return [normalize_exposure(this_map) for this_map in aia_maps]
    if executor is not None:
        return list(executor.map(normalize_exposure, aia_maps))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(normalize_exposure, aia_maps))


# **********************************************************


def precompute_em_calibrated_full_maps(
    aia_maps, correction_table, workers=1, executor=None, already_normalized=False
):
    """
    Apply exposure normalization + degradation correction on full-disk maps.
    """
    if len(aia_maps) == 0:
        return []

    def _calib(this_map):
        base_map = this_map if already_normalized else normalize_exposure(this_map)
        return correct_degradation(
            base_map,
            correction_table=correction_table,
        )

    if workers is None:
        workers = 1
    workers = max(1, min(int(workers), len(aia_maps)))

    if workers == 1:
        return [_calib(this_map) for this_map in aia_maps]
    if executor is not None:
        return list(executor.map(_calib, aia_maps))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(_calib, aia_maps))


# **********************************************************


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
    save_submaps_timestamp=None,
    save_submaps_label=None,
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
            if save_submaps_timestamp:
                safe_stamp = _safe_timestamp_for_path(save_submaps_timestamp)
                stamp_dir = os.path.join(cropped_maps_folder, safe_stamp)
                box_dir = os.path.join(
                    stamp_dir,
                    str(save_submaps_label)
                    if save_submaps_label is not None
                    else "ar" + str(arnum),
                )
                wav_dir = os.path.join(box_dir, str(wav))
                mkdir(stamp_dir)
                mkdir(box_dir)
                mkdir(wav_dir)
                fitsname = os.path.join(
                    wav_dir,
                    f"aia.lev1_euv_12s.{safe_stamp}.{wav}.image_lev1.fits",
                )
            else:
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


def fast_crop_em_cube(aia_maps, ar_lon, ar_lat, n_pix_x=1000, n_pix_y=1000):
    """
    Faster crop path for EM computation.
    Uses one WCS submap (for metadata) and NumPy slicing for all channels.
    """
    if len(aia_maps) == 0:
        return np.empty((0, 0, 0)), None

    ref = aia_maps[0]
    this_coord = SkyCoord(
        ar_lon * u.deg, ar_lat * u.deg, frame=frames.HeliographicStonyhurst
    )
    pix_x = int(np.round(ref.world_to_pixel(this_coord).x.value))
    pix_y = int(np.round(ref.world_to_pixel(this_coord).y.value))

    ny_ref, nx_ref = ref.data.shape
    x0 = max(0, pix_x - n_pix_x // 2)
    y0 = max(0, pix_y - n_pix_y // 2)
    x1 = min(nx_ref, x0 + n_pix_x)
    y1 = min(ny_ref, y0 + n_pix_y)
    x0 = max(0, x1 - n_pix_x)
    y0 = max(0, y1 - n_pix_y)

    # Build metadata once from a true SunPy submap on reference channel.
    bl = ref.pixel_to_world(x0 * u.pix, y0 * u.pix)
    tr = ref.pixel_to_world((x1 - 1) * u.pix, (y1 - 1) * u.pix)
    ref_sub = ref.submap(bl, top_right=tr)
    metadata = ref_sub.meta

    # Slice all channels directly.
    arrs = []
    for this_map in aia_maps:
        arrs.append(this_map.data[y0:y1, x0:x1])

    min_ny = min(a.shape[0] for a in arrs)
    min_nx = min(a.shape[1] for a in arrs)
    arrs = [a[:min_ny, :min_nx] for a in arrs]
    cube = np.stack(arrs, axis=0)
    cube = np.transpose(cube, (1, 2, 0))
    return cube, metadata


# **********************************************************


def submaps_to_em_cube(aia_submaps):
    """
    Convert channel submaps into an EM cube with shape (ny, nx, nchannels).
    """
    if len(aia_submaps) == 0:
        return np.empty((0, 0, 0)), None

    arrs = [this_map.data for this_map in aia_submaps]
    min_ny = min(a.shape[0] for a in arrs)
    min_nx = min(a.shape[1] for a in arrs)
    arrs = [a[:min_ny, :min_nx] for a in arrs]
    cube = np.stack(arrs, axis=0)
    cube = np.transpose(cube, (1, 2, 0))
    return cube, aia_submaps[0].meta


def save_box_crop_bundle(
    aia_maps,
    em_map,
    ar_lon,
    ar_lat,
    arnum,
    box_label,
    output_root,
    record_time_utc,
    n_pix_x=1000,
    n_pix_y=1000,
):
    """
    Save timestamped cropped AIA wavelength FITS plus the EM map for one box.

    Output layout:
        <output_root>/<timestamp-no-colons>/<box_label>/<wavelength>/aia.lev1_euv_12s.<timestamp-no-colons>.<wavelength>.image_lev1.fits
        <output_root>/<timestamp-no-colons>/<box_label>/em/em_map.fits
    """
    aia_submaps = crop_full_disk_maps(
        aia_maps,
        ar_lon,
        ar_lat,
        arnum,
        output_root,
        n_pix_x=n_pix_x,
        n_pix_y=n_pix_y,
        save_submaps=True,
        save_submaps_timestamp=record_time_utc,
        save_submaps_label=box_label,
    )
    stamp_dir = os.path.join(output_root, _safe_timestamp_for_path(record_time_utc))
    box_dir = os.path.join(stamp_dir, str(box_label))
    em_dir = os.path.join(box_dir, "em")
    mkdir(stamp_dir)
    mkdir(box_dir)
    mkdir(em_dir)
    fitsname = os.path.join(em_dir, "em_map.fits")
    astropy.io.fits.writeto(
        fitsname,
        em_map.data,
        em_map.fits_header,
        output_verify="exception",
        overwrite=True,
        checksum=False,
    )
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
        # Hydrate cache from existing CSV so restarts preserve prior series.
        try:
            time_em_array, total_em_array = load_em_series(
                file_name_em_csv, timezone=timezone, em_cache=None
            )
            em_cache[file_name_em_csv] = {
                "timezone": timezone,
                "time_em_array": np.array(time_em_array),
                "total_em": np.array(total_em_array, dtype=float),
            }
            cached = em_cache[file_name_em_csv]
        except Exception:
            em_cache[file_name_em_csv] = {
                "timezone": timezone,
                "time_em_array": np.array([dt_local]),
                "total_em": np.array([total_em_val], dtype=float),
            }
        return

    # Avoid duplicate timestamp insertion on restart/retry loops.
    if len(cached["time_em_array"]) > 0 and cached["time_em_array"][-1] == dt_local:
        cached["total_em"][-1] = total_em_val
    else:
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
    ssh_user = "emslie"  # massa"
    ssh_password = "waffle"  #'waffle!' FF_Proj

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
    suvi_wav = int(wav)
    if suvi_wav not in (94, 131):
        raise ValueError(
            f"Unsupported SUVI wavelength: {suvi_wav}. Allowed values are 94 or 131."
        )
    return "094" if suvi_wav == 94 else "131"


def _parse_suvi_obs_time_from_src(suvi_src):
    """
    Parse SUVI observation time from URL/filename when encoded.
    Returns UTC-aware datetime or None.
    """
    if not suvi_src:
        return None
    name = os.path.basename(str(suvi_src))
    # Primary SWPC SUVI flare product pattern:
    # ..._sYYYYMMDDTHHMMSSZ_... (start time token)
    m = re.search(r"_s(\d{8})T(\d{6})Z", name, flags=re.IGNORECASE)
    if not m:
        # Fallback for older/alternate naming:
        # YYYYMMDDTHHMMSS, YYYYMMDD_HHMMSS, YYYYMMDD-HHMMSS, or YYYYMMDDHHMMSS.
        m = re.search(r"(\d{8})[T_-]?(\d{6})", name)
    if not m:
        return None
    try:
        return datetime.datetime.strptime(
            m.group(1) + m.group(2), "%Y%m%d%H%M%S"
        ).replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return None


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
        # Support both href/src and single/double quotes.
        refs = re.findall(r'href=["\']([^"\']+\.png)["\']', html, flags=re.IGNORECASE)
        refs += re.findall(r'src=["\']([^"\']+\.png)["\']', html, flags=re.IGNORECASE)
        # Also capture bare .png tokens from directory listings.
        refs += re.findall(r'([A-Za-z0-9_./-]+\.png)', html, flags=re.IGNORECASE)
        seen = set()
        refs = [x for x in refs if not (x in seen or seen.add(x))]
        dated = []
        for h in refs:
            name = h.split("/")[-1].lower()
            if "latest.png" in name:
                continue
            ts = _parse_suvi_obs_time_from_src(name)
            if ts is None:
                continue
            d = ts.strftime("%Y%m%d")
            if d <= target_day:
                dated.append((ts, h))
        if dated:
            # latest available at or before requested day
            pick = sorted(dated, key=lambda x: x[0])[-1][1]
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


def resolve_suvi_latest_dated_url(wavelength=131, spacecraft="primary"):
    """
    Resolve most recent dated SUVI PNG from SWPC listing using directory order.
    Practical behavior: pick the latest listed dated file (typically the entry
    immediately before latest.png). Returns None if no dated file is found.
    """
    wav_dir = _suvi_wav_path(wavelength)
    base = f"https://services.swpc.noaa.gov/images/flares/hgs/{spacecraft}/{wav_dir}/"
    try:
        with urlopen(base, timeout=8) as r:
            html = r.read().decode("utf-8", errors="ignore")
        refs = re.findall(r'href=["\']([^"\']+\.png)["\']', html, flags=re.IGNORECASE)
        refs += re.findall(r'src=["\']([^"\']+\.png)["\']', html, flags=re.IGNORECASE)
        refs += re.findall(r'([A-Za-z0-9_./-]+\.png)', html, flags=re.IGNORECASE)
        seen = set()
        refs = [x for x in refs if not (x in seen or seen.add(x))]
        # Prefer the dated entry immediately before latest.png in listing order.
        latest_idx = -1
        for i, h in enumerate(refs):
            if "latest.png" in h.split("/")[-1].lower():
                latest_idx = i
                break
        if latest_idx > 0:
            for j in range(latest_idx - 1, -1, -1):
                h = refs[j]
                name = h.split("/")[-1].lower()
                if "latest.png" in name:
                    continue
                if _parse_suvi_obs_time_from_src(name) is None:
                    continue
                if h.startswith("http"):
                    return h
                return base + h.lstrip("./")
        dated = []
        for h in refs:
            name = h.split("/")[-1].lower()
            if "latest.png" in name:
                continue
            ts = _parse_suvi_obs_time_from_src(name)
            if ts is None:
                continue
            dated.append((ts, h))
        if not dated:
            return None
        pick = sorted(dated, key=lambda x: x[0])[-1][1]
        if pick.startswith("http"):
            return pick
        return base + pick.lstrip("./")
    except Exception:
        return None


# **********************************************************


def fetch_suvi_image_for_panel(
    suvi_top_wavelength=131,
    suvi_day_utc=None,
    suvi_use_realtime=False,
):
    """
    Fetch SUVI flare-location image for embedding in the full-disk panel figure.
    Returns (image_array_or_none, title_string, suvi_obs_time_utc_or_none).
    In realtime mode, uses latest dated SUVI file (not latest.png) so the
    timestamp is tied to that specific file.
    """
    suvi_wav = int(suvi_top_wavelength)
    wav_dir = _suvi_wav_path(suvi_wav)

    if suvi_use_realtime:
        suvi_src = resolve_suvi_latest_dated_url(
            wavelength=suvi_wav, spacecraft="primary"
        )
        title = f"SUVI {suvi_wav}Å"
    else:
        suvi_src = resolve_suvi_day_url(
            suvi_day_utc,
            wavelength=suvi_wav,
            spacecraft="primary",
        )
        title = f"SUVI {suvi_wav}Å"

    if not suvi_src:
        return None, title + " - not available", None

    cached = _SUVI_IMAGE_CACHE.get(suvi_src)
    if cached is not None:
        return cached["image"], title, cached.get("obs_time_utc")

    try:
        with urlopen(suvi_src, timeout=12) as r:
            img_bytes = r.read()
        with Image.open(io.BytesIO(img_bytes)) as im:
            arr = np.asarray(im.convert("RGB"))
        obs_time_utc = _parse_suvi_obs_time_from_src(suvi_src)
        _SUVI_IMAGE_CACHE.clear()
        _SUVI_IMAGE_CACHE[suvi_src] = {
            "image": arr,
            "obs_time_utc": obs_time_utc,
        }
        return arr, title, obs_time_utc
    except Exception:
        return None, title + " - unavailable", None


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

    index_html = build_waffle_v2_index_html(
        suvi_top_wavelength=suvi_top_wavelength,
        suvi_day_utc=suvi_day_utc,
        suvi_use_realtime=suvi_use_realtime,
    )

    with open(
        os.path.join(destination_volume, "index.html"), "w", encoding="utf-8"
    ) as f:
        f.write(index_html)


def build_waffle_v2_index_html(
    suvi_top_wavelength=131, suvi_day_utc=None, suvi_use_realtime=False
):
    index_html = ""
    # Use the template next to near_realtime_aia_pipeline.py / aux_functions.py.
    template_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "wku_template.html"
    )
    if not os.path.exists(template_path):
        index_html = """<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no"><title>WAFFLE v2</title></head><body><center><img id="image0" src="./latest_plots/full_disk_maps.gif" style="width:97.5%;max-width:100%;height:auto;"><br><img id="image1" src="./latest_plots/em_goes_plot.png" style="width:97.5%;max-width:100%;height:auto;"><br><img id="image2" src="./latest_plots/imminence_risk.png" style="width:85%;max-width:100%;height:auto;"><script>setInterval(function(){var t=new Date().getTime();document.getElementById("image0").src="./latest_plots/full_disk_maps.gif?t="+t;document.getElementById("image1").src="./latest_plots/em_goes_plot.png?t="+t;document.getElementById("image2").src="./latest_plots/imminence_risk.png?t="+t;},15000);</script></center></body></html>"""
    else:
        with open(template_path, "r", encoding="utf-8") as f:
            index_html = f.read()

    suvi_wav = int(suvi_top_wavelength)
    wav_dir = _suvi_wav_path(suvi_wav)
    if suvi_use_realtime:
        suvi_src = resolve_suvi_latest_dated_url(
            wavelength=suvi_wav, spacecraft="primary"
        )
    else:
        suvi_src = resolve_suvi_day_url(
            suvi_day_utc,
            wavelength=suvi_wav,
            spacecraft="primary",
        )
        if not suvi_src:
            suvi_src = ""
    if suvi_src is None:
        suvi_src = ""
    index_html = index_html.replace("__SUVI_TOP_WAVELENGTH__", str(suvi_wav))
    index_html = index_html.replace("__SUVI_TOP_SRC__", suvi_src)
    return index_html


def publish_remote_index_html(
    ssh_client,
    destination_volume,
    suvi_top_wavelength=131,
    suvi_day_utc=None,
    suvi_use_realtime=False,
):
    index_html = build_waffle_v2_index_html(
        suvi_top_wavelength=suvi_top_wavelength,
        suvi_day_utc=suvi_day_utc,
        suvi_use_realtime=suvi_use_realtime,
    )
    with SCPClient(ssh_client.get_transport()) as scp:
        scp.putfo(
            io.BytesIO(index_html.encode("utf-8")),
            remote_path=os.path.join(destination_volume, "index.html"),
        )


# **********************************************************


def select_data_to_download(
    start_time_series,
    grouped_wav,
    current_time_ut,
    wavelengths_needed,
    prefer_latest=True,
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

    # Realtime mode: pick latest valid cycle in window.
    # Archive mode: pick earliest valid cycle after cursor (step-following replay).
    if prefer_latest:
        idx_iter = range(len(start_time_series) - 1, -1, -1)
    else:
        idx_iter = range(len(start_time_series))

    for idx in idx_iter:
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

    # Keep a short rolling animation to reduce encode time per cycle.
    image_files = image_files[-6:]
    image_files.append(image_files[-1])

    duration_ms = max(1, int(1000 / max(1, fps)))
    frames = []
    for file_name in image_files:
        try:
            stat = os.stat(file_name)
            cache_key = (file_name, int(stat.st_mtime), stat.st_size)
        except OSError:
            continue

        cached_img = _GIF_FRAME_CACHE.get(cache_key)
        if cached_img is None:
            with Image.open(file_name) as img:
                cached_img = img.convert("P", palette=Image.Palette.ADAPTIVE)
            # Keep only recent entries to avoid unbounded cache growth.
            if len(_GIF_FRAME_CACHE) > 64:
                _GIF_FRAME_CACHE.clear()
            _GIF_FRAME_CACHE[cache_key] = cached_img

        # Use a copy so writer operations do not mutate cached base image.
        frames.append(cached_img.copy())

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
#     #ax8.spines['left'].set_color('blue')

#     fig.legend(bbox_to_anchor=(0.09, 0.05, 0.45, 0.38), fontsize=legsize)

#     fig.suptitle('AR ' + str(arnum) + ' - ' + time_em_array[-1].strftime("%H:%M:%S") + ' ' + timezone, fontsize=25)


#     plt.savefig(os.path.join(plots_folder, 'aia_em_' + str(i))  , dpi=100,bbox_inches='tight')
def load_realtime_XRS(reference_time_ut=None):
    """

    Function for loading the latest GOES XRS data (taken from https://github.com/pet00184/flarepred)

    Parameters
        ----------
        reference_time_ut: datetime or None
            Unused in v2 (kept for call-site compatibility).

    """

    # SWPC-only mode: use the same corrected `flux` values as the original method.
    # reference_time_ut is intentionally ignored in this mode.
    json_url = "https://services.swpc.noaa.gov/json/goes/primary/xrays-6-hour.json"
    df = None
    # Fail-safe, lightweight retry: keep stream alive on transient SWPC issues.
    for attempt in range(2):
        try:
            with urlopen(json_url, timeout=10) as r:
                payload = r.read().decode("utf-8", errors="strict")
            parsed = json.loads(payload)
            df = pd.DataFrame(parsed)
            break
        except Exception:
            if attempt == 0:
                time.sleep(0.8)
            else:
                return _empty_xrs_frames()

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


def _empty_xrs_frames():
    cols = ["time_tag", "flux", "energy"]
    return pd.DataFrame(columns=cols), pd.DataFrame(columns=cols)


def load_archive_XRS(reference_time_ut, goes_folder, lookback_hours=6):
    """
    Load historical GOES XRS data for archive/replay mode.

    Uses SunPy/Fido retrieval for XRS over a bounded window ending at reference_time_ut.
    Returns same dataframe structure as load_realtime_XRS.
    """
    if reference_time_ut is None:
        return _empty_xrs_frames()

    try:
        from sunpy.net import Fido, attrs as a
        from sunpy.timeseries import TimeSeries
    except Exception:
        return _empty_xrs_frames()

    try:
        end_time = reference_time_ut.astimezone(datetime.timezone.utc)
        start_time = end_time - timedelta(hours=float(lookback_hours))
        cache_dir = os.path.join(goes_folder, "archive_cache")
        mkdir(cache_dir)

        result = Fido.search(a.Time(start_time, end_time), a.Instrument("XRS"))
        if len(result) == 0:
            return _empty_xrs_frames()

        files = Fido.fetch(result, path=os.path.join(cache_dir, "{file}"))
        if len(files) == 0:
            return _empty_xrs_frames()

        ts = TimeSeries(files, concatenate=True)
        df = ts.to_dataframe()
        if df is None or len(df) == 0:
            return _empty_xrs_frames()

        # Handle common XRS column naming variants.
        cols = {str(c).lower(): c for c in df.columns}
        col_a = cols.get("xrsa")
        col_b = cols.get("xrsb")
        if col_a is None or col_b is None:
            return _empty_xrs_frames()

        # Ensure UTC-aware index for consistency.
        idx = pd.to_datetime(df.index, utc=True, errors="coerce")
        good = ~idx.isna()
        idx = idx[good]
        dfa = pd.to_numeric(df.loc[good, col_a], errors="coerce")
        dfb = pd.to_numeric(df.loc[good, col_b], errors="coerce")
        ok = ~(dfa.isna() | dfb.isna())
        idx = idx[ok]
        dfa = dfa[ok]
        dfb = dfb[ok]
        if len(idx) == 0:
            return _empty_xrs_frames()

        xrsa_current = pd.DataFrame(
            {
                "time_tag": idx.to_pydatetime(),
                "flux": np.asarray(dfa, dtype=float),
                "energy": "0.05-0.4nm",
            }
        )
        xrsb_current = pd.DataFrame(
            {
                "time_tag": idx.to_pydatetime(),
                "flux": np.asarray(dfb, dtype=float),
                "energy": "0.1-0.8nm",
            }
        )
        return xrsa_current.iloc[-100:].reset_index(drop=True), xrsb_current.iloc[
            -100:
        ].reset_index(drop=True)
    except Exception:
        return _empty_xrs_frames()


# **********************************************************
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
    trigger_states=None,
    trigger_times=None,
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

    # Match original WAFFLE behavior:
    # - x-max follows latest GOES time (realtime)
    # - x-min is one hour before latest AIA, but not before earliest GOES shown
    if len(goes_time_array) > 0:
        min_time = max(
            time_em_array[-1] - timedelta(minutes=60),
            np.min(goes_time_array),
        )
        max_time = np.max(goes_time_array)
    else:
        min_time = time_em_array[-1] - timedelta(minutes=60)
        max_time = time_em_array[-1]

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

    if trigger_times is not None:
        for trigger_time in trigger_times:
            if min_time <= trigger_time <= max_time:
                ax8.axvline(
                    trigger_time,
                    color="black",
                    linestyle="--",
                    linewidth=1.5,
                    alpha=0.9,
                    zorder=30,
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

    fig.legend(bbox_to_anchor=(0.46, -0.05, 0.45, 0.38), fontsize=legsize, ncol=2)

    if trigger_states is None:
        trigger_states = []
    any_trigger = any(bool(x) for x in trigger_states)
    face_color = "#2ca02c" if any_trigger else "#d62728"

    # Place the alert icon under the EM/GOES panel, away from the DEM panels.
    ax7_pos = ax7.get_position()
    face_size = 0.085
    face_ax = fig.add_axes(
        [
            ax7_pos.x1 - (3 * face_size) - 0.015,
            max(0.005, ax7_pos.y0 - (2 * face_size) - 0.04),
            face_size,
            face_size,
        ]
    )
    face_ax.set_xlim(0, 1)
    face_ax.set_ylim(0, 1)
    face_ax.set_aspect("equal")
    face_ax.axis("off")
    face_ax.add_patch(
        matplotlib.patches.Circle(
            (0.5, 0.5),
            0.46,
            facecolor=face_color,
            edgecolor="black",
            linewidth=2,
            zorder=20,
        )
    )
    for eye_x in (0.35, 0.65):
        face_ax.add_patch(
            matplotlib.patches.Circle(
                (eye_x, 0.62),
                0.055,
                facecolor="white",
                edgecolor="white",
                linewidth=1,
                zorder=21,
            )
        )
    mouth_theta = (205, 335) if any_trigger else (25, 155)
    mouth_y = 0.43 if any_trigger else 0.33
    face_ax.add_patch(
        matplotlib.patches.Arc(
            (0.5, mouth_y),
            0.42,
            0.30,
            theta1=mouth_theta[0],
            theta2=mouth_theta[1],
            color="white",
            linewidth=3,
            zorder=21,
        )
    )

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
    suvi_obs_time_utc=None,
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

    # Build ordered map list in O(n) without repeated np.where.
    map_by_wav = {int(m.meta["wavelnth"]): m for m in calibrated_aia_maps}
    ordered_aia_maps = [map_by_wav[w] for w in ordered_wav]

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

    # Reuse SkyCoord objects across channels.
    ar_coords = [
        SkyCoord(
            ar_lon[ii] * u.deg, ar_lat[ii] * u.deg, frame=frames.HeliographicStonyhurst
        )
        for ii in range(len(ar_lon))
    ]
    for jj in range(5):
        this_map = ordered_aia_maps[jj]

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
            this_coord = ar_coords[ii]

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
    if suvi_obs_time_utc is not None:
        suvi_time_local = convert_utc_to_timezone(suvi_obs_time_utc, timezone=timezone)
        suvi_panel_title = (
            f"{suvi_title} | {suvi_time_local.strftime('%Y-%m-%d %H:%M:%S')}"
        )
    else:
        suvi_panel_title = suvi_title
    ax6.set_title(suvi_panel_title, fontsize=20, pad=6, color="r")
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
    save_box_crops=False,
    box_crops_root=None,
    save_box_vis=False,
    box_vis_root=None,
    publish_mode="scp",
    local_publish_dir=None,
    drms_series="aia.lev1_nrt2",
    drms_segment="image_lev1",
    query_start_ut=None,
    time_step_minutes=None,
    worker_count=4,
    print_phase_timing=False,
    em_processing_mode=0,
    suvi_top_wavelength=131,
    suvi_use_realtime=False,
    imminence_model_path="",
    imminence_alert_threshold=0.68,
    imminence_alert_count=3,
    imminence_alert_avg_threshold=None,
    imminence_alert_peak_threshold=None,
    imminence_alert_delta_threshold=None,
    imminence_alert_baseline_count=15,
    imminence_em_nondecrease_tolerance=0.05,
    imminence_alert_cooldown_frames=10,
    imminence_bin_factor=4,
    imminence_recenter=True,
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

        worker_count: int. Shared worker threads used for download/calibration/AR compute.

        print_phase_timing: bool. If True, print per-phase timing diagnostics each cycle.

        em_processing_mode: int. EM crop/calibration strategy:
                            0 -> optimized (full-disk EM calibration + fast NumPy crop)
                            1 -> middle ground (full-disk EM calibration + WCS submaps)
                            2 -> WCS submaps first, then normalize/degradation per channel submap

        suvi_top_wavelength: int. SUVI wavelength used for the top-row remote image in generated website (94 or 131).

        suvi_use_realtime: bool. If True, force SUVI top image to use realtime latest.png;
                           if False, resolve a day-specific SUVI image from the stream day.

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
    if em_processing_mode not in (0, 1, 2):
        raise ValueError("em_processing_mode must be 0, 1, or 2")

    # Define colors that will be used for plotting the boxes and the corresponding curves
    color_arr = ["red", "gold", "blue", "lime", "cyan", "magenta"]

    # Define JSOC server client.
    use_nrt2_server = str(drms_series).lower().startswith("aia.lev1_nrt2")
    client = configure_jsoc_server(use_nrt2_server=use_nrt2_server)

    # Plots folder
    plots_folder = os.path.join(data_folder, "all_plots")
    mkdir(plots_folder)

    # Latest results folder
    latest_plots_folder = os.path.join(data_folder, "latest_plots")
    mkdir(latest_plots_folder)

    # AIA data folder
    aia_data_folder = os.path.join(data_folder, "aia_data_folder")
    mkdir(aia_data_folder)

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
    risk_history = {lab: [] for lab in label[:n_ar]}
    vis_history = {lab: [] for lab in label[:n_ar]}
    em_history = {lab: [] for lab in label[:n_ar]}
    imminence_trigger_times = []
    imminence_alert_cooldown_remaining = 0
    imminence_runtime = _load_imminence_runtime(imminence_model_path)
    plot_imminence_risk_history(
        latest_plots_folder,
        risk_history,
        color_arr,
        label,
        imminence_alert_threshold,
        focus_label=None,
    )

    # Array containing the wavelengths needed to compute the high temperature EM maps
    wavelengths_needed = np.array([94, 131, 171, 193, 211])

    # Initialize start time, current time and difference between start time and current time (zero at the beginning of the stream)
    realtime_mode = query_start_ut is None
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
    destination_volume = "/server/html/waffle_2/"
    ssh_client = None
    if publish_mode == "scp":
        ssh_client = define_ssh_client()
    elif publish_mode == "local":
        if local_publish_dir is None:
            local_publish_dir = os.path.join(data_folder, "local_web")
        mkdir(local_publish_dir)
    else:
        raise ValueError("publish_mode must be either 'scp' or 'local'")

    # One shared thread pool for the whole stream to avoid per-phase pool churn.
    worker_count = max(1, int(worker_count))
    shared_executor = None
    if worker_count > 1:
        shared_executor = ThreadPoolExecutor(max_workers=worker_count)

    ############ START STREAM

    try:
        while time_diff <= duration_stream:
            phase_times = {}
            cycle_start = time.time()
            t_phase = time.time()
            # Query data (retry transient/partial DRMS responses before skipping cycle).
            ds_query = (
                drms_series
                + "["
                + current_time_ut.strftime("%Y.%m.%d_%H:%M:%S")
                + "_UT/"
                + str(latency)
                + "m]"
            )
            query = None
            segments = None
            query_cols = set()
            query_ready = False
            for attempt in range(3):
                try:
                    query, segments = client.query(
                        ds_query,
                        key="T_REC, WAVELNTH",
                        seg=drms_segment,
                    )
                except Exception as err:
                    query = None
                    segments = None
                    if attempt < 2:
                        print("awaiting new data...")
                        time.sleep(2)
                        client = configure_jsoc_server(
                            use_nrt2_server=use_nrt2_server
                        )
                        continue
                    print("awaiting new data...")
                    break

                if query is not None and len(query) > 0:
                    query_cols = set(getattr(query, "columns", []))
                    if ("WAVELNTH" in query_cols) and ("T_REC" in query_cols):
                        query_ready = True
                        break

                if attempt < 2:
                    print("awaiting new data...")
                    time.sleep(2)
                    client = configure_jsoc_server(use_nrt2_server=use_nrt2_server)
                else:
                    print("awaiting new data...")
            if print_phase_timing:
                phase_times["query"] = time.time() - t_phase

            if not query_ready:
                time.sleep(15)
                time_diff = (
                    datetime.datetime.now(datetime.timezone.utc)
                    - start_time_ut_time_diff
                )
                time_diff = time_diff.seconds / 60
                continue

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
                    datetime.datetime.now(datetime.timezone.utc)
                    - start_time_ut_time_diff
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
                prefer_latest=realtime_mode,
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
                t_phase = time.time()
                aia_maps, dowloaded_data_folder, error = download_aia_data(
                    grouped_wav,
                    grouped_t_rec,
                    grouped_segments,
                    aia_data_folder,
                    timezone=timezone,
                    worker_count=worker_count,
                    executor=shared_executor,
                )
                if print_phase_timing:
                    phase_times["download"] = time.time() - t_phase

                t_phase = time.time()
                calibrated_aia_maps = calibrate_full_disk_maps(
                    aia_maps,
                    workers=worker_count,
                    executor=shared_executor,
                )
                normalized_aia_maps = normalize_full_disk_maps(
                    calibrated_aia_maps,
                    workers=worker_count,
                    executor=shared_executor,
                )
                # Precompute EM-calibrated full-disk maps once per cycle (avoids repeating
                # degradation/exposure calibration for each AR crop).
                em_calibrated_full_maps = precompute_em_calibrated_full_maps(
                    normalized_aia_maps,
                    correction_table=correction_table,
                    workers=worker_count,
                    executor=shared_executor,
                    already_normalized=True,
                )
                if print_phase_timing:
                    phase_times["calibrate"] = time.time() - t_phase

                if error:
                    print("Error in downloading data. Continue..")
                    time.sleep(30)
                    continue

                # Crop images around ARs and compute EM of the "hottest region"
                cropped_maps_folder = dowloaded_data_folder + "_crop"
                if save_maps:
                    mkdir(cropped_maps_folder)
                if save_box_crops:
                    if box_crops_root is None:
                        box_crops_root = os.path.join(data_folder, "box_crops")
                    mkdir(box_crops_root)
                if save_box_vis:
                    if box_vis_root is None:
                        box_vis_root = os.path.join(data_folder, "box_vis")
                    mkdir(box_vis_root)

                # Plot full-disk maps
                t_phase = time.time()
                suvi_day_key = start_time_series.astimezone(
                    datetime.timezone.utc
                ).strftime("%Y-%m-%d")
                suvi_img, suvi_title, suvi_obs_time_utc = fetch_suvi_image_for_panel(
                    suvi_top_wavelength=suvi_top_wavelength,
                    suvi_day_utc=suvi_day_key,
                    suvi_use_realtime=suvi_use_realtime,
                )
                plot_full_disk_images(
                    normalized_aia_maps,
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
                    suvi_obs_time_utc=suvi_obs_time_utc,
                )
                if print_phase_timing:
                    phase_times["full_disk_render"] = time.time() - t_phase

                # Create gif animation
                t_gif = time.time()
                create_animation_from_images(
                    plots_folder,
                    animation_filename=os.path.join(
                        latest_plots_folder, "full_disk_maps.gif"
                    ),
                    fps=2,
                )
                if print_phase_timing:
                    phase_times["full_disk_gif"] = time.time() - t_gif
                    phase_times["full_disk_plot"] = (
                        phase_times["full_disk_render"] + phase_times["full_disk_gif"]
                    )

                # Download GOES data
                t_phase = time.time()
                if realtime_mode:
                    xrsa_current, xrsb_current = load_realtime_XRS(
                        reference_time_ut=start_time_series
                    )
                else:
                    # Archive mode: skip GOES retrieval entirely.
                    xrsa_current, xrsb_current = _empty_xrs_frames()
                goes_plot_data = prepare_goes_plot_arrays(
                    xrsa_current, xrsb_current, timezone=timezone
                )
                if print_phase_timing:
                    phase_times["goes"] = time.time() - t_phase

                t_phase = time.time()
                em_maps = [None] * n_ar
                em_totals = [0.0] * n_ar
                vis_frames = [None] * n_ar

                def _compute_ar(i):
                    if em_processing_mode == 0:
                        aia_img, metadata = fast_crop_em_cube(
                            em_calibrated_full_maps,
                            ar_lon[i],
                            ar_lat[i],
                            n_pix_x=n_pix_x,
                            n_pix_y=n_pix_y,
                        )
                    elif em_processing_mode == 1:
                        aia_submaps = crop_full_disk_maps(
                            em_calibrated_full_maps,
                            ar_lon[i],
                            ar_lat[i],
                            arnum[i],
                            cropped_maps_folder,
                            n_pix_x=n_pix_x,
                            n_pix_y=n_pix_y,
                            save_submaps=False,
                        )
                        aia_img, metadata = submaps_to_em_cube(aia_submaps)
                    else:
                        aia_submaps_raw = crop_full_disk_maps(
                            calibrated_aia_maps,
                            ar_lon[i],
                            ar_lat[i],
                            arnum[i],
                            cropped_maps_folder,
                            n_pix_x=n_pix_x,
                            n_pix_y=n_pix_y,
                            save_submaps=False,
                        )
                        aia_submaps_em = []
                        for this_submap in aia_submaps_raw:
                            this_submap_norm = normalize_exposure(this_submap)
                            this_submap_em = correct_degradation(
                                this_submap_norm,
                                correction_table=correction_table,
                            )
                            aia_submaps_em.append(this_submap_em)
                        aia_img, metadata = submaps_to_em_cube(aia_submaps_em)

                    em_map_raw = compute_em_map(aia_img, metadata, weights)
                    em_map_th = em_map_raw.data.copy()
                    em_map_th[em_map_th < th_tot_em] = 0
                    # Match legacy WAFFLE scaling used in CSV totals.
                    total_em_current = float(np.sum(em_map_th) * 1.0e6 / (n_pix_x * n_pix_y))
                    return i, em_map_raw, total_em_current, aia_img

                n_workers = max(1, min(int(worker_count), n_ar))
                if n_workers == 1:
                    for i in range(n_ar):
                        i_out, em_map_raw, total_em_current, aia_img = _compute_ar(i)
                        em_maps[i_out] = em_map_raw
                        em_totals[i_out] = total_em_current
                        if imminence_runtime:
                            vis_frame = _extract_box_visibility_frame(
                                aia_img,
                                imminence_runtime,
                                recenter=imminence_recenter,
                                bin_factor=imminence_bin_factor,
                            )
                            vis_frames[i_out] = vis_frame
                            hist = vis_history[label[i_out]]
                            hist.append(vis_frame)
                            if len(hist) > 32:
                                del hist[:-32]
                else:
                    active_executor = shared_executor
                    if active_executor is None:
                        with ThreadPoolExecutor(max_workers=n_workers) as executor:
                            futures = [
                                executor.submit(_compute_ar, i) for i in range(n_ar)
                            ]
                            for fut in as_completed(futures):
                                i_out, em_map_raw, total_em_current, aia_img = fut.result()
                                em_maps[i_out] = em_map_raw
                                em_totals[i_out] = total_em_current
                                if imminence_runtime:
                                    vis_frame = _extract_box_visibility_frame(
                                        aia_img,
                                        imminence_runtime,
                                        recenter=imminence_recenter,
                                        bin_factor=imminence_bin_factor,
                                    )
                                    vis_frames[i_out] = vis_frame
                                    hist = vis_history[label[i_out]]
                                    hist.append(vis_frame)
                                    if len(hist) > 32:
                                        del hist[:-32]
                    else:
                        futures = [
                            active_executor.submit(_compute_ar, i) for i in range(n_ar)
                        ]
                        for fut in as_completed(futures):
                            i_out, em_map_raw, total_em_current, aia_img = fut.result()
                            em_maps[i_out] = em_map_raw
                            em_totals[i_out] = total_em_current
                            if imminence_runtime:
                                vis_frame = _extract_box_visibility_frame(
                                    aia_img,
                                    imminence_runtime,
                                    recenter=imminence_recenter,
                                    bin_factor=imminence_bin_factor,
                                )
                                vis_frames[i_out] = vis_frame
                                hist = vis_history[label[i_out]]
                                hist.append(vis_frame)
                                if len(hist) > 32:
                                    del hist[:-32]

                # Optional FITS exports remain single-threaded I/O.
                if save_maps:
                    for i in range(n_ar):
                        crop_full_disk_maps(
                            calibrated_aia_maps,
                            ar_lon[i],
                            ar_lat[i],
                            arnum[i],
                            cropped_maps_folder,
                            n_pix_x=n_pix_x,
                            n_pix_y=n_pix_y,
                            save_submaps=True,
                        )
                        fitsname = os.path.join(
                            cropped_maps_folder, "em_map_ar" + str(arnum[i]) + ".fits"
                        )
                        astropy.io.fits.writeto(
                            fitsname,
                            em_maps[i].data,
                            em_maps[i].fits_header,
                            output_verify="exception",
                            overwrite=True,
                            checksum=False,
                        )
                elif save_box_crops:
                    for i in range(n_ar):
                        save_box_crop_bundle(
                            calibrated_aia_maps,
                            em_maps[i],
                            ar_lon[i],
                            ar_lat[i],
                            arnum[i],
                            label[i],
                            box_crops_root,
                            grouped_t_rec[0],
                            n_pix_x=n_pix_x,
                            n_pix_y=n_pix_y,
                        )
                if print_phase_timing:
                    phase_times["em_compute"] = time.time() - t_phase

                focus_idx = int(np.argmax(np.asarray(em_totals, dtype=np.float64)))
                focus_label = label[focus_idx]
                trigger_states = [False] * n_ar
                cycle_new_trigger = False
                if imminence_runtime:
                    if imminence_alert_cooldown_remaining > 0:
                        imminence_alert_cooldown_remaining -= 1
                    recent_summary = []
                    for i in range(n_ar):
                        risk_val, prob_val = _infer_imminence_risk_from_history(
                            vis_history[label[i]], imminence_runtime
                        )
                        if np.isfinite(risk_val):
                            risk_history[label[i]].append(float(risk_val))
                            if len(risk_history[label[i]]) > 10:
                                del risk_history[label[i]][:-10]
                        if save_box_vis and vis_frames[i] is not None:
                            _save_box_visibility_frame(
                                vis_frames[i],
                                box_vis_root,
                                grouped_t_rec[0],
                                label[i],
                                arnum[i],
                                em_totals[i],
                                risk=risk_val,
                                prob=prob_val,
                            )
                        vals = risk_history[label[i]]
                        recent_vals = vals[-int(imminence_alert_count) :]
                        triggered = False
                        trigger_txt = "watch"
                        if len(recent_vals) >= int(imminence_alert_count):
                            avg_thr = (
                                float(imminence_alert_avg_threshold)
                                if imminence_alert_avg_threshold is not None
                                else float(imminence_alert_threshold)
                            )
                            avg_ok = float(np.mean(recent_vals)) >= avg_thr
                            peak_ok = (
                                True
                                if imminence_alert_peak_threshold is None
                                else float(np.max(recent_vals)) >= float(imminence_alert_peak_threshold)
                            )
                            delta_ok = True
                            baseline_avg = float("nan")
                            if imminence_alert_delta_threshold is not None:
                                base_n = int(imminence_alert_baseline_count)
                                prev_vals = vals[-(base_n + int(imminence_alert_count)) : -int(imminence_alert_count)]
                                if len(prev_vals) >= base_n:
                                    baseline_avg = float(np.mean(prev_vals))
                                    delta_ok = (
                                        float(np.mean(recent_vals)) - baseline_avg
                                    ) >= float(imminence_alert_delta_threshold)
                                else:
                                    delta_ok = False
                            em_ok = True
                            em_prev = float("nan")
                            em_curr = float(em_totals[i])
                            if (
                                imminence_em_nondecrease_tolerance is not None
                                and em_history[label[i]]
                            ):
                                em_prev = float(em_history[label[i]][-1])
                                if np.isfinite(em_prev) and em_prev > 0:
                                    em_ok = em_curr >= (
                                        1.0 - float(imminence_em_nondecrease_tolerance)
                                    ) * em_prev
                            triggered = avg_ok and peak_ok and delta_ok and em_ok
                            if i == focus_idx:
                                if triggered and imminence_alert_cooldown_remaining == 0:
                                    trigger_states[i] = True
                                    cycle_new_trigger = True
                                    imminence_alert_cooldown_remaining = max(
                                        0, int(imminence_alert_cooldown_frames)
                                    )
                                    trigger_txt = "TRIGGER"
                                elif triggered and imminence_alert_cooldown_remaining > 0:
                                    trigger_states[i] = True
                                    trigger_txt = (
                                        f"cooldown({imminence_alert_cooldown_remaining})"
                                    )
                                elif imminence_alert_cooldown_remaining > 0:
                                    trigger_states[i] = True
                                    trigger_txt = (
                                        f"cooldown({imminence_alert_cooldown_remaining})"
                                    )
                                else:
                                    trigger_txt = "watch"
                            else:
                                trigger_txt = "TRIGGER" if triggered else "watch"
                        if vals:
                            recent_txt = ", ".join(
                                f"{v:.3f}" for v in vals[-int(imminence_alert_count) :]
                            )
                            avg_recent = float(np.mean(recent_vals)) if recent_vals else float("nan")
                            peak_recent = float(np.max(recent_vals)) if recent_vals else float("nan")
                            baseline_avg = float("nan")
                            if imminence_alert_delta_threshold is not None:
                                base_n = int(imminence_alert_baseline_count)
                                prev_vals = vals[-(base_n + int(imminence_alert_count)) : -int(imminence_alert_count)]
                                if len(prev_vals) >= base_n:
                                    baseline_avg = float(np.mean(prev_vals))
                            msg = (
                                f"Box {label[i]} risk last {len(vals)}: [{recent_txt}] "
                                f"avg{int(imminence_alert_count)}={avg_recent:.3f} "
                                f"peak{int(imminence_alert_count)}={peak_recent:.3f} "
                            )
                            if imminence_alert_delta_threshold is not None:
                                if np.isfinite(baseline_avg):
                                    msg += (
                                        f"prev{int(imminence_alert_baseline_count)}={baseline_avg:.3f} "
                                        f"delta={avg_recent - baseline_avg:.3f} "
                                    )
                                else:
                                    msg += f"prev{int(imminence_alert_baseline_count)}=NA delta=NA "
                            em_prev = float("nan")
                            em_curr = float(em_totals[i])
                            if em_history[label[i]]:
                                em_prev = float(em_history[label[i]][-1])
                            if np.isfinite(em_prev) and em_prev > 0:
                                msg += f"em_ratio={em_curr / em_prev:.3f} "
                            else:
                                msg += "em_ratio=NA "
                            msg += f"-> {trigger_txt}"
                            print(msg)
                            recent_summary.append((label[i], vals[-1], triggered))
                    print(
                        f"Focus box by EM: {focus_label} "
                        f"(EM={float(em_totals[focus_idx]):.3e})"
                    )
                    if cycle_new_trigger:
                        trigger_time_utc = datetime.datetime.strptime(
                            grouped_t_rec[0], "%Y-%m-%dT%H:%M:%SZ"
                        ).replace(tzinfo=datetime.timezone.utc)
                        trigger_time_local = convert_utc_to_timezone(
                            trigger_time_utc, timezone=timezone
                        )
                        if (
                            not imminence_trigger_times
                            or imminence_trigger_times[-1] != trigger_time_local
                        ):
                            imminence_trigger_times.append(trigger_time_local)
                    plot_imminence_risk_history(
                        latest_plots_folder,
                        risk_history,
                        color_arr,
                        label,
                        imminence_alert_threshold,
                        focus_label=focus_label,
                    )

                for i in range(n_ar):
                    file_name_em_csv = os.path.join(
                        total_em_folder, "total_em_" + str(arnum[i]) + ".csv"
                    )
                    write_csv_em(file_name_em_csv, grouped_t_rec[0], em_totals[i])
                    em_history[label[i]].append(float(em_totals[i]))
                    if len(em_history[label[i]]) > 16:
                        del em_history[label[i]][:-16]
                    append_em_cache(
                        file_name_em_csv,
                        grouped_t_rec[0],
                        em_totals[i],
                        timezone=timezone,
                        em_cache=em_cache,
                    )

                    # v2: no detailed-analysis plot generation.

                # Plot GOES and AIA curves
                t_phase = time.time()
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
                    trigger_states=trigger_states,
                    trigger_times=imminence_trigger_times,
                )
                if print_phase_timing:
                    phase_times["em_goes_plot"] = time.time() - t_phase

                print("Publish data...")
                t_phase = time.time()
                if publish_mode == "scp":
                    ssh_scp_files(ssh_client, latest_plots_folder, destination_volume)
                    publish_remote_index_html(
                        ssh_client,
                        destination_volume,
                        suvi_top_wavelength=suvi_top_wavelength,
                        suvi_day_utc=start_time_series.astimezone(
                            datetime.timezone.utc
                        ).strftime("%Y-%m-%d"),
                        suvi_use_realtime=suvi_use_realtime,
                    )
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
                if print_phase_timing:
                    phase_times["publish"] = time.time() - t_phase

                if not save_maps:
                    t_phase = time.time()
                    shutil.rmtree(dowloaded_data_folder)
                    if print_phase_timing:
                        phase_times["cleanup"] = time.time() - t_phase

                # Ensure no matplotlib figures accumulate across loop iterations.
                plt.close("all")

                elapsed = time.time() - t
                if print_phase_timing:
                    phase_times["total_cycle"] = time.time() - cycle_start
                    print(
                        "Phase times (s): "
                        + ", ".join(
                            f"{k}={phase_times[k]:.2f}"
                            for k in [
                                "query",
                                "download",
                                "calibrate",
                                "full_disk_render",
                                "full_disk_gif",
                                "full_disk_plot",
                                "goes",
                                "em_compute",
                                "em_goes_plot",
                                "publish",
                                "cleanup",
                                "total_cycle",
                            ]
                            if k in phase_times
                        )
                    )
                print("Elapsed time: " + str(round(elapsed)) + " s")
                time_diff = (
                    datetime.datetime.now(datetime.timezone.utc)
                    - start_time_ut_time_diff
                )
                time_diff = time_diff.seconds / 60
                # Follow original stream behavior: advance cursor after each accepted cycle.
                # In replay mode this uses configured step; in realtime we follow the selected
                # cycle directly so the same cycle is not reprocessed.
                if realtime_mode:
                    current_time_ut = start_time_series
                else:
                    current_time_ut = start_time_series + timedelta(
                        minutes=time_step_minutes
                    )

            else:
                print("No new data series. Wait 15 s.")
                time.sleep(15)
                time_diff = (
                    datetime.datetime.now(datetime.timezone.utc)
                    - start_time_ut_time_diff
                )
                time_diff = time_diff.seconds / 60
                continue
    finally:
        if shared_executor is not None:
            shared_executor.shutdown(wait=True)
    # GOES folder
    goes_folder = os.path.join(data_folder, "goes_data_folder")
    mkdir(goes_folder)
