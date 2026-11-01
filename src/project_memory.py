"""Project-aware persistent engineering memory for Moon Man.

SQLite-backed (same DB file as memory.py, new tables only):
projects, per-turn checkpoints, namespaced facts with verification status.

memory.py (general long-term facts) is left untouched. Checkpoints are
written by code from tool results; the model never fabricates them.
"""

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "moonman_memory.db"

PROJECT_ALIASES = (
    ("moonman", ("moon man", "moonman", "head gimbal", "gimbal")),
    ("gumbler", ("gumbler", "gumbling", "gumbling machine")),
    ("mac_lite", ("mac lite", "maclite", "mac_lite")),
)
VALID_PROJECTS = ("moonman", "gumbler", "mac_lite", "general")
STATUSES = ("verified", "assumption", "plan", "failed", "user_confirmed")

MAX_FACT_CHARS = 1000
MAX_SUBJECT_CHARS = 200
MAX_PROVENANCE_CHARS = 300
MAX_BRIEF_CHARS = 750


def _now():
    return datetime.now(timezone.utc).isoformat()


class _ClosingConnection(sqlite3.Connection):
    """Connection that commits/rolls back AND closes on with-block exit."""

    def __exit__(self, *exc):
        try:
            super().__exit__(*exc)
        finally:
            self.close()


def connect(db_path=None):
    target = Path(db_path) if db_path else DB_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(target, factory=_ClosingConnection)
    db.row_factory = sqlite3.Row

    db.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            name TEXT PRIMARY KEY,
            aliases TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS checkpoints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project TEXT NOT NULL,
            created_at TEXT NOT NULL,
            turn_status TEXT NOT NULL,
            rounds_used INTEGER NOT NULL DEFAULT 0,
            tool_calls_used INTEGER NOT NULL DEFAULT 0,
            summary TEXT NOT NULL DEFAULT '',
            verified_json TEXT NOT NULL DEFAULT '[]',
            pending TEXT NOT NULL DEFAULT '',
            blockers TEXT NOT NULL DEFAULT '',
            next_step TEXT NOT NULL DEFAULT ''
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS project_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project TEXT NOT NULL,
            subject TEXT NOT NULL,
            fact TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'assumption',
            provenance TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            supersedes INTEGER
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL DEFAULT ''
        )
    """)

    for name, aliases in PROJECT_ALIASES + (("general", ()),):
        db.execute(
            "INSERT OR IGNORE INTO projects (name, aliases, created_at)"
            " VALUES (?, ?, ?)",
            (name, json.dumps(list(aliases)), _now()),
        )

    db.commit()
    return db


def detect_project(text):
    """Return the single project named in text, else None (never guess)."""
    found = []
    lowered = text.lower()
    for name, aliases in PROJECT_ALIASES:
        for alias in aliases:
            if re.search(r"\b" + re.escape(alias) + r"\b", lowered):
                found.append(name)
                break
    unique = list(dict.fromkeys(found))
    return unique[0] if len(unique) == 1 else None


def set_active_project(name):
    if name not in VALID_PROJECTS:
        raise ValueError("Unknown project: %r" % (name,))
    with connect() as db:
        db.execute(
            "INSERT INTO meta (key, value) VALUES ('last_active', ?)"
            " ON CONFLICT(key) DO UPDATE SET value = ?",
            (name, name),
        )
    return name


def get_active_project():
    with connect() as db:
        row = db.execute(
            "SELECT value FROM meta WHERE key = 'last_active'"
        ).fetchone()
    if row and row["value"] in VALID_PROJECTS:
        return row["value"]
    return "general"


def write_checkpoint(project, turn_status, rounds_used=0, tool_calls_used=0,
                     summary="", verified=None, pending="",
                     blockers="", next_step=""):
    if project not in VALID_PROJECTS:
        raise ValueError("Unknown project: %r" % (project,))
    with connect() as db:
        cursor = db.execute(
            """
            INSERT INTO checkpoints
            (project, created_at, turn_status, rounds_used, tool_calls_used,
             summary, verified_json, pending, blockers, next_step)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project,
                _now(),
                str(turn_status)[:40],
                int(rounds_used),
                int(tool_calls_used),
                str(summary)[:600],
                json.dumps(list(verified or [])[:12], default=str)[:4000],
                str(pending)[:400],
                str(blockers)[:400],
                str(next_step)[:400],
            ),
        )
        return cursor.lastrowid


