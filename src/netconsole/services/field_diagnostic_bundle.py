"""只读现场诊断包采集器。

采集器运行在 Export Worker 中，所有输入均为可序列化参数。它不打开业务
数据库写连接、不触发 checkpoint，也不停止任何运行中的采集器。
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import platform
import re
import socket
import subprocess
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from netconsole.core.storage_io import detect_storage_profile
from netconsole.core.version import APP_VERSION
from netconsole.services.export.common_exporters import ExportCancelled
from netconsole.services.system_maintenance_redaction import redact_system_maintenance_text

ProgressCallback = Callable[[str, int, int, str], None]
CancelCallback = Callable[[], bool]

MAX_BUNDLE_BYTES = 200 * 1024 * 1024
MAX_LOG_BYTES = 20 * 1024 * 1024
MAX_RAW_BYTES = 5 * 1024 * 1024
MAX_RAW_LINES = 1000
MAX_LARGEST_FILES = 100
MAX_SCANNED_FILES = 50_000
MAX_DISCOVERED_LOG_FILES = 200
MAX_RAW_SOURCE_FILES = 20

SAFE_RUNTIME_HEALTH_FIELDS = frozenset(
    {
        "status",
        "udp_running",
        "udp_receive_rate_per_second",
        "udp_received_count",
        "udp_unidentified_count",
        "udp_identity_conflict_count",
        "udp_last_received_at",
        "udp_queue_length",
        "udp_queue_capacity",
        "udp_queue_pressure",
        "udp_dropped_count",
        "raw_records_written",
        "raw_bytes_written",
        "raw_last_write_duration_ms",
        "database_pending_count",
        "database_last_batch_duration_ms",
        "open_file_count",
        "deep_queue_length",
        "archive_pending_count",
        "disk_free_bytes",
        "updated_at",
        "receiver_alive",
        "writer_alive",
        "parser_alive",
        "received",
        "written",
        "parsed",
        "db_saved",
        "dropped",
        "memory_queue_size",
        "memory_queue_capacity",
        "disk_queue_count",
        "parser_queue_size",
        "parser_queue_capacity",
        "raw_file_size",
        "last_write_time",
        "spool_bytes",
        "spool_files",
        "disk_usage_percent",
        "spool_guard_state",
        "spool_warning_percent",
        "spool_critical_percent",
        "spool_emergency_percent",
        "volume",
        "media_type",
        "media_confidence",
        "storage_profile",
        "profile_source",
    }
)


class DiagnosticCancelled(ExportCancelled):
    """用户取消诊断采集。"""


def _cancelled(should_cancel: CancelCallback | None) -> bool:
    return bool(should_cancel and should_cancel())


def _json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str).encode("utf-8")


def _safe_rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        return path.name


def _section(status: str = "ok", *, data: Any = None, reason: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {"status": status}
    if data is not None:
        result["data"] = data
    if reason:
        result["reason"] = reason[:500]
    return result


def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        blocked = ("password", "passwd", "secret", "token", "api_key", "authorization", "cookie", "community", "private_key")
        return {
            str(key): "[REDACTED]" if any(item in str(key).casefold() for item in blocked) else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return [_redact(item) for item in value]
    return value


class DiagnosticRedactor:
    """配置只允许白名单字段；文本仅做有限秘密键替换。"""

    ALLOWLIST = frozenset({
        "storage_profile", "profile_source", "udp_port", "queue_capacity",
        "raw_batch_bytes", "db_batch_size", "flush_interval_ms", "durable_sync_interval_ms",
        "parser_batch_size", "archive_during_active_collection", "site_id", "site_name",
    })

    @classmethod
    def config(cls, value: Mapping[str, Any] | None) -> dict[str, Any]:
        source = value or {}
        return {key: _redact(source[key]) for key in cls.ALLOWLIST if key in source}

    @staticmethod
    def text(value: str) -> str:
        result = redact_system_maintenance_text(value)
        return re.sub(
            r"(?im)\b(password|passwd|secret|community|private-key)\s+(?:(?:cipher|simple)\s+)?\S+",
            r"\1 [REDACTED]",
            result,
        )


def _validated_scope(data_root: Path, site_name: str) -> tuple[Path, Path]:
    selected = str(site_name or "").strip()
    if (
        not selected
        or selected in {".", ".."}
        or Path(selected).name != selected
        or "/" in selected
        or "\\" in selected
        or any(ord(character) < 32 for character in selected)
    ):
        raise ValueError("诊断包局点范围无效")
    sites_root = (data_root / "sites").resolve()
    site_root = (sites_root / selected).resolve()
    if site_root.parent != sites_root:
        raise ValueError("诊断包局点范围越界")
    ground_root = (
        site_root / "files" / "rail_transit" / "ground_unattended"
    ).resolve()
    if not ground_root.is_relative_to(site_root):
        raise ValueError("诊断包 Ground 范围越界")
    return site_root, ground_root


def safe_runtime_health(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {
        key: _redact(value[key])
        for key in SAFE_RUNTIME_HEALTH_FIELDS
        if key in value
    }


def _run_powershell(command: str, timeout: float = 4.0) -> tuple[Any, str]:
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, check=False,
        )
        if result.returncode:
            return None, f"exit_code={result.returncode}"
        return json.loads(result.stdout or "null"), ""
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _windows_storage(root: Path) -> dict[str, Any]:
    drive = root.drive.rstrip(":")
    if not drive:
        return _section("unavailable", reason="data_root 没有 Windows 卷标识")
    command = (
        f"$p=Get-Partition -DriveLetter '{drive}' -ErrorAction SilentlyContinue; "
        "$d=$p | Get-Disk -ErrorAction SilentlyContinue; "
        "@{partition=$p;disk=$d} | ConvertTo-Json -Depth 5"
    )
    value, reason = _run_powershell(command)
    if value is None:
        return _section("unavailable", reason=reason)
    return _section(data=value)


def _raid_tools() -> dict[str, Any]:
    names = ("storcli64.exe", "perccli64.exe", "ssacli.exe", "hpssacli.exe")
    detected = []
    for name in names:
        try:
            result = subprocess.run(["where", name], capture_output=True, text=True, timeout=1, check=False)
            if result.returncode == 0:
                detected.append(name)
        except Exception:
            continue
    return {"status": "not_available" if not detected else "detected_only", "detected_tools": detected}


def _file_inventory(root: Path, should_cancel: CancelCallback | None) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    total = 0
    count = 0
    directories: dict[str, int] = {}
    largest: list[dict[str, Any]] = []
    active: list[dict[str, Any]] = []
    active_suffixes = (".ndjson", ".log", ".db-wal", ".db-shm", ".part", ".tmp")
    try:
        iterator = root.rglob("*")
        for path in iterator:
            if _cancelled(should_cancel):
                raise DiagnosticCancelled("诊断采集已取消")
            try:
                if not path.is_file() or path.is_symlink():
                    continue
                stat = path.stat()
            except OSError:
                continue
            size = max(0, int(stat.st_size))
            rel = _safe_rel(path, root)
            total += size
            count += 1
            first = rel.split("/", 1)[0] if "/" in rel else rel
            directories[first] = directories.get(first, 0) + size
            item = {"relative_path": rel, "size_bytes": size, "mtime": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(), "extension": path.suffix.lower(), "category": "file"}
            largest.append(item)
            if path.name.lower().endswith(active_suffixes) or "spool" in path.name.lower():
                active.append({**item, "inferred_active": True, "writer_owner": None})
            if count >= MAX_SCANNED_FILES:
                break
    except FileNotFoundError:
        pass
    largest.sort(key=lambda item: item["size_bytes"], reverse=True)
    active.sort(key=lambda item: item["size_bytes"], reverse=True)
    inventory = {
        "status": "partial" if count >= MAX_SCANNED_FILES else "ok",
        "scope": "current_site",
        "total_bytes_scanned": total,
        "file_count_scanned": count,
        "scan_limit": MAX_SCANNED_FILES,
        "top_level_bytes_scanned": directories,
    }
    return inventory, largest[:MAX_LARGEST_FILES], active[:MAX_LARGEST_FILES]


def _tail_file(path: Path, max_bytes: int) -> tuple[bytes, str]:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            end = handle.tell()
            handle.seek(max(0, end - max_bytes))
            return handle.read(max_bytes), ""
    except OSError as exc:
        return b"", f"{type(exc).__name__}: {exc}"


def _collect_logs(
    roots: Iterable[tuple[str, Path]],
    scope_root: Path,
    log_window_minutes: int,
    should_cancel: CancelCallback | None,
) -> tuple[dict[str, bytes], list[str]]:
    now = time.time()
    selected: list[Path] = []
    labels: dict[Path, str] = {}
    for label, candidate_root in roots:
        if not candidate_root.exists():
            continue
        try:
            for path in candidate_root.rglob("*.log"):
                if len(selected) >= MAX_DISCOVERED_LOG_FILES:
                    break
                if (
                    path.is_file()
                    and not path.is_symlink()
                    and now - path.stat().st_mtime <= log_window_minutes * 60
                    and path not in selected
                ):
                    selected.append(path)
                    labels[path] = label
        except OSError:
            continue
    selected.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    selected = selected[:3]
    outputs: dict[str, bytes] = {}
    warnings: list[str] = []
    for index, path in enumerate(selected):
        if _cancelled(should_cancel):
            raise DiagnosticCancelled("诊断采集已取消")
        data, reason = _tail_file(path, MAX_LOG_BYTES)
        if reason:
            warnings.append(f"log:{_safe_rel(path, scope_root)}: {reason}")
            continue
        label = re.sub(r"[^a-z0-9_-]+", "_", labels.get(path, "runtime").casefold())
        outputs[f"logs/{label}_{index + 1}_recent.log"] = DiagnosticRedactor.text(
            data.decode("utf-8", errors="replace")
        ).encode("utf-8")
    return outputs, warnings


def _raw_sample(root: Path, should_cancel: CancelCallback | None) -> tuple[bytes, dict[str, Any]]:
    candidates: list[Path] = []
    try:
        for path in root.rglob("*.ndjson"):
            if path.is_file() and not path.is_symlink():
                candidates.append(path)
    except OSError:
        pass
    candidates.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    lines: list[bytes] = []
    remaining = MAX_RAW_BYTES
    for path in candidates[:MAX_RAW_SOURCE_FILES]:
        if _cancelled(should_cancel):
            raise DiagnosticCancelled("诊断采集已取消")
        chunk, _reason = _tail_file(path, remaining)
        for line in chunk.splitlines()[-MAX_RAW_LINES:]:
            if not line:
                continue
            line = line[:remaining]
            lines.append(line + b"\n")
            remaining -= len(line) + 1
            if remaining <= 0 or len(lines) >= MAX_RAW_LINES:
                break
        if remaining <= 0 or len(lines) >= MAX_RAW_LINES:
            break
    payload = DiagnosticRedactor.text(b"".join(lines)[-MAX_RAW_BYTES:].decode("utf-8", errors="replace")).encode("utf-8")[-MAX_RAW_BYTES:]
    return payload, {
        "status": "ok",
        "records": len(lines),
        "bytes": len(payload),
        "source_files_considered": min(len(candidates), MAX_RAW_SOURCE_FILES),
    }


def _performance_snapshot(root: Path, duration_minutes: int, should_cancel: CancelCallback | None, progress: ProgressCallback | None) -> tuple[bytes, bytes, list[str]]:
    duration = max(0, min(int(duration_minutes), 30))
    samples = 1 if duration == 0 else max(1, min(360, duration * 60 // 5))
    disk_rows: list[dict[str, Any]] = []
    process_rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    for index in range(samples):
        if _cancelled(should_cancel):
            raise DiagnosticCancelled("诊断采集已取消")
        drive = root.drive.rstrip("\\")
        disk, disk_reason = _run_powershell(
            "Get-Counter "
            f"'\\LogicalDisk({drive})\\Avg. Disk sec/Read',"
            f"'\\LogicalDisk({drive})\\Avg. Disk sec/Write',"
            f"'\\LogicalDisk({drive})\\Disk Reads/sec',"
            f"'\\LogicalDisk({drive})\\Disk Writes/sec',"
            f"'\\LogicalDisk({drive})\\Current Disk Queue Length' "
            "| Select-Object -ExpandProperty CounterSamples "
            "| Select-Object InstanceName,Path,CookedValue | ConvertTo-Json -Depth 3"
        )
        if disk is None:
            warnings.append(f"windows_disk_perf: {disk_reason}")
            disk = []
        disk_items = disk if isinstance(disk, list) else [disk]
        for item in disk_items:
            if isinstance(item, Mapping):
                disk_rows.append({"sample": index, "volume": drive, **dict(item)})
        process_rows.append({"sample": index, "pid": os.getpid(), "process": "NetConsole export worker", "cpu_percent": None, "working_set_bytes": None, "thread_count": None})
        if progress:
            progress("performance", index + 1, samples, f"正在采样性能 {index + 1}/{samples}")
        if index + 1 < samples:
            time.sleep(5)
    def csv_bytes(rows: Iterable[Mapping[str, Any]], headers: tuple[str, ...]) -> bytes:
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        return stream.getvalue().encode("utf-8-sig")
    disk_headers = ("sample", "volume", "InstanceName", "Path", "CookedValue")
    proc_headers = ("sample", "pid", "process", "cpu_percent", "working_set_bytes", "thread_count")
    return csv_bytes(disk_rows, disk_headers), csv_bytes(process_rows, proc_headers), warnings


def collect_field_diagnostic_bundle(params: Mapping[str, Any], output_path: str | Path, *, progress_callback: ProgressCallback | None = None, should_cancel: CancelCallback | None = None) -> dict[str, Any]:
    raw_root = str(params.get("data_root") or "").strip()
    if not raw_root:
        raise ValueError("诊断包缺少 data_root")
    data_root = Path(raw_root).resolve()
    site_name = str(params.get("site_name") or "")
    site_root, ground_root = _validated_scope(data_root, site_name)
    warnings: list[str] = []
    failed_sections: list[str] = []
    files: dict[str, bytes] = {}
    def add_json(name: str, value: Any) -> None:
        files[name] = _json(value)
    if progress_callback:
        progress_callback("prepare", 0, 7, "正在准备只读诊断采集")
    try:
        detection, profile = detect_storage_profile(data_root)
        add_json("storage/storage_profile.json", {"detection": detection.to_dict(), "profile": profile.to_dict()})
        windows_storage = _windows_storage(data_root)
        add_json("storage/windows_storage.json", windows_storage)
        storage_data = windows_storage.get("data") if isinstance(windows_storage, Mapping) else None
        if isinstance(storage_data, Mapping):
            add_json("storage/volumes.json", storage_data.get("partition") or _section("unavailable", reason="未发现卷信息"))
            add_json("storage/disks.json", storage_data.get("disk") or _section("unavailable", reason="未发现磁盘信息"))
        else:
            for name in ("volumes.json", "disks.json"):
                add_json(f"storage/{name}", windows_storage)
        add_json("storage/raid_controller.json", _raid_tools())
        add_json(
            "storage/storage_mapping.json",
            {
                "volume": detection.volume,
                "media_type": detection.media_type,
                "confidence": detection.confidence,
                "profile": detection.profile,
                "reason": detection.reason,
            },
        )
    except Exception as exc:
        failed_sections.append("storage")
        warnings.append(f"storage: {type(exc).__name__}: {exc}")
    runtime = (
        params.get("runtime_snapshot")
        if isinstance(params.get("runtime_snapshot"), Mapping)
        else {}
    )
    safe_runtime = safe_runtime_health(runtime)
    add_json(
        "runtime/ground_health.json",
        _section(data=safe_runtime)
        if safe_runtime
        else _section("unavailable", reason="导出进程未连接 Ground 内存状态"),
    )
    add_json("config/effective_runtime_config.json", DiagnosticRedactor.config(params.get("runtime_config") if isinstance(params.get("runtime_config"), Mapping) else params))
    try:
        inventory, largest, active = _file_inventory(site_root, should_cancel)
        add_json("files/storage_inventory.json", inventory)
        add_json("files/largest_files.json", {"status": "ok", "files": largest})
        add_json("files/active_write_files.json", {"status": "ok", "files": active, "active_raw_writer_count": sum(1 for item in active if str(item.get("extension")) == ".ndjson")})
    except DiagnosticCancelled:
        raise
    except Exception as exc:
        failed_sections.append("file_inventory")
        warnings.append(f"file_inventory: {type(exc).__name__}: {exc}")
    if bool(params.get("raw_sample", False)):
        raw, raw_meta = _raw_sample(ground_root / "active", should_cancel)
        files["samples/raw_sample.ndjson"] = raw
        add_json("samples/raw_sample_meta.json", raw_meta)
    else:
        raw, raw_meta = b"", {"status": "excluded", "records": 0, "bytes": 0}
        add_json("samples/raw_sample_meta.json", raw_meta)
    log_files, log_warnings = _collect_logs(
        (
            ("application", data_root / "runtime" / "logs"),
            ("ground", ground_root),
        ),
        site_root,
        int(params.get("log_window_minutes") or 30),
        should_cancel,
    )
    files.update(log_files)
    warnings.extend(log_warnings)
    disk_csv, process_csv, perf_warnings = _performance_snapshot(data_root, int(params.get("sample_duration_minutes") or 0), should_cancel, progress_callback)
    files["performance/windows_disk_perf.csv"] = disk_csv
    files["performance/process_perf.csv"] = process_csv
    warnings.extend(perf_warnings)
    if progress_callback:
        progress_callback("package", 6, 7, "正在生成诊断包")
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    summary = {
        "storage": {"volume": str(data_root.drive or ""), "media_type": None, "confidence": None, "profile": None, "profile_source": None},
        "ground": safe_runtime or None,
        "process": None,
    }
    try:
        storage = json.loads(files["storage/storage_profile.json"].decode("utf-8"))
        detection = storage.get("detection", {})
        summary["storage"].update({key: detection.get(key) for key in ("media_type", "confidence", "profile")})
        summary["storage"]["profile_source"] = storage.get("profile", {}).get("profile_source")
    except Exception:
        pass
    manifest = {
        "bundle_version": "1",
        "created_at": created_at,
        "app_version": APP_VERSION,
        "git_revision": str(params.get("git_revision") or ""),
        "host_name": socket.gethostname(),
        "os_version": platform.platform(),
        "architecture": platform.machine(),
        "data_volume": str(data_root.drive or ""),
        "site_id": site_name,
        "site_name": site_name,
        "collection_window": {
            "sample_duration_minutes": int(params.get("sample_duration_minutes") or 0),
            "log_window_minutes": int(params.get("log_window_minutes") or 30),
        },
        "raw_sample_included": bool(params.get("raw_sample", False)),
        "redaction_policy": "allowlist-config; current-site-scope; bounded-tail-samples",
        "included_sections": sorted(files),
        "failed_sections": failed_sections,
        "warnings": warnings,
    }
    add_json("summary.json", _redact(summary))
    add_json("manifest.json", manifest)
    integrity_entries: list[dict[str, Any]] = []
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=3) as archive:
        for name in sorted(files):
            if _cancelled(should_cancel):
                raise DiagnosticCancelled("诊断采集已取消")
            data = files[name]
            if sum(item["size_bytes"] for item in integrity_entries) + len(data) > MAX_BUNDLE_BYTES:
                warnings.append(f"bundle_size_limit: skipped {name}")
                continue
            archive.writestr(name, data)
            integrity_entries.append({"path": name, "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        integrity = {"status": "PARTIAL" if failed_sections or warnings else "OK", "failed_sections": failed_sections, "warnings": warnings, "files": integrity_entries}
        archive.writestr("bundle_integrity.json", _json(integrity))
    if progress_callback:
        progress_callback("package", 7, 7, "诊断包生成完成")
    return {"path": str(target), "size_bytes": target.stat().st_size, "failed_sections": failed_sections, "warnings": warnings, "sample_records": raw_meta.get("records", 0)}


__all__ = [
    "DiagnosticCancelled",
    "DiagnosticRedactor",
    "collect_field_diagnostic_bundle",
    "safe_runtime_health",
]
