import json
import os
import re
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


VISION_IMAGE_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}
MAX_VISION_IMAGES = 4
MAX_VISION_IMAGE_BYTES = 10_000_000


def find_image_paths(question):
    """Return existing image files named in the question, in order."""
    text = question or ""
    candidates = [match.group(1)
                  for match in re.finditer(r'"([^"]+)"', text)]
    candidates.extend(
        match.group(0) for match in re.finditer(
            r"[A-Za-z]:[\\/][^\n\"']+?\.(?:jpg|jpeg|png|gif|webp|bmp)\b"
            r"|/[^\n\"']+?\.(?:jpg|jpeg|png|gif|webp|bmp)\b",
            text, re.IGNORECASE))
    found = []
    for candidate in candidates:
        path = candidate.strip()
        if not path or path in found:
            continue
        if (os.path.splitext(path)[1].lower() in VISION_IMAGE_TYPES
                and os.path.isfile(path)):
            found.append(path)
    return found[:MAX_VISION_IMAGES]


def attach_file_images(user_content, question):
    """Append image_url parts for image files named in the question."""
    attached = []
    for path in find_image_paths(question):
        try:
            if os.path.getsize(path) > MAX_VISION_IMAGE_BYTES:
                print("Image skipped (over size limit):", path)
                continue
            with open(path, "rb") as handle:
                encoded = base64.b64encode(handle.read()).decode("ascii")
        except OSError as error:
            print("Image skipped (unreadable %s): %s" % (path, error))
            continue
        mime = VISION_IMAGE_TYPES[os.path.splitext(path)[1].lower()]
        user_content.append({"type": "image_url", "image_url": {
            "url": "data:%s;base64,%s" % (mime, encoded)}})
        attached.append(path)
    if attached:
        print("Moon Man is looking at file(s):", ", ".join(attached))
    return attached



# MOONMAN_FUSION_INTEGRATION_V1
import urllib.request as _moonman_http
import time as _moonman_time

