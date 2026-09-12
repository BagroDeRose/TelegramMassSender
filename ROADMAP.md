# TelegramMassSender — Product Roadmap

> **This is a planning document.** Checklist items reflect intended scope;
> a checked box means that specific item has been implemented **and**
> verified with tests, not just planned. See `README.md` for what the
> application actually does today, and `CLAUDE.md` for the current
> architecture. As work lands, update the relevant checkboxes here rather
> than letting this drift out of sync with reality — and do not check a
> box for a feature that is only partially implemented.

## Vision

Evolve TelegramMassSender from a functional Windows desktop Telegram
campaign manager into a polished, reliable, multilingual desktop
application suitable for real-world controlled messaging and as a strong
software engineering portfolio project.

The application should remain focused and should NOT become a CRM,
scraping tool, spam/anti-ban system, or general Telegram automation
platform.

---

# v1.4 — Core UX & Media

## Localization

- [x] Add Russian / English UI language switcher — a `QComboBox` next to
      the existing theme combo on the Settings page
      (`app/ui/main_window.py::_build_appearance_settings`), backed by a
      new `app/i18n` package (`translator.py`'s `tr()`/`trn()` catalog
      lookup + `strings.py`'s ~250-entry Russian/English catalog),
      following the same active-state pattern `app/ui/theme.py` already
      uses for the theme combo rather than pulling in gettext or Qt
      Linguist's .ts/.qm + lupdate/lrelease toolchain
- [x] Translate all user-facing UI strings — every `app/ui/*.py` file, plus
      the strings that reach the UI from outside it: `app/config/settings.py`'s
      validation errors, `app/campaign/report_library.py`'s errors,
      `app/telegram/account_manager.py`'s `AccountSwitchBlockedError`,
      `app/telegram/recipient_resolver.py`'s per-recipient status labels,
      and `app/campaign/campaign_manager.py`'s Journal messages/permanent-
      error labels. Deliberately NOT translated: the product name
      ("Telegram Mass Sender" / "Mass Sender") and the generated CSV
      report's own content (a file artifact for the user's records, not a
      UI surface — translating it was never requested and would silently
      expand scope)
- [x] Translate dialogs and confirmation messages — `app/ui/dialogs.py`,
      `login_dialog.py`, and `message_editor_dialog.py`'s unsaved-changes
      prompt, which previously used Qt's stock (untranslated)
      `QMessageBox.StandardButton.Yes/No` -- now converted to the same
      custom-button pattern every other dialog in the app already used, so
      it no longer silently stays in whatever language Qt's own bundled
      translations pick
- [x] Translate validation and error messages
- [x] Translate Campaign / Accounts / Results / Settings / Journal
- [x] Translate empty states
- [x] Persist selected language — reuses the existing (previously dead)
      `AppSettings.language` / `SETTINGS_KEY_LANGUAGE` field, already
      round-tripped by `SettingsRepository`
- [x] Decide whether language switching applies immediately or after
      restart — **immediate**, matching the existing theme switch: every
      persistent widget/page gets a `retranslate_ui()` method, dispatched
      from `MainWindow.retranslate_ui()` the same way `_on_theme_combo_changed`
      already dispatches `apply_theme()`; transient dialogs need no such
      wiring since they read `tr()` fresh each time they're constructed
