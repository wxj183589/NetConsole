from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from netconsole.core.database import Database
from netconsole.repositories.config_snapshot_repository import ConfigSnapshotRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.config_lifecycle_service import ConfigLifecycleService, safe_device_name
from netconsole.services.export.export_task_builders import config_diff_text_spec, config_snapshots_zip_spec
from netconsole.services.job_center.job_context import BackgroundTaskCancelled, JobContext
from netconsole.services.job_center.worker_protocol import parse_event_line


CONFIG_WEB_SAVE_TASK = "config_web_save_force"
CONFIG_WEB_EXPORT_DIFF_TASK = "config_web_export_diff"
CONFIG_WEB_EXPORT_SNAPSHOTS_TASK = "config_web_export_snapshots"
CONFIG_WEB_EXPORT_TASKS = frozenset({CONFIG_WEB_EXPORT_DIFF_TASK, CONFIG_WEB_EXPORT_SNAPSHOTS_TASK})


def config_web_save_force(context: JobContext) -> dict[str, object]:
    device_uuids = list(dict.fromkeys(str(value) for value in context.params.get("device_uuids") or [] if value))
    if not device_uuids or len(device_uuids) > 50:
        raise ValueError("一次最多保存 50 台设备配置")
    database = Database(Path(str(context.params.get("db_path") or "")))
    devices = DeviceRepository(database)
    service = ConfigLifecycleService(str(context.params.get("site_name") or ""), database, context.paths)
    saved_snapshot_ids: list[int] = []
    failed_items: list[dict[str, str]] = []
    total = len(device_uuids)
    for index, device_uuid in enumerate(device_uuids, start=1):
        context.check_cancelled()
        context.progress("config_save_force", index - 1, total, f"正在保存设备配置 {index}/{total}")
        device = devices.get_by_uuid(device_uuid)
        if device is None or str(device.device_vendor or "").upper() != "H3C":
            failed_items.append({"device_uuid": device_uuid, "error": "H3C 设备不存在"})
            continue
        result = service.save_force(device)
        if result.success:
            saved_snapshot_ids.extend(int(item.id) for item in result.snapshots if item.id is not None)
        else:
            failed_items.append({"device_uuid": device_uuid, "error": str(result.error_message or "保存配置失败")})
    context.progress("config_save_force", total, total, "设备配置保存完成")
    if failed_items and not saved_snapshot_ids:
        raise RuntimeError(f"保存配置失败：{failed_items[0]['error']}")
    return {
        "total": total,
        "saved": total - len(failed_items),
        "failed": len(failed_items),
        "failed_items": failed_items,
        "snapshot_ids": saved_snapshot_ids,
        "partial_success": bool(failed_items),
    }


def config_web_export_diff(context: JobContext) -> dict[str, object]:
    repository = _snapshot_repository(context)
    left_id = int(context.params.get("left_snapshot_id") or 0)
    right_id = int(context.params.get("right_snapshot_id") or 0)
    repository.get(left_id)
    repository.get(right_id)
    artifact_id, output_path, display_name = _artifact_target(context, ".diff", "配置差异")
    spec = config_diff_text_spec(
        output_path,
        db_path=str(context.params.get("db_path") or ""),
        site_name=str(context.params.get("site_name") or ""),
        app_root=context.paths.app_root,
        data_root=context.paths.data_root,
        left_snapshot_id=left_id,
        right_snapshot_id=right_id,
        title="导出配置差异",
        open_dir_on_success=False,
    )
    return _run_export(context, spec.to_job(f"{context.job_id}-export"), artifact_id, output_path, display_name)


def config_web_export_snapshots(context: JobContext) -> dict[str, object]:
    repository = _snapshot_repository(context)
    snapshot_ids = list(dict.fromkeys(int(value) for value in context.params.get("snapshot_ids") or [] if int(value) > 0))
    if not snapshot_ids or len(snapshot_ids) > 200:
        raise ValueError("一次最多导出 200 个配置快照")
    entries: list[dict[str, object]] = []
    for snapshot_id in snapshot_ids:
        snapshot = repository.get(snapshot_id)
        suffix = "diff" if snapshot.type == "diff" else "txt"
        folder = safe_device_name(snapshot.device_uuid or "device")
        snapshot_type = safe_device_name(snapshot.type or "snapshot")
        timestamp = safe_device_name(snapshot.timestamp or str(snapshot_id))
        entries.append(
            {
                "snapshot_id": snapshot_id,
                "archive_name": f"{folder}/{snapshot_type}_{timestamp}.{suffix}",
            }
        )
    artifact_id, output_path, display_name = _artifact_target(context, ".zip", "配置快照")
    spec = config_snapshots_zip_spec(
        output_path,
        db_path=str(context.params.get("db_path") or ""),
        site_name=str(context.params.get("site_name") or ""),
        snapshot_entries=entries,
        title="批量导出配置快照",
        open_dir_on_success=False,
    )
    return _run_export(context, spec.to_job(f"{context.job_id}-export"), artifact_id, output_path, display_name)


def _snapshot_repository(context: JobContext) -> ConfigSnapshotRepository:
    return ConfigSnapshotRepository(Database(Path(str(context.params.get("db_path") or ""))), ensure_schema=False)


