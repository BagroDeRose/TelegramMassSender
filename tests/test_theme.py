"""Tests for the theme module (app.ui.theme) and its persistence via
app.database.repositories.SettingsRepository."""
from __future__ import annotations

from app.config.settings import DEFAULT_THEME
from app.database.database import Database
from app.database.repositories import SettingsRepository
from app.ui import theme


def test_default_theme_is_dark():
    assert DEFAULT_THEME == theme.THEME_DARK


def test_stylesheet_for_both_themes_returns_content():
    assert theme.stylesheet_for(theme.THEME_DARK).strip()
    assert theme.stylesheet_for(theme.THEME_LIGHT).strip()


def test_stylesheet_for_invalid_theme_falls_back_to_default():
    result = theme.stylesheet_for("not-a-real-theme")
    assert result == theme.stylesheet_for(DEFAULT_THEME)


def test_set_and_get_active_theme_roundtrip():
    theme.set_active_theme(theme.THEME_LIGHT)
    try:
        assert theme.get_active_theme() == theme.THEME_LIGHT
    finally:
        theme.set_active_theme(DEFAULT_THEME)


def test_set_active_theme_invalid_falls_back_to_default():
    theme.set_active_theme("bogus")
    try:
        assert theme.get_active_theme() == DEFAULT_THEME
    finally:
        theme.set_active_theme(DEFAULT_THEME)


def test_color_helpers_differ_between_themes():
    theme.set_active_theme(theme.THEME_DARK)
    dark_link = theme.link_color()
    dark_spoiler = theme.spoiler_background()
    dark_spoiler_preview = theme.spoiler_preview_color()
    dark_code = theme.code_background()
    dark_placeholder = theme.placeholder_text_color()

    theme.set_active_theme(theme.THEME_LIGHT)
    try:
        assert theme.link_color() != dark_link
        assert theme.spoiler_background() != dark_spoiler
        assert theme.spoiler_preview_color() != dark_spoiler_preview
        assert theme.code_background() != dark_code
        assert theme.placeholder_text_color() != dark_placeholder
    finally:
        theme.set_active_theme(DEFAULT_THEME)


def test_tokens_for_returns_distinct_token_sets_per_theme():
    dark = theme.tokens_for(theme.THEME_DARK)
    light = theme.tokens_for(theme.THEME_LIGHT)
    assert dark.bg != light.bg
    assert dark.accent != light.accent


def test_tokens_for_invalid_theme_falls_back_to_default():
    assert theme.tokens_for("not-a-real-theme") == theme.tokens_for(DEFAULT_THEME)


def test_current_tokens_follows_active_theme():
    theme.set_active_theme(theme.THEME_LIGHT)
    try:
        assert theme.current_tokens() == theme.tokens_for(theme.THEME_LIGHT)
    finally:
        theme.set_active_theme(DEFAULT_THEME)


def test_stylesheet_contains_no_unsubstituted_placeholders():
    # A stray "$token_name" left in the generated QSS would mean a typo in
    # the template vs. the substitution dict -- catch that here rather
    # than as a silently-broken style rule in the running app.
    css = theme.stylesheet_for(theme.THEME_DARK)
    assert "$" not in css


def test_combobox_popup_styled_for_both_themes():
    # Regression test for a confirmed bug: QComboBox's dropdown popup is a
    # separate QAbstractItemView that Qt does NOT theme via the QComboBox
    # selector alone -- left unstyled, it falls back to the native (light)
    # OS palette even when the app is in Dark theme, making the popup
    # nearly unreadable. Assert the explicit popup rule exists and uses
    # each theme's own tokens, not a hardcoded light fallback.
    for theme_name in theme.VALID_THEMES:
        tokens = theme.tokens_for(theme_name)
        css = theme.stylesheet_for(theme_name)
        assert "QComboBox QAbstractItemView" in css
        assert f"background-color: {tokens.surface_elevated};" in css
        assert f"selection-color: {tokens.accent};" in css


def test_combobox_popup_dark_and_light_use_different_colors():
    dark_css = theme.stylesheet_for(theme.THEME_DARK)
    light_css = theme.stylesheet_for(theme.THEME_LIGHT)
    dark_tokens = theme.tokens_for(theme.THEME_DARK)
    light_tokens = theme.tokens_for(theme.THEME_LIGHT)
    assert dark_tokens.surface_elevated != light_tokens.surface_elevated
    # The popup rule in each generated stylesheet must reference that
    # theme's own surface color, not a value shared/hardcoded across both.
    assert f"background-color: {dark_tokens.surface_elevated};" in dark_css
    assert f"background-color: {light_tokens.surface_elevated};" in light_css


def test_scrollbar_tokens_present_and_distinct_per_theme():
    dark = theme.tokens_for(theme.THEME_DARK)
    light = theme.tokens_for(theme.THEME_LIGHT)
    for tokens in (dark, light):
        assert tokens.scrollbar_track
        assert tokens.scrollbar_handle
        assert tokens.scrollbar_handle_hover
        assert tokens.scrollbar_handle_pressed
        # hover/pressed must actually be distinct states, not aliases of
        # the resting handle color (a visually-dead hover would defeat
        # the point of styling them separately).
        assert tokens.scrollbar_handle != tokens.scrollbar_handle_hover
        assert tokens.scrollbar_handle_hover != tokens.scrollbar_handle_pressed
    assert dark.scrollbar_handle != light.scrollbar_handle