MOONMAN_FUSION_TOOLS = [{'type': 'function', 'function': {'name': 'fusion_create_box', 'description': 'Fusion 360 operation create_box. Requires a running MoonManBridge. Use explicit dimensions in millimeters. Inspect the design before selecting components or edges. Never invent dimensions or geometry. Do not export or print without user approval.', 'parameters': {'type': 'object', 'properties': {'width_mm': {'type': 'number'}, 'depth_mm': {'type': 'number'}, 'height_mm': {'type': 'number'}, 'name': {'type': 'string'}}, 'required': ['width_mm', 'depth_mm', 'height_mm'], 'additionalProperties': False}}}, {'type': 'function', 'function': {'name': 'fusion_create_cylinder', 'description': 'Fusion 360 operation create_cylinder. Requires a running MoonManBridge. Use explicit dimensions in millimeters. Inspect the design before selecting components or edges. Never invent dimensions or geometry. Do not export or print without user approval.', 'parameters': {'type': 'object', 'properties': {'diameter_mm': {'type': 'number'}, 'height_mm': {'type': 'number'}, 'name': {'type': 'string'}}, 'required': ['diameter_mm', 'height_mm'], 'additionalProperties': False}}}, {'type': 'function', 'function': {'name': 'fusion_create_sketch', 'description': 'Fusion 360 operation create_sketch. Requires a running MoonManBridge. Use explicit dimensions in millimeters. Inspect the design before selecting components or edges. Never invent dimensions or geometry. Do not export or print without user approval.', 'parameters': {'type': 'object', 'properties': {'component': {'type': 'string'}, 'shape': {'type': 'string'}, 'name': {'type': 'string'}, 'x_mm': {'type': 'number'}, 'y_mm': {'type': 'number'}, 'width_mm': {'type': 'number'}, 'depth_mm': {'type': 'number'}, 'diameter_mm': {'type': 'number'}}, 'required': [], 'additionalProperties': False}}}, {'type': 'function', 'function': {'name': 'fusion_extrude_profile', 'description': 'Fusion 360 operation extrude_profile. Requires a running MoonManBridge. Use explicit dimensions in millimeters. Inspect the design before selecting components or edges. Never invent dimensions or geometry. Do not export or print without user approval.', 'parameters': {'type': 'object', 'properties': {'component': {'type': 'string'}, 'sketch': {'type': 'string'}, 'profile_index': {'type': 'integer'}, 'distance_mm': {'type': 'number'}, 'operation': {'type': 'string'}}, 'required': ['sketch', 'distance_mm'], 'additionalProperties': False}}}, {'type': 'function', 'function': {'name': 'fusion_create_hole', 'description': 'Fusion 360 operation create_hole. Requires a running MoonManBridge. Use explicit dimensions in millimeters. Inspect the design before selecting components or edges. Never invent dimensions or geometry. Do not export or print without user approval.', 'parameters': {'type': 'object', 'properties': {'component': {'type': 'string'}, 'diameter_mm': {'type': 'number'}, 'depth_mm': {'type': 'number'}, 'x_mm': {'type': 'number'}, 'y_mm': {'type': 'number'}, 'plane': {'type': 'string', 'description': "Sketch plane, verified live: 'xy' (default): center at world (x_mm, y_mm), cuts one-sided +Z by depth_mm. 'xz': center at world X=x_mm, Z=y_mm, cuts symmetric +-depth_mm about the y=0 plane. 'yz': center at world Y=x_mm, Z=y_mm, cuts symmetric +-depth_mm about the x=0 plane. Cut applies to every body in the component it intersects. Returns volume_change_mm3: negative means material removed; exactly 0.0 means MISS (circle hit no body — never treat a MISS as a hole)."}}, 'required': ['diameter_mm', 'depth_mm'], 'additionalProperties': False}}}, {'type': 'function', 'function': {'name': 'fusion_fillet_edges', 'description': 'Fusion 360 operation fillet_edges. Requires a running MoonManBridge. Use explicit dimensions in millimeters. Inspect the design before selecting components or edges. Never invent dimensions or geometry. Do not export or print without user approval.', 'parameters': {'type': 'object', 'properties': {'component': {'type': 'string'}, 'body_index': {'type': 'integer'}, 'edge_indices': {'type': 'array', 'items': {'type': 'integer'}}, 'radius_mm': {'type': 'number'}}, 'required': ['edge_indices', 'radius_mm'], 'additionalProperties': False}}}, {'type': 'function', 'function': {'name': 'fusion_chamfer_edges', 'description': 'Fusion 360 operation chamfer_edges. Requires a running MoonManBridge. Use explicit dimensions in millimeters. Inspect the design before selecting components or edges. Never invent dimensions or geometry. Do not export or print without user approval.', 'parameters': {'type': 'object', 'properties': {'component': {'type': 'string'}, 'body_index': {'type': 'integer'}, 'edge_indices': {'type': 'array', 'items': {'type': 'integer'}}, 'distance_mm': {'type': 'number'}}, 'required': ['edge_indices', 'distance_mm'], 'additionalProperties': False}}}, {'type': 'function', 'function': {'name': 'fusion_inspect_design', 'description': 'Fusion 360 operation inspect_design. Requires a running MoonManBridge. Use explicit dimensions in millimeters. Inspect the design before selecting components or edges. Never invent dimensions or geometry. Do not export or print without user approval.', 'parameters': {'type': 'object', 'properties': {}, 'required': [], 'additionalProperties': False}}}, {'type': 'function', 'function': {'name': 'fusion_export_stl', 'description': 'Fusion 360 operation export_stl. Requires a running MoonManBridge. Use explicit dimensions in millimeters. Inspect the design before selecting components or edges. Never invent dimensions or geometry. Do not export or print without user approval.', 'parameters': {'type': 'object', 'properties': {'component': {'type': 'string'}}, 'required': ['component'], 'additionalProperties': False}}}]

MOONMAN_FUSION_TOOLS.append({
    "type": "function",
    "function": {
        "name": "fusion_export_body",
        "description": (
            "Export exactly one existing Fusion solid body as STL without "
            "modifying the source design. Inspect the design to identify "
            "the correct component and body. Use body_index if names are "
            "ambiguous. Do not print without explicit user approval."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "component": {"type": "string"},
                "body": {"type": "string"},
                "body_index": {"type": "integer"}
            },
            "required": ["component"],
            "additionalProperties": False
        }
    }
})


CAD_TOOLS.extend(MOONMAN_FUSION_TOOLS)

def moonman_fusion_command(action, arguments):
    denial = _check_owned(action, arguments)
    if denial is not None:
        return denial
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
                if action in ("create_box", "create_cylinder"):
                    created = result.get("result") or {}
                    if isinstance(created, dict):
                        _register_owned(created.get("component", ""))
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


# MOONMAN_TRACK_V1: gaze tools. The tracker daemon (moonman_track.py) owns
# servo motion; these tools just publish targets over MQTT (one-shot, the
# agent keeps no persistent MQTT client). After a successful gaze move the
# tool loop appends a fresh helmet-cam frame so the model can refine.
_TRACK_BROKER = os.environ.get("MOONMAN_BROKER", "192.168.1.11")
_TRACK_PORT = int(os.environ.get("MOONMAN_MQTT_PORT", "1883"))
GAZE_MOVE_TOOLS = ("gaze_point", "look_at")

