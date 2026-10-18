"""Recipient list input: paste/edit, import TXT/CSV, live validation
summary (spec items 12-15, 44). Large lists are re-parsed on a short
debounce timer rather than on every keystroke, so pasting/importing
thousands of lines doesn't stall the UI thread.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

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
from app.recipients.csv_importer import CsvImportError, import_recipients_from_csv
from app.recipients.importer import import_recipients_from_txt
from app.recipients.parser import ParsedRecipient, ParseSummary, parse_recipient_line, parse_recipient_lines
from app.ui import icons
from app.ui.dialogs import show_invalid_rows
from app.ui.theme import SPACE_SM, SPACE_XS

_DEBOUNCE_MS = 300


class RecipientWidget(QWidget):
    recipients_changed = Signal(object)  # ParseSummary
    # "From my chats…" clicked. The widget can't load chats itself (that
    # needs the active account's client) -- MainWindow does, through the
    # service layer, and writes the picked chats back via append_lines().
    pick_chats_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None, show_chat_picker: bool = False) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._text_edit = QPlainTextEdit(self)
        self._text_edit.setPlaceholderText(tr("recipient_widget.placeholder"))
        self._text_edit.setToolTip(tr("recipient_widget.tooltip"))
        self._text_edit.textChanged.connect(self._on_text_changed)
        layout.addWidget(self._text_edit)

        buttons = QHBoxLayout()
        buttons.setSpacing(SPACE_SM)
        self._import_button = QPushButton(tr("recipient_widget.import_txt_button"), self)
        self._import_button.setIcon(icons.themed("import"))
        self._import_button.clicked.connect(self._on_import_clicked)
        self._import_csv_button = QPushButton(tr("recipient_widget.import_csv_button"), self)
        self._import_csv_button.setIcon(icons.themed("import"))
        self._import_csv_button.clicked.connect(self._on_import_csv_clicked)
        self._pick_chats_button = QPushButton(tr("recipient_widget.pick_chats_button"), self)
        self._pick_chats_button.setToolTip(tr("recipient_widget.pick_chats_tooltip"))
        self._pick_chats_button.setIcon(icons.themed("chats"))
        self._pick_chats_button.clicked.connect(self.pick_chats_requested.emit)
        self._pick_chats_button.setVisible(show_chat_picker)
        self._pick_chats_button.setEnabled(False)  # until an account is connected
        self._clear_button = QPushButton(tr("recipient_widget.clear_button"), self)
        self._clear_button.setProperty("variant", "ghost")
        self._clear_button.clicked.connect(self._on_clear_clicked)
        buttons.addWidget(self._import_button)
        buttons.addWidget(self._import_csv_button)
        buttons.addWidget(self._pick_chats_button)
        buttons.addWidget(self._clear_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        summary_row = QHBoxLayout()
        summary_row.setSpacing(SPACE_XS)
        # Shown only while the box is empty (a hint); otherwise the counts
        # are pills and this keeps the full sentence for screen readers.
        self._summary_label = QLabel(self)
        self._summary_label.setWordWrap(True)
        self._summary_label.setObjectName("summaryLabel")
        summary_row.addWidget(self._summary_label, 1)
        self._pills = {}
        for key, status in (("valid", ""), ("chats", "info"), ("invalid", "error"), ("duplicates", "")):
            pill = QLabel(self)
            pill.setObjectName("pill")
            pill.setProperty("status", status)
            pill.setVisible(False)
            summary_row.addWidget(pill)
            self._pills[key] = pill
        summary_row.addStretch(1)
        self._review_invalid_button = QPushButton(tr("recipient_widget.review_invalid_button"), self)
        self._review_invalid_button.setProperty("variant", "ghost")
        self._review_invalid_button.clicked.connect(self._on_review_invalid_clicked)
        self._review_invalid_button.setVisible(False)
        summary_row.addWidget(self._review_invalid_button)
        layout.addLayout(summary_row)

        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self._recompute_summary)

        # normalized_key -> display name, from a CSV column that didn't
        # parse as a recipient identifier itself (see app.recipients.
        # csv_importer) -- overrides the {name} placeholder for that
        # specific recipient at send time. Pruned in _recompute_summary()
        # to only keys still present among the current valid recipients,
        # so an override never outlives the row it came from.
        self._name_overrides: Dict[str, str] = {}

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
            chat_count = sum(1 for p in summary.valid_recipients if p.is_chat_target)
            if chat_count:
                details.insert(0, tr("recipient_widget.summary_chat_count", count=chat_count))
            suffix = f"  ({', '.join(details)})" if details else ""
            self._summary_label.setText(f"{trn('recipient_widget.recipient_count', valid_count)}{suffix}")
        self._update_pills(summary)
        self._review_invalid_button.setVisible(summary.invalid_count > 0)

        surviving_keys = {p.normalized_key for p in summary.valid_recipients}
        self._name_overrides = {k: v for k, v in self._name_overrides.items() if k in surviving_keys}

        self.recipients_changed.emit(summary)

    def _update_pills(self, summary: ParseSummary) -> None:
        empty = summary.total_recipients == 0
        self._summary_label.setVisible(empty)
        chat_count = sum(1 for p in summary.valid_recipients if p.is_chat_target)
        values = {
            "valid": (len(summary.valid_recipients), trn("recipient_widget.recipient_count", len(summary.valid_recipients))),
            "chats": (chat_count, tr("recipient_widget.pill_chats", count=chat_count)),
            "invalid": (summary.invalid_count, tr("recipient_widget.summary_invalid_count", count=summary.invalid_count)),
            "duplicates": (
                summary.duplicates_removed,
                tr("recipient_widget.summary_duplicates_removed", count=summary.duplicates_removed),
            ),
        }
        for key, pill in self._pills.items():
            count, text = values[key]
            pill.setText(text)
            pill.setVisible(not empty and (count > 0 or key == "valid"))
        self.setAccessibleDescription(self._summary_label.text())

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

    def _on_import_csv_clicked(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self, tr("recipient_widget.import_dialog_title"), "", tr("recipient_widget.import_csv_file_filter")
        )
        if not file_path:
            return
        try:
            result = import_recipients_from_csv(Path(file_path))
        except CsvImportError as exc:
            QMessageBox.warning(
                self, tr("recipient_widget.import_dialog_title"), tr("recipient_widget.import_read_failed", error=exc)
            )
            return

        existing_text = self._text_edit.toPlainText()
        new_lines = "\n".join(p.raw.strip() for p in result.parsed)
        combined = f"{existing_text}\n{new_lines}" if existing_text.strip() else new_lines
        self._text_edit.setPlainText(combined)
        self._name_overrides.update(result.names)
        self.flush()

        QMessageBox.information(
            self,
            tr("recipient_widget.import_dialog_title"),
            tr(
                "recipient_widget.import_result",
                total=result.total_rows,
                duplicates=result.duplicates_removed,
                invalid=result.invalid_count,
                valid=len(result.valid_recipients),
            ),
        )

    def _on_review_invalid_clicked(self) -> None:
        rows = [(p.raw.strip() or p.raw, p.error or "") for p in self._last_summary.parsed if not p.is_valid]
        show_invalid_rows(self, tr("recipient_widget.review_invalid_title"), rows)

    def _on_clear_clicked(self) -> None:
        self._text_edit.clear()
        self._name_overrides = {}

    def get_summary(self) -> ParseSummary:
        return self._last_summary

    def valid_recipients(self) -> List[ParsedRecipient]:
        return self._last_summary.valid_recipients

    def name_overrides(self) -> Dict[str, str]:
        """normalized_key -> display name, sourced from CSV import (see
        app.recipients.csv_importer) -- consumed by
        app.ui.main_window._start_campaign to override the {name}
        placeholder for a specific recipient over whatever Telegram
        itself reports as that user's first name."""
        return dict(self._name_overrides)

    def get_text(self) -> str:
        return self._text_edit.toPlainText()

    def set_pick_chats_enabled(self, enabled: bool) -> None:
        self._pick_chats_button.setEnabled(enabled)

    def append_lines(self, lines: List[str]) -> int:
        """Append recipient lines (e.g. chats picked in "From my chats…")
        below whatever is already there, skipping ones already present by
        normalized identity. Returns how many were actually added."""
        existing = {p.normalized_key for p in self._last_summary.valid_recipients}
        new_lines = []
        for line in lines:
            parsed = parse_recipient_line(line)
            key = parsed.normalized_key
            if key is None or key in existing:
                continue
            existing.add(key)
            new_lines.append(line)
        if not new_lines:
            return 0
        existing_text = self._text_edit.toPlainText()
        joined = "\n".join(new_lines)
        combined = f"{existing_text.rstrip()}\n{joined}" if existing_text.strip() else joined
        self._text_edit.setPlainText(combined)
        self.flush()
        return len(new_lines)

    def set_text(self, text: str) -> None:
        self._text_edit.setPlainText(text)
        self.flush()

    def set_text_with_names(self, text: str, name_overrides: Dict[str, str]) -> None:
        """Like set_text(), but also restores name overrides for the new
        list (e.g. loading a saved recipient group whose text came from a
        CSV import) -- overrides are set before flush() so pruning keeps
        exactly the ones that still match a currently-valid recipient."""
        self._text_edit.setPlainText(text)
        self._name_overrides = dict(name_overrides)
        self.flush()

    def retranslate_ui(self) -> None:
        self._text_edit.setPlaceholderText(tr("recipient_widget.placeholder"))
        self._text_edit.setToolTip(tr("recipient_widget.tooltip"))
        self._import_button.setText(tr("recipient_widget.import_txt_button"))
        self._import_csv_button.setText(tr("recipient_widget.import_csv_button"))
        self._pick_chats_button.setText(tr("recipient_widget.pick_chats_button"))
        self._pick_chats_button.setToolTip(tr("recipient_widget.pick_chats_tooltip"))
        self._clear_button.setText(tr("recipient_widget.clear_button"))
        self._review_invalid_button.setText(tr("recipient_widget.review_invalid_button"))
        self._recompute_summary()
