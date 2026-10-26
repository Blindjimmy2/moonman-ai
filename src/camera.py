import urllib.request
from pathlib import Path

CAMERA_URL = "http://192.168.1.11:8081/1/stream"

def capture_frame():
    print("Connecting to Moon Man's helmet camera...")

    request = urllib.request.Request(CAMERA_URL)

    with urllib.request.urlopen(request, timeout=10) as stream:
        buffer = bytearray()

        while len(buffer) < 5_000_000:
            chunk = stream.read(4096)

            if not chunk:
                raise RuntimeError("Camera stream disconnected.")

            buffer.extend(chunk)

            start = buffer.find(b"\xff\xd8")

            if start >= 0:
                end = buffer.find(b"\xff\xd9", start + 2)

                if end >= 0:
                    image = bytes(buffer[start:end + 2])
                    output = Path(__file__).resolve().parent.parent / "moonman_test.jpg"
                    output.write_bytes(image)

                    print(f"SUCCESS! Captured {len(image)} bytes.")
                    print(f"Saved image: {output}")
                    return

        raise RuntimeError("No JPEG frame found in camera stream.")

if __name__ == "__main__":
    capture_frame()