def _track_pub(topic, payload):
    try:
        import paho.mqtt.client as mqtt_mod
    except ImportError:
        print("Track publish failed: paho-mqtt missing")
        return False
    try:
        try:
            client = mqtt_mod.Client(mqtt_mod.CallbackAPIVersion.VERSION2)
        except Exception:
            client = mqtt_mod.Client()
        client.connect(_TRACK_BROKER, _TRACK_PORT, keepalive=5)
        if not isinstance(payload, str):
            payload = json.dumps(payload)
        client.publish(topic, payload)
        client.disconnect()
        return True
    except Exception as error:
        print("Track publish failed:", error)
        return False

def _track_get(timeout=3.0):
    try:
        import paho.mqtt.client as mqtt_mod
    except ImportError:
        return None
    box = {}
    try:
        try:
            client = mqtt_mod.Client(mqtt_mod.CallbackAPIVersion.VERSION2)
        except Exception:
            client = mqtt_mod.Client()
        def on_message(_c, _u, m):
            try:
                box["status"] = json.loads(m.payload.decode("utf-8", "replace"))
            except Exception:
                pass
            box["got"] = True
        client.on_message = on_message
        client.connect(_TRACK_BROKER, _TRACK_PORT, keepalive=5)
        client.subscribe("moonman/track/status")
        client.loop_start()
        waited = 0.0
        while waited < timeout and "got" not in box:
            _moonman_time.sleep(0.1)
            waited += 0.1
        client.loop_stop()
        client.disconnect()
    except Exception as error:
        print("Track status read failed:", error)
        return None
    return box.get("status")

def _track_append_fresh_view(messages, turn_log):
    moves = sum(1 for entry in turn_log if entry[0] in GAZE_MOVE_TOOLS)
    if moves > 3:
        return
    try:
        _moonman_time.sleep(0.6)  # let the head arrive
        frame = capture_image()
    except Exception as error:
        print("Gaze view skipped:", error)
        return
    try:
        gaze = _track_get() or {}
        where = "gaze now (%s,%s)" % (gaze.get("pan"), gaze.get("tilt"))
    except Exception:
        where = "gaze unknown"
    encoded = base64.b64encode(frame).decode("ascii")
    messages.append({"role": "user", "content": [
        {"type": "text", "text": "Head moved (%s). Fresh helmet-cam view:" % where},
        {"type": "image_url", "image_url": {
            "url": "data:image/jpeg;base64," + encoded}}]})
    print("Moon Man glanced somewhere new.")

MOONMAN_TRACK_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "gaze_point",
            "description": (
                "Turn Moon Man's helmet toward a target visible in the "
                "helmet-cam image. x,y are FRACTIONS of image width and "
                "height (0.0-1.0) where the target appears: x=0 is frame "
                "left, y=0 is frame top. After each move you get a fresh "
                "helmet-cam view automatically; call again to refine "
                "(max 3 per turn). Use for 'look at the "
                "printer/door/person'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "number"},
                    "y": {"type": "number"}
                },
                "required": ["x", "y"],
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "look_at",
            "description": (
                "Point Moon Man's helmet to absolute angles. pan 0-180 "
                "(0 left, 90 center, 180 right), tilt 45-135 (45 up, 90 "
                "center, 135 down). Use for 'look left/right/up/down/center'. Prefer gaze_point when you can see "
                "the target in the helmet-cam image."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pan": {"type": "number"},
                    "tilt": {"type": "number"}
                },
                "required": ["pan", "tilt"],
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "track_mode",
            "description": (
                "Idle head behavior. auto: gentle wander and slow drift "
                "back to center when idle. still: hold the current "
                "position."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {"type": "string"}
                },
                "required": ["mode"],
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_gaze",
            "description": (
                "Read the helmet's current pan/tilt angles and idle mode."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False
            }
        }
    }
]
CAD_TOOLS.extend(MOONMAN_TRACK_TOOLS)

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
            str(text).replace("\n", " ") + "\n"
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

# MOONMAN_WEB_RESEARCH_V1
from web_research import web_research

# MOONMAN_PROJECT_MEMORY_V1
from project_memory import (
    detect_project, set_active_project, get_active_project,
    recall_facts, project_brief, write_checkpoint,
    tool_project_recall, tool_project_checkpoint, tool_project_remember,
)

# MOONMAN_TRACK2_CLIENT_V1
COMPONENT_REGISTRY = ROOT / "config" / "moonman_components.json"

SCOPED_WRITE_ACTIONS = frozenset({
    "create_hole", "fillet_edges", "chamfer_edges", "edit_extrusion",
    "edit_circle", "move_body", "rotate_body", "rename_body",
    "delete_body", "delete_feature", "delete_sketch",
    "extrude_profile", "create_sketch", "align_bodies",
})


def _load_owned():
    try:
        data = json.loads(COMPONENT_REGISTRY.read_text(encoding="utf-8"))
        owned = data.get("owned", [])
        return {str(name) for name in owned if isinstance(name, str)}
    except Exception:
        return set()


