"""The "From my chats…" dialog itself (app.ui.chat_picker_dialog): states,
filters, ticking by mouse and keyboard, the counter, and what it hands back.
Presentational only -- fed with DialogList objects, no Telegram client."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.i18n import get_language, set_language, tr
from app.recipients.parser import parse_recipient_line
from app.telegram.chat_targets import DialogCategory, DialogFolder, DialogList, DialogTarget, TargetType
from app.ui.chat_picker_dialog import ChatPickerDialog
from app.ui.dialog_picker_model import TARGET_ROLE

NOW = datetime.now(timezone.utc)


def _d(peer_id, title, target_type=TargetType.USER, *, username=None, bot=False, archived=False, age=0,
       reason=None, folders=()):
    return DialogTarget(
        peer_id=peer_id,
        title=title,
        username=username,
        target_type=target_type,
        is_bot=bot,
        archived=archived,
        last_message_date=NOW - timedelta(hours=age),
        unavailable_reason_key=reason,
        folder_ids=frozenset(folders),
    )


DIALOGS = (
    _d(101, "Anna Petrova", username="anna_p", age=1, folders={7}),
    _d(102, "Boris", age=2, archived=True),
    _d(103, "Helper", username="helper_bot", bot=True, age=3),
    _d(-1000000000201, "News", TargetType.CHANNEL, username="news", age=4, folders={7}),
    _d(-1000000000202, "Partner channel", TargetType.CHANNEL, age=5,
       reason="chat_targets.reason.channel_admin_required"),
    _d(-1000000000203, "Team", TargetType.SUPERGROUP, age=6, folders={8}),
    _d(-205, "Family", TargetType.GROUP, age=7, archived=True),
)
FOLDERS = (DialogFolder(7, "Work"), DialogFolder(8, "Friends"))


@pytest.fixture(autouse=True)
def _english():
    language = get_language()
    set_language("en")
    yield
    set_language(language)


def _picker(dialogs=DIALOGS, folders=FOLDERS, existing=()):
    dialog = ChatPickerDialog({parse_recipient_line(line).normalized_key for line in existing})
    dialog.set_dialogs(DialogList(dialogs=tuple(dialogs), folders=tuple(folders)))
    return dialog


def _visible(dialog):
    return [dialog._proxy.index(row, 0).data(TARGET_ROLE).title for row in range(dialog._proxy.rowCount())]


def _proxy_row(dialog, title):
    return next(row for row in range(dialog._proxy.rowCount()) if dialog._proxy.index(row, 0).data(TARGET_ROLE).title == title)


def _click_row(dialog, title):
    dialog.show()
    QApplication.processEvents()
    index = dialog._proxy.index(_proxy_row(dialog, title), 0)
    rect = dialog._list.visualRect(index)
    QTest.mouseClick(dialog._list.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, rect.center())


# ---- states -------------------------------------------------------------------


def test_opens_in_loading_state_with_filters_disabled(qapp):
    dialog = ChatPickerDialog()
    assert dialog._pages.currentIndex() == 1  # loading
    assert dialog._loading_bar.maximum() == 0  # indeterminate
    assert not dialog._search_edit.isEnabled()
    assert not dialog._refresh_button.isEnabled()
    assert not dialog._add_button.isEnabled()


def test_loaded_list_shows_rows_newest_first_without_archive(qapp):
    dialog = _picker()
    assert dialog._pages.currentWidget() is dialog._list
    assert _visible(dialog) == ["Anna Petrova", "Helper", "News", "Partner channel", "Team"]
    assert dialog._search_edit.isEnabled() and dialog._refresh_button.isEnabled()


def test_refresh_returns_to_loading_and_keeps_ticks(qapp):
    dialog = _picker()
    emitted = []
    dialog.refresh_requested.connect(lambda: emitted.append(True))
    _click_row(dialog, "Team")
    dialog._refresh_button.click()
    assert emitted == [True]
    assert dialog._pages.currentIndex() == 1
    assert not dialog._refresh_button.isEnabled()  # no second load while one runs
    dialog.set_dialogs(DialogList(dialogs=DIALOGS, folders=FOLDERS))
    assert [t.title for t in dialog.selected_targets()] == ["Team"]


def test_error_state_keeps_refresh(qapp):
    dialog = ChatPickerDialog()
    dialog.set_error("Telegram has temporarily limited requests. Try again in 30 sec.")
    assert dialog._pages.currentWidget() is dialog._message_state
    texts = [label.text() for label in dialog._message_state.findChildren(type(dialog._selection_label))]
    assert tr("chat_picker.error_title") in texts
    assert dialog._refresh_button.isEnabled()
    assert not dialog._search_edit.isEnabled()


def test_account_without_dialogs(qapp):
    dialog = _picker(dialogs=(), folders=())
    texts = [label.text() for label in dialog._message_state.findChildren(type(dialog._selection_label))]
    assert tr("chat_picker.empty_title") in texts
    assert not dialog._select_all_button.isEnabled()


def test_nothing_matches_then_back(qapp):
    dialog = _picker()
    dialog._search_edit.setText("zzz")
    assert dialog._pages.currentWidget() is dialog._message_state
    assert not dialog._select_all_button.isEnabled()
    dialog._search_edit.clear()
    assert dialog._pages.currentWidget() is dialog._list


# ---- filters ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "category, expected",
    [
        (DialogCategory.PEOPLE, ["Anna Petrova"]),
        (DialogCategory.GROUPS, ["Team"]),
        (DialogCategory.CHANNELS, ["News", "Partner channel"]),
        (DialogCategory.BOTS, ["Helper"]),
    ],
)
def test_type_segments(qapp, category, expected):
    dialog = _picker()
    assert dialog._type_filter.currentData() is None  # "All" by default
    dialog._type_filter.setCurrentIndex(dialog._type_filter.findData(category))
    assert _visible(dialog) == expected


def test_type_segment_labels(qapp):
    dialog = _picker()
    labels = [button.text() for button in dialog._type_filter._buttons]
    assert labels == ["All", "People", "Groups", "Channels", "Bots"]


def test_folder_combo_lists_folders_and_filters(qapp):
    dialog = _picker()
    assert not dialog._folder_combo.isHidden()
    assert [dialog._folder_combo.itemText(i) for i in range(dialog._folder_combo.count())] == [
        "All folders", "Work", "Friends",
    ]
    dialog._folder_combo.setCurrentIndex(dialog._folder_combo.findData(7))
    assert _visible(dialog) == ["Anna Petrova", "News"]
    dialog._folder_combo.setCurrentIndex(dialog._folder_combo.findData(8))
    assert _visible(dialog) == ["Team"]


def test_folder_combo_hidden_without_folders(qapp):
    dialog = _picker(folders=())
    assert dialog._folder_combo.isHidden()
    assert len(_visible(dialog)) == 5


def test_folder_choice_survives_refresh_or_resets_if_gone(qapp):
    dialog = _picker()
    dialog._folder_combo.setCurrentIndex(dialog._folder_combo.findData(8))
    dialog.set_dialogs(DialogList(dialogs=DIALOGS, folders=FOLDERS))
    assert dialog._folder_combo.currentData() == 8 and _visible(dialog) == ["Team"]
    dialog.set_dialogs(DialogList(dialogs=DIALOGS, folders=FOLDERS[:1]))
    assert dialog._folder_combo.currentData() is None
    assert len(_visible(dialog)) == 5


def test_archive_toggle(qapp):
    dialog = _picker()
    assert not dialog._archive_toggle.isChecked()
    dialog._archive_toggle.setChecked(True)
    assert "Boris" in _visible(dialog) and "Family" in _visible(dialog)
    dialog._archive_toggle.setChecked(False)
    assert "Boris" not in _visible(dialog)


def test_search_by_name_title_and_username(qapp):
    dialog = _picker()
    dialog._search_edit.setText("petrova")
    assert _visible(dialog) == ["Anna Petrova"]
    dialog._search_edit.setText("@helper")
    assert _visible(dialog) == ["Helper"]
    dialog._search_edit.setText("NEWS")
    assert _visible(dialog) == ["News"]


# ---- ticking ---------------------------------------------------------------------------


def test_click_anywhere_on_a_row_ticks_it(qapp):
    dialog = _picker()
    _click_row(dialog, "Anna Petrova")
    assert [t.title for t in dialog.selected_targets()] == ["Anna Petrova"]
    _click_row(dialog, "Anna Petrova")
    assert dialog.selected_targets() == []


def test_space_ticks_the_current_row(qapp):
    dialog = _picker()
    dialog.show()
    QApplication.processEvents()
    dialog._list.setFocus()
    dialog._list.setCurrentIndex(dialog._proxy.index(_proxy_row(dialog, "Team"), 0))
    QTest.keyClick(dialog._list, Qt.Key.Key_Space)
    assert [t.title for t in dialog.selected_targets()] == ["Team"]


def test_unavailable_row_cannot_be_ticked_and_explains_why(qapp):
    dialog = _picker()
    _click_row(dialog, "Partner channel")
    dialog._select_all_button.click()
    assert "Partner channel" not in [t.title for t in dialog.selected_targets()]
    index = dialog._proxy.index(_proxy_row(dialog, "Partner channel"), 0)
    assert index.data(Qt.ItemDataRole.ToolTipRole) == tr("chat_targets.reason.channel_admin_required")


@pytest.mark.parametrize("line", ["@anna_p", "101", "https://t.me/anna_p"])
def test_already_listed_person_is_marked_and_not_tickable(qapp, line):
    dialog = _picker(existing=[line])
    _click_row(dialog, "Anna Petrova")
    dialog._select_all_button.click()
    titles = [t.title for t in dialog.selected_targets()]
    assert "Anna Petrova" not in titles
    index = dialog._proxy.index(_proxy_row(dialog, "Anna Petrova"), 0)
    assert index.data(Qt.ItemDataRole.ToolTipRole) == tr("chat_picker.already_added_tooltip")


@pytest.mark.parametrize("line", ["@news", "-1000000000201", "https://t.me/c/201"])
def test_already_listed_channel_by_name_or_id(qapp, line):
    dialog = _picker(existing=[line])
    dialog._select_all_button.click()
    assert "News" not in [t.title for t in dialog.selected_targets()]


def test_select_all_shown_only_ticks_the_filtered_rows(qapp):
    dialog = _picker()
    dialog._type_filter.setCurrentIndex(dialog._type_filter.findData(DialogCategory.PEOPLE))
    dialog._select_all_button.click()
    dialog._type_filter.setCurrentIndex(dialog._type_filter.findData(DialogCategory.GROUPS))
    dialog._select_all_button.click()
    # Archived (hidden) people and groups weren't ticked.
    assert [t.title for t in dialog.selected_targets()] == ["Anna Petrova", "Team"]
    dialog._select_none_button.click()
    assert [t.title for t in dialog.selected_targets()] == ["Anna Petrova"]


def test_counter_splits_people_bots_and_chats(qapp):
    dialog = _picker()
    assert dialog._selection_label.text() == tr("chat_picker.selected_none")
    assert not dialog._add_button.isEnabled()
    dialog._select_all_button.click()
    assert dialog._selection_label.text() == "Selected: 4 (people 1, bots 1, chats 2)"
    assert dialog._add_button.isEnabled()
    dialog._type_filter.setCurrentIndex(dialog._type_filter.findData(DialogCategory.BOTS))
    dialog._select_none_button.click()
    assert dialog._selection_label.text() == "Selected: 3 (people 1, chats 2)"
    set_language("ru")
    dialog._update_selection_label()
    assert dialog._selection_label.text() == "Выбрано: 3 (людей 1, чатов 2)"


def test_selected_lines_prefer_username_else_id(qapp):
    dialog = _picker()
    dialog._archive_toggle.setChecked(True)
    dialog._select_all_button.click()
    assert dialog.selected_lines() == ["@anna_p", "102", "@helper_bot", "@news", "-1000000000203", "-205"]
    for line in dialog.selected_lines():
        assert parse_recipient_line(line).is_valid


def test_add_is_the_primary_rightmost_button(qapp):
    dialog = _picker()
    dialog.show()
    QApplication.processEvents()
    assert dialog._add_button.property("variant") == "primary"
    footer_buttons = [b for b in dialog.findChildren(type(dialog._add_button)) if b.parentWidget().objectName() == "dialogFooter"]
    cancel = next(b for b in footer_buttons if b.text() == tr("dialogs.cancel"))
    assert dialog._add_button.mapTo(dialog, QPoint(0, 0)).x() > cancel.mapTo(dialog, QPoint(0, 0)).x()
    assert max(footer_buttons, key=lambda b: b.mapTo(dialog, QPoint(0, 0)).x()) is dialog._add_button


def test_both_languages(qapp):
    for language in ("ru", "en"):
        set_language(language)
        dialog = _picker()
        assert dialog.windowTitle() == tr("chat_picker.title")
        assert dialog._archive_toggle.text() == tr("chat_picker.show_archive")
        assert dialog._select_all_button.text() == tr("chat_picker.select_visible")
        assert dialog._folder_combo.itemText(0) == tr("chat_picker.folder_all")


# ---- shared folders (chat lists joined by link) --------------------------------------


async def test_shared_folder_from_a_link_appears_and_filters(qapp):
    """A DialogFilterChatlist (a folder added through a t.me/addlist link)
    sits in the folder combo next to the ordinary folders, in Telegram's
    order, and narrows the list to its own chats."""
    from telethon.tl.types import (
        DialogFilter,
        DialogFilterChatlist,
        DialogFilterDefault,
        InputPeerChannel,
        InputPeerUser,
    )

    from app.telegram.chat_targets import list_dialogs
    from tests.mocks.mock_telegram_client import MockTelegramClient, make_fake_channel, make_user

    news = make_fake_channel(301, "Shared News", username="shared_news", broadcast=True, creator=True)
    club = make_fake_channel(302, "Club Chat")
    other = make_fake_channel(303, "Other Group")
    anna = make_user(401, "Anna", contact=True)
    client = MockTelegramClient(
        dialogs=[news, club, other, anna],
        dialog_filters=[
            DialogFilterDefault(),
            DialogFilter(id=2, title="Contacts", pinned_peers=[], include_peers=[], exclude_peers=[], contacts=True),
            DialogFilterChatlist(
                id=5,
                title="Club (shared)",
                pinned_peers=[InputPeerChannel(channel_id=302, access_hash=1)],
                include_peers=[InputPeerChannel(channel_id=301, access_hash=1), InputPeerUser(user_id=401, access_hash=1)],
                has_my_invites=True,
                emoticon="📚",
            ),
        ],
    )
    dialog = ChatPickerDialog()
    dialog.set_dialogs(await list_dialogs(client))
    combo = dialog._folder_combo
    assert not combo.isHidden()
    assert [combo.itemText(i) for i in range(combo.count())] == ["All folders", "Contacts", "Club (shared)"]
    combo.setCurrentIndex(combo.findData(5))
    assert sorted(_visible(dialog)) == ["Anna", "Club Chat", "Shared News"]
    combo.setCurrentIndex(combo.findData(2))
    assert _visible(dialog) == ["Anna"]


async def test_only_a_shared_folder_still_shows_the_folder_filter(qapp):
    from telethon.tl.types import DialogFilterChatlist, InputPeerChannel

    from app.telegram.chat_targets import list_dialogs
    from tests.mocks.mock_telegram_client import MockTelegramClient, make_fake_channel

    club = make_fake_channel(302, "Club Chat")
    client = MockTelegramClient(
        dialogs=[club, make_fake_channel(303, "Other Group")],
        dialog_filters=[
            DialogFilterChatlist(
                id=9, title="Club", pinned_peers=[], include_peers=[InputPeerChannel(channel_id=302, access_hash=1)]
            )
        ],
    )
    dialog = ChatPickerDialog()
    dialog.set_dialogs(await list_dialogs(client))
    assert not dialog._folder_combo.isHidden()
    dialog._folder_combo.setCurrentIndex(dialog._folder_combo.findData(9))
    assert _visible(dialog) == ["Club Chat"]
