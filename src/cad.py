
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "generated"


def create_knob(diameter=25, height=15, shaft_diameter=6):
    diameter = float(diameter)
    height = float(height)
    shaft_diameter = float(shaft_diameter)

    if not (10 <= diameter <= 100):
        raise ValueError("Knob diameter must be 10–100 mm.")
    if not (5 <= height <= 60):
        raise ValueError("Knob height must be 5–60 mm.")
    if not (2 <= shaft_diameter < diameter - 4):
        raise ValueError("Invalid shaft diameter.")

    OUTPUT.mkdir(parents=True, exist_ok=True)

    scad = f"""
// MOON MAN AI - PARAMETRIC KNOB
// Units: millimeters
// Prototype: round shaft bore, not a verified spline fit

knob_diameter = {diameter};
knob_height = {height};
shaft_diameter = {shaft_diameter};
clearance = 0.2;

$fn = 96;

difference() {{
    cylinder(d=knob_diameter, h=knob_height);

    translate([0, 0, -0.1])
        cylinder(
            d=shaft_diameter + clearance,
            h=knob_height + 0.2
        );
}}
"""

    version = 1

    while True:
        path = OUTPUT / f"moonman_knob_v{version:03d}.scad"

        try:
            with path.open("x", encoding="utf-8") as file:
                file.write(scad)
            break
        except FileExistsError:
            version += 1

        	

    state = {
        "diameter": diameter,
        "height": height,
        "shaft_diameter": shaft_diameter,
        "file": str(path),
    }

    (OUTPUT / "knob_state.json").write_text(
        __import__("json").dumps(state, indent=2),
        encoding="utf-8",
    )

    return path
if __name__ == "__main__":
    result = create_knob()
    print("MOON MAN CAD GENERATOR")
    print("Created:", result)
    print("Status: awaiting engineering review")

import json

STATE_FILE = OUTPUT / "knob_state.json"


def revise_knob(diameter=None, height=None, shaft_diameter=None):
    if not STATE_FILE.exists():
        raise ValueError(
            "No active knob design. Create a knob first."
        )

    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))

    return create_knob(
        diameter=state["diameter"] if diameter is None else diameter,
        height=state["height"] if height is None else height,
        shaft_diameter=(
            state["shaft_diameter"]
            if shaft_diameter is None
            else shaft_diameter
        ),
    )


