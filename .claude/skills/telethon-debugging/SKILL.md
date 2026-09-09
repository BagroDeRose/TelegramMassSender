---
name: telethon-debugging
description: Use when debugging a Telethon/Telegram-related bug in this project — unexpected exceptions, wrong entity resolution, broken formatting/albums, or any traceback originating from app/telegram/**.
---

# Telethon debugging workflow

Follow this sequence for any bug that originates from Telethon or the
`app/telegram/*` layer. Do not skip straight to a fix.

1. **Identify the exact Telethon version** in use (`requirements.txt` pins
   `Telethon==1.36.0`; confirm the installed version matches — behavior and
   exception types can differ across versions).
2. **Read the actual traceback**, not a guess. Note the exact Telethon
   exception class (`app/telegram/exceptions.py` wraps some of these) and the
   call site.
3. **Find a minimal reproduction** — a small script or test using
   `tests/mocks/mock_telegram_client.py` (or, if the bug only reproduces
   against real Telegram, a minimal manual script the user runs themselves,
   never one that sends live messages during automated debugging).
4. **Check Telethon's documented behavior** for the API involved before
   assuming it's a bug in this project's code.
5. **Check Telethon's own source** (in the venv's site-packages) when
   documentation doesn't explain the behavior.
6. **Write a regression test first** that reproduces the failure (see
   [[regression-testing]]).
7. **Fix minimally** — do not refactor unrelated code while fixing a bug.
8. **Run the targeted test**, then the full suite (`pytest`).

## Areas that need extra care

- **Entities / access_hash** — resolution failures, stale cache, wrong peer type.
- **Formatting entities & UTF-16 offsets** — Telegram message entities
  (bold/italic/underline/links) are indexed in UTF-16 code units, not Python
  string indices or UTF-8 bytes. Any bug touching `app/ui/message_editor.py`,
  `message_preview.py`, or caption/entity building in `media_sender.py` /
  `sender.py` needs a check against surrogate-pair characters (emoji, etc.)
  — see [[telegram-media-testing]].
- **Albums / media** — grouped media messages have their own send path
  (`media_sender.py`); a caption on an album applies differently than a
  caption on a single media item.
- **Async behavior** — Telethon is asyncio-based; verify cancellation and
  event-loop interaction against [[qt-async-development]].
- **FloodWait / session handling** — see [[telegram-development]].
