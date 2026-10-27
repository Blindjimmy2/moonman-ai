import re
import sys
from pathlib import Path

ALLOWED = {
    "G1", "G21", "G28", "G29", "G90", "G91", "G92",
    "M83", "M84", "M104", "M106", "M107", "M109",
    "M140", "M190", "M200", "M220", "M221", "M400"
}

def validate(path):
    path = Path(path)

    if not path.is_file():
        raise ValueError("G-code file not found.")

    if path.suffix.lower() != ".gcode":
        raise ValueError("Expected a .gcode file.")

    # MOONMAN_COORDINATE_LIMITS
    bounds = {"X": 300.0, "Y": 300.0, "Z": 400.0}
    position = {"X": 0.0, "Y": 0.0, "Z": 0.0}
    absolute = True
    checked = 0

    for number, line in enumerate(
        path.open(encoding="utf-8-sig", errors="strict"), 1
    ):
        code = line.split(";", 1)[0].strip().upper()

        if not code:
            continue

        match = re.match(r"^([GMT]\d+)(?:\s|$)", code)

        if not match or match.group(1) not in ALLOWED:
            raise ValueError(
                f"Unrecognized command on line {number}: {code[:100]}"
            )

        # PLA temperature safety limits
        command = match.group(1)

        if command in ("M104", "M109", "M140", "M190"):
            temperature_match = re.search(
                r"(?:^|\s)S(-?\d+(?:\.\d+)?)(?=\s|$)",
                code
            )

            if not temperature_match:
                raise ValueError(
                    f"Missing temperature on line {number}"
                )

            temperature = float(temperature_match.group(1))
            maximum = 230 if command in ("M104", "M109") else 75

            if not 0 <= temperature <= maximum:
                raise ValueError(
                    f"Unsafe temperature on line {number}: "
                    f"{command} S{temperature}"
                )

        # Track coordinate mode
        if command == "G90":
            absolute = True

        elif command == "G91":
            absolute = False

        elif command == "G92":
            for axis, value in re.findall(
                r"([XYZ])\s*(-?(?:\d+(?:\.\d*)?|\.\d+))",
                code
            ):
                position[axis] = float(value)

        elif command == "G1":
            for axis, value in re.findall(
                r"([XYZ])\s*(-?(?:\d+(?:\.\d*)?|\.\d+))",
                code
            ):
                value = float(value)
                target = value if absolute else position[axis] + value

                if not 0 <= target <= bounds[axis]:
                    raise ValueError(
                        f"Out-of-bounds movement on line {number}: "
                        f"{axis}={target:.2f} mm "
                        f"(allowed 0-{bounds[axis]:g} mm)"
                    )

                position[axis] = target

        checked += 1

    print(f"MOON MAN: Validated {checked} G-code commands.")
    print("Command allowlist: PASS")
    print("Physical printing remains disabled.")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: gcode_safety.py <file.gcode>")

    validate(sys.argv[1])
