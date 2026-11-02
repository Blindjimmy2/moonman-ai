#!/usr/bin/env python3
"""MoonMan head tracker: eased helmet motion + MQTT gaze commands (LAPTOP).

Owns the servo MOTION (the eye firmware snaps instantly, so all easing
lives here). The Meta agent owns ATTENTION: it looks at the helmet-cam
image and sends gaze targets; this daemon slews the head there like
muscle, not like a stepper.

Subscribes:
  moonman/track/look   {"pan": 0-180, "tilt": 45-135} absolute, and/or
                       {"dpan": .., "dtilt": ..} relative degrees, and/or
                       {"fx": 0-1, "fy": 0-1} image fractions (target spot)
  moonman/track/mode   "auto" (idle wander + drift home) or "still" (hold)
Publishes:
  moonman/helmet/angle  int degrees, eased, <=10Hz, on change >=1
  moonman/helmet/tilt   int degrees, eased, <=10Hz, on change >=1
  moonman/track/status  retained {"pan","tilt","mode","online":true}

Motion feel: exponential ease toward target with a slew-rate cap, so a
new target gets a quick saccade that settles instead of snapping. In
auto mode with no recent command the head drifts home slowly with a
faint idle sway (toggle AUTOSWAY).

Sign conventions (flip MIRROR_X/Y if he looks the wrong way on the rig):
  fx < 0.5 (target left of frame) -> pan decreases toward 0 (LEFT)
  fy < 0.5 (target high in frame) -> tilt decreases toward 45 (UP)

Run (system Python, needs paho-mqtt):
  py moonman_track.py
"""

import json
import math
import os
import sys
import threading
import time

BROKER = os.environ.get("MOONMAN_BROKER", "192.168.1.11")
PORT = int(os.environ.get("MOONMAN_MQTT_PORT", "1883"))
LOOK_TOPIC = "moonman/track/look"
MODE_TOPIC = "moonman/track/mode"
STATUS_TOPIC = "moonman/track/status"
PAN_TOPIC = "moonman/helmet/angle"
TILT_TOPIC = "moonman/helmet/tilt"

HOME_PAN, HOME_TILT = 90.0, 90.0
PAN_MIN, PAN_MAX = 0.0, 180.0
TILT_MIN, TILT_MAX = 45.0, 135.0
PAN_SPEED = 120.0    # deg/sec saccade cap
TILT_SPEED = 90.0
HOME_SPEED = 25.0    # slow drift home when idle
FX_DEG = 60.0        # full image width in pan degrees (tune to lens)
FY_DEG = 45.0        # full image height in tilt degrees
LOOK_GAIN = 0.6      # nudge scale per face message
LOOK_DEADBAND = 0.03  # ignore offsets < 3% of frame (lock)
MIRROR_X = -1.0       # set -1.0 if left/right is flipped on the rig
MIRROR_Y = -1.0       # set -1.0 if up/down is flipped on the rig
IDLE_HOME_SEC = 5.0  # no commands -> drift home (auto mode only)
AUTOSWAY = True
SWAY_DEG = 1.5
SWAY_HZ = 0.15
LOOP_DT = 0.05       # 20 Hz motion loop
PUB_MIN_DT = 0.1     # at most 10 servo pubs/sec
PUB_MIN_DEG = 1      # only publish whole-degree changes
SIM_ONLY = False        # True: suppress moonman/helmet/* servo pubs (sim only)
FOCUS_KEEP_SEC = 15.0  # status keeps the last agent focus this long

_state_lock = threading.Lock()
_pan, _tilt = HOME_PAN, HOME_TILT
_tpan, _ttilt = HOME_PAN, HOME_TILT
_mode = "auto"
_last_cmd = 0.0
_focus = None          # {"fx","fy","ts"} of last agent gaze_point


def log(*a):
    print("[track]", *a, flush=True)


def _clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def on_look(payload):
    global _tpan, _ttilt, _last_cmd, _focus
    try:
        obj = json.loads(payload.decode("utf-8", "replace"))
    except Exception:
        log("ignoring non-JSON look command")
        return
    with _state_lock:
        if "pan" in obj:
            _tpan = _clamp(float(obj["pan"]), PAN_MIN, PAN_MAX)
        if "tilt" in obj:
            _ttilt = _clamp(float(obj["tilt"]), TILT_MIN, TILT_MAX)
        if "dpan" in obj:
            _tpan = _clamp(_tpan + float(obj["dpan"]), PAN_MIN, PAN_MAX)
        if "dtilt" in obj:
            _ttilt = _clamp(_ttilt + float(obj["dtilt"]), TILT_MIN, TILT_MAX)
        if "fx" in obj and "fy" in obj:
            fx = _clamp(float(obj["fx"]), 0.0, 1.0)
            fy = _clamp(float(obj["fy"]), 0.0, 1.0)
            ex, ey = fx - 0.5, fy - 0.5
            if abs(ex) >= LOOK_DEADBAND:
                _tpan = _clamp(_tpan + MIRROR_X * ex * FX_DEG * LOOK_GAIN,
                               PAN_MIN, PAN_MAX)
            if abs(ey) >= LOOK_DEADBAND:
                _ttilt = _clamp(_ttilt + MIRROR_Y * ey * FY_DEG * LOOK_GAIN,
                                TILT_MIN, TILT_MAX)
            _focus = {"fx": fx, "fy": fy, "ts": time.time()}
        _last_cmd = time.time()
        log("target pan=%.0f tilt=%.0f" % (_tpan, _ttilt))


