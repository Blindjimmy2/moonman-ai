#!/usr/bin/env python3
"""MoonMan Mission Control: local dashboard + service manager (LAPTOP).

One server, localhost only: http://localhost:8100/
Start / stop / restart MoonMan's laptop services, watch status, PID,
uptime and recent logs, plus live tracker state and the helmet cam.

Managed services (never double-started: live-handle + pidfile + port
checks; only processes this dashboard started are ever stopped):
  brain  moonman_mqtt_bridge.py    (system python)
  voice  moonman_brain_voice.py    (its own .venv python, port 8099)
  track  moonman_track.py          (system python)
  view   moonman_trackview.py      (system python, needs a display)

Shutdown: Ctrl+C or the Stop All button stops managed children first.
Killing this window's process hard on Windows orphans children (the OS
gives no intercept); pidfiles mark orphans so the next launch refuses
to double-start them instead of piling on.

Launch:
  py C:\\MoonworksDev\\moonman-ai\\src\\moonman_control.py
Test port: MOONMAN_CONTROL_PORT=18100
"""

import atexit
import collections
import ctypes.wintypes
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
HOST = "127.0.0.1"  # localhost only, always
PORT = int(os.environ.get("MOONMAN_CONTROL_PORT", "8100"))
BROKER = os.environ.get("MOONMAN_BROKER", "192.168.1.11")
MQTT_PORT = int(os.environ.get("MOONMAN_MQTT_PORT", "1883"))
CAMERA_URL = os.environ.get("MOONMAN_CAMERA_URL",
                             "http://192.168.1.11:8081/1/stream")
VOICE_DIR = r"C:\Users\twill\Documents\MoonMan"
VOICE_PY = os.path.join(VOICE_DIR, ".venv", "Scripts", "python.exe")
PIDDIR = os.path.join(os.environ.get("TEMP", HERE), "moonman-ctl")
LOG_KEEP = 300

STARTED_AT = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def _packed_ref(dotgit, ref):
    try:
        with open(os.path.join(dotgit, "packed-refs")) as handle:
            for line in handle:
                if line.rstrip("\n").endswith(" " + ref):
                    return line.split(" ", 1)[0].strip()
    except OSError:
        pass
    return ""


def _git_hash():
    """Short commit hash + branch for the footer. Never raises."""
    try:
        dotgit = os.path.join(os.path.dirname(HERE), ".git")
        with open(os.path.join(dotgit, "HEAD")) as handle:
            head = handle.read().strip()
        branch, full = "", ""
        if head.startswith("ref:"):
            ref = head.split(" ", 1)[1].strip()
            branch = ref.split("/")[-1]
            try:
                with open(os.path.join(dotgit, *ref.split("/"))) as handle:
                    full = handle.read().strip()
            except OSError:
                full = _packed_ref(dotgit, ref)
        else:
            full = head
        if len(full) < 7 or any(
                c not in "0123456789abcdef" for c in full[:40]):
            return "unknown"
        short = full[:7]
        return "%s@%s" % (branch, short) if branch else short
    except Exception:
        return "unknown"

SERVICES = {
    "brain": {"label": "Brain (MQTT bridge)",
              "argv": [sys.executable, "moonman_mqtt_bridge.py"], "cwd": HERE},
    "voice": {"label": "Voice server",
              "argv": [VOICE_PY, "moonman_brain_voice.py"], "cwd": VOICE_DIR,
              "port": 8099},
    "track": {"label": "Tracking",
              "argv": [sys.executable, "moonman_track.py"], "cwd": HERE},
    "view": {"label": "Tracking preview",
              "argv": [sys.executable, "moonman_trackview.py"], "cwd": HERE},
}

_state = {n: {"proc": None, "started": 0.0, "exit": None,
              "logs": collections.deque(maxlen=LOG_KEEP)}
          for n in SERVICES}
_lock = threading.Lock()
_mqtt = {"track": None, "track_ts": 0.0, "faces": None, "faces_ts": 0.0,
         "ok": False, "client": None, "mic": None, "mic_ts": 0.0,
         "ear": None, "ear_ts": 0.0}
_ask_pending = {}  # req_id -> {"event": Event, "text": str, "status": str}


def log(*a):
    print("[control]", *a, flush=True)


def _pidfile(name):
    return os.path.join(PIDDIR, "moonman-ctl-%s.pid" % name)


_STILL_ACTIVE = 259
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_ERROR_INVALID_PARAMETER = 87

if hasattr(ctypes, "windll"):
    _K32 = ctypes.windll.kernel32
    _K32.OpenProcess.argtypes = [ctypes.wintypes.DWORD,
                                 ctypes.wintypes.BOOL, ctypes.wintypes.DWORD]
    _K32.OpenProcess.restype = ctypes.wintypes.HANDLE
    _K32.GetExitCodeProcess.argtypes = [
        ctypes.wintypes.HANDLE, ctypes.POINTER(ctypes.wintypes.DWORD)]
    _K32.GetExitCodeProcess.restype = ctypes.wintypes.BOOL
    _K32.GetProcessTimes.argtypes = [ctypes.wintypes.HANDLE] + \
        [ctypes.POINTER(ctypes.wintypes.FILETIME)] * 4
    _K32.GetProcessTimes.restype = ctypes.wintypes.BOOL
    _K32.CloseHandle.argtypes = [ctypes.wintypes.HANDLE]
    _K32.CloseHandle.restype = ctypes.wintypes.BOOL
    _K32.GetLastError.argtypes = []
    _K32.GetLastError.restype = ctypes.wintypes.DWORD
else:
    _K32 = None


