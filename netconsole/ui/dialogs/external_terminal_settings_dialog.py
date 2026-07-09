from __future__ import annotations

from netconsole.ui.dialogs.message_service import MessageBox
from pathlib import Path

from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLineEdit, QPushButton, QSizePolicy, QVBoxLayout

from netconsole.core.i18n import I18n
from netconsole.core.settings import SettingsStore


class ExternalTerminalSettingsDialog(QDialog):
    def __init__(self, i18n: I18n, settings: SettingsStore, parent=None) -> None:
        super().__init__(parent)
        self.i18n = i18n
        self.settings = settings
        self.setWindowTitle(self.i18n.t("external_terminal.settings"))
        self.resize(760, 320)
        self.setMinimumSize(680, 280)
        self.securecrt_path = QLineEdit(str(settings.get_value("external_terminal/securecrt_path", "") or ""))
        self.xshell_path = QLineEdit(str(settings.get_value("external_terminal/xshell_path", "") or ""))
        self.putty_path = QLineEdit(str(settings.get_value("external_terminal/putty_path", "") or ""))
        for edit in (self.securecrt_path, self.xshell_path, self.putty_path):
            edit.setMinimumWidth(420)
            edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.pass_password = QCheckBox(self.i18n.t("external_terminal.pass_password"))
        self.pass_password.setChecked(bool(settings.get_value("external_terminal/pass_password", False)))

        form = QFormLayout()
        form.addRow(self.i18n.t("external_terminal.securecrt_path"), self._path_row(self.securecrt_path, "exe"))
        form.addRow(self.i18n.t("external_terminal.xshell_path"), self._path_row(self.xshell_path, "exe"))
        form.addRow(self.i18n.t("external_terminal.putty_path"), self._path_row(self.putty_path, "exe"))
        form.addRow("", self.pass_password)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _path_row(self, edit: QLineEdit, mode: str) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(edit, 1)
        button = QPushButton(self.i18n.t("common.browse"))
        button.setMinimumWidth(88)
        button.clicked.connect(lambda: self._browse(edit, mode))
        row.addWidget(button)
        test_button = QPushButton(self.i18n.t("external_terminal.test_path"))
        test_button.setMinimumWidth(88)
        test_button.clicked.connect(lambda: self._test_path(edit))
        row.addWidget(test_button)
        return row

    def _browse(self, edit: QLineEdit, mode: str) -> None:
        if mode == "dir":
            path = QFileDialog.getExistingDirectory(self, self.i18n.t("common.browse"))
        elif mode == "ini":
            path, _ = QFileDialog.getOpenFileName(self, self.i18n.t("common.browse"), "", "SecureCRT Session (*.ini);;All Files (*)")
        else:
            path, _ = QFileDialog.getOpenFileName(self, self.i18n.t("common.browse"), "", "Executable (*.exe);;All Files (*)")
        if path:
            edit.setText(path)

    def _test_path(self, edit: QLineEdit) -> None:
        path = Path(edit.text().strip())
        if path.is_file():
            MessageBox.information(self, self.i18n.t("external_terminal.settings"), self.i18n.t("external_terminal.path_ok"))
        else:
            MessageBox.warning(self, self.i18n.t("external_terminal.settings"), self.i18n.t("external_terminal.path_missing"))

    def _save(self) -> None:
        self.settings.set_value("external_terminal/securecrt_path", self.securecrt_path.text().strip())
        self.settings.set_value("external_terminal/xshell_path", self.xshell_path.text().strip())
        self.settings.set_value("external_terminal/putty_path", self.putty_path.text().strip())
        self.settings.set_value("external_terminal/pass_password", self.pass_password.isChecked())
        self.accept()
