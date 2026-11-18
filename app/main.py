"""Application entry point."""
from __future__ import annotations

import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.config.paths import get_app_data_dir, get_resource_path
from app.logging.logger import configure_logging, get_logger
from app.telegram.qt_bridge import install_event_loop, run_event_loop
from app.ui.main_window import MainWindow


def schedule_onboarding(window: MainWindow) -> None:
    """Show the first-run onboarding once the event loop is running, not
    before it. The onboarding is a modal exec() that can open the login
    dialog ("Get Started"); called before run_event_loop(), Qt's nested
    loop still ran the login coroutines, but asyncio had no running loop
    yet, and Telethon's connect failed with "no running event loop"."""
    QTimer.singleShot(0, window.maybe_show_onboarding)


def main() -> int:
    configure_logging()
    logger = get_logger()
    logger.info("Приложение запускается")
    logger.info("Каталог данных: %s", get_app_data_dir())

    qt_app = QApplication(sys.argv)
    qt_app.setApplicationName("Telegram Mass Sender")
    qt_app.setOrganizationName("TelegramMassSender")

    icon_path = get_resource_path("assets", "icons", "app.ico")
    if icon_path.exists():
        qt_app.setWindowIcon(QIcon(str(icon_path)))

    loop, close_event = install_event_loop(qt_app)

    window = MainWindow(close_event=close_event)
    window.show()
    schedule_onboarding(window)

    try:
        run_event_loop(loop, close_event)
    finally:
        logger.info("Приложение завершает работу")

    return 0


if __name__ == "__main__":
    sys.exit(main())
