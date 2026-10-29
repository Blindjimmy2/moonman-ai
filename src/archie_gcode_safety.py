from pathlib import Path
import re

ALLOWED = {'MESH_MIN', 'G29', 'G4', 'G0', 'G21', 'M221', 'M84', 'M140', 'G92', 'M109', 'T0', 'G28', 'M205', 'M73', 'M400', 'G91', 'M82', 'G3', 'MESH_MAX', 'START_PRINT', 'EXCLUDE_OBJECT_DEFINE', 'M200', 'M104', 'M106', 'SET_VELOCITY_LIMIT', 'M83', 'BED_MESH_PROFILE', 'G1', 'G90', 'SET_PRESSURE_ADVANCE', 'SET_GCODE_OFFSET', 'M190', 'EXCLUDE_OBJECT_END', 'END_PRINT', 'BED_MESH_CLEAR', 'M220', 'G2', 'EXCLUDE_OBJECT_START', 'M107', 'M204'}
def validate(path):
    path = Path(path)

    if not path.is_file() or path.suffix.lower() != ".gcode":
        raise ValueError("Valid G-code file required")

    bounds = {"X": 220.0, "Y": 220.0, "Z": 250.0}
    position = {"X": 0.0, "Y": 0.0, "Z": 0.0}
    absolute = True
    checked = 0

    for number, line in enumerate(
        path.open(encoding="utf-8-sig", errors="strict"), 1
    ):
        code = line.split(";", 1)[0].strip().upper()
        if not code:
            continue

        command = code.split()[0]

        if command not in ALLOWED:
            raise ValueError(
                f"Unrecognized Archie command on line {number}: {code[:120]}"
            )

        if command in ("M104", "M109", "M140", "M190"):
            match = re.search(r"(?:^|\s)S(-?\d+(?:\.\d+)?)", code)
            if not match:
                raise ValueError(f"Missing temperature on line {number}")

            temperature = float(match.group(1))
            maximum = 300 if command in ("M104", "M109") else 110

            if not 0 <= temperature <= maximum:
                raise ValueError(
                    f"Unsafe Archie temperature on line {number}: {temperature}"
                )

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

        elif command in ("G0", "G1"):
            for axis, value in re.findall(
                r"([XYZ])\s*(-?(?:\d+(?:\.\d*)?|\.\d+))",
                code
            ):
                value = float(value)
                target = value if absolute else position[axis] + value

                if not 0 <= target <= bounds[axis]:
                    raise ValueError(
                        f"Out-of-bounds Archie movement on line {number}: "
                        f"{axis}={target:.2f}"
                    )

                position[axis] = target

        checked += 1

    return {
        "safe": True,
        "printer": "Archie",
        "commands_checked": checked,
        "message": "Archie G-code validation passed."
    }


