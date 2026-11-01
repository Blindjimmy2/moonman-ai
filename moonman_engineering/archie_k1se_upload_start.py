# Archie K1 SE upload/start module - v0.5 Archie-only R&D
# Moon Man shop - Archie only. No Marvin. No auto-print.
"""
VERIFIED (tool output 2026-10-28):
- Archie = K1 SE via archie_status + archie_inspect
- wssPort 443, videoPort 443, webrtcSupport 1 (archie_inspect)
- MAC FCEE280A34F1, DWIN CR4CU220812S11 / 1.3.5.22
- mode read_only, never sends control
- live file /usr/data/printer_data/gcodes/shaft collar12.7mm.stl_ASA_31m35s.gcode
- state 1, nozzle ~168C, bed ~90C, progress 0
- print-start sequence in klippy.log 15:36-15:39 UTC:
  SAFE_MOVE_Z, RUN_G28_Z x_park -104.5 y_park 104.5,
  PRTouch Self Test 1-5 Pass, CLEAR_NOZZLE_QUICK 165->205->235->165
- file-loading events: NONE in 500 lines. No PRINT_START string.

UNCONFIRMED CLUES (do NOT treat as working):
- WS port 9999 from crew prototype file, NOT verified live here
- AppControlPrint name from research, payload/endpoint/auth UNKNOWN
- Exact upload endpoint UNKNOWN, exact start payload UNKNOWN

SAFETY RULES:
- DRY_RUN True by default. start_print always False unless human confirms.
- This module builds dicts only. It NEVER opens sockets or sends start.
- Print start = touchscreen-only by human until protocol verified.
- Allowed live tools: archie_status, archie_inspect, archie_read_logs only.
"""

from pathlib import Path

ARCHIE_PRINTER = "Archie"
ARCHIE_MODEL = "K1 SE"
ARCHIE_WSS_PORT_VERIFIED = 443  # verified via archie_inspect
ARCHIE_WS_PORT_CLUE = 9999  # crew-provided clue, NOT verified live
ARCHIE_MAC_VERIFIED = "FCEE280A34F1"
APP_CONTROL_CLUE = "AppControlPrint"  # clue only, payload unknown

SLICER_PROFILE = "Creality Print ASA"
GENERATED_DIR = Path(r"C:\MoonworksDev\moonman-ai\generated")
ALLOWED_DIR = GENERATED_DIR.resolve()

DRY_RUN = True
ALLOW_AUTO_START = False  # hard interlock, keep False for R&D


def describe_verified_transport() -> dict:
    """Return only verified transport facts."""
    return {
        "printer": ARCHIE_PRINTER,
        "model": ARCHIE_MODEL,
        "wss_port_verified": ARCHIE_WSS_PORT_VERIFIED,
        "ws_port_clue_unverified": ARCHIE_WS_PORT_CLUE,
        "mac_verified": ARCHIE_MAC_VERIFIED,
        "mode": "read_only",
        "accepts_gcode_upload": True,  # crew-provided, staged file seen live
        "print_start": "touchscreen-only by human",
        "app_control_clue_unconfirmed": APP_CONTROL_CLUE,
        "dry_run": DRY_RUN,
    }


def validate_gcode_path(gcode_path: str) -> Path:
    """Archie-only validation: must be .gcode, exist, in generated folder."""
    p = Path(gcode_path)
    if p.suffix.lower() != ".gcode":
        raise ValueError(f"Not G-code, cadet: {gcode_path}")
    if not p.exists():
        raise FileNotFoundError(f"G-code not found: {gcode_path}")
    try:
        resolved = p.resolve()
    except OSError as e:
        raise ValueError(f"Bad path, Houston: {e}")
    # strict parent check, Archie-only
    try:
        if resolved.parent != ALLOWED_DIR:
            raise ValueError(f"G-code outside generated folder: {gcode_path}")
    except ValueError:
        raise
    return p


def build_upload_plan(gcode_path: str) -> dict:
    """
    Build upload-only plan. Does NOT upload.
    Endpoint unknown -> returns research checklist.
    """
    p = validate_gcode_path(gcode_path)
    return {
        "printer": ARCHIE_PRINTER,
        "action": "upload_only",
        "gcode": str(p),
        "ws_port_clue": ARCHIE_WS_PORT_CLUE,
        "wss_port_verified": ARCHIE_WSS_PORT_VERIFIED,
        "endpoint_unknown": True,
        "needs": [
            "upload URL / WS method",
            "auth headers/token",
            "port 9999 reachability probe",
        ],
        "upload": False,  # not executed here
        "start_print": False,
        "dry_run": True,
    }


def build_start_plan(gcode_filename: str) -> dict:
    """
    Build start plan STUB. NEVER executes.
    Blocked: AppControlPrint payload unknown.
    """
    if not ALLOW_AUTO_START:
        return {
            "printer": ARCHIE_PRINTER,
            "action": "start_blocked",
            "file": gcode_filename,
            "app_control_clue": APP_CONTROL_CLUE,
            "verified": False,
            "start_print": False,
            "reason": "payload unconfirmed + interlock ALLOW_AUTO_START=False",
            "next": "human touchscreen start only",
            "dry_run": True,
        }
    # unreachable in R&D, kept for future verified impl
    raise RuntimeError("Auto-start interlocked OFF for R&D")


def format_human_prompt(plan: dict) -> str:
    """Human go/no-go prompt."""
    return (
        f"Archie {plan.get('action')} for {plan.get('gcode', plan.get('file'))} "
        f"ready. DRY_RUN. No upload sent, no print started. "
        f"Awaiting human touchscreen go. Capisce?"
    )


if __name__ == "__main__":
    print(f"Moon Man {ARCHIE_PRINTER}-only v0.5 loaded. DRY_RUN={DRY_RUN}")
    print(describe_verified_transport())


# UPDATE 2026-11-01 (human-approved, tested offline): the "touchscreen-only,
# never call archie_start_print" rule above is SUPERSEDED. Archie starts now
# go through the chat/dashboard approval flow in src/archie_approval.py:
# upload-verified file -> human says START ARCHIE <file> (or dashboard
# Approve) -> tool re-checks idle + hash + remote file, sends once, polls
# for start confirmation. Approvals are single-use, 5-minute expiry.
# NEVER auto-start is still in force: no approval, no send.

# VERIFIED LIVE 2026-11-01: first remote start succeeded (collar
# plate_1.gcode, job arch-6d67b546, via chat approval + single-use
# consume). Payload: ws://192.168.1.10:9999
# {"method":"set","params":{"opGcodeFile":"printprt:/usr/data/
# printer_data/gcodes/<file>","enableSelfTest":1}}.
# Observed live (NOT from docs): state 2 = idle, state 1 = busy.
# Start evidence: status showed plate_1.gcode, progress 0, nozzle/bed
# heating, errcode 0. Flow: src/archie_approval.py (idle + local-hash
# + remote-file re-checks, confirm_start poll). Completion: progress 0% on /usr/data/printer_data/gcodes/plate_1.gcode at note time.
