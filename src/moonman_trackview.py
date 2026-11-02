#!/usr/bin/env python3
"""MoonMan tracking debug overlay (LAPTOP, optional).

Shows the helmet-cam feed with face boxes, the agent's current gaze focus
(highlighted), crosshair, pan/tilt state, sim servo commands, FPS and
detection confidence. READ-ONLY: subscribes to tracker status, never
publishes gaze or servo commands.

The camera stream has exactly one continuous reader (this preview). The
agent's snapshots (capture_image) are separate short HTTP connections and
coexist fine. The tracker never reads frames.

Face boxes are a visual aid (YuNet detector, local). The HIGHLIGHTED box
is the agent's doing: whichever box sits under his latest gaze_point
focus. He can also gaze where no face exists; then only the gaze
reticle shows.

Own process: closing the window (X, Q, ESC) stops ONLY this preview.
Agent, bridge, voice and tracker keep running headless.

Needs: py -m pip install opencv-python  (YuNet model sits next to this file)

Launch:
  py moonman_trackview.py [--selftest N] [--no-faces]
"""

import base64
import json
import os
import sys
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
BROKER = os.environ.get("MOONMAN_BROKER", "192.168.1.11")
PORT = int(os.environ.get("MOONMAN_MQTT_PORT", "1883"))
CAMERA_URL = os.environ.get("MOONMAN_CAMERA_URL",
                             "http://192.168.1.11:8081/1/stream")
STATUS_TOPIC = "moonman/track/status"
FACES_TOPIC = "moonman/track/faces"
LOOK_TOPIC = "moonman/track/look"
EYE_LOOK_TOPIC = "moonman/eye/all/look"
EYE_MIRROR_X = -1.0  # keep in sync with tracker MIRROR_X
EYE_MIRROR_Y = -1.0  # keep in sync with tracker MIRROR_Y
PAN_TOPIC = "moonman/helmet/angle"
TILT_TOPIC = "moonman/helmet/tilt"
MODEL_PATH = os.path.join(HERE, "face_detection_yunet.onnx")
MAX_W = 960            # downscale display wider than this
DETECT_EVERY = 2       # run the detector every Nth frame
SCORE_THRESH = 0.6
STATUS_STALE_SEC = 3.0


def log(*a):
    print("[trackview]", *a, flush=True)


class Shared:
    def __init__(self):
        self.lock = threading.Lock()
        self.status = None      # tracker status dict
        self.status_ts = 0.0
        self.sim_pan = None     # last raw servo pubs (when SIM off)
        self.sim_tilt = None


def mqtt_thread(shared):
    try:
        import paho.mqtt.client as mqtt_mod
    except ImportError:
        log("paho-mqtt missing: state overlay disabled (video still works)")
        return
    try:
        client = mqtt_mod.Client(mqtt_mod.CallbackAPIVersion.VERSION2)
    except Exception:
        client = mqtt_mod.Client()

    def on_message(_c, _u, m):
        try:
            payload = m.payload.decode("utf-8", "replace")
        except Exception:
            return
        with shared.lock:
            if m.topic == STATUS_TOPIC:
                try:
                    shared.status = json.loads(payload)
                    shared.status_ts = time.time()
                except Exception:
                    pass
            elif m.topic == PAN_TOPIC:
                shared.sim_pan = payload.strip()
            elif m.topic == TILT_TOPIC:
                shared.sim_tilt = payload.strip()

    def on_connect(c, _u, _f, rc, _p=None):
        if rc == 0:
            c.subscribe([(STATUS_TOPIC, 0), (PAN_TOPIC, 0), (TILT_TOPIC, 0)])
            log("mqtt up")
        else:
            log("mqtt connect failed rc=", rc)

    client.on_connect = on_connect  # _p=None default fits paho v1 and v2
    client.on_message = on_message
    shared.client = client  # main loop borrows it for faces telemetry
    while True:
        try:
            client.connect(BROKER, PORT, keepalive=30)
            client.loop_forever()
        except Exception as error:
            log("mqtt down (%s), retrying..." % error)
            time.sleep(3.0)