def _pid_create_time(pid):
    """Process creation time as epoch seconds. None when unknown."""
    if _K32 is None:
        return None
    try:
        handle = _K32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION,
                                  False, pid)
        if not handle:
            return None
        try:
            created = ctypes.wintypes.FILETIME()
            dummy = ctypes.wintypes.FILETIME()
            ok = _K32.GetProcessTimes(
                handle, ctypes.byref(created), ctypes.byref(dummy),
                ctypes.byref(dummy), ctypes.byref(dummy))
            if not ok:
                return None
            ticks = (created.dwHighDateTime << 32) | created.dwLowDateTime
            return ticks / 10000000.0 - 11644473600.0
        finally:
            _K32.CloseHandle(handle)
    except Exception:
        return None


def _pid_alive(pid):
    """True only if the process exists AND is still running.

    os.kill(pid, 0) alone lies on Windows: it succeeds for a
    terminated process while any handle to it stays open (including
    our own unreaped Popen object), which wedged crashed services as
    permanent phantom orphans blocking their own restart. The exit
    code is the truth: STILL_ACTIVE means running. Fail closed: a
    process we cannot query (access denied) counts as alive so we
    never double-start over it.
    """
    try:
        if _K32 is not None:
            handle = _K32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION,
                                      False, pid)
            if not handle:
                return _K32.GetLastError() != _ERROR_INVALID_PARAMETER
            try:
                code = ctypes.wintypes.DWORD()
                if not _K32.GetExitCodeProcess(handle, ctypes.byref(code)):
                    return True  # unqueryable: fail closed
                return code.value == _STILL_ACTIVE
            finally:
                _K32.CloseHandle(handle)
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _pidfile_pid(name):
    try:
        with open(_pidfile(name)) as f:
            parts = f.read().strip().split()
            pid = int(parts[0])
            born = float(parts[1]) if len(parts) > 1 else None
    except Exception:
        return None
    if not _pid_alive(pid):
        try:
            os.remove(_pidfile(name))  # stale: process is gone
        except Exception:
            pass
        return None
    if born is not None:
        actual = _pid_create_time(pid)
        if actual is not None and abs(actual - born) > 5.0:
            try:
                os.remove(_pidfile(name))  # stale: PID recycled
            except Exception:
                pass
            return None
    return pid


def _port_busy(port):
    try:
        s = socket.create_connection((HOST, port), timeout=1.0)
        s.close()
        return True
    except Exception:
        return False


def _reader(name, proc):
    try:
        for line in proc.stdout:
            with _lock:
                _state[name]["logs"].append(line.rstrip("\n"))
    except Exception:
        pass
    finally:
        with _lock:
            _state[name]["logs"].append("[exited code=%s]" % proc.poll())


def svc_status(name):
    st = _state[name]
    proc = st["proc"]
    running = proc is not None and proc.poll() is None
    orphan = None if running else _pidfile_pid(name)
    return {"name": name, "label": SERVICES[name]["label"], "running": running,
            "pid": proc.pid if running else None,
            "uptime_s": int(time.time() - st["started"]) if running else 0,
            "exit": None if running else st["exit"], "orphan_pid": orphan}


def svc_start(name):
    if name not in SERVICES:
        return False, "unknown service", None
    with _lock:
        st = _state[name]
        if st["proc"] is not None and st["proc"].poll() is None:
            return False, "already running", svc_status(name)
        other = _pidfile_pid(name)
        if other is not None:
            return False, "already running (pid %d)" % other, svc_status(name)
        spec = SERVICES[name]
        if spec.get("port") and _port_busy(spec["port"]):
            return False, "port %d busy (external process?)" % spec["port"], \
                svc_status(name)
        if not os.path.exists(spec["argv"][0]):
            return False, "python not found: %s" % spec["argv"][0], \
                svc_status(name)
        if not os.path.exists(os.path.join(spec["cwd"], spec["argv"][1])):
            return False, "script missing: %s" % spec["argv"][1], \
                svc_status(name)
        try:
            proc = subprocess.Popen(
                spec["argv"], cwd=spec["cwd"], stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                errors="replace", bufsize=1)
        except Exception as error:
            return False, "launch failed: %s" % error, svc_status(name)
        st["proc"], st["started"], st["exit"] = proc, time.time(), None
        st["logs"].append("[started pid=%d]" % proc.pid)
        try:
            with open(_pidfile(name), "w") as f:
                f.write("%d %.3f" % (proc.pid, st["started"]))
        except Exception:
            pass
        threading.Thread(target=_reader, args=(name, proc),
                         daemon=True).start()
        log("started", name, "pid=%d" % proc.pid)
        return True, "started", svc_status(name)


def _stop_locked(name):
    st = _state[name]
    proc = st["proc"]
    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
        except Exception:
            pass
        for _ in range(50):
            if proc.poll() is not None:
                break
            time.sleep(0.1)
        if proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass
        st["exit"] = proc.poll()
        st["proc"] = None
        st["logs"].append("[stopped by dashboard]")
        try:
            os.remove(_pidfile(name))
        except Exception:
            pass
        log("stopped", name)
        return True, "stopped"
    st["proc"] = None
    orphan = _pidfile_pid(name)
    if orphan is not None:
        return False, "orphaned (pid %d): stop it in its own window" % orphan
    return True, "already stopped"


def svc_stop(name):
    if name not in SERVICES:
        return False, "unknown service", None
    with _lock:
        ok, msg = _stop_locked(name)
        return ok, msg, svc_status(name)


def svc_restart(name):
    if name not in SERVICES:
        return False, "unknown service", None
    with _lock:
        ok, msg = _stop_locked(name)
        if not ok:
            return False, msg, svc_status(name)
    return svc_start(name)


def stop_all():
    for name in SERVICES:
        try:
            with _lock:
                _stop_locked(name)
        except Exception:
            pass


