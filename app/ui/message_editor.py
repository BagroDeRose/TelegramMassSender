"""Rich-text message editor with a Telegram-formatting toolbar.

Bold/Italic/Underline/Strikethrough/links are backed by native Qt rich-text
character formatting. Spoiler/Code/Code block have no native Qt equivalent,
so they are tracked via custom QTextCharFormat properties (PROP_SPOILER /
PROP_CODE / PROP_PRE) with a monospace/background visual cue in the editor.

extract_message_content() converts the resulting QTextDocument into the
(plain_text, entities) pair Telethon expects for
client.send_message(..., formatting_entities=entities). It is written by
hand rather than round-tripped through telethon.extensions.html because
the bundled HTML parser (as of the pinned Telethon version) has no
<spoiler> tag support -- but it deliberately mirrors that parser's
UTF-16-surrogate-aware offset counting, since Telegram message entity
offsets are UTF-16 code units, not Python codepoints, and get this wrong
for any text containing astral-plane characters (many emoji included).
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QKeySequence, QShortcut, QTextCharFormat, QTextCursor, QTextDocument, QTextFormat
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QMenu,
    QMessageBox,
    QTextEdit,
    QToolButton,
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
from app.ui import icons, theme
from app.ui.theme import (
    EDITOR_COMPACT_HEIGHT,
    FONT_FAMILY_MONO,
    FONT_FAMILY_MONO_FALLBACK,
    ICON_SIZE,
    SPACE_XS,
    icon_qsize,
)

PROP_SPOILER = QTextFormat.Property.UserProperty + 1
PROP_CODE = QTextFormat.Property.UserProperty + 2
PROP_PRE = QTextFormat.Property.UserProperty + 3

_MONO_FAMILIES = [FONT_FAMILY_MONO, FONT_FAMILY_MONO_FALLBACK]

_BOOLEAN_KINDS = ("bold", "italic", "underline", "strike", "code", "pre", "spoiler")

_ENTITY_CLASSES = {
    "bold": MessageEntityBold,
    "italic": MessageEntityItalic,
    "underline": MessageEntityUnderline,
    "strike": MessageEntityStrike,
    "code": MessageEntityCode,
}

_EMOJI_LIST = [
    "😀", "😂", "😍", "👍", "👎", "🎉", "🔥", "❤️", "🙏", "😊",
    "😢", "😎", "🤔", "👏", "🚀", "✅", "⚠️", "📌", "📎", "💬",
]

_PARAGRAPH_SEPARATOR = chr(0x2029)


def _active_kinds(fmt: QTextCharFormat) -> Dict[str, bool]:
    return {
        "bold": fmt.fontWeight() >= QFont.Weight.Bold.value,
        "italic": fmt.fontItalic(),
        # Links are rendered with an underline purely as a visual affordance
        # (both when freshly inserted and when an editor is repopulated by
        # apply_content_to_editor) -- Telegram itself renders TextUrl
        # entities underlined automatically, so that decoration must never
        # be picked up as an independent MessageEntityUnderline here, or
        # every link would silently gain a spurious duplicate entity.
        "underline": fmt.fontUnderline() and not fmt.isAnchor(),
        "strike": fmt.fontStrikeOut(),
        "code": bool(fmt.property(PROP_CODE)),
        "pre": bool(fmt.property(PROP_PRE)),
        "spoiler": bool(fmt.property(PROP_SPOILER)),
    }


def extract_message_content(document: QTextDocument) -> Tuple[str, List[TypeMessageEntity]]:
    surrogate_text = ""
    entities: List[TypeMessageEntity] = []
    open_runs: Dict[str, int] = {}
    open_link: Optional[Tuple[int, str]] = None

    def close_kind(kind: str, end: int) -> None:
        start = open_runs.pop(kind, None)
        if start is None or end <= start:
            return
        if kind == "pre":
            entities.append(MessageEntityPre(offset=start, length=end - start, language=""))
        elif kind == "spoiler":
            entities.append(MessageEntitySpoiler(offset=start, length=end - start))
        else:
            entities.append(_ENTITY_CLASSES[kind](offset=start, length=end - start))

    def close_link(end: int) -> None:
        nonlocal open_link
        if open_link is None:
            return
        start, href = open_link
        if end > start:
            entities.append(MessageEntityTextUrl(offset=start, length=end - start, url=href))
        open_link = None

    block = document.begin()
    first_block = True
    while block.isValid():
        if not first_block:
            surrogate_text += "\n"
        first_block = False

        it = block.begin()
        while not it.atEnd():
            fragment = it.fragment()
            if fragment.isValid():
                fmt = fragment.charFormat()
                frag_text = fragment.text().replace(_PARAGRAPH_SEPARATOR, "\n")
                kinds = _active_kinds(fmt)
                cur_start = len(surrogate_text)

                for kind in _BOOLEAN_KINDS:
                    active = kinds[kind]
                    is_open = kind in open_runs
                    if active and not is_open:
                        open_runs[kind] = cur_start
                    elif not active and is_open:
                        close_kind(kind, cur_start)

                href = fmt.anchorHref() if fmt.isAnchor() else ""
                if href:
                    if open_link is None:
                        open_link = (cur_start, href)
                    elif open_link[1] != href:
                        close_link(cur_start)
                        open_link = (cur_start, href)
                else:
                    close_link(cur_start)

                surrogate_text += add_surrogate(frag_text)
            it += 1
        block = block.next()

    end = len(surrogate_text)
    for kind in list(open_runs.keys()):
        close_kind(kind, end)
    close_link(end)

    entities.sort(key=lambda e: e.offset)
    return del_surrogate(surrogate_text), entities


_ENTITY_TO_KIND = {
    MessageEntityBold: "bold",
    MessageEntityItalic: "italic",
    MessageEntityUnderline: "underline",
    MessageEntityStrike: "strike",
    MessageEntityCode: "code",
    MessageEntityPre: "pre",
    MessageEntitySpoiler: "spoiler",
}


def _format_for_kind(kind: str) -> QTextCharFormat:
    fmt = QTextCharFormat()
    if kind == "bold":
        fmt.setFontWeight(QFont.Weight.Bold.value)
    elif kind == "italic":
        fmt.setFontItalic(True)
    elif kind == "underline":
        fmt.setFontUnderline(True)
    elif kind == "strike":
        fmt.setFontStrikeOut(True)
    elif kind == "code":
        fmt.setProperty(PROP_CODE, True)
        fmt.setFontFamilies(_MONO_FAMILIES)
    elif kind == "pre":
        fmt.setProperty(PROP_PRE, True)
        fmt.setFontFamilies(_MONO_FAMILIES)
    elif kind == "spoiler":
        fmt.setProperty(PROP_SPOILER, True)
        fmt.setBackground(QColor(theme.spoiler_background()))
    return fmt


def recolor_document(text_edit: QTextEdit) -> None:
    """Re-apply the active theme's spoiler background and link colour to
    text that was formatted under the previous theme (QTextCharFormat
    colours are baked in when applied; QSS can't reach them)."""
    document = text_edit.document()
    spoiler = QColor(theme.spoiler_background())
    link = QColor(theme.link_color())
    cursor = QTextCursor(document)
    cursor.beginEditBlock()
    block = document.begin()
    while block.isValid():
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            fmt = fragment.charFormat()
            update = QTextCharFormat()
            changed = False
            if fmt.property(PROP_SPOILER):
                update.setBackground(spoiler)
                changed = True
            if fmt.isAnchor():
                update.setForeground(link)
                changed = True
            if changed:
                cursor.setPosition(fragment.position())
                cursor.setPosition(fragment.position() + fragment.length(), QTextCursor.MoveMode.KeepAnchor)
                cursor.mergeCharFormat(update)
            iterator += 1
        block = block.next()
    cursor.endEditBlock()


def apply_content_to_editor(text_edit: QTextEdit, text: str, entities: List[TypeMessageEntity]) -> None:
    """Inverse of extract_message_content(): repopulate a QTextEdit from a
    previously-extracted (text, entities) pair, preserving formatting.

    Entity offsets/lengths are UTF-16 code units -- exactly the unit
    QTextCursor positions already use internally (QString is UTF-16), so
    they apply directly with no extra conversion. This is what lets the
    floating editor dialog reopen with formatting intact instead of only
    carrying plain text across.
    """
    text_edit.setPlainText(text)
    cursor = text_edit.textCursor()
    for entity in entities:
        cursor.setPosition(entity.offset)
        cursor.setPosition(entity.offset + entity.length, QTextCursor.MoveMode.KeepAnchor)
        if isinstance(entity, MessageEntityTextUrl):
            fmt = QTextCharFormat()
            fmt.setAnchor(True)
            fmt.setAnchorHref(entity.url)
            fmt.setForeground(QColor(theme.link_color()))
            fmt.setFontUnderline(True)
        else:
            kind = _ENTITY_TO_KIND.get(type(entity))
            if kind is None:
                continue
            fmt = _format_for_kind(kind)
        cursor.mergeCharFormat(fmt)

    reset_cursor = text_edit.textCursor()
    reset_cursor.movePosition(QTextCursor.MoveOperation.Start)
    text_edit.setTextCursor(reset_cursor)


class MessageEditorWidget(QWidget):
    def __init__(self, parent: Optional[QWidget] = None, compact: bool = False) -> None:
        super().__init__(parent)
        self._toggle_buttons: Dict[str, QToolButton] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(SPACE_XS)
        toolbar.addWidget(self._make_toggle_button("bold", "bold", "message_editor.bold_tooltip", self._toggle_bold))
        toolbar.addWidget(self._make_toggle_button("italic", "italic", "message_editor.italic_tooltip", self._toggle_italic))
        toolbar.addWidget(
            self._make_toggle_button("underline", "underline", "message_editor.underline_tooltip", self._toggle_underline)
        )
        toolbar.addWidget(
            self._make_toggle_button("strike", "strikethrough", "message_editor.strike_tooltip", self._toggle_strike)
        )
        toolbar.addWidget(self._make_toggle_button("spoiler", "spoiler", "message_editor.spoiler_tooltip", self._toggle_spoiler))
        toolbar.addWidget(self._make_toggle_button("code", "code", "message_editor.code_tooltip", self._toggle_code))
        toolbar.addWidget(self._make_toggle_button("pre", "code_block", "message_editor.pre_tooltip", self._toggle_pre))
        self._link_button = self._make_button("link", "message_editor.link_tooltip", self._insert_link)
        toolbar.addWidget(self._link_button)
        self._emoji_button = self._make_emoji_button()
        toolbar.addWidget(self._emoji_button)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        self._text_edit = QTextEdit(self)
        self._text_edit.setPlaceholderText(tr("message_editor.placeholder"))
        self._text_edit.setAcceptRichText(False)
        if compact:
            self._text_edit.setFixedHeight(EDITOR_COMPACT_HEIGHT)
        layout.addWidget(self._text_edit)

        self._text_edit.cursorPositionChanged.connect(self._sync_toolbar_state)
        self._text_edit.selectionChanged.connect(self._sync_toolbar_state)
        theme.on_theme_changed(self, lambda *_args: recolor_document(self._text_edit))

        QShortcut(QKeySequence("Ctrl+B"), self._text_edit, activated=self._toggle_bold)
        QShortcut(QKeySequence("Ctrl+I"), self._text_edit, activated=self._toggle_italic)
        QShortcut(QKeySequence("Ctrl+U"), self._text_edit, activated=self._toggle_underline)

    def _make_button(self, icon_name: str, tooltip_key: str, handler) -> QToolButton:
        button = QToolButton(self)
        button.setObjectName("toolbarButton")
        button.setIcon(icons.themed(icon_name, "text_secondary", checked_role="accent"))
        button.setIconSize(icon_qsize(ICON_SIZE))
        button.setToolTip(tr(tooltip_key))
        # Icon-only: the tooltip text is also the accessible name.
        button.setAccessibleName(tr(tooltip_key))
        button.setProperty("tooltipKey", tooltip_key)
        button.clicked.connect(handler)
        return button

    def _make_toggle_button(self, kind: str, icon_name: str, tooltip_key: str, handler) -> QToolButton:
        button = self._make_button(icon_name, tooltip_key, handler)
        button.setCheckable(True)
        self._toggle_buttons[kind] = button
        return button

    def _make_emoji_button(self) -> QToolButton:
        button = QToolButton(self)
        button.setObjectName("toolbarButton")
        button.setIcon(icons.themed("emoji"))
        button.setIconSize(icon_qsize(ICON_SIZE))
        button.setAccessibleName(tr("message_editor.emoji_tooltip"))
        button.setToolTip(tr("message_editor.emoji_tooltip"))
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(button)
        for emoji in _EMOJI_LIST:
            action = menu.addAction(emoji)
            action.triggered.connect(lambda checked=False, e=emoji: self._insert_emoji(e))
        button.setMenu(menu)
        return button

    def retranslate_ui(self) -> None:
        self._text_edit.setPlaceholderText(tr("message_editor.placeholder"))
        for button in list(self._toggle_buttons.values()) + [self._link_button]:
            tooltip_key = button.property("tooltipKey")
            if tooltip_key:
                button.setToolTip(tr(tooltip_key))
        self._emoji_button.setToolTip(tr("message_editor.emoji_tooltip"))

    def _current_format(self) -> QTextCharFormat:
        return self._text_edit.textCursor().charFormat()

    def _sync_toolbar_state(self) -> None:
        kinds = _active_kinds(self._current_format())
        for kind, button in self._toggle_buttons.items():
            button.blockSignals(True)
            button.setChecked(kinds.get(kind, False))
            button.blockSignals(False)

    def _toggle_bold(self) -> None:
        fmt = QTextCharFormat()
        is_bold = self._current_format().fontWeight() >= QFont.Weight.Bold.value
        fmt.setFontWeight(
            QFont.Weight.Normal.value if is_bold else QFont.Weight.Bold.value
        )
        self._text_edit.mergeCurrentCharFormat(fmt)
        self._sync_toolbar_state()

    def _toggle_italic(self) -> None:
        fmt = QTextCharFormat()
        fmt.setFontItalic(not self._current_format().fontItalic())
        self._text_edit.mergeCurrentCharFormat(fmt)
        self._sync_toolbar_state()

    def _toggle_underline(self) -> None:
        fmt = QTextCharFormat()
        fmt.setFontUnderline(not self._current_format().fontUnderline())
        self._text_edit.mergeCurrentCharFormat(fmt)
        self._sync_toolbar_state()

    def _toggle_strike(self) -> None:
        fmt = QTextCharFormat()
        fmt.setFontStrikeOut(not self._current_format().fontStrikeOut())
        self._text_edit.mergeCurrentCharFormat(fmt)
        self._sync_toolbar_state()

    def _toggle_spoiler(self) -> None:
        fmt = QTextCharFormat()
        active = not bool(self._current_format().property(PROP_SPOILER))
        fmt.setProperty(PROP_SPOILER, active)
        fmt.setBackground(QColor(theme.spoiler_background()) if active else QColor(Qt.GlobalColor.transparent))
        self._text_edit.mergeCurrentCharFormat(fmt)
        self._sync_toolbar_state()

    def _toggle_code(self) -> None:
        fmt = QTextCharFormat()
        active = not bool(self._current_format().property(PROP_CODE))
        fmt.setProperty(PROP_CODE, active)
        fmt.setFontFamilies(_MONO_FAMILIES if active else [self._text_edit.document().defaultFont().family()])
        self._text_edit.mergeCurrentCharFormat(fmt)
        self._sync_toolbar_state()

    def _toggle_pre(self) -> None:
        fmt = QTextCharFormat()
        active = not bool(self._current_format().property(PROP_PRE))
        fmt.setProperty(PROP_PRE, active)
        fmt.setFontFamilies(_MONO_FAMILIES if active else [self._text_edit.document().defaultFont().family()])
        self._text_edit.mergeCurrentCharFormat(fmt)
        self._sync_toolbar_state()

    def _insert_link(self) -> None:
        cursor = self._text_edit.textCursor()
        if not cursor.hasSelection():
            QMessageBox.information(
                self, tr("message_editor.link_dialog_title"), tr("message_editor.link_no_selection")
            )
            return
        url, ok = QInputDialog.getText(self, tr("message_editor.add_link_dialog_title"), tr("message_editor.url_label"))
        url = url.strip()
        if not ok or not url:
            return
        fmt = QTextCharFormat()
        fmt.setAnchor(True)
        fmt.setAnchorHref(url)
        fmt.setForeground(QColor(theme.link_color()))
        fmt.setFontUnderline(True)
        self._text_edit.mergeCurrentCharFormat(fmt)

    def _insert_emoji(self, emoji: str) -> None:
        self._text_edit.insertPlainText(emoji)
        self._text_edit.setFocus()

    def get_content(self) -> Tuple[str, List[TypeMessageEntity]]:
        return extract_message_content(self._text_edit.document())

    def set_content(self, text: str, entities: List[TypeMessageEntity]) -> None:
        apply_content_to_editor(self._text_edit, text, entities)
        self._sync_toolbar_state()

    def get_plain_text(self) -> str:
        return self._text_edit.toPlainText()

    def character_count(self) -> int:
        return len(self._text_edit.toPlainText())

    def is_empty(self) -> bool:
        return not self._text_edit.toPlainText().strip()

    def clear(self) -> None:
        self._text_edit.clear()

    @property
    def text_edit(self) -> QTextEdit:
        return self._text_edit
