"""Model / filter / row painting behind the "From my chats…" picker.

DialogListModel holds the account's dialogs (app.telegram.chat_targets.
DialogTarget, already loaded by MainWindow through the service layer) in
last-message order, which dialogs are ticked, and which are already in the
Recipients box. DialogFilterProxy narrows it by type, folder, archive and
search text without copying anything; DialogRowDelegate paints a row
(initials circle -- no avatars are downloaded --, name, type, @username or
ID, date). Built for thousands of dialogs: filtering reads plain Python
fields precomputed once per load, never the model's data() roles.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, FrozenSet, Iterable, List, Optional, Sequence, Set

from PySide6.QtCore import (
    QAbstractListModel,
    QDate,
    QEvent,
    QLocale,
    QModelIndex,
    QRect,
    QRectF,
    QSize,
    QSortFilterProxyModel,
    Qt,
)
from PySide6.QtGui import QFontMetrics, QPainter
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from app.i18n import get_language, tr
from app.recipients.parser import parse_recipient_line
from app.telegram.chat_targets import DialogCategory, DialogTarget, TargetType
from app.ui import icons, theme
from app.ui.theme import (
    AVATAR_SIZE,
    DIALOG_PICKER_CHECK_COL,
    DIALOG_PICKER_DATE_WIDTH,
    DIALOG_PICKER_ROW_HEIGHT,
    FONT_SIZE_BODY,
    FONT_SIZE_CAPTION,
    FONT_SIZE_HELPER,
    ICON_SIZE_SM,
    PILL_TINT_ALPHA,
    SPACE_MD,
    SPACE_SM,
    SPACE_XS,
)

TARGET_ROLE = Qt.ItemDataRole.UserRole + 1
ALREADY_ADDED_ROLE = Qt.ItemDataRole.UserRole + 2

TYPE_ICONS = {
    TargetType.USER: "user",
    TargetType.GROUP: "group",
    TargetType.SUPERGROUP: "supergroup",
    TargetType.FORUM: "forum",
    TargetType.CHANNEL: "channel",
}


def dialog_icon_name(dialog: DialogTarget) -> str:
    return "bot" if dialog.is_bot else TYPE_ICONS[dialog.target_type]


def dialog_recipient_keys(dialog: DialogTarget) -> FrozenSet[str]:
    """Every normalized recipient key that names this dialog's addressee
    (its @username and its ID), so a dialog counts as already listed
    whichever form the Recipients box holds it in."""
    lines = [str(dialog.peer_id)]
    if dialog.username:
        lines.append(f"@{dialog.username}")
    keys = {parse_recipient_line(line).normalized_key for line in lines}
    return frozenset(key for key in keys if key)


def dialog_initials(title: str) -> str:
    words = [word for word in title.replace("_", " ").split() if word[:1].isalnum()]
    letters = "".join(word[0] for word in words[:2])
    return (letters or title[:1] or "?").upper()


def format_dialog_date(value: Optional[datetime], now: Optional[datetime] = None) -> str:
    """Time for today, day and month for this year, the full date before."""
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    local = value.astimezone()
    today = (now or datetime.now(timezone.utc)).astimezone()
    locale = QLocale(QLocale.Language.Russian if get_language() == "ru" else QLocale.Language.English)
    date = QDate(local.year, local.month, local.day)
    if local.date() == today.date():
        return f"{local.hour:02d}:{local.minute:02d}"
    if local.year == today.year:
        return locale.toString(date, "d MMM")
    return locale.toString(date, "dd.MM.yyyy")


def _sort_key(dialog: DialogTarget) -> float:
    date = dialog.last_message_date
    if date is None:
        return float("-inf")
    if date.tzinfo is None:
        date = date.replace(tzinfo=timezone.utc)
    return date.timestamp()


class DialogListModel(QAbstractListModel):
    def __init__(self, dialogs: Sequence[DialogTarget] = (), parent=None) -> None:
        super().__init__(parent)
        self._dialogs: List[DialogTarget] = []
        self._keys: List[FrozenSet[str]] = []
        self._haystacks: List[str] = []
        self._existing: Set[str] = set()
        self._already: List[bool] = []
        self._checked: Set[int] = set()  # peer ids
        self.set_dialogs(dialogs)

    # ---- loading ----------------------------------------------------------------

    def set_dialogs(self, dialogs: Sequence[DialogTarget]) -> None:
        """Replace the list (newest last message first, Telegram's order
        among equals). Ticks survive for dialogs that are still there and
        still selectable."""
        self.beginResetModel()
        self._dialogs = sorted(dialogs, key=_sort_key, reverse=True)
        self._keys = [dialog_recipient_keys(d) for d in self._dialogs]
        self._haystacks = [f"{d.title}\n{d.username or ''}".casefold() for d in self._dialogs]
        self._recompute_already()
        selectable = {d.peer_id for row, d in enumerate(self._dialogs) if self.is_selectable(row)}
        self._checked &= selectable
        self.endResetModel()

    def set_existing_keys(self, keys: Iterable[str]) -> None:
        """Normalized keys of what the Recipients box already holds."""
        self._existing = set(keys)
        self._recompute_already()
        self._checked -= {d.peer_id for row, d in enumerate(self._dialogs) if self._already[row]}
        if self._dialogs:
            self.dataChanged.emit(self.index(0), self.index(len(self._dialogs) - 1))

    def _recompute_already(self) -> None:
        self._already = [bool(keys & self._existing) for keys in self._keys]

    # ---- per-row facts (also what the proxy filters on) ------------------------

    def dialog(self, row: int) -> DialogTarget:
        return self._dialogs[row]

    def haystack(self, row: int) -> str:
        return self._haystacks[row]

    def is_already_added(self, row: int) -> bool:
        return self._already[row]

    def is_selectable(self, row: int) -> bool:
        return self._dialogs[row].writable and not self._already[row]

    def is_checked(self, row: int) -> bool:
        return self._dialogs[row].peer_id in self._checked

    # ---- Qt model API -------------------------------------------------------------

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802 - Qt override
        return 0 if parent.isValid() else len(self._dialogs)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = index.row()
        dialog = self._dialogs[row]
        if role == Qt.ItemDataRole.DisplayRole:
            # Plain-text summary, for accessibility and keyboard search.
            return f"{dialog.title}, {dialog.type_label}, {dialog.recipient_line}"
        if role == TARGET_ROLE:
            return dialog
        if role == ALREADY_ADDED_ROLE:
            return self._already[row]
        if role == Qt.ItemDataRole.CheckStateRole:
            if not self.is_selectable(row):
                return None  # no check box at all
            return Qt.CheckState.Checked if dialog.peer_id in self._checked else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.ToolTipRole:
            if not dialog.writable:
                return tr(dialog.unavailable_reason_key)
            if self._already[row]:
                return tr("chat_picker.already_added_tooltip")
            return dialog.recipient_line
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        if self.is_selectable(index.row()):
            return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable
        # Unavailable / already listed: shown (with the reason as tooltip),
        # never tickable.
        return Qt.ItemFlag.NoItemFlags

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole) -> bool:  # noqa: N802 - Qt override
        if not index.isValid() or role != Qt.ItemDataRole.CheckStateRole or not self.is_selectable(index.row()):
            return False
        peer_id = self._dialogs[index.row()].peer_id
        if Qt.CheckState(value) == Qt.CheckState.Checked:
            self._checked.add(peer_id)
        else:
            self._checked.discard(peer_id)
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.CheckStateRole])
        return True

    # ---- bulk ticking -------------------------------------------------------------

    def set_rows_checked(self, rows: Iterable[int], checked: bool) -> None:
        """One dataChanged for the whole batch (thousands of rows)."""
        rows = [row for row in rows if self.is_selectable(row)]
        if not rows:
            return
        ids = {self._dialogs[row].peer_id for row in rows}
        if checked:
            self._checked |= ids
        else:
            self._checked -= ids
        self.dataChanged.emit(self.index(min(rows)), self.index(max(rows)), [Qt.ItemDataRole.CheckStateRole])

    def checked_targets(self) -> List[DialogTarget]:
        """Ticked dialogs in list order -- including ones a filter hides,
        since filtering only narrows what's shown."""
        return [d for d in self._dialogs if d.peer_id in self._checked]


