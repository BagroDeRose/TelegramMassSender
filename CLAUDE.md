# TelegramMassSender — project context for Claude Code

Windows desktop app: Python 3.13 + PySide6 6.8 + qasync + Telethon 1.36,
packaged as a onedir EXE via PyInstaller. Sends Telegram messages
one-by-one, from the user's own account, to individual recipients the user
has the right to message, and to groups/supergroups/channels the account is
*already a member of and allowed to post in* (see `README.md`) — it never
joins a chat (invite links are only checked) and never works around a
chat's permissions, slow mode or FloodWait.

This file documents the **current implementation** and the **development
rules** that apply when working on it. Planned/future work lives in
`ROADMAP.md`, not here — nothing in that file exists yet unless it's also
described below.

## Architecture (current state)

- `app/main.py` — entry point; creates the `QApplication`/qasync event loop
  and the DPAPI-backed secret store before the main window.
- `app/version.py` — `APP_VERSION`, the single source of truth for the
  version string shown in Diagnostics; bumped only at an actual release.
- `app/diagnostics.py` — v1.7 Diagnostics: `collect_diagnostics()`/
  `format_diagnostics_text()`, read-only application/environment/status
  info (app/Python/Telethon versions, DB reachability, Telegram
  connection, session-file presence, network state) for the Settings
  page's Diagnostics card. Every field degrades to an error string rather
  than raising if its underlying check fails; never reads API ID/Hash, a
  password, or session file contents.
