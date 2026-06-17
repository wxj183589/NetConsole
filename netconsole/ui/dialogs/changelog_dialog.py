from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout

from netconsole.core.i18n import I18n
from netconsole.core.resources import changelog_path, icon_path
from netconsole.core.version import APP_VERSION


class ChangelogDialog(QDialog):
    def __init__(self, i18n: I18n, parent=None) -> None:
        super().__init__(parent)
        self.i18n = i18n
        self.setModal(False)
        self.setWindowIcon(QIcon(str(icon_path("love.ico"))))
        self.setMinimumSize(720, 520)
        self.setWindowTitle(self.i18n.t("changelog.title", version=APP_VERSION))

        layout = QVBoxLayout(self)
        title = QLabel(self.i18n.t("changelog.title", version=APP_VERSION))
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        layout.addWidget(title)

        self.text = QTextEdit()
        self.text.setReadOnly(True)
        self.text.setPlainText(self._read_changelog())
        layout.addWidget(self.text, 1)

        actions = QHBoxLayout()
        actions.addStretch(1)
        close_button = QPushButton(self.i18n.t("dialog.close"))
        close_button.clicked.connect(self.close)
        actions.addWidget(close_button)
        layout.addLayout(actions)

    def _read_changelog(self) -> str:
        path = changelog_path()
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return self.i18n.t("changelog.not_found", path=str(path))
