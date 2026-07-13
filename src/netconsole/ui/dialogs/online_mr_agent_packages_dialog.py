from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.models.agent import AgentAuthenticationType
from netconsole.models.device import Device
from netconsole.models.online_mr_agent import OnlineMrAgentImportStatus
from netconsole.services.agent.controller import AgentControllerService
from netconsole.services.background_job import BackgroundJob
from netconsole.ui.dialogs.dialog_style import apply_dialog_style
from netconsole.ui.dialogs.message_service import MessageBox, confirm
from netconsole.ui.job_action_helper import submit_background_job
from netconsole.ui.table_utils import auto_fit_table_columns, configure_readonly_table, make_table_item

AGENT_TOKEN_ENV = "NETCONSOLE_JOB_SECRET_ONLINE_MR_AGENT_TOKEN"
JobSubmitter = Callable[..., str]


class OnlineMrAgentPackagesDialog(QDialog):
    """Qt 侧既有 Agent 包同步/导入入口，不提供远程任务控制。"""

    def __init__(
        self,
        *,
        paths: PathResolver,
        site_name: str,
        i18n: I18n,
        devices: Iterable[Device],
        parent: QWidget | None = None,
        profile_controller: AgentControllerService | None = None,
        job_submitter: JobSubmitter = submit_background_job,
    ) -> None:
        super().__init__(parent)
        self.paths = paths
        self.site_name = site_name
        self.i18n = i18n
        self.devices = tuple(device for device in devices if device.id is not None)
        self.profile_controller = profile_controller or AgentControllerService(paths=paths, site_name=site_name)
        self.job_submitter = job_submitter
        self.profiles: dict[str, dict[str, Any]] = {}
        self.packages: dict[str, dict[str, Any]] = {}
        self._job_running = False
        self._last_import_dir: Path | None = None
        self._acceptance_command = ""

        self.profile_combo = QComboBox()
        self.base_url_edit = QLineEdit("http://127.0.0.1:18080")
        self.token_edit = QLineEdit()
        self.token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.refresh_button = QPushButton(self._t("online_mr.agent_packages.refresh"))
        self.agent_status_label = QLabel(self._t("online_mr.agent_packages.not_refreshed"))
        self.tools_status_label = QLabel(self._t("online_mr.agent_packages.tools_not_refreshed"))
        self.table = QTableWidget(0, 11)
        self.device_combo = QComboBox()
        self.import_button = QPushButton(self._t("online_mr.agent_packages.import_matched"))
        self.manual_import_button = QPushButton(self._t("online_mr.agent_packages.import_manual"))
        self.copy_package_id_button = QPushButton(self._t("online_mr.agent_packages.copy_package_id"))
        self.open_import_dir_button = QPushButton(self._t("online_mr.agent_packages.open_import_dir"))
        self.copy_acceptance_command_button = QPushButton(
            self._t("online_mr.agent_packages.copy_acceptance_command")
        )
        self.result_label = QLabel(self._t("online_mr.agent_packages.no_import_result"))
        self.close_button = QPushButton(self._t("online_mr.agent_packages.close"))
        self.hint_label = QLabel(self._t("online_mr.agent_packages.boundary_hint"))

        self._build_ui()
        self._load_profiles()
        self._load_devices()
        self._connect_signals()
        self._update_actions()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        form.addRow(self._t("online_mr.agent_packages.profile"), self.profile_combo)
        form.addRow(self._t("online_mr.agent_packages.base_url"), self.base_url_edit)
        form.addRow(self._t("online_mr.agent_packages.token"), self.token_edit)
        layout.addLayout(form)

        actions = QHBoxLayout()
        actions.addWidget(self.refresh_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        for label in (self.agent_status_label, self.tools_status_label, self.hint_label):
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            label.setWordWrap(True)
        layout.addWidget(self.agent_status_label)
        layout.addWidget(self.tools_status_label)

        self.table.setHorizontalHeaderLabels(
            [
                self._t("online_mr.agent_packages.package_id"),
                self._t("online_mr.agent_packages.task_type"),
                self._t("online_mr.agent_packages.remote_status"),
                self._t("online_mr.agent_packages.time"),
                self._t("online_mr.agent_packages.size"),
                self._t("online_mr.agent_packages.source_host"),
                self._t("online_mr.agent_packages.source_device"),
                self._t("online_mr.agent_packages.local_candidate"),
                self._t("online_mr.agent_packages.match_status"),
                self._t("online_mr.agent_packages.import_status"),
                self._t("online_mr.agent_packages.file_name"),
            ]
        )
        configure_readonly_table(self.table)
        self.table.setMinimumHeight(280)
        layout.addWidget(self.table, 1)

        manual_row = QHBoxLayout()
        manual_row.addWidget(QLabel(self._t("online_mr.agent_packages.manual_device")))
        manual_row.addWidget(self.device_combo, 1)
        manual_row.addWidget(self.import_button)
        manual_row.addWidget(self.manual_import_button)
        layout.addLayout(manual_row)

        result_actions = QHBoxLayout()
        result_actions.addWidget(self.copy_package_id_button)
        result_actions.addWidget(self.open_import_dir_button)
        result_actions.addWidget(self.copy_acceptance_command_button)
        result_actions.addStretch(1)
        layout.addLayout(result_actions)
        self.result_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.result_label.setWordWrap(True)
        layout.addWidget(self.result_label)
        layout.addWidget(self.hint_label)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_row.addWidget(self.close_button)
        layout.addLayout(close_row)
        apply_dialog_style(
            self,
            title=self._t("online_mr.agent_packages.title"),
            minimum_size=(760, 520),
            default_size=(1180, 720),
            delete_on_close=True,
            center=False,
        )

    def _connect_signals(self) -> None:
        self.profile_combo.currentIndexChanged.connect(self._profile_changed)
        self.refresh_button.clicked.connect(self.refresh_packages)
        self.table.itemSelectionChanged.connect(self._update_actions)
        self.import_button.clicked.connect(self.import_matched_package)
        self.manual_import_button.clicked.connect(self.import_manual_package)
        self.copy_package_id_button.clicked.connect(self.copy_selected_package_id)
        self.open_import_dir_button.clicked.connect(self.open_import_dir)
        self.copy_acceptance_command_button.clicked.connect(self.copy_acceptance_command)
        self.close_button.clicked.connect(self.close)

    def _load_profiles(self) -> None:
        self.profile_combo.clear()
        self.profile_combo.addItem(self._t("online_mr.agent_packages.temporary_profile"), "")
        try:
            records = self.profile_controller.list_agents()
        except Exception as exc:
            records = []
            self.agent_status_label.setText(self._t("online_mr.agent_packages.profile_load_failed", error=str(exc)))
        for record in records:
            profile_id = str(record.get("agent_id") or "")
            if not profile_id:
                continue
            self.profiles[profile_id] = dict(record)
            suffix = "" if bool(record.get("enabled", True)) else self._t("online_mr.agent_packages.disabled_suffix")
            label = f"{record.get('name') or profile_id} · {record.get('base_url') or ''}{suffix}"
            self.profile_combo.addItem(label, profile_id)
        self._profile_changed()

    def _load_devices(self) -> None:
        self.device_combo.clear()
        ordered = sorted(self.devices, key=lambda item: (item.name.casefold(), item.primary_address))
        for device in ordered:
            self.device_combo.addItem(
                f"{device.name} · {device.primary_address}",
                {
                    "device_id": device.id,
                    "device_name": device.name,
                    "mr_id": str(device.id or ""),
                    "mr_name": device.name,
                    "host": device.primary_address,
                },
            )

    def _profile_changed(self) -> None:
        profile_id = str(self.profile_combo.currentData() or "")
        profile = self.profiles.get(profile_id)
        self.base_url_edit.setReadOnly(profile is not None)
        if profile is not None:
            self.base_url_edit.setText(str(profile.get("base_url") or ""))
        self.token_edit.clear()
        self.token_edit.setPlaceholderText(self._t("online_mr.agent_packages.token_placeholder"))

    def refresh_packages(self) -> None:
        if self._job_running:
            return
        prepared = self._connection_job_parts()
        if prepared is None:
            return
        params, environment = prepared
        self._set_job_running(True)
        self.job_submitter(
            self,
            BackgroundJob(task_type="online_mr_agent_packages_sync", params=params),
            paths=self.paths,
            environment=environment,
            success_title=self._t("online_mr.agent_packages.sync_done"),
            progress_title=self._t("online_mr.agent_packages.syncing"),
            on_finished=self._sync_finished,
            on_failed=self._job_failed,
            on_cancelled=self._job_cancelled,
        )

    def import_matched_package(self) -> None:
        package = self._selected_package()
        if package is None or not self._can_auto_import(package):
            return
        candidate = dict(package.get("candidate_local_device") or {})
        message = self._t(
            "online_mr.agent_packages.confirm_matched",
            package_id=str(package.get("package_id") or ""),
            device=str(candidate.get("device_name") or ""),
        )
        if MessageBox.question(self, self.windowTitle(), message) != MessageBox.Yes:
            return
        self._submit_import(package, manual_device=None)

    def import_manual_package(self) -> None:
        package = self._selected_package()
        device = self.device_combo.currentData()
        if package is None or not self._can_manual_import(package) or not isinstance(device, dict):
            return
        message = self._t(
            "online_mr.agent_packages.confirm_manual",
            package_id=str(package.get("package_id") or ""),
            source=str(package.get("source_device_name") or package.get("source_host") or "-"),
            device=str(device.get("device_name") or ""),
            host=str(device.get("host") or ""),
        )
        if not confirm(self, self.windowTitle(), message, danger=True):
            return
        self._submit_import(package, manual_device=dict(device))

    def _submit_import(self, package: dict[str, Any], manual_device: dict[str, Any] | None) -> None:
        if self._job_running:
            return
        prepared = self._connection_job_parts()
        if prepared is None:
            return
        params, environment = prepared
        params.update(
            {
                "package_id": str(package.get("package_id") or ""),
                "manual_override": manual_device is not None,
                "expected_host": str((manual_device or {}).get("host") or ""),
                **(manual_device or {}),
            }
        )
        self._set_job_running(True)
        self.job_submitter(
            self,
            BackgroundJob(task_type="online_mr_agent_package_import", params=params),
            paths=self.paths,
            environment=environment,
            success_title=self._t("online_mr.agent_packages.import_done"),
            progress_title=self._t("online_mr.agent_packages.importing"),
            on_finished=self._import_finished,
            on_failed=self._job_failed,
            on_cancelled=self._job_cancelled,
        )

    def _connection_job_parts(self) -> tuple[dict[str, Any], dict[str, str]] | None:
        base_url = self.base_url_edit.text().strip()
        if not base_url:
            MessageBox.warning(self, self.windowTitle(), self._t("online_mr.agent_packages.base_url_required"))
            return None
        profile_id = str(self.profile_combo.currentData() or "")
        profile = self.profiles.get(profile_id, {})
        if profile and not bool(profile.get("enabled", True)):
            MessageBox.warning(self, self.windowTitle(), self._t("online_mr.agent_packages.profile_disabled"))
            return None
        token = self.token_edit.text()
        authentication_type = str(profile.get("authentication_type") or AgentAuthenticationType.NONE.value)
        if token:
            authentication_type = AgentAuthenticationType.TOKEN.value
        if authentication_type == AgentAuthenticationType.TOKEN.value and not token:
            MessageBox.warning(self, self.windowTitle(), self._t("online_mr.agent_packages.token_required"))
            return None
        params = {
            "site_id": self.site_name,
            "site_name": self.site_name,
            "profile_id": profile_id,
            "base_url": base_url,
            "authentication_type": authentication_type,
        }
        environment = {AGENT_TOKEN_ENV: token} if token else {}
        return params, environment

    def _sync_finished(self, payload: dict[str, Any]) -> None:
        self._set_job_running(False)
        result = dict(payload.get("result") or {})
        self._apply_sync_result(result)

    def _apply_sync_result(self, result: dict[str, Any]) -> None:
        status = dict(result.get("agent_status") or {})
        tools = dict(result.get("tools") or {})
        self.agent_status_label.setText(
            self._t(
                "online_mr.agent_packages.agent_status",
                name=str(status.get("agent_name") or status.get("agent_id") or "-"),
                version=str(status.get("version") or "-"),
                platform=f"{status.get('os') or '-'} / {status.get('arch') or '-'}",
                count=int(status.get("package_count") or 0),
            )
        )
        self.tools_status_label.setText(
            self._t(
                "online_mr.agent_packages.tools_status",
                mr=self._tool_text(tools.get("mr_collector")),
                fping=self._tool_text(tools.get("fping")),
                iperf=self._tool_text(tools.get("iperf3")),
            )
        )
        packages = [dict(item) for item in list(result.get("packages") or []) if isinstance(item, dict)]
        self.packages = {str(item.get("package_id") or ""): item for item in packages}
        self.table.setRowCount(len(packages))
        for row, package in enumerate(packages):
            candidate = dict(package.get("candidate_local_device") or {})
            candidates = [dict(item) for item in list(package.get("candidate_local_devices") or []) if isinstance(item, dict)]
            candidate_text = str(candidate.get("device_name") or "")
            if not candidate_text and candidates:
                candidate_text = " / ".join(str(item.get("device_name") or "") for item in candidates)
            values = (
                package.get("package_id"),
                package.get("task_type"),
                package.get("status"),
                package.get("end_time") or package.get("created_at") or package.get("start_time"),
                self._format_size(int(package.get("size") or 0)),
                package.get("source_host"),
                package.get("source_device_name") or package.get("source_device_id"),
                candidate_text or "-",
                self._match_status_text(str(package.get("candidate_match_method") or "")),
                self._import_status_text(str(package.get("import_status") or "")),
                package.get("file_name"),
            )
            for column, value in enumerate(values):
                item = make_table_item(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, package)
                self.table.setItem(row, column, item)
        if packages:
            self.table.selectRow(0)
        auto_fit_table_columns(self.table, max_rows=200, max_widths={0: 260, 10: 320})
        self._update_actions()

    def _import_finished(self, payload: dict[str, Any]) -> None:
        self._set_job_running(False)
        result = dict(payload.get("result") or {})
        task_id = str(result.get("task_id") or "")
        session_id = str(result.get("session_id") or "")
        session_dir_text = str(result.get("session_dir") or "")
        self._last_import_dir = Path(session_dir_text) if session_dir_text else None
        self._acceptance_command = self._build_acceptance_command(task_id=task_id, session_id=session_id)
        self.result_label.setText(
            self._t(
                "online_mr.agent_packages.import_result",
                task_id=task_id or "-",
                session_id=session_id or "-",
                session_dir=session_dir_text or "-",
            )
        )
        if bool(result.get("already_imported")):
            MessageBox.information(self, self.windowTitle(), self._t("online_mr.agent_packages.already_imported"))
        elif result.get("warnings"):
            MessageBox.warning(self, self.windowTitle(), "\n".join(str(item) for item in result["warnings"]))
        self._update_actions()
        self.refresh_packages()

    def copy_selected_package_id(self) -> None:
        package = self._selected_package()
        package_id = str((package or {}).get("package_id") or "")
        if package_id:
            QGuiApplication.clipboard().setText(package_id)

    def open_import_dir(self) -> None:
        if self._last_import_dir is not None and self._last_import_dir.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._last_import_dir)))

    def copy_acceptance_command(self) -> None:
        if self._acceptance_command:
            QGuiApplication.clipboard().setText(self._acceptance_command)

    def _build_acceptance_command(self, *, task_id: str, session_id: str) -> str:
        if task_id:
            return f'python -m scripts.maintenance.check_online_mr_session_state --task-id "{task_id}"'
        if session_id:
            return (
                "python -m scripts.maintenance.check_online_mr_session_state "
                f'--site "{self.site_name}" --session-id "{session_id}"'
            )
        return ""

    def _job_failed(self, _payload: dict[str, Any]) -> None:
        self._set_job_running(False)

    def _job_cancelled(self, _payload: dict[str, Any]) -> None:
        self._set_job_running(False)

    def _set_job_running(self, running: bool) -> None:
        self._job_running = running
        self.profile_combo.setEnabled(not running)
        self.base_url_edit.setEnabled(not running)
        self.token_edit.setEnabled(not running)
        self.refresh_button.setEnabled(not running)
        self._update_actions()

    def _selected_package(self) -> dict[str, Any] | None:
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        value = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        return dict(value) if isinstance(value, dict) else None

    def _update_actions(self) -> None:
        package = self._selected_package()
        self.import_button.setEnabled(not self._job_running and package is not None and self._can_auto_import(package))
        self.manual_import_button.setEnabled(
            not self._job_running and package is not None and self._can_manual_import(package)
        )
        self.copy_package_id_button.setEnabled(package is not None)
        self.open_import_dir_button.setEnabled(
            self._last_import_dir is not None and self._last_import_dir.is_dir()
        )
        self.copy_acceptance_command_button.setEnabled(bool(self._acceptance_command))
        self.device_combo.setEnabled(not self._job_running and bool(self.devices))

    @staticmethod
    def _can_auto_import(package: dict[str, Any]) -> bool:
        status = str(package.get("import_status") or "")
        return bool(package.get("package_id")) and status == OnlineMrAgentImportStatus.NOT_IMPORTED.value and bool(
            package.get("candidate_local_device")
        )

    def _can_manual_import(self, package: dict[str, Any]) -> bool:
        status = str(package.get("import_status") or "")
        return bool(self.devices) and bool(package.get("package_id")) and status == OnlineMrAgentImportStatus.NOT_IMPORTED.value

    def _tool_text(self, raw: object) -> str:
        tool = dict(raw) if isinstance(raw, dict) else {}
        state = self._t(
            "online_mr.agent_packages.tool_ready"
            if bool(tool.get("ready"))
            else "online_mr.agent_packages.tool_not_ready"
        )
        version = str(tool.get("version") or "")
        return f"{state} ({version})" if version else state

    def _match_status_text(self, status: str) -> str:
        return self._t(
            {
                "ip_match": "online_mr.agent_packages.match_ip",
                "matched": "online_mr.agent_packages.match_ip",
                "not_found": "online_mr.agent_packages.match_none",
                "conflict": "online_mr.agent_packages.match_conflict",
            }.get(status, "online_mr.agent_packages.match_unknown")
        )

    def _import_status_text(self, status: str) -> str:
        return self._t(
            {
                "not_imported": "online_mr.agent_packages.import_not_imported",
                "already_imported": "online_mr.agent_packages.import_already",
                "imported": "online_mr.agent_packages.import_already",
                "conflict": "online_mr.agent_packages.import_conflict",
            }.get(status, "online_mr.agent_packages.import_unknown")
        )

    @staticmethod
    def _format_size(size: int) -> str:
        value = float(max(size, 0))
        for unit in ("B", "KiB", "MiB", "GiB"):
            if value < 1024 or unit == "GiB":
                return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
            value /= 1024
        return f"{size} B"

    def _t(self, key: str, **kwargs: object) -> str:
        return self.i18n.t(key, **kwargs)


__all__ = ["OnlineMrAgentPackagesDialog"]
