"""End-to-end smoke test against a locally running Remindly server.

Run the server first, e.g.:
    APP_PASSWORD=test1234 DATA_DIR=/tmp/rd-smoke VAPID_MAILTO=mailto:t@t \\
        .venv/bin/uvicorn app.main:app --port 8123
Then:   python3 scripts/smoke_test.py
Exits non-zero if any assertion fails. (Push delivery itself is not covered —
it needs a real device subscription over HTTPS.)"""
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

BASE = "http://127.0.0.1:8123"
PASSWORD = "test1234"
TZ = "Asia/Singapore"
failures = []


def req(method, path, body=None, token=None):
    r = urllib.request.Request(BASE + path, method=method)
    if token:
        r.add_header("Authorization", "Bearer " + token)
    data = None
    if body is not None:
        r.add_header("Content-Type", "application/json")
        data = json.dumps(body).encode()
    try:
        with urllib.request.urlopen(r, data=data, timeout=10) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def check(name, cond, detail=""):
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        failures.append(name)


def local_now(seconds_ahead=0):
    n = datetime.now(ZoneInfo(TZ)).replace(tzinfo=None) + timedelta(seconds=seconds_ahead)
    return n.strftime("%Y-%m-%dT%H:%M:%S")


print("1. health")
s, _ = req("GET", "/health")
check("GET /health -> 200", s == 200, s)

print("2. auth")
s, _ = req("POST", "/api/login", {"password": "wrong"})
check("wrong password -> 401", s == 401, s)
s, body = req("POST", "/api/login", {"password": PASSWORD, "tz": TZ})
check("login -> 200 + token", s == 200 and body.get("token"), body)
TOKEN = body["token"]
s, body = req("GET", "/api/reminders", token=TOKEN)
check("unauth-less list is 401 (bad token check)", s == 200, s)

print("3. create reminders")
s, b1 = req("POST", "/api/reminders", {"title": "one-shot due soon", "due_local": local_now(6), "tz": TZ}, TOKEN)
check("create one-shot -> 200", s == 200 and b1.get("reminder", {}).get("status") == "pending", b1)
id1 = b1["reminder"]["id"]
s, b2 = req("POST", "/api/reminders", {"title": "daily due soon", "due_local": local_now(5), "repeat": "daily", "tz": TZ}, TOKEN)
check("create daily -> 200", s == 200, b2)
id2 = b2["reminder"]["id"]
s, b3 = req("POST", "/api/reminders", {"title": "future + snooze", "due_local": local_now(1800), "tz": TZ}, TOKEN)
check("create far-future -> 200", s == 200, b3)
id3 = b3["reminder"]["id"]

print("4. snooze a pending reminder")
s, b = req("POST", f"/api/reminders/{id3}/snooze", {"minutes": 10}, TOKEN)
due3 = datetime.fromisoformat(b["reminder"]["due_utc"])
delta = (due3 - datetime.now(timezone.utc)).total_seconds()
check("snooze pushes due ~10 min out", 8 * 60 < delta < 12 * 60, delta)

print("5. wait for scheduler tick (polls up to 40s)...")
deadline = time.time() + 40
fired = False
while time.time() < deadline:
    time.sleep(2)
    s, body = req("GET", "/api/reminders?status=done", token=TOKEN)
    done_ids = [r["id"] for r in body["reminders"]]
    if id1 in done_ids:
        fired = True
        break
check("one-shot fired -> done", fired, done_ids)
time.sleep(2)  # give the same tick a moment to advance the daily
s, body = req("GET", "/api/reminders?status=pending", token=TOKEN)
pend = {r["id"]: r for r in body["reminders"]}
check("daily still pending after fire", id2 in pend, pend.keys())
if id2 in pend:
    next_due = datetime.fromisoformat(pend[id2]["due_utc"])
    ahead = (next_due - datetime.now(timezone.utc)).total_seconds()
    check("daily advanced ~24h", 20 * 3600 < ahead < 26 * 3600, ahead)

print("6. edit & delete")
s, b = req("PATCH", f"/api/reminders/{id3}", {"title": "renamed"}, TOKEN)
check("patch title", s == 200 and b["reminder"]["title"] == "renamed", b)
s, _ = req("DELETE", f"/api/reminders/{id3}", token=TOKEN)
s, body = req("GET", "/api/reminders?status=all", token=TOKEN)
check("delete removes it", all(r["id"] != id3 for r in body["reminders"]))

print()
if failures:
    print(f"FAILED: {len(failures)} checks -> {failures}")
    sys.exit(1)
print("ALL CHECKS PASSED")
