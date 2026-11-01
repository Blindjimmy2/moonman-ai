"""Autonomous objective runner with research-before-escalation policy.

run_objective() drives ask_moonman turn by turn until the objective is
done, blocked, needs a human, or run caps are hit. Needs-human stops for
ordinary missing-information questions are accepted only with a
structured escalation record backed by code-recorded tool evidence;
safety, authorization, and irreversible stops are immediate.

Safety inherits from ask_moonman unchanged: ownership fail-closed, doc
pinning, per-turn 8 rounds / 20 calls. The runner never emits
print-confirmation commands.
"""

import json
import re
from datetime import datetime, timezone

import agent
from project_memory import (
    latest_checkpoint,
    recall_facts,
    set_active_project,
    facts_since,
)

RUNNER_PROJECTS = ("moonman", "gumbler", "mac_lite")
DISPOSITIONS = ("done", "continue", "needs_human")
IMMEDIATE_KINDS = ("safety", "authorization", "irreversible", "design_intent")
ESCALATION_KINDS = ("ordinary",) + IMMEDIATE_KINDS
ORDINARY_MIN_CATEGORIES = 2

FOOTER_RE = re.compile(r"^RUN:\s*(done|continue|needs_human)\b",
                       re.IGNORECASE | re.MULTILINE)
ENTRY_RE = re.compile(r"^\[(VERIFIED|UNVERIFIED|FAILED)\]\s+(\w+):")

MEMORY_TOOLS = frozenset({
    "project_recall", "project_checkpoint",
    "engineering_list", "engineering_read",
})
GEOMETRY_TOOLS = frozenset({
    "fusion_inspect_design", "fusion_inspect_features",
    "fusion_inspect_geometry", "fusion_check_clearance",
    "fusion_interference_check", "fusion_document_info",
})
TRANSIENT_HINTS = ("bridge", "timeout", "timed out", "connection",
                   "temporarily")

RECORD_KEYS = ("question", "kind", "conflicts", "confidence", "why_human")
CHECKED_CATEGORIES = ("memory", "web", "geometry")


def _now():
    return datetime.now(timezone.utc).isoformat()


def parse_footer(reply):
    """Return the last RUN footer disposition, or unknown."""
    matches = FOOTER_RE.findall(reply or "")
    if not matches:
        return {"disposition": "unknown", "raw": None}
    return {"disposition": matches[-1].lower(),
            "raw": matches[-1]}


def parse_escalation(reply):
    """Parse the structured ESCALATION record. Strict by design."""
    errors = []
    text = reply or ""
    head = re.search(r"^ESCALATION:\s*$", text,
                     re.IGNORECASE | re.MULTILINE)
    if not head:
        return {"ok": False, "record": None,
                "errors": ["missing ESCALATION: record"]}
    fields = {}
    checked = {}
    in_checked = False
    for line in text[head.end():].splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if re.match(r"^checked:\s*$", stripped, re.IGNORECASE):
            in_checked = True
            continue
        item = re.match(r"^-\s*(\w+)\s*:\s*(.*?)\s*$", stripped)
        if in_checked and item:
            category = item.group(1).lower()
            if category not in CHECKED_CATEGORIES:
                errors.append("unknown checked category: %s" % category)
                continue
            query, arrow, result = item.group(2).partition("->")
            if not arrow or not result.strip():
                continue
            checked.setdefault(category, []).append(
                (query.strip(), result.strip()))
            continue
        pair = re.match(r"^(\w+)\s*:\s*(.*?)\s*$", stripped)
        if pair and pair.group(1).lower() in RECORD_KEYS:
            in_checked = False
            fields[pair.group(1).lower()] = pair.group(2)
    for key in RECORD_KEYS:
        if not fields.get(key):
            errors.append("missing field: %s" % key)
    if fields.get("kind") and fields["kind"].lower() not in ESCALATION_KINDS:
        errors.append("kind must be one of: "
                      + ", ".join(ESCALATION_KINDS))
    if fields.get("confidence") and fields["confidence"].lower() not in (
            "low", "medium", "high"):
        errors.append("confidence must be low, medium, or high")
    if errors:
        return {"ok": False, "record": None, "errors": errors}
    fields["kind"] = fields["kind"].lower()
    fields["confidence"] = fields["confidence"].lower()
    fields["checked"] = checked
    return {"ok": True, "record": fields, "errors": []}


def evidence_categories(checkpoint_rows):
    """Ladder categories with code-recorded tool evidence this run."""
    found = set()
    for row in checkpoint_rows or []:
        raw = (row or {}).get("verified_json", "[]")
        try:
            entries = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            continue
        for entry in entries or []:
            match = ENTRY_RE.match(str(entry))
            if not match or match.group(1) == "FAILED":
                continue
            tool = match.group(2)
            if tool in MEMORY_TOOLS:
                found.add("memory")
            elif tool == "web_research" and "search_occurred=True" in str(entry):
                found.add("web")
            elif tool in GEOMETRY_TOOLS:
                found.add("geometry")
    return found


