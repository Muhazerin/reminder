# Remindly

A mobile-first reminder PWA. You add reminders on your phone; a server on your VPS
fires them and delivers a **Web Push notification** — even when the browser is closed.
Single-user for now, but the data model and API are scoped by `user_id` so real
accounts can be bolted on later.

## How it works

```
[phone browser / PWA] --HTTPS--> [Caddy] --> [FastAPI app]
                                        |         |
                                   auto-TLS   sqlite (reminders, push subs)
                                                 |
                                     scheduler thread: every 20s,
                                     fire due reminders -> Web Push to phone
```

- One-shot reminders become `done` when they fire; repeating ones advance to the
  next occurrence (daily / weekly / monthly, computed in *your* timezone — DST safe).
- If the server was down at fire time, the reminder fires late on the next tick.
- Push subscriptions live in SQLite; dead ones (404/410 from the push service)
  are pruned automatically. VAPID keys are generated on first run in `data/`.

## Stack

FastAPI + SQLite + stdlib `threading` scheduler (backend) · vanilla JS PWA
(frontend, no framework) · Caddy (reverse proxy + automatic HTTPS) · Docker Compose.

## Project layout

```
app/            FastAPI backend (db, scheduler, web-push, routes)
static/         PWA: index.html, app.js, style.css, sw.js, manifest, icons
scripts/        gen_icons.py (regenerate PWA icons), smoke_test.py (API tests)
docs/           glossary.md — the project's vocabulary (Ubiquitous Language)
Dockerfile, docker-compose.yml, Caddyfile   deployment
```

## Run locally (dev)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
python3 scripts/gen_icons.py
APP_PASSWORD=devpass .venv/bin/uvicorn app.main:app --port 8000
# open http://localhost:8000  (sign in with: devpass)
```

Smoke test (needs the server running on port 8123):

```bash
APP_PASSWORD=test1234 DATA_DIR=/tmp/rd-smoke .venv/bin/uvicorn app.main:app --port 8123 &
python3 scripts/smoke_test.py
```

> Local push needs HTTPS + a phone; verify push only after deploying.

## Deploy on the VPS (no domain needed — free DuckDNS + auto-HTTPS)

Reminders are pushed through Google/Apple's push services, which **require HTTPS**
and a **stable URL** (a push subscription is tied to the origin). DuckDNS gives you a
free `yourname.duckdns.org` subdomain; Caddy gets a free Let's Encrypt certificate
for it automatically.

1. **Create the DuckDNS entry**
   - Go to https://www.duckdns.org and sign in (free, with any account).
   - Under *domains* create e.g. `remindly` → your host becomes `remindly.duckdns.org`.
   - Set its IP to your VPS's public IP: `curl ifconfig.me` (run on the VPS).
   - DuckDNS gives you a *token* — keep it; you need it for step 3.

2. **Open ports 80 and 443** on the VPS (firewall / cloud security group) — Caddy
   needs them for the Let's Encrypt check and for HTTPS traffic.

3. **Keep the IP updated** (VPS IPs can change). On the VPS host add a cron job:
   ```bash
   crontab -e
   # add:
   */5 * * * * curl -s "https://www.duckdns.org/update?domains=remindly&token=YOUR_DUCK_TOKEN&ip=" >/dev/null
   ```

4. **Get the code on the VPS** and configure it:
   ```bash
   git clone https://Muhazerin:YOUR_GITHUB_TOKEN@github.com/Muhazerin/reminder.git
   cd reminder
   cp .env.example .env
   nano .env      # APP_PASSWORD = a strong password, DOMAIN = remindly.duckdns.org
   ```

5. **Start it:**
   ```bash
   docker compose up -d --build
   docker compose ps          # wait until both containers are healthy
   ```

6. **On your phone**
   - Visit `https://remindly.duckdns.org` and sign in with your app password.
   - **Android (Chrome):** tap Install in the menu, then allow notifications.
   - **iPhone (Safari):** Share → *Add to Home Screen*, open the app from your home
     screen, then allow notifications (iOS only pushes to installed PWAs).
   - Hit **Test ping** in the app — a notification should arrive.

7. **Done.** Add a reminder a minute out, leave the page, and watch it arrive.

## API (all JSON, `Authorization: Bearer <token>` except login)

| Method | Path                          | Body / notes                                  |
|--------|-------------------------------|-----------------------------------------------|
| POST   | `/api/login`                  | `{password, timezone}` → token               |
| GET    | `/api/me` · PUT `/api/me`     | get / set timezone (`{timezone: "Asia/Singapore"}`) |
| GET    | `/api/reminders?status=`      | `pending` \| `done` \| `all`                  |
| POST   | `/api/reminders`              | `{title, due_local, timezone, repeat?, note?}` |
| PATCH  | `/api/reminders/{id}`         | partial update (title/note/due_local/repeat/timezone/status) |
| DELETE | `/api/reminders/{id}`         |                                               |
| POST   | `/api/reminders/{id}/snooze`  | `{minutes}` (pending only)                    |
| GET    | `/api/push/vapid-public-key`  | for the PWA to subscribe                      |
| POST   | `/api/push/subscribe`         | `{endpoint, keys:{p256dh, auth}}`             |
| POST   | `/api/push/test`              | send a test push to all devices               |

`due_local` is a naive wall-clock time in the client's timezone, e.g.
`2026-09-06T21:30`; the server converts to UTC (`due_utc`) for storage and
scheduling. JSON field names follow the vocabulary in `docs/glossary.md`
(e.g. `timezone`, never `tz`).

## Security notes

- Auth today: one shared `APP_PASSWORD`. The login token is `sha256(password)` —
  change the password to invalidate. Fine for a solo app; replace with per-user
  accounts when you open it to others.
- The API is **unauthenticated-able only via login**; every other route needs the
  bearer token, including push subscribe (prevents strangers subscribing your phone).
- TLS/HTTPS handled by Caddy. Database + VAPID keys live in `./data` (keep backups
  of that folder; the db is your reminders, `vapid.pem` keeps push working).

## Roadmap (in rough order)

- [ ] real multi-user accounts (sessions instead of shared password)
- [ ] repeat options: "every N days", weekday picker (Mon–Fri)
- [ ] notification actions: snooze / done straight from the notification
- [ ] edit dialog instead of delete-and-recreate
- [ ] natural-language input ("water plants tomorrow 9am")
- [ ] export/backup of reminders
