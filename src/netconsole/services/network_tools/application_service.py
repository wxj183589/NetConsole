from __future__ import annotations

import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import threading
from typing import Any, Iterable
import uuid

from netconsole.core.paths import PathResolver
from netconsole.core.sites import SiteManager
from netconsole.models.task_snapshot import TaskSnapshot
from netconsole.models.task_state import TERMINAL_TASK_STATES, TaskState
from netconsole.models.traffic_test import ExecutionTargetDTO, TcpPortTestConfig, TrafficRun
from netconsole.services.background_job import BackgroundJob
from netconsole.services.job_center.local_process_adapter import LocalProcessAdapter
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.network_tools.job_handlers import (
    NETWORK_PROBE_TASK_TYPES,
    NETWORK_TASK_SOURCE,
    NETWORK_TOOLBOX_EXPORT_TASK,
    NETWORK_TOOLBOX_TASK_TYPES,
    NETWORK_TOOL_OWNER,
    NETWORK_WIRELESS_EXPORT_TASK,
    NETWORK_WIRELESS_SCAN_TASK,
    NETWORK_WIRELESS_TASK_TYPES,
)
from netconsole.services.network_tools.toolbox.ip_calc import (
    TableResult,
    ipv4_calculate,
    ipv6_calculate,
    plan_vlsm,
    split_subnets,
    summarize_routes,
    wildcard_calculate,
)
from netconsole.services.traffic.application_service import TrafficTestApplicationService


_CONTROLLED_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_ARTIFACT_SUFFIXES = {".csv", ".xlsx"}
_INVALID_FILENAME_CHARS = set('<>:"|?*')
_ACTIVE_TASK_STATES = {TaskState.PENDING, TaskState.STARTING, TaskState.RUNNING, TaskState.STOPPING}
_PROJECT_LOCKS: dict[str, threading.RLock] = {}
_PROJECT_LOCKS_GUARD = threading.Lock()


