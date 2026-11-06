"""How the message goes out, shown where it is written (the Message card,
the editor, the wizard's message step):

- a calm notice when the text is too long for a caption, so text and media
  go as separate messages, with the order choice for that case;
- a hint when {name} could push the text over the caption limit;
- "Link preview": off by default; a switch for one link, a list for
  several; above/below the text and image size. Unavailable (with the
  reason) when the text goes as a caption.

It reads the same send plan the sender executes
(app.telegram.media_sender.build_media_send_plan), so what it says is
what happens.
"""
from __future__ import annotations

from typing import List, Optional, Sequence

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget
from telethon.tl.types import TypeMessageEntity

from app.i18n import LANGUAGE_RU, get_language, tr
from app.telegram.media_sender import Attachment, AttachmentCategory, MediaSendPlan, build_media_send_plan
from app.telegram.message_options import (
    LinkPreviewOptions,
    MediaTextOrder,
    MessageLink,
    MessageOptions,
    PreviewSize,
    find_links,
    utf16_len,
)
from app.telegram.template import PLACEHOLDER
from app.ui import icons
from app.ui.layouts import FlowLayout, WrappingLabel
from app.ui.theme import ICON_SIZE, SPACE_SM, SPACE_XS

# Telegram's longest first name; a chat's title can be longer, but a
# person's name is what {name} usually becomes.
_LONGEST_NAME = 64


def format_count(value: int) -> str:
    """1487 -> "1 487" (Russian, non-breaking space) / "1,487" (English)."""
    grouped = f"{value:,}"
    return grouped.replace(",", " ") if get_language() == LANGUAGE_RU else grouped


