"""Capture screenshots of every page and dialog, for docs/redesign and
docs/images.

Runs the real MainWindow on the real (Windows) Qt platform and the real
qasync loop, against an isolated temporary database and secret store --
never the user's own data -- in Demo Mode, with synthetic recipients,
message and attachments only.

    python scripts/capture_screenshots.py OUT_DIR [--theme dark|light] [--lang ru|en] [--only name,name]

Each shot is written as OUT_DIR/<name>_<theme>_<lang>.png.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
from pathlib import Path
from typing import Callable, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QWidget

parser = argparse.ArgumentParser()
parser.add_argument("out_dir")
parser.add_argument("--theme", default="dark")
parser.add_argument("--lang", default="ru")
parser.add_argument("--only", default="")
parser.add_argument("--width", type=int, default=1280)
parser.add_argument("--height", type=int, default=860)
args = parser.parse_args()

OUT = Path(args.out_dir)
OUT.mkdir(parents=True, exist_ok=True)
ONLY = {name for name in args.only.split(",") if name}

qt_app = QApplication(sys.argv)
from app.telegram.qt_bridge import install_event_loop  # noqa: E402

loop, close_event = install_event_loop(qt_app)

import app.ui.main_window as main_window_module  # noqa: E402
from app.database.database import Database  # noqa: E402
from app.database.repositories import SettingsRepository  # noqa: E402
from app.security.secure_storage import SecureStorage  # noqa: E402
from app.telegram.chat_targets import list_writable_chats  # noqa: E402
from app.telegram.demo_client import DemoTelegramClient  # noqa: E402


class _QuickRateLimiter:
    """Screenshots only: the real RateLimiter enforces the app's 5 s floor."""

    min_delay_seconds = 5
    max_delay_seconds = 5

    def __init__(self, *_a, **_k) -> None:
        pass

    def next_delay(self) -> float:
        return 0.6


main_window_module.RateLimiter = _QuickRateLimiter

TMP = Path(tempfile.mkdtemp(prefix="tms_shots_"))
SUFFIX = f"_{args.theme}_{args.lang}"


def _save(widget: QWidget, name: str) -> None:
    if ONLY and name not in ONLY:
        return
    qt_app.processEvents()
    widget.grab().save(str(OUT / f"{name}{SUFFIX}.png"))
    print("saved", name)


def _synthetic_images() -> List[Path]:
    paths = []
    for index, color in enumerate(("#6f8fc7", "#c79a6f", "#7fb38f")):
        image = QImage(640, 420, QImage.Format.Format_RGB32)
        image.fill(QColor(color))
        painter = QPainter(image)
        painter.setPen(QColor("#ffffff"))
        font = painter.font()
        font.setPixelSize(64)
        painter.setFont(font)
        painter.drawText(QRect(0, 0, 640, 420), Qt.AlignmentFlag.AlignCenter, f"Photo {index + 1}")
        painter.end()
        path = TMP / f"photo_{index + 1}.png"
        image.save(str(path))
        paths.append(path)
    document = TMP / "price-list.pdf"
    document.write_bytes(b"%PDF-1.4\n% synthetic\n")
    paths.append(document)
    return paths


db = Database(TMP / "app.db")
repo = SettingsRepository(db)
settings = repo.load_app_settings()
settings.theme = args.theme
settings.language = args.lang
settings.onboarding_completed = True
settings.journal_visible = False
repo.save_app_settings(settings)

window = main_window_module.MainWindow(
    database=db, secure_storage=SecureStorage(TMP / "secrets.dat"), close_event=close_event
)
window.resize(args.width, args.height)
window.show()


async def wait_until(predicate: Callable[[], bool], timeout: float = 30.0) -> None:
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise TimeoutError("condition not reached")
        await asyncio.sleep(0.05)


async def settle(seconds: float = 0.35) -> None:
    await asyncio.sleep(seconds)
    qt_app.processEvents()


async def show_dialog(dialog: QWidget, name: str, before_grab: Callable[[], None] = lambda: None) -> None:
    dialog.show()
    await settle()
    before_grab()
    await settle(0.15)
    _save(dialog, name)
    dialog.hide()  # close() may ask about unsaved changes
    dialog.deleteLater()


def message_entities():
    from telethon.tl.types import MessageEntityBold, MessageEntityItalic, MessageEntityTextUrl

    text = (
        "Здравствуйте, {name}!\n\nНапоминаем: встреча клуба в субботу в 18:00. "
        "Программа и адрес — по ссылке.\nДо встречи!"
        if args.lang == "ru"
        else "Hello, {name}!\n\nA reminder: the club meets on Saturday at 6 pm. "
        "Agenda and address are at the link.\nSee you there!"
    )
    link_word = "ссылке" if args.lang == "ru" else "link"
    from telethon.helpers import add_surrogate

    def offset(sub: str) -> int:
        return len(add_surrogate(text[: text.index(sub)]))

    entities = [
        MessageEntityBold(offset=0, length=len(add_surrogate(text.split("\n")[0]))),
        MessageEntityTextUrl(offset=offset(link_word), length=len(link_word), url="https://example.org/club"),
        MessageEntityItalic(offset=offset(text.split("\n")[-1]), length=len(add_surrogate(text.split("\n")[-1]))),
    ]
    return text, entities


