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

if __name__ == "__main__":
    # Define folder where to save the data.
    # - today=None -> full realtime mode (default WAFFLE realtime source + current UTC cursor)
    # - today="YYYYMonDD" -> replay mode for that day
    today = "2026Apr01"
    # Optional exact UTC start time for the JSOC query cursor.
    # Sentinel: None -> realtime cursor when today=None, otherwise UTC midnight of `today`.
    # Example: "2026-02-04T10:30:00Z"
    query_start_time_utc = "2026-04-01T07:30:00Z"
    # Separate controls:
    # 1) today selects realtime vs replay mode and folder naming
    # 2) query_start_time_utc optionally overrides the cursor start
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
    data_folder = os.path.join(".", today)
    aux_functions.mkdir(data_folder)

    # AR parameters, top three first, then bottom three
    rsun = 1000  # radius of solar disk in arcsec
    label_top = ["A", "B", "C"]

    arnum_top = [4046, 4044, 4043]  # active region numbers

    x_top = np.array([-250, 250, 830])  # heliographic X
    y_top = np.array([200, 240, 120])  # heliographic Y
    lat_top = (180 / np.pi) * np.arcsin(y_top / rsun)
    long_top = (180 / np.pi) * np.arcsin(
        x_top / (rsun * np.cos((np.pi / 180) * lat_top))
    )

    # Direct Heliographic Stonyhurst degrees for the same regions.
    # Kept here for reference; WAFFLE currently uses the projected X/Y path above.
    # lat_top = np.array([5, 20, 14], dtype=float)
    # long_top = np.array([-31, 4, 27], dtype=float)

    # lat_top=[23, -15, 21]# active region latitude in degrees - original line
    # long_top=[29, 15, 53]# active region longitude in degrees - orginal line

    # box_x_top = [200,200,100] # widths of boxes (in pixel units)
    # box_y_top = [100,100,200] # heights of boxes (in pixel units)
    # These positions are for the southern region
    label_bottom = ["D", "E", "F"]

    arnum_bottom = [4048, 4045, 4049]  # active region numbers

    x_bottom = np.array([-100, 200, 750])  # heliographic X
    y_bottom = np.array([-276, -180, -515])  # heliographic Y
    lat_bottom = (180 / np.pi) * np.arcsin(y_bottom / rsun)
    long_bottom = (180 / np.pi) * np.arcsin(
        x_bottom / (rsun * np.cos((np.pi / 180) * lat_bottom))
    )

    # Direct Heliographic Stonyhurst degrees for the same regions.
    # Kept here for reference; WAFFLE currently uses the projected X/Y path above.
    # lat_bottom = np.array([-16, -15, -31], dtype=float)
    # long_bottom = np.array([-53, -23, -27], dtype=float)

    # lat_bottom=[2, -28, -10]# active region latitude in degrees - BA
    # long_bottom=[0, 15, 75]# active region longitude in degrees - BA

    # box_x_bottom = [200,200,100] # widths of boxes (in arcsec units)
    # box_y_bottom = [100,100,200] # heights of boxes (in arcsec units)
    label = label_top + label_bottom
    arnum = arnum_top + arnum_bottom
    ar_lat = np.concatenate((lat_top, lat_bottom))
    ar_lon = np.concatenate((long_top, long_bottom))

    # box_x = box_x_top + box_x_bottom
    # box_y = box_y_top + box_y_bottom

    # arnum  = [3624, 3626, 3622, 1, 0, 3620]
    # ar_lat = [15, 11, 11, -15, +15, -8] #North and South
    # ar_lon = [-30, 33, 53, -15, -55, 66] #West and East
    # #If boxes are not used, move to ~,80

    # Normalization of light curves: multiply by 1000^2 / (w*h) [ or 500^2 / (w * h ) ]

    # Duration of the current session of the data stream
    duration_stream = 480  # minutes

    # Timezone with respect to which the times are expressed in the plots
    timezone = "US/Central"  #'US/Mountain'#'US/Alaska'#

    # Boolean: if True, the fits files of the downloaded AIA maps and of the EM maps that are computed from the AIA data are saved.
    save_maps = False
    # Boolean: if True, save only timestamped cropped box FITS (plus EM) and still clean up full-disk downloads.
    save_box_crops = False
    box_crops_root = os.path.join(data_folder, "box_crops")
    # Boolean: if True, save the exact per-box visibility frame computed for NN inference.
    save_box_vis = False
    box_vis_root = os.path.join(data_folder, "box_vis")
    # SUVI top image wavelength (94 or 131) for generated website.
    suvi_top_wavelength = 131
    # In v1 this should follow replay date by default.
    suvi_use_realtime = True

    # Output publishing mode:
    # - 'local': publish latest outputs into a local folder (safe for local testing)
    # - 'scp': publish to remote WKU server using SCP
    publish_mode = "local"
    local_publish_dir = os.path.join(data_folder, "local_web")
    imminence_model_path = os.path.join(
        os.path.dirname(__file__), "models", "empeak_c5_pre30_b51020.pt"
    )
    imminence_alert_threshold = 0.80
    imminence_alert_count = 2
    imminence_alert_avg_threshold = 0.80
    imminence_alert_peak_threshold = None
    imminence_alert_delta_threshold = None
    imminence_alert_baseline_count = 5
    imminence_em_nondecrease_tolerance = None
    imminence_alert_cooldown_frames = 10
    # Local website auto-server controls (used only when publish_mode == "local").
    auto_start_local_web = True
    local_web_host = "127.0.0.1"
    local_web_port = 8000
    # Performance diagnostics + calibration parallelism
    print_phase_timing = True
    worker_count = 10

    # DRMS query mode:
    # - "nrt2"   -> near-real-time series used on WKU environment
    # - "public" -> public JSOC series
    drms_mode = "public"
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
            arnum,
            label,
            correction_table,
            timezone=timezone,
            n_pix_x=500,
            n_pix_y=500,
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
            latency=10,
            time_step_minutes=1,
            worker_count=worker_count,
            print_phase_timing=print_phase_timing,
            suvi_top_wavelength=suvi_top_wavelength,
            suvi_use_realtime=suvi_use_realtime,
            imminence_model_path=imminence_model_path,
            imminence_alert_threshold=imminence_alert_threshold,
            imminence_alert_count=imminence_alert_count,
            imminence_alert_avg_threshold=imminence_alert_avg_threshold,
            imminence_alert_peak_threshold=imminence_alert_peak_threshold,
            imminence_alert_delta_threshold=imminence_alert_delta_threshold,
            imminence_alert_baseline_count=imminence_alert_baseline_count,
            imminence_em_nondecrease_tolerance=imminence_em_nondecrease_tolerance,
            imminence_alert_cooldown_frames=imminence_alert_cooldown_frames,
            imminence_bin_factor=4,
            imminence_recenter=True,
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
