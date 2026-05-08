import drms
from drms import ServerConfig
import os
import sys
from pathlib import Path
from sunpy.map import Map
import datetime
from datetime import timedelta

from aiapy.calibrate import register, correct_degradation
import time

from sunpy.coordinates import frames

import csv
import random
import re

import astropy
from astropy.coordinates import SkyCoord
import astropy.units as u

import numpy as np

import glob
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed

from paramiko import SSHClient
from scp import SCPClient

import pytz

from urllib.request import urlopen
from urllib.error import HTTPError

import pandas as pd

import json
import io
import importlib.util
import pickle
import subprocess
import base64
import secrets
import socket
import threading
import http.server
import logging
import smtplib
from email.message import EmailMessage
from urllib.parse import urlparse
from urllib.parse import urljoin

from dateutil import tz

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import matplotlib.colors as colors

import shutil

from PIL import Image, ImageDraw, ImageFont

logging.getLogger("parfive").setLevel(logging.WARNING)

# **********************************************************

_TZ_CACHE = {}
_SUVI_URL_CACHE = {}
_SUVI_IMAGE_CACHE = {}
_GIF_FRAME_CACHE = {}


def resolve_run_day_and_query_start(today, query_start_time_utc):
    realtime_mode = today is None
    if realtime_mode:
        today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%b%d")

    if query_start_time_utc is None:
        if realtime_mode:
            query_start_ut = None
        else:
            query_start_ut = datetime.datetime.strptime(today, "%Y%b%d").replace(
                tzinfo=datetime.timezone.utc
            )
    else:
        query_start_ut = datetime.datetime.strptime(
            query_start_time_utc, "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=datetime.timezone.utc)

    if not realtime_mode and query_start_ut is not None:
        query_day = query_start_ut.astimezone(datetime.timezone.utc).strftime("%Y%b%d")
        if today != query_day:
            print(
                f"Archive replay config mismatch: today={today} but query_start_time_utc is on {query_day}; "
                f"using {query_day} for replay outputs/cache."
            )
            today = query_day
    return realtime_mode, today, query_start_ut


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc)


def resolve_drms_source(drms_mode):
    if drms_mode == "nrt2":
        return "aia.lev1_nrt2", "image_lev1"
    if drms_mode == "public":
        return "aia.lev1_euv_12s", "image"
    raise ValueError("drms_mode must be either 'nrt2' or 'public'")


def load_aia_correction_table():
    from aiapy.calibrate.utils import get_correction_table

    return get_correction_table()


def default_box_control_path(local_publish_dir):
    return os.path.join(local_publish_dir, "box_control.json")


def build_box_control_config(
    region_source,
    arnum,
    ar_x,
    ar_y,
    startup_box_recenter,
    startup_box_recenter_arcsec,
    box_recenter_interval_hours,
    min_box_center_dx_pix,
    min_box_center_dy_pix,
    solarmonitor_refresh_on_utc_day_rollover,
    solarmonitor_refresh_on_timezone_day_rollover,
):
    labels = ["A", "B", "C", "D", "E", "F"]
    boxes = {}
    for i, box_label in enumerate(labels):
        boxes[box_label] = {
            "arnum": int(arnum[i]) if i < len(arnum) and np.isfinite(arnum[i]) else 0,
            "x": int(round(float(ar_x[i])))
            if i < len(ar_x) and np.isfinite(ar_x[i])
            else None,
            "y": int(round(float(ar_y[i])))
            if i < len(ar_y) and np.isfinite(ar_y[i])
            else None,
        }
    return {
        "updated_utc": datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "region_source": str(region_source),
        "manual_boxes": boxes,
        "box_settings": {
            "startup_box_recenter": bool(startup_box_recenter),
            "startup_box_recenter_arcsec": float(startup_box_recenter_arcsec),
            "box_recenter_interval_hours": (
                None
                if box_recenter_interval_hours is None
                else float(box_recenter_interval_hours)
            ),
            "min_box_center_dx_pix": int(min_box_center_dx_pix),
            "min_box_center_dy_pix": int(min_box_center_dy_pix),
            "solarmonitor_refresh_on_utc_day_rollover": bool(
                solarmonitor_refresh_on_utc_day_rollover
            ),
            "solarmonitor_refresh_on_timezone_day_rollover": bool(
                solarmonitor_refresh_on_timezone_day_rollover
            ),
        },
    }


def _write_json_atomic(path, payload):
    mkdir(os.path.dirname(path))
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
    os.replace(tmp_path, path)


def initialize_box_control_file(control_path, default_payload):
    if not control_path:
        return
    if not os.path.exists(control_path):
        _write_json_atomic(control_path, default_payload)


def write_box_control_file(control_path, payload):
    if not control_path:
        return
    _write_json_atomic(control_path, payload)


def write_box_control_file_and_get_mtime(control_path, payload):
    if not control_path:
        return None
    _write_json_atomic(control_path, payload)
    try:
        return os.path.getmtime(control_path)
    except OSError:
        return None


def _load_json_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _coerce_box_control_payload(payload, fallback_payload):
    out = build_box_control_config(
        region_source=fallback_payload.get("region_source", "manual"),
        arnum=[fallback_payload["manual_boxes"][lab]["arnum"] for lab in ["A", "B", "C", "D", "E", "F"]],
        ar_x=[fallback_payload["manual_boxes"][lab]["x"] for lab in ["A", "B", "C", "D", "E", "F"]],
        ar_y=[fallback_payload["manual_boxes"][lab]["y"] for lab in ["A", "B", "C", "D", "E", "F"]],
        startup_box_recenter=fallback_payload["box_settings"]["startup_box_recenter"],
        startup_box_recenter_arcsec=fallback_payload["box_settings"]["startup_box_recenter_arcsec"],
        box_recenter_interval_hours=fallback_payload["box_settings"]["box_recenter_interval_hours"],
        min_box_center_dx_pix=fallback_payload["box_settings"]["min_box_center_dx_pix"],
        min_box_center_dy_pix=fallback_payload["box_settings"]["min_box_center_dy_pix"],
        solarmonitor_refresh_on_utc_day_rollover=fallback_payload["box_settings"]["solarmonitor_refresh_on_utc_day_rollover"],
        solarmonitor_refresh_on_timezone_day_rollover=fallback_payload["box_settings"]["solarmonitor_refresh_on_timezone_day_rollover"],
    )
    region_source = str(payload.get("region_source", out["region_source"])).strip().lower()
    out["region_source"] = "solarmonitor" if region_source == "solarmonitor" else "manual"
    box_settings = payload.get("box_settings", {}) if isinstance(payload, dict) else {}
    manual_boxes = payload.get("manual_boxes", {}) if isinstance(payload, dict) else {}
    for key in (
        "startup_box_recenter",
        "solarmonitor_refresh_on_utc_day_rollover",
        "solarmonitor_refresh_on_timezone_day_rollover",
    ):
        if key in box_settings:
            out["box_settings"][key] = bool(box_settings[key])
    for key in (
        "startup_box_recenter_arcsec",
        "box_recenter_interval_hours",
    ):
        if key in box_settings:
            try:
                value = box_settings[key]
                out["box_settings"][key] = None if value in (None, "", "None") else float(value)
            except Exception:
                pass
    for key in ("min_box_center_dx_pix", "min_box_center_dy_pix"):
        if key in box_settings:
            try:
                out["box_settings"][key] = int(float(box_settings[key]))
            except Exception:
                pass
    for lab in ["A", "B", "C", "D", "E", "F"]:
        box = manual_boxes.get(lab, {})
        if not isinstance(box, dict):
            continue
        if "arnum" in box:
            try:
                out["manual_boxes"][lab]["arnum"] = int(float(box["arnum"]))
            except Exception:
                pass
        for key in ("x", "y"):
            if key in box:
                try:
                    value = box[key]
                    out["manual_boxes"][lab][key] = None if value in (None, "", "None") else float(value)
                except Exception:
                    pass
    out["updated_utc"] = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    return out


def _validate_manual_box_control_payload(payload, max_radius_arcsec=1000.0):
    if str(payload.get("region_source", "")).strip().lower() != "manual":
        return
    bad_boxes = []
    for lab in ["A", "B", "C", "D", "E", "F"]:
        box = payload.get("manual_boxes", {}).get(lab, {})
        x = box.get("x")
        y = box.get("y")
        if x is None or y is None:
            bad_boxes.append(f"{lab}(missing)")
            continue
        try:
            x = float(x)
            y = float(y)
        except Exception:
            bad_boxes.append(f"{lab}(invalid)")
            continue
        if (not np.isfinite(x)) or (not np.isfinite(y)):
            bad_boxes.append(f"{lab}(invalid)")
            continue
        if (x * x + y * y) > float(max_radius_arcsec) ** 2:
            bad_boxes.append(f"{lab}({int(round(x))},{int(round(y))})")
    if bad_boxes:
        raise ValueError(
            "Manual box coordinates must stay on the solar disk. Invalid boxes: "
            + ", ".join(bad_boxes)
        )


class _LocalControlRequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(
        self,
        *args,
        directory=None,
        control_config_path=None,
        control_auth_user="",
        control_auth_password="",
        **kwargs,
    ):
        self._control_config_path = control_config_path
        self._control_auth_user = str(control_auth_user or "")
        self._control_auth_password = str(control_auth_password or "")
        super().__init__(*args, directory=directory, **kwargs)

    def log_message(self, fmt, *args):
        return

    def _send_json(self, status_code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _control_auth_enabled(self):
        return bool(self._control_auth_user or self._control_auth_password)

    def _is_control_path(self, path):
        return path in ("/control.html", "/api/box-control")

    def _authorized(self):
        if not self._control_auth_enabled():
            return True
        header = str(self.headers.get("Authorization", "") or "")
        if not header.startswith("Basic "):
            return False
        try:
            raw = base64.b64decode(header.split(" ", 1)[1]).decode("utf-8")
        except Exception:
            return False
        user, sep, password = raw.partition(":")
        if not sep:
            return False
        return secrets.compare_digest(user, self._control_auth_user) and secrets.compare_digest(
            password, self._control_auth_password
        )

    def _request_auth(self):
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="WAFFLE Box Control"')
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if self._is_control_path(parsed.path) and not self._authorized():
            self._request_auth()
            return
        if parsed.path == "/api/box-control":
            if not self._control_config_path or not os.path.exists(self._control_config_path):
                self._send_json(404, {"ok": False, "error": "box control unavailable"})
                return
            try:
                self._send_json(200, _load_json_file(self._control_config_path))
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if self._is_control_path(parsed.path) and not self._authorized():
            self._request_auth()
            return
        if parsed.path != "/api/box-control":
            self._send_json(404, {"ok": False, "error": "not found"})
            return
        if not self._control_config_path:
            self._send_json(404, {"ok": False, "error": "box control unavailable"})
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(content_length) if content_length > 0 else b"{}"
            incoming = json.loads(raw.decode("utf-8"))
            current = _load_json_file(self._control_config_path)
            payload = _coerce_box_control_payload(incoming, current)
            _validate_manual_box_control_payload(payload)
            _write_json_atomic(self._control_config_path, payload)
            self._send_json(200, {"ok": True, "config": payload})
        except Exception as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})


def start_local_publish_server(
    local_publish_dir,
    host,
    port,
    control_config_path=None,
    control_auth_user="",
    control_auth_password="",
):
    mkdir(local_publish_dir)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        if s.connect_ex((host, port)) == 0:
            print(f"Local web server not started: {host}:{port} already in use.")
            return None

    handler = lambda *args, **kwargs: _LocalControlRequestHandler(
        *args,
        directory=local_publish_dir,
        control_config_path=control_config_path,
        control_auth_user=control_auth_user,
        control_auth_password=control_auth_password,
        **kwargs,
    )
    server = http.server.ThreadingHTTPServer((host, port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"Local website server started at http://{host}:{port}")
    return {"server": server, "thread": thread}


def stop_local_publish_server(proc):
    if proc is None:
        return
    try:
        proc["server"].shutdown()
        proc["server"].server_close()
    finally:
        thread = proc.get("thread")
        if thread is not None:
            thread.join(timeout=3)
    print("Local website server stopped.")


def default_global_control_config_path():
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "global_control_config.json",
    )


def load_global_control_config(path):
    cfg_path = Path(path)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    default_cfg = {
        "ngrok_authtoken": "",
        "external_control_url": "",
    }
    if not cfg_path.exists():
        cfg_path.write_text(json.dumps(default_cfg, indent=2) + "\n", encoding="utf-8")
        return dict(default_cfg)
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        return dict(default_cfg)
    out = dict(default_cfg)
    if isinstance(data, dict):
        out["ngrok_authtoken"] = str(data.get("ngrok_authtoken", "") or "").strip()
        out["external_control_url"] = str(data.get("external_control_url", "") or "").strip()
    return out


def _extract_tunnel_url(line):
    match = re.search(r"https://[A-Za-z0-9.-]+", str(line))
    return match.group(0) if match else None


def resolve_global_control_url(tunnel_info, external_control_url=""):
    configured = str(external_control_url or "").strip()
    if configured:
        return configured
    if not tunnel_info:
        return ""
    public_url = str(tunnel_info.get("public_url", "") or "").rstrip("/")
    return public_url + "/control.html" if public_url else ""


def global_control_health_url(control_url):
    control_url = str(control_url or "").strip()
    if not control_url:
        return ""
    if control_url.endswith("/control.html"):
        return control_url[: -len("/control.html")] + "/status.json"
    return control_url.rstrip("/") + "/status.json"


def is_global_control_tunnel_healthy(
    tunnel_info,
    external_control_url="",
    timeout_sec=6.0,
):
    if not tunnel_info:
        return False
    proc = tunnel_info.get("proc")
    if proc is not None and proc.poll() is not None:
        return False
    health_url = global_control_health_url(
        resolve_global_control_url(tunnel_info, external_control_url)
    )
    if not health_url:
        return False
    try:
        with urlopen(health_url, timeout=float(timeout_sec)) as r:
            code = int(getattr(r, "status", 200) or 200)
        return 200 <= code < 500
    except HTTPError as exc:
        return 200 <= int(exc.code) < 500
    except Exception:
        return False


def start_global_control_tunnel(
    local_port,
    provider="auto",
    startup_timeout_sec=20.0,
    ngrok_authtoken="",
    external_control_url="",
):
    ngrok_authtoken = str(ngrok_authtoken or "").strip()
    external_control_url = str(external_control_url or "").strip()
    if ngrok_authtoken:
        try:
            import ngrok

            listener = ngrok.forward(
                int(local_port),
                authtoken=ngrok_authtoken,
            )
            public_url = str(listener.url()).rstrip("/")
            print(f"Global control tunnel started with ngrok sdk: {public_url}")
            return {
                "listener": listener,
                "provider": "ngrok-sdk",
                "public_url": public_url,
            }
        except Exception as exc:
            print(f"Global control tunnel ngrok sdk failed to start: {exc}")

    provider_order = []
    provider = str(provider or "auto").strip().lower()
    if provider == "auto":
        provider_order = ["ngrok", "cloudflared"]
    elif provider in ("ngrok", "cloudflared"):
        provider_order = [provider]
    else:
        raise ValueError(
            "global control provider must be 'auto', 'ngrok', or 'cloudflared'"
        )

    for name in provider_order:
        if name == "ngrok":
            if not ngrok_authtoken:
                continue
            try:
                import ngrok

                listener = ngrok.forward(
                    int(local_port),
                    authtoken=ngrok_authtoken,
                )
                public_url = str(listener.url()).rstrip("/")
                print(f"Global control tunnel started with ngrok sdk: {public_url}")
                return {
                    "listener": listener,
                    "provider": "ngrok-sdk",
                    "public_url": public_url,
                }
            except Exception as exc:
                print(f"Global control tunnel ngrok sdk failed to start: {exc}")
                continue
        if name == "cloudflared":
            try:
                from pycloudflared import try_cloudflare

                urls = try_cloudflare(int(local_port), verbose=False)
                url = str(urls.tunnel).rstrip("/")
                print(f"Global control tunnel started with pycloudflared: {url}")
                return {
                    "proc": urls.process,
                    "provider": "pycloudflared",
                    "public_url": url,
                }
            except Exception as exc:
                print(f"Global control tunnel pycloudflared fallback failed: {exc}")
    raise RuntimeError(
        "No supported Python tunnel could be started. Configure ngrok_authtoken for ngrok or use pycloudflared fallback."
    )


def stop_global_control_tunnel(tunnel_info):
    if not tunnel_info:
        return
    listener = tunnel_info.get("listener")
    if listener is not None:
        try:
            listener.close()
        except Exception:
            pass
    proc = tunnel_info.get("proc")
    if proc is None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def ensure_global_control_tunnel(
    tunnel_info,
    local_port,
    provider="auto",
    ngrok_authtoken="",
    external_control_url="",
    startup_timeout_sec=20.0,
    health_timeout_sec=6.0,
):
    if is_global_control_tunnel_healthy(
        tunnel_info,
        external_control_url=external_control_url,
        timeout_sec=health_timeout_sec,
    ):
        resolved_url = resolve_global_control_url(tunnel_info, external_control_url)
        return tunnel_info, resolved_url, False
    if tunnel_info:
        print("Global control tunnel unhealthy; restarting.")
    stop_global_control_tunnel(tunnel_info)
    new_info = start_global_control_tunnel(
        local_port,
        provider=provider,
        startup_timeout_sec=startup_timeout_sec,
        ngrok_authtoken=ngrok_authtoken,
        external_control_url=external_control_url,
    )
    resolved_url = resolve_global_control_url(new_info, external_control_url)
    return new_info, resolved_url, True

def em_active_area_fraction(em_map, active_threshold=1.0e43):
    arr = np.asarray(em_map, dtype=np.float64)
    if arr.size == 0 or not np.isfinite(arr).any():
        return 0.0
    arr = np.where(np.isfinite(arr), arr, 0.0)
    mask = arr >= float(active_threshold)
    active_pixels = int(np.sum(mask))
    total_pixels = int(mask.size)
    if active_pixels <= 0 or total_pixels <= 0:
        return 0.0
    return float(active_pixels / total_pixels)


def _runtime_state_path(data_folder):
    return os.path.join(data_folder, "waffle_v1p2_runtime_state.pkl")


def load_solarmonitor_regions(date_yyyymmdd, image_type="shmi_maglc", indexnum=1, timeout=15):
    """
    Load NOAA active-region centers from SolarMonitor for a given UTC date.

    Returns a list of dicts with:
    - region
    - lat_text / lon_text
    - x_arcsec / y_arcsec
    """
    url = (
        "https://www.solarmonitor.org/full_disk.php"
        f"?date={date_yyyymmdd}&type={image_type}&indexnum={int(indexnum)}"
    )
    with urlopen(url, timeout=timeout) as r:
        html = r.read().decode("utf-8", errors="replace")
    regions = []

    def _parse_first_int(text, default=0):
        m = re.search(r"(\d+)", text)
        return int(m.group(1)) if m else int(default)

    def _flare_strength(token):
        m = re.search(r"([ABCMX])\s*([0-9]+(?:\.[0-9]+)?)", token, re.I)
        if not m:
            return 0.0
        scale = {"A": 1e-3, "B": 1e-2, "C": 1.0, "M": 10.0, "X": 100.0}
        return scale[m.group(1).upper()] * float(m.group(2))

    row_pattern = re.compile(r'<tr class=noaaresults align=center>(.*?)</tr>', re.S)
    for row_html in row_pattern.findall(html):
        m_region = re.search(r'href="index\.php\?date=\d+&region=(\d+)"', row_html)
        m_pos = re.search(
            r'<td[^>]*id="position"[^>]*>\s*([NS]\d+)([EW]\d+)<br>\(([-+]?\d+)",([-\+]?\d+)"\)\s*</td>',
            row_html,
            re.S,
        )
        if not m_region or not m_pos:
            continue
        region = m_region.group(1)
        lat_txt, lon_txt, x_txt, y_txt = m_pos.groups()
        m_hale = re.search(r'<td[^>]*id="hale"[^>]*>\s*(.*?)\s*</td>', row_html, re.S)
        m_mcintosh = re.search(r'<td[^>]*id="mcintosh"[^>]*>\s*(.*?)\s*</td>', row_html, re.S)
        m_area = re.search(r'<td[^>]*id="area"[^>]*>\s*(.*?)\s*</td>', row_html, re.S)
        m_spots = re.search(r'<td[^>]*id="nspots"[^>]*>\s*(.*?)\s*</td>', row_html, re.S)
        m_events = re.search(r'<td[^>]*id="events"[^>]*>\s*(.*?)\s*</td>', row_html, re.S)

        hale_html = m_hale.group(1) if m_hale else ""
        mcintosh_html = m_mcintosh.group(1) if m_mcintosh else ""
        area_html = m_area.group(1) if m_area else ""
        spots_html = m_spots.group(1) if m_spots else ""
        events_html = m_events.group(1) if m_events else ""

        recent_flares = re.findall(r'([ABCMX]\d+(?:\.\d+)?)', events_html, re.I)
        flare_score = sum(_flare_strength(tok) for tok in recent_flares)
        area_val = _parse_first_int(area_html, default=0)
        spots_val = _parse_first_int(spots_html, default=0)
        hale_score = 2.0 * hale_html.lower().count("delta") + 1.0 * hale_html.lower().count("gamma")
        mcintosh_score = 0.5 * len(re.findall(r"[A-Za-z]", mcintosh_html.split("/")[0]))
        activity_score = 1000.0 * flare_score + area_val + 2.0 * spots_val + 10.0 * hale_score + mcintosh_score

        regions.append(
            {
                "region": int(region),
                "lat_text": lat_txt,
                "lon_text": lon_txt,
                "x_arcsec": float(x_txt),
                "y_arcsec": float(y_txt),
                "hale_html": hale_html,
                "mcintosh_html": mcintosh_html,
                "area": area_val,
                "spots": spots_val,
                "recent_flares": recent_flares,
                "activity_score": float(activity_score),
            }
        )
    return regions


