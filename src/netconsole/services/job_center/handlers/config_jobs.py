from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from netconsole.core.database import Database
from netconsole.models.device import Device
from netconsole.repositories.config_snapshot_repository import (
    ConfigSnapshot,
    ConfigSnapshotRepository,
)
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services import config_collection_job_handlers
from netconsole.services.config_lifecycle_service import (
    ConfigLifecycleService,
    build_side_by_side_rows,
    clean_config_for_diff,
    compare_named_config_text,
    structure_diff,
)
from netconsole.services.job_center.job_context import JobContext


def config_compare_latest_running_between_devices(context: JobContext) -> dict[str, object]:
    context.progress("config_compare", 0, 1, "正在比较两台设备最新 running 配置")
    context.check_cancelled()
    repository, service, database = _snapshot_context(context)
    del repository
    left_device = _device_by_uuid(database, str(context.params.get("device_uuid_a") or ""))
    right_device = _device_by_uuid(database, str(context.params.get("device_uuid_b") or ""))
    left_snapshots = service.list_device_snapshots(left_device, "running")
    right_snapshots = service.list_device_snapshots(right_device, "running")
    if not left_snapshots or not right_snapshots:
        raise ValueError("两台设备都需要先采集 running 配置。")
    left_text = service.snapshot_text(left_snapshots[0])
    right_text = service.snapshot_text(right_snapshots[0])
    left_label = _device_label(left_device, "device_a")
    right_label = _device_label(right_device, "device_b")
    result = _diff_payload("two_devices", left_label, right_label, left_text, right_text)
    result["structure_diff"] = structure_diff(left_text, right_text)
    result["diff_file"] = str(_write_diff_file(context, "two_devices_diff", str(result["raw_diff"])))
    context.progress("config_compare", 1, 1, "配置比较完成")
    return result


def config_compare_latest_snapshots(context: JobContext) -> dict[str, object]:
    context.progress("config_compare", 0, 1, "正在比较最新 running/saved 配置")
    context.check_cancelled()
    _repository, service, database = _snapshot_context(context)
    device = _device_by_uuid(database, str(context.params.get("device_uuid") or ""))
    running = service.list_device_snapshots(device, "running")
    saved = service.list_device_snapshots(device, "saved")
    if not running or not saved:
        raise ValueError("需要先采集 running 和 saved 配置。")
    result = _snapshot_diff_payload(service, running[0], saved[0], "latest_snapshots")
    result["diff_file"] = str(_write_diff_file(context, "latest_snapshots_diff", str(result["raw_diff"])))
    context.progress("config_compare", 1, 1, "配置比较完成")
    return result


def config_compare_snapshot_pair(context: JobContext) -> dict[str, object]:
    context.progress("config_compare", 0, 1, "正在比较配置快照")
    context.check_cancelled()
    repository, service, _database = _snapshot_context(context)
    left = repository.get(int(context.params.get("left_snapshot_id") or 0))
    right = repository.get(int(context.params.get("right_snapshot_id") or 0))
    result = _snapshot_diff_payload(service, left, right, "snapshot_pair")
    result["diff_file"] = str(_write_diff_file(context, "snapshot_pair_diff", str(result["raw_diff"])))
    context.progress("config_compare", 1, 1, "配置比较完成")
    return result


def config_snapshot_load_content(context: JobContext) -> dict[str, object]:
    context.progress("config_snapshot_load_content", 0, 1, "正在后台读取配置快照")
    context.check_cancelled()
    repository, service, _database = _snapshot_context(context)
    snapshot = repository.get(int(context.params.get("snapshot_id") or 0))
    text, truncated, original_length = _limited_snapshot_text(
        service.snapshot_text(snapshot),
        int(context.params.get("max_chars") or 2_000_000),
    )
    result: dict[str, object] = {
        "snapshot_id": snapshot.id,
        "snapshot_type": snapshot.type,
        "text": text,
        "truncated": truncated,
        "original_length": original_length,
    }
    if snapshot.type == "diff":
        result["diff_file"] = str(_write_diff_file(context, "snapshot_diff", text))
    context.progress("config_snapshot_load_content", 1, 1, "配置快照读取完成")
    return result


def config_snapshot_copy(context: JobContext) -> dict[str, object]:
    repository, service, _database = _snapshot_context(context)
    entries = [entry for entry in context.params.get("entries") or [] if isinstance(entry, dict)]
    total = max(len(entries), 1)
    copied: list[str] = []
    for index, entry in enumerate(entries, start=1):
        context.check_cancelled()
        snapshot = repository.get(int(entry.get("snapshot_id") or 0))
        target = Path(str(entry.get("target_path") or ""))
        context.progress("config_snapshot_copy", index - 1, total, f"正在复制配置快照 {index}/{len(entries)}")
        service.copy_snapshot(snapshot, target)
        copied.append(str(target))
    context.progress("config_snapshot_copy", total, total, "配置快照复制完成")
    return {"copied_paths": copied}


