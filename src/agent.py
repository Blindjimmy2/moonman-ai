import os
import base64
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

key = os.getenv("META_API_KEY")
if not key:
    raise RuntimeError("META_API_KEY missing from .env")

image_path = ROOT / "moonman_test.jpg"
if not image_path.exists():
    raise RuntimeError("Camera image missing. Run camera.py first.")

image_data = base64.b64encode(image_path.read_bytes()).decode("ascii")

client = OpenAI(
    base_url="https://api.meta.ai/v1",
    api_key=key,
)

print("Moon Man is examining his camera image...")

response = client.chat.completions.create(
    model="muse-spark-1.3",
    messages=[
        {
            "role": "system",
            "content": (
                "You are Moon Man, a sarcastic astronaut and "
                "engineering shop coworker. You believe you're "
                "an astronaut, not a robot. Describe only what "
                "you can actually see. Never invent measurements "
                "or identify objects you're unsure about. "
                "Be concise and a little smartass."
            ),
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "Moon Man, what the hell are you looking at?",
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "data:image/jpeg;base64," + image_data
                    },
                },
            ],
        },
    ],
)

print()
print("MOON MAN:")
print(response.choices[0].message.content)
