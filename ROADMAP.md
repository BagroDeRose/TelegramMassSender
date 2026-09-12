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

- [x] Improve campaign statistics
- [x] Sent count — already shown via the existing stat cards; unchanged
- [x] Failed count — already shown via the existing stat cards; unchanged
- [x] Skipped count — already shown via the existing stat cards; unchanged
- [x] Duration — frozen once, right when the campaign finishes
      (`CampaignControlsWidget.elapsed_seconds()`, read into
      `MainWindow._last_campaign_duration_seconds` since the live timer
      keeps counting up afterward and can't be re-read later); shown on
      the Results page, survives a language switch
- [x] Detailed failure categories — the current campaign's FAILED items
      grouped by their (already-localized) error message, e.g.
      "Пользователь не найден: 2; Заблокирован: 1" — reuses the exact
      error text already produced by `app.campaign.campaign_manager`, no
      new categorization taxonomy invented
- [x] Filter results — the Retry section (v1.6) is now a general
      recipient-results browser: a filter combo (Все/Отправлено/Ошибки/
      Пропущено), defaulting to "Ошибки" to preserve Retry's original
      behavior exactly. Only FAILED rows are ever checkable, regardless
      of which filter is active, so "select failures to retry" stays well
      defined even under the "Все" filter
- [x] Export all results — already implemented before this stage
      (`_on_export_report_requested`/"Экспорт CSV-отчёта"); unchanged
- [x] Export only failures — new "Экспортировать только ошибки" button,
      reuses the existing `write_csv_report` (already generic over any
      `List[SendItem]`) over just the FAILED subset -- no new export
      implementation
- [x] Retry failed recipients from Results — already implemented in the
      Campaign Controls/Retry stages (v1.6); "Повторить все ошибки" now
      always retries every actual failure regardless of the active
      filter, not just what happens to be visible

## Structured Logging

- [x] Use structured event types — new `app/logging/events.py`
      (`EventType` enum + `log_event()`); one JSON object per log line,
      written through the exact same rotating, secret-scrubbing handler
      `app/logging/logger.py` already sets up -- one logging pipeline,
      not a second log file. Wired into `app/campaign/campaign_manager.py`
      alongside (not replacing) its existing human-readable journal
      messages
- [x] CAMPAIGN_STARTED — recipient count, configured interval, max
      retries, emitted once at the top of `_run()`
- [x] RECIPIENT_RESOLVED — emitted right after a recipient successfully
      resolves, before the send is attempted
- [x] MESSAGE_SENT — emitted once a `SendItem` reaches `SENT`
- [x] ATTACHMENT_SENT — emitted alongside `MESSAGE_SENT` whenever the
      campaign has attachments, with the delivered-step count; this app's
      send pipeline doesn't expose a separate per-attachment callback
      (attachments are sent as part of one recipient's send, not as
      discrete steps CampaignManager watches individually), so this is
      the honest granularity available without a deeper rework of
      `app.telegram.sender`/`media_sender`
- [x] FLOOD_WAIT — wait duration + the recipient in flight when it hit,
      emitted from the same `_handle_flood_wait` both the resolve-step
      and the send-step already share
- [x] RECIPIENT_FAILED — emitted once a `SendItem` reaches `FAILED`
      (covers resolve failure, permanent errors, exhausted retries, and
      the critical-error path), with the same already-localized error
      text the journal already shows
- [x] CAMPAIGN_COMPLETED — emitted once per run in `_run()`'s `finally`
      block (covers COMPLETED/STOPPED/ERROR alike, not just the
      happy-path finish), with final sent/failed/skipped/total counts
- [x] Never log credentials — no event ever carries API ID/Hash, a
      password, or session data; verified by a dedicated test asserting
      no event's fields include `password`/`api_hash`/`session`
- [x] Never log message contents — no event field ever carries the
      message text/entities, only counts and recipient display labels
      (already logged today via the existing journal messages)
- [x] Never log sensitive session data — same `SecretScrubbingFilter`
      every other log line already goes through applies to these lines
      too, since they're written via the same logger

## Diagnostics

- [x] Add Diagnostics section — a new "Диагностика" card on the Settings
      page (after Advanced), a read-only text block plus Copy/Refresh
      buttons; new `app/diagnostics.py` (`collect_diagnostics`/
      `format_diagnostics_text`) and `app/version.py` (`APP_VERSION`,
      the single source of truth for the version shown here). Placed in
      Settings rather than a new sidebar page -- adding a 5th nav item
      would have touched page-index bounds checking, persisted
      `last_page_index`, and sidebar wiring in several places for a
      read-only status panel that fits the existing card-based Settings
      layout just as well
- [x] Application version — `app.version.APP_VERSION`, currently the
      last actually-tagged release (`1.3.0`); bumped only when a real
      release is cut, the same way semantic versioning always works
      between releases (the in-progress v1.4-v1.7 work here is an
      internal roadmap label, not yet a shipped version)
- [x] Python version — `platform.python_version()`
- [x] Telethon version — `telethon.__version__`
- [x] Database status — a real `SELECT 1` against the live database
      connection, not just "assume it's fine"; reports the actual error
      text if it fails, and every other diagnostic field still reports
      something (rather than the whole report crashing) if the database
      turns out to be unreachable
- [x] Telegram connection status — reuses the exact same "is an account
      currently active" signal already shown in the status bar's
      connection indicator, so Diagnostics never claims a different
      notion of "connected" than the rest of the app already shows
- [x] Session storage status — counts how many accounts have a session
      *file* present on disk vs. missing (`Path.exists()` only -- file
      contents are never read)
- [x] Network status — reads the active Telegram client's own
      `is_connected()` state (a local, synchronous check Telethon already
      maintains, not a new network probe/ping mechanism); reports
      "Unknown" rather than fabricating a check when no client exists
- [x] Copy diagnostics — "Копировать диагностику" button, writes the
      same text shown on screen to the system clipboard
- [x] Sanitize all diagnostic output — no field ever reads API ID/Hash,
      a password, session file contents, or message text; verified by a
      dedicated test asserting none of those ever appear in the
      formatted report

## Diagnostic Bundle

- [x] Export sanitized diagnostic ZIP — new `app/diagnostic_bundle.py`
      (`export_diagnostic_bundle`), an "Экспорт диагностического пакета"
      button next to Copy/Refresh on the Diagnostics card. Built entirely
      from already-sanitized sources -- nothing new to redact here
- [x] Include relevant logs — the same rotating log files
      `app/logging/logger.py` already scrubs of secrets at write time
      (`application.log` + rotated backups), included as-is
- [x] Include application/version information — `diagnostics.txt`, the
      same report the Diagnostics card shows (app/Python/Telethon
      versions, DB/Telegram/session/network status)
- [x] Include sanitized configuration — `settings.json`, a plain dump of
      `AppSettings` (interval, retry count, theme, language, window
      geometry, reports directory, etc.); nothing to sanitize out since
      API ID/Hash live in `app.security.secure_storage`, a separate
      DPAPI-encrypted file, never in `AppSettings`
- [x] Never include Telegram session files — `app.config.paths.get_sessions_dir()`
      is never read by this module
- [x] Never include credentials — API ID/Hash/2FA password are never in
      any of the three sources this bundle draws from
- [x] Never include message contents — message text/entities are never
      persisted in `AppSettings` or the logs to begin with; verified by a
      dedicated test scanning every file in the exported ZIP

## Reliability Tests

This section is an audit against the existing test suite, not a new
feature -- for each item below, existing coverage was checked first, and
new tests were written only where a genuine gap existed (`app/telegram/client_manager.py`
had *no* dedicated test file before this pass, despite being a real,
previously-untested module).

- [x] Network disconnect — `tests/test_client_manager.py` (new): a
      client whose `is_connected()` flips to `False`, simulating a real
      drop; a transient `ConnectionError`/`OSError`/timeout mid-send is
      already covered by `tests/test_campaign_manager.py`'s existing
      retry-with-backoff tests
- [x] Reconnect — `tests/test_client_manager.py::test_reconnect_after_a_simulated_network_drop`:
      the next `connect()` call after a simulated drop must actually
      reconnect, not silently no-op because a client object already
      exists
- [x] FloodWait — already extensively covered before this stage
      (`tests/test_campaign_manager.py`, `tests/test_recipient_resolver.py`,
      `tests/test_campaign_controls.py`); unchanged
- [x] Partial media send — already covered before this stage
      (`test_transient_error_after_first_of_two_steps_does_not_resend_first_step`,
      `test_send_media_plan_resumes_from_start_step`); unchanged
- [x] Failure after first media group — already covered before this
      stage (`test_floodwait_after_first_of_two_steps_does_not_resend_first_step`);
      unchanged
- [x] Application close during campaign — new
      `tests/test_main_window_shutdown.py` tests: declining the
      confirmation keeps the window open with no shutdown started;
      confirming stops the active campaign before completing shutdown
- [x] Attachment deleted during campaign preparation — new
      `tests/test_main_window_ux.py::test_start_blocked_by_an_attachment_deleted_after_being_added`
      (a file added while it existed, removed before Start is clicked)
- [x] Unreadable attachment — already covered before this stage (v1.4
      Stage 4a: `tests/test_media_sender.py`,
      `tests/test_main_window_ux.py::test_start_blocked_by_an_unreadable_attachment`);
      unchanged
- [x] Corrupted file — already covered before this stage
      (`tests/test_thumbnails.py::test_make_thumbnail_returns_none_for_corrupted_image`,
      `tests/test_presets.py`'s corrupted-JSON tests); unchanged
- [x] Very large file — new `tests/test_thumbnails.py` tests:
      `format_file_size` at GB scale, and proof that `make_thumbnail`
      requests a small scaled decode target regardless of how large the
      source image reports itself (never a full-resolution decode)
- [x] Long message — new `tests/test_template.py` test: a message well
      past `TEXT_MESSAGE_MAX_LENGTH` (4096 chars) with Unicode/emoji
      still expands `{name}` correctly and keeps a trailing entity
      aligned. This app does not truncate/split long messages itself
      (Telegram's own API is the one authority on that limit) -- adding
      auto-splitting would be a new feature, not a reliability fix, and
      was not implemented
- [x] Unicode / emoji — already extensively covered before this stage
      across `tests/test_template.py`, `tests/test_media_formatting.py`,
      `tests/test_message_editor.py`, `tests/test_message_preview.py`;
      unchanged
- [x] Mixed attachments — already covered before this stage
      (`test_photo_plus_video_uses_album_path`,
      `test_photo_plus_document_does_not_album_but_keeps_caption` in
      `tests/test_media_formatting.py` -- different attachment kinds
      mixed in one send, both the album-eligible and non-album cases);
      unchanged
- [x] Concurrent user actions — already covered before this stage,
      spread across the specific actions that can race: double-clicking
      Start (`test_double_click_start_does_not_launch_two_campaigns`),
      double-clicking account switch
      (`test_duplicate_switch_clicks_are_ignored_while_in_flight`), and
      retrying while a campaign is already active
      (`test_retry_blocked_while_a_campaign_is_already_running`, v1.6);
      `CampaignStateMachine` also structurally rejects invalid
      concurrent state transitions regardless of UI click timing
      (`test_state_machine_rejects_invalid_transition`)
- [x] Duplicate campaign start protection — already covered before this
      stage (`test_double_click_start_does_not_launch_two_campaigns`,
      the TOCTOU race fix documented in `CLAUDE.md`); unchanged

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
