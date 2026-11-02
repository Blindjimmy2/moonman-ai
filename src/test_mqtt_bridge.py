"""Offline tests for the MQTT bridge's voice shaping. No broker, no agent.

Parses the source (importing the bridge would import agent.py, which needs
a live API key). Run:
  python test_mqtt_bridge.py
"""

import re
from pathlib import Path

BRIDGE = (Path(__file__).parent / "moonman_mqtt_bridge.py").read_text(
    encoding="utf-8")

# Voice asks carry a hard spoken-length target (latency + TTS budgets).
found = re.search(r"\[Voice reply: ([^\]]+)\]", BRIDGE)
assert found, "voice hint missing"
hint = found.group(1)
assert "500" in hint and "sentence" in hint.lower(), repr(hint)
print("PASS voice hint:", hint)

# Dashboard reads (no hint); console commands keep exact control phrases.
assert 'if device == "dashboard"' in BRIDGE, "dashboard exemption missing"
for cmd in ("confirm print", "remember ", "recall "):
    assert cmd in BRIDGE, cmd
print("PASS dashboard + command exemptions")

# Junk-line stripping still guards speech.
assert "def _strip_junk_lines" in BRIDGE, "junk stripping missing"
print("PASS junk stripping present")

print("ALL MQTT BRIDGE TESTS PASSED")
