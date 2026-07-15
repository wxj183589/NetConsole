from __future__ import annotations

import hashlib
import ipaddress
import json
import os
from pathlib import Path
from queue import Empty, Queue
import re
import subprocess
import sys
from threading import Thread
import time
from typing import Any
from uuid import uuid4

from netconsole.core.sites import SiteManager
from netconsole.services.export.export_job import ExportJob
from netconsole.services.export.export_task_builders import result_file_rows_source
from netconsole.services.job_center.job_context import BackgroundTaskCancelled, JobContext
from netconsole.services.job_center.worker_protocol import parse_event_line
from netconsole.services.network_tools.toolbox.ping_tools import run_batch_ping, run_single_ping, run_tcp_ping
from netconsole.services.network_tools.wireless_scan_service import (
    WIRELESS_SCAN_EXPORT_COLUMNS,
    WirelessScanService,
    repository_row_to_display_row,
    result_to_row,
)


NETWORK_TOOL_OWNER = "web_network_tools"
NETWORK_TASK_SOURCE = "local"
NETWORK_SINGLE_PING_TASK = "network_tools.single_ping"
NETWORK_CONTINUOUS_PING_TASK = "network_tools.continuous_ping"
NETWORK_BATCH_PING_TASK = "network_tools.batch_ping"
NETWORK_SUBNET_PING_TASK = "network_tools.subnet_ping"
NETWORK_TCP_PING_TASK = "network_tools.tcp_ping"
NETWORK_WIRELESS_SCAN_TASK = "network_tools.wireless_scan"
NETWORK_TOOLBOX_EXPORT_TASK = "network_tools.toolbox_export"
NETWORK_WIRELESS_EXPORT_TASK = "network_tools.wireless_export"

NETWORK_PROBE_TASK_TYPES = frozenset(
    {
        NETWORK_SINGLE_PING_TASK,
        NETWORK_CONTINUOUS_PING_TASK,
        NETWORK_BATCH_PING_TASK,
        NETWORK_SUBNET_PING_TASK,
        NETWORK_TCP_PING_TASK,
    }
)
NETWORK_TOOLBOX_TASK_TYPES = frozenset({*NETWORK_PROBE_TASK_TYPES, NETWORK_TOOLBOX_EXPORT_TASK})
NETWORK_WIRELESS_TASK_TYPES = frozenset({NETWORK_WIRELESS_SCAN_TASK, NETWORK_WIRELESS_EXPORT_TASK})
NETWORK_EXPORT_TASK_TYPES = frozenset({NETWORK_TOOLBOX_EXPORT_TASK, NETWORK_WIRELESS_EXPORT_TASK})

_CONTROLLED_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_SCAN_ID_RE = re.compile(r"^scan_[0-9]{8}_[0-9]{6}_[0-9a-f]{8}$")
_INVALID_FILENAME_CHARS = set('<>:"|?*')
_PROBE_KIND_BY_TASK = {
    NETWORK_SINGLE_PING_TASK: "single_ping",
    NETWORK_CONTINUOUS_PING_TASK: "continuous_ping",
    NETWORK_BATCH_PING_TASK: "batch_ping",
    NETWORK_SUBNET_PING_TASK: "subnet_ping",
    NETWORK_TCP_PING_TASK: "tcp_ping",
}


def run_network_probe(context: JobContext) -> dict[str, object]:
    kind = _PROBE_KIND_BY_TASK.get(context.task_type)
    if kind is None:
        raise ValueError("不支持的网络探测任务")
    site_name = _site_name(context)
    params = _validated_probe_params(kind, context.params)
    context.check_cancelled()
    context.progress("network_probe", 0, 0, "网络探测任务执行中")

    if kind == "single_ping":
        rows = [_safe_probe_row(run_single_ping(
            params["target"],
            count=params["count"],
            size=params["packet_size"],
            timeout_ms=params["timeout_ms"],
            source_ip=params["source_ip"],
        ))]
    elif kind == "continuous_ping":
        rows = _run_continuous_ping(context, params)
    elif kind in {"batch_ping", "subnet_ping"}:
        targets = _targets_for_probe(kind, params)
        completed = 0

        def progress(_result: object) -> None:
            nonlocal completed
            completed += 1
            context.progress(
                "network_probe",
                completed,
                len(targets),
                f"已完成 {completed}/{len(targets)} 个目标",
            )

        results = run_batch_ping(
            targets,
            count=params["count"],
            size=params["packet_size"],
            timeout_ms=params["timeout_ms"],
            concurrency=params["concurrency"],
            source_ip=params["source_ip"],
            progress=progress,
            should_stop=context.should_cancel,
        )
        context.check_cancelled()
        rows = [_safe_probe_row(result) for result in results]
    else:
        rows = [_safe_probe_row(run_tcp_ping(
            params["target"],
            params["port"],
            timeout_seconds=params["timeout_ms"] / 1000,
        ))]

    context.check_cancelled()
    _write_jsonl_atomic(_probe_result_path(context, site_name), rows)
    context.progress("network_probe", len(rows), len(rows), f"网络探测完成，共 {len(rows)} 条结果")
    return {"result_id": context.job_id, "row_count": len(rows)}


