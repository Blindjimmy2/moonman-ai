import os
import posixpath
import shlex
import subprocess
from pathlib import Path

import paramiko

HOST = "192.168.1.10"
SECRET = Path(__file__).resolve().parent / ".archie_ssh_secret"

ROOTS = (
    "/usr/data/printer_data/logs",
    "/usr/data/printer_data/config",
    "/usr/data/printer_data/gcodes",
)

def _path(path, default=None):
    if path is None or path == "":
        path = default

    if (
        not isinstance(path, str)
        or not path.startswith("/")
        or any(c in path for c in ("\x00", "\n", "\r"))
    ):
        raise ValueError("Absolute printer path required")

    clean = posixpath.normpath(path)

    if not any(
        clean == root or clean.startswith(root + "/")
        for root in ROOTS
    ):
        raise ValueError("Path outside Archie diagnostic directories: " + repr(clean))

    return clean


def _connect():
    if not SECRET.is_file():
        raise RuntimeError("Archie SSH password not configured")

    encrypted = SECRET.read_text(encoding="utf-8").strip()

    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "$s=ConvertTo-SecureString $env:ARCHIE_ENCRYPTED_SECRET;"
            "$b=[System.Net.NetworkCredential]::new('', $s).Password;"
            "[Console]::Write($b)",
        ],
        env={**os.environ, "ARCHIE_ENCRYPTED_SECRET": encrypted},
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )

    ssh = paramiko.SSHClient()
    ssh.load_system_host_keys()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        ssh.connect(
            HOST,
            username="root",
            password=result.stdout,
            look_for_keys=False,
            allow_agent=False,
            timeout=10,
            auth_timeout=10,
            banner_timeout=20,
        )
        return ssh
    except Exception:
        ssh.close()
        raise


def _run(ssh, command, limit=25000):
    _, stdout, stderr = ssh.exec_command(command, timeout=15)

    data = stdout.read(limit + 1)
    error = stderr.read(3000).decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()

    return (
        code,
        data[:limit].decode("utf-8", errors="replace"),
        error,
        len(data) > limit,
    )


def _verified(ssh, path, directory=False):
    code, output, error, _ = _run(
        ssh, "readlink -f " + shlex.quote(path), 4096
    )

    if code != 0 or not output.strip():
        raise RuntimeError(
            "Cannot resolve remote path: " + (error.strip() or path)
        )

    real = _path(output.strip())
    test = "-d" if directory else "-f"

    code, _, _, _ = _run(
        ssh, "test " + test + " " + shlex.quote(real)
    )

    if code != 0:
        raise ValueError(
            "Not a " + ("directory" if directory else "regular file")
            + ": " + path
        )

    return real


def archie_list_files(path="/usr/data/printer_data/gcodes/"):
    try:
        clean = _path(path, "/usr/data/printer_data/gcodes/")
        ssh = _connect()

        try:
            real = _verified(ssh, clean, directory=True)
            code, output, error, truncated = _run(
                ssh, "ls -la " + shlex.quote(real), 18000
            )

            if code != 0:
                raise RuntimeError(error.strip() or "Listing failed")

            return {
                "status": "ok",
                "printer": "Archie",
                "path": real,
                "listing": output,
                "truncated": truncated,
                "mode": "read_only",
            }
        finally:
            ssh.close()

    except Exception as exc:
        return {
            "status": "error",
            "printer": "Archie",
            "error": str(exc),
        }


def archie_read_file(path, max_bytes=12000):
    try:
        clean = _path(path)
        count = max(1, min(int(max_bytes), 20000))
        ssh = _connect()

        try:
            real = _verified(ssh, clean)
            code, output, error, truncated = _run(
                ssh,
                "head -c " + str(count) + " " + shlex.quote(real),
                count,
            )

            if code != 0:
                raise RuntimeError(error.strip() or "Read failed")

            return {
                "status": "ok",
                "printer": "Archie",
                "path": real,
                "content": output,
                "truncated": truncated,
                "mode": "read_only",
            }
        finally:
            ssh.close()

    except Exception as exc:
        return {
            "status": "error",
            "printer": "Archie",
            "error": str(exc),
        }


def archie_moonraker_status():
    import urllib.request

    try:
        with urllib.request.urlopen(
            "http://" + HOST + ":7125/server/info", timeout=4
        ) as response:
            return {
                "status": "ok",
                "data": response.read(12000).decode(
                    errors="replace"
                ),
            }
    except Exception as exc:
        return {"status": "unavailable", "error": str(exc)}

