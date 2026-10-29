
import json
import time
import urllib.request
import websocket

IP = "192.168.1.10"

def archie_inspect(seconds=8):
    seconds = max(1, min(int(seconds), 15))
    result = {"printer": "Archie", "mode": "read_only", "messages": []}

    try:
        with urllib.request.urlopen("http://" + IP + "/info", timeout=5) as response:
            result["info"] = json.loads(response.read(4096))
    except Exception as exc:
        result["info_error"] = str(exc)

    ws = websocket.create_connection("ws://" + IP + ":9999", timeout=5)
    try:
        ws.settimeout(2)
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and len(result["messages"]) < 15:
            try:
                packet = json.loads(ws.recv())
                if isinstance(packet, dict):
                    result["messages"].append(packet)
            except websocket.WebSocketTimeoutException:
                continue
    finally:
        ws.close()

    return result

def archie_read_logs(lines=100):
    """Read Archie's Klipper log via password SSH. No printer commands."""
    import os
    import subprocess
    import paramiko
    from pathlib import Path

    try:
        count = max(1, min(int(lines), 500))
        secret_file = Path(__file__).resolve().parent / ".archie_ssh_secret"

        if not secret_file.is_file():
            return {"status": "error", "error": "Archie SSH password not configured"}

        encrypted = secret_file.read_text(encoding="utf-8").strip()

        result = subprocess.run(
            [
                "powershell.exe", "-NoProfile", "-Command",
                "$s=ConvertTo-SecureString $env:ARCHIE_ENCRYPTED_SECRET;"
                "$b=[System.Net.NetworkCredential]::new('', $s).Password;"
                "[Console]::Write($b)"
            ],
            env={**os.environ, "ARCHIE_ENCRYPTED_SECRET": encrypted},
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )

        password = result.stdout
        ssh = paramiko.SSHClient()
        ssh.load_system_host_keys()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            ssh.connect(
                "192.168.1.10",
                username="root",
                password=password,
                look_for_keys=False,
                allow_agent=False,
                timeout=10,
                auth_timeout=10,
            )
            command = f"tail -n {count} /usr/data/printer_data/logs/klippy.log"
            _, stdout, stderr = ssh.exec_command(command, timeout=15)

            log = stdout.read().decode("utf-8", errors="replace")
            error = stderr.read().decode("utf-8", errors="replace")
            code = stdout.channel.recv_exit_status()

            return {
                "status": "ok" if code == 0 else "error",
                "printer": "Archie",
                "lines": count,
                "log": log,
                "error": error,
            }
        finally:
            ssh.close()

    except Exception as exc:
        return {
            "status": "error",
            "printer": "Archie",
            "error": str(exc),
        }

