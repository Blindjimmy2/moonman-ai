"""Moon Man Meta MMS voice module; independent of existing agent.py."""
from pathlib import Path
import subprocess
import sys
import wave

MODEL_ID = "facebook/mms-tts-eng"
_model = None
_tokenizer = None


def speak(text: str, output_file: str = "moonman_voice.wav", play: bool = False) -> Path:
    """Synthesize text via Meta MMS English TTS, optionally play locally."""
    global _model, _tokenizer
    if not text or not text.strip():
        raise ValueError("Speech text must not be empty")
    import torch
    from transformers import VitsModel, AutoTokenizer

    if _model is None:
        print(f"Loading Meta speech model: {MODEL_ID}")
        _tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
        _model = VitsModel.from_pretrained(MODEL_ID).eval()

    # Text normalization is handled by the checkpoint tokenizer.
    inputs = _tokenizer(text, return_tensors="pt")
    with torch.no_grad():
        output = _model(**inputs).waveform.squeeze().cpu().numpy()

    import numpy as np
    pcm = (np.clip(output, -1, 1) * 32767).astype(np.int16)
    path = Path(output_file).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(_model.config.sampling_rate)
        f.writeframes(pcm.tobytes())
    print(f"Saved: {path}")

    if play:
        if sys.platform.startswith("win"):
            import winsound
            winsound.PlaySound(str(path), winsound.SND_FILENAME)
        elif sys.platform.startswith("linux"):
            subprocess.run(["aplay", str(path)], check=True)
        else:
            print("Playback not configured on this platform; open the WAV manually.")
    return path


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Moon Man's Meta TTS test")
    parser.add_argument("text", nargs="?", default=(
        "Och, look who finally showed up. I've been keeping an eye on "
        "these printers all morning. Someone has to run this workshop."
    ))
    parser.add_argument("--play", action="store_true", help="Play through the computer's speaker")
    parser.add_argument("--output", default="moonman_voice.wav")
    args = parser.parse_args()
    speak(args.text, args.output, args.play)
