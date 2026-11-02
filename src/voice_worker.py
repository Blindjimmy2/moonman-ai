"""Persistent streaming Pocket TTS worker for Moon Man (Windows)."""
import sys
import re
import numpy as np
import sounddevice as sd
from pocket_tts import TTSModel

VOICE = "stuart_bell"
MAX_CHUNK = 400  # chars per synthesis call; long replies split on sentences


def clean_speech(text):
    # Remove code blocks and inline code formatting.
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)

    # Remove Markdown formatting.
    text = re.sub(r"\*\*|__|(?<!\w)\*(?!\s)", "", text)
    text = re.sub(r"(?m)^\s*[-*]\s+", "", text)
    text = re.sub(r"(?m)^\s*#+\s*", "", text)

    # Collapse whitespace.
    return " ".join(text.split())


def split_chunks(text):
    # Sentence-ish splits, each at most MAX_CHUNK chars (same rule as the
    # file worker, so both voices chunk identically).
    parts = re.split(r"(?<=[.!?])\s+", text)
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
    print("Loading Moon Man's Pocket TTS voice...", file=sys.stderr, flush=True)

    model = TTSModel.load_model()
    voice = model.get_state_for_audio_prompt(VOICE)

    print("Moon Man's streaming voice is ready.", file=sys.stderr, flush=True)

    gap = np.zeros((int(model.sample_rate * 0.05), 1), dtype=np.float32)
    for line in sys.stdin:
        text = clean_speech(line.strip())
        if not text:
            continue

        try:
            with sd.OutputStream(
                samplerate=model.sample_rate,
                channels=1,
                dtype="float32"
            ) as stream:
                chunks = split_chunks(text)
                for index, piece in enumerate(chunks):
                    for chunk in model.generate_audio_stream(voice, piece):
                        samples = chunk.detach().cpu().numpy()
                        samples = np.asarray(samples, dtype=np.float32).reshape(-1, 1)
                        if samples.size:
                            stream.write(samples)
                    if index < len(chunks) - 1:
                        stream.write(gap)

        except Exception as error:
            print(f"Voice error: {error}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
