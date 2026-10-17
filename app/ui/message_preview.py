"""Message preview that reads like a chat: an outgoing bubble with a tail on
a calm background, photos/videos as an album grid, other files as rows,
the formatted text, and a time stamp. Recognisable as a Telegram message
without copying Telegram's UI.

The text is rendered with the same entities -> HTML mapping as before
(bold/italic/underline/strike/code/pre/spoiler/links); colours inside that
HTML come from the active theme's tokens and are re-rendered on a theme
switch (theme.notifier). The bubble and album are painted from tokens at
paint time, so they follow a switch on their own.
"""
from __future__ import annotations

from datetime import datetime
from html import escape as html_escape
from pathlib import Path
from typing import List, Optional, Sequence

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)
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

from app.i18n import tr
from app.telegram.media_sender import AttachmentCategory, Attachment, MAX_ALBUM_SIZE
from app.ui import icons, theme
from app.ui.theme import (
    FONT_FAMILY_MONO,
    FONT_FAMILY_MONO_FALLBACK,
    ICON_SIZE,
    PREVIEW_ALBUM_GAP,
    PREVIEW_BUBBLE_MAX_WIDTH,
    PREVIEW_BUBBLE_PADDING,
    PREVIEW_MIN_HEIGHT,
    PREVIEW_TAIL,
    RADIUS_LG,
    RADIUS_SM,
    SPACE_MD,
    SPACE_SM,
    SPACE_XS,
)
from app.ui.thumbnails import make_thumbnail

_MONO = f"{FONT_FAMILY_MONO},{FONT_FAMILY_MONO_FALLBACK},monospace"


def _placeholder_html() -> str:
    return f'<span style="color:{theme.placeholder_text_color()};">{html_escape(tr("message_preview.placeholder"))}</span>'


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
                f'<code style="background:{theme.code_background()};padding:1px 4px;border-radius:3px;'
                f'font-family:{_MONO};">'
            )
            close_tags.insert(0, "</code>")
        elif isinstance(entity, MessageEntityPre):
            open_tags.append(
                f'<span style="font-family:{_MONO};background:{theme.code_background()};'
                'padding:1px 4px;border-radius:3px;display:inline-block;">'
            )
            close_tags.insert(0, "</span>")
        elif isinstance(entity, MessageEntitySpoiler):
            spoiler_color = theme.spoiler_preview_color()
            open_tags.append(
                f'<span style="background:{spoiler_color};color:{spoiler_color};border-radius:3px;">'
            )
            close_tags.insert(0, "</span>")
        elif isinstance(entity, MessageEntityTextUrl):
            open_tags.append(f'<a href="{html_escape(entity.url)}" style="color:{theme.link_color()};">')
            close_tags.insert(0, "</a>")
    return "".join(open_tags) + escaped + "".join(close_tags)


def entities_to_preview_html(text: str, entities: List[TypeMessageEntity]) -> str:
    if not text:
        return _placeholder_html()

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
    return "".join(parts) or _placeholder_html()


