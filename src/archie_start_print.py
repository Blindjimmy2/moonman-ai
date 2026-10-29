import json
import sys
from pathlib import PurePosixPath

ARCHIE_WS = "ws://192.168.1.10:9999"
GCODE_DIR = "/usr/data/printer_data/gcodes"

def build_start_command(filename):
    if not isinstance(filename, str) or not filename:
        raise ValueError("G-code filename required")
    if filename != PurePosixPath(filename).name or filename in (".", ".."):
        raise ValueError("Filename only, no paths")
    if not filename.lower().endswith(".gcode"):
        raise ValueError("Must be a .gcode file")
    if any(ord(c) < 32 or ord(c) == 127 for c in filename):
        raise ValueError("Invalid filename characters")

    return {
        "method": "set",
        "params": {
            "opGcodeFile": f"printprt:{GCODE_DIR}/{filename}",
            "enableSelfTest": 1
        }
    }

def archie_start_print(filename, *, approved=False):
    command = build_start_command(filename)

    if approved is not True:
        return {
            "status": "approval_required",
            "printer": "Archie",
            "filename": filename,
            "command": command
        }

    from websocket import create_connection

    ws = None
    try:
        ws = create_connection(ARCHIE_WS, timeout=5)
        ws.send(json.dumps(command, separators=(",", ":")))

        try:
            response = ws.recv()
        except Exception:
            response = None

        return {
            "status": "command_sent_unverified",
            "printer": "Archie",
            "filename": filename,
            "response": response[:1500] if isinstance(response, str) else None
        }
    except Exception as exc:
        return {
            "status": "error",
            "printer": "Archie",
            "error": str(exc)
        }
    finally:
        if ws is not None:
            ws.close()

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python archie_start_print.py filename.gcode")
        sys.exit(2)

    filename = sys.argv[1]
    command = build_start_command(filename)

    print("ARCHIE PRINT START")
    print(json.dumps(command, indent=2))
    print("WARNING: This will physically start a print.")
    approval = input("Type START ARCHIE to approve: ").strip()

    if approval != "START ARCHIE":
        print("Cancelled. Nothing sent.")
        sys.exit(0)

    result = archie_start_print(filename, approved=True)
    print(json.dumps(result, indent=2))
