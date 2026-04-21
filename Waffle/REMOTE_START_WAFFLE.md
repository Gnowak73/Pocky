# Remote-starting WAFFLE from another computer

The remote-start setup has two parts. The remote Windows computer must already be running OpenSSH Server, and the local/control computer uses SSH or the Python Paramiko helper in this folder to run the WAFFLE start command. Paramiko does not replace OpenSSH Server; it only connects to it.

The useful files are:

```text
Waffle/REMOTE_START_WAFFLE.md
Waffle/remote_start_waffle.py
Waffle/windows_remote_setup_info.ps1
```

`remote_start_waffle.py` is the local Python helper. It connects to the remote computer and starts `near_realtime_aia_pipeline.py` through the remote `Waffle` conda environment. `windows_remote_setup_info.ps1` is the script to run on the remote Windows computer. It does not install anything and does not need administrator rights. It checks what it can see, then prints the exact SSH and Python commands to run from the local/control computer.

Start on the remote Windows computer. Open PowerShell in the WAFFLE v2 folder if possible, meaning the folder that contains `near_realtime_aia_pipeline.py` and `waffle_env.yml`. Then run:

```powershell
powershell -ExecutionPolicy Bypass -File ..\windows_remote_setup_info.ps1
```

If the script is not one directory above the current folder, give PowerShell the actual path to `windows_remote_setup_info.ps1`. If you are not currently inside the WAFFLE v2 folder, pass the path explicitly:

```powershell
powershell -ExecutionPolicy Bypass -File C:\Path\To\Pocky\Waffle\windows_remote_setup_info.ps1 -WafflePath "C:\Path\To\Pocky\Waffle\waffle_v2"
```

The Windows script prints the OpenSSH Server status, the Windows username to try, candidate IPv4 addresses, the conda path if it can find one, the WAFFLE v2 path, and then three commands to run from the local/control computer. The first command is a plain SSH test, for example in placeholder form:

```bash
ssh REMOTE_USERNAME@REMOTE_HOST_OR_IP "hostname"
```

Run that from the local/control computer first. If that fails, do not use Paramiko yet. Fix the SSH connection first. A timeout means the machine is not reachable or the network/firewall is blocking it. A refused connection means SSH is not listening. A permission error means the username/password/key is wrong.

Once the plain SSH test works, run the second command printed by the Windows script. That command starts WAFFLE directly through SSH and keeps it attached to your terminal. It will look like this in placeholder form:

```bash
ssh REMOTE_USERNAME@REMOTE_HOST_OR_IP "cd /d \"REMOTE_WAFFLE_V2_PATH\" && \"REMOTE_CONDA_PATH\" run --no-capture-output -n Waffle python near_realtime_aia_pipeline.py"
```

This attached SSH command is the important test. It proves that the remote path, conda path, environment name, and WAFFLE imports are correct. If this fails, the Paramiko helper would fail for the same reason, so fix the attached SSH command first.

After the attached SSH command works, use the Python helper from the local/control computer:

```bash
python Waffle/remote_start_waffle.py --host REMOTE_HOST_OR_IP --user REMOTE_USERNAME --password --remote-root "REMOTE_WAFFLE_V2_PATH" --conda "REMOTE_CONDA_PATH"
```

The helper prompts for the SSH password, connects, prints the remote command it is about to run, and streams WAFFLE output back into the local terminal. This is the safest default mode because errors stay visible.

If the remote `Waffle` conda environment exists but needs to be updated from `waffle_env.yml`, add `--update-env`:

```bash
python Waffle/remote_start_waffle.py --host REMOTE_HOST_OR_IP --user REMOTE_USERNAME --password --remote-root "REMOTE_WAFFLE_V2_PATH" --conda "REMOTE_CONDA_PATH" --update-env
```

Only use detached/background mode after attached mode works. Background mode sends the start command and returns without keeping the WAFFLE output attached:

```bash
python Waffle/remote_start_waffle.py --host REMOTE_HOST_OR_IP --user REMOTE_USERNAME --password --remote-root "REMOTE_WAFFLE_V2_PATH" --conda "REMOTE_CONDA_PATH" --background
```

You can also test only the Paramiko connection without starting WAFFLE:

```bash
python Waffle/remote_start_waffle.py --host REMOTE_HOST_OR_IP --user REMOTE_USERNAME --password --remote-root "REMOTE_WAFFLE_V2_PATH" --conda "REMOTE_CONDA_PATH" --test
```

The local Python environment only needs Paramiko. Install it locally with either:

```bash
python -m pip install paramiko
```

or:

```bash
conda install -c conda-forge paramiko
```

The local Python environment does not need to be the WAFFLE environment. WAFFLE itself runs on the remote computer through the remote `Waffle` conda environment.

The remote WAFFLE command depends on two paths. `REMOTE_WAFFLE_V2_PATH` is the folder on the remote computer containing `near_realtime_aia_pipeline.py`. `REMOTE_CONDA_PATH` is the full path to the remote `conda.bat`, usually inside a Miniforge, Miniconda, or Anaconda `condabin` folder. Use the full `conda.bat` path instead of relying on `conda` being on PATH, because SSH sessions often have a different PATH than the normal desktop terminal.

Do not commit real usernames, passwords, internal IP addresses, private keys, or machine-specific personal paths if those are sensitive. The scripts are written to take those values as command-line arguments so they do not need to be stored in the repo.

Useful remote checks are:

```powershell
Get-Service sshd
ipconfig
whoami
where conda
```

Useful conda checks on the remote computer are:

```bat
"REMOTE_CONDA_PATH" env list
"REMOTE_CONDA_PATH" run -n Waffle python -c "import torch; print(torch.__version__); print(torch.__file__)"
"REMOTE_CONDA_PATH" run -n Waffle python -c "import sunpy, aiapy, paramiko, torch; print('imports ok')"
```

The basic rule is simple: first make `ssh REMOTE_USERNAME@REMOTE_HOST_OR_IP "hostname"` work, then make the attached remote WAFFLE command work, then use `remote_start_waffle.py`.
