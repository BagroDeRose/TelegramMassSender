"""Small statistic tile used on the Results page (Total/Success/Failed/
Skipped) -- a compact QFrame with a big number and a muted caption, styled
entirely through the #statCard/#statValue/#statLabel rules in
app.ui.theme so it never carries its own hardcoded colors.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from app.ui.theme import SPACE_LG, SPACE_MD, SPACE_XS


class StatCard(QFrame):
    def __init__(self, label: str, variant: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("statCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE_LG, SPACE_MD, SPACE_LG, SPACE_MD)
        layout.setSpacing(SPACE_XS)

        self._value_label = QLabel("0", self)
        self._value_label.setObjectName("statValue")
        if variant:
            self._value_label.setProperty("variant", variant)
        layout.addWidget(self._value_label)

        caption = QLabel(label.upper(), self)
        caption.setObjectName("statLabel")
        layout.addWidget(caption)

        layout.addStretch(1)
        self.setMinimumHeight(84)

    def set_value(self, value: int) -> None:
        self._value_label.setText(str(value))

    def restyle(self) -> None:
        """Force Qt to re-evaluate the [variant=...] property selector after
        a stylesheet swap (theme change) -- polish()/unpolish() is the
        standard way to make Qt re-apply QSS for a dynamic property."""
        style = self.style()
        style.unpolish(self._value_label)
        style.polish(self._value_label)