def select_solarmonitor_box_layout(
    regions,
    per_row=3,
    min_dx_arcsec=300.0,
    min_dy_arcsec=300.0,
):
    """
    Pick the most active regions first, randomize ties, then map the selected
    set into WAFFLE's A/B/C top row and D/E/F bottom row.
    Prefer non-overlapping box centers when possible.
    """
    rng = random.SystemRandom()
    by_score = {}
    for region in regions:
        score = float(region.get("activity_score", 0.0))
        by_score.setdefault(score, []).append(region)
    ranked = []
    for score in sorted(by_score.keys(), reverse=True):
        bucket = list(by_score[score])
        rng.shuffle(bucket)
        ranked.extend(bucket)

    def loc_key(region):
        return (
            round(float(region["x_arcsec"]), 3),
            round(float(region["y_arcsec"]), 3),
        )

    def overlaps(candidate, selected_regions):
        for other in selected_regions:
            if (
                abs(float(candidate["x_arcsec"]) - float(other["x_arcsec"])) < float(min_dx_arcsec)
                and abs(float(candidate["y_arcsec"]) - float(other["y_arcsec"])) < float(min_dy_arcsec)
            ):
                return True
        return False

    selected = []
    picked_locs = set()
    for region in ranked:
        if len(selected) >= 2 * per_row:
            break
        key = loc_key(region)
        if key in picked_locs:
            continue
        if overlaps(region, selected):
            continue
        selected.append(region)
        picked_locs.add(key)

    # If strict non-overlap leaves us short, fill the remainder by score anyway.
    if len(selected) < 2 * per_row:
        picked = {r["region"] for r in selected}
        for region in ranked:
            if len(selected) >= 2 * per_row:
                break
            if region["region"] in picked:
                continue
            key = loc_key(region)
            if key in picked_locs:
                continue
            selected.append(region)
            picked.add(region["region"])
            picked_locs.add(key)

    top = sorted([r for r in selected if r["y_arcsec"] >= 0.0], key=lambda r: r["x_arcsec"])
    bottom = sorted([r for r in selected if r["y_arcsec"] < 0.0], key=lambda r: r["x_arcsec"])
    if len(top) < per_row or len(bottom) < per_row:
        selected_sorted = sorted(selected, key=lambda r: (r["y_arcsec"] < 0.0, r["x_arcsec"]))
        top = sorted(selected_sorted[:per_row], key=lambda r: r["x_arcsec"])
        bottom = sorted(selected_sorted[per_row : 2 * per_row], key=lambda r: r["x_arcsec"])
    else:
        top = top[:per_row]
        bottom = bottom[:per_row]
    top_sel = top
    bottom_sel = bottom
    return top_sel, bottom_sel


def resolve_solarmonitor_boxes(
    date_yyyymmdd,
    image_type="shmi_maglc",
    indexnum=1,
    n_pix_x=500,
    n_pix_y=500,
    min_center_dx_pix=None,
    min_center_dy_pix=None,
):
    regions = load_solarmonitor_regions(
        date_yyyymmdd,
        image_type=image_type,
        indexnum=indexnum,
    )
    if min_center_dx_pix is None:
        min_center_dx_pix = n_pix_x
    if min_center_dy_pix is None:
        min_center_dy_pix = n_pix_y
    box_width_arcsec = 0.6 * float(min_center_dx_pix)
    box_height_arcsec = 0.6 * float(min_center_dy_pix)
    top_sel, bottom_sel = select_solarmonitor_box_layout(
        regions,
        per_row=3,
        min_dx_arcsec=box_width_arcsec,
        min_dy_arcsec=box_height_arcsec,
    )
    selected = top_sel + bottom_sel
    fallback_needed = max(0, 6 - len(selected))
    selected_arnum = [int(r["region"]) % 10000 for r in selected]
    selected_x = [float(r["x_arcsec"]) for r in selected]
    selected_y = [float(r["y_arcsec"]) for r in selected]
    selected_priority = [float(r.get("activity_score", 0.0)) for r in selected]
    while len(selected_arnum) < 6:
        fallback_id = len(selected_arnum) - len(selected) + 1
        selected_arnum.append(fallback_id)
        selected_x.append(float("nan"))
        selected_y.append(float("nan"))
        selected_priority.append(float("-inf"))
    return {
        "top_sel": top_sel,
        "bottom_sel": bottom_sel,
        "arnum": selected_arnum[:6],
        "ar_x": np.array(selected_x[:6], dtype=float),
        "ar_y": np.array(selected_y[:6], dtype=float),
        "ar_priority": np.array(selected_priority[:6], dtype=float),
        "fallback_needed": fallback_needed,
    }


def resolve_initial_region_layout(
    region_source,
    query_start_ut,
    n_pix_x,
    n_pix_y,
    min_box_center_dx_pix,
    min_box_center_dy_pix,
    arnum_top,
    x_top,
    y_top,
    arnum_bottom,
    x_bottom,
    y_bottom,
    solarmonitor_type="shmi_maglc",
    solarmonitor_indexnum=1,
):
    x_top = np.array(x_top, dtype=float)
    y_top = np.array(y_top, dtype=float)
    x_bottom = np.array(x_bottom, dtype=float)
    y_bottom = np.array(y_bottom, dtype=float)

    if region_source == "manual":
        return {
            "ar_priority": np.zeros(6, dtype=float),
            "arnum_top": list(arnum_top),
            "x_top": x_top,
            "y_top": y_top,
            "arnum_bottom": list(arnum_bottom),
            "x_bottom": x_bottom,
            "y_bottom": y_bottom,
        }

    if region_source != "solarmonitor":
        raise ValueError("region_source must be either 'manual' or 'solarmonitor'")

    solarmonitor_anchor_ut = query_start_ut if query_start_ut is not None else utc_now()
    date_yyyymmdd = solarmonitor_anchor_ut.astimezone(datetime.timezone.utc).strftime(
        "%Y%m%d"
    )
    resolved = resolve_solarmonitor_boxes(
        date_yyyymmdd,
        image_type=solarmonitor_type,
        indexnum=solarmonitor_indexnum,
        n_pix_x=n_pix_x,
        n_pix_y=n_pix_y,
        min_center_dx_pix=min_box_center_dx_pix,
        min_center_dy_pix=min_box_center_dy_pix,
    )
    top_sel = resolved["top_sel"]
    bottom_sel = resolved["bottom_sel"]
    fallback_needed = int(resolved["fallback_needed"])
    print(
        "SolarMonitor regions: top="
        + ", ".join(
            f"{(r['region'] % 10000)}@({int(r['x_arcsec'])},{int(r['y_arcsec'])})"
            f"[score={r['activity_score']:.1f}]"
            for r in top_sel
        )
        + " bottom="
        + ", ".join(
            f"{(r['region'] % 10000)}@({int(r['x_arcsec'])},{int(r['y_arcsec'])})"
            f"[score={r['activity_score']:.1f}]"
            for r in bottom_sel
        )
    )
    if fallback_needed > 0:
        print(
            "SolarMonitor fallback placeholders: "
            + ", ".join(str(v) for v in range(1, fallback_needed + 1))
        )
    return {
        "ar_priority": np.array(resolved["ar_priority"], dtype=float),
        "arnum_top": resolved["arnum"][:3],
        "x_top": np.array(resolved["ar_x"][:3], dtype=float),
        "y_top": np.array(resolved["ar_y"][:3], dtype=float),
        "arnum_bottom": resolved["arnum"][3:6],
        "x_bottom": np.array(resolved["ar_x"][3:6], dtype=float),
        "y_bottom": np.array(resolved["ar_y"][3:6], dtype=float),
    }


def load_box_control_update(control_path, last_mtime):
    if not control_path or not os.path.exists(control_path):
        return None, last_mtime
    try:
        mtime = os.path.getmtime(control_path)
    except OSError:
        return None, last_mtime
    if last_mtime is not None and mtime <= last_mtime:
        return None, last_mtime
    try:
        return _load_json_file(control_path), mtime
    except Exception as exc:
        print(f"Box control reload skipped: {exc}")
        return None, last_mtime


def apply_box_control_runtime_config(
    control_cfg,
    query_anchor_ut,
    n_pix_x,
    n_pix_y,
    current_region_source,
    startup_box_recenter,
    startup_box_recenter_arcsec,
    box_recenter_interval_hours,
    min_box_center_dx_pix,
    min_box_center_dy_pix,
    solarmonitor_refresh_on_utc_day_rollover,
    solarmonitor_refresh_on_timezone_day_rollover,
):
    def _box_float(boxes, lab, key):
        value = boxes.get(lab, {}).get(key)
        if value in (None, "", "None"):
            return np.nan
        return float(value)

    requested_region_source = str(
        control_cfg.get("region_source", current_region_source)
    ).strip().lower()
    if requested_region_source != "solarmonitor":
        requested_region_source = "manual"
    box_settings = control_cfg.get("box_settings", {})
    startup_box_recenter = bool(
        box_settings.get("startup_box_recenter", startup_box_recenter)
    )
    startup_box_recenter_arcsec = float(
        box_settings.get("startup_box_recenter_arcsec", startup_box_recenter_arcsec)
    )
    interval_value = box_settings.get(
        "box_recenter_interval_hours", box_recenter_interval_hours
    )
    box_recenter_interval_hours = (
        None
        if interval_value in (None, "", "None")
        else float(interval_value)
    )
    min_box_center_dx_pix = int(
        float(box_settings.get("min_box_center_dx_pix", min_box_center_dx_pix))
    )
    min_box_center_dy_pix = int(
        float(box_settings.get("min_box_center_dy_pix", min_box_center_dy_pix))
    )
    solarmonitor_refresh_on_utc_day_rollover = bool(
        box_settings.get(
            "solarmonitor_refresh_on_utc_day_rollover",
            solarmonitor_refresh_on_utc_day_rollover,
        )
    )
    solarmonitor_refresh_on_timezone_day_rollover = bool(
        box_settings.get(
            "solarmonitor_refresh_on_timezone_day_rollover",
            solarmonitor_refresh_on_timezone_day_rollover,
        )
    )

    if (
        requested_region_source == "solarmonitor"
        and str(current_region_source).strip().lower() != "solarmonitor"
    ):
        resolved = resolve_initial_region_layout(
            region_source="solarmonitor",
            query_start_ut=query_anchor_ut,
            n_pix_x=n_pix_x,
            n_pix_y=n_pix_y,
            min_box_center_dx_pix=min_box_center_dx_pix,
            min_box_center_dy_pix=min_box_center_dy_pix,
            arnum_top=[0, 0, 0],
            x_top=[np.nan, np.nan, np.nan],
            y_top=[np.nan, np.nan, np.nan],
            arnum_bottom=[0, 0, 0],
            x_bottom=[np.nan, np.nan, np.nan],
            y_bottom=[np.nan, np.nan, np.nan],
        )
    else:
        if requested_region_source == "manual":
            boxes = control_cfg.get("manual_boxes", {})
            arnum_top = [int(float(boxes.get(lab, {}).get("arnum", 0) or 0)) for lab in ["A", "B", "C"]]
            x_top = [_box_float(boxes, lab, "x") for lab in ["A", "B", "C"]]
            y_top = [_box_float(boxes, lab, "y") for lab in ["A", "B", "C"]]
            arnum_bottom = [int(float(boxes.get(lab, {}).get("arnum", 0) or 0)) for lab in ["D", "E", "F"]]
            x_bottom = [_box_float(boxes, lab, "x") for lab in ["D", "E", "F"]]
            y_bottom = [_box_float(boxes, lab, "y") for lab in ["D", "E", "F"]]
            resolved = resolve_initial_region_layout(
                region_source="manual",
                query_start_ut=query_anchor_ut,
                n_pix_x=n_pix_x,
                n_pix_y=n_pix_y,
                min_box_center_dx_pix=min_box_center_dx_pix,
                min_box_center_dy_pix=min_box_center_dy_pix,
                arnum_top=arnum_top,
                x_top=x_top,
                y_top=y_top,
                arnum_bottom=arnum_bottom,
                x_bottom=x_bottom,
                y_bottom=y_bottom,
            )
        else:
            resolved = {
                "ar_priority": np.zeros(6, dtype=float),
                "arnum_top": [],
                "x_top": np.array([], dtype=float),
                "y_top": np.array([], dtype=float),
                "arnum_bottom": [],
                "x_bottom": np.array([], dtype=float),
                "y_bottom": np.array([], dtype=float),
            }

    if requested_region_source == "solarmonitor" and str(current_region_source).strip().lower() == "solarmonitor":
        arnum = None
        ar_x = None
        ar_y = None
        ar_priority = None
    else:
        ar_priority = resolved["ar_priority"]
        arnum = list(resolved["arnum_top"]) + list(resolved["arnum_bottom"])
        ar_x = np.concatenate((resolved["x_top"], resolved["x_bottom"]))
        ar_y = np.concatenate((resolved["y_top"], resolved["y_bottom"]))
    return {
        "region_source": requested_region_source,
        "startup_box_recenter": startup_box_recenter,
        "startup_box_recenter_arcsec": startup_box_recenter_arcsec,
        "box_recenter_interval_hours": box_recenter_interval_hours,
        "min_box_center_dx_pix": min_box_center_dx_pix,
        "min_box_center_dy_pix": min_box_center_dy_pix,
        "solarmonitor_refresh_on_utc_day_rollover": solarmonitor_refresh_on_utc_day_rollover,
        "solarmonitor_refresh_on_timezone_day_rollover": solarmonitor_refresh_on_timezone_day_rollover,
        "arnum": arnum,
        "ar_x": ar_x,
        "ar_y": ar_y,
        "ar_priority": ar_priority,
    }


def find_em_hotspot_boxes(
    aia_maps,
    weights,
    existing_xy,
    needed,
    min_dx_arcsec,
    min_dy_arcsec,
    disk_margin_arcsec=0.0,
):
    """
    Find non-overlapping fallback box centers from the strongest full-disk EM regions.
    Candidates are ranked by integrated EM in a box-sized window, not just by
    single-pixel hotspot intensity.
    A candidate is allowed as long as its center is on-disk and inside the map.
    Returns a list of (x_arcsec, y_arcsec) tuples.
    """
    if needed <= 0 or len(aia_maps) == 0:
        return []

    ref_map = aia_maps[0]
    arrs = [np.asarray(m.data) for m in aia_maps]
    min_ny = min(a.shape[0] for a in arrs)
    min_nx = min(a.shape[1] for a in arrs)
    aia_img = np.stack([a[:min_ny, :min_nx] for a in arrs], axis=-1)
    em_map = compute_em_map(aia_img, ref_map.meta, weights)
    em_data = np.array(em_map.data, dtype=float, copy=True)
    em_data[~np.isfinite(em_data)] = 0.0
    em_data = np.maximum(em_data, 0.0)

    ny, nx = em_data.shape
    half_w = max(1, int(np.ceil(float(min_dx_arcsec) / 0.6 / 2.0)))
    half_h = max(1, int(np.ceil(float(min_dy_arcsec) / 0.6 / 2.0)))
    span_x = 2 * half_w + 1
    span_y = 2 * half_h + 1

    # Rank candidate centers by integrated EM inside a box-sized window.
    integ = np.pad(em_data, ((1, 0), (1, 0)), mode="constant").cumsum(axis=0).cumsum(axis=1)
    y_idx = np.arange(ny)
    x_idx = np.arange(nx)
    y0 = np.clip(y_idx - half_h, 0, ny)
    y1 = np.clip(y_idx + half_h + 1, 0, ny)
    x0 = np.clip(x_idx - half_w, 0, nx)
    x1 = np.clip(x_idx + half_w + 1, 0, nx)
    score_map = (
        integ[y1[:, None], x1[None, :]]
        - integ[y0[:, None], x1[None, :]]
        - integ[y1[:, None], x0[None, :]]
        + integ[y0[:, None], x0[None, :]]
    )

    picked = []
    occupied = [
        (float(x), float(y))
        for x, y in existing_xy
        if np.isfinite(x) and np.isfinite(y)
    ]
    attempts = 0
    max_attempts = 5000
    while len(picked) < needed and attempts < max_attempts:
        attempts += 1
        flat_idx = int(np.argmax(score_map))
        peak = float(score_map.flat[flat_idx])
        if not np.isfinite(peak) or peak <= 0.0:
            break
        ypix, xpix = np.unravel_index(flat_idx, score_map.shape)
        world = ref_map.pixel_to_world(xpix * u.pix, ypix * u.pix)
        x_arcsec = float(world.Tx.to_value(u.arcsec))
        y_arcsec = float(world.Ty.to_value(u.arcsec))
        on_disk = _is_valid_hpc_center(
            ref_map,
            x_arcsec,
            y_arcsec,
            disk_margin_arcsec=disk_margin_arcsec,
        )
        overlaps = any(
            abs(x_arcsec - ox) < float(min_dx_arcsec) and abs(y_arcsec - oy) < float(min_dy_arcsec)
            for ox, oy in occupied
        )
        iy0 = max(0, ypix - span_y + 1)
        iy1 = min(ny, ypix + span_y)
        ix0 = max(0, xpix - span_x + 1)
        ix1 = min(nx, xpix + span_x)
        score_map[iy0:iy1, ix0:ix1] = -np.inf
        if not on_disk or overlaps:
            continue
        picked.append((x_arcsec, y_arcsec))
        occupied.append((x_arcsec, y_arcsec))
    return picked


def assign_fallback_arnums(current_arnum, slots):
    used = {int(v) for i, v in enumerate(current_arnum) if i not in slots and np.isfinite(v)}
    next_id = 1
    assigned = {}
    for slot in slots:
        while next_id in used:
            next_id += 1
        assigned[slot] = int(next_id)
        used.add(int(next_id))
        next_id += 1
    return assigned


def reorder_box_layout(arnum, ar_x, ar_y, ar_priority=None):
    """
    Keep WAFFLE box assignment stable:
    - top row (A/B/C): left-to-right
    - bottom row (D/E/F): left-to-right
    Fallback-filled boxes are reordered into that layout before plotting/inference.
    Guarantee the top three boxes have y >= the bottom three boxes by splitting
    the valid boxes into an upper row and a lower row by y-rank, not by sign.
    """
    items = []
    for i in range(len(arnum)):
        items.append(
            {
                "arnum": int(arnum[i]) if np.isfinite(arnum[i]) else arnum[i],
                "x": float(ar_x[i]),
                "y": float(ar_y[i]),
                "priority": (
                    float(ar_priority[i])
                    if ar_priority is not None and i < len(ar_priority) and np.isfinite(ar_priority[i])
                    else 0.0
                ),
            }
        )

    valid = [it for it in items if np.isfinite(it["x"]) and np.isfinite(it["y"])]
    invalid = [it for it in items if not (np.isfinite(it["x"]) and np.isfinite(it["y"]))]
    by_y = sorted(valid, key=lambda it: (-it["y"], it["x"], -it["priority"]))
    top_seed = by_y[:3]
    bottom_seed = by_y[3:]
    top = sorted(top_seed, key=lambda it: (it["x"], -it["priority"]))
    bottom = sorted(bottom_seed[:3], key=lambda it: (it["x"], -it["priority"]))

    ordered = top + bottom
    leftovers = [it for it in valid if it not in ordered] + invalid
    while len(ordered) < len(items) and leftovers:
        ordered.append(leftovers.pop(0))

    out_arnum = [it["arnum"] for it in ordered[: len(items)]]
    out_x = np.array([it["x"] for it in ordered[: len(items)]], dtype=float)
    out_y = np.array([it["y"] for it in ordered[: len(items)]], dtype=float)
    if ar_priority is None:
        out_priority = None
    else:
        out_priority = np.array(
            [it["priority"] for it in ordered[: len(items)]], dtype=float
        )
    return out_arnum, out_x, out_y, out_priority


def _solarmonitor_rollover_key(this_time_ut, timezone="US/Central", use_local_day=False):
    if use_local_day:
        return convert_utc_to_timezone(this_time_ut, timezone=timezone).strftime("%Y%m%d")
    return this_time_ut.astimezone(datetime.timezone.utc).strftime("%Y%m%d")


