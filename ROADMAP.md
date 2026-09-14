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
- [x] Create English portfolio screenshots — all 6 of `docs/images/`'s
      screenshots regenerated against the current UI, in English, with
      only synthetic data (no real accounts/recipients/personal info);
      see the release-candidate documentation stage for the full account

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
      `QWidget.mouseGrabber()` (Qt's own grab-state introspection).
      Click/Ctrl-click/Shift-click selection is implemented explicitly
      against the list's `QItemSelectionModel`, and the native
      `QListWidget::item:selected` paint is neutralized in favor of a
      deliberate `[selected]`-driven highlight on the tile itself
      (`app/ui/attachments_widget.py::_AttachmentTile`,
      `_ReorderableListWidget`).
      **Correction (re-audited after a user report that reordering was
      still unreliable in practice):** a real bug survived the stage
      described above -- `_on_tile_reorder_requested` reused the drop
      target's row index as a raw insertion index straight from the
      pre-drop list, so the *same* drop gesture (release directly on a
      given tile) landed the dragged item *after* that tile for a forward
      drag but *before* it for a backward drag -- confirmed and quantified
      by replaying every (source, target) pair over a 4-item list, all 12
      of which showed this exact asymmetry. Fixed by re-locating the drop
      target by stable path identity *after* the source is removed, so
      "drop on tile X" now always means "insert immediately before X,"
      regardless of drag direction; a drop past the last tile (an invalid
      `indexAt()` hit) is a distinct "true append" case handled via its
      own sentinel. Regression tests now exercise this through a real
      `QDropEvent` dispatched into `_ReorderableListWidget.dropEvent()`
      itself (not just the handler called directly), and assert the
      direction-independence invariant explicitly
      (`tests/test_attachments_widget.py`). Real OS-level mouse-drag
      injection still cannot be exercised by this project's automated/
      sandboxed environments -- verified instead via real Qt rendering
      (`QWidget.grab()`) of an actual drop event's before/after tile
      layout, cross-checked against `get_attachments()`'s send order to
      confirm the two never diverge.
- [x] Remove attachments individually
- [x] Clear attachment queue
- [x] Improve attachment preview — every tile (including images, which
      previously showed nothing but the thumbnail) now shows a
      `<size> · <TYPE>` line (`app/ui/attachments_widget.py::_meta_text`);
      long filenames already elide with a full-path tooltip; spacing and
      both themes visually re-verified.
      **Correction (re-audited after a user report of a stray dashed/
      dotted outline on a selected tile in dark theme):** root cause was
      Qt's native "current item" focus indicator
      (`QStyle::PE_FrameFocusRect`), which `QAbstractItemView` paints for
      whichever item is current -- selecting a tile also makes it the
      list's current item -- and which `theme.py`'s QSS never disabled
      (`border: none` suppresses the native selection background, but not
      this separate focus-rect paint step; only the `outline` QSS
      property does). Fixed by adding `outline: none` to the
      `#attachmentsList` item rules. Confirmed via a `QProxyStyle` probe
      counting real `PE_FrameFocusRect` draw calls on an actually-shown,
      actually-selected tile (2 calls before the fix, 0 after) -- a
      direct, code-level check of Qt's own style machinery, chosen over
      screenshot comparison after the sandbox's offscreen rasterizer
      proved too subtle/font-dependent to eyeball reliably. Regression
      test in `tests/test_attachments_widget.py`.
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
      button next to Copy/Refresh on the Diagnostics card
- [x] Include relevant logs — the same rotating log files
      `app/logging/logger.py` already scrubs of secrets at write time
      (`application.log` + rotated backups), included as-is
- [x] Include application/version information — `diagnostics.txt`, the
      same report the Diagnostics card shows (app/Python/Telethon
      versions, DB/Telegram/session/network status)
- [x] Include sanitized configuration — `settings.json`, a dump of
      `AppSettings` (interval, retry count, theme, language, window
      geometry, reports directory, etc.). API ID/Hash live in
      `app.security.secure_storage`, a separate DPAPI-encrypted file,
      never in `AppSettings`, so there's nothing to strip out on that
      front. **Correction (release-candidate audit):** this bundle was
      never actually generated and inspected end-to-end before now --
      doing so surfaced a real gap the "nothing to sanitize" claim above
      had missed: a user-customized `reports_directory` is very often
      somewhere under the user's own Windows profile (e.g. Documents),
      which embeds their Windows account name. `_sanitize_reports_directory()`
      now redacts that `C:\Users\<name>\` segment specifically for this
      export (every other use of the setting still sees the real path)
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

- [x] Rename local account alias — new `accounts.local_alias` column
      (migrated in for existing installs by `Database._migrate`, since
      `CREATE TABLE IF NOT EXISTS` alone never reaches a table that
      already exists), `AccountRepository.rename`/`AccountManager.rename_account`,
      and a pencil-icon button on each account card
      (`app/ui/account_widget.py`) opening a `QInputDialog` (matching the
      existing saved-report rename pattern in `main_window.py`). Distinct
      from `display_name` (Telegram's own profile name, refreshed from
      the server) -- the alias is purely local and takes priority over it
      when set; a blank alias clears back to the default. Not gated by
      the mid-campaign account-switch guard, since renaming a local label
      doesn't affect the active session
- [x] Show avatar — initial-letter avatar (`app/ui/icons.py::avatar_pixmap`),
      already implemented before this stage
- [x] Show phone number where appropriate — always shown on the account
      card unless it would just repeat the title (i.e. no alias/display
      name set, so the phone already *is* the title)
- [x] Show username — `@username` shown on the card when present, already
      implemented before this stage
- [x] Show connection status — connected/connection-problem/reauth-required/
      not-authorized, each with distinct text and color
      (`_status_text_and_variant`), already implemented before this stage
- [x] Reconnect account — already implemented before this stage
- [x] Log out account — `AccountManager.delete_account` now calls
      `ClientManager.log_out` (Telethon's own `log_out()`, which actually
      invalidates the session on Telegram's servers) before removing the
      local session file/DB row; `disconnect()` alone (the previous
      behavior) only closed the local connection and left the session
      technically still valid server-side. Best-effort and never blocks
      local removal -- an unreachable network or an already-invalid
      session still lets the account be removed from the app
- [x] Remove local account/session — same action as "Log out" above (one
      user action, the account card's delete button); already implemented
      before this stage, now paired with a real server-side logout too
- [x] Confirm destructive actions — `confirm_delete_account` dialog before
      any delete, already implemented before this stage
- [x] Never persist 2FA password — `login_dialog.py` discards the entered
      password immediately after use; never written to disk, settings, or
      logs, already the case before this stage

## Windows Integration

- [x] System tray support — `MainWindow._setup_system_tray` creates a
      `QSystemTrayIcon` (the same `assets/icons/app.ico`) with a Show/Exit
      context menu; only actually shown when
      `QSystemTrayIcon.isSystemTrayAvailable()` (false under this
      project's offscreen test platform, so nothing leaks a real icon
      during the test suite). Left/double-click restores the window
- [x] Minimize to tray — minimizing hides the window from the taskbar
      entirely (restorable via the tray icon) rather than leaving a
      minimized entry there, only when a tray actually exists to restore
      it from. The actual `hide()` is deferred one event-loop tick via
      `QTimer.singleShot(0, ...)` -- calling it synchronously from inside
      `changeEvent` loses a real reentrancy race against the window
      manager's own in-progress minimize transition (confirmed directly:
      the window stayed visible despite `hide()` being called). Maximized
      state is remembered and restored correctly
- [x] Campaign completion notification — a native tray notification on
      `CampaignStatus.COMPLETED`, in addition to the existing status-bar
      message; a user-initiated Stop does not notify (not a completion or
      an error)
- [x] Critical error notification — a native tray notification on
      `CampaignStatus.ERROR`, alongside the existing modal error dialog
      (the dialog alone wouldn't be seen if the window is minimized to
      tray)
- [x] Windows application metadata/version information —
      `scripts/generate_version_info.py` generates the PyInstaller
      version-resource file (`version_info.txt`, gitignored, regenerated
      at build time from `app.version.APP_VERSION`) embedded via the
      `.spec`'s `EXE(..., version=...)`; shows CompanyName/
      FileDescription/FileVersion/ProductName/ProductVersion/
      LegalCopyright in Windows Explorer's file Properties dialog.
      Generated rather than hand-maintained so it can't drift from
      `APP_VERSION` -- PyInstaller's version-file format only accepts a
      single `eval()`'d expression (confirmed from its own loader source),
      which rules out a plain `from app.version import APP_VERSION`
      inside the file itself
- [x] Verify application icon everywhere — `assets/icons/app.ico` already
      carries six real embedded resolutions (16-256px, confirmed via
      `QIcon.availableSizes()`), is set as the `QApplication`'s window
      icon before any window is constructed (so every dialog/QMessageBox
      inherits it automatically -- confirmed no dialog overrides it), and
      is the EXE's taskbar icon via the `.spec`'s `icon=` parameter

## Accessibility

- [x] Keyboard navigation — audited: every standard Qt input (buttons,
      combos, line edits, list widgets) is already keyboard-navigable by
      default. The one real gap was `_AttachmentTile`
      (`app/ui/attachments_widget.py`): a plain `QWidget` with no focus
      policy at all, reachable only by mouse. Now `StrongFocus`, with
      Space toggling that tile's selection (matching
      `QAbstractItemView`'s own convention) and Delete/Backspace removing
      it -- both real keyboard equivalents of the existing mouse
      gestures, not new unrelated features
- [x] Correct tab order — no page in this app explicitly overrides Qt's
      default (creation-order) tab sequence anywhere
      (`grep setTabOrder` -> no matches); verified sensible for the
      Campaign page's top-to-bottom field flow, which is where it matters
      most
- [x] Accessible names — audited every icon-only button (no visible
      text, so nothing for a screen reader to read without one) across
      `app/ui/*.py`: `account_widget.py`'s rename/delete buttons and
      `journal_widget.py`'s collapse button now set `setAccessibleName`
      alongside their existing tooltip. `_AttachmentTile` also gets
      `setAccessibleName`/`setAccessibleDescription` (filename / size+type)
      since it's a composite widget with no text of its own. Every other
      `QToolButton` in the app already has real visible text, which Qt
      uses as the accessible name automatically
- [x] Useful tooltips — already extensive before this stage (every
      icon-only or non-obvious control already had one); unchanged here
- [x] UI scaling support — Qt 6 (PySide6 6.8) enables per-monitor
      high-DPI scaling by default with no opt-in attribute needed (the
      old `AA_EnableHighDpiScaling`/`AA_UseHighDpiPixmaps` are Qt 6
      no-ops); confirmed `app/main.py` doesn't disable it, and every
      fixed pixel size in the UI (e.g. attachment tile dimensions) is in
      logical pixels, which Qt scales automatically per-monitor
- [x] Adequate contrast — new `tests/test_color_contrast.py`: a real WCAG
      2.1 contrast-ratio calculation (not a guess) against `theme.py`'s
      actual token values, applying the correct threshold per each
      token's real usage (4.5:1 normal text for primary/secondary body
      text and error/warning messages; 3:1 for large-scale text like
      `QLabel#statValue`'s 26px numbers and non-text UI components like
      borders) -- all pass in both themes except one **known, tracked
      gap**: the dark theme's primary-button text (white on `$accent`,
      14px bold) measures 2.70:1, short of even the 3:1 large-text floor.
      Investigated and deliberately not "fixed" by darkening `$accent`:
      that token is also used as *text* color elsewhere against dark
      backgrounds (links, checked nav state, card counts -- currently a
      comfortable 5.7-6.6:1), and darkening it enough to fix the button
      would drop every one of those to a new, worse near-3:1 shortfall --
      trading one gap for several rather than fixing anything. A real fix
      needs a second, purpose-built "button text" token, which is a
      small design-system change outside this stage's scope; tracked by
      a test that fails loudly if the ratio changes in either direction
      without this note being updated, not silently ignored
- [x] Verify light/dark themes — `tests/test_color_contrast.py` checks
      both themes explicitly (not just dark); `tests/test_theme.py`
      already covered structural parity (every themed selector exists in
      both) before this stage

---

# v2.0 — Demo & Distribution

## Demo Mode

- [x] Add fully local Demo Mode — new `app/telegram/demo_client.py`
      (`DemoTelegramClient`/`DemoClientManager`, duck-compatible with
      Telethon/`ClientManager` for exactly the surface this app calls)
      and `TelegramService.enter_demo_mode()`, which swaps in a
      `DemoClientManager` and seeds one pre-authorized demo account --
      no real network connection ever opens. Reachable from the Accounts
      page ("Попробовать демо-режим" next to "+ Добавить аккаунт") or
      from the first-run `OnboardingDialog`
- [x] No Telegram authentication required — `enter_demo_mode()` never
      reads or writes `SecureStorage`/real API credentials; the demo
      account is already-authorized by construction
      (`DemoTelegramClient.is_user_authorized()` always returns `True`)
- [x] No real messages sent — `DemoTelegramClient` never opens a socket;
      `send_message`/`send_file`/album sending are entirely fabricated
      locally
- [x] Simulated recipients — any recipient the user types resolves
      through the real, unmodified `RecipientResolver` against
      `DemoTelegramClient.get_entity`, which fabricates a plausible fake
      `User` (or a realistic "not found" failure) for any identifier
- [x] Simulated campaign progress — proven end-to-end: an unmodified,
      real `CampaignManager` runs a full campaign directly against
      `DemoTelegramClient` in
      `tests/test_demo_mode.py::test_a_real_campaign_runs_to_completion_against_the_demo_client`
- [x] Simulated success/failure results — `DemoTelegramClient.FAILURE_RATE`
      (12%) gives a realistic mix, high enough to exercise retry/results/
      diagnostics without making the demo feel broken
- [x] Allow recruiter/user to explore the application safely — reachable
      at any time from the Accounts page, not just first-run onboarding;
      blocked (like account switching) only while a real campaign is
      already active, same guard as switching/deleting an account
- [x] Clearly indicate Demo Mode — a persistent, high-contrast banner
      (`$warning`/`$warning_soft` tokens) spanning the full width above
      the entire app shell, with its own "Выйти из демо-режима"/"Exit
      Demo Mode" button; visually verified in both themes
      (`window.grab()`)

## Onboarding

- [x] First-run welcome screen — new `app/ui/onboarding_dialog.py`
      (`OnboardingDialog`), shown once by `MainWindow.maybe_show_onboarding()`
      when `AppSettings.onboarding_completed` is `False`. Deliberately
      NOT called from `MainWindow.__init__` -- a blocking modal dialog
      started mid-construction would hang every test that constructs
      `MainWindow` directly, since a fresh test database's
      `onboarding_completed` is always `False`; only `app/main.py`'s real
      entry point calls it, once, right after `window.show()`
- [x] Explain basic workflow — the dialog lists all six steps below, in
      order
- [x] Add account
- [x] Add recipients
- [x] Write message
- [x] Add attachments
- [x] Preview
- [x] Start campaign
- [x] Optional skip button — "Пропустить"/"Skip", alongside "Начать"/
      "Get Started" (opens the real `LoginDialog`) and "Попробовать
      демо-режим"/"Try Demo Mode" (activates Demo Mode, see above); any
      choice persists `onboarding_completed = True` so the dialog never
      shows again

## Release Engineering

- [x] Automated Windows build in GitHub Actions — new
      `.github/workflows/release.yml`, triggered by pushing a `v*` tag
      (additive to `tests.yml`, which still runs on every push/PR)
- [x] Run full test suite — the workflow's first real step, `pytest
      tests/ -v`; a release is never built from code that hasn't just
      passed in that exact CI run
- [x] Build PyInstaller application — `python -m PyInstaller
      telegram_mass_sender.spec --noconfirm`, the same spec (and thus
      the same `scripts/generate_version_info.py`-generated version
      resource, app icon, bundled `assets/`) the manual process uses
- [x] Produce release artifact — `dist/TelegramMassSender/*` compressed
      to `TelegramMassSender-Windows.zip`, matching the existing
      v1.0.0-v1.3.0 manual releases' asset naming
- [x] Generate SHA-256 checksum — computed via `Get-FileHash`, published
      alongside the artifact as `TelegramMassSender-Windows.zip.sha256`
- [x] Publish GitHub Release — `gh release create` with
      `--generate-notes` (GitHub's own commit-based auto-changelog since
      the previous tag; `actions/checkout`'s `fetch-depth: 0` is required
      for this to see that history at all)
- [x] Keep manual release as fallback — `build_windows.bat` and a
      hand-run `gh release create` are both untouched; nothing about the
      automated workflow removes or requires them
- [x] Never publish secrets/session data — an explicit verification step
      scans the built output for `*.session`/`*.session-journal`/
      `secrets.dat`/`*.env`/`*.log` and refuses to publish if any are
      found, before the release step ever runs. Defense in depth: a
      GitHub-hosted runner is a fresh checkout with no real credentials
      or session files ever present to begin with, but the checklist
      item says "never," not "shouldn't," so this verifies rather than
      assumes

---

# Cross-cutting Engineering Goals

These are ongoing properties of the codebase, not one-time deliverables
-- checked here because each is currently true and verified (not because
there's nothing left to watch), re-verified as part of this stage's
audit rather than assumed to still hold from when each was first built:

- [x] Maintain modular architecture — `app/ui`/`app/telegram`/`app/campaign`/
      `app/recipients`/`app/security`/`app/config`/`app/database`/
      `app/logging`/`app/i18n` stay separated by concern, per `CLAUDE.md`
- [x] Keep UI independent from Telegram transport logic — `app/ui/*.py`
      never imports Telethon directly; it goes through
      `app/telegram/service.py`/`account_manager.py`/`client_manager.py`
- [x] Keep attachment abstraction generic — `AttachmentKind` stays a
      closed, extension-based classification table read by both
      `media_sender.py` and the UI, not duplicated
- [x] Preserve async/qasync architecture — every network call stays on
      the shared qasync loop; nothing blocks the Qt event loop
- [x] Preserve UTF-16 Telegram entity correctness — `template.py`/
      `message_editor.py`/`message_preview.py` all still do entity-offset
      math in surrogate-pair space
- [x] Preserve Windows DPAPI credential protection — `app/security/dpapi.py`/
      `secure_storage.py` unchanged; API ID/Hash still never touch plain
      config, logs, or exception messages
- [x] Preserve safe FloodWait handling — still waited out or cleanly
      aborted everywhere it can occur (resolve and send alike), never
      bypassed
- [x] Preserve graceful shutdown — `MainWindow._perform_shutdown`/the
      `close_event` mechanism (`tests/test_main_window_shutdown.py`)
      unchanged
- [x] Preserve partial-send protection — `next_step`-based resume in
      `campaign_manager.py`/`media_sender.py` unchanged
- [x] Maintain strong regression test coverage — 678 tests, 0 failures,
      CI green (this stage alone added 86: 5 for the two attachment bug
      fixes, 81 across v1.8/v2.0)
- [x] Keep application history intentionally limited — presets/groups/
      saved reports are still only ever created by an explicit user
      action, never auto-logged
- [x] Avoid unnecessary database persistence — the only new persisted
      fields this stage (`accounts.local_alias`, `onboarding_completed`)
      are both small, explicit, user-facing settings, not new implicit
      history
- [x] Avoid collecting sensitive user data — Demo Mode's simulated
      recipients/results never touch a real network or real personal
      data; nothing new here reads message contents or personal info
      beyond what campaign sending already required

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

# Known Issues

None currently open. One issue was flagged, investigated, and retracted
during this stage after finding its actual cause:

- **Retracted: Accounts page "+ Add account" button partial-text
  glitch.** Originally flagged as a possible real, pre-existing
  rendering bug (reproducible via `window.grab()` after
  `AccountWidget.set_accounts()` populated a card) and even seemed to
  survive a `git stash` check against unmodified `main`. Root-caused
  further: it was an artifact of the verification script itself, not
  the app. The script reused one `asyncio` event loop across several
  `loop.run_until_complete(...)` calls; `MainWindow.__init__` and
  `_enter_demo_mode()` each independently schedule their own
  `asyncio.ensure_future(self._refresh_accounts())`, and driving a
  shared loop forward again later let those orphaned tasks execute
  interleaved with the script's own explicit call, at some point
  relative to Qt's paint queue that a real run never produces. Confirmed
  directly: switching the same script to construct one isolated event
  loop per call (`asyncio.run(...)`, matching how a real, single qasync
  loop actually behaves for the lifetime of one app session) made the
  glitch disappear completely, at the same window size/theme/language/
  account count that reproduced it moments before. The earlier `git
  stash` check "confirming" this on unmodified `main` used the same
  flawed multi-call script both times, so it never actually ruled out
  the script itself -- a reminder that a control run must vary only the
  one thing being tested, not carry over an unexamined assumption from
  the original repro.

---

# Portfolio Goals

Ongoing properties, re-verified as part of this stage rather than
assumed to still hold:

- [x] Keep README English-first — the English summary/features/screenshots/
      architecture/highlights/testing/security sections stay first; the
      full Russian user guide stays below them, unchanged in structure
- [x] Keep Russian documentation available — unchanged, still complete
- [x] Maintain English UI screenshots — all 6 of `docs/images/` were
      stale (predated v1.8/v2.0's UI changes, and Russian rather than
      English) and have been regenerated against the current UI in
      English this stage, using only synthetic data
- [x] Keep architecture diagram updated — the Mermaid diagram documents
      layer boundaries (UI/orchestration/campaign/telegram/MTPROTO,
      SQLite/DPAPI/config/CSV), which haven't structurally changed;
      still accurate
- [x] Keep engineering highlights updated — added the direction-dependent
      drag-reorder bug and Demo Mode's duck-typed backend as two new
      entries this stage
- [x] Document major technical decisions — `CLAUDE.md` plus inline
      comments at each real decision point (this stage: why Demo Mode
      isn't shared code with the test mock, why onboarding can't run
      from `__init__`, why the account-rename migration is generated
      rather than a raw `ALTER TABLE`, why `SecureStorage` needed to
      become injectable)
- [x] Keep CI green — every commit this stage individually verified
      green on GitHub Actions before moving to the next (one required a
      follow-up fix: a test's `QSystemTrayIcon`-adjacent object-lifetime
      issue that passed locally but crashed on the CI runner specifically)
- [x] Keep release artifacts reproducible — `.github/workflows/release.yml`
      builds from the same `.spec`/version-resource generation the manual
      process uses, so an automated and a manual build of the same commit
      produce the same artifact
- [x] Maintain honest AI-assisted development disclosure — the top-of-README
      disclosure line is unchanged and still accurate
