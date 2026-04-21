# Remote-starting WAFFLE with SSH/Paramiko

This folder now has two helper scripts for remote-starting WAFFLE v2. The first one, `Waffle/windows_remote_setup_info.ps1`, is run on the remote Windows computer. It does not install anything, does not require administrator permissions, and only prints the information and commands needed to connect from another computer. The second one, `Waffle/remote_start_waffle.py`, is run on the local/control computer. It uses Paramiko to SSH into the remote computer and start `near_realtime_aia_pipeline.py` through the remote `Waffle` conda environment.

Paramiko does not replace SSH. The remote computer must already be running OpenSSH Server. On the remote Windows computer, this can be checked with `Get-Service sshd`. If the service exists and says `Running` with display name `OpenSSH Server`, then the remote computer is ready for SSH connections. If `sshd` is missing or stopped, someone with the right permissions has to enable or start OpenSSH Server before Paramiko can work.

Start on the remote Windows computer. The easiest method is to double-click:

```text
Waffle\windows_remote_setup_info.cmd
```

The `.cmd` wrapper opens a terminal, runs `windows_remote_setup_info.ps1`, auto-passes the `Waffle\waffle_v2` path when it can find it, prints the commands you need, and then pauses so the window does not close. Copy the printed commands to the local/control computer.

If you prefer to run it manually, open PowerShell in the WAFFLE v2 directory if possible. That means the directory containing `near_realtime_aia_pipeline.py` and `waffle_env.yml`. From there, run:

```powershell
powershell -ExecutionPolicy Bypass -File ..\windows_remote_setup_info.ps1
```

That works when the repo layout is `Waffle\waffle_v2` and the script is located at `Waffle\windows_remote_setup_info.ps1`. If PowerShell is not currently in `waffle_v2`, pass the WAFFLE v2 path directly:

```powershell
powershell -ExecutionPolicy Bypass -File C:\Path\To\Pocky\Waffle\windows_remote_setup_info.ps1 -WafflePath "C:\Path\To\Pocky\Waffle\waffle_v2"
```

If the script cannot automatically find Conda, pass that too:

```powershell
powershell -ExecutionPolicy Bypass -File C:\Path\To\Pocky\Waffle\windows_remote_setup_info.ps1 -WafflePath "C:\Path\To\Pocky\Waffle\waffle_v2" -CondaPath "C:\Path\To\condabin\conda.bat"
```

The Windows helper prints the SSH server status, the username to try, the machine hostname, candidate IPv4 addresses, the Conda path, the WAFFLE v2 path, and then the exact commands to run from the local/control computer. The first command it prints is a plain SSH test. It will look like this:

```bash
ssh REMOTE_USERNAME@REMOTE_HOST_OR_IP "hostname"
```

Run that command from the local/control computer, not from the remote computer. This has to work before the Python helper will work. If it times out, the remote computer is not reachable from the local computer or the network/firewall is blocking it. If it says connection refused, SSH is not listening on the remote computer. If it says permission denied, the network path is working but the username, password, or SSH key is wrong.

After the plain SSH test works, run the second command printed by the Windows helper. That command starts WAFFLE directly through SSH and keeps the output attached to your local terminal. In placeholder form it looks like this:

```bash
ssh REMOTE_USERNAME@REMOTE_HOST_OR_IP "cd /d \"REMOTE_WAFFLE_V2_PATH\" && \"REMOTE_CONDA_PATH\" run --no-capture-output -n Waffle python near_realtime_aia_pipeline.py"
```

This attached SSH command is the most important test. It proves that the remote WAFFLE folder path, remote Conda path, environment name, Python imports, and WAFFLE startup all work. If this command fails, fix that failure first. The Paramiko helper runs the same kind of command, so it will not solve a broken Conda path or missing package by itself.

Once the attached SSH command works, use the Python helper from the local/control computer. The Windows helper prints a full command, but the generic form is:

```bash
python Waffle/remote_start_waffle.py --host REMOTE_HOST_OR_IP --user REMOTE_USERNAME --password --remote-root "REMOTE_WAFFLE_V2_PATH" --conda "REMOTE_CONDA_PATH"
```