def _save_runtime_stream_state(
    data_folder,
    labels,
    fai_history,
    active_area_fraction_history,
    em_history,
    fai_trigger_cooldown_remaining,
    persistent_fai_active,
    persistent_fai_label,
    region_source,
    arnum,
    ar_x,
    ar_y,
    ar_priority,
    startup_boxes_refined,
    last_box_recenter_ut,
):
    state = {
        "labels": list(labels),
        "fai_history": {k: list(v) for k, v in fai_history.items()},
        "active_area_fraction_history": {
            k: list(v) for k, v in active_area_fraction_history.items()
        },
        "em_history": {k: list(v) for k, v in em_history.items()},
        "fai_trigger_cooldown_remaining": dict(fai_trigger_cooldown_remaining),
        "persistent_fai_active": bool(persistent_fai_active),
        "persistent_fai_label": persistent_fai_label,
        "region_source": str(region_source),
        "arnum": list(arnum),
        "ar_x": np.asarray(ar_x, dtype=float),
        "ar_y": np.asarray(ar_y, dtype=float),
        "ar_priority": np.asarray(ar_priority, dtype=float),
        "startup_boxes_refined": bool(startup_boxes_refined),
        "last_box_recenter_ut": (
            last_box_recenter_ut.astimezone(datetime.timezone.utc).isoformat()
            if last_box_recenter_ut is not None
            else None
        ),
    }
    path = _runtime_state_path(data_folder)
    tmp_path = path + ".tmp"
    with open(tmp_path, "wb") as f:
        pickle.dump(state, f, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(tmp_path, path)


def _load_runtime_stream_state(data_folder, labels):
    path = _runtime_state_path(data_folder)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            state = pickle.load(f)
    except Exception as exc:
        print(f"Failed to load waffle_v1p2 runtime state: {exc}")
        return None
    if list(state.get("labels", [])) != list(labels):
        print("Ignoring waffle_v1p2 runtime state: box labels do not match current run.")
        return None
    return state


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


def _load_python_module(module_name, file_path):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load module {module_name} from {file_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _goes_flux_history_to_frame(xrsa_current, xrsb_current):
    if xrsa_current is None or xrsb_current is None:
        return pd.DataFrame(columns=["xrsa", "xrsb"])
    if len(xrsa_current) == 0 or len(xrsb_current) == 0:
        return pd.DataFrame(columns=["xrsa", "xrsb"])
    a = xrsa_current[["time_tag", "flux"]].copy()
    b = xrsb_current[["time_tag", "flux"]].copy()
    a["time_tag"] = pd.to_datetime(a["time_tag"], utc=True, errors="coerce")
    b["time_tag"] = pd.to_datetime(b["time_tag"], utc=True, errors="coerce")
    a = a.dropna(subset=["time_tag"]).rename(columns={"flux": "xrsa"})
    b = b.dropna(subset=["time_tag"]).rename(columns={"flux": "xrsb"})
    merged = pd.merge(a, b, on="time_tag", how="inner").sort_values("time_tag")
    if merged.empty:
        return pd.DataFrame(columns=["xrsa", "xrsb"])
    merged = merged.set_index("time_tag")
    merged["xrsa"] = pd.to_numeric(merged["xrsa"], errors="coerce")
    merged["xrsb"] = pd.to_numeric(merged["xrsb"], errors="coerce")
    merged["goes_satellite"] = np.nan
    return merged[["xrsa", "xrsb", "goes_satellite"]]


def _runtime_make_xrs_timeseries(df: pd.DataFrame, observatory: str):
    from astropy import units as u
    from sunpy.timeseries import TimeSeries
    from sunpy.util.metadata import MetaDict

    meta = MetaDict({"TELESCOP": observatory, "instrument": "XRS"})
    units = {"xrsa": u.W / (u.m**2), "xrsb": u.W / (u.m**2)}
    return TimeSeries(df[["xrsa", "xrsb"]], meta, units, source="XRS")


def _runtime_compute_temp_em(flux_df: pd.DataFrame, temp_col: str, em_col: str) -> pd.DataFrame:
    from sunkit_instruments.goes_xrs.goes_chianti_tem import calculate_temperature_em

    out = pd.DataFrame(index=flux_df.index, data={temp_col: np.nan, em_col: np.nan})
    valid = (
        np.isfinite(flux_df["xrsa"].to_numpy())
        & np.isfinite(flux_df["xrsb"].to_numpy())
        & (flux_df["xrsa"].to_numpy() > 0.0)
        & (flux_df["xrsb"].to_numpy() > 0.0)
    )
    if not np.any(valid):
        return out
    valid_df = flux_df.loc[valid, ["xrsa", "xrsb"]].copy()
    observatory = "GOES 18"
    ts = _runtime_make_xrs_timeseries(valid_df, observatory)
    temp_em = calculate_temperature_em(ts).to_dataframe()
    out.loc[temp_em.index, temp_col] = pd.to_numeric(
        temp_em["temperature"], errors="coerce"
    ).to_numpy(dtype=np.float64)
    out.loc[temp_em.index, em_col] = (
        pd.to_numeric(temp_em["emission_measure"], errors="coerce").to_numpy(dtype=np.float64) / 1.0e49
    )
    return out


def _runtime_consecutive_true(flag: pd.Series) -> pd.Series:
    arr = flag.fillna(False).to_numpy(dtype=bool)
    out = np.zeros(len(arr), dtype=np.int32)
    run = 0
    for i, v in enumerate(arr):
        run = run + 1 if v else 0
        out[i] = run
    return pd.Series(out, index=flag.index, dtype=np.int32)


def _runtime_compute_goes_paper_feature_frame(goes_df: pd.DataFrame) -> pd.DataFrame:
    df = goes_df.copy().sort_index()
    df["dxrsa_5"] = df["xrsa"].diff(5)
    df["dxrsb_5"] = df["xrsb"].diff(5)
    diff_for_tem = df[["dxrsa_5", "dxrsb_5", "goes_satellite"]].rename(
        columns={"dxrsa_5": "xrsa", "dxrsb_5": "xrsb"}
    )
    temp_em = _runtime_compute_temp_em(diff_for_tem, "fai_T_mk", "fai_EM49")
    df = pd.concat([df, temp_em], axis=1)
    df["fai_T_in_6_20"] = ((df["fai_T_mk"] > 6.0) & (df["fai_T_mk"] < 20.0)).astype(np.float64)
    df["fai_EM_gt_005"] = (df["fai_EM49"] > 0.005).astype(np.float64)
    df["fai_EM_gt_01"] = (df["fai_EM49"] > 0.1).astype(np.float64)
    df["fai_flag_6_20_005"] = (
        (df["fai_T_in_6_20"] > 0.0) & (df["fai_EM_gt_005"] > 0.0)
    ).astype(np.float64)
    df["fai_flag_6_20_01"] = (
        (df["fai_T_in_6_20"] > 0.0) & (df["fai_EM_gt_01"] > 0.0)
    ).astype(np.float64)
    consec_005 = _runtime_consecutive_true(df["fai_flag_6_20_005"] > 0.0)
    consec_01 = _runtime_consecutive_true(df["fai_flag_6_20_01"] > 0.0)
    df["fai_consec_2_005"] = (consec_005 >= 2).astype(np.float64)
    df["fai_consec_2_01"] = (consec_01 >= 2).astype(np.float64)
    return df


def _select_runtime_goes_cursor_row(
    xrsa_current,
    xrsb_current,
    anchor_time_ut,
    realtime_mode: bool,
    archive_goes_offset_minutes: float = 0.0,
):
    try:
        goes_df = _goes_flux_history_to_frame(xrsa_current, xrsb_current)
        if goes_df.empty:
            return None, None
        feat_df = _runtime_compute_goes_paper_feature_frame(goes_df)
        if feat_df.empty:
            return None, None
        if realtime_mode:
            return feat_df.index[-1], feat_df.iloc[-1]
        target_ts = pd.Timestamp(anchor_time_ut)
        if target_ts.tzinfo is None:
            target_ts = target_ts.tz_localize("UTC")
        else:
            target_ts = target_ts.tz_convert("UTC")
        target_ts = (
            target_ts + pd.Timedelta(minutes=float(archive_goes_offset_minutes))
        ).floor("min")
        hit = feat_df.loc[feat_df.index <= target_ts]
        if hit.empty:
            return None, None
        return hit.index[-1], hit.iloc[-1]
    except Exception as exc:
        print(f"Runtime GOES cursor snapshot failed: {exc}")
        return None, None


def _print_runtime_goes_cursor_snapshot(
    xrsa_current,
    xrsb_current,
    anchor_time_ut,
    realtime_mode: bool,
    archive_goes_offset_minutes: float = 0.0,
):
    cursor_ts, row = _select_runtime_goes_cursor_row(
        xrsa_current,
        xrsb_current,
        anchor_time_ut,
        realtime_mode=realtime_mode,
        archive_goes_offset_minutes=archive_goes_offset_minutes,
    )
    mode_label = "realtime" if realtime_mode else "archive"
    if cursor_ts is None or row is None:
        print(f"XRS cursor ({mode_label}): no temperature/EM49 available")
        return None, np.nan, np.nan
    t_mk = pd.to_numeric(row.get("fai_T_mk", np.nan), errors="coerce")
    em49 = pd.to_numeric(row.get("fai_EM49", np.nan), errors="coerce")
    ts_txt = pd.Timestamp(cursor_ts).strftime("%Y-%m-%d %H:%M:%S UTC")
    t_txt = f"{float(t_mk):.3f}" if np.isfinite(t_mk) else "NA"
    em_txt = f"{float(em49):.6f}" if np.isfinite(em49) else "NA"
    print(f"XRS cursor ({mode_label}) {ts_txt}: T_mk={t_txt} EM_49={em_txt}")
    return cursor_ts, float(t_mk) if np.isfinite(t_mk) else np.nan, float(em49) if np.isfinite(em49) else np.nan


def _c5_fai_trigger_condition(
    box_em_total: float,
    t_mk: float,
    em49: float,
    box_em_total_thresholds,
    t_mk_thresholds,
    em49_thresholds,
) -> bool:
    if not (np.isfinite(box_em_total) and np.isfinite(t_mk) and np.isfinite(em49)):
        return False
    levels = sorted(
        zip(box_em_total_thresholds, t_mk_thresholds, em49_thresholds),
        key=lambda x: float(x[0]),
        reverse=True,
    )
    for em_thresh, t_thresh, em49_thresh in levels:
        if box_em_total >= float(em_thresh):
            return (t_mk >= float(t_thresh)) and (em49 >= float(em49_thresh))
    return False


def _estimate_realtime_from_aia(trigger_time_utc, timezone="US/Central", delay_minutes=4.5):
    est_utc = trigger_time_utc + datetime.timedelta(minutes=float(delay_minutes))
    est_local = convert_utc_to_timezone(est_utc, timezone=timezone)
    return est_utc, est_local


def _estimate_realtime_from_utc(base_time_utc, timezone="US/Central", delay_minutes=0.0):
    est_utc = base_time_utc + datetime.timedelta(minutes=float(delay_minutes))
    est_local = convert_utc_to_timezone(est_utc, timezone=timezone)
    return est_utc, est_local


def save_flare_trigger_snapshot(
    data_folder,
    latest_plots_folder,
    trigger_time_utc,
    trigger_time_local,
    snapshot_time_utc,
    snapshot_time_local,
    focus_label,
    focus_em,
    trigger_box_stats,
    snapshot_box_stats,
    alert_config=None,
    copy_em_goes_plot=True,
    snapshot_root_name="FAI Triggers",
    snapshot_label="FAI trigger",
    estimated_realtime_utc=None,
    estimated_realtime_local=None,
):
    """Copy trigger snapshot assets into a timestamped folder."""

    trigger_root = os.path.join(data_folder, snapshot_root_name)
    mkdir(trigger_root)
    trigger_stamp = trigger_time_utc.strftime("%Y-%m-%dT%H%M%SZ")
    trigger_folder = os.path.join(trigger_root, trigger_stamp)
    suffix = 2
    while os.path.exists(trigger_folder):
        trigger_folder = os.path.join(trigger_root, f"{trigger_stamp}_{suffix}")
        suffix += 1
    mkdir(trigger_folder)

    for name in os.listdir(latest_plots_folder):
        if (not copy_em_goes_plot) and name == "em_goes_plot.png":
            continue
        src = os.path.join(latest_plots_folder, name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(trigger_folder, name))

    info_path = os.path.join(trigger_folder, "trigger_info.txt")
    with open(info_path, "w", encoding="utf-8") as f:
        f.write(f"trigger_time_utc={trigger_time_utc.isoformat()}\n")
        f.write(f"trigger_time_local={trigger_time_local.isoformat()}\n")
        f.write(f"snapshot_time_utc={snapshot_time_utc.isoformat()}\n")
        f.write(f"snapshot_time_local={snapshot_time_local.isoformat()}\n")
        if estimated_realtime_utc is not None:
            f.write(
                f"estimated_realtime_trigger_time_utc="
                f"{estimated_realtime_utc.isoformat()}\n"
            )
        if estimated_realtime_local is not None:
            f.write(
                f"estimated_realtime_trigger_time_local="
                f"{estimated_realtime_local.isoformat()}\n"
            )
        f.write(
            f"snapshot_delay_min="
            f"{(snapshot_time_utc - trigger_time_utc).total_seconds() / 60.0:.2f}\n"
        )
        f.write(f"focus_label={focus_label}\n")
        f.write(f"focus_em={float(focus_em):.6e}\n")
        if alert_config:
            f.write("alert_config=\n")
            for key in sorted(alert_config):
                f.write(f"  {key}: {alert_config[key]}\n")
        f.write("trigger_box_stats=\n")
        _write_fai_box_stats(f, trigger_box_stats)
        f.write("snapshot_box_stats=\n")
        _write_fai_box_stats(f, snapshot_box_stats)

    print(f"Saved {snapshot_label} snapshot: {trigger_folder}")
    return trigger_folder


def update_flare_trigger_em_goes_plot(
    trigger_folder,
    latest_plots_folder,
    trigger_time_utc,
    snapshot_time_utc,
    snapshot_time_local,
    estimated_realtime_utc=None,
    estimated_realtime_local=None,
):
    """Refresh only the EM/GOES plot for an existing trigger folder."""

    src = os.path.join(latest_plots_folder, "em_goes_plot.png")
    if not os.path.isfile(src):
        print(f"EM/GOES plot missing for trigger refresh: {src}")
        return
    dst = os.path.join(trigger_folder, "em_goes_plot.png")
    shutil.copy2(src, dst)

    info_path = os.path.join(trigger_folder, "trigger_info.txt")
    with open(info_path, "a", encoding="utf-8") as f:
        f.write(f"em_goes_snapshot_time_utc={snapshot_time_utc.isoformat()}\n")
        f.write(f"em_goes_snapshot_time_local={snapshot_time_local.isoformat()}\n")
        if estimated_realtime_utc is not None:
            f.write(
                "em_goes_estimated_realtime_trigger_time_utc="
                f"{estimated_realtime_utc.isoformat()}\n"
            )
        if estimated_realtime_local is not None:
            f.write(
                "em_goes_estimated_realtime_trigger_time_local="
                f"{estimated_realtime_local.isoformat()}\n"
            )
        f.write(
            "em_goes_snapshot_delay_min="
            f"{(snapshot_time_utc - trigger_time_utc).total_seconds() / 60.0:.2f}\n"
        )



def _write_fai_box_stats(file_obj, box_stats):
    if not box_stats:
        file_obj.write("  none\n")
        return
    max_em = max(
        (float(row.get("em", float("nan"))) for row in box_stats),
        default=float("nan"),
    )
    file_obj.write(f"  max_em={max_em:.6e}\n")
    for row in box_stats:
        file_obj.write(
            "  "
            f"box={row.get('label')} "
            f"ar={row.get('ar')} "
            f"lon={float(row.get('lon', float('nan'))):.3f} "
            f"lat={float(row.get('lat', float('nan'))):.3f} "
            f"em={float(row.get('em', float('nan'))):.6e} "
            f"prev_em={float(row.get('prev_em', float('nan'))):.6e} "
            f"em_ratio={float(row.get('em_ratio', float('nan'))):.6f} "
            f"active_area_frac={float(row.get('active_area_frac', float('nan'))):.6f} "
            f"fai_trigger={row.get('fai_trigger')} "
            f"status={row.get('status')} "
            "\n"
        )


def _make_fai_box_stats(
    labels,
    arnums,
    ar_lons,
    ar_lats,
    em_totals,
    em_history,
    active_area_fraction_history,
    trigger_flags,
    statuses_by_label,
):
    rows = []
    for i, lab in enumerate(labels):
        em_prev = float("nan")
        if em_history.get(lab):
            em_prev = float(em_history[lab][-1])
        area_vals = active_area_fraction_history.get(lab, [])
        em_curr = float(em_totals[i])
        rows.append(
            {
                "label": lab,
                "ar": arnums[i],
                "lon": float(ar_lons[i]),
                "lat": float(ar_lats[i]),
                "em": em_curr,
                "prev_em": em_prev,
                "em_ratio": em_curr / em_prev
                if np.isfinite(em_prev) and em_prev > 0
                else float("nan"),
                "active_area_frac": float(area_vals[-1]) if area_vals else float("nan"),
                "fai_trigger": bool(trigger_flags[i]) if i < len(trigger_flags) else False,
                "status": statuses_by_label.get(lab, "watch"),
            }
        )
    return rows


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


def is_nrt2_auth_error(err: Exception) -> bool:
    text = str(err).lower()
    return (
        "aia.lev1_nrt2" in text
        and (
            "auth" in text
            or "authorized" in text
            or "not allowed" in text
            or "permission" in text
            or "forbidden" in text
            or "denied" in text
        )
    )


def print_query_wait_message(use_nrt2_server: bool, err: Exception | None = None) -> None:
    if use_nrt2_server and err is not None and is_nrt2_auth_error(err):
        print(
            "NRT2 authorization error: this IP is not authorized for the Stanford "
            "aia.lev1_nrt2 series. Use drms_mode='public' or run from an authorized IP."
        )
        return
    print("awaiting new data...")


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
    download_timeout_sec=30.0,
    download_retry_delay_sec=10.0,
    download_retry_attempts=2,
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
        max_attempts = max(1, int(download_retry_attempts))
        for attempt in range(1, max_attempts + 1):
            try:
                with urlopen(fits_file_url, timeout=float(download_timeout_sec)) as src, open(
                    filename, "wb"
                ) as dst:
                    shutil.copyfileobj(src, dst)
                return i, filename, False
            except Exception:
                try:
                    if os.path.exists(filename):
                        os.remove(filename)
                except OSError:
                    pass
                if attempt >= max_attempts:
                    return i, None, True
                if not silent:
                    print(
                        f"Retrying AIA download {int(wav[i])}A "
                        f"(attempt {attempt + 1}/{max_attempts}) after {float(download_retry_delay_sec):.0f}s..."
                    )
                time.sleep(float(download_retry_delay_sec))

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


def hpc_xy_to_hgs(aia_map, x_arcsec, y_arcsec):
    """
    Convert helioprojective image-plane coordinates in arcsec into true
    Heliographic Stonyhurst lon/lat using the current map WCS/observer.
    """
    hpc = SkyCoord(
        float(x_arcsec) * u.arcsec,
        float(y_arcsec) * u.arcsec,
        frame=frames.Helioprojective,
        obstime=aia_map.date,
        observer=aia_map.observer_coordinate,
    )
    hgs = hpc.transform_to(frames.HeliographicStonyhurst(obstime=aia_map.date))
    return float(hgs.lon.deg), float(hgs.lat.deg)


# **********************************************************


def _hpc_xy_to_pixel(aia_map, x_arcsec, y_arcsec):
    hpc = SkyCoord(
        float(x_arcsec) * u.arcsec,
        float(y_arcsec) * u.arcsec,
        frame=frames.Helioprojective,
        obstime=aia_map.date,
        observer=aia_map.observer_coordinate,
    )
    pix = aia_map.world_to_pixel(hpc)
    return float(pix.x.value), float(pix.y.value)


def _pixel_to_hpc_xy(aia_map, x_pix, y_pix):
    world = aia_map.pixel_to_world(float(x_pix) * u.pix, float(y_pix) * u.pix)
    return float(world.Tx.to_value(u.arcsec)), float(world.Ty.to_value(u.arcsec))


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


def _is_valid_hpc_center(aia_map, x_arcsec, y_arcsec, disk_margin_arcsec=0.0):
    """
    Reject candidate box centers that are off-disk or outside the map footprint.
    """
    try:
        x_arcsec = float(x_arcsec)
        y_arcsec = float(y_arcsec)
    except Exception:
        return False
    if (not np.isfinite(x_arcsec)) or (not np.isfinite(y_arcsec)):
        return False

    rsun_arcsec = float(
        getattr(aia_map, "rsun_obs", 960.0 * u.arcsec).to_value(u.arcsec)
    )
    safe_r = max(0.0, rsun_arcsec - float(disk_margin_arcsec))
    if (x_arcsec * x_arcsec + y_arcsec * y_arcsec) > (safe_r * safe_r):
        return False

    try:
        pix_x, pix_y = _hpc_xy_to_pixel(aia_map, x_arcsec, y_arcsec)
    except Exception:
        return False
    if (not np.isfinite(pix_x)) or (not np.isfinite(pix_y)):
        return False

    ny, nx = aia_map.data.shape
    return (0.0 <= pix_x < float(nx)) and (0.0 <= pix_y < float(ny))


def refine_box_centers_from_em_map(
    aia_maps,
    weights,
    ar_x,
    ar_y,
    ar_priority=None,
    search_radius_arcsec=180.0,
    min_dx_arcsec=300.0,
    min_dy_arcsec=300.0,
    percentile=99.5,
    min_pixels=3,
):
    """
    Slightly shift box centers toward the brightest local EM structure on the first
    cycle so the crop better captures the active region core.
    """
    if len(aia_maps) == 0:
        return np.array(ar_x, dtype=float), np.array(ar_y, dtype=float), []

    ref_map = aia_maps[0]
    arrs = [np.asarray(m.data) for m in aia_maps]
    min_ny = min(a.shape[0] for a in arrs)
    min_nx = min(a.shape[1] for a in arrs)
    aia_img = np.stack([a[:min_ny, :min_nx] for a in arrs], axis=-1)
    em_map = compute_em_map(aia_img, ref_map.meta, weights)
    em_data = np.array(em_map.data, dtype=float, copy=False)
    em_data[~np.isfinite(em_data)] = 0.0

    out_x = np.array(ar_x, dtype=float, copy=True)
    out_y = np.array(ar_y, dtype=float, copy=True)
    orig_x = np.array(ar_x, dtype=float, copy=True)
    orig_y = np.array(ar_y, dtype=float, copy=True)
    priority = np.zeros(len(out_x), dtype=float) if ar_priority is None else np.asarray(ar_priority, dtype=float)
    shifts = []
    occupied = []

    pix_radius = max(1, int(np.ceil(float(search_radius_arcsec) / 0.6)))
    ny, nx = em_data.shape
    order = sorted(
        range(len(out_x)),
        key=lambda i: (np.isfinite(priority[i]), float(priority[i]) if np.isfinite(priority[i]) else float("-inf"), -i),
        reverse=True,
    )

    def _would_swap_slot(candidate_x, candidate_y, slot_idx):
        own_x = orig_x[slot_idx]
        own_y = orig_y[slot_idx]
        if not np.isfinite(own_x) or not np.isfinite(own_y):
            return False
        own_dist2 = (float(candidate_x) - float(own_x)) ** 2 + (float(candidate_y) - float(own_y)) ** 2
        for j in range(len(orig_x)):
            if j == slot_idx:
                continue
            if not np.isfinite(orig_x[j]) or not np.isfinite(orig_y[j]):
                continue
            other_dist2 = (float(candidate_x) - float(orig_x[j])) ** 2 + (float(candidate_y) - float(orig_y[j])) ** 2
            if other_dist2 < own_dist2:
                return True
        return False

    for i in order:
        if not np.isfinite(out_x[i]) or not np.isfinite(out_y[i]):
            continue
        if not _is_valid_hpc_center(ref_map, out_x[i], out_y[i], disk_margin_arcsec=0.0):
            shifts.append((i, float(out_x[i]), float(out_y[i]), float("nan"), float("nan")))
            out_x[i] = np.nan
            out_y[i] = np.nan
            continue
        px, py = _hpc_xy_to_pixel(ref_map, out_x[i], out_y[i])
        cx = int(np.round(px))
        cy = int(np.round(py))
        x0 = max(0, cx - pix_radius)
        x1 = min(nx, cx + pix_radius + 1)
        y0 = max(0, cy - pix_radius)
        y1 = min(ny, cy + pix_radius + 1)
        window = np.array(em_data[y0:y1, x0:x1], dtype=float, copy=True)
        if window.size == 0 or not np.any(np.isfinite(window)):
            continue
        chosen = None
        half_w = max(1, int(np.ceil(float(min_dx_arcsec) / 0.6 / 2.0)))
        half_h = max(1, int(np.ceil(float(min_dy_arcsec) / 0.6 / 2.0)))
        for _ in range(64):
            if not np.any(np.isfinite(window)):
                break
            wy, wx = _bright_region_centroid_masked(window, percentile=percentile, min_pixels=min_pixels)
            new_xpix = x0 + wx
            new_ypix = y0 + wy
            new_x, new_y = _pixel_to_hpc_xy(ref_map, new_xpix, new_ypix)
            if not _is_valid_hpc_center(ref_map, new_x, new_y, disk_margin_arcsec=0.0):
                wy0 = max(0, int(wy) - half_h)
                wy1 = min(window.shape[0], int(wy) + half_h + 1)
                wx0 = max(0, int(wx) - half_w)
                wx1 = min(window.shape[1], int(wx) + half_w + 1)
                window[wy0:wy1, wx0:wx1] = -np.inf
                continue
            # Keep slot identity fixed during recentering. If a candidate hotspot is
            # closer to another box's original center than this box's original center,
            # reject it instead of letting neighboring active regions trade places.
            if _would_swap_slot(new_x, new_y, i):
                wy0 = max(0, int(wy) - half_h)
                wy1 = min(window.shape[0], int(wy) + half_h + 1)
                wx0 = max(0, int(wx) - half_w)
                wx1 = min(window.shape[1], int(wx) + half_w + 1)
                window[wy0:wy1, wx0:wx1] = -np.inf
                continue
            overlaps = any(
                abs(float(new_x) - ox) < float(min_dx_arcsec)
                and abs(float(new_y) - oy) < float(min_dy_arcsec)
                for ox, oy in occupied
            )
            wy0 = max(0, int(wy) - half_h)
            wy1 = min(window.shape[0], int(wy) + half_h + 1)
            wx0 = max(0, int(wx) - half_w)
            wx1 = min(window.shape[1], int(wx) + half_w + 1)
            if not overlaps:
                chosen = (float(new_x), float(new_y))
                break
            window[wy0:wy1, wx0:wx1] = -np.inf
        if chosen is None:
            orig = (float(out_x[i]), float(out_y[i]))
            if not _is_valid_hpc_center(ref_map, orig[0], orig[1], disk_margin_arcsec=0.0):
                shifts.append((i, float(out_x[i]), float(out_y[i]), float("nan"), float("nan")))
                out_x[i] = np.nan
                out_y[i] = np.nan
                continue
            orig_overlaps = any(
                abs(orig[0] - ox) < float(min_dx_arcsec)
                and abs(orig[1] - oy) < float(min_dy_arcsec)
                for ox, oy in occupied
            )
            if orig_overlaps:
                shifts.append((i, float(out_x[i]), float(out_y[i]), float("nan"), float("nan")))
                out_x[i] = np.nan
                out_y[i] = np.nan
                continue
            chosen = orig
        shifts.append((i, float(out_x[i]), float(out_y[i]), chosen[0], chosen[1]))
        out_x[i] = chosen[0]
        out_y[i] = chosen[1]
        occupied.append(chosen)

    return out_x, out_y, shifts


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


def prepare_goes_plot_arrays(
    xrsa_current,
    xrsb_current,
    timezone="US/Central",
    anchor_time_local=None,
    lookback_minutes=60,
    archive_goes_offset_minutes=0.0,
):
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
    if anchor_time_local is not None and len(goes_time_array) > 0:
        max_time = anchor_time_local + timedelta(
            minutes=float(archive_goes_offset_minutes)
        )
        min_time = max_time - timedelta(minutes=float(lookback_minutes))
        mask = (goes_time_array >= min_time) & (goes_time_array <= max_time)
        goes_time_array = goes_time_array[mask]
        goes_xrsa_flux = goes_xrsa_flux[mask]
        goes_xrsb_flux = goes_xrsb_flux[mask]
    return goes_time_array, goes_xrsa_flux, goes_xrsb_flux


def append_goes_plot_break(goes_plot_data, break_time_local):
    """Extend the last successful GOES plot with a NaN endpoint to render a break."""
    if goes_plot_data is None:
        return None
    goes_time_array, goes_xrsa_flux, goes_xrsb_flux = goes_plot_data
    if len(goes_time_array) == 0 or break_time_local is None:
        return goes_plot_data
    if goes_time_array[-1] >= break_time_local:
        return goes_plot_data
    return (
        np.append(goes_time_array, break_time_local),
        np.append(np.asarray(goes_xrsa_flux, dtype=float), np.nan),
        np.append(np.asarray(goes_xrsb_flux, dtype=float), np.nan),
    )


def _latest_xrsb_derivative(xrsb_current, reference_time_ut=None):
    if xrsb_current is None or len(xrsb_current) < 2:
        return np.nan
    try:
        time_tag = pd.to_datetime(xrsb_current["time_tag"], utc=True, errors="coerce")
        flux = pd.to_numeric(
            xrsb_current["flux"], errors="coerce"
        ).to_numpy(dtype=np.float64)
    except Exception:
        return np.nan
    valid = np.isfinite(flux) & (~pd.isna(time_tag).to_numpy())
    if np.count_nonzero(valid) < 2:
        return np.nan
    time_tag = time_tag[valid]
    flux = flux[valid]
    if reference_time_ut is not None:
        ref_ts = pd.Timestamp(reference_time_ut)
        if ref_ts.tzinfo is None:
            ref_ts = ref_ts.tz_localize("UTC")
        else:
            ref_ts = ref_ts.tz_convert("UTC")
        # Use the last GOES sample at or before the AIA timestamp, not the
        # archive lead-ahead sample used elsewhere for plotting/fetching.
        valid_idx = np.flatnonzero(time_tag <= ref_ts)
        if valid_idx.size < 2:
            return np.nan
        idx = int(valid_idx[-1])
        return float(flux[idx] - flux[idx - 1])
    if flux.size < 2:
        return np.nan
    return float(flux[-1] - flux[-2])


# **********************************************************


def define_ssh_client(ssh_host="physics.wku.edu", ssh_user="emslie", ssh_password="waffle"):
    """

    Function for defining an ssh client object

    Returns
        ----------
        ssh_client: SSHClient object
            ssh client object used for uploading files via scp

    """

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
    control_page_href="./control.html",
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
        control_enabled=True,
        page_mode="full",
        control_page_href=control_page_href,
    )
    control_html = build_waffle_v2_index_html(
        suvi_top_wavelength=suvi_top_wavelength,
        suvi_day_utc=suvi_day_utc,
        suvi_use_realtime=suvi_use_realtime,
        control_enabled=True,
        page_mode="control",
        control_page_href=control_page_href,
    )

    with open(
        os.path.join(destination_volume, "index.html"), "w", encoding="utf-8"
    ) as f:
        f.write(index_html)
    with open(
        os.path.join(destination_volume, "control.html"), "w", encoding="utf-8"
    ) as f:
        f.write(control_html)


def _mirror_directory(source_dir, dest_dir):
    mkdir(dest_dir)
    source_names = set(os.listdir(source_dir))
    dest_names = set(os.listdir(dest_dir))

    for stale_name in dest_names - source_names:
        stale_path = os.path.join(dest_dir, stale_name)
        if os.path.isdir(stale_path):
            shutil.rmtree(stale_path)
        else:
            os.remove(stale_path)

    for name in source_names:
        src = os.path.join(source_dir, name)
        dst = os.path.join(dest_dir, name)
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


def build_detailed_analysis_box_html(box_label, arnum, image_name):
    title = f"WAFFLE Detailed Analysis - Box {box_label}"
    return f"""<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no">
<title>{title}</title>
<style>
body {{
    margin: 0;
    background: #ffffff;
    color: #10212b;
    font-family: "Trebuchet MS", "Avenir Next", sans-serif;
}}
#page {{
    width: min(96vw, 1240px);
    margin: 0 auto;
    padding: 8px 0 12px 0;
}}
h1 {{
    margin: 0 0 4px 0;
    font-size: 21px;
}}
.subhead {{
    margin: 0 0 10px 0;
    color: #52636c;
    font-size: 13px;
}}
.plot-frame {{
    border: 1px solid rgba(16, 33, 43, 0.12);
    border-radius: 12px;
    box-shadow: 0 10px 24px rgba(16, 33, 43, 0.08);
    overflow: hidden;
    background: #ffffff;
}}
.plot-frame img {{
    display: block;
    width: 100%;
    height: auto;
}}
</style>
</head>
<body>
<div id="page">
<h1>Detailed Analysis - Box {box_label}</h1>
<div class="subhead">AR {int(arnum)} | Auto-refresh every 15 seconds</div>
<div class="plot-frame">
<img id="detail-image" src="./{image_name}" alt="Detailed analysis plot for box {box_label}">
</div>
</div>
<script>
setInterval(function() {{
    var timestamp = new Date().getTime();
    document.getElementById("detail-image").src = "./{image_name}?t=" + timestamp;
}}, 15000);
</script>
</body>
</html>"""


def write_detailed_analysis_pages(detail_dir, labels, arnums):
    mkdir(detail_dir)
    for idx, box_label in enumerate(labels):
        image_name = f"aia_em_{idx + 1}.png"
        html_name = f"box_{box_label}.html"
        arnum = arnums[idx] if idx < len(arnums) else 0
        with open(os.path.join(detail_dir, html_name), "w", encoding="utf-8") as f:
            f.write(build_detailed_analysis_box_html(box_label, arnum, image_name))


def publish_detailed_analysis_local(source_dir, destination_volume, subdir="detailed_analysis"):
    if not source_dir or not os.path.isdir(source_dir):
        return
    dest_dir = os.path.join(destination_volume, subdir)
    _mirror_directory(source_dir, dest_dir)


def publish_detailed_analysis_remote(
    ssh_client, source_dir, destination_volume, subdir="detailed_analysis"
):
    if not source_dir or not os.path.isdir(source_dir):
        return
    remote_dir = os.path.join(destination_volume, subdir)
    ssh_client.exec_command(f'mkdir -p "{remote_dir}"')
    with SCPClient(ssh_client.get_transport()) as scp:
        for name in os.listdir(source_dir):
            scp.put(os.path.join(source_dir, name), remote_path=remote_dir, recursive=True)


def resolve_detailed_plot_render_workers(
    enabled, requested_workers, worker_count, n_boxes
):
    if not bool(enabled):
        return 1
    if n_boxes <= 1:
        return 1
    if requested_workers in (None, 0, "", "None"):
        requested_workers = worker_count
    try:
        resolved = int(requested_workers)
    except Exception:
        resolved = int(worker_count)
    return max(1, min(int(n_boxes), resolved))


def _status_payload(kind, title, detail):
    return {
        "kind": str(kind),
        "title": str(title),
        "detail": str(detail),
        "updated_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "updated_unix": time.time(),
    }


def publish_status_local(destination_volume, kind, title, detail):
    mkdir(destination_volume)
    status_path = os.path.join(destination_volume, "status.json")
    tmp_path = status_path + ".tmp"
    payload = _status_payload(kind, title, detail)
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp_path, status_path)


