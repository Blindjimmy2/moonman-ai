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

    path = OUTPUT / "moonman_knob.scad"
    path.write_text(scad, encoding="utf-8")

    return path


if __name__ == "__main__":
    result = create_knob()
    print("MOON MAN CAD GENERATOR")
    print("Created:", result)
    print("Dimensions: 25 mm diameter x 15 mm height")
    print("Shaft bore: 6.2 mm")
    print("Status: awaiting engineering review")