def _register_owned(name):
    try:
        owned = _load_owned()
        if name and name not in owned:
            owned.add(name)
            COMPONENT_REGISTRY.parent.mkdir(parents=True, exist_ok=True)
            COMPONENT_REGISTRY.write_text(
                json.dumps({"owned": sorted(owned)}, indent=2),
                encoding="utf-8")
    except Exception as error:
        print("Component registry update failed:", error)


def _unregister_owned(name):
    owned = _load_owned()
    if name not in owned:
        return False
    owned.discard(name)
    COMPONENT_REGISTRY.write_text(
        json.dumps({"owned": sorted(owned)}, indent=2),
        encoding="utf-8")
    return True


def _check_owned(action, arguments):
    if action not in SCOPED_WRITE_ACTIONS:
        return None
    name = arguments.get("component", "")
    if name in _load_owned():
        return None
    return {
        "status": "error",
        "error": (
            "Component %r is not Moon Man-owned. Ask the user to grant it "
            "with: moonman owns %s" % (name, name)),
    }

# MOONMAN_AUTONOMY_O1O3_V1
OBJECTIVE_FILE = ROOT / "moonman_engineering" / "active_objective.md"
OBJECTIVE_DIR = ROOT / "moonman_engineering" / "objectives"
MAX_OBJECTIVE_CHARS = 2000
MAX_OUTCOME_CHARS = 1500

RETRYABLE_READ_TOOLS = frozenset({
    "engineering_list", "engineering_read", "engineering_test",
    "archie_list_files", "archie_read_file", "archie_moonraker_status",
    "archie_inspect", "archie_read_logs", "archie_status",
    "fusion_inspect_design", "fusion_inspect_features",
    "fusion_inspect_geometry", "web_research", "project_recall",
    "project_checkpoint",
    "fusion_document_info", "fusion_check_clearance",
    "fusion_interference_check",
})

AUTONOMY_DIRECTIVE = (
    "\nEngineering autonomy protocol:\n"
    "- For a high-level engineering objective: keep a short numbered plan, work it "
    "stepwise with real tool results, inspect to verify, and continue across turns "
    "until the design is coherent or you are genuinely blocked.\n"
    "- Maintain the per-project engineering scratchpad via engineering_write to "
    "'objectives/<project>.md' (active project shown above; paths are relative to the "
    "engineering workspace root -- never prefix with 'moonman_engineering/'): objective, "
    "plan checklist, key dimensions with provenance, artifact paths, blockers. Read it "
    "back with engineering_read('objectives/<project>.md'). Keep it under ~2 KB. It and "
    "the turn-outcome records are your memory across turns and restarts; resume "
    "from them without re-asking.\n"
    "- Label claims: VERIFIED (seen in tool output this session), PLAN (intended "
    "steps), UNVERIFIED (inference or web research -- never use as manufacturing "
    "dimensions), BLOCKED (needs a human).\n"
    "- If an inspection or read tool fails, retry with corrected input or an "
    "alternative check; never build dependent geometry on assumed state -- mark "
    "BLOCKED if the check cannot be satisfied.\n"
    "- On resume ('continue', new session, new project): re-verify cited files and "
    "Fusion bodies (filesystem check / fusion_inspect_*) before asserting they "
    "exist; mark missing ones STALE in scratchpad and checkpoint; never present "
    "unchecked stored dimensions as current.\n"
    "- After every hole or cut, check volume_change_mm3: 0.0 means the cut "
    "missed everything -- inspect, adjust, retry, and delete the no-op "
    "feature and sketch. Never assume a reported success removed material.\n"
    "- Fusion turns are pinned to one document: if the active design changes "
    "mid-turn the turn halts -- tell the user and stop.\n"
    "- You may only modify Moon Man-owned components (registry). Reads, "
    "clearance checks, and exports may reference any component. If a write is "
    "refused, ask the user to grant it with 'moonman owns NAME'.\n"
    "- Ask the human only when an essential requirement is missing, a meaningful "
    "tradeoff decision is needed, or approval is required. Never re-ask settled "
    "matters.\n"
    "- You have at most 8 tool rounds per turn. Pace multi-stage work; if cut off, "
    "the next turn continues from the outcome record -- end plateaued turns with "
    "PROGRESS and NEXT lines.\n"
    "- Research-before-escalation ladder R1-R5: before asking the human about "
    "any missing dimension, spec, or blocker, walk (R1) project memory -- "
    "project_recall including deadend: entries, plus engineering_list/read for "
    "BOMs and docs; (R2) web_research for technical references (stays "
    "UNVERIFIED, keep citations); (R3) fusion_inspect_*/clearance/interference "
    "to measure existing geometry and constraints; (R4) calculate, bound with "
    "stated uncertainty, or frame a reversible assumption; (R5) decide: act, "
    "or escalate with a record.\n"
    "- Decision classes: ACT on verified memory or measured geometry, then "
    "verify the result. ASSUME only reversible low-risk items: record via "
    "project_remember with status assumption, stated uncertainty, and how you "
    "will verify -- then verify. Never fabricate dimensions, never present "
    "web data as manufacturer specs, never report inferred fits as "
    "validated.\n"
    "- Before every hole or cut, predict the expected volume_change_mm3 from "
    "the geometry; after the cut, flag any mismatch beyond 0.1 and "
    "investigate before proceeding.\n"
    "- Never re-search a settled question: check deadend: facts first, and "
    "record new dead ends as failed facts with sources tried, conflicts, and "
    "confidence.\n"
    "- End EVERY runner turn with a footer line, exactly one of: RUN: done "
    "(objective complete), RUN: continue (more turns needed), RUN: "
    "needs_human (blocked on a human). With needs_human, append a record:\n"
    "ESCALATION:\n"
    "question: <single question>\n"
    "kind: <ordinary|design_intent|safety|authorization|irreversible>\n"
    "checked:\n"
    "- memory: <query> -> <result>\n"
    "- web: <query> -> <result>\n"
    "- geometry: <inspection> -> <result>\n"
    "conflicts: <none|describe>\n"
    "confidence: <low|medium|high>\n"
    "why_human: <reason>\n"
    "Ordinary questions need evidence of at least two ladder avenues "
    "actually checked (code verifies this against the turn record); safety, "
    "authorization, and irreversible stops are accepted immediately."
)


