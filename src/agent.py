import json
import os
import base64
import urllib.request
from collections import deque

from dotenv import load_dotenv
from openai import OpenAI
from pathlib import Path
from memory import remember, recall, correct
from cad import create_knob, revise_knob, STATE_FILE
from preview import show_design
ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

API_KEY = os.getenv("META_API_KEY")
CAMERA_URL = os.getenv(
    "MOONMAN_CAMERA_URL",
    "http://192.168.1.11:8081/1/stream"
)

if not API_KEY:
    raise RuntimeError("META_API_KEY missing from .env")

client = OpenAI(
    base_url="https://api.meta.ai/v1",
    api_key=API_KEY,
    timeout=45.0,
)

SYSTEM_PROMPT = (
    "You are Moon Man, a sarcastic astronaut and engineering "
    "shop coworker. You believe you're an astronaut, not a robot. "
    "Be funny, practical, and concise. "
    "Use prior conversation context to understand follow-up questions. "
    "Only claim visual details supported by the current image. "
    "Never invent measurements or specifications. "
    "Distinguish confirmed facts from visual guesses."
)

CAD_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "create_knob",
            "description": (
                "Generate a parametric OpenSCAD knob from explicit "
                "user-supplied dimensions in millimeters. "
                "Never guess missing dimensions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "diameter": {
                        "type": "number",
                        "description": "Outside diameter in mm"
                    },
                    "height": {
                        "type": "number",
                        "description": "Knob height in mm"
                    },
                    "shaft_diameter": {
                        "type": "number",
                        "description": "Shaft diameter in mm"
                    }
                },
                "required": [
                    "diameter",
                    "height",
                    "shaft_diameter"
                ],
                "additionalProperties": False
            }
        }
    }
,
    {
        "type": "function",
        "function": {
            "name": "revise_knob",
            "description": (
                "Revise the active knob design using NEW TOTAL dimensions "
                "in millimeters. Unspecified dimensions remain unchanged. "
                "For relative requests like '5 mm taller', first calculate "
                "the new total from the active design dimensions provided "
                "in the system context. Never guess dimensions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "diameter": {"type": "number"},
                    "height": {"type": "number"},
                    "shaft_diameter": {"type": "number"}
                },
                "additionalProperties": False
            }
        }
    }
]


history = deque(maxlen=12)


def capture_image():
    print("Moon Man is opening his eyes...")

    with urllib.request.urlopen(CAMERA_URL, timeout=10) as stream:
        buffer = bytearray()

        while len(buffer) < 5_000_000:
            chunk = stream.read(4096)

            if not chunk:
                raise RuntimeError("Camera stream disconnected.")

            buffer.extend(chunk)

            start = buffer.find(b"\xff\xd8")

            if start >= 0:
                end = buffer.find(b"\xff\xd9", start + 2)

                if end >= 0:
                    return bytes(buffer[start:end + 2])

        raise RuntimeError("No JPEG frame found.")



# MOONMAN_FUSION_INTEGRATION_V1
import urllib.request as _moonman_http
import time as _moonman_time

