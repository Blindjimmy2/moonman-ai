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


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _pidfile_pid(name):
    try:
        with open(_pidfile(name)) as f:
            pid = int(f.read().strip())
    except Exception:
        return None
    if _pid_alive(pid):
        return pid
    try:
        os.remove(_pidfile(name))  # stale: process is gone
    except Exception:
        pass
    return None


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
                f.write(str(proc.pid))
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
<html><head><meta charset="utf-8"><title>MoonMan Mission Control</title>
<style>
body{background:#070b16;color:#d7e3ff;font-family:Consolas,monospace;margin:0}
.wrap{max-width:1100px;margin:0 auto;padding:18px}
h1{font-size:20px;letter-spacing:2px;color:#7fd4ff;margin:0}
.sub{color:#5b6b8c;font-size:12px;margin:2px 0 14px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.card{background:#0d1428;border:1px solid #1d2a4d;border-radius:8px;padding:12px}
.card h2{font-size:14px;margin:0 0 6px;color:#a9c6ff}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px}
.on{background:#3dff8e}.off{background:#ff5470}.warn{background:#ffb347}
.meta{font-size:12px;color:#8fa3cc;min-height:18px}
pre{background:#05070f;border:1px solid #182449;border-radius:6px;height:130px;
overflow:auto;font-size:11px;padding:6px;color:#9fe8c0;margin:8px 0}
button{background:#16305c;color:#d7e3ff;border:1px solid #2c4d85;border-radius:5px;
padding:4px 12px;margin-right:6px;cursor:pointer;font-family:inherit}
button:hover{background:#1e4179}
input[type=text]{width:65%;background:#05070f;color:#d7e3ff;border:1px solid #2c4d85;
border-radius:5px;padding:5px 8px;font-family:inherit}
.panel{background:#0d1428;border:1px solid #1d2a4d;border-radius:8px;
padding:12px;margin-top:12px}
.bar{height:10px;background:#182449;border-radius:5px;margin:4px 0 8px}
.bar>i{display:block;height:100%;background:#7fd4ff;border-radius:5px}
img.cam{width:100%;max-width:640px;border:1px solid #1d2a4d;border-radius:6px}
.foot{color:#5b6b8c;font-size:11px;margin-top:14px}
</style></head><body><div class="wrap">
<h1>OPERATION MOONWORKS &mdash; MISSION CONTROL</h1>
<div class="sub">localhost only &middot; manages this dashboard's own services</div>
<div class="grid" id="svcs"></div>
<div class="panel"><h2 style="font-size:14px;color:#a9c6ff;margin:0 0 6px">TRACKER</h2>
<div class="meta" id="trk"></div>
<div class="meta">PAN</div><div class="bar"><i id="panb"></i></div>
<div class="meta">TILT</div><div class="bar"><i id="tiltb"></i></div>
<div class="meta" id="fcs"></div></div>
<div class="panel"><h2 style="font-size:14px;color:#a9c6ff;margin:0 0 6px">MICROPHONE</h2>
<div class="meta" id="mic"></div><div class="meta" id="micev"></div></div>
<div class="panel"><h2 style="font-size:14px;color:#a9c6ff;margin:0 0 6px">HELMET CAM</h2>
<img class="cam" src="__CAM__" onerror="this.outerHTML='<div class=meta>camera unreachable</div>'"></div>
<div class="panel"><h2 style="font-size:14px;color:#a9c6ff;margin:0 0 6px">TALK TO MOONMAN</h2>
<div><input type="text" id="askbox" placeholder="Type to MoonMan, Enter to send">
<label class="meta"><input type="checkbox" id="saychk" checked> speak reply on eye</label>
<button onclick="ask()">Send</button></div>
<div class="meta" id="thinking"></div><div id="hist"></div></div>
<div class="foot"><button onclick="stopAll()">Stop All Services</button>
<span id="clk"></span></div></div>
<script>
const NAMES=["brain","voice","track","view"];
async function api(p){const r=await fetch(p,{method:"POST"});return r.json();}
async function refresh(){
 const s=await (await fetch("/api/services")).json();
 const c=document.getElementById("svcs");c.innerHTML="";
 for(const v of s){
  const d=document.createElement("div");d.className="card";
  const cls=v.running?"on":(v.orphan_pid?"warn":"off");
  const st=v.running?("RUNNING pid="+v.pid+" up="+v.uptime_s+"s")
    :(v.orphan_pid?("ORPHAN pid="+v.orphan_pid):"STOPPED");
  d.innerHTML="<h2>"+v.label+"</h2><div class=meta><span class='dot "+cls+"'></span>"+st+"</div>"
   +"<pre id='log-"+v.name+"'></pre>"
   +"<button onclick=\"ctl('start','"+v.name+"')\">Start</button>"
   +"<button onclick=\"ctl('stop','"+v.name+"')\">Stop</button>"
   +"<button onclick=\"ctl('restart','"+v.name+"')\">Restart</button>";
  c.appendChild(d);
  const l=await (await fetch("/api/logs?name="+v.name)).json();
  document.getElementById("log-"+v.name).textContent=l.lines.join("\n");
 }
 const t=await (await fetch("/api/state")).json();
 const trk=document.getElementById("trk"),fcs=document.getElementById("fcs");
 if(t.track&&t.track_age<3){
  trk.textContent="mode="+t.track.mode+" pan="+t.track.pan+" tilt="+t.track.tilt;
  document.getElementById("panb").style.width=(t.track.pan/180*100)+"%";
  const tl=(t.track.tilt-45)/90*100;
  document.getElementById("tiltb").style.width=Math.min(100,Math.max(0,tl))+"%";
 }else{trk.textContent="tracker offline";}
 const mc=document.getElementById("mic"),me=document.getElementById("micev");
 const dot=t.mic.state==="Listening"?"on":(t.mic.state==="Processing"?"warn":"off");
 mc.innerHTML="<span class='dot "+dot+"'></span>MIC: "+t.mic.state+" ("+t.mic.detail+")";
 const ev=t.mic.event||{};
 me.textContent="last: "+(ev.event||"none")+(t.mic.age!=null?" "+t.mic.age+"s ago":"")
  +(ev.text?" heard="+ev.text:"")+(ev.src?" src="+ev.src:"")+(ev.kind?" reply="+ev.kind:"")
  +(ev.status?" "+ev.status:"")+" ear="+(t.mic.ear||"never seen");
 if(t.faces&&t.faces_age<3){
  fcs.textContent="faces="+t.faces.count+" conf="+t.faces.conf+" fps="+t.faces.fps;
 }else{fcs.textContent="face data: none (preview publishes while running)";}
 document.getElementById("clk").textContent=new Date().toLocaleTimeString();
}
async function ctl(a,n){await api("/api/"+a+"?name="+n);refresh();}
async function stopAll(){await api("/api/stopall");refresh();}
const esc=s=>s.replace(/&/g,"&amp;").replace(/</g,"&lt;");
const hist=[];
async function ask(){
 const box=document.getElementById("askbox"),t=box.value.trim();
 if(!t)return;box.value="";
 document.getElementById("thinking").textContent="thinking...";
 try{
  const r=await fetch("/api/ask",{method:"POST",headers:{"Content-Type":"application/json"},
   body:JSON.stringify({text:t,speak:document.getElementById("saychk").checked})});
  const j=await r.json();
  hist.unshift({q:t,a:j.answer||("(no answer: "+(j.status||j.error)+")")});
 }catch(e){hist.unshift({q:t,a:"(request failed)"});}
 document.getElementById("thinking").textContent="";
 const h=document.getElementById("hist");h.innerHTML="";
 for(const e of hist.slice(0,10)){
  h.innerHTML+="<div class=meta>YOU: "+esc(e.q)+"</div><div class=meta>MOONMAN: "+esc(e.a)+"</div><br>";
 }
}
refresh();setInterval(refresh,2000);
document.getElementById("askbox").addEventListener("keydown",e=>{if(e.key==="Enter")ask();});
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

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(url.query)
        if url.path == "/":
            page = PAGE.replace("__CAM__", CAMERA_URL).encode()
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
