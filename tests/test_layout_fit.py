"""Nothing on any page is clipped sideways, at any supported window width,
with the journal open or closed and the sidebar expanded or collapsed.

The Campaign page's two columns used to fold at a fixed width that had
nothing to do with what the columns actually need: at the default
first-run window (1180 px) the left column needed 674 px and got 546,
and with horizontal scrolling switched off the rest was cut off (and a
focus change could scroll it sideways). The right column was 6 px too
narrow for the launch panel at every width."""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QScrollArea

from app.config.settings import DEFAULT_WINDOW_HEIGHT, DEFAULT_WINDOW_WIDTH
from app.database.database import Database
from app.security.secure_storage import SecureStorage
from app.ui.main_window import MainWindow

WIDTHS = (900, 1100, DEFAULT_WINDOW_WIDTH, 1280, 1366, 1600, 1920)
PAGES = {0: "campaign", 1: "accounts", 2: "results", 3: "settings"}


@pytest.fixture
async def window(qapp, tmp_path: Path):
    # Async, like every MainWindow test: the window spawns its account
    # refresh on the running loop.
    window = MainWindow(database=Database(tmp_path / "app.db"), secure_storage=SecureStorage(tmp_path / "s.dat"))
    window.show()
    yield window


def _settle():
    for _ in range(4):
        QApplication.processEvents()


def _clipping(page):
    problems = []
    for area in page.findChildren(QScrollArea):
        if not area.isVisible() or area.widget() is None:
            continue
        need, have = area.widget().minimumSizeHint().width(), area.viewport().width()
        if need > have:
            problems.append(f"{type(area.widget()).__name__} needs {need}px, has {have}px")
        if area.horizontalScrollBar().maximum() > 0:
            problems.append(f"{type(area.widget()).__name__} scrolls sideways by {area.horizontalScrollBar().maximum()}px")
    if page.minimumSizeHint().width() > page.width():
        problems.append(f"page needs {page.minimumSizeHint().width()}px, has {page.width()}px")
    return problems


def _configure(window, width, journal, collapsed):
    window.resize(width, DEFAULT_WINDOW_HEIGHT)
    window._journal.setVisible(journal)
    window._sidebar.set_collapsed(collapsed)
    _settle()


@pytest.mark.parametrize("width", WIDTHS)
async def test_no_page_is_clipped_at_any_width(window, width):
    failures = []
    for journal in (False, True):
        for collapsed in (False, True):
            _configure(window, width, journal, collapsed)
            for index, name in PAGES.items():
                window._navigate_to_page(index)
                _settle()
                for problem in _clipping(window._stack.currentWidget()):
                    failures.append(f"{name} (journal={journal}, sidebar collapsed={collapsed}): {problem}")
    assert failures == []


async def test_default_first_run_size_shows_the_campaign_page_whole(window):
    _configure(window, DEFAULT_WINDOW_WIDTH, journal=False, collapsed=False)
    window._navigate_to_page(0)
    _settle()
    columns = window._campaign_columns
    assert _clipping(window._stack.currentWidget()) == []
    # Whatever is in the left column ends inside its viewport.
    content = columns.scroll.widget()
    assert content.width() <= columns.scroll.viewport().width()


@pytest.mark.parametrize("width", WIDTHS)
async def test_columns_fold_exactly_when_two_do_not_fit(window, width):
    for journal in (False, True):
        for collapsed in (False, True):
            _configure(window, width, journal, collapsed)
            window._navigate_to_page(0)
            _settle()
            columns = window._campaign_columns
            needed = columns.two_column_width()
            assert columns.is_folded == (columns.width() < needed), (width, journal, collapsed, columns.width(), needed)
            if not columns.is_folded:
                # Side by side, each column gets at least what it needs.
                assert columns.scroll.viewport().width() >= columns.scroll.widget().minimumSizeHint().width()


async def test_narrow_page_folds_into_one_column(window):
    _configure(window, 900, journal=True, collapsed=False)
    window._navigate_to_page(0)
    _settle()
    assert window._campaign_columns.is_folded
    _configure(window, 1920, journal=False, collapsed=False)
    _settle()
    assert not window._campaign_columns.is_folded


def _row_lines(row):
    """How many lines a FlowLayout row of buttons takes."""
    widgets = [row.itemAt(i).widget() for i in range(row.count())]
    return len({w.y() for w in widgets if w is not None and w.isVisible()})


@pytest.mark.parametrize("width", (1100, 1120, 1140, 1160, DEFAULT_WINDOW_WIDTH))
async def test_recipient_buttons_stay_on_one_line(window, width):
    # "Clear" wrapped onto a second line at 1100-1180 px with the sidebar
    # expanded: Import TXT + Import CSV + From my chats + Clear needed
    # ~510 px and the box had 385-465.
    from app.i18n import LANGUAGE_EN, LANGUAGE_RU, set_language

    try:
        for language in (LANGUAGE_RU, LANGUAGE_EN):
            set_language(language)
            window.retranslate_ui()
            for journal in (False, True):
                _configure(window, width, journal, collapsed=False)
                window._navigate_to_page(0)
                _settle()
                row = window._recipient_widget._buttons_row
                assert _row_lines(row) == 1, (language, width, journal, window._recipient_widget.width())
    finally:
        set_language(LANGUAGE_RU)
        window.retranslate_ui()


async def test_wizard_recipient_buttons_stay_on_one_line(window):
    wizard = window._build_campaign_wizard()
    try:
        wizard.show()
        _settle()
        assert _row_lines(wizard.recipient_widget._buttons_row) == 1
    finally:
        wizard.reject()
