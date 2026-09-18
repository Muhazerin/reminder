# Web Push, VAPID & notifications

How a reminder travels from our server to your phone when the app is closed —
and the videos that explain it well.

Domain terms used here (**Device**, **push relay**, **VAPID keys**,
**Notification**) are defined in [`../glossary.md`](../glossary.md).

## The 30-second version

1. Your phone subscribes once (through its browser) and gets an **endpoint** URL
   from the push relay (Google FCM / Apple APNS).
2. We store that subscription as a **Device** row.
3. When a reminder fires, our server POSTs an encrypted notification to the
   endpoint, signed with our **VAPID** key.
4. The relay verifies the signature, wakes your phone, and the **service worker**
   (`static/sw.js`) shows the notification.

## Watch in this order

> **Honest note:** every link below was checked (title, channel, that the video
> is still live) using YouTube's oEmbed API in September 2026. We have *not*
> watched them end to end, and they are third-party material. Most are
> JavaScript/Node teaching examples — the browser-side code transfers directly
> to this project, the server side transfers conceptually (we use Python).

### 1. Use VAPID to secure push messages — *Chrome for Developers*, 3:39
<https://www.youtube.com/watch?v=c25PDH7ZJfk>
The narrowest, most useful thing to watch first: what VAPID is and why a push
service needs it. Straight from Google's own PWA training series.

### 2. Intro to Web Push & Notifications — *Chrome for Developers*, 14:42
<https://www.youtube.com/watch?v=ggUY0Q4f5ok>
The architecture: application server → push service → service worker → user.
Watch this for the mental model rather than the code.

### 3. Web Push Notifications — End to End implementation — *A shot of code*, 17:24
<https://www.youtube.com/watch?v=2zHqTjyfIY8>
Builds both halves — subscribing in the browser and sending from a server. The
closest thing here to watching someone do what `app/push.py` does.

### 4. Full-Stack Web Push Notifications Tutorial (Service Workers, VAPID) — *Code & Chill*, 19:12
<https://www.youtube.com/watch?v=FPD8f2pDQAI>
The most recent of the set, so the API details are least likely to be stale.
Full-stack shape (like this project: backend + PWA), though in Node.

### 5. How Do Push Notifications Work? — *Gerald Versluis*, 8:42
<https://www.youtube.com/watch?v=AKYebqOCAzY>
Zoomed-out, platform-level view (iOS vs Android push, why a relay exists even
for native apps). Good context for *why* the design is the way it is.

### Also available (older or narrower)

- How To Send Push Notifications With JavaScript — *Web Dev Simplified*, 11:38 —
  <https://www.youtube.com/watch?v=Bm0JjR4kP8w> — popular, concise, JS-focused.
- Push Notifications with Service Worker — *Akilesh Rao*, 14:15 —
  <https://www.youtube.com/watch?v=oDIYl3G613E> — explains the Push API and the
  push service as separate moving parts.
- Push Notifications Using Node.js & Service Worker — *Traversy Media*, 29:52 —
  <https://www.youtube.com/watch?v=HlYFW2zaYQM> — a classic walkthrough, but old.

**Age warning:** several of these predate iOS 16.4 (March 2023), when iPhones
finally gained Web Push support. The core concepts are unchanged, but ignore any
claim that iOS cannot receive web push. Our README has the iPhone-specific
installation step ("Add to Home Screen") because iOS only pushes to *installed*
PWAs.

## Written sources (exact, if you want precision)

- **RFC 8292** — VAPID itself: the JWT claims (`aud`, `exp`, `sub`), the ES256
  signature, and subscription restriction.
  <https://datatracker.ietf.org/doc/html/rfc8292>
- **RFC 8030** — the Web Push protocol: endpoints, TTL, delivery.
  <https://datatracker.ietf.org/doc/html/rfc8030>
- **RFC 8291** — the payload encryption (the per-device `p256dh` / `auth` keys).
  <https://datatracker.ietf.org/doc/html/rfc8291>
- **web.dev — Notifications and push** — Google's practical, current guide.
  <https://web.dev/articles/push-notifications-overview>

## Where each concept lives in this repo

| Concept | In the code |
|---|---|
| VAPID keypair (generated once, stored) | `load_or_create_vapid()` — `app/push.py` |
| Public key handed to the browser | `vapid_public_key()` → `GET /api/push/vapid-public-key` → `static/app.js` (`applicationServerKey`) |
| Subscription stored as a **Device** | `upsert_device()` — `app/db.py`, `POST /api/push/subscribe` |
| Signing + sending a push | `notify_devices()` — `app/push.py` (claims: `sub` from `VAPID_MAILTO`) |
| Deciding *when* to send | `fire_reminder()` / `tick()` — `app/scheduler.py` |
| Receiving it on the phone | `static/sw.js` (service worker `push` event) |

Two things that are easy to mix up, both explained in `app/push.py`:

- **VAPID keys are identity, not encryption.** Payload encryption uses the
  per-device keys (`p256dh`, `auth_secret`). VAPID just proves the push came
  from our server.
- **`data/vapid.pem` is the server's push identity.** Back it up. If it is lost
  or regenerated, existing subscriptions must subscribe again.
