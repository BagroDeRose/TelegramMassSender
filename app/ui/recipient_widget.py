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

from app.i18n import tr, trn
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
        self._text_edit.setPlaceholderText(tr("recipient_widget.placeholder"))
        self._text_edit.setToolTip(tr("recipient_widget.tooltip"))
        self._text_edit.textChanged.connect(self._on_text_changed)
        layout.addWidget(self._text_edit)

        buttons = QHBoxLayout()
        self._import_button = QPushButton(tr("recipient_widget.import_txt_button"), self)
        self._import_button.clicked.connect(self._on_import_clicked)
        self._clear_button = QPushButton(tr("recipient_widget.clear_button"), self)
        self._clear_button.setObjectName("ghostButton")
        self._clear_button.clicked.connect(self._on_clear_clicked)
        buttons.addWidget(self._import_button)
        buttons.addWidget(self._clear_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self._summary_label = QLabel(self)
        self._summary_label.setWordWrap(True)
        self._summary_label.setObjectName("summaryLabel")
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
        if summary.total_recipients == 0:
            self._summary_label.setText(tr("recipient_widget.empty_summary"))
        else:
            valid_count = len(summary.valid_recipients)
            details = []
            if summary.invalid_count:
                details.append(tr("recipient_widget.summary_invalid_count", count=summary.invalid_count))
            if summary.duplicates_removed:
                details.append(tr("recipient_widget.summary_duplicates_removed", count=summary.duplicates_removed))
            suffix = f"  ({', '.join(details)})" if details else ""
            self._summary_label.setText(f"{trn('recipient_widget.recipient_count', valid_count)}{suffix}")
        self.recipients_changed.emit(summary)

    def _on_import_clicked(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self, tr("recipient_widget.import_dialog_title"), "", tr("recipient_widget.import_file_filter")
        )
        if not file_path:
            return
        try:
            summary = import_recipients_from_txt(Path(file_path))
        except OSError as exc:
            QMessageBox.warning(
                self, tr("recipient_widget.import_dialog_title"), tr("recipient_widget.import_read_failed", error=exc)
            )
            return

        existing_text = self._text_edit.toPlainText()
        new_lines = "\n".join(p.raw.strip() for p in summary.parsed)
        combined = f"{existing_text}\n{new_lines}" if existing_text.strip() else new_lines
        self._text_edit.setPlainText(combined)
        self.flush()

        QMessageBox.information(
            self,
            tr("recipient_widget.import_dialog_title"),
            tr(
                "recipient_widget.import_result",
                total=summary.total_recipients,
                duplicates=summary.duplicates_removed,
                invalid=summary.invalid_count,
                valid=len(summary.valid_recipients),
            ),
        )

    def _on_clear_clicked(self) -> None:
        self._text_edit.clear()

    def get_summary(self) -> ParseSummary:
        return self._last_summary

    def valid_recipients(self) -> List[ParsedRecipient]:
        return self._last_summary.valid_recipients

    def get_text(self) -> str:
        return self._text_edit.toPlainText()

    def set_text(self, text: str) -> None:
        self._text_edit.setPlainText(text)
        self.flush()

    def retranslate_ui(self) -> None:
        self._text_edit.setPlaceholderText(tr("recipient_widget.placeholder"))
        self._text_edit.setToolTip(tr("recipient_widget.tooltip"))
        self._import_button.setText(tr("recipient_widget.import_txt_button"))
        self._clear_button.setText(tr("recipient_widget.clear_button"))
        self._recompute_summary()
