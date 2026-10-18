"""Keeps the redesign's rules from eroding: no colours, setStyleSheet calls
or literal pixel sizes in app/ui outside the token module, and no emoji /
symbol glyphs used as icons (the emoji palette and journal markers aside).
See scripts/check_ui_hygiene.py for exactly what is checked."""
from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_ui_hygiene.py"


def test_ui_code_has_no_inline_colours_sizes_or_emoji_icons(capsys):
    spec = importlib.util.spec_from_file_location("check_ui_hygiene", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.main()
    output = capsys.readouterr().out
    assert result == 0, output
