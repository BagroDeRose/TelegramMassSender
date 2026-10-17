"""Small, short-lived motion only (120-180 ms, ease-out): a fade when a page
appears, and non-blocking toast notifications. Nothing here loops.

Toasts replace modal message boxes for successful, non-critical actions
("Preset saved", "Report saved", "Copied"). Confirmations and errors that
need a decision stay modal (app.ui.dialogs).
"""
from __future__ import annotations

from typing import List

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPropertyAnimation, Qt, QTimer
from PySide6.QtWidgets import QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QWidget

from app.ui import icons
from app.ui.theme import (
    ICON_SIZE,
    MOTION_FAST_MS,
    MOTION_SLOW_MS,
    SPACE_LG,
    SPACE_MD,
    SPACE_SM,
    TOAST_DURATION_MS,
    TOAST_WIDTH,
)

_STATUS_ICONS = {
    "success": ("check_circle", "success"),
    "info": ("info", "accent"),
    "warning": ("warning", "warning"),
    "error": ("error_circle", "error"),
}
_MAX_TOASTS = 3


def fade_in(widget: QWidget, duration: int = MOTION_FAST_MS) -> None:
    """Fade a freshly shown widget in. The opacity effect is removed when
    done -- leaving one installed would slow every later repaint."""
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(0.0)
    widget.setGraphicsEffect(effect)
    animation = QPropertyAnimation(effect, b"opacity", widget)
    animation.setDuration(duration)
    animation.setStartValue(0.0)
    animation.setEndValue(1.0)
    animation.setEasingCurve(QEasingCurve.Type.OutCubic)
    animation.finished.connect(lambda: widget.setGraphicsEffect(None))
    animation.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)


class Toast(QFrame):
    def __init__(self, text: str, status: str, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("toast")
        self.setProperty("status", status)
        self.setFixedWidth(TOAST_WIDTH)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(SPACE_MD, SPACE_MD, SPACE_MD, SPACE_MD)
        layout.setSpacing(SPACE_SM)
        icon_name, role = _STATUS_ICONS.get(status, _STATUS_ICONS["info"])
        icon = QLabel(self)
        icon.setPixmap(icons.themed_pixmap(icon_name, role, ICON_SIZE, self.devicePixelRatioF()))
        layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        self.text_label = QLabel(text, self)
        self.text_label.setObjectName("toastText")
        self.text_label.setWordWrap(True)
        layout.addWidget(self.text_label, 1)
        self.setAccessibleName(text)

        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(0.0)
        self.setGraphicsEffect(self._effect)
        self._animation = QPropertyAnimation(self._effect, b"opacity", self)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    def appear(self) -> None:
        self._animation.stop()
        self._animation.setDuration(MOTION_SLOW_MS)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.start()

    def vanish(self, on_done) -> None:
        self._animation.stop()
        self._animation.setDuration(MOTION_SLOW_MS)
        self._animation.setStartValue(self._effect.opacity())
        self._animation.setEndValue(0.0)
        self._animation.finished.connect(on_done)
        self._animation.start()


class ToastHost(QObject):
    """Stacks toasts in the bottom-right corner of `anchor` and keeps them
    there when the anchor resizes."""

    def __init__(self, anchor: QWidget) -> None:
        super().__init__(anchor)
        self._anchor = anchor
        self._toasts: List[Toast] = []
        anchor.installEventFilter(self)

    @property
    def toasts(self) -> List[Toast]:
        return list(self._toasts)

    def show_toast(self, text: str, status: str = "success", duration: int = TOAST_DURATION_MS) -> Toast:
        while len(self._toasts) >= _MAX_TOASTS:
            self._remove(self._toasts[0])
        toast = Toast(text, status, self._anchor)
        self._toasts.append(toast)
        toast.adjustSize()
        toast.show()
        toast.raise_()
        self._relayout()
        toast.appear()
        QTimer.singleShot(duration, toast, lambda t=toast: self._dismiss(t))
        return toast

    def _dismiss(self, toast: Toast) -> None:
        if toast in self._toasts:
            toast.vanish(lambda t=toast: self._remove(t))

    def _remove(self, toast: Toast) -> None:
        if toast in self._toasts:
            self._toasts.remove(toast)
            toast.hide()
            toast.deleteLater()
            self._relayout()

    def _relayout(self) -> None:
        bottom = self._anchor.height() - SPACE_LG
        for toast in reversed(self._toasts):
            toast.adjustSize()
            height = toast.sizeHint().height()
            toast.setGeometry(self._anchor.width() - TOAST_WIDTH - SPACE_LG, bottom - height, TOAST_WIDTH, height)
            bottom -= height + SPACE_SM

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt override
        if obj is self._anchor and event.type() == QEvent.Type.Resize:
            self._relayout()
        return False