def start_all():
    """Staggered background start of every service (Start All button)."""
    threading.Thread(target=_autostart, daemon=True).start()


def ask_agent(text, timeout=60.0):
    """Ask the Meta agent over MQTT, wait for the matching answer id."""
    import uuid
    req_id = uuid.uuid4().hex[:8]
    slot = {"event": threading.Event(), "text": "", "status": "timeout"}
    with _lock:
        _ask_pending[req_id] = slot
    try:
        _mqtt["client"].publish("moonman/brain/ask", json.dumps(
            {"id": req_id, "text": text, "device": "dashboard"}))
    except Exception:
        with _lock:
            _ask_pending.pop(req_id, None)
        return "", "publish-failed"
    slot["event"].wait(timeout)
    with _lock:
        _ask_pending.pop(req_id, None)
    return slot["text"], slot["status"]


def _speak_chunks(text):
    """Split a reply into eye-sized (~230 char) sentence chunks."""
    import re
    parts = re.split(r"(?<=[.!?])\s+", " ".join(text.split()))
    chunks, cur = [], ""
    for part in parts:
        if len(cur) + 1 + len(part) <= 230:
            cur = (cur + " " + part).strip()
        else:
            if cur:
                chunks.append(cur)
            while len(part) > 230:
                chunks.append(part[:230])
                part = part[230:]
            cur = part
    if cur:
        chunks.append(cur)
    return chunks


def _speak_forward(answer):
    """Fire-and-forget: pace answer chunks to the eye speaker."""
    cli = _mqtt.get("client")
    if cli is None:
        return
    for piece in _speak_chunks(answer):
        try:
            cli.publish("moonman/eye/right/say", piece)
        except Exception:
            return
        time.sleep(len(piece) / 15.0 + 2.5)


def _mic_state():
    """Listening / Processing / Disconnected / Error from real signals."""
    now = time.time()
    voice_up = False
    with _lock:
        st = _state["voice"]
        if st["proc"] is not None and st["proc"].poll() is None:
            voice_up = True
    if not voice_up and _port_busy(8099):
        voice_up = True  # managed elsewhere (own window)
    ev = _mqtt.get("mic") or {}
    age = round(now - _mqtt["mic_ts"], 1) if _mqtt["mic_ts"] else None
    ear = (_mqtt.get("ear") or {}).get("state")
    if not voice_up:
        return {"state": "Disconnected", "detail": "voice server down",
                "age": age, "event": ev, "ear": ear}
    if ev.get("event") == "error" and age is not None and age < 120:
        return {"state": "Error", "detail": ev.get("where", "?"),
                "age": age, "event": ev, "ear": ear}
    if ev.get("event") in ("listen", "heard") and age is not None and age < 60:
        return {"state": "Processing",
                "detail": ev.get("text") or "clip", "age": age, "event": ev,
                "ear": ear}
    src = "Pi ear" if ear == "online" else "Eye mic"
    return {"state": "Listening", "detail": src, "age": age, "event": ev,
            "ear": ear}


def _autostart():
    time.sleep(2.0)  # let the server + mqtt settle first
    for name in ("brain", "voice", "track", "view"):
        ok, msg, _ = svc_start(name)
        log("autostart", name, msg)
        time.sleep(3.0)


def mqtt_thread():
    try:
        import paho.mqtt.client as mqtt_mod
    except ImportError:
        log("paho-mqtt missing: live state disabled")
        return
    try:
        client = mqtt_mod.Client(mqtt_mod.CallbackAPIVersion.VERSION2)
    except Exception:
        client = mqtt_mod.Client()

    def on_message(_c, _u, m):
        try:
            raw = m.payload.decode("utf-8", "replace")
        except Exception:
            return
        try:
            obj = json.loads(raw)
        except Exception:
            obj = {"_raw": raw}
        if m.topic == "moonman/voice/activity":
            _mqtt["mic"], _mqtt["mic_ts"] = obj, time.time()
            return
        if m.topic == "moonman/status/ear":
            _mqtt["ear"], _mqtt["ear_ts"] = {"state": raw}, time.time()
            return
        if m.topic == "moonman/track/status":
            _mqtt["track"], _mqtt["track_ts"] = obj, time.time()
        elif m.topic == "moonman/track/faces":
            _mqtt["faces"], _mqtt["faces_ts"] = obj, time.time()
        elif m.topic == "moonman/brain/answer":
            with _lock:
                slot = _ask_pending.get(str(obj.get("id", "")))
            if slot is not None and obj.get("text"):
                slot["text"] = str(obj.get("text", ""))
                slot["status"] = str(obj.get("status", "ok"))
                slot["event"].set()

    def on_connect(c, _u, _f, rc, _p=None):
        if rc == 0:
            c.subscribe([("moonman/track/status", 0),
                         ("moonman/track/faces", 0),
                         ("moonman/brain/answer", 0),
                         ("moonman/voice/activity", 0),
                         ("moonman/status/ear", 0)])
            _mqtt["ok"] = True
            log("mqtt up")
        else:
            log("mqtt connect failed rc=", rc)

    client.on_connect = on_connect  # _p=None default fits paho v1 and v2
    client.on_message = on_message
    _mqtt["client"] = client  # ask + speak-forward borrow it for publishes
    while True:
        try:
            client.connect(BROKER, MQTT_PORT, keepalive=30)
            client.loop_forever()
        except Exception as error:
            _mqtt["ok"] = False
            log("mqtt down (%s), retrying..." % error)
            time.sleep(3.0)


