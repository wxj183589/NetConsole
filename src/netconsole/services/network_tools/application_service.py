from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import os
import re
import sys
import threading
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from netconsole.core.paths import PathResolver
from netconsole.models.task_state import TERMINAL_TASK_STATES, TaskState
from netconsole.models.traffic_test import ExecutionTargetDTO, TcpPortTestConfig, TrafficRun
from netconsole.services.export.export_job import ExportJob
from netconsole.services.export.export_task_builders import result_file_rows_source
from netconsole.services.network_tools.toolbox.ip_calc import (
    TableResult,
    ipv4_calculate,
    ipv6_calculate,
    plan_vlsm,
    split_subnets,
    summarize_routes,
    wildcard_calculate,
)
from netconsole.services.network_tools.toolbox.ping_tools import run_batch_ping, run_single_ping, run_tcp_ping
from netconsole.services.traffic.application_service import TrafficTestApplicationService


_CONTROLLED_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_ARTIFACT_SUFFIXES = {".csv", ".xlsx"}
_INVALID_FILENAME_CHARS = set('<>:"|?*')


class NetworkToolsApplicationService:
    """网络工具 Web Facade；算法、探测和无线扫描均复用既有 Python Service。"""

    def __init__(
        self,
        traffic_service: TrafficTestApplicationService,
        task_service: Any | None = None,
        *,
        paths: PathResolver | None = None,
        site_name: str = "",
        wireless_scan_service: Any | None = None,
    ) -> None:
        self.traffic_service = traffic_service
        self.paths = paths or getattr(traffic_service, "paths", None) or PathResolver()
        self.site_name = str(site_name or getattr(traffic_service, "site_name", "demo") or "demo")
        self.task_service = task_service or getattr(traffic_service, "task_service", None)
        self._wireless_scan_service = wireless_scan_service
        self._jobs: dict[str, asyncio.Task[None]] = {}
        self._stop_events: dict[str, threading.Event] = {}

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
    ) -> Any:
        params = {
            "target": target.strip(),
            "targets": list(targets or []),
            "port": port,
            "interval_ms": interval_ms,
            "timeout_ms": timeout_ms,
            "count": count,
            "packet_size": packet_size,
            "concurrency": concurrency,
            "source_ip": source_ip.strip(),
        }
        self._validate_network_task(kind, params)
        task_service = self._ensure_task_service()
        task_id = uuid.uuid4().hex
        task_service.create_external_task(
            task_id=task_id,
            task_type=f"network_tools.{kind}",
            task_name=self._task_name(kind),
            source="network_tools_web",
            site_name=self.site_name,
        )
        stop_event = threading.Event()
        self._stop_events[task_id] = stop_event
        self._jobs[task_id] = asyncio.create_task(
            self._run_network_task(
                task_id,
                kind,
                params,
                stop_event,
            )
        )
        return task_service.get_task(task_id)

    def list_network_tasks(self, *, offset: int = 0, limit: int = 100) -> list[Any]:
        tasks = [task for task in self._ensure_task_service().list_tasks(limit=1000) if task.task_type.startswith("network_tools.")]
        return tasks[max(0, int(offset)) : max(0, int(offset)) + max(1, min(int(limit), 500))]

    def get_network_task(self, task_id: str) -> Any | None:
        task = self._ensure_task_service().get_task(task_id)
        return task if task and task.task_type.startswith("network_tools.") else None

    def list_network_task_events(self, task_id: str, *, after_sequence: int = 0, limit: int = 500) -> list[dict[str, Any]]:
        if self.get_network_task(task_id) is None:
            return []
        return self._ensure_task_service().list_events(task_id, after_sequence=after_sequence, limit=min(max(1, limit), 2000))

    def cancel_network_task(self, task_id: str) -> Any:
        task = self.get_network_task(task_id)
        if task is None:
            raise KeyError(task_id)
        if task.status in TERMINAL_TASK_STATES:
            return task
        stop_event = self._stop_events.get(task_id)
        if stop_event is not None:
            stop_event.set()
        return self._record_event(task_id, "state", {"state": TaskState.STOPPING.value, "message": "已请求停止网络工具任务"})

    async def export_network_task(self, task_id: str, file_format: str, filename: str = "") -> dict[str, object]:
        task = self.get_network_task(task_id)
        if task is None:
            raise KeyError(task_id)
        if task.status not in TERMINAL_TASK_STATES:
            raise ValueError("网络工具任务尚未完成")
        rows = self._task_rows(task)
        if not task.result and not rows:
            raise ValueError("网络工具任务没有可导出的结果")
        result_file = self._controlled_task_result_path(task.task_id)
        source_is_temporary = result_file is None
        source_file = result_file or self._write_result_rows(f"export_{task_id}", rows)
        return await self._export_process(
            source_file,
            self.paths.toolbox_outputs_dir(self.site_name),
            task_id,
            file_format,
            filename,
            cleanup_source=source_is_temporary,
        )

    def resolve_artifact(self, artifact_id: str) -> Path | None:
        binding = self._resolve_artifact_binding(artifact_id)
        return binding[0] if binding else None

    def artifact_display_name(self, artifact_id: str) -> str:
        binding = self._resolve_artifact_binding(artifact_id)
        return binding[1] if binding else ""

    def list_wireless_adapters(self) -> list[dict[str, object]]:
        service = self._wireless()
        return [
            {**asdict(adapter), "display_name": adapter.display_name}
            for adapter in service.list_adapters()
        ]

    def list_wireless_projects(self) -> list[dict[str, object]]:
        path = self._project_path()
        if not path.is_file():
            return []
        try:
            values = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return [dict(item) for item in values if isinstance(item, dict)]

    def create_wireless_project(self, name: str, description: str = "") -> dict[str, object]:
        projects = self.list_wireless_projects()
        if any(str(item.get("name") or "").casefold() == name.casefold() for item in projects):
            raise ValueError("无线扫描项目名称已存在")
        project = {"project_id": uuid.uuid4().hex, "name": name.strip(), "description": description.strip()}
        projects.append(project)
        self._write_projects(projects)
        return project

    def delete_wireless_project(self, project_id: str) -> None:
        projects = self.list_wireless_projects()
        remaining = [item for item in projects if str(item.get("project_id") or "") != project_id]
        if len(remaining) == len(projects):
            raise KeyError(project_id)
        self._write_projects(remaining)

    async def start_wireless_scan(self, *, adapter_name: str = "", adapter_guid: str = "", project_id: str = "") -> Any:
        project_id = str(project_id or "").strip()
        if project_id and not any(str(item.get("project_id") or "") == project_id for item in self.list_wireless_projects()):
            raise ValueError("无线扫描项目不存在")
        task_service = self._ensure_task_service()
        task_id = uuid.uuid4().hex
        task_service.create_external_task(
            task_id=task_id,
            task_type="network_tools.wireless_scan",
            task_name="无线扫描",
            source="network_tools_web",
            site_name=self.site_name,
            device=adapter_name or adapter_guid,
        )
        stop_event = threading.Event()
        self._stop_events[task_id] = stop_event
        self._jobs[task_id] = asyncio.create_task(self._run_wireless_scan(task_id, adapter_name, adapter_guid, project_id, stop_event))
        return task_service.get_task(task_id)

    def list_wireless_runs(self, *, offset: int = 0, limit: int = 100) -> list[dict[str, object]]:
        rows = self._wireless().repository.list_runs(limit=500)
        safe_rows = []
        for row in rows:
            safe_row = dict(row)
            scan_id = str(safe_row.get("scan_id") or "")
            safe_row["raw_file"] = f"{scan_id}.txt" if scan_id else ""
            safe_rows.append(safe_row)
        return safe_rows[max(0, int(offset)) : max(0, int(offset)) + max(1, min(int(limit), 500))]

    def list_wireless_results(self, scan_id: str, *, offset: int = 0, limit: int = 500) -> list[dict[str, object]]:
        rows = self._wireless().repository.list_results(scan_id)
        from netconsole.services.network_tools.wireless_scan_service import repository_row_to_display_row

        display_rows = [repository_row_to_display_row(row) for row in rows]
        return display_rows[max(0, int(offset)) : max(0, int(offset)) + max(1, min(int(limit), 2000))]

    async def export_wireless_scan(self, scan_id: str, file_format: str, filename: str = "") -> dict[str, object]:
        rows = self.list_wireless_results(scan_id, limit=2000)
        if not rows and not any(str(item.get("scan_id") or "") == scan_id for item in self.list_wireless_runs(limit=500)):
            raise KeyError(scan_id)
        from netconsole.services.network_tools.wireless_scan_service import WIRELESS_SCAN_EXPORT_COLUMNS

        headers = [field for _key, field in WIRELESS_SCAN_EXPORT_COLUMNS]
        source_file = self._write_jsonl_file(
            self.paths.runtime_cache_dir / "network_tool_exports" / f"{scan_id}.jsonl",
            rows,
        )
        try:
            return await self._export_process(
                source_file,
                self.paths.wireless_scan_export_dir(self.site_name),
                scan_id,
                file_format,
                filename,
                headers,
            )
        finally:
            try:
                source_file.unlink()
            except OSError:
                pass

    async def _run_network_task(self, task_id: str, kind: str, params: dict[str, object], stop_event: threading.Event) -> None:
        try:
            self._record_event(task_id, "state", {"state": TaskState.RUNNING.value, "message": "网络工具任务执行中"})
            if kind == "single_ping":
                result = await asyncio.to_thread(
                    run_single_ping,
                    str(params["target"]),
                    count=int(params["count"]),
                    size=int(params["packet_size"]),
                    timeout_ms=int(params["timeout_ms"]),
                    source_ip=str(params["source_ip"]),
                )
                rows = [asdict(result)]
            elif kind == "continuous_ping":
                rows = []
                while not stop_event.is_set() and len(rows) < 1000:
                    result = await asyncio.to_thread(
                        run_single_ping,
                        str(params["target"]),
                        count=1,
                        size=int(params["packet_size"]),
                        timeout_ms=int(params["timeout_ms"]),
                        source_ip=str(params["source_ip"]),
                    )
                    rows.append(asdict(result))
                    self._record_event(task_id, "progress", {"current": len(rows), "total": 0, "message": f"已完成第 {len(rows)} 次 Ping"})
                    await asyncio.to_thread(stop_event.wait, int(params["interval_ms"]) / 1000)
                if stop_event.is_set():
                    self._record_event(task_id, "cancelled", {"message": "网络工具任务已取消"})
                    return
            elif kind in {"batch_ping", "subnet_ping"}:
                targets = self._targets_for_task(kind, params)
                completed = 0

                def on_progress(_result: object) -> None:
                    nonlocal completed
                    completed += 1
                    self._record_event(
                        task_id,
                        "progress",
                        {"current": completed, "total": len(targets), "message": f"已完成 {completed}/{len(targets)} 个目标"},
                    )

                results = await asyncio.to_thread(
                    run_batch_ping,
                    targets,
                    count=int(params["count"]),
                    size=int(params["packet_size"]),
                    timeout_ms=int(params["timeout_ms"]),
                    concurrency=int(params["concurrency"]),
                    source_ip=str(params["source_ip"]),
                    progress=on_progress,
                    should_stop=stop_event.is_set,
                )
                rows = [asdict(result) for result in results]
            elif kind == "tcp_ping":
                result = await asyncio.to_thread(run_tcp_ping, str(params["target"]), int(params["port"]), timeout_seconds=int(params["timeout_ms"]) / 1000)
                rows = [asdict(result)]
            else:
                raise ValueError("不支持的网络工具任务类型")
            if stop_event.is_set():
                self._record_event(task_id, "cancelled", {"message": "网络工具任务已取消"})
                return
            self._write_result_rows(task_id, rows)
            self._record_event(task_id, "finished", {"result": {"rows": rows, "row_count": len(rows), "result_id": task_id}})
        except asyncio.CancelledError:
            self._record_event(task_id, "cancelled", {"message": "网络工具任务已取消"})
        except Exception as exc:
            self._record_event(task_id, "error", {"error": str(exc), "message": "网络工具任务失败"})
        finally:
            self._jobs.pop(task_id, None)
            self._stop_events.pop(task_id, None)

    async def _run_wireless_scan(self, task_id: str, adapter_name: str, adapter_guid: str, project_id: str, stop_event: threading.Event) -> None:
        try:
            self._record_event(task_id, "state", {"state": TaskState.RUNNING.value, "message": "无线扫描执行中"})
            adapter = self._find_adapter(adapter_name, adapter_guid)
            result = await asyncio.to_thread(self._wireless().scan, adapter)
            if stop_event.is_set():
                self._record_event(task_id, "cancelled", {"message": "无线扫描已取消"})
                return
            from netconsole.services.network_tools.wireless_scan_service import result_to_row

            rows = [result_to_row(item) for item in result.results]
            self._write_result_rows(task_id, rows)
            self._record_event(
                task_id,
                "progress",
                {"current": len(rows), "total": len(rows), "message": f"扫描完成，共 {len(rows)} 条结果"},
            )
            self._record_event(
                task_id,
                "finished",
                {
                    "result": {
                        "result_id": task_id,
                        "scan_id": result.scan_id,
                        "project_id": project_id,
                        "row_count": len(rows),
                    }
                },
            )
        except asyncio.CancelledError:
            self._record_event(task_id, "cancelled", {"message": "无线扫描已取消"})
        except Exception as exc:
            self._record_event(task_id, "error", {"error": str(exc), "message": "无线扫描失败"})
        finally:
            self._jobs.pop(task_id, None)
            self._stop_events.pop(task_id, None)

    def _ensure_task_service(self) -> Any:
        if self.task_service is None:
            from netconsole.services.job_center.task_application_service import TaskApplicationService

            self.task_service = TaskApplicationService(paths=self.paths, site_name=self.site_name)
        return self.task_service

    def _wireless(self) -> Any:
        if self._wireless_scan_service is None:
            from netconsole.services.network_tools.wireless_scan_service import WirelessScanService

            self._wireless_scan_service = WirelessScanService(self.site_name, self.paths)
        return self._wireless_scan_service

    def _record_event(self, task_id: str, event_type: str, payload: dict[str, object]) -> Any:
        return self._ensure_task_service().record_external_event(task_id, event_type, payload, site_name=self.site_name)

    def _targets_for_task(self, kind: str, params: dict[str, object]) -> list[str]:
        if kind == "subnet_ping":
            network = ipaddress.ip_network(str(params["target"]).strip(), strict=False)
            if network.version != 4:
                raise ValueError("网段 Ping 只支持 IPv4")
            targets = [str(item) for item in network.hosts()]
            if len(targets) > 4096:
                raise ValueError("网段 Ping 最多支持 4096 个地址")
            return targets
        raw_targets = params.get("targets")
        if not isinstance(raw_targets, list):
            raise ValueError("批量 Ping 目标格式无效")
        if len(raw_targets) > 4096:
            raise ValueError("批量 Ping 最多支持 4096 个地址")
        targets = [str(item).strip() for item in raw_targets if str(item).strip()]
        if any(len(item) > 255 for item in targets):
            raise ValueError("单个 Ping 目标最多 255 个字符")
        if not targets:
            raise ValueError("请至少提供一个 Ping 目标")
        return targets

    def _validate_network_task(self, kind: str, params: dict[str, object]) -> None:
        if kind not in {"single_ping", "continuous_ping", "batch_ping", "subnet_ping", "tcp_ping"}:
            raise ValueError("不支持的网络工具任务类型")
        target = str(params["target"]).strip()
        if len(target) > 255:
            raise ValueError("Ping 目标最多 255 个字符")
        if kind in {"single_ping", "continuous_ping", "subnet_ping", "tcp_ping"} and not target:
            raise ValueError("请提供目标地址")
        if kind in {"batch_ping", "subnet_ping"}:
            self._targets_for_task(kind, params)

    def _task_rows(self, task: Any) -> list[dict[str, object]]:
        result = dict(task.result or {})
        result_file = self._controlled_task_result_path(str(getattr(task, "task_id", "")))
        if result_file is not None:
            rows: list[dict[str, object]] = []
            with result_file.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(row, dict):
                        rows.append(dict(row))
            return rows
        return [dict(row) for row in result.get("rows") or [] if isinstance(row, dict)]

    def _controlled_task_result_path(self, task_id: str) -> Path | None:
        value = str(task_id or "").strip()
        if not _CONTROLLED_ID_RE.fullmatch(value):
            return None
        root = self.paths.toolbox_outputs_dir(self.site_name).resolve()
        path = (root / f"{value}.jsonl").resolve()
        if path.parent != root or not path.is_file():
            return None
        return path

    def _write_result_rows(self, task_id: str, rows: list[dict[str, object]]) -> Path:
        output_dir = self.paths.toolbox_outputs_dir(self.site_name)
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{task_id}.jsonl"
        temp = path.with_suffix(".jsonl.tmp")
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, default=str))
                handle.write("\n")
        os.replace(temp, path)
        return path

    async def _export_process(
        self,
        source_file: Path,
        output_dir: Path,
        artifact_id: str,
        file_format: str,
        filename: str,
        headers: list[str] | None = None,
        cleanup_source: bool = False,
    ) -> dict[str, object]:
        if file_format not in {"csv", "xlsx"}:
            raise ValueError("导出格式不支持")
        suffix = ".csv" if file_format == "csv" else ".xlsx"
        selected = str(filename or "").strip() or f"{artifact_id}{suffix}"
        if (
            any(separator in selected for separator in ("/", "\\", "\x00"))
            or selected != Path(selected).name
            or any(character in _INVALID_FILENAME_CHARS for character in selected)
        ):
            raise ValueError("导出文件名不允许包含路径")
        if selected in {"", ".", ".."} or Path(selected).suffix.lower() != suffix:
            selected = f"{Path(selected).stem or artifact_id}{suffix}"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_dir = output_dir.resolve()
        artifact_id = uuid.uuid4().hex
        path = output_dir / f"{artifact_id}{suffix}"
        manifest_path = output_dir / f"{artifact_id}.json"
        manifest_temp_path = output_dir / f".{artifact_id}.json.tmp"
        job_id = uuid.uuid4().hex
        job_dir = self.paths.runtime_cache_dir / "network_tool_exports"
        job_dir.mkdir(parents=True, exist_ok=True)
        job_path = job_dir / f"{job_id}.json"
        tmp_path = path.with_name(f".{path.name}.{job_id}.tmp")
        cancel_path = job_dir / f"{job_id}.cancel"
        columns = [{"key": field, "title": field} for field in (headers or _jsonl_headers(source_file))]
        job = ExportJob(
            job_id=job_id,
            job_type="table_csv" if file_format == "csv" else "table_xlsx",
            site_name=self.site_name,
            output_path=str(path),
            tmp_path=str(tmp_path),
            cancel_path=str(cancel_path),
            params={
                "payload": {
                    "columns": columns,
                    "source": result_file_rows_source(source_file),
                    "freeze_header": True,
                    "auto_filter": True,
                }
            },
        )
        job_path.write_text(json.dumps(job.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        environment = os.environ.copy()
        source_root = Path(__file__).resolve().parents[3]
        python_path = [str(source_root)]
        if environment.get("PYTHONPATH"):
            python_path.append(environment["PYTHONPATH"])
        environment["PYTHONPATH"] = os.pathsep.join(python_path)
        arguments = ["--export-worker", "--job", str(job_path)] if getattr(sys, "frozen", False) else ["-m", "netconsole.export_worker", "--job", str(job_path)]
        completed = False
        try:
            process = await asyncio.create_subprocess_exec(sys.executable, *arguments, cwd=str(source_root.parent), env=environment, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            _stdout, stderr = await process.communicate()
            if process.returncode != 0 or not path.is_file():
                message = stderr.decode("utf-8", errors="replace").strip() or "导出进程失败"
                raise RuntimeError(message)
            digest, size = await asyncio.to_thread(_hash_file, path)
            manifest_temp_path.write_text(
                json.dumps(
                    {
                        "artifact_id": artifact_id,
                        "physical_name": path.name,
                        "filename": selected,
                        "format": file_format,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            os.replace(manifest_temp_path, manifest_path)
            completed = True
            return {
                "artifact_id": artifact_id,
                "filename": selected,
                "format": file_format,
                "sha256": digest,
                "size": size,
                "download_url": f"/api/network-tools/artifacts/{artifact_id}",
            }
        finally:
            for temp_path in (job_path, cancel_path, tmp_path):
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            if cleanup_source:
                try:
                    source_file.unlink()
                except OSError:
                    pass
            if not completed:
                for export_path in (path, manifest_path, manifest_temp_path):
                    try:
                        export_path.unlink()
                    except OSError:
                        pass

    def _resolve_artifact_binding(self, artifact_id: str) -> tuple[Path, str] | None:
        value = str(artifact_id or "").strip()
        if not _CONTROLLED_ID_RE.fullmatch(value):
            return None
        bindings: list[tuple[Path, str]] = []
        for root_path in (self.paths.toolbox_outputs_dir(self.site_name), self.paths.wireless_scan_export_dir(self.site_name)):
            root = root_path.resolve()
            manifest_path = (root / f"{value}.json").resolve()
            if manifest_path.parent != root or not manifest_path.is_file():
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(manifest, dict) or manifest.get("artifact_id") != value:
                continue
            suffix = "." + str(manifest.get("format") or "").lower()
            physical_name = str(manifest.get("physical_name") or "")
            display_name = str(manifest.get("filename") or "")
            if suffix not in _ARTIFACT_SUFFIXES or physical_name != f"{value}{suffix}":
                continue
            if (
                not display_name
                or any(separator in display_name for separator in ("/", "\\", "\x00"))
                or Path(display_name).name != display_name
                or any(character in _INVALID_FILENAME_CHARS for character in display_name)
            ):
                continue
            path = (root / physical_name).resolve()
            if path.parent != root or not path.is_file():
                continue
            bindings.append((path, display_name))
        return bindings[0] if len(bindings) == 1 else None

    @staticmethod
    def _write_jsonl_file(path: Path, rows: list[dict[str, object]]) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".jsonl.tmp")
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, default=str))
                handle.write("\n")
        os.replace(temp, path)
        return path

    def _project_path(self) -> Path:
        return self.paths.wireless_scan_projects_dir(self.site_name) / "projects.json"

    def _write_projects(self, projects: list[dict[str, object]]) -> None:
        path = self._project_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(projects, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, path)

    def _find_adapter(self, name: str, guid: str) -> Any | None:
        if not name and not guid:
            return None
        for adapter in self._wireless().list_adapters():
            if (guid and adapter.guid == guid) or (name and adapter.name == name):
                return adapter
        raise ValueError("无线网卡不存在")

    @staticmethod
    def _task_name(kind: str) -> str:
        return {
            "single_ping": "单个 Ping",
            "continuous_ping": "持续 Ping",
            "batch_ping": "批量 Ping",
            "subnet_ping": "网段 Ping",
            "tcp_ping": "TCP Ping",
        }.get(kind, "网络工具任务")


def _jsonl_headers(path: Path) -> list[str]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    row = json.loads(line)
                    return list(row) if isinstance(row, dict) else []
    except (OSError, json.JSONDecodeError):
        return []
    return []


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


__all__ = ["NetworkToolsApplicationService"]
