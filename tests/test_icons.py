"""Tests for the hand-drawn icon set (app.ui.icons) -- no icon-font/SVG
dependency, so this just checks the factory produces a real, non-null
icon for every glyph the app actually uses, and degrades gracefully
(rather than raising) for an unknown name.
"""
from __future__ import annotations

from app.ui import icons


def test_known_icon_names_produce_nonnull_icon(qapp):
    for name in ("campaign", "accounts", "results", "settings", "attachment", "close", "check_circle", "error_circle", "clock", "plus"):
        icon = icons.icon(name, "#ffffff", size=18)
        assert not icon.isNull()
        pixmap = icon.pixmap(18, 18)
        assert pixmap.width() == 18
        assert pixmap.height() == 18


def test_unknown_icon_name_returns_empty_icon_not_raise(qapp):
    icon = icons.icon("does-not-exist", "#ffffff", size=18)
    assert icon.isNull() or icon.pixmap(18, 18).width() == 18


def test_different_sizes_produce_correctly_sized_pixmaps(qapp):
    icon = icons.icon("campaign", "#4ea1f7", size=32)
    pixmap = icon.pixmap(32, 32)
    assert pixmap.width() == 32
    assert pixmap.height() == 32