def _artifact_target(context: JobContext, suffix: str, label: str) -> tuple[str, Path, str]:
    site_name = str(context.params.get("site_name") or "")
    artifact_id = f"export-{uuid4().hex}"
    root = context.paths.config_center_root(site_name) / "outputs"
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return artifact_id, root / f"{artifact_id}{suffix}", f"{label}_{stamp}{suffix}"


def _run_export(context: JobContext, job, artifact_id: str, output_path: Path, display_name: str) -> dict[str, object]:
    context.check_cancelled()
    runtime_dir = context.paths.runtime_cache_dir / "export_jobs"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    job_path = runtime_dir / f"{job.job_id}.json"
    cancel_path = runtime_dir / f"{job.job_id}.cancel"
    tmp_path = output_path.with_suffix(f"{output_path.suffix}.tmp")
    manifest_path = output_path.parent / f"{artifact_id}.json"
    manifest_tmp = manifest_path.with_suffix(".json.tmp")
    runtime_job = job.with_runtime_paths(tmp_path=str(tmp_path), cancel_path=str(cancel_path))
    completed = False
    process: subprocess.Popen[str] | None = None
    try:
        job_path.write_text(json.dumps(runtime_job.to_dict(), ensure_ascii=False), encoding="utf-8")
        context.progress("config_export", 0, 1, "正在启动配置导出进程")
        process = subprocess.Popen(
            _export_worker_command(job_path),
            cwd=str(context.paths.app_root),
            env=_export_worker_environment(context),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        stdout, _stderr = _wait_for_export(context, process, cancel_path)
        terminal: dict[str, object] | None = None
        for line in stdout.splitlines():
            event = parse_event_line(line)
            if event is None:
                continue
            if event["type"] == "progress":
                context.progress(
                    str(event.get("stage") or "config_export"),
                    int(event.get("current") or 0),
                    int(event.get("total") or 0),
                    str(event.get("message") or "正在导出配置"),
                )
            elif event["type"] in {"finished", "error", "cancelled"}:
                terminal = event
        if terminal is None or terminal.get("type") != "finished" or process.returncode != 0:
            if terminal and (terminal.get("cancelled") or terminal.get("type") == "cancelled"):
                raise BackgroundTaskCancelled("配置导出已取消")
            raise RuntimeError(str((terminal or {}).get("error") or (terminal or {}).get("message") or "配置导出失败"))
        if not output_path.is_file() or output_path.is_symlink():
            raise RuntimeError("配置导出未生成有效 Artifact")
        digest = _sha256_file(output_path)
        size = output_path.stat().st_size
        manifest = {
            "schema_version": 1,
            "artifact_id": artifact_id,
            "site_name": str(context.params.get("site_name") or ""),
            "task_id": context.job_id,
            "task_type": context.task_type,
            "owner": str(context.params.get("owner") or ""),
            "source": str(context.params.get("task_source") or ""),
            "status": "COMPLETED",
            "display_name": display_name,
            "physical_name": output_path.name,
            "sha256": digest,
            "size_bytes": size,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        manifest_tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(manifest_tmp, manifest_path)
        completed = True
        context.progress("config_export", 1, 1, "配置导出完成")
        return {"artifact_id": artifact_id, "hash": digest, "size": size, "display_name": display_name}
    finally:
        for path in (job_path, cancel_path, tmp_path, manifest_tmp):
            _unlink(path)
        if not completed:
            _unlink(output_path)
            _unlink(manifest_path)
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=3)


def _wait_for_export(context: JobContext, process: subprocess.Popen[str], cancel_path: Path) -> tuple[str, str]:
    while True:
        try:
            return process.communicate(timeout=0.1)
        except subprocess.TimeoutExpired:
            if context.should_cancel is None or not context.should_cancel():
                continue
            cancel_path.write_text("cancelled", encoding="utf-8")
            try:
                process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            raise BackgroundTaskCancelled("配置导出已取消")


def _export_worker_command(job_path: Path) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--export-worker", "--job", str(job_path)]
    return [sys.executable, "-m", "netconsole.export_worker", "--job", str(job_path)]


def _export_worker_environment(context: JobContext) -> dict[str, str]:
    environment = dict(os.environ)
    environment["NETCONSOLE_DATA_ROOT"] = str(context.paths.data_root)
    if not getattr(sys, "frozen", False):
        source_root = str(Path(__file__).resolve().parents[2])
        existing = environment.get("PYTHONPATH", "")
        environment["PYTHONPATH"] = os.pathsep.join(value for value in (source_root, existing) if value)
    return environment


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


HANDLERS = {
    CONFIG_WEB_SAVE_TASK: config_web_save_force,
    CONFIG_WEB_EXPORT_DIFF_TASK: config_web_export_diff,
    CONFIG_WEB_EXPORT_SNAPSHOTS_TASK: config_web_export_snapshots,
}


__all__ = [
    "CONFIG_WEB_EXPORT_TASKS",
    "CONFIG_WEB_SAVE_TASK",
    "HANDLERS",
    "config_web_export_diff",
    "config_web_export_snapshots",
    "config_web_save_force",
]
