import sqlite3
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "moonman_memory.db"


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row

    db.execute("""
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT NOT NULL,
            fact TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'user_confirmed',
            created_at TEXT NOT NULL
        )
    """)

    db.commit()
    return db


def remember(subject, fact):
    subject = subject.strip()
    fact = fact.strip()

    if not subject or not fact:
        return "Memory needs both a subject and a fact."

    with connect() as db:
        existing = db.execute(
            """
            SELECT id FROM memories
            WHERE subject = ? COLLATE NOCASE
              AND fact = ? COLLATE NOCASE
            LIMIT 1
            """,
            (subject, fact)
        ).fetchone()

        if existing:
            return f"Already remembered: {subject} — {fact}"

        db.execute(
            """
            INSERT INTO memories
            (subject, fact, source, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                subject,
                fact,
                "user_confirmed",
                datetime.now(timezone.utc).isoformat()
            )
        )

    return f"Remembered: {subject} — {fact}"


def recall(subject):
    with connect() as db:
        rows = db.execute(
            """
            SELECT DISTINCT fact FROM memories
            WHERE subject LIKE ?
            ORDER BY id DESC
            LIMIT 10
            """,
            (f"%{subject}%",)
        ).fetchall()

    return [row["fact"] for row in rows]


def correct(subject, old_fact, new_fact):
    subject = subject.strip()
    old_fact = old_fact.strip()
    new_fact = new_fact.strip()

    if not subject or not old_fact or not new_fact:
        return "Correction needs a subject, old fact, and new fact."

    with connect() as db:
        rows = db.execute(
            """
            SELECT id FROM memories
            WHERE subject = ? COLLATE NOCASE
              AND fact = ? COLLATE NOCASE
            """,
            (subject, old_fact)
        ).fetchall()

        if not rows:
            return "I couldn't find that exact fact to correct."

        db.execute(
            """
            DELETE FROM memories
            WHERE subject = ? COLLATE NOCASE
              AND fact = ? COLLATE NOCASE
            """,
            (subject, old_fact)
        )

        existing = db.execute(
            """
            SELECT id FROM memories
            WHERE subject = ? COLLATE NOCASE
              AND fact = ? COLLATE NOCASE
            LIMIT 1
            """,
            (subject, new_fact)
        ).fetchone()

        if not existing:
            db.execute(
                """
                INSERT INTO memories
                (subject, fact, source, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    subject,
                    new_fact,
                    "user_confirmed",
                    datetime.now(timezone.utc).isoformat()
                )
            )

    return f"Corrected {len(rows)} matching memory entries."


if __name__ == "__main__":
    print("MOON MAN MEMORY SYSTEM")
    print("Database:", DB_PATH)

    print("\nStored Gumbling Machine memories:")
    for fact in recall("Gumbling Machine"):
        print("-", fact)
