"""Icon provider: Lucide line icons (ISC licence, assets/icons/lucide/),
tinted to the active theme's tokens.

Two kinds of icon come out of here:

* icon(name, color, size)  -- a fixed colour, for the rare caller that
  really wants one exact colour.
* themed(name, role, ...)  -- the normal case. The colour is a *token
  name* resolved at paint time, with separate roles for the checked (On)
  state, hover (Active mode) and Disabled mode. Because it's resolved when
  Qt paints, a theme switch recolours every themed icon on the next repaint
  (which the global stylesheet swap triggers anyway) -- no widget needs to
  re-set its icons by hand.

SVGs are rendered by QSvgRenderer at the exact device size Qt asks for
(including the screen's scale factor, so 125 % / 150 % stay crisp) and
cached per (name, colour, size).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional, Tuple

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QIconEngine, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from app.config.paths import get_resource_path

DEFAULT_STROKE = 1.75

# Names used across the app -> Lucide file names. The left column also
# keeps every name the old hand-drawn QPainter set exposed.
_ALIASES: Dict[str, str] = {
    "campaign": "send",
    "accounts": "users",
    "results": "chart-column",
    "settings": "settings",
    "attachment": "paperclip",
    "document": "file-text",
    "close": "x",
    "edit": "pencil",
    "check_circle": "circle-check",
    "error_circle": "circle-x",
    "clock": "clock",
    "plus": "plus",
    "video": "file-video",
    "audio": "music",
    "archive": "file-archive",
    "image": "image",
    "start": "play",
    "pause": "pause",
    "resume": "play",
    "stop": "square",
    "retry": "rotate-ccw",
    "more": "ellipsis",
    "favorite": "star",
    "spoiler": "eye-off",
    "link": "link",
    "emoji": "smile",
    "code": "code",
    "code_block": "square-code",
    "bold": "bold",
    "italic": "italic",
    "underline": "underline",
    "strikethrough": "strikethrough",
    "import": "file-up",
    "chats": "messages-square",
    "channel": "megaphone",
    "group": "users-round",
    "supergroup": "users-round",
    "forum": "messages-square",
    "user": "user",
    "export": "download",
    "save": "save",
    "copy": "copy",
    "refresh": "refresh-cw",
    "folder": "folder-open",
    "delete": "trash-2",
    "warning": "triangle-alert",
    "info": "info",
    "logout": "log-out",
    "journal": "scroll-text",
    "search": "search",
    "chevron_left": "chevron-left",
    "chevron_right": "chevron-right",
    "chevron_down": "chevron-down",
    "chevron_up": "chevron-up",
    "collapse": "panel-left-close",
    "expand": "panel-left-open",
    "hourglass": "hourglass",
    "wizard": "list-checks",
    "add_account": "user-plus",
    "check": "check",
    "skipped": "circle-dot",
    "back": "arrow-left",
    "next": "arrow-right",
    "open": "external-link",
    "offline": "wifi-off",
    "editor": "square-pen",
}


def _svg_dir() -> Path:
    return get_resource_path("assets", "icons", "lucide")


@lru_cache(maxsize=None)
def _svg_source(name: str) -> Optional[str]:
    file_name = _ALIASES.get(name, name)
    path = _svg_dir() / f"{file_name}.svg"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def has_icon(name: str) -> bool:
    return _svg_source(name) is not None


_pixmap_cache: Dict[Tuple[str, str, int, int, float, float], QPixmap] = {}


def render_pixmap(name: str, color: str, size: QSize, scale: float = 1.0, stroke: float = DEFAULT_STROKE) -> QPixmap:
    """Render one icon at `size` logical pixels for a `scale` device pixel
    ratio. Unknown names give a transparent pixmap of the right size."""
    width = max(1, round(size.width() * scale))
    height = max(1, round(size.height() * scale))
    key = (name, color, width, height, scale, stroke)
    cached = _pixmap_cache.get(key)
    if cached is not None:
        return cached
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    source = _svg_source(name)
    if source is not None:
        svg = source.replace("currentColor", color).replace('stroke-width="2"', f'stroke-width="{stroke}"')
        renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        renderer.render(painter, QRectF(0, 0, width, height))
        painter.end()
    pixmap = QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(scale)
    _pixmap_cache[key] = pixmap
    return pixmap


class _TintedSvgEngine(QIconEngine):
    """Renders one SVG; the colour is either fixed or a token role looked
    up at paint time (so it follows the active theme)."""

    def __init__(
        self,
        name: str,
        color: Optional[str] = None,
        role: str = "text_secondary",
        checked_role: Optional[str] = None,
        active_role: Optional[str] = None,
        stroke: float = DEFAULT_STROKE,
    ) -> None:
        super().__init__()
        self._name = name
        self._color = color
        self._role = role
        self._checked_role = checked_role
        self._active_role = active_role
        self._stroke = stroke

    def _color_for(self, mode: QIcon.Mode, state: QIcon.State) -> str:
        if self._color is not None:
            return self._color
        from app.ui import theme  # local: theme imports this module

        tokens = theme.current_tokens()
        if mode == QIcon.Mode.Disabled:
            return tokens.disabled_text
        if state == QIcon.State.On and self._checked_role:
            return getattr(tokens, self._checked_role)
        if mode in (QIcon.Mode.Active, QIcon.Mode.Selected) and self._active_role:
            return getattr(tokens, self._active_role)
        return getattr(tokens, self._role)

    def paint(self, painter: QPainter, rect, mode, state) -> None:  # noqa: D401 - Qt override
        scale = painter.device().devicePixelRatioF() if painter.device() is not None else 1.0
        pixmap = render_pixmap(self._name, self._color_for(mode, state), rect.size(), scale, self._stroke)
        painter.drawPixmap(rect, pixmap)

    def pixmap(self, size: QSize, mode, state) -> QPixmap:
        return self.scaledPixmap(size, mode, state, 1.0)

    def scaledPixmap(self, size: QSize, mode, state, scale: float) -> QPixmap:  # noqa: N802 - Qt override
        return QPixmap(render_pixmap(self._name, self._color_for(mode, state), size, scale or 1.0, self._stroke))

    def actualSize(self, size: QSize, mode, state) -> QSize:  # noqa: N802 - Qt override
        return size

    def isNull(self) -> bool:  # noqa: N802 - Qt override
        return _svg_source(self._name) is None

    def clone(self) -> "_TintedSvgEngine":
        return _TintedSvgEngine(
            self._name, self._color, self._role, self._checked_role, self._active_role, self._stroke
        )


def icon(name: str, color: str, size: int = 18, stroke_width: float = DEFAULT_STROKE) -> QIcon:
    """A fixed-colour icon. Unknown names give a null icon rather than
    raising, so a typo degrades to "no icon" instead of a crash. `size` is
    kept for API compatibility: the engine renders at whatever size Qt
    asks for."""
    del size
    return QIcon(_TintedSvgEngine(name, color=color, stroke=stroke_width))


def themed(
    name: str,
    role: str = "text_secondary",
    checked_role: Optional[str] = None,
    active_role: Optional[str] = "text_primary",
    stroke_width: float = DEFAULT_STROKE,
) -> QIcon:
    """The normal way to get an icon: coloured by token roles of the
    active theme, recoloured automatically after a theme switch."""
    return QIcon(_TintedSvgEngine(name, None, role, checked_role, active_role, stroke_width))


def themed_pixmap(name: str, role: str, size: int, scale: float = 1.0) -> QPixmap:
    """A pixmap for a QLabel (labels can't hold a QIcon). Callers that keep
    one must re-request it after a theme switch (see theme.notifier)."""
    from app.ui import theme

    return render_pixmap(name, getattr(theme.current_tokens(), role), QSize(size, size), scale)


def save_tinted_png(name: str, color: str, path: Path, size: int, stroke_width: float = 2.25) -> None:
    """Write a tinted icon as a 1x PNG plus an @2x variant next to it. QSS
    sub-controls (check marks, combo/spin arrows) can only take an
    `image: url(...)`, and Qt picks the @2x file on high-DPI screens."""
    render_pixmap(name, color, QSize(size, size), 1.0, stroke_width).save(str(path))
    double = path.with_name(f"{path.stem}@2x{path.suffix}")
    image = render_pixmap(name, color, QSize(size, size), 2.0, stroke_width).toImage()
    image.save(str(double))