def frame_reader():
    """Yield JPEG bytes from the MJPEG stream (sole continuous reader)."""
    while True:
        try:
            req = urllib.request.Request(CAMERA_URL)
            stream = urllib.request.urlopen(req, timeout=10)
        except Exception as error:
            log("camera down (%s), retrying..." % error)
            time.sleep(3.0)
            continue
        buf = bytearray()
        try:
            while True:
                chunk = stream.read(4096)
                if not chunk:
                    raise RuntimeError("stream closed")
                buf.extend(chunk)
                if len(buf) > 5_000_000:
                    del buf[:-1_000_000]
                # Realtime: newest complete JPEG only, drop stale.
                end = buf.rfind(b"\xff\xd9")
                if end < 0:
                    continue
                start = buf.rfind(b"\xff\xd8", 0, end)
                if start < 0:
                    continue
                jpg = bytes(buf[start:end + 2])
                del buf[:]
                yield jpg
        except Exception as error:
            log("camera read failed (%s), reconnecting..." % error)
            try:
                stream.close()
            except Exception:
                pass
            time.sleep(1.0)


def main():
    import cv2
    import numpy as np

    args = sys.argv[1:]
    selftest = 0
    if "--selftest" in args:
        i = args.index("--selftest")
        try:
            selftest = int(args[i + 1])
        except (IndexError, ValueError):
            selftest = 30
    no_faces = "--no-faces" in args

    det = None
    if not no_faces:
        if not os.path.exists(MODEL_PATH):
            log("face model missing (%s): boxes disabled" % MODEL_PATH)
        else:
            det = cv2.FaceDetectorYN_create(MODEL_PATH, "", (320, 320))
            log("face detector ready (YuNet)")

    shared = Shared()
    threading.Thread(target=mqtt_thread, args=(shared,), daemon=True).start()

    win = "MoonMan TRACK (preview only - X/Q/ESC closes just this)"
    faces = []
    det_size = (0, 0)
    fps, frames, faces_seen, det_err = 0.0, 0, 0, 0
    look_blank = False
    shape = "?"
    prev = time.time()
    for jpg in frame_reader():
        try:
            now = time.time()
            dt = now - prev
            prev = now
            if dt > 0:
                fps = fps * 0.9 + (1.0 / dt) * 0.1
            img = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8),
                               cv2.IMREAD_COLOR)
            if img is None:
                continue
            if img.shape[1] > MAX_W:
                s = MAX_W / img.shape[1]
                img = cv2.resize(img, (MAX_W, int(img.shape[0] * s)))
            h, w = img.shape[:2]
            shape = "%dx%d" % (w, h)
            frames += 1

            # Faces (throttled; boxes persist between runs).
            if det is not None and frames % DETECT_EVERY == 0:
                if det_size != (w, h):
                    det.setInputSize((w, h))
                    det_size = (w, h)
                try:
                    _, found = det.detect(img)
                except Exception:
                    found = None
                    det_err += 1
                faces = []
                if found is not None:
                    for f in found:
                        x, y, bw, bh = (int(v) for v in f[:4])
                        faces.append((x, y, bw, bh, float(f[14])))
                faces_seen += len(faces)

                # Gaze reflex at detection rate: largest (closest)
                # face steers the head AND the eye pupils. Camera
                # rides the head so the tracker mapping converges.
                _cli = getattr(shared, "client", None)
                if faces and _cli is not None:
                    try:
                        _x, _y, _bw, _bh, _ = max(
                            faces, key=lambda f: f[2] * f[3])
                        _fx = (_x + _bw / 2) / w
                        _fy = (_y + _bh / 2) / h
                        _cli.publish(LOOK_TOPIC, json.dumps({
                            "fx": round(_fx, 4),
                            "fy": round(_fy, 4)}))
                        _rx = int(EYE_MIRROR_X * (_fx - 0.5) * 200)
                        _ry = int(EYE_MIRROR_Y * (_fy - 0.5) * 200)
                        _cli.publish(EYE_LOOK_TOPIC, "%d,%d" % (
                            max(-100, min(100, _rx)),
                            max(-100, min(100, _ry))))
                    except Exception:
                        pass
                    look_blank = False
                elif _cli is not None and not look_blank:
                    try:
                        _cli.publish(EYE_LOOK_TOPIC, "center")
                    except Exception:
                        pass
                    look_blank = True

            with shared.lock:
                status = dict(shared.status) if shared.status else None
                status_age = now - shared.status_ts
                sim_pan, sim_tilt = shared.sim_pan, shared.sim_tilt
            online = (status is not None and status.get("online") and
                      status_age < STATUS_STALE_SEC)
            focus = (status or {}).get("focus") if online else None

            # Match focus to nearest face for the highlight.
            hi = -1
            if focus:
                fx, fy = focus["fx"] * w, focus["fy"] * h
                best = (min(w, h) * 0.25) ** 2
                for i, (x, y, bw, bh, _) in enumerate(faces):
                    cx, cy = x + bw / 2, y + bh / 2
                    d2 = (cx - fx) ** 2 + (cy - fy) ** 2
                    if d2 < best:
                        best, hi = d2, i

            # Faces telemetry for Mission Control (display logic untouched).
            if frames % 10 == 0:
                cli = getattr(shared, "client", None)
                if cli is not None:
                    try:
                        cli.publish(FACES_TOPIC, json.dumps({
                            "count": len(faces),
                            "conf": round(max([c for _, _, _, _, c in faces]
                                              + [0.0]), 2),
                            "fps": round(fps, 1)}))
                    except Exception:
                        pass

            if selftest:
                if frames >= selftest:
                    break
                continue

            # ---- draw ----
            for i, (x, y, bw, bh, conf) in enumerate(faces):
                color = (0, 255, 255) if i == hi else (0, 255, 0)
                thick = 3 if i == hi else 2
                cv2.rectangle(img, (x, y), (x + bw, y + bh), color, thick)
                cv2.putText(img, "%.2f" % conf, (x, max(y - 6, 12)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
            if focus:
                fx, fy = int(focus["fx"] * w), int(focus["fy"] * h)
                cv2.drawMarker(img, (fx, fy), (255, 0, 255),
                               cv2.MARKER_TILTED_CROSS, 24, 2)
                cv2.circle(img, (fx, fy), 30, (255, 0, 255), 1)
            cx, cy = w // 2, h // 2
            cv2.drawMarker(img, (cx, cy), (255, 255, 255),
                           cv2.MARKER_CROSS, 20, 1)
            if focus:
                cv2.line(img, (cx, cy), (fx, fy), (255, 255, 255), 1)

            pan = (status or {}).get("pan", "?")
            tilt = (status or {}).get("tilt", "?")
            mode = (status or {}).get("mode", "?")
            if sim_pan is None:  # SIM mode: state doubles as the sim command
                sim_pan, sim_tilt = pan, tilt
            lines = [
                "%s mode=%s faces=%d fps=%.0f" % (
                    "TRACKER ONLINE" if online else "TRACKER OFFLINE",
                    mode, len(faces), fps),
                "PAN %s  TILT %s" % (pan, tilt),
                "SIM SERVO pan=%s tilt=%s" % (sim_pan, sim_tilt),
                ("FOCUS %.2f,%.2f age=%.0fs" % (
                    focus["fx"], focus["fy"], focus["age"])
                 if focus else "focus: none"),
            ]
            y0 = 22
            for line in lines:
                cv2.putText(img, line, (10, y0), cv2.FONT_HERSHEY_SIMPLEX,
                            0.6, (0, 0, 0), 3)
                cv2.putText(img, line, (10, y0), cv2.FONT_HERSHEY_SIMPLEX,
                            0.6, (255, 255, 255), 1)
                y0 += 24

            cv2.imshow(win, img)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            try:
                if cv2.getWindowProperty(win, cv2.WND_PROP_VISIBLE) < 1:
                    break  # X button
            except Exception:
                break
        except Exception as error:
            log("frame error (%s), continuing..." % error)
            continue

    if selftest:
        with shared.lock:
            snap = dict(shared.status) if shared.status else None
        print("SELFTEST frames=%d shape=%s faces_seen=%d det_err=%d fps=%.1f status=%s" % (
            frames, shape, faces_seen, det_err, fps, json.dumps(snap)))
        return 0
    cv2.destroyAllWindows()
    log("preview closed (agent/voice/tracker untouched)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
