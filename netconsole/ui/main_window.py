from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QMainWindow, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from netconsole.core.i18n import I18n
from netconsole.core.sites import Site
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.ui.navigation import Navigation
from netconsole.ui.pages.device_management_page import DeviceManagementPage
from netconsole.ui.windowing import fit_default_window_size


class MainWindow(QMainWindow):
    def __init__(self, site: Site, repository: DeviceRepository, i18n: I18n) -> None:
        super().__init__()
        self.site = site
        self.repository = repository
        self.i18n = i18n

        self.navigation = Navigation(i18n)
        self.stack = QStackedWidget()
        self.device_page = DeviceManagementPage(repository, i18n, site.name)
        self.stack.addWidget(self.device_page)

        self.site_label = QLabel()
        self.always_on_top_button = QPushButton()
        self.always_on_top_button.setCheckable(True)
        self.zh_button = QPushButton()
        self.en_button = QPushButton()
        self.always_on_top_button.toggled.connect(self.set_always_on_top)
        self.zh_button.clicked.connect(lambda: self.switch_language("zh_CN"))
        self.en_button.clicked.connect(lambda: self.switch_language("en_US"))

        top_bar = QHBoxLayout()
        top_bar.addWidget(self.site_label)
        top_bar.addStretch(1)
        top_bar.addWidget(self.always_on_top_button)
        top_bar.addWidget(self.zh_button)
        top_bar.addWidget(self.en_button)

        content_layout = QVBoxLayout()
        content_layout.addLayout(top_bar)
        content_layout.addWidget(self.stack)

        root_layout = QHBoxLayout()
        root_layout.addWidget(self.navigation)
        content = QWidget()
        content.setLayout(content_layout)
        root_layout.addWidget(content, 1)

        root = QWidget()
        root.setLayout(root_layout)
        self.setCentralWidget(root)
        self.setMinimumSize(1200, 760)
        self.apply_initial_geometry()
        self.apply_style()
        self.retranslate()

    def switch_language(self, language: str) -> None:
        self.i18n.set_language(language)
        self.retranslate()

    def set_always_on_top(self, enabled: bool) -> None:
        self.setWindowFlag(Qt.WindowStaysOnTopHint, enabled)
        self.always_on_top_button.setText(self.i18n.t("window.cancel_always_on_top" if enabled else "window.always_on_top"))
        self.show()

    def apply_initial_geometry(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            self.resize(1440, 900)
            return
        available = screen.availableGeometry()
        size = fit_default_window_size(available.width(), available.height(), 1440, 900)
        self.resize(size.width, size.height)
        frame = self.frameGeometry()
        frame.moveCenter(available.center())
        self.move(frame.topLeft())

    def retranslate(self) -> None:
        self.setWindowTitle(self.i18n.t("app.title"))
        self.site_label.setText(f"{self.i18n.t('site.current')}: {self.site.name}")
        self.always_on_top_button.setText(self.i18n.t("window.cancel_always_on_top" if self.always_on_top_button.isChecked() else "window.always_on_top"))
        self.zh_button.setText(self.i18n.t("language.zh"))
        self.en_button.setText(self.i18n.t("language.en"))
        self.navigation.retranslate()
        self.device_page.retranslate()

    def apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #f7f8fa; color: #1f2933; font-family: "Microsoft YaHei", "Segoe UI"; font-size: 13px; }
            #navigation { background: #ffffff; border: 1px solid #dde3ea; padding: 8px; }
            QListWidget::item { height: 36px; padding-left: 10px; border-radius: 4px; }
            QListWidget::item:selected { background: #e8f1ff; color: #1459b3; }
            QPushButton { background: #ffffff; border: 1px solid #cbd5df; border-radius: 4px; padding: 6px 10px; }
            QPushButton:hover { background: #eef5ff; border-color: #8bb7ee; }
            QLineEdit, QComboBox, QSpinBox, QTextEdit { background: #ffffff; border: 1px solid #cbd5df; border-radius: 4px; padding: 5px; }
            QTableWidget { background: #ffffff; border: 1px solid #dde3ea; gridline-color: #edf1f5; selection-background-color: #dcecff; }
            QHeaderView::section { background: #f0f3f7; border: 0; border-right: 1px solid #dde3ea; border-bottom: 1px solid #dde3ea; padding: 6px; font-weight: 600; }
            """
        )