- `app/diagnostic_bundle.py` — v1.7 Diagnostic Bundle:
  `export_diagnostic_bundle()` zips the Diagnostics report, the rotating
  log files (already secret-scrubbed at write time), and an `AppSettings`
  dump (API ID/Hash live elsewhere, in `app.security.secure_storage`, so
  there's nothing to strip out of settings) -- never touches session
  files. Found via actually generating and inspecting a real bundle
  during the release-candidate audit: a user-customized
  `reports_directory` is very often somewhere under the user's own
  Windows profile (e.g. Documents), which embeds their Windows account
  name -- `_sanitize_reports_directory()` redacts just that `C:\Users\<name>\`
  segment before the settings dump is written, only for this export
  (the real path is still what every other use of the setting sees).
- `app/ui/` — PySide6 widgets/dialogs/pages:
  - `main_window.py` — top-level window, orchestrates the service layer and
    all pages; sidebar navigation between Campaign/Accounts/Results/Settings.
    (v1.8) Owns a `QSystemTrayIcon` (Show/Exit menu; only actually shown
    when `QSystemTrayIcon.isSystemTrayAvailable()`); minimizing hides the
    window to tray instead of the taskbar (restorable from the tray icon),
    and native tray notifications fire on campaign completion and on a
    campaign-ending critical error, alongside the existing status-bar
    text/modal dialog respectively -- "Exit" in the tray menu always goes
    through the normal `closeEvent`, never a separate shutdown path.
    Layout (UI redesign): the shell is sidebar | page stack | journal
    (right); the Campaign page is two columns via `layouts.
    ResponsiveColumns` (Recipients/Message/Attachments scroll left; the
    preview card and `CampaignControlsWidget` are pinned right, and fold
    under the left column below `CAMPAIGN_FOLD_WIDTH`); Tab order is set
    explicitly in `campaign_tab_chain()`. Quick successes go to
    `self._toast()` (`motion.ToastHost`), not modal boxes; file exports
    and errors stay modal.
    Every start path (Campaign page, Campaign Wizard, Retry) asks through
    the one `_confirm_campaign_start`: more recipients than the
    `large_campaign_threshold` setting (default 50, min 10) always gets
    `dialogs.confirm_large_campaign` (people/bots/chats, danger Start,
    Cancel default), otherwise the opt-in `confirm_before_start` box.
    The Results page's recipient-results list (v1.6 Retry, v1.7 Filter
    results) shows `_report_source`'s items filtered by a segmented control
    (`results_view.SegmentedControl`, QComboBox-compatible API; default:
    Failed, preserving Retry's original behavior), painted as table rows
    by `results_view.ResultsRowDelegate` -- only FAILED rows are
    ever checkable, regardless of the active filter. Retry relaunches
    through the exact same `_start_campaign` every other start path (fast
    workflow, Campaign Wizard) already shares, reusing the message/
    attachments/account captured in `_last_campaign_context` when that
    campaign originally started -- never whatever is currently in the
    page's boxes; "retry all failures" always means every actual failure,
    independent of the filter. Duration is frozen once at completion
    (`_last_campaign_duration_seconds`) since `CampaignControlsWidget.
    elapsed_seconds()` keeps counting up and can't be re-read later.
  - `sidebar.py` (collapsible to an icon rail, state in the
    `sidebar_collapsed` setting; active-account block at the bottom),
    `recipient_widget.py` (count pills), `journal_widget.py` (rows painted
    by a delegate: monospace time, status icon from the campaign layer's
    marker glyph), `stat_card.py`, `empty_state.py` (icon + sentence +
    optional single action), `results_view.py`, `layouts.py`, `motion.py`
    (toasts, page fade), `dialog_frame.py` (title / content / footer with
    the primary action rightmost) — page/widget components.
  - `attachments_widget.py` — the attachment tile grid. `move_attachment(
    from_index, to_index)` is the single canonical ordering operation:
    `to_index` is the *final* index, which is what makes it
    direction-independent; drag-and-drop, the Move earlier/later buttons
    and Ctrl+Left/Right on a focused tile all route through it. (v2.0.0
    used "insert immediately before the target tile" instead, which
    matched the drop slot only for backward drags and left every forward
    drag one slot short.) Decoded thumbnails and size/type metadata are
    cached per path, because every reorder rebuilds all tiles and
    re-decoding each image from disk cost ~208 ms per reorder for 12
    photos; the metadata half of that cache is dropped on a language
    switch since file sizes are localized. Tile contents are inset past
    the tile border so its own selected/focus styling stays visible.
    Cards have no hover effect at all (the theme neutralizes the hover
    highlight on *their* remove button only -- the account cards use the
    same `chipRemoveButton` and keep theirs). A plain click toggles
    selection, which is why a tile uses `TabFocus` and takes mouse focus
    itself in `mousePressEvent` *after* recording whether it was already
    the sole selection: a click that moves focus onto an item widget makes
    the list view select that item during the press, before the tile sees
    the event. The focus ring is suppressed for click focus, since it
    shares its color with the selection border.
  - `account_widget.py` — one card per account (avatar, username, phone,
    connection status). (v1.8) A card's title prefers the user's own
    local alias (`Account.local_alias`, set via the card's rename
    button/`QInputDialog`) over Telegram's own profile name, which wins
    over the phone number; the phone is otherwise always shown on the
    card unless it would just repeat the title.
  - `campaign_controls.py` — the launch/progress panel: a summary (users,
    groups/channels, attachments, interval, estimate) above the page's one
    primary button, turning into progress while running (state pill,
    progress bar, counters, Pause/Resume, Stop) with a FloodWait block
    (countdown; Continue enabled only once the campaign has paused).
    Also Start/Pause/Stop, progress, and (v1.6) the
    pre-start duration estimate (recipient count × average configured
    interval) plus the live elapsed-time/remaining-time display (a
    1-second `QTimer` owned by the widget itself, started once by
    `MainWindow` when a campaign actually starts, not on every
    pause/resume) and the current-recipient label, driven by
    `CampaignManager.current_item_changed`.
  - `message_editor.py` / `message_editor_dialog.py` / `message_preview.py`
    — rich-text message editor and its preview.
  - `login_dialog.py`, `dialogs.py` — account connection and confirmation
    dialogs. The optional start confirmation splits the count into users,
    groups/channels (by format) and `@username`/`t.me` names whose type
    is only known after resolving — nothing is resolved before confirming.
  - `chat_picker_dialog.py` — the "From my chats…" picker: every dialog
    of the active account (people, bots, groups, supergroups, forums,
    channels) with type segments, a folder combo (hidden when the account
    has no folders), an archive toggle (off by default), search, muted
    unavailable rows (reason as tooltip, not tickable), "already listed"
    rows (matched by normalized key, so `@name` and the ID of the same
    addressee both count) and a people/bots/chats counter.
    Presentational only: it opens at once in a loading state and emits
    `refresh_requested`; `MainWindow._on_pick_chats_requested(target,
    parent)` opens it with `open()` (never `exec()` inside a coroutine),
    loads through `chat_targets.list_dialogs` in `self._spawn(...)` under
    `_account_lock`, feeds `set_dialogs()`/`set_error()` (FloodWait shown,
    never retried), drops a result that arrives after it closed, and
    keeps what it read in `MainWindow._dialog_cache` (`chat_targets.
    DialogCache`, one `DialogSnapshot` for the active account for the
    session; reopening shows it at once, Refresh and every account change
    — switch, Demo Mode in/out, delete — drop it, and `get()` only
    answers for the account it was filled for), and writes picked
    dialogs back via `RecipientWidget.append_lines()` (as
    `@username`, else the ID: positive for people, marked for chats). One
    picker at a time (`MainWindow._chat_picker`). The button is on the
    Campaign page's `RecipientWidget` and the Campaign Wizard's
    (`show_chat_picker=True` on both; the wizard's opens the picker over
    the wizard and fills the wizard's box), enabled only for a connected,
    authorized active account with no campaign starting or running.
  - `dialog_picker_model.py` — the picker's `DialogListModel` (newest
    first, ticked set, already-listed flags), `DialogFilterProxy` (type/
    folder/archive/search on fields precomputed per load, never on data()
    roles, no re-sort — 5000 dialogs filter in well under 0.25 s) and
    `DialogRowDelegate` (initials circle — no avatars are downloaded —,
    name, type icon + label, @username/ID in monospace, date, pill; all
    colours from tokens at paint time).
  - `campaign_wizard.py` — optional step-by-step Campaign Wizard (a modal
    dialog reusing `RecipientWidget`/`MessageEditorDialog`/
    `AttachmentsWidget`/`MessagePreviewWidget` instances, one per step, so
    it holds no parsing/validation/formatting logic of its own). On
    confirm it hands its collected state back to
    `MainWindow._on_open_campaign_wizard_clicked`, which writes that state
    into the same live Campaign-page widgets the fast single-page workflow
    uses and calls the same `_on_start_requested` — both workflows share
    one validation/start path and one live-progress UI.
  - `theme/` — the one theme system (see docs/design.md). `tokens.py`:
    every colour, size, font name and motion duration for both themes,
    the only place literals like these may live (enforced by
    `scripts/check_ui_hygiene.py` / `tests/test_ui_hygiene.py`). `qss.py`:
    the single QSS template. `__init__.py`: the public API every caller
    already used (`tokens_for`, `current_tokens`, `stylesheet_for`, scale
    constants, ...) plus `apply_theme(app, name)` — the only place a
    theme is applied: QPalette, Inter registration, exactly one
    `QApplication.setStyleSheet` per switch, a `QProxyStyle` (themed
    message-box icons, primary-right button order), Windows dark/light
    title bars (DwmSetWindowAttribute, silent on failure), a keyboard-only
    focus-ring event filter, and `notifier.theme_changed` for colours QSS
    can't reach (preview HTML, editor char formats, pixmap labels).
    Variants are dynamic properties (`variant`, `status`) changed via
    `theme.set_property()`, never per-widget `setStyleSheet`. A token
    colour becomes a QColor only through `theme.qcolor()` (translucent
    tokens are `rgba(...)` strings, which QColor's constructor reads as
    invalid and paints black; icons parse them the same way); the hygiene
    check flags any other `QColor(...)` in `app/ui` outside `theme/`. The stored
    choice (settings key `theme`, values `dark`/`light`) is unchanged.
  - `icons.py` — Lucide SVGs (assets/icons/lucide, ISC) rendered by a
    `QIconEngine`; `icons.themed(name, role, checked_role, active_role)`
    resolves token roles at paint time, so icons follow a theme switch by
    themselves. The old glyph names (`campaign`, `close`, ...) are aliases.
  - `thumbnails.py` — image-attachment thumbnail generation.
- `app/telegram/` — Telethon (MTProto) integration:
  - `client_manager.py`, `account_manager.py`, `authentication.py` — client
    lifecycle, multi-account session management/switching. (v1.8)
    `AccountManager.delete_account` calls `ClientManager.log_out` (real,
    server-side Telethon session invalidation, not just closing the local
    connection) before removing the local session file/DB row -- one user
    action covers both "log out" and "remove local account/session";
    best-effort and never blocks local removal if the server call fails
    (offline, already-invalid session). `ClientManager.remove()` also
    closes the session's sqlite connection: constructing a TelegramClient
    opens and locks its `.session` file on Windows, and that handle is
    what makes deleting the file fail with WinError 32. Deletion retries a
    locked file a bounded number of times and then raises
    `AccountDeletionError` rather than silently leaving it behind.
    `check_status` treats `sqlite3.OperationalError` ("database is
    locked", raised by Telethon's own session file under contention) as a
    connection problem, not as `needs_reauth` — it is a timing issue, and
    reporting it as an authorization failure made valid accounts look
    broken.
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
    Chat targets: a `@username` is typed by whatever it resolves to; a
    marked chat ID (`-100…`/`-…`) is looked up in the account's dialogs,
    fetched once per resolver (lazily, before the first chat ID —
    Telethon has no access_hash for a bare ID otherwise; FloodWait there
    propagates like any other); an invite link only goes through
    `CheckChatInviteRequest`, and anything but `ChatInviteAlready` is
    NOT_MEMBER. A positive numeric ID that resolves to a chat is still
    rejected (it has always meant a user). A positive user ID the session
    has no access_hash for (`get_entity` → ValueError — e.g. a person
    picked by ID) triggers the same one-time dialogs read, and the user is
    taken from there; users already in loaded dialogs need no lookup.
    `RecipientResolver(client, dialogs=snapshot)` (passed through
    `CampaignManager(dialog_snapshot=...)` from the session cache) starts
    from the picker's last read and reads the dialogs from Telegram again
    only for an ID missing there — at most once per campaign.
  - `chat_targets.py` — `TargetType` (user/group/supergroup/forum/
    channel), the pure permission preflight `check_send_rights()`
    (channel: creator or `post_messages` admin; group: left/banned/
    `banned_rights`/`default_banned_rights` incl. `send_plain`,
    `send_media` and the granular media flags, expired restrictions
    ignored, multi-part messages refused in slow mode), the send-error →
    reason mapping (by Telethon error class, and by RPC message code for
    errors newer than Telethon 1.36's list), and `list_dialogs()` behind
    the "From my chats…" picker (`load_dialog_snapshot()` returns the
    same list plus every dialog's entity by peer id, for the cache and the
    resolver warm-up): `DialogList` of `DialogTarget`s (type
    incl. bot, title, @username, peer id, archived, last-message date,
    unavailable reason — people/bots writable by default, chats through
    `check_send_rights` for plain text —, folder ids) plus folders from
    `GetDialogFiltersRequest`, mapped with Telegram's own rule order
    (explicit peers, exclusions, archived/read/muted, type flags). Leaves
    out Saved Messages, deleted accounts and 777000 and migrated basic
    groups. Reads only the dialog and folder lists; a folder failure
    (FloodWait included) only hides folders, a FloodWait on the dialogs
    propagates.
  - `template.py` — `{name}` placeholder expansion; works in UTF-16
    surrogate-pair space so formatting-entity offsets stay correct.
  - `service.py`, `qt_bridge.py` — glue between the Telethon client and the
    Qt/qasync event loop. Demo Mode (`enter_demo_mode`/`exit_demo_mode`)
    sets the real ClientManager/AccountManager aside and restores the
    *same objects* on exit, rather than rebuilding them: rebuilding
    orphaned every live TelegramClient, leaving its session file open
    while a new manager opened a second sqlite connection to the same
    file. `purge_demo_accounts()` removes the demo account row on exit and
    again at startup, since v2.0.0 persisted it into the real accounts
    table and never cleaned it up.
  - `demo_client.py` — the simulated backend Demo Mode runs against
    (see ROADMAP v2.0), including a fixed set of simulated chats (real
    Telethon `Chat`/`Channel` objects) set up for each realistic outcome:
    posted, no admin rights, members can't write, no media, forum, and a
    slow-mode chat that starts "just posted to" — and a dialog list with
    people (with and without a @username), bots, archived dialogs, three
    folders, the three dialogs the picker leaves out, and dates; dialog
    people resolve to themselves by @username or ID.
  - `exceptions.py` — Telegram-error taxonomy used by the campaign layer.
- `app/campaign/` — send orchestration:
  - `campaign_manager.py`, `send_queue.py`, `campaign_state.py` — the send
    queue, per-item status/retry (`next_step`-based resume), FloodWait
    pause/resume, and the duplicate-campaign-start guard. Chat targets go
    through the same loop: preflight after resolving, chat-specific
    reasons for send errors, `SlowModeWaitError` fails only that target
    (no pause — it is *not* FloodWait), `{name}` = chat title unless a
    CSV name exists, and a chat already delivered to in this run (or in
    the run a Retry comes from: `delivered_chat_ids`) is SKIPPED, so
    `@name` and `-100…` for the same chat never both get it. Retry also
    passes `resume_steps` (normalized_key → delivered steps) so a partly
    delivered message continues instead of starting over.
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
- `app/recipients/` — `parser.py` (format detection: username/ID/link/phone,
  plus chat targets — `RecipientKind.CHAT_ID` for `-100…`/`-…`/`t.me/c/…`
  and `INVITE_LINK` for `t.me/+…`/`t.me/joinchat/…`; `is_chat_target` is
  only true for those two, since a username may be either; also owns
  `dedupe_recipients`, shared by every import path), `validator.py`,
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
- `app/logging/` — `logger.py` (rotating file logging + secret scrubbing);
  `events.py` (v1.7 structured logging — `EventType`/`log_event()`, one
  JSON object per log line through the same rotating/scrubbing handler,
  wired into `app/campaign/campaign_manager.py` alongside its existing
  human-readable journal messages, never message text/credentials).
- `app/i18n/` — Russian/English translation catalog and lookup:
  `translator.py` (`tr()`/`trn()`, active-language state following the
  same pattern as `app/ui/theme/`'s active-theme state), `strings.py`
  (the catalog itself). A top-level package, not under `app/ui/`, because
  `app/config/settings.py`'s validation-error messages and other non-UI
  layers need it too. Language switches immediately (no restart): every
  persistent widget/page implements `retranslate_ui()`, dispatched from
  `MainWindow.retranslate_ui()` the same way theme switching already
  dispatches `apply_theme()`. Deliberately not gettext or Qt Linguist
  (.ts/.qm + lupdate/lrelease) — this app has no other use for either.
- `tests/` — pytest + pytest-asyncio (`asyncio_mode = auto`), 1162 tests,
  using `tests/mocks/mock_telegram_client.py` and
  `tests/mocks/fake_client_manager.py` instead of a real Telegram
  connection. `tests/conftest.py` has two autouse fixtures: an
  autouse `_block_network` fixture refuses every non-loopback connection
  (socket.connect, asyncio `create_connection` -- the Windows proactor
  loop bypasses socket.connect -- and Telethon's own
  `TelegramBaseClient.connect`) and fails the test at teardown even if
  the code swallowed the error; an autouse `_dispose_top_level_widgets`
  hides and deletes every top-level widget a test leaves behind. Without
  the latter, every later `QApplication.setStyleSheet()` (each MainWindow
  applies its theme) re-polished all leaked windows and the single-process
  suite took hours; with it, ~1 minute. CI runs this suite on `windows-latest` with
  `QT_QPA_PLATFORM=offscreen` (`.github/workflows/tests.yml`).

Packaging: `telegram_mass_sender.spec` (PyInstaller, portable onedir build,
bundles `assets/`), invoked by `build_windows.bat`. (v1.8)
`scripts/generate_version_info.py` generates `version_info.txt` (the
Windows EXE version resource -- CompanyName/FileVersion/ProductName/etc.,
shown in Explorer's file Properties) from `app.version.APP_VERSION` before
each build; gitignored, never hand-edited.

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
to make the suite pass. The current baseline is 1162 passed, 0 failures —
if that number changes, know exactly why before saying the change is done.

**GUI.** Never block the Qt event loop or the asyncio event loop.
Long-running work (network calls, FloodWait waits) must be async/background,
following the existing patterns in `app/telegram/qt_bridge.py` and
`app/campaign/campaign_manager.py`.

**Background tasks.** Every background task needs a defined owner and
somewhere its failure actually lands; otherwise a raising task surfaces
only as asyncio's "Task exception was never retrieved" at collection
time. In `MainWindow` use `self._spawn(coro, description)`, which holds a
reference to the task (asyncio may drop one nothing keeps alive) and
observes its result. Elsewhere, whatever owns the task observes it — the
way `CampaignManager.start()` attaches a done-callback, since nothing
awaits a campaign that ends on its own. `login_dialog.py`'s three
`ensure_future` calls are the one deliberate exception: each coroutine
catches everything itself and writes the failure into the dialog's own
error label, and the dialog is parented to the window (no
`WA_DeleteOnClose`), so it outlives the task and a late callback always
finds a live widget. Observing is not the same as swallowing — do not
wrap a coroutine body in a blanket `except Exception: pass`, which hides
a real failure behind a UI that looks fine.

**Account operations.** Refresh, switch, delete and the Demo Mode
transitions all run under `MainWindow._account_lock`. They share client
instances and session files, and interleaving them is what let a status
refresh rebuild a Telethon client — reopening its session file — in the
middle of a delete, making the delete fail with WinError 32.

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
