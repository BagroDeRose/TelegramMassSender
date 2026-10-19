"""The empty Results page showed a small filled square above the report
buttons: the campaign-status pill (a QLabel styled as a pill) was always
visible, and with no campaign yet its text is empty -- so only its
background and padding were drawn. The pill and the duration next to it
are shown only once they have something to say."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication, QLabel

from app.database.database import Database
from app.i18n import tr
from app.security.secure_storage import SecureStorage
from app.ui.main_window import _PAGE_RESULTS, MainWindow


def _make_window(tmp_path: Path) -> MainWindow:
    return MainWindow(database=Database(tmp_path / "app.db"), secure_storage=SecureStorage(tmp_path / "s.dat"))


def _visible_empty_labels(page):
    return [
        label.objectName()
        for label in page.findChildren(QLabel)
        if label.isVisible() and not label.text() and label.pixmap().isNull() and label.objectName() in ("pill", "helperText")
    ]


async def test_empty_results_page_draws_no_empty_pill(qapp, tmp_path):
    window = _make_window(tmp_path)
    window.show()
    window._navigate_to_page(_PAGE_RESULTS)
    QApplication.processEvents()
    page = window._stack.currentWidget()
    assert window._results_empty_label.isVisible()
    assert _visible_empty_labels(page) == []


async def test_status_pill_and_duration_appear_once_set(qapp, tmp_path):
    window = _make_window(tmp_path)
    window.show()
    window._navigate_to_page(_PAGE_RESULTS)
    window._set_results_status(tr("main_window.results.completed"), "success")
    window._last_campaign_duration_seconds = 90
    window._update_duration_label()
    QApplication.processEvents()
    assert window._results_status_label.isVisible()
    assert window._results_duration_label.isVisible()

    window._last_campaign_duration_seconds = None
    window._update_duration_label()
    assert not window._results_duration_label.isVisible()