MOONMAN_FUSION_TOOLS = [{'type': 'function', 'function': {'name': 'fusion_create_box', 'description': 'Fusion 360 operation create_box. Requires a running MoonManBridge. Use explicit dimensions in millimeters. Inspect the design before selecting components or edges. Never invent dimensions or geometry. Do not export or print without user approval.', 'parameters': {'type': 'object', 'properties': {'width_mm': {'type': 'number'}, 'depth_mm': {'type': 'number'}, 'height_mm': {'type': 'number'}, 'name': {'type': 'string'}}, 'required': ['width_mm', 'depth_mm', 'height_mm'], 'additionalProperties': False}}}, {'type': 'function', 'function': {'name': 'fusion_create_cylinder', 'description': 'Fusion 360 operation create_cylinder. Requires a running MoonManBridge. Use explicit dimensions in millimeters. Inspect the design before selecting components or edges. Never invent dimensions or geometry. Do not export or print without user approval.', 'parameters': {'type': 'object', 'properties': {'diameter_mm': {'type': 'number'}, 'height_mm': {'type': 'number'}, 'name': {'type': 'string'}}, 'required': ['diameter_mm', 'height_mm'], 'additionalProperties': False}}}, {'type': 'function', 'function': {'name': 'fusion_create_sketch', 'description': 'Fusion 360 operation create_sketch. Requires a running MoonManBridge. Use explicit dimensions in millimeters. Inspect the design before selecting components or edges. Never invent dimensions or geometry. Do not export or print without user approval.', 'parameters': {'type': 'object', 'properties': {'component': {'type': 'string'}, 'shape': {'type': 'string'}, 'name': {'type': 'string'}, 'x_mm': {'type': 'number'}, 'y_mm': {'type': 'number'}, 'width_mm': {'type': 'number'}, 'depth_mm': {'type': 'number'}, 'diameter_mm': {'type': 'number'}}, 'required': [], 'additionalProperties': False}}}, {'type': 'function', 'function': {'name': 'fusion_extrude_profile', 'description': 'Fusion 360 operation extrude_profile. Requires a running MoonManBridge. Use explicit dimensions in millimeters. Inspect the design before selecting components or edges. Never invent dimensions or geometry. Do not export or print without user approval.', 'parameters': {'type': 'object', 'properties': {'component': {'type': 'string'}, 'sketch': {'type': 'string'}, 'profile_index': {'type': 'integer'}, 'distance_mm': {'type': 'number'}, 'operation': {'type': 'string'}}, 'required': ['sketch', 'distance_mm'], 'additionalProperties': False}}}, {'type': 'function', 'function': {'name': 'fusion_create_hole', 'description': 'Fusion 360 operation create_hole. Requires a running MoonManBridge. Use explicit dimensions in millimeters. Inspect the design before selecting components or edges. Never invent dimensions or geometry. Do not export or print without user approval.', 'parameters': {'type': 'object', 'properties': {'component': {'type': 'string'}, 'diameter_mm': {'type': 'number'}, 'depth_mm': {'type': 'number'}, 'x_mm': {'type': 'number'}, 'y_mm': {'type': 'number'}}, 'required': ['diameter_mm', 'depth_mm'], 'additionalProperties': False}}}, {'type': 'function', 'function': {'name': 'fusion_fillet_edges', 'description': 'Fusion 360 operation fillet_edges. Requires a running MoonManBridge. Use explicit dimensions in millimeters. Inspect the design before selecting components or edges. Never invent dimensions or geometry. Do not export or print without user approval.', 'parameters': {'type': 'object', 'properties': {'component': {'type': 'string'}, 'body_index': {'type': 'integer'}, 'edge_indices': {'type': 'array', 'items': {'type': 'integer'}}, 'radius_mm': {'type': 'number'}}, 'required': ['edge_indices', 'radius_mm'], 'additionalProperties': False}}}, {'type': 'function', 'function': {'name': 'fusion_chamfer_edges', 'description': 'Fusion 360 operation chamfer_edges. Requires a running MoonManBridge. Use explicit dimensions in millimeters. Inspect the design before selecting components or edges. Never invent dimensions or geometry. Do not export or print without user approval.', 'parameters': {'type': 'object', 'properties': {'component': {'type': 'string'}, 'body_index': {'type': 'integer'}, 'edge_indices': {'type': 'array', 'items': {'type': 'integer'}}, 'distance_mm': {'type': 'number'}}, 'required': ['edge_indices', 'distance_mm'], 'additionalProperties': False}}}, {'type': 'function', 'function': {'name': 'fusion_inspect_design', 'description': 'Fusion 360 operation inspect_design. Requires a running MoonManBridge. Use explicit dimensions in millimeters. Inspect the design before selecting components or edges. Never invent dimensions or geometry. Do not export or print without user approval.', 'parameters': {'type': 'object', 'properties': {}, 'required': [], 'additionalProperties': False}}}, {'type': 'function', 'function': {'name': 'fusion_export_stl', 'description': 'Fusion 360 operation export_stl. Requires a running MoonManBridge. Use explicit dimensions in millimeters. Inspect the design before selecting components or edges. Never invent dimensions or geometry. Do not export or print without user approval.', 'parameters': {'type': 'object', 'properties': {'component': {'type': 'string'}}, 'required': ['component'], 'additionalProperties': False}}}]

CAD_TOOLS.extend(MOONMAN_FUSION_TOOLS)

