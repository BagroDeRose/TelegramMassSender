"""Icons inside line edits (QLineEdit.addAction: the picker's search
magnifier, clear buttons) sit inside the field, vertically centred.

They are QToolButtons, so the regular QToolButton QSS rule (min-height,
padding, border) used to apply to them too: the button grew taller than
the field and the magnifier was drawn low and over the frame. The theme
now has a rule for `QLineEdit QToolButton`; these tests check the
geometry everywhere such icons exist, in both themes."""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication, QLineEdit, QToolButton, QWidget

from app.database.database import Database
from app.security.secure_storage import SecureStorage
from app.telegram.chat_targets import DialogList, DialogTarget, TargetType
from app.ui import theme
from app.ui.chat_picker_dialog import ChatPickerDialog
from app.ui.main_window import MainWindow


@pytest.fixture(autouse=True)
def _restore_theme(qapp):
    name = theme.get_active_theme()
    yield
    if theme.get_active_theme() != name:
        theme.apply_theme(qapp, name)


def _picker() -> ChatPickerDialog:
    dialog = ChatPickerDialog()
    dialog.set_dialogs(
        DialogList(dialogs=(DialogTarget(peer_id=1, title="Anna", username="anna", target_type=TargetType.USER),))
    )
    dialog.show()
    QApplication.processEvents()
    return dialog


def _icon_buttons(edit: QLineEdit):
    return [b for b in edit.findChildren(QToolButton) if b.isVisible()]


def _assert_centred_inside(edit: QLineEdit, button: QToolButton) -> None:
    field = edit.rect()
    rect = button.geometry()
    assert field.contains(rect), (edit.objectName(), rect, field)
    assert rect.height() < field.height()
    assert abs(rect.center().y() - field.center().y()) <= 1, (rect, field)


def _painted_bounds(edit: QLineEdit, region: QRect) -> QRect:
    """Bounding box of the icon's own pixels: what differs from the
    field's background inside `region`."""
    image = edit.grab().toImage()
    ratio = image.devicePixelRatio()
    background = image.pixelColor(int((edit.width() // 2) * ratio), int(2 * ratio))
    xs, ys = [], []
    for x in range(int(region.left() * ratio), int((region.right() + 1) * ratio)):
        for y in range(int(region.top() * ratio), int((region.bottom() + 1) * ratio)):
            pixel = image.pixelColor(x, y)
            if abs(pixel.red() - background.red()) + abs(pixel.green() - background.green()) > 60:
                xs.append(x / ratio)
                ys.append(y / ratio)
    assert xs, "no icon pixels found"
    return QRect(int(min(xs)), int(min(ys)), int(max(xs) - min(xs)) + 1, int(max(ys) - min(ys)) + 1)


@pytest.mark.parametrize("theme_name", ["dark", "light"])
def test_picker_search_magnifier_is_centred_inside_the_field(qapp, theme_name):
    theme.apply_theme(qapp, theme_name)
    dialog = _picker()
    edit = dialog._search_edit
    buttons = _icon_buttons(edit)
    assert len(buttons) == 1  # the magnifier (no clear button while empty)
    magnifier = buttons[0]
    _assert_centred_inside(edit, magnifier)
    assert magnifier.geometry().left() >= 2  # not on the frame

    # The drawn magnifier itself: centred vertically, clear of the frame.
    drawn = _painted_bounds(edit, magnifier.geometry())
    field = edit.rect()
    assert abs(drawn.center().y() - field.center().y()) <= 1, (drawn, field)
    assert drawn.top() >= 3 and drawn.bottom() <= field.height() - 4
    assert drawn.left() >= 4
    assert drawn.height() <= theme.ICON_SIZE


@pytest.mark.parametrize("theme_name", ["dark", "light"])
def test_clear_button_is_centred_too(qapp, theme_name):
    theme.apply_theme(qapp, theme_name)
    dialog = _picker()
    dialog._search_edit.setText("ann")
    QApplication.processEvents()
    buttons = _icon_buttons(dialog._search_edit)
    assert len(buttons) == 2
    for button in buttons:
        _assert_centred_inside(dialog._search_edit, button)


def _line_edits_with_icons(root: QWidget):
    return [edit for edit in root.findChildren(QLineEdit) if edit.findChildren(QToolButton)]


async def test_every_line_edit_icon_in_the_app_is_inside_its_field(qapp, tmp_path: Path):
    window = MainWindow(database=Database(tmp_path / "app.db"), secure_storage=SecureStorage(tmp_path / "s.dat"))
    window.show()
    roots = [window, _picker(), window._build_campaign_wizard()]
    for root in roots:
        root.show()
    QApplication.processEvents()
    checked = 0
    for root in roots:
        for edit in _line_edits_with_icons(root):
            if not edit.isVisible():
                continue
            edit.setText(edit.text() or "x")  # bring up clear buttons too
            QApplication.processEvents()
            for button in _icon_buttons(edit):
                _assert_centred_inside(edit, button)
                checked += 1
    assert checked >= 1


def test_theme_rule_targets_line_edit_tool_buttons():
    sheet = theme.stylesheet_for("dark")
    assert "QLineEdit QToolButton" in sheet
    block = sheet[sheet.index("QLineEdit QToolButton") :]
    block = block[: block.index("}")]
    assert "min-height: 0px" in block and "padding: 0px" in block and "border: none" in block
