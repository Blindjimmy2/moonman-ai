"""MoonMan laptop ear: laptop mic -> laptop brain -> eye speaker.

Same role as the Pi ear (moonman_ear.py), running on the laptop with
whatever input device Windows hands us. Intended for demos/bench work
when the Pi webcam mic can't cut it; the pipeline is identical
(energy VAD -> POST /listen -> forward answer text to the eye).

Only ONE ear may run at a time: stop the Pi ear service first, or
MoonMan hears everything twice.

Needs: the repo .venv (paho-mqtt, sounddevice).
Setup (repo root, once):
  py -m venv .venv
  .venv\\Scripts\\pip install paho-mqtt sounddevice
Run (repo root):
  .venv\\Scripts\\python src\\moonman_laptop_ear.py
Tune: VAD_THRESH above your room level (printed at startup).
  MIC_INDEX selects a non-default input (device list printed).
Test: SMOKE_SEC=25 runs 25 seconds then exits cleanly.
"""

import array
import math
import os
import re
import struct
import time
import urllib.parse
import urllib.request

MIC_INDEX = os.environ.get("MIC_INDEX", "").strip()
BRAIN_URL = os.environ.get("BRAIN_URL", "http://127.0.0.1:8099")
BROKER = os.environ.get("MOONMAN_BROKER", "192.168.1.11")
PORT = int(os.environ.get("MOONMAN_MQTT_PORT", "1883"))
VAD_THRESH = float(os.environ.get("VAD_THRESH", "500"))
SMOKE_SEC = float(os.environ.get("SMOKE_SEC", "0"))
SILENCE_SEC = 1.2
MIN_SEC = 0.5
MAX_SEC = 12.0
CHUNK_SAMPLES = 1600   # 100ms of 16k mono 16-bit
RATE = 16000
SAY_TOPIC = "moonman/eye/right/say"
EAR_TOPIC = "moonman/eye/right/listen"
STATUS_TOPIC = "moonman/status/ear"
STATUS_ONLINE = "online-laptop"
SAY_MAX = 230          # eye cmd text buffer is 240 chars
CHARS_PER_SEC = 15.0   # speech rate estimate for pacing/muting


def log(*a):
    print("[laptop-ear]", *a, flush=True)


def rms(chunk):
    try:
        samples = array.array("h", chunk)
    except Exception:
        return 0.0
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))


def wav_wrap(pcm):
    head = struct.pack("<4sI4s4sIHHIIHH4sI",
                       b"RIFF", 36 + len(pcm), b"WAVE", b"fmt ", 16,
                       1, 1, RATE, RATE * 2, 2, 16, b"data", len(pcm))
    return head + pcm


def chunk_text(text):
    """Split a reply into eye-sized sentence chunks."""
    parts = re.split(r"(?<=[.!?])\s+", " ".join(text.split()))
    chunks, cur = [], ""
    for part in parts:
        if len(cur) + 1 + len(part) <= SAY_MAX:
            cur = (cur + " " + part).strip()
        else:
            if cur:
                chunks.append(cur)
            while len(part) > SAY_MAX:
                chunks.append(part[:SAY_MAX])
                part = part[SAY_MAX:]
            cur = part
    if cur:
        chunks.append(cur)
    return chunks