def config_snapshot_pair_load_content(context: JobContext) -> dict[str, object]:
    context.progress("config_snapshot_pair_load_content", 0, 2, "正在后台读取配置快照")
    context.check_cancelled()
    repository, service, _database = _snapshot_context(context)
    snapshot_ids = [
        int(value)
        for value in context.params.get("snapshot_ids") or []
        if int(value or 0) > 0
    ]
    max_chars = int(context.params.get("max_chars") or 2_000_000)
    rows: list[dict[str, object]] = []
    for snapshot_id in snapshot_ids:
        context.check_cancelled()
        snapshot = repository.get(snapshot_id)
        text, truncated, original_length = _limited_snapshot_text(service.snapshot_text(snapshot), max_chars)
        rows.append(
            {
                "snapshot_id": snapshot.id,
                "snapshot_type": snapshot.type,
                "text": text,
                "truncated": truncated,
                "original_length": original_length,
            }
        )
    raw_diff = str(context.params.get("raw_diff") or "")
    result: dict[str, object] = {"snapshots": rows, "raw_diff": raw_diff}
    if raw_diff:
        result["diff_file"] = str(_write_diff_file(context, "snapshot_pair_content_diff", raw_diff))
    context.progress("config_snapshot_pair_load_content", 2, 2, "配置快照读取完成")
    return result


