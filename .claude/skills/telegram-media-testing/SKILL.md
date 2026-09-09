---
name: telegram-media-testing
description: Use when changing anything related to sending media, captions, or text formatting (app/telegram/media_sender.py, app/ui/message_editor*.py, app/ui/message_preview.py) — defines the test matrix that must be covered before considering the change done.
---

# Media / formatting / caption test matrix

Any change touching media sending, captions, or rich-text formatting must be
exercised against this matrix — not just the one case you were fixing. See
`tests/test_media_formatting.py`, `tests/test_message_editor*.py`,
`tests/test_message_preview.py` for existing coverage to extend.

## Attachment count

- 0 files (text-only message)
- 1 file
- 2 files
- 3 files
- many files (album grouping behavior — Telegram albums cap at 10 items per
  group; verify `media_sender.py` batches correctly beyond that)

## Caption / formatting

- No caption at all
- Plain caption, no formatting
- **Bold**, *italic*, __underline__, individually and combined/nested
- Links (make sure the link text and URL survive round-trip, not just plain
  URLs)
- Emoji and other characters outside the Basic Multilingual Plane (these are
  UTF-16 surrogate pairs — a common source of off-by-one entity offset bugs;
  see [[telethon-debugging]])
- Caption present on a single media item vs. caption on an album (Telegram
  applies album captions differently than single-item captions)

## Media types

- Photo, video, generic file/document — each has a different Telethon send
  path in `media_sender.py`; don't assume a fix for one covers the others.

## Low-level verification

- When a low-level Telethon API call is involved (raw `entities=` list,
  `send_file`, `send_message` with formatting), inspect the *actual*
  parameters being sent (e.g. via a mock client assertion or a debug log in a
  test), not just the rendered UI preview — the preview and the wire request
  can diverge.

## Workflow

Follow [[regression-testing]]: reproduce the specific broken case with a
test first, fix, then run the full matrix above (or the relevant subset) plus
the full test suite before considering the change done.
