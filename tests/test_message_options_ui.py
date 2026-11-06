"""The preview, the Message card and the editor follow the send plan: as
many bubbles as messages, in the send order; a notice when the text is
too long for a caption, with the order choice; the link preview block;
the options in templates, Retry and Demo Mode.

Synthetic texts; links point at t.me/example."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QApplication, QFrame, QLabel
from telethon.tl.types import MessageEntityTextUrl

from app.database.database import Database
from app.i18n import tr
from app.security.secure_storage import SecureStorage
from app.telegram.demo_client import DemoTelegramClient
from app.telegram.media_sender import Attachment, build_media_send_plan
from app.telegram.message_options import (
    LinkPreviewOptions,
    MediaTextOrder,
    MessageOptions,
    find_links,
    utf16_len,
)
from app.telegram.sender import send_to_recipient
from app.telegram.server_info import ServerInfoCache, fetch_link_preview
from app.ui.main_window import MainWindow
from app.ui.message_editor_dialog import MessageEditorDialog
from app.ui.message_preview import MessagePreviewWidget
from tests.mocks.mock_telegram_client import MockTelegramClient

TEXT_BODY = "Синтетический текст для проверки длины подписи. "


def _text(length: int, prefix: str = "") -> str:
    return (prefix + TEXT_BODY * (length // len(TEXT_BODY) + 2))[:length]


def _file(tmp_path: Path, name: str) -> Attachment:
    path = tmp_path / name
    path.write_bytes(b"x")
    return Attachment(path)


def _make_window(tmp_path: Path) -> MainWindow:
    return MainWindow(database=Database(tmp_path / "app.db"), secure_storage=SecureStorage(tmp_path / "s.dat"))


# ---- the preview draws the plan the sender executes ------------------------------------

_SENT_KIND = {"message": "text", "webpage": "text", "file": "media"}


def _cases(tmp_path):
    photo, doc = _file(tmp_path, "photo.jpg"), _file(tmp_path, "price.pdf")
    link = MessageOptions(link_preview=LinkPreviewOptions(url="https://t.me/example"))
    return [
        ("short text + photo", _text(500), [photo], MessageOptions(), 1024),
        ("long text + photo", _text(1500), [photo], MessageOptions(), 1024),
        ("long text + photo, media first", _text(1500), [photo], MessageOptions(order=MediaTextOrder.MEDIA_FIRST), 1024),
        ("long text + photo, Premium", _text(1500), [photo], MessageOptions(), 4096),
        ("text with a link preview", "Смотрите t.me/example", [], link, 1024),
        ("long text with a link + photo + file", _text(1500, "t.me/example "), [photo, doc], link, 1024),
        ("file only", "", [doc], MessageOptions(), 1024),
    ]


async def test_preview_draws_exactly_what_is_sent(qapp, tmp_path):
    for name, text, attachments, options, limit in _cases(tmp_path):
        client = MockTelegramClient()
        await send_to_recipient(client, "peer", text, [], attachments, options=options, caption_limit=limit)
        sent = [(_SENT_KIND[m[0]], m[2] if m[0] != "file" else (m[3] or "")) for m in client.sent_messages]

        widget = MessagePreviewWidget()
        plan = build_media_send_plan(attachments, text, [], options=options, caption_limit=limit, validate=False)
        widget.update_preview(text, [], [a.file_name for a in attachments], attachments, plan=plan)
        drawn = [(m.kind, m.text) for m in widget.planned_messages()]

        assert drawn == sent, name
        assert widget.bubble_count() == len(sent), name


async def test_link_card_is_drawn_above_or_below_the_text(qapp):
    widget = MessagePreviewWidget()
    for above in (False, True):
        options = MessageOptions(link_preview=LinkPreviewOptions(url="https://t.me/example", above_text=above))
        plan = build_media_send_plan([], "Смотрите t.me/example", [], options=options, validate=False)
        widget.update_preview("Смотрите t.me/example", [], plan=plan)
        widget.show()
        QApplication.processEvents()
        (bubble,) = widget._bubbles
        (card,) = [f for f in bubble.findChildren(QFrame) if f.objectName() == "linkPreviewCard"]
        assert (card.y() < widget._browser.y()) is above
        assert "t.me" in " ".join(label.text() for label in card.findChildren(QLabel))


# ---- the Campaign page ---------------------------------------------------------------------


async def test_long_text_with_photo_shows_two_bubbles_and_a_calm_notice(qapp, tmp_path):
    window = _make_window(tmp_path)
    window._attachments_widget.add_file(_file(tmp_path, "photo.jpg").path)
    window._message_text = _text(1487)
    window._update_message_preview()
    assert window._message_preview.bubble_count() == 2
    assert [m.kind for m in window._message_preview.planned_messages()] == ["text", "media"]
    notice = window._message_options_widget.notice_text()
    assert notice == tr("message_options.overflow_photo_two", length="1 487", limit="1 024", count=2)

    # The order choice changes what is sent -- and the preview with it.
    combo = window._message_options_widget.order_combo
    combo.setCurrentIndex(combo.findData(MediaTextOrder.MEDIA_FIRST))
    assert window._message_options.order == MediaTextOrder.MEDIA_FIRST
    assert [m.kind for m in window._message_preview.planned_messages()] == ["media", "text"]


async def test_short_text_with_photo_is_one_bubble_and_no_notice(qapp, tmp_path):
    window = _make_window(tmp_path)
    window._attachments_widget.add_file(_file(tmp_path, "photo.jpg").path)
    window._message_text = _text(500)
    window._update_message_preview()
    assert window._message_preview.bubble_count() == 1
    assert window._message_options_widget.notice_text() == ""


async def test_premium_limit_of_the_active_account_keeps_one_bubble(qapp, tmp_path):
    window = _make_window(tmp_path)
    window._enter_demo_mode()
    deadline = asyncio.get_event_loop().time() + 5
    while window._active_account() is None:
        assert asyncio.get_event_loop().time() < deadline
        await asyncio.sleep(0.02)
    window._server_info._caption_limits[window._server_info_key(window._active_account())] = 4096
    window._attachments_widget.add_file(_file(tmp_path, "photo.jpg").path)
    window._message_text = _text(1500)
    window._update_message_preview()
    assert window._message_preview.bubble_count() == 1
    assert window._message_options_widget.notice_text() == ""


async def test_name_that_might_not_fit_is_mentioned(qapp, tmp_path):
    window = _make_window(tmp_path)
    window._attachments_widget.add_file(_file(tmp_path, "photo.jpg").path)
    window._message_text = "{name}, " + _text(1000)
    window._update_message_preview()
    assert window._message_preview.bubble_count() == 1
    assert window._message_options_widget._name_hint.isVisibleTo(window._message_options_widget)


async def test_one_link_gets_a_switch_off_by_default(qapp, tmp_path):
    window = _make_window(tmp_path)
    window._message_text = "Смотрите t.me/example"
    window._update_message_preview()
    block = window._message_options_widget
    assert block._link_box.isVisibleTo(block)
    assert block.preview_check.isVisibleTo(block) and not block.link_combo.isVisibleTo(block)
    assert block.preview_check.isChecked() is False
    assert window._message_preview.planned_messages()[0].link_preview is None

    block.preview_check.setChecked(True)
    assert window._message_options.link_preview.url == "https://t.me/example"
    assert window._message_preview.planned_messages()[0].link_preview.url == "https://t.me/example"


async def test_no_links_no_block(qapp, tmp_path):
    window = _make_window(tmp_path)
    window._message_text = "Просто текст"
    window._update_message_preview()
    assert not window._message_options_widget._link_box.isVisibleTo(window._message_options_widget)


async def test_several_links_a_list_and_the_chosen_one_is_used(qapp, tmp_path):
    window = _make_window(tmp_path)
    text = "Сайт https://example.org и Алсу"
    window._message_text = text
    window._message_entities = [
        MessageEntityTextUrl(offset=utf16_len("Сайт https://example.org и "), length=4, url="https://t.me/example")
    ]
    window._update_message_preview()
    block = window._message_options_widget
    combo = block.link_combo
    assert combo.isVisibleTo(block) and not block.preview_check.isVisibleTo(block)
    assert [combo.itemData(i) for i in range(combo.count())] == [None, "https://example.org", "https://t.me/example"]
    assert combo.itemText(0) == tr("message_options.link_none")
    assert "Алсу" in combo.itemText(2) and "t.me" in combo.itemText(2)

    combo.setCurrentIndex(2)
    assert window._message_options.link_preview.url == "https://t.me/example"
    (message,) = window._message_preview.planned_messages()
    assert message.link_preview.url == "https://t.me/example"

    above = block.position_combo.findData(True)
    block.position_combo.setCurrentIndex(above)
    assert window._message_options.link_preview.above_text is True


async def test_preview_unavailable_in_a_caption_with_the_reason(qapp, tmp_path):
    window = _make_window(tmp_path)
    window._attachments_widget.add_file(_file(tmp_path, "photo.jpg").path)
    window._message_text = "Смотрите t.me/example"
    window._update_message_preview()
    block = window._message_options_widget
    assert block._link_box.isVisibleTo(block)
    assert not block.preview_check.isEnabled()
    assert block._caption_note.isVisibleTo(block)
    assert block._caption_note.text() == tr("message_options.caption_note")


async def test_editor_counts_against_the_caption_limit_when_there_is_media(qapp, tmp_path):
    photo = _file(tmp_path, "photo.jpg")
    dialog = MessageEditorDialog(_text(1487), [], attachments=[photo], caption_limit=1024)
    assert dialog._char_count_label.text() == tr(
        "message_editor_dialog.char_count_caption", count="1 487", limit="1 024"
    )
    assert dialog._char_count_label.property("status") == "warning"
    assert "1 487" in dialog.options_widget.notice_text()

    plain = MessageEditorDialog("Привет", [])
    assert plain._char_count_label.text() == tr("message_editor_dialog.char_count", count=6)


async def test_editor_returns_the_chosen_options(qapp):
    dialog = MessageEditorDialog("Смотрите t.me/example", [])
    dialog.options_widget.preview_check.setChecked(True)
    dialog._on_apply()
    assert dialog.result_options().link_preview.url == "https://t.me/example"


async def test_template_keeps_the_options(qapp, tmp_path):
    window = _make_window(tmp_path)
    window._message_text = "Смотрите t.me/example"
    window._update_message_preview()
    window._message_options_widget.preview_check.setChecked(True)
    with patch("app.ui.main_window.QInputDialog") as dialog:
        dialog.getText.return_value = ("With preview", True)
        window._templates_menu.save_action.trigger()

    window._set_message_options(MessageOptions())
    window._update_message_preview()
    assert window._message_options.link_preview.enabled is False

    (action,) = [a for a in window._templates_menu.load_menu.actions() if a.text() == "With preview"]
    action.trigger()
    assert window._message_options.link_preview.url == "https://t.me/example"
    assert window._message_options_widget.preview_check.isChecked()


async def test_retry_sends_with_the_original_runs_options_and_limit(qapp, tmp_path):
    from unittest.mock import MagicMock

    from app.campaign.send_queue import SendItemStatus
    from app.recipients.parser import parse_recipient_line

    window = _make_window(tmp_path)
    options = MessageOptions(order=MediaTextOrder.MEDIA_FIRST, link_preview=LinkPreviewOptions(url="https://t.me/example"))
    window._last_campaign_context = (MagicMock(), "t.me/example", [], [], {})
    window._last_campaign_send_options = (options, 4096)
    # Whatever is on the page now must not leak into the retry.
    window._set_message_options(MessageOptions())
    item = MagicMock(status=SendItemStatus.FAILED, next_step=0, recipient=parse_recipient_line("@someone"))
    window._report_source = MagicMock(items=[item], delivered_chat_ids=set())
    with patch.object(window, "_start_campaign", new=MagicMock(return_value=None)) as start, patch.object(
        window, "_spawn"
    ):
        window._retry_recipients([parse_recipient_line("@someone")])
    kwargs = start.call_args.kwargs
    assert kwargs["message_options"] == options and kwargs["caption_limit"] == 4096


# ---- Demo Mode -------------------------------------------------------------------------------


async def test_demo_mode_supports_the_new_modes(qapp, tmp_path):
    client = DemoTelegramClient()
    cache = ServerInfoCache()
    assert await cache.caption_limit("demo", client) == 1024
    info = await fetch_link_preview(client, "https://t.me/example")
    assert info is not None and info.site_name == "t.me" and info.title

    options = MessageOptions(link_preview=LinkPreviewOptions(url="https://t.me/example", above_text=True))
    with patch("app.telegram.demo_client.FAILURE_RATE", 0.0):
        await send_to_recipient(client, "peer", "Смотрите t.me/example", [], options=options)
        await send_to_recipient(client, "peer", "Без превью", [])
    assert [m[0] for m in client.sent_messages] == ["webpage", "message"]


def test_links_found_for_the_block_are_the_ones_the_plan_uses():
    # The block lists find_links(); the plan only previews a link that is
    # in that list -- one rule for both.
    links = find_links("Смотрите t.me/example", [])
    assert [link.url for link in links] == ["https://t.me/example"]


@pytest.fixture(autouse=True)
def _russian():
    from app.i18n import LANGUAGE_RU, set_language

    set_language(LANGUAGE_RU)
    yield
    set_language(LANGUAGE_RU)


async def test_wizard_options_reach_the_campaign_page(qapp, tmp_path):
    window = _make_window(tmp_path)
    wizard = window._build_campaign_wizard()
    try:
        wizard.set_message("Смотрите t.me/example", [])
        wizard._message_options_widget.preview_check.setChecked(True)
        assert wizard.result_state().message_options.link_preview.url == "https://t.me/example"
        wizard.recipient_widget.set_text("@someone")
        with patch.object(wizard, "exec", return_value=1), patch.object(window, "_on_start_requested"):
            window._campaign_wizard = None
            with patch.object(window, "_build_campaign_wizard", return_value=wizard):
                window._on_open_campaign_wizard_clicked()
        assert window._message_options.link_preview.url == "https://t.me/example"
        assert window._message_options_widget.preview_check.isChecked()
    finally:
        wizard.reject()


async def test_caption_limit_and_link_cards_follow_the_active_account(qapp, tmp_path):
    # Switching accounts (or Demo Mode in/out, or deleting one) must not
    # carry one account's caption limit or link cards over to another: a
    # Premium limit would split nothing for a regular account, and a card
    # that failed to load under one account would never be asked for again.
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from telethon.errors import FloodWaitError
    from telethon.tl.functions.messages import GetWebPagePreviewRequest

    window = _make_window(tmp_path)
    premium = SimpleNamespace(id=1, session_name="account_premium")
    regular = SimpleNamespace(id=2, session_name="account_regular")
    window._server_info._caption_limits[window._server_info_key(premium)] = 4096

    with patch.object(window, "_active_account", return_value=premium):
        assert window._current_caption_limit() == 4096
    with patch.object(window, "_active_account", return_value=regular):
        assert window._current_caption_limit() == 1024

    class _Offline(MockTelegramClient):
        async def __call__(self, request):
            if isinstance(request, GetWebPagePreviewRequest):
                raise FloodWaitError(request=None, capture=30)
            return await super().__call__(request)

    url = "https://t.me/example"
    offline = _Offline()
    with patch.object(window, "_active_account", return_value=premium), patch.object(
        window, "_connected_client", return_value=offline
    ):
        await window._server_info.link_preview(window._server_info_key(premium), offline, url)
        assert window._known_link_preview(url) is None

    with patch.object(window, "_active_account", return_value=regular), patch.object(
        window, "_connected_client", return_value=MockTelegramClient()
    ), patch.object(window, "_spawn", new=MagicMock()) as spawn:
        window._ensure_link_preview(url)
    assert spawn.called, "the other account asks Telegram for the card itself"
    spawn.call_args.args[0].close()
