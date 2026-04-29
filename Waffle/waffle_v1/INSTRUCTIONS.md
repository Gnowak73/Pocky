# WAFFLE v1 Instructions

## What WAFFLE v1 does

`waffle_v1` downloads AIA data, computes EM maps, tracks six target boxes, and publishes the latest plots either:

- to the WKU website over SCP, or
- to a local folder with a small local web server.

The main entry point is:

- `Waffle/waffle_v1/near_realtime_aia_pipeline.py`

## The normal way to start it

Use the launcher for the standard workflow. It handles Conda setup and starts the pipeline.

Launcher docs:

- `Waffle/waffle_v1/launcher_go/README.md`

Typical run:

macOS/Linux:

```bash
./waffle-launcher-macos-arm64
```

Windows:

```powershell
.\waffle-launcher-windows-amd64.exe
```

The launcher will:

1. find `waffle_env.yml`
2. create or update the `Waffle` Conda environment
3. run `near_realtime_aia_pipeline.py`

On a normal run, the launcher already handles environment creation and updates as needed.

To force an environment update on the next launcher run:

macOS/Linux:

```bash
WAFFLE_FORCE_UPDATE=1 ./waffle-launcher-macos-arm64
```

Windows PowerShell:

```powershell
$env:WAFFLE_FORCE_UPDATE = "1"
.\waffle-launcher-windows-amd64.exe
```

## Conda, manual Python, and the packaged launcher

There are two supported ways to start `waffle_v1`.

### Option 1: use the packaged launcher

Use the built launcher binary for:

- automatic Conda detection
- automatic environment creation/update
- a simpler start command

Typical examples:

macOS/Linux:

```bash
./waffle-launcher-macos-arm64
```

Windows:

```powershell
.\waffle-launcher-windows-amd64.exe
```

### Option 2: run it manually with Python

Use manual Python when:

- explicit control over the environment
- explicit control over the Python executable
- easier debugging when imports or paths fail

Typical manual run:

```bash
conda activate Waffle
cd /path/to/Pocky/Waffle/waffle_v1
python near_realtime_aia_pipeline.py
```

You can also run the environment Python directly instead of relying on shell activation.

Example:

```bash
/full/path/to/conda/envs/Waffle/bin/python near_realtime_aia_pipeline.py
```

### When to use each one

Use the launcher if:

- you are just trying to run WAFFLE
- you want the packaged/distribution-style workflow
- you do not want to manage Conda details manually

Use manual Python if:

- you are changing code
- you are testing imports or environment problems
- you need to know exactly which interpreter is running

### Conda environment notes

`waffle_v1` expects the `Waffle` Conda environment unless you intentionally override it.

The launcher will normally create/update that environment from:

- `Waffle/waffle_v1/waffle_env.yml`

If you need to create the environment manually, run:

```bash
cd /path/to/Pocky/Waffle/waffle_v1
conda env create -f waffle_env.yml
```

If the environment already exists and you need to update it from the YAML file, run:

```bash
cd /path/to/Pocky/Waffle/waffle_v1
conda env update -n Waffle -f waffle_env.yml --prune
```

If you are running manually and Conda is already working, check it with:

```bash
conda env list
conda activate Waffle
python -V
```

If imports fail in manual mode, check:

- wrong environment activated
- wrong Python on `PATH`
- incomplete Conda environment

If the launcher fails, fix the environment first. If needed, force an environment update and run it again.

## Before you start

Open `Waffle/waffle_v1/near_realtime_aia_pipeline.py` and check these settings.

### 1. Realtime vs replay

```python
today = None
query_start_time_utc = None
```

- `today = None` means realtime mode
- `today = "2026Feb04"` means replay mode for that day
- `query_start_time_utc` can override the exact UTC start time if needed

### 2. Target boxes

The six boxes are defined in two groups:

- top row: `A`, `B`, `C`
- bottom row: `D`, `E`, `F`

Relevant variables:

```python
arnum_top = [...]
x_top = np.array([...])
y_top = np.array([...])

arnum_bottom = [...]
x_bottom = np.array([...])
y_bottom = np.array([...])
```

If a NOAA region number does not exist yet, use a placeholder like `1`.

### 3. Publishing mode

```python
publish_mode = "scp"
local_publish_dir = os.path.join(data_folder, "local_web")
```

Use:

- `publish_mode = "scp"` to publish to the WKU website
- `publish_mode = "local"` for local testing only

If you use local mode, the script can also start a local web server:

```python
auto_start_local_web = True
local_web_host = "127.0.0.1"
local_web_port = 8000
```

### 4. DRMS source

```python
drms_mode = "nrt2"
```

Options:

- `"nrt2"` = near-real-time source
- `"public"` = public JSOC source

### 5. Runtime length

```python
duration_stream = 480 by default.
```

This is in minutes.

## Running it manually

If you do not want to use the launcher, run it directly from the `Waffle` Conda environment.

```bash
conda activate Waffle
cd /path/to/Pocky/Waffle/waffle_v1
python near_realtime_aia_pipeline.py
```

## What you should expect

When it is running, the terminal should show repeated cycles like:

- data query/download
- EM computation
- plotting
- publishing
- `Elapsed time: ... s`

Repeated `Elapsed time` lines mean the loop is running.

## Stopping and restarting

Stop with:

```text
Ctrl+C
```

Then start it again with the same launcher or Python command.

Notes:

- `waffle_v1` keeps prior EM curve history through the `total_em/*.csv` files
- after restart, plots can pick up those old EM values again from disk
- this is plot continuity, not full in-memory model-state resume

## Changing box locations while running

1. stop the script with `Ctrl+C`
2. edit `near_realtime_aia_pipeline.py`
3. save the file
4. start the script again

Do not edit box definitions and assume the running process will reload them automatically.

## Common issues

### “No new data series”

A few of these in a row can happen. That is normal.

If it keeps happening for a long stretch, stop and restart the run.

### Local web server port already in use

If you run local mode and see that port `8000` is already in use, either:

- stop the process using that port, or
- change `local_web_port` in `near_realtime_aia_pipeline.py`

### SCP publishing fails

If `publish_mode = "scp"` is set and publishing fails, switch temporarily to:

```python
publish_mode = "local"
```

Use local mode to confirm the pipeline is working before debugging SSH/SCP.

### Conda environment problems

If the launcher is not enough and the environment is clearly broken, force an update:

macOS/Linux:

```bash
WAFFLE_FORCE_UPDATE=1 ./waffle-launcher-macos-arm64
```

Windows PowerShell:

```powershell
$env:WAFFLE_FORCE_UPDATE = "1"
.\waffle-launcher-windows-amd64.exe
```

## Files worth knowing

- `Waffle/waffle_v1/near_realtime_aia_pipeline.py` — main runtime config and entry point
- `Waffle/waffle_v1/aux_functions.py` — stream logic, plotting, publishing
- `Waffle/waffle_v1/launcher_go/README.md` — launcher behavior
- `Waffle/waffle_v1/waffle_env.yml` — Conda environment definition

## Short version

If you just want the minimal workflow:

1. edit `near_realtime_aia_pipeline.py`
2. set box positions and publish mode
3. run the launcher
4. watch for repeated `Elapsed time` output
5. stop with `Ctrl+C` when you need to change anything
