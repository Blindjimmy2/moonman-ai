
from pathlib import Path
import subprocess
import uuid

ROOT = Path(__file__).resolve().parent.parent
GENERATED = (ROOT / "generated").resolve()
CONFIG = ROOT / "config" / "longer_full.ini"
SLICER = Path(
    r"C:\Program Files\Prusa3D\PrusaSlicer\prusa-slicer-console.exe"
)

def prepare_marvin_print(stl_path):
    from gcode_safety import validate
    from printer import upload_gcode
    from print_approval import prepare_print

    if stl_path:
        stl = Path(stl_path).resolve()
    else:
        files = sorted(
            GENERATED.glob("*.stl"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )
        if not files:
            raise RuntimeError("No STL files found.")
        stl = files[0].resolve()

    if not stl.is_file() or stl.suffix.lower() != ".stl":
        raise ValueError("Valid STL required.")

    if not stl.is_relative_to(GENERATED):
        raise ValueError("STL must be inside generated folder.")

    if not CONFIG.is_file() or not SLICER.is_file():
        raise RuntimeError("Marvin slicer configuration missing.")

    output = GENERATED / (
        stl.stem + "_" + uuid.uuid4().hex[:8] + ".gcode"
    )

    result = subprocess.run(
        [
            str(SLICER),
            "--load", str(CONFIG),
            "--export-gcode",
            "--output", str(output),
            str(stl)
        ],
        capture_output=True,
        text=True,
        timeout=300,
        check=False
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Slicing failed: " + result.stderr[-1500:]
        )

    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError("Slicer produced no G-code.")

    validate(output)

    # Upload only. Never select or start printing.
    upload_gcode(output)

    # Create approval record after successful upload.
    prepare_print(output)

    return {
        "status": "awaiting_approval",
        "stl": str(stl),
        "gcode": str(output),
        "size_bytes": output.stat().st_size,
        "printer": "Marvin - Longer LK5 Pro",
        "physical_print_started": False
    }