def read_objective(project="general"):
    try:
        safe = project if (project or "").isidentifier() else "general"
        path = OBJECTIVE_DIR / (safe + ".md")
        if not path.is_file():
            path = OBJECTIVE_FILE
        if not path.is_file():
            return "None recorded."
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return "None recorded."
        if len(text) > MAX_OBJECTIVE_CHARS:
            return text[:MAX_OBJECTIVE_CHARS] + "\n[truncated]"
        return text
    except Exception:
        return "None recorded."


def _short_result(name, args, result):
    if not isinstance(result, dict):
        return "[VERIFIED] %s: %s" % (name, str(result)[:140])
    status = result.get("status")
    if status in ("error", "timeout", "failed") or result.get("success") is False:
        detail = str(result.get("error", "")) or json.dumps(result, default=str)
        return "[FAILED] %s: %s" % (name, detail[:140])
    if name == "web_research":
        cites = result.get("citations", [])
        count = len(cites) if isinstance(cites, list) else 0
        return (
            "[UNVERIFIED] %s: search_occurred=%s, citations=%d (research only)"
            % (name, result.get("search_occurred"), count)
        )
    if name in ("prepare_marvin_print", "prepare_archie_print"):
        target = result.get("gcode", "") or result.get("stl", "")
        return "[VERIFIED] %s: %s file=%s print_started=%s" % (
            name, status,
            Path(target).name if target else "?",
            result.get("physical_print_started", False),
        )
    if name in ("archie_upload_gcode", "archie_start_print"):
        return "[VERIFIED] %s: %s file=%s" % (
            name, status, result.get("filename", "?"))
    if name in ("create_knob", "revise_knob"):
        target = result.get("file", "")
        return "[VERIFIED] %s: file=%s" % (
            name, Path(target).name if target else "?")
    if name == "engineering_write":
        target = result.get("saved", "")
        return "[VERIFIED] %s: saved=%s" % (
            name, Path(target).name if target else "?")
    dims = ""
    if name.startswith("fusion_") or "knob" in name:
        dims = " args=" + json.dumps(args, default=str)[:100]
    return "[VERIFIED] %s:%s %s" % (
        name, dims, json.dumps(result, default=str)[:140])


def build_outcome(turn_log, turn_status):
    head = ["[TURN OUTCOME -- code-recorded facts]", "Status: " + turn_status]
    if not turn_log:
        head.append("Tools: no tool calls this turn.")
    else:
        for entry in turn_log[:12]:
            try:
                head.append(_short_result(*entry))
            except Exception:
                head.append("[VERIFIED] %s: (summary failed)" % (entry[0],))
        if len(turn_log) > 12:
            head.append("... +%d more tool calls" % (len(turn_log) - 12))
    if turn_status in ("round-budget-exhausted", "tool-cap-exhausted"):
        tail = "NEXT: resume from this record; reply states the next step."
    elif turn_status == "error-halt":
        tail = "NEXT: address the FAILED entry above, then continue."
    else:
        tail = "NEXT: none recorded -- see reply text."
    body = "\n".join(head)
    room = MAX_OUTCOME_CHARS - len(tail) - 1
    if len(body) > room:
        body = body[:room] + "\n[trimmed]"
    return body + "\n" + tail


