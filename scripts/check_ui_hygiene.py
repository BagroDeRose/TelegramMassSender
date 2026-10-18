"""Redesign hygiene checks (run from the repo root):

1. Emoji / symbol glyphs used as icons in UI code and UI strings. Allowed:
   the emoji palette of the message editor (_EMOJI_LIST), keyboard arrows
   in shortcut hints (Ctrl+<-), and the marker glyphs the campaign layer
   prefixes its journal messages with (app.campaign -- logic, not UI; the
   journal turns them into icons).
2. Colours outside the token module: hex colours, rgb()/rgba(), named
   QColor/Qt.GlobalColor colours, setStyleSheet calls.
3. Hard-coded pixel sizes outside the token module: numeric arguments to
   size / margin / spacing setters.
4. QColor(...) built directly from a value outside the theme package:
   token colours go through theme.qcolor(), the only path that also reads
   translucent "rgba(...)" tokens (QColor's constructor paints those
   black). QColor(Qt.GlobalColor.transparent) is the one exception.

Prints every finding and exits non-zero if there is any.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UI_FILES = sorted((ROOT / "app" / "ui").rglob("*.py"))
TOKENS = ROOT / "app" / "ui" / "theme" / "tokens.py"

GLYPH = re.compile(
    "[←-⇿⌀-⏿■-◿☀-➿⬀-⯿⋯★☆\U0001F000-\U0001FAFF]"
)
ALLOWED_GLYPH_LINES = (
    "_EMOJI_LIST",  # the emoji palette itself
    '"😀"',
    '"😢"',
)
HEX = re.compile(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b")
RGB = re.compile(r"\brgba?\(")
NAMED = re.compile(r"QColor\(\"|Qt\.GlobalColor\.(?!transparent)")
STYLESHEET = re.compile(r"\.setStyleSheet\(")
RAW_QCOLOR = re.compile(r"\bQColor\((?!Qt\.GlobalColor\.transparent\))")
SIZE_CALL = re.compile(
    r"\.(setFixedWidth|setFixedHeight|setFixedSize|setMinimumWidth|setMinimumHeight|setMinimumSize|"
    r"setMaximumWidth|setMaximumHeight|setMaximumSize|resize|setContentsMargins|setSpacing|"
    r"setHorizontalSpacing|setVerticalSpacing|addSpacing|setIconSize)\(([^)]*)\)"
)
NUMBER = re.compile(r"(?<![\w.])([1-9]\d*)(?![\w.])")


def _ui_strings_findings():
    findings = []
    strings = ROOT / "app" / "i18n" / "strings.py"
    current_key = ""
    for number, line in enumerate(strings.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith('"') and '": {' in stripped:
            current_key = stripped.split('"')[1]
        key = current_key
        if "campaign_manager.journal" in key:
            continue  # journal markers -> icons in the journal panel
        if "move_earlier_tooltip" in key or "move_later_tooltip" in key:
            continue
        # Shortcut arrows inside a key's continuation lines.
        if "Ctrl+" in line:
            continue
        for glyph in GLYPH.findall(line):
            findings.append(f"glyph {glyph!r}: app/i18n/strings.py:{number}: {line.strip()[:90]}")
    return findings


def main() -> int:
    findings = _ui_strings_findings()
    for path in UI_FILES:
        rel = path.relative_to(ROOT).as_posix()
        in_tokens = path == TOKENS
        text = path.read_text(encoding="utf-8")
        in_emoji_block = False
        in_docstring = False
        for number, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            quotes = stripped.count('"""') + stripped.count("'''")
            if in_docstring:
                if quotes % 2 == 1:
                    in_docstring = False
                continue
            if quotes % 2 == 1 and (stripped.startswith('"""') or stripped.startswith("'''") or stripped.endswith('"""')):
                in_docstring = True
                continue
            if stripped.startswith("_EMOJI_LIST"):
                in_emoji_block = True
            if in_emoji_block:
                if stripped.endswith(")") and not stripped.startswith('"'):
                    in_emoji_block = False
                continue
            if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                continue
            if rel == "app/ui/journal_widget.py" and ('"' + "✓" in line or "_MARKERS" in line or '": (' in line):
                continue
            for glyph in GLYPH.findall(line):
                if not any(allowed in line for allowed in ALLOWED_GLYPH_LINES):
                    findings.append(f"glyph {glyph!r}: {rel}:{number}: {stripped[:90]}")
            if in_tokens:
                continue
            if rel.startswith("app/ui/theme/"):
                continue  # qss template + theme runtime render tokens only
            for pattern, label in (
                (HEX, "hex colour"),
                (RGB, "rgb()"),
                (NAMED, "named colour"),
                (STYLESHEET, "setStyleSheet"),
                (RAW_QCOLOR, "QColor() instead of theme.qcolor()"),
            ):
                if pattern.search(line):
                    findings.append(f"{label}: {rel}:{number}: {stripped[:90]}")
            for match in SIZE_CALL.finditer(line):
                # Multipliers ("2 * PADDING") scale a token; they aren't sizes.
                arguments = re.sub(r"\d+\s*\*|\*\s*\d+", "", match.group(2))
                if NUMBER.search(arguments):
                    findings.append(f"size literal: {rel}:{number}: {stripped[:90]}")
    for finding in findings:
        print(finding)
    print(f"{len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