def run_wireless_scan(context: JobContext) -> dict[str, object]:
    site_name = _site_name(context)
    adapter_name = _bounded_text(context.params.get("adapter_name"), 256, "无线网卡名称")
    adapter_guid = _bounded_text(context.params.get("adapter_guid"), 128, "无线网卡 GUID")
    project_id = _bounded_text(context.params.get("project_id"), 128, "无线扫描项目 ID")
    service = WirelessScanService(site_name, context.paths)
    adapter = _find_wireless_adapter(service, adapter_name, adapter_guid)
    context.check_cancelled()
    context.progress("wireless_scan", 0, 0, "无线扫描执行中")
    result = service.scan(adapter, project_id=project_id)
    context.check_cancelled()
    rows = [result_to_row(item) for item in result.results]
    context.progress("wireless_scan", len(rows), len(rows), f"无线扫描完成，共 {len(rows)} 条结果")
    return {"result_id": result.scan_id, "row_count": len(rows)}


def run_toolbox_export(context: JobContext) -> dict[str, object]:
    return _run_network_export(context, wireless=False)


def run_wireless_export(context: JobContext) -> dict[str, object]:
    return _run_network_export(context, wireless=True)


def _run_continuous_ping(context: JobContext, params: dict[str, Any]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    while len(rows) < 1000:
        context.check_cancelled()
        result = run_single_ping(
            params["target"],
            count=1,
            size=params["packet_size"],
            timeout_ms=params["timeout_ms"],
            source_ip=params["source_ip"],
        )
        rows.append(_safe_probe_row(result))
        context.progress("network_probe", len(rows), 0, f"已完成第 {len(rows)} 次 Ping")
        deadline = time.monotonic() + params["interval_ms"] / 1000
        while time.monotonic() < deadline:
            context.check_cancelled()
            time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
    return rows


def _run_network_export(context: JobContext, *, wireless: bool) -> dict[str, object]:
    site_name = _site_name(context)
    file_format = str(context.params.get("format") or "").strip().lower()
    if file_format not in {"csv", "xlsx"}:
        raise ValueError("导出格式不支持")
    artifact_id = str(context.params.get("artifact_id") or "").strip()
    if not _CONTROLLED_ID_RE.fullmatch(artifact_id):
        raise ValueError("导出 Artifact ID 无效")
    suffix = f".{file_format}"
    display_name = _safe_export_filename(str(context.params.get("filename") or ""), artifact_id, suffix)
    parent_id = str(context.params.get("scan_id" if wireless else "source_task_id") or "").strip()
    output_root = (
        context.paths.wireless_scan_export_dir(site_name)
        if wireless
        else context.paths.toolbox_outputs_dir(site_name)
    ).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    output_path = output_root / f"{artifact_id}{suffix}"
    manifest_path = output_root / f"{artifact_id}.json"
    if output_path.exists() or manifest_path.exists():
        raise ValueError("导出 Artifact 已存在")
    manifest_tmp = output_root / f".{artifact_id}.{context.job_id}.json.tmp"
    source_path: Path | None = None
    temporary_source = False
    completed = False
    try:
        if wireless:
            if not _SCAN_ID_RE.fullmatch(parent_id):
                raise ValueError("无线扫描 ID 无效")
            source_path, columns = _wireless_export_source(context, site_name, parent_id)
            temporary_source = True
        else:
            if not _CONTROLLED_ID_RE.fullmatch(parent_id):
                raise ValueError("网络探测任务 ID 无效")
            source_path = _controlled_result_path(context, site_name, parent_id)
            if source_path is None:
                raise FileNotFoundError("网络探测结果不存在")
            columns = _jsonl_columns(source_path)
        context.check_cancelled()
        row_count = _invoke_export_worker(
            context,
            source_path,
            output_path,
            columns,
            file_format,
        )
        digest, size = _hash_file(output_path)
        manifest = {
            "artifact_id": artifact_id,
            "physical_name": output_path.name,
            "filename": display_name,
            "format": file_format,
            "sha256": digest,
            "size": size,
            "task_id": context.job_id,
            "parent_id": parent_id,
            "site_name": site_name,
            "owner": NETWORK_TOOL_OWNER,
            "source": NETWORK_TASK_SOURCE,
            "task_type": context.task_type,
        }
        _write_json_atomic(manifest_tmp, manifest_path, manifest)
        completed = True
        context.progress("network_export", row_count, row_count, "网络工具导出完成")
        return {"result_id": artifact_id, "row_count": row_count}
    finally:
        if temporary_source and source_path is not None:
            _unlink(source_path)
        _unlink(manifest_tmp)
        if not completed:
            _unlink(output_path)
            _unlink(manifest_path)


def _invoke_export_worker(
    context: JobContext,
    source_path: Path,
    output_path: Path,
    columns: list[dict[str, object]],
    file_format: str,
) -> int:
    work_dir = context.paths.runtime_cache_dir / "network_tool_exports"
    work_dir.mkdir(parents=True, exist_ok=True)
    export_id = uuid4().hex
    job_path = work_dir / f"{export_id}.json"
    job_tmp = work_dir / f".{export_id}.json.tmp"
    cancel_path = work_dir / f"{export_id}.cancel"
    tmp_path = output_path.with_name(f".{output_path.name}.{export_id}.tmp")
    job = ExportJob(
        job_id=export_id,
        job_type="table_csv" if file_format == "csv" else "table_xlsx",
        site_name=str(context.params.get("site_name") or ""),
        output_path=str(output_path),
        tmp_path=str(tmp_path),
        cancel_path=str(cancel_path),
        params={
            "payload": {
                "columns": columns,
                "source": result_file_rows_source(source_path),
                "freeze_header": True,
                "auto_filter": True,
            }
        },
    )
    _write_json_atomic(job_tmp, job_path, job.to_dict())
    process: subprocess.Popen[str] | None = None
    try:
        process = subprocess.Popen(
            _export_worker_command(job_path),
            cwd=str(Path(__file__).resolve().parents[4]),
            env=_export_worker_environment(context),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        terminal, diagnostics = _wait_for_export(context, process, cancel_path)
        if process.returncode != 0 or terminal is None or terminal.get("type") != "finished" or not output_path.is_file():
            message = str((terminal or {}).get("error") or (terminal or {}).get("message") or diagnostics or "导出进程失败")
            raise RuntimeError(message)
        result = terminal.get("result")
        return int(result.get("row_count") or 0) if isinstance(result, dict) else 0
    finally:
        for path in (job_path, job_tmp, cancel_path, tmp_path):
            _unlink(path)
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=3)


def _wait_for_export(
    context: JobContext,
    process: subprocess.Popen[str],
    cancel_path: Path,
) -> tuple[dict[str, object] | None, str]:
    if process.stdout is None or process.stderr is None:
        raise RuntimeError("导出进程未提供输出流")
    lines: Queue[tuple[str, str] | None] = Queue()
    readers = [
        Thread(target=_read_process_output, args=(process.stdout, "stdout", lines), daemon=True),
        Thread(target=_read_process_output, args=(process.stderr, "stderr", lines), daemon=True),
    ]
    for reader in readers:
        reader.start()
    terminal: dict[str, object] | None = None
    diagnostics: list[str] = []
    closed = 0
    try:
        while not (closed == len(readers) and process.poll() is not None):
            if process.poll() is None and context.should_cancel is not None and context.should_cancel():
                _cancel_export_process(process, cancel_path)
                raise BackgroundTaskCancelled("网络工具导出已取消")
            try:
                item = lines.get(timeout=0.1)
            except Empty:
                continue
            if item is None:
                closed += 1
                continue
            stream_name, line = item
            event = parse_event_line(line) if stream_name == "stdout" else None
            if event is None:
                text = line.strip()
                if text:
                    diagnostics = [*diagnostics[-19:], text]
                continue
            if event["type"] == "progress":
                context.progress(
                    str(event.get("stage") or "network_export"),
                    int(event.get("current") or 0),
                    int(event.get("total") or 0),
                    str(event.get("message") or "正在导出网络工具结果"),
                )
            elif event["type"] in {"finished", "error", "cancelled"}:
                terminal = event
        process.wait(timeout=3)
    finally:
        for reader in readers:
            reader.join(timeout=1)
    return terminal, "\n".join(diagnostics)


def _read_process_output(stream: Any, name: str, lines: Queue[tuple[str, str] | None]) -> None:
    try:
        for line in iter(stream.readline, ""):
            lines.put((name, line))
    finally:
        lines.put(None)


def _cancel_export_process(process: subprocess.Popen[str], cancel_path: Path) -> None:
    cancel_path.write_text("cancelled", encoding="utf-8")
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)


