"""Background scheduler: every N seconds fire every due reminder.

Fire semantics:
- push a notification to all registered devices of the user
- repeating reminder  -> advance due_utc to the next occurrence
- one-shot reminder   -> mark done
If the process was down when a reminder came due, it fires late on the next
tick ("fire-late" — better than silently dropping it).

Vocabulary: see docs/glossary.md — a *reminder* that is *due* gets *fired*:
devices are *notified* and a repeating reminder advances to its next
*occurrence* (computed from its *due_local* base time in the user's
*timezone*)."""
import calendar
import logging
import threading
import time
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from . import db
from . import push

log = logging.getLogger("scheduler")


def next_occurrence(due_local: str, repeat: str, timezone: str, now_utc: datetime = None) -> str:
    """Advance a repeat rule to the next occurrence strictly after now.

    Returns UTC ISO string, or None if the rule cannot be advanced.
    due_local is the naive wall-clock time of the first occurrence and is the
    fixed base of the repeat rule; only due_utc ever moves forward."""
    now_utc = now_utc or datetime.now(UTC)
    zone = ZoneInfo(timezone)
    first = datetime.fromisoformat(due_local)
    now_local = now_utc.astimezone(zone).replace(tzinfo=None)  # naive local now

    if repeat == "daily":
        n = 1
        while first + timedelta(days=n) <= now_local and n < 4000:
            n += 1
        return (first + timedelta(days=n)).replace(tzinfo=zone).astimezone(UTC).isoformat()

    if repeat == "weekly":
        n = 1
        while first + timedelta(weeks=n) <= now_local and n < 1000:
            n += 1
        return (first + timedelta(weeks=n)).replace(tzinfo=zone).astimezone(UTC).isoformat()

    if repeat == "monthly":
        y, m = first.year, first.month
        for _ in range(600):
            m += 1
            if m > 12:
                m, y = 1, y + 1
            day = min(first.day, calendar.monthrange(y, m)[1])  # clamp Jan 31 -> Feb 28
            cand = datetime(y, m, day, first.hour, first.minute)
            if cand > now_local:
                return cand.replace(tzinfo=zone).astimezone(UTC).isoformat()
    return None


def fire_reminder(rem: dict):
    """A due reminder has arrived: notify the user's devices, then advance a
    repeating reminder to its next occurrence or mark a one-shot done."""
    devices = db.list_devices(rem["user_id"])
    if devices:
        notification = {
            "title": rem["title"],
            "body": rem["note"] or "It's time!",
            "tag": f"rem-{rem['id']}",
            "data": {"url": "/", "id": rem["id"]},
        }
        push.notify_devices(devices, notification)

    if rem.get("repeat") and rem.get("due_local"):
        nxt = next_occurrence(rem["due_local"], rem["repeat"], rem["timezone"])
        if nxt:
            db.update_reminder(rem["id"], rem["user_id"], {"due_utc": nxt})
            return
    db.update_reminder(rem["id"], rem["user_id"], {"status": "done", "done_at": db.utcnow()})


def tick():
    """One scheduler pass: fire every due reminder (failures are logged, not fatal)."""
    for rem in db.list_due_reminders():
        try:
            fire_reminder(rem)
        except Exception:
            log.exception("fire failed for reminder %s", rem["id"])


def run_loop(interval: float = 20, stop: threading.Event = None):
    """Call tick() every interval seconds until the stop event is set."""
    while not (stop and stop.is_set()):
        try:
            tick()
        except Exception:
            log.exception("scheduler tick error")
        time.sleep(interval)


def start(interval: float = 20) -> threading.Event:
    """Start the scheduler as a daemon thread; returns the event that stops it."""
    stop = threading.Event()
    t = threading.Thread(target=run_loop, args=(interval, stop), daemon=True, name="reminder-scheduler")
    t.start()
    return stop
