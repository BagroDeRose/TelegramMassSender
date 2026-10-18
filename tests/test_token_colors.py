"""Every colour token of both themes becomes a valid QColor through
theme.qcolor() -- including the translucent "rgba(...)" ones alpha()
produces, which QColor's own constructor reads as an invalid colour
(painted black: the dialog picker's initials circle once was) -- and
every place that paints a token goes through it."""
from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor

from app.ui import icons, theme
from app.ui.theme.tokens import Tokens, parse_color, tokens_for

ROOT = Path(__file__).resolve().parent.parent
COLOR_FIELDS = [f.name for f in dataclasses.fields(Tokens) if f.type in ("str", str)]


def test_every_colour_field_is_covered():
    # Guards the parametrisation below: a new colour token is tested too.
    assert len(COLOR_FIELDS) >= 40
    assert "accent_soft" in COLOR_FIELDS and "overlay" in COLOR_FIELDS and "scrollbar_track" in COLOR_FIELDS


@pytest.mark.parametrize("theme_name", ["dark", "light"])
@pytest.mark.parametrize("field", COLOR_FIELDS)
def test_token_becomes_a_valid_qcolor(qapp, theme_name, field):
    value = getattr(tokens_for(theme_name), field)
    r, g, b, opacity = parse_color(value)
    color = theme.qcolor(value)
    assert color.isValid(), (field, value)
    assert (color.red(), color.green(), color.blue()) == (r, g, b)
    assert abs(color.alphaF() - opacity) < 0.01
    if value.startswith("#"):
        assert color.name() == QColor(value).name() and color.alpha() == 255


@pytest.mark.parametrize("theme_name", ["dark", "light"])
def test_translucent_tokens_keep_their_opacity(qapp, theme_name):
    tokens = tokens_for(theme_name)
    translucent = [f for f in COLOR_FIELDS if getattr(tokens, f).startswith("rgba(")]
    assert {"accent_soft", "success_soft", "error_soft", "overlay", "selected_account"} <= set(translucent)
    for field in translucent:
        value = getattr(tokens, field)
        assert not QColor(value).isValid()  # why theme.qcolor exists
        color = theme.qcolor(value)
        assert 0 < color.alpha() < 255, field
    assert theme.qcolor(tokens.scrollbar_track).alpha() == 0  # "transparent"


@pytest.mark.parametrize("bad", ["", "accent", "#12345", "rgba(1, 2)", "rgba(300, 0, 0, 1)", "rgba(1, 2, 3, 1.5)"])
def test_anything_else_is_refused_not_painted_black(bad):
    with pytest.raises(ValueError):
        theme.qcolor(bad)


@pytest.mark.parametrize("theme_name", ["dark", "light"])
def test_icons_take_every_token_colour(qapp, theme_name):
    """SVG accepts neither rgba() nor "transparent" as a stroke: the icon
    renderer goes through the same parser."""
    tokens = tokens_for(theme_name)
    for field in COLOR_FIELDS:
        value = getattr(tokens, field)
        image = icons.render_pixmap("square", value, QSize(24, 24)).toImage()
        strongest = max((image.pixelColor(x, y) for x in range(24) for y in range(24)), key=lambda c: c.alpha())
        expected = theme.qcolor(value)
        if expected.alpha() == 0:
            assert strongest.alpha() == 0, field
            continue
        assert strongest.alpha() > 0, (field, value)
        assert abs(strongest.alpha() - expected.alpha()) <= 3, field
        # Premultiplied storage rounds the channels of a 14 % colour a little.
        tolerance = 3 if expected.alpha() == 255 else 12
        for channel in ("red", "green", "blue"):
            assert abs(getattr(strongest, channel)() - getattr(expected, channel)()) <= tolerance, field


def test_palette_uses_the_same_path(qapp):
    for theme_name in ("dark", "light"):
        palette = theme.palette_for(theme_name)
        assert palette.color(palette.ColorRole.Highlight).name() == theme.qcolor(tokens_for(theme_name).accent).name()


def test_no_token_reaches_a_raw_qcolor_in_ui_code():
    """Delegates and other paint code (dialog picker rows, results rows,
    journal rows, message preview, editor formats) build colours only via
    theme.qcolor(); the hygiene check enforces it for new code."""
    offenders = []
    for path in sorted((ROOT / "app" / "ui").rglob("*.py")):
        if "theme" in path.relative_to(ROOT / "app" / "ui").parts:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "QColor(" in line and "QColor(Qt.GlobalColor.transparent)" not in line and "qcolor(" not in line:
                offenders.append(f"{path.name}:{number}: {line.strip()}")
    assert offenders == []
    painters = ["dialog_picker_model.py", "results_view.py", "journal_widget.py", "message_preview.py"]
    for name in painters:
        assert "theme.qcolor(" in (ROOT / "app" / "ui" / name).read_text(encoding="utf-8"), name
