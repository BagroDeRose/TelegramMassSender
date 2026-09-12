"""Confirmation and result dialogs (spec items 21, 37-38).

Every dialog here is built fresh on each call, so reading tr()/trn() at
call time is all "immediate" language switching needs for this file --
there is no persistent widget to retranslate.
"""
from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QWidget

from app.i18n import tr, trn


def confirm_delete_account(parent: QWidget, phone: str) -> bool:
    # Custom Russian/English button labels (spec item 37 mockup: [Да] [Нет])
    # -- QMessageBox's StandardButton.Yes/No render in whatever language
    # Qt's own bundled translations pick unless a Qt translator is loaded,
    # which this app does not do.
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle(tr("dialogs.delete_account.title"))
    box.setText(tr("dialogs.delete_account.message", phone=phone))
    yes_button = box.addButton(tr("dialogs.yes"), QMessageBox.ButtonRole.YesRole)
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
    box.setDefaultButton(exit_button)
    box.exec()
    return box.clickedButton() is exit_button


def show_error(parent: QWidget, title: str, message: str) -> None:
    QMessageBox.warning(parent, title, message)


def show_info(parent: QWidget, title: str, message: str) -> None:
    QMessageBox.information(parent, title, message)


def confirm_start_campaign(parent: QWidget, recipient_count: int) -> bool:
    """Optional pre-start confirmation, gated behind
    AppSettings.confirm_before_start (off by default -- the app has never
    required this, so it stays opt-in rather than new friction for
    everyone)."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle(tr("dialogs.start_campaign.title"))
    box.setText(trn("dialogs.start_campaign.message", recipient_count))
    yes_button = box.addButton(tr("dialogs.start_campaign.start"), QMessageBox.ButtonRole.YesRole)
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
    box.addButton(tr("dialogs.cancel"), QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(yes_button)
    box.exec()
    return box.clickedButton() is yes_button


def confirm_delete_preset(parent: QWidget, name: str) -> bool:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(tr("main_window.dialogs.delete_preset_title"))
    box.setText(tr("main_window.dialogs.delete_preset_message", name=name))
    yes_button = box.addButton(tr("main_window.presets.delete_button"), QMessageBox.ButtonRole.YesRole)
    box.addButton(tr("dialogs.cancel"), QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(yes_button)
    box.exec()
    return box.clickedButton() is yes_button
