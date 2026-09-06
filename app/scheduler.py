"""Background scheduler: every N seconds fire every due reminder.

Fire semantics:
- push a notification to all registered devices of the user
- repeating reminder  -> advance due_utc to the next occurrence
- one-shot reminder   -> mark done
If the process was down when a reminder came due, it fires late on the next
tick ("fire-late" — better than silently dropping it)."""
import calendar
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import db
from . import push

log = logging.getLogger("scheduler")


def next_occurrence(anchor_local: str, repeat: str, tz_name: str, now_utc: datetime = None) -> str:
    """Advance a repeat rule to the next occurrence strictly after now.

    Returns UTC ISO string, or None if the rule cannot be advanced.
    anchor_local is the naive wall-clock time of the first occurrence."""
    now_utc = now_utc or datetime.now(timezone.utc)
    tz = ZoneInfo(tz_name)
    anchor = datetime.fromisoformat(anchor_local)
    now_loc = now_utc.astimezone(tz).replace(tzinfo=None)  # naive local now

    if repeat == "daily":
        n = 1
        while anchor + timedelta(days=n) <= now_loc and n < 4000:
            n += 1
        return (anchor + timedelta(days=n)).replace(tzinfo=tz).astimezone(timezone.utc).isoformat()

    if repeat == "weekly":
        n = 1
        while anchor + timedelta(weeks=n) <= now_loc and n < 1000:
            n += 1
        return (anchor + timedelta(weeks=n)).replace(tzinfo=tz).astimezone(timezone.utc).isoformat()

    if repeat == "monthly":
        y, m = anchor.year, anchor.month
        for _ in range(600):
            m += 1
            if m > 12:
                m, y = 1, y + 1
            day = min(anchor.day, calendar.monthrange(y, m)[1])  # clamp Jan 31 -> Feb 28
            cand = datetime(y, m, day, anchor.hour, anchor.minute)
            if cand > now_loc:
                return cand.replace(tzinfo=tz).astimezone(timezone.utc).isoformat()
    return None


def _fire(rem: dict):
    devices = db.list_devices(rem["user_id"])
    if devices:
        payload = {
            "title": rem["title"],
            "body": rem["note"] or "It's time!",
            "tag": f"rem-{rem['id']}",
            "data": {"url": "/", "id": rem["id"]},
        }
        push.send_all(devices, payload)

    if rem.get("repeat") and rem.get("anchor"):
        nxt = next_occurrence(rem["anchor"], rem["repeat"], rem["tz"])
        if nxt:
            db.update_reminder(rem["id"], rem["user_id"], {"due_utc": nxt})
            return
    db.update_reminder(rem["id"], rem["user_id"], {"status": "done", "done_at": db.utcnow()})


def tick():
    for rem in db.due_pending():
        try:
            _fire(rem)
        except Exception:
            log.exception("fire failed for reminder %s", rem["id"])


def run_loop(interval: float = 20, stop: threading.Event = None):
    while not (stop and stop.is_set()):
        try:
            tick()
        except Exception:
            log.exception("scheduler tick error")
        time.sleep(interval)


def start(interval: float = 20) -> threading.Event:
    stop = threading.Event()
    t = threading.Thread(target=run_loop, args=(interval, stop), daemon=True, name="reminder-scheduler")
    t.start()
    return stop
