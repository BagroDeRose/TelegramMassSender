"""Application entry point."""
from __future__ import annotations

import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.config.paths import get_app_data_dir, get_resource_path
from app.logging.logger import configure_logging, get_logger
from app.telegram.qt_bridge import install_event_loop, run_event_loop
from app.ui.main_window import MainWindow


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

    try:
        run_event_loop(loop, close_event)
    finally:
        logger.info("Приложение завершает работу")

    return 0


if __name__ == "__main__":
    sys.exit(main())