def publish_status_remote(ssh_client, destination_volume, kind, title, detail):
    payload = _status_payload(kind, title, detail)
    with SCPClient(ssh_client.get_transport()) as scp:
        scp.putfo(
            io.BytesIO(json.dumps(payload, indent=2).encode("utf-8")),
            remote_path=os.path.join(destination_volume, "status.json"),
        )


def publish_runtime_status(
    publish_mode,
    destination_volume,
    ssh_client,
    kind,
    title,
    detail,
    local_mirror_destination=None,
):
    try:
        if publish_mode == "scp":
            publish_status_remote(ssh_client, destination_volume, kind, title, detail)
            if local_mirror_destination:
                publish_status_local(local_mirror_destination, kind, title, detail)
        else:
            publish_status_local(destination_volume, kind, title, detail)
    except Exception as exc:
        print(f"Status publish failed: {exc}")


def _ensure_text_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("", encoding="utf-8")


def load_sms_recipients(path: Path) -> list[str]:
    _ensure_text_file(path)
    out: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        out.append(text)
    return out


def load_sms_smtp_config(path: Path) -> dict:
    if not path.exists():
        path.write_text(
            json.dumps(
                {
                    "from_email": "",
                    "app_password": "",
                    "smtp_host": "smtp.gmail.com",
                    "smtp_port": 465,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def send_sms_alert(message: str, recipients: list[str], smtp_cfg: dict) -> bool:
    from_email = str(smtp_cfg.get("from_email", "")).strip()
    app_password = str(smtp_cfg.get("app_password", "")).strip()
    smtp_host = str(smtp_cfg.get("smtp_host", "smtp.gmail.com")).strip() or "smtp.gmail.com"
    smtp_port = int(smtp_cfg.get("smtp_port", 465) or 465)
    if not from_email or not app_password or not recipients:
        return False
    try:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=20) as smtp:
            smtp.login(from_email, app_password)
            for recipient in recipients:
                msg = EmailMessage()
                msg["From"] = from_email
                msg["To"] = recipient
                msg["Subject"] = ""
                msg.set_content(message)
                smtp.send_message(msg)
        return True
    except Exception as exc:
        print(f"SMS alert failed: {exc}")
        return False


def start_delayed_runtime_status(
    delay_sec,
    publish_mode,
    destination_volume,
    ssh_client,
    kind,
    title,
    detail,
    local_mirror_destination=None,
):
    timer = threading.Timer(
        float(delay_sec),
        publish_runtime_status,
        args=(
            publish_mode,
            destination_volume,
            ssh_client,
            kind,
            title,
            detail,
            local_mirror_destination,
        ),
    )
    timer.daemon = True
    timer.start()
    return timer


def build_waffle_v2_index_html(
    suvi_top_wavelength=131,
    suvi_day_utc=None,
    suvi_use_realtime=False,
    control_enabled=False,
    page_mode="full",
    control_page_href="#",
):
    index_html = ""
    # Use the template next to near_realtime_aia_pipeline.py / aux_functions.py.
    template_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "wku_template.html"
    )
    if not os.path.exists(template_path):
        index_html = """<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no"><title>WAFFLE v1p2</title></head><body><center><img id="image0" src="./latest_plots/full_disk_maps.gif" style="width:97.5%;max-width:100%;height:auto;"><br><img id="image1" src="./latest_plots/em_goes_plot.png" style="width:97.5%;max-width:100%;height:auto;"><script>setInterval(function(){var t=new Date().getTime();document.getElementById("image0").src="./latest_plots/full_disk_maps.gif?t="+t;document.getElementById("image1").src="./latest_plots/em_goes_plot.png?t="+t;},15000);</script></center></body></html>"""
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
    index_html = index_html.replace(
        "__CONTROL_ENABLED__", "true" if control_enabled else "false"
    )
    index_html = index_html.replace("__PAGE_MODE__", str(page_mode))
    index_html = index_html.replace("__CONTROL_PAGE_HREF__", str(control_page_href))
    return index_html


def publish_remote_index_html(
    ssh_client,
    destination_volume,
    suvi_top_wavelength=131,
    suvi_day_utc=None,
    suvi_use_realtime=False,
    control_page_href="#",
):
    control_link_enabled = str(control_page_href).strip() not in ("", "#")
    index_html = build_waffle_v2_index_html(
        suvi_top_wavelength=suvi_top_wavelength,
        suvi_day_utc=suvi_day_utc,
        suvi_use_realtime=suvi_use_realtime,
        control_enabled=control_link_enabled,
        page_mode="full",
        control_page_href=control_page_href,
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


def _waffle_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _candidate_goes_archive_roots(goes_folder) -> list[Path]:
    roots = []
    env_root = os.environ.get("WAFFLE_GOES_ARCHIVE_CACHE", "").strip()
    if env_root:
        roots.append(Path(env_root).expanduser())
    repo_root = _waffle_repo_root()
    roots.extend(
        [
            Path(goes_folder) / "archive_cache_auto",
            repo_root / "ML_FFT" / "goes_xrs_archive_cache_primary",
            repo_root / "ML_FFT" / "goes_xrs_archive_cache",
            Path(goes_folder) / "archive_cache_primary",
            Path(goes_folder) / "archive_cache",
        ]
    )
    out = []
    seen = set()
    for root in roots:
        key = str(root)
        if key in seen:
            continue
        seen.add(key)
        out.append(root)
    return out


def _load_goes_cache_day(cache_root: Path, day: datetime.date) -> pd.DataFrame:
    path = cache_root / "minute" / f"{day:%Y}" / f"{day:%Y%m%d}.npz"
    if not path.exists():
        raise FileNotFoundError(path)
    with np.load(path, allow_pickle=False) as d:
        time_utc = d["time_utc"].astype(str)
        xrsa = d["xrsa"].astype(np.float64)
        xrsb = d["xrsb"].astype(np.float64)
    idx = pd.to_datetime(time_utc, utc=True, errors="coerce")
    good = ~idx.isna()
    return pd.DataFrame({"xrsa": xrsa[good], "xrsb": xrsb[good]}, index=idx[good]).sort_index()


def _load_goes_cache_window(cache_root: Path, start_time, end_time) -> pd.DataFrame:
    days = []
    cur = start_time.date()
    while cur <= end_time.date():
        days.append(cur)
        cur += timedelta(days=1)
    frames = []
    for day in days:
        try:
            frames.append(_load_goes_cache_day(cache_root, day))
        except FileNotFoundError:
            continue
    if not frames:
        raise FileNotFoundError(f"no GOES cache files found in {cache_root} for {start_time}..{end_time}")
    df = pd.concat(frames, axis=0).sort_index()
    return df[(df.index >= start_time) & (df.index <= end_time)].copy()


def _goes_cache_day_path(cache_root: Path, day: datetime.date) -> Path:
    return cache_root / "minute" / f"{day:%Y}" / f"{day:%Y%m%d}.npz"


def _save_goes_cache_day(cache_root: Path, day: datetime.date, df: pd.DataFrame) -> Path:
    path = _goes_cache_day_path(cache_root, day)
    path.parent.mkdir(parents=True, exist_ok=True)
    day_start = pd.Timestamp(
        datetime.datetime.combine(day, datetime.time(0, 0, tzinfo=datetime.timezone.utc))
    )
    day_end = day_start + pd.Timedelta(days=1) - pd.Timedelta(minutes=1)
    minute_index = pd.date_range(day_start, day_end, freq="1min", tz="UTC")
    day_df = df.sort_index().copy()
    day_df = day_df[~day_df.index.duplicated(keep="last")]
    day_df = day_df.reindex(minute_index)
    np.savez_compressed(
        path,
        time_utc=minute_index.strftime("%Y-%m-%dT%H:%M:%SZ").to_numpy(dtype="U20"),
        xrsa=day_df["xrsa"].to_numpy(dtype=np.float64),
        xrsb=day_df["xrsb"].to_numpy(dtype=np.float64),
    )
    return path


_GOES_SATELLITE_ATTR_NAMES = {
    2: "two",
    5: "five",
    6: "six",
    7: "seven",
    8: "eight",
    9: "nine",
    10: "ten",
    11: "eleven",
    12: "twelve",
    13: "thirteen",
    14: "fourteen",
    15: "fifteen",
    16: "sixteen",
    17: "seventeen",
    18: "eighteen",
}
_GOES_SATELLITE_FAIL_COOLDOWN_SEC = 600


def _archive_primary_goes_satellite(day: datetime.date) -> int:
    """
    Approximate the primary GOES XRS satellite by era, then allow fallback to nearby
    operational spacecraft.
    """
    if day >= datetime.date(2022, 3, 1):
        return 18
    if day >= datetime.date(2018, 6, 1):
        return 17
    if day >= datetime.date(2017, 2, 7):
        return 16
    if day >= datetime.date(2010, 4, 1):
        return 15
    return 14


def _archive_goes_satellite_candidates(day: datetime.date):
    primary = _archive_primary_goes_satellite(day)
    if primary >= 18:
        return [18, 17, 16, 15, 14]
    if primary == 17:
        return [17, 16, 15, 14]
    if primary == 16:
        return [16, 15, 14]
    if primary == 15:
        return [15, 14, 13]
    return [14, 13, 12]


def _goes_satellite_attr(a_module, sat_num: int):
    try:
        return a_module.goes.SatelliteNumber(int(sat_num))
    except Exception as exc:
        raise ValueError(f"unsupported GOES satellite number {sat_num}") from exc


def _sanitize_goes_xrs_dataframe(df, start_time, end_time):
    cols = {str(c).lower(): c for c in df.columns}
    col_a = cols.get("xrsa")
    col_b = cols.get("xrsb")
    if col_a is None or col_b is None:
        raise ValueError(
            f"GOES XRS dataframe missing XRSA/XRSB columns for {start_time.date().isoformat()}"
        )
    idx = pd.to_datetime(df.index, utc=True, errors="coerce")
    good = ~idx.isna()
    idx = idx[good]
    dfa = pd.to_numeric(df.loc[good, col_a], errors="coerce")
    dfb = pd.to_numeric(df.loc[good, col_b], errors="coerce")
    ok = ~(dfa.isna() | dfb.isna())
    idx = idx[ok]
    dfa = dfa[ok]
    dfb = dfb[ok]
    in_range = (idx >= pd.Timestamp(start_time)) & (idx <= pd.Timestamp(end_time))
    idx = idx[in_range]
    dfa = dfa[in_range]
    dfb = dfb[in_range]
    if len(idx) == 0:
        raise FileNotFoundError(
            f"GOES XRS valid rows empty for {start_time.date().isoformat()}"
        )
    return pd.DataFrame(
        {"xrsa": np.asarray(dfa, dtype=float), "xrsb": np.asarray(dfb, dtype=float)},
        index=idx,
    ).sort_index()


def _extract_goes_xrs_window(df, start_time, end_time, pad_slack=None):
    cols = {str(c).lower(): c for c in df.columns}
    col_a = cols.get("xrsa")
    col_b = cols.get("xrsb")
    if col_a is None or col_b is None:
        return None
    idx = pd.to_datetime(df.index, utc=True, errors="coerce")
    good = ~idx.isna()
    idx = idx[good]
    dfa = pd.to_numeric(df.loc[good, col_a], errors="coerce")
    dfb = pd.to_numeric(df.loc[good, col_b], errors="coerce")
    ok = ~(dfa.isna() | dfb.isna())
    idx = idx[ok]
    dfa = dfa[ok]
    dfb = dfb[ok]
    in_window = (idx >= start_time) & (idx <= end_time)
    if np.any(in_window):
        return idx[in_window], dfa[in_window], dfb[in_window]
    if pad_slack is None:
        return None
    slack_start = start_time - pad_slack
    slack_end = end_time + pad_slack
    in_slack = (idx >= slack_start) & (idx <= slack_end)
    if np.any(in_slack):
        return idx[in_slack], dfa[in_slack], dfb[in_slack]
    return None


def _search_goes_xrs(a_module, start_time, end_time, sat_num):
    from sunpy.net import Fido

    sat_attr = _goes_satellite_attr(a_module, sat_num)
    try:
        return Fido.search(
            a_module.Time(start_time, end_time),
            a_module.Instrument("XRS"),
            a_module.Resolution("avg1m"),
            sat_attr,
        )
    except Exception:
        return Fido.search(
            a_module.Time(start_time, end_time),
            a_module.Instrument("XRS"),
            sat_attr,
        )


def _search_goes_xrs_all(a_module, start_time, end_time):
    from sunpy.net import Fido

    try:
        return Fido.search(
            a_module.Time(start_time, end_time),
            a_module.Instrument("XRS"),
            a_module.Resolution("avg1m"),
        )
    except Exception:
        return Fido.search(
            a_module.Time(start_time, end_time),
            a_module.Instrument("XRS"),
        )


def _describe_fetch_errors(fetch_result):
    errors = getattr(fetch_result, "errors", None)
    if not errors:
        return ""
    parts = []
    for err in errors[:3]:
        msg = str(err).strip().replace("\n", " ")
        if msg:
            parts.append(msg)
    return "; ".join(parts)


def _fetch_goes_xrs_from_candidates(
    a_module,
    TimeSeries,
    start_time,
    end_time,
    sat_candidates,
    path_template,
    goes_folder=None,
    fail_day=None,
):
    from sunpy.net import Fido

    last_status = "no-search-results"
    last_exc = None
    attempt_log = []
    for sat_num in sat_candidates:
        try:
            result = _search_goes_xrs(a_module, start_time, end_time, sat_num)
            if len(result) == 0:
                last_status = f"no-search-results-g{sat_num}"
                attempt_log.append((sat_num, "no search results"))
                continue
            files = Fido.fetch(
                result,
                path=path_template,
                progress=False,
                overwrite=False,
                max_conn=1,
            )
            if len(files) == 0:
                last_status = f"empty-fetch-g{sat_num}"
                if goes_folder is not None and fail_day is not None:
                    _mark_bad_goes_satellite(goes_folder, fail_day, sat_num)
                reason = "empty fetch"
                attempt_log.append((sat_num, reason))
                print(_format_goes_satellite_skip(sat_num, reason))
                continue
            ts = TimeSeries(files, concatenate=True)
            df = ts.to_dataframe()
            if df is None or len(df) == 0:
                last_status = f"empty-dataframe-g{sat_num}"
                if goes_folder is not None and fail_day is not None:
                    _mark_bad_goes_satellite(goes_folder, fail_day, sat_num)
                reason = "empty dataframe"
                attempt_log.append((sat_num, reason))
                print(_format_goes_satellite_skip(sat_num, reason))
                continue
            attempt_log.append((sat_num, "ok"))
            return df, sat_num, "ok", attempt_log
        except Exception as exc:
            last_exc = exc
            last_status = f"fetch-error-g{sat_num}"
            if goes_folder is not None and fail_day is not None:
                _mark_bad_goes_satellite(goes_folder, fail_day, sat_num)
            reason = f"fetch error: {exc}"
            attempt_log.append((sat_num, reason))
            print(_format_goes_satellite_skip(sat_num, reason))
    if last_exc is not None:
        raise FileNotFoundError(
            f"no usable GOES XRS dataframe for {start_time.date().isoformat()} ({last_exc})"
        )
    return None, None, last_status, attempt_log


def _fetch_goes_day_dataframe(day: datetime.date, download_root: Path, goes_folder) -> pd.DataFrame:
    from sunpy.net import Fido
    from sunpy.net import attrs as a
    from sunpy.timeseries import TimeSeries

    start_time = datetime.datetime.combine(
        day, datetime.time(0, 0, tzinfo=datetime.timezone.utc)
    )
    end_time = start_time + timedelta(days=1) - timedelta(seconds=1)
    download_root.mkdir(parents=True, exist_ok=True)
    broad_reason = None
    try:
        result_all = _search_goes_xrs_all(a, start_time, end_time)
        if len(result_all) > 0:
            files_all = Fido.fetch(
                result_all,
                path=os.path.join(str(download_root), "{file}"),
                progress=False,
                overwrite=False,
                max_conn=1,
            )
            if len(files_all) > 0:
                ts_all = TimeSeries(files_all, concatenate=True)
                df_all = ts_all.to_dataframe()
                if df_all is not None and len(df_all) > 0:
                    return _sanitize_goes_xrs_dataframe(df_all, start_time, end_time)
            broad_err = _describe_fetch_errors(files_all)
            broad_reason = f"broad fetch empty{': ' + broad_err if broad_err else ''}"
        else:
            broad_reason = "broad search returned no results"
    except Exception as exc:
        broad_reason = f"broad fetch error: {exc}"

    df, sat_num, status, attempt_log = _fetch_goes_xrs_from_candidates(
        a,
        TimeSeries,
        start_time,
        end_time,
        _ordered_goes_satellite_candidates(day, goes_folder),
        os.path.join(str(download_root), "{file}"),
        goes_folder=goes_folder,
        fail_day=day,
    )
    if df is None:
        broad_prefix = f"{broad_reason}; " if broad_reason else ""
        raise FileNotFoundError(
            f"no usable GOES XRS dataframe for {day.isoformat()} "
            f"({broad_prefix}{status}; tried "
            + ", ".join(f"G{sat}:{reason}" for sat, reason in attempt_log)
            + ")"
        )
    if sat_num is not None:
        _remember_good_goes_satellite(goes_folder, day, sat_num)
    return _sanitize_goes_xrs_dataframe(df, start_time, end_time)


def _ensure_local_goes_cache_window(goes_folder, start_time, end_time):
    cache_root = Path(goes_folder) / "archive_cache_auto"
    download_root = cache_root / "downloads"
    built_days = []
    failed_days = []
    cur = start_time.date()
    while cur <= end_time.date():
        day_path = _goes_cache_day_path(cache_root, cur)
        if not day_path.exists():
            fail_until = _get_goes_day_failure_until(goes_folder, cur)
            if fail_until > time.time():
                failed_days.append(cur)
                cur += timedelta(days=1)
                continue
            try:
                df_day = _fetch_goes_day_dataframe(cur, download_root, goes_folder)
                _save_goes_cache_day(cache_root, cur, df_day)
                _clear_goes_day_failed(goes_folder, cur)
                built_days.append(cur)
            except Exception as exc:
                _mark_goes_day_failed(goes_folder, cur, cooldown_seconds=300)
                print(f"Archive GOES XRS: day {cur.isoformat()} fetch failed ({exc})")
                failed_days.append(cur)
        cur += timedelta(days=1)
    return cache_root, built_days, failed_days


def _goes_satellite_hint_path(goes_folder) -> Path:
    return Path(goes_folder) / "archive_cache" / "satellite_hints.json"


def _load_goes_satellite_hints(goes_folder):
    path = _goes_satellite_hint_path(goes_folder)
    if not path.exists():
        return {"good": {}, "bad": {}}
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and "good" in data:
            good = {
                str(k): int(v)
                for k, v in data.get("good", {}).items()
            }
            bad = {}
            for day_key, per_day in data.get("bad", {}).items():
                if isinstance(per_day, dict):
                    bad[str(day_key)] = {
                        str(sat): float(expiry) for sat, expiry in per_day.items()
                    }
            return {"good": good, "bad": bad}
        if isinstance(data, dict):
            return {
                "good": {str(k): int(v) for k, v in data.items()},
                "bad": {},
            }
    except Exception:
        return {"good": {}, "bad": {}}
    return {"good": {}, "bad": {}}


def _save_goes_satellite_hints(goes_folder, hints):
    path = _goes_satellite_hint_path(goes_folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as fh:
        json.dump(hints, fh, indent=2, sort_keys=True)
    tmp_path.replace(path)


def _remember_good_goes_satellite(goes_folder, day: datetime.date, sat_num: int):
    hints = _load_goes_satellite_hints(goes_folder)
    day_key = f"{day:%Y%m%d}"
    hints["good"][day_key] = int(sat_num)
    bad_for_day = hints["bad"].get(day_key, {})
    bad_for_day.pop(str(int(sat_num)), None)
    if bad_for_day:
        hints["bad"][day_key] = bad_for_day
    elif day_key in hints["bad"]:
        del hints["bad"][day_key]
    _save_goes_satellite_hints(goes_folder, hints)


def _mark_bad_goes_satellite(goes_folder, day: datetime.date, sat_num: int, cooldown_seconds=_GOES_SATELLITE_FAIL_COOLDOWN_SEC):
    hints = _load_goes_satellite_hints(goes_folder)
    day_key = f"{day:%Y%m%d}"
    bad = hints.setdefault("bad", {})
    bad.setdefault(day_key, {})[str(int(sat_num))] = time.time() + float(cooldown_seconds)
    _save_goes_satellite_hints(goes_folder, hints)


def _format_goes_satellite_skip(sat_num: int, reason: str) -> str:
    return f"Archive GOES XRS: skipping G{sat_num} ({reason})"


def _goes_day_failure_path(goes_folder) -> Path:
    return Path(goes_folder) / "archive_cache" / "day_failures.json"


def _load_goes_day_failures(goes_folder):
    path = _goes_day_failure_path(goes_folder)
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return {str(k): float(v) for k, v in data.items()}
    except Exception:
        return {}
    return {}


def _save_goes_day_failures(goes_folder, failures):
    path = _goes_day_failure_path(goes_folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as fh:
        json.dump({str(k): float(v) for k, v in failures.items()}, fh, indent=2, sort_keys=True)
    tmp_path.replace(path)


def _get_goes_day_failure_until(goes_folder, day: datetime.date) -> float:
    return float(_load_goes_day_failures(goes_folder).get(f"{day:%Y%m%d}", 0.0))


def _mark_goes_day_failed(goes_folder, day: datetime.date, cooldown_seconds=300):
    failures = _load_goes_day_failures(goes_folder)
    failures[f"{day:%Y%m%d}"] = time.time() + float(cooldown_seconds)
    _save_goes_day_failures(goes_folder, failures)


def _clear_goes_day_failed(goes_folder, day: datetime.date):
    failures = _load_goes_day_failures(goes_folder)
    day_key = f"{day:%Y%m%d}"
    if day_key in failures:
        del failures[day_key]
        _save_goes_day_failures(goes_folder, failures)


def _ordered_goes_satellite_candidates(day: datetime.date, goes_folder):
    day_key = f"{day:%Y%m%d}"
    hints = _load_goes_satellite_hints(goes_folder)
    base = list(_archive_goes_satellite_candidates(day))
    hinted = hints.get("good", {}).get(day_key)
    now = time.time()
    bad_today = hints.get("bad", {}).get(day_key, {})
    allowed = [
        sat for sat in base
        if float(bad_today.get(str(int(sat)), 0.0)) <= now
    ]
    if not allowed:
        allowed = base
    if hinted is not None and hinted in base:
        return [hinted] + [sat for sat in allowed if sat != hinted]
    return allowed


def _load_archive_xrs_window_legacy(start_time, end_time, cache_dir, timeout_seconds=12):
    script = f"""
import json
import os
import pandas as pd
from sunpy.net import Fido, attrs as a
from sunpy.timeseries import TimeSeries

start_time = pd.Timestamp({start_time.isoformat()!r})
end_time = pd.Timestamp({end_time.isoformat()!r})
cache_dir = {cache_dir!r}

try:
    result = Fido.search(
        a.Time(start_time.to_pydatetime(), end_time.to_pydatetime()),
        a.Instrument("XRS"),
        a.Resolution("avg1m"),
    )
except Exception:
    result = Fido.search(
        a.Time(start_time.to_pydatetime(), end_time.to_pydatetime()),
        a.Instrument("XRS"),
    )
if len(result) == 0:
    print(json.dumps({{"status": "empty-search"}}))
    raise SystemExit(0)

files = Fido.fetch(
    result,
    path=os.path.join(cache_dir, "{{file}}"),
    progress=False,
    overwrite=False,
    max_conn=1,
)
if len(files) == 0:
    print(json.dumps({{"status": "empty-fetch"}}))
    raise SystemExit(0)

ts = TimeSeries(files, concatenate=True)
df = ts.to_dataframe()
if df is None or len(df) == 0:
    print(json.dumps({{"status": "empty-dataframe"}}))
    raise SystemExit(0)

cols = {{str(c).lower(): c for c in df.columns}}
col_a = cols.get("xrsa")
col_b = cols.get("xrsb")
if col_a is None or col_b is None:
    print(json.dumps({{"status": "missing-columns"}}))
    raise SystemExit(0)

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
    print(json.dumps({{"status": "empty-valid"}}))
    raise SystemExit(0)

print(json.dumps({{
    "status": "ok",
    "time_tag": [t.isoformat() for t in idx.to_pydatetime()],
    "xrsa": [float(x) for x in dfa],
    "xrsb": [float(x) for x in dfb],
}}))
"""
    env = os.environ.copy()
    env.setdefault("SUNPY_CONFIGDIR", os.path.join(cache_dir, "sunpy_config"))
    mkdir(env["SUNPY_CONFIGDIR"])
    try:
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=float(timeout_seconds),
            env=env,
        )
    except subprocess.TimeoutExpired:
        print(
            f"Archive GOES XRS: skipped after {int(timeout_seconds)}s timeout "
            f"for {start_time.isoformat()} .. {end_time.isoformat()}"
        )
        return _empty_xrs_frames()
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        msg = detail[-1] if detail else "subprocess failed"
        print(f"Archive GOES XRS: skipped ({msg})")
        return _empty_xrs_frames()
    lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
    if not lines:
        return _empty_xrs_frames()
    try:
        payload = json.loads(lines[-1])
    except Exception:
        return _empty_xrs_frames()
    if payload.get("status") != "ok":
        return _empty_xrs_frames()
    idx = pd.to_datetime(payload.get("time_tag", []), utc=True, errors="coerce")
    xrsa = np.asarray(payload.get("xrsa", []), dtype=float)
    xrsb = np.asarray(payload.get("xrsb", []), dtype=float)
    good = ~idx.isna()
    idx = idx[good]
    xrsa = xrsa[good]
    xrsb = xrsb[good]
    if len(idx) == 0:
        return _empty_xrs_frames()
    xrsa_current = pd.DataFrame(
        {"time_tag": idx.to_pydatetime(), "flux": xrsa, "energy": "0.05-0.4nm"}
    )
    xrsb_current = pd.DataFrame(
        {"time_tag": idx.to_pydatetime(), "flux": xrsb, "energy": "0.1-0.8nm"}
    )
    return (
        xrsa_current.iloc[-100:].reset_index(drop=True),
        xrsb_current.iloc[-100:].reset_index(drop=True),
    )


def load_archive_XRS(reference_time_ut, goes_folder, lookback_hours=6, lead_minutes=3.0):
    """
    Load historical GOES XRS data for archive/replay mode.

    Prefer a local 1-minute GOES archive cache, with a legacy SunPy retrieval fallback.
    In replay mode, allow GOES to run a few minutes ahead of the AIA cursor to mimic
    the lower GOES latency relative to AIA availability.
    Returns same dataframe structure as load_realtime_XRS.
    """
    if reference_time_ut is None:
        return _empty_xrs_frames()

    try:
        end_time = reference_time_ut.astimezone(datetime.timezone.utc) + timedelta(
            minutes=float(lead_minutes)
        )
        start_time = end_time - timedelta(hours=float(lookback_hours))
        try:
            from sunpy.net import attrs as a
            from sunpy.net.dataretriever.sources.goes import XRSClient
            from sunpy.timeseries import TimeSeries
        except Exception:
            return _empty_xrs_frames()

        cache_dir = os.path.join(goes_folder, "archive_cache")
        mkdir(cache_dir)
        client = XRSClient()
        try:
            result = client.search(
                a.Time(start_time, end_time),
                a.Instrument("XRS"),
                a.Resolution("avg1m"),
            )
        except Exception:
            result = client.search(a.Time(start_time, end_time), a.Instrument("XRS"))
        if len(result) == 0:
            print(
                f"Archive GOES XRS: no search results for {start_time.isoformat()} .. {end_time.isoformat()}"
            )
            return _empty_xrs_frames()
        files = client.fetch(
            result,
            path=os.path.join(cache_dir, "{file}"),
            progress=False,
            overwrite=False,
        )
        if len(files) == 0:
            print(
                f"Archive GOES XRS: search returned files but fetch was empty for {start_time.isoformat()} .. {end_time.isoformat()}"
            )
            return _empty_xrs_frames()
        ts = TimeSeries(files, concatenate=True)
        df = ts.to_dataframe()
        if df is None or len(df) == 0:
            print(
                f"Archive GOES XRS: fetched files but dataframe was empty for {start_time.isoformat()} .. {end_time.isoformat()}"
            )
            return _empty_xrs_frames()
        cols = {str(c).lower(): c for c in df.columns}
        col_a = cols.get("xrsa")
        col_b = cols.get("xrsb")
        if col_a is None or col_b is None:
            return _empty_xrs_frames()
        idx = pd.to_datetime(df.index, utc=True, errors="coerce")
        good = ~idx.isna()
        idx = idx[good]
        dfa = pd.to_numeric(df.loc[good, col_a], errors="coerce")
        dfb = pd.to_numeric(df.loc[good, col_b], errors="coerce")
        ok = ~(dfa.isna() | dfb.isna())
        idx = idx[ok]
        dfa = dfa[ok]
        dfb = dfb[ok]
        in_window = (idx >= start_time) & (idx <= end_time)
        idx = idx[in_window]
        dfa = dfa[in_window]
        dfb = dfb[in_window]
        if len(idx) == 0:
            print(
                f"Archive GOES XRS: fetched archive data had no valid XRSA/XRSB rows for {start_time.isoformat()} .. {end_time.isoformat()}"
            )
            return _empty_xrs_frames()

        print(
            f"Archive GOES XRS: rows={len(idx)} "
            f"window={start_time.isoformat()}..{end_time.isoformat()} "
            f"first={idx[0].isoformat()} last={idx[-1].isoformat()} "
            f"source=sunpy-fetch"
        )

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
        return (
            xrsa_current.iloc[-100:].reset_index(drop=True),
            xrsb_current.iloc[-100:].reset_index(drop=True),
        )
    except Exception as exc:
        print(f"Archive GOES XRS load failed: {exc}")
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
    alert_face_mode=None,
    goes_anchor_time_local=None,
    archive_goes_offset_minutes=0.0,
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

    # Preserve WAFFLE v3 realtime behavior: when no explicit GOES/AIA anchor is
    # provided, the panel right edge follows the latest GOES sample rather than the
    # latest AIA timestamp. Archive/replay mode passes an explicit anchor so that the
    # panel advances with the replay cursor and can optionally expose a small GOES lead.
    if goes_anchor_time_local is None:
        if len(goes_time_array) > 0:
            min_time = max(
                time_em_array[-1] - timedelta(minutes=60),
                np.min(goes_time_array),
            )
            max_time = np.max(goes_time_array)
        else:
            min_time = time_em_array[-1] - timedelta(minutes=60)
            max_time = time_em_array[-1]
    else:
        aia_now_local = goes_anchor_time_local
        max_time = aia_now_local + timedelta(
            minutes=float(archive_goes_offset_minutes)
        )
        min_time = max_time - timedelta(minutes=60)

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
    display_time_local = time_em_array[-1]
    ax7.set_title(
        "Latest AIA data: - " + display_time_local.strftime("%H:%M:%S") + " " + timezone,
        fontsize=chsize * 1.5,
    )
    ax7.set(xlabel="Time (" + display_time_local.strftime("%m/%d/%Y") + ")")
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
        for trigger_entry in trigger_times:
            if isinstance(trigger_entry, dict):
                trigger_time = trigger_entry.get("time")
                trigger_color = trigger_entry.get("color", "black")
                trigger_style = trigger_entry.get("linestyle", "--")
            else:
                trigger_time = trigger_entry
                trigger_color = "black"
                trigger_style = "--"
            if min_time <= trigger_time <= max_time:
                ax8.axvline(
                    trigger_time,
                    color=trigger_color,
                    linestyle=trigger_style,
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
    if alert_face_mode is None:
        alert_face_mode = "trigger" if any_trigger else "watch"
    if alert_face_mode == "trigger":
        face_color = "#2ca02c"
    elif alert_face_mode == "pretrigger":
        face_color = "#f1c40f"
    else:
        face_color = "#d62728"

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
    if alert_face_mode == "trigger":
        face_ax.add_patch(
            matplotlib.patches.Arc(
                (0.5, 0.43),
                0.42,
                0.30,
                theta1=205,
                theta2=335,
                color="white",
                linewidth=3,
                zorder=21,
            )
        )
    elif alert_face_mode == "pretrigger":
        face_ax.plot([0.31, 0.69], [0.30, 0.30], color="white", linewidth=3, zorder=21)
    else:
        face_ax.add_patch(
            matplotlib.patches.Arc(
                (0.5, 0.33),
                0.42,
                0.30,
                theta1=25,
                theta2=155,
                color="white",
                linewidth=3,
                zorder=21,
            )
        )

    # plt.show()

    plt.savefig(os.path.join(plots_folder, "em_goes_plot"), dpi=85, bbox_inches="tight")
    plt.close(fig)


# **********************************************************


def plot_detailed_em_result(
    plots_folder,
    aia_submaps,
    em_map,
    xrsa_current,
    xrsb_current,
    arnum,
    label,
    box_index,
    file_name_em_csv,
    timezone="US/Central",
    em_cache=None,
    ar_color="red",
    goes_plot_data=None,
):
    ordered_wav = [171, 193, 211, 131, 94]
    map_by_wav = {int(m.meta["wavelnth"]): m for m in aia_submaps}
    ordered_aia_maps = [map_by_wav[w] for w in ordered_wav]

    if goes_plot_data is None:
        goes_time_array, goes_xrsa_flux, goes_xrsb_flux = prepare_goes_plot_arrays(
            xrsa_current, xrsb_current, timezone=timezone
        )
    else:
        goes_time_array, goes_xrsa_flux, goes_xrsb_flux = goes_plot_data

    fig = plt.figure(figsize=(22, 10))

    ax1 = plt.subplot2grid((2, 5), (0, 0), colspan=1, projection=ordered_aia_maps[0])
    ax2 = plt.subplot2grid((2, 5), (0, 1), colspan=1, projection=ordered_aia_maps[1])
    ax3 = plt.subplot2grid((2, 5), (0, 2), colspan=1, projection=ordered_aia_maps[2])
    ax4 = plt.subplot2grid((2, 5), (0, 3), colspan=1, projection=ordered_aia_maps[3])
    ax5 = plt.subplot2grid((2, 5), (0, 4), colspan=1, projection=ordered_aia_maps[4])
    ax6 = plt.subplot2grid((2, 5), (1, 0), colspan=2, projection=em_map)
    ax7 = plt.subplot2grid((2, 5), (1, 2), colspan=3)

    plt.subplots_adjust(
        left=0.1, bottom=0.1, right=0.9, top=0.9, wspace=0.48, hspace=0.4
    )

    labelsize = 15
    ticksize = 15
    chsize = 15
    legsize = 15
    xlabel = "Solar X [arcsec]"
    ylabel = "Solar Y [arcsec]"

    for jj, aia_map in enumerate(ordered_aia_maps):
        aia_map.plot(axes=[ax1, ax2, ax3, ax4, ax5][jj])
        ax = [ax1, ax2, ax3, ax4, ax5][jj]
        ax.set_title("AIA " + str(aia_map.meta["wavelnth"]) + "A", fontsize=labelsize)
        ax.set_xlabel(xlabel, fontsize=labelsize)
        ax.set_ylabel(ylabel, fontsize=labelsize)
        ax.tick_params(axis="x", labelsize=ticksize)
        ax.tick_params(axis="y", labelsize=ticksize)

    title = "AIA Emission Measure \n (T $\\geq 10^{6.6}$ K)"
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
        [ax6.get_position().x1 + 0.01, ax6.get_position().y0, 0.01, ax6.get_position().height]
    )
    cbar = fig.colorbar(im, cax=cax)
    cbar.ax.tick_params(labelsize=labelsize)
    cbar.ax.set_ylabel("EM [cm$^{-3}$ pixel$^{-1}$]", fontsize=labelsize)

    time_em_array, total_em = load_em_series(
        file_name_em_csv,
        timezone=timezone,
        em_cache=em_cache,
    )
    min_time = time_em_array[-1] - timedelta(minutes=150)
    max_time = time_em_array[-1]
    if len(goes_time_array) > 0:
        goes_mask = (goes_time_array >= min_time) & (goes_time_array <= max_time)
        goes_time_array = goes_time_array[goes_mask]
        goes_xrsa_flux = np.asarray(goes_xrsa_flux)[goes_mask]
        goes_xrsb_flux = np.asarray(goes_xrsb_flux)[goes_mask]

    if len(goes_time_array) > 0:
        ax7.plot(goes_time_array, goes_xrsa_flux, "gray", label="GOES XRSA", linestyle="-.")
        ax7.plot(goes_time_array, goes_xrsb_flux, "black", label="GOES XRSB", linestyle="dashed")
    ax7.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=tz.gettz(timezone)))
    ax7.xaxis.set_major_locator(mdates.MinuteLocator(interval=20))
    ax7.set_yscale("log")
    ax7.tick_params(axis="x", labelsize=chsize)
    ax7.tick_params(axis="y", labelsize=chsize)
    ax7.set(xlabel="Time (" + time_em_array[-1].strftime("%m/%d/%Y") + ")")
    ax7.set(ylabel="GOES level")
    ax7.xaxis.label.set_size(chsize)
    ax7.yaxis.label.set_size(chsize)
    ax7.set_xlim((min_time, max_time))
    ax7.set_ylim(1e-8, 1e-4)
    ax7.set_yticks([1e-8, 1e-7, 1e-6, 1e-5, 1e-4])
    ax7.set_yticklabels(["A", "B", "C", "M", "X"])
    ax7.grid(True)
    ax7.tick_params(axis="y", labelcolor="black")
    ax7.yaxis.label.set_color("black")

    ax8 = ax7.twinx()
    em_mask = time_em_array >= min_time
    ax8.plot(time_em_array[em_mask], total_em[em_mask], ar_color, label="AIA EM")
    ax8.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=tz.gettz(timezone)))
    ax8.set_yscale("log")
    ax8.set_ylim(1e46, 1e50)
    ax8.set_xlim((min_time, max_time))
    ax8.tick_params(axis="x", labelsize=chsize)
    ax8.set(ylabel="EM [cm$^{-3}$]")
    ax8.tick_params(axis="y", labelsize=chsize)
    ax8.yaxis.label.set_size(chsize)
    ax8.tick_params(axis="y", labelcolor=ar_color)
    ax8.yaxis.label.set_color(ar_color)
    ax8.spines["right"].set_color(ar_color)

    # Lock left-side y-axis titles to fixed offsets relative to each subplot box.
    top_ylabel_offset = 0.041
    em_ylabel_offset = 0.038
    for ax in [ax1, ax2, ax3, ax4, ax5]:
        ax.set_ylabel("")
        pos = ax.get_position()
        fig.text(
            pos.x0 - top_ylabel_offset,
            pos.y0 + pos.height / 2.0,
            ylabel,
            rotation='vertical',
            va='center',
            ha='center',
            fontsize=labelsize,
        )
    ax6.set_ylabel("")
    pos = ax6.get_position()
    fig.text(
        pos.x0 - em_ylabel_offset,
        pos.y0 + pos.height / 2.0,
        ylabel,
        rotation='vertical',
        va='center',
        ha='center',
        fontsize=labelsize,
    )

    fig.legend(bbox_to_anchor=(0.09, 0.05, 0.45, 0.38), fontsize=legsize)
    fig.suptitle(
        label + " " + str(arnum) + " - " + time_em_array[-1].strftime("%H:%M:%S") + " " + timezone,
        fontsize=25,
    )

    out_path = os.path.join(plots_folder, "aia_em_" + str(box_index))
    plt.savefig(
        out_path,
        dpi=85,
        facecolor="white",
    )
    plt.close(fig)



