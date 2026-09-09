"""Tests for the redesigned application shell's sidebar navigation
(app.ui.sidebar) -- a pure navigation control with no knowledge of what
each page contains, so it's tested standalone from MainWindow.
"""
from __future__ import annotations

from app.ui.sidebar import NAV_ITEMS, Sidebar


def test_first_nav_button_checked_by_default(qapp):
    sidebar = Sidebar()
    assert sidebar._buttons[0].isChecked() is True
    for button in sidebar._buttons[1:]:
        assert button.isChecked() is False


def test_clicking_nav_button_emits_page_selected(qapp):
    sidebar = Sidebar()
    selected = []
    sidebar.page_selected.connect(selected.append)

    sidebar._buttons[2].click()

    assert selected == [2]
    assert sidebar._buttons[2].isChecked() is True
    assert sidebar._buttons[0].isChecked() is False


def test_set_current_index_updates_checked_state(qapp):
    sidebar = Sidebar()
    sidebar.set_current_index(3)
    assert sidebar._buttons[3].isChecked() is True
    assert sidebar._buttons[0].isChecked() is False


def test_nav_button_count_matches_declared_items(qapp):
    sidebar = Sidebar()
    assert len(sidebar._buttons) == len(NAV_ITEMS)


def test_apply_theme_does_not_raise(qapp):
    sidebar = Sidebar()
    sidebar.apply_theme()  # should not raise regardless of active theme