def moonman_fusion_command(action, arguments):
    payload = dict(arguments)
    payload["action"] = action

    request = _moonman_http.Request(
        "http://127.0.0.1:8765/command",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with _moonman_http.urlopen(request, timeout=10) as response:
            queued = json.load(response)

        command_id = queued["command_id"]

        for attempt in range(40):
            _moonman_time.sleep(0.25)
            url = "http://127.0.0.1:8765/result/" + command_id
            with _moonman_http.urlopen(url, timeout=5) as response:
                result = json.load(response)

            if result.get("status") != "queued":
                return result

        return {
            "status": "timeout",
            "command_id": command_id,
            "message": "Fusion result pending. Do not assume success."
        }

    except Exception as error:
        return {"status": "error", "error": str(error)}


# MOONMAN_SLICER_TOOL_V1
from slicer import open_stl



from archie_research import archie_list_files, archie_read_file, archie_moonraker_status

CAD_TOOLS.extend([
    {"type":"function","function":{"name":"archie_list_files",
      "description":"List approved Archie printer directories, read-only.",
      "parameters":{"type":"object","properties":{"path":{"type":"string"}}}}},
    {"type":"function","function":{"name":"archie_read_file",
      "description":"Read a limited amount of an approved Archie file.",
      "parameters":{"type":"object","properties":{
        "path":{"type":"string"},"max_bytes":{"type":"integer"}},
        "required":["path"]}}},
    {"type":"function","function":{"name":"archie_moonraker_status",
      "description":"Check Archie's Moonraker service availability.",
      "parameters":{"type":"object","properties":{}}}}
])

CAD_TOOLS.extend([
    {"type":"function","function":{
        "name":"engineering_list",
        "description":"List files in Moon Man's restricted engineering workspace.",
        "parameters":{"type":"object","properties":{
            "path":{"type":"string"}}}
    }},
    {"type":"function","function":{
        "name":"engineering_read",
        "description":"Read a text file from the restricted engineering workspace.",
        "parameters":{"type":"object","properties":{
            "path":{"type":"string"}},"required":["path"]}
    }},
    {"type":"function","function":{
        "name":"engineering_write",
        "description":"Create or update a file in the restricted engineering workspace.",
        "parameters":{"type":"object","properties":{
            "path":{"type":"string"},"content":{"type":"string"}},
            "required":["path","content"]}
    }},
    {"type":"function","function":{
        "name":"engineering_test",
        "description":"Check Python syntax without executing the file.",
        "parameters":{"type":"object","properties":{
            "path":{"type":"string"}},"required":["path"]}
    }}
])

CAD_TOOLS.append({
    "type": "function",
    "function": {
        "name": "open_in_prusaslicer",
        "description": (
            "Open an existing STL file in PrusaSlicer for review. "
            "Use its full path. Does not slice or start printing."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "stl_path": {"type": "string"}
            },
            "required": ["stl_path"],
            "additionalProperties": False
        }
    }
})