def _write_turn_checkpoint(project, status, rounds_used, calls_used, log):
    outcome = build_outcome(log, status)
    verified = []
    failed = []
    for entry in log:
        try:
            short = _short_result(*entry)
        except Exception:
            continue
        if short.startswith("[FAILED]"):
            failed.append(short)
        elif short.startswith("[VERIFIED]"):
            verified.append(short)
        elif short.startswith("[UNVERIFIED]"):
            verified.append(short)
    tail = outcome.rsplit("\n", 1)[-1]
    next_step = tail[6:] if tail.startswith("NEXT: ") else ""
    write_checkpoint(
        project=project,
        turn_status=status,
        rounds_used=rounds_used,
        tool_calls_used=calls_used,
        summary=outcome[:600],
        verified=verified[:10],
        pending="",
        blockers="; ".join(failed)[:400],
        next_step=next_step[:400],
    )


def _summarize_turn(messages):
    try:
        prompt = (
            "Turn tool budget exhausted. Using ONLY the tool results above, write:\n"
            "PROGRESS: 1-3 factual lines (VERIFIED outcomes, artifact paths).\n"
            "NEXT: the single exact next tool step to continue.\n"
            "BLOCKED: only if a human is genuinely required, else 'none'."
        )
        response = client.chat.completions.create(
            model="muse-spark-1.3",
            messages=messages + [{"role": "user", "content": prompt}],
            tool_choice="none",
        )
        text = (response.choices[0].message.content or "").strip()
        return text[:1500] if text else None
    except Exception:
        return None

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

# MOONMAN_WEB_RESEARCH_V1
CAD_TOOLS.append({
    "type": "function",
    "function": {
        "name": "web_research",
        "description": (
            "Read-only engineering web research via Meta Search Grounding. "
            "Use for manufacturer datasheets, servo dimensions, shaft "
            "specifications, mounting-hole spacing, component identification. "
            "Returns a grounded answer with citations (URL, title, and text "
            "spans linking claims to sources) plus a search_occurred flag. "
            "Results are UNVERIFIED research candidates -- never treat "
            "returned dimensions as confirmed specs; confirm against the cited "
            "source before CAD or printing. Never use for printer control."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Engineering research question, max 500 chars."
                }
            },
            "required": ["query"],
            "additionalProperties": False
        }
    }
})

# MOONMAN_PROJECT_MEMORY_V1
CAD_TOOLS.extend([
    {"type": "function", "function": {
        "name": "project_recall",
        "description": (
            "Search namespaced project memory facts for one project. "
            "Never returns other projects' facts. Use for resume context "
            "beyond the auto-injected checkpoint summary."
        ),
        "parameters": {"type": "object", "properties": {
            "project": {"type": "string"},
            "query": {"type": "string"},
            "limit": {"type": "integer"}},
            "required": ["project", "query"]}}},
    {"type": "function", "function": {
        "name": "project_checkpoint",
        "description": (
            "Read the latest auto-checkpoint for a project: turn status, "
            "verified refs, blockers, and NEXT step."
        ),
        "parameters": {"type": "object", "properties": {
            "project": {"type": "string"}},
            "required": ["project"]}}},
    {"type": "function", "function": {
        "name": "project_remember",
        "description": (
            "Record a namespaced project fact with a status. Use verified "
            "ONLY for tool-observed results; use assumption, plan, failed, "
            "or user_confirmed otherwise. Never record research or inference "
            "as verified."
        ),
        "parameters": {"type": "object", "properties": {
            "project": {"type": "string"},
            "subject": {"type": "string"},
            "fact": {"type": "string"},
            "status": {"type": "string"},
            "provenance": {"type": "string"}},
            "required": ["project", "subject", "fact", "status"]}}},
])

