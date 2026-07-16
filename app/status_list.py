"""
Manual override list: roll numbers that are frozen or dropped out.

Backed by SQLite for simplicity. On Railway, mount a volume at DB_PATH's
directory (or switch to Postgres, same as your other projects) so this
survives redeploys - by default Railway's filesystem is ephemeral.
"""
import sqlite3
import csv
import io
import os
from contextlib import contextmanager

DB_PATH = os.environ.get("STATUS_DB_PATH", "app/data/status.db")


def _ensure_dir():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)


@contextmanager
def _conn():
    _ensure_dir()
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with _conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS status_overrides (
                roll_number TEXT PRIMARY KEY,
                status TEXT NOT NULL,   -- 'frozen' or 'dropped'
                note TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)


def normalize_roll(roll_number: str) -> str:
    return roll_number.strip().upper().replace(" ", "")


def check_roll(roll_number: str):
    """Returns the override row (status, note) if this roll number is frozen/dropped, else None."""
    roll = normalize_roll(roll_number)
    with _conn() as conn:
        cur = conn.execute(
            "SELECT status, note FROM status_overrides WHERE roll_number = ?",
            (roll,),
        )
        row = cur.fetchone()
    if row:
        return {"status": row[0], "note": row[1]}
    return None


def upsert_roll(roll_number: str, status: str, note: str = ""):
    roll = normalize_roll(roll_number)
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO status_overrides (roll_number, status, note)
            VALUES (?, ?, ?)
            ON CONFLICT(roll_number) DO UPDATE SET
                status = excluded.status,
                note = excluded.note,
                updated_at = CURRENT_TIMESTAMP
            """,
            (roll, status, note),
        )


def delete_roll(roll_number: str):
    roll = normalize_roll(roll_number)
    with _conn() as conn:
        conn.execute("DELETE FROM status_overrides WHERE roll_number = ?", (roll,))


def list_all():
    with _conn() as conn:
        cur = conn.execute(
            "SELECT roll_number, status, note, updated_at FROM status_overrides ORDER BY updated_at DESC"
        )
        rows = cur.fetchall()
    return [
        {"roll_number": r[0], "status": r[1], "note": r[2], "updated_at": r[3]}
        for r in rows
    ]


def import_csv(file_bytes: bytes):
    """
    Bulk import from a CSV with columns: roll_number, status[, note]
    status must be 'frozen' or 'dropped'. Existing entries are updated.
    Returns (count_imported, errors).
    """
    text = file_bytes.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))

    required = {"roll_number", "status"}
    if not reader.fieldnames or not required.issubset(
        {f.strip().lower() for f in reader.fieldnames}
    ):
        raise ValueError(
            f"CSV must have columns: roll_number, status (optional: note). "
            f"Found: {reader.fieldnames}"
        )

    count = 0
    errors = []
    for i, row in enumerate(reader, start=2):  # row 1 is header
        row = {k.strip().lower(): (v or "").strip() for k, v in row.items()}
        roll = row.get("roll_number", "")
        status = row.get("status", "").lower()
        note = row.get("note", "")

        if not roll:
            errors.append(f"Row {i}: missing roll_number")
            continue
        if status not in ("frozen", "dropped"):
            errors.append(f"Row {i}: status must be 'frozen' or 'dropped', got '{status}'")
            continue

        upsert_roll(roll, status, note)
        count += 1

    return count, errors
