from __future__ import annotations

import json
import re
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.core.sites import SiteManager
from netconsole.models.api.config_collection import (
    ConfigDirectoryDTO,
    ConfigDeviceDTO,
    ConfigDeviceGroupDTO,
    ConfigDevicePageDTO,
    ConfigSnapshotDTO,
    ConfigTaskReferenceDTO,
    ConfigTaskStatusDTO,
)
from netconsole.models.device import Device
from netconsole.models.task_snapshot import TaskSnapshot
from netconsole.models.task_state import TaskState
from netconsole.repositories.config_snapshot_repository import ConfigSnapshot, ConfigSnapshotRepository
from netconsole.repositories.device_group_repository import DeviceGroupRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.background_job import BackgroundJob
from netconsole.services.config_lifecycle_service import safe_device_name
from netconsole.services.job_center.local_process_adapter import LocalProcessAdapter
from netconsole.services.job_center.task_application_service import TaskApplicationService


CONFIG_COLLECTION_ACTIONS = {"fetch": "config_web_snapshot_fetch"}
CONFIG_WEB_OWNER = "web_config_collection"
ACTIVE_TASK_STATES = {TaskState.PENDING, TaskState.STARTING, TaskState.RUNNING, TaskState.STOPPING}
CONFIG_WEB_TASK_TYPES = frozenset(
    {
        "config_web_snapshot_fetch",
        "config_snapshot_load_content",
        "config_compare_latest_snapshots",
        "config_compare_latest_running_between_devices",
        "config_compare_snapshot_pair",
        "config_snapshot_delete_many",
    }
)
CONFIG_WEB_COMPARE_TASK_TYPES = frozenset(
    {
        "config_compare_latest_snapshots",
        "config_compare_latest_running_between_devices",
        "config_compare_snapshot_pair",
    }
)
_SNAPSHOT_ARTIFACT_RE = re.compile(r"snapshot-(\d+)")
_DIFF_ARTIFACT_RE = re.compile(r"diff-([0-9A-Za-z_.-]+)")
_ABSOLUTE_PATH_RE = re.compile(r"(?i)(?:file://[^\s\"']+|[a-z]:[\\/][^\s\"']+|\\\\[^\\/\s]+[\\/][^\s\"']+)")
_SECRET_VALUE_RE = re.compile(
    r"(?i)\b((?:x-agent-token|authorization|token|password|credential|secret|community)\s*[:=]\s*(?:bearer\s+)?)\S+"
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")


class ConfigCollectionApplicationService:
    """配置中心 Web 适配层；设备 IO 统一交给现有 Job Center Worker。"""

    def __init__(
        self,
        paths: PathResolver,
        task_service: TaskApplicationService,
        process_adapter: LocalProcessAdapter | None = None,
    ) -> None:
        self.paths = paths
        self.task_service = task_service
        self.process_adapter = process_adapter or LocalProcessAdapter(task_service)
        self._start_lock = RLock()

    def close(self) -> None:
        self.process_adapter.shutdown()

    def current_site_id(self) -> str:
        try:
            payload = json.loads(self.paths.app_config_path.read_text(encoding="utf-8"))
            value = payload.get("current_site") if isinstance(payload, dict) else "demo"
            return SiteManager(self.paths).validate_site_name(str(value or "demo"))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return "demo"

    def list_devices(
        self,
        site_name: str,
        *,
        search: str = "",
        group_filter: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> ConfigDevicePageDTO:
        database = self._database(site_name)
        if not database.path.is_file():
            return ConfigDevicePageDTO(page=page, page_size=page_size)
        devices = DeviceRepository(database).list(
            search=str(search or "").strip() or None,
            vendor="H3C",
            group_filter=self._group_filter(group_filter),
        )
        current_page = max(1, int(page))
        size = max(1, min(int(page_size), 200))
        total = len(devices)
        total_pages = max(1, (total + size - 1) // size)
        current_page = min(current_page, total_pages)
        start = (current_page - 1) * size
        groups = self._groups(database, site_name)
        return ConfigDevicePageDTO(
            items=[self._device_dto(device) for device in devices[start : start + size]],
            total=total,
            page=current_page,
            page_size=size,
            total_pages=total_pages,
            groups=groups,
        )

    def list_snapshots(self, site_name: str, device_id: int, snapshot_type: str = "") -> list[ConfigSnapshotDTO]:
        device, _repository, service = self._device_context(site_name, device_id)
        snapshots = service.list_device_snapshots(device, str(snapshot_type or "").strip() or None)
        return [
            self._snapshot_dto(site_name, device, snapshot, self._snapshot_path(site_name, snapshot))
            for snapshot in snapshots
            if self._safe_snapshot_path(site_name, snapshot) is not None
        ]

    def submit_collection(self, site_name: str, action: str, device_ids: list[int]) -> list[ConfigTaskReferenceDTO]:
        task_type = CONFIG_COLLECTION_ACTIONS.get(str(action or "").strip().lower())
        if task_type is None:
            raise ValueError("不支持的配置操作")
        if not device_ids or len(device_ids) > 50:
            raise ValueError("一次最多选择 50 台设备")
        database = self._database(site_name)
        repository = DeviceRepository(database)
        devices = [self._h3c_device(repository, int(device_id)) for device_id in dict.fromkeys(device_ids)]
        return [self._start_device_job(site_name, task_type, device) for device in devices]

    def submit_snapshot_content(self, site_name: str, snapshot_id: int) -> ConfigTaskReferenceDTO:
        self._snapshot_context(site_name, snapshot_id)
        return self._start_job(
            site_name,
            "config_snapshot_load_content",
            {"snapshot_id": int(snapshot_id), "max_chars": 2_000_000},
            "读取配置快照",
        )

    def submit_latest_diff(self, site_name: str, device_id: int) -> ConfigTaskReferenceDTO:
        database = self._database(site_name)
        device = self._h3c_device(DeviceRepository(database), device_id)
        return self._start_job(
            site_name,
            "config_compare_latest_snapshots",
            {"device_uuid": str(device.device_uuid or "")},
            f"比较配置 · {device.name or device.device_uuid}",
        )

    def submit_snapshot_diff(self, site_name: str, left_snapshot_id: int, right_snapshot_id: int) -> ConfigTaskReferenceDTO:
        self._snapshot_context(site_name, left_snapshot_id)
        self._snapshot_context(site_name, right_snapshot_id)
        return self._start_job(
            site_name,
            "config_compare_snapshot_pair",
            {"left_snapshot_id": int(left_snapshot_id), "right_snapshot_id": int(right_snapshot_id)},
            "比较配置快照",
        )

    def submit_device_diff(self, site_name: str, left_device_id: int, right_device_id: int) -> ConfigTaskReferenceDTO:
        database = self._database(site_name)
        repository = DeviceRepository(database)
        left = self._h3c_device(repository, left_device_id)
        right = self._h3c_device(repository, right_device_id)
        return self._start_job(
            site_name,
            "config_compare_latest_running_between_devices",
            {"device_uuid_a": str(left.device_uuid or ""), "device_uuid_b": str(right.device_uuid or "")},
            f"比较设备 · {left.name} / {right.name}",
        )

    def submit_snapshot_delete(self, site_name: str, snapshot_ids: list[int]) -> ConfigTaskReferenceDTO:
        if not snapshot_ids or len(snapshot_ids) > 50:
            raise ValueError("一次最多删除 50 个配置快照")
        ids = list(dict.fromkeys(int(value) for value in snapshot_ids))
        for snapshot_id in ids:
            self._snapshot_context(site_name, snapshot_id)
        return self._start_job(site_name, "config_snapshot_delete_many", {"snapshot_ids": ids}, "删除配置快照")

    def cancel_task(self, site_name: str, task_id: str) -> ConfigTaskStatusDTO | None:
        task = self.task_service.repository(site_name).get(str(task_id or ""))
        if not self._is_web_task(task):
            return None
        if task.status not in ACTIVE_TASK_STATES:
            return self._task_dto(task)
        cancel = getattr(self.process_adapter, "cancel_job", None)
        if callable(cancel):
            cancel(task.task_id)
        else:
            self.task_service.cancel_task(task.task_id)
        return self._task_dto(self.task_service.repository(site_name).get(task.task_id) or task)

    def directory_info(self, site_name: str, directory_kind: str) -> ConfigDirectoryDTO:
        kind = str(directory_kind or "").strip()
        if kind not in {"config_snapshots", "config_exports"}:
            raise ValueError("结果目录类型无效")
        directory = self.paths.config_center_root(site_name) / ("snapshots" if kind == "config_snapshots" else "outputs")
        return ConfigDirectoryDTO(
            directory_kind=kind,
            available=directory.is_dir(),
            message="Browser/Server 模式不直接打开本机目录，请使用 Artifact 下载。",
        )

    def list_tasks(self, site_name: str, limit: int = 100) -> list[ConfigTaskStatusDTO]:
        snapshots = self.task_service.repository(site_name).list(limit=max(1, min(int(limit), 200)))
        return [
            self._task_dto(snapshot)
            for snapshot in snapshots
            if snapshot.source == "local"
            and snapshot.owner == CONFIG_WEB_OWNER
            and snapshot.task_type in CONFIG_WEB_TASK_TYPES
        ]

    def get_task(self, site_name: str, task_id: str, diff_filter: str = "all") -> ConfigTaskStatusDTO | None:
        snapshot = self.task_service.repository(site_name).get(str(task_id))
        if not self._is_web_task(snapshot):
            return None
        return self._task_dto(snapshot, diff_filter=diff_filter)

    def open_artifact(self, site_name: str, artifact_id: str) -> tuple[Path, str]:
        value = str(artifact_id or "")
        snapshot_match = _SNAPSHOT_ARTIFACT_RE.fullmatch(value)
        if snapshot_match:
            snapshot_id = int(snapshot_match.group(1))
            snapshot = self._snapshot_context(site_name, snapshot_id)[0]
            path = self._safe_snapshot_path(site_name, snapshot)
            if path is None:
                raise FileNotFoundError("配置快照不存在")
            name = f"{safe_device_name(str(snapshot.device_uuid or 'device'))}_{snapshot.type}_{snapshot.timestamp}"
            return path, f"{name}{'.diff' if snapshot.type == 'diff' else '.txt'}"
        diff_match = _DIFF_ARTIFACT_RE.fullmatch(value)
        if diff_match:
            task_id = diff_match.group(1)
            task = self.task_service.repository(site_name).get(task_id)
            if task is None:
                raise FileNotFoundError("配置差异 Artifact 不存在")
            if (
                task.source != "local"
                or task.owner != CONFIG_WEB_OWNER
                or task.task_type not in CONFIG_WEB_COMPARE_TASK_TYPES
            ):
                raise FileNotFoundError("配置差异 Artifact 不存在")
            raw_path = str(task.result.get("diff_file") or "")
            path = Path(raw_path)
            root = (self.paths.runtime_cache_dir / "config_diff").resolve()
            if path.is_symlink():
                raise FileNotFoundError("配置差异 Artifact 不存在")
            resolved = path.resolve()
            if root not in resolved.parents or not resolved.is_file() or resolved.is_symlink():
                raise FileNotFoundError("配置差异 Artifact 不存在")
            return resolved, f"config_diff_{task.task_id}.diff"
        raise FileNotFoundError("Artifact 不存在或不属于当前局点")

    def _start_device_job(self, site_name: str, task_type: str, device: Device) -> ConfigTaskReferenceDTO:
        device_uuid = str(device.device_uuid or "")
        with self._start_lock:
            active = next(
                (
                    task
                    for task in self.task_service.repository(site_name).list(statuses=ACTIVE_TASK_STATES, limit=1000)
                    if task.task_type == task_type
                    and task.owner == CONFIG_WEB_OWNER
                    and task.device == device_uuid
                ),
                None,
            )
            if active is not None:
                return self._task_dto(active)
            return self._start_job(
                site_name,
                task_type,
                {"device_uuid": device_uuid},
                f"配置采集 · {device.name or device.device_uuid}",
                device=device,
            )

    def _start_job(
        self,
        site_name: str,
        task_type: str,
        extra_params: dict[str, object],
        task_name: str,
        *,
        device: Device | None = None,
    ) -> ConfigTaskReferenceDTO:
        task_id = f"config-web-{uuid4().hex}"
        params: dict[str, object] = {
            "site_name": site_name,
            "db_path": str(self.paths.site_db_path(site_name)),
            "app_root": str(self.paths.app_root),
            "data_root": str(self.paths.data_root),
            "task_name": task_name,
            "owner": CONFIG_WEB_OWNER,
            "task_source": "local",
            "_emit_log_events": True,
            "_cancel_grace_ms": 3_000,
            **extra_params,
        }
        if device is not None:
            params.update(
                {
                    "device": str(device.device_uuid or ""),
                    "device_name": str(device.name or ""),
                    "device_id": str(device.id or ""),
                }
            )
        job = BackgroundJob(job_id=task_id, task_type=task_type, params=params)
        self.process_adapter.start_job(job)
        snapshot = self.task_service.repository(site_name).get(task_id)
        if snapshot is None:
            raise RuntimeError("配置任务创建后未写入任务中心")
        return self._task_dto(snapshot)

    def _device_context(self, site_name: str, device_id: int):
        database = self._database(site_name)
        device = self._h3c_device(DeviceRepository(database), device_id)
        repository = ConfigSnapshotRepository(database, ensure_schema=False)
        from netconsole.services.config_lifecycle_service import ConfigLifecycleService

        return device, repository, ConfigLifecycleService(site_name, database, self.paths, repository)

    def _snapshot_context(self, site_name: str, snapshot_id: int) -> tuple[ConfigSnapshot, ConfigSnapshotRepository, Path]:
        database = self._database(site_name)
        repository = ConfigSnapshotRepository(database, ensure_schema=False)
        snapshot = repository.get(int(snapshot_id))
        path = self._safe_snapshot_path(site_name, snapshot)
        if path is None:
            raise FileNotFoundError("配置快照不存在")
        return snapshot, repository, path

    def _database(self, site_name: str) -> Database:
        site = SiteManager(self.paths).validate_site_name(site_name)
        return Database(self.paths.site_db_path(site))

    @staticmethod
    def _h3c_device(repository: DeviceRepository, device_id: int) -> Device:
        try:
            device = repository.get(int(device_id))
        except KeyError as exc:
            raise FileNotFoundError("设备不存在") from exc
        if str(device.device_vendor or "").upper() != "H3C":
            raise ValueError("配置中心仅支持 H3C 设备")
        return device

    @staticmethod
    def _group_filter(value: str) -> int | str | None:
        text = str(value or "").strip()
        if not text or text == "__all_groups__":
            return None
        if text == "__ungrouped__":
            return text
        try:
            return int(text)
        except ValueError as exc:
            raise ValueError("设备分组筛选无效") from exc

    @staticmethod
    def _device_dto(device: Device) -> ConfigDeviceDTO:
        return ConfigDeviceDTO(
            id=int(device.id or 0),
            device_uuid=str(device.device_uuid or ""),
            name=str(device.name or ""),
            system_name=str(device.system_name or ""),
            device_type=str(device.device_type or ""),
            station=str(device.station or ""),
            group_id=int(device.group_id) if device.group_id is not None else None,
        )

    def _groups(self, database: Database, site_name: str) -> list[ConfigDeviceGroupDTO]:
        repository = DeviceGroupRepository(database, site_name)
        counts = repository.counts()
        return [
            ConfigDeviceGroupDTO(id=int(group.id or 0), name=str(group.name), device_count=counts.get(int(group.id or 0), 0))
            for group in repository.list()
            if group.id is not None
        ]

    def _snapshot_dto(self, site_name: str, device: Device, snapshot: ConfigSnapshot, path: Path) -> ConfigSnapshotDTO:
        suffix = ".diff" if snapshot.type == "diff" else ".txt"
        filename = f"{safe_device_name(device.name or device.device_uuid or 'device')}_{snapshot.type}_{snapshot.timestamp}{suffix}"
        return ConfigSnapshotDTO(
            id=int(snapshot.id or 0),
            device_id=snapshot.device_id,
            device_uuid=snapshot.device_uuid,
            timestamp=snapshot.timestamp,
            type=snapshot.type,
            size_bytes=path.stat().st_size if path.is_file() else 0,
            artifact_id=f"snapshot-{int(snapshot.id or 0)}",
            filename=filename,
            hash=snapshot.hash,
            created_at=str(snapshot.created_at or ""),
            error_message=_sanitize_text(str(snapshot.error_message or "")),
        )

    def _snapshot_path(self, site_name: str, snapshot: ConfigSnapshot) -> Path:
        return self._safe_snapshot_path(site_name, snapshot) or Path()

    def _safe_snapshot_path(self, site_name: str, snapshot: ConfigSnapshot) -> Path | None:
        root = self.paths.config_center_root(site_name).resolve()
        candidate = self.paths.site_dir(site_name) / snapshot.file_path
        if candidate.is_symlink():
            return None
        path = candidate.resolve()
        if root not in path.parents or not path.is_file():
            return None
        return path

    @staticmethod
    def _is_web_task(snapshot: TaskSnapshot | None) -> bool:
        return bool(
            snapshot is not None
            and snapshot.source == "local"
            and snapshot.owner == CONFIG_WEB_OWNER
            and snapshot.task_type in CONFIG_WEB_TASK_TYPES
        )

    @staticmethod
    def _task_dto(snapshot: TaskSnapshot, *, diff_filter: str = "all") -> ConfigTaskStatusDTO:
        result = _safe_result(snapshot.result)
        if snapshot.task_type in CONFIG_WEB_COMPARE_TASK_TYPES and snapshot.result.get("diff_file"):
            result["artifact_id"] = f"diff-{snapshot.task_id}"
            if str(diff_filter or "all") != "all":
                result["raw_diff"] = _filter_diff(str(result.get("raw_diff") or ""), diff_filter)
        return ConfigTaskStatusDTO(
            id=snapshot.task_id,
            type=snapshot.task_type,
            status=snapshot.status.value,
            progress=int(snapshot.progress),
            device_name=snapshot.device,
            message=_sanitize_text(snapshot.message),
            stage=snapshot.stage,
            created_time=snapshot.created_time,
            started_time=snapshot.started_time,
            finished_time=snapshot.finished_time,
            error_message=_sanitize_text(snapshot.error_message),
            result=result,
        )


def _safe_result(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    blocked = ("path", "file", "password", "token", "secret", "credential", "username", "community")
    result: dict[str, Any] = {}
    for key, item in value.items():
        name = str(key).casefold()
        if any(word in name for word in blocked):
            continue
        if isinstance(item, dict):
            result[str(key)] = _safe_result(item)
        elif isinstance(item, list):
            result[str(key)] = [_safe_value(entry) for entry in item]
        elif isinstance(item, str):
            result[str(key)] = _sanitize_text(item)
        else:
            result[str(key)] = item
    return result


def _safe_value(value: object) -> object:
    if isinstance(value, dict):
        return _safe_result(value)
    if isinstance(value, list):
        return [_safe_value(item) for item in value]
    if isinstance(value, str):
        return _sanitize_text(value)
    return value


def _sanitize_text(value: str) -> str:
    redacted = _ABSOLUTE_PATH_RE.sub("<redacted-path>", str(value or ""))
    redacted = _SECRET_VALUE_RE.sub(r"\1<redacted>", redacted)
    return _BEARER_RE.sub("Bearer <redacted>", redacted)


def _filter_diff(text: str, diff_filter: str) -> str:
    kind = str(diff_filter or "all").strip().casefold()
    if kind not in {"all", "added", "removed"}:
        raise ValueError("差异过滤类型无效")
    if kind == "all":
        return text
    return "\n".join(
        line
        for line in str(text or "").splitlines()
        if line.startswith("---")
        or line.startswith("+++")
        or line.startswith("@@")
        or (kind == "added" and line.startswith("+") and not line.startswith("+++"))
        or (kind == "removed" and line.startswith("-") and not line.startswith("---"))
    )


__all__ = ["CONFIG_WEB_TASK_TYPES", "ConfigCollectionApplicationService"]
