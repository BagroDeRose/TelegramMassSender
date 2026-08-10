"""Message formatting tests (spec: full re-verification of every format,
not just "the button exists").

Covers round-tripping through extract_message_content() /
apply_content_to_editor() -- the mechanism the floating editor dialog
relies on to preserve formatting across close/reopen -- plus a regression
test for a real bug found during the UI/UX audit: links are rendered with
a decorative underline, which must never be picked up as a spurious extra
MessageEntityUnderline.
"""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QTextEdit
from telethon.helpers import add_surrogate
from telethon.tl.types import (
    MessageEntityBold,
    MessageEntityCode,
    MessageEntityItalic,
    MessageEntityPre,
    MessageEntitySpoiler,
    MessageEntityStrike,
    MessageEntityTextUrl,
    MessageEntityUnderline,
)

from app.ui.message_editor import (
    PROP_CODE,
    PROP_PRE,
    PROP_SPOILER,
    MessageEditorWidget,
    apply_content_to_editor,
    extract_message_content,
)


def _select(text_edit: QTextEdit, start: int, end: int, fmt: QTextCharFormat) -> None:
    cursor = text_edit.textCursor()
    cursor.setPosition(start)
    cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
    cursor.mergeCharFormat(fmt)


def _bold() -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setFontWeight(QFont.Weight.Bold.value)
    return fmt


def _link(url: str) -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setAnchor(True)
    fmt.setAnchorHref(url)
    fmt.setFontUnderline(True)  # exactly what the real "insert link" button does
    fmt.setForeground(QColor("#4ea1f7"))
    return fmt


def _entities_equal(a, b) -> bool:
    if len(a) != len(b):
        return False
    key = lambda e: (type(e).__name__, e.offset, e.length)
    for x, y in zip(sorted(a, key=key), sorted(b, key=key)):
        if type(x) is not type(y) or x.offset != y.offset or x.length != y.length:
            return False
        if isinstance(x, MessageEntityTextUrl) and x.url != y.url:
            return False
    return True


def test_link_does_not_produce_spurious_underline_entity(qapp):
    """Regression test: the link button visually underlines its text for
    affordance, which must not leak into the extracted entities as a
    separate MessageEntityUnderline alongside the MessageEntityTextUrl."""
    te = QTextEdit()
    te.setPlainText("Visit our website now")
    _select(te, 6, 14, _link("https://example.com"))

    text, entities = extract_message_content(te.document())
    assert text == "Visit our website now"
    assert len(entities) == 1
    assert isinstance(entities[0], MessageEntityTextUrl)
    assert entities[0].url == "https://example.com"


def test_roundtrip_all_basic_formats(qapp):
    cases = [
        ("bold", _bold(), MessageEntityBold),
        ("code", _fmt_with_prop(PROP_CODE), MessageEntityCode),
        ("pre", _fmt_with_prop(PROP_PRE), MessageEntityPre),
        ("spoiler", _fmt_with_prop(PROP_SPOILER), MessageEntitySpoiler),
    ]
    for name, fmt, entity_cls in cases:
        te = QTextEdit()
        te.setPlainText("Hello world")
        _select(te, 0, 5, fmt)

        text1, entities1 = extract_message_content(te.document())
        te2 = QTextEdit()
        apply_content_to_editor(te2, text1, entities1)
        text2, entities2 = extract_message_content(te2.document())

        assert text1 == text2 == "Hello world", name
        assert _entities_equal(entities1, entities2), name
        assert len(entities1) == 1 and isinstance(entities1[0], entity_cls), name


def _fmt_with_prop(prop) -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setProperty(prop, True)
    return fmt


def test_roundtrip_bold_link_combo(qapp):
    te = QTextEdit()
    te.setPlainText("Click here to continue")
    cursor = te.textCursor()
    cursor.setPosition(6)
    cursor.setPosition(10, QTextCursor.MoveMode.KeepAnchor)
    fmt = _bold()
    fmt.setAnchor(True)
    fmt.setAnchorHref("https://t.me/example")
    cursor.mergeCharFormat(fmt)

    text1, entities1 = extract_message_content(te.document())
    assert len(entities1) == 2  # exactly Bold + TextUrl, no spurious Underline

    te2 = QTextEdit()
    apply_content_to_editor(te2, text1, entities1)
    text2, entities2 = extract_message_content(te2.document())
    assert text1 == text2
    assert _entities_equal(entities1, entities2)


def test_roundtrip_emoji_utf16_offset(qapp):
    """'Привет 😀 мир' -- bolding 'мир' must land on the correct UTF-16
    offset, not be shifted by the emoji's surrogate pair."""
    te = QTextEdit()
    te.setPlainText("Привет 😀 мир")
    full = te.toPlainText()
    utf16_len = len(add_surrogate(full))
    _select(te, utf16_len - 3, utf16_len, _bold())

    text, entities = extract_message_content(te.document())
    assert text == "Привет 😀 мир"
    assert len(entities) == 1
    assert entities[0].offset == 10  # "Привет "=7 units + emoji=2 units + " "=1 unit
    assert entities[0].length == 3


def test_widget_set_content_get_content_roundtrip(qapp):
    widget = MessageEditorWidget()
    te = widget.text_edit
    te.setPlainText("Widget level test with a link and bold")
    _select(te, 0, 6, _bold())
    _select(te, 25, 29, _link("https://t.me/test"))
    text1, entities1 = widget.get_content()

    widget2 = MessageEditorWidget()
    widget2.set_content(text1, entities1)
    text2, entities2 = widget2.get_content()

    assert text1 == text2
    assert _entities_equal(entities1, entities2)


def test_toolbar_checked_state_tracks_cursor(qapp):
    widget = MessageEditorWidget()
    te = widget.text_edit
    te.setPlainText("plain bold plain")
    _select(te, 6, 10, _bold())

    cursor = te.textCursor()
    cursor.setPosition(8)
    te.setTextCursor(cursor)
    assert widget._toggle_buttons["bold"].isChecked() is True

    cursor.setPosition(2)
    te.setTextCursor(cursor)
    assert widget._toggle_buttons["bold"].isChecked() is False
