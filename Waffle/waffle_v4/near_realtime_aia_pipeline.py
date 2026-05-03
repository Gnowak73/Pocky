import warnings

warnings.filterwarnings("ignore")

import os
import datetime
import socket
import subprocess
import sys

# import dem_rml
import aux_functions
import numpy as np
from aiapy.calibrate.utils import get_correction_table as get_correction_table


def resolve_imminence_model_path(model_name_or_path: str) -> str:
    if not model_name_or_path:
        return ""
    if os.path.isabs(model_name_or_path):
        return model_name_or_path
    models_dir = os.path.join(os.path.dirname(__file__), "models")
    candidate = model_name_or_path
    if not candidate.endswith(".pt"):
        candidate = f"{candidate}.pt"
    return os.path.join(models_dir, candidate)


if __name__ == "__main__":
    # ------------------------------------------------------------
    # User settings
    # ------------------------------------------------------------
    # Realtime vs replay:
    # - today=None -> full realtime mode
    # - today="YYYYMonDD" -> replay mode for that day
    today = "2026Apr01"
    # Optional exact UTC start time for the JSOC query cursor.
    # None -> realtime cursor when today=None, otherwise UTC midnight of `today`.
    # Example: "2026-02-04T10:30:00Z"
    query_start_time_utc = "2026-04-01T13:40:00Z"

    # Target boxes: top row A/B/C, bottom row D/E/F.
    # Coordinates are heliographic X/Y in arcsec.
    region_source = "solarmonitor"  # "manual" or "solarmonitor"
    solarmonitor_type = "shmi_maglc"
    solarmonitor_indexnum = 1
    solarmonitor_refresh_on_utc_day_rollover = True
    solarmonitor_refresh_on_timezone_day_rollover = False

    arnum_top = [4046, 4044, 4043]
    x_top = [-450, -80, 830]
    y_top = [60, 320, 120]

    arnum_bottom = [4048, 4045, 4049]
    x_bottom = [-100, 200, 750]
    y_bottom = [-276, -180, -515]

    # Run behavior.
    duration_stream = None
    timezone = "US/Central"
    save_maps = False
    save_box_crops = False
    save_box_vis = False

    # Plot / website settings.
    publish_mode = "local"  # "scp" or "local"
    auto_start_local_web = True
    local_web_host = "127.0.0.1"
    local_web_port = 8003

    # Data source / cadence settings.
    drms_mode = "public"  # "nrt2" or "public"
    latency_minutes = 10
    time_step_minutes = 1
    n_pix_x = 500
    n_pix_y = 500
    # Minimum allowed center-to-center spacing between boxes, in image pixels.
    # Lower values allow more overlap. Defaults match current box size behavior.
    min_box_center_dx_pix = 500
    min_box_center_dy_pix = 500
    startup_box_recenter = True
    startup_box_recenter_arcsec = 200.0
    box_recenter_interval_hours = 2.0  # None/0 disables periodic recenter

    # Performance / diagnostics.
    worker_count = 10
    print_phase_timing = True

    # Website image settings.
    suvi_top_wavelength = 131  # 94 or 131
    suvi_use_realtime = True

    # Imminence model settings.
    imminence_alert_threshold = 0.70
    imminence_alert_count = 2
    imminence_alert_avg_threshold = 0.70
    imminence_small_area_alert_avg_threshold = 0.60
    imminence_require_positive_xrsb_derivative = True
    imminence_xrs_missing_em_ratio_threshold = 1.08
    imminence_alert_peak_threshold = None
    imminence_alert_delta_threshold = None
    imminence_alert_baseline_count = 5
    imminence_em_nondecrease_tolerance = 0.03
    imminence_min_active_area_fraction = 0.03
    imminence_large_area_fraction = 0.17
    imminence_large_area_alert_count = 2
    imminence_large_area_alert_avg_threshold = 0.85
    imminence_large_area_peak_threshold = 0.85
    imminence_large_area_em_ratio_threshold = 1.05
    imminence_alert_cooldown_frames = 15
    imminence_bin_factor = 4
    imminence_recenter = True

    # ------------------------------------------------------------
    # Derived settings and setup
    # ------------------------------------------------------------
    realtime_mode = today is None
    if realtime_mode:
        today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%b%d")

    if query_start_time_utc is None:
        if realtime_mode:
            # Realtime cursor: let stream_aia_data anchor to current UTC now.
            query_start_ut = None
        else:
            # Replay cursor: UTC midnight of the selected day.
            query_start_ut = datetime.datetime.strptime(today, "%Y%b%d").replace(
                tzinfo=datetime.timezone.utc
            )
    else:
        # Exact cursor override.
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
    data_folder = os.path.join(".", today)
    aux_functions.mkdir(data_folder)

    label_top = ["A", "B", "C"]
    x_top = np.array(x_top)
    y_top = np.array(y_top)
    label_bottom = ["D", "E", "F"]
    x_bottom = np.array(x_bottom)
    y_bottom = np.array(y_bottom)

    if region_source == "solarmonitor":
        solarmonitor_anchor_ut = (
            query_start_ut
            if query_start_ut is not None
            else datetime.datetime.now(datetime.timezone.utc)
        )
        date_yyyymmdd = solarmonitor_anchor_ut.astimezone(
            datetime.timezone.utc
        ).strftime("%Y%m%d")
        resolved = aux_functions.resolve_solarmonitor_boxes(
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
        ar_priority = np.array(resolved["ar_priority"], dtype=float)
        arnum_top = resolved["arnum"][:3]
        x_top = np.array(resolved["ar_x"][:3], dtype=float)
        y_top = np.array(resolved["ar_y"][:3], dtype=float)
        arnum_bottom = resolved["arnum"][3:6]
        x_bottom = np.array(resolved["ar_x"][3:6], dtype=float)
        y_bottom = np.array(resolved["ar_y"][3:6], dtype=float)
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
    elif region_source != "manual":
        raise ValueError("region_source must be either 'manual' or 'solarmonitor'")
    else:
        ar_priority = np.zeros(6, dtype=float)

    label = label_top + label_bottom
    arnum = arnum_top + arnum_bottom
    ar_x = np.concatenate((x_top, x_bottom))
    ar_y = np.concatenate((y_top, y_bottom))
    # Initial placeholders only. stream_aia_data() now recomputes true
    # Heliographic Stonyhurst lon/lat each cycle from these image-plane x/y
    # coordinates using the current AIA map WCS.
    ar_lon = np.zeros(len(arnum), dtype=float)
    ar_lat = np.zeros(len(arnum), dtype=float)

    box_crops_root = os.path.join(data_folder, "box_crops")
    box_vis_root = os.path.join(data_folder, "box_vis")
    local_publish_dir = os.path.join(data_folder, "local_web")
    # Main legacy trigger model now uses the GOES/FAI paper-feature checkpoint as primary.
    imminence_model_path = resolve_imminence_model_path("legacy_main_trigger_legacy.pt")
    if drms_mode == "nrt2":
        drms_series = "aia.lev1_nrt2"
        drms_segment = "image_lev1"
    elif drms_mode == "public":
        drms_series = "aia.lev1_euv_12s"
        drms_segment = "image"
    else:
        raise ValueError("drms_mode must be either 'nrt2' or 'public'")

    # Read correction table
    correction_table_path = os.path.join(
        ".", "tables", "aia_V10_20201119_190000_response_table.txt"
    )
    if os.path.exists(correction_table_path):
        correction_table = get_correction_table(source=correction_table_path)
    else:
        correction_table = get_correction_table()

    local_server_proc = None
    started_local_server = False

    def _is_port_in_use(host, port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            return s.connect_ex((host, port)) == 0

    try:
        if publish_mode == "local" and auto_start_local_web:
            aux_functions.mkdir(local_publish_dir)
            if _is_port_in_use(local_web_host, local_web_port):
                print(
                    f"Local web server not started: {local_web_host}:{local_web_port} already in use."
                )
            else:
                local_server_proc = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "http.server",
                        str(local_web_port),
                        "--bind",
                        local_web_host,
                    ],
                    cwd=local_publish_dir,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                started_local_server = True
                print(
                    f"Local website server started at http://{local_web_host}:{local_web_port}"
                )

        # Start AIA data stream
        aux_functions.stream_aia_data(
            duration_stream,
            data_folder,
            ar_lon,
            ar_lat,
            ar_x,
            ar_y,
            arnum,
            label,
            correction_table,
            timezone=timezone,
            n_pix_x=n_pix_x,
            n_pix_y=n_pix_y,
            save_maps=save_maps,
            save_box_crops=save_box_crops,
            box_crops_root=box_crops_root,
            save_box_vis=save_box_vis,
            box_vis_root=box_vis_root,
            publish_mode=publish_mode,
            local_publish_dir=local_publish_dir,
            drms_series=drms_series,
            drms_segment=drms_segment,
            query_start_ut=query_start_ut,
            latency=latency_minutes,
            time_step_minutes=time_step_minutes,
            worker_count=worker_count,
            print_phase_timing=print_phase_timing,
            suvi_top_wavelength=suvi_top_wavelength,
            suvi_use_realtime=suvi_use_realtime,
            imminence_model_path=imminence_model_path,
            imminence_state_model_path="",
            imminence_alert_threshold=imminence_alert_threshold,
            imminence_alert_count=imminence_alert_count,
            imminence_alert_avg_threshold=imminence_alert_avg_threshold,
            imminence_small_area_alert_avg_threshold=imminence_small_area_alert_avg_threshold,
            imminence_require_positive_xrsb_derivative=imminence_require_positive_xrsb_derivative,
            imminence_xrs_missing_em_ratio_threshold=imminence_xrs_missing_em_ratio_threshold,
            imminence_alert_peak_threshold=imminence_alert_peak_threshold,
            imminence_alert_delta_threshold=imminence_alert_delta_threshold,
            imminence_alert_baseline_count=imminence_alert_baseline_count,
            imminence_em_nondecrease_tolerance=imminence_em_nondecrease_tolerance,
            imminence_min_active_area_fraction=imminence_min_active_area_fraction,
            imminence_large_area_fraction=imminence_large_area_fraction,
            imminence_large_area_alert_count=imminence_large_area_alert_count,
            imminence_large_area_alert_avg_threshold=imminence_large_area_alert_avg_threshold,
            imminence_large_area_peak_threshold=imminence_large_area_peak_threshold,
            imminence_large_area_em_ratio_threshold=imminence_large_area_em_ratio_threshold,
            imminence_alert_cooldown_frames=imminence_alert_cooldown_frames,
            imminence_bin_factor=4,
            imminence_recenter=True,
            startup_box_recenter=startup_box_recenter,
            startup_box_recenter_arcsec=startup_box_recenter_arcsec,
            box_recenter_interval_hours=box_recenter_interval_hours,
            region_source=region_source,
            solarmonitor_type=solarmonitor_type,
            solarmonitor_indexnum=solarmonitor_indexnum,
            solarmonitor_refresh_on_utc_day_rollover=solarmonitor_refresh_on_utc_day_rollover,
            solarmonitor_refresh_on_timezone_day_rollover=solarmonitor_refresh_on_timezone_day_rollover,
            min_box_center_dx_pix=min_box_center_dx_pix,
            min_box_center_dy_pix=min_box_center_dy_pix,
            ar_priority=ar_priority,
        )
    finally:
        if started_local_server and local_server_proc is not None:
            local_server_proc.terminate()
            try:
                local_server_proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                local_server_proc.kill()
                local_server_proc.wait(timeout=3)
            print("Local website server stopped.")
    # aux_functions.stream_aia_data(duration_stream, data_folder, ar_lon, ar_lat, arnum, label, correction_table, timezone=timezone, n_pix_x=1000, n_pix_y=1000, save_maps=save_maps)