def test_scrollbar_qss_uses_scrollbar_tokens_not_generic_ones():
    css = theme.stylesheet_for(theme.THEME_DARK)
    tokens = theme.tokens_for(theme.THEME_DARK)
    assert f"background: {tokens.scrollbar_handle};" in css
    assert f"background: {tokens.scrollbar_handle_hover};" in css
    assert f"background: {tokens.scrollbar_handle_pressed};" in css
    # No native arrow buttons -- both dimensions collapsed to zero.
    assert "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical" in css
    assert "QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal" in css


def test_checkbox_indicator_styled_for_both_themes():
    for theme_name in theme.VALID_THEMES:
        css = theme.stylesheet_for(theme_name)
        assert "QCheckBox::indicator" in css
        assert "QCheckBox::indicator:checked" in css


def test_spinbox_buttons_styled_for_both_themes():
    for theme_name in theme.VALID_THEMES:
        css = theme.stylesheet_for(theme_name)
        assert "QSpinBox::up-button" in css
        assert "QSpinBox::down-button" in css


def test_spinbox_arrows_use_generated_image_for_both_themes():
    # Regression test for a confirmed bug: once ::up-button/::down-button
    # carry any QSS, Qt stops painting its native arrow glyph inside them
    # -- verified by direct rendering before writing the fix, not assumed
    # -- so ::up-arrow/::down-arrow MUST supply an explicit `image:`, or
    # the spin buttons render as blank boxes with no visible arrow at all.
    for theme_name in theme.VALID_THEMES:
        css = theme.stylesheet_for(theme_name)
        assert "QSpinBox::up-arrow {" in css
        assert "QSpinBox::down-arrow {" in css
        assert "image: url(" in css
        assert f"spin_up_{theme_name}.png" in css
        assert f"spin_down_{theme_name}.png" in css


def test_spinbox_tokens_present_and_distinct_per_theme():
    dark = theme.tokens_for(theme.THEME_DARK)
    light = theme.tokens_for(theme.THEME_LIGHT)
    for tokens in (dark, light):
        assert tokens.spinbox_button is not None
        assert tokens.spinbox_button_hover
        assert tokens.spinbox_button_pressed
        assert tokens.spinbox_arrow
    assert dark.spinbox_arrow != light.spinbox_arrow
    assert dark.spinbox_button_hover != light.spinbox_button_hover


def test_stylesheet_for_never_crashes_without_a_running_qapplication():
    # The actual regression this guards: constructing QPixmap/QPainter
    # (needed to draw the spin-arrow PNGs) before any QApplication exists
    # is a documented Qt precondition violation that crashes the process
    # outright rather than raising a catchable Python exception --
    # confirmed by direct reproduction before writing the guard in
    # app.ui.theme._spinbox_arrow_urls. This test intentionally does NOT
    # request the `qapp` fixture, so it only passes if stylesheet_for()
    # tolerates having no QApplication instance at all -- run this file
    # in isolation (pytest tests/test_theme.py::test_stylesheet_for_never_crashes_without_a_running_qapplication)
    # to actually exercise the no-QApplication path; inside the full
    # suite some other test will typically have created one already.
    css = theme.stylesheet_for(theme.THEME_DARK)
    assert "QSpinBox" in css


def test_generated_spinbox_arrow_files_exist_after_stylesheet_build(qapp):
    from app.config.paths import get_theme_assets_dir

    theme.stylesheet_for(theme.THEME_DARK)
    directory = get_theme_assets_dir()
    up_path = directory / "spin_up_dark.png"
    down_path = directory / "spin_down_dark.png"
    assert up_path.is_file()
    assert down_path.is_file()
    assert up_path.stat().st_size > 0
    assert down_path.stat().st_size > 0


def test_ghost_button_style_present():
    css = theme.stylesheet_for(theme.THEME_DARK)
    assert "QPushButton#ghostButton" in css


def test_menu_popup_styled_for_both_themes():
    # QMenu (the message editor's emoji picker, a saved report's "..."
    # overflow menu) is a top-level popup that Qt does not theme
    # automatically -- same class of bug as the QComboBox popup.
    for theme_name in theme.VALID_THEMES:
        tokens = theme.tokens_for(theme_name)
        css = theme.stylesheet_for(theme_name)
        assert "QMenu {" in css
        assert "QMenu::item:selected" in css
        assert f"background-color: {tokens.surface_elevated};" in css


def test_selected_account_token_distinct_per_theme():
    dark = theme.tokens_for(theme.THEME_DARK)
    light = theme.tokens_for(theme.THEME_LIGHT)
    assert dark.selected_account
    assert light.selected_account
    assert dark.selected_account != light.selected_account


def test_theme_setting_persists_across_save_and_reload(tmp_path):
    db = Database(db_path=tmp_path / "test.db")
    try:
        repo = SettingsRepository(db)
        settings = repo.load_app_settings()
        assert settings.theme == DEFAULT_THEME

        settings.theme = theme.THEME_LIGHT
        repo.save_app_settings(settings)

        reloaded = repo.load_app_settings()
        assert reloaded.theme == theme.THEME_LIGHT
    finally:
        db.close()
