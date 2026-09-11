"""Tests for the hand-drawn icon set (app.ui.icons) -- no icon-font/SVG
dependency, so this just checks the factory produces a real, non-null
icon for every glyph the app actually uses, and degrades gracefully
(rather than raising) for an unknown name.
"""
from __future__ import annotations

from app.ui import icons


def test_known_icon_names_produce_nonnull_icon(qapp):
    for name in ("campaign", "accounts", "results", "settings", "attachment", "close", "check_circle", "error_circle", "clock", "plus", "video", "audio", "archive"):
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


def test_attachment_type_icons_are_visually_distinct_from_each_other(qapp):
    # Stage 2 (per-type attachment icons): video/audio/archive/document must
    # each be a genuinely different glyph, not accidental duplicates of one
    # another -- compare the actual rendered pixels, not just that a
    # non-null icon came back for each name.
    names = ("video", "audio", "archive", "document")
    images = {name: icons.icon(name, "#ffffff", size=30).pixmap(30, 30).toImage() for name in names}
    for i, name_a in enumerate(names):
        for name_b in names[i + 1 :]:
            assert images[name_a] != images[name_b], f"{name_a} and {name_b} render identically"
