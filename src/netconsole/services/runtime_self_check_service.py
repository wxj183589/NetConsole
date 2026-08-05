from __future__ import annotations

import sqlite3
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from netconsole.core import app_logger
from netconsole.core.build_metadata import current_build_metadata
from netconsole.core.database import Database
from netconsole.core.feature_flags import PACKAGED_PRODUCTION_FEATURE_IDS, FeatureGate
from netconsole.core.runtime_environment import is_packaged_runtime
from netconsole.core.settings import SettingsStore
from netconsole.models.api.system_settings import (
    RuntimeSelfCheckItemDTO,
    RuntimeSelfCheckSnapshotDTO,
)
from netconsole.services.tool_path_resolver import resolve_network_tool


_UNICODE_SAMPLE = "宁波地铁1号线 · 中文设备 · 任务已完成"
SelfCheckStatus = Literal["normal", "warning", "error"]


class RuntimeSelfCheckService:
    def __init__(
        self,
        paths,
        feature_gate: FeatureGate,
        site_name: str,
    ) -> None:
        self.paths = paths
        self.feature_gate = feature_gate
        self.site_name = site_name

    def run(
        self,
        *,
        backend_build_id: str,
        frontend_build_id: str,
    ) -> RuntimeSelfCheckSnapshotDTO:
        packaged = is_packaged_runtime()
        items = [
            self._backend_executable(packaged),
            self._build_contract(backend_build_id, frontend_build_id, packaged),
            self._feature_policy(packaged),
            self._current_site(),
            self._data_root_write(),
            self._database(
                "tasks_database",
                "任务数据库",
                self.paths.site_tasks_db_path(self.site_name),
            ),
            self._database(
                "devices_database",
                "设备数据库",
                self.paths.site_db_path(self.site_name),
            ),
            self._credential_storage(),
            self._tool("fping", "fping"),
            self._tool("iperf3", "iPerf3"),
            self._unicode_round_trip(),
        ]
        overall = _overall_status(items)
        app_logger.log_info(
            "CLEAN_INSTALL_SELF_CHECK_COMPLETED",
            f"status={overall}; packaged={packaged}; checks={len(items)}",
        )
        return RuntimeSelfCheckSnapshotDTO(
            status=overall,
            checked_at=datetime.now(UTC).isoformat(timespec="seconds"),
            packaged=packaged,
            unicode_sample=_UNICODE_SAMPLE,
            items=items,
        )

    @staticmethod
    def _backend_executable(packaged: bool) -> RuntimeSelfCheckItemDTO:
        exists = Path(sys.executable).is_file()
        if packaged and exists:
            return _item(
                "backend_executable",
                "Backend 可执行文件",
                "normal",
                "正式包 Backend 可执行文件可用。",
            )
        if exists:
            return _item(
                "backend_executable",
                "Backend 可执行文件",
                "warning",
                "当前为开发运行时，尚未验证正式 Backend 可执行文件。",
                "请在最终安装包中再次运行自检。",
            )
        return _item(
            "backend_executable",
            "Backend 可执行文件",
            "error",
            "Backend 可执行文件不存在。",
            "重新安装 NetConsole。",
        )

    def _build_contract(
        self,
        backend_build_id: str,
        frontend_build_id: str,
        packaged: bool,
    ) -> RuntimeSelfCheckItemDTO:
        build_info = dict(getattr(self.feature_gate, "build_info", {}) or {})
        build_metadata = current_build_metadata(self.paths.app_root)
        if packaged and (not backend_build_id or not frontend_build_id):
            return _item(
                "build_contract",
                "前后端构建一致性",
                "error",
                "正式包缺少构建标识。",
                "重新生成并安装完整发布包。",
            )
        if backend_build_id and frontend_build_id and backend_build_id != frontend_build_id:
            return _item(
                "build_contract",
                "前后端构建一致性",
                "error",
                "Frontend 与 Backend 构建标识不一致。",
                "清理旧安装后重新安装同一版本。",
            )
        if packaged and not build_info:
            return _item(
                "build_contract",
                "前后端构建一致性",
                "error",
                "正式包 build_info 缺失。",
                "重新生成发布基线和安装包。",
            )
        if packaged and (
            not build_metadata
            or bool(build_metadata.get("build_dirty"))
            or str(build_metadata.get("frontend_commit") or "")
            != str(build_metadata.get("backend_commit") or "")
            or str(build_metadata.get("git_commit_full") or "")
            != str(build_metadata.get("backend_commit") or "")
        ):
            return _item(
                "build_contract",
                "前后端构建一致性",
                "error",
                "正式包统一构建元数据缺失、dirty 或提交号不一致。",
                "从 clean commit 重新生成并安装完整发布包。",
            )
        return _item(
            "build_contract",
            "前后端构建一致性",
            "normal",
            "版本与构建标识一致。",
        )

    def _feature_policy(self, packaged: bool) -> RuntimeSelfCheckItemDTO:
        missing = [
            feature
            for feature in PACKAGED_PRODUCTION_FEATURE_IDS
            if not self.feature_gate.is_visible(feature)
            or not self.feature_gate.is_enabled(feature)
        ]
        configuration_open = self.feature_gate.is_feature_configuration_available()
        if packaged and (missing or configuration_open):
            return _item(
                "production_feature_policy",
                "生产功能策略",
                "error",
                "正式包生产功能策略异常。",
                "重新安装包含只读生产基线的正式包。",
            )
        if not packaged:
            return _item(
                "production_feature_policy",
                "生产功能策略",
                "warning",
                "当前为开发策略，正式包策略尚待安装验收。",
                "在最终安装包中再次运行自检。",
            )
        return _item(
            "production_feature_policy",
            "生产功能策略",
            "normal",
            "只读生产功能策略已加载，核心业务功能可用。",
        )

    def _current_site(self) -> RuntimeSelfCheckItemDTO:
        root = self.paths.site_dir(self.site_name)
        if root.is_dir():
            return _item(
                "current_site", "当前局点", "normal", "当前局点目录可用。"
            )
        return _item(
            "current_site",
            "当前局点",
            "error",
            "当前局点目录不存在。",
            "在局点管理中创建或切换局点。",
        )

    def _data_root_write(self) -> RuntimeSelfCheckItemDTO:
        marker = self.paths.temp_dir / f"self-check-{uuid.uuid4().hex}.tmp"
        try:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(_UNICODE_SAMPLE, encoding="utf-8")
            if marker.read_text(encoding="utf-8") != _UNICODE_SAMPLE:
                raise OSError("round trip mismatch")
        except OSError:
            return _item(
                "data_root_writable",
                "数据根可写",
                "error",
                "数据根写入校验失败。",
                "检查 D:\\NetConsoleData 的目录权限和磁盘空间。",
            )
        finally:
            marker.unlink(missing_ok=True)
        return _item("data_root_writable", "数据根可写", "normal", "数据根 UTF-8 读写正常。")

    @staticmethod
    def _database(check_id: str, title: str, path: Path) -> RuntimeSelfCheckItemDTO:
        if not path.is_file():
            return _item(
                check_id,
                title,
                "error",
                f"{title}不存在。",
                "重新启动软件或检查当前局点。",
            )
        try:
            with sqlite3.connect(path, timeout=2) as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("CREATE TEMP TABLE netconsole_self_check(value TEXT)")
                connection.execute("INSERT INTO netconsole_self_check VALUES (?)", (_UNICODE_SAMPLE,))
                value = connection.execute("SELECT value FROM netconsole_self_check").fetchone()
                connection.rollback()
            if not value or value[0] != _UNICODE_SAMPLE:
                raise sqlite3.DatabaseError("unicode mismatch")
        except (OSError, sqlite3.DatabaseError):
            return _item(
                check_id,
                title,
                "error",
                f"{title}读写校验失败。",
                "关闭占用数据库的外部程序并重试。",
            )
        return _item(check_id, title, "normal", f"{title}读写正常。")

    def _credential_storage(self) -> RuntimeSelfCheckItemDTO:
        path = self.paths.site_db_path(self.site_name)
        try:
            with Database(path).connect() as connection:
                row = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                    "AND name = 'device_credential_states'"
                ).fetchone()
        except sqlite3.DatabaseError:
            row = None
        if row:
            return _item(
                "credential_storage",
                "设备凭据状态",
                "normal",
                "设备凭据状态表可用；局点包凭据重录标记可持久化。",
            )
        return _item(
            "credential_storage",
            "设备凭据状态",
            "error",
            "设备凭据状态表不可用。",
            "重启软件以完成数据库兼容升级。",
        )

    def _tool(self, tool_id: str, title: str) -> RuntimeSelfCheckItemDTO:
        resolution = resolve_network_tool(tool_id, self.paths, settings=SettingsStore(self.paths))
        path = resolution.effective_path
        if path is not None and path.is_file():
            status = "warning" if resolution.fallback_used else "normal"
            message = resolution.fallback_reason or f"{title} {resolution.source} 组件可用。"
            return _item(f"tool_{tool_id}", title, status, message)
        return _item(
            f"tool_{tool_id}",
            title,
            "warning",
            resolution.validation_message,
            "在工具集的网络测试组件页面恢复内置组件，或选择有效的自定义组件。",
        )

    @staticmethod
    def _unicode_round_trip() -> RuntimeSelfCheckItemDTO:
        with sqlite3.connect(":memory:") as connection:
            connection.execute("CREATE TABLE probe(value TEXT)")
            connection.execute("INSERT INTO probe VALUES (?)", (_UNICODE_SAMPLE,))
            value = connection.execute("SELECT value FROM probe").fetchone()
        if value and value[0] == _UNICODE_SAMPLE:
            return _item(
                "unicode_round_trip",
                "Windows 中文编码",
                "normal",
                "Python、SQLite 与 JSON Unicode 基线正常。",
            )
        return _item(
            "unicode_round_trip",
            "Windows 中文编码",
            "error",
            "Unicode 往返校验失败。",
            "保留日志并联系维护人员。",
        )


def _item(
    check_id: str,
    title: str,
    status: SelfCheckStatus,
    message: str,
    suggestion: str = "",
) -> RuntimeSelfCheckItemDTO:
    return RuntimeSelfCheckItemDTO(
        check_id=check_id,
        title=title,
        status=status,
        message=message,
        suggestion=suggestion,
    )


def _overall_status(items: list[RuntimeSelfCheckItemDTO]) -> SelfCheckStatus:
    statuses = {item.status for item in items}
    if "error" in statuses:
        return "error"
    if "warning" in statuses:
        return "warning"
    return "normal"


__all__ = ["RuntimeSelfCheckService"]