# MOONMAN_FUSION_EDIT_V1
MOONMAN_FUSION_TOOLS.extend([
    {
        "type": "function",
        "function": {
            "name": "fusion_inspect_features",
            "description": "Inspect existing extrusion features and sketch circles in a Fusion component before editing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "component": {"type": "string"}
                },
                "required": ["component"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "fusion_edit_extrusion",
            "description": "Change the distance of an existing Fusion extrusion in place. Inspect features first. Do not create a replacement component.",
            "parameters": {
                "type": "object",
                "properties": {
                    "component": {"type": "string"},
                    "feature": {"type": "string"},
                    "distance_mm": {"type": "number"}
                },
                "required": ["component", "feature", "distance_mm"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "fusion_edit_circle",
            "description": "Change the diameter of an existing Fusion sketch circle in place. Inspect features first.",
            "parameters": {
                "type": "object",
                "properties": {
                    "component": {"type": "string"},
                    "sketch": {"type": "string"},
                    "circle_index": {"type": "integer"},
                    "diameter_mm": {"type": "number"}
                },
                "required": ["component", "sketch", "circle_index", "diameter_mm"]
            }
        }
    }
])

# Register Fusion editing tools with the actual Meta tool list.
CAD_TOOLS.extend([
    tool for tool in MOONMAN_FUSION_TOOLS
    if tool["function"]["name"] in (
        "fusion_inspect_features",
        "fusion_edit_extrusion",
        "fusion_edit_circle"
    )
])


# MOONMAN_ENGINEERING_V2_TOOLS
MOONMAN_V2_TOOLS = [{'function': {'description': 'Inspect body bounding boxes, positions and volume. Use before and '
                              'after movement or rotation.',
               'name': 'fusion_inspect_geometry',
               'parameters': {'additionalProperties': False,
                              'properties': {'component': {'type': 'string'}},
                              'required': ['component'],
                              'type': 'object'}},
  'type': 'function'},
 {'function': {'description': 'Translate an existing body in Fusion. Inspect geometry first. '
                              'Movement is relative in millimeters.',
               'name': 'fusion_move_body',
               'parameters': {'additionalProperties': False,
                              'properties': {'body_index': {'type': 'integer'},
                                             'component': {'type': 'string'},
                                             'x_mm': {'type': 'number'},
                                             'y_mm': {'type': 'number'},
                                             'z_mm': {'type': 'number'}},
                              'required': ['component', 'body_index'],
                              'type': 'object'}},
  'type': 'function'},
 {'function': {'description': 'Rotate an existing Fusion body around an X, Y or Z axis. Inspect '
                              'geometry first. Angle is in degrees. Rotation is about the '
                              'specified origin, defaulting to zero.',
               'name': 'fusion_rotate_body',
               'parameters': {'additionalProperties': False,
                              'properties': {'angle_deg': {'type': 'number'},
                                             'axis': {'enum': ['x', 'y', 'z'], 'type': 'string'},
                                             'body_index': {'type': 'integer'},
                                             'component': {'type': 'string'},
                                             'origin_x_mm': {'type': 'number'},
                                             'origin_y_mm': {'type': 'number'},
                                             'origin_z_mm': {'type': 'number'}},
                              'required': ['component', 'body_index', 'axis', 'angle_deg'],
                              'type': 'object'}},
  'type': 'function'},
 {'function': {'description': 'Rename an existing Fusion body without recreating it.',
               'name': 'fusion_rename_body',
               'parameters': {'additionalProperties': False,
                              'properties': {'body_index': {'type': 'integer'},
                                             'component': {'type': 'string'},
                                             'new_name': {'type': 'string'}},
                              'required': ['component', 'body_index', 'new_name'],
                              'type': 'object'}},
  'type': 'function'}]
CAD_TOOLS.extend(MOONMAN_V2_TOOLS)

# MOONMAN_MARVIN_WORKFLOW_V1

# ARCHIE_TOOLS_V1
from archie_workflow import archie_status, prepare_archie_print

CAD_TOOLS.extend([
    {
        "type": "function",
        "function": {
            "name": "archie_status",
            "description": "Read live status and temperatures from Archie, the Creality K1 SE printer.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "prepare_archie_print",
            "description": "Slice an STL for Archie using Creality Print and ASA. Does not upload or start printing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "stl_path": {
                        "type": "string",
                        "description": "Absolute path to an STL in Moon Man's generated folder."
                    }
                },
                "required": ["stl_path"]
            }
        }
    }
])

from marvin_workflow import prepare_marvin_print
from engineering_tools import engineering_list, engineering_read, engineering_write, engineering_test

CAD_TOOLS.append({
    "type": "function",
    "function": {
        "name": "prepare_marvin_print",
        "description": (
            "Slice an existing STL for Marvin using the approved "
            "PrusaSlicer configuration, validate G-code, upload "
            "to OctoPrint without printing, and prepare approval. "
            "Use the exact STL path when known. "
            "Never call this for a request to physically start printing. "
            "Physical printing requires separate explicit confirmation."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "stl_path": {
                    "type": "string",
                    "description": (
                        "Full STL path. Empty string selects the "
                        "newest STL in the generated folder."
                    )
                }
            },
            "required": ["stl_path"],
            "additionalProperties": False
        }
    }
})


# MOONMAN_VOICE_RESTORE_V1
import subprocess as _voice_subprocess
import sys as _voice_sys
import atexit as _voice_atexit

_moonman_voice_process = None

