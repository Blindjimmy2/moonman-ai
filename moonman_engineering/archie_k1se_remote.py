# Archie K1 SE remote-print prototype - v0.4 Archie-only
# Moon Man engineering shop - Archie only. No Marvin.
"""
Confirmed facts (crew-provided):
- Archie = Creality K1 SE
- Archie WebSocket port: 9999
- Archie accepts uploaded G-code
- Archie prints OK from touchscreen

Clues (UNCONFIRMED, do not treat as working):
- AppControlPrint-related WebSocket hints seen in research
- Exact upload/start payloads NOT confirmed

Rules:
- Archie-only. No Marvin logic, no Marvin imports, no Marvin calls.
- Slice + stage only. NEVER auto-start a physical print.
- Print start = touchscreen-only by human.
- Agent tools allowed: archie_status + prepare_archie_print only.
"""

from pathlib import Path

ARCHIE_PRINTER = "Archie"
ARCHIE_MODEL = "K1 SE"
ARCHIE_WS_PORT = 9999
SLICER_PROFILE = "Creality Print ASA"
GENERATED_DIR = Path(r"C:\MoonworksDev\moonman-ai\generated")
ALLOWED_DIR = GENERATED_DIR.resolve()

# Clue name only - payload not confirmed, never sent automatically
APP_CONTROL_CLUE = "AppControlPrint"


def describe_archie_transport() -> dict:
    """Return confirmed Archie transport facts only."""
    return {
        "printer": ARCHIE_PRINTER,
        "model": ARCHIE_MODEL,
        "websocket_port": ARCHIE_WS_PORT,
        "accepts_gcode_upload": True,
        "print_start": "touchscreen-only by human",
        "start_print": False,
        "clue_unconfirmed": APP_CONTROL_CLUE,
    }


def get_status_snapshot() -> dict:
    """Placeholder - live data comes from archie_status tool only."""
    return {
        "printer": ARCHIE_PRINTER,
        "model": ARCHIE_MODEL,
        "note": "call archie_status tool for live temps/progress",
    }


def validate_stl_path(stl_path: str) -> Path:
    """Archie-only validation: must be .stl, exist, in generated folder."""
    p = Path(stl_path)
    if p.suffix.lower() != ".stl":
        raise ValueError(f"Not an STL, cadet: {stl_path}")
    if not p.exists():
        raise FileNotFoundError(f"STL not found on this ship: {stl_path}")
    try:
        resolved = p.resolve()
    except OSError as e:
        raise ValueError(f"Bad path, Houston: {e}")
    if resolved.parent != ALLOWED_DIR:
        raise ValueError(f"STL outside generated folder: {stl_path}")
    return p


def pick_latest_stl() -> str:
    """Pick newest STL from generated folder."""
    if not GENERATED_DIR.exists():
        raise FileNotFoundError("Generated folder missing.")
    stls = sorted(GENERATED_DIR.glob("*.stl"))
    if not stls:
        raise FileNotFoundError("No STLs in generated folder.")
    return str(stls[-1])


def build_slice_job(stl_path: str) -> dict:
    """Build Archie-only slice request. No upload, no print start."""
    p = validate_stl_path(stl_path)
    return {
        "printer": ARCHIE_PRINTER,
        "model": ARCHIE_MODEL,
        "stl": str(p),
        "slicer": SLICER_PROFILE,
        "tool": "prepare_archie_print",
        "websocket_port": ARCHIE_WS_PORT,
        "upload": False,
        "start_print": False,
        "next": "await human go/no-go",
    }


def build_upload_job(gcode_path: str) -> dict:
    """Build upload-only job. Human starts print from touchscreen."""
    g = Path(gcode_path)
    if g.suffix.lower() != ".gcode":
        raise ValueError(f"Not G-code, cadet: {gcode_path}")
    return {
        "printer": ARCHIE_PRINTER,
        "model": ARCHIE_MODEL,
        "gcode": str(g),
        "websocket_port": ARCHIE_WS_PORT,
        "app_control_clue": APP_CONTROL_CLUE,
        "upload": True,
        "start_print": False,
        "print_start": "touchscreen-only by human",
    }


def format_approval_prompt(slice_result: dict) -> str:
    """Human go/no-go prompt after slicing."""
    return (
        f"Archie slice ready for {slice_result.get('stl')} "
        f"via {slice_result.get('slicer')}. "
        "Approval required before upload. No auto-print. Capisce?"
    )


if __name__ == "__main__":
    print("Moon Man Archie-only v0.4 loaded. Port 9999, upload OK, touchscreen start.")