# **********************************************************


def _serialize_map_for_process(aia_map):
    return {"data": np.asarray(aia_map.data), "meta": dict(aia_map.meta)}


def _deserialize_map_from_process(payload):
    return Map(np.asarray(payload["data"]), payload["meta"])


def render_detailed_em_result_process(payload):
    aia_submaps = [
        _deserialize_map_from_process(item) for item in payload["aia_submaps"]
    ]
    em_map = _deserialize_map_from_process(payload["em_map"])
    goes_plot_data = payload.get("goes_plot_data")
    if goes_plot_data is not None:
        goes_time_array, goes_xrsa_flux, goes_xrsb_flux = goes_plot_data
        goes_plot_data = (
            np.asarray(goes_time_array, dtype=object),
            np.asarray(goes_xrsa_flux, dtype=float),
            np.asarray(goes_xrsb_flux, dtype=float),
        )
    plot_detailed_em_result(
        payload["plots_folder"],
        aia_submaps,
        em_map,
        pd.DataFrame(),
        pd.DataFrame(),
        payload["arnum"],
        payload["label"],
        payload["box_index"],
        payload["file_name_em_csv"],
        timezone=payload.get("timezone", "US/Central"),
        em_cache=None,
        ar_color=payload.get("ar_color", "red"),
        goes_plot_data=goes_plot_data,
    )


