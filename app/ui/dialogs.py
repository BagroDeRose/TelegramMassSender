"""Confirmation and result dialogs (spec items 21, 37-38)."""
from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QWidget


def confirm_delete_account(parent: QWidget, phone: str) -> bool:
    # Custom Russian button labels (spec item 37 mockup: [Да] [Нет]) --
    # QMessageBox's StandardButton.Yes/No render in English unless a Qt
    # translator is loaded, which this app does not do.
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle("Удалить аккаунт?")
    box.setText(f"Будет удалена локальная Telegram-сессия аккаунта {phone}.\n\nПродолжить?")
    yes_button = box.addButton("Да", QMessageBox.ButtonRole.YesRole)
    box.addButton("Нет", QMessageBox.ButtonRole.NoRole)
    box.setDefaultButton(yes_button)
    box.exec()
    return box.clickedButton() is yes_button


def confirm_exit_during_campaign(parent: QWidget) -> bool:
    # Custom Russian button labels matching spec item 38 mockup exactly:
    # [ Отмена ]      [ Выйти ]
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle("Рассылка ещё выполняется")
    box.setText("Вы действительно хотите выйти?")
    box.addButton("Отмена", QMessageBox.ButtonRole.RejectRole)
    exit_button = box.addButton("Выйти", QMessageBox.ButtonRole.DestructiveRole)
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
    box.setWindowTitle("Начать рассылку?")
    box.setText(f"Сообщение будет отправлено {recipient_count} получателям. Продолжить?")
    yes_button = box.addButton("Начать", QMessageBox.ButtonRole.YesRole)
    box.addButton("Отмена", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(yes_button)
    box.exec()
    return box.clickedButton() is yes_button


def confirm_reset_settings(parent: QWidget) -> bool:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle("Сбросить настройки?")
    box.setText("Все настройки приложения будут возвращены к значениям по умолчанию. Продолжить?")
    yes_button = box.addButton("Сбросить", QMessageBox.ButtonRole.YesRole)
    box.addButton("Отмена", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(yes_button)
    box.exec()
    return box.clickedButton() is yes_button
