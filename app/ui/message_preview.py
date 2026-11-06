"""Message preview that reads like a chat: outgoing bubbles with a tail on a
calm background -- one per message that will actually be sent, in the
send order (the send plan from app.telegram.media_sender, the one the
sender executes): photos/videos as an album grid, other files as rows,
the text as a caption or a message of its own, a link preview card above
or below it, and a time stamp. Recognisable as Telegram without copying
Telegram's UI.

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
from PySide6.QtGui import QPainter, QPainterPath, QPen, QPixmap
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
from app.telegram.media_sender import (
    MAX_ALBUM_SIZE,
    Attachment,
    AttachmentCategory,
    MediaSendPlan,
    PlannedMessage,
    build_media_send_plan,
)
from app.telegram.message_options import LinkPreviewOptions, PreviewSize, link_domain
from app.telegram.server_info import LinkPreviewInfo
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


def _cover(pixmap: QPixmap, size: QSize, scale: float) -> QPixmap:
    """`pixmap` scaled to fill `size` (logical px) and centre-cropped, at the
    screen's device pixel ratio."""
    target = size * scale
    scaled = pixmap.scaled(target, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
    x = (scaled.width() - target.width()) // 2
    y = (scaled.height() - target.height()) // 2
    cropped = scaled.copy(x, y, target.width(), target.height())
    cropped.setDevicePixelRatio(scale)
    return cropped


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
        # Kept compact: the preview is about the message, so the album
        # leaves room for the text below it.
        if count % 2 == 1:
            cells.append(QRectF(0, 0, width, width * 0.45))
            y = width * 0.45 + gap
            index = 1
        while index < count:
            cells.append(QRectF(0, y, half, half * 0.62))
            if index + 1 < count:
                cells.append(QRectF(half + gap, y, half, half * 0.62))
            y += half * 0.62 + gap
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
            painter.fillRect(rect, theme.qcolor(tokens.thumbnail_bg))
            if pixmap is not None and not pixmap.isNull():
                painter.drawPixmap(rect.toRect(), _cover(pixmap, rect.size().toSize(), self.devicePixelRatioF()))
            else:
                icon_rect = QRectF(0, 0, ICON_SIZE, ICON_SIZE)
                icon_rect.moveCenter(rect.center())
                icons.themed("image", "text_muted").paint(painter, icon_rect.toRect())
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
        painter.fillPath(path, theme.qcolor(tokens.bubble))
        if not tokens.is_dark:
            painter.setPen(QPen(theme.qcolor(tokens.border), 1))
            painter.drawPath(path)
        painter.end()
        super().paintEvent(event)


class _ImagePlaceholder(QWidget):
    """Where a link preview's large image would be. Nothing is downloaded
    for the preview, so it is a calm block with an image icon."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 - Qt override
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - Qt override
        return int(width * 0.45)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return QSize(PREVIEW_BUBBLE_MAX_WIDTH, self.heightForWidth(PREVIEW_BUBBLE_MAX_WIDTH))

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        tokens = theme.current_tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(rect, RADIUS_SM, RADIUS_SM)
        painter.fillPath(path, theme.qcolor(tokens.thumbnail_bg))
        icon_rect = QRectF(0, 0, ICON_SIZE, ICON_SIZE)
        icon_rect.moveCenter(rect.center())
        icons.themed("image", "text_muted").paint(painter, icon_rect.toRect())
        painter.end()


class _LinkCard(QFrame):
    """A link preview inside the bubble: site, title and description from
    messages.getWebPagePreview when the account could read them, otherwise
    just the domain."""

    def __init__(self, preview: LinkPreviewOptions, info: Optional[LinkPreviewInfo], parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("linkPreviewCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE_SM, SPACE_XS, 0, SPACE_XS)
        layout.setSpacing(SPACE_XS)
        site = QLabel((info.site_name if info and info.site_name else link_domain(preview.url)), self)
        site.setObjectName("linkPreviewSite")
        layout.addWidget(site)
        self.title_label = QLabel(info.title if info else "", self)
        self.title_label.setObjectName("linkPreviewTitle")
        self.title_label.setWordWrap(True)
        self.title_label.setVisible(bool(info and info.title))
        layout.addWidget(self.title_label)
        description = QLabel(info.description if info else tr("message_preview.link_card_unknown"), self)
        description.setObjectName("linkPreviewDescription")
        description.setWordWrap(True)
        layout.addWidget(description)
        large = preview.size == PreviewSize.LARGE or (preview.size == PreviewSize.AUTO and bool(info and info.has_large_media))
        if large:
            layout.addWidget(_ImagePlaceholder(self))


class MessagePreviewWidget(QFrame):
    """One bubble per message that will actually be sent, in the send
    order: it draws app.telegram.media_sender's send plan -- the same plan
    the sender executes -- never its own idea of how text and files go."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("chatPreview")
        self.setMinimumHeight(PREVIEW_MIN_HEIGHT)
        self._text = ""
        self._entities: List[TypeMessageEntity] = []
        self._html = ""
        self._plan: Optional[MediaSendPlan] = None
        self._link_info: Optional[LinkPreviewInfo] = None
        self._bubbles: List[_Bubble] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll)
        # Like a chat: the latest message stays in view, so a long text
        # doesn't hide the photo sent after it.
        scroll.verticalScrollBar().rangeChanged.connect(lambda _low, high: scroll.verticalScrollBar().setValue(high))
        self._scroll = scroll

        self._canvas = QWidget()
        self._canvas_layout = QVBoxLayout(self._canvas)
        self._canvas_layout.setContentsMargins(SPACE_MD, SPACE_MD, SPACE_MD, SPACE_MD)
        self._canvas_layout.setSpacing(SPACE_XS)
        self._canvas_layout.addStretch(1)
        scroll.setWidget(self._canvas)

        # The one text view, moved into whichever bubble carries the text
        # (a caption or a message of its own).
        self._browser = QTextBrowser(self._canvas)
        self._browser.setObjectName("bubbleBrowser")
        self._browser.setReadOnly(True)
        self._browser.setOpenExternalLinks(True)
        self._browser.setFrameShape(QFrame.Shape.NoFrame)
        self._browser.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._browser.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._browser.document().setDocumentMargin(0)
        self._browser.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        # Kept for callers that list attachment names under the preview
        # (e.g. the wizard); the bubbles themselves show them visually.
        self._attachments_label = QLabel(self)
        self._attachments_label.setObjectName("attachmentsPreviewLabel")
        self._attachments_label.setWordWrap(True)
        self._attachments_label.setVisible(False)
        outer.addWidget(self._attachments_label)

        self._rebuild()
        theme.on_theme_changed(self, self._on_theme_changed)

    # ---- public API ------------------------------------------------------------

    def update_preview(
        self,
        text: str,
        entities: List[TypeMessageEntity],
        attachment_names: Sequence[str] = (),
        attachments: Optional[Sequence[Attachment]] = None,
        plan: Optional[MediaSendPlan] = None,
        link_info: Optional[LinkPreviewInfo] = None,
    ) -> None:
        """`plan`: the send plan for this text (with the account's caption
        limit and the message options); without one, the default plan for
        a regular account and no preview."""
        self._text = text
        self._entities = list(entities)
        self._attachments_label.setText(", ".join(attachment_names))
        if plan is None:
            plan = build_media_send_plan(list(attachments or []), text, self._entities, validate=False)
        self._plan = plan
        self._link_info = link_info
        self._rebuild()

    def planned_messages(self) -> List[PlannedMessage]:
        return self._plan.messages() if self._plan is not None else []

    def bubble_count(self) -> int:
        return len(self._bubbles)

    def rendered_html(self) -> str:
        """The HTML of the message text currently shown (as built, before
        QTextDocument normalises it) -- lets callers check its colours."""
        return self._html

    # ---- internals --------------------------------------------------------------

    def _on_theme_changed(self, _name: str) -> None:
        self._rebuild()

    def _rebuild(self) -> None:
        self._browser.setParent(self._canvas)
        self._browser.hide()
        for bubble in self._bubbles:
            bubble.hide()
            bubble.deleteLater()
        self._bubbles = []
        while self._canvas_layout.count() > 1:
            item = self._canvas_layout.takeAt(1)
            if item.layout() is not None:
                item.layout().deleteLater()

        messages = self.planned_messages()
        if not messages:
            # Nothing to send yet: one bubble with the placeholder text.
            messages = [PlannedMessage("text")]
        self._html = ""
        for message in messages:
            bubble = self._make_bubble(message)
            row = QHBoxLayout()
            row.addStretch(1)
            row.addWidget(bubble)
            self._canvas_layout.addLayout(row)
            self._bubbles.append(bubble)
        self._fit_browser()

    def _make_bubble(self, message: PlannedMessage) -> _Bubble:
        bubble = _Bubble(self._canvas)
        layout = QVBoxLayout(bubble)
        pad = PREVIEW_BUBBLE_PADDING
        layout.setContentsMargins(pad, pad, pad + PREVIEW_TAIL, pad - SPACE_XS)
        layout.setSpacing(SPACE_SM)

        if message.kind == "media" and message.group is not None:
            attachments = message.group.attachments
            if attachments[0].category == AttachmentCategory.ALBUM_ELIGIBLE:
                album = _AlbumGrid(bubble)
                album.set_paths([a.path for a in attachments])
                layout.addWidget(album)
            else:
                for attachment in attachments:
                    layout.addWidget(self._file_row(bubble, attachment.file_name))

        preview = message.link_preview if message.kind == "text" else None
        if preview is not None and preview.above_text:
            layout.addWidget(_LinkCard(preview, self._link_info, bubble))
        if message.text or message.kind == "text":
            self._html = entities_to_preview_html(message.text, list(message.entities))
            tokens = theme.current_tokens()
            self._browser.setHtml(f'<div style="color:{tokens.bubble_text};">{self._html}</div>')
            self._browser.setParent(bubble)
            layout.addWidget(self._browser)
            self._browser.show()
        if preview is not None and not preview.above_text:
            layout.addWidget(_LinkCard(preview, self._link_info, bubble))

        meta_row = QHBoxLayout()
        meta_row.addStretch(1)
        time_label = QLabel(datetime.now().strftime("%H:%M"), bubble)
        time_label.setObjectName("bubbleMeta")
        meta_row.addWidget(time_label)
        layout.addLayout(meta_row)
        return bubble

    def _file_row(self, parent: QWidget, name: str) -> QWidget:
        row = QWidget(parent)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_SM)
        icon = QLabel(row)
        icon.setObjectName("fileIcon")
        icon.setPixmap(icons.themed_pixmap("document", "accent", ICON_SIZE, icon.devicePixelRatioF()))
        layout.addWidget(icon)
        label = QLabel(name, row)
        label.setObjectName("bubbleText")
        layout.addWidget(label, 1)
        return row

    def _fit_browser(self) -> None:
        document = self._browser.document()
        width = max(1, self._browser.viewport().width() or (PREVIEW_BUBBLE_MAX_WIDTH - 2 * PREVIEW_BUBBLE_PADDING))
        document.setTextWidth(width)
        self._browser.setFixedHeight(int(document.size().height()) + 2)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._fit_browser()