def _wireless_export_source(
    context: JobContext,
    site_name: str,
    scan_id: str,
) -> tuple[Path, list[dict[str, object]]]:
    service = WirelessScanService(site_name, context.paths)
    if service.repository.get_run(scan_id) is None:
        raise FileNotFoundError("无线扫描结果不存在")
    rows = [repository_row_to_display_row(row) for row in service.repository.list_results(scan_id)]
    path = context.paths.runtime_cache_dir / "network_tool_exports" / f"{context.job_id}-{uuid4().hex}.jsonl"
    _write_jsonl_atomic(path, rows)
    columns = [{"key": field, "title": field} for _key, field in WIRELESS_SCAN_EXPORT_COLUMNS]
    return path, columns


def _validated_probe_params(kind: str, values: dict[str, Any]) -> dict[str, Any]:
    params = {
        "target": _bounded_text(values.get("target"), 255, "Ping 目标"),
        "targets": [_bounded_text(value, 255, "单个 Ping 目标") for value in values.get("targets") or []],
        "port": _bounded_int(values.get("port"), 1, 65535, 443, "端口"),
        "interval_ms": _bounded_int(values.get("interval_ms"), 1, 60000, 1000, "间隔"),
        "timeout_ms": _bounded_int(values.get("timeout_ms"), 1, 60000, 1500, "超时"),
        "count": _bounded_int(values.get("count"), 1, 1000, 4, "次数"),
        "packet_size": _bounded_int(values.get("packet_size"), 1, 65500, 32, "包大小"),
        "concurrency": _bounded_int(values.get("concurrency"), 1, 500, 100, "并发数"),
        "source_ip": _bounded_text(values.get("source_ip"), 128, "源地址"),
    }
    if kind in {"single_ping", "continuous_ping", "subnet_ping", "tcp_ping"} and not params["target"]:
        raise ValueError("请提供目标地址")
    if kind in {"batch_ping", "subnet_ping"}:
        _targets_for_probe(kind, params)
    return params


