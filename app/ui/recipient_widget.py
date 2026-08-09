"""Recipient list input: paste/edit, import TXT, live validation summary
(spec items 12-15, 44). Large lists are re-parsed on a short debounce
timer rather than on every keystroke, so pasting/importing thousands of
lines doesn't stall the UI thread.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.recipients.importer import import_recipients_from_txt
from app.recipients.parser import ParsedRecipient, ParseSummary, parse_recipient_lines

_DEBOUNCE_MS = 300


class RecipientWidget(QWidget):
    recipients_changed = Signal(object)  # ParseSummary

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._text_edit = QPlainTextEdit(self)
        self._text_edit.setPlaceholderText("@username1\n@username2\n123456789\nhttps://t.me/username3")
        self._text_edit.textChanged.connect(self._on_text_changed)
        layout.addWidget(self._text_edit)

        buttons = QHBoxLayout()
        import_button = QPushButton("Импорт TXT", self)
        import_button.clicked.connect(self._on_import_clicked)
        clear_button = QPushButton("Очистить", self)
        clear_button.clicked.connect(self._on_clear_clicked)
        buttons.addWidget(import_button)
        buttons.addWidget(clear_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self._summary_label = QLabel(self)
        layout.addWidget(self._summary_label)

        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self._recompute_summary)

        self._last_summary: ParseSummary = ParseSummary()
        self._recompute_summary()

    def _on_text_changed(self) -> None:
        self._debounce_timer.start(_DEBOUNCE_MS)

    def flush(self) -> None:
        """Force an immediate recompute, bypassing the debounce -- callers
        that are about to act on the recipient list (e.g. Start) must call
        this first so they never read a stale summary."""
        if self._debounce_timer.isActive():
            self._debounce_timer.stop()
        self._recompute_summary()

    def _recompute_summary(self) -> None:
        lines = self._text_edit.toPlainText().splitlines()
        summary = parse_recipient_lines(lines)
        self._last_summary = summary
        self._summary_label.setText(
            f"Всего получателей: {summary.total_recipients}    "
            f"Валидных: {len(summary.valid_recipients)}    "
            f"Ошибок формата: {summary.invalid_count}    "
            f"Дубликатов удалено: {summary.duplicates_removed}"
        )
        self.recipients_changed.emit(summary)

    def _on_import_clicked(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(self, "Импорт получателей", "", "Текстовые файлы (*.txt)")
        if not file_path:
            return
        try:
            summary = import_recipients_from_txt(Path(file_path))
        except OSError as exc:
            QMessageBox.warning(self, "Импорт получателей", f"Не удалось прочитать файл: {exc}")
            return

        existing_text = self._text_edit.toPlainText()
        new_lines = "\n".join(p.raw.strip() for p in summary.parsed)
        combined = f"{existing_text}\n{new_lines}" if existing_text.strip() else new_lines
        self._text_edit.setPlainText(combined)
        self.flush()

        QMessageBox.information(
            self,
            "Импорт получателей",
            f"Импортировано: {summary.total_recipients}\n"
            f"Дубликатов удалено: {summary.duplicates_removed}\n"
            f"Некорректных строк: {summary.invalid_count}\n"
            f"Итого получателей: {len(summary.valid_recipients)}",
        )

    def _on_clear_clicked(self) -> None:
        self._text_edit.clear()

    def get_summary(self) -> ParseSummary:
        return self._last_summary

    def valid_recipients(self) -> List[ParsedRecipient]:
        return self._last_summary.valid_recipients
