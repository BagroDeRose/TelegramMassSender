"""Simplified read-only preview of the message as it will roughly look in
Telegram: bold/italic/underline/strike/code/pre/spoiler/links rendered,
plus a list of attached file names. Not a pixel-perfect clone of the
Telegram UI -- just enough for the user to sanity-check formatting
without leaving the main window (spec: "упрощённый preview").
"""
from __future__ import annotations

from html import escape as html_escape
from typing import List, Optional, Sequence

from PySide6.QtWidgets import QLabel, QTextBrowser, QVBoxLayout, QWidget
from telethon.helpers import add_surrogate, del_surrogate
from telethon.tl.types import (
    MessageEntityBold,
    MessageEntityCode,
    MessageEntityItalic,
    MessageEntityPre,
    MessageEntitySpoiler,
    MessageEntityStrike,
    MessageEntityTextUrl,
    MessageEntityUnderline,
    TypeMessageEntity,
)

_PLACEHOLDER_HTML = '<span style="color:#7d7f85;">Текст сообщения появится здесь…</span>'


def _wrap_segment(escaped: str, active_entities: Sequence[TypeMessageEntity]) -> str:
    open_tags: List[str] = []
    close_tags: List[str] = []
    for entity in active_entities:
        if isinstance(entity, MessageEntityBold):
            open_tags.append("<b>")
            close_tags.insert(0, "</b>")
        elif isinstance(entity, MessageEntityItalic):
            open_tags.append("<i>")
            close_tags.insert(0, "</i>")
        elif isinstance(entity, MessageEntityUnderline):
            open_tags.append("<u>")
            close_tags.insert(0, "</u>")
        elif isinstance(entity, MessageEntityStrike):
            open_tags.append("<s>")
            close_tags.insert(0, "</s>")
        elif isinstance(entity, MessageEntityCode):
            open_tags.append(
                '<code style="background:#2b2d31;padding:1px 4px;border-radius:3px;'
                'font-family:Consolas,monospace;">'
            )
            close_tags.insert(0, "</code>")
        elif isinstance(entity, MessageEntityPre):
            open_tags.append(
                '<span style="font-family:Consolas,monospace;background:#2b2d31;'
                'padding:1px 4px;border-radius:3px;display:inline-block;">'
            )
            close_tags.insert(0, "</span>")
        elif isinstance(entity, MessageEntitySpoiler):
            open_tags.append('<span style="background:#54565c;color:#54565c;border-radius:3px;">')
            close_tags.insert(0, "</span>")
        elif isinstance(entity, MessageEntityTextUrl):
            open_tags.append(f'<a href="{html_escape(entity.url)}" style="color:#4ea1f7;">')
            close_tags.insert(0, "</a>")
    return "".join(open_tags) + escaped + "".join(close_tags)


def entities_to_preview_html(text: str, entities: List[TypeMessageEntity]) -> str:
    if not text:
        return _PLACEHOLDER_HTML

    surrogate_text = add_surrogate(text)
    cut_points = {0, len(surrogate_text)}
    for entity in entities:
        cut_points.add(max(0, min(entity.offset, len(surrogate_text))))
        cut_points.add(max(0, min(entity.offset + entity.length, len(surrogate_text))))
    points = sorted(cut_points)

    parts: List[str] = []
    for i in range(len(points) - 1):
        start, end = points[i], points[i + 1]
        if start >= end:
            continue
        segment = del_surrogate(surrogate_text[start:end])
        active = [e for e in entities if e.offset <= start < e.offset + e.length]
        escaped = html_escape(segment).replace("\n", "<br>")
        parts.append(_wrap_segment(escaped, active))
    return "".join(parts) or _PLACEHOLDER_HTML


class MessagePreviewWidget(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._browser = QTextBrowser(self)
        self._browser.setReadOnly(True)
        self._browser.setOpenExternalLinks(True)
        self._browser.setFixedHeight(140)
        self._browser.setHtml(_PLACEHOLDER_HTML)
        layout.addWidget(self._browser)

        self._attachments_label = QLabel(self)
        self._attachments_label.setWordWrap(True)
        self._attachments_label.setObjectName("attachmentsPreviewLabel")
        layout.addWidget(self._attachments_label)

    def update_preview(
        self,
        text: str,
        entities: List[TypeMessageEntity],
        attachment_names: Sequence[str] = (),
    ) -> None:
        self._browser.setHtml(entities_to_preview_html(text, entities))
        if attachment_names:
            self._attachments_label.setText("📎 " + ", ".join(attachment_names))
        else:
            self._attachments_label.setText("")