def moonman_say(text):
    global _moonman_voice_process

    if not text or not str(text).strip():
        return

    try:
        if (
            _moonman_voice_process is None
            or _moonman_voice_process.poll() is not None
        ):
            _moonman_voice_process = _voice_subprocess.Popen(
                [
                    str(Path(r"C:\MoonworksDev\moonman-voice-test\Scripts\python.exe")),
                    str(
                        Path(__file__).resolve().parent
                        / "voice_worker.py"
                    )
                ],
                stdin=_voice_subprocess.PIPE,
                text=True,
                encoding="utf-8",
                bufsize=1
            )

        _moonman_voice_process.stdin.write(
            str(text).replace("\\n", " ") + "\\n"
        )
        _moonman_voice_process.stdin.flush()

    except Exception as error:
        print("MOON MAN VOICE ERROR:", error)

def moonman_stop_voice():
    global _moonman_voice_process
    if _moonman_voice_process is not None:
        try:
            _moonman_voice_process.terminate()
        except Exception:
            pass

_voice_atexit.register(moonman_stop_voice)

from archie_diagnostics import archie_inspect, archie_read_logs


CAD_TOOLS.extend([
    {
        "type": "function",
        "function": {
            "name": "archie_inspect",
            "description": "Read-only Archie K1 SE WebSocket telemetry and printer information. Never sends control commands.",
            "parameters": {
                "type": "object",
                "properties": {
                    "seconds": {"type": "integer"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "archie_read_logs",
            "description": "Read-only Archie Klipper log retrieval over noninteractive SSH. No printer commands.",
            "parameters": {
                "type": "object",
                "properties": {
                    "lines": {"type": "integer"}
                }
            }
        }
    }
])


# MOONMAN_ARCHIE_START_INTEGRATION_V1
from archie_start_print import archie_start_print as _archie_start_print

CAD_TOOLS.append({
    "type": "function",
    "function": {
        "name": "archie_start_print",
        "description": (
            "Request physical printing of an existing G-code file on Archie. "
            "Use only after the user explicitly asks to print. "
            "The tool requires a separate human approval in the local terminal. "
            "Never claim printing started until the printer status confirms it."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Exact basename of the G-code file already uploaded to Archie."
                }
            },
            "required": ["filename"],
            "additionalProperties": False
        }
    }
})


# MOONMAN_ARCHIE_UPLOAD_INTEGRATION_V1
from archie_upload import archie_upload_gcode

CAD_TOOLS.append({
    "type": "function",
    "function": {
        "name": "archie_upload_gcode",
        "description": (
            "Upload an existing validated G-code file to Archie. "
            "Verify filename and size on the printer. "
            "Does not start printing. "
            "After verified upload, physical print start requires "
            "separate explicit human approval."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "gcode_path": {"type": "string"}
            },
            "required": ["gcode_path"]
        }
    }
})

