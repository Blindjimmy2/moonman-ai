"""Persistent Pocket TTS file worker for Moon Man (Windows).

Same established voice as voice_worker.py (stuart_bell), but renders to WAV
files for the ESP32 speaker instead of playing on the laptop.

Protocol (stdin/stdout, text, line-buffered):
  parent -> worker:  <jobid>\\t<output.wav>\\t<text...>
  worker -> parent:  READY                      (once, after model load)
                     OK <jobid>                 (wav written, 16kHz mono 16-bit)
                     ERR <jobid> <message>      (job failed, worker still alive)
  parent -> worker:  QUIT                       (clean shutdown; EOF also stops)

A jobid containing no spaces; text must have no raw newlines/tabs (the
parent replaces them with spaces). The worker never exits on a bad job.

Runs under the voice-test interpreter (torch + pocket_tts live there):
  C:\\MoonworksDev\\moonman-voice-test\\Scripts\\python.exe pocket_file_worker.py
"""

import re
import sys
import time
import wave

import numpy as np
from pocket_tts import TTSModel

VOICE = "stuart_bell"
TARGET_RATE = 16000
MAX_CHUNK = 400  # chars per synthesis call; long replies split on sentences


def clean_speech(text):
    # Same cleanup as voice_worker: strip code blocks and markdown formatting.
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\\*\\*|__|(?<!\\w)\\*(?!\\s)", "", text)
    text = re.sub(r"(?m)^\\s*[-*]\\s+", "", text)
    text = re.sub(r"(?m)^\\s*#+\\s*", "", text)
    return " ".join(text.split())


def split_chunks(text):
    # Sentence-ish splits, each at most MAX_CHUNK chars.
    parts = re.split(r"(?<=[.!?])\\s+", text)
    chunks, cur = [], ""
    for part in parts:
        if len(cur) + 1 + len(part) <= MAX_CHUNK:
            cur = (cur + " " + part).strip()
        else:
            if cur:
                chunks.append(cur)
            while len(part) > MAX_CHUNK:  # hard split pathological runs
                chunks.append(part[:MAX_CHUNK])
                part = part[MAX_CHUNK:]
            cur = part
    if cur:
        chunks.append(cur)
    return chunks or [text[:MAX_CHUNK]]


def main():
    print("loading pocket tts ...", file=sys.stderr, flush=True)
    model = TTSModel.load_model()
    voice = model.get_state_for_audio_prompt(VOICE)
    src_rate = int(model.sample_rate)
    print(
        "pocket file worker ready (%s @ %dHz)" % (VOICE, src_rate),
        file=sys.stderr,
        flush=True,
    )
    print("READY", flush=True)

    gap = np.zeros(int(src_rate * 0.05), dtype=np.float32)  # 50ms between chunks
    for line in sys.stdin:
        line = line.rstrip("\n")
        if not line.strip():
            continue
        if line.strip() == "QUIT":
            break
        parts = line.split("\t", 2)
        if len(parts) != 3:
            print("ERR - bad-job", flush=True)
            continue
        jobid, outpath, text = parts
        text = clean_speech(text)
        if not text:
            print("ERR %s empty-text" % jobid, flush=True)
            continue
        try:
            started = time.time()
            pieces = []
            for chunk in split_chunks(text):
                for tensor in model.generate_audio_stream(voice, chunk):
                    arr = np.asarray(
                        tensor.detach().cpu().numpy(), dtype=np.float32
                    ).reshape(-1)
                    if arr.size:
                        pieces.append(arr)
                pieces.append(gap)
            if not pieces:
                raise ValueError("no audio generated")
            audio = np.concatenate(pieces)
            if src_rate != TARGET_RATE:
                n_out = max(int(len(audio) * TARGET_RATE / src_rate), 1)
                audio = np.interp(
                    np.linspace(0, len(audio) - 1, n_out),
                    np.arange(len(audio)),
                    audio,
                ).astype(np.float32)
            pcm16 = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2")
            with wave.open(outpath, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(TARGET_RATE)
                wav.writeframes(pcm16.tobytes())
            print("OK %s %.1fs" % (jobid, time.time() - started), flush=True)
        except Exception as error:
            print("ERR %s %s" % (jobid, str(error).replace("\n", " ")), flush=True)


if __name__ == "__main__":
    main()
