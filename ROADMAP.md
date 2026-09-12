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

- [ ] Add Russian / English UI language switcher
- [ ] Translate all user-facing UI strings
- [ ] Translate dialogs and confirmation messages
- [ ] Translate validation and error messages
- [ ] Translate Campaign / Accounts / Results / Settings / Journal
- [ ] Translate empty states
- [ ] Persist selected language
- [ ] Decide whether language switching applies immediately or after restart
- [ ] Add tests for localization and language persistence
- [ ] Create English portfolio screenshots

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

- [ ] Add visual Telegram-style message preview
- [ ] Render rich text entities correctly
- [ ] Render links correctly
- [ ] Render emoji correctly
- [ ] Render attachments in preview
- [ ] Preview should use the same formatting model as actual sending
- [ ] Preview should support personalized messages

## Personalization Preview

- [ ] Support `{name}` preview for selected recipient
- [ ] Allow switching preview recipient
- [ ] Show example personalized messages
- [ ] Verify UTF-16 entity offsets remain correct after personalization

## Drafts / Presets

- [ ] Add message drafts
- [ ] Add named message presets
- [ ] Save message text
- [ ] Save formatting
- [ ] Save attachments
- [ ] Optionally save campaign interval/settings
- [ ] Load/edit/delete presets
- [ ] Do not turn presets into message history

## Campaign Wizard

- [ ] Introduce optional step-by-step campaign workflow
- [ ] Recipients
- [ ] Message
- [ ] Attachments
- [ ] Sending options
- [ ] Preview
- [ ] Confirmation
- [ ] Sending
- [ ] Results
- [ ] Preserve a fast workflow for experienced users

---

# v1.6 — Recipient & Campaign Management

## Smart Recipient Import

- [ ] Improve TXT import
- [ ] Add CSV import
- [ ] Automatically detect CSV columns
- [ ] Map username/ID/phone columns
- [ ] Map name column to `{name}`
- [ ] Normalize recipient identifiers
- [ ] Remove duplicates
- [ ] Show import statistics
- [ ] Show invalid recipients before campaign start
- [ ] Allow user to review problematic rows

## Recipient Groups

- [ ] Local recipient groups
- [ ] Customers
- [ ] Partners
- [ ] Test accounts
- [ ] Imported lists
- [ ] Rename groups
- [ ] Delete groups
- [ ] No CRM functionality

## Campaign Controls

- [ ] Pause campaign
- [ ] Resume campaign
- [ ] Cancel campaign
- [ ] Show current recipient
- [ ] Show current campaign step
- [ ] Show progress
- [ ] Show elapsed time
- [ ] Estimate remaining time
- [ ] Calculate approximate campaign duration before start
- [ ] Preserve safe partial-progress behavior

## Retry

- [ ] Retry failed recipients
- [ ] Allow retry of selected failures
- [ ] Allow retry of all failures
- [ ] Never knowingly resend already-successful campaign steps
- [ ] Preserve existing FloodWait safety behavior
- [ ] Test retry behavior extensively

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
