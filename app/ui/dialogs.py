"""Confirmation and result dialogs (spec items 21, 37-38).

Every dialog here is built fresh on each call, so reading tr()/trn() at
call time is all "immediate" language switching needs for this file --
there is no persistent widget to retranslate.
"""
from __future__ import annotations

from typing import List, Tuple

from PySide6.QtWidgets import QDialog, QMessageBox, QPlainTextEdit, QPushButton, QWidget

from app.i18n import tr, trn
from app.ui.dialog_frame import build_dialog_frame
from app.ui.theme import DIALOG_HEIGHT_SM, DIALOG_WIDTH


def confirm_delete_account(parent: QWidget, phone: str) -> bool:
    # Custom Russian/English button labels (spec item 37 mockup: [Да] [Нет])
    # -- QMessageBox's StandardButton.Yes/No render in whatever language
    # Qt's own bundled translations pick unless a Qt translator is loaded,
    # which this app does not do.
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)  # destructive: warn, don't just ask
    box.setWindowTitle(tr("dialogs.delete_account.title"))
    box.setText(tr("dialogs.delete_account.message", phone=phone))
    yes_button = box.addButton(tr("dialogs.yes"), QMessageBox.ButtonRole.YesRole)
    yes_button.setProperty("variant", "danger")
    box.addButton(tr("dialogs.no"), QMessageBox.ButtonRole.NoRole)
    box.setDefaultButton(yes_button)
    box.exec()
    return box.clickedButton() is yes_button


def confirm_exit_during_campaign(parent: QWidget) -> bool:
    # Custom button labels matching spec item 38 mockup exactly:
    # [ Отмена ]      [ Выйти ]
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(tr("dialogs.exit_during_campaign.title"))
    box.setText(tr("dialogs.exit_during_campaign.message"))
    box.addButton(tr("dialogs.cancel"), QMessageBox.ButtonRole.RejectRole)
    exit_button = box.addButton(tr("dialogs.exit"), QMessageBox.ButtonRole.DestructiveRole)
    exit_button.setProperty("variant", "danger")
    box.setDefaultButton(exit_button)
    box.exec()
    return box.clickedButton() is exit_button


def show_error(parent: QWidget, title: str, message: str) -> None:
    QMessageBox.warning(parent, title, message)


def show_info(parent: QWidget, title: str, message: str) -> None:
    QMessageBox.information(parent, title, message)


def start_campaign_breakdown(user_count: int, chat_count: int, username_count: int) -> str:
    """The users / groups-and-channels split shown under the confirmation
    question. Counted from the recipient formats alone (nothing is resolved
    before the user confirms): a @username or t.me/username may be either a
    person or a public chat, so those get their own line instead of being
    guessed into one of the other two."""
    lines = []
    if user_count:
        lines.append(tr("dialogs.start_campaign.users_line", count=user_count))
    if chat_count:
        lines.append(tr("dialogs.start_campaign.chats_line", count=chat_count))
    if username_count:
        lines.append(tr("dialogs.start_campaign.usernames_line", count=username_count))
    return "\n".join(lines)


def confirm_start_campaign(
    parent: QWidget, recipient_count: int, chat_count: int = 0, username_count: int = 0
) -> bool:
    """Optional pre-start confirmation, gated behind
    AppSettings.confirm_before_start (off by default -- the app has never
    required this, so it stays opt-in rather than new friction for
    everyone). chat_count/username_count are the parts of recipient_count
    that are definitely groups/channels and that are @username/t.me
    names of not-yet-known type; the rest are users."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle(tr("dialogs.start_campaign.title"))
    box.setText(trn("dialogs.start_campaign.message", recipient_count))
    user_count = max(0, recipient_count - chat_count - username_count)
    box.setInformativeText(start_campaign_breakdown(user_count, chat_count, username_count))
    yes_button = box.addButton(tr("dialogs.start_campaign.start"), QMessageBox.ButtonRole.YesRole)
    yes_button.setProperty("variant", "primary")
    box.addButton(tr("dialogs.cancel"), QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(yes_button)
    box.exec()
    return box.clickedButton() is yes_button


def confirm_reset_settings(parent: QWidget) -> bool:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(tr("dialogs.reset_settings.title"))
    box.setText(tr("dialogs.reset_settings.message"))
    yes_button = box.addButton(tr("dialogs.reset_settings.reset"), QMessageBox.ButtonRole.YesRole)
    yes_button.setProperty("variant", "danger")
    box.addButton(tr("dialogs.cancel"), QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(yes_button)
    box.exec()
    return box.clickedButton() is yes_button


def show_invalid_rows(parent: QWidget, title: str, rows: List[Tuple[str, str]]) -> None:
    """Read-only review of recipient rows that failed to parse (ROADMAP:
    "Allow user to review problematic rows") -- one "<raw> -- <reason>"
    line per row. A QDialog with a plain-text view rather than another
    QMessageBox: the row list can be long, and a message box is not
    scrollable/selectable the way this needs to be."""
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.resize(DIALOG_WIDTH, DIALOG_HEIGHT_SM)
    frame = build_dialog_frame(dialog, title)
    text_view = QPlainTextEdit(dialog)
    text_view.setObjectName("monoText")
    text_view.setReadOnly(True)
    text_view.setPlainText("\n".join(f"{raw}  —  {reason}" for raw, reason in rows))
    frame.content.addWidget(text_view, 1)
    close_button = frame.add_button(QPushButton(tr("dialogs.close"), dialog), "primary")
    close_button.clicked.connect(dialog.accept)
    dialog.exec()


def confirm_delete_preset(parent: QWidget, name: str) -> bool:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(tr("main_window.dialogs.delete_preset_title"))
    box.setText(tr("main_window.dialogs.delete_preset_message", name=name))
    yes_button = box.addButton(tr("main_window.presets.delete_button"), QMessageBox.ButtonRole.YesRole)
    yes_button.setProperty("variant", "danger")
    box.addButton(tr("dialogs.cancel"), QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(yes_button)
    box.exec()
    return box.clickedButton() is yes_button


def confirm_delete_group(parent: QWidget, name: str) -> bool:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(tr("main_window.dialogs.delete_group_title"))
    box.setText(tr("main_window.dialogs.delete_group_message", name=name))
    yes_button = box.addButton(tr("main_window.groups.delete_button"), QMessageBox.ButtonRole.YesRole)
    yes_button.setProperty("variant", "danger")
    box.addButton(tr("dialogs.cancel"), QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(yes_button)
    box.exec()
    return box.clickedButton() is yes_button
