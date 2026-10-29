from pathlib import Path
import hashlib
import json
import requests
import websocket

ROOT = Path(__file__).resolve().parent.parent
JOBS = (ROOT / "generated" / "archie_jobs").resolve()
HOST = "192.168.1.10"


def _find_file(entries, filename):
    if isinstance(entries, dict):
        if entries.get("name") == filename:
            return entries
        for value in entries.values():
            result = _find_file(value, filename)
            if result:
                return result
    elif isinstance(entries, list):
        for value in entries:
            result = _find_file(value, filename)
            if result:
                return result
    return None


def archie_upload_gcode(gcode_path):
    path = Path(gcode_path).resolve()

    if not path.is_file() or path.suffix.lower() != ".gcode":
        raise ValueError("Valid G-code file required")

    if not path.is_relative_to(JOBS):
        raise ValueError("G-code must be inside generated/archie_jobs")

    from archie_gcode_safety import validate
    validation = validate(path)

    if not isinstance(validation, dict) or validation.get("safe") is not True:
        raise RuntimeError("Archie G-code validation failed")

    size = path.stat().st_size
    digest = hashlib.sha256(path.read_bytes()).hexdigest()

    # Upload does not start printing.
    session = requests.Session()
    session.trust_env = False

    with path.open("rb") as file:
        response = session.post(
            f"http://{HOST}/upload/{path.name}",
            files={"file": (path.name, file, "application/octet-stream")},
            timeout=90
        )

    response.raise_for_status()
    data = response.json()

    if data.get("code") != 200:
        raise RuntimeError(f"Archie rejected upload: {data}")

    # Verify the file appears on Archie's storage.
    ws = websocket.create_connection(
        f"ws://{HOST}:9999", timeout=6
    )

    remote = None
    try:
        ws.settimeout(3)
        ws.send(json.dumps({
            "method": "get",
            "params": {"reqGcodeFile": 1}
        }))

        for _ in range(8):
            try:
                message = json.loads(ws.recv())
            except websocket.WebSocketTimeoutException:
                break

            candidate = _find_file(message, path.name)
            if candidate:
                remote = candidate
                break
    finally:
        ws.close()

    if remote is None:
        return {
            "printer": "Archie",
            "status": "upload_accepted_verification_pending",
            "filename": path.name,
            "sha256_local": digest,
            "message": "Upload accepted but remote file not verified. Do not print yet."
        }

    remote_size = remote.get("file_size")

    if remote_size != size:
        raise RuntimeError(
            f"Remote size mismatch: local={size}, remote={remote_size}"
        )

    return {
        "printer": "Archie",
        "status": "uploaded_verified_not_printing",
        "filename": path.name,
        "remote_path": remote.get("path"),
        "bytes": size,
        "sha256_local": digest,
        "message": (
            "Archie confirms filename and size. "
            "Physical printing requires separate human approval."
        )
    }
