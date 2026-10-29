Moon Man Pocket TTS Voice Integration

Copy voice_worker.py into C:\MoonworksDev\moonman-ai\src\

At the top of src\agent.py make sure you have:
import subprocess
import sys
from pathlib import Path

Immediately before the existing main `while True:` input loop in the
`if __name__ == "__main__":` block, add:

    voice_python = r"C:\MoonworksDev\moonman-voice-test\Scripts\python.exe"
    voice_script = Path(__file__).with_name("voice_worker.py")
    voice_process = subprocess.Popen(
        [voice_python, str(voice_script)],
        stdin=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

Inside the existing conversation loop, replace the old
`if answer: subprocess.run([...meta_voice.py...])` block with:

        if answer and voice_process.poll() is None:
            try:
                voice_process.stdin.write(answer.replace("\n", " ") + "\n")
                voice_process.stdin.flush()
            except (BrokenPipeError, OSError) as error:
                print(f"Voice unavailable: {error}")

After the main while loop ends, add:

    if voice_process.poll() is None:
        voice_process.stdin.close()
        voice_process.wait(timeout=30)

Run:
cd C:\MoonworksDev\moonman-ai\src
py -m py_compile agent.py
py agent.py

Note: Voice playback happens in the worker; it remains loaded between answers.
Playback queues sequentially. Stop old Pocket TTS server if RAM is tight.
