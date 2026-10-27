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


def ask_moonman(question):
    # MOONMAN_PRINT_COMMANDS
    command = question.strip().lower()

    if command == "prepare print":
        from print_approval import prepare_print
        from pathlib import Path

        gcode = (
            Path(__file__).resolve().parent.parent
            / "generated"
            / "moonman_knob_v007_test.gcode"
        )
        prepare_print(gcode)
        return "Longer is ready. Print prepared. Say CONFIRM PRINT to authorize the physical print."

    if command == "confirm print":
        from print_approval import confirm_print
        confirm_print()
        return "Print-start request submitted to OctoPrint. Check the printer status."

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
    image = capture_image()
    encoded = base64.b64encode(image).decode("ascii")

    print("Moon Man is thinking...")

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT + (
                "\nRelevant stored memories:\n" + memory_context
+ "\n\nCurrent CAD state:\n" + cad_context
            ),
        }
    ]

    messages.extend(history)

    messages.append({
        "role": "user",
        "content": [
            {"type": "text", "text": question},
            {
                "type": "image_url",
                "image_url": {
                    "url": "data:image/jpeg;base64," + encoded
                },
            },
        ],
    })

    response = client.chat.completions.create(
        model="muse-spark-1.3",
        messages=messages,
        tools=CAD_TOOLS,
        tool_choice="auto",
    )

    message = response.choices[0].message

    if message.tool_calls:
        import json

        results = []

        for call in message.tool_calls:
            if call.function.name == "revise_knob":
                args = json.loads(call.function.arguments)

                path = revise_knob(
                    diameter=args.get("diameter"),
                    height=args.get("height"),
                    shaft_diameter=args.get("shaft_diameter"),
                )    
                show_design(path)

                results.append(
                    f"CAD REVISED: {path}\n"
                    "Previous version preserved.\n"
                    "Status: Awaiting engineering review. Not printed."
                )
                continue

            if call.function.name != "create_knob":
                results.append("Unknown CAD tool requested.")
                continue

            args = json.loads(call.function.arguments)

            required = ("diameter", "height", "shaft_diameter")

            if any(name not in args for name in required):
                results.append(
                    "CAD request incomplete. Please provide "
                    "diameter, height, and shaft diameter in mm."
                )
                continue

            path = create_knob(
                diameter=args["diameter"],
                height=args["height"],
                shaft_diameter=args["shaft_diameter"],
            )
            show_design(path)

            results.append(
                f"CAD CREATED: {path}\n"
                f"Diameter: {args['diameter']} mm\n"
                f"Height: {args['height']} mm\n"
                f"Shaft: {args['shaft_diameter']} mm\n"
                "Status: Awaiting engineering review. Not printed."
            )

        answer = "\n\n".join(results)

    else:
        answer = message.content or ""

    # Retain text conversation without retaining camera images
    history.append({"role": "user", "content": question})
    history.append({"role": "assistant", "content": answer})

    return answer


if __name__ == "__main__":
    print("MOON MAN AI — LIVE VISION + MEMORY")
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

        except KeyboardInterrupt:
            break
        except Exception as error:
            print(f"\nError: {error}")