class _AlbumGrid(QWidget):
    """Photos/videos as Telegram lays out an album: two columns, the first
    item spanning the full width when the count is odd."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._pixmaps: List[Optional[QPixmap]] = []
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_paths(self, paths: Sequence[Path]) -> None:
        self._pixmaps = [make_thumbnail(path, PREVIEW_BUBBLE_MAX_WIDTH * 2) for path in paths[:MAX_ALBUM_SIZE]]
        self.setVisible(bool(self._pixmaps))
        self.updateGeometry()
        self.update()

    def _cells(self, width: int) -> List[QRectF]:
        count = len(self._pixmaps)
        gap = PREVIEW_ALBUM_GAP
        half = (width - gap) / 2
        cells: List[QRectF] = []
        y = 0.0
        index = 0
        if count % 2 == 1:
            cells.append(QRectF(0, 0, width, width * 0.56))
            y = width * 0.56 + gap
            index = 1
        while index < count:
            cells.append(QRectF(0, y, half, half * 0.8))
            if index + 1 < count:
                cells.append(QRectF(half + gap, y, half, half * 0.8))
            y += half * 0.8 + gap
            index += 2
        return cells

    def hasHeightForWidth(self) -> bool:  # noqa: N802 - Qt override
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - Qt override
        cells = self._cells(width)
        return int(cells[-1].bottom()) if cells else 0

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return QSize(PREVIEW_BUBBLE_MAX_WIDTH, self.heightForWidth(PREVIEW_BUBBLE_MAX_WIDTH))

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        tokens = theme.current_tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        for rect, pixmap in zip(self._cells(self.width()), self._pixmaps):
            path = QPainterPath()
            path.addRoundedRect(rect, RADIUS_SM, RADIUS_SM)
            painter.save()
            painter.setClipPath(path)
            painter.fillRect(rect, QColor(tokens.thumbnail_bg))
            if pixmap is not None and not pixmap.isNull():
                scaled = pixmap.scaled(
                    rect.size().toSize() * self.devicePixelRatioF(),
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
                scaled.setDevicePixelRatio(self.devicePixelRatioF())
                source = QRectF(
                    (scaled.width() / scaled.devicePixelRatio() - rect.width()) / 2,
                    (scaled.height() / scaled.devicePixelRatio() - rect.height()) / 2,
                    rect.width(),
                    rect.height(),
                )
                painter.drawPixmap(rect, scaled, QRectF(source.x() * scaled.devicePixelRatio(), source.y() * scaled.devicePixelRatio(), source.width() * scaled.devicePixelRatio(), source.height() * scaled.devicePixelRatio()))
            else:
                icons.themed("image", "text_muted").paint(
                    painter, rect.center().toPoint().x() - ICON_SIZE // 2, rect.center().toPoint().y() - ICON_SIZE // 2, ICON_SIZE, ICON_SIZE
                )
            painter.restore()
        painter.end()


class _Bubble(QFrame):
    """An outgoing message bubble with a small tail at the bottom-right,
    painted from the active tokens."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("chatBubble")
        self.setMaximumWidth(PREVIEW_BUBBLE_MAX_WIDTH + PREVIEW_TAIL)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        tokens = theme.current_tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        body = QRectF(0.5, 0.5, self.width() - PREVIEW_TAIL - 1, self.height() - 1)
        path = QPainterPath()
        path.addRoundedRect(body, RADIUS_LG, RADIUS_LG)
        tail = QPainterPath()
        right = body.right()
        bottom = body.bottom()
        tail.moveTo(right - RADIUS_LG, bottom)
        tail.lineTo(right + PREVIEW_TAIL, bottom)
        tail.quadTo(right, bottom - 2, right, bottom - RADIUS_LG)
        tail.lineTo(right - RADIUS_LG, bottom - RADIUS_LG)
        tail.closeSubpath()
        path = path.united(tail)
        painter.fillPath(path, QColor(tokens.bubble))
        if not tokens.is_dark:
            painter.setPen(QPen(QColor(tokens.border), 1))
            painter.drawPath(path)
        painter.end()
        super().paintEvent(event)


