"""Remindly — FastAPI app. Single-user password auth for now; schema and user_id
scoping are already multi-user ready (swap auth for real accounts later).

Vocabulary: see docs/glossary.md. Handlers are named <verb>_<resource> with the
same verb the db layer uses (create/update/delete/list/get), so the API and the
data layer speak one language.

Style: every function carries a docstring — one line saying what it does, plus
a second line only where the behaviour isn't obvious from the signature."""
import hashlib
import hmac
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, Optional
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db
from . import push
from . import scheduler

APP_PASSWORD = os.environ.get("APP_PASSWORD", "dev-password-change-me")
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
LOCAL_USER = "local"  # single hard-coded user until real accounts exist


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Startup/shutdown hook: create the tables, ensure the user, start the scheduler."""
    db.init_db()
    db.upsert_user(LOCAL_USER)
    stop = scheduler.start(interval=20)
    yield
    stop.set()


app = FastAPI(title="Remindly", version="0.1.0", lifespan=lifespan)

# ---------------------------------------------------------------- auth
def _expected_token() -> str:
    """The bearer token clients must present: sha256 of APP_PASSWORD."""
    return hashlib.sha256(APP_PASSWORD.encode()).hexdigest()


def require_auth(authorization: str = Header(default="")):
    """FastAPI dependency: validate the bearer token, or raise 401.
    Returns the user id the request acts as."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    given = authorization[7:].strip()
    if not hmac.compare_digest(given, _expected_token()):
        raise HTTPException(401, "invalid token")
    return LOCAL_USER


class LoginIn(BaseModel):
    password: str
    timezone: str = "UTC"


@app.post("/api/login")
def login(body: LoginIn):
    """Exchange the app password for a token; records the client's timezone."""
    if not hmac.compare_digest(body.password, APP_PASSWORD):
        raise HTTPException(401, "wrong password")
    timezone = db.upsert_user(LOCAL_USER, body.timezone)
    return {"token": _expected_token(), "timezone": timezone}


@app.get("/api/me")
def get_me(user=Depends(require_auth)):
    """Return the current user id and their timezone."""
    timezone = db.get_user_timezone(user) or db.upsert_user(user)
    return {"user_id": user, "timezone": timezone}


class MeIn(BaseModel):
    timezone: str


@app.put("/api/me")
def update_me(body: MeIn, user=Depends(require_auth)):
    """Set the user's timezone and return it."""
    timezone = db.upsert_user(user, body.timezone)
    return {"timezone": timezone}


# ------------------------------------------------------------- reminders
class ReminderIn(BaseModel):
    title: str
    due_local: str  # naive local wall time, e.g. 2026-09-06T21:30 (user's clock)
    note: str = ""
    repeat: Literal["", "daily", "weekly", "monthly"] = ""
    timezone: str = "UTC"


def _local_to_utc(due_local: str, timezone: str) -> str:
    """Convert a naive local wall-clock time in the given timezone to a UTC
    ISO string. Raises 422 on an unparseable time or unknown timezone."""
    try:
        naive = datetime.fromisoformat(due_local)
    except ValueError:
        raise HTTPException(422, "due_local must be ISO like 2026-09-06T21:30")
    try:
        tzinfo = ZoneInfo(timezone)
    except Exception:
        raise HTTPException(422, f"unknown timezone: {timezone}")
    return naive.replace(tzinfo=tzinfo).astimezone(UTC).isoformat()


@app.get("/api/reminders")
def list_reminders(status: Literal["pending", "done", "all"] = "all", user=Depends(require_auth)):
    """List the user's reminders, filtered by status (default: all)."""
    return {"reminders": db.list_reminders(user, None if status == "all" else status)}


@app.post("/api/reminders")
def create_reminder(body: ReminderIn, user=Depends(require_auth)):
    """Create a reminder, converting due_local from the user's timezone to due_utc."""
    title = body.title.strip()
    if not title:
        raise HTTPException(422, "title required")
    due_utc = _local_to_utc(body.due_local, body.timezone)
    r = db.create_reminder(
        user, title, body.note.strip(), body.due_local, body.repeat, body.timezone, due_utc
    )
    return {"reminder": r}


