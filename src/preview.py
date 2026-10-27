from pathlib import Path
import subprocess
import os

OPENSCAD = Path(r"C:\Program Files (x86)\OpenSCAD\openscad.exe")


def show_design(scad_file):
    scad_file = Path(scad_file).resolve()

    if not scad_file.is_file():
        raise FileNotFoundError(f"CAD file not found: {scad_file}")

    if not OPENSCAD.is_file():
        raise FileNotFoundError(f"OpenSCAD not found: {OPENSCAD}")

    preview_file = scad_file.with_suffix(".png")

    command = [
        str(OPENSCAD),
        "-o", str(preview_file),
        "--imgsize=1000,800",
        "--autocenter",
        "--viewall",
        "--colorscheme=Tomorrow",
        str(scad_file),
    ]

    subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=90,
    )

    if not preview_file.is_file():
        raise RuntimeError("OpenSCAD did not create a preview.")

    os.startfile(str(preview_file))

    return preview_file


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    scad = root / "generated" / "moonman_knob_v006.scad"

    result = show_design(scad)
    print("MOON MAN CAD PREVIEW:", result)
