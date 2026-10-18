"""app.ui.dialog_picker_model: the list model, filter proxy and row
delegate behind the "From my chats…" picker."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest
from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication, QListView, QStyleOptionViewItem

from app.i18n import get_language, set_language, tr
from app.recipients.parser import parse_recipient_line
from app.telegram.chat_targets import DialogCategory, DialogTarget, TargetType
from app.ui import theme
from app.ui.dialog_picker_model import (
    ALREADY_ADDED_ROLE,
    TARGET_ROLE,
    DialogFilterProxy,
    DialogListModel,
    DialogRowDelegate,
    dialog_initials,
    dialog_recipient_keys,
    format_dialog_date,
    selection_breakdown,
)

NOW = datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def _restore_language_and_theme():
    language, theme_name = get_language(), theme.get_active_theme()
    yield
    set_language(language)
    app = QApplication.instance()
    if theme.get_active_theme() != theme_name:
        theme.apply_theme(app, theme_name)


def _d(peer_id, title, target_type=TargetType.USER, *, username=None, bot=False, archived=False, age=0.0,
       reason=None, folders=()):
    return DialogTarget(
        peer_id=peer_id,
        title=title,
        username=username,
        target_type=target_type,
        is_bot=bot,
        archived=archived,
        last_message_date=None if age is None else NOW - timedelta(hours=age),
        unavailable_reason_key=reason,
        folder_ids=frozenset(folders),
    )


DIALOGS = [
    _d(101, "Anna Petrova", username="anna_p", age=1, folders={1}),
    _d(102, "Boris", age=3, archived=True, folders={1}),
    _d(103, "Helper", username="helper_bot", bot=True, age=5),
    _d(-1000000000201, "News", TargetType.CHANNEL, username="news", age=0.5, folders={2}),
    _d(-1000000000202, "Read-only channel", TargetType.CHANNEL, age=2,
       reason="chat_targets.reason.channel_admin_required"),
    _d(-1000000000203, "Team", TargetType.SUPERGROUP, age=4, folders={2}),
    _d(-205, "Family", TargetType.GROUP, age=6, archived=True),
    _d(-1000000000206, "Help Forum", TargetType.FORUM, username="help_forum", age=None),
]


@pytest.fixture
def model(qapp):
    return DialogListModel(DIALOGS)


@pytest.fixture
def proxy(model):
    proxy = DialogFilterProxy()
    proxy.setSourceModel(model)
    return proxy


def _titles(proxy):
    return [proxy.index(row, 0).data(TARGET_ROLE).title for row in range(proxy.rowCount())]


def _row(model, title):
    return next(row for row in range(model.rowCount()) if model.dialog(row).title == title)


def test_sorted_by_last_message_newest_first_undated_last(model):
    assert [model.dialog(r).title for r in range(model.rowCount())] == [
        "News", "Anna Petrova", "Read-only channel", "Boris", "Team", "Helper", "Family", "Help Forum",
    ]


def test_archive_hidden_by_default_and_shown_on_request(proxy):
    assert "Boris" not in _titles(proxy) and "Family" not in _titles(proxy)
    proxy.set_show_archived(True)
    assert "Boris" in _titles(proxy) and "Family" in _titles(proxy)


@pytest.mark.parametrize(
    "category, expected",
    [
        (None, ["News", "Anna Petrova", "Read-only channel", "Team", "Helper", "Help Forum"]),
        (DialogCategory.PEOPLE, ["Anna Petrova"]),
        (DialogCategory.BOTS, ["Helper"]),
        (DialogCategory.GROUPS, ["Team", "Help Forum"]),
        (DialogCategory.CHANNELS, ["News", "Read-only channel"]),
    ],
)
def test_type_filter(proxy, category, expected):
    proxy.set_category(category)
    assert _titles(proxy) == expected


def test_folder_filter(proxy):
    proxy.set_folder(1)
    assert _titles(proxy) == ["Anna Petrova"]
    proxy.set_show_archived(True)
    assert _titles(proxy) == ["Anna Petrova", "Boris"]
    proxy.set_folder(2)
    assert _titles(proxy) == ["News", "Team"]
    proxy.set_folder(None)
    assert len(_titles(proxy)) == 8


@pytest.mark.parametrize(
    "needle, expected",
    [
        ("anna", ["Anna Petrova"]),
        ("PETROVA", ["Anna Petrova"]),
        ("@helper_b", ["Helper"]),
        ("help", ["Helper", "Help Forum"]),
        ("news", ["News"]),
        ("  team ", ["Team"]),
        ("nobody", []),
    ],
)
def test_search_by_title_and_username(proxy, needle, expected):
    proxy.set_search_text(needle)
    assert _titles(proxy) == expected


def test_filters_combine(proxy):
    proxy.set_category(DialogCategory.GROUPS)
    proxy.set_search_text("help")
    assert _titles(proxy) == ["Help Forum"]


def test_unavailable_dialog_is_shown_but_not_selectable(model):
    row = _row(model, "Read-only channel")
    index = model.index(row)
    assert not index.flags() & Qt.ItemFlag.ItemIsUserCheckable
    assert index.data(Qt.ItemDataRole.CheckStateRole) is None
    assert not model.setData(index, Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
    model.set_rows_checked([row], True)
    assert model.checked_targets() == []
    assert index.data(Qt.ItemDataRole.ToolTipRole) == tr("chat_targets.reason.channel_admin_required")


def _existing(*lines):
    return {parse_recipient_line(line).normalized_key for line in lines}


@pytest.mark.parametrize(
    "line, title",
    [
        ("@anna_p", "Anna Petrova"),
        ("@ANNA_P", "Anna Petrova"),
        ("101", "Anna Petrova"),  # same person by ID
        ("https://t.me/anna_p", "Anna Petrova"),
        ("102", "Boris"),
        ("-1000000000203", "Team"),
        ("https://t.me/c/203", "Team"),
        ("@news", "News"),
        ("-1000000000201", "News"),  # same channel by marked ID
    ],
)
def test_already_listed_by_username_or_id(model, line, title):
    model.set_existing_keys(_existing(line))
    row = _row(model, title)
    index = model.index(row)
    assert index.data(ALREADY_ADDED_ROLE) is True
    assert not model.is_selectable(row)
    assert index.data(Qt.ItemDataRole.CheckStateRole) is None
    others = [r for r in range(model.rowCount()) if r != row]
    assert not any(model.is_already_added(r) for r in others)


def test_dialog_recipient_keys_cover_username_and_id():
    keys = dialog_recipient_keys(DIALOGS[0])
    assert keys == {"username:anna_p", "id:101"}
    assert dialog_recipient_keys(DIALOGS[1]) == {"id:102"}


def test_existing_keys_untick_a_dialog_that_becomes_listed(model):
    row = _row(model, "Anna Petrova")
    model.setData(model.index(row), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
    model.set_existing_keys(_existing("@anna_p"))
    assert model.checked_targets() == []


def test_select_all_shown_ticks_only_the_filtered_selectable_rows(model, proxy):
    proxy.set_category(DialogCategory.CHANNELS)
    model.set_rows_checked(proxy.visible_source_rows(), True)
    # Read-only channel is shown but can't be ticked.
    assert [d.title for d in model.checked_targets()] == ["News"]
    proxy.set_category(None)
    proxy.set_search_text("a")
    model.set_rows_checked(proxy.visible_source_rows(), True)
    assert [d.title for d in model.checked_targets()] == ["News", "Anna Petrova", "Team"]
    # "Select none" also only touches what's shown.
    proxy.set_search_text("team")
    model.set_rows_checked(proxy.visible_source_rows(), False)
    assert [d.title for d in model.checked_targets()] == ["News", "Anna Petrova"]


def test_ticks_survive_filtering_and_reload(model, proxy):
    model.setData(model.index(_row(model, "Team")), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
    proxy.set_category(DialogCategory.PEOPLE)
    assert [d.title for d in model.checked_targets()] == ["Team"]
    model.set_dialogs(DIALOGS)  # "Refresh"
    assert [d.title for d in model.checked_targets()] == ["Team"]
    model.set_dialogs([d for d in DIALOGS if d.title != "Team"])
    assert model.checked_targets() == []


def test_selection_breakdown():
    counts = selection_breakdown(DIALOGS)
    assert counts == {"people": 2, "bots": 1, "chats": 5}


def test_initials():
    assert dialog_initials("Anna Petrova") == "AP"
    assert dialog_initials("news_channel") == "NC"
    assert dialog_initials("Boris") == "B"
    assert dialog_initials("") == "?"
    assert dialog_initials("«Клуб» по средам") == "ПС"


def test_date_format():
    set_language("en")
    now = datetime(2026, 10, 18, 15, 0).astimezone()
    assert format_dialog_date(now.replace(hour=9, minute=5), now) == "09:05"
    assert format_dialog_date(now.replace(month=3, day=2), now) == "2 Mar"
    assert format_dialog_date(now.replace(year=2024, month=3, day=2), now) == "02.03.2024"
    assert format_dialog_date(None, now) == ""
    set_language("ru")
    assert format_dialog_date(now.replace(month=3, day=2), now).startswith("2 мар")


@pytest.mark.parametrize("theme_name", ["dark", "light"])
def test_delegate_paints_every_row_kind(qapp, model, theme_name):
    theme.apply_theme(qapp, theme_name)
    model.set_existing_keys(_existing("@anna_p"))
    view = QListView()
    proxy = DialogFilterProxy()
    proxy.setSourceModel(model)
    proxy.set_show_archived(True)
    view.setModel(proxy)
    delegate = DialogRowDelegate(view)
    view.setItemDelegate(delegate)
    view.resize(640, 480)
    image = QImage(640, 60, QImage.Format.Format_ARGB32)
    for row in range(proxy.rowCount()):
        index = proxy.index(row, 0)
        option = QStyleOptionViewItem()
        option.rect = view.visualRect(index).translated(0, -view.visualRect(index).top())
        option.widget = view
        option.rect.setWidth(640)
        option.rect.setHeight(delegate.sizeHint(option, index).height())
        painter = QPainter(image)
        delegate.paint(painter, option, index)
        painter.end()
    assert delegate.sizeHint(QStyleOptionViewItem(), proxy.index(0, 0)).height() == theme.DIALOG_PICKER_ROW_HEIGHT
    view.deleteLater()


def test_thousands_of_dialogs_filter_without_noticeable_delay(qapp):
    dialogs = []
    for index in range(5000):
        kind = index % 4
        target_type = (TargetType.USER, TargetType.USER, TargetType.SUPERGROUP, TargetType.CHANNEL)[kind]
        peer_id = 10_000 + index if target_type is TargetType.USER else -1_000_000_000_000 - index
        dialogs.append(
            _d(peer_id, f"Dialog {index}", target_type, username=f"name{index}" if index % 2 else None,
               bot=kind == 1, archived=index % 10 == 0, age=index / 60, folders={index % 3})
        )
    started = time.perf_counter()
    model = DialogListModel(dialogs)
    proxy = DialogFilterProxy()
    proxy.setSourceModel(model)
    build = time.perf_counter() - started
    view = QListView()
    view.setUniformItemSizes(True)
    view.setModel(proxy)

    timings = []
    for step in (
        lambda: proxy.set_category(DialogCategory.PEOPLE),
        lambda: proxy.set_folder(1),
        lambda: proxy.set_show_archived(True),
        lambda: proxy.set_search_text("dialog 4"),
        lambda: proxy.set_search_text("dialog 49"),
        lambda: proxy.set_search_text(""),
        lambda: proxy.set_category(None),
        lambda: proxy.set_folder(None),
        lambda: model.set_rows_checked(proxy.visible_source_rows(), True),
    ):
        started = time.perf_counter()
        step()
        QApplication.processEvents()
        timings.append(time.perf_counter() - started)
    assert proxy.rowCount() == 5000
    assert len(model.checked_targets()) == 5000
    assert build < 1.0, build
    # A filter change on 5000 dialogs stays well under what a person notices.
    assert max(timings) < 0.25, timings
    view.deleteLater()


def test_empty_model(qapp):
    model = DialogListModel([])
    assert model.rowCount() == 0
    assert model.data(QModelIndex()) is None
    model.set_existing_keys({"id:1"})
    assert model.checked_targets() == []
