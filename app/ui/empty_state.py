"""Shared "nothing here yet" block: an optional line icon, a short title,
one sentence, and optionally one action button -- used wherever a page or
section has no content yet, so every empty state reads the same way.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from app.ui import icons, theme
from app.ui.theme import ICON_SIZE_EMPTY, SPACE_SM, SPACE_XL, SPACE_XS


def build_empty_state(
    title: str,
    body: str,
    parent: Optional[QWidget] = None,
    icon_name: Optional[str] = None,
    action_text: Optional[str] = None,
) -> QWidget:
    container = QWidget(parent)
    container.setObjectName("emptyState")
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, SPACE_XL, 0, SPACE_XL)
    layout.setSpacing(SPACE_XS)
    layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

    if icon_name:
        icon_label = QLabel(container)
        icon_label.setObjectName("emptyStateIcon")
        icon_label.setProperty("iconName", icon_name)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _paint_icon(icon_label)
        theme.on_theme_changed(icon_label, lambda *_a, label=icon_label: _paint_icon(label))
        layout.addWidget(icon_label)
        layout.addSpacing(SPACE_SM)

    title_label = QLabel(title, container)
    title_label.setObjectName("emptyStateTitle")
    title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(title_label)

    body_label = QLabel(body, container)
    body_label.setObjectName("emptyStateBody")
    body_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    body_label.setWordWrap(True)
    layout.addWidget(body_label)

    if action_text:
        layout.addSpacing(SPACE_SM)
        button = QPushButton(action_text, container)
        button.setObjectName("emptyStateAction")
        button.setProperty("variant", "primary")
        layout.addWidget(button, 0, Qt.AlignmentFlag.AlignHCenter)

    return container


def _paint_icon(label: QLabel) -> None:
    try:
        scale = label.devicePixelRatioF()
        label.setPixmap(icons.themed_pixmap(label.property("iconName"), "text_muted", ICON_SIZE_EMPTY, scale))
    except RuntimeError:
        pass  # label already deleted


def empty_state_action(container: QWidget) -> Optional[QPushButton]:
    return container.findChild(QPushButton, "emptyStateAction")


def retranslate_empty_state(container: QWidget, title: str, body: str, action_text: Optional[str] = None) -> None:
    """Re-set an already-built empty state's text after a language switch."""
    title_label = container.findChild(QLabel, "emptyStateTitle")
    if title_label is not None:
        title_label.setText(title)
    body_label = container.findChild(QLabel, "emptyStateBody")
    if body_label is not None:
        body_label.setText(body)
    button = empty_state_action(container)
    if button is not None and action_text is not None:
        button.setText(action_text)
