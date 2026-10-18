"""WCAG 2.1 contrast-ratio checks for app.ui.theme's color tokens (ROADMAP
v1.8 Accessibility: "Adequate contrast"). No prior automated coverage
existed for this -- theme.py's existing tests check that colors differ
between themes, never that they're actually readable.

Thresholds follow WCAG 2.1 SC 1.4.3 (Contrast (Minimum), Level AA):
4.5:1 for normal text, 3:1 for large-scale text (>=18pt, or >=14pt bold)
and for non-text UI components/graphics (SC 1.4.11). Which threshold
applies to which token pair below is decided by how theme.py's QSS
template actually uses that pair, not guessed -- see each test's comment.
"""
from __future__ import annotations

import pytest

from app.ui import theme

_AA_NORMAL_TEXT = 4.5
_AA_LARGE_TEXT_OR_UI = 3.0


def _linearize(channel: float) -> float:
    return channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_color: str) -> float:
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i : i + 2], 16) / 255 for i in (0, 2, 4))
    r, g, b = _linearize(r), _linearize(g), _linearize(b)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(hex_a: str, hex_b: str) -> float:
    la, lb = relative_luminance(hex_a), relative_luminance(hex_b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def test_contrast_ratio_helper_sanity_checks():
    assert contrast_ratio("#ffffff", "#000000") == pytest.approx(21.0, abs=0.01)
    assert contrast_ratio("#000000", "#000000") == pytest.approx(1.0, abs=0.01)
    # Symmetric regardless of argument order.
    assert contrast_ratio("#4ea1f7", "#16171a") == contrast_ratio("#16171a", "#4ea1f7")


# ---- primary/secondary body text -- QLabel's default color and
# QLabel#pageSubtitle/helperText-adjacent normal-sized text; the bulk of
# what a user actually reads in this app. Must meet full AA (4.5:1). -------


@pytest.mark.parametrize("theme_name", [theme.THEME_DARK, theme.THEME_LIGHT])
def test_primary_text_meets_aa_on_the_main_background(theme_name):
    t = theme.tokens_for(theme_name)
    assert contrast_ratio(t.text_primary, t.bg) >= _AA_NORMAL_TEXT


@pytest.mark.parametrize("theme_name", [theme.THEME_DARK, theme.THEME_LIGHT])
def test_secondary_text_meets_aa_on_the_main_background(theme_name):
    # QLabel { color: $text_secondary; } is this app's *default* label
    # color -- most on-screen text, not a de-emphasized variant.
    t = theme.tokens_for(theme_name)
    assert contrast_ratio(t.text_secondary, t.bg) >= _AA_NORMAL_TEXT


@pytest.mark.parametrize("theme_name", [theme.THEME_DARK, theme.THEME_LIGHT])
def test_primary_text_meets_aa_on_a_card_surface(theme_name):
    t = theme.tokens_for(theme_name)
    assert contrast_ratio(t.text_primary, t.surface) >= _AA_NORMAL_TEXT


@pytest.mark.parametrize("theme_name", [theme.THEME_DARK, theme.THEME_LIGHT])
def test_secondary_text_meets_aa_on_a_card_surface(theme_name):
    t = theme.tokens_for(theme_name)
    assert contrast_ratio(t.text_secondary, t.surface) >= _AA_NORMAL_TEXT


@pytest.mark.parametrize("theme_name", [theme.THEME_DARK, theme.THEME_LIGHT])
def test_error_text_meets_aa_on_the_main_background(theme_name):
    # QLabel#dialogErrorLabel / QLabel#statusLabel-adjacent error text --
    # normal-sized, must be fully readable.
    t = theme.tokens_for(theme_name)
    assert contrast_ratio(t.error, t.bg) >= _AA_NORMAL_TEXT


@pytest.mark.parametrize("theme_name", [theme.THEME_DARK, theme.THEME_LIGHT])
def test_warning_text_meets_aa_on_the_main_background(theme_name):
    t = theme.tokens_for(theme_name)
    assert contrast_ratio(t.warning, t.bg) >= _AA_NORMAL_TEXT


# ---- large-scale / UI-component contexts -- QLabel#statValue (26px,
# comfortably >=18pt "large text"), border/accent-as-UI-component colors.
# WCAG's large-text and non-text-UI-component exception applies: 3:1. -----


@pytest.mark.parametrize("theme_name", [theme.THEME_DARK, theme.THEME_LIGHT])
def test_success_text_meets_the_large_text_threshold(theme_name):
    # QLabel#statValue[variant="success"] -- FONT_SIZE_STAT_VALUE=26px,
    # well past WCAG's large-text cutoff.
    t = theme.tokens_for(theme_name)
    assert contrast_ratio(t.success, t.bg) >= _AA_LARGE_TEXT_OR_UI


@pytest.mark.parametrize("theme_name", [theme.THEME_DARK, theme.THEME_LIGHT])
def test_accent_as_text_or_border_meets_the_ui_component_threshold(theme_name):
    # $accent is used both as a border color (a non-text UI component,
    # SC 1.4.11's 3:1) and as text color for short/bold labels (nav
    # "checked" state, card counts) -- 3:1 covers both real usages.
    t = theme.tokens_for(theme_name)
    assert contrast_ratio(t.accent, t.bg) >= _AA_LARGE_TEXT_OR_UI


@pytest.mark.parametrize("theme_name", [theme.THEME_DARK, theme.THEME_LIGHT])
def test_muted_text_meets_a_reasonable_de_emphasis_floor(theme_name):
    # $text_muted is this app's deliberately de-emphasized tertiary text
    # (captions, helper text) -- a common, widely-used UI pattern that
    # accepts a lower floor than primary content while still staying
    # clearly legible (matches WCAG's non-text/large-scale 3:1 floor
    # rather than full AA's 4.5:1, which is reserved for primary content
    # above).
    t = theme.tokens_for(theme_name)
    assert contrast_ratio(t.text_muted, t.bg) >= _AA_LARGE_TEXT_OR_UI


# ---- primary button text -----------------------------------------------
#
# QPushButton[variant="primary"] draws $on_accent text on $accent at the
# 13 px body size -- normal text, so full AA (4.5:1). This used to be a
# tracked known gap in the dark theme (white on the old accent, 2.70:1);
# the redesign gave $on_accent its own value per theme (dark text on the
# dark theme's light-blue accent) instead of darkening $accent, which is
# also used as text and borders elsewhere.


@pytest.mark.parametrize("theme_name", [theme.THEME_DARK, theme.THEME_LIGHT])
def test_primary_button_text_meets_aa(theme_name):
    t = theme.tokens_for(theme_name)
    assert contrast_ratio(t.on_accent, t.accent) >= _AA_NORMAL_TEXT
    assert contrast_ratio(t.on_accent, t.accent_hover) >= _AA_NORMAL_TEXT
