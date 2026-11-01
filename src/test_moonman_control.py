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
    "/api/ask",
    "/assets/emblem.png",
    "/favicon.ico",
):
    assert required in routes, "missing route " + required
print("PASS required endpoints present")

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
    "askbox",
):
    assert 'id="%s"' % element_id in CONTROL or "id='%s'" % element_id in (
        CONTROL
    ), "missing element " + element_id
print("PASS dashboard element IDs present")

print("ALL MISSION CONTROL TESTS PASSED")
