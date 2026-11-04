"""Chat-driven single-use approval for Archie print starts.

Replaces the old console input() gate (which can never work under Mission
Control) with an async state file the user drives from chat or dashboard:

  1. archie_upload_gcode verifies a file on Archie -> pend() records it.
  2. User says "START ARCHIE <filename>" (or dashboard Approve) -> approve().
  3. archie_start_print tool -> idle + consume + hash + file checks -> send.
  4. confirm_start() polls read-only status for start evidence.

Safety: approvals bind printer + filename + sha256 + job ID, are
single-use, expire after MAX_AGE seconds, and the tool re-verifies
printer-idle, local hash, and remote-file presence before every send.
This module NEVER starts a print by itself.

Isolation: this file governs ARCHIE ONLY (printer field asserted on
every read). Marvin/Longer approvals live in print_approval.py and its
own state file; the two can never cross (see consume/approve guards).

State file: generated/archie_approval.json
  (override for tests: ARCHIE_APPROVAL_FILE)
"""

import hashlib
import json
import os
import time
import uuid
from pathlib import Path

PRINTER = "archie"
ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "generated" / "archie_approval.json"
MAX_AGE = 300

HOST = "192.168.1.10"
WS_URL = f"ws://{HOST}:9999"


class ApprovalError(Exception):
    """Raised for any missing/expired/mismatched/consumed approval."""


def _state_path():
    override = os.environ.get("ARCHIE_APPROVAL_FILE")
    return Path(override) if override else STATE


def _read():
    path = _state_path()
    if not path.is_file():
        return None
    try:
        record = json.loads(path.read_text())
    except Exception:
        return None
    if not isinstance(record, dict):
        return None
    # Cross-printer guard: this state file must only ever hold Archie.
    if record.get("printer", PRINTER) != PRINTER:
        raise ApprovalError(
            "Approval is for %r, not Archie. Refusing."
            % record.get("printer")
        )
    return record


def _write(record):
    record["printer"] = PRINTER
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2))


def _expired(record):
    try:
        return time.time() - float(record.get("created", 0)) > MAX_AGE
    except Exception:
        return True


def _expire(record):
    record["status"] = "expired"
    _write(record)


def pend(filename, sha256, size, local_path=""):
    """Record a freshly upload-verified file as awaiting approval."""
    from archie_start_print import build_start_command

    build_start_command(filename)  # validates basename/.gcode, sends nothing
    record = {
        "printer": PRINTER,
        "job_id": "arch-%s" % uuid.uuid4().hex[:8],
        "filename": filename,
        "sha256": sha256 or "",
        "size": int(size or 0),
        "local_path": str(local_path or ""),
        "created": time.time(),
        "approved_at": None,
        "status": "pending",
    }
    _write(record)
    return record


_NUMWORDS = {"zero": "0", "one": "1", "two": "2", "three": "3",
             "four": "4", "five": "5", "six": "6", "seven": "7",
             "eight": "8", "nine": "9"}


def _spoken_match(want, have):
    """True if a voice transcript plausibly names the staged file.

    Speech turns plate_1.gcode into 'plate 1G code' or 'plate one'.
    Normalize both sides (lowercase, number words to digits, drop
    everything but alphanumerics) and accept only a clear containment
    either way, with at least 5 matching characters so 'cube' or 'it'
    can never approve. All other guards (status, expiry, single-use)
    still apply.
    """
    import re

    def norm(text):
        text = str(text or "").lower()
        for word, digit in _NUMWORDS.items():
            text = re.sub(r"\b%s\b" % word, digit, text)
        return re.sub(r"[^a-z0-9]", "", text)

    a, b = norm(want), norm(have)
    if len(a) < 5 or len(b) < 5:
        return False
    return a in b or b in a


def approve(filename):
    """Arm ONE print start. Returns a human-readable confirmation."""
    want = (filename or "").strip()
    if not want:
        raise ApprovalError("Name the staged file: START ARCHIE <file.gcode>")
    record = _read()
    if record is None:
        raise ApprovalError("No file is staged awaiting approval.")
    if record.get("status") == "consumed":
        raise ApprovalError("That approval was already used. Re-stage.")
    if record.get("status") not in ("pending", "approved"):
        raise ApprovalError(
            "Staged job is %s, not approvable." % record.get("status")
        )
    have = str(record.get("filename", ""))
    if have.lower() != want.lower() and not _spoken_match(want, have):
        raise ApprovalError(
            "Staged file is %s, not %s. Nothing approved." % (have, want)
        )
    if _expired(record):
        _expire(record)
        raise ApprovalError("Staging expired (>5 min). Re-stage to continue.")
    record["status"] = "approved"
    record["approved_at"] = time.time()
    _write(record)
    left = int(MAX_AGE - (time.time() - float(record["created"])))
    return (
        "Approved ONE start of %s on Archie (job %s, expires in ~%ds). "
        "Tell Moon Man to print it."
        % (have, record["job_id"], max(0, left))
    )


def consume(filename):
    """Consume a live approval. Returns the record or raises ApprovalError."""
    want = (filename or "").strip()
    record = _read()
    if record is None:
        raise ApprovalError("No file is staged awaiting approval.")
    if record.get("status") == "consumed":
        raise ApprovalError("Approval already used. Re-approve to print again.")
    if record.get("status") != "approved":
        raise ApprovalError(
            "Say: START ARCHIE %s" % record.get("filename", "<file.gcode>")
        )
    have = str(record.get("filename", ""))
    if have.lower() != want.lower():
        raise ApprovalError("Approved file is %s, not %s." % (have, want))
    if _expired(record):
        _expire(record)
        raise ApprovalError("Approval expired (>5 min). Re-approve.")
    record["status"] = "consumed"
    _write(record)
    return record


