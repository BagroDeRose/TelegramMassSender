"""Tests for the redesigned tile/grid-based AttachmentsWidget. Public API
(get_attachments/is_empty/missing_files/add_file/attachments_changed) is
what app.ui.main_window and the send flow depend on.
"""
from __future__ import annotations

import pytest

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
    assert tile.icon_name == "document"


# ---- per-type attachment icons (stage 2) ------------------------------------


@pytest.mark.parametrize(
    "filename,expected_icon_name",
    [
        ("clip.mp4", "video"),
        ("song.mp3", "audio"),
        ("bundle.zip", "archive"),
        ("report.pdf", "document"),
        ("notes.txt", "document"),
        ("weird.xyz123", "document"),  # unknown extension -> generic document, not rejected
    ],
)
def test_tile_picks_icon_matching_attachment_kind(qapp, tmp_path, filename, expected_icon_name):
    widget = AttachmentsWidget()
    path = tmp_path / filename
    path.write_bytes(b"x")

    widget.add_file(path)

    item = widget._list.item(0)
    tile = widget._tiles[id(item)]
    assert tile.is_image is False
    assert tile.icon_name == expected_icon_name


def test_theme_switch_preserves_each_tiles_own_icon_not_just_document(qapp, tmp_path):
    # Regression guard: apply_theme() re-tints every non-image tile by
    # re-rendering icons.icon(tile.icon_name, ...) -- before this stage it
    # hardcoded "document", which would have silently collapsed a video/
    # audio/archive tile back to the generic document glyph on every theme
    # switch.
    widget = AttachmentsWidget()
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"x")
    audio_path = tmp_path / "song.mp3"
    audio_path.write_bytes(b"x")
    widget.add_file(video_path)
    widget.add_file(audio_path)

    widget.apply_theme()

    video_tile = widget._tiles[id(widget._list.item(0))]
    audio_tile = widget._tiles[id(widget._list.item(1))]
    assert video_tile.icon_name == "video"
    assert audio_tile.icon_name == "audio"
    assert not video_tile.image_label.pixmap().isNull()
    assert not audio_tile.image_label.pixmap().isNull()


def test_image_attachment_icon_name_stays_default_even_though_unused(qapp, tmp_path):
    # An attachment that gets a real thumbnail never reads icon_name (see
    # _build_tile), but the field should still hold a sane, harmless value
    # rather than something stale or type-inconsistent.
    widget = AttachmentsWidget()
    path = tmp_path / "photo.png"
    _write_minimal_png(path)

    widget.add_file(path)

    tile = widget._tiles[id(widget._list.item(0))]
    assert tile.is_image is True
    assert tile.icon_name == "document"


# ---- drag-to-reorder (stage 3) -----------------------------------------------
#
# A real mouse-driven QDrag gesture (_ReorderableListWidget.mousePressEvent /
# mouseMoveEvent / QDrag.exec()) does not simulate reliably under pytest --
# there is no real OS input queue and QDrag.exec() runs its own native nested
# event loop. Per the task's own guidance, these tests instead drive the
# underlying reorder operation directly -- _on_tile_reorder_requested is
# exactly what _ReorderableListWidget's dropEvent calls once a real drag
# completes, so this exercises the actual state-synchronization logic, not a
# reimplementation of it. One test below also emits the Qt signal itself
# (rather than calling the handler method) to prove the signal-to-handler
# wiring is actually connected, not just that the handler works in isolation.
# The real mouse-driven gesture is verified separately, visually, against the
# running app (see the stage 3 commit/report) -- not part of the automated
# suite.


def _make_widget_with_files(tmp_path, names):
    widget = AttachmentsWidget()
    paths = []
    for name in names:
        path = tmp_path / name
        path.write_bytes(b"x")
        paths.append(path)
        widget.add_file(path)
    return widget, paths


def test_initial_order_matches_add_order_before_any_reorder(qapp, tmp_path):
    widget, paths = _make_widget_with_files(tmp_path, ["a.pdf", "b.pdf", "c.pdf"])
    assert [a.path for a in widget.get_attachments()] == paths


def test_moving_first_item_to_end(qapp, tmp_path):
    widget, paths = _make_widget_with_files(tmp_path, ["a.pdf", "b.pdf", "c.pdf"])
    widget._on_tile_reorder_requested(0, 2)
    assert [a.path for a in widget.get_attachments()] == [paths[1], paths[2], paths[0]]


def test_moving_last_item_to_beginning(qapp, tmp_path):
    widget, paths = _make_widget_with_files(tmp_path, ["a.pdf", "b.pdf", "c.pdf"])
    widget._on_tile_reorder_requested(2, 0)
    assert [a.path for a in widget.get_attachments()] == [paths[2], paths[0], paths[1]]


def test_moving_item_to_the_middle(qapp, tmp_path):
    widget, paths = _make_widget_with_files(tmp_path, ["a.pdf", "b.pdf", "c.pdf", "d.pdf"])
    widget._on_tile_reorder_requested(0, 2)
    assert [a.path for a in widget.get_attachments()] == [paths[1], paths[2], paths[0], paths[3]]


def test_multiple_reorders_compose_to_the_correct_final_order(qapp, tmp_path):
    widget, paths = _make_widget_with_files(tmp_path, ["a.pdf", "b.pdf", "c.pdf", "d.pdf"])
    # a b c d
    widget._on_tile_reorder_requested(0, 3)  # -> b c d a
    widget._on_tile_reorder_requested(1, 0)  # -> c b d a
    widget._on_tile_reorder_requested(3, 1)  # -> c a b d
    expected = [paths[2], paths[0], paths[1], paths[3]]
    assert [a.path for a in widget.get_attachments()] == expected


