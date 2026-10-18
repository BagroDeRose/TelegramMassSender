"""UI for group/channel targets: the "From my chats…" button and picker
dialog, the start-confirmation breakdown, chat types on the Results list,
and Retry carrying already-delivered chats/steps forward -- all through
MainWindow's single start path.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from PySide6.QtCore import Qt

from app.campaign.send_queue import SendItem, SendItemStatus
from app.database.database import Database
from app.i18n import get_language, set_language, tr
from app.recipients.parser import parse_recipient_line
from app.security.secure_storage import SecureStorage
from app.telegram.chat_targets import ChatTarget, TargetType
from app.ui.chat_picker_dialog import ChatPickerDialog
from app.ui.dialogs import start_campaign_breakdown
from app.ui.main_window import MainWindow
from app.ui.recipient_widget import RecipientWidget

CHATS = [
    ChatTarget(peer_id=-1000000000001, title="Daily News", username="daily_news", target_type=TargetType.CHANNEL),
    ChatTarget(peer_id=-1000000000002, title="Team Room", username=None, target_type=TargetType.SUPERGROUP),
    ChatTarget(peer_id=-3, title="Family", username=None, target_type=TargetType.GROUP),
    ChatTarget(peer_id=-1000000000004, title="Help Forum", username="help_forum", target_type=TargetType.FORUM),
]


def _make_window(tmp_path: Path) -> MainWindow:
    storage = SecureStorage(tmp_path / "secrets.dat")
    return MainWindow(database=Database(tmp_path / "app.db"), secure_storage=storage)


async def _wait_until(predicate, timeout=5.0):
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("condition not reached")
        await asyncio.sleep(0.02)


# ---- picker dialog ---------------------------------------------------------------


def _visible_titles(dialog: ChatPickerDialog):
    return [
        dialog._list.item(i).data(Qt.ItemDataRole.UserRole).title
        for i in range(dialog._list.count())
        if not dialog._list.item(i).isHidden()
    ]


def test_picker_type_filter_and_search(qapp):
    dialog = ChatPickerDialog(CHATS)
    assert _visible_titles(dialog) == ["Daily News", "Team Room", "Family", "Help Forum"]

    dialog._type_combo.setCurrentIndex(dialog._type_combo.findData(TargetType.CHANNEL.value))
    assert _visible_titles(dialog) == ["Daily News"]

    dialog._type_combo.setCurrentIndex(0)
    dialog._search_edit.setText("team")
    assert _visible_titles(dialog) == ["Team Room"]

    dialog._search_edit.setText("nothing like this")
    assert _visible_titles(dialog) == []
    assert dialog._empty_label.isHidden() is False


def test_picker_select_shown_and_selected_targets(qapp):
    dialog = ChatPickerDialog(CHATS)
    assert dialog._add_button.isEnabled() is False
    dialog._type_combo.setCurrentIndex(dialog._type_combo.findData(TargetType.SUPERGROUP.value))
    dialog._select_all_button.click()
    dialog._type_combo.setCurrentIndex(dialog._type_combo.findData(TargetType.GROUP.value))
    dialog._select_all_button.click()
    # Ticked rows hidden by the current filter still count.
    assert [c.title for c in dialog.selected_targets()] == ["Team Room", "Family"]
    assert dialog._add_button.isEnabled() is True
    dialog._select_none_button.click()  # only the visible (Family) row is cleared
    assert [c.title for c in dialog.selected_targets()] == ["Team Room"]


# ---- recipient widget --------------------------------------------------------------


def test_pick_chats_button_only_on_the_main_campaign_page_widget(qapp):
    assert RecipientWidget()._pick_chats_button.isHidden() is True  # e.g. the Campaign Wizard's
    widget = RecipientWidget(show_chat_picker=True)
    assert widget._pick_chats_button.isHidden() is False
    assert widget._pick_chats_button.isEnabled() is False


def test_append_lines_skips_existing_targets(qapp):
    widget = RecipientWidget(show_chat_picker=True)
    widget.set_text("@ivan_petrov\n-1000000000002")
    added = widget.append_lines(["@daily_news", "-1000000000002", "-3"])
    assert added == 2
    assert widget.get_text() == "@ivan_petrov\n-1000000000002\n@daily_news\n-3"


def test_summary_mentions_chat_targets(qapp):
    widget = RecipientWidget()
    widget.set_text("@ivan_petrov\n-1001234567890\nhttps://t.me/+Abc123")
    assert tr("recipient_widget.summary_chat_count", count=2) in widget._summary_label.text()
    widget.set_text("@ivan_petrov\n@maria_test")
    assert "-100" not in widget._summary_label.text()
    assert tr("recipient_widget.summary_chat_count", count=0) not in widget._summary_label.text()


# ---- confirmation ------------------------------------------------------------------


def test_start_confirmation_breakdown():
    text = start_campaign_breakdown(user_count=3, chat_count=2, username_count=4)
    assert tr("dialogs.start_campaign.users_line", count=3) in text
    assert tr("dialogs.start_campaign.chats_line", count=2) in text
    assert tr("dialogs.start_campaign.usernames_line", count=4) in text
    only_users = start_campaign_breakdown(user_count=5, chat_count=0, username_count=0)
    assert only_users == tr("dialogs.start_campaign.users_line", count=5)


async def test_start_confirmation_receives_users_and_chats_separately(qapp, tmp_path):
    window = _make_window(tmp_path)
    window._enter_demo_mode()
    window._recipient_widget.set_text("@ivan_petrov\n123456789\n-1001234567890\nhttps://t.me/c/2222222222/5\n+4917612345678")
    window._message_text = "hello"
    settings = window._service.settings_repository.load_app_settings()
    settings.confirm_before_start = True
    window._service.settings_repository.save_app_settings(settings)

    with patch("app.ui.main_window.confirm_start_campaign", return_value=False) as confirm:
        window._on_start_requested()

    confirm.assert_called_once()
    _, total, chat_count, username_count = confirm.call_args[0]
    assert (total, chat_count, username_count) == (5, 2, 1)
    assert window._campaign_starting is False


# ---- "From my chats…" in MainWindow --------------------------------------------------


async def test_pick_chats_button_follows_connection_and_campaign_state(qapp, tmp_path):
    window = _make_window(tmp_path)
    button = window._recipient_widget._pick_chats_button
    assert button.isEnabled() is False  # no account

    window._enter_demo_mode()
    await _wait_until(lambda: button.isEnabled())

    fake_campaign = MagicMock()
    fake_campaign.is_active = True
    window._current_campaign = fake_campaign
    window._on_form_state_changed()
    assert button.isEnabled() is False

    window._current_campaign = None
    window._on_form_state_changed()
    assert button.isEnabled() is True


async def test_pick_chats_in_demo_mode_adds_the_ticked_chats(qapp, tmp_path):
    window = _make_window(tmp_path)
    window._enter_demo_mode()
    await _wait_until(lambda: window._recipient_widget._pick_chats_button.isEnabled())
    window._recipient_widget.set_text("@ivan_petrov")

    shown = {}

    def fake_exec(dialog):
        shown["titles"] = [dialog._list.item(i).data(Qt.ItemDataRole.UserRole).title for i in range(dialog._list.count())]
        for i in range(dialog._list.count()):
            chat = dialog._list.item(i).data(Qt.ItemDataRole.UserRole)
            if chat.title in ("Demo News", "Demo Family"):
                dialog._list.item(i).setCheckState(Qt.CheckState.Checked)
        return ChatPickerDialog.DialogCode.Accepted

    with patch.object(ChatPickerDialog, "exec", fake_exec):
        window._recipient_widget._pick_chats_button.click()
        await _wait_until(lambda: "Demo Family" in str(shown) and not window._chat_picker_loading)
        await asyncio.sleep(0.05)

    assert "Demo Partner Channel" not in shown["titles"]  # can't post there
    assert window._recipient_widget.get_text() == "@ivan_petrov\n@demo_news\n-900000003"
    assert window._recipient_widget._pick_chats_button.isEnabled() is True


async def test_pick_chats_flood_wait_is_reported_not_retried(qapp, tmp_path):
    from tests.mocks.mock_telegram_client import make_flood_wait

    window = _make_window(tmp_path)
    window._enter_demo_mode()
    await _wait_until(lambda: window._recipient_widget._pick_chats_button.isEnabled())

    async def flood(_client):
        raise make_flood_wait(120)

    with patch("app.ui.main_window.list_writable_chats", new=flood), patch("app.ui.main_window.show_error") as err:
        window._on_pick_chats_requested()
        await _wait_until(lambda: err.called)
    assert tr("chat_picker.error.flood_wait", seconds=120) == err.call_args[0][2]
    await _wait_until(lambda: window._recipient_widget._pick_chats_button.isEnabled())


# ---- results / retry -------------------------------------------------------------------


def _mixed_report_source():
    source = MagicMock()
    source.items = [
        SendItem(recipient=parse_recipient_line("@daily_news"), status=SendItemStatus.SENT, target_type="channel", resolved_id=-1000000000001),
        SendItem(recipient=parse_recipient_line("@ivan_petrov"), status=SendItemStatus.FAILED, target_type="user", error="x"),
        SendItem(
            recipient=parse_recipient_line("-1000000000001"),
            status=SendItemStatus.FAILED,
            target_type="channel",
            resolved_id=-1000000000001,
            error="y",
        ),
        SendItem(
            recipient=parse_recipient_line("@slow_chat"),
            status=SendItemStatus.FAILED,
            target_type="supergroup",
            resolved_id=-1000000000009,
            error=tr("chat_targets.reason.slowmode_wait", seconds=30),
            next_step=1,
        ),
    ]
    source.delivered_chat_ids = {-1000000000001}
    return source


async def test_results_list_shows_chat_types(qapp, tmp_path):
    window = _make_window(tmp_path)
    window._report_source = _mixed_report_source()
    window._results_filter_combo.setCurrentIndex(0)  # "all"
    window._refresh_failed_items()
    texts = [window._failed_items_list.item(i).text() for i in range(window._failed_items_list.count())]
    assert any(t.startswith("@slow_chat  (" + tr("chat_targets.type.supergroup") + ")") for t in texts)
    assert any(t.startswith("@ivan_petrov  —") for t in texts), "users keep their exact label"


async def test_retry_of_a_mixed_list_skips_delivered_chats_and_steps(qapp, tmp_path):
    window = _make_window(tmp_path)
    window._report_source = _mixed_report_source()
    window._refresh_failed_items()
    window._last_campaign_context = (MagicMock(), "hello", [], [], {})

    with patch.object(window, "_start_campaign", new=AsyncMock()) as mock_start:
        window._on_retry_all_failures_clicked()
        await asyncio.sleep(0)

    mock_start.assert_called_once()
    recipients = mock_start.call_args[0][1]
    assert [r.display_label for r in recipients] == ["@ivan_petrov", "-1000000000001", "@slow_chat"]
    kwargs = mock_start.call_args.kwargs
    assert kwargs["delivered_chat_ids"] == {-1000000000001}
    assert kwargs["resume_steps"] == {"username:slow_chat": 1}


async def test_retry_end_to_end_does_not_resend_to_a_delivered_chat(qapp, tmp_path):
    from app.campaign.campaign_manager import CampaignManager
    from tests.mocks.mock_telegram_client import MockTelegramClient, make_fake_channel

    channel = make_fake_channel(1, "Daily News", username="daily_news", broadcast=True, creator=True)
    client = MockTelegramClient(chats={"daily_news": channel, -1000000000001: channel}, dialogs=[channel])

    class Instant:
        def next_delay(self):
            return 0.01

    retry = CampaignManager(
        client=client,
        recipients=[parse_recipient_line("-1000000000001")],
        message_text="hi",
        message_entities=[],
        attachments=[],
        rate_limiter=Instant(),
        max_retries=1,
        delivered_chat_ids=_mixed_report_source().delivered_chat_ids,
    )
    done = asyncio.get_event_loop().create_future()
    retry.finished.connect(lambda s: done.done() or done.set_result(s))
    retry.start()
    await asyncio.wait_for(done, timeout=5)
    assert retry.items[0].status == SendItemStatus.SKIPPED
    assert client.sent_messages == []


# ---- language / theme --------------------------------------------------------------------


def test_picker_and_button_render_in_both_languages(qapp):
    original_language = get_language()
    try:
        for language in ("ru", "en"):
            set_language(language)
            widget = RecipientWidget(show_chat_picker=True)
            widget.retranslate_ui()
            assert widget._pick_chats_button.text() == tr("recipient_widget.pick_chats_button")
            dialog = ChatPickerDialog(CHATS)
            assert dialog.windowTitle() == tr("chat_picker.title")
            assert tr("chat_targets.type.channel") in dialog._list.item(0).text()
    finally:
        set_language(original_language)


async def test_failure_breakdown_groups_slow_mode_regardless_of_seconds(qapp, tmp_path):
    window = _make_window(tmp_path)
    source = MagicMock()
    source.items = [
        SendItem(
            recipient=parse_recipient_line(f"@slow_{n}"),
            status=SendItemStatus.FAILED,
            target_type="supergroup",
            error=tr("chat_targets.reason.slowmode_wait", seconds=n),
            error_category="slowmode",
        )
        for n in (12, 29, 47)
    ] + [
        SendItem(
            recipient=parse_recipient_line("@locked_group"),
            status=SendItemStatus.FAILED,
            target_type="supergroup",
            error=tr("chat_targets.reason.write_forbidden"),
        )
    ]
    window._report_source = source
    window._refresh_failed_items()

    breakdown = window._failure_categories_label.text()
    assert f"{tr('chat_targets.reason.slowmode')}: 3" in breakdown
    assert f"{tr('chat_targets.reason.write_forbidden')}: 1" in breakdown
    assert "29" not in breakdown and "12" not in breakdown
    # Each recipient's own reason keeps its exact wait.
    texts = [window._failed_items_list.item(i).text() for i in range(window._failed_items_list.count())]
    assert any(tr("chat_targets.reason.slowmode_wait", seconds=29) in t for t in texts)
