from __future__ import annotations

import json
import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from netconsole.models.cloud_sync_models import CloudSyncProfile
from netconsole.repositories.cloud_sync_repository import CloudSyncRepository
from netconsole.services.cloud_sync.wps_auth import WpsAuthContext
from netconsole.services.cloud_sync.wps_ksheet_client import WpsKSheetClient


class WpsKSheetSyncDialog(QDialog):
    def __init__(self, i18n, repository: CloudSyncRepository, site_id: str, parent=None) -> None:
        super().__init__(parent)
        self.i18n = i18n
        self.repository = repository
        self.site_id = site_id
        self.profile = repository.get_or_create_profile(site_id)

        self.enabled = QCheckBox()
        self.auto_sync = QCheckBox()
        self.sync_mode = QComboBox()
        self.sync_mode.addItem("手动同步", "manual")
        self.sync_mode.addItem("导出后自动同步", "auto_after_export")
        self.app_id = QLineEdit()
        self.tenant_id = QLineEdit()
        self.access_token = QLineEdit()
        self.access_token.setEchoMode(QLineEdit.Password)
        self.refresh_token = QLineEdit()
        self.refresh_token.setEchoMode(QLineEdit.Password)
        self.token_expires_at = QLineEdit()
        self.target_name = QLineEdit()
        self.file_token = QLineEdit()
        self.remote_url = QLineEdit()
        self.permission_mode = QComboBox()
        self.permission_mode.addItem("指定人员只读", "readonly_members")
        self.permission_mode.addItem("只读链接", "readonly_link")
        self.readonly_link_enabled = QCheckBox()
        self.readonly_members = QTextEdit()
        self.readonly_members.setMinimumHeight(90)
        self.readonly_link_url = QLineEdit()
        self.last_sync_at = QLineEdit()
        self.last_sync_status = QLineEdit()
        self.last_error = QTextEdit()
        self.last_error.setMinimumHeight(60)
        for widget in (self.last_sync_at, self.last_sync_status, self.readonly_link_url):
            widget.setReadOnly(True)
        self.last_error.setReadOnly(True)

        self.test_button = QPushButton("测试连接")
        self.clear_binding_button = QPushButton("清除绑定")
        self.open_button = QPushButton("打开在线表格")
        self.history_button = QPushButton("查看同步记录")

        form = QFormLayout()
        form.addRow("启用WPS在线表格同步", self.enabled)
        form.addRow("导出后自动同步", self.auto_sync)
        form.addRow("同步模式", self.sync_mode)
        form.addRow("WPS应用ID", self.app_id)
        form.addRow("租户/账号标识", self.tenant_id)
        form.addRow("access_token", self.access_token)
        form.addRow("refresh_token", self.refresh_token)
        form.addRow("token过期时间", self.token_expires_at)
        form.addRow("在线表格名称", self.target_name)
        form.addRow("file_token", self.file_token)
        form.addRow("在线表格链接", self.remote_url)
        form.addRow("查看权限模式", self.permission_mode)
        form.addRow("启用只读链接", self.readonly_link_enabled)
        form.addRow("只读查看人员(JSON或每行账号)", self.readonly_members)
        form.addRow("只读链接", self.readonly_link_url)
        form.addRow("最后同步时间", self.last_sync_at)
        form.addRow("最后同步状态", self.last_sync_status)
        form.addRow("最后错误", self.last_error)

        actions = QHBoxLayout()
        actions.addWidget(self.test_button)
        actions.addWidget(self.clear_binding_button)
        actions.addWidget(self.open_button)
        actions.addWidget(self.history_button)
        actions.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(actions)
        layout.addWidget(buttons)

        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        self.test_button.clicked.connect(self.test_connection)
        self.clear_binding_button.clicked.connect(self.clear_binding)
        self.open_button.clicked.connect(self.open_document)
        self.history_button.clicked.connect(self.show_runs)

        self.setWindowTitle("WPS在线表格同步配置")
        self.resize(720, 680)
        self.load_profile(self.profile)

    def load_profile(self, profile: CloudSyncProfile) -> None:
        self.enabled.setChecked(profile.enabled)
        self.auto_sync.setChecked(profile.auto_sync_after_export)
        self.sync_mode.setCurrentIndex(max(self.sync_mode.findData(profile.sync_mode), 0))
        self.app_id.setText(profile.app_id)
        self.tenant_id.setText(profile.tenant_id)
        self.access_token.setText(profile.access_token)
        self.refresh_token.setText(profile.refresh_token)
        self.token_expires_at.setText(profile.token_expires_at)
        self.target_name.setText(profile.target_name)
        self.file_token.setText(profile.file_token)
        self.remote_url.setText(profile.remote_url)
        self.permission_mode.setCurrentIndex(max(self.permission_mode.findData(profile.permission_mode), 0))
        self.readonly_link_enabled.setChecked(profile.readonly_link_enabled)
        self.readonly_members.setPlainText(json.dumps(profile.readonly_members, ensure_ascii=False, indent=2) if profile.readonly_members else "")
        self.readonly_link_url.setText(profile.readonly_link_url)
        self.last_sync_at.setText(profile.last_sync_at)
        self.last_sync_status.setText(profile.last_sync_status)
        self.last_error.setPlainText(profile.last_error_message)

    def save(self) -> None:
        profile = self.build_profile()
        self.repository.save_profile(profile)
        self.accept()

    def build_profile(self) -> CloudSyncProfile:
        return CloudSyncProfile(
            site_id=self.site_id,
            enabled=self.enabled.isChecked(),
            auto_sync_after_export=self.auto_sync.isChecked(),
            sync_mode=str(self.sync_mode.currentData() or "manual"),
            access_token=self.access_token.text().strip(),
            refresh_token=self.refresh_token.text().strip(),
            token_expires_at=self.token_expires_at.text().strip(),
            app_id=self.app_id.text().strip(),
            tenant_id=self.tenant_id.text().strip(),
            target_name=self.target_name.text().strip() or f"{self.site_id}_轨旁AP业务",
            file_token=self.file_token.text().strip(),
            remote_url=self.remote_url.text().strip(),
            permission_mode=str(self.permission_mode.currentData() or "readonly_members"),
            readonly_members=self._parse_readonly_members(),
            readonly_link_enabled=self.readonly_link_enabled.isChecked(),
            readonly_link_url=self.readonly_link_url.text().strip(),
            last_sync_at=self.profile.last_sync_at,
            last_sync_status=self.profile.last_sync_status,
            last_error_message=self.profile.last_error_message,
        )

    def _parse_readonly_members(self) -> list[dict[str, str]]:
        text = self.readonly_members.toPlainText().strip()
        if not text:
            return []
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return [item for item in data if isinstance(item, dict)]
        except json.JSONDecodeError:
            pass
        return [{"account": line.strip(), "permission": "read"} for line in text.splitlines() if line.strip()]

    def test_connection(self) -> None:
        profile = self.build_profile()
        try:
            WpsKSheetClient(WpsAuthContext.from_profile(profile)).test_connection()
        except Exception as exc:
            QMessageBox.warning(self, "WPS在线表格同步", str(exc))
            return
        QMessageBox.information(self, "WPS在线表格同步", "连接配置可用")

    def clear_binding(self) -> None:
        self.file_token.clear()
        self.remote_url.clear()

    def open_document(self) -> None:
        url = self.remote_url.text().strip() or (f"https://kdocs.cn/l/{self.file_token.text().strip()}" if self.file_token.text().strip() else "")
        if url:
            webbrowser.open(url)

    def show_runs(self) -> None:
        runs = self.repository.list_runs(self.site_id)
        lines = []
        for run in runs[:20]:
            lines.append(f"{run.get('started_at') or ''} {run.get('status') or ''} rows={run.get('rows_total') or 0} {run.get('error_message') or ''}")
        QMessageBox.information(self, "WPS在线表格同步记录", "\n".join(lines) if lines else "暂无同步记录")

