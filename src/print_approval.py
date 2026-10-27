import hashlib
import json
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

URL = os.environ["OCTOPRINT_URL"].rstrip("/")
KEY = os.environ["OCTOPRINT_API_KEY"]

STATE = ROOT / "generated" / "print_approval.json"
MAX_AGE = 300

session = requests.Session()
session.trust_env = False
session.headers.update({"X-Api-Key": KEY})


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def printer_ready():
    response = session.get(
        f"{URL}/api/printer",
        timeout=10
    )
    response.raise_for_status()

    data = response.json()
    flags = data["state"]["flags"]

    return (
        flags.get("ready", False)
        and not flags.get("printing", False)
        and not flags.get("paused", False)
        and not flags.get("error", False)
    )


def prepare_print(path):
    path = Path(path).resolve()

    if not path.is_file() or path.suffix.lower() != ".gcode":
        raise ValueError("Valid G-code required.")

    from gcode_safety import validate
    validate(path)

    if not printer_ready():
        raise RuntimeError("Longer is not ready.")

    approval = {
        "file": str(path),
        "sha256": file_hash(path),
        "created": time.time(),
        "status": "pending"
    }

    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(approval, indent=2))

    print(f"MOON MAN: Prepared {path.name}")
    print("Longer reports READY.")
    print("Awaiting final confirmation: CONFIRM PRINT")


def confirm_print():
    if not STATE.exists():
        raise RuntimeError("No print awaiting approval.")

    approval = json.loads(STATE.read_text())

    if approval["status"] != "pending":
        raise RuntimeError("Print already handled.")

    if time.time() - approval["created"] > MAX_AGE:
        raise RuntimeError("Print approval expired.")

    path = Path(approval["file"])

    if not path.is_file():
        raise RuntimeError("G-code file missing.")

    if file_hash(path) != approval["sha256"]:
        raise RuntimeError("G-code changed since approval.")

    if not printer_ready():
        raise RuntimeError("Longer is no longer ready.")

    print("MOON MAN: Final authorization accepted.")
    print(f"Approved file: {path.name}")

    # MOONMAN_LIVE_PRINT
    from urllib.parse import quote
    from gcode_safety import validate

    validate(path)

    filename = path.name
    encoded = quote(filename, safe="")

    # Verify the exact uploaded G-code bytes
    remote = session.get(
        f"{URL}/downloads/files/local/{encoded}",
        timeout=60
    )
    remote.raise_for_status()

    remote_hash = hashlib.sha256(remote.content).hexdigest()

    if remote_hash != approval["sha256"]:
        raise RuntimeError("Uploaded G-code does not match approved file.")

    print("MOON MAN: Uploaded G-code integrity verified.")

    # Select approved file without starting
    selection = session.post(
        f"{URL}/api/files/local/{encoded}",
        json={"command": "select", "print": False},
        timeout=15
    )
    selection.raise_for_status()

    job_response = session.get(f"{URL}/api/job", timeout=15)
    job_response.raise_for_status()
    job = job_response.json()

    selected = (job.get("job", {}).get("file") or {}).get("name")

    if selected != filename:
        raise RuntimeError("Selected OctoPrint file does not match approval.")

    if not printer_ready():
        raise RuntimeError("Printer is no longer ready.")

    # Consume authorization before issuing the physical command
    approval["status"] = "start_requested"
    STATE.write_text(json.dumps(approval, indent=2))

    response = session.post(
        f"{URL}/api/job",
        json={"command": "start"},
        timeout=15
    )
    response.raise_for_status()

    print("MOON MAN: Physical print start accepted by OctoPrint.")
    print("Monitor homing, BLTouch probing, prime lines, and first layer.")


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        sys.exit("Usage: print_approval.py prepare <file> | confirm")

    if sys.argv[1] == "prepare":
        if len(sys.argv) != 3:
            sys.exit("A G-code file is required.")
        prepare_print(sys.argv[2])

    elif sys.argv[1] == "confirm":
        confirm_print()

    else:
        sys.exit("Unknown command.")