def config_snapshot_delete_many(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    repository, service, _database = _snapshot_context(context)
    snapshot_ids = [
        int(value)
        for value in context.params.get("snapshot_ids") or []
        if int(value or 0) > 0
    ]
    total = len(snapshot_ids)
    completed_items: list[dict[str, object]] = []
    failed_items: list[dict[str, object]] = []
    _write_delete_checkpoint(context, total, completed_items, failed_items, None, snapshot_ids)
    for index, snapshot_id in enumerate(snapshot_ids, start=1):
        context.check_cancelled()
        context.progress(
            "config_snapshot_delete_irreversible",
            index - 1,
            max(total, 1),
            f"正在删除配置快照 {index}/{total}",
        )
        _write_delete_checkpoint(
            context,
            total,
            completed_items,
            failed_items,
            {"snapshot_id": snapshot_id},
            snapshot_ids[index:],
        )
        try:
            service.delete_snapshot(repository.get(snapshot_id))
            completed_items.append({"snapshot_id": snapshot_id})
        except Exception as exc:
            failed_items.append({"snapshot_id": snapshot_id, "error": str(exc)})
        _write_delete_checkpoint(
            context,
            total,
            completed_items,
            failed_items,
            None,
            snapshot_ids[index:],
        )
    context.progress("config_snapshot_delete_many", max(total, 1), max(total, 1), "配置快照删除完成")
    result = {
        "total": total,
        "deleted": len(completed_items),
        "failed": len(failed_items),
        "failed_items": failed_items,
        "deleted_snapshot_ids": [int(item["snapshot_id"]) for item in completed_items],
        "partial_success": bool(failed_items),
        "cancel_policy": "checkpointed_between_items",
    }
    if _checkpoint_enabled(context):
        config_collection_job_handlers.write_irreversible_checkpoint(
            context,
            {
                "operation": "delete_snapshots",
                "status": "completed",
                "total": total,
                "completed_items": completed_items,
                "failed_items": failed_items,
                "current_item": None,
                "pending_items": [],
                "result": result,
            },
        )
    if failed_items and not completed_items:
        details = "；".join(f"{item['snapshot_id']}: {item['error']}" for item in failed_items)
        raise RuntimeError(f"配置快照删除全部失败：{details}")
    return result


def config_web_snapshot_fetch(context: JobContext) -> dict[str, object]:
    context.progress("config_collection", 0, 1, "正在连接设备")
    context.check_cancelled()
    _repository, service, database = _snapshot_context(context)
    device = _device_by_uuid(database, str(context.params.get("device_uuid") or ""))
    result = service.fetch_configs(device)
    if not result.success:
        raise RuntimeError(result.error_message or "配置采集失败")
    context.progress("config_collection", 1, 1, "配置采集完成")
    return {
        "action": "fetch",
        "device_uuid": result.device_uuid,
        "timestamp": result.timestamp,
        "snapshot_ids": [snapshot.id for snapshot in result.snapshots if snapshot.id is not None],
        "snapshot_types": [snapshot.type for snapshot in result.snapshots],
        "warning_message": result.warning_message or "",
    }


def _database(context: JobContext) -> Database:
    site_name = str(context.params.get("site_name") or "demo").strip() or "demo"
    raw_db_path = str(context.params.get("db_path") or "").strip()
    candidates: list[Path] = []
    if raw_db_path:
        candidate = Path(raw_db_path)
        if not candidate.is_absolute():
            candidate = context.paths.data_root / candidate
        candidates.append(candidate.resolve())
    candidates.append(context.paths.site_db_path(site_name).resolve())
    candidates = list(dict.fromkeys(candidates))
    last_error: Exception | None = None
    for path in candidates:
        try:
            if not path.exists():
                continue
            database = Database(path)
            with database.connect() as connection:
                connection.execute("SELECT 1").fetchone()
            return database
        except Exception as exc:
            last_error = exc
    paths_text = "\n".join(str(path) for path in candidates)
    raise RuntimeError(
        "无法打开局点数据库，配置快照后台任务失败。\n"
        f"site={site_name}\n"
        f"候选数据库路径：\n{paths_text}\n"
        f"原始错误：{last_error or 'database file not found'}"
    )


def _snapshot_context(
    context: JobContext,
) -> tuple[ConfigSnapshotRepository, ConfigLifecycleService, Database]:
    database = _database(context)
    repository = ConfigSnapshotRepository(database)
    service = ConfigLifecycleService(
        str(context.params.get("site_name") or ""),
        database,
        context.paths,
        repository,
    )
    return repository, service, database


def _device_by_uuid(database: Database, device_uuid: str) -> Device:
    if not device_uuid:
        raise ValueError("缺少设备 UUID")
    device = DeviceRepository(database).get_by_uuid(device_uuid)
    if device is None:
        raise KeyError(f"未找到设备：{device_uuid}")
    return device


def _device_label(device: Device, fallback: str) -> str:
    return str(device.name or device.system_name or device.device_uuid or fallback)


def _snapshot_diff_payload(
    service: ConfigLifecycleService,
    left: ConfigSnapshot,
    right: ConfigSnapshot,
    kind: str,
) -> dict[str, object]:
    return _diff_payload(
        kind,
        str(left.type or "left"),
        str(right.type or "right"),
        service.snapshot_text(left),
        service.snapshot_text(right),
    )


def _diff_payload(
    kind: str,
    left_label: str,
    right_label: str,
    left_text: str,
    right_text: str,
) -> dict[str, object]:
    diff = compare_named_config_text(left_text, right_text, left_label, right_label)
    rows, added, removed, modified = build_side_by_side_rows(
        clean_config_for_diff(left_text).splitlines(),
        clean_config_for_diff(right_text).splitlines(),
    )
    return {
        "kind": kind,
        "left_label": left_label,
        "right_label": right_label,
        "left_text": left_text,
        "right_text": right_text,
        "raw_diff": diff.raw_diff,
        "diff_rows": [asdict(row) for row in rows],
        "diff_summary": {
            "added": added,
            "removed": removed,
            "modified": modified,
        },
    }


def _write_diff_file(context: JobContext, prefix: str, text: str) -> Path:
    directory = context.paths.runtime_cache_dir / "config_diff"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.txt"
    path.write_text(text, encoding="utf-8")
    return path


def _limited_snapshot_text(text: str, max_chars: int) -> tuple[str, bool, int]:
    original_length = len(text)
    if max_chars > 0 and original_length > max_chars:
        notice = f"\n\n[内容过长，仅显示前 {max_chars} 个字符；完整内容请下载快照查看。]"
        return text[:max_chars] + notice, True, original_length
    return text, False, original_length


def _write_delete_checkpoint(
    context: JobContext,
    total: int,
    completed_items: list[dict[str, object]],
    failed_items: list[dict[str, object]],
    current_item: dict[str, object] | None,
    pending_items: list[int],
) -> None:
    if not _checkpoint_enabled(context):
        return
    config_collection_job_handlers.write_irreversible_checkpoint(
        context,
        {
            "operation": "delete_snapshots",
            "status": "running",
            "total": total,
            "completed_items": completed_items,
            "failed_items": failed_items,
            "current_item": current_item,
            "pending_items": pending_items,
        },
    )


def _checkpoint_enabled(context: JobContext) -> bool:
    return context.job_id.startswith("config-web-")


HANDLERS = {
    name: globals()[name]
    for name in (
        "config_compare_latest_running_between_devices",
        "config_compare_latest_snapshots",
        "config_compare_snapshot_pair",
        "config_snapshot_load_content",
        "config_snapshot_copy",
        "config_snapshot_pair_load_content",
        "config_snapshot_delete_many",
        "config_web_snapshot_fetch",
    )
}
HANDLERS.update(config_collection_job_handlers.HANDLERS)


__all__ = ["HANDLERS"]
