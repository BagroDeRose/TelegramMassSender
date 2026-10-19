"""Confirmation and result dialogs (spec items 21, 37-38).

Every dialog here is built fresh on each call, so reading tr()/trn() at
call time is all "immediate" language switching needs for this file --
there is no persistent widget to retranslate.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Mapping, Tuple

from PySide6.QtWidgets import QDialog, QMessageBox, QPlainTextEdit, QPushButton, QWidget

from app.i18n import tr, trn
from app.ui import theme
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


@dataclass(frozen=True)
class RecipientBreakdown:
    """Who a campaign is about to reach, as far as is known before
    anything is resolved: people, bots, groups/channels, and @usernames
    whose type only resolving will tell."""

    people: int = 0
    bots: int = 0
    chats: int = 0
    unknown: int = 0

    @property
    def total(self) -> int:
        return self.people + self.bots + self.chats + self.unknown


def recipient_breakdown(recipients: Iterable, known: Mapping[str, object]) -> "RecipientBreakdown":
    """People / bots / groups-and-channels / not-yet-known. `known` maps a
    normalized recipient key to its DialogCategory value from the
    session's dialog cache; otherwise the format decides (a chat ID or
    invite link is a chat, a phone/ID/link a person, a bare @username
    unknown until resolved). Nothing is resolved here."""
    from app.recipients.parser import RecipientKind
    from app.telegram.chat_targets import DialogCategory

    people = bots = chats = unknown = 0
    for recipient in recipients:
        category = known.get(recipient.normalized_key)
        if category is DialogCategory.BOTS:
            bots += 1
        elif category is DialogCategory.PEOPLE:
            people += 1
        elif category is not None or recipient.is_chat_target:
            chats += 1
        elif recipient.kind == RecipientKind.USERNAME:
            unknown += 1
        else:
            people += 1
    return RecipientBreakdown(people=people, bots=bots, chats=chats, unknown=unknown)


def build_large_campaign_box(
    parent: QWidget, breakdown: RecipientBreakdown, threshold: int
) -> Tuple[QMessageBox, QPushButton, QPushButton]:
    """The large-campaign guard: starting is the dangerous choice, so the
    Start button is "danger" and Cancel is the default (Enter or Esc
    cancels)."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(tr("dialogs.large_campaign.title"))
    box.setText(tr("dialogs.large_campaign.message", count=breakdown.total, threshold=threshold))
    lines = [
        tr("dialogs.large_campaign.people_line", count=breakdown.people),
        tr("dialogs.large_campaign.bots_line", count=breakdown.bots),
        tr("dialogs.large_campaign.chats_line", count=breakdown.chats),
    ]
    if breakdown.unknown:
        lines.append(tr("dialogs.large_campaign.unknown_line", count=breakdown.unknown))
    box.setInformativeText("\n".join(lines))
    start_button = box.addButton(tr("dialogs.large_campaign.start"), QMessageBox.ButtonRole.AcceptRole)
    # set_property re-polishes: the box already styled the button when it
    # was added, and (unlike a default button) nothing would restyle it later.
    theme.set_property(start_button, "variant", "danger")
    cancel_button = box.addButton(tr("dialogs.cancel"), QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(cancel_button)
    box.setEscapeButton(cancel_button)
    cancel_button.setFocus()
    return box, start_button, cancel_button


def confirm_large_campaign(parent: QWidget, breakdown: RecipientBreakdown, threshold: int) -> bool:
    box, start_button, _cancel = build_large_campaign_box(parent, breakdown, threshold)
    box.exec()
    return box.clickedButton() is start_button


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