def latest_checkpoint(project):
    if project not in VALID_PROJECTS:
        raise ValueError("Unknown project: %r" % (project,))
    with connect() as db:
        row = db.execute(
            """
            SELECT * FROM checkpoints
            WHERE project = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (project,),
        ).fetchone()
    return dict(row) if row else None


def project_brief(project):
    """Bounded resume context for prompt injection. Never raises."""
    try:
        if project not in VALID_PROJECTS:
            return "No project context."
        row = latest_checkpoint(project)
        if not row:
            return "No checkpoints recorded for %s yet." % project
        parts = [
            "Latest %s checkpoint (%s, %s, %d rounds/%d calls):" % (
                project, row["created_at"][:16].replace("T", " "),
                row["turn_status"], row["rounds_used"], row["tool_calls_used"]),
            row["summary"] or "(no summary)",
        ]
        if row["blockers"]:
            parts.append("Blockers: " + row["blockers"])
        if row["next_step"]:
            parts.append("NEXT: " + row["next_step"])
        elif row["pending"]:
            parts.append("Pending: " + row["pending"])
        text = "\n".join(parts)
        return text[:MAX_BRIEF_CHARS]
    except Exception:
        return "No project context."


def remember_fact(project, subject, fact, status="assumption", provenance=""):
    if project not in VALID_PROJECTS:
        raise ValueError("Unknown project: %r" % (project,))
    if status not in STATUSES:
        raise ValueError("Status must be one of: " + ", ".join(STATUSES))
    subject = (subject or "").strip()
    fact = (fact or "").strip()
    provenance = (provenance or "").strip()
    if not subject or not fact:
        raise ValueError("Both subject and fact are required.")
    if len(subject) > MAX_SUBJECT_CHARS:
        raise ValueError("Subject too long (max %d chars)." % MAX_SUBJECT_CHARS)
    if len(fact) > MAX_FACT_CHARS:
        raise ValueError(
            "Fact too long (max %d chars); split it, never truncate specs."
            % MAX_FACT_CHARS
        )
    if len(provenance) > MAX_PROVENANCE_CHARS:
        raise ValueError("Provenance too long.")

    with connect() as db:
        existing = db.execute(
            """
            SELECT id FROM project_facts
            WHERE project = ? AND subject = ? COLLATE NOCASE
              AND fact = ? COLLATE NOCASE
            LIMIT 1
            """,
            (project, subject, fact),
        ).fetchone()
        if existing:
            return "Already recorded for %s: %s" % (project, subject)
        db.execute(
            """
            INSERT INTO project_facts
            (project, subject, fact, status, provenance, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (project, subject, fact, status, provenance, _now(), _now()),
        )
    return "Recorded for %s [%s]: %s" % (project, status, subject)


def recall_facts(project, query, limit=3):
    if project not in VALID_PROJECTS:
        raise ValueError("Unknown project: %r" % (project,))
    limit = max(1, min(int(limit or 3), 10))
    words = [w.strip(".,?!:;") for w in str(query or "").split()]
    words = [w for w in words if len(w) >= 4][:4]

    with connect() as db:
        if not words:
            rows = db.execute(
                """
                SELECT subject, fact, status, provenance, updated_at
                FROM project_facts WHERE project = ?
                ORDER BY id DESC LIMIT ?
                """,
                (project, limit),
            ).fetchall()
        else:
            clauses = " OR ".join(
                "(subject LIKE ? OR fact LIKE ?)" for _ in words
            )
            params = [project]
            for word in words:
                params.extend(["%" + word + "%", "%" + word + "%"])
            params.append(limit)
            rows = db.execute(
                """
                SELECT subject, fact, status, provenance, updated_at
                FROM project_facts WHERE project = ? AND (%s)
                ORDER BY id DESC LIMIT ?
                """ % clauses,
                params,
            ).fetchall()
    return [dict(row) for row in rows]


def facts_since(project, since, status=None):
    """Facts updated at or after an ISO timestamp, newest last."""
    if project not in VALID_PROJECTS:
        raise ValueError("Unknown project: %r" % (project,))
    if status is not None and status not in STATUSES:
        raise ValueError("Status must be one of: " + ", ".join(STATUSES))
    query = """
        SELECT subject, fact, status, provenance, updated_at
        FROM project_facts WHERE project = ? AND updated_at >= ?
        """
    params = [project, str(since)]
    if status is not None:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY id"
    with connect() as db:
        rows = db.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def tool_project_recall(project, query, limit=5):
    try:
        if (project or "") not in VALID_PROJECTS:
            return {"status": "error",
                    "error": "Unknown project. Use one of: "
                             + ", ".join(VALID_PROJECTS)}
        rows = recall_facts(project, query or "", limit)
        return {"status": "ok", "project": project,
                "facts": rows, "count": len(rows)}
    except Exception as exc:
        return {"status": "error", "error": str(exc)[:300]}


def tool_project_checkpoint(project):
    try:
        if (project or "") not in VALID_PROJECTS:
            return {"status": "error",
                    "error": "Unknown project. Use one of: "
                             + ", ".join(VALID_PROJECTS)}
        row = latest_checkpoint(project)
        if not row:
            return {"status": "ok", "project": project,
                    "checkpoint": None,
                    "message": "No checkpoints recorded yet."}
        row["verified"] = json.loads(row.pop("verified_json") or "[]")
        return {"status": "ok", "project": project, "checkpoint": row}
    except Exception as exc:
        return {"status": "error", "error": str(exc)[:300]}


def tool_project_remember(project, subject, fact, status="assumption",
                          provenance=""):
    try:
        if (project or "") not in VALID_PROJECTS:
            return {"status": "error",
                    "error": "Unknown project. Use one of: "
                             + ", ".join(VALID_PROJECTS)}
        message = remember_fact(project, subject, fact, status, provenance)
        return {"status": "ok", "project": project, "message": message}
    except Exception as exc:
        return {"status": "error", "error": str(exc)[:300]}


if __name__ == "__main__":
    import sys

    name = sys.argv[1] if len(sys.argv) > 1 else get_active_project()
    print("Active project:", get_active_project())
    print(project_brief(name))
