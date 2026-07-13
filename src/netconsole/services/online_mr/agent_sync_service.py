from __future__ import annotations

import ipaddress
import json
from dataclasses import dataclass
from pathlib import Path

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.online_mr_agent import (
    OnlineMrAgentDeviceCandidate,
    OnlineMrAgentDeviceMatchStatus,
    OnlineMrAgentDeviceResolution,
    OnlineMrAgentImportStatus,
    OnlineMrAgentPackageInfo,
)
from netconsole.models.online_mr_application import OnlineMrExecutorKind, OnlineMrMappingState, OnlineMrPhase
from netconsole.models.task_state import TaskState
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.repositories.online_mr_task_session_repository import OnlineMrTaskSessionRepository
from netconsole.repositories.task_repository import TaskRepository
from netconsole.services.online_mr.errors import OnlineMrApplicationErrorCode


class OnlineMrAgentDeviceResolver:
    """只在当前局点正式 devices 表内按静态地址匹配，不查询 FIT-AP 资源表。"""

    def __init__(self, paths: PathResolver) -> None:
        self.paths = paths

    def resolve_device_by_ip(self, site_id: str, host: str) -> OnlineMrAgentDeviceResolution:
        normalized = _normalize_ip(host)
        site = _safe_site_id(site_id)
        if not site:
            return OnlineMrAgentDeviceResolution(
                status=OnlineMrAgentDeviceMatchStatus.NOT_FOUND,
                source_host=normalized,
                error_code=str(OnlineMrApplicationErrorCode.AGENT_DEVICE_MATCH_NOT_FOUND),
                message="目标局点标识无效",
            )
        if not normalized:
            return OnlineMrAgentDeviceResolution(
                status=OnlineMrAgentDeviceMatchStatus.NOT_FOUND,
                source_host=str(host or "").strip(),
                error_code=str(OnlineMrApplicationErrorCode.AGENT_DEVICE_MATCH_NOT_FOUND),
                message="Agent 包未提供可匹配的目标 IP",
            )
        database_path = self.paths.site_db_path(site)
        if not self.paths.site_dir(site).is_dir() or not database_path.is_file():
            return OnlineMrAgentDeviceResolution(
                status=OnlineMrAgentDeviceMatchStatus.NOT_FOUND,
                source_host=normalized,
                error_code=str(OnlineMrApplicationErrorCode.AGENT_DEVICE_MATCH_NOT_FOUND),
                message="目标局点不存在或没有设备数据库",
            )
        devices = DeviceRepository(Database(database_path)).list()
        matched = [
            device
            for device in devices
            if normalized
            in {
                _normalize_ip(device.primary_address),
                _normalize_ip(device.backup_address),
            }
        ]
        candidates = tuple(
            OnlineMrAgentDeviceCandidate(
                device_id=device.id or "",
                device_name=device.name,
                mr_id=str(device.id or ""),
                mr_name=device.name,
                host=normalized,
                device_type=str(device.device_type or ""),
            )
            for device in matched
        )
        if len(candidates) == 1:
            return OnlineMrAgentDeviceResolution(
                status=OnlineMrAgentDeviceMatchStatus.MATCHED,
                source_host=normalized,
                candidates=candidates,
            )
        if len(candidates) > 1:
            return OnlineMrAgentDeviceResolution(
                status=OnlineMrAgentDeviceMatchStatus.CONFLICT,
                source_host=normalized,
                candidates=candidates,
                error_code=str(OnlineMrApplicationErrorCode.AGENT_DEVICE_MATCH_CONFLICT),
                message="当前局点有多个设备使用相同 IP，不能自动选择",
            )
        return OnlineMrAgentDeviceResolution(
            status=OnlineMrAgentDeviceMatchStatus.NOT_FOUND,
            source_host=normalized,
            error_code=str(OnlineMrApplicationErrorCode.AGENT_DEVICE_MATCH_NOT_FOUND),
            message="当前局点没有匹配该 IP 的正式设备",
        )


@dataclass(frozen=True)
class OnlineMrAgentImportLookup:
    status: OnlineMrAgentImportStatus
    task_id: str = ""


