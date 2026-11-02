"""Offline tests for moonman_control. No servers, no network.

Parses the source (no import side effects). Run:
  python test_moonman_control.py
"""

import re
from pathlib import Path

SRC = Path(__file__).read_text(encoding="utf-8")

CONTROL = (Path(__file__).parent / "moonman_control.py").read_text(
    encoding="utf-8"
)

# Every route branch must be unique (guards applier re-run duplication).
routes = re.findall(r'elif url\.path == "([^"]+)"', CONTROL)
dupes = sorted({r for r in routes if routes.count(r) > 1})
assert not dupes, "duplicate routes: %r" % (dupes,)
print("PASS unique routes (%d):" % len(routes), ", ".join(sorted(routes)))

# Required endpoints (backend API surface).
for required in (
    "/api/services",
    "/api/logs",
    "/api/state",
    "/api/costs",
    "/api/archie/status",
    "/api/archie/approve",
    "/api/archie/cancel",
    "/api/servo",
    "/api/ask",
    "/api/startall",
    "/assets/emblem.png",
    "/favicon.ico",
):
    assert required in routes, "missing route " + required
print("PASS required endpoints present")
assert "startAll" in CONTROL and "Start All" in CONTROL, \
    "missing Start All button"
print("PASS start-all present")

# Dashboard page keeps the element IDs the JS refresh loop needs.
for element_id in (
    "svcs",
    "trk",
    "mic",
    "cost",
    "costd",
    "costt",
    "archie_info",
    "archie_file",
    "archie_hist",
    "archie_cd",
    "askbox",
    "askcancel",
    "ver",
    "sv_pan",
    "sv_pan_v",
    "sv_tilt_v",
    "sv_visor",
    "sv_visor_v",
    "sv_msg",
):
    assert 'id="%s"' % element_id in CONTROL or "id='%s'" % element_id in (
        CONTROL
    ), "missing element " + element_id
print("PASS dashboard element IDs present")

# Footer carries server version + start time (reliability pass).
for token in ("__VER__", "__STARTED__"):
    assert token in CONTROL, "missing footer token " + token
print("PASS footer version tokens")

# Archie status separates staged work from history.
for key in ('"staged"', '"last"', '"expires_at"'):
    assert key in CONTROL, "missing status key " + key
print("PASS archie staged/history payload")

# Failed services show their exit code; Ask has timeout + cancel.
assert "(exit " in CONTROL, "missing exit-code display"
assert "AbortController" in CONTROL, "missing ask abort"
print("PASS exit codes + ask cancel")

# Chat history renders markdown bold (display-only, escape-first).
assert "const fmt=" in CONTROL, "missing chat markdown renderer"
assert "fmt(e.q)" in CONTROL and "fmt(e.a)" in CONTROL, \
    "history not using fmt"
print("PASS chat markdown")

# Servo panel, PID birth verification, grid blowout guard.
assert "_pid_create_time" in CONTROL, "missing pid birth check"
assert "PID recycled" in CONTROL, "missing recycle cleanup"
assert "min-width:0}" in CONTROL, "missing grid guard"
assert "servoNudge" in CONTROL, "missing tilt nudge"
print("PASS servos + orphans + layout")

print("ALL MISSION CONTROL TESTS PASSED")