def test_reorder_via_actual_qt_signal_not_just_direct_handler_call(qapp, tmp_path):
    # Proves the wiring itself (connect() in __init__), not just that the
    # handler function works when called directly.
    widget, paths = _make_widget_with_files(tmp_path, ["a.pdf", "b.pdf", "c.pdf"])
    widget._list.tile_reorder_requested.emit(0, 2)
    assert [a.path for a in widget.get_attachments()] == [paths[1], paths[2], paths[0]]


def test_reorder_rebuilds_tiles_dict_with_no_stale_entries(qapp, tmp_path):
    widget, paths = _make_widget_with_files(tmp_path, ["a.pdf", "b.pdf", "c.pdf"])
    old_tile_ids = set(widget._tiles.keys())

    widget._on_tile_reorder_requested(0, 2)

    assert widget._list.count() == 3
    assert len(widget._tiles) == 3
    new_tile_ids = set(widget._tiles.keys())
    # _rebuild_tiles clears and recreates every QListWidgetItem, so the old
    # id(item) keys must not linger -- a stale entry here would mean a
    # memory leak / dangling reference, not just a display glitch.
    assert old_tile_ids.isdisjoint(new_tile_ids)
    for item_id, tile in widget._tiles.items():
        assert not tile.image_label.pixmap().isNull()


def test_reorder_with_out_of_range_rows_is_ignored_not_corrupting_order(qapp, tmp_path):
    widget, paths = _make_widget_with_files(tmp_path, ["a.pdf", "b.pdf"])
    widget._on_tile_reorder_requested(0, 5)  # target well past the end
    widget._on_tile_reorder_requested(-1, 1)  # negative source
    assert [a.path for a in widget.get_attachments()] == paths


def test_remove_after_reorder_removes_the_correct_file(qapp, tmp_path):
    widget, paths = _make_widget_with_files(tmp_path, ["a.pdf", "b.pdf", "c.pdf"])
    widget._on_tile_reorder_requested(0, 2)  # -> b c a
    # Displayed order is now [b, c, a]; removing row 1 must remove c.
    item = widget._list.item(1)
    widget._remove_item(item)
    assert [a.path for a in widget.get_attachments()] == [paths[1], paths[0]]


def test_add_after_reorder_appends_without_corrupting_existing_order(qapp, tmp_path):
    widget, paths = _make_widget_with_files(tmp_path, ["a.pdf", "b.pdf", "c.pdf"])
    widget._on_tile_reorder_requested(0, 2)  # -> b c a
    new_path = tmp_path / "d.pdf"
    new_path.write_bytes(b"x")
    widget.add_file(new_path)
    assert [a.path for a in widget.get_attachments()] == [paths[1], paths[2], paths[0], new_path]


def test_clear_after_reorder_leaves_widget_empty(qapp, tmp_path):
    widget, paths = _make_widget_with_files(tmp_path, ["a.pdf", "b.pdf", "c.pdf"])
    widget._on_tile_reorder_requested(0, 2)

    widget._on_clear_clicked()

    assert widget.is_empty() is True
    assert widget.get_attachments() == []
    assert widget._tiles == {}
    assert widget._list.count() == 0


def test_missing_file_validation_after_reorder_reports_correct_paths(qapp, tmp_path):
    widget, paths = _make_widget_with_files(tmp_path, ["a.pdf", "b.pdf", "c.pdf"])
    widget._on_tile_reorder_requested(0, 2)  # -> b c a
    paths[0].unlink()  # "a.pdf" -- now at the end of the displayed order

    assert widget.missing_files() == [paths[0]]


def test_theme_apply_after_reorder_does_not_raise_and_keeps_correct_icons(qapp, tmp_path):
    widget, paths = _make_widget_with_files(tmp_path, ["clip.mp4", "song.mp3", "c.pdf"])
    widget._on_tile_reorder_requested(0, 2)  # -> song.mp3, c.pdf, clip.mp4

    widget.apply_theme()  # must not raise, and must re-tint the rebuilt tiles

    icon_names = [widget._tiles[id(widget._list.item(i))].icon_name for i in range(3)]
    assert icon_names == ["audio", "document", "video"]


def test_send_plan_consumes_attachments_in_the_reordered_display_order(qapp, tmp_path):
    # End-to-end proof that the visual order becomes the actual send order,
    # through the real production functions (not a reimplementation of
    # album-grouping logic in this test). Before the reorder the order is
    # [a.jpg, b.pdf, c.jpg] -- the two photos are NOT adjacent (b.pdf sits
    # between them), so they would NOT be album-grouped. The reorder below
    # moves a.jpg to the end, making the order [b.pdf, c.jpg, a.jpg] --
    # now c.jpg and a.jpg ARE adjacent, so build_send_groups (unchanged,
    # unmodified production code) correctly groups them into one album.
    # This is deliberately a case where reordering changes grouping, not
    # just delivery sequence -- proving grouping follows the NEW order.
    from app.telegram.media_sender import build_media_send_plan

    widget, paths = _make_widget_with_files(tmp_path, ["a.jpg", "b.pdf", "c.jpg"])
    widget._on_tile_reorder_requested(0, 2)  # -> b.pdf, c.jpg, a.jpg

    plan = build_media_send_plan(widget.get_attachments(), "caption", [])

    sent_paths = [a.path for group in plan.groups for a in group.attachments]
    assert sent_paths == [paths[1], paths[2], paths[0]]
    assert len(plan.groups) == 2
    assert plan.groups[0].is_album is False  # b.pdf, alone
    assert plan.groups[1].is_album is True  # c.jpg + a.jpg, now adjacent
