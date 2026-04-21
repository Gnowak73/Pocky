#!/usr/bin/env python3
"""Start WAFFLE v2 on a remote Windows computer over SSH.

This script is meant to be run from the local/control computer. The remote
computer must already have OpenSSH Server running.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from typing import Optional

try:
    import paramiko
except ImportError as exc:  # pragma: no cover - runtime guidance
    raise SystemExit(
        "paramiko is not installed. Install it locally with: python -m pip install paramiko"
    ) from exc


def ps_single_quote(value: str) -> str:
    """Return a PowerShell single-quoted string literal."""
    return "'" + value.replace("'", "''") + "'"


def build_attached_command(remote_root: str, conda_path: str, env_name: str, update_env: bool) -> str:
    update = ""
    if update_env:
        update = (
            f'if exist "waffle_env_windows.yml" ('
            f'"{conda_path}" env update -n {env_name} -f waffle_env_windows.yml --prune'
            f') else ('
            f'"{conda_path}" env update -n {env_name} -f waffle_env.yml --prune'
            f') && '
        )
    return (
        f'cd /d "{remote_root}" && '
        f'{update}'
        f'"{conda_path}" run --no-capture-output -n {env_name} '
        f'python near_realtime_aia_pipeline.py'
    )


def build_background_command(remote_root: str, conda_path: str, env_name: str, update_env: bool) -> str:
    if update_env:
        # Run update attached first; backgrounding an env update hides too many useful errors.
        update_cmd = (
            f'cd /d "{remote_root}" && '
            f'if exist "waffle_env_windows.yml" ('
            f'"{conda_path}" env update -n {env_name} -f waffle_env_windows.yml --prune'
            f') else ('
            f'"{conda_path}" env update -n {env_name} -f waffle_env.yml --prune'
            f') && '
        )
    else:
        update_cmd = ""

    args = f"run --no-capture-output -n {env_name} python near_realtime_aia_pipeline.py"
    ps = (
        "Start-Process "
        f"-FilePath {ps_single_quote(conda_path)} "
        f"-ArgumentList {ps_single_quote(args)} "
        f"-WorkingDirectory {ps_single_quote(remote_root)}"
    )
    return update_cmd + "powershell -NoProfile -ExecutionPolicy Bypass -Command " + '"' + ps + '"'


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start WAFFLE v2 on a remote Windows computer over SSH.")
    parser.add_argument("--host", required=True, help="Remote IP address or hostname.")
    parser.add_argument("--user", required=True, help="Remote SSH username.")
    parser.add_argument("--remote-root", required=True, help="Remote WAFFLE v2 directory.")
    parser.add_argument("--conda", required=True, help="Full path to remote conda.bat.")
    parser.add_argument("--env", default="Waffle", help="Remote conda environment name.")
    parser.add_argument("--password", action="store_true", help="Prompt for SSH password.")
    parser.add_argument("--key", default=None, help="Optional SSH private key path.")
    parser.add_argument("--port", type=int, default=22, help="SSH port.")
    parser.add_argument("--background", action="store_true", help="Start WAFFLE detached with PowerShell Start-Process.")
    parser.add_argument("--update-env", action="store_true", help="Update the remote Waffle env before starting.")
    parser.add_argument("--test", action="store_true", help="Only run a lightweight remote hostname test.")
    return parser.parse_args()


def connect(host: str, port: int, user: str, password: Optional[str], key: Optional[str]) -> paramiko.SSHClient:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(
        hostname=host,
        port=port,
        username=user,
        password=password,
        key_filename=key,
        look_for_keys=not password and key is None,
        allow_agent=not password,
    )
    return ssh


def run_streaming(ssh: paramiko.SSHClient, command: str) -> int:
    transport = ssh.get_transport()
    if transport is None:
        raise RuntimeError("SSH transport was not established")
    channel = transport.open_session()
    channel.get_pty()
    channel.set_combine_stderr(True)
    channel.exec_command(command)

    while True:
        if channel.recv_ready():
            sys.stdout.write(channel.recv(4096).decode(errors="replace"))
            sys.stdout.flush()
        if channel.exit_status_ready():
            while channel.recv_ready():
                sys.stdout.write(channel.recv(4096).decode(errors="replace"))
                sys.stdout.flush()
            return channel.recv_exit_status()


def main() -> int:
    args = parse_args()
    password = getpass.getpass("SSH password: ") if args.password else None

    if args.test:
        command = "hostname"
    elif args.background:
        command = build_background_command(args.remote_root, args.conda, args.env, args.update_env)
    else:
        command = build_attached_command(args.remote_root, args.conda, args.env, args.update_env)

    print(f"Connecting to {args.user}@{args.host}:{args.port}")
    print(f"Remote command: {command}")

    ssh = connect(args.host, args.port, args.user, password, args.key)
    try:
        code = run_streaming(ssh, command)
    finally:
        ssh.close()

    if code != 0:
        print(f"Remote command failed with exit code {code}")
    elif args.background and not args.test:
        print("WAFFLE start command was sent in background mode.")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
