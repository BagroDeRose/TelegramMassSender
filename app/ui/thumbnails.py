"""Image thumbnail generation for attachment tiles.

Uses QImageReader.setScaledSize() so the decoder itself produces a small
image (efficient for JPEG's native DCT scaling and for large PNGs alike)
instead of decoding a multi-megapixel photo at full resolution just to
downscale it afterward for a ~90px tile -- important since a campaign's
attachment list can hold several images at once, each getting its own
tile.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImageReader, QPixmap

from app.i18n import tr
from app.telegram.media_sender import THUMBNAILABLE_KINDS, kind_for_path

_UNIT_KEYS = ("thumbnails.unit.bytes", "thumbnails.unit.kilobytes", "thumbnails.unit.megabytes", "thumbnails.unit.gigabytes")


def is_image(path: Path) -> bool:
    """Whether Qt can plausibly decode a visual thumbnail for `path` --
    reads from app.telegram.media_sender's single extension->kind table
    rather than keeping an independent list here, so this and the
    send-side album-eligibility check can never silently drift apart."""
    return kind_for_path(path) in THUMBNAILABLE_KINDS


def make_thumbnail(path: Path, size: int) -> Optional[QPixmap]:
    """Return an aspect-preserved QPixmap no larger than `size`x`size`
    pixels, or None if the file isn't a recognized image or can't be
    decoded (corrupted/unsupported/unreadable) -- callers must fall back
    to the generic document tile in that case, never crash on a bad file."""
    if not is_image(path):
        return None
    try:
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)  # respect EXIF orientation
        original_size = reader.size()
        if original_size.isValid() and original_size.width() > 0 and original_size.height() > 0:
            target = original_size.scaled(QSize(size, size), Qt.AspectRatioMode.KeepAspectRatio)
            reader.setScaledSize(target)
        image = reader.read()
    except Exception:  # noqa: BLE001 - a bad/unreadable file must degrade, not crash the UI
        return None
    if image.isNull():
        return None
    return QPixmap.fromImage(image)


def format_file_size(size_bytes: int) -> str:
    size = float(size_bytes)
    for i, unit_key in enumerate(_UNIT_KEYS):
        unit = tr(unit_key)
        if size < 1024 or i == len(_UNIT_KEYS) - 1:
            return f"{size:.0f} {unit}" if i == 0 else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} {tr(_UNIT_KEYS[-1])}"
