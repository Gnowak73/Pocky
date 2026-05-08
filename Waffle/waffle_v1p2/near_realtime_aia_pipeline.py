import warnings

warnings.filterwarnings("ignore")

import os

import aux_functions
import numpy as np


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
    query_start_time_utc = "2026-04-01T13:25:00Z"

    # Target boxes: top row A/B/C, bottom row D/E/F.
    # Coordinates are heliographic X/Y in arcsec.
    region_source = "solarmonitor"  # "manual" or "solarmonitor"
    solarmonitor_refresh_on_utc_day_rollover = True
    solarmonitor_refresh_on_timezone_day_rollover = False

    arnum_top = [4046, 4044, 4043]
    x_top = [-450, -80, 830]
    y_top = [60, 320, 120]

    arnum_bottom = [4048, 4045, 4049]
    x_bottom = [-100, 200, 750]
    y_bottom = [-276, -180, -515]

    # SMS Alerts
    send_sms = True

    # Run behavior.
    duration_stream = None
    timezone = "US/Central"
    save_maps = False
    save_box_crops = False

    # Plot / website settings.
    publish_mode = "local"  # "scp" or "local"
    local_web_host = "127.0.0.1"
    local_web_port = 8003
    enable_global_control = True
    global_control_provider = "cloudflared"  # "auto", "ngrok", or "cloudflared"
    global_control_config_path = aux_functions.default_global_control_config_path()
    external_control_url = ""
    detailed_analysis_subdir = "detailed_analysis"
    control_auth_user = "waffle"
    control_auth_password = "waffle"
    ssh_host = "physics.wku.edu"
    ssh_user = "emslie"
    ssh_password = "waffle"
    remote_publish_dir = "/server/html/waffle_2/"

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
    download_timeout_sec = 30.0
    download_retry_delay_sec = 10.0
    download_retry_attempts = 2
    startup_box_recenter = True
    startup_box_recenter_arcsec = 200.0
    box_recenter_interval_hours = 2.0  # None/0 disables periodic recenter

    # Performance / diagnostics.
    worker_count = 10
    parallel_full_disk_render = True
    full_disk_render_workers = None
    # Detailed-analysis rendering:
    # - False -> render detailed plots serially
    # - True  -> allow parallel rendering
    parallel_detailed_plot_renders = True
    # Number of workers for detailed-analysis plot rendering.
    # None -> auto-resolve inside aux_functions.py from worker_count / box count.
    detailed_plot_render_workers = None
    print_phase_timing = True

    # Website image settings.
    suvi_top_wavelength = 131  # 94 or 131
    suvi_use_realtime = True

    # FAI-trigger-only settings.
    fai_trigger_cooldown_frames = 15
    fai_trigger_box_em_total_thresholds = [5.0e47, 1.0e48, 5.0e48, 9.0e48]
    fai_trigger_t_mk_thresholds = [9.3, 9.0, 10.5, 12.0]
    fai_trigger_em49_thresholds = [0.015, 0.015, 0.05, 0.1]
    trigger_realtime_delay_minutes = 2.5

    # ------------------------------------------------------------
    # Derived settings and setup
    # ------------------------------------------------------------
    realtime_mode, today, query_start_ut = (
        aux_functions.resolve_run_day_and_query_start(today, query_start_time_utc)
    )
    data_folder = os.path.join(".", today)
    aux_functions.mkdir(data_folder)

    label_top = ["A", "B", "C"]
    label_bottom = ["D", "E", "F"]
    resolved_layout = aux_functions.resolve_initial_region_layout(
        region_source=region_source,
        query_start_ut=query_start_ut,
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
    ar_priority = resolved_layout["ar_priority"]
    arnum_top = resolved_layout["arnum_top"]
    x_top = resolved_layout["x_top"]
    y_top = resolved_layout["y_top"]
    arnum_bottom = resolved_layout["arnum_bottom"]
    x_bottom = resolved_layout["x_bottom"]
    y_bottom = resolved_layout["y_bottom"]

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
    local_publish_dir = os.path.join(data_folder, "local_web")
    box_control_path = aux_functions.default_box_control_path(local_publish_dir)
    aux_functions.write_box_control_file(
        box_control_path,
        aux_functions.build_box_control_config(
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
    drms_series, drms_segment = aux_functions.resolve_drms_source(drms_mode)
    correction_table = aux_functions.load_aia_correction_table()
    local_server_proc = None
    global_control_tunnel = None
    global_control_cfg = aux_functions.load_global_control_config(
        global_control_config_path
    )
    ngrok_authtoken = str(global_control_cfg.get("ngrok_authtoken", "") or "").strip()
    if ngrok_authtoken:
        if not external_control_url:
            external_control_url = str(
                global_control_cfg.get("external_control_url", "") or ""
            ).strip()
    else:
        # Free temporary tunnels must publish a fresh URL every run.
        external_control_url = ""

    try:
        if publish_mode == "local" or enable_global_control:
            local_server_proc = aux_functions.start_local_publish_server(
                local_publish_dir,
                local_web_host,
                local_web_port,
                control_config_path=box_control_path,
                control_auth_user=control_auth_user,
                control_auth_password=control_auth_password,
            )
        if enable_global_control:
            try:
                global_control_tunnel = aux_functions.start_global_control_tunnel(
                    local_web_port,
                    provider=global_control_provider,
                    ngrok_authtoken=ngrok_authtoken,
                    external_control_url=external_control_url,
                )
                external_control_url = aux_functions.resolve_global_control_url(
                    global_control_tunnel, external_control_url
                )
                if external_control_url:
                    print(f"Global control link resolved: {external_control_url}")
                else:
                    print("Global control link unresolved for this run.")
            except Exception as exc:
                global_control_tunnel = None
                if not ngrok_authtoken:
                    external_control_url = ""
                print(f"Global control tunnel startup failed: {exc}")

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
            publish_mode=publish_mode,
            local_publish_dir=local_publish_dir,
            external_control_url=external_control_url,
            enable_global_control=enable_global_control,
            global_control_provider=global_control_provider,
            local_web_port=local_web_port,
            ngrok_authtoken=ngrok_authtoken,
            global_control_tunnel=global_control_tunnel,
            detailed_analysis_subdir=detailed_analysis_subdir,
            parallel_detailed_plot_renders=parallel_detailed_plot_renders,
            detailed_plot_render_workers=detailed_plot_render_workers,
            drms_series=drms_series,
            drms_segment=drms_segment,
            query_start_ut=query_start_ut,
            latency=latency_minutes,
            time_step_minutes=time_step_minutes,
            worker_count=worker_count,
            print_phase_timing=print_phase_timing,
            parallel_full_disk_render=parallel_full_disk_render,
            full_disk_render_workers=full_disk_render_workers,
            suvi_top_wavelength=suvi_top_wavelength,
            suvi_use_realtime=suvi_use_realtime,
            fai_trigger_cooldown_frames=fai_trigger_cooldown_frames,
            fai_trigger_box_em_total_thresholds=fai_trigger_box_em_total_thresholds,
            fai_trigger_t_mk_thresholds=fai_trigger_t_mk_thresholds,
            fai_trigger_em49_thresholds=fai_trigger_em49_thresholds,
            startup_box_recenter=startup_box_recenter,
            startup_box_recenter_arcsec=startup_box_recenter_arcsec,
            box_recenter_interval_hours=box_recenter_interval_hours,
            download_timeout_sec=download_timeout_sec,
            download_retry_delay_sec=download_retry_delay_sec,
            download_retry_attempts=download_retry_attempts,
            archive_trigger_realtime_delay_minutes=trigger_realtime_delay_minutes,
            send_sms=send_sms,
            ssh_host=ssh_host,
            ssh_user=ssh_user,
            ssh_password=ssh_password,
            destination_volume=remote_publish_dir,
            region_source=region_source,
            solarmonitor_refresh_on_utc_day_rollover=solarmonitor_refresh_on_utc_day_rollover,
            solarmonitor_refresh_on_timezone_day_rollover=solarmonitor_refresh_on_timezone_day_rollover,
            min_box_center_dx_pix=min_box_center_dx_pix,
            min_box_center_dy_pix=min_box_center_dy_pix,
            ar_priority=ar_priority,
        )
    finally:
        aux_functions.stop_global_control_tunnel(global_control_tunnel)
        aux_functions.stop_local_publish_server(local_server_proc)
