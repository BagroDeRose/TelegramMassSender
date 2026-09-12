"""Tests for app.ui.thumbnails: scaled-decode image thumbnails and the
file-size formatter used on document tiles.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.ui.thumbnails import format_file_size, is_image, make_thumbnail


def _write_minimal_png(path):
    from PySide6.QtGui import QColor, QImage

    image = QImage(8, 8, QImage.Format.Format_RGB32)
    image.fill(QColor("#4488ff"))
    assert image.save(str(path), "PNG")


def test_is_image_recognizes_common_extensions(tmp_path):
    assert is_image(tmp_path / "a.jpg") is True
    assert is_image(tmp_path / "a.PNG") is True
    assert is_image(tmp_path / "a.webp") is True
    assert is_image(tmp_path / "a.pdf") is False
    assert is_image(tmp_path / "a.docx") is False


def test_make_thumbnail_decodes_valid_image(qapp, tmp_path):
    path = tmp_path / "photo.png"
    _write_minimal_png(path)
    pixmap = make_thumbnail(path, 64)
    assert pixmap is not None
    assert not pixmap.isNull()
    assert pixmap.width() <= 64
    assert pixmap.height() <= 64


def test_make_thumbnail_returns_none_for_non_image(qapp, tmp_path):
    path = tmp_path / "doc.pdf"
    path.write_bytes(b"not an image")
    assert make_thumbnail(path, 64) is None


def test_make_thumbnail_returns_none_for_corrupted_image(qapp, tmp_path):
    path = tmp_path / "broken.png"
    path.write_bytes(b"this is not a valid png")
    assert make_thumbnail(path, 64) is None


def test_make_thumbnail_returns_none_for_missing_file(qapp, tmp_path):
    assert make_thumbnail(tmp_path / "does_not_exist.png", 64) is None


def test_format_file_size_bytes():
    assert format_file_size(500) == "500 Б"


def test_format_file_size_kilobytes():
    assert format_file_size(2048) == "2.0 КБ"


def test_format_file_size_megabytes():
    assert format_file_size(5 * 1024 * 1024) == "5.0 МБ"


def test_format_file_size_gigabytes():
    # Reliability Tests: "Very large file" -- the size formatter itself
    # must scale cleanly up to GB, not just the KB/MB cases above.
    assert format_file_size(3 * 1024 * 1024 * 1024) == "3.0 ГБ"


def test_make_thumbnail_uses_scaled_decode_for_a_very_large_source_image(qapp, tmp_path):
    # Reliability Tests: "Very large file" -- make_thumbnail must never
    # decode a huge source image at full resolution just to shrink it
    # afterward (see the module docstring); this proves setScaledSize()
    # is actually given a small target regardless of how large the
    # reported source image is, without needing a real multi-hundred-MB
    # test fixture on disk.
    from PySide6.QtCore import QSize

    path = tmp_path / "huge.jpg"
    path.write_bytes(b"x")  # content is irrelevant -- QImageReader itself is mocked

    fake_reader = MagicMock()
    fake_reader.size.return_value = QSize(20000, 16000)  # an implausibly large photo
    # isNull() True short-circuits make_thumbnail before QPixmap.fromImage,
    # which is fine here -- this test only cares that a small scaled
    # target was actually requested from the reader, not what a mocked
    # (non-real) QImage would ultimately convert to.
    fake_image = MagicMock()
    fake_image.isNull.return_value = True
    fake_reader.read.return_value = fake_image

    with patch("app.ui.thumbnails.QImageReader", return_value=fake_reader):
        make_thumbnail(path, 64)

    fake_reader.setScaledSize.assert_called_once()
    target = fake_reader.setScaledSize.call_args[0][0]
    assert target.width() <= 64
    assert target.height() <= 64