class OnlineMrAgentImportStatusResolver:
    def __init__(self, paths: PathResolver) -> None:
        self.paths = paths

    def resolve(
        self,
        site_id: str,
        package: OnlineMrAgentPackageInfo,
        *,
        session_id: str,
        agent_id: str,
    ) -> OnlineMrAgentImportLookup:
        site = _safe_site_id(site_id)
        if not site:
            return OnlineMrAgentImportLookup(OnlineMrAgentImportStatus.UNKNOWN)
        root = self.paths.online_mr_root(site)
        if not root.is_dir():
            return OnlineMrAgentImportLookup(OnlineMrAgentImportStatus.NOT_IMPORTED)
        matches: list[tuple[Path, dict[str, object]]] = []
        for path in root.glob("*/sessions/*/import_manifest.json"):
            manifest = _read_json(path)
            if _same_remote_package(manifest, package, session_id):
                matches.append((path.parent, manifest))
        if not matches:
            return OnlineMrAgentImportLookup(OnlineMrAgentImportStatus.NOT_IMPORTED)
        if len(matches) != 1:
            return OnlineMrAgentImportLookup(OnlineMrAgentImportStatus.CONFLICT)
        session_dir, manifest = matches[0]
        if package.source_zip_sha256 and manifest.get("source_zip_sha256") != package.source_zip_sha256:
            return OnlineMrAgentImportLookup(OnlineMrAgentImportStatus.CONFLICT)
        if agent_id and str(manifest.get("agent_id") or "") not in {"", agent_id}:
            return OnlineMrAgentImportLookup(OnlineMrAgentImportStatus.CONFLICT)
        if session_id and str(manifest.get("session_id") or "") != session_id:
            return OnlineMrAgentImportLookup(OnlineMrAgentImportStatus.CONFLICT)
        task_id = str(manifest.get("controller_task_id") or "")
        mapping = OnlineMrTaskSessionRepository(
            self.paths.site_tasks_db_path(site), site_id=site
        ).get_by_session(session_id)
        task = TaskRepository(self.paths.site_tasks_db_path(site)).get(task_id) if task_id else None
        package_relative = str(manifest.get("package_relative_path") or "")
        package_path = (session_dir / package_relative).resolve()
        try:
            package_path.relative_to(session_dir.resolve())
            package_exists = package_relative.endswith(".zip") and package_path.is_file()
        except ValueError:
            package_exists = False
        valid = (
            task is not None
            and mapping is not None
            and mapping.controller_task_id == task_id
            and mapping.session_id == session_id
            and mapping.executor_kind is OnlineMrExecutorKind.AGENT
            and mapping.mapping_state is OnlineMrMappingState.TERMINAL
            and mapping.phase is OnlineMrPhase.TERMINAL
            and task.source == "agent"
            and task.status in {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}
            and package_exists
        )
        return OnlineMrAgentImportLookup(
            OnlineMrAgentImportStatus.ALREADY_IMPORTED if valid else OnlineMrAgentImportStatus.CONFLICT,
            task_id=task_id,
        )


def _same_remote_package(
    manifest: dict[str, object], package: OnlineMrAgentPackageInfo, session_id: str
) -> bool:
    package_id = str(manifest.get("source_package_id") or "")
    agent_task_id = str(manifest.get("agent_task_id") or "")
    imported_session_id = str(manifest.get("session_id") or "")
    return bool(
        (package.package_id and package_id == package.package_id)
        or (package.task_id and agent_task_id == package.task_id)
        or (session_id and imported_session_id == session_id)
    )


def _normalize_ip(value: object) -> str:
    text = str(value or "").strip()
    try:
        return str(ipaddress.ip_address(text))
    except ValueError:
        return ""


def _safe_site_id(value: object) -> str:
    site = str(value or "").strip()
    if (
        not site
        or site in {".", ".."}
        or Path(site).name != site
        or "/" in site
        or "\\" in site
        or ":" in site
        or any(ord(char) < 32 for char in site)
    ):
        return ""
    return site


def _read_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(value) if isinstance(value, dict) else {}


__all__ = [
    "OnlineMrAgentDeviceResolver",
    "OnlineMrAgentImportLookup",
    "OnlineMrAgentImportStatusResolver",
]
