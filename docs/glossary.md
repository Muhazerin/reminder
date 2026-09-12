# Remindly Glossary — Ubiquitous Language

This is the project's single vocabulary, following the DDD practice of
**Ubiquitous Language**: every concept has exactly **one name**, and that name
is used everywhere — database columns, API JSON fields, function names,
comments, and this document. If you meet a term that is not here (or a term
that has several names), that is a bug: fix it here first, then in the code.

> This document holds **domain language only**. Engineering conventions —
> docstrings, commit style, the branch/PR workflow, how to run the tests —
> live in [`AGENTS.md`](../AGENTS.md).

> Naming rules of thumb
> - **One concept = one word.** No near-synonyms (`add` vs `create`, `tz` vs `timezone`).
> - **DB layer and API speak the same verbs**: `create / list / get / update / delete / upsert`.
> - **HTTP handlers are named `<verb>_<resource>`** (`create_reminder`,
>   `delete_device`) and call the same verb in the db layer.
> - **Documented exceptions live in the section below.** A deviation is only
>   acceptable when it is written down there — an undocumented near-synonym is
>   still a bug.
> - **Wire-format names are kept as-is** where the browser push protocol
>   dictates them (`endpoint`, `p256dh`, `auth`) — renaming those would lie
>   about the protocol.
> - Words like `row_to_dict`, `utcnow` are plumbing, not domain language —
>   they describe code, not the problem, so they may stay.

---

## Core domain terms

| Term | Meaning |
|---|---|
| **Reminder** | The thing you ask Remindly to notify you about. Has a `title`, optional `note`, a `due_local` + `timezone` + `repeat` (its schedule), a `due_utc` (its next fire instant), and a `status`. Stored in the `reminders` table. |
| **User** | The person using the app. Today there is exactly one hard-coded user, id `"local"` (`LOCAL_USER`), authenticated by the shared `APP_PASSWORD`. The schema is scoped by `user_id` so real accounts can be added later. |
| **Device** | One phone/browser that may receive notifications: a row in the `devices` table holding a push subscription (`endpoint`, `p256dh`, `auth_secret`). A synonym would be "subscription" — we call it **Device**. |
| **Push subscription** | The browser-side object (wire term from the Push API). It is what a **Device** row stores. Contains an **endpoint** URL and encryption **keys**. |
| **Notification** | The message delivered to the phone: `{title, body, tag, data}`. Created when a reminder fires; delivered by the push relay. |
| **Occurrence** | One concrete firing of a repeating reminder (daily → one occurrence per day). `next_occurrence()` computes the next one. |
| **Snooze** | Postponing a pending reminder: pushes its `due_utc` a fixed number of minutes into the future. Snoozing never changes `due_local` or `repeat`. |

## The time model (the heart of the app)

| Term | Meaning |
|---|---|
| **due_local** | A *wall-clock* time, naive and local to the user, e.g. `2026-09-06T21:30`. This is what you type in the app. For a repeating reminder it is the fixed base of the rule (the first occurrence). Stored in the `due_local` column. |
| **due_utc** | The *instant* the reminder must next fire, as UTC ISO. The scheduler compares `due_utc` against the clock. When a repeating reminder fires, `due_utc` advances to the next occurrence; when you snooze, `due_utc` moves forward. **Never** changes `due_local`. |
| **timezone** | The user's IANA zone name (e.g. `Asia/Singapore`). Needed to convert between `due_local` (wall clock) and `due_utc` (instant), and to compute occurrences DST-safely. |
| **due** | A reminder is *due* when `status = pending` and `due_utc <= now`. |
| **overdue** | Frontend word for a pending reminder whose instant has passed (shown as "Due now"). |

The rule to remember: **`due_local` is the human's rule, `due_utc` is the
machine's deadline.**

## Reminder schedule & lifecycle

| Term | Meaning |
|---|---|
| **one-shot** | A reminder with `repeat = ""`. Fires once, then `status` becomes `done`. |
| **repeating** | A reminder with `repeat` = `daily`, `weekly`, or `monthly`. After each fire, `due_utc` advances to the next occurrence; it stays `pending` forever. |
| **repeat rule** | The value of `repeat`: `""` (once) \| `daily` \| `weekly` \| `monthly`. |
| **status** | Column with two values: `pending` (waiting to fire) and `done` (a one-shot that fired, or one you marked done). |
| **fire** | The act of acting on a due reminder: notify the user's devices, then advance a repeating reminder or mark a one-shot `done`. `fire_reminder()` in the scheduler. |
| **fire-late** | Deliberate behaviour: if the server was down when a reminder came due, it fires on the next scheduler tick instead of being dropped. |
| **tick** | One pass of the scheduler loop (every 20 s): find due reminders and fire them. |
| **scheduler** | The background thread that ticks. |

