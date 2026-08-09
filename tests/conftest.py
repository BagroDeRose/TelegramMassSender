"""Shared pytest fixtures.

QT_QPA_PLATFORM=offscreen is set before any Qt import so the suite runs
headlessly -- no real display required, matching how this runs on a
build machine / CI.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