- [x] Add tests for localization and language persistence — `tests/test_i18n.py`
      (lookup, fallback, Russian 3-way + English 2-way pluralization,
      catalog-completeness checks that every registered key has both
      languages) plus `tests/test_main_window_ux.py` (live language switch
      actually changes already-built widget text, persists across reload,
      and reset-settings doesn't silently flip it)
- [ ] Create English portfolio screenshots — separate README/portfolio
      task, not yet done

## Universal Attachments

- [x] Support arbitrary files as Telegram documents — any unrecognized
      extension falls through to a generic document, never rejected
      (`app/telegram/media_sender.py::AttachmentKind.DOCUMENT`)
- [x] Support JPG/JPEG
- [x] Support PNG
- [x] Support WEBP
- [ ] Support GIF where Telegram/API semantics allow it — GIF is already
      accepted and sent today, but only as a generic document
      (`AttachmentKind.ANIMATION`, deliberately not album-eligible yet).
      Telegram's distinct "animation" send mode (`DocumentAttributeAnimated`)
      is a separate, deferred subtask — see the note below.
- [x] Support common video formats (MP4/MOV/AVI)
- [x] Support PDF
- [x] Support DOC/DOCX
- [x] Support XLS/XLSX
- [x] Support CSV
- [x] Support TXT
- [x] Support ZIP
- [x] Support unknown file types through document upload fallback
- [ ] Detect MIME type — deliberately not added; extension-based detection
      already matches Telethon's own behavior, see CLAUDE.md
- [x] Display filename
- [x] Display file size
- [x] Display appropriate document/file icon — distinct icons for
      video/audio/archive attachments plus the existing generic document
      glyph (`app/ui/icons.py`, wired in `app/ui/attachments_widget.py`);
      PHOTO/ANIMATION/IMAGE_OTHER already get a real decoded thumbnail
      instead and don't need an icon in the normal case
- [x] Generate thumbnails where applicable
- [x] Validate files before campaign start
- [x] Detect missing files
- [x] Detect unreadable files — a lightweight readability probe
      (`Attachment.is_readable()`/`validate_readable()`, opens and reads 1
      byte rather than the whole file) distinguishes a locked/permission-
      denied file from both a healthy one and a missing one
      (`AttachmentUnreadableError`, checked before campaign start
      alongside the existing missing-file check, and in
      `build_media_send_plan` itself)
- [x] Preserve attachment order
- [x] Support mixed attachment types where Telegram allows it
- [x] Add comprehensive attachment tests — classification, per-type icon,
      and drag-to-reorder coverage are all done (`tests/test_attachment_kind.py`,
      `tests/test_icons.py`, `tests/test_attachments_widget.py`)

**Deferred subtask (not v1.4 scope unless separately planned):** native
Telegram semantics for GIF-as-animation and audio-as-voice/audio-message.
Both are more than an extension-table change — they need `media_sender.py`
to pass Telegram-specific attributes through `send_file`/the album path,
which is a real enough change to warrant its own design pass rather than
folding it into the attachment-classification work above. Re-verified
during Stage 4: Telethon 1.36's `send_file` does expose the needed
primitives (`attributes=[DocumentAttributeAnimated()]`, `voice_note=True`),
so this is technically reachable, but audio-as-voice specifically needs a
new *opt-in per-file* UI decision before it could ship — defaulting every
`.mp3` to voice-message semantics (a visually distinct Telegram bubble)
would be a surprising, unrequested behavior change, not a pure enhancement.
Still deferred.

## Attachment UX

- [x] Drag & Drop files into the message/campaign area — dropping local
      files (e.g. from Explorer) directly onto the attachments tile grid
      adds them, in addition to the existing "choose files" dialog
      (`app/ui/attachments_widget.py::_ReorderableListWidget.dropEvent`)
- [x] Drag & Drop to reorder attachments — dragging a tile to a new
      position updates `self._paths` (the single source of truth for send
      order) and rebuilds the tile grid to match; the campaign pipeline
      already consumed `get_attachments()` order with no separate ordering
      mechanism to keep in sync. Each tile (`_AttachmentTile`) detects the
      gesture itself via `grabMouse()`/explicit event acceptance rather
      than a viewport-level event filter, verified directly via
      `QWidget.mouseGrabber()` (Qt's own grab-state introspection) after
      an event-filter-based first attempt was found, via real hardware
      testing, to never receive a real mouse move at all. Click/Ctrl-click/
      Shift-click selection is implemented explicitly against the list's
      `QItemSelectionModel`, and the native `QListWidget::item:selected`
      paint is neutralized in favor of a deliberate `[selected]`-driven
      highlight on the tile itself (`app/ui/attachments_widget.py::_AttachmentTile`,
      `_ReorderableListWidget`). The reorder gesture's *logic* is
      exhaustively covered by automated tests and independently verified
      selection rendering visually in both themes; the physical mouse
      drag itself could not be exercised by this environment's synthetic
      input and was confirmed on real hardware by the project owner.
- [x] Remove attachments individually
- [x] Clear attachment queue
- [x] Improve attachment preview — every tile (including images, which
      previously showed nothing but the thumbnail) now shows a
      `<size> · <TYPE>` line (`app/ui/attachments_widget.py::_meta_text`);
      long filenames already elide with a full-path tooltip; spacing and
      both themes visually re-verified
- [x] Show file type and size — see above
- [x] Show useful validation errors — missing-file and unreadable-file
      errors each name the affected file(s) and, for an unreadable file,
      explain the likely cause and what to do
      (`app/ui/main_window.py::_on_start_requested`)

---

# v1.5 — Message Experience

## Telegram-like Message Preview

- [x] Add visual Telegram-style message preview — a read-only
      `QTextBrowser` rendering (`app/ui/message_preview.py`); simplified,
      not a pixel-perfect Telegram clone by design, but a real rendering
      of the actual formatting, not a mock
- [x] Render rich text entities correctly — bold/italic/underline/strike/
      code/pre/spoiler all render (`entities_to_preview_html`,
      `tests/test_message_preview.py`)
- [x] Render links correctly
- [x] Render emoji correctly — Qt's rich-text renderer displays Unicode
      (including astral-plane/surrogate-pair emoji) natively; verified the
      HTML pipeline doesn't mangle it
- [x] Render attachments in preview — filename list with an icon; not
      per-type thumbnails (would be a real visual overhaul, not requested,
      and the tile grid immediately below the preview already shows those)
- [x] Preview should use the same formatting model as actual sending —
      `entities_to_preview_html` operates on the exact same
      `TypeMessageEntity` objects `app.telegram.sender` sends, not a
      second parallel formatting implementation
- [x] Preview should support personalized messages — see Personalization
      Preview below; the same `expand_name_placeholder()` the real
      per-recipient send path uses now runs before the preview renders

## Personalization Preview

- [x] Support `{name}` preview for selected recipient — implemented as an
      editable "example name" field next to the message editor
      (`app/ui/main_window.py`'s `_preview_name_edit`), not a picker over
      the actual parsed recipient list: `ParsedRecipient` (`app/recipients/parser.py`)
      deliberately carries no name field, and a real recipient's name is
      only known once Telegram resolves them during actual sending (see
      `app.telegram.recipient_resolver`) -- there is no real per-recipient
      name to select from before that. An example name is the only
      technically honest thing to preview with pre-send.
- [x] Allow switching preview recipient — implemented as editing the
      example name (see above); each edit re-renders the preview live
- [x] Show example personalized messages
- [x] Verify UTF-16 entity offsets remain correct after personalization —
      already guaranteed by `app.telegram.template.expand_name_placeholder`
      (unchanged, reused as-is, same function the real send path calls);
      re-verified for the new preview wiring specifically with ASCII/
      Cyrillic/emoji/empty/long example names and a bold-entity-offset
      regression test (`tests/test_main_window_ux.py`), plus a real
      running-app screenshot showing correct bold placement after
      substitution

## Drafts / Presets

- [x] Add message drafts — interpreted as the named-preset feature below
      ("drafts" and "presets" are the same saved-template concept in this
      roadmap section; there is no separate unnamed-autosave mechanism,
      since campaign state already survives app restart via the existing
      recipient/message/attachment fields on the Campaign page)
- [x] Add named message presets — new `presets` SQLite table
      (`app/database/database.py`), `Preset` model
      (`app/database/models.py`), `PresetRepository`
      (`app/database/repositories.py`), and `app/campaign/presets.py`
      (`save_preset`/`list_presets`/`rename_preset`/`delete_preset`/
      `load_preset`); UI wired into the Campaign page as a
      combo box + Load/Save as.../Delete buttons
      (`app/ui/main_window.py`)
- [x] Save message text
- [x] Save formatting — rich-text entities round-tripped through
      Telethon's `.to_dict()`/reconstructed via a name→class map in
      `app/campaign/presets.py`, since Telethon has no built-in
      `from_dict()`
- [x] Save attachments — attachment file paths only (not file contents);
      `load_preset` reports which saved paths still exist vs. are missing
      so a preset survives files moving/being deleted, per the same
      philosophy as the existing missing-file detection on the Campaign
      page
- [x] Optionally save campaign interval/settings — min/max delay seconds
      saved with the preset and restored on load if present
- [x] Load/edit/delete presets — rename is implemented at the repository/
      business-logic layer (`PresetRepository.rename`,
      `presets.rename_preset`) but has no UI entry point yet, since the
      spec's UI mockup only called for Load/Save as.../Delete; load
      warns (via `show_error`) about any attachments that no longer exist
      on disk but still restores everything else
- [x] Do not turn presets into message history — presets are only ever
      created by an explicit "Save as..." action, never auto-saved after
      a send, so the list can't grow into an implicit sent-message log

## Campaign Wizard

- [x] Introduce optional step-by-step campaign workflow — new
      `app/ui/campaign_wizard.py::CampaignWizardDialog`, opened via a
      "Мастер кампании" / "Campaign Wizard" button on the Campaign page
      header (`app/ui/main_window.py`). Every step reuses the exact
      widget classes the existing single-page workflow already uses
      (`RecipientWidget`, `MessageEditorDialog`, `AttachmentsWidget`,
      `MessagePreviewWidget`) — no parsing/validation/formatting logic is
      duplicated in the wizard
- [x] Recipients
- [x] Message
- [x] Attachments
- [x] Sending options — the shared interval (min/max delay) setting;
      there is no other per-campaign "sending option" in this app today
- [x] Preview
- [x] Confirmation
- [x] Sending
- [x] Results
- [x] Preserve a fast workflow for experienced users — interpretation:
      "Sending" and "Results" are the spec's last two steps, but are
      deliberately **not** separate wizard-internal pages. MainWindow
      already owns one live-progress UI (`CampaignControlsWidget` + the
      journal + the Results page) wired to pause/resume/stop and
      FloodWait handling; duplicating that inside a modal wizard dialog
      would either re-implement that machinery or run two UIs off the
      same `CampaignManager` signals at once. Instead, confirming the
      wizard closes it and hands its collected state to `MainWindow`
      (`_on_open_campaign_wizard_clicked`), which writes that state into
      the same live Campaign-page widgets the fast workflow uses and
      calls the exact same start path (`_on_start_requested`) — so
      Sending/Results are the existing Campaign/Results pages, and both
      workflows share one validation/start implementation. The fast,
      single-page workflow itself (Recipients/Message/Attachments/
      Campaign cards) is completely untouched by this feature

---

# v1.6 — Recipient & Campaign Management

## Smart Recipient Import

- [x] Improve TXT import — now shares the same "review problematic rows"
      dialog CSV import gets (see below); its own row-by-row parsing was
      already correct and is unchanged
- [x] Add CSV import — new `app/recipients/csv_importer.py`, an "Импорт
      CSV" button next to the existing "Импорт TXT" on the Campaign page's
      Recipients card
- [x] Automatically detect CSV columns — content-based, not header-based:
      for each row, every cell is tried against the existing
      `parse_recipient_line` (the exact same recognizer the paste box and
      TXT import already use), and the first cell that parses as a valid
      username/ID/phone becomes that row's identifier. This works
      regardless of column order or header names/language, without a
      manual column-mapping UI
- [x] Map username/ID/phone columns — see above; a t.me link is also
      recognized as an identifier if present in a cell
- [x] Map name column to `{name}` — any other non-empty cell in the row
      that does *not* itself parse as a recipient identifier becomes that
      row's display name, stored as a normalized_key -> name override
      (`RecipientWidget.name_overrides()`) and passed into
      `CampaignManager(recipient_names=...)`; a CSV-supplied name takes
      priority over whatever Telegram itself reports as the resolved
      user's first_name for that recipient, since it's the sender's own,
      deliberately supplied data
- [x] Normalize recipient identifiers — reuses `ParsedRecipient.normalized_key`
      (unchanged) for both de-duplication and the name-override lookup key
- [x] Remove duplicates — `app.recipients.parser.dedupe_recipients`, a
      single shared implementation now used by both `parse_recipient_lines`
      (paste box / TXT import) and the new CSV importer
- [x] Show import statistics — the existing total/duplicates/invalid/valid
      summary dialog, now shown for CSV import too
- [x] Show invalid recipients before campaign start — a "Показать ошибки"
      button appears next to the Recipients summary line whenever the
      current list has invalid entries (from typing, pasting, TXT import,
      or CSV import alike), available at any time before Start, not just
      right after an import
- [x] Allow user to review problematic rows — that button opens
      `app.ui.dialogs.show_invalid_rows`, listing each invalid row's raw
      text and its specific reason. This is also what surfaced a
      pre-existing gap: `app.recipients.parser`'s per-row error messages
      were hardcoded Russian literals never routed through the app's
      localization system (`tr()`) added in the Localization stage --
      invisible before because nothing displayed `.error` in the UI.
      Fixed as part of this stage (now real i18n keys) since this feature
      is what makes those messages user-visible for the first time

## Recipient Groups

- [x] Local recipient groups — new `recipient_groups` SQLite table
      (`app/database/database.py`), `RecipientGroup` model
      (`app/database/models.py`), `RecipientGroupRepository`
      (`app/database/repositories.py`), and `app/recipients/groups.py`
      (`save_group`/`list_groups`/`rename_group`/`delete_group`/
      `load_group`) — mirrors `app.campaign.presets`'s structure exactly.
      A group is a named snapshot of the Recipients box's raw text plus
      any CSV-derived `{name}` overrides (`RecipientWidget.name_overrides()`);
      UI wired into the Campaign page's Recipients card as a combo box +
      Load/Save as.../Delete buttons, right below the TXT/CSV import row
- [x] Customers
- [x] Partners
- [x] Test accounts
- [x] Imported lists — the four names above are examples a user can
      choose when saving a group, not built-in categories; nothing in the
      schema or code treats any group name specially
- [x] Rename groups — implemented at the repository/business-logic layer
      (`RecipientGroupRepository.rename`, `groups.rename_group`) but has
      no UI entry point yet, matching the same interpretation already
      recorded for preset rename in the Drafts/Presets section above
- [x] Delete groups
- [x] No CRM functionality — a group carries only its raw recipient text
      and `{name}` overrides; no tags, notes, contact history, or other
      per-recipient metadata

## Campaign Controls

- [x] Pause campaign — already implemented before this stage
      (`CampaignManager.pause`/`CampaignControlsWidget`'s Pause button);
      unchanged here
- [x] Resume campaign — already implemented before this stage; unchanged
- [x] Cancel campaign — already implemented before this stage (the Stop
      button/`CampaignManager.stop`); unchanged
- [x] Show current recipient — new `CampaignManager.current_item_changed`
      signal (item, 1-based position, total), emitted once per recipient
      right as its send begins (never on internal retries -- those don't
      re-dispatch a new queue item); displayed as "Получатель {n} из
      {total}: {recipient}" while a campaign is running
      (`CampaignControlsWidget.set_current_item`)
- [x] Show current campaign step — interpreted as the same position/total
      shown above (this app has no other notion of "step" visible to the
      user within a single recipient's send -- media-plan sub-steps are
      an internal resume mechanism, not user-facing)
- [x] Show progress — already implemented before this stage (progress bar
      + totals line); unchanged
- [x] Show elapsed time — `CampaignControlsWidget` now owns a 1-second
      `QTimer`, started once by `MainWindow` right when a campaign
      actually starts (`start_elapsed_timer`, not on every pause/resume)
      and stopped when it finishes (`stop_elapsed_timer`)
- [x] Estimate remaining time — computed live each tick from the observed
      average time per completed item once at least one has completed
      (`elapsed / done * pending`), falling back to the configured
      min/max interval's midpoint before anything has completed yet
- [x] Calculate approximate campaign duration before start —
      `recipient_count × average configured interval`, shown above the
      Start button and kept live as the Recipients list or the interval
      setting changes (`CampaignControlsWidget.set_recipient_count`/
      `set_interval_summary`); hidden once the campaign is actually
      running (the live elapsed/remaining display takes over)
- [x] Preserve safe partial-progress behavior — none of this touches
      `next_step`-based resume, retry, or FloodWait handling; verified by
      the full existing `test_campaign_manager.py` suite still passing
      unchanged

## Retry

- [x] Retry failed recipients — a new "Неудачные получатели" (Failed
      recipients) section on the Results page, populated once a campaign
      finishes: one checkable row per FAILED `SendItem` (raw identifier +
      its specific error), with "Повторить выбранные"/"Повторить все
      ошибки" buttons. Retrying relaunches through the exact same
      `_start_campaign` the fast workflow, the Campaign Wizard, and Start
      all already share -- one validation/start implementation, not a
      fourth. The message text/formatting/attachments/account reused are
      exactly what was actually sent the first time
      (`MainWindow._last_campaign_context`, captured when that campaign
      started), never whatever currently happens to be sitting in the
      Campaign page's boxes; the sending interval and retry-count are
      re-read fresh from current settings, same as a normal Start
- [x] Allow retry of selected failures — checkboxes per row, "Повторить
      выбранные" enabled only once at least one is checked
- [x] Allow retry of all failures — "Повторить все ошибки", enabled
      whenever there is at least one failed recipient
- [x] Never knowingly resend already-successful campaign steps — only
      `SendItemStatus.FAILED` items are ever offered for retry; SENT/
      SKIPPED items never appear in the list or get included
- [x] Preserve existing FloodWait safety behavior — a retry is a brand
      new `CampaignManager` over a smaller recipient list, going through
      the exact same resolve/send/FloodWait code path as any other
      campaign; nothing here bypasses or shortcuts it
- [x] Test retry behavior extensively — 7 new tests: list population
      (only failed items, correct text/visibility), selected-only vs.
      all-failures relaunch (asserting the exact recipient set passed to
      `_start_campaign`), no-op with no prior campaign context, and
      blocked while another campaign is already active

---

# v1.7 — Results, Diagnostics & Reliability

## Results

- [ ] Improve campaign statistics
- [ ] Sent count
- [ ] Failed count
- [ ] Skipped count
- [ ] Duration
- [ ] Detailed failure categories
- [ ] Filter results
- [ ] Export all results
- [ ] Export only failures
- [ ] Retry failed recipients from Results

## Structured Logging

- [ ] Use structured event types
- [ ] CAMPAIGN_STARTED
- [ ] RECIPIENT_RESOLVED
- [ ] MESSAGE_SENT
- [ ] ATTACHMENT_SENT
- [ ] FLOOD_WAIT
- [ ] RECIPIENT_FAILED
- [ ] CAMPAIGN_COMPLETED
- [ ] Never log credentials
- [ ] Never log message contents
- [ ] Never log sensitive session data

## Diagnostics

- [ ] Add Diagnostics section
- [ ] Application version
- [ ] Python version
- [ ] Telethon version
- [ ] Database status
- [ ] Telegram connection status
- [ ] Session storage status
- [ ] Network status
- [ ] Copy diagnostics
- [ ] Sanitize all diagnostic output

## Diagnostic Bundle

- [ ] Export sanitized diagnostic ZIP
- [ ] Include relevant logs
- [ ] Include application/version information
- [ ] Include sanitized configuration
- [ ] Never include Telegram session files
- [ ] Never include credentials
- [ ] Never include message contents

## Reliability Tests

- [ ] Network disconnect
- [ ] Reconnect
- [ ] FloodWait
- [ ] Partial media send
- [ ] Failure after first media group
- [ ] Application close during campaign
- [ ] Attachment deleted during campaign preparation
- [ ] Unreadable attachment
- [ ] Corrupted file
- [ ] Very large file
- [ ] Long message
- [ ] Unicode / emoji
- [ ] Mixed attachments
- [ ] Concurrent user actions
- [ ] Duplicate campaign start protection

---

# v1.8 — Accounts & Windows UX

## Accounts

- [ ] Rename local account alias
- [ ] Show avatar
- [ ] Show phone number where appropriate
- [ ] Show username
- [ ] Show connection status
- [ ] Reconnect account
- [ ] Log out account
- [ ] Remove local account/session
- [ ] Confirm destructive actions
- [ ] Never persist 2FA password

## Windows Integration

- [ ] System tray support
- [ ] Minimize to tray
- [ ] Campaign completion notification
- [ ] Critical error notification
- [ ] Windows application metadata/version information
- [ ] Verify application icon everywhere

## Accessibility

- [ ] Keyboard navigation
- [ ] Correct tab order
- [ ] Accessible names
- [ ] Useful tooltips
- [ ] UI scaling support
- [ ] Adequate contrast
- [ ] Verify light/dark themes

---

# v2.0 — Demo & Distribution

## Demo Mode

- [ ] Add fully local Demo Mode
- [ ] No Telegram authentication required
- [ ] No real messages sent
- [ ] Simulated recipients
- [ ] Simulated campaign progress
- [ ] Simulated success/failure results
- [ ] Allow recruiter/user to explore the application safely
- [ ] Clearly indicate Demo Mode

## Onboarding

- [ ] First-run welcome screen
- [ ] Explain basic workflow
- [ ] Add account
- [ ] Add recipients
- [ ] Write message
- [ ] Add attachments
- [ ] Preview
- [ ] Start campaign
- [ ] Optional skip button

## Release Engineering

- [ ] Automated Windows build in GitHub Actions
- [ ] Run full test suite
- [ ] Build PyInstaller application
- [ ] Produce release artifact
- [ ] Generate SHA-256 checksum
- [ ] Publish GitHub Release
- [ ] Keep manual release as fallback
- [ ] Never publish secrets/session data

---

# Cross-cutting Engineering Goals

- [ ] Maintain modular architecture
- [ ] Keep UI independent from Telegram transport logic
- [ ] Keep attachment abstraction generic
- [ ] Preserve async/qasync architecture
- [ ] Preserve UTF-16 Telegram entity correctness
- [ ] Preserve Windows DPAPI credential protection
- [ ] Preserve safe FloodWait handling
- [ ] Preserve graceful shutdown
- [ ] Preserve partial-send protection
- [ ] Maintain strong regression test coverage
- [ ] Keep application history intentionally limited
- [ ] Avoid unnecessary database persistence
- [ ] Avoid collecting sensitive user data

---

# Explicit Non-Goals

Do NOT turn TelegramMassSender into:

- [ ] CRM
- [ ] Telegram scraping platform
- [ ] Spam automation platform
- [ ] Anti-ban system
- [ ] Flood/limit bypass system
- [ ] Proxy rotation system
- [ ] Contact scraping/import automation
- [ ] Mass account management platform
- [ ] General Telegram bot framework
- [ ] Linux/macOS application unless explicitly reconsidered
- [ ] Web application
- [ ] Docker-based deployment

---

# Portfolio Goals

- [ ] Keep README English-first
- [ ] Keep Russian documentation available
- [ ] Maintain English UI screenshots
- [ ] Keep architecture diagram updated
- [ ] Keep engineering highlights updated
- [ ] Document major technical decisions
- [ ] Keep CI green
- [ ] Keep release artifacts reproducible
- [ ] Maintain honest AI-assisted development disclosure