# **********************************************************


def resolve_full_disk_render_workers(enabled, requested_workers, worker_count, n_maps):
    if not bool(enabled):
        return 1
    if n_maps <= 1:
        return 1
    if requested_workers in (None, 0, "", "None"):
        requested_workers = worker_count
    try:
        resolved = int(requested_workers)
    except Exception:
        resolved = int(worker_count)
    return max(1, min(int(n_maps), resolved))


def _load_font(size):
    # Prefer broadly available font names before falling back to Pillow's bitmap default.
    for font_name in (
        "DejaVuSans.ttf",
        "Arial.ttf",
        "LiberationSans-Regular.ttf",
        "FreeSans.ttf",
    ):
        try:
            return ImageFont.truetype(font_name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _render_full_disk_aia_panel_process(payload):
    aia_map = _deserialize_map_from_process(payload["map"])
    out_path = payload["out_path"]
    ar_lon = payload["ar_lon"]
    ar_lat = payload["ar_lat"]
    color_arr = payload["color_arr"]
    n_pix_x = int(payload["n_pix_x"])
    n_pix_y = int(payload["n_pix_y"])

    fig = plt.figure(figsize=(4.7, 5.35))
    ax = fig.add_subplot(111, projection=aia_map)
    aia_map.plot_settings["norm"] = colors.LogNorm(vmin=0.3, vmax=16000.0 / 2.9, clip=True)
    aia_map.plot_settings["cmap"] = matplotlib.cm.get_cmap("gray")
    aia_map.plot(axes=ax)
    ax.set_title(f"AIA {int(aia_map.meta['wavelnth'])}Å", fontsize=16)
    ax.set_xlabel("Solar X [arcsec]", fontsize=13)
    ax.set_ylabel("Solar Y [arcsec]", fontsize=13, labelpad=-0.8)
    ax.tick_params(axis="x", labelsize=13)
    ax.tick_params(axis="y", labelsize=13, pad=2.0)

    ar_coords = [
        SkyCoord(ar_lon[ii] * u.deg, ar_lat[ii] * u.deg, frame=frames.HeliographicStonyhurst)
        for ii in range(len(ar_lon))
    ]
    for ii in range(len(ar_lon)):
        this_coord = ar_coords[ii]
        pix_x = aia_map.world_to_pixel(this_coord).x.value
        pix_y = aia_map.world_to_pixel(this_coord).y.value
        top_right = aia_map.pixel_to_world(
            (pix_x + n_pix_x // 2 - 1) * u.pix, (pix_y + n_pix_y // 2 - 1) * u.pix
        )
        bottom_left = aia_map.pixel_to_world(
            (pix_x - n_pix_x // 2) * u.pix, (pix_y - n_pix_y // 2) * u.pix
        )
        new_bl = SkyCoord(bottom_left.Tx, bottom_left.Ty, frame=aia_map.coordinate_frame)
        new_tr = SkyCoord(top_right.Tx, top_right.Ty, frame=aia_map.coordinate_frame)
        aia_map.draw_quadrangle(
            new_bl,
            axes=ax,
            top_right=new_tr,
            color=color_arr[ii],
            linewidth=2,
        )

    fig.subplots_adjust(left=0.14, right=1.06, top=0.89, bottom=0.14)
    fig.savefig(out_path, dpi=130)
    plt.close(fig)

    # Trim only blank right-edge whitespace without changing the left-side axis area.
    try:
        panel = Image.open(out_path).convert("RGB")
        arr = np.asarray(panel)
        nonwhite = np.where(np.any(arr < 250, axis=2))[1]
        if nonwhite.size:
            right_edge = min(panel.width, int(nonwhite.max()) + 3)
            if right_edge > 0 and right_edge < panel.width:
                panel.crop((0, 0, right_edge, panel.height)).save(out_path)
    except Exception:
        pass
    return out_path


def _render_suvi_panel_image(suvi_image, suvi_title, out_path, target_height):
    width = int(round(target_height * 0.93))
    panel = Image.new("RGB", (width, target_height), "white")
    draw = ImageDraw.Draw(panel)
    title_font = _load_font(34)
    bbox = draw.textbbox((0, 0), suvi_title, font=title_font)
    title_w = bbox[2] - bbox[0]
    draw.text((max(10, (width - title_w) / 2), 36), suvi_title, fill=(255, 0, 0), font=title_font)
    top_pad = 76
    side_pad = 10
    bottom_pad = 8
    if suvi_image is None:
        draw.rectangle([side_pad, top_pad, width - side_pad, target_height - bottom_pad], fill=(0, 0, 0))
        msg_font = _load_font(16)
        msg = "SUVI data not available"
        bbox = draw.textbbox((0, 0), msg, font=msg_font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        draw.text(
            ((width - tw) / 2, top_pad + (target_height - top_pad - bottom_pad - th) / 2),
            msg,
            fill=(255, 255, 255),
            font=msg_font,
        )
    else:
        src = suvi_image
        if not isinstance(src, Image.Image):
            src = Image.fromarray(np.asarray(src))
        src = src.convert("RGB")
        avail_w = width - 2 * side_pad
        avail_h = target_height - top_pad - bottom_pad
        scale = min(avail_w / src.width, avail_h / src.height)
        new_size = (max(1, int(src.width * scale)), max(1, int(src.height * scale)))
        resized = src.resize(new_size, Image.Resampling.LANCZOS)
        x0 = (width - resized.width) // 2
        y0 = top_pad + (avail_h - resized.height) // 2
        panel.paste(resized, (x0, y0))
    panel.save(out_path)
    return out_path


def plot_full_disk_images_parallel(
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
    render_workers=5,
):
    ordered_wav = [171, 193, 211, 131, 94]
    map_by_wav = {int(m.meta["wavelnth"]): m for m in calibrated_aia_maps}
    ordered_aia_maps = [map_by_wav[w] for w in ordered_wav]
    current_time_utc = datetime.datetime.strptime(
        t_rec[0], "%Y-%m-%dT%H:%M:%SZ"
    ).replace(tzinfo=datetime.timezone.utc)
    current_time_local = convert_utc_to_timezone(current_time_utc, timezone=timezone)
    if suvi_obs_time_utc is not None:
        suvi_time_local = convert_utc_to_timezone(suvi_obs_time_utc, timezone=timezone)
        suvi_panel_title = f"{suvi_title} | {suvi_time_local.strftime('%Y-%m-%d %H:%M:%S')}"
    else:
        suvi_panel_title = suvi_title

    temp_dir = os.path.join(plots_folder, "_full_disk_panel_cache")
    mkdir(temp_dir)
    panel_paths = [os.path.join(temp_dir, f"panel_{wav}.png") for wav in ordered_wav]
    payloads = []
    for idx, aia_map in enumerate(ordered_aia_maps):
        payloads.append(
            {
                "map": _serialize_map_for_process(aia_map),
                "out_path": panel_paths[idx],
                "ar_lon": [float(v) for v in ar_lon],
                "ar_lat": [float(v) for v in ar_lat],
                "color_arr": list(color_arr),
                "n_pix_x": int(n_pix_x),
                "n_pix_y": int(n_pix_y),
            }
        )

    with ProcessPoolExecutor(max_workers=render_workers) as ex:
        futures = [ex.submit(_render_full_disk_aia_panel_process, payload) for payload in payloads]
        for fut in as_completed(futures):
            fut.result()

    panel_images = [Image.open(path).convert("RGB") for path in panel_paths]
    panel_heights = [img.height for img in panel_images]
    target_height = max(panel_heights)
    suvi_path = os.path.join(temp_dir, "panel_suvi.png")
    _render_suvi_panel_image(suvi_image, suvi_panel_title, suvi_path, target_height)
    suvi_panel = Image.open(suvi_path).convert("RGB")

    gap = 18.2
    side_margin = 26
    top_margin = 88
    bottom_margin = 12
    title_font = _load_font(70)
    title = "AIA data " + current_time_local.strftime("%m/%d/%Y - %H:%M:%S") + " " + timezone

    total_width = int(round(
        side_margin * 2
        + sum(img.width for img in panel_images)
        + suvi_panel.width
        + gap * 5
    ))
    total_height = int(round(top_margin + target_height + bottom_margin))
    canvas = Image.new("RGB", (total_width, total_height), "white")
    draw = ImageDraw.Draw(canvas)
    bbox = draw.textbbox((0, 0), title, font=title_font)
    draw.text(
        (int(round((total_width - (bbox[2] - bbox[0])) / 2)), 10),
        title,
        fill=(0, 0, 0),
        font=title_font,
    )

    x = float(side_margin)
    y = int(round(top_margin))
    for img in panel_images:
        canvas.paste(img, (int(round(x)), y))
        x += img.width + gap
    canvas.paste(suvi_panel, (int(round(x)), y))

    out_path = os.path.join(
        plots_folder,
        "aia_full_disk_" + current_time_local.strftime("%Y-%m-%dT%H%M%S") + ".png",
    )
    canvas.save(out_path)
    for img in panel_images:
        img.close()
    suvi_panel.close()
    prune_full_disk_images(plots_folder, keep_last=30)


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
    ar_x,
    ar_y,
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
    publish_mode="scp",
    local_publish_dir=None,
    external_control_url="",
    enable_global_control=False,
    global_control_provider="auto",
    local_web_port=8003,
    ngrok_authtoken="",
    global_control_tunnel=None,
    detailed_analysis_subdir="detailed_analysis",
    parallel_detailed_plot_renders=False,
    detailed_plot_render_workers=None,
    tunnel_health_check_interval_sec=60.0,
    tunnel_restart_cooldown_sec=30.0,
    tunnel_health_timeout_sec=6.0,
    drms_series="aia.lev1_nrt2",
    drms_segment="image_lev1",
    query_start_ut=None,
    time_step_minutes=None,
    worker_count=4,
    print_phase_timing=False,
    parallel_full_disk_render=False,
    full_disk_render_workers=None,
    em_processing_mode=0,
    suvi_top_wavelength=131,
    suvi_use_realtime=False,
    fai_trigger_cooldown_frames=10,
    fai_trigger_box_em_total_thresholds=(5.0e47, 1.0e48, 5.0e48, 9.0e48),
    fai_trigger_t_mk_thresholds=(9.3, 9.0, 10.5, 12.0),
    fai_trigger_em49_thresholds=(0.015, 0.015, 0.05, 0.1),
    startup_box_recenter=True,
    startup_box_recenter_arcsec=180.0,
    box_recenter_interval_hours=2.0,
    download_timeout_sec=30.0,
    download_retry_delay_sec=10.0,
    download_retry_attempts=2,
    archive_trigger_realtime_delay_minutes=4.5,
    send_sms=False,
    sms_recipients_file="",
    sms_smtp_config_file="",
    ssh_host="physics.wku.edu",
    ssh_user="emslie",
    ssh_password="waffle",
    destination_volume="/server/html/waffle_2/",
    region_source="manual",
    solarmonitor_type="shmi_maglc",
    solarmonitor_indexnum=1,
    solarmonitor_refresh_on_utc_day_rollover=True,
    solarmonitor_refresh_on_timezone_day_rollover=False,
    min_box_center_dx_pix=None,
    min_box_center_dy_pix=None,
    ar_priority=None,
):
    """

    Function for downloading near real time AIA data, computing the high temperature EM maps and plot the results on the WKU website

    Parameters
        ----------

        duration_stream: int or None. Duration of the data stream in minutes.
                         If None, stream runs until manually stopped.

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
    if len(ar_x) < n_ar:
        raise Exception("The number of elements in ar_x is less than " + str(n_ar))
    if len(ar_y) < n_ar:
        raise Exception("The number of elements in ar_y is less than " + str(n_ar))
    if em_processing_mode not in (0, 1, 2):
        raise ValueError("em_processing_mode must be 0, 1, or 2")

    # Define colors that will be used for plotting the boxes and the corresponding curves
    color_arr = ["#FF0000", "#FFD700", "#0000FF", "#00FF00", "#00FFFF", "#FF00FF"]
    arnum = list(arnum)
    ar_x = np.array(ar_x, dtype=float)
    ar_y = np.array(ar_y, dtype=float)
    if min_box_center_dx_pix is None:
        min_box_center_dx_pix = n_pix_x
    if min_box_center_dy_pix is None:
        min_box_center_dy_pix = n_pix_y
    min_center_dx_arcsec = 0.6 * float(min_box_center_dx_pix)
    min_center_dy_arcsec = 0.6 * float(min_box_center_dy_pix)

    # Define JSOC server client.
    use_nrt2_server = str(drms_series).lower().startswith("aia.lev1_nrt2")
    client = configure_jsoc_server(use_nrt2_server=use_nrt2_server)

    # Plots folder
    plots_folder = os.path.join(data_folder, "all_plots")
    mkdir(plots_folder)

    # Latest results folder
    latest_plots_folder = os.path.join(data_folder, "latest_plots")
    mkdir(latest_plots_folder)
    detailed_analysis_folder = os.path.join(data_folder, detailed_analysis_subdir)
    mkdir(detailed_analysis_folder)
    write_detailed_analysis_pages(detailed_analysis_folder, label[:n_ar], arnum[:n_ar])

    # AIA data folder
    aia_data_folder = os.path.join(data_folder, "aia_data_folder")
    mkdir(aia_data_folder)

    # GOES data folder
    goes_folder = os.path.join(data_folder, "goes_data_folder")
    mkdir(goes_folder)

    # Total EM folder
    total_em_folder = os.path.join(data_folder, "total_em")
    mkdir(total_em_folder)
    def ensure_total_em_files(current_arnum):
        for i in range(len(current_arnum)):
            file_name_csv = os.path.join(
                total_em_folder, "total_em_" + str(current_arnum[i]) + ".csv"
            )
            if not os.path.exists(file_name_csv):
                write_csv_em(file_name_csv, 0, 0, function_csv="w")

    ensure_total_em_files(arnum)

    # Cache to avoid repeated CSV reads/parsing in plotting calls.
    em_cache = {}
    fai_history = {lab: [] for lab in label[:n_ar]}
    active_area_fraction_history = {lab: [] for lab in label[:n_ar]}
    em_history = {lab: [] for lab in label[:n_ar]}
    fai_trigger_times = []
    fai_trigger_cooldown_remaining = {lab: 0 for lab in label[:n_ar]}
    persistent_fai_active = False
    persistent_fai_label = None
    persistent_fai_release_avg = 0.45
    startup_boxes_refined = False
    last_solarmonitor_day = None
    last_box_recenter_ut = None
    if box_recenter_interval_hours is not None and float(box_recenter_interval_hours) <= 0:
        box_recenter_interval_hours = None
    resumed_state = _load_runtime_stream_state(data_folder, label[:n_ar])
    if resumed_state is not None:
        fai_history.update(
            resumed_state.get("fai_history", {})
        )
        active_area_fraction_history.update(
            resumed_state.get("active_area_fraction_history", {})
        )
        em_history.update(resumed_state.get("em_history", {}))
        fai_trigger_cooldown_remaining.update(
            resumed_state.get("fai_trigger_cooldown_remaining", {})
        )
        persistent_fai_active = bool(
            resumed_state.get("persistent_fai_active", False)
        )
        persistent_fai_label = resumed_state.get(
            "persistent_fai_label"
        )
        saved_arnum = resumed_state.get("arnum")
        saved_ar_x = resumed_state.get("ar_x")
        saved_ar_y = resumed_state.get("ar_y")
        saved_ar_priority = resumed_state.get("ar_priority")
        if (
            saved_arnum is not None
            and saved_ar_x is not None
            and saved_ar_y is not None
            and len(saved_arnum) == n_ar
            and len(saved_ar_x) == n_ar
            and len(saved_ar_y) == n_ar
        ):
            arnum = list(saved_arnum)
            ar_x = np.asarray(saved_ar_x, dtype=float)
            ar_y = np.asarray(saved_ar_y, dtype=float)
            if saved_ar_priority is not None and len(saved_ar_priority) == n_ar:
                ar_priority = np.asarray(saved_ar_priority, dtype=float)
            ensure_total_em_files(arnum)
            print("Resumed saved box coordinates from previous run.")
        startup_boxes_refined = bool(
            resumed_state.get("startup_boxes_refined", startup_boxes_refined)
        )
        saved_last_box_recenter_ut = resumed_state.get("last_box_recenter_ut")
        if saved_last_box_recenter_ut:
            try:
                last_box_recenter_ut = datetime.datetime.fromisoformat(
                    str(saved_last_box_recenter_ut)
                )
                if last_box_recenter_ut.tzinfo is None:
                    last_box_recenter_ut = last_box_recenter_ut.replace(
                        tzinfo=datetime.timezone.utc
                    )
            except Exception:
                last_box_recenter_ut = None
        print("Resumed waffle_v1p2 runtime state from previous run.")
    # Array containing the wavelengths needed to compute the high temperature EM maps
    wavelengths_needed = np.array([94, 131, 171, 193, 211])

    # Initialize start time, current time and difference between start time and current time (zero at the beginning of the stream)
    realtime_mode = query_start_ut is None
    if query_start_ut is None:
        query_start_ut = datetime.datetime.now(datetime.timezone.utc)
    start_time_ut = query_start_ut - timedelta(minutes=latency)
    if region_source == "solarmonitor":
        last_solarmonitor_day = _solarmonitor_rollover_key(
            query_start_ut,
            timezone=timezone,
            use_local_day=solarmonitor_refresh_on_timezone_day_rollover,
        )
    if ar_priority is None:
        ar_priority = np.zeros(len(arnum), dtype=float)
    else:
        ar_priority = np.asarray(ar_priority, dtype=float)
    start_time_ut_time_diff = datetime.datetime.now(datetime.timezone.utc)
    current_time_ut = start_time_ut
    time_diff = 0

    # Define utc time zone
    utc = pytz.timezone("UTC")

    # Independent cursor step control (defaults to latency for backward compatibility).
    if time_step_minutes is None:
        time_step_minutes = latency

    # Define publishing destination.
    publish_root = destination_volume
    ssh_client = None
    sms_recipients_path = Path(
        sms_recipients_file.strip()
        if str(sms_recipients_file).strip()
        else os.path.join(os.path.dirname(os.path.abspath(__file__)), "sms_recipients.txt")
    )
    sms_smtp_config_path = Path(
        sms_smtp_config_file.strip()
        if str(sms_smtp_config_file).strip()
        else os.path.join(os.path.dirname(os.path.abspath(__file__)), "sms_smtp_config.json")
    )
    sms_recipients = load_sms_recipients(sms_recipients_path)
    sms_smtp_cfg = load_sms_smtp_config(sms_smtp_config_path)
    sms_enabled = bool(send_sms)
    if sms_enabled:
        sms_missing = []
        if not sms_recipients:
            sms_missing.append(f"no recipients in {sms_recipients_path}")
        if not str(sms_smtp_cfg.get("from_email", "")).strip():
            sms_missing.append(f"missing from_email in {sms_smtp_config_path}")
        if not str(sms_smtp_cfg.get("app_password", "")).strip():
            sms_missing.append(f"missing app_password in {sms_smtp_config_path}")
        if sms_missing:
            print(
                "SMS disabled: "
                + "; ".join(sms_missing)
            )
            sms_enabled = False
    c5_sms_active = False
    goes_sms_active = False
    aia_sms_active = False
    offline_sms_active = False
    startup_sms_sent = False
    last_successful_publish_unix = time.time()
    last_successful_goes_plot_data = None
    configured_control_url = (
        str(external_control_url).strip() if str(ngrok_authtoken or "").strip() else ""
    )
    tunnel_health_check_interval_sec = max(10.0, float(tunnel_health_check_interval_sec))
    tunnel_restart_cooldown_sec = max(10.0, float(tunnel_restart_cooldown_sec))
    tunnel_next_health_check_unix = 0.0
    tunnel_next_restart_unix = 0.0
    box_control_path = None
    box_control_mtime = None
    if publish_mode == "scp":
        ssh_client = define_ssh_client(
            ssh_host=ssh_host,
            ssh_user=ssh_user,
            ssh_password=ssh_password,
        )
        if local_publish_dir is not None:
            mkdir(local_publish_dir)
            box_control_path = default_box_control_path(local_publish_dir)
            initialize_box_control_file(
                box_control_path,
                build_box_control_config(
                    region_source=region_source,
                    arnum=arnum,
                    ar_x=ar_x,
                    ar_y=ar_y,
                    startup_box_recenter=startup_box_recenter,
                    startup_box_recenter_arcsec=startup_box_recenter_arcsec,
                    box_recenter_interval_hours=box_recenter_interval_hours,
                    min_box_center_dx_pix=min_box_center_dx_pix,
                    min_box_center_dy_pix=min_box_center_dy_pix,
                    solarmonitor_refresh_on_utc_day_rollover=solarmonitor_refresh_on_utc_day_rollover,
                    solarmonitor_refresh_on_timezone_day_rollover=solarmonitor_refresh_on_timezone_day_rollover,
                ),
            )
            if os.path.exists(box_control_path):
                box_control_mtime = os.path.getmtime(box_control_path)
    elif publish_mode == "local":
        if local_publish_dir is None:
            local_publish_dir = os.path.join(data_folder, "local_web")
        mkdir(local_publish_dir)
        publish_root = local_publish_dir
        box_control_path = default_box_control_path(local_publish_dir)
        initialize_box_control_file(
            box_control_path,
            build_box_control_config(
                region_source=region_source,
                arnum=arnum,
                ar_x=ar_x,
                ar_y=ar_y,
                startup_box_recenter=startup_box_recenter,
                startup_box_recenter_arcsec=startup_box_recenter_arcsec,
                box_recenter_interval_hours=box_recenter_interval_hours,
                min_box_center_dx_pix=min_box_center_dx_pix,
                min_box_center_dy_pix=min_box_center_dy_pix,
                solarmonitor_refresh_on_utc_day_rollover=solarmonitor_refresh_on_utc_day_rollover,
                solarmonitor_refresh_on_timezone_day_rollover=solarmonitor_refresh_on_timezone_day_rollover,
            ),
        )
        if os.path.exists(box_control_path):
            box_control_mtime = os.path.getmtime(box_control_path)
        publish_status_local(local_publish_dir, "warn", "Waiting", "WAFFLE stream is initializing")
    else:
        raise ValueError("publish_mode must be either 'scp' or 'local'")

    if publish_mode == "scp":
        publish_runtime_status(
            publish_mode,
            publish_root,
            ssh_client,
            "warn",
            "Waiting",
            "WAFFLE stream is initializing",
            local_mirror_destination=local_publish_dir,
        )

    def sync_box_control_file():
        if local_publish_dir is None:
            return None
        try:
            return write_box_control_file_and_get_mtime(
                default_box_control_path(local_publish_dir),
                build_box_control_config(
                    region_source=region_source,
                    arnum=arnum,
                    ar_x=ar_x,
                    ar_y=ar_y,
                    startup_box_recenter=startup_box_recenter,
                    startup_box_recenter_arcsec=startup_box_recenter_arcsec,
                    box_recenter_interval_hours=box_recenter_interval_hours,
                    min_box_center_dx_pix=min_box_center_dx_pix,
                    min_box_center_dy_pix=min_box_center_dy_pix,
                    solarmonitor_refresh_on_utc_day_rollover=solarmonitor_refresh_on_utc_day_rollover,
                    solarmonitor_refresh_on_timezone_day_rollover=solarmonitor_refresh_on_timezone_day_rollover,
                ),
            )
        except Exception as exc:
            print(f"Failed to sync box control file: {exc}")
            return None

    if resumed_state is not None:
        synced_mtime = sync_box_control_file()
        if synced_mtime is not None:
            box_control_mtime = synced_mtime

    # One shared thread pool for the whole stream to avoid per-phase pool churn.
    worker_count = max(1, int(worker_count))
    shared_executor = None
    if worker_count > 1:
        shared_executor = ThreadPoolExecutor(max_workers=worker_count)

    def maybe_send_sms(message: str) -> None:
        if not sms_enabled:
            return
        send_sms_alert(message, sms_recipients, sms_smtp_cfg)

    ############ START STREAM

    stream_forever = duration_stream is None

    try:
        while stream_forever or time_diff <= duration_stream:
            phase_times = {}
            cycle_start = time.time()
            t_phase = time.time()
            if box_control_path is not None:
                control_cfg, box_control_mtime_new = load_box_control_update(
                    box_control_path, box_control_mtime
                )
                if control_cfg is not None:
                    query_anchor_ut = current_time_ut + timedelta(minutes=latency)
                    applied = apply_box_control_runtime_config(
                        control_cfg,
                        query_anchor_ut=query_anchor_ut,
                        n_pix_x=n_pix_x,
                        n_pix_y=n_pix_y,
                        current_region_source=region_source,
                        startup_box_recenter=startup_box_recenter,
                        startup_box_recenter_arcsec=startup_box_recenter_arcsec,
                        box_recenter_interval_hours=box_recenter_interval_hours,
                        min_box_center_dx_pix=min_box_center_dx_pix,
                        min_box_center_dy_pix=min_box_center_dy_pix,
                        solarmonitor_refresh_on_utc_day_rollover=solarmonitor_refresh_on_utc_day_rollover,
                        solarmonitor_refresh_on_timezone_day_rollover=solarmonitor_refresh_on_timezone_day_rollover,
                    )
                    region_source = applied["region_source"]
                    startup_box_recenter = applied["startup_box_recenter"]
                    startup_box_recenter_arcsec = applied["startup_box_recenter_arcsec"]
                    box_recenter_interval_hours = applied["box_recenter_interval_hours"]
                    min_box_center_dx_pix = applied["min_box_center_dx_pix"]
                    min_box_center_dy_pix = applied["min_box_center_dy_pix"]
                    solarmonitor_refresh_on_utc_day_rollover = applied[
                        "solarmonitor_refresh_on_utc_day_rollover"
                    ]
                    solarmonitor_refresh_on_timezone_day_rollover = applied[
                        "solarmonitor_refresh_on_timezone_day_rollover"
                    ]
                    if applied["arnum"] is not None:
                        arnum = applied["arnum"]
                        ar_x = applied["ar_x"]
                        ar_y = applied["ar_y"]
                        ar_priority = applied["ar_priority"]
                    ensure_total_em_files(arnum)
                    for box_label in label[:n_ar]:
                        fai_history[box_label].clear()
                        active_area_fraction_history[box_label].clear()
                        em_history[box_label].clear()
                        fai_trigger_cooldown_remaining[box_label] = 0
                    fai_trigger_times.clear()
                    persistent_fai_active = False
                    persistent_fai_label = None
                    startup_boxes_refined = False
                    last_box_recenter_ut = None
                    last_solarmonitor_day = None
                    box_control_mtime = box_control_mtime_new
                    synced_mtime = sync_box_control_file()
                    if synced_mtime is not None:
                        box_control_mtime = synced_mtime
                    print("Applied website box-control update for next cycle.")
            if enable_global_control:
                now_unix = time.time()
                if now_unix >= tunnel_next_health_check_unix:
                    tunnel_next_health_check_unix = (
                        now_unix + tunnel_health_check_interval_sec
                    )
                    if is_global_control_tunnel_healthy(
                        global_control_tunnel,
                        external_control_url=configured_control_url or external_control_url,
                        timeout_sec=tunnel_health_timeout_sec,
                    ):
                        resolved_control_url = resolve_global_control_url(
                            global_control_tunnel,
                            configured_control_url or external_control_url,
                        )
                        if resolved_control_url and resolved_control_url != external_control_url:
                            external_control_url = resolved_control_url
                            print(f"Global control link resolved: {external_control_url}")
                    elif now_unix >= tunnel_next_restart_unix:
                        try:
                            global_control_tunnel, resolved_control_url, _ = (
                                ensure_global_control_tunnel(
                                    global_control_tunnel,
                                    local_web_port,
                                    provider=global_control_provider,
                                    ngrok_authtoken=ngrok_authtoken,
                                    external_control_url=configured_control_url,
                                    startup_timeout_sec=20.0,
                                    health_timeout_sec=tunnel_health_timeout_sec,
                                )
                            )
                            tunnel_next_restart_unix = (
                                now_unix + tunnel_restart_cooldown_sec
                            )
                            if resolved_control_url:
                                external_control_url = resolved_control_url
                                print(
                                    f"Global control link resolved: {external_control_url}"
                                )
                            elif not configured_control_url:
                                external_control_url = ""
                                print("Global control link unresolved for this run.")
                        except Exception as exc:
                            tunnel_next_restart_unix = (
                                now_unix + tunnel_restart_cooldown_sec
                            )
                            print(f"Global control tunnel recovery failed: {exc}")
            publish_age = time.time() - float(last_successful_publish_unix)
            if publish_age > 500.0:
                if not offline_sms_active:
                    maybe_send_sms("Waffle: The internet connection has gone down.")
                    offline_sms_active = True
            else:
                offline_sms_active = False
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
                        publish_runtime_status(
                            publish_mode,
                            publish_root,
                            ssh_client,
                            "warn",
                            "Waiting",
                            "Transient DRMS query issue; retrying shortly",
                            local_mirror_destination=local_publish_dir,
                        )
                        print_query_wait_message(use_nrt2_server, err)
                        time.sleep(2)
                        client = configure_jsoc_server(
                            use_nrt2_server=use_nrt2_server
                        )
                        continue
                    publish_runtime_status(
                        publish_mode,
                        publish_root,
                        ssh_client,
                        "warn",
                        "Waiting",
                        "DRMS query failed; WAFFLE will keep retrying",
                        local_mirror_destination=local_publish_dir,
                    )
                    print_query_wait_message(use_nrt2_server, err)
                    print(f"DRMS query failed for {ds_query}: {err}")
                    break

                if query is not None and len(query) > 0:
                    query_cols = set(getattr(query, "columns", []))
                    if ("WAVELNTH" in query_cols) and ("T_REC" in query_cols):
                        query_ready = True
                        break

                if attempt < 2:
                    publish_runtime_status(
                        publish_mode,
                        publish_root,
                        ssh_client,
                        "warn",
                        "Waiting",
                        "JSOC responded without a complete AIA cycle; retrying shortly",
                        local_mirror_destination=local_publish_dir,
                    )
                    print_query_wait_message(use_nrt2_server)
                    time.sleep(2)
                    client = configure_jsoc_server(use_nrt2_server=use_nrt2_server)
                else:
                    publish_runtime_status(
                        publish_mode,
                        publish_root,
                        ssh_client,
                        "warn",
                        "Waiting",
                        "No usable DRMS rows yet; WAFFLE is still polling",
                        local_mirror_destination=local_publish_dir,
                    )
                    cols = list(getattr(query, "columns", [])) if query is not None else []
                    rows = len(query) if query is not None else 0
                    print_query_wait_message(use_nrt2_server)
                    print(
                        f"no usable DRMS rows for {ds_query} "
                        f"(rows={rows}, columns={cols})"
                    )
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
                if realtime_mode:
                    latest_query_start = datetime.datetime.now(
                        datetime.timezone.utc
                    ) - timedelta(minutes=latency)
                    if latest_query_start > current_time_ut:
                        current_time_ut = latest_query_start
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

                cycle_day_yyyymmdd = _solarmonitor_rollover_key(
                    start_time_series,
                    timezone=timezone,
                    use_local_day=solarmonitor_refresh_on_timezone_day_rollover,
                )
                if (
                    region_source == "solarmonitor"
                    and (
                        solarmonitor_refresh_on_utc_day_rollover
                        or solarmonitor_refresh_on_timezone_day_rollover
                    )
                    and cycle_day_yyyymmdd != last_solarmonitor_day
                ):
                    resolved = resolve_solarmonitor_boxes(
                        cycle_day_yyyymmdd,
                        image_type=solarmonitor_type,
                        indexnum=solarmonitor_indexnum,
                        n_pix_x=n_pix_x,
                        n_pix_y=n_pix_y,
                        min_center_dx_pix=min_box_center_dx_pix,
                        min_center_dy_pix=min_box_center_dy_pix,
                    )
                    arnum = list(resolved["arnum"])
                    ar_x = np.array(resolved["ar_x"], dtype=float)
                    ar_y = np.array(resolved["ar_y"], dtype=float)
                    ar_priority = np.array(resolved["ar_priority"], dtype=float)
                    arnum, ar_x, ar_y, ar_priority = reorder_box_layout(
                        arnum, ar_x, ar_y, ar_priority
                    )
                    ensure_total_em_files(arnum)
                    startup_boxes_refined = False
                    last_solarmonitor_day = cycle_day_yyyymmdd
                    synced_mtime = sync_box_control_file()
                    if synced_mtime is not None:
                        box_control_mtime = synced_mtime
                    print(
                        "SolarMonitor refresh "
                        + cycle_day_yyyymmdd
                        + ": top="
                        + ", ".join(
                            f"{(r['region'] % 10000)}@({int(r['x_arcsec'])},{int(r['y_arcsec'])})"
                            f"[score={r['activity_score']:.1f}]"
                            for r in resolved["top_sel"]
                        )
                        + " bottom="
                        + ", ".join(
                            f"{(r['region'] % 10000)}@({int(r['x_arcsec'])},{int(r['y_arcsec'])})"
                            f"[score={r['activity_score']:.1f}]"
                            for r in resolved["bottom_sel"]
                        )
                    )
                    if int(resolved["fallback_needed"]) > 0:
                        print(
                            "SolarMonitor fallback placeholders: "
                            + ", ".join(
                                str(v)
                                for v in range(1, int(resolved["fallback_needed"]) + 1)
                            )
                        )

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
                    if realtime_mode:
                        latest_query_start = datetime.datetime.now(
                            datetime.timezone.utc
                        ) - timedelta(minutes=latency)
                        if latest_query_start > current_time_ut:
                            current_time_ut = latest_query_start
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
                waiting_timer = start_delayed_runtime_status(
                    120.0,
                    publish_mode,
                    publish_root,
                    ssh_client,
                    "warn",
                    "Waiting",
                    "AIA download is taking longer than expected",
                    local_mirror_destination=local_publish_dir,
                )
                aia_maps, dowloaded_data_folder, error = download_aia_data(
                    grouped_wav,
                    grouped_t_rec,
                    grouped_segments,
                    aia_data_folder,
                    timezone=timezone,
                    worker_count=worker_count,
                    executor=shared_executor,
                    download_timeout_sec=download_timeout_sec,
                    download_retry_delay_sec=download_retry_delay_sec,
                    download_retry_attempts=download_retry_attempts,
                )
                waiting_timer.cancel()
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
                missing_box_idx = [
                    i for i in range(n_ar) if (not np.isfinite(ar_x[i])) or (not np.isfinite(ar_y[i]))
                ]
                if missing_box_idx:
                    fallback_xy = find_em_hotspot_boxes(
                        normalized_aia_maps,
                        weights,
                        existing_xy=[
                            (ar_x[i], ar_y[i])
                            for i in range(n_ar)
                            if np.isfinite(ar_x[i]) and np.isfinite(ar_y[i])
                        ],
                        needed=len(missing_box_idx),
                        min_dx_arcsec=min_center_dx_arcsec,
                        min_dy_arcsec=min_center_dy_arcsec,
                    )
                    for slot, (x_fill, y_fill) in zip(missing_box_idx, fallback_xy):
                        ar_x[slot] = float(x_fill)
                        ar_y[slot] = float(y_fill)
                    if fallback_xy:
                        print(
                            "EM hotspot fallback boxes: "
                            + ", ".join(
                                f"{arnum[slot]}@({int(ar_x[slot])},{int(ar_y[slot])})"
                                for slot in missing_box_idx[: len(fallback_xy)]
                            )
                        )
                    # If SolarMonitor gave us no usable boxes, assign the initial
                    # fallback-only layout into WAFFLE's top/bottom slot order once.
                    if np.sum(np.isfinite(ar_priority)) == 0 and np.all(np.isfinite(ar_x)) and np.all(np.isfinite(ar_y)):
                        arnum, ar_x, ar_y, ar_priority = reorder_box_layout(
                            arnum, ar_x, ar_y, ar_priority
                        )
                should_recenter_now = False
                recenter_kind = "Box recenter"
                if startup_box_recenter and (not startup_boxes_refined):
                    should_recenter_now = True
                    recenter_kind = "Startup box recenter"
                elif (
                    box_recenter_interval_hours is not None
                    and last_box_recenter_ut is not None
                    and (
                        start_time_series - last_box_recenter_ut
                    ).total_seconds()
                    >= float(box_recenter_interval_hours) * 3600.0
                ):
                    should_recenter_now = True
                if should_recenter_now:
                    ar_x, ar_y, refined_shifts = refine_box_centers_from_em_map(
                        normalized_aia_maps,
                        weights,
                        ar_x,
                        ar_y,
                        ar_priority=ar_priority,
                        search_radius_arcsec=startup_box_recenter_arcsec,
                        min_dx_arcsec=min_center_dx_arcsec,
                        min_dy_arcsec=min_center_dy_arcsec,
                    )
                    recenter_missing_idx = [
                        i for i in range(n_ar) if (not np.isfinite(ar_x[i])) or (not np.isfinite(ar_y[i]))
                    ]
                    if recenter_missing_idx:
                        fallback_arnums = assign_fallback_arnums(arnum, recenter_missing_idx)
                        for slot, fallback_id in fallback_arnums.items():
                            arnum[slot] = int(fallback_id)
                        ensure_total_em_files(arnum)
                        fallback_xy = find_em_hotspot_boxes(
                            normalized_aia_maps,
                            weights,
                            existing_xy=[
                                (ar_x[j], ar_y[j])
                                for j in range(n_ar)
                                if np.isfinite(ar_x[j]) and np.isfinite(ar_y[j])
                            ],
                            needed=len(recenter_missing_idx),
                            min_dx_arcsec=min_center_dx_arcsec,
                            min_dy_arcsec=min_center_dy_arcsec,
                        )
                        for slot, (x_fill, y_fill) in zip(recenter_missing_idx, fallback_xy):
                            ar_x[slot] = float(x_fill)
                            ar_y[slot] = float(y_fill)
                        if fallback_xy:
                            print(
                                "Post-recenter fallback boxes: "
                                + ", ".join(
                                    f"{arnum[slot]}@({int(ar_x[slot])},{int(ar_y[slot])})"
                                    for slot in recenter_missing_idx[: len(fallback_xy)]
                                )
                            )
                    startup_boxes_refined = True
                    last_box_recenter_ut = start_time_series
                    synced_mtime = sync_box_control_file()
                    if synced_mtime is not None:
                        box_control_mtime = synced_mtime
                    if refined_shifts:
                        print(
                            recenter_kind + ": "
                            + ", ".join(
                                (
                                    f"{arnum[i]} ({x0:.0f},{y0:.0f})->dropped"
                                    if (not np.isfinite(x1) or not np.isfinite(y1))
                                    else f"{arnum[i]} ({x0:.0f},{y0:.0f})->({x1:.0f},{y1:.0f})"
                                )
                                for i, x0, y0, x1, y1 in refined_shifts
                            )
                        )
                cycle_ar_lon = np.array(ar_lon[:n_ar], dtype=float)
                cycle_ar_lat = np.array(ar_lat[:n_ar], dtype=float)
                if len(normalized_aia_maps) > 0:
                    ref_map = normalized_aia_maps[0]
                    for i in range(n_ar):
                        lon_i, lat_i = hpc_xy_to_hgs(ref_map, ar_x[i], ar_y[i])
                        cycle_ar_lon[i] = lon_i
                        cycle_ar_lat[i] = lat_i
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
                    if realtime_mode:
                        latest_query_start = datetime.datetime.now(
                            datetime.timezone.utc
                        ) - timedelta(minutes=latency)
                        if latest_query_start > current_time_ut:
                            current_time_ut = latest_query_start
                    if not aia_sms_active:
                        maybe_send_sms("Waffle: AIA data download has dropped out.")
                        aia_sms_active = True
                    publish_runtime_status(
                        publish_mode,
                        publish_root,
                        ssh_client,
                        "warn",
                        "Waiting",
                        "One or more AIA files failed to download; retrying next cycle",
                        local_mirror_destination=local_publish_dir,
                    )
                    print("Error in downloading data. Continue..")
                    time.sleep(30)
                    continue
                aia_sms_active = False

                # Crop images around ARs and compute EM of the "hottest region"
                cropped_maps_folder = dowloaded_data_folder + "_crop"
                if save_maps:
                    mkdir(cropped_maps_folder)
                if save_box_crops:
                    if box_crops_root is None:
                        box_crops_root = os.path.join(data_folder, "box_crops")
                    mkdir(box_crops_root)
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
                full_disk_workers = resolve_full_disk_render_workers(
                    parallel_full_disk_render,
                    full_disk_render_workers,
                    worker_count,
                    len(normalized_aia_maps),
                )
                if full_disk_workers > 1:
                    try:
                        plot_full_disk_images_parallel(
                            normalized_aia_maps,
                            plots_folder,
                            grouped_t_rec,
                            arnum,
                            cycle_ar_lon,
                            cycle_ar_lat,
                            color_arr,
                            timezone=timezone,
                            n_pix_x=n_pix_x,
                            n_pix_y=n_pix_y,
                            suvi_image=suvi_img,
                            suvi_title=suvi_title,
                            suvi_obs_time_utc=suvi_obs_time_utc,
                            render_workers=full_disk_workers,
                        )
                    except Exception as exc:
                        print(
                            "Parallel full-disk rendering failed; "
                            f"retrying serially. Error: {exc}"
                        )
                        plot_full_disk_images(
                            normalized_aia_maps,
                            plots_folder,
                            grouped_t_rec,
                            arnum,
                            cycle_ar_lon,
                            cycle_ar_lat,
                            color_arr,
                            timezone=timezone,
                            n_pix_x=n_pix_x,
                            n_pix_y=n_pix_y,
                            suvi_image=suvi_img,
                            suvi_title=suvi_title,
                            suvi_obs_time_utc=suvi_obs_time_utc,
                        )
                else:
                    plot_full_disk_images(
                        normalized_aia_maps,
                        plots_folder,
                        grouped_t_rec,
                        arnum,
                        cycle_ar_lon,
                        cycle_ar_lat,
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
                    xrsa_current, xrsb_current = load_archive_XRS(
                        reference_time_ut=start_time_series,
                        goes_folder=goes_folder,
                        lookback_hours=1.0,
                        lead_minutes=3.0,
                    )
                archive_goes_offset_minutes = 0.0 if realtime_mode else 3.0
                goes_available = (not xrsa_current.empty) and (not xrsb_current.empty)
                if goes_available:
                    goes_sms_active = False
                elif not goes_sms_active:
                    maybe_send_sms("Waffle: GOES XRS data has dropped out.")
                    goes_sms_active = True
                goes_anchor_local = None
                if not realtime_mode:
                    goes_anchor_local = convert_utc_to_timezone(
                        start_time_series, timezone=timezone
                    )
                goes_plot_data = prepare_goes_plot_arrays(
                    xrsa_current,
                    xrsb_current,
                    timezone=timezone,
                    anchor_time_local=goes_anchor_local,
                    lookback_minutes=60,
                    archive_goes_offset_minutes=archive_goes_offset_minutes,
                )
                if goes_available:
                    last_successful_goes_plot_data = goes_plot_data
                elif last_successful_goes_plot_data is not None:
                    break_time_local = goes_anchor_local
                    if break_time_local is None:
                        break_time_local = convert_utc_to_timezone(
                            start_time_series, timezone=timezone
                        )
                    goes_plot_data = append_goes_plot_break(
                        last_successful_goes_plot_data,
                        break_time_local,
                    )
                xrsb_derivative = _latest_xrsb_derivative(
                    xrsb_current, reference_time_ut=start_time_series
                )
                _, cursor_t_mk, cursor_em49 = _print_runtime_goes_cursor_snapshot(
                    xrsa_current,
                    xrsb_current,
                    start_time_series,
                    realtime_mode=realtime_mode,
                    archive_goes_offset_minutes=archive_goes_offset_minutes,
                )
                if print_phase_timing:
                    phase_times["goes"] = time.time() - t_phase

                t_phase = time.time()
                em_maps = [None] * n_ar
                em_totals = [0.0] * n_ar
                detail_aia_submaps = [None] * n_ar

                def _compute_ar(i):
                    detail_submaps = crop_full_disk_maps(
                        calibrated_aia_maps,
                        cycle_ar_lon[i],
                        cycle_ar_lat[i],
                        arnum[i],
                        cropped_maps_folder,
                        n_pix_x=n_pix_x,
                        n_pix_y=n_pix_y,
                        save_submaps=False,
                    )
                    if em_processing_mode == 0:
                        aia_img, metadata = fast_crop_em_cube(
                            em_calibrated_full_maps,
                            cycle_ar_lon[i],
                            cycle_ar_lat[i],
                            n_pix_x=n_pix_x,
                            n_pix_y=n_pix_y,
                        )
                    elif em_processing_mode == 1:
                        aia_submaps = crop_full_disk_maps(
                            em_calibrated_full_maps,
                            cycle_ar_lon[i],
                            cycle_ar_lat[i],
                            arnum[i],
                            cropped_maps_folder,
                            n_pix_x=n_pix_x,
                            n_pix_y=n_pix_y,
                            save_submaps=False,
                        )
                        aia_img, metadata = submaps_to_em_cube(aia_submaps)
                    else:
                        aia_submaps_em = []
                        for this_submap in detail_submaps:
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
                    return i, em_map_raw, total_em_current, detail_submaps

                n_workers = max(1, min(int(worker_count), n_ar))
                if n_workers == 1:
                    for i in range(n_ar):
                        i_out, em_map_raw, total_em_current, detail_submaps = _compute_ar(i)
                        em_maps[i_out] = em_map_raw
                        em_totals[i_out] = total_em_current
                        detail_aia_submaps[i_out] = detail_submaps
                else:
                    active_executor = shared_executor
                    if active_executor is None:
                        with ThreadPoolExecutor(max_workers=n_workers) as executor:
                            futures = [
                                executor.submit(_compute_ar, i) for i in range(n_ar)
                            ]
                            for fut in as_completed(futures):
                                i_out, em_map_raw, total_em_current, detail_submaps = fut.result()
                                em_maps[i_out] = em_map_raw
                                em_totals[i_out] = total_em_current
                                detail_aia_submaps[i_out] = detail_submaps
                    else:
                        futures = [
                            active_executor.submit(_compute_ar, i) for i in range(n_ar)
                        ]
                        for fut in as_completed(futures):
                            i_out, em_map_raw, total_em_current, detail_submaps = fut.result()
                            em_maps[i_out] = em_map_raw
                            em_totals[i_out] = total_em_current
                            detail_aia_submaps[i_out] = detail_submaps

                # Optional FITS exports remain single-threaded I/O.
                if save_maps:
                    for i in range(n_ar):
                        crop_full_disk_maps(
                            calibrated_aia_maps,
                            cycle_ar_lon[i],
                            cycle_ar_lat[i],
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
                            cycle_ar_lon[i],
                            cycle_ar_lat[i],
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
                fai_trigger_states = [False] * n_ar
                cycle_new_fai_trigger = False
                cycle_fai_trigger_record = None
                statuses_by_label = {}
                cycle_box_stats = []

                for lab in fai_trigger_cooldown_remaining:
                    if fai_trigger_cooldown_remaining[lab] > 0:
                        fai_trigger_cooldown_remaining[lab] -= 1

                for i in range(n_ar):
                    box_label = label[i]
                    area_frac = float(em_active_area_fraction(em_maps[i].data))
                    if np.isfinite(area_frac):
                        active_area_fraction_history[box_label].append(area_frac)
                        if len(active_area_fraction_history[box_label]) > 16:
                            del active_area_fraction_history[box_label][:-16]

                    fai_trigger_hit = _c5_fai_trigger_condition(
                        float(em_totals[i]),
                        cursor_t_mk,
                        cursor_em49,
                        fai_trigger_box_em_total_thresholds,
                        fai_trigger_t_mk_thresholds,
                        fai_trigger_em49_thresholds,
                    )
                    fai_history[box_label].append(
                        1.0 if fai_trigger_hit else 0.0
                    )
                    if len(fai_history[box_label]) > 10:
                        del fai_history[box_label][:-10]

                    recent_fai_trigger_vals = fai_history[box_label][-2:]
                    fai_trigger_ok = (
                        len(recent_fai_trigger_vals) >= 2
                        and all(v >= 0.5 for v in recent_fai_trigger_vals)
                    )
                    box_fai_trigger_cooldown = int(
                        fai_trigger_cooldown_remaining[box_label]
                    )
                    trigger_txt = "watch"
                    if i == focus_idx:
                        if fai_trigger_ok and box_fai_trigger_cooldown == 0:
                            fai_trigger_states[i] = True
                            cycle_new_fai_trigger = True
                            fai_trigger_cooldown_remaining[box_label] = max(
                                0, int(fai_trigger_cooldown_frames)
                            )
                            trigger_txt = "FAI_TRIGGER10"
                        elif fai_trigger_ok and box_fai_trigger_cooldown > 0:
                            fai_trigger_states[i] = True
                            trigger_txt = (
                                f"fai_trigger_cooldown({box_fai_trigger_cooldown},box={box_label})"
                            )
                    statuses_by_label[box_label] = trigger_txt

                    em_prev = float("nan")
                    em_curr = float(em_totals[i])
                    if em_history[box_label]:
                        em_prev = float(em_history[box_label][-1])
                    if np.isfinite(em_prev) and em_prev > 0:
                        em_ratio_txt = f"{em_curr / em_prev:.3f}"
                    else:
                        em_ratio_txt = "NA"
                    if np.isfinite(area_frac):
                        area_txt = f"{area_frac:.3f}"
                    else:
                        area_txt = "NA"
                    msg = (
                        f"Box {box_label} em_ratio={em_ratio_txt} "
                        f"active_area_frac={area_txt} -> {trigger_txt}"
                    )
                    print(msg)

                print(
                    f"Focus box by EM: {focus_label} "
                    f"(EM={float(em_totals[focus_idx]):.3e})"
                )
                if float(em_totals[focus_idx]) >= 5.0e48:
                    if not c5_sms_active:
                        maybe_send_sms("Waffle: C5+ level has been reached, possible flare.")
                        c5_sms_active = True
                else:
                    c5_sms_active = False

                focus_area_frac = float(em_active_area_fraction(em_maps[focus_idx].data))
                if np.isfinite(focus_area_frac):
                    print(
                        "Focus box active area fraction: "
                        f"{focus_area_frac:.3f}"
                    )
                else:
                    print("Focus box active area fraction: NA")

                cycle_box_stats = _make_fai_box_stats(
                    label[:n_ar],
                    arnum[:n_ar],
                    cycle_ar_lon[:n_ar],
                    cycle_ar_lat[:n_ar],
                    em_totals[:n_ar],
                    em_history,
                    active_area_fraction_history,
                    fai_trigger_states,
                    statuses_by_label,
                )
                if cycle_new_fai_trigger:
                    trigger_time_utc = datetime.datetime.strptime(
                        grouped_t_rec[0], "%Y-%m-%dT%H:%M:%SZ"
                    ).replace(tzinfo=datetime.timezone.utc)
                    trigger_time_local = convert_utc_to_timezone(
                        trigger_time_utc, timezone=timezone
                    )
                    estimated_realtime_utc = None
                    estimated_realtime_local = None
                    if (
                        (not realtime_mode)
                        and archive_trigger_realtime_delay_minutes is not None
                    ):
                        estimated_realtime_utc, estimated_realtime_local = _estimate_realtime_from_aia(
                            trigger_time_utc,
                            timezone=timezone,
                            delay_minutes=archive_trigger_realtime_delay_minutes,
                        )
                        print(
                            "FAI trigger estimated realtime: "
                            f"{estimated_realtime_local.isoformat()} "
                            f"({estimated_realtime_utc.isoformat()})"
                        )
                    maybe_send_sms(
                        f"Waffle: FAI trigger fired in box {focus_label}."
                    )
                    if (
                        not fai_trigger_times
                        or (
                            fai_trigger_times[-1].get("time")
                            if isinstance(fai_trigger_times[-1], dict)
                            else fai_trigger_times[-1]
                        ) != (
                            estimated_realtime_local
                            if estimated_realtime_local is not None
                            else trigger_time_local
                        )
                    ):
                        trigger_color = color_arr[label.index(focus_label)] if focus_label in label else "black"
                        fai_trigger_times.append(
                            {
                                "time": (
                                    estimated_realtime_local
                                    if estimated_realtime_local is not None
                                    else trigger_time_local
                                ),
                                "label": focus_label,
                                "color": trigger_color,
                                "linestyle": "--",
                            }
                        )
                        cycle_fai_trigger_record = (
                            trigger_time_utc,
                            trigger_time_local,
                            focus_label,
                            float(em_totals[focus_idx]),
                            cycle_box_stats,
                            estimated_realtime_utc,
                            estimated_realtime_local,
                        )
                    persistent_fai_active = True
                    persistent_fai_label = focus_label
                elif persistent_fai_active:
                    tracked_vals = fai_history.get(
                        persistent_fai_label or "", []
                    )
                    tracked_recent = tracked_vals[-2:]
                    tracked_avg = (
                        float(np.mean(tracked_recent))
                        if len(tracked_recent) >= 2
                        else float("nan")
                    )
                    if (
                        not np.isfinite(tracked_avg)
                        or tracked_avg < persistent_fai_release_avg
                    ):
                        persistent_fai_active = False
                        persistent_fai_label = None

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

                _save_runtime_stream_state(
                    data_folder,
                    label[:n_ar],
                    fai_history,
                    active_area_fraction_history,
                    em_history,
                    fai_trigger_cooldown_remaining,
                    persistent_fai_active,
                    persistent_fai_label,
                    region_source,
                    arnum,
                    ar_x,
                    ar_y,
                    ar_priority,
                    startup_boxes_refined,
                    last_box_recenter_ut,
                )

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
                    cycle_ar_lon,
                    cycle_ar_lat,
                    timezone=timezone,
                    em_cache=em_cache,
                    goes_plot_data=goes_plot_data,
                    trigger_states=fai_trigger_states,
                    trigger_times=fai_trigger_times,
                    alert_face_mode=("pretrigger" if persistent_fai_active else "watch"),
                    goes_anchor_time_local=goes_anchor_local,
                    archive_goes_offset_minutes=archive_goes_offset_minutes,
                )
                if print_phase_timing:
                    phase_times["em_goes_plot"] = time.time() - t_phase

                t_phase = time.time()
                write_detailed_analysis_pages(
                    detailed_analysis_folder, label[:n_ar], arnum[:n_ar]
                )
                def _render_detail_plot(i):
                    plot_detailed_em_result(
                        detailed_analysis_folder,
                        detail_aia_submaps[i],
                        em_maps[i],
                        xrsa_current,
                        xrsb_current,
                        arnum[i],
                        label[i],
                        i + 1,
                        os.path.join(total_em_folder, "total_em_" + str(arnum[i]) + ".csv"),
                        timezone=timezone,
                        em_cache=em_cache,
                        ar_color=color_arr[i],
                        goes_plot_data=goes_plot_data,
                    )

                plot_workers = resolve_detailed_plot_render_workers(
                    parallel_detailed_plot_renders,
                    detailed_plot_render_workers,
                    worker_count,
                    n_ar,
                )
                if plot_workers > 1:
                    try:
                        render_payloads = []
                        for i in range(n_ar):
                            render_payloads.append(
                                {
                                    "plots_folder": detailed_analysis_folder,
                                    "aia_submaps": [
                                        _serialize_map_for_process(m)
                                        for m in detail_aia_submaps[i]
                                    ],
                                    "em_map": _serialize_map_for_process(em_maps[i]),
                                    "arnum": arnum[i],
                                    "label": label[i],
                                    "box_index": i + 1,
                                    "file_name_em_csv": os.path.join(
                                        total_em_folder, "total_em_" + str(arnum[i]) + ".csv"
                                    ),
                                    "timezone": timezone,
                                    "ar_color": color_arr[i],
                                    "goes_plot_data": (
                                        list(goes_plot_data[0]),
                                        np.asarray(goes_plot_data[1], dtype=float),
                                        np.asarray(goes_plot_data[2], dtype=float),
                                    ),
                                }
                            )
                        with ProcessPoolExecutor(max_workers=plot_workers) as plot_executor:
                            futures = [
                                plot_executor.submit(
                                    render_detailed_em_result_process, payload
                                )
                                for payload in render_payloads
                            ]
                            for fut in as_completed(futures):
                                fut.result()
                    except Exception as exc:
                        print(
                            "Parallel detailed plot rendering failed; "
                            f"retrying serially. Error: {exc}"
                        )
                        for i in range(n_ar):
                            _render_detail_plot(i)
                else:
                    for i in range(n_ar):
                        _render_detail_plot(i)
                if print_phase_timing:
                    phase_times["detailed_analysis"] = time.time() - t_phase

                if cycle_fai_trigger_record is not None:
                    (
                        fai_trigger_time_utc,
                        fai_trigger_time_local,
                        fai_trigger_focus_label,
                        fai_trigger_focus_em,
                        fai_trigger_box_stats,
                        fai_trigger_estimated_realtime_utc,
                        fai_trigger_estimated_realtime_local,
                    ) = cycle_fai_trigger_record
                    save_flare_trigger_snapshot(
                        data_folder,
                        latest_plots_folder,
                        fai_trigger_time_utc,
                        fai_trigger_time_local,
                        fai_trigger_time_utc,
                        fai_trigger_time_local,
                        fai_trigger_focus_label,
                        fai_trigger_focus_em,
                        fai_trigger_box_stats,
                        cycle_box_stats,
                        alert_config={
                            "type": "fai_trigger",
                            "alert_count": 2,
                            "box_em_total_thresholds": list(fai_trigger_box_em_total_thresholds),
                            "t_mk_thresholds": list(fai_trigger_t_mk_thresholds),
                            "em49_thresholds": list(fai_trigger_em49_thresholds),
                            "consecutive_frames_required": 2,
                            "cooldown_frames": int(
                                fai_trigger_cooldown_frames
                            ),
                        },
                        copy_em_goes_plot=True,
                        snapshot_root_name="FAI Triggers",
                        snapshot_label="FAI trigger",
                        estimated_realtime_utc=fai_trigger_estimated_realtime_utc,
                        estimated_realtime_local=fai_trigger_estimated_realtime_local,
                    )

                print("Publish data...")
                t_phase = time.time()
                if publish_mode == "scp":
                    if local_publish_dir:
                        publish_local_files(
                            latest_plots_folder,
                            local_publish_dir,
                            suvi_top_wavelength=suvi_top_wavelength,
                            suvi_day_utc=start_time_series.astimezone(
                                datetime.timezone.utc
                            ).strftime("%Y-%m-%d"),
                            suvi_use_realtime=suvi_use_realtime,
                            control_page_href=(
                                external_control_url.strip()
                                if str(external_control_url).strip()
                                else "./control.html"
                            ),
                        )
                        publish_detailed_analysis_local(
                            detailed_analysis_folder,
                            local_publish_dir,
                            subdir=detailed_analysis_subdir,
                        )
                    ssh_scp_files(ssh_client, latest_plots_folder, destination_volume)
                    publish_detailed_analysis_remote(
                        ssh_client,
                        detailed_analysis_folder,
                        destination_volume,
                        subdir=detailed_analysis_subdir,
                    )
                    publish_remote_index_html(
                        ssh_client,
                        destination_volume,
                        suvi_top_wavelength=suvi_top_wavelength,
                        suvi_day_utc=start_time_series.astimezone(
                            datetime.timezone.utc
                        ).strftime("%Y-%m-%d"),
                        suvi_use_realtime=suvi_use_realtime,
                        control_page_href=(
                            external_control_url.strip()
                            if str(external_control_url).strip()
                            else "#"
                        ),
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
                        control_page_href=(
                            external_control_url.strip()
                            if str(external_control_url).strip()
                            else "./control.html"
                        ),
                    )
                    publish_detailed_analysis_local(
                        detailed_analysis_folder,
                        local_publish_dir,
                        subdir=detailed_analysis_subdir,
                    )
                if goes_available:
                    publish_runtime_status(
                        publish_mode,
                        publish_root,
                        ssh_client,
                        "ok",
                        "Online",
                        "Latest plots are up to date",
                        local_mirror_destination=local_publish_dir,
                    )
                else:
                    publish_runtime_status(
                        publish_mode,
                        publish_root,
                        ssh_client,
                        "warn",
                        "Waiting",
                        "AIA is online but GOES XRS is unavailable",
                        local_mirror_destination=local_publish_dir,
                    )
                last_successful_publish_unix = time.time()
                if not startup_sms_sent:
                    maybe_send_sms("Waffle: Waffle is up and running.")
                    startup_sms_sent = True
                if offline_sms_active:
                    maybe_send_sms("Waffle: Internet is back online.")
                offline_sms_active = False
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
                if realtime_mode:
                    latest_query_start = datetime.datetime.now(
                        datetime.timezone.utc
                    ) - timedelta(minutes=latency)
                    if latest_query_start > current_time_ut:
                        current_time_ut = latest_query_start
                print("No new data series. Wait 15 s.")
                time.sleep(15)
                time_diff = (
                    datetime.datetime.now(datetime.timezone.utc)
                    - start_time_ut_time_diff
                )
                time_diff = time_diff.seconds / 60
                continue
    finally:
        try:
            _save_runtime_stream_state(
                data_folder,
                label[:n_ar],
                fai_history,
                active_area_fraction_history,
                em_history,
                fai_trigger_cooldown_remaining,
                persistent_fai_active,
                persistent_fai_label,
                region_source,
                arnum,
                ar_x,
                ar_y,
                ar_priority,
                startup_boxes_refined,
                last_box_recenter_ut,
            )
        except Exception as exc:
            print(f"Failed to save waffle_v1p2 runtime state: {exc}")
        try:
            publish_runtime_status(
                publish_mode,
                publish_root,
                ssh_client,
                "warn",
                "Offline",
                "WAFFLE is not running",
                local_mirror_destination=local_publish_dir,
            )
        except Exception as exc:
            print(f"Failed to publish offline runtime status: {exc}")
        try:
            stop_global_control_tunnel(global_control_tunnel)
        except Exception as exc:
            print(f"Failed to stop global control tunnel: {exc}")
        if shared_executor is not None:
            shared_executor.shutdown(wait=True)
