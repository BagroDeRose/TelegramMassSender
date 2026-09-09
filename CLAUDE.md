# TelegramMassSender — project rules for Claude Code

Windows desktop app: Python 3.13 + PySide6 6.7 + qasync + Telethon 1.36,
packaged as a onedir EXE via PyInstaller. Sends personal Telegram messages
one-by-one, from the user's own account, only to individual recipients the
user has the right to message (see `README.md`) — never to groups/channels.

Stack quick reference:
- `app/main.py` — entry point.
- `app/ui/` — PySide6 widgets/dialogs.
- `app/telegram/` — Telethon client, sending, entity resolution, media.
- `app/campaign/` — send queue, rate limiting, campaign state.
- `app/recipients/` — parsing/validating/importing recipient lists.
- `app/security/` — DPAPI-backed secret storage.
- `app/config/` — settings and `%APPDATA%` paths.
- `app/database/` — local persistence.
- `app/logging/` — rotating file logging with secret scrubbing.
- `tests/` — pytest + pytest-asyncio (`asyncio_mode = auto`), with
  `tests/mocks/mock_telegram_client.py` standing in for real Telegram.

## Project-specific skills

Detailed rules live in `.claude/skills/` — Claude Code should load these
automatically when relevant, based on their descriptions:

- `telegram-development` — Telethon entities, access_hash, FloodWait, no
  anti-spam bypasses, credential handling.
- `telethon-debugging` — reproduce-first workflow for Telegram-related bugs.
- `qt-async-development` — PySide6 + qasync event-loop, task lifecycle,
  clean shutdown.
- `telegram-media-testing` — the test matrix for media/caption/formatting
  changes.
- `windows-exe-release` — PyInstaller build/release checklist.
- `telegram-security-review` — secrets, sessions, 2FA, logging checklist
  (named to avoid colliding with the built-in `security-review` skill).
- `regression-testing` — reproduce → failing test → fix → full suite.

## Architecture

Don't rewrite existing architecture without a clear need. Before a large
change: read the existing structure of the affected module(s), find related
components, scope the minimal change, and weigh regression risk.

## Bug fixing

Never fix "by eye". Always: reproduce -> understand root cause -> write a
test -> fix -> regression test -> full suite. See the `regression-testing`
skill.

## Tests

After any code change, run the targeted test file, then the full suite
(`pytest`). Don't delete or weaken existing tests just to make the suite
pass.

## GUI

Never block the Qt event loop or the asyncio event loop. Long-running work
must be async/background, following the existing patterns in
`app/telegram/qt_bridge.py` and `app/campaign/`. See the
`qt-async-development` skill.

## Telegram

Do not add anti-ban bypasses, flood-limit bypasses, spam mechanics, or ways
to work around Telegram restrictions. Handle `FloodWaitError` safely
(wait it out or abort cleanly, never shortcut it). See the
`telegram-development` skill.

## Security

Never print in a response, commit, or log: API hash, session contents,
passwords, or other secrets. Never commit secrets to git. See the
`telegram-security-review` skill.

## Release

Before saying a task is complete, when it's release-related: tests -> build
-> launch the actual EXE -> smoke test. See the `windows-exe-release`
skill. Don't claim a release step succeeded unless you actually ran it.

## General

Don't modify application source code unless the task actually requires it.