class ReminderPatch(BaseModel):
    title: Optional[str] = None
    note: Optional[str] = None
    due_local: Optional[str] = None
    repeat: Optional[Literal["", "daily", "weekly", "monthly"]] = None
    timezone: Optional[str] = None
    status: Optional[Literal["pending", "done"]] = None


@app.patch("/api/reminders/{rid}")
def update_reminder(rid: int, body: ReminderPatch, user=Depends(require_auth)):
    """Partially update a reminder; recomputes due_utc when due_local changes."""
    fields = {}
    for f in ("title", "note", "repeat", "timezone", "status"):
        v = getattr(body, f)
        if v is not None:
            fields[f] = v
    if body.due_local is not None:
        timezone = body.timezone or (db.get_reminder(rid, user) or {}).get("timezone") or "UTC"
        fields["due_utc"] = _local_to_utc(body.due_local, timezone)
        fields["due_local"] = body.due_local
        if body.timezone is not None:
            fields["timezone"] = body.timezone
    if not fields:
        raise HTTPException(422, "nothing to update")
    r = db.update_reminder(rid, user, fields)
    if not r:
        raise HTTPException(404, "not found")
    return {"reminder": r}


@app.delete("/api/reminders/{rid}")
def delete_reminder(rid: int, user=Depends(require_auth)):
    """Delete a reminder; 404 if this user has no such reminder."""
    if not db.delete_reminder(rid, user):
        raise HTTPException(404, "not found")
    return {"ok": True}


class SnoozeIn(BaseModel):
    minutes: int = 10


@app.post("/api/reminders/{rid}/snooze")
def snooze_reminder(rid: int, body: SnoozeIn, user=Depends(require_auth)):
    """Push a pending reminder's due_utc N minutes into the future.
    Only due_utc moves — due_local and repeat stay as they were."""
    r = db.get_reminder(rid, user)
    if not r:
        raise HTTPException(404, "not found")
    if r["status"] != "pending":
        raise HTTPException(409, "only pending reminders can be snoozed")
    if body.minutes < 1:
        raise HTTPException(422, "minutes must be >= 1")
    new_due = datetime.now(UTC) + timedelta(minutes=body.minutes)
    r = db.update_reminder(rid, user, {"due_utc": new_due.isoformat()})
    return {"reminder": r}


# -------------------------------------------------------------- web push
@app.get("/api/push/vapid-public-key")
def get_vapid_public_key(user=Depends(require_auth)):
    """Return the VAPID public key the PWA needs to create a push subscription."""
    return {"key": push.vapid_public_key()}


class SubscribeIn(BaseModel):
    endpoint: str
    keys: dict


@app.post("/api/push/subscribe")
def subscribe_device(body: SubscribeIn, user=Depends(require_auth)):
    """Register (or refresh) one device's push subscription."""
    db.upsert_device(user, body.endpoint, body.keys.get("p256dh", ""), body.keys.get("auth", ""))
    return {"ok": True}


class UnsubscribeIn(BaseModel):
    endpoint: str


@app.post("/api/push/unsubscribe")
def unsubscribe_device(body: UnsubscribeIn, user=Depends(require_auth)):
    """Remove a device's push subscription by its endpoint."""
    db.delete_device(body.endpoint)
    return {"ok": True}


class TestIn(BaseModel):
    title: str = "Remindly test"


@app.post("/api/push/test")
def send_test_notification(body: TestIn, user=Depends(require_auth)):
    """Send a test notification to every registered device of the user."""
    devices = db.list_devices(user)
    push.notify_devices(
        devices,
        {"title": body.title, "body": "Push is working ✔", "tag": "remindly-test", "data": {"url": "/"}},
    )
    return {"sent_to": len(devices)}


@app.get("/health")
def health():
    """Liveness probe used by Docker/Caddy checks; no auth."""
    return {"ok": True}


# Serve the PWA (must be mounted last so /api routes win)
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
