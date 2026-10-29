
import json
import time
import websocket

ARCHIE_IP = "192.168.1.10"
ARCHIE_WS = f"ws://{ARCHIE_IP}:9999"

def connect_archie(seconds=15):
    print("MOON MAN: Contacting Archie...")
    print("Address:", ARCHIE_WS)

    ws = websocket.create_connection(
        ARCHIE_WS,
        timeout=5,
        enable_multithread=True
    )

    print("MOON MAN: WebSocket connected to Archie.")
    print("Listening for printer messages...")
    ws.settimeout(2)

    end = time.monotonic() + seconds
    count = 0

    try:
        while time.monotonic() < end:
            try:
                message = ws.recv()
                count += 1

                try:
                    data = json.loads(message)
                    print(
                        "ARCHIE:",
                        json.dumps(data, indent=2)[:3000]
                    )
                except (ValueError, TypeError):
                    print("ARCHIE:", str(message)[:3000])

            except websocket.WebSocketTimeoutException:
                continue

    finally:
        ws.close()

    print("MOON MAN: Connection closed.")
    print("Messages received:", count)
    return count

if __name__ == "__main__":
    try:
        connect_archie()
    except Exception as error:
        print("ARCHIE CONNECTION ERROR:", error)
        sys.exit(1)
