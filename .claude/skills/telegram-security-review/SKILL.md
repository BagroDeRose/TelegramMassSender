---
name: telegram-security-review
description: Use when reviewing or writing code that touches credentials, sessions, 2FA, logging, or local storage (app/security/**, app/logging/**, app/database/**, app/config/paths.py) — checklist for secrets handling in this project. Renamed from security-review to avoid colliding with the built-in security-review skill.
---

# Security review checklist

This app stores real user secrets locally on Windows. Existing
infrastructure (extend it, don't bypass it):

- `app/security/dpapi.py` — Windows DPAPI encrypt/decrypt primitives.
- `app/security/secure_storage.py` — API ID/Hash persisted as a
  DPAPI-encrypted blob at `get_secrets_path()`. **The 2FA password is never
  written to disk anywhere in this codebase** — it's used once during login
  (`app/telegram/authentication.py`) and discarded. Any new code path must
  preserve this; do not add a "remember 2FA password" feature.
- `app/logging/logger.py` — `SecretScrubbingFilter` redacts API hash/id,
  passwords, 2FA password, and session-like strings from every log line as a
  defensive second line. **This is a backstop, not a license** — never
  deliberately log a secret and rely on the scrubber to catch it; the regex
  patterns are best-effort and can miss variants.
- Telegram session data goes through the same DPAPI-backed storage layer as
  API credentials — never plain JSON/text next to the exe.

## When reviewing or writing code, check for

- API ID/Hash or session data written to disk outside
  `secure_storage.py`/`dpapi.py`.
- Any secret (API hash, 2FA password, session string) passed to
  `print()`, an exception message that could surface in the UI or logs, or a
  new log call that bypasses `configure_logging()`'s handlers.
- Exception messages that embed request/response payloads verbatim — Telethon
  errors can contain sensitive context; scrub before displaying/logging.
- Temporary files containing session or credential data left on disk after
  use.
- New config/settings fields (`app/config/settings.py`) that should be secret
  but are being added as plain values instead of routed through
  `secure_storage.py`.
- Anything committed to git that shouldn't be (check `.gitignore` covers
  `%APPDATA%`-equivalent local data dirs, `.venv`, build output — this repo
  does not store secrets in-tree, keep it that way).
- User input (recipient lists, message text, imported files in
  `app/recipients/importer.py`) validated before use — not blindly trusted.

## Do not

- Print API hash, session contents, passwords, or other secrets in your own
  chat responses while debugging, even redacted-looking fragments.
- Add secrets to git.