By default, `remote_start_waffle.py` prompts for the SSH password, connects to the remote machine, prints the remote command it is running, and streams WAFFLE output back to the local terminal. This attached mode is the safest mode because any Python, Conda, Torch, SunPy, or WAFFLE error stays visible.

The helper also has a connection-only test mode. This runs `hostname` remotely and does not start WAFFLE:

```bash
python Waffle/remote_start_waffle.py --host REMOTE_HOST_OR_IP --user REMOTE_USERNAME --password --remote-root "REMOTE_WAFFLE_V2_PATH" --conda "REMOTE_CONDA_PATH" --test
```

If the SSH server uses a nonstandard port, add `--port PORT_NUMBER`. If using an SSH private key instead of a password, use `--key PATH_TO_PRIVATE_KEY` and omit `--password`:

```bash
python Waffle/remote_start_waffle.py --host REMOTE_HOST_OR_IP --user REMOTE_USERNAME --key PATH_TO_PRIVATE_KEY --remote-root "REMOTE_WAFFLE_V2_PATH" --conda "REMOTE_CONDA_PATH"
```

If the remote `Waffle` conda environment already exists but needs to be updated before starting, add `--update-env`. On Windows, the helper uses `waffle_env_windows.yml` when that file exists; otherwise it falls back to `waffle_env.yml`:

```bash
python Waffle/remote_start_waffle.py --host REMOTE_HOST_OR_IP --user REMOTE_USERNAME --password --remote-root "REMOTE_WAFFLE_V2_PATH" --conda "REMOTE_CONDA_PATH" --update-env
```

If the remote environment name is not `Waffle`, add `--env ENV_NAME`. The default is `Waffle`, matching the env yml files.

Only use detached/background mode after attached mode works. Background mode uses PowerShell `Start-Process` on the remote computer, sends the start command, and returns without keeping WAFFLE output attached:

```bash
python Waffle/remote_start_waffle.py --host REMOTE_HOST_OR_IP --user REMOTE_USERNAME --password --remote-root "REMOTE_WAFFLE_V2_PATH" --conda "REMOTE_CONDA_PATH" --background
```

Background mode is useful once the setup is stable, but it is worse for debugging because errors are not streamed back the same way. First make the normal attached command work.

The local/control computer needs Python with Paramiko installed. It does not need the WAFFLE conda environment. WAFFLE runs on the remote computer. To install Paramiko locally, use one of:

```bash
python -m pip install paramiko
```

```bash
conda install -c conda-forge paramiko
```

The two remote paths matter. `REMOTE_WAFFLE_V2_PATH` is the Windows path to the folder containing `near_realtime_aia_pipeline.py`. `REMOTE_CONDA_PATH` is the full Windows path to `conda.bat`, usually inside a Miniforge, Miniconda, or Anaconda `condabin` folder. Use the full `conda.bat` path. Do not rely on just `conda`, because SSH sessions often have a different PATH from the regular desktop terminal.

Do not commit real usernames, passwords, internal IP addresses, SSH private keys, or sensitive machine-specific paths. The helper scripts take those values as command-line arguments so they do not have to be stored in the repo.

Useful commands to run on the remote Windows computer are:

```powershell
Get-Service sshd
ipconfig
whoami
where conda
```

Useful remote Conda checks are:

```bat
"REMOTE_CONDA_PATH" env list
"REMOTE_CONDA_PATH" run -n Waffle python -c "import torch; print(torch.__version__); print(torch.__file__)"
"REMOTE_CONDA_PATH" run -n Waffle python -c "import sunpy, aiapy, paramiko, torch; print('imports ok')"
```

The expected workflow is: run `windows_remote_setup_info.ps1` on the remote Windows computer, run the printed `ssh REMOTE_USERNAME@REMOTE_HOST_OR_IP "hostname"` command from the local/control computer, run the printed attached WAFFLE SSH command from the local/control computer, then use `remote_start_waffle.py` for normal remote starts.


For the WAFFLE v2 launcher specifically, Windows uses `waffle_env_windows.yml`, which pins `python=3.12`. macOS and Linux continue to use `waffle_env.yml`, so their Python version is unchanged.