def on_mode(payload):
    global _mode, _last_cmd
    mode = payload.decode("utf-8", "replace").strip().lower()
    if mode not in ("auto", "still"):
        log("ignoring bad mode:", mode)
        return
    with _state_lock:
        _mode = mode
        _last_cmd = time.time()
    log("mode", mode)


def motion_loop(client):
    global _pan, _tilt
    last_pub, last_pan_i, last_tilt_i = 0.0, None, None
    last_status = 0.0
    while True:
        now = time.time()
        with _state_lock:
            tpan, ttilt = _tpan, _ttilt
            idle = (now - _last_cmd) > IDLE_HOME_SEC
            auto = (_mode == "auto")
        if auto and idle:
            # Slow drift home; the ease below keeps it graceful.
            tpan, ttilt = HOME_PAN, HOME_TILT
            speed_p, speed_t = HOME_SPEED, HOME_SPEED
        else:
            speed_p, speed_t = PAN_SPEED, TILT_SPEED
        # Exponential ease + slew cap = fast start, soft landing.
        for _ in (0,):
            err_p, err_t = tpan - _pan, ttilt - _tilt
            step_p = err_p * min(1.0, LOOP_DT * 6.0)
            step_t = err_t * min(1.0, LOOP_DT * 6.0)
            cap_p, cap_t = speed_p * LOOP_DT, speed_t * LOOP_DT
            step_p = _clamp(step_p, -cap_p, cap_p)
            step_t = _clamp(step_t, -cap_t, cap_t)
            if abs(err_p) < 0.3:
                step_p = err_p
            if abs(err_t) < 0.3:
                step_t = err_t
            _pan = _clamp(_pan + step_p, PAN_MIN, PAN_MAX)
            _tilt = _clamp(_tilt + step_t, TILT_MIN, TILT_MAX)
        pub_pan, pub_tilt = _pan, _tilt
        if AUTOSWAY and auto and idle:
            sway = math.sin(now * 2 * math.pi * SWAY_HZ) * SWAY_DEG
            pub_pan = _clamp(pub_pan + sway, PAN_MIN, PAN_MAX)
            pub_tilt = _clamp(pub_tilt + sway * 0.5, TILT_MIN, TILT_MAX)
        pan_i, tilt_i = int(round(pub_pan)), int(round(pub_tilt))
        if (now - last_pub >= PUB_MIN_DT and
                (last_pan_i is None or abs(pan_i - last_pan_i) >= PUB_MIN_DEG
                 or abs(tilt_i - last_tilt_i) >= PUB_MIN_DEG)):
            if not SIM_ONLY:
                client.publish(PAN_TOPIC, str(pan_i))
                client.publish(TILT_TOPIC, str(tilt_i))
            last_pub, last_pan_i, last_tilt_i = now, pan_i, tilt_i
        if now - last_status >= 1.0:
            with _state_lock:
                mode = _mode
                focus = dict(_focus) if _focus else None
            if focus:
                focus["age"] = round(now - focus.pop("ts"), 1)
                if focus["age"] > FOCUS_KEEP_SEC:
                    focus = None
            client.publish(STATUS_TOPIC, json.dumps({
                "pan": pan_i, "tilt": tilt_i, "mode": mode,
                "focus": focus, "online": True}), retain=True)
            last_status = now
        time.sleep(LOOP_DT)


def main():
    try:
        import paho.mqtt.client as mqtt_mod
    except ImportError:
        log("paho-mqtt missing: py -m pip install paho-mqtt")
        sys.exit(1)
    try:
        client = mqtt_mod.Client(mqtt_mod.CallbackAPIVersion.VERSION2)
    except Exception:
        client = mqtt_mod.Client()
    client.will_set(STATUS_TOPIC, json.dumps({"online": False}), retain=True)

    def on_connect(c, _u, _f, rc, _p=None):
        if rc == 0:
            c.subscribe([(LOOK_TOPIC, 0), (MODE_TOPIC, 0)])
            c.publish(STATUS_TOPIC, json.dumps({
                "pan": 90, "tilt": 90, "mode": "auto",
                "online": True}), retain=True)
            log("tracker up on %s:%d" % (BROKER, PORT))
            if SIM_ONLY:
                log("SIM MODE: servo topics suppressed (flip SIM_ONLY for hardware)")
        else:
            log("mqtt connect failed rc=", rc)

    def on_message(_c, _u, m):
        if m.topic == LOOK_TOPIC:
            on_look(m.payload)
        elif m.topic == MODE_TOPIC:
            on_mode(m.payload)

    client.on_connect = on_connect  # _p=None default fits paho v1 and v2
    client.on_message = on_message
    log("connecting to broker %s:%d ..." % (BROKER, PORT))
    client.connect(BROKER, PORT, keepalive=30)
    client.loop_start()
    try:
        motion_loop(client)
    except KeyboardInterrupt:
        client.publish(STATUS_TOPIC, json.dumps({"online": False}), retain=True)
        log("stopping")


if __name__ == "__main__":
    main()
