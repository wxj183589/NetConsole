from __future__ import annotations

import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout

from netconsole.core.i18n import I18n
from netconsole.core.resources import icon_path
from netconsole.core import version as version_info


class AboutRepositoryDialog(QDialog):
    def __init__(self, i18n: I18n, parent=None) -> None:
        super().__init__(parent)
        self.i18n = i18n
        self.setModal(False)
        self.setWindowIcon(QIcon(str(icon_path("love.ico"))))
        self.setWindowTitle(self.i18n.t("about.title"))
        self.setMinimumWidth(620)

        layout = QVBoxLayout(self)
        title = QLabel(f"{version_info.APP_NAME} {version_info.APP_VERSION_DISPLAY}")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        layout.addWidget(title)
        layout.addWidget(QLabel(f"{self.i18n.t('about.author')}: {version_info.APP_AUTHOR}"))
        layout.addWidget(QLabel(self.i18n.t("about.repositories")))

        grid = QGridLayout()
        for row, url in enumerate(version_info.REPOSITORY_URLS):
            line = QLineEdit(url)
            line.setReadOnly(True)
            copy_button = QPushButton(self.i18n.t("about.copy_link"))
            open_button = QPushButton(self.i18n.t("about.open_browser"))
            copy_button.clicked.connect(lambda _checked=False, value=url: self.copy_link(value))
            open_button.clicked.connect(lambda _checked=False, value=url: webbrowser.open(value))
            grid.addWidget(line, row, 0)
            grid.addWidget(copy_button, row, 1)
            grid.addWidget(open_button, row, 2)
        layout.addLayout(grid)

        actions = QHBoxLayout()
        actions.addStretch(1)
        close_button = QPushButton(self.i18n.t("dialog.close"))
        close_button.clicked.connect(self.close)
        actions.addWidget(close_button)
        layout.addLayout(actions)

    def copy_link(self, url: str) -> None:
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(url)