def validate_escalation(record, evidenced):
    """Ordinary questions need >=2 evidenced avenues; urgent kinds pass."""
    if record["kind"] in IMMEDIATE_KINDS:
        return {"valid": True, "reasons": []}
    claimed = set((record.get("checked") or {}))
    matched = claimed & set(evidenced or set())
    if len(matched) >= ORDINARY_MIN_CATEGORIES:
        return {"valid": True, "reasons": []}
    reasons = [
        "ordinary escalation needs evidence of at least %d ladder avenues "
        "checked; matched: %s" % (
            ORDINARY_MIN_CATEGORIES,
            ", ".join(sorted(matched)) or "none"),
    ]
    for category in sorted(claimed - matched):
        reasons.append("claimed but unevidenced in turn record: %s"
                       % category)
    return {"valid": False, "reasons": reasons}


def is_settled(project, question):
    """True when a deadend: fact already settles this question."""
    try:
        rows = recall_facts(project, question, limit=10)
    except Exception:
        return False
    return any(str(row.get("subject", "")).lower().startswith("deadend:")
               for row in rows)


def _report(status, project, objective, turns, calls, checkpoint_ids,
            assumptions, escalation, warnings, reply):
    return {
        "status": status,
        "project": project,
        "objective": objective,
        "turns": turns,
        "tool_calls": calls,
        "checkpoint_ids": checkpoint_ids,
        "assumptions": assumptions,
        "escalation": escalation,
        "validation_warnings": warnings,
        "reply_tail": (reply or "")[-500:],
    }


def run_objective(objective, project, max_turns=6, max_calls=60,
                  turn_fn=None, read_checkpoint=None, set_active=None,
                  assumptions_fn=None):
    """Drive turns until done, needs_human, blocked, or run caps."""
    if project not in RUNNER_PROJECTS:
        raise ValueError("Runner project must be one of: "
                         + ", ".join(RUNNER_PROJECTS))
    ask = turn_fn or agent.ask_moonman
    read_row = read_checkpoint or latest_checkpoint
    activate = set_active or set_active_project
    collect_assumptions = assumptions_fn or (
        lambda proj, since: facts_since(proj, since, status="assumption"))

    activate(project)
    started = _now()
    prompt = ("%s: engineering objective:\n%s\n"
              "Follow the autonomy protocol. End EVERY turn with a "
              "RUN footer." % (project, objective))
    turns = 0
    calls = 0
    checkpoint_ids = []
    evidence_rows = []
    bounced = False
    retried = False
    warnings = []
    reply = ""
    while True:
        if turns >= max_turns or calls >= max_calls:
            return _report("run_cap", project, objective, turns, calls,
                           checkpoint_ids,
                           collect_assumptions(project, started),
                           None, warnings, reply)
        reply = ask(prompt)
        turns += 1
        try:
            row = read_row(project)
        except Exception as error:
            row = None
            warnings.append("checkpoint unreadable: %s" % error)
        if not row:
            warnings.append("no checkpoint for turn %d; halting for human"
                            % turns)
            return _report("needs_human", project, objective, turns,
                           calls, checkpoint_ids,
                           collect_assumptions(project, started),
                           None, warnings, reply)
        calls += int(row.get("tool_calls_used") or 0)
        if row.get("id") is not None:
            checkpoint_ids.append(row["id"])
        evidence_rows.append(row)
        status = row.get("turn_status", "")
        if status == "error-halt":
            blockers = str(row.get("blockers") or "")
            transient = any(hint in blockers.lower()
                            for hint in TRANSIENT_HINTS)
            if transient and not retried:
                retried = True
                prompt = ("%s: retry once after transient failure: %s "
                          "End with a RUN footer."
                          % (project, blockers[:200]))
                continue
            warnings.append("error-halt: %s" % (blockers[:200]
                                                or "see reply"))
            return _report("needs_human", project, objective, turns,
                           calls, checkpoint_ids,
                           collect_assumptions(project, started),
                           None, warnings, reply)
        footer = parse_footer(reply)["disposition"]
        if footer == "done":
            return _report("done", project, objective, turns, calls,
                           checkpoint_ids,
                           collect_assumptions(project, started),
                           None, warnings, reply)
        if footer == "needs_human":
            parsed = parse_escalation(reply)
            if parsed["ok"]:
                check = validate_escalation(
                    parsed["record"], evidence_categories(evidence_rows))
            else:
                check = {"valid": False, "reasons": parsed["errors"]}
            if check["valid"]:
                return _report("needs_human", project, objective, turns,
                               calls, checkpoint_ids,
                               collect_assumptions(project, started),
                               parsed["record"] if parsed["ok"] else None,
                               warnings, reply)
            warnings.extend(check["reasons"])
            if not bounced:
                bounced = True
                prompt = ("%s: ESCALATION-REJECTED: %s Complete ladder "
                          "R1-R4 with real tool calls (memory, web, "
                          "geometry), then re-decide. End with a RUN "
                          "footer." % (project, " ".join(check["reasons"])))
                continue
            return _report("needs_human", project, objective, turns,
                           calls, checkpoint_ids,
                           collect_assumptions(project, started),
                           parsed["record"] if parsed["ok"] else None,
                           warnings, reply)
        if status in ("round-budget-exhausted", "tool-cap-exhausted"):
            prompt = ("%s: continue the objective from the outcome "
                      "record. End with a RUN footer." % project)
            continue
        if footer == "unknown":
            warnings.append("no RUN footer on a completed turn; halting "
                            "for human")
            return _report("needs_human", project, objective, turns,
                           calls, checkpoint_ids,
                           collect_assumptions(project, started),
                           None, warnings, reply)
        prompt = ("%s: continue the objective from the outcome record. "
                  "End with a RUN footer." % project)
