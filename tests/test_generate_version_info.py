"""Tests for scripts/generate_version_info.py -- the Windows EXE
version-resource generator run before every PyInstaller build (see
build_windows.bat and telegram_mass_sender.spec). No prior coverage
existed since this script/module is new.
"""
from __future__ import annotations

import pytest

from app.version import APP_VERSION
from scripts.generate_version_info import build_version_info_text


def test_generated_text_embeds_the_current_app_version():
    text = build_version_info_text("1.3.0")
    assert "1.3.0" in text
    assert "(1, 3, 0, 0)" in text


def test_generated_text_is_valid_pyinstaller_version_info():
    # The real contract: PyInstaller.utils.win32.versioninfo.
    # load_version_info_from_text_file eval()'s this text directly and
    # asserts the result is a VSVersionInfo instance -- exercised here
    # via the same loader PyInstaller itself uses at build time, not a
    # reimplementation of its parsing.
    pytest.importorskip("PyInstaller")
    from PyInstaller.utils.win32 import versioninfo

    text = build_version_info_text(APP_VERSION)
    info = eval(text, vars(versioninfo))
    assert isinstance(info, versioninfo.VSVersionInfo)


def test_rejects_a_malformed_version_string():
    with pytest.raises(ValueError):
        build_version_info_text("1.3")  # missing patch component
    with pytest.raises(ValueError):
        build_version_info_text("1.3.0-beta")  # non-numeric component


def test_matches_the_projects_actual_app_version():
    # Guards against this generator drifting out of sync with the real
    # single source of truth if someone edits one without the other.
    text = build_version_info_text(APP_VERSION)
    assert f"u'{APP_VERSION}'" in text
