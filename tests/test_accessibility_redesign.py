"""Keyboard and contrast checks for the redesigned UI: a logical Tab order
on the Campaign page, the focus ring shown for keyboard focus only, and
WCAG contrast for the token pairs the redesign introduced (pills on their
tinted backgrounds, the chat bubble, links inside it, muted text on raised
surfaces)."""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.database.database import Database
from app.security.secure_storage import SecureStorage
from app.ui import theme
from app.ui.main_window import MainWindow
from tests.test_color_contrast import contrast_ratio

_AA = 4.5
_UI = 3.0


def _make_window(tmp_path: Path) -> MainWindow:
    return MainWindow(database=Database(tmp_path / "app.db"), secure_storage=SecureStorage(tmp_path / "s.dat"))


def _focus_chain(start) -> list:
    chain, current = [start], start.nextInFocusChain()
    while current is not start and len(chain) < 2000:
        chain.append(current)
        current = current.nextInFocusChain()
    return chain


async def test_campaign_page_tab_order_runs_top_to_bottom(qapp, tmp_path):
    window = _make_window(tmp_path)
    window.show()
    expected = window.campaign_tab_chain()
    order = _focus_chain(expected[0])
    positions = [order.index(widget) for widget in expected]
    assert positions == sorted(positions), "Tab order must follow the visual order of the Campaign page"
    # The primary action is reachable, and containers aren't Tab stops.
    assert window._campaign_controls._start_button in order
    assert window._message_preview._browser.focusPolicy() == Qt.FocusPolicy.ClickFocus


async def test_focus_ring_is_shown_for_keyboard_focus_only(qapp, tmp_path):
    window = _make_window(tmp_path)
    window.show()
    window.activateWindow()
    QApplication.processEvents()
    button = window._open_editor_button

    button.setFocus(Qt.FocusReason.TabFocusReason)
    QApplication.processEvents()
    assert button.property("focusRing") is True

    window._preview_name_edit.setFocus(Qt.FocusReason.MouseFocusReason)
    QApplication.processEvents()
    assert button.property("focusRing") is False
    assert window._preview_name_edit.property("focusRing") is False


def _composite(fg_rgba: str, bg_hex: str) -> str:
    """Flatten an rgba() token over an opaque background."""
    inner = fg_rgba[fg_rgba.index("(") + 1 : fg_rgba.index(")")]
    r, g, b, a = (float(part) for part in inner.split(","))
    bg = bg_hex.lstrip("#")
    br, bgc, bb = (int(bg[i : i + 2], 16) for i in (0, 2, 4))
    mixed = (round(r * a + br * (1 - a)), round(g * a + bgc * (1 - a)), round(b * a + bb * (1 - a)))
    return "#" + "".join(f"{c:02x}" for c in mixed)


@pytest.mark.parametrize("theme_name", [theme.THEME_DARK, theme.THEME_LIGHT])
@pytest.mark.parametrize("status", ["success", "warning", "error"])
def test_status_pills_are_readable_on_their_tint(theme_name, status):
    t = theme.tokens_for(theme_name)
    background = _composite(getattr(t, f"{status}_soft"), t.surface)
    assert contrast_ratio(getattr(t, f"{status}_ink"), background) >= _AA


@pytest.mark.parametrize("theme_name", [theme.THEME_DARK, theme.THEME_LIGHT])
def test_info_pill_and_selection_tint_are_readable(theme_name):
    t = theme.tokens_for(theme_name)
    assert contrast_ratio(t.info_ink, _composite(t.info_soft, t.surface)) >= _AA
    assert contrast_ratio(t.text_primary, _composite(t.accent_soft, t.surface)) >= _AA


@pytest.mark.parametrize("theme_name", [theme.THEME_DARK, theme.THEME_LIGHT])
def test_chat_bubble_text_link_and_time_are_readable(theme_name):
    t = theme.tokens_for(theme_name)
    assert contrast_ratio(t.bubble_text, t.bubble) >= _AA
    assert contrast_ratio(t.link, t.bubble) >= _AA
    assert contrast_ratio(t.bubble_meta, t.bubble) >= _UI


@pytest.mark.parametrize("theme_name", [theme.THEME_DARK, theme.THEME_LIGHT])
def test_secondary_and_muted_text_on_raised_surfaces(theme_name):
    t = theme.tokens_for(theme_name)
    assert contrast_ratio(t.text_secondary, t.surface_elevated) >= _AA
    assert contrast_ratio(t.text_muted, t.surface_elevated) >= _UI
    assert contrast_ratio(t.text_muted, t.surface) >= _UI


@pytest.mark.parametrize("theme_name", [theme.THEME_DARK, theme.THEME_LIGHT])
def test_focus_ring_and_borders_of_inputs_are_visible(theme_name):
    t = theme.tokens_for(theme_name)
    # The 2 px focus ring is a UI component: 3:1 against what it sits on.
    assert contrast_ratio(t.focus_ring, t.surface) >= _UI
    assert contrast_ratio(t.focus_ring, t.bg) >= _UI
