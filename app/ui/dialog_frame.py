"""One structure for every dialog: an optional title, the content, and a
footer bar with the buttons -- secondary actions first, the primary action
last (rightmost). Message boxes get their themed icons from the
application style (app.ui.theme._ThemedStyle).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.ui.theme import SPACE_LG, SPACE_MD, SPACE_SM, SPACE_XL


@dataclass
class DialogFrame:
    title: Optional[QLabel]
    content: QVBoxLayout
    footer: QFrame
    footer_left: QHBoxLayout
    footer_buttons: QHBoxLayout

    def add_button(self, button: QPushButton, variant: str = "secondary") -> QPushButton:
        button.setProperty("variant", variant)
        if variant == "primary":
            button.setDefault(True)
        self.footer_buttons.addWidget(button)
        return button


def build_dialog_frame(dialog: QDialog, title: Optional[str] = None) -> DialogFrame:
    root = QVBoxLayout(dialog)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(0)

    body = QWidget(dialog)
    content = QVBoxLayout(body)
    content.setContentsMargins(SPACE_XL, SPACE_XL, SPACE_XL, SPACE_LG)
    content.setSpacing(SPACE_MD)
    title_label = None
    if title is not None:
        title_label = QLabel(title, body)
        title_label.setObjectName("dialogTitle")
        content.addWidget(title_label)
    root.addWidget(body, 1)

    footer = QFrame(dialog)
    footer.setObjectName("dialogFooter")
    footer_row = QHBoxLayout(footer)
    footer_row.setContentsMargins(SPACE_XL, SPACE_MD, SPACE_XL, SPACE_MD)
    footer_row.setSpacing(SPACE_SM)
    left = QHBoxLayout()
    left.setSpacing(SPACE_SM)
    footer_row.addLayout(left)
    footer_row.addStretch(1)
    buttons = QHBoxLayout()
    buttons.setSpacing(SPACE_SM)
    footer_row.addLayout(buttons)
    root.addWidget(footer)
    return DialogFrame(title_label, content, footer, left, buttons)

