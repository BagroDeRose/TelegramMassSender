"""Shared "nothing here yet" block: a short bold title plus one muted
explanatory line, centered and modestly padded -- used wherever a page or
section has no content yet (Recipients, Attachments, Accounts, Results,
Saved Reports), instead of each spot inventing its own single mashed-
together label with no visual hierarchy.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from app.ui.theme import SPACE_XS, SPACE_XXL


def build_empty_state(title: str, body: str, parent: Optional[QWidget] = None) -> QWidget:
    container = QWidget(parent)
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, SPACE_XXL, 0, SPACE_XXL)
    layout.setSpacing(SPACE_XS)

    title_label = QLabel(title, container)
    title_label.setObjectName("emptyStateTitle")
    title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(title_label)

    body_label = QLabel(body, container)
    body_label.setObjectName("emptyStateBody")
    body_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    body_label.setWordWrap(True)
    layout.addWidget(body_label)

    return container
