"""Archie filament selection (needs this machine's Creality install)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import archie_workflow as aw

mats = aw.list_archie_filaments()
assert isinstance(mats, list) and len(mats) > 5, mats
assert "Generic ASA" in mats and "Generic PLA" in mats, mats
print("PASS filament list (%d)" % len(mats))
assert aw._resolve_filament(None).name == aw.FILAMENT.name
assert aw._resolve_filament("Generic PLA").is_file()
assert aw._resolve_filament("generic pla").name.startswith("Generic PLA")
for _bad in ("NoSuchFilament", "../evil", "pla", ""):
    try:
        aw._resolve_filament(_bad)
    except ValueError:
        pass
    else:
        raise AssertionError("accepted %r" % (_bad,))
print("PASS filament validation")
print("ALL ARCHIE FILAMENT TESTS PASSED")
