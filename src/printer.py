import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

URL = os.environ["OCTOPRINT_URL"].rstrip("/")
KEY = os.environ["OCTOPRINT_API_KEY"]

def upload_gcode(path):
    path = Path(path).resolve()

    if not path.is_file() or path.suffix.lower() != ".gcode":
        raise ValueError("A valid G-code file is required.")

    headers = {"X-Api-Key": KEY}

    session = requests.Session()
    session.trust_env = False

    with path.open("rb") as file:
        response = session.post(
            f"{URL}/api/files/local",
            headers=headers,
            files={"file": (path.name, file, "application/octet-stream")},
            data={"select": "false", "print": "false"},
            timeout=60,
        )

    response.raise_for_status()
    print(f"MOON MAN: Uploaded {path.name}")
    print("Status: Awaiting explicit print authorization.")
    return response.json()

if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python src/printer.py <file.gcode>")

    upload_gcode(sys.argv[1])
