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


def _add_months(anchor: datetime, months: int) -> datetime:
    """Return anchor shifted by N calendar months, clamping the day to the target
    month's length (31 Jan + 1 month -> 28/29 Feb). The day always comes from the
    original anchor, so a 31st anchor stays a "31st" rule."""
    y, m = anchor.year, anchor.month - 1 + months
    y, m = y + m // 12, m % 12 + 1
    return datetime(y, m, min(anchor.day, calendar.monthrange(y, m)[1]), anchor.hour, anchor.minute)


def next_occurrence(due_local: str, repeat: str, timezone: str, now_utc: datetime = None) -> str:
    """Advance a repeat rule to the next occurrence strictly after now.

    Returns UTC ISO string, or None if the rule cannot be advanced.
    due_local is the naive wall-clock time of the first occurrence and is the
    fixed base of the repeat rule; only due_utc ever moves forward."""
    now_utc = now_utc or datetime.now(UTC)
    zone = ZoneInfo(timezone)
    first = datetime.fromisoformat(due_local)
    now_local = now_utc.astimezone(zone).replace(tzinfo=None)  # naive local now

    # Fixed-length periods (days, weeks): one calculation instead of a loop.
    # `//` between timedeltas is floor division — how many whole periods fit
    # between the anchor and now — so adding 1 gives the first occurrence
    # strictly after now. max(1, …) keeps the rule that the occurrence which
    # just fired is never returned again (or it would re-fire every tick).
    if repeat in ("daily", "weekly"):
        period = timedelta(days=1) if repeat == "daily" else timedelta(weeks=1)
        n = max(1, (now_local - first) // period + 1)
        return (first + n * period).replace(tzinfo=zone).astimezone(UTC).isoformat()

    # Months are not a fixed length, so count calendar months instead of looping.
    # The anchor stays the base for the day clamp, and at most two candidates
    # need checking: the first may already be <= now when today is later in the
    # month than the anchor's day, and then the following month is the answer.
    # TODO: revisit this explanation — ask the agent for the walkthrough of why
    # two candidate months are enough (and why the old 600-iteration loop could
    # only ever agree with this or give up).
    if repeat == "monthly":
        months = max(1, (now_local.year - first.year) * 12 + (now_local.month - first.month))
        for k in (months, months + 1):
            cand = _add_months(first, k)
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
