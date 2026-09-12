"""SQLite persistence layer. One connection per operation (WAL mode) so the
API threads and the scheduler thread never share a connection.

Vocabulary: see docs/glossary.md — column names are the canonical terms
(`due_local`, `due_utc`, `timezone`), functions use the CRUD verbs
(create/get/list/update/delete/upsert)."""
import os
import sqlite3
import threading
from datetime import UTC, datetime

DATA_DIR = os.environ.get(
    "DATA_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"),
)
DB_PATH = os.path.join(DATA_DIR, "remindly.db")
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id    TEXT PRIMARY KEY,
    timezone   TEXT NOT NULL DEFAULT 'UTC',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reminders (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    TEXT NOT NULL,          -- multi-user ready: everything is scoped by user
    title      TEXT NOT NULL,
    note       TEXT NOT NULL DEFAULT '',
    due_local  TEXT,                   -- naive local wall time of first due (repeat base)
    repeat     TEXT NOT NULL DEFAULT '',  -- '' | 'daily' | 'weekly' | 'monthly'
    timezone   TEXT NOT NULL DEFAULT 'UTC',
    due_utc    TEXT NOT NULL,          -- next fire time, UTC ISO
    status     TEXT NOT NULL DEFAULT 'pending',  -- pending | done
    created_at TEXT NOT NULL,
    done_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(status, due_utc);
CREATE TABLE IF NOT EXISTS devices (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT NOT NULL,
    endpoint    TEXT UNIQUE NOT NULL,
    p256dh      TEXT NOT NULL,
    auth_secret TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
"""


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


def connect():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    with _lock:
        with connect() as c:
            c.executescript(SCHEMA)


# ---------------------------------------------------------------- users
def upsert_user(user_id: str, timezone: str = "UTC") -> str:
    """Create the user if missing; update their timezone if provided.
    Returns the effective timezone."""
    with _lock:
        with connect() as c:
            c.execute(
                "INSERT OR IGNORE INTO users(user_id, timezone, created_at) VALUES(?,?,?)",
                (user_id, timezone, utcnow()),
            )
            row = c.execute("SELECT timezone FROM users WHERE user_id=?", (user_id,)).fetchone()
            if timezone and timezone != row["timezone"]:
                c.execute("UPDATE users SET timezone=? WHERE user_id=?", (timezone, user_id))
                row = c.execute("SELECT timezone FROM users WHERE user_id=?", (user_id,)).fetchone()
            return row["timezone"]


def get_user_timezone(user_id: str):
    with connect() as c:
        row = c.execute("SELECT timezone FROM users WHERE user_id=?", (user_id,)).fetchone()
    return row["timezone"] if row else None


# ------------------------------------------------------------- reminders
def row_to_dict(r) -> dict:
    return {k: r[k] for k in r.keys()}


def create_reminder(user_id, title, note, due_local, repeat, timezone, due_utc) -> dict:
    with _lock:
        with connect() as c:
            cur = c.execute(
                "INSERT INTO reminders(user_id,title,note,due_local,repeat,timezone,due_utc,status,created_at)"
                " VALUES(?,?,?,?,?,?,?, 'pending', ?)",
                (user_id, title, note, due_local, repeat, timezone, due_utc, utcnow()),
            )
            r = c.execute("SELECT * FROM reminders WHERE id=?", (cur.lastrowid,)).fetchone()
            return row_to_dict(r)


def get_reminder(rid: int, user_id: str = None):
    with connect() as c:
        if user_id:
            r = c.execute("SELECT * FROM reminders WHERE id=? AND user_id=?", (rid, user_id)).fetchone()
        else:
            r = c.execute("SELECT * FROM reminders WHERE id=?", (rid,)).fetchone()
        return row_to_dict(r) if r else None


def list_reminders(user_id: str, status: str = None):
    with connect() as c:
        if status == "done":
            rows = c.execute(
                "SELECT * FROM reminders WHERE user_id=? AND status='done' ORDER BY done_at DESC",
                (user_id,),
            ).fetchall()
        elif status == "pending":
            rows = c.execute(
                "SELECT * FROM reminders WHERE user_id=? AND status='pending' ORDER BY due_utc ASC",
                (user_id,),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM reminders WHERE user_id=? ORDER BY (status='pending') DESC, due_utc ASC",
                (user_id,),
            ).fetchall()
        return [row_to_dict(r) for r in rows]


def update_reminder(rid: int, user_id: str, fields: dict):
    if not fields:
        return get_reminder(rid, user_id)
    sets = ", ".join(f"{k}=?" for k in fields)
    with _lock:
        with connect() as c:
            c.execute(
                f"UPDATE reminders SET {sets} WHERE id=? AND user_id=?",
                (*fields.values(), rid, user_id),
            )
            r = c.execute("SELECT * FROM reminders WHERE id=?", (rid,)).fetchone()
            return row_to_dict(r) if r else None


def delete_reminder(rid: int, user_id: str) -> bool:
    with _lock:
        with connect() as c:
            cur = c.execute("DELETE FROM reminders WHERE id=? AND user_id=?", (rid, user_id))
            return cur.rowcount > 0


def list_due_reminders(now_iso: str = None):
    """Reminders that are pending and whose due_utc has passed (fire-late is fine)."""
    now_iso = now_iso or utcnow()
    with connect() as c:
        rows = c.execute(
            "SELECT * FROM reminders WHERE status='pending' AND due_utc<=? ORDER BY due_utc",
            (now_iso,),
        ).fetchall()
        return [row_to_dict(r) for r in rows]


# --------------------------------------------------------------- devices
def upsert_device(user_id, endpoint, p256dh, auth_secret):
    """Register (or re-register) a device for push delivery."""
    with _lock:
        with connect() as c:
            c.execute(
                "INSERT INTO devices(user_id,endpoint,p256dh,auth_secret,created_at) VALUES(?,?,?,?,?)"
                " ON CONFLICT(endpoint) DO UPDATE SET p256dh=excluded.p256dh,"
                " auth_secret=excluded.auth_secret, user_id=excluded.user_id",
                (user_id, endpoint, p256dh, auth_secret, utcnow()),
            )


def delete_device(endpoint: str):
    with _lock:
        with connect() as c:
            c.execute("DELETE FROM devices WHERE endpoint=?", (endpoint,))


def list_devices(user_id: str):
    with connect() as c:
        rows = c.execute("SELECT * FROM devices WHERE user_id=?", (user_id,)).fetchall()
        return [row_to_dict(r) for r in rows]
