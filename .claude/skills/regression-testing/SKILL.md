---
name: regression-testing
description: Use whenever fixing a bug anywhere in this project — defines the required reproduce-first workflow and when a regression test is mandatory.
---

# Regression-testing workflow

Every bug fix in this project should follow this sequence:

```text
bug
  -> reproduce
  -> write a failing test
  -> fix the code
  -> run the targeted test (confirm it now passes)
  -> run the full suite (pytest)
  -> manual smoke test if GUI or live Telegram behavior is involved
```

## Rules

- Reproduce the bug before writing any fix. If you can't reproduce it, say
  so explicitly instead of guessing at a fix.
- Write the regression test **before** or **alongside** the fix, and make
  sure it actually fails against the old code (mentally or by checking it
  would have caught the bug) — a test that would have passed either way
  proves nothing.
- Place the test in the matching file under `tests/` (e.g.
  `tests/test_campaign_manager.py`, `tests/test_recipient_resolver.py`,
  `tests/test_media_formatting.py`) rather than creating a new file for a
  single test unless no existing file fits.
- Use `tests/mocks/mock_telegram_client.py` for anything that would
  otherwise touch real Telegram — never let a test send a live message.
- After the fix: run the specific test file first
  (`pytest tests/test_x.py -v`), then the full suite (`pytest`) — a fix that
  breaks something else is not done.
- Never delete or weaken an existing test just to make the suite pass; if a
  test is actually wrong, fix the test and say so explicitly, don't quietly
  remove it.
- For bugs involving GUI (`app/ui/*`) or live Telegram interaction
  (formatting, albums, FloodWait), automated tests won't catch everything —
  do a manual smoke test after the automated suite passes, per
  [[qt-async-development]] and [[telegram-media-testing]].
- Root-cause the bug, not just the symptom — a minimal fix at the true
  source, not a patch at the call site that happened to trigger it.
