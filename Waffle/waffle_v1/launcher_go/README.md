# WAFFLE Go Launcher

Cross-platform bootstrap launcher for WAFFLE.

## What it does

1. Finds `waffle_env.yml` and `near_realtime_aia_pipeline.py` in the WAFFLE folder.
2. Detects `conda`.
3. If missing, attempts Miniforge auto-install.
4. Creates/updates the `Waffle` conda env.
5. Runs `near_realtime_aia_pipeline.py`.

## Build

```bash
cd waffle_v1/launcher_go
./build.sh
```

## Run

Place the built binary in `waffle_v1` (or run from `waffle_v1/launcher_go` where parent has WAFFLE files):

```bash
./waffle-launcher-macos-arm64
```

Windows:

```powershell
.\waffle-launcher-windows-amd64.exe
```

## Notes

- Archive/realtime behavior is controlled by `near_realtime_aia_pipeline.py` variables.
- Set `WAFFLE_ENV_NAME` to override env name (default `Waffle`).
- Set `WAFFLE_FORCE_UPDATE=1` to force `conda env update` on each run.
- For macOS/Linux, Miniforge installs to `$HOME/miniforge3`.
- For Windows, Miniforge installs to `%USERPROFILE%\\miniforge3`.
