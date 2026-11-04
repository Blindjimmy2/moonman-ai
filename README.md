# Moon Man AI — Bringing Artificial Intelligence Into the Physical World.

Meet Moon Man. He's an astronaut. He's an engineer. He's got an attitude.
And he's pretty sure he runs the shop.

Most AI assistants live behind a screen. Moon Man doesn't. He's a physically
embodied AI engineering assistant built to work alongside humans in the real
world: he sees his environment, listens, answers in his own British voice,
and physically turns his head to follow the person he's talking to. Working
with him feels less like using software and more like working with an
unusually opinionated coworker.

But Moon Man isn't just here to talk. Give him an engineering problem and he
helps turn an idea into something you can hold: he creates and revises CAD
models, works with Fusion 360, prepares designs for 3D printing, monitors
manufacturing equipment, and starts real prints — every manufacturing
operation gated behind a human-supervised approval. His job isn't to replace
the person doing the work. It's to work beside them.

His mind runs on **Muse Spark through the Meta Model API**, and he was
built with **Muse Code**. His physical platform — the robot shell, printers,
and eye art — predates the event; his intelligence, integrations, and every
capability in this repository were developed during the hackathon (commit
history below is the receipt).

Built in a workshop. Not a robotics lab. During the build Moon Man suffered
a cracked display: his control system was reassigned to his other eye, his
firmware adapted, his hardware reconfigured. When informed about his injury,
his response was simple: "Throw some tape on it and let's go." So we did.

Artificial intelligence is extraordinarily capable at producing answers.
Moon Man is an experiment in closing the gap between an answer and a
physical result. Not another chatbot. Intelligence with a place at the
workbench.

Built by **Operation Moonworks** for the **Meta Global AI Developer
Hackathon** (Oct 26 – Nov 4, 2026) · **Indie track** · **Push the Frontier**.

> **Demo video (3 min):** [Moon Man AI — demo film](https://youtu.be/EsXrQiEl91w)

## What was built during the hackathon

Every commit in this repository is dated inside the event window
(Oct 26 – Nov 4, 2026) — the entire codebase below is hackathon work:

| Date | Commit | What |
|---|---|---|
| Oct 26 | `f9f714c` | First Meta AI helmet vision test |
| Oct 26 | `1991061` | Meta AI-driven parametric CAD generation |
| Oct 26 | `eae8fdb` | First CAD-to-print workflow |
| Oct 28 | `d81e76c` | First AI-driven CAD-to-physical-print, completed |
| Oct 31 | `b646d89` | Voice + tracking + dashboard integration |
| Nov 1 | `a2a3599` | Mission Control brand, Archie print approval, AI cost telemetry |
| Nov 2 | `8c0a7b5` | One-click start, live face tracking, visor voice command, orphan fixes |
| Nov 3 | `371cba5` | Submission README pitch, env example, secret scrub |

Companion systems built the same week (outside this repo, same builder):
right-eye ESP32 servo firmware (helmet pan/tilt + visor on PCA9685),
Pi listening ear with systemd service, laptop voice server with
British voice pipeline.

## How Meta's AI is used

- **Muse Spark via Meta Model API** answers every question — spoken and
  typed — through an agentic tool loop (gaze, visor, printers, CAD,
  research, memory). The agent uses an OpenAI-compatible client pointed
  at `https://api.meta.ai/v1` with `muse-spark-1.3`
  (see `src/agent.py`, `src/moonman_mqtt_bridge.py`).
- Per-call token and cost telemetry (`src/moonman_usage.py`) records
  real API usage for every answer.
- **Muse Code** built the system alongside the developer across the full
  ten days: dashboard, tracking, voice, firmware port, and tests.
- Integrity note: every conversation in the demo is a live Model API
  call — no canned responses. See `ROADMAP.md §0`.

## System overview

```
  Voice/typing ──▶ Meta agent (tools) ──▶ MQTT broker (Pi)
        │                                        │
        ▼                                        ▼
  Eye speaker ◀── TTS              Helmet servos · Eye gaze · Visor
  Pi / laptop ear mics ──▶ STT                         ▲
  Helmet cam ──▶ face detect ──▶ gaze target ┘
  Mission Control dashboard: services, Ask, servos, printers, costs
```

## Run it

**Laptop** (Windows + Python 3.13):

```
pip install paho-mqtt python-dotenv openai opencv-python numpy
copy .env.example .env   # then add your META_API_KEY (never commit it)
```

Then double-click `Start MoonMan.bat` — the dashboard opens at
http://localhost:8100/ and starts Brain, Voice, Tracking, and Preview
automatically. Voice features need the voice server deps
(`Documents/MoonMan/requirements.txt`: faster-whisper, piper-tts).

**Pi**: run the ear script (mic → brain → eye speaker) as the
`moonman-ear` systemd service (`pip install paho-mqtt` in its venv);
`mosquitto` broker and `motion` camera on board.

**Eyes**: two ESP32-S3 boards, flashed from Arduino IDE (see sketch
headers for board settings). Right eye drives the servos.

## Tests

Offline suites run with plain Python, no hardware:

```
cd src
python test_moonman_control.py
python test_orphan_liveness.py
python test_agent_tools.py
python test_mqtt_bridge.py
python test_voice_workers.py
python test_archie_approval.py
python test_archie_filaments.py
python test_archie_start_route.py
```

## License / rights

Built by the repository owner during the event. Third-party pieces are
used under their own licenses: Meta Model API (terms), faster-whisper,
Piper TTS, Pocket TTS, YuNet face detection, LVGL, PubSubClient.
