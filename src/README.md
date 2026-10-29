# Moon Man — Meta MMS voice test

This is a **standalone voice module**. It does not change your existing Moon Man agent, MQTT code, servos or printer controls.

## Test on Windows (PowerShell)

```powershell
cd C:\MoonworksDev\moonman-ai
py -m pip install -r path\to\moonman_meta_voice\requirements.txt
py path\to\moonman_meta_voice\meta_voice.py --play
```

Or copy `meta_voice.py` and `requirements.txt` into `C:\MoonworksDev\moonman-ai\src` and run:

```powershell
cd C:\MoonworksDev\moonman-ai\src
py -m pip install -r requirements.txt
py meta_voice.py --play
```

First run will download the model checkpoint from Hugging Face. Network required for installation and first run.

## Later: integrate into agent.py

After validating the voice, add:

```python
from meta_voice import speak
# where the agent has produced its final reply text:
speak(reply_text, play=True)
```

Do not add this blindly until you identify your agent's response and audio location. On Raspberry Pi install `alsa-utils` if `aplay` is missing and configure the actual audio output device.

## Limitations

- This English MMS model is a Meta-authored speech model, not the current Meta Model API / Muse conversational model. It does not make the entire agent Meta-powered.
- The English voice has **no controlled Scottish-accent selection**; Scottish spellings in text won't reliably produce a Scottish voice.
- This specific model uses **CC BY-NC 4.0 (noncommercial)**. Verify rights for any commercial use, distribution, or competition-specific terms.
- Live low-latency dialogue is a later integration; this module generates a WAV file per response.
- Raspberry Pi CPU performance varies; first test on the Windows development PC.
