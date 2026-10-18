"""Live theme switching with dialogs open: dark -> light -> dark through the
real Settings combo must leave no widget carrying the previous theme's
colours, recolour themed icons and HTML previews, and call the global
QApplication.setStyleSheet exactly once per switch.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QIcon, QPalette
from PySide6.QtWidgets import QApplication

from app.database.database import Database
from app.security.secure_storage import SecureStorage
from app.telegram.chat_targets import DialogList, DialogTarget, TargetType
from app.ui import icons, theme
from app.ui.chat_picker_dialog import ChatPickerDialog
from app.ui.main_window import MainWindow
from app.ui.message_editor_dialog import MessageEditorDialog

_PALETTE_ROLES = (
    QPalette.ColorRole.Window,
    QPalette.ColorRole.WindowText,
    QPalette.ColorRole.Base,
    QPalette.ColorRole.Text,
    QPalette.ColorRole.Button,
    QPalette.ColorRole.ButtonText,
    QPalette.ColorRole.Highlight,
    QPalette.ColorRole.ToolTipBase,
)


def _theme_colors(name: str) -> set:
    tokens = theme.tokens_for(name)
    colors = set()
    for value in vars(tokens).values():
        if isinstance(value, str) and value.startswith("#"):
            colors.add(QColor(value).name())
    return colors


def _stale_colors(old: str, new: str) -> set:
    """Colours that exist only in the theme we just left."""
    return _theme_colors(old) - _theme_colors(new)


def _switch(window: MainWindow, name: str) -> None:
    window._theme_combo.setCurrentIndex(window._theme_combo.findData(name))
    QApplication.processEvents()


def _widgets_with_stale_palette(stale: set) -> list:
    offenders = []
    for widget in QApplication.allWidgets():
        palette = widget.palette()
        for role in _PALETTE_ROLES:
            if palette.color(role).name() in stale:
                offenders.append((type(widget).__name__, widget.objectName(), role.name, palette.color(role).name()))
    return offenders


def _dominant_icon_color(icon: QIcon, state: QIcon.State = QIcon.State.Off) -> str:
    image = icon.pixmap(QSize(24, 24), QIcon.Mode.Normal, state).toImage()
    best, best_alpha = None, -1
    for x in range(image.width()):
        for y in range(image.height()):
            color = image.pixelColor(x, y)
            if color.alpha() > best_alpha:
                best, best_alpha = color, color.alpha()
    return QColor(best.red(), best.green(), best.blue()).name()


async def test_dark_light_dark_with_open_dialogs_leaves_no_stale_colors(qapp, tmp_path: Path):
    window = MainWindow(database=Database(tmp_path / "app.db"), secure_storage=SecureStorage(tmp_path / "s.dat"))
    window.show()
    assert theme.get_active_theme() == theme.THEME_DARK

    editor = MessageEditorDialog("Hello {name}", [], window)
    editor.show()
    picker = ChatPickerDialog(parent=window)
    picker.set_dialogs(
        DialogList(
            dialogs=(
                DialogTarget(peer_id=-1001, title="Team", username="team", target_type=TargetType.SUPERGROUP),
                DialogTarget(peer_id=42, title="Anna", username=None, target_type=TargetType.USER),
            )
        )
    )
    picker.show()
    window._journal.setVisible(True)
    QApplication.processEvents()

    themed_icon = icons.themed("campaign", "text_secondary", checked_role="accent")
    original_set_stylesheet = QApplication.setStyleSheet
    calls = []

    def counting_set_stylesheet(app, sheet):
        calls.append(sheet)
        return original_set_stylesheet(app, sheet)

    with patch.object(QApplication, "setStyleSheet", counting_set_stylesheet):
        for previous, name in (
            (theme.THEME_DARK, theme.THEME_LIGHT),
            (theme.THEME_LIGHT, theme.THEME_DARK),
        ):
            calls.clear()
            _switch(window, name)
            tokens = theme.tokens_for(name)

            assert len(calls) == 1, f"setStyleSheet called {len(calls)} times for one switch"
            assert theme.get_active_theme() == name
            assert QApplication.instance().palette().color(QPalette.ColorRole.Window).name() == QColor(tokens.bg).name()
            assert _widgets_with_stale_palette(_stale_colors(previous, name)) == []
            # Open dialogs follow too (they are polished by the same QSS).
            for dialog in (editor, picker):
                assert dialog.palette().color(QPalette.ColorRole.Window).name() == QColor(tokens.surface).name()
            # The picker's dialog list (painted by its own delegate) too.
            picker_image = picker._list.viewport().grab().toImage()
            assert picker_image.pixelColor(2, picker_image.height() - 2).name() == QColor(tokens.input_bg).name()
            # Themed SVG icons resolve their colour from the active tokens.
            assert _dominant_icon_color(themed_icon) == QColor(tokens.text_secondary).name()
            assert _dominant_icon_color(themed_icon, QIcon.State.On) == QColor(tokens.accent).name()
            # The message preview (HTML, which QSS can't reach) is re-rendered
            # in the new colours without anyone asking it to.
            assert QColor(tokens.placeholder).name() in window._message_preview.rendered_html()
            assert QColor(theme.tokens_for(previous).placeholder).name() not in window._message_preview.rendered_html()


def test_stored_light_choice_from_an_older_version_opens_light(qapp, tmp_path: Path):
    # The redesign kept the settings key and values: a database that says
    # "light" (as written by the old version) opens the light theme as-is.
    from app.database.repositories import SettingsRepository

    db = Database(tmp_path / "app.db")
    repo = SettingsRepository(db)
    repo.set("theme", "light")
    window = MainWindow(database=db, secure_storage=SecureStorage(tmp_path / "s.dat"))
    try:
        assert theme.get_active_theme() == theme.THEME_LIGHT
        assert window._theme_combo.currentData() == theme.THEME_LIGHT
        palette = QApplication.instance().palette()
        assert palette.color(QPalette.ColorRole.Window).name() == QColor(theme.tokens_for("light").bg).name()
    finally:
        theme.apply_theme(QApplication.instance(), theme.THEME_DARK)