def cancel():
    """Clear any staged/approved state. Returns a message."""
    try:
        record = _read()
    except ApprovalError as error:
        return str(error)
    if record is None or record.get("status") in ("consumed", "expired"):
        return "Nothing staged. Nothing to cancel."
    record["status"] = "cancelled"
    _write(record)
    return "Archie staging cancelled for %s (job %s)." % (
        record.get("filename", "?"),
        record.get("job_id", "?"),
    )


def current():
    """Return (record-or-None, expires_in-or-None) for dashboards."""
    try:
        record = _read()
    except ApprovalError:
        return None, None
    if record is None:
        return None, None
    if record.get("status") not in ("pending", "approved"):
        return record, None
    try:
        left = int(MAX_AGE - (time.time() - float(record.get("created", 0))))
    except Exception:
        left = 0
    return record, max(0, left)


def describe():
    """One-line status for chat / dashboard."""
    try:
        record = _read()
    except ApprovalError as error:
        return str(error)
    if record is None:
        return "No Archie file staged."
    left = int(MAX_AGE - (time.time() - float(record.get("created", 0))))
    base = "Archie: %s [%s] job %s" % (
        record.get("filename", "?"),
        record.get("status", "?"),
        record.get("job_id", "?"),
    )
    if record.get("status") in ("pending", "approved"):
        base += " expires in ~%ds" % max(0, left)
    return base


def verify_local(record):
    """Re-hash the local G-code against the approval. (ok, reason)"""
    path = Path(record.get("local_path") or "")
    if not path.is_file():
        return False, "Local G-code missing; re-stage before printing."
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except Exception as error:
        return False, "Could not re-hash G-code: %s" % error
    if not record.get("sha256"):
        return False, "Approval has no recorded hash; re-stage."
    if digest != record["sha256"]:
        return False, "Local G-code changed since staging; re-stage."
    return True, "Local hash matches approval."


def _num(value, default=None):
    try:
        if value is None or isinstance(value, bool):
            return default
        return float(value)
    except Exception:
        return default


def printer_idle():
    """Read-only readiness probe. Returns (ok, reason, snapshot).

    Refuses when: unreachable, error code set, progress shows mid-print,
    or hot nozzle at 0% (heating/starting). The raw `state` enum is NOT
    gated on -- its values were never documented -- but is reported.
    """
    try:
        from archie_workflow import archie_status

        status = archie_status()
    except Exception as error:
        return False, "Archie unreachable: %s" % error, {}
    snapshot = {
        "state": status.get("state"),
        "progress": status.get("progress"),
        "file": status.get("file"),
        "nozzle_c": status.get("nozzle_c"),
        "bed_c": status.get("bed_c"),
    }
    error = status.get("error") or {}
    errcode = error.get("errcode", 0) if isinstance(error, dict) else 0
    if _num(errcode, 0) != 0:
        return False, "Archie reports error %r." % (error,), snapshot
    progress = _num(status.get("progress"))
    if progress is None:
        return False, "Could not determine Archie progress; refusing.", snapshot
    if 0 < progress < 100:
        return (
            False,
            "Archie looks mid-print (%s%% of %s)."
            % (status.get("progress"), status.get("file")),
            snapshot,
        )
    nozzle = _num(status.get("nozzle_c"), 0.0) or 0.0
    if progress == 0 and status.get("file") and nozzle > 60:
        return False, "Archie looks busy (hot nozzle, 0%%).", snapshot
    return True, "Archie idle (progress %s, no errors)." % progress, snapshot


def remote_file_ok(filename, size):
    """Read-only check that the staged file is still on Archie."""
    import json as _json

    import websocket

    try:
        from archie_upload import _find_file
    except Exception:
        return False
    try:
        ws = websocket.create_connection(WS_URL, timeout=6)
    except Exception:
        return False
    try:
        ws.settimeout(3)
        ws.send(_json.dumps({"method": "get", "params": {"reqGcodeFile": 1}}))
        for _ in range(8):
            try:
                message = _json.loads(ws.recv())
            except Exception:
                break
            candidate = _find_file(message, filename)
            if candidate:
                return candidate.get("file_size") == size
    except Exception:
        return False
    finally:
        try:
            ws.close()
        except Exception:
            pass
    return False


def confirm_start(filename, timeout_s=12, poll_s=3):
    """Poll READ-ONLY status for start evidence. Never raises, never commands.

    Returns {"confirmed": bool, ...}. Confirmed only when Archie reports
    our file active below 100% progress. A sent command alone is NOT
    confirmation -- callers must report this result honestly.
    """
    from archie_workflow import archie_status

    want = (filename or "").lower()
    deadline = time.time() + timeout_s
    last = {}
    while time.time() < deadline:
        try:
            last = archie_status()
        except Exception as error:
            return {
                "confirmed": False,
                "note": "status unreadable after send: %s" % error,
            }
        remote = str(last.get("file") or "")
        progress = _num(last.get("progress"))
        if (
            want
            and remote.lower().endswith(want)
            and progress is not None
            and progress < 100
        ):
            return {
                "confirmed": True,
                "file": remote,
                "progress": progress,
                "state": last.get("state"),
            }
        time.sleep(poll_s)
    return {
        "confirmed": False,
        "file": last.get("file"),
        "progress": last.get("progress"),
        "state": last.get("state"),
        "note": "no start evidence within %ss; check Archie directly" % timeout_s,
    }
