
from pathlib import Path
import subprocess
import hashlib
import json
import websocket

ROOT = Path(__file__).resolve().parent.parent
GENERATED = (ROOT / "generated").resolve()
EXE = Path(r"C:\Program Files\Creality\Creality Print 7.0\CrealityPrint.exe")
PROFILES = EXE.parent / "resources" / "profiles" / "Creality"
MACHINE = PROFILES / "machine" / "Creality K1 SE 0.4 nozzle.json"
PROCESS = PROFILES / "process" / "0.20mm  Standard @Creality K1 SE 0.4 nozzle.json"
FILAMENT = PROFILES / "filament" / "Generic ASA @Creality K1 SE 0.4 nozzle.json"
DEFAULT_FILAMENT = "Generic ASA"


def list_archie_filaments():
    """Material names profiled for Archie machine (short names)."""
    tag = "@" + MACHINE.stem + ".json"
    try:
        files = sorted((PROFILES / "filament").glob("*" + tag))
    except Exception:
        return []
    return [f.name[:-len(tag)].strip() for f in files]


def _resolve_filament(name):
    """Profile path for a listed material (exact or case-insensitive).

    Anything not on the list raises ValueError, so slicer paths can
    never escape the profiles directory.
    """
    if name is None:
        return FILAMENT
    want = str(name).strip()
    mats = list_archie_filaments()
    if want in mats:
        picked = want
    else:
        lowered = [m for m in mats if m.lower() == want.lower()]
        if len(lowered) != 1:
            raise ValueError("unknown Archie filament %r" % (name,))
        picked = lowered[0]
    return PROFILES / "filament" / (picked + " @" + MACHINE.stem + ".json")

def archie_status():
    ws = websocket.create_connection("ws://192.168.1.10:9999", timeout=6)
    try:
        ws.settimeout(6)
        data = json.loads(ws.recv())
        return {
            "printer": data.get("hostname", "Archie"),
            "model": data.get("model"),
            "state": data.get("state"),
            "nozzle_c": data.get("nozzleTemp"),
            "bed_c": data.get("bedTemp0"),
            "progress": data.get("printProgress"),
            "file": data.get("printFileName"),
            "error": data.get("err"),
        }
    finally:
        ws.close()

def prepare_archie_print(stl_path, filament=None):
    path = Path(stl_path).resolve()
    if not path.is_file() or path.suffix.lower() != ".stl":
        raise ValueError("Valid STL required")
    if not path.is_relative_to(GENERATED):
        raise ValueError("STL must be inside Moon Man generated folder")

    filament_path = _resolve_filament(filament)
    for required in (EXE, MACHINE, PROCESS, filament_path):
        if not required.is_file():
            raise FileNotFoundError(str(required))

    output = GENERATED / "archie_jobs" / (
        path.stem + "_" +
        hashlib.sha256(path.read_bytes()).hexdigest()[:8]
    )
    output.mkdir(parents=True, exist_ok=True)

    args = [
        str(EXE),
        "--load-settings", str(MACHINE) + ";" + str(PROCESS),
        "--load-filaments", str(filament_path),
        "--slice", "0",
        "--ensure-on-bed",
        "--outputdir", str(output),
        str(path)
    ]

    result = subprocess.run(args, capture_output=True, text=True, timeout=180)
    files = list(output.glob("*.gcode"))
    if result.returncode != 0 or not files:
        raise RuntimeError(
            "Creality slicing failed: " +
            (result.stdout + result.stderr)[-1500:]
        )

    gcode = max(files, key=lambda p: p.stat().st_mtime)
    if gcode.stat().st_size < 1000:
        raise RuntimeError("G-code unexpectedly small")

    from archie_gcode_safety import validate
    validation = validate(gcode)
    if isinstance(validation, dict) and validation.get("safe") is False:
        raise RuntimeError("G-code validation failed")

    return {
        "printer": "Archie",
        "status": "sliced_locally_not_uploaded",
        "filament": filament_path.stem,
        "gcode": str(gcode),
        "bytes": gcode.stat().st_size,
        "sha256": hashlib.sha256(gcode.read_bytes()).hexdigest(),
        "message": "Archie G-code prepared. Upload and physical print are not enabled."
    }
