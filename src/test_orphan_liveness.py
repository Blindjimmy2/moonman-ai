"""Orphan liveness: an exited-but-unreaped child must read dead.

Regression test: os.kill(pid, 0) succeeds on Windows while any handle
to a terminated process stays open (the dashboard keeps its Popen
object forever), so a crashed service wedged as a permanent phantom
ORPHAN that blocked its own restart. _pid_alive must consult the real
exit state, not mere openability.
Run (Windows): python test_orphan_liveness.py
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import moonman_control as m

proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
try:
    assert m._pid_alive(proc.pid) is True, "live child reads dead"
    print("PASS live child reads alive")
    birth = m._pid_create_time(proc.pid)
    assert birth is not None and abs(birth - time.time()) < 180, \
        "birth insane: %r" % (birth,)
    print("PASS birth sane while live")
    proc.kill()
    proc.poll()  # reap the CODE, keep the HANDLE: mirrors the server
    assert m._pid_alive(proc.pid) is False, \
        "PHANTOM: unreaped dead child reads alive"
    print("PASS unreaped dead child reads dead (no phantom orphan)")
finally:
    proc.wait()
print("ALL ORPHAN LIVENESS TESTS PASSED")