PAGE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Moon Man Mission Control | Operation Moonworks</title>
<link rel="icon" type="image/png" href="/favicon.ico">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@500;600;700&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#07090d; --panel:#10141d; --panel-2:#151b26;
  --line:rgba(255,255,255,.12); --text:#f4f7fb; --muted:#9ea9b8;
  --blue:#1ca7ff; --cyan:#5ee7ff; --orange:#ff7a18;
  --ok:#64f4b0; --err:#ff8b8b; --max:1180px;
}
*{box-sizing:border-box}
body{
  margin:0; color:var(--text);
  background:
    radial-gradient(circle at 80% 5%, rgba(28,167,255,.13), transparent 30%),
    radial-gradient(circle at 10% 25%, rgba(255,122,24,.08), transparent 22%),
    var(--bg);
  font-family:Inter,system-ui,sans-serif; line-height:1.6;
}
.noise{position:fixed;inset:0;pointer-events:none;opacity:.035;z-index:20;
  background-image:url("data:image/svg+xml,%3Csvg viewBox='0 0 180 180' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.8' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='.5'/%3E%3C/svg%3E");}
.site-header{position:sticky;top:0;z-index:15;display:flex;align-items:center;justify-content:space-between;
  gap:16px;padding:14px max(24px,calc((100vw - var(--max))/2));
  background:rgba(7,9,13,.78);backdrop-filter:blur(18px);border-bottom:1px solid var(--line)}
.brand{display:flex;align-items:center;gap:12px}
.header-logo{width:58px;height:58px;object-fit:contain;flex:0 0 auto;
  filter:drop-shadow(0 0 14px rgba(28,167,255,.3))}
.brand strong{display:block;font-family:Orbitron,sans-serif;font-size:14px;letter-spacing:.08em}
.brand small{display:block;color:var(--muted);font-size:11px;letter-spacing:.08em;text-transform:uppercase}
.head-right{display:flex;align-items:center;gap:14px;color:var(--muted);font-size:13px}
main{max-width:var(--max);margin:0 auto;padding:44px 24px 30px}
.eyebrow{color:var(--cyan);font-size:12px;font-weight:700;letter-spacing:.22em;margin:0 0 8px}
h1{margin:0 0 6px;font-family:Orbitron,sans-serif;font-size:clamp(26px,3.4vw,40px);letter-spacing:-.025em;line-height:1.12}
.sub{color:var(--muted);font-size:14px;margin:0 0 28px}
.work-grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}
.span2{grid-column:1/-1}
.panel{padding:24px;border:1px solid var(--line);border-radius:16px;
  background:linear-gradient(180deg,rgba(255,255,255,.045),rgba(255,255,255,.018))}
