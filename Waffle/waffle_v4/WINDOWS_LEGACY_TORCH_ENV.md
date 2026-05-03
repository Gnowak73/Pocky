# Windows Legacy Torch Setup

The legacy Windows launcher uses two conda environments so PyTorch runs in a
separate process from the main WAFFLE pipeline.

This avoids the Windows DLL conflicts that showed up when the full WAFFLE stack
and PyTorch were installed in the same environment.

## Environments

- `Waffle`: main WAFFLE environment.
  - Python 3.14.
  - Downloads, calibration, DEM/EM plots, website publishing, and all normal
    WAFFLE processing.
  - No PyTorch packages.
- `Waffle_Torch`: isolated PyTorch environment.
  - Python 3.11.
  - Only the CPU PyTorch wheel stack installed from
    `https://download.pytorch.org/whl/cpu`.
  - Torch versions are not pinned; pip resolves the current compatible wheels.

## How The Legacy Launcher Works

The executable with `legacy` in its filename does this:

1. Finds conda.
2. Creates or checks the base environment named `Waffle`.
3. Creates or checks the side environment named `Waffle_Torch`.
4. Starts WAFFLE from `Waffle`.
5. Tells WAFFLE to run neural-network inference through a persistent subprocess
   in `Waffle_Torch`.

The Torch worker stays open while WAFFLE runs, so the model loads once instead
of starting a new Python process for every prediction.

## Force Update

Set this before launching if the environments already exist and need to be
updated:

```powershell
$env:WAFFLE_FORCE_UPDATE = "1"
```

For a fully clean rebuild, remove both environments first:

```powershell
conda env remove -n Waffle -y
conda env remove -n Waffle_Torch -y
```

Then run the legacy launcher again.
