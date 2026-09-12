# TelegramMassSender — project context for Claude Code

Windows desktop app: Python 3.13 + PySide6 6.8 + qasync + Telethon 1.36,
packaged as a onedir EXE via PyInstaller. Sends personal Telegram messages
one-by-one, from the user's own account, only to individual recipients the
user has the right to message (see `README.md`) — never to groups/channels.

This file documents the **current implementation** and the **development
rules** that apply when working on it. Planned/future work lives in
`ROADMAP.md`, not here — nothing in that file exists yet unless it's also
described below.

## Architecture (current state)

- `app/main.py` — entry point; creates the `QApplication`/qasync event loop
  and the DPAPI-backed secret store before the main window.
- `app/ui/` — PySide6 widgets/dialogs/pages:
  - `main_window.py` — top-level window, orchestrates the service layer and
    all pages; sidebar navigation between Campaign/Accounts/Results/Settings.
  - `sidebar.py`, `account_widget.py`, `recipient_widget.py`,
    `attachments_widget.py`, `journal_widget.py`, `stat_card.py`,
    `empty_state.py` — page/widget components.
  - `campaign_controls.py` — Start/Pause/Stop, progress, and (v1.6) the
    pre-start duration estimate (recipient count × average configured
    interval) plus the live elapsed-time/remaining-time display (a
    1-second `QTimer` owned by the widget itself, started once by
    `MainWindow` when a campaign actually starts, not on every
    pause/resume) and the current-recipient label, driven by
    `CampaignManager.current_item_changed`.
  - `message_editor.py` / `message_editor_dialog.py` / `message_preview.py`
    — rich-text message editor and its preview.
  - `login_dialog.py`, `dialogs.py` — account connection and confirmation
    dialogs.
  - `campaign_wizard.py` — optional step-by-step Campaign Wizard (a modal
    dialog reusing `RecipientWidget`/`MessageEditorDialog`/
    `AttachmentsWidget`/`MessagePreviewWidget` instances, one per step, so
    it holds no parsing/validation/formatting logic of its own). On
    confirm it hands its collected state back to
    `MainWindow._on_open_campaign_wizard_clicked`, which writes that state
    into the same live Campaign-page widgets the fast single-page workflow
    uses and calls the same `_on_start_requested` — both workflows share
    one validation/start path and one live-progress UI.
  - `theme.py` — light/dark theme tokens and QSS stylesheet generation
    (generated at runtime, not shipped as static `.qss` files).
  - `icons.py`, `thumbnails.py` — hand-drawn `QPainter` icon set (including
    per-attachment-type glyphs: video/audio/archive/document, selected in
    `attachments_widget.py` from `AttachmentKind`) and image-attachment
    thumbnail generation.
- `app/telegram/` — Telethon (MTProto) integration:
  - `client_manager.py`, `account_manager.py`, `authentication.py` — client
    lifecycle, multi-account session management/switching.
  - `sender.py`, `media_sender.py` — message/media sending, album batching,
    caption-vs-leading-message logic. `media_sender.AttachmentKind`
    (PHOTO/VIDEO/ANIMATION/IMAGE_OTHER/AUDIO/ARCHIVE/DOCUMENT) is the single
    source of truth for local-file classification — extension-based,
    deliberately no MIME sniffing; `app/ui/thumbnails.py` and
    `app/ui/attachments_widget.py`'s icon selection both read the same
    table rather than keeping their own. AUDIO/ARCHIVE are purely
    descriptive (icon selection only) — adding a kind here does NOT by
    itself change what gets sent or how; only PHOTO/VIDEO are
    album-eligible and only PHOTO/ANIMATION/IMAGE_OTHER are thumbnailed,
    exactly as before each kind was added.
  - `recipient_resolver.py` — resolves `@username` / numeric ID / phone
    (E.164) to a Telegram entity; phone resolution uses
    `contacts.ResolvePhoneRequest` (does not mutate the contact list).
  - `template.py` — `{name}` placeholder expansion; works in UTF-16
    surrogate-pair space so formatting-entity offsets stay correct.
  - `service.py`, `qt_bridge.py` — glue between the Telethon client and the
    Qt/qasync event loop.
  - `exceptions.py` — Telegram-error taxonomy used by the campaign layer.
- `app/campaign/` — send orchestration:
  - `campaign_manager.py`, `send_queue.py`, `campaign_state.py` — the send
    queue, per-item status/retry (`next_step`-based resume), FloodWait
    pause/resume, and the duplicate-campaign-start guard.
  - `rate_limiter.py` — randomized interval between sends.
  - `report.py`, `report_library.py` — CSV report generation (with
    formula-injection sanitization) and the saved-reports library.
  - `presets.py` — named message presets (text, formatting, attachments,
    optionally the campaign interval), explicitly saved/loaded by name via
    the Campaign page's Presets row in `app/ui/main_window.py` — never an
    automatic history of everything typed. Round-trips Telethon TL
    formatting entities through `.to_dict()`/a name→class map (Telethon has
    no built-in `from_dict()`), and re-checks attachment paths against the
    filesystem on load since a saved file may have moved or been deleted.
