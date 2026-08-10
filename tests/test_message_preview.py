"""Message preview rendering tests: HTML escaping (must be XSS-safe since
it renders user-typed text), formatting tags, and widget update behavior.
"""
from __future__ import annotations

from telethon.tl.types import MessageEntityBold, MessageEntityCode, MessageEntitySpoiler, MessageEntityTextUrl

from app.ui.message_preview import MessagePreviewWidget, entities_to_preview_html


def test_empty_text_shows_placeholder():
    html = entities_to_preview_html("", [])
    assert "Текст сообщения" in html


def test_plain_text_passthrough():
    assert entities_to_preview_html("Hello world", []) == "Hello world"


def test_html_special_characters_are_escaped():
    html = entities_to_preview_html("<script>alert(1)</script> & stuff", [])
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "&amp;" in html


def test_bold_and_link_rendering():
    entities = [
        MessageEntityBold(offset=0, length=5),
        MessageEntityTextUrl(offset=6, length=4, url="https://example.com"),
    ]
    html = entities_to_preview_html("Click here now", entities)
    assert "<b>Click</b>" in html
    assert '<a href="https://example.com"' in html
    assert ">here</a>" in html


def test_spoiler_and_code_rendering():
    entities = [MessageEntitySpoiler(offset=0, length=6), MessageEntityCode(offset=7, length=4)]
    html = entities_to_preview_html("secret code", entities)
    assert "background:#54565c" in html
    assert "<code" in html


def test_multiline_uses_br():
    assert "<br>" in entities_to_preview_html("line1\nline2", [])


def test_widget_update_preview(qapp):
    widget = MessagePreviewWidget()
    widget.update_preview("Hello", [MessageEntityBold(offset=0, length=5)], ["photo.jpg", "doc.pdf"])
    assert "📎" in widget._attachments_label.text()
    assert "photo.jpg" in widget._attachments_label.text()

    widget.update_preview("", [], [])
    assert widget._attachments_label.text() == ""