class MessagePreviewWidget(QFrame):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("chatPreview")
        self.setMinimumHeight(PREVIEW_MIN_HEIGHT)
        self._text = ""
        self._entities: List[TypeMessageEntity] = []
        self._html = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        canvas = QWidget()
        canvas_layout = QVBoxLayout(canvas)
        canvas_layout.setContentsMargins(SPACE_MD, SPACE_MD, SPACE_MD, SPACE_MD)
        canvas_layout.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        self._bubble = _Bubble(canvas)
        row.addWidget(self._bubble)
        canvas_layout.addLayout(row)
        scroll.setWidget(canvas)

        bubble_layout = QVBoxLayout(self._bubble)
        pad = PREVIEW_BUBBLE_PADDING
        bubble_layout.setContentsMargins(pad, pad, pad + PREVIEW_TAIL, pad - SPACE_XS)
        bubble_layout.setSpacing(SPACE_SM)

        self._album = _AlbumGrid(self._bubble)
        self._album.setVisible(False)
        bubble_layout.addWidget(self._album)

        self._files_box = QVBoxLayout()
        self._files_box.setSpacing(SPACE_XS)
        bubble_layout.addLayout(self._files_box)

        self._browser = QTextBrowser(self._bubble)
        self._browser.setObjectName("bubbleBrowser")
        self._browser.setReadOnly(True)
        self._browser.setOpenExternalLinks(True)
        self._browser.setFrameShape(QFrame.Shape.NoFrame)
        self._browser.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._browser.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._browser.document().setDocumentMargin(0)
        self._browser.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        bubble_layout.addWidget(self._browser)

        meta_row = QHBoxLayout()
        meta_row.addStretch(1)
        self._time_label = QLabel(self._bubble)
        self._time_label.setObjectName("bubbleMeta")
        meta_row.addWidget(self._time_label)
        bubble_layout.addLayout(meta_row)

        # Kept for callers that list attachment names under the preview
        # (e.g. the wizard); the bubble itself shows them visually.
        self._attachments_label = QLabel(self)
        self._attachments_label.setObjectName("attachmentsPreviewLabel")
        self._attachments_label.setWordWrap(True)
        self._attachments_label.setVisible(False)
        outer.addWidget(self._attachments_label)

        self._render()
        theme.on_theme_changed(self, self._on_theme_changed)

    # ---- public API ------------------------------------------------------------

    def update_preview(
        self,
        text: str,
        entities: List[TypeMessageEntity],
        attachment_names: Sequence[str] = (),
        attachments: Optional[Sequence[Attachment]] = None,
    ) -> None:
        self._text = text
        self._entities = list(entities)
        self._attachments_label.setText(", ".join(attachment_names))
        self._set_attachments(list(attachments or []), list(attachment_names))
        self._render()

    def rendered_html(self) -> str:
        """The HTML currently shown (as built, before QTextDocument
        normalises it) -- lets callers check what colours it uses."""
        return self._html

    # ---- internals --------------------------------------------------------------

    def _set_attachments(self, attachments: List[Attachment], names: List[str]) -> None:
        while self._files_box.count():
            item = self._files_box.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        album = [a.path for a in attachments if a.category == AttachmentCategory.ALBUM_ELIGIBLE]
        self._album.set_paths(album)
        file_names = [a.file_name for a in attachments if a.category != AttachmentCategory.ALBUM_ELIGIBLE]
        if not attachments:
            file_names = names  # names only (no paths): show them as files
        for name in file_names:
            self._files_box.addWidget(self._file_row(name))

    def _file_row(self, name: str) -> QWidget:
        row = QWidget(self._bubble)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_SM)
        icon = QLabel(row)
        icon.setObjectName("fileIcon")
        icon.setProperty("iconName", "document")
        layout.addWidget(icon)
        label = QLabel(name, row)
        label.setObjectName("bubbleText")
        layout.addWidget(label, 1)
        self._paint_file_icon(icon)
        return row

    def _paint_file_icon(self, label: QLabel) -> None:
        label.setPixmap(icons.themed_pixmap("document", "accent", ICON_SIZE, label.devicePixelRatioF()))

    def _on_theme_changed(self, _name: str) -> None:
        for label in self._bubble.findChildren(QLabel, "fileIcon"):
            self._paint_file_icon(label)
        self._render()

    def _render(self) -> None:
        self._html = entities_to_preview_html(self._text, self._entities)
        tokens = theme.current_tokens()
        self._browser.setHtml(f'<div style="color:{tokens.bubble_text};">{self._html}</div>')
        self._time_label.setText(datetime.now().strftime("%H:%M"))
        self._fit_browser()
        self._bubble.update()
        self._album.update()

    def _fit_browser(self) -> None:
        document = self._browser.document()
        width = max(1, self._browser.viewport().width() or (PREVIEW_BUBBLE_MAX_WIDTH - 2 * PREVIEW_BUBBLE_PADDING))
        document.setTextWidth(width)
        self._browser.setFixedHeight(int(document.size().height()) + 2)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._fit_browser()