- `app/recipients/` — `parser.py` (format detection: username/ID/link/phone;
  also owns `dedupe_recipients`, shared by every import path), `validator.py`,
  `importer.py` (TXT import), `csv_importer.py` (CSV import with
  content-based column detection — no header parsing or manual column
  mapping: the first cell in a row that parses as a recipient identifier
  via `parser.parse_recipient_line` is that row's identifier, and the
  first remaining non-identifier cell becomes a per-recipient `{name}`
  override, consumed by `CampaignManager(recipient_names=...)`),
  `groups.py` (named local recipient groups — a saved snapshot of the
  Recipients box's raw text plus any `{name}` overrides, explicitly
  saved/loaded/renamed/deleted; mirrors `app.campaign.presets`'s
  structure. Deliberately not a CRM: no tags/notes/contact history).
- `app/security/` — `dpapi.py` (Windows `CryptProtectData`/`CryptUnprotectData`
  wrapper), `secure_storage.py` (API ID/Hash at-rest encryption).
- `app/config/` — `settings.py` (defaults/bounds for all user settings),
  `paths.py` (`%APPDATA%` layout).
- `app/database/` — SQLite via `database.py`; `models.py`/`repositories.py`
  for accounts, settings, saved-report metadata, named presets, and named
  recipient groups.
- `app/logging/` — rotating file logging with secret scrubbing.
- `app/i18n/` — Russian/English translation catalog and lookup:
  `translator.py` (`tr()`/`trn()`, active-language state following the
  same pattern as `app/ui/theme.py`'s active-theme state), `strings.py`
  (the catalog itself). A top-level package, not under `app/ui/`, because
  `app/config/settings.py`'s validation-error messages and other non-UI
  layers need it too. Language switches immediately (no restart): every
  persistent widget/page implements `retranslate_ui()`, dispatched from
  `MainWindow.retranslate_ui()` the same way theme switching already
  dispatches `apply_theme()`. Deliberately not gettext or Qt Linguist
  (.ts/.qm + lupdate/lrelease) — this app has no other use for either.
- `tests/` — pytest + pytest-asyncio (`asyncio_mode = auto`), 505 tests,
  using `tests/mocks/mock_telegram_client.py` and
  `tests/mocks/fake_client_manager.py` instead of a real Telegram
  connection. CI runs this suite on `windows-latest` with
  `QT_QPA_PLATFORM=offscreen` (`.github/workflows/tests.yml`).

Packaging: `telegram_mass_sender.spec` (PyInstaller, portable onedir build,
bundles `assets/`), invoked by `build_windows.bat`.

## Development rules & constraints

**Architecture.** Don't rewrite existing architecture without a clear need.
Before a large change: read the existing structure of the affected
module(s), find related components, scope the minimal change, and weigh
regression risk.

**Bug fixing.** Never fix "by eye." Always: reproduce → understand root
cause → write a failing test → fix → regression test → full suite. Recent
examples of this discipline: the duplicate-campaign-start race (a
synchronous guard closing a TOCTOU gap between a button click and an
awaited `ensure_connected` call) and the CSV formula-injection fix (cells
starting with `=+-@` are prefixed with `'`) were both found via review,
reproduced with a failing test first, then fixed.

**Tests.** After any code change, run the targeted test file, then the
full suite (`pytest tests/ -v`). Don't delete or weaken existing tests just
to make the suite pass. The current baseline is 505 passed, 0 failures —
if that number changes, know exactly why before saying the change is done.

**GUI.** Never block the Qt event loop or the asyncio event loop.
Long-running work (network calls, FloodWait waits) must be async/background,
following the existing patterns in `app/telegram/qt_bridge.py` and
`app/campaign/campaign_manager.py`.

**Telegram.** Do not add anti-ban bypasses, flood-limit bypasses, spam
mechanics, or ways to work around Telegram restrictions. Handle
`FloodWaitError` safely (wait it out or abort cleanly, never shortcut it).
Never construct entities with a guessed `access_hash` — always resolve
through Telethon or cached dialogs/messages.

**Security.** Never print in a response, commit, or log: API hash, session
contents, passwords, or other secrets. Never commit secrets to git. The
2FA password is used once during login and never persisted. Credentials at
rest go through `app/security/` (Windows DPAPI) — never plain-text config,
logs, or exception messages.

**Release.** Before saying a release-related task is complete: tests →
build → launch the actual EXE → smoke test. Don't claim a release step
succeeded unless it was actually run. See the packaged-build validation
process used for the v1.3.0 release as the reference (manual launch,
account load/restore, both themes, clean shutdown — not just "the build
didn't error").

**Documentation.** `README.md` is the authoritative public documentation
(English-first summary, full Russian user guide below it). `ROADMAP.md` is
planning-only — do not treat anything listed there as implemented. Keep
both honest: don't claim a feature exists before it does, and don't remove
the AI-assisted-development disclosure.

**General.** Don't modify application source code unless the task actually
requires it. Don't add features, refactor, or introduce abstractions beyond
what the current task requires.