def ask_moonman(question):
    # Explicit approval for the pending, verified Marvin job.
    command = question.strip().lower()
    if command in ("confirm print", "yes print", "yes print it", "yes, print it", "print it"):
        try:
            from print_approval import confirm_print
            confirm_print()
            return ("Print start accepted by OctoPrint for the approved "
                    "Marvin job. Monitor the first layer.")
        except Exception as error:
            return f"Print not started or start unconfirmed: {error}"

    lower = question.lower().strip()

    # Explicit memory commands: remember SUBJECT: FACT
    if lower.startswith("remember "):
        payload = question[9:].strip()

        if ":" not in payload:
            return (
                "Give me a subject and fact, cadet. "
                "Example: remember Gumbling Machine: "
                "The white gear belongs to this project."
            )

        subject, fact = payload.split(":", 1)
        subject = subject.strip()
        fact = fact.strip()

        if not subject or not fact:
            return "I need both a subject and a fact, Houston."

        return remember(subject, fact)

    # Explicit correction: correct SUBJECT: OLD FACT -> NEW FACT
    if lower.startswith("correct "):
        payload = question[8:].strip()

        if ":" not in payload or "->" not in payload:
            return (
                "Use: correct SUBJECT: OLD FACT -> NEW FACT"
            )

        subject, change = payload.split(":", 1)
        old_fact, new_fact = change.split("->", 1)

        return correct(
            subject.strip(),
            old_fact.strip(),
            new_fact.strip()
        )
    # Explicit memory lookup: recall SUBJECT
    if lower.startswith("recall "):
        subject = question[7:].strip()

        if not subject:
            return "What am I supposed to remember, Houston?"

        facts = recall(subject)

        if not facts:
            return f"No stored memories found for {subject}."

        return "Here's what I remember:\n" + "\n".join(
            f"- {fact}" for fact in facts
        )

    # Ordinary conversation gets relevant stored facts
    stored_facts = []
    words = [
        word.strip(".,?!:;")
        for word in question.split()
        if len(word.strip(".,?!:;")) >= 5
    ]

    for word in words[:5]:
        for fact in recall(word):
            if fact not in stored_facts:
                stored_facts.append(fact)

    memory_context = (
        "\n".join(f"- {fact}" for fact in stored_facts[:10])
        if stored_facts
        else "No relevant stored facts found."
    )
    cad_context = "No active CAD design."

    if STATE_FILE.exists():
        import json

        state = json.loads(
            STATE_FILE.read_text(encoding="utf-8")
        )

        cad_context = (
            "ACTIVE KNOB DESIGN:\n"
            f"Diameter: {state['diameter']} mm\n"
            f"Height: {state['height']} mm\n"
            f"Shaft diameter: {state['shaft_diameter']} mm\n"
            f"File: {state['file']}\n"
            "For relative revisions, calculate the NEW TOTAL "
            "dimension before calling revise_knob. "
            "Preserve all unspecified dimensions."
        )
    # MOONMAN_MULTI_TOOL_LOOP_V2
    print("Moon Man is thinking...")
    messages = [{
        "role": "system",
        "content": SYSTEM_PROMPT +
            "\nRelevant stored memories:\n" + memory_context +
            "\n\nCurrent CAD state:\n" + cad_context +
            "\nExecute sequential engineering tools using their actual results. "
            "Do not invent paths, geometry, measurements, or successful actions. "
            "Only export STL when the user requests it or asks to prepare a print. "
            "Preparing a print may slice, validate, and upload G-code but NEVER "
            "starts a physical print. Never claim a printer was started. "
            "If a tool reports an error, stop and explain it."
    }]
    messages.extend(history)
    user_content = [{"type": "text", "text": question}]
    try:
        encoded = base64.b64encode(capture_image()).decode("ascii")
        user_content.append({"type": "image_url", "image_url": {
            "url": "data:image/jpeg;base64," + encoded}})
    except Exception as error:
        print("Camera unavailable; continuing with text:", error)
    messages.append({"role": "user", "content": user_content})

    max_rounds = 8
    max_tool_calls = 20
    tool_count = 0
    answer = ""
    for round_number in range(max_rounds):
        response = client.chat.completions.create(
            model="muse-spark-1.3", messages=messages,
            tools=CAD_TOOLS, tool_choice="auto")
        message = response.choices[0].message
        calls = message.tool_calls or []
        if not calls:
            answer = message.content or "Done. No additional tool calls requested."
            break
        messages.append({
            "role": "assistant", "content": message.content,
            "tool_calls": [c.model_dump(exclude_none=True) for c in calls]
        })
        error_result = None
        for call in calls:
            tool_count += 1
            if tool_count > max_tool_calls:
                error_result = "Stopped: too many tool calls."
                break
            name = call.function.name
            try:
                args = json.loads(call.function.arguments or "{}")
                if not isinstance(args, dict):
                    raise ValueError("Tool arguments must be an object")
                if name == "open_in_prusaslicer":
                    result = {"status": "ok", "result": open_stl(args.get("stl_path", ""))}
                elif name == "archie_start_print":
                    filename = args.get("filename", "")
                    from archie_start_print import build_start_command
                    command = build_start_command(filename)

                    print("\n" + "=" * 55, flush=True)
                    print("MOON MAN REQUESTS PERMISSION TO START ARCHIE", flush=True)
                    print("FILE:", filename, flush=True)
                    print("COMMAND:", command["params"]["opGcodeFile"], flush=True)
                    print("WARNING: Approval will physically start the printer.", flush=True)
                    print("=" * 55, flush=True)

                    approval = input(
                        "TYPE START ARCHIE TO AUTHORIZE (anything else cancels): "
                    ).strip()

                    if approval == "START ARCHIE":
                        result = _archie_start_print(filename, approved=True)
                    else:
                        result = {
                            "status": "cancelled",
                            "printer": "Archie",
                            "filename": filename,
                            "message": "Human did not approve print start."
                        }
                elif name == "archie_upload_gcode":
                    result = archie_upload_gcode(args.get("gcode_path", ""))
                elif name == "archie_status":
                    result = archie_status()
                elif name == "prepare_archie_print":
                    result = prepare_archie_print(args.get("stl_path", ""))
                elif name == "archie_inspect":
                    result = archie_inspect(args.get("seconds", 8))
                elif name == "archie_list_files":
                    result = archie_list_files(args.get("path", "/usr/data/printer_data/gcodes/"))
                elif name == "archie_read_file":
                    result = archie_read_file(args.get("path", ""), args.get("max_bytes", 12000))
                elif name == "archie_moonraker_status":
                    result = archie_moonraker_status()
                elif name == "archie_read_logs":
                    result = archie_read_logs(args.get("lines", 80))
                elif name == "engineering_list":
                    result = engineering_list(args.get("path", "."))
                elif name == "engineering_read":
                    result = engineering_read(args.get("path", ""))
                elif name == "engineering_write":
                    result = engineering_write(args.get("path", ""), args.get("content", ""))
                elif name == "engineering_test":
                    result = engineering_test(args.get("path", ""))
                elif name == "prepare_marvin_print":
                    result = prepare_marvin_print(args.get("stl_path", ""))
                elif name.startswith("fusion_"):
                    action = name[len("fusion_"):]
                    allowed = {"create_box", "create_cylinder", "create_sketch",
                               "extrude_profile", "create_hole", "fillet_edges",
                               "chamfer_edges", "inspect_design", "export_stl",
                           "inspect_features", "edit_extrusion", "edit_circle",
                           "inspect_geometry", "move_body", "rotate_body", "rename_body"}
                    if action not in allowed:
                        raise ValueError("Unknown Fusion action: " + action)
                    result = moonman_fusion_command(action, args)
                elif name == "create_knob":
                    required = ("diameter", "height", "shaft_diameter")
                    if any(k not in args for k in required):
                        raise ValueError("Missing knob dimensions")
                    path = create_knob(**{k: args[k] for k in required})
                    show_design(path)
                    result = {"status": "ok", "file": str(path),
                              "message": "Awaiting engineering review; not printed"}
                elif name == "revise_knob":
                    path = revise_knob(
                        diameter=args.get("diameter"),
                        height=args.get("height"),
                        shaft_diameter=args.get("shaft_diameter"))
                    show_design(path)
                    result = {"status": "ok", "file": str(path),
                              "message": "Previous version preserved; not printed"}
                else:
                    raise ValueError("Unknown tool: " + name)
                if not isinstance(result, dict):
                    result = {"result": str(result)}
            except Exception as error:
                result = {"status": "error", "error": str(error)}
            print("TOOL", name, json.dumps(result, default=str))
            messages.append({"role": "tool", "tool_call_id": call.id,
                             "content": json.dumps(result, default=str)})
            if result.get("status") in ("error", "timeout", "failed") or result.get("success") is False:
                error_result = name + " failed: " + json.dumps(result, default=str)
                break
        if error_result:
            answer = error_result + "\nStopped without requesting further actions."
            break
    else:
        answer = "Stopped at the eight-round safety limit. Review the last tool results before continuing."

    history.append({"role": "user", "content": question})
    history.append({"role": "assistant", "content": answer})
    return answer


if __name__ == "__main__":
    print("MOON MAN AI â€” LIVE VISION + MEMORY")
    print("Commands: remember SUBJECT: FACT | recall SUBJECT | exit")

    while True:
        try:
            question = input("\nYOU: ").strip()

            if question.lower() in ("exit", "quit"):
                break

            if not question:
                continue

            answer = ask_moonman(question)

            print("\nMOON MAN:")
            print(answer)
            moonman_say(answer)

        except KeyboardInterrupt:
            break
        except Exception as error:
            print(f"\nError: {error}")