class Ear:
    def __init__(self):
        import paho.mqtt.client as mqtt_mod
        try:
            import sounddevice as sd_mod
        except ImportError:
            raise SystemExit("need sounddevice: .venv\\Scripts\\pip install sounddevice")
        self.sd = sd_mod
        try:
            self.mqtt = mqtt_mod.Client(mqtt_mod.CallbackAPIVersion.VERSION2)
        except Exception:
            self.mqtt = mqtt_mod.Client()
        # Crash -> eye ears come back on (LWT fires on unclean disconnect).
        self.mqtt.will_set(EAR_TOPIC, "on")
        self.mqtt.connect(BROKER, PORT, keepalive=30)
        self.mqtt.loop_start()
        self.mqtt.publish(STATUS_TOPIC, STATUS_ONLINE, retain=True)
        self.mqtt.publish(EAR_TOPIC, "off")  # ears are ours now
        log("ears taken (eye mic asleep)")
        self.mute_until = 0.0
        self.stream = None

    def close(self):
        try:
            self.mqtt.publish(EAR_TOPIC, "on")  # eye ears back on
            self.mqtt.publish(STATUS_TOPIC, "offline", retain=True)
            self.mqtt.loop_stop()
            self.mqtt.disconnect()
        except Exception:
            pass
        self.stop_mic()

    def start_mic(self):
        self.stop_mic()
        devs = self.sd.query_devices()
        index = int(MIC_INDEX) if MIC_INDEX else None
        if index is None:
            default = self.sd.default.device[0]
            log("inputs available:")
            for i, dev in enumerate(devs):
                if dev["max_input_channels"] > 0:
                    mark = " <== default" if i == default else ""
                    log("  [%d] %s%s" % (i, dev["name"], mark))
        else:
            log("mic index:", index, devs[index]["name"])
        self.stream = self.sd.InputStream(samplerate=RATE, channels=1,
                                          dtype="int16",
                                          blocksize=CHUNK_SAMPLES,
                                          device=index)
        self.stream.start()
        log("mic open")

    def stop_mic(self):
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None

    def read_chunk(self):
        try:
            data, _overflow = self.stream.read(CHUNK_SAMPLES)
        except Exception:
            raise RuntimeError("mic stream died")
        return bytes(data)

    def calibrate(self, seconds=2.0):
        peak = 0.0
        end = time.time() + seconds
        while time.time() < end:
            peak = max(peak, rms(self.read_chunk()))
        log("room level: %.0f (VAD_THRESH=%s)" % (peak, VAD_THRESH))

    def listen_once(self):
        """Record one utterance (b'' if muted / too short / mic died)."""
        if time.time() < self.mute_until:
            time.sleep(0.2)
            return b""
        # Wait for voice onset (2 consecutive loud chunks).
        loud = 0
        while True:
            data = self.read_chunk()
            if time.time() < self.mute_until:
                return b""
            loud = loud + 1 if rms(data) > VAD_THRESH else 0
            if loud >= 2:
                pcm = bytearray(data)
                break
        # Capture until silence or cap.
        silent = 0.0
        start = time.time()
        while time.time() - start < MAX_SEC:
            data = self.read_chunk()
            pcm.extend(data)
            if rms(data) > VAD_THRESH:
                silent = 0.0
            else:
                silent += len(data) / (RATE * 2.0)
                if silent >= SILENCE_SEC:
                    break
        seconds = len(pcm) / (RATE * 2.0)
        if seconds < MIN_SEC:
            return b""
        log("clip %.1fs" % seconds)
        return bytes(pcm)

    def ask(self, pcm):
        body = wav_wrap(pcm)
        req = urllib.request.Request(
            BRAIN_URL + "/listen", data=body,
            headers={"Content-Type": "audio/wav"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=70) as resp:
                code = resp.status
                heard = urllib.parse.unquote(
                    resp.headers.get("X-Transcript", ""))
                answer = urllib.parse.unquote(
                    resp.headers.get("X-Answer", ""))
        except Exception as error:
            log("brain POST failed:", error)
            return
        if code == 204:
            log("brain silent (heard: %s)" % heard)
            return
        if not answer:
            log("no answer text, nothing to forward")
            return
        log('Q: "%s"' % heard)
        log('A: "%s"' % answer[:120])
        chunks = chunk_text(answer)
        total = 0.0
        for piece in chunks:
            self.mqtt.publish(SAY_TOPIC, piece)
            wait = len(piece) / CHARS_PER_SEC + 2.5
            total += wait
            time.sleep(wait)
        self.mute_until = time.time() + 3.0  # tail past our own estimate
        log("forwarded %d chunk(s), ears back in %.0fs" % (len(chunks), total))

    def run(self):
        self.start_mic()
        self.calibrate()
        deadline = time.time() + SMOKE_SEC if SMOKE_SEC > 0 else None
        while True:
            try:
                if deadline is not None and time.time() >= deadline:
                    log("smoke time up, exiting cleanly")
                    return
                pcm = self.listen_once()
                if pcm:
                    self.ask(pcm)
            except RuntimeError as error:
                log(error)
                self.stop_mic()
                time.sleep(1.0)
                self.start_mic()
            except KeyboardInterrupt:
                raise


def main():
    ear = Ear()
    try:
        ear.run()
    except KeyboardInterrupt:
        log("stopping")
    finally:
        ear.close()
        log("eye ears restored")


if __name__ == "__main__":
    main()