## Devices & push

| Term | Meaning |
|---|---|
| **Web Push** | The mechanism (RFC 8030) that delivers a notification to a phone even when the app is closed, via a push relay (Google FCM / Apple APNS). |
| **push relay** | The browser-vendor service that actually wakes the phone. The server never talks to the phone directly. |
| **endpoint** | The relay URL of one subscription (wire-format name, kept as-is). |
| **p256dh / auth** | The subscription's encryption keys (wire-format names, kept as-is). |
| **VAPID keys** | The server's push identity: a keypair generated once into `data/vapid.pem`. The public key (`vapid_public_key()`) is served to the PWA so it can subscribe; the private key signs pushes so the relay trusts us. |
| **subscribe / unsubscribe** | A device registering (or unregistering) its subscription with our server. |
| **notify** | The act of sending a notification to devices: `notify_devices()` in `push.py`. |
| **dead subscription** | A subscription the relay rejects with 404/410 (app uninstalled). Automatically pruned. |

## Auth & app shell

| Term | Meaning |
|---|---|
| **password** | The one shared `APP_PASSWORD` you type to sign in. |
| **token** | What the server returns at login. It *is* `sha256(password)`; every other request sends it as `Authorization: Bearer <token>`. Changing the password invalidates every token. |
| **bearer token** | The auth header scheme. |
| **PWA** | The installable phone app: `static/` served over HTTPS. |
| **service worker** | `sw.js` — the script the browser registers; it receives incoming pushes and shows the notification. |
| **Caddy** | Reverse proxy that terminates TLS and fetches Let's Encrypt certificates automatically. |
| **Docker Compose** | How the app + Caddy are packaged and started on the VPS. |
| **DuckDNS** | Free dynamic-DNS provider giving the app a stable `*.duckdns.org` name (pushes require a stable HTTPS origin). |
| **SQLite / WAL** | The database and its journal mode; one connection per operation so API and scheduler threads never share a connection. |

---

## Documented exceptions

Rules are only useful if the exceptions are written down. Each entry here is a
deliberate, accepted deviation — not a synonym to be "fixed" later.

### `me` — the currently authenticated user

`me` is a **widespread, accepted REST idiom** for the currently authenticated
user: the endpoint answers "the record belonging to whoever is making this
request." GitHub and GitLab express the same idea as `/user`, and many other
APIs use `/me`. The benefit is that the client never needs to know or send its
own user id — which stays true whether the app has one user or many.

- API paths: `GET /api/me`, `PUT /api/me`
- Handlers: `get_me`, `update_me` — named after the path, so they are the one
  place that does **not** follow the `<verb>_<resource>` naming rule
- Everywhere else the domain word is **User**: `upsert_user`,
  `get_user_timezone`, and the response field `user_id`

There is a pointer comment next to the handlers in `app/main.py`.

---

## Retired names (old → new)

Everything below used to have a *different* name somewhere in the codebase.
They now all speak the canonical term on the right. There is **no schema
migration yet**: if you have a database created before this change, delete the
`data/` folder (dev-local, gitignored) and let the app recreate it. A real
migration story comes after the first deploy.

| Retired name | Where it lived | Canonical term now |
|---|---|---|
| `tz` / `TZ` / `tz_name` | variables, JSON fields, columns `users.tz`, `reminders.tz` | `timezone` |
| `anchor` / `anchor_local` | `reminders.anchor` column, scheduler param | `due_local` |
| `add_reminder` | HTTP handler for `POST /api/reminders` | `create_reminder` |
| `edit_reminder` | HTTP handler for `PATCH /api/reminders/{id}` | `update_reminder` |
| `remove_reminder` | HTTP handler for `DELETE /api/reminders/{id}` | `delete_reminder` |
| `ensure_user` | db function | `upsert_user` |
| `get_user_tz` | db function | `get_user_timezone` |
| `due_pending` | db function | `list_due_reminders` |
| `add_device` | db function | `upsert_device` |
| `remove_device` | db function | `delete_device` |
| `send_all` | push function | `notify_devices` |
| `public_key_b64` | push function | `vapid_public_key` |
| `_fire` | scheduler function | `fire_reminder` |

---

## One-line summaries

- A **reminder** (with a **repeat rule**) is created with a **due_local**
  wall-clock time in the user's **timezone**; the server stores the next
  instant as **due_utc**.
- Every **tick** (20 s) the **scheduler** **fires** reminders that are **due**:
  it **notifies** the user's **devices** (via the **push relay**), then
  advances **repeating** ones to their next **occurrence** or marks
  **one-shots** `done`.
- You can **snooze** a pending reminder; the phone can be closed the whole
  time — that's the point.
