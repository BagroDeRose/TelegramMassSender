"""A small, consistent icon set drawn with QPainter -- no icon-font/SVG
dependency, nothing to bundle for PyInstaller, and every icon shares the
same stroke weight and viewBox so the sidebar/nav/status marks read as one
system instead of mixed emoji styles.

Icons are rendered on demand (cheap: a handful of primitives on a small
pixmap) and tinted to whatever color the caller passes, so the same glyph
works in both themes and in a hover/active/muted state without needing
separate asset files per variant.
"""
from __future__ import annotations

import math
from typing import Callable, Dict

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

_VIEWBOX = 24.0


def _pen(color: str, width: float = 1.8) -> QPen:
    pen = QPen(QColor(color))
    pen.setWidthF(width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _draw_campaign(p: QPainter) -> None:
    # Paper plane: a simple send/campaign glyph.
    path = QPainterPath()
    path.moveTo(3, 12.5)
    path.lineTo(20.5, 3.5)
    path.lineTo(14.5, 20.5)
    path.lineTo(11, 13)
    path.lineTo(3, 12.5)
    path.closeSubpath()
    p.drawPath(path)
    p.drawLine(QPointF(11, 13), QPointF(20.5, 3.5))


def _draw_accounts(p: QPainter) -> None:
    p.drawEllipse(QRectF(8, 3.5, 8, 8))
    path = QPainterPath()
    path.moveTo(4, 21)
    path.cubicTo(4, 15.5, 8.5, 14.5, 12, 14.5)
    path.cubicTo(15.5, 14.5, 20, 15.5, 20, 21)
    p.drawPath(path)


def _draw_results(p: QPainter) -> None:
    p.drawLine(QPointF(4, 21), QPointF(21, 21))
    p.drawRect(QRectF(6.5, 13, 3.5, 8))
    p.drawRect(QRectF(12, 8.5, 3.5, 12.5))
    p.drawRect(QRectF(17.5, 4.5, 3.5, 16.5))


def _draw_settings(p: QPainter) -> None:
    p.drawEllipse(QRectF(8.5, 8.5, 7, 7))
    center = QPointF(12, 12)
    for i in range(8):
        angle = math.pi / 4 * i
        inner = QPointF(center.x() + 8.4 * math.cos(angle), center.y() + 8.4 * math.sin(angle))
        outer = QPointF(center.x() + 10.6 * math.cos(angle), center.y() + 10.6 * math.sin(angle))
        p.drawLine(inner, outer)


def _draw_attachment(p: QPainter) -> None:
    path = QPainterPath()
    path.moveTo(16.5, 6.5)
    path.lineTo(9, 14)
    path.cubicTo(7.5, 15.5, 7.5, 17.5, 9, 19)
    path.cubicTo(10.5, 20.5, 12.5, 20.5, 14, 19)
    path.lineTo(20, 13)
    path.cubicTo(21.8, 11.2, 21.8, 8.4, 20, 6.6)
    path.cubicTo(18.2, 4.8, 15.4, 4.8, 13.6, 6.6)
    path.lineTo(7, 13.2)
    p.drawPath(path)


def _draw_close(p: QPainter) -> None:
    p.drawLine(QPointF(6, 6), QPointF(18, 18))
    p.drawLine(QPointF(18, 6), QPointF(6, 18))


def _draw_check_circle(p: QPainter) -> None:
    p.drawEllipse(QRectF(3, 3, 18, 18))
    path = QPainterPath()
    path.moveTo(7.5, 12.5)
    path.lineTo(10.5, 15.5)
    path.lineTo(16.5, 8.5)
    p.drawPath(path)


def _draw_error_circle(p: QPainter) -> None:
    p.drawEllipse(QRectF(3, 3, 18, 18))
    p.drawLine(QPointF(9, 9), QPointF(15, 15))
    p.drawLine(QPointF(15, 9), QPointF(9, 15))


def _draw_clock(p: QPainter) -> None:
    p.drawEllipse(QRectF(3, 3, 18, 18))
    p.drawLine(QPointF(12, 12), QPointF(12, 7))
    p.drawLine(QPointF(12, 12), QPointF(16, 14.5))


def _draw_document(p: QPainter) -> None:
    path = QPainterPath()
    path.moveTo(6, 3)
    path.lineTo(14.5, 3)
    path.lineTo(19, 7.5)
    path.lineTo(19, 21)
    path.lineTo(6, 21)
    path.closeSubpath()
    p.drawPath(path)
    corner = QPainterPath()
    corner.moveTo(14.5, 3)
    corner.lineTo(14.5, 7.5)
    corner.lineTo(19, 7.5)
    p.drawPath(corner)
    p.drawLine(QPointF(9, 12), QPointF(16, 12))
    p.drawLine(QPointF(9, 16), QPointF(16, 16))


def _draw_plus(p: QPainter) -> None:
    p.drawLine(QPointF(12, 5), QPointF(12, 19))
    p.drawLine(QPointF(5, 12), QPointF(19, 12))


def _draw_video(p: QPainter) -> None:
    # Rounded frame + play triangle -- attachment tile glyph for video
    # files (app.telegram.media_sender.AttachmentKind.VIDEO), which never
    # get a decoded thumbnail in this app.
    p.drawRoundedRect(QRectF(3.5, 5, 17, 14), 2.5, 2.5)
    path = QPainterPath()
    path.moveTo(10, 9)
    path.lineTo(16, 12)
    path.lineTo(10, 15)
    path.closeSubpath()
    p.drawPath(path)


def _draw_audio(p: QPainter) -> None:
    # Outline eighth-note -- attachment tile glyph for common audio files
    # (AttachmentKind.AUDIO). Purely a local UI cue: audio is still sent as
    # a plain document, same as before this kind existed.
    p.drawEllipse(QRectF(5.5, 15, 5.5, 4.5))
    p.drawLine(QPointF(10.8, 17.2), QPointF(10.8, 4.5))
    flag = QPainterPath()
    flag.moveTo(10.8, 4.5)
    flag.cubicTo(15, 4.5, 15.5, 8, 12.5, 9.5)
    p.drawPath(flag)


def _draw_archive(p: QPainter) -> None:
    # Same page silhouette as _draw_document (folded-corner page) so it
    # reads as "a file" at a glance, with a zipper down the middle instead
    # of text lines -- attachment tile glyph for .zip archives
    # (AttachmentKind.ARCHIVE).
    path = QPainterPath()
    path.moveTo(6, 3)
    path.lineTo(14.5, 3)
    path.lineTo(19, 7.5)
    path.lineTo(19, 21)
    path.lineTo(6, 21)
    path.closeSubpath()
    p.drawPath(path)
    corner = QPainterPath()
    corner.moveTo(14.5, 3)
    corner.lineTo(14.5, 7.5)
    corner.lineTo(19, 7.5)
    p.drawPath(corner)
    p.drawLine(QPointF(12.5, 8.5), QPointF(12.5, 21))
    for y in (10, 12.5, 15, 17.5):
        p.drawLine(QPointF(11.3, y), QPointF(13.7, y))


_DRAWERS: Dict[str, Callable[[QPainter], None]] = {
    "campaign": _draw_campaign,
    "accounts": _draw_accounts,
    "results": _draw_results,
    "settings": _draw_settings,
    "attachment": _draw_attachment,
    "document": _draw_document,
    "close": _draw_close,
    "check_circle": _draw_check_circle,
    "error_circle": _draw_error_circle,
    "clock": _draw_clock,
    "plus": _draw_plus,
    "video": _draw_video,
    "audio": _draw_audio,
    "archive": _draw_archive,
}


def icon(name: str, color: str, size: int = 18, stroke_width: float = 1.8) -> QIcon:
    """Render a named glyph tinted `color` at `size` px, returned as a QIcon.
    Unknown names return an empty icon rather than raising, so a typo in a
    call site degrades to "no icon" instead of crashing the UI."""
    drawer = _DRAWERS.get(name)
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    if drawer is None:
        return QIcon(pixmap)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(_pen(color, stroke_width))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    scale = size / _VIEWBOX
    painter.scale(scale, scale)
    drawer(painter)
    painter.end()
    return QIcon(pixmap)


def avatar_pixmap(initial: str, bg_color: str, text_color: str, size: int = 40) -> QPixmap:
    """A filled circle with a single bold initial letter -- the account
    card's avatar (app.ui.account_widget). Deliberately one consistent
    color pair for every account rather than per-account hues, to stay
    restrained rather than turning the Accounts page into a rainbow."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(bg_color))
    painter.drawEllipse(0, 0, size, size)

    font = painter.font()
    font.setPixelSize(max(10, int(size * 0.42)))
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor(text_color))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, (initial or "?")[:1].upper())
    painter.end()
    return pixmap


def save_spinbox_arrow(direction: str, color: str, path) -> None:
    """Draw a small filled up/down triangle and write it as a PNG at
    `path` -- QSpinBox's ::up-arrow/::down-arrow sub-controls only accept
    an `image: url(...)` in QSS (no way to paint a themed triangle from
    CSS colors alone), and once ::up-button/::down-button gets *any* QSS
    styling, Qt stops drawing its native arrow glyph there entirely --
    confirmed empirically, not just in theory, before writing this fix --
    leaving the buttons blank unless an explicit image is supplied. This
    is that image, generated fresh (not shipped as a static asset) so it
    always matches the active theme's color exactly."""
    size = 8
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    if direction == "up":
        points = [QPointF(1, 6), QPointF(7, 6), QPointF(4, 1.5)]
    else:
        points = [QPointF(1, 2), QPointF(7, 2), QPointF(4, 6.5)]
    painter.drawPolygon(QPolygonF(points))
    painter.end()
    pixmap.save(str(path))
