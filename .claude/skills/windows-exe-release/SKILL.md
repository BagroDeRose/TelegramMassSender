---
name: windows-exe-release
description: Use before declaring a release/build task done, or when touching build_windows.bat, telegram_mass_sender.spec, or app/config/paths.py — the release checklist for the PyInstaller Windows EXE.
---

# Windows EXE release checklist

Build is `onedir` (not `onefile` — see the comment in
`telegram_mass_sender.spec`), produced by `build_windows.bat` via
`pyinstaller telegram_mass_sender.spec`. Output:
`dist\TelegramMassSender\TelegramMassSender.exe`.

Before claiming a release-related task is complete, verify each step —
do not just assume it worked:

1. **Run the full test suite** (`pytest`) and confirm it passes.
2. **Clean build**: `build_windows.bat` already removes `build/` and `dist/`
   before building — don't build on top of stale artifacts.
3. **Confirm the EXE exists** at
   `dist\TelegramMassSender\TelegramMassSender.exe` after the build.
4. **Launch the EXE** (not just `python app/main.py`) and confirm the window
   opens and basic navigation works — a dev-mode pass does not prove the
   frozen build works (hidden imports, missing data files, and path
   assumptions only surface in the packaged EXE).
5. **Check bundled files**: `assets/` is bundled via `datas=[("assets",
   "assets")]` in the spec. If a new runtime asset is added, it must be added
   to `datas` or it will be missing from the EXE even though it works in dev
   mode. Telethon's submodules are collected via
   `collect_submodules("telethon")` — if a new hidden-import issue appears
   (`ModuleNotFoundError` only in the frozen build), add it explicitly rather
   than guessing at excludes/includes.
6. **Check `%APPDATA%`** — runtime data (DB, sessions, logs, secrets) lives
   under `%APPDATA%`, not next to the exe (see `app/config/paths.py`). Verify
   a fresh run creates the expected structure there and that nothing writes
   next to the exe instead.
7. **Verify clean shutdown**: closing the window must fully terminate the
   process (no leftover `TelegramMassSender.exe` in Task Manager) — see
   [[qt-async-development]].
8. **No Python/runtime dependency for the end user** — the EXE must run on a
   clean Windows machine without a system Python or Node install.
9. **README accuracy** — if user-facing behavior changed (setup steps,
   requirements, troubleshooting), check `README.md` still matches reality.
10. **Release artifact** — if producing a distributable ZIP, verify it
    contains the full `dist\TelegramMassSender\` folder, not just the exe
    (Qt DLLs and data files are required alongside it).

Do not report a release as verified unless you actually ran the build and
launched the resulting EXE in this session.
