"""Agent tool registry checks (offline text markers)."""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
AGENT = open(os.path.join(HERE, "agent.py"), encoding="utf-8").read()

# Gaze + visor tools registered.
for _name in ("gaze_point", "look_at", "track_mode", "get_gaze",
                "visor", "archie_filaments"):
    assert '"name": "%s"' % _name in AGENT, "tool missing: " + _name
print("PASS tools registered")

# Visor dispatch publishes the firmware topic with validated actions.
assert 'elif name == "visor"' in AGENT, "visor dispatch missing"
assert '"moonman/visor"' in AGENT, "visor topic missing"
assert '("open", "close")' in AGENT, "visor action validation missing"
print("PASS visor dispatch")

assert 'elif name == "archie_filaments"' in AGENT, "filament dispatch missing"
assert '"filament"' in AGENT, "filament param missing"
print("PASS archie filaments")

print("ALL AGENT TOOL TESTS PASSED")
