"""Tests for the redesigned tile/grid-based AttachmentsWidget. Public API
(get_attachments/is_empty/missing_files/add_file/attachments_changed) is
what app.ui.main_window and the send flow depend on.
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

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
# The full gesture has two halves:
#   1. mouse press + move past the drag threshold on an _AttachmentTile ->
#      it emits drag_requested, which _ReorderableListWidget.start_tile_drag
#      turns into a QDrag.exec() call.
#   2. a completed drop -> _ReorderableListWidget.dropEvent emits
#      tile_reorder_requested -> AttachmentsWidget._on_tile_reorder_requested
#      does the actual reorder.
#
# QDrag.exec() itself runs its own native nested event loop and cannot be
# driven under pytest (there is no real OS input queue to complete a native
# drag against), so half 2 is exercised directly by calling
# _on_tile_reorder_requested / emitting tile_reorder_requested -- this is
# exactly what a completed drop calls, so it exercises the real
# state-synchronization logic, not a reimplementation of it. Half 1 (does a
# real mouse gesture on a tile actually reach the code that starts the drag,
# and does the remove button correctly NOT trigger it) IS exercised here via
# PySide6.QtTest.QTest, which delivers genuine QMouseEvents through Qt's own
# event dispatch (qApp.notify) -- unlike a real OS-injected drag, this does
# not depend on the platform's native input queue, so it reliably tests the
# actual mousePressEvent/mouseMoveEvent logic on _AttachmentTile.
#
# What this suite cannot prove: that a physical mouse drag on a real Windows
# desktop feels natural, targets the right drop position, or is visually
# glitch-free (no flicker/stale widgets). That was verified separately,
# manually, against the real running app for the parts that could be (see
# the stage 3 correction commit/report) -- real OS-level drag-move injection
# did not register in this sandboxed environment even after the fix (a
# press+release did, confirming events reach the tile correctly), consistent
# with the same synthetic-input limitation identified in the original stage
# 3 session. That specific gap should be verified manually on a real machine.


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


# ---- drag-gesture interaction boundary (stage 3 correction pass) ------------
#
# These exercise _AttachmentTile's own mousePressEvent/mouseMoveEvent
# directly via QTest, which delivers real QMouseEvents through Qt's normal
# event dispatch -- the same delivery path a genuine mouse press on the tile
# uses, and the thing the original stage 3 implementation got wrong (it
# listened on the QListWidget viewport's event filter instead, which never
# sees events whose real target is a child index-widget like this tile).
#
# A second, subtler bug survived that first fix: _AttachmentTile called the
# QWidget base implementation in each handler, which ignore()s the event --
# and an ignored mouse press is redelivered by Qt to the parent (the list's
# viewport), which accepts it to run its own default click-to-select. That
# made the viewport (not the tile) become the effective target for the rest
# of a real gesture, so clicking still selected a tile while dragging still
# never reached this tile's mouseMoveEvent. The fix is a self.grabMouse() on
# press / self.releaseMouse() on release-or-drag-start -- Qt's own
# documented mechanism for exactly this (the QWidget docs name drag-and-drop
# detection as its intended use), which guarantees delivery to this widget
# regardless of hit-testing or redelivery. test_press_makes_the_tile_the_
# mouse_grabber below verifies this directly via QWidget.mouseGrabber(),
# Qt's own grab-state introspection -- a reliable, environment-independent
# check, unlike a synthetic OS-level drag gesture (which this sandboxed
# environment cannot reliably deliver either way; see the stage 3 correction
# report for what could and couldn't be verified with real mouse input).


def _tile_widget(widget, row):
    item = widget._list.item(row)
    return widget._tiles[id(item)].widget


def test_press_makes_the_tile_the_mouse_grabber(qapp, tmp_path):
    # Direct proof (via Qt's own QWidget.mouseGrabber() introspection, not
    # inference from a synthetic gesture's side effects) that the tile
    # becomes -- and correctly remains, until release -- Qt's exclusive
    # mouse-event target for the whole gesture. Qt guarantees delivery to
    # the grabbing widget regardless of hit-testing, so this is what
    # actually settles whether a real drag can reach mouseMoveEvent here.
    widget, paths = _make_widget_with_files(tmp_path, ["a.pdf"])
    tile = _tile_widget(widget, 0)
    threshold = QApplication.startDragDistance()

    assert QWidget.mouseGrabber() is None
    QTest.mousePress(tile, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    assert QWidget.mouseGrabber() is tile
    # Still held after a small move that stays under the drag threshold.
    QTest.mouseMove(tile, pos=QPoint(10 + max(threshold - 3, 1), 10))
    assert QWidget.mouseGrabber() is tile
    QTest.mouseRelease(tile, Qt.MouseButton.LeftButton, pos=QPoint(10 + max(threshold - 3, 1), 10))
    assert QWidget.mouseGrabber() is None


def test_grab_is_released_before_drag_requested_is_emitted(qapp, tmp_path):
    # QDrag.exec() (started from _ReorderableListWidget.start_tile_drag,
    # connected to this same signal in production) runs its own native
    # nested event loop and manages its own input capture -- our explicit
    # grab must already be gone by the time that happens, or it would only
    # fight the native drag. The real start_tile_drag slot is disconnected
    # here specifically so this check doesn't also trigger a live
    # drag.exec() with no drop target to complete it.
    widget, paths = _make_widget_with_files(tmp_path, ["a.pdf"])
    tile = _tile_widget(widget, 0)
    tile.drag_requested.disconnect(widget._list.start_tile_drag)
    grabber_at_emit = []
    tile.drag_requested.connect(lambda item: grabber_at_emit.append(QWidget.mouseGrabber()))
    threshold = QApplication.startDragDistance()

    QTest.mousePress(tile, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    assert QWidget.mouseGrabber() is tile
    QTest.mouseMove(tile, pos=QPoint(10 + threshold + 5, 10))

    assert grabber_at_emit == [None]


def test_mouse_press_alone_does_not_reorder_or_start_a_drag(qapp, tmp_path):
    widget, paths = _make_widget_with_files(tmp_path, ["a.pdf", "b.pdf"])
    tile = _tile_widget(widget, 0)
    requests = []
    tile.drag_requested.connect(lambda item: requests.append(item))

    QTest.mousePress(tile, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))

    assert requests == []
    assert [a.path for a in widget.get_attachments()] == paths


def test_move_below_drag_threshold_does_not_start_a_drag(qapp, tmp_path):
    widget, paths = _make_widget_with_files(tmp_path, ["a.pdf", "b.pdf"])
    tile = _tile_widget(widget, 0)
    requests = []
    tile.drag_requested.connect(lambda item: requests.append(item))
    threshold = QApplication.startDragDistance()

    QTest.mousePress(tile, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    # Move by less than the platform's own drag threshold -- must not be
    # mistaken for a drag gesture (a click/small jitter, not a drag).
    QTest.mouseMove(tile, pos=QPoint(10 + max(threshold - 2, 1), 10))

    assert requests == []


def test_move_past_drag_threshold_emits_drag_requested_for_the_right_item(qapp, tmp_path):
    widget, paths = _make_widget_with_files(tmp_path, ["a.pdf", "b.pdf", "c.pdf"])
    tile = _tile_widget(widget, 1)
    expected_item = widget._list.item(1)
    requests = []
    tile.drag_requested.connect(lambda item: requests.append(item))
    threshold = QApplication.startDragDistance()

    QTest.mousePress(tile, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    QTest.mouseMove(tile, pos=QPoint(10 + threshold + 5, 10))

    assert requests == [expected_item]


def test_real_press_and_release_without_movement_selects_the_tile(qapp, tmp_path):
    # Exercises _AttachmentTile's own explicit click-to-select logic (not
    # QListWidgetItem.setSelected() called directly, as the other selection
    # tests do) -- this replaces click-to-select behavior that used to come
    # for free via an ignored mouse press bubbling up to the QAbstractItemView
    # parent, which is exactly the mechanism that made real dragging never
    # reach this tile's mouseMoveEvent (see _AttachmentTile's docstring).
    widget, paths = _make_widget_with_files(tmp_path, ["a.pdf", "b.pdf"])
    tile = _tile_widget(widget, 0)

    QTest.mousePress(tile, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    QTest.mouseRelease(tile, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))

    assert widget._list.item(0).isSelected() is True
    assert tile.property("selected") == "true"


def test_plain_click_on_a_different_tile_replaces_the_selection(qapp, tmp_path):
    widget, paths = _make_widget_with_files(tmp_path, ["a.pdf", "b.pdf", "c.pdf"])
    widget._list.item(0).setSelected(True)
    tile_1 = _tile_widget(widget, 1)

    QTest.mousePress(tile_1, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    QTest.mouseRelease(tile_1, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))

    assert widget._list.item(0).isSelected() is False
    assert widget._list.item(1).isSelected() is True


def test_ctrl_click_toggles_selection_without_clearing_others(qapp, tmp_path):
    widget, paths = _make_widget_with_files(tmp_path, ["a.pdf", "b.pdf", "c.pdf"])
    widget._list.item(0).setSelected(True)
    widget._list.setCurrentItem(widget._list.item(0))
    tile_2 = _tile_widget(widget, 2)

    QTest.mousePress(tile_2, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, QPoint(10, 10))
    QTest.mouseRelease(tile_2, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, QPoint(10, 10))

    assert widget._list.item(0).isSelected() is True  # untouched by Ctrl+click elsewhere
    assert widget._list.item(2).isSelected() is True  # newly toggled on


def test_shift_click_selects_a_range(qapp, tmp_path):
    widget, paths = _make_widget_with_files(tmp_path, ["a.pdf", "b.pdf", "c.pdf", "d.pdf"])
    widget._list.setCurrentItem(widget._list.item(0))
    widget._list.item(0).setSelected(True)
    tile_2 = _tile_widget(widget, 2)

    QTest.mousePress(tile_2, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier, QPoint(10, 10))
    QTest.mouseRelease(tile_2, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier, QPoint(10, 10))

    assert [widget._list.item(i).isSelected() for i in range(4)] == [True, True, True, False]


def test_completed_drag_gesture_does_not_also_apply_click_selection(qapp, tmp_path):
    # A move past the drag threshold clears _press_pos, so the eventual
    # mouseReleaseEvent (would normally arrive from QDrag's own native loop,
    # not simulated here) must not re-select on top of an in-progress drag.
    widget, paths = _make_widget_with_files(tmp_path, ["a.pdf", "b.pdf"])
    tile = _tile_widget(widget, 0)
    threshold = QApplication.startDragDistance()
    requests = []
    tile.drag_requested.connect(lambda item: requests.append(item))

    QTest.mousePress(tile, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    QTest.mouseMove(tile, pos=QPoint(10 + threshold + 5, 10))
    QTest.mouseRelease(tile, Qt.MouseButton.LeftButton, pos=QPoint(10 + threshold + 5, 10))

    assert requests == [widget._list.item(0)]
    # Selection is untouched by the release that follows a drag -- neither
    # selected nor deselected as a side effect of the gesture ending.
    assert widget._list.item(0).isSelected() is False


def test_clicking_remove_button_does_not_emit_drag_requested(qapp, tmp_path):
    widget, paths = _make_widget_with_files(tmp_path, ["a.pdf", "b.pdf"])
    tile = _tile_widget(widget, 0)
    requests = []
    tile.drag_requested.connect(lambda item: requests.append(item))

    widget._tiles[id(widget._list.item(0))].remove_button.click()

    assert requests == []
    assert [a.path for a in widget.get_attachments()] == [paths[1]]


# ---- selection rendering (stage 3 correction pass) ---------------------------


def test_clicking_a_tile_marks_it_selected_via_the_selected_property(qapp, tmp_path):
    widget, paths = _make_widget_with_files(tmp_path, ["a.pdf", "b.pdf"])
    item = widget._list.item(0)
    tile = widget._tiles[id(item)].widget
    assert tile.property("selected") == "false"

    item.setSelected(True)

    assert tile.property("selected") == "true"
    other_tile = widget._tiles[id(widget._list.item(1))].widget
    assert other_tile.property("selected") == "false"


def test_deselecting_a_tile_clears_the_selected_property(qapp, tmp_path):
    widget, paths = _make_widget_with_files(tmp_path, ["a.pdf", "b.pdf"])
    item = widget._list.item(0)
    tile = widget._tiles[id(item)].widget
    item.setSelected(True)
    assert tile.property("selected") == "true"

    item.setSelected(False)

    assert tile.property("selected") == "false"


def test_selection_survives_reorder(qapp, tmp_path):
    widget, paths = _make_widget_with_files(tmp_path, ["a.pdf", "b.pdf", "c.pdf"])
    widget._list.item(0).setSelected(True)  # select "a.pdf"

    widget._on_tile_reorder_requested(0, 2)  # -> b, c, a

    # "a.pdf" is now the last tile (index 2) and must still be selected.
    new_order = [a.path for a in widget.get_attachments()]
    assert new_order == [paths[1], paths[2], paths[0]]
    selected_tile = widget._tiles[id(widget._list.item(2))].widget
    assert selected_tile.property("selected") == "true"
    unselected_tiles = [widget._tiles[id(widget._list.item(i))].widget for i in (0, 1)]
    assert all(t.property("selected") == "false" for t in unselected_tiles)


def test_selection_property_unaffected_by_theme_apply(qapp, tmp_path):
    widget, paths = _make_widget_with_files(tmp_path, ["a.pdf", "b.pdf"])
    widget._list.item(0).setSelected(True)

    widget.apply_theme()

    tile = widget._tiles[id(widget._list.item(0))].widget
    assert tile.property("selected") == "true"


def test_removing_the_selected_tile_leaves_a_valid_selection_state(qapp, tmp_path):
    widget, paths = _make_widget_with_files(tmp_path, ["a.pdf", "b.pdf"])
    item = widget._list.item(0)
    item.setSelected(True)

    widget._remove_item(item)  # must not raise

    assert [a.path for a in widget.get_attachments()] == [paths[1]]
    assert len(widget._tiles) == 1
    remaining_tile = widget._tiles[id(widget._list.item(0))].widget
    assert remaining_tile.property("selected") == "false"


def test_repeated_add_reorder_remove_leaves_no_stale_tile_widgets(qapp, tmp_path):
    widget, paths = _make_widget_with_files(tmp_path, ["a.pdf", "b.pdf", "c.pdf"])
    widget._on_tile_reorder_requested(0, 2)
    extra = tmp_path / "d.pdf"
    extra.write_bytes(b"x")
    widget.add_file(extra)
    widget._on_tile_reorder_requested(1, 3)
    widget._remove_item(widget._list.item(0))

    assert widget._list.count() == len(widget._paths) == len(widget._tiles)
    for i in range(widget._list.count()):
        item = widget._list.item(i)
        assert id(item) in widget._tiles
        tile = widget._tiles[id(item)]
        assert tile.widget is widget._list.itemWidget(item)


# ---- external file drag-and-drop (stage 3 correction pass) ------------------
#
# This behavior (dropping local files, e.g. from Explorer, onto the
# attachments area) already existed since the original stage 3 commit but had
# no test coverage at all -- added here per the explicit requirement that it
# must keep working through the drag-to-reorder fixes.


def _make_drop_event(paths, pos=None):
    from PySide6.QtCore import QMimeData, QPointF, QUrl
    from PySide6.QtCore import Qt as QtC
    from PySide6.QtGui import QDropEvent
    from PySide6.QtWidgets import QApplication as QApp

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    event = QDropEvent(
        pos or QPointF(5, 5),
        QtC.DropAction.CopyAction,
        mime,
        QApp.mouseButtons(),
        QApp.keyboardModifiers(),
    )
    # QDropEvent only holds a raw pointer to the QMimeData it's given, not
    # a reference that keeps it alive -- without this, `mime` is garbage
    # collected as soon as this function returns (nothing else in Python
    # holds it), and the event's own mimeData() access later becomes a
    # real Windows access violation (use-after-free), not a Python
    # exception. Tying its lifetime to the event object it's used with is
    # the simplest fix.
    event._mime_keepalive = mime
    return event


def test_dropping_external_files_onto_empty_widget_adds_them(qapp, tmp_path):
    widget = AttachmentsWidget()
    a = tmp_path / "a.pdf"
    a.write_bytes(b"x")
    b = tmp_path / "b.pdf"
    b.write_bytes(b"x")

    event = _make_drop_event([a, b])
    widget.dropEvent(event)

    assert [x.path for x in widget.get_attachments()] == [a, b]


def test_dropping_external_files_onto_populated_list_adds_them(qapp, tmp_path):
    widget, paths = _make_widget_with_files(tmp_path, ["a.pdf"])
    new_file = tmp_path / "b.pdf"
    new_file.write_bytes(b"x")

    event = _make_drop_event([new_file])
    widget._list.dropEvent(event)

    assert [x.path for x in widget.get_attachments()] == [paths[0], new_file]


def test_dropping_a_duplicate_external_file_is_ignored(qapp, tmp_path):
    widget, paths = _make_widget_with_files(tmp_path, ["a.pdf"])

    event = _make_drop_event([paths[0]])
    widget._list.dropEvent(event)

    assert [x.path for x in widget.get_attachments()] == [paths[0]]


def test_files_dropped_signal_is_wired_to_add_file(qapp, tmp_path):
    # Proves the _ReorderableListWidget.files_dropped -> AttachmentsWidget
    # wiring itself (connect() in __init__), not just that
    # _on_files_dropped_on_list works when called directly.
    widget, paths = _make_widget_with_files(tmp_path, ["a.pdf"])
    new_file = tmp_path / "b.pdf"
    new_file.write_bytes(b"x")

    widget._list.files_dropped.emit([str(new_file)])

    assert [x.path for x in widget.get_attachments()] == [paths[0], new_file]
