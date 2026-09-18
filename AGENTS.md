# Remindly — agent notes

Remindly is a phone-first reminder PWA: FastAPI + SQLite + a scheduler thread
(tick every 20 s) + Web Push, served by Caddy with automatic HTTPS. Domain
vocabulary lives in [`docs/glossary.md`](docs/glossary.md) — read it before
naming anything new.

## How work happens here

- **Never push to `main`.** Work on a feature branch, open a PR, and explain
  the change in plain English (what, why, how it was verified). The owner
  reviews, asks questions, and merges — the merge is the owner's call.
- Small, focused changes beat big rewrites. If a change is large, say so in
  the PR description.
- **Keep scratch files out of the repo.** Verification artifacts (API dumps,
  logs, throwaway scripts) belong outside the working tree — never let
  `git add -A` sweep them in. Check `git status` before committing, and confirm
  the file count matches what you actually changed.
- Everything in the repo (code, docs, comments, commit messages) is English.

## Code conventions

- Every function has a docstring: one line saying what it does, plus a second
  line only when the behaviour isn't obvious from the signature (auth
  requirements, ordering, `None` returns).
- Naming follows `docs/glossary.md`: one concept, one word. Same verb in the
  API handler and the db function (`create_reminder` → `db.create_reminder`).
- Commit messages: short imperative subject with a type prefix, e.g.
  `refactor:`, `docs:`, `feat:`, `fix:`.
- Secrets live in `.env` (gitignored) — never commit a real password or token.

## Verify before claiming done

```bash
# syntax
python3 -m py_compile app/*.py scripts/*.py

# end-to-end: start the app on a scratch DB, then run the smoke test
rm -rf /tmp/rd-smoke
APP_PASSWORD=test1234 DATA_DIR=/tmp/rd-smoke .venv/bin/uvicorn app.main:app --port 8123 &
.venv/bin/python scripts/smoke_test.py   # 13 checks: auth, CRUD, snooze,
                                         # scheduler firing, daily advance
```

Web Push itself cannot be verified locally — it needs HTTPS and a real phone,
so that check happens after deploying to the VPS.