.panel.featured{border-color:rgba(94,231,255,.45);box-shadow:0 0 45px rgba(28,167,255,.09)}
.panel h2{margin:0 0 12px;font-family:Orbitron,sans-serif;font-size:15px;letter-spacing:.12em}
.panel h2 .tag{margin-left:10px;vertical-align:2px}
.meta{color:var(--muted);font-size:13px}
.meta b,.meta strong{color:var(--text)}
.urgent{color:var(--err);font-weight:700}
.tag{display:inline-block;padding:5px 10px;border:1px solid var(--line);border-radius:999px;
  color:#c8d1dd;font-size:11px;letter-spacing:.06em}
.button{display:inline-flex;justify-content:center;align-items:center;min-height:48px;padding:0 22px;
  border-radius:8px;font-weight:700;border:1px solid transparent;cursor:pointer;font-family:inherit;font-size:14px}
.button-primary{color:#031019;background:linear-gradient(135deg,var(--cyan),var(--blue));
  box-shadow:0 10px 34px rgba(28,167,255,.24)}
.button-secondary{border-color:var(--line);background:rgba(255,255,255,.04);color:var(--text)}
.btn-sm{min-height:34px;padding:0 14px;font-size:13px;font-weight:600}
.button:focus-visible{outline:2px solid var(--cyan);outline-offset:3px}
input[type=text]{width:100%;color:#fff;background:#090d14;border:1px solid var(--line);
  border-radius:8px;padding:13px;font-family:inherit;font-size:14px}
input[type=text]:focus{outline:1px solid var(--cyan);border-color:var(--cyan)}
input[type=range]{width:100%;accent-color:var(--cyan)}
.talk-row{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-top:12px}
.talk-row input[type=text]{flex:1;min-width:220px}
.speak{display:flex;align-items:center;gap:7px;color:var(--muted);font-size:13px;white-space:nowrap}
#thinking{color:var(--cyan);font-size:13px;min-height:1.4em;margin:8px 0 0}
#hist{margin-top:6px}
#hist .chat{margin:0 0 12px;font-size:14px}
#hist .who{display:block;font-size:10px;font-weight:700;letter-spacing:.16em;color:var(--muted);margin-bottom:2px}
#hist .chat.a .who{color:var(--cyan)}
.svc-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.svc{padding:16px;border:1px solid var(--line);border-radius:12px;background:rgba(7,9,13,.55);min-width:0}
.svc h3{margin:0 0 6px;font-size:15px}
.svc .row{display:flex;gap:8px;margin-top:10px;flex-wrap:wrap}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:7px;vertical-align:1px}
.dot.on{background:var(--cyan);box-shadow:0 0 12px rgba(94,231,255,.8)}
.dot.ok{background:var(--ok);box-shadow:0 0 12px rgba(100,244,176,.7)}
.dot.warn{background:var(--orange);box-shadow:0 0 12px rgba(255,122,24,.7)}
.dot.off{background:#3a4356}
.dot.err{background:var(--err);box-shadow:0 0 12px rgba(255,139,139,.7)}
pre.log{background:#090d14;border:1px solid var(--line);border-radius:8px;max-height:130px;
  overflow:auto;font-family:Consolas,monospace;font-size:11px;line-height:1.5;padding:8px;color:#9fe8c0;margin:10px 0 0}
.bar{height:8px;background:var(--panel-2);border:1px solid var(--line);border-radius:999px;margin:4px 0 10px;overflow:hidden}
.bar>i{display:block;height:100%;background:linear-gradient(90deg,var(--blue),var(--cyan));border-radius:999px}
img.cam{width:100%;border:1px solid rgba(94,231,255,.3);border-radius:12px;background:#0a1119;display:block}
.tstat{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap}
footer{padding:26px max(24px,calc((100vw - var(--max))/2));border-top:1px solid var(--line);
  color:var(--muted);font-size:12px;display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}
footer a{color:var(--cyan)}
@media (max-width:900px){.work-grid,.svc-grid{grid-template-columns:1fr}.brand strong{font-size:11px}.header-logo{width:48px;height:48px}}
@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation-duration:.01ms!important;transition-duration:.01ms!important}}
</style></head>
<body>
<div class="noise"></div>
<header class="site-header">
  <div class="brand">
    <img class="header-logo" src="/assets/emblem.png" alt="" aria-hidden="true">
    <span><strong>OPERATION MOONWORKS</strong><small>Moon Man Mission Control</small></span>
  </div>
  <div class="head-right"><span id="clk"></span>
    <button class="button btn-sm" onclick="startAll()">Start All</button>
    <button class="button button-secondary btn-sm" onclick="stopAll()">Stop All Services</button>
  </div>
</header>
<main>
  <p class="eyebrow">AI ENGINEERING WORKSTATION</p>
  <h1>Mission Control</h1>
  <p class="sub">Localhost only &middot; manages this dashboard's own services</p>
  <div class="work-grid">
    <div class="panel featured span2"><h2>TALK TO MOONMAN</h2>
      <div class="talk-row">
        <input type="text" id="askbox" placeholder="Type to MoonMan, Enter to send">
        <label class="speak"><input type="checkbox" id="saychk" checked> speak reply on eye</label>
        <button class="button button-primary btn-sm" style="min-height:44px" onclick="ask()">Send</button>
        <button class="button button-secondary btn-sm" style="min-height:44px" id="askcancel" onclick="cancelAsk()" disabled>Cancel</button>
      </div>
      <div id="thinking"></div><div id="hist"></div>
    </div>
    <div class="panel span2"><h2>SERVICES</h2><div class="svc-grid" id="svcs"></div></div>
    <div class="panel"><h2>TRACKER</h2>
      <div class="meta" id="trk"></div>
      <div class="meta">PAN</div><div class="bar"><i id="panb"></i></div>
      <div class="meta">TILT</div><div class="bar"><i id="tiltb"></i></div>
      <div class="meta" id="fcs"></div>
    </div>
    <div class="panel"><h2>SERVOS <span class="tag">MANUAL</span></h2>
      <div class="meta">Pan + visor are rig-safe. Tilt range unverified: nudge only.</div>
      <div class="meta">Pan <b id="sv_pan_v">90</b></div>
      <input type="range" id="sv_pan" min="0" max="180" value="90">
      <div class="meta">Tilt <b id="sv_tilt_v">90</b> (provisional)</div>
      <div class="talk-row">
        <button class="button button-secondary btn-sm" onclick="servoNudge(-5)">-5</button>
        <button class="button button-secondary btn-sm" onclick="servoNudge(5)">+5</button>
        <button class="button button-secondary btn-sm" onclick="servoTilt(90)">Center</button>
      </div>
      <div class="meta">Visor <b id="sv_visor_v">35</b></div>
      <input type="range" id="sv_visor" min="35" max="103" value="35">
      <div class="talk-row">
        <button class="button button-secondary btn-sm" onclick="servoVisor(103)">Open</button>
        <button class="button button-secondary btn-sm" onclick="servoVisor(35)">Close</button>
      </div>
      <div class="meta" id="sv_msg"></div>
    </div>
    <div class="panel"><h2>HELMET CAM</h2>
      <img class="cam" src="__CAM__" onerror="this.outerHTML='<div class=meta>camera unreachable</div>'">
    </div>
    <div class="panel"><h2>MICROPHONE</h2>
      <div class="meta" id="mic"></div><div class="meta" id="micev"></div>
    </div>
    <div class="panel"><h2>AI COST <span class="tag">META API</span></h2>
      <div class="meta" id="cost"></div><div class="meta" id="costd"></div><div class="meta" id="costt"></div>
    </div>
    <div class="panel"><h2>ARCHIE PRINT <span class="tag">APPROVAL</span></h2>
      <div class="meta" id="archie_info">loading...</div>
      <div class="meta" id="archie_cd"></div>
      <div class="talk-row"><input type="text" id="archie_file" placeholder="plate_1.gcode">
      <button class="button button-primary btn-sm" style="min-height:44px" onclick="approveArchie()">Approve</button>
      <button class="button button-secondary btn-sm" style="min-height:44px" onclick="cancelArchie()">Cancel</button></div>
      <div class="meta" id="archie_msg"></div>
      <div class="meta" id="archie_hist"></div>
    </div>
  </div>
</main>
<footer><span>OPERATION MOONWORKS &middot; MOON MAN</span>
<span id="ver">__VER__ &middot; up since __STARTED__</span>
<span>pricing: <a href="https://dev.meta.ai/docs/pricing-rate-limits">dev.meta.ai/docs/pricing-rate-limits</a></span></footer>
<script>
const NAMES=['brain','voice','track','view'];
async function api(p){const r=await fetch(p,{method:'POST'});return r.json();}
let svcNames='';
const logCache={};
function setLog(el,txt){
 if(logCache[el.id]===txt)return;
 logCache[el.id]=txt;
 const pinned=el.scrollHeight-el.scrollTop-el.clientHeight<24;
 el.textContent=txt;
 if(pinned)el.scrollTop=el.scrollHeight;
}
async function refreshSvcs(){
 const s=await (await fetch('/api/services')).json();
 const names=s.map(v=>v.name).join(',');
 const c=document.getElementById('svcs');
 if(names!==svcNames){
  svcNames=names;c.innerHTML='';
  for(const v of s){
   const d=document.createElement('div');d.className='svc';
   d.innerHTML='<h3>'+v.label+'</h3><div class=meta><span class=\'dot off\' id=\'dot-'+v.name+'\'></span><span id=\'st-'+v.name+'\'></span></div>'
    +'<pre class=log id=\'log-'+v.name+'\'></pre>'
    +'<div class=row><button class=\'button button-secondary btn-sm\' onclick=\'ctl("start","'+v.name+'")\'>Start</button>'
    +'<button class=\'button button-secondary btn-sm\' onclick=\'ctl("stop","'+v.name+'")\'>Stop</button>'
    +'<button class=\'button button-secondary btn-sm\' onclick=\'ctl("restart","'+v.name+'")\'>Restart</button></div>';
   c.appendChild(d);
  }
 }
 for(const v of s){
  const failed=!v.running&&!v.orphan_pid&&v.exit!=null&&v.exit!==0;
  const cls=v.running?'on':(v.orphan_pid?'warn':(failed?'err':'off'));
  const st=v.running?('RUNNING pid='+v.pid+' up='+v.uptime_s+'s')
    :(v.orphan_pid?('ORPHAN pid='+v.orphan_pid):('STOPPED'+(v.exit!=null?' (exit '+v.exit+')':'')));
  const dot=document.getElementById('dot-'+v.name),stEl=document.getElementById('st-'+v.name);
  if(dot&&stEl){dot.className='dot '+cls;if(stEl.textContent!==st)stEl.textContent=st;}
  const l=await (await fetch('/api/logs?name='+v.name)).json();
  const logEl=document.getElementById('log-'+v.name);
  if(logEl)setLog(logEl,l.lines.join('\n'));
 }
}
let archieDeadline=0;
function tickArchie(){
 const el=document.getElementById('archie_cd');
 if(!el)return;
 if(!archieDeadline){el.textContent='';el.className='meta';return;}
 const left=Math.max(0,Math.round(archieDeadline-Date.now()/1000));
 const mm=Math.floor(left/60),ss=('0'+(left%60)).slice(-2);
 el.textContent='approval expires in '+mm+':'+ss;
 el.className='meta'+(left<60?' urgent':'');
 if(!left)archieDeadline=0;
}
let tiltCmd=90;
async function servoPost(axis,value){
 const m=document.getElementById('sv_msg');
 try{
  const r=await fetch('/api/servo',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({axis:axis,value:value})});
  const j=await r.json();
  m.textContent=j.ok?('sent '+axis+' '+j.value):('error: '+(j.error||'failed'));
 }catch(e){m.textContent='(request failed)';}
}
function servoPan(v){v=+v;document.getElementById('sv_pan_v').textContent=v;servoPost('pan',v);}
function servoVisor(v){v=+v;document.getElementById('sv_visor').value=v;document.getElementById('sv_visor_v').textContent=v;servoPost('visor',v);}
function servoTilt(v){tiltCmd=Math.max(45,Math.min(135,v));document.getElementById('sv_tilt_v').textContent=tiltCmd;servoPost('tilt',tiltCmd);}
function servoNudge(d){servoTilt(tiltCmd+d);}
async function refreshArchie(){
 try{
  const a=await (await fetch('/api/archie/status')).json();
  const el=document.getElementById('archie_info'),hi=document.getElementById('archie_hist');
  if(a.staged){el.textContent='STAGED '+a.staged.filename+' job '+a.staged.job_id+' ['+a.staged.status+']';}
  else{el.textContent=a.text||'No Archie file staged.';}
  if(a.last){hi.textContent='last job: '+a.last.filename+' job '+a.last.job_id+' ['+a.last.status+']';}
  else{hi.textContent='';}
  archieDeadline=(a.staged&&a.expires_at)?a.expires_at:0;
  tickArchie();
 }catch(e){document.getElementById('archie_info').textContent='approval state unavailable';}
}
async function approveArchie(){
 const f=document.getElementById('archie_file').value.trim();
 const m=document.getElementById('archie_msg');
 if(!f){m.textContent='Type the staged filename first.';return;}
 m.textContent='approving...';
 try{
  const r=await fetch('/api/archie/approve',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({filename:f})});
  const j=await r.json();
  m.textContent=j.message||j.error||'(no response)';
 }catch(e){m.textContent='(request failed)';}
 refreshArchie();
}
async function cancelArchie(){
 const m=document.getElementById('archie_msg');
 m.textContent='cancelling...';
 try{
  const r=await fetch('/api/archie/cancel',{method:'POST'});
  const j=await r.json();
  m.textContent=j.message||j.error||'(no response)';
 }catch(e){m.textContent='(request failed)';}
 refreshArchie();
}
async function refresh(){
 const t=await (await fetch('/api/state')).json();
 const trk=document.getElementById('trk'),fcs=document.getElementById('fcs');
 if(t.track&&t.track_age<3){
  trk.textContent='mode='+t.track.mode+' pan='+t.track.pan+' tilt='+t.track.tilt;
  document.getElementById('panb').style.width=(t.track.pan/180*100)+'%';
  const tl=(t.track.tilt-45)/90*100;
  document.getElementById('tiltb').style.width=Math.min(100,Math.max(0,tl))+'%';
 }else{trk.textContent='tracker offline';}
 const mc=document.getElementById('mic'),me=document.getElementById('micev');
 const dot=t.mic.state==='Listening'?'on':(t.mic.state==='Processing'?'warn':'off');
 mc.innerHTML='<span class=\'dot '+dot+'\'></span>MIC: '+t.mic.state+' ('+t.mic.detail+')';
 const ev=t.mic.event||{};
 me.textContent='last: '+(ev.event||'none')+(t.mic.age!=null?' '+t.mic.age+'s ago':'')
  +(ev.text?' heard='+ev.text:'')+(ev.src?' src='+ev.src:'')+(ev.kind?' reply='+ev.kind:'')
  +(ev.status?' '+ev.status:'')+' ear='+(t.mic.ear||'never seen');
 if(t.faces&&t.faces_age<3){
  fcs.textContent='faces='+t.faces.count+' conf='+t.faces.conf+' fps='+t.faces.fps;
 }else{fcs.textContent='face data: none (preview publishes while running)';}
 const c8=await (await fetch('/api/costs')).json();
 const ce=document.getElementById('cost'),cd=document.getElementById('costd'),ct=document.getElementById('costt');
 if(c8.error){ce.textContent='costs unavailable: '+c8.error;cd.textContent='';ct.textContent='';}
 else{
  const L=c8.last||{};
  let w='';
  if(c8.budget_monthly_usd>0&&c8.month_usd>=c8.budget_monthly_usd*0.8){w=' BUDGET '+Math.round(c8.month_usd/c8.budget_monthly_usd*100)+'%';}
  ce.textContent='last: '+(L.cost_usd!=null?('$'+L.cost_usd.toFixed(4)+' in='+L.input_tokens+' cached='+L.cached_tokens+' out='+L.output_tokens+(L.reasoning_tokens?' (think='+L.reasoning_tokens+')':'')+(L.searches?' searches='+L.searches:'')+(L.estimated?' EST':'')):'none yet')+' ['+c8.tier+']';
  cd.textContent='today: $'+c8.today_usd.toFixed(4)+' ('+c8.today_calls+' calls, '+c8.today_measured+' measured)'+w;
  ct.textContent='month: $'+c8.month_usd.toFixed(2)+' | est full month: $'+c8.est_month_usd.toFixed(2)+' (budget $'+(c8.budget_monthly_usd||'none')+')';
 }
 document.getElementById('clk').textContent=new Date().toLocaleTimeString();
}
async function ctl(a,n){await api('/api/'+a+'?name='+n);refreshSvcs();refresh();}
async function startAll(){await api('/api/startall');refreshSvcs();refresh();}
async function stopAll(){await api('/api/stopall');refreshSvcs();refresh();}
const esc=s=>s.replace(/&/g,'&amp;').replace(/</g,'&lt;');
const fmt=s=>esc(s).replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>').replace(/\n/g,'<br>');
const hist=[];
let askCtl=null,askTimer=null;
function cancelAsk(){if(askCtl)askCtl.abort();}
async function ask(){
 const box=document.getElementById('askbox'),t=box.value.trim();
 if(!t||askCtl)return;box.value='';
 const think=document.getElementById('thinking'),cx=document.getElementById('askcancel');
 askCtl=new AbortController();cx.disabled=false;
 const t0=Date.now();
 think.textContent='thinking... 0s';
 askTimer=setInterval(()=>{think.textContent='thinking... '+Math.round((Date.now()-t0)/1000)+'s';},1000);
 const to=setTimeout(()=>askCtl.abort(),65000);
 try{
  const r=await fetch('/api/ask',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({text:t,speak:document.getElementById('saychk').checked}),signal:askCtl.signal});
  const j=await r.json();
  hist.unshift({q:t,a:j.answer||('(no answer: '+(j.status||j.error)+')')});
 }catch(e){hist.unshift({q:t,a:(e&&e.name==='AbortError'?'(cancelled)':'(request failed)')});}
 clearTimeout(to);clearInterval(askTimer);askCtl=null;askTimer=null;cx.disabled=true;
 think.textContent='';
 const h=document.getElementById('hist');h.innerHTML='';
 for(const e of hist.slice(0,10)){
  h.innerHTML+='<div class=chat><span class=who>YOU</span>'+fmt(e.q)+'</div><div class="chat a"><span class=who>MOONMAN</span>'+fmt(e.a)+'</div>';
 }
}
refreshSvcs();refresh();refreshArchie();setInterval(refresh,2000);setInterval(refreshSvcs,6000);setInterval(refreshArchie,6000);setInterval(tickArchie,1000);
document.getElementById('askbox').addEventListener('keydown',e=>{if(e.key==='Enter')ask();});
document.getElementById('sv_pan').addEventListener('change',e=>servoPan(e.target.value));
document.getElementById('sv_visor').addEventListener('change',e=>servoVisor(e.target.value));
</script></body></html>