def _targets_for_probe(kind: str, params: dict[str, Any]) -> list[str]:
    if kind == "subnet_ping":
        network = ipaddress.ip_network(params["target"], strict=False)
        if network.version != 4:
            raise ValueError("网段 Ping 只支持 IPv4")
        host_count = network.num_addresses if network.prefixlen >= 31 else max(0, network.num_addresses - 2)
        if host_count > 4096:
            raise ValueError("批量或网段 Ping 最多支持 4096 个地址")
        targets = [str(address) for address in network.hosts()]
    else:
        raw_targets = params["targets"]
        if not isinstance(raw_targets, list):
            raise ValueError("批量 Ping 目标格式无效")
        targets = [str(value).strip() for value in raw_targets if str(value).strip()]
    if not targets:
        raise ValueError("请至少提供一个 Ping 目标")
    if len(targets) > 4096:
        raise ValueError("批量或网段 Ping 最多支持 4096 个地址")
    return targets


def _find_wireless_adapter(service: WirelessScanService, name: str, guid: str) -> Any | None:
    if not name and not guid:
        return None
    for adapter in service.list_adapters():
        if (guid and adapter.guid == guid) or (name and adapter.name == name):
            return adapter
    raise ValueError("无线网卡不存在")


def _site_name(context: JobContext) -> str:
    return SiteManager(context.paths).validate_site_name(str(context.params.get("site_name") or "demo"))


