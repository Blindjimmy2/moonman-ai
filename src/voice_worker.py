"""Persistent streaming Pocket TTS worker for Moon Man (Windows)."""
import sys
import re
import numpy as np
import sounddevice as sd
from pocket_tts import TTSModel

VOICE = "stuart_bell"


def clean_speech(text):
    # Remove code blocks and inline code formatting.
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\\1", text)

    # Remove Markdown formatting.
    text = re.sub(r"\\*\\*|__|(?<!\\w)\\*(?!\\s)", "", text)
    text = re.sub(r"(?m)^\\s*[-*]\\s+", "", text)
    text = re.sub(r"(?m)^\\s*#+\\s*", "", text)

    # Collapse whitespace.
    return " ".join(text.split())


def main():
    print("Loading Moon Man's Pocket TTS voice...", file=sys.stderr, flush=True)

    model = TTSModel.load_model()
    voice = model.get_state_for_audio_prompt(VOICE)

    print("Moon Man's streaming voice is ready.", file=sys.stderr, flush=True)

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
                for chunk in model.generate_audio_stream(voice, text):
                    samples = chunk.detach().cpu().numpy()
                    samples = np.asarray(samples, dtype=np.float32).reshape(-1, 1)
                    if samples.size:
                        stream.write(samples)

        except Exception as error:
            print(f"Voice error: {error}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