"""


class Handler(BaseHTTPRequestHandler):
    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _asset(self, name, ctype):
        try:
            base = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "assets")
            path = os.path.join(base, name)
            if os.path.dirname(os.path.abspath(path)) != base:
                return self._json({"error": "not found"}, 404)
            with open(path, "rb") as handle:
                body = handle.read()
        except OSError:
            return self._json({"error": "not found"}, 404)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "max-age=3600")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(url.query)
        if url.path == "/":
            page = PAGE.replace("__CAM__", CAMERA_URL).replace(
                "__VER__", _git_hash()).replace(
                "__STARTED__", STARTED_AT).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)
        elif url.path == "/api/services":
            with _lock:
                self._json([svc_status(n) for n in SERVICES])
        elif url.path == "/api/logs":
            name = qs.get("name", [""])[0]
            if name not in SERVICES:
                return self._json({"error": "unknown service"}, 404)
            with _lock:
                self._json({"name": name,
                            "lines": list(_state[name]["logs"])[-120:]})
        elif url.path == "/assets/emblem.png":
            return self._asset("emblem.png", "image/png")
        elif url.path == "/favicon.ico":
            return self._asset("favicon.png", "image/png")
        elif url.path == "/api/archie/status":
            try:
                from archie_approval import MAX_AGE as _arch_max_age
                from archie_approval import current as _arch_current
                from archie_approval import describe as _arch_desc

                record, expires = _arch_current()
                live = (isinstance(record, dict)
                        and record.get("status") in ("pending", "approved"))
                try:
                    expires_at = (float(record["created"]) + _arch_max_age
                                  if live else None)
                except Exception:
                    expires_at = None
                self._json({"record": record, "expires_in": expires,
                            "expires_at": expires_at,
                            "staged": record if live else None,
                            "last": record if (record and not live) else None,
                            "text": _arch_desc()})
            except Exception as error:
                self._json({"record": None, "expires_in": None,
                            "expires_at": None, "staged": None, "last": None,
                            "text": "approval state unavailable: %s"
                            % error})
        elif url.path == "/api/costs":
            try:
                from moonman_usage import summary as _usage_summary
                self._json(_usage_summary())
            except Exception as error:
                self._json({"error": "costs unavailable: %s" % error})
        elif url.path == "/api/state":
            now = time.time()
            self._json({"track": _mqtt["track"],
                        "track_age": round(now - _mqtt["track_ts"], 1)
                        if _mqtt["track_ts"] else None,
                        "faces": _mqtt["faces"],
                        "faces_age": round(now - _mqtt["faces_ts"], 1)
                        if _mqtt["faces_ts"] else None,
                        "mqtt": "up" if _mqtt["ok"] else "down",
                        "mic": _mic_state()})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        url = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(url.query)
        name = qs.get("name", [""])[0]
        if url.path == "/api/start":
            ok, msg, svc = svc_start(name)
            self._json({"ok": ok, "message": msg, "service": svc})
        elif url.path == "/api/stop":
            ok, msg, svc = svc_stop(name)
            self._json({"ok": ok, "message": msg, "service": svc})
        elif url.path == "/api/restart":
            ok, msg, svc = svc_restart(name)
            self._json({"ok": ok, "message": msg, "service": svc})
        elif url.path == "/api/stopall":
            stop_all()
            self._json({"ok": True})
        elif url.path == "/api/startall":
            start_all()
            self._json({"ok": True})
        elif url.path == "/api/archie/approve":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                body = {}
            filename = str(body.get("filename", "")).strip()
            try:
                from archie_approval import ApprovalError as _ArchErr
                from archie_approval import approve as _arch_approve

                message = _arch_approve(filename)
                self._json({"ok": True, "message": message})
            except _ArchErr as error:
                self._json({"ok": False,
                            "message": "Not approved: %s" % error})
            except Exception as error:
                self._json({"ok": False,
                            "message": "approve failed: %s" % error})
        elif url.path == "/api/archie/cancel":
            try:
                from archie_approval import cancel as _arch_cancel

                self._json({"ok": True, "message": _arch_cancel()})
            except Exception as error:
                self._json({"ok": False,
                            "message": "cancel failed: %s" % error})
        elif url.path == "/api/servo":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                body = {}
            axis = body.get("axis")
            try:
                value = int(body.get("value"))
            except Exception:
                value = None
            spec = {"pan": ("moonman/helmet/angle", 0, 180),
                    "tilt": ("moonman/helmet/tilt", 45, 135),
                    "visor": ("moonman/visor/angle", 35, 103)}
            if axis not in spec or value is None:
                self._json({"ok": False,
                            "error": "need axis pan|tilt|visor + int value"})
            elif _mqtt.get("client") is None or not _mqtt["ok"]:
                self._json({"ok": False, "error": "mqtt down"})
            else:
                topic, lo, hi = spec[axis]
                value = max(lo, min(hi, value))
                try:
                    _mqtt["client"].publish(topic, str(value))
                    self._json({"ok": True, "axis": axis, "value": value})
                except Exception as error:
                    self._json({"ok": False,
                                "error": "publish failed: %s" % error})
        elif url.path == "/api/ask":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                body = {}
            text = str(body.get("text", "")).strip()
            want_say = bool(body.get("speak", True))
            if not text:
                self._json({"ok": False, "error": "empty"})
            elif _mqtt.get("client") is None or not _mqtt["ok"]:
                self._json({"ok": False, "error": "mqtt down"})
            else:
                answer, status = ask_agent(text)
                if answer and want_say:
                    threading.Thread(target=_speak_forward, args=(answer,),
                                     daemon=True).start()
                self._json({"ok": bool(answer), "answer": answer,
                            "status": status})
        else:
            self._json({"error": "not found"}, 404)

    def log_message(self, *a):  # quieter than default
        log("%s %s" % (self.address_string(), a[0] % a[1:] if len(a) > 1 else a))


def main():
    os.makedirs(PIDDIR, exist_ok=True)
    threading.Thread(target=mqtt_thread, daemon=True).start()
    if os.environ.get("MOONMAN_CONTROL_AUTOSTART", "0") == "1":
        threading.Thread(target=_autostart, daemon=True).start()
    atexit.register(stop_all)
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    log("Mission Control at http://%s:%d/  (Ctrl+C stops services first)"
        % (HOST, PORT))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_all()
        log("shutdown complete")


if __name__ == "__main__":
    main()
