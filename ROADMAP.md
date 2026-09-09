# TelegramMassSender — Product Roadmap

> **This is a planning document only.** Nothing below is implemented yet.
> Checklist items reflect ideas and intended scope, not shipped features —
> see `README.md` for what the application actually does today, and
> `CLAUDE.md` for the current architecture. As work lands, update the
> relevant checkboxes here rather than letting this drift out of sync with
> reality.

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

- [ ] Support arbitrary files as Telegram documents
- [ ] Support JPG/JPEG
- [ ] Support PNG
- [ ] Support WEBP
- [ ] Support GIF where Telegram/API semantics allow it
- [ ] Support common video formats
- [ ] Support PDF
- [ ] Support DOC/DOCX
- [ ] Support XLS/XLSX
- [ ] Support CSV
- [ ] Support TXT
- [ ] Support ZIP
- [ ] Support unknown file types through document upload fallback
- [ ] Detect MIME type
- [ ] Display filename
- [ ] Display file size
- [ ] Display appropriate document/file icon
- [ ] Generate thumbnails where applicable
- [ ] Validate files before campaign start
- [ ] Detect missing files
- [ ] Detect unreadable files
- [ ] Preserve attachment order
- [ ] Support mixed attachment types where Telegram allows it
- [ ] Add comprehensive attachment tests

## Attachment UX

- [ ] Drag & Drop files into the message/campaign area
- [ ] Drag & Drop to reorder attachments
- [ ] Remove attachments individually
- [ ] Clear attachment queue
- [ ] Improve attachment preview
- [ ] Show file type and size
- [ ] Show useful validation errors

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
