#!/usr/bin/env python3
"""MoonMan MQTT bridge: voice server <-> Meta agent (runs on the LAPTOP).

agent.py is UNCHANGED. This module imports its ask_moonman() entry point and
serves it over the voice protocol:

  subscribe moonman/brain/ask     JSON {"id": ..., "text": ..., "device": ...}
  publish   moonman/brain/answer  JSON {"id": ..., "text": ..., "status": ...}
  publish   moonman/brain/status  "online"/"offline" (retained, LWT)

status is "ok" for a real answer. "busy" also carries speakable text (the
agent was mid-thought; the eye speaks it and the human retries). "timeout"
and "error" carry "" and the voice side falls back to its echo reply.

One question at a time: the agent keeps shared conversation history, so a
second question arriving mid-answer gets "busy". A question that runs past
BRIDGE_TIMEOUT_SEC is abandoned (its late answer is dropped, never spoken
for a newer question); the voice side matches replies by id too.

Physical approvals (e.g. START ARCHIE) print on THIS console: type the
approval here within the timeout and the action proceeds with a spoken
answer. After the timeout the voice side has already moved on, so type
approvals promptly. Approval-gated actions still NEVER run without the
typed phrase.

Run from this folder with the same interpreter that runs agent.py:
  py moonman_mqtt_bridge.py
"""

import json
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agent import ask_moonman  # noqa: E402 (agent loads .env + tools on import)

BROKER = os.environ.get("MOONMAN_BROKER", "192.168.1.11")
PORT = int(os.environ.get("MOONMAN_MQTT_PORT", "1883"))
ASK_TOPIC = "moonman/brain/ask"
ANSWER_TOPIC = "moonman/brain/answer"
STATUS_TOPIC = "moonman/brain/status"
BRIDGE_TIMEOUT_SEC = 40.0  # under the voice server's 45s, over Meta's 45s/call

_lock = threading.Lock()


def log(*a):
    print("[bridge]", *a, flush=True)


def _strip_junk_lines(text):
    """Cut checkpoint noise the model echoes from history (RUN: / TURN blocks).

    ask_moonman appends outcome summaries to history, so the model sometimes
    imitates them. Those lines are dashboard noise, not speech. Only
    line-starting markers are cut; inline mentions survive.
    """
    keep = []
    for line in text.strip().split("\n"):
        if line.strip().startswith(("RUN:", "[TURN OUTCOME")):
            break
        keep.append(line)
    return "\n".join(keep).strip()


def _voice_text(text, device=""):
    """Append a brevity hint for spoken replies.

    Skipped for agent console commands (exact/phrase matches in
    ask_moonman) so voice can still drive memory and approvals, and
    for dashboard asks (typed answers are read, not heard).
    """
    if device == "dashboard":
        return text
    low = text.strip().lower()
    exact = ("confirm print", "yes print", "yes print it", "yes, print it",
             "print it")
    prefixes = ("remember ", "correct ", "recall ", "moonman owns ",
                "moonman release ")
    if low in exact or low.startswith(prefixes):
        return text
    return text + ("\n[Voice reply: this is SPOKEN aloud - 1-3 short "
                   "sentences, under 500 characters, no lists, no markdown, "
                   "no code.]")


def handle(payload):
    try:
        obj = json.loads(payload.decode("utf-8", "replace"))
        text = str(obj.get("text", "")).strip()
        req_id = str(obj.get("id", ""))
        device = str(obj.get("device", ""))
    except Exception:
        text, req_id, device = payload.decode("utf-8", "replace").strip(), "", ""
    if not text:
        return {"id": req_id, "text": "", "status": "empty"}
    text = _voice_text(text, device)
    if not _lock.acquire(blocking=False):
        return {
            "id": req_id,
            "text": "One moment, cadet, still thinking.",
            "status": "busy",
        }
    try:
        box = {}

        def run():
            try:
                box["answer"] = ask_moonman(text)
            except Exception as error:  # never let the bridge die on one ask
                box["error"] = error

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        worker.join(BRIDGE_TIMEOUT_SEC)
        if "answer" in box:
            return {"id": req_id, "text": _strip_junk_lines(str(box["answer"])),
                    "status": "ok"}
        if "error" in box:
            log("agent error:", box["error"])
            return {"id": req_id, "text": "", "status": "error"}
        # Timeout: the worker keeps running as a daemon (it may be blocked
        # on a console approval) but its late answer is dropped, and a new
        # question may overlap it. Rare; logged loudly.
        log("agent timeout after %.0fs (q: %s...)" % (BRIDGE_TIMEOUT_SEC, text[:60]))
        return {"id": req_id, "text": "", "status": "timeout"}
    finally:
        _lock.release()


def main():
    try:
        import paho.mqtt.client as mqtt_mod
    except ImportError:
        log("paho-mqtt missing: py -m pip install paho-mqtt")
        sys.exit(1)
    try:
        client = mqtt_mod.Client(mqtt_mod.CallbackAPIVersion.VERSION2)
    except Exception:
        client = mqtt_mod.Client()
    client.will_set(STATUS_TOPIC, "offline", retain=True)

    def on_connect(c, _u, _f, rc, _p=None):
        if rc == 0:
            c.subscribe(ASK_TOPIC)
            c.publish(STATUS_TOPIC, "online", retain=True)
            log("bridge up on %s:%d (%s -> %s)" % (BROKER, PORT, ASK_TOPIC, ANSWER_TOPIC))
        else:
            log("mqtt connect failed rc=", rc)

    def on_message(_c, _u, m):
        if m.topic != ASK_TOPIC:
            return
        reply = handle(m.payload)
        _c.publish(ANSWER_TOPIC, json.dumps(reply))

    client.on_connect = on_connect  # _p=None default fits paho v1 and v2
    client.on_message = on_message
    log("connecting to broker %s:%d ..." % (BROKER, PORT))
    client.connect(BROKER, PORT, keepalive=30)
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        client.publish(STATUS_TOPIC, "offline", retain=True)
        log("stopping")


if __name__ == "__main__":
    main()