# MOONMAN_TRACK2_TOOLS_V1
CAD_TOOLS.extend([
    {"type": "function", "function": {
        "name": "fusion_save_document",
        "description": (
            "Save the active Fusion design. No arguments needed when the "
            "design was saved before. For an unsaved design requires name, "
            "which creates a cloud document by that name -- confirm the name "
            "with the user first."
        ),
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string"}},
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "fusion_delete_body",
        "description": (
            "Permanently delete one solid body from a Moon Man-owned "
            "component. Inspect geometry first. Cannot be undone via Moon Man."
        ),
        "parameters": {"type": "object", "properties": {
            "component": {"type": "string"},
            "body": {"type": "string"},
            "body_index": {"type": "integer"}},
            "required": ["component"],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "fusion_delete_feature",
        "description": (
            "Permanently delete one feature (extrusion, fillet, chamfer, "
            "hole, move) by exact name from inspect_features, in a Moon "
            "Man-owned component. Cannot be undone via Moon Man."
        ),
        "parameters": {"type": "object", "properties": {
            "component": {"type": "string"},
            "feature": {"type": "string"}},
            "required": ["component", "feature"],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "fusion_delete_sketch",
        "description": (
            "Permanently delete one sketch by exact name from inspect_design, "
            "in a Moon Man-owned component. Cannot be undone via Moon Man."
        ),
        "parameters": {"type": "object", "properties": {
            "component": {"type": "string"},
            "sketch": {"type": "string"}},
            "required": ["component", "sketch"],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "fusion_document_info",
        "description": (
            "Read-only: active document title and saved state. No parameters."
        ),
        "parameters": {"type": "object", "properties": {},
            "required": [],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "fusion_check_clearance",
        "description": (
            "Read-only bounding-box clearance between two bodies, which may "
            "belong to any components. Returns per-axis gaps and an overlap "
            "flag. Approximation -- use interference_check for exact."
        ),
        "parameters": {"type": "object", "properties": {
            "component_a": {"type": "string"},
            "body_a": {"type": "integer"},
            "component_b": {"type": "string"},
            "body_b": {"type": "integer"}},
            "required": ["component_a", "component_b"],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "fusion_interference_check",
        "description": (
            "Read-only exact solid interference between two bodies via "
            "temporary geometry; never modifies the design. Bodies may belong "
            "to any components. Returns interferes true/false and volume."
        ),
        "parameters": {"type": "object", "properties": {
            "component_a": {"type": "string"},
            "body_a": {"type": "integer"},
            "component_b": {"type": "string"},
            "body_b": {"type": "integer"}},
            "required": ["component_a", "component_b"],
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "fusion_align_bodies",
        "description": (
            "Move a Moon Man-owned body so its bounding box aligns to a "
            "target body's on chosen axes (center, min, or max). Target may "
            "be any component and is never moved. Inspect both first."
        ),
        "parameters": {"type": "object", "properties": {
            "component": {"type": "string"},
            "body_index": {"type": "integer"},
            "target_component": {"type": "string"},
            "target_body": {"type": "integer"},
            "axes": {"type": "string"},
            "mode": {"type": "string"}},
            "required": ["component", "target_component"],
            "additionalProperties": False}}},
])

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

    if lower.startswith("moonman owns "):
        grant = question[len("moonman owns "):].strip()
        if not grant:
            return "Name the component, e.g. moonman owns BRACKET"
        _register_owned(grant)
        return "Moon Man now owns component: " + grant

    if lower.startswith("moonman release "):
        drop = question[len("moonman release "):].strip()
        try:
            if _unregister_owned(drop):
                return "Moon Man released component: " + drop
            return "That component was not Moon Man-owned: " + drop
        except Exception as error:
            return "Registry update failed: " + str(error)

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

    try:
        detected = detect_project(question)
        if detected:
            set_active_project(detected)
        active_project = get_active_project()
    except Exception:
        active_project = "general"

    # Ordinary conversation gets relevant stored facts
    stored_facts = []
    project_hits = []
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
        "\n".join(f"- [general] {fact}" for fact in stored_facts[:5])
        if stored_facts
        else "No relevant stored facts found."
    )
    try:
        for word in words[:5]:
            for row in recall_facts(active_project, word, 3):
                label = "[%s:%s] %s: %s" % (
                    active_project, row["status"], row["subject"], row["fact"])
                if label not in project_hits and len(project_hits) < 3:
                    project_hits.append(label)
    except Exception:
        project_hits = []
    if project_hits:
        memory_context = (
            "Project memory:\n"
            + "\n".join("- " + hit for hit in project_hits)
            + "\n" + memory_context
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
    messages[0]["content"] += (
        "\n\nActive project: " + active_project + "\n" + project_brief(active_project)
        + "\n\nActive engineering objective (scratchpad):\n" + read_objective(active_project)
        + AUTONOMY_DIRECTIVE
    )
    user_content = [{"type": "text", "text": question}]
    attach_file_images(user_content, question)
    vision_phrases = (
        "what do you see", "what can you see",
        "look at", "take a look", "look around",
        "use your camera", "check your camera",
        "show me what you see", "inspect visually",
        "look through your camera"
    )
    if any(phrase in question.lower() for phrase in vision_phrases):
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
    turn_log = []
    answer = ""
    turn_status = "completed"
    turn_doc = None
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
                turn_status = "tool-cap-exhausted"
                error_result = "Stopped: too many tool calls."
                break
            name = call.function.name
            args = {}
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
                elif name == "project_recall":
                    result = tool_project_recall(args.get("project", ""), args.get("query", ""), args.get("limit", 5))
                elif name == "project_checkpoint":
                    result = tool_project_checkpoint(args.get("project", ""))
                elif name == "project_remember":
                    result = tool_project_remember(args.get("project", ""), args.get("subject", ""), args.get("fact", ""), args.get("status", "assumption"), args.get("provenance", ""))
                elif name == "web_research":
                    result = web_research(args.get("query", ""))
                elif name.startswith("fusion_"):
                    action = name[len("fusion_"):]
                    allowed = {"create_box", "create_cylinder", "create_sketch",
                               "extrude_profile", "create_hole", "fillet_edges",
                               "chamfer_edges", "inspect_design", "export_stl", "export_body",
                           "inspect_features", "edit_extrusion", "edit_circle",
                           "inspect_geometry", "move_body", "rotate_body", "rename_body",
                           "delete_body", "delete_feature", "delete_sketch", "save_document",
                           "document_info", "check_clearance", "interference_check", "align_bodies"}
                    if action not in allowed:
                        raise ValueError("Unknown Fusion action: " + action)
                    result = moonman_fusion_command(action, args)
                    if isinstance(result, dict) and "Unsupported action" in str(result.get("error", "")):
                        result = {"status": "error", "error": result["error"] + " Restart the MoonManBridge add-in in Fusion to load new actions, then retry."}
                    doc_now = result.get("document") if isinstance(result, dict) else None
                    if doc_now:
                        if turn_doc is None:
                            turn_doc = doc_now
                        elif doc_now != turn_doc:
                            result = {"status": "error", "error": "Active Fusion document changed mid-turn (was %r, now %r). Stopped to avoid writing to the wrong design." % (turn_doc, doc_now)}
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
                elif name == "gaze_point":
                    ok = _track_pub("moonman/track/look",
                                    {"fx": args.get("x"), "fy": args.get("y")})
                    result = {"status": "ok" if ok else "unavailable",
                              "message": "glancing" if ok else
                              "tracker unreachable (is moonman_track.py running?)"}
                elif name == "look_at":
                    ok = _track_pub("moonman/track/look",
                                    {"pan": args.get("pan"), "tilt": args.get("tilt")})
                    result = {"status": "ok" if ok else "unavailable",
                              "message": "moving" if ok else
                              "tracker unreachable (is moonman_track.py running?)"}
                elif name == "track_mode":
                    ok = _track_pub("moonman/track/mode", args.get("mode", "auto"))
                    result = {"status": "ok" if ok else "unavailable",
                              "message": "mode set" if ok else
                              "tracker unreachable (is moonman_track.py running?)"}
                elif name == "get_gaze":
                    gaze = _track_get()
                    result = {"status": "ok", **gaze} if gaze else \
                        {"status": "unavailable",
                         "message": "tracker unreachable (is moonman_track.py running?)"}
                else:
                    raise ValueError("Unknown tool: " + name)
                if not isinstance(result, dict):
                    result = {"result": str(result)}
            except Exception as error:
                result = {"status": "error", "error": str(error)}
            print("TOOL", name, json.dumps(result, default=str))
            turn_log.append((name, args, result))
            messages.append({"role": "tool", "tool_call_id": call.id,
                             "content": json.dumps(result, default=str)})
            if name in GAZE_MOVE_TOOLS and result.get("status") == "ok":
                _track_append_fresh_view(messages, turn_log)
            if result.get("status") in ("error", "timeout", "failed") or result.get("success") is False:
                if "changed mid-turn" in str(result.get("error", "")):
                    error_result = name + " failed: " + json.dumps(result, default=str)
                    break
                if name in RETRYABLE_READ_TOOLS:
                    continue
                error_result = name + " failed: " + json.dumps(result, default=str)
                break
        if error_result:
            if turn_status == "completed":
                turn_status = "error-halt"
            answer = error_result + "\nStopped without requesting further actions."
            break
    else:
        summary = _summarize_turn(messages)
        turn_status = "round-budget-exhausted"
        if summary:
            answer = summary + "\n\n(Round budget exhausted. Progress preserved; say 'continue' to resume.)"
        else:
            answer = "Stopped at the eight-round safety limit. Review the last tool results before continuing."

    history.append({"role": "user", "content": question})
    history.append({"role": "assistant", "content": answer + "\n\n" + build_outcome(turn_log, turn_status)})
    try:
        _write_turn_checkpoint(active_project, turn_status, round_number + 1,
                               tool_count, turn_log)
    except Exception as error:
        print("Checkpoint skipped (in-memory outcome preserved):", error)
    return answer


if __name__ == "__main__":
    print("MOON MAN AI â€” LIVE VISION + MEMORY")
    print("Commands: remember SUBJECT: FACT | recall SUBJECT | paste an image path to share a picture | exit")

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




