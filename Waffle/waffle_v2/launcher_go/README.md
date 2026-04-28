# WAFFLE Go Launcher

Cross-platform bootstrap launcher for WAFFLE.

## What it does

1. Finds the env yml and `near_realtime_aia_pipeline.py` in the WAFFLE folder.
   - Normal Windows/macOS/Linux launchers use `waffle_env.yml`.
   - Windows launchers with `legacy` in the executable name use the legacy Windows setup: a no-Torch base WAFFLE env plus an isolated pip-installed Torch worker env. `waffle_env_windows_legacy_base.yml` documents the base WAFFLE stack.
2. Detects `conda`.
3. If missing, attempts Miniforge auto-install.
4. Creates/updates the `Waffle` conda env.
5. Runs `near_realtime_aia_pipeline.py`.

## Build

```bash
cd waffle_v2/launcher_go
./build.sh
```

## Run

Run the built binary from `waffle_v2/launcher_go/dist`:

```bash
./waffle-launcher-macos-arm64
```

Windows normal:

```powershell
.\waffle-launcher-windows-amd64.exe
```

Windows legacy:

```powershell
.\waffle-launcher-windows-amd64-legacy.exe
```

## Notes

- Archive/realtime behavior is controlled by `near_realtime_aia_pipeline.py` variables.
- Set `WAFFLE_ENV_NAME` to override env name (default `Waffle`).
- Set `WAFFLE_FORCE_UPDATE=1` to force `conda env update` on each run.
- For macOS/Linux, Miniforge installs to `$HOME/miniforge3`.
- For Windows, Miniforge installs to `%USERPROFILE%\\miniforge3`.

Legacy Windows also pins NumPy to `1.26.4` because the pinned Torch 2.2.1/bqplot stack is not clean with the newest NumPy 2.4 builds.