class MessageOptionsWidget(QWidget):
    options_changed = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._options = MessageOptions()
        self._links: List[MessageLink] = []
        self._plan: Optional[MediaSendPlan] = None
        self._has_photo = True
        self._large_media_supported: Optional[bool] = None
        self._updating = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_SM)

        # ---- the "two messages" notice + order ----
        self._notice = QFrame(self)
        self._notice.setObjectName("sendNotice")
        notice_layout = QVBoxLayout(self._notice)
        notice_layout.setContentsMargins(SPACE_SM, SPACE_SM, SPACE_SM, SPACE_SM)
        notice_layout.setSpacing(SPACE_XS)
        notice_row = QHBoxLayout()
        notice_row.setSpacing(SPACE_SM)
        self._notice_icon = QLabel(self._notice)
        self._notice_icon.setPixmap(icons.themed_pixmap("warning", "warning", ICON_SIZE, self.devicePixelRatioF()))
        notice_row.addWidget(self._notice_icon)
        self._notice_label = WrappingLabel("", self._notice)
        self._notice_label.setObjectName("sendNoticeText")
        notice_row.addWidget(self._notice_label, 1)
        notice_layout.addLayout(notice_row)
        order_row = FlowLayout(spacing=SPACE_SM)
        self._order_label = QLabel(self._notice)
        self._order_label.setObjectName("sendNoticeText")
        order_row.addWidget(self._order_label)
        self.order_combo = QComboBox(self._notice)
        self.order_combo.currentIndexChanged.connect(self._on_controls_changed)
        order_row.addWidget(self.order_combo)
        notice_layout.addLayout(order_row)
        layout.addWidget(self._notice)

        self._name_hint = WrappingLabel("", self)
        self._name_hint.setObjectName("helperText")
        layout.addWidget(self._name_hint)

        # ---- link preview ----
        self._link_box = QWidget(self)
        link_layout = QVBoxLayout(self._link_box)
        link_layout.setContentsMargins(0, 0, 0, 0)
        link_layout.setSpacing(SPACE_XS)
        self._link_title = QLabel(self._link_box)
        self._link_title.setObjectName("summaryKey")
        link_layout.addWidget(self._link_title)
        self.preview_check = QCheckBox(self._link_box)
        self.preview_check.toggled.connect(self._on_controls_changed)
        link_layout.addWidget(self.preview_check)
        self.link_combo = QComboBox(self._link_box)
        self.link_combo.currentIndexChanged.connect(self._on_controls_changed)
        link_layout.addWidget(self.link_combo)
        # Label + combo pairs wrap as a unit, never a label alone on a line.
        details = FlowLayout(spacing=SPACE_SM)
        position_pair, self._position_label, self.position_combo = self._labelled_combo(self._link_box)
        size_pair, self._size_label, self.size_combo = self._labelled_combo(self._link_box)
        details.addWidget(position_pair)
        details.addWidget(size_pair)
        link_layout.addLayout(details)
        self._details_widgets = (position_pair, size_pair)
        self._caption_note = WrappingLabel("", self._link_box)
        self._caption_note.setObjectName("helperText")
        link_layout.addWidget(self._caption_note)
        layout.addWidget(self._link_box)

        self.retranslate_ui()
        self._refresh()

    # ---- public API -----------------------------------------------------------------

    def options(self) -> MessageOptions:
        return self._options

    def set_options(self, options: MessageOptions) -> None:
        self._options = options
        self._refresh()

    def plan(self) -> Optional[MediaSendPlan]:
        return self._plan

    def set_context(
        self,
        template_text: str,
        template_entities: Sequence[TypeMessageEntity],
        attachments: Sequence[Attachment],
        caption_limit: int,
        example_text: Optional[str] = None,
        example_entities: Optional[Sequence[TypeMessageEntity]] = None,
    ) -> None:
        """The message as written (links are found there) and, for the
        length, the text with the example name in place of {name}."""
        self._template_text = template_text
        self._links = find_links(template_text, template_entities)
        text = template_text if example_text is None else example_text
        entities = list(template_entities if example_entities is None else example_entities)
        attachments = list(attachments)
        self._has_photo = any(a.category == AttachmentCategory.ALBUM_ELIGIBLE for a in attachments)
        self._plan = build_media_send_plan(
            attachments, text, entities, options=self._options, caption_limit=caption_limit, validate=False
        )
        self._name_overflow = False
        if attachments and PLACEHOLDER in template_text and not self._plan.caption_overflow:
            placeholders = template_text.count(PLACEHOLDER)
            worst = utf16_len(template_text) - placeholders * len(PLACEHOLDER) + placeholders * _LONGEST_NAME
            self._name_overflow = worst > caption_limit
        self._refresh()

    def set_large_media_supported(self, supported: Optional[bool]) -> None:
        """From the chosen page's preview: False when it has no large
        image (the size choice then does nothing), None when unknown."""
        self._large_media_supported = supported
        self._refresh()

    def notice_text(self) -> str:
        return self._notice_label.text() if not self._notice.isHidden() else ""

    def retranslate_ui(self) -> None:
        self._updating = True
        self._order_label.setText(tr("message_options.order_label"))
        self._fill_combo(
            self.order_combo,
            [
                (tr("message_options.order_text_first"), MediaTextOrder.TEXT_FIRST),
                (tr("message_options.order_media_first"), MediaTextOrder.MEDIA_FIRST),
            ],
        )
        self._link_title.setText(tr("message_options.link_title"))
        self._link_box.setToolTip(tr("message_options.link_tooltip"))
        self.preview_check.setText(tr("message_options.link_show_one"))
        self._position_label.setText(tr("message_options.position_label"))
        self._fill_combo(
            self.position_combo,
            [(tr("message_options.position_below"), False), (tr("message_options.position_above"), True)],
        )
        self._size_label.setText(tr("message_options.size_label"))
        self._fill_combo(
            self.size_combo,
            [
                (tr("message_options.size_auto"), PreviewSize.AUTO),
                (tr("message_options.size_large"), PreviewSize.LARGE),
                (tr("message_options.size_small"), PreviewSize.SMALL),
            ],
        )
        self._caption_note.setText(tr("message_options.caption_note"))
        self._updating = False
        self._refresh()

    # ---- internals ----------------------------------------------------------------------

    def _labelled_combo(self, parent: QWidget):
        pair = QWidget(parent)
        row = QHBoxLayout(pair)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(SPACE_XS)
        label = QLabel(pair)
        label.setObjectName("helperText")
        row.addWidget(label)
        combo = QComboBox(pair)
        combo.currentIndexChanged.connect(self._on_controls_changed)
        row.addWidget(combo)
        return pair, label, combo

    @staticmethod
    def _fill_combo(combo: QComboBox, items) -> None:
        current = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        for label, value in items:
            combo.addItem(label, value)
        index = combo.findData(current)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.blockSignals(False)

    def _refresh(self) -> None:
        self._updating = True
        plan = self._plan
        options = self._options

        overflow = bool(plan and plan.caption_overflow)
        self._notice.setVisible(overflow)
        if overflow:
            count = len(plan.messages())
            kind = "photo" if self._has_photo else "file"
            key = f"message_options.overflow_{kind}_{'two' if count == 2 else 'many'}"
            self._notice_label.setText(
                tr(key, length=format_count(plan.text_length), limit=format_count(plan.caption_limit), count=count)
            )
        index = self.order_combo.findData(options.order)
        self.order_combo.setCurrentIndex(max(0, index))

        name_overflow = bool(getattr(self, "_name_overflow", False))
        self._name_hint.setVisible(name_overflow)
        if name_overflow and plan is not None:
            self._name_hint.setText(
                tr(
                    "message_options.name_may_overflow",
                    length=format_count(plan.text_length),
                    limit=format_count(plan.caption_limit),
                )
            )

        links = self._links
        self._link_box.setVisible(bool(links))
        possible = bool(plan and plan.link_preview_possible)
        self.preview_check.setVisible(len(links) == 1)
        self.link_combo.setVisible(len(links) > 1)
        if len(links) == 1:
            self.preview_check.setChecked(options.link_preview.url == links[0].url)
        self.link_combo.blockSignals(True)
        self.link_combo.clear()
        self.link_combo.addItem(tr("message_options.link_none"), None)
        for link in links:
            label = link.domain if link.label in (link.url, "") or link.label.rstrip("/") in link.url else link.label
            text = tr("message_options.link_item", label=label, domain=link.domain) if label != link.domain else link.url
            self.link_combo.addItem(text, link.url)
        selected = self.link_combo.findData(options.link_preview.url) if options.link_preview.enabled else 0
        self.link_combo.setCurrentIndex(max(0, selected))
        self.link_combo.blockSignals(False)

        for widget in (self.preview_check, self.link_combo):
            widget.setEnabled(possible)
        enabled = possible and self._chosen_url() is not None
        for widget in self._details_widgets:
            widget.setVisible(enabled)
        self.position_combo.setCurrentIndex(max(0, self.position_combo.findData(options.link_preview.above_text)))
        self.size_combo.setCurrentIndex(max(0, self.size_combo.findData(options.link_preview.size)))
        size_supported = self._large_media_supported is not False
        self.size_combo.setEnabled(size_supported)
        self.size_combo.setToolTip("" if size_supported else tr("message_options.size_unavailable_tooltip"))
        self._caption_note.setVisible(bool(links) and not possible and plan is not None and bool(plan.groups))
        self._updating = False

    def _chosen_url(self) -> Optional[str]:
        if not self._links:
            return None
        if len(self._links) == 1:
            return self._links[0].url if self.preview_check.isChecked() else None
        return self.link_combo.currentData()

    def _on_controls_changed(self, *_args) -> None:
        if self._updating:
            return
        url = self._chosen_url()
        self._options = MessageOptions(
            order=self.order_combo.currentData() or MediaTextOrder.TEXT_FIRST,
            link_preview=LinkPreviewOptions(
                url=url,
                above_text=bool(self.position_combo.currentData()) if url else False,
                size=(self.size_combo.currentData() or PreviewSize.AUTO) if url else PreviewSize.AUTO,
            ),
        )
        self._refresh()
        self.options_changed.emit()
