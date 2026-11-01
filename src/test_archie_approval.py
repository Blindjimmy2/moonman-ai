"""Offline tests for archie_approval. No printer, no network.

Uses a temp state file (ARCHIE_APPROVAL_FILE). Run:
  python test_archie_approval.py
"""

import hashlib
import json
import os
import tempfile
import time

_tmp = tempfile.NamedTemporaryFile(
    prefix="archie_approval_test_", suffix=".json", delete=False
)
_tmp.close()
os.environ["ARCHIE_APPROVAL_FILE"] = _tmp.name

import archie_approval as aa


def expect_error(func, *args):
    try:
        func(*args)
    except aa.ApprovalError as error:
        return str(error)
    raise AssertionError("expected ApprovalError from %r" % (func,))


# pend + approve + consume happy path
rec0 = aa.pend("plate_1.gcode", "abc123", 288333, "fake/path.gcode")
assert rec0["printer"] == "archie", rec0
assert rec0["job_id"].startswith("arch-"), rec0
rec0b = aa.pend("plate_1.gcode", "abc123", 288333)
assert rec0b["job_id"] != rec0["job_id"], "job IDs must be unique"
msg = aa.approve("plate_1.gcode")
assert "Approved ONE start" in msg and "job arch-" in msg, msg
rec = aa.consume("plate_1.gcode")
assert rec["status"] == "consumed", rec
print("PASS happy path + job_id:", msg)

# single-use: second consume refused
err = expect_error(aa.consume, "plate_1.gcode")
assert "already used" in err, err
print("PASS single-use:", err)

# approve is case-insensitive on filename
aa.pend("Plate_2.gcode", "d", 10)
assert "Approved ONE start" in aa.approve("plate_2.gcode")
print("PASS case-insensitive approve")

# wrong file refused
aa.pend("plate_1.gcode", "a", 1)
err = expect_error(aa.approve, "other.gcode")
assert "not other.gcode" in err, err
print("PASS wrong-file:", err)

# consume without approve -> chat instruction, not a hang
err = expect_error(aa.consume, "plate_1.gcode")
assert err.startswith("Say: START ARCHIE"), err
print("PASS awaiting message:", err)

# bad filenames rejected at pend (same rules as the start command)
for bad in ("", "../x.gcode", "x.stl", "a/b.gcode"):
    try:
        aa.pend(bad, "a", 1)
    except ValueError:
        pass
    else:
        raise AssertionError("pend accepted %r" % bad)
print("PASS filename validation")

# expiry (craft an old record directly)
old = {
    "printer": "archie",
    "job_id": "arch-old",
    "filename": "plate_1.gcode",
    "sha256": "a",
    "size": 1,
    "local_path": "",
    "created": time.time() - 9999,
    "approved_at": time.time() - 9999,
    "status": "approved",
}
with open(_tmp.name, "w") as handle:
    handle.write(json.dumps(old))
err = expect_error(aa.consume, "plate_1.gcode")
assert "expired" in err, err
print("PASS expiry:", err)

# foreign-printer record can never route to Archie
foreign = dict(old)
foreign["printer"] = "marvin"
foreign["status"] = "approved"
foreign["created"] = time.time()
with open(_tmp.name, "w") as handle:
    handle.write(json.dumps(foreign))
err = expect_error(aa.consume, "plate_1.gcode")
assert "not Archie" in err, err
err = expect_error(aa.approve, "plate_1.gcode")
assert "not Archie" in err, err
print("PASS cross-printer guard:", err)

# local hash verification (real temp gcode bytes)
gcode = tempfile.NamedTemporaryFile(
    prefix="hash_test_", suffix=".gcode", delete=False
)
gcode.write(b"G28\nG1 X10\n")
gcode.close()
digest = hashlib.sha256(b"G28\nG1 X10\n").hexdigest()
aa.pend("hash_test.gcode", digest, 12, gcode.name)
aa.approve("hash_test.gcode")
held = dict(json.loads(open(_tmp.name).read()))
ok, reason = aa.verify_local(held)
assert ok, reason
with open(gcode.name, "wb") as handle:
    handle.write(b"TAMPERED!")
ok, reason = aa.verify_local(held)
assert not ok and "changed" in reason, reason
os.unlink(gcode.name)
ok, reason = aa.verify_local(held)
assert not ok and "missing" in reason, reason
print("PASS local re-hash:", reason)

# start confirmation against stubbed (fake) printer status
import archie_workflow

real_status = archie_workflow.archie_status
try:
    archie_workflow.archie_status = lambda: {
        "file": "/usr/data/printer_data/gcodes/plate_1.gcode",
        "progress": 3,
        "state": 5,
    }
    conf = aa.confirm_start("plate_1.gcode", timeout_s=5, poll_s=0.5)
    assert conf["confirmed"] is True, conf
    print("PASS confirm_start positive:", conf)
    archie_workflow.archie_status = lambda: {
        "file": "/usr/data/printer_data/gcodes/other.gcode",
        "progress": 100,
        "state": 2,
    }
    conf = aa.confirm_start("plate_1.gcode", timeout_s=1, poll_s=0.2)
    assert conf["confirmed"] is False, conf
    print("PASS confirm_start negative:", conf)
finally:
    archie_workflow.archie_status = real_status

# dashboard accessor
aa.pend("plate_1.gcode", "a", 1)
record, expires = aa.current()
assert record["job_id"].startswith("arch-") and expires is not None
assert "job arch-" in aa.describe(), aa.describe()
print("PASS dashboard accessor:", aa.describe())

# cancel clears staging
assert "cancelled" in aa.cancel()
print("PASS cancel:", aa.describe())

os.unlink(_tmp.name)
print("ALL ARCHIE APPROVAL TESTS PASSED")
