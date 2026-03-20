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
    # - today=None -> realtime mode (start from current UTC time)
    # - today="YYYYMonDD" with query_start_time_utc=None -> midnight UTC of that day
    today = "2026Mar4"
    # Optional exact UTC start time for the JSOC query cursor.
    # Sentinel: None -> keep default behavior (UTC midnight of `today`).
    # Example: "2026-02-04T10:30:00Z"
    query_start_time_utc = None  # "2026-02-04T12:00:00Z"
    # Separate controls:
    # 1) today decides folder naming + default day anchor
    # 2) query_start_time_utc decides exact cursor start when provided
    if today is None:
        today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%b%d")

    if query_start_time_utc is None:
        # Default cursor at UTC midnight of `today`.
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

    arnum_top = [4367, 4366, 4358]  # active region numbers

    x_top = np.array([-200, 450, 800])  # heliographic X
    y_top = np.array([300, 250, 300])  # heliographic Y
    lat_top = (180 / np.pi) * np.arcsin(y_top / rsun)
    long_top = (180 / np.pi) * np.arcsin(
        x_top / (rsun * np.cos((np.pi / 180) * lat_top))
    )

    # lat_top=[23, -15, 21]# active region latitude in degrees - original line
    # long_top=[29, 15, 53]# active region longitude in degrees - orginal line

    # box_x_top = [200,200,100] # widths of boxes (in pixel units)
    # box_y_top = [100,100,200] # heights of boxes (in pixel units)
    # These positions are for the southern region
    label_bottom = ["D", "E", "F"]

    arnum_bottom = [4371, 4369, 4362]  # active region numbers

    x_bottom = np.array([-550, -400, 200])  # heliographic X
    y_bottom = np.array([-400, 0, -400])  # heliographic Y
    lat_bottom = (180 / np.pi) * np.arcsin(y_bottom / rsun)
    long_bottom = (180 / np.pi) * np.arcsin(
        x_bottom / (rsun * np.cos((np.pi / 180) * lat_bottom))
    )

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
    # SUVI top image wavelength (94 or 131) for generated website.
    suvi_top_wavelength = 131
    # In v1 this should follow replay date by default.
    suvi_use_realtime = True

    # Output publishing mode:
    # - 'local': publish latest outputs into a local folder (safe for local testing)
    # - 'scp': publish to remote WKU server using SCP
    publish_mode = "local"
    local_publish_dir = os.path.join(data_folder, "local_web")
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
            publish_mode=publish_mode,
            local_publish_dir=local_publish_dir,
            drms_series=drms_series,
            drms_segment=drms_segment,
            query_start_ut=query_start_ut,
            latency=10,
            time_step_minutes=3,
            worker_count=worker_count,
            print_phase_timing=print_phase_timing,
            suvi_top_wavelength=suvi_top_wavelength,
            suvi_use_realtime=suvi_use_realtime,
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
