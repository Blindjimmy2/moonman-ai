
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GENERATED = (ROOT / "generated").resolve()

EXE = Path(
    r"C:\Program Files\Prusa3D\PrusaSlicer\prusa-slicer.exe"
)

def open_stl(stl_path):
    path = Path(stl_path).resolve()

    if not path.is_file() or path.suffix.lower() != ".stl":
        raise ValueError("Valid STL required.")

    if not path.is_relative_to(GENERATED):
        raise ValueError("STL must be in generated directory.")

    subprocess.Popen([str(EXE), str(path)])

    return "PrusaSlicer launch requested for " + path.name
