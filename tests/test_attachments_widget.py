"""Tests for the redesigned tile/grid-based AttachmentsWidget. Public API
(get_attachments/is_empty/missing_files/add_file/attachments_changed) is
what app.ui.main_window and the send flow depend on.
"""
from __future__ import annotations

from app.ui.attachments_widget import AttachmentsWidget


def _write_minimal_png(path):
    from PySide6.QtGui import QColor, QImage

    image = QImage(8, 8, QImage.Format.Format_RGB32)
    image.fill(QColor("#4488ff"))
    assert image.save(str(path), "PNG")


def test_starts_empty(qapp):
    widget = AttachmentsWidget()
    assert widget.is_empty() is True
    assert widget.get_attachments() == []
    # isHidden() reflects the widget's own setVisible() call regardless of
    # whether the (never-.show()'d) top-level window is actually on
    # screen -- isVisible() would be False for both regardless of state.
    assert widget._empty_label.isHidden() is False
    assert widget._list.isHidden() is True


def test_add_file_makes_it_available_and_visible(qapp, tmp_path):
    widget = AttachmentsWidget()
    path = tmp_path / "doc.pdf"
    path.write_bytes(b"x")

    changed = []
    widget.attachments_changed.connect(lambda: changed.append(True))
    widget.add_file(path)

    assert widget.is_empty() is False
    assert [a.path for a in widget.get_attachments()] == [path]
    assert widget._empty_label.isHidden() is True
    assert widget._list.isHidden() is False
    assert changed == [True]


def test_add_duplicate_path_is_ignored(qapp, tmp_path):
    widget = AttachmentsWidget()
    path = tmp_path / "doc.pdf"
    path.write_bytes(b"x")
    widget.add_file(path)
    widget.add_file(path)
    assert len(widget.get_attachments()) == 1


def test_tile_remove_button_removes_only_that_attachment(qapp, tmp_path):
    widget = AttachmentsWidget()
    path_a = tmp_path / "a.pdf"
    path_a.write_bytes(b"x")
    path_b = tmp_path / "b.pdf"
    path_b.write_bytes(b"x")
    widget.add_file(path_a)
    widget.add_file(path_b)

    item_a = widget._list.item(0)
    tile_a = widget._tiles[id(item_a)]
    tile_a.remove_button.click()

    remaining = [a.path for a in widget.get_attachments()]
    assert remaining == [path_b]
    assert widget._list.count() == 1


def test_clear_removes_everything_and_restores_empty_state(qapp, tmp_path):
    widget = AttachmentsWidget()
    path = tmp_path / "doc.pdf"
    path.write_bytes(b"x")
    widget.add_file(path)

    widget._on_clear_clicked()

    assert widget.is_empty() is True
    assert widget._empty_label.isHidden() is False
    assert widget._tiles == {}


def test_missing_files_detects_deleted_path(qapp, tmp_path):
    widget = AttachmentsWidget()
    path = tmp_path / "gone.pdf"
    path.write_bytes(b"x")
    widget.add_file(path)
    path.unlink()

    assert widget.missing_files() == [path]


def test_apply_theme_does_not_raise_with_or_without_tiles(qapp, tmp_path):
    widget = AttachmentsWidget()
    widget.apply_theme()
    path = tmp_path / "doc.pdf"
    path.write_bytes(b"x")
    widget.add_file(path)
    widget.apply_theme()  # must re-tint the now-existing tile without raising


def test_ordering_preserved_across_adds(qapp, tmp_path):
    widget = AttachmentsWidget()
    paths = [tmp_path / f"{i}.pdf" for i in range(5)]
    for p in paths:
        p.write_bytes(b"x")
        widget.add_file(p)

    assert [a.path for a in widget.get_attachments()] == paths


# ---- thumbnails ------------------------------------------------------------


def test_image_attachment_gets_a_real_thumbnail(qapp, tmp_path):
    widget = AttachmentsWidget()
    path = tmp_path / "photo.png"
    _write_minimal_png(path)

    widget.add_file(path)

    item = widget._list.item(0)
    tile = widget._tiles[id(item)]
    assert tile.is_image is True
    assert not tile.image_label.pixmap().isNull()


def test_multiple_image_attachments_each_get_their_own_thumbnail(qapp, tmp_path):
    widget = AttachmentsWidget()
    paths = [tmp_path / f"photo{i}.png" for i in range(3)]
    for p in paths:
        _write_minimal_png(p)
        widget.add_file(p)

    for i in range(3):
        item = widget._list.item(i)
        tile = widget._tiles[id(item)]
        assert tile.is_image is True
        assert not tile.image_label.pixmap().isNull()


def test_non_image_attachment_falls_back_to_document_tile(qapp, tmp_path):
    widget = AttachmentsWidget()
    path = tmp_path / "report.docx"
    path.write_bytes(b"not actually a real docx, just bytes")

    widget.add_file(path)

    item = widget._list.item(0)
    tile = widget._tiles[id(item)]
    assert tile.is_image is False
    # A generic file icon is still shown (not a blank tile).
    assert not tile.image_label.pixmap().isNull()


def test_corrupted_image_extension_falls_back_to_document_tile(qapp, tmp_path):
    # A .jpg that isn't actually a valid image must degrade gracefully to
    # the document tile rather than crashing thumbnail generation.
    widget = AttachmentsWidget()
    path = tmp_path / "fake.jpg"
    path.write_bytes(b"this is not a real jpeg")

    widget.add_file(path)

    item = widget._list.item(0)
    tile = widget._tiles[id(item)]
    assert tile.is_image is False
