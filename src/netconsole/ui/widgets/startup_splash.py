from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QLabel, QProgressBar, QVBoxLayout, QWidget

from netconsole.core import app_logger
from netconsole.core.i18n import I18n
from netconsole.core import version as version_info
from netconsole.ui.widgets.loading_overlay import LoadingSpinner


class StartupSplash(QWidget):
    def __init__(self, i18n: I18n) -> None:
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.i18n = i18n
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("startupSplash")
        self.setFixedSize(520, 300)
        self.setStyleSheet(
            """
            QWidget#startupSplash {
                background: #0f172a;
                border: 1px solid #334155;
                border-radius: 8px;
            }
            QLabel {
                color: #e5e7eb;
                background: transparent;
            }
            QProgressBar {
                min-height: 10px;
                max-height: 10px;
                border: 1px solid #334155;
                border-radius: 5px;
                background: #111827;
                color: #e5e7eb;
                font-size: 10px;
                text-align: center;
            }
            QProgressBar::chunk {
                background: #60a5fa;
                border-radius: 5px;
            }
            """
        )
        self.title_label = QLabel(version_info.APP_TITLE_DISPLAY)
        title_font = QFont()
        title_font.setPointSize(22)
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        self.title_label.setAlignment(Qt.AlignCenter)
        self.spinner = LoadingSpinner(self)
        self.message_label = QLabel(self.i18n.t("app.starting"))
        self.message_label.setAlignment(Qt.AlignCenter)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.progress.setMinimumWidth(380)
        self.progress.setMaximumWidth(440)
        self.version_label = QLabel(self.i18n.t("app.version_label", version=f"{version_info.APP_VERSION_DISPLAY} {version_info.APP_BYLINE}"))
        self.version_label.setAlignment(Qt.AlignCenter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(44, 30, 44, 26)
        layout.setSpacing(16)
        layout.addWidget(self.title_label)
        layout.addWidget(self.spinner, 0, Qt.AlignCenter)
        layout.addWidget(self.message_label)
        layout.addWidget(self.progress, 0, Qt.AlignCenter)
        layout.addWidget(self.version_label)

    def show_centered(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            x = available.x() + max(0, (available.width() - self.width()) // 2)
            y = available.y() + max(0, (available.height() - self.height()) // 2)
            self.move(x, y)
            message = f"[UI] Splash: {self.width()}x{self.height()}+{x}+{y} available={available.width()}x{available.height()}"
            print(message)
            app_logger.log_info("UI_STARTUP", message)
        self.spinner.start()
        self.show()

    def show_message(self, text: str) -> None:
        self.message_label.setText(text)
        QApplication.processEvents()

    def set_progress(self, value: int) -> None:
        self.progress.setValue(max(0, min(100, value)))
        QApplication.processEvents()

    def close_after_main_window_shown(self) -> None:
        QTimer.singleShot(350, self.close)