class NetworkToolsApplicationService:
    """网络工具 Web 应用层；所有长任务统一进入正式 Job Center Worker。"""

    def __init__(
        self,
        traffic_service: TrafficTestApplicationService,
        task_service: TaskApplicationService | None = None,
        *,
        paths: PathResolver | None = None,
        site_name: str = "",
        wireless_scan_service: Any | None = None,
        process_adapter: LocalProcessAdapter | None = None,
    ) -> None:
        self.traffic_service = traffic_service
        self.paths = paths or getattr(traffic_service, "paths", None) or PathResolver()
        selected_site = str(site_name or getattr(traffic_service, "site_name", "demo") or "demo")
        self.site_name = SiteManager(self.paths).validate_site_name(selected_site)
        self.task_service = task_service or getattr(traffic_service, "task_service", None)
        if self.task_service is None:
            self.task_service = TaskApplicationService(paths=self.paths, site_name=self.site_name)
        inherited_process_adapter = getattr(getattr(traffic_service, "local_adapter", None), "process_adapter", None)
        self._owns_process_adapter = process_adapter is None and inherited_process_adapter is None
        self.process_adapter = process_adapter or inherited_process_adapter or LocalProcessAdapter(self.task_service)
        self._wireless_scan_service = wireless_scan_service
        self._project_lock = _project_lock(self._project_path())
        self._reconcile_module_tasks()

    def close(self) -> None:
        if self._owns_process_adapter:
            self.process_adapter.shutdown()

    async def start_tcp_port_test(
        self,
        config: TcpPortTestConfig,
        execution_target: ExecutionTargetDTO,
    ) -> TrafficRun:
        return await self.traffic_service.start_tcp_port_test(config, execution_target)

    def calculate_ipv4(self, text: str) -> dict[str, object]:
        return ipv4_calculate(text)

    def calculate_ipv6(self, text: str) -> dict[str, object]:
        return ipv6_calculate(text)

    def plan_vlsm(self, parent: str, requests: str) -> TableResult:
        return plan_vlsm(parent, requests)

    def split_subnets(self, parent: str, target_prefix: int, page: int, page_size: int) -> TableResult:
        return split_subnets(parent, target_prefix, page=page, page_size=page_size)

    def summarize_routes(self, text: str) -> TableResult:
        return summarize_routes(text)

    def wildcard_calculate(self, text: str) -> TableResult:
        return wildcard_calculate(text)

    async def start_network_task(
        self,
        *,
        kind: str,
        target: str = "",
        targets: list[str] | None = None,
        port: int = 443,
        interval_ms: int = 1000,
        timeout_ms: int = 1500,
        count: int = 4,
        packet_size: int = 32,
        concurrency: int = 100,
        source_ip: str = "",
    ) -> TaskSnapshot:
        params: dict[str, object] = {
            "target": str(target or "").strip(),
            "targets": [str(value).strip() for value in targets or [] if str(value).strip()],
            "port": int(port),
            "interval_ms": int(interval_ms),
            "timeout_ms": int(timeout_ms),
            "count": int(count),
            "packet_size": int(packet_size),
            "concurrency": int(concurrency),
            "source_ip": str(source_ip or "").strip(),
        }
        self._validate_network_task(kind, params)
        task_type = f"network_tools.{kind}"
        if task_type not in NETWORK_PROBE_TASK_TYPES:
            raise ValueError("不支持的网络工具任务类型")
        return self._start_job(task_type, self._task_name(kind), params)

    def list_network_tasks(self, *, offset: int = 0, limit: int = 100) -> list[TaskSnapshot]:
        return self._list_scoped_tasks(NETWORK_TOOLBOX_TASK_TYPES, offset=offset, limit=limit)

    def get_network_task(self, task_id: str) -> TaskSnapshot | None:
        return self._get_scoped_task(task_id, NETWORK_TOOLBOX_TASK_TYPES)

    def list_network_task_events(
        self,
        task_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        if self.get_network_task(task_id) is None:
            return []
        return self.task_service.repository(self.site_name).list_events(
            task_id,
            after_sequence=max(0, int(after_sequence)),
            limit=min(max(1, int(limit)), 2000),
        )

    def cancel_network_task(self, task_id: str) -> TaskSnapshot:
        return self._cancel_scoped_task(task_id, NETWORK_TOOLBOX_TASK_TYPES)

    def list_network_task_results(
        self,
        task_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, object]:
        task = self._get_scoped_task(task_id, NETWORK_PROBE_TASK_TYPES)
        if task is None:
            raise KeyError(task_id)
        start = max(0, int(offset))
        size = max(1, min(int(limit), 500))
        path = self._controlled_task_result_path(task.task_id)
        rows: list[dict[str, object]] = []
        if path is not None:
            with path.open("r", encoding="utf-8") as handle:
                for index, line in enumerate(handle):
                    if index < start:
                        continue
                    if len(rows) >= size:
                        break
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(row, dict):
                        rows.append(dict(row))
        total = task.result.get("row_count") if isinstance(task.result, dict) else 0
        return {
            "items": rows,
            "offset": start,
            "limit": size,
            "total": int(total or 0),
        }

    async def export_network_task(self, task_id: str, file_format: str, filename: str = "") -> TaskSnapshot:
        task = self._get_scoped_task(task_id, NETWORK_PROBE_TASK_TYPES)
        if task is None:
            raise KeyError(task_id)
        if task.status is not TaskState.COMPLETED or self._controlled_task_result_path(task.task_id) is None:
            raise ValueError("网络工具任务尚未完成或没有结果")
        artifact_id = uuid.uuid4().hex
        return self._start_job(
            NETWORK_TOOLBOX_EXPORT_TASK,
            f"导出网络工具结果 · {task.task_name}",
            {
                "source_task_id": task.task_id,
                "artifact_id": artifact_id,
                "format": self._validate_export_format(file_format),
                "filename": self._validate_export_filename(filename),
            },
        )

    def get_network_export_artifact(self, task_id: str) -> dict[str, object]:
        return self._artifact_for_export_task(task_id, scope="toolbox")

    def open_network_artifact(self, artifact_id: str) -> tuple[Path, str, dict[str, object]]:
        return self._open_artifact(artifact_id, scope="toolbox")

    def list_wireless_adapters(self) -> list[dict[str, object]]:
        from dataclasses import asdict

        return [{**asdict(adapter), "display_name": adapter.display_name} for adapter in self._wireless().list_adapters()]

    def list_wireless_projects(self) -> list[dict[str, object]]:
        with self._project_lock:
            return self._read_projects_unlocked()

    def create_wireless_project(self, name: str, description: str = "") -> dict[str, object]:
        selected_name = str(name or "").strip()
        if not selected_name:
            raise ValueError("无线扫描项目名称不能为空")
        with self._project_lock:
            projects = self._read_projects_unlocked()
            if any(str(item.get("name") or "").casefold() == selected_name.casefold() for item in projects):
                raise ValueError("无线扫描项目名称已存在")
            project = {
                "project_id": uuid.uuid4().hex,
                "name": selected_name,
                "description": str(description or "").strip(),
            }
            self._write_projects_unlocked([*projects, project])
        return project

    def delete_wireless_project(self, project_id: str) -> None:
        selected_id = str(project_id or "").strip()
        with self._project_lock:
            projects = self._read_projects_unlocked()
            remaining = [item for item in projects if str(item.get("project_id") or "") != selected_id]
            if len(remaining) == len(projects):
                raise KeyError(selected_id)
            self._write_projects_unlocked(remaining)

    async def start_wireless_scan(
        self,
        *,
        adapter_name: str = "",
        adapter_guid: str = "",
        project_id: str = "",
    ) -> TaskSnapshot:
        selected_project = str(project_id or "").strip()
        if selected_project and not self._project_exists(selected_project):
            raise ValueError("无线扫描项目不存在")
        return self._start_job(
            NETWORK_WIRELESS_SCAN_TASK,
            "无线扫描",
            {
                "adapter_name": str(adapter_name or "").strip(),
                "adapter_guid": str(adapter_guid or "").strip(),
                "project_id": selected_project,
                "device": str(adapter_name or adapter_guid or "").strip(),
            },
        )

    def list_wireless_tasks(self, *, offset: int = 0, limit: int = 100) -> list[TaskSnapshot]:
        return self._list_scoped_tasks(NETWORK_WIRELESS_TASK_TYPES, offset=offset, limit=limit)

    def get_wireless_task(self, task_id: str) -> TaskSnapshot | None:
        return self._get_scoped_task(task_id, NETWORK_WIRELESS_TASK_TYPES)

    def list_wireless_task_events(
        self,
        task_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        if self.get_wireless_task(task_id) is None:
            return []
        return self.task_service.repository(self.site_name).list_events(
            task_id,
            after_sequence=max(0, int(after_sequence)),
            limit=min(max(1, int(limit)), 2000),
        )

    def cancel_wireless_task(self, task_id: str) -> TaskSnapshot:
        return self._cancel_scoped_task(task_id, NETWORK_WIRELESS_TASK_TYPES)

    def list_wireless_runs(self, *, offset: int = 0, limit: int = 100) -> list[dict[str, object]]:
        start = max(0, int(offset))
        size = max(1, min(int(limit), 500))
        rows = self._wireless().repository.list_runs(limit=min(1000, start + size))
        safe_rows: list[dict[str, object]] = []
        for row in rows[start : start + size]:
            safe = dict(row)
            scan_id = str(safe.get("scan_id") or "")
            safe["raw_file"] = f"{scan_id}.txt" if scan_id else ""
            safe_rows.append(safe)
        return safe_rows

    def list_wireless_results(self, scan_id: str, *, offset: int = 0, limit: int = 500) -> list[dict[str, object]]:
        repository = self._wireless().repository
        if repository.get_run(str(scan_id or "")) is None:
            raise KeyError(scan_id)
        from netconsole.services.network_tools.wireless_scan_service import repository_row_to_display_row

        start = max(0, int(offset))
        size = max(1, min(int(limit), 2000))
        rows = repository.list_results(scan_id)
        return [repository_row_to_display_row(row) for row in rows[start : start + size]]

    async def export_wireless_scan(self, scan_id: str, file_format: str, filename: str = "") -> TaskSnapshot:
        if self._wireless().repository.get_run(str(scan_id or "")) is None:
            raise KeyError(scan_id)
        return self._start_job(
            NETWORK_WIRELESS_EXPORT_TASK,
            f"导出无线扫描结果 · {scan_id}",
            {
                "scan_id": str(scan_id),
                "artifact_id": uuid.uuid4().hex,
                "format": self._validate_export_format(file_format),
                "filename": self._validate_export_filename(filename),
            },
        )

    def get_wireless_export_artifact(self, task_id: str) -> dict[str, object]:
        return self._artifact_for_export_task(task_id, scope="wireless")

    def open_wireless_artifact(self, artifact_id: str) -> tuple[Path, str, dict[str, object]]:
        return self._open_artifact(artifact_id, scope="wireless")

    def _start_job(self, task_type: str, task_name: str, params: dict[str, object]) -> TaskSnapshot:
        task_id = uuid.uuid4().hex
        job_params = {
            **params,
            "site_name": self.site_name,
            "task_name": task_name,
            "owner": NETWORK_TOOL_OWNER,
            "task_source": NETWORK_TASK_SOURCE,
            "app_root": str(self.paths.app_root),
            "data_root": str(self.paths.data_root),
            "_cancel_grace_ms": 1500,
        }
        self.process_adapter.start_job(BackgroundJob(job_id=task_id, task_type=task_type, params=job_params))
        task = self.task_service.repository(self.site_name).get(task_id)
        if task is None:
            raise RuntimeError("网络工具任务启动后未写入任务中心")
        return task

    def _list_scoped_tasks(
        self,
        task_types: frozenset[str],
        *,
        offset: int,
        limit: int,
    ) -> list[TaskSnapshot]:
        self._reconcile_module_tasks()
        tasks = [
            task
            for task in self.task_service.repository(self.site_name).list(limit=1000)
            if self._is_scoped_task(task, task_types)
        ]
        tasks.sort(key=lambda task: task.updated_time, reverse=True)
        tasks.sort(key=lambda task: task.status not in _ACTIVE_TASK_STATES)
        start = max(0, int(offset))
        size = max(1, min(int(limit), 500))
        return tasks[start : start + size]

    def _get_scoped_task(self, task_id: str, task_types: Iterable[str]) -> TaskSnapshot | None:
        task = self.task_service.repository(self.site_name).get(str(task_id or ""))
        return task if self._is_scoped_task(task, task_types) else None

    def _is_scoped_task(self, task: TaskSnapshot | None, task_types: Iterable[str]) -> bool:
        return bool(
            task
            and task.task_type in task_types
            and task.site_name == self.site_name
            and task.owner == NETWORK_TOOL_OWNER
            and task.source == NETWORK_TASK_SOURCE
        )

    def _cancel_scoped_task(self, task_id: str, task_types: frozenset[str]) -> TaskSnapshot:
        task = self._get_scoped_task(task_id, task_types)
        if task is None:
            raise KeyError(task_id)
        if task.status in TERMINAL_TASK_STATES:
            return task
        if not self.process_adapter.cancel_job(task.task_id):
            self._fail_orphaned_task(task)
        return self.task_service.repository(self.site_name).get(task.task_id) or task

    def _reconcile_module_tasks(self) -> None:
        repository = self.task_service.repository(self.site_name)
        for task in repository.list(statuses=_ACTIVE_TASK_STATES, limit=1000):
            if not self._is_scoped_task(task, {*NETWORK_TOOLBOX_TASK_TYPES, *NETWORK_WIRELESS_TASK_TYPES}):
                continue
            if not self.process_adapter.is_running(task.task_id):
                self._fail_orphaned_task(task)

    def _fail_orphaned_task(self, task: TaskSnapshot) -> None:
        current = self.task_service.repository(self.site_name).get(task.task_id)
        if current is None or current.status in TERMINAL_TASK_STATES:
            return
        self.task_service.record_external_event(
            task.task_id,
            "error",
            {
                "message": "网络工具任务宿主已退出",
                "error": "未发现仍受控的本地 Worker，任务已由恢复流程收口",
            },
            source="recovery",
            site_name=self.site_name,
        )

    def _artifact_for_export_task(self, task_id: str, *, scope: str) -> dict[str, object]:
        task_type = NETWORK_TOOLBOX_EXPORT_TASK if scope == "toolbox" else NETWORK_WIRELESS_EXPORT_TASK
        task = self._get_scoped_task(task_id, frozenset({task_type}))
        if task is None:
            raise KeyError(task_id)
        if task.status is not TaskState.COMPLETED:
            raise ValueError("导出任务尚未完成")
        artifact_id = str(task.result.get("result_id") or "") if isinstance(task.result, dict) else ""
        _path, _name, metadata = self._validated_artifact_binding(artifact_id, task, scope=scope)
        return metadata

    def _open_artifact(self, artifact_id: str, *, scope: str) -> tuple[Path, str, dict[str, object]]:
        task_type = NETWORK_TOOLBOX_EXPORT_TASK if scope == "toolbox" else NETWORK_WIRELESS_EXPORT_TASK
        manifest = self._read_artifact_manifest(artifact_id, scope=scope)
        task_id = str(manifest.get("task_id") or "")
        task = self._get_scoped_task(task_id, frozenset({task_type}))
        if task is None or task.status is not TaskState.COMPLETED:
            raise KeyError(artifact_id)
        return self._validated_artifact_binding(artifact_id, task, scope=scope)

    def _validated_artifact_binding(
        self,
        artifact_id: str,
        task: TaskSnapshot,
        *,
        scope: str,
    ) -> tuple[Path, str, dict[str, object]]:
        manifest = self._read_artifact_manifest(artifact_id, scope=scope)
        expected_type = NETWORK_TOOLBOX_EXPORT_TASK if scope == "toolbox" else NETWORK_WIRELESS_EXPORT_TASK
        if any(
            (
                manifest.get("artifact_id") != artifact_id,
                manifest.get("task_id") != task.task_id,
                manifest.get("site_name") != self.site_name,
                manifest.get("owner") != NETWORK_TOOL_OWNER,
                manifest.get("source") != NETWORK_TASK_SOURCE,
                manifest.get("task_type") != expected_type,
            )
        ):
            raise KeyError(artifact_id)
        file_format = str(manifest.get("format") or "").lower()
        suffix = f".{file_format}"
        physical_name = str(manifest.get("physical_name") or "")
        display_name = self._validate_export_filename(str(manifest.get("filename") or ""))
        if not display_name or suffix not in _ARTIFACT_SUFFIXES or physical_name != f"{artifact_id}{suffix}":
            raise KeyError(artifact_id)
        root = self._artifact_root(scope).resolve()
        path = (root / physical_name).resolve()
        if path.parent != root or not path.is_file():
            raise KeyError(artifact_id)
        digest, size = _hash_file(path)
        if digest != str(manifest.get("sha256") or "") or size != int(manifest.get("size") or -1):
            raise ValueError("导出文件完整性校验失败")
        metadata = {
            "artifact_id": artifact_id,
            "filename": display_name,
            "format": file_format,
            "sha256": digest,
            "size": size,
            "download_url": (
                f"/api/network-tools/artifacts/{artifact_id}"
                if scope == "toolbox"
                else f"/api/network-tools/wireless-scan/artifacts/{artifact_id}"
            ),
        }
        return path, display_name, metadata

    def _read_artifact_manifest(self, artifact_id: str, *, scope: str) -> dict[str, object]:
        value = str(artifact_id or "").strip()
        if not _CONTROLLED_ID_RE.fullmatch(value):
            raise KeyError(value)
        root = self._artifact_root(scope).resolve()
        path = (root / f"{value}.json").resolve()
        if path.parent != root or not path.is_file():
            raise KeyError(value)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise KeyError(value) from exc
        if not isinstance(payload, dict):
            raise KeyError(value)
        return payload

    def _artifact_root(self, scope: str) -> Path:
        return (
            self.paths.toolbox_outputs_dir(self.site_name)
            if scope == "toolbox"
            else self.paths.wireless_scan_export_dir(self.site_name)
        )

    def _controlled_task_result_path(self, task_id: str) -> Path | None:
        value = str(task_id or "").strip()
        if not _CONTROLLED_ID_RE.fullmatch(value):
            return None
        root = self.paths.toolbox_outputs_dir(self.site_name).resolve()
        path = (root / f"{value}.jsonl").resolve()
        return path if path.parent == root and path.is_file() else None

    def _wireless(self) -> Any:
        if self._wireless_scan_service is None:
            from netconsole.services.network_tools.wireless_scan_service import WirelessScanService

            self._wireless_scan_service = WirelessScanService(self.site_name, self.paths)
        return self._wireless_scan_service

    def _project_path(self) -> Path:
        return self.paths.wireless_scan_projects_dir(self.site_name) / "projects.json"

    def _read_projects_unlocked(self) -> list[dict[str, object]]:
        path = self._project_path()
        if not path.is_file():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise RuntimeError("无线扫描项目存储读取失败") from exc
        except json.JSONDecodeError as exc:
            raise ValueError("无线扫描项目存储已损坏") from exc
        if not isinstance(payload, list):
            raise ValueError("无线扫描项目存储格式无效")
        return [dict(item) for item in payload if isinstance(item, dict)]

    def _write_projects_unlocked(self, projects: list[dict[str, object]]) -> None:
        path = self._project_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temp.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(projects, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path)
        finally:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass

    def _project_exists(self, project_id: str) -> bool:
        with self._project_lock:
            return any(str(item.get("project_id") or "") == project_id for item in self._read_projects_unlocked())

    def _validate_network_task(self, kind: str, params: dict[str, object]) -> None:
        if f"network_tools.{kind}" not in NETWORK_PROBE_TASK_TYPES:
            raise ValueError("不支持的网络工具任务类型")
        target = str(params.get("target") or "")
        if len(target) > 255:
            raise ValueError("Ping 目标最多 255 个字符")
        if kind in {"single_ping", "continuous_ping", "subnet_ping", "tcp_ping"} and not target:
            raise ValueError("请提供目标地址")
        if kind == "subnet_ping":
            try:
                network = ipaddress.ip_network(target, strict=False)
            except ValueError as exc:
                raise ValueError("网段 Ping 目标无效") from exc
            if network.version != 4:
                raise ValueError("网段 Ping 只支持 IPv4")
            if network.num_addresses - 2 > 4096:
                raise ValueError("网段 Ping 最多支持 4096 个地址")
        if kind == "batch_ping":
            targets = list(params.get("targets") or [])
            if not targets:
                raise ValueError("请至少提供一个 Ping 目标")
            if len(targets) > 4096 or any(len(str(value)) > 255 for value in targets):
                raise ValueError("批量 Ping 最多支持 4096 个地址，单个目标最多 255 个字符")

    @staticmethod
    def _validate_export_format(value: str) -> str:
        selected = str(value or "").lower()
        if selected not in {"csv", "xlsx"}:
            raise ValueError("导出格式不支持")
        return selected

    @staticmethod
    def _validate_export_filename(value: str) -> str:
        selected = str(value or "").strip()
        if selected and (
            selected in {".", ".."}
            or any(separator in selected for separator in ("/", "\\", "\x00"))
            or Path(selected).name != selected
            or any(character in _INVALID_FILENAME_CHARS for character in selected)
            or any(ord(character) < 32 for character in selected)
        ):
            raise ValueError("导出文件名不允许包含路径或非法字符")
        return selected

    @staticmethod
    def _task_name(kind: str) -> str:
        return {
            "single_ping": "单个 Ping",
            "continuous_ping": "持续 Ping",
            "batch_ping": "批量 Ping",
            "subnet_ping": "网段 Ping",
            "tcp_ping": "TCP Ping",
        }.get(kind, "网络工具任务")


def _project_lock(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _PROJECT_LOCKS_GUARD:
        return _PROJECT_LOCKS.setdefault(key, threading.RLock())


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


__all__ = ["NetworkToolsApplicationService"]
