# Learning — getting up to speed

Short, practical notes on the technologies this project uses: what each one is,
why it is here, and where it lives in the code. Written for someone who knows
some programming but is meeting these tools for the first time.

Start anywhere — each section is self-contained. Domain vocabulary (Reminder,
Device, due_local, …) is defined in [`../glossary.md`](../glossary.md) and is not
repeated here.

## Deep dives

- [push-notifications.md](push-notifications.md) — Web Push, VAPID and how a
  notification travels from the server to a closed phone (with videos)

## The stack, one section each

### FastAPI — the web framework
The Python library that turns functions into HTTP endpoints. We use it because
it is small, typed, and generates interactive API docs for free at `/docs` while
the server runs. **Where:** every `@app.get(...)` / `@app.post(...)` in
[`../../app/main.py`](../../app/main.py).

### Pydantic — request/response validation
The models (`LoginIn`, `ReminderIn`, `ReminderPatch`) that describe what a
request body must look like. FastAPI rejects a malformed request with a 422
before our code runs — validation as a type declaration instead of manual
`if` checks. **Where:** the `class … (BaseModel)` blocks in `app/main.py`.

### SQLite + WAL — the database
A database that is a single file, needing no server process — perfect for a solo
app on a small VPS. WAL (write-ahead logging) mode lets a reader and a writer work
at the same time, which matters because the API threads and the scheduler thread
both touch the database. **Where:** [`../../app/db.py`](../../app/db.py) — one
connection per operation, never shared.

### Threading + a hand-rolled scheduler
Instead of cron, Celery or a queue, a single daemon thread wakes up every 20
seconds and fires whatever is due. This is the standard-library `threading`
module doing a simple job — deliberately unglamorous. **Where:**
[`../../app/scheduler.py`](../../app/scheduler.py) (`start`, `run_loop`, `tick`).

### Timezones done properly (`zoneinfo` / IANA)
The app stores two times for every reminder: `due_local` (the wall-clock time you
typed, e.g. `21:30`) and `due_utc` (the exact instant). Conversion happens via
`zoneinfo` and IANA zone names like `Asia/Singapore`, so "daily at 21:30" keeps
meaning 21:30 across daylight-saving changes. **Where:** `_local_to_utc()` in
`app/main.py`, `next_occurrence()` in `app/scheduler.py`.

### Service Worker + PWA — the installable phone app
A service worker is a script the browser runs in the background, separate from
the page. It is what lets the site be installed to the home screen and receives
push notifications when the app is closed. **Where:** `static/sw.js`,
`static/manifest.json` (installability), registration in `static/app.js`.

### Web Push + VAPID — notifications to a closed phone
The standard that lets our server hand a notification to Google/Apple's push
service, which wakes the phone. VAPID is the part that proves the push came from
us. **Where:** [`../../app/push.py`](../../app/push.py). **Deep dive:**
[push-notifications.md](push-notifications.md).

### pywebpush + cryptography — the plumbing under push
`pywebpush` builds and signs the push request; `cryptography` generates the VAPID
keypair. Both are hidden behind two functions in `app/push.py`, so you rarely
touch them directly.

### Vanilla JavaScript — no framework, no build step
The frontend is plain HTML/CSS/JS served as static files. No React, no bundler,
no `node_modules` — you can read the whole client in one sitting, which is the
point for a project this size. **Where:** `static/index.html`, `static/app.js`,
`static/style.css`.

### Caddy — HTTPS and the reverse proxy
Sits in front of the Python app, terminates TLS, and obtains/renews Let's Encrypt
certificates automatically. Web Push requires HTTPS, so this piece is not
optional. **Where:** `Caddyfile`, and the `caddy` service in `docker-compose.yml`.

### Docker Compose — packaging and running it
Describes the two containers (app + Caddy), their networking and volumes, so the
VPS deploy is `docker compose up -d --build` rather than a list of manual steps.
**Where:** `Dockerfile`, `docker-compose.yml`.

### DuckDNS — a stable name without buying a domain
A free dynamic-DNS service. Push subscriptions are tied to an HTTPS *origin*, so
the app needs a stable hostname; `yourname.duckdns.org` provides one, and Caddy
can get a certificate for it. **Where:** the deploy section of the main
[README](../../README.md).

## Working conventions

Docstrings, commit style, the branch/PR workflow and the test command live in
[`../../AGENTS.md`](../../AGENTS.md).