class DialogFilterProxy(QSortFilterProxyModel):
    """Type / folder / archive / text filter over DialogListModel. Keeps
    the source order (already newest first) instead of re-sorting."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._category: Optional[DialogCategory] = None
        self._folder_id: Optional[int] = None
        self._show_archived = False
        self._needle = ""

    def _source(self) -> DialogListModel:
        return self.sourceModel()

    def set_category(self, category: Optional[DialogCategory]) -> None:
        self._category = category
        self.invalidateFilter()

    def set_folder(self, folder_id: Optional[int]) -> None:
        self._folder_id = folder_id
        self.invalidateFilter()

    def set_show_archived(self, show: bool) -> None:
        self._show_archived = bool(show)
        self.invalidateFilter()

    def set_search_text(self, text: str) -> None:
        needle = text.strip().casefold()
        self._needle = needle[1:] if needle.startswith("@") else needle
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent) -> bool:  # noqa: N802 - Qt override
        source = self._source()
        dialog = source.dialog(source_row)
        if dialog.archived and not self._show_archived:
            return False
        if self._category is not None and dialog.category is not self._category:
            return False
        if self._folder_id is not None and self._folder_id not in dialog.folder_ids:
            return False
        return not self._needle or self._needle in source.haystack(source_row)

    def visible_source_rows(self) -> List[int]:
        return [self.mapToSource(self.index(row, 0)).row() for row in range(self.rowCount())]


class DialogRowDelegate(QStyledItemDelegate):
    """Check box | initials circle | name over type + @username/ID |
    date over the "already listed" pill. Every colour comes from the
    active tokens at paint time, so a theme switch needs only a repaint."""

    def sizeHint(self, option, index) -> QSize:  # noqa: N802 - Qt override
        # No width of its own: rows always fit the view, never scroll sideways.
        return QSize(0, DIALOG_PICKER_ROW_HEIGHT)

    def paint(self, painter: QPainter, option, index) -> None:
        dialog: Optional[DialogTarget] = index.data(TARGET_ROLE)
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        widget = option.widget
        style = widget.style() if widget is not None else None
        if style is not None:
            # Hover background and the check box, as styled by the QSS; the
            # check box rect matches what editorEvent hit-tests.
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)
        if dialog is None:
            return

        tokens = theme.current_tokens()
        already = bool(index.data(ALREADY_ADDED_ROLE))
        muted = not dialog.writable
        rect = option.rect
        primary = theme.qcolor(tokens.disabled_text if muted else tokens.text_primary)
        secondary = theme.qcolor(tokens.disabled_text if muted else tokens.text_secondary)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Initials circle.
        avatar = QRectF(
            rect.left() + DIALOG_PICKER_CHECK_COL,
            rect.center().y() - AVATAR_SIZE / 2 + 1,
            AVATAR_SIZE,
            AVATAR_SIZE,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        circle = theme.qcolor(tokens.disabled_bg if muted else tokens.accent)
        if not muted:
            circle.setAlphaF(PILL_TINT_ALPHA)
        painter.setBrush(circle)
        painter.drawEllipse(avatar)
        painter.setFont(theme.ui_font(FONT_SIZE_HELPER, theme.FONT_WEIGHT_SEMIBOLD))
        painter.setPen(theme.qcolor(tokens.disabled_text if muted else tokens.accent))
        painter.drawText(avatar, Qt.AlignmentFlag.AlignCenter, dialog_initials(dialog.title))

        left = int(avatar.right()) + SPACE_MD
        right_column = QRect(rect.right() - DIALOG_PICKER_DATE_WIDTH - SPACE_SM, rect.top(), DIALOG_PICKER_DATE_WIDTH, rect.height())
        text_right = right_column.left() - SPACE_SM
        top_half = QRect(left, rect.top() + SPACE_XS, max(0, text_right - left), rect.height() // 2 - SPACE_XS)
        bottom_half = QRect(left, rect.center().y(), max(0, text_right - left), rect.height() // 2 - SPACE_XS)

        # Name, with an archive mark after it for archived dialogs.
        name_font = theme.ui_font(FONT_SIZE_BODY, theme.FONT_WEIGHT_MEDIUM)
        painter.setFont(name_font)
        painter.setPen(primary)
        name_width = top_half.width() - (ICON_SIZE_SM + SPACE_XS if dialog.archived else 0)
        name = QFontMetrics(name_font).elidedText(dialog.title, Qt.TextElideMode.ElideRight, max(0, name_width))
        painter.drawText(top_half, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft, name)
        if dialog.archived:
            name_end = top_half.left() + QFontMetrics(name_font).horizontalAdvance(name) + SPACE_XS
            archive_rect = QRect(name_end, top_half.bottom() - ICON_SIZE_SM - 1, ICON_SIZE_SM, ICON_SIZE_SM)
            icons.themed("archived", "text_muted").paint(painter, archive_rect)

        # Type icon + label, then @username or the ID in monospace.
        icon_rect = QRect(bottom_half.left(), bottom_half.top() + SPACE_XS // 2, ICON_SIZE_SM, ICON_SIZE_SM)
        icons.themed(dialog_icon_name(dialog), "text_muted").paint(painter, icon_rect)
        x = icon_rect.right() + SPACE_XS + 1
        type_font = theme.ui_font(FONT_SIZE_HELPER)
        painter.setFont(type_font)
        painter.setPen(secondary)
        type_text = dialog.type_label
        type_width = QFontMetrics(type_font).horizontalAdvance(type_text)
        line_rect = QRect(x, bottom_half.top(), max(0, bottom_half.right() - x), ICON_SIZE_SM + SPACE_XS)
        painter.drawText(line_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, type_text)
        x += type_width + SPACE_SM
        mono = theme.mono_font(FONT_SIZE_HELPER)
        painter.setFont(mono)
        painter.setPen(theme.qcolor(tokens.disabled_text if muted else tokens.text_muted))
        id_rect = QRect(x, line_rect.top(), max(0, bottom_half.right() - x), line_rect.height())
        address = f"@{dialog.username}" if dialog.username else str(dialog.peer_id)
        painter.drawText(
            id_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            QFontMetrics(mono).elidedText(address, Qt.TextElideMode.ElideRight, id_rect.width()),
        )

        # Date (secondary), and the "already listed" pill under it.
        painter.setFont(theme.ui_font(FONT_SIZE_CAPTION))
        painter.setPen(theme.qcolor(tokens.text_muted))
        date_rect = QRect(right_column.left(), top_half.top(), right_column.width(), top_half.height())
        painter.drawText(date_rect, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight, format_dialog_date(dialog.last_message_date))
        if already:
            label = tr("chat_picker.already_added")
            pill_font = theme.ui_font(FONT_SIZE_CAPTION, theme.FONT_WEIGHT_MEDIUM)
            metrics = QFontMetrics(pill_font)
            pill_w = min(right_column.width(), metrics.horizontalAdvance(label) + 2 * SPACE_SM)
            pill_h = metrics.height() + SPACE_XS // 2
            pill = QRectF(right_column.right() - pill_w, bottom_half.top() + 1, pill_w, pill_h)
            tint = theme.qcolor(tokens.success)
            tint.setAlphaF(PILL_TINT_ALPHA)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(tint)
            painter.drawRoundedRect(pill, pill_h / 2, pill_h / 2)
            painter.setFont(pill_font)
            painter.setPen(theme.qcolor(tokens.success_ink))
            painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, metrics.elidedText(label, Qt.TextElideMode.ElideRight, int(pill_w) - SPACE_XS))
        painter.restore()

    def editorEvent(self, event, model, option, index) -> bool:  # noqa: N802 - Qt override
        """A click anywhere on a tickable row toggles it, not just on the
        check box; Space keeps working through the base class."""
        if not index.flags() & Qt.ItemFlag.ItemIsUserCheckable:
            return False
        kind = event.type()
        if kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick):
            return event.button() == Qt.MouseButton.LeftButton
        if kind == QEvent.Type.MouseButtonRelease:
            if event.button() != Qt.MouseButton.LeftButton or not option.rect.contains(event.position().toPoint()):
                return False
            state = index.data(Qt.ItemDataRole.CheckStateRole)
            new_state = Qt.CheckState.Unchecked if Qt.CheckState(state) == Qt.CheckState.Checked else Qt.CheckState.Checked
            return model.setData(index, new_state, Qt.ItemDataRole.CheckStateRole)
        return super().editorEvent(event, model, option, index)


def selection_breakdown(targets: Sequence[DialogTarget]) -> Dict[str, int]:
    counts = {"people": 0, "bots": 0, "chats": 0}
    for target in targets:
        if target.category is DialogCategory.PEOPLE:
            counts["people"] += 1
        elif target.category is DialogCategory.BOTS:
            counts["bots"] += 1
        else:
            counts["chats"] += 1
    return counts