def _probe_result_path(context: JobContext, site_name: str) -> Path:
    if not _CONTROLLED_ID_RE.fullmatch(context.job_id):
        raise ValueError("网络工具任务 ID 无效")
    return context.paths.toolbox_outputs_dir(site_name) / f"{context.job_id}.jsonl"


def _controlled_result_path(context: JobContext, site_name: str, task_id: str) -> Path | None:
    root = context.paths.toolbox_outputs_dir(site_name).resolve()
    path = (root / f"{task_id}.jsonl").resolve()
    return path if path.parent == root and path.is_file() else None


def _safe_probe_row(value: object) -> dict[str, object]:
    from dataclasses import asdict

    row = asdict(value)  # type: ignore[arg-type]
    row.pop("raw_output", None)
    return row


def _write_jsonl_atomic(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, default=str, separators=(",", ":")))
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        _unlink(temp)


def _write_json_atomic(temp: Path, path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        _unlink(temp)


def _jsonl_columns(path: Path) -> list[dict[str, object]]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if isinstance(row, dict):
                return [{"key": str(key), "title": str(key)} for key in row]
    return []


def _safe_export_filename(value: str, artifact_id: str, suffix: str) -> str:
    selected = value.strip() or f"{artifact_id}{suffix}"
    if (
        selected in {".", ".."}
        or any(separator in selected for separator in ("/", "\\", "\x00"))
        or Path(selected).name != selected
        or any(character in _INVALID_FILENAME_CHARS for character in selected)
        or any(ord(character) < 32 for character in selected)
    ):
        raise ValueError("导出文件名不允许包含路径或非法字符")
    if Path(selected).suffix.lower() != suffix:
        selected = f"{Path(selected).stem or artifact_id}{suffix}"
    return selected


def _bounded_text(value: object, maximum: int, label: str) -> str:
    text = str(value or "").strip()
    if len(text) > maximum:
        raise ValueError(f"{label}最多 {maximum} 个字符")
    return text


def _bounded_int(value: object, minimum: int, maximum: int, default: int, label: str) -> int:
    try:
        selected = int(value if value is not None else default)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}格式无效") from exc
    if selected < minimum or selected > maximum:
        raise ValueError(f"{label}必须在 {minimum}-{maximum} 之间")
    return selected


def _export_worker_command(job_path: Path) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--export-worker", "--job", str(job_path)]
    return [sys.executable, "-m", "netconsole.export_worker", "--job", str(job_path)]


def _export_worker_environment(context: JobContext) -> dict[str, str]:
    environment = dict(os.environ)
    environment["NETCONSOLE_DATA_ROOT"] = str(context.paths.data_root)
    if not getattr(sys, "frozen", False):
        source_root = str(Path(__file__).resolve().parents[3])
        existing = environment.get("PYTHONPATH", "")
        environment["PYTHONPATH"] = os.pathsep.join(value for value in (source_root, existing) if value)
    return environment


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


HANDLERS = {
    **{task_type: run_network_probe for task_type in NETWORK_PROBE_TASK_TYPES},
    NETWORK_WIRELESS_SCAN_TASK: run_wireless_scan,
    NETWORK_TOOLBOX_EXPORT_TASK: run_toolbox_export,
    NETWORK_WIRELESS_EXPORT_TASK: run_wireless_export,
}


__all__ = [
    "HANDLERS",
    "NETWORK_EXPORT_TASK_TYPES",
    "NETWORK_PROBE_TASK_TYPES",
    "NETWORK_TASK_SOURCE",
    "NETWORK_TOOLBOX_EXPORT_TASK",
    "NETWORK_TOOLBOX_TASK_TYPES",
    "NETWORK_TOOL_OWNER",
    "NETWORK_WIRELESS_EXPORT_TASK",
    "NETWORK_WIRELESS_SCAN_TASK",
    "NETWORK_WIRELESS_TASK_TYPES",
]
