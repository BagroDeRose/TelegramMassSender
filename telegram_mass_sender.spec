# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Telegram Mass Sender.

Builds a portable one-folder (--onedir) distribution rather than a
single-file exe: --onefile re-extracts the whole bundle to a temp
directory on every launch, which is slower to start and more prone to
antivirus interference and missing-DLL issues with PySide6's large Qt
payload. Runtime data (DB, sessions, logs, secrets) already lives under
%APPDATA%, not next to the exe, so onedir loses nothing in exchange for
that stability.
"""
from PyInstaller.utils.hooks import collect_submodules

import sys as _sys
_sys.path.insert(0, SPECPATH)
from scripts.generate_version_info import main as _generate_version_info

# Regenerated here (not just by build_windows.bat) so this stays correct
# regardless of how the spec is invoked -- e.g. `pyinstaller
# telegram_mass_sender.spec` run directly, bypassing the batch script.
# See scripts/generate_version_info.py for why this can't just be a
# static, hand-maintained file (app.version.APP_VERSION is the one source
# of truth for the version number).
_generate_version_info()

block_cipher = None

# Telethon has no bundled PyInstaller hook and touches a large tree of
# tl.types/tl.functions submodules; collect all of them explicitly rather
# than relying on static analysis to catch every one.
hidden_imports = collect_submodules("telethon")

a = Analysis(
    ["app/main.py"],
    pathex=[],
    binaries=[],
    datas=[("assets", "assets")],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TelegramMassSender",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/icons/app.ico",
    version="version_info.txt",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="TelegramMassSender",
)
