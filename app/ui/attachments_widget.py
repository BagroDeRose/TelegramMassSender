"""Attachment list widget: add via file dialog or drag & drop, remove,
clear (spec items 18-19, 50). Wraps app.telegram.media_sender.Attachment
so downstream code (the send plan) can consume the list directly.

Presentation: a compact grid of tiles. Image files get a real (memory-
conscious, scaled-decode) thumbnail via app.ui.thumbnails; everything else
gets a generic document tile with filename + size. Order is exactly
insertion order -- matches app.telegram.media_sender's own send order.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import QItemSelection, QItemSelectionModel, QMimeData, QPoint, QSize, Qt, Signal
from PySide6.QtGui import QDrag, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.i18n import tr
from app.telegram.media_sender import Attachment, AttachmentKind, kind_for_path
from app.ui import icons, theme
from app.ui.empty_state import build_empty_state, retranslate_empty_state
from app.ui.theme import SPACE_SM, SPACE_XS
from app.ui.thumbnails import format_file_size, is_image, make_thumbnail

_TILE_SIZE = 108
_THUMBNAIL_SIZE = 84
# Inset between the tile's edge (where its selection background and focus
# ring are painted) and its contents.
_TILE_PADDING = 5
_REMOVE_ICON_SIZE = 11
_FILE_ICON_SIZE = 30

# Which icons.py glyph represents each AttachmentKind in a tile that isn't
# showing a real decoded thumbnail. PHOTO/ANIMATION/IMAGE_OTHER are omitted
# on purpose: they normally get a real thumbnail (see THUMBNAILABLE_KINDS in
# media_sender.py) and only reach this fallback for a corrupted/unreadable
# file, same as any other kind -- the generic document glyph is an honest,
# unchanged-from-before fallback for that rare case, not a missing icon.
_ICON_NAME_FOR_KIND = {
    AttachmentKind.VIDEO: "video",
    AttachmentKind.AUDIO: "audio",
    AttachmentKind.ARCHIVE: "archive",
}
_DEFAULT_ICON_NAME = "document"


def _icon_name_for(path: Path) -> str:
    return _ICON_NAME_FOR_KIND.get(kind_for_path(path), _DEFAULT_ICON_NAME)


def _meta_text(path: Path) -> str:
    """"<size> · <TYPE>" for a tile's metadata line, e.g. "228 КБ · JPG" --
    both file size and file type in one compact line rather than two,
    keeping the tile from getting visually busier. Falls back to just the
    size (no extension) or just the type (unreadable size) rather than
    hiding the line entirely, since either half is still useful on its
    own."""
    try:
        size_text = format_file_size(path.stat().st_size)
    except OSError:
        size_text = ""
    ext = path.suffix.lstrip(".").upper()
    if size_text and ext:
        return f"{size_text} · {ext}"
    return size_text or ext


@dataclass
class _Tile:
    widget: QWidget  # the _AttachmentTile itself -- needed to drive its [selected] QSS property
    image_label: QLabel  # holds either the decoded thumbnail or the file-type icon
    remove_button: QToolButton
    is_image: bool
    icon_name: str = _DEFAULT_ICON_NAME  # which glyph is shown when is_image is False


_REORDER_MIME_TYPE = "application/x-telegrammasssender-attachment-row"


class _AttachmentTile(QWidget):
    """A single attachment card. Detects the drag-to-reorder gesture itself
    via its own mousePressEvent/mouseMoveEvent, rather than an event filter
    installed on the owning QListWidget's viewport.

    This tile is attached to its QListWidgetItem via setItemWidget(), which
    makes it a genuine child widget of the list's viewport, positioned on
    top of it. Qt delivers a mouse event to whichever widget is actually
    under the cursor -- for a press landing inside this tile, that target
    is this widget (or a WA_TransparentForMouseEvents decorative label
    inside it, which forwards straight to its parent, i.e. this widget),
    never the viewport itself.

    Two things make sure this tile stays the exclusive mouse target for the
    whole press-move-release gesture, not just the initial press:

    1. Every handler explicitly accept()s the event rather than calling the
       QWidget base implementation, which ignore()s it. An *ignored* mouse
       press is redelivered by Qt to the parent widget (the list's
       viewport) for a second chance to handle it -- and QAbstractItemView's
       own default press handling DOES accept it, to run its native
       click-to-select logic. A previous version of this class called
       super() in each handler and hit exactly that: selection-by-click
       kept working (via the viewport's default handling receiving the
       redelivered press), while a real, physical mouse drag never reached
       mouseMoveEvent here at all -- only a synthetic QTest event targeted
       directly at this widget did, since that bypasses the redelivery path
       entirely. Click-to-select is therefore implemented explicitly below
       instead of relying on that redelivery.

    2. self.grabMouse() on press / self.releaseMouse() on release-or-
       drag-start, on top of (1) -- Qt's own documented mechanism for
       exactly this (the QWidget docs name drag-and-drop detection as its
       intended use): "While the mouse is grabbed... this widget receives
       all mouse events." Verified directly via QWidget.mouseGrabber() in
       tests/test_attachments_widget.py rather than inferred from a
       synthetic gesture's side effects.
    """

    drag_requested = Signal(object)  # emits the QListWidgetItem this tile represents
    remove_requested = Signal(object)  # emits the QListWidgetItem this tile represents (Delete/Backspace key)
    move_requested = Signal(object, int)  # (QListWidgetItem, -1 earlier / +1 later) from Ctrl+Arrow

    def __init__(self, item: QListWidgetItem, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._item = item
        self._press_pos: Optional[QPoint] = None
        self._was_sole_selection_on_press = False
        self._focus_from_click = False
        # Accessibility (ROADMAP v1.8): without a focus policy the tile is
        # unreachable by Tab and invisible to a screen reader.
        #
        # TabFocus rather than StrongFocus, with mouse focus taken by hand in
        # mousePressEvent: when a click moves focus onto an item widget, the
        # list view selects that item *during* the press, before this class
        # sees the event. Click-to-deselect has to know whether the tile was
        # already selected before the click, so focus must move only after
        # that has been recorded. A click still focuses the tile, so Delete
        # and Ctrl+Arrow keep working after clicking.
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setProperty("focused", "false")

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.button() == Qt.MouseButton.LeftButton:
            list_widget = self._item.listWidget()
            self._was_sole_selection_on_press = (
                list_widget is not None
                and self._item.isSelected()
                and len(list_widget.selectedItems()) == 1
            )
            self._focus_from_click = True
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self._press_pos = event.position().toPoint()
            # Explicit grab, on top of accept() below: accept() alone stops
            # *this* press from being redelivered to the parent, but Qt's
            # internal "who gets the next move" tracking is a separate,
            # less-documented mechanism this class cannot fully control by
            # accept/ignore alone. grabMouse() is Qt's own documented
            # mechanism for exactly this (the QWidget docs explicitly name
            # drag-and-drop detection as its intended use): while held, ALL
            # mouse events go to this widget regardless of hit-testing or
            # any redelivery heuristic, full stop.
            self.grabMouse()
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if (
            self._press_pos is not None
            and bool(event.buttons() & Qt.MouseButton.LeftButton)
            and (event.position().toPoint() - self._press_pos).manhattanLength() >= QApplication.startDragDistance()
        ):
            self._press_pos = None
            # Released before starting the native drag rather than after --
            # QDrag.exec() runs its own native nested event loop and manages
            # its own input capture; holding our own explicit grab across
            # that call would only fight it.
            self.releaseMouse()
            self.drag_requested.emit(self._item)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (Qt override)
        # self._press_pos is still set here for a plain click (no drag was
        # started -- mouseMoveEvent above clears it, and releases the grab,
        # once the drag threshold is crossed), so this is the point a
        # click's selection change actually applies, mirroring
        # QAbstractItemView's own click semantics (plain/Ctrl/Shift) via
        # its selection model directly rather than reimplementing that
        # logic by hand.
        if event.button() == Qt.MouseButton.LeftButton:
            if self._press_pos is not None:
                self.releaseMouse()
                self._apply_click_selection(event.modifiers())
            self._press_pos = None
        event.accept()

    def _apply_click_selection(self, modifiers: Qt.KeyboardModifier) -> None:
        list_widget = self._item.listWidget()
        if list_widget is None:
            return  # item was already removed from the list mid-gesture
        selection_model = list_widget.selectionModel()
        index = list_widget.indexFromItem(self._item)
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            anchor = list_widget.currentIndex()
            if anchor.isValid():
                selection_model.select(QItemSelection(anchor, index), QItemSelectionModel.SelectionFlag.ClearAndSelect)
                selection_model.setCurrentIndex(index, QItemSelectionModel.SelectionFlag.Current)
                return
        elif modifiers & Qt.KeyboardModifier.ControlModifier:
            # Deliberately two separate calls rather than Toggle|Current in
            # one setCurrentIndex() -- combined, Qt's list-widget selection
            # sync clears every other item's selection first (confirmed
            # empirically), which defeats the entire point of Ctrl+click.
            selection_model.select(index, QItemSelectionModel.SelectionFlag.Toggle)
            selection_model.setCurrentIndex(index, QItemSelectionModel.SelectionFlag.Current)
            return
        if self._was_sole_selection_on_press:
            # Clicking the only selected tile again deselects it. With several
            # selected, a plain click still narrows the selection to this one.
            selection_model.clearSelection()
            return
        selection_model.setCurrentIndex(index, QItemSelectionModel.SelectionFlag.ClearAndSelect)

    def focusInEvent(self, event) -> None:  # noqa: N802 (Qt override)
        # A deliberate, QSS-driven focus ring on the tile itself (see
        # #attachmentTile[focused] in theme.py) -- NOT the native
        # QAbstractItemView "current item" focus rectangle
        # (QStyle::PE_FrameFocusRect), which theme.py explicitly
        # suppresses via outline:none (see the dark-theme dashed-outline
        # bugfix). Keyboard users still need to see where focus is; this
        # is a correctly-scoped replacement for it, not a reintroduction
        # of that bug.
        #
        # No ring when the focus came from a mouse click: the ring shares its
        # color with the selection border, so a ring left behind by a click
        # would make a tile that was just clicked to deselect it still look
        # selected. Tracked by flag rather than by event.reason(), because
        # focus restored by re-activating the window arrives as
        # ActiveWindowFocusReason whichever way it originally got there.
        self.setProperty("focused", "false" if self._focus_from_click else "true")
        self.style().unpolish(self)
        self.style().polish(self)
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.reason() not in (Qt.FocusReason.ActiveWindowFocusReason, Qt.FocusReason.PopupFocusReason):
            # A real move elsewhere; just switching windows keeps how focus arrived.
            self._focus_from_click = False
        self.setProperty("focused", "false")
        self.style().unpolish(self)
        self.style().polish(self)
        super().focusOutEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        key = event.key()
        # Ctrl+Arrow moves this tile one position in the send order. Plain
        # arrows are deliberately left to the list view's own focus
        # navigation, so moving is always an explicit, modified gesture --
        # a keyboard user can never reorder by accident while just walking
        # the grid.
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier and key in (
            Qt.Key.Key_Left,
            Qt.Key.Key_Right,
        ):
            self.move_requested.emit(self._item, -1 if key == Qt.Key.Key_Left else 1)
            event.accept()
            return
        if key == Qt.Key.Key_Space:
            # Toggle this tile's selection -- the same convention
            # QAbstractItemView itself uses for Space in extended-
            # selection mode, kept consistent with Ctrl+click above.
            list_widget = self._item.listWidget()
            if list_widget is not None:
                selection_model = list_widget.selectionModel()
                index = list_widget.indexFromItem(self._item)
                selection_model.select(index, QItemSelectionModel.SelectionFlag.Toggle)
                selection_model.setCurrentIndex(index, QItemSelectionModel.SelectionFlag.Current)
            event.accept()
            return
        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.remove_requested.emit(self._item)
            event.accept()
            return
        super().keyPressEvent(event)


class _ReorderableListWidget(QListWidget):
    """QListWidget whose items carry a fully custom tile widget attached
    via setItemWidget() (thumbnail/icon, filename, remove button) and are
    reordered via a minimal hand-rolled QDrag, rather than Qt's built-in
    setDragDropMode(InternalMove).

    Qt's built-in item-view drag-and-drop reorders by round-tripping each
    dragged row's *model data* (text/icon/decoration roles) through
    mimeData()/dropMimeData() -- it has no mechanism to carry a
    setItemWidget()-attached widget across that round-trip, so enabling
    InternalMove here would silently drop each moved tile's thumbnail/
    icon/remove-button. Instead, a drag only ever carries the source row
    index as private MIME data (started by _AttachmentTile.drag_requested,
    see start_tile_drag below); the actual reorder is done by the owning
    AttachmentsWidget mutating its own path list and rebuilding tiles from
    scratch (see AttachmentsWidget._rebuild_tiles), reusing the same,
    already-tested per-tile construction used for a normal add_file().

    Movement stays Static throughout (unchanged from before this class
    existed) -- this is about the *order* changing, not items being
    freely repositioned to arbitrary pixel coordinates.
    """

    tile_reorder_requested = Signal(int, int)  # from_row, to_row
    files_dropped = Signal(list)  # List[str] local file paths from an external (e.g. Explorer) drag

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        # Required for dragEnterEvent/dropEvent below to be delivered to
        # this widget at all -- for both the internal reorder drag and an
        # external file drag landing directly on the (populated) tile
        # grid. AttachmentsWidget's own setAcceptDrops(True) still handles
        # an external drop while the grid is empty/hidden.
        self.setAcceptDrops(True)

    def start_tile_drag(self, item: QListWidgetItem) -> None:
        """Called from an _AttachmentTile's drag_requested signal once its
        own mouseMoveEvent has confirmed a real drag gesture past Qt's
        standard drag threshold."""
        row = self.row(item)
        if row < 0:
            return  # stale signal from a tile whose item was already removed
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(_REORDER_MIME_TYPE, str(row).encode("ascii"))
        drag.setMimeData(mime)
        # Without a drag pixmap the user drags an invisible nothing and has
        # no way to tell what is being moved or that a drag started at all.
        tile = self.itemWidget(item)
        if tile is not None:
            pixmap = tile.grab()
            drag.setPixmap(pixmap)
            drag.setHotSpot(QPoint(pixmap.width() // 2, pixmap.height() // 2))
        drag.exec(Qt.DropAction.MoveAction)

    def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.mimeData().hasFormat(_REORDER_MIME_TYPE) or event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.mimeData().hasFormat(_REORDER_MIME_TYPE) or event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802 (Qt override)
        mime = event.mimeData()
        if mime.hasFormat(_REORDER_MIME_TYPE):
            source_row = int(bytes(mime.data(_REORDER_MIME_TYPE)).decode("ascii"))
            index = self.indexAt(event.position().toPoint())
            # The emitted target is the slot the dragged tile should end up
            # occupying. Dropping ON a tile means "take that tile's slot";
            # dropping past every tile (the cursor was in the wrapped
            # grid's trailing empty space, so indexAt() is invalid) means
            # "take the last slot". Both are expressed directly as a final
            # index, so the drop is not direction-dependent -- see
            # AttachmentsWidget.move_attachment.
            target_row = index.row() if index.isValid() else self.count() - 1
            event.acceptProposedAction()
            if target_row != source_row:
                self.tile_reorder_requested.emit(source_row, target_row)
        elif mime.hasUrls():
            paths = [url.toLocalFile() for url in mime.urls() if url.toLocalFile()]
            event.acceptProposedAction()
            if paths:
                self.files_dropped.emit(paths)


class AttachmentsWidget(QWidget):
    attachments_changed = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._paths: List[Path] = []
        self._tiles: Dict[int, _Tile] = {}  # id(QListWidgetItem) -> its themed parts
        # Per-path decoded thumbnail and metadata line, kept across tile
        # rebuilds. Every reorder rebuilds all tiles (see _rebuild_tiles),
        # and without this each rebuild re-decoded every image from disk:
        # measured at 12 disk decodes and ~208 ms of blocked UI for a
        # single reorder of 12 photos, which is what made dragging feel
        # laggy and choppy. Entries are dropped in _remove_item/clear(),
        # so the cache never outlives the attachment itself.
        self._thumbnail_cache: Dict[Path, Optional[QPixmap]] = {}
        self._meta_cache: Dict[Path, str] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_SM)

        self._empty_label = build_empty_state(
            tr("attachments_widget.empty_title"), tr("attachments_widget.empty_body"), self
        )
        layout.addWidget(self._empty_label)

        self._list = _ReorderableListWidget(self)
        # Scoped objectName so the QSS in theme.py can neutralize the
        # native QListWidget::item:selected paint for this list without
        # affecting any other QListWidget in the app -- the native
        # selection rectangle is drawn at the item's own rect, not the
        # custom tile's rounded shape, and shows through at the edges;
        # selection is instead drawn deliberately on the tile itself (see
        # _AttachmentTile / #attachmentTile[selected] and
        # _on_selection_changed below).
        self._list.setObjectName("attachmentsList")
        self._list.setViewMode(QListView.ViewMode.IconMode)
        self._list.setFlow(QListView.Flow.LeftToRight)
        self._list.setWrapping(True)
        self._list.setResizeMode(QListView.ResizeMode.Adjust)
        self._list.setMovement(QListView.Movement.Static)
        self._list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self._list.setFrameShape(QListWidget.Shape.NoFrame)
        self._list.setSpacing(SPACE_SM)
        self._list.setUniformItemSizes(True)
        self._list.hide()
        self._list.tile_reorder_requested.connect(self._on_tile_reorder_requested)
        self._list.files_dropped.connect(self._on_files_dropped_on_list)
        self._list.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self._list)

        # Explicit ordering controls. Drag-and-drop still works, but it
        # depends on landing the cursor precisely on the intended tile;
        # these give a deterministic, one-position-at-a-time alternative
        # that works by selection alone (and by keyboard via Ctrl+Arrow on
        # a focused tile), which is what makes an exact target order
        # reliably reachable.
        self._order_hint = QLabel(tr("attachments_widget.order_hint"), self)
        self._order_hint.setObjectName("thumbnailMeta")
        self._order_hint.setVisible(False)
        layout.addWidget(self._order_hint)

        buttons = QHBoxLayout()
        self._move_earlier_button = QPushButton(tr("attachments_widget.move_earlier_button"), self)
        self._move_earlier_button.setObjectName("ghostButton")
        self._move_earlier_button.setToolTip(tr("attachments_widget.move_earlier_tooltip"))
        self._move_earlier_button.setAccessibleName(tr("attachments_widget.move_earlier_tooltip"))
        self._move_earlier_button.setEnabled(False)
        self._move_earlier_button.clicked.connect(lambda: self._move_selected(-1))
        self._move_later_button = QPushButton(tr("attachments_widget.move_later_button"), self)
        self._move_later_button.setObjectName("ghostButton")
        self._move_later_button.setToolTip(tr("attachments_widget.move_later_tooltip"))
        self._move_later_button.setAccessibleName(tr("attachments_widget.move_later_tooltip"))
        self._move_later_button.setEnabled(False)
        self._move_later_button.clicked.connect(lambda: self._move_selected(1))
        buttons.addWidget(self._move_earlier_button)
        buttons.addWidget(self._move_later_button)

        self._add_button = QPushButton(tr("attachments_widget.add_button"), self)
        self._add_button.clicked.connect(self._on_add_clicked)
        self._remove_selected_button = QPushButton(tr("attachments_widget.remove_selected_button"), self)
        self._remove_selected_button.clicked.connect(self._on_remove_clicked)
        self._clear_button = QPushButton(tr("attachments_widget.clear_button"), self)
        self._clear_button.setObjectName("ghostButton")
        self._clear_button.clicked.connect(self._on_clear_clicked)
        buttons.addWidget(self._add_button)
        buttons.addWidget(self._remove_selected_button)
        buttons.addWidget(self._clear_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self._sync_empty_state()

    # ---- adding / removing ---------------------------------------------------

    def _on_add_clicked(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, tr("attachments_widget.add_dialog_title"))
        for file_path in files:
            self.add_file(Path(file_path))

    def _on_remove_clicked(self) -> None:
        for item in self._list.selectedItems():
            self._remove_item(item)

    def _on_clear_clicked(self) -> None:
        self.clear()

    def clear(self) -> None:
        self._list.clear()
        self._paths.clear()
        self._tiles.clear()
        self._thumbnail_cache.clear()
        self._meta_cache.clear()
        self._sync_empty_state()
        self._update_move_buttons()
        self.attachments_changed.emit()

    def _remove_item(self, item: QListWidgetItem) -> None:
        row = self._list.row(item)
        if row < 0:
            return
        removed = self._paths[row]
        self._tiles.pop(id(item), None)
        self._list.takeItem(row)
        del self._paths[row]
        self._thumbnail_cache.pop(removed, None)
        self._meta_cache.pop(removed, None)
        # Positions shift for every tile after the removed one, and each
        # tile announces its own position to a screen reader, so the
        # remaining tiles have to be re-labelled.
        self._relabel_tiles()
        self._sync_empty_state()
        self._update_move_buttons()
        self.attachments_changed.emit()

    def _relabel_tiles(self) -> None:
        for row, path in enumerate(self._paths):
            item = self._list.item(row)
            if item is None:
                continue
            tile = self._list.itemWidget(item)
            if tile is not None:
                tile.setAccessibleName(self._accessible_name_for(path, row))

    def _accessible_name_for(self, path: Path, row: int) -> str:
        """Screen readers get the send position as well as the filename --
        with ordering as a first-class feature, "which one is this and
        where is it in the order" is the whole point of the tile."""
        position = tr(
            "attachments_widget.position_label", position=row + 1, total=len(self._paths)
        )
        return f"{path.name} — {position}"

    def add_file(self, path: Path) -> None:
        if path in self._paths:
            return
        self._paths.append(path)
        self._append_tile(path)
        self._relabel_tiles()  # the new tile changes every tile's "of N" total
        self._sync_empty_state()
        self._update_move_buttons()
        self.attachments_changed.emit()

    def _on_files_dropped_on_list(self, paths: List[str]) -> None:
        # Forwarded from _ReorderableListWidget for an external file drag
        # landing directly on the (already populated, thus visible) tile
        # grid -- add_file already de-dupes and emits attachments_changed.
        for file_path in paths:
            self.add_file(Path(file_path))

    def _on_tile_reorder_requested(self, source_row: int, target_row: int) -> None:
        # Strict, unlike move_attachment's clamping: a genuine drop always
        # produces an in-range target (dropEvent resolves it from either a
        # valid index or the last row), so anything out of range here is a
        # stale or corrupt signal and must be ignored rather than clamped
        # into a reorder the user never asked for.
        count = len(self._paths)
        if not (0 <= source_row < count) or not (0 <= target_row < count):
            return
        self.move_attachment(source_row, target_row)

    def move_attachment(self, from_index: int, to_index: int) -> bool:
        """Move one attachment so that it ends up at exactly `to_index` in
        the resulting order. Returns True if the order actually changed.

        This is the single canonical ordering operation -- drag-and-drop,
        the Move earlier/later buttons and the Ctrl+Arrow shortcuts all go
        through it, so every path shares one semantic and one set of
        tests.

        `to_index` is the *final* index, not an insertion point relative to
        some other item, which is what makes this direction-independent:
        popping the source first and then inserting at `to_index` lands the
        item on that slot whether it travelled forwards or backwards. The
        previous "insert immediately before the target tile" rule only
        agreed with that for backward moves and always landed one slot
        short going forward (measured: dragging row 0 onto slot 2 put it at
        index 1), which is why reordering felt unreliable.
        """
        count = len(self._paths)
        if not (0 <= from_index < count):
            return False  # stale/out-of-range row -- ignore rather than corrupt order
        to_index = max(0, min(to_index, count - 1))
        if to_index == from_index:
            return False
        path = self._paths.pop(from_index)
        self._paths.insert(to_index, path)
        # Keep the moved attachment selected and current so repeated moves
        # (clicking Move later three times, or holding Ctrl+Right) keep
        # acting on the same tile instead of losing it after one step.
        self._rebuild_tiles(selected_paths={path}, focus_path=path)
        return True

    def _move_selected(self, delta: int) -> None:
        index = self._selected_index()
        if index is not None:
            self.move_attachment(index, index + delta)

    def _on_tile_move_requested(self, item: QListWidgetItem, delta: int) -> None:
        row = self._list.row(item)
        if row >= 0:
            self.move_attachment(row, row + delta)

    def _selected_index(self) -> Optional[int]:
        """The row the ordering controls act on: exactly one selected tile.
        With none or several selected there is no unambiguous "this one",
        so the buttons disable instead of guessing."""
        items = self._list.selectedItems()
        if len(items) != 1:
            return None
        row = self._list.row(items[0])
        return row if row >= 0 else None

    def _update_move_buttons(self) -> None:
        index = self._selected_index()
        last = len(self._paths) - 1
        self._move_earlier_button.setEnabled(index is not None and index > 0)
        self._move_later_button.setEnabled(index is not None and 0 <= index < last)

    def _append_tile(self, path: Path) -> None:
        item = QListWidgetItem(self._list)
        item.setSizeHint(QSize(_TILE_SIZE, _TILE_SIZE + 46 + 2 * _TILE_PADDING))
        self._list.addItem(item)
        tile = self._build_tile(item, path)
        self._list.setItemWidget(item, tile)
        tile.drag_requested.connect(self._list.start_tile_drag)
        tile.remove_requested.connect(self._remove_item)
        tile.move_requested.connect(self._on_tile_move_requested)

    def _rebuild_tiles(self, *, selected_paths: Optional[set] = None, focus_path: Optional[Path] = None) -> None:
        """Rebuild every tile from self._paths, in its current order. Used
        after a reorder rather than trying to move the existing
        QListWidgetItem/setItemWidget pair in place -- Qt's item-view
        drag-and-drop machinery does not preserve a setItemWidget()
        widget across a move (see _ReorderableListWidget), so a full
        rebuild via the same per-path tile construction add_file() already
        uses is the simplest way to guarantee the displayed tiles always
        match self._paths exactly, without a second, parallel code path.

        A full clear() drops all QListWidgetItem selection state, so a
        previously-selected tile would otherwise silently lose its
        selection on every reorder -- selected_paths (identified by path,
        not row, since rows shift) lets the caller ask for it back."""
        self._list.clear()
        self._tiles.clear()
        for path in self._paths:
            self._append_tile(path)
        if selected_paths:
            for i, path in enumerate(self._paths):
                if path in selected_paths:
                    self._list.item(i).setSelected(True)
        if focus_path is not None and focus_path in self._paths:
            row = self._paths.index(focus_path)
            item = self._list.item(row)
            self._list.setCurrentItem(item)
            tile = self._list.itemWidget(item)
            if tile is not None:
                tile.setFocus(Qt.FocusReason.OtherFocusReason)
        self._sync_empty_state()
        self._update_move_buttons()
        self.attachments_changed.emit()

    def _on_selection_changed(self) -> None:
        """Drive each tile's own [selected] QSS state -- the native
        QListWidget::item:selected paint is deliberately neutralized for
        this list (see theme.py) because it draws behind the custom tile
        at the item's own rect rather than the tile's actual rounded
        shape."""
        self._update_move_buttons()
        selected_ids = {id(i) for i in self._list.selectedItems()}
        for item_id, tile in self._tiles.items():
            is_selected = item_id in selected_ids
            if tile.widget.property("selected") == ("true" if is_selected else "false"):
                continue
            tile.widget.setProperty("selected", "true" if is_selected else "false")
            style = tile.widget.style()
            style.unpolish(tile.widget)
            style.polish(tile.widget)

    def _build_tile(self, item: QListWidgetItem, path: Path) -> _AttachmentTile:
        tokens = theme.current_tokens()
        tile = _AttachmentTile(item, self._list)
        tile.setObjectName("attachmentTile")
        # A plain QWidget doesn't paint QSS background-color/border on its
        # own -- only QFrame-derived widgets do that automatically.
        tile.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        tile.setProperty("selected", "false")
        # Accessibility (ROADMAP v1.8): a screen reader has no other text
        # to announce for this composite widget (its child labels are all
        # WA_TransparentForMouseEvents decoration, not focusable in their
        # own right) -- accessibleName is what gets read when the tile
        # itself receives focus.
        tile.setAccessibleName(self._accessible_name_for(path, self._list.row(item)))
        tile.setFixedWidth(_TILE_SIZE)
        column = QVBoxLayout(tile)
        # Inset the contents by more than the 2px border so the tile's own
        # [selected] background and [focused] ring stay visible. With zero
        # margins the full-width children painted straight over both, and
        # the ring survived only as four corner arcs -- selection was
        # effectively invisible, which matters now that selecting a tile is
        # how the ordering controls are aimed.
        column.setContentsMargins(_TILE_PADDING, _TILE_PADDING, _TILE_PADDING, _TILE_PADDING)
        column.setSpacing(4)

        frame = QLabel(tile)
        frame.setObjectName("thumbnailTile")
        frame.setFixedSize(_TILE_SIZE - 2 * _TILE_PADDING, _THUMBNAIL_SIZE)
        frame.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Purely decorative -- let a press/drag started here pass through to
        # the tile underneath instead of being swallowed by the label, so
        # dragging by the thumbnail (the most natural place to grab a
        # tile) actually reaches _AttachmentTile's own mouse handlers.
        frame.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        if path not in self._thumbnail_cache:
            self._thumbnail_cache[path] = make_thumbnail(path, _THUMBNAIL_SIZE - 8) if is_image(path) else None
        thumbnail = self._thumbnail_cache[path]
        image_is_thumbnail = thumbnail is not None
        icon_name = _icon_name_for(path)
        if thumbnail is not None:
            frame.setPixmap(thumbnail)
        else:
            frame.setPixmap(icons.icon(icon_name, tokens.text_muted, _FILE_ICON_SIZE).pixmap(_FILE_ICON_SIZE, _FILE_ICON_SIZE))
        column.addWidget(frame)

        name_label = QLabel(_elide(path.name), tile)
        name_label.setObjectName("thumbnailName")
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_label.setToolTip(str(path))
        name_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        column.addWidget(name_label)

        if path not in self._meta_cache:
            self._meta_cache[path] = _meta_text(path)
        meta_text = self._meta_cache[path]
        if meta_text:
            meta_label = QLabel(meta_text, tile)
            meta_label.setObjectName("thumbnailMeta")
            meta_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            meta_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            column.addWidget(meta_label)
            tile.setAccessibleDescription(meta_text)

        remove_button = QToolButton(tile)
        remove_button.setObjectName("chipRemoveButton")
        remove_button.setIcon(icons.icon("close", tokens.text_muted, _REMOVE_ICON_SIZE))
        remove_button.setText(tr("attachments_widget.remove_tile_button"))
        remove_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        remove_button.setToolTip(tr("attachments_widget.remove_tile_tooltip"))
        remove_button.clicked.connect(lambda: self._remove_item(item))
        remove_row = QHBoxLayout()
        remove_row.setContentsMargins(0, 0, 0, 0)
        remove_row.addStretch(1)
        remove_row.addWidget(remove_button)
        remove_row.addStretch(1)
        column.addLayout(remove_row)

        self._tiles[id(item)] = _Tile(
            widget=tile, image_label=frame, remove_button=remove_button, is_image=image_is_thumbnail, icon_name=icon_name
        )
        return tile

    def _sync_empty_state(self) -> None:
        has_items = bool(self._paths)
        self._empty_label.setVisible(not has_items)
        self._list.setVisible(has_items)
        # Only meaningful once there is actually an order to change.
        self._order_hint.setVisible(len(self._paths) > 1)

    # ---- drag & drop ------------------------------------------------------

    def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802 (Qt override)
        for url in event.mimeData().urls():
            local_path = url.toLocalFile()
            if local_path:
                self.add_file(Path(local_path))
        event.acceptProposedAction()

    # ---- theming -------------------------------------------------------------

    def apply_theme(self) -> None:
        """Re-tint baked file-icon/remove-button pixmaps after a theme
        switch -- QSS alone can't recolor a QIcon/QPixmap, and real image
        thumbnails don't need re-decoding since they carry their own
        colors regardless of theme. Each tile remembers which glyph it
        was built with (icon_name) so re-tinting doesn't collapse every
        non-image tile back to the generic document icon."""
        color = theme.current_tokens().text_muted
        for tile in self._tiles.values():
            if not tile.is_image:
                tile.image_label.setPixmap(icons.icon(tile.icon_name, color, _FILE_ICON_SIZE).pixmap(_FILE_ICON_SIZE, _FILE_ICON_SIZE))
            tile.remove_button.setIcon(icons.icon("close", color, _REMOVE_ICON_SIZE))

    def retranslate_ui(self) -> None:
        retranslate_empty_state(
            self._empty_label, tr("attachments_widget.empty_title"), tr("attachments_widget.empty_body")
        )
        self._add_button.setText(tr("attachments_widget.add_button"))
        self._remove_selected_button.setText(tr("attachments_widget.remove_selected_button"))
        self._clear_button.setText(tr("attachments_widget.clear_button"))
        self._order_hint.setText(tr("attachments_widget.order_hint"))
        self._move_earlier_button.setText(tr("attachments_widget.move_earlier_button"))
        self._move_earlier_button.setToolTip(tr("attachments_widget.move_earlier_tooltip"))
        self._move_earlier_button.setAccessibleName(tr("attachments_widget.move_earlier_tooltip"))
        self._move_later_button.setText(tr("attachments_widget.move_later_button"))
        self._move_later_button.setToolTip(tr("attachments_widget.move_later_tooltip"))
        self._move_later_button.setAccessibleName(tr("attachments_widget.move_later_tooltip"))
        # Rebuilds every tile from self._paths (preserving selection) --
        # the same mechanism a reorder already uses -- rather than looping
        # each tile's remove-button text/tooltip and the size/type meta
        # line separately, since a full rebuild already guarantees every
        # tile matches the current language with no second code path.
        selected_paths = {self._paths[self._list.row(i)] for i in self._list.selectedItems()}
        # The size half of a tile's meta line is localized ("228 КБ" vs
        # "228 KB"), so that cache is stale after a language switch. The
        # thumbnail cache is language-independent and deliberately kept --
        # it is the expensive one.
        self._meta_cache.clear()
        self._rebuild_tiles(selected_paths=selected_paths)

    # ---- public API used by app.ui.main_window --------------------------------

    def get_attachments(self) -> List[Attachment]:
        return [Attachment(path=p) for p in self._paths]

    def is_empty(self) -> bool:
        return not self._paths

    def missing_files(self) -> List[Path]:
        return [p for p in self._paths if not p.is_file()]

    def unreadable_files(self) -> List[Path]:
        """Files that exist but fail the lightweight read probe (locked by
        another program, permission denied) -- distinct from
        missing_files(), which is about the path not existing at all. Only
        checks files that do exist, so this can be called independently of
        missing_files() without double-reporting a missing path here."""
        return [p for p in self._paths if p.is_file() and not Attachment(path=p).is_readable()]


def _elide(text: str, max_chars: int = 16) -> str:
    """Character-count elision, not pixel-measured -- the tile has a fixed
    width and this app's font, so a fixed budget is good enough and avoids
    needing a QFontMetrics instance at tile-build time."""
    if len(text) <= max_chars:
        return text
    stem, _, ext = text.rpartition(".")
    if not stem:
        return text[: max_chars - 2] + "…"
    return f"{stem[:10]}…{('.' + ext) if ext else ''}"
