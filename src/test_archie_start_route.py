"""Offline test for POST /api/archie/start. No printer, no network.

Stubs archie_approval + archie_start_print (mirroring their real return
contracts), loads the real dashboard handler, and POSTs over localhost.
Run:
  python test_archie_start_route.py
"""

import http.server
import importlib.util
import json
import sys
import threading
import types
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent

# --- stub archie_approval (same shapes as the real module) ---
approval = types.ModuleType("archie_approval")


class ApprovalError(Exception):
    pass


approval.ApprovalError = ApprovalError
approval.calls = []
approval.mode = {"idle": True, "record": True, "consumable": True}


def _current():
    if not approval.mode["record"]:
        return None, None
    return {"filename": "plate_1.gcode", "size": 288333,
            "status": "approved"}, 299


def _consume(name):
    approval.calls.append(("consume", name))
    if not approval.mode["consumable"]:
        raise ApprovalError("Approval expired (>5 min). Re-approve.")
    if name != "plate_1.gcode":
        raise ApprovalError("Approved file is plate_1.gcode, not %s." % name)
    return {"filename": "plate_1.gcode", "size": 288333,
            "status": "consumed"}


def _idle():
    if approval.mode["idle"]:
        return True, "Archie idle.", {}
    return False, "Archie busy (printing).", {}


approval.current = _current
approval.consume = _consume
approval.printer_idle = _idle
approval.remote_file_ok = lambda name, size: True  # noqa: E731
approval.verify_local = lambda record: (True, "hash ok")  # noqa: E731
approval.confirm_start = lambda name: {"confirmed": True}  # noqa: E731

# --- stub archie_start_print (records calls, sends nothing) ---
starter = types.ModuleType("archie_start_print")
starter.calls = []
starter.archie_start_print = lambda name, approved=False: (
    starter.calls.append((name, approved)) or
    {"status": "command_sent_unverified", "filename": name})

sys.modules["archie_approval"] = approval
sys.modules["archie_start_print"] = starter

spec = importlib.util.spec_from_file_location(
    "control_start_test", str(HERE / "moonman_control.py"))
ctl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ctl)

srv = http.server.HTTPServer(("127.0.0.1", 0), ctl.Handler)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()


def post_start():
    req = urllib.request.Request(
        "http://127.0.0.1:%d/api/archie/start" % port,
        data=b"{}", method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


try:
    # happy path: guarded sequence runs, start fires once, approved
    body = post_start()
    assert body["ok"] is True, body
    assert "plate_1.gcode" in body["message"], body
    assert starter.calls == [("plate_1.gcode", True)], starter.calls
    print("PASS start happy path:", body["message"])

    # busy printer: refused BEFORE consume/start (no hardware call)
    starter.calls.clear()
    approval.calls.clear()
    approval.mode["idle"] = False
    body = post_start()
    assert body["ok"] is False and "not ready" in body["message"], body
    assert starter.calls == [] and approval.calls == [], (
        starter.calls, approval.calls)
    approval.mode["idle"] = True
    print("PASS busy printer refused cleanly:", body["message"])

    # nothing staged: refused, nothing fired
    approval.mode["record"] = False
    body = post_start()
    assert body["ok"] is False and "No file is staged" in body["message"], \
        body
    assert starter.calls == [], starter.calls
    approval.mode["record"] = True
    print("PASS unstaged refused cleanly:", body["message"])

    # expired approval: consume error surfaces, start never fires
    approval.mode["consumable"] = False
    body = post_start()
    assert body["ok"] is False and "expired" in body["message"], body
    assert starter.calls == [], starter.calls
    approval.mode["consumable"] = True
    print("PASS expired approval refused cleanly:", body["message"])
finally:
    srv.shutdown()

print("ALL ARCHIE START ROUTE TESTS PASSED")
