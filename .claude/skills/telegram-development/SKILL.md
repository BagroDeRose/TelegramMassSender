---
name: telegram-development
description: Use when writing or reviewing any code that talks to the Telegram API in this project (app/telegram/**, app/campaign/**, app/recipients/**) — entity resolution, sending messages/media, account/session handling, or anything touching Telethon.
---

# Telegram / Telethon development rules

This project (`app/telegram/*`) sends personal Telegram messages one-by-one from
the user's own account via Telethon. Relevant files: `client_manager.py`,
`sender.py`, `service.py`, `recipient_resolver.py`, `media_sender.py`,
`account_manager.py`, `authentication.py`, `exceptions.py`.

## Entities and access_hash

- Never construct a `User`/`Channel`/`Chat` entity by hand with a guessed
  `access_hash`. Always resolve entities through Telethon (`get_entity`,
  `get_input_entity`) or from previously cached dialogs/messages — a stale or
  wrong `access_hash` causes `PEER_ID_INVALID` at send time.
- Recipients may be given as `@username`, numeric ID, or phone number (see
  `app/telegram/recipient_resolver.py` and `app/recipients/parser.py` /
  `validator.py`). Resolve and validate each recipient explicitly; do not
  assume a numeric-looking string is a valid resolvable ID without resolving it.
- Distinguish private users from groups/channels before sending — this app is
  scoped to **personal direct messages only** (see README.md). Do not add code
  paths that target groups/channels/broadcast lists.

## FloodWait and API errors

- Every Telegram API call that can raise `FloodWaitError` (or other
  `telethon.errors` types, see `app/telegram/exceptions.py`) must handle it
  explicitly: wait the required duration (surfaced to the UI/log, not silently
  swallowed) and resume, or abort the campaign cleanly. Never retry
  in a tight loop and never shorten the wait Telegram tells you to take.
- Do not implement or suggest techniques whose purpose is to bypass or reduce
  Telegram's flood/anti-spam limits (message rotation tricks, fake
  typing/read receipts to look "less automated", parallel accounts to split
  volume across a single campaign, etc.). Sending stays deliberately
  sequential with user-configured delay (`app/campaign/rate_limiter.py`).

## Credentials and sessions

- API ID/Hash and session files are secrets. They must go through
  `app/security/secure_storage.py` / `app/security/dpapi.py` (Windows DPAPI),
  never written to plain-text config, logs, or exception messages.
- Never print or log a session string, 2FA password, or API hash — see the
  [[telegram-security-review]] skill.

## Tests

- Business logic here (entity resolution, recipient parsing/validation,
  campaign/rate-limit behavior) must be covered by tests in `tests/`, using
  the mock client in `tests/mocks/mock_telegram_client.py` rather than a real
  Telegram connection. See [[telethon-debugging]] and [[regression-testing]].
