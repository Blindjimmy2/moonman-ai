"""Persistent Pocket TTS playback worker for Moon Man (Windows)."""
import sys
import winsound
from pathlib import Path

import numpy as np
from scipy.io.wavfile import write
from pocket_tts import TTSModel

VOICE = "stuart_bell"
OUTPUT = Path(__file__).with_name("moonman_pocket.wav")


def main():
    print("Loading Moon Man's Pocket TTS voice...", file=sys.stderr, flush=True)
    model = TTSModel.load_model()
    voice = model.get_state_for_audio_prompt(VOICE)
    print("Moon Man's voice is ready.", file=sys.stderr, flush=True)

    for line in sys.stdin:
        text = line.strip()
        if not text:
            continue
        try:
            audio = model.generate_audio(voice, text)
            pcm = (np.clip(audio.detach().cpu().numpy(), -1, 1) * 32767).astype(np.int16)
            write(str(OUTPUT), model.sample_rate, pcm)
            winsound.PlaySound(str(OUTPUT), winsound.SND_FILENAME)
        except Exception as error:
            print(f"Voice error: {error}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