RECIPIENTS = "\n".join(
    [
        "@anna_demo",
        "@ivan_demo",
        "+4917612345678",
        "123456789",
        "@demo_news",
        "-1001900000002",
        "-900000003",
        "@demo_forum",
        "@demo_partner_channel",
        "@demo_readonly_group",
        "@demo_slow_chat",
        "https://t.me/+NotJoinedHash",
        "not a recipient!",
    ]
)


async def scenario() -> None:
    from app.ui.campaign_wizard import CampaignWizardDialog
    from app.ui.chat_picker_dialog import ChatPickerDialog
    from app.ui.dialogs import confirm_delete_account, confirm_start_campaign
    from app.ui.login_dialog import LoginDialog
    from app.ui.message_editor_dialog import MessageEditorDialog
    from app.ui.onboarding_dialog import OnboardingDialog

    await settle(0.8)
    window._navigate_to_page(1)
    await settle()
    _save(window, "accounts_empty")
    window._navigate_to_page(0)
    await settle()
    _save(window, "campaign_empty")

    await show_dialog(OnboardingDialog(window), "dialog_onboarding")
    await show_dialog(LoginDialog(window._service, window), "dialog_login")

    window._enter_demo_mode()
    await wait_until(lambda: window._active_account() is not None)
    await settle(0.8)

    text, entities = message_entities()
    window._message_text, window._message_entities = text, entities
    window._recipient_widget.set_text(RECIPIENTS)
    for path in _synthetic_images():
        window._attachments_widget.add_file(path)
    window._update_message_preview()
    window._on_form_state_changed()
    await settle()
    _save(window, "campaign_filled")

    window._navigate_to_page(1)
    await settle()
    _save(window, "accounts")
    window._navigate_to_page(3)
    await settle()
    _save(window, "settings")
    window._navigate_to_page(0)
    await settle()

    await show_dialog(MessageEditorDialog(text, entities, window), "dialog_editor")

    chats = await list_writable_chats(DemoTelegramClient())
    picker = ChatPickerDialog(chats, window)
    await show_dialog(
        picker, "dialog_chat_picker", lambda: picker._list.item(0).setCheckState(Qt.CheckState.Checked)
    )

    wizard = CampaignWizardDialog(window._service.settings_repository, window)
    wizard._recipient_widget.set_text(RECIPIENTS)
    await show_dialog(wizard, "dialog_wizard_recipients")
    wizard = CampaignWizardDialog(window._service.settings_repository, window)
    wizard._recipient_widget.set_text(RECIPIENTS)
    wizard._message_text, wizard._message_entities = text, entities

    def to_preview() -> None:
        for _ in range(4):
            wizard._on_next_clicked()

    await show_dialog(wizard, "dialog_wizard_preview", to_preview)

    # Message boxes build and exec() themselves; show them instead.
    original_exec = QMessageBox.exec

    def grab_box(box: QMessageBox) -> int:
        box.show()
        qt_app.processEvents()
        _save(box, pending_box_name[0])
        box.hide()
        return 0

    pending_box_name = ["dialog_confirm_start"]
    QMessageBox.exec = grab_box
    try:
        confirm_start_campaign(window, 13, 4, 6)
        pending_box_name[0] = "dialog_delete_account"
        confirm_delete_account(window, "+10000000000")
    finally:
        QMessageBox.exec = original_exec

    window._journal.setVisible(True)
    window._on_start_requested()
    await wait_until(lambda: window._current_campaign is not None, 10)
    await wait_until(lambda: window._current_campaign.snapshot().sent >= 3, 30)
    await settle(0.2)
    _save(window, "campaign_running")
    _save(window, "journal")
    window._current_campaign.pause()
    await wait_until(lambda: window._current_campaign.status.value == "paused", 10)
    await settle()
    _save(window, "campaign_paused")
    finished = loop.create_future()
    window._current_campaign.finished.connect(lambda s: finished.done() or finished.set_result(s))
    window._current_campaign.resume()
    await asyncio.wait_for(finished, 60)
    window._journal.setVisible(False)
    await settle()

    window._navigate_to_page(2)
    window._results_filter_combo.setCurrentIndex(0)
    await settle()
    _save(window, "results")


async def main() -> None:
    code = 0
    try:
        await scenario()
    except Exception:  # noqa: BLE001
        import traceback

        traceback.print_exc()
        code = 1
    window.hide()
    window.deleteLater()
    await asyncio.sleep(0.2)
    loop.stop()
    sys.exit(code)


with loop:
    loop.create_task(main())
    loop.run_forever()
