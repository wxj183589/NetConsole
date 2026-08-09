from __future__ import annotations

import os
from hashlib import sha256
from datetime import datetime, timedelta
from pathlib import Path

from netconsole.core import app_logger
from netconsole.core.paths import PathResolver
from netconsole.services import app_auto_cleanup as cleanup_module
from netconsole.services.app_auto_cleanup import (
    APP_CLEANUP_RETENTION_DAYS,
    AppCleanupService,
    claim_auto_cleanup,
    finish_auto_cleanup,
    run_app_auto_cleanup,
)


def test_app_auto_cleanup_removes_only_old_software_runtime_logs(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path)
    old_log = paths.logs_dir / "app_20260701.log"
    fresh_log = paths.logs_dir / "app_20260708.log"
    old_cache = paths.runtime_cache_dir / "chart_cache" / "chart_preview_xxx.png"
    fresh_cache = paths.runtime_cache_dir / "chart_cache" / "fresh_preview.png"
    user_data = paths.site_files_dir("demo") / "mesh_analysis" / "列车07-MR-CT.log.gz"
    for path in (old_cache, fresh_cache, user_data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(path.name, encoding="utf-8")
    old_log.parent.mkdir(parents=True, exist_ok=True)
    old_log.write_text("2026-07-01 10:00:00 | INFO | OLD_EVENT | old\n", encoding="utf-8")
    fresh_log.write_text(
        datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " | INFO | FRESH_EVENT | fresh\n",
        encoding="utf-8",
    )
    _set_mtime_days_ago(old_log, 8)
    _set_mtime_days_ago(old_cache, 4)
    _set_mtime_days_ago(fresh_log, 1)
    _set_mtime_days_ago(fresh_cache, 1)
    _set_mtime_days_ago(user_data, 10)

    result = run_app_auto_cleanup(paths, APP_CLEANUP_RETENTION_DAYS, emit_log=False)

    assert result.deleted_log_files == 1
    assert result.deleted_cache_files == 0
    assert not old_log.exists()
    assert old_cache.exists()
    assert fresh_log.exists()
    assert fresh_cache.exists()
    assert user_data.exists()


def test_app_auto_cleanup_writes_summary_log(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path)
    app_logger.configure_path_resolver(paths)
    old_log = paths.logs_dir / "app_20260701.log"
    old_log.parent.mkdir(parents=True, exist_ok=True)
    old_log.write_text("2026-07-01 10:00:00 | INFO | OLD_EVENT | old\n", encoding="utf-8")
    _set_mtime_days_ago(old_log, 8)

    run_app_auto_cleanup(paths)

    logs = app_logger.read_logs()
    assert logs[0]["event"] == "APP_AUTO_CLEANUP_COMPLETED"
    assert "deleted_log_files=1" in logs[0]["detail"]
    assert "deleted_cache_files=0" in logs[0]["detail"]


def test_app_cleanup_service_scans_items_without_touching_site_data(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path)
    old_log = paths.logs_dir / "runtime_20260701.log"
    old_temp = paths.runtime_dir / "export_tmp" / "preview.tmp"
    protected_log = paths.site_files_dir("demo") / "rail_transit" / "online_mr" / "raw.log"
    for path in (old_temp, protected_log):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(path.name, encoding="utf-8")
        _set_mtime_days_ago(path, 5)
    old_log.parent.mkdir(parents=True, exist_ok=True)
    old_log.write_text("2026-07-01 10:00:00 | INFO | OLD_EVENT | old\n", encoding="utf-8")
    _set_mtime_days_ago(old_log, 5)

    items = AppCleanupService(paths).scan_cleanup_items(3)
    item_map = {item.item_id: item for item in items}

    assert item_map["runtime_logs"].file_count == 1
    assert item_map["temporary_files"].file_count == 1
    assert str(protected_log) not in "\n".join(str(candidate.path) for item in items for candidate in item.candidates)


def test_default_cleanup_retention_is_independent_by_item(
    tmp_path: Path, monkeypatch
) -> None:
    paths = PathResolver(tmp_path)
    old_log = paths.logs_dir / "app_20260801.log"
    old_cache = paths.runtime_cache_dir / "chart_cache" / "chart.json"
    old_temp = paths.runtime_dir / "tmp" / "working.tmp"
    for path in (old_log, old_cache, old_temp):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(path.name, encoding="utf-8")
        _set_mtime_days_ago(path, 5)
    monkeypatch.setattr(cleanup_module, "APP_CLEANUP_RETENTION_DAYS", 7)
    monkeypatch.setattr(cleanup_module, "RUNTIME_CACHE_RETENTION_DAYS", 3)
    monkeypatch.setattr(cleanup_module, "TEMPORARY_RETENTION_DAYS", 9)

    default_items = {
        item.item_id: item for item in AppCleanupService(paths).scan_cleanup_items()
    }
    override_items = {
        item.item_id: item
        for item in AppCleanupService(paths).scan_cleanup_items(4)
    }

    assert default_items["runtime_logs"].file_count == 0
    assert default_items["runtime_cache"].file_count == 1
    assert default_items["temporary_files"].file_count == 0
    assert all(item.file_count == 1 for item in override_items.values())


def test_app_cleanup_excludes_task_protocol_and_preview_roots(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path)
    protected = [
        paths.runtime_cache_dir / "background_jobs" / "active.json",
        paths.runtime_cache_dir / "background_jobs" / "active.cancel",
        paths.runtime_cache_dir / "export_jobs" / "active.json",
        paths.runtime_dir / "base_data_import_previews" / "preview_meta.json",
        paths.runtime_cache_dir / "rail_web_uploads" / "upload.bin",
    ]
    allowed = paths.runtime_cache_dir / "preview_cache" / "chart.json"
    for path in [*protected, allowed]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(path.name, encoding="utf-8")
        _set_mtime_days_ago(path, 10)

    _items, result = AppCleanupService(paths).cleanup_selected(["runtime_cache"], 3)

    assert result.deleted_cache_files == 1
    assert not allowed.exists()
    assert all(path.exists() for path in protected)


def test_app_cleanup_rechecks_file_age_before_delete(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path)
    candidate = paths.runtime_cache_dir / "chart_cache" / "became-fresh.tmp"
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_text("cache", encoding="utf-8")
    _set_mtime_days_ago(candidate, 10)
    service = AppCleanupService(paths)
    items = service.scan_cleanup_items(3)

    os.utime(candidate, None)
    result = service.cleanup_items(items, 3)

    assert candidate.exists()
    assert result.processed_files == 0
    assert result.deleted_files == 0


def test_runtime_log_cleanup_protects_active_and_business_logs(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path)
    now = datetime.now()
    active = paths.app_log_path
    business = paths.site_files_dir("demo") / "rail_transit" / "online_mr" / "MR-1" / "raw" / "terminal_monitor_raw.log"
    report = paths.site_files_dir("demo") / "rail_transit" / "online_mr" / "MR-1" / "outputs" / "report.xlsx"
    active.parent.mkdir(parents=True, exist_ok=True)
    business.parent.mkdir(parents=True, exist_ok=True)
    report.parent.mkdir(parents=True, exist_ok=True)
    old_line = (now - timedelta(days=4)).strftime("%Y-%m-%d %H:%M:%S") + " | INFO | OLD | old\n"
    fresh_line = (now - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S") + " | INFO | FRESH | fresh\n"
    malformed = "legacy line without timestamp\n"
    active.write_text(old_line + fresh_line + malformed, encoding="utf-8")
    business.write_text("business raw", encoding="utf-8")
    report.write_bytes(b"report")
    protected_before = {path: sha256(path.read_bytes()).hexdigest() for path in (business, report)}

    result = run_app_auto_cleanup(paths, emit_log=False)

    assert active.read_text(encoding="utf-8") == old_line + fresh_line + malformed
    assert result.deleted_log_files == 0
    assert result.rewritten_log_files == 0
    assert protected_before == {path: sha256(path.read_bytes()).hexdigest() for path in (business, report)}


def test_runtime_log_cleanup_never_rewrites_active_log(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path)
    active = paths.app_log_path
    active.parent.mkdir(parents=True, exist_ok=True)
    content = "2026-07-01 10:00:00 | INFO | OLD | old\n"
    active.write_text(content, encoding="utf-8")
    result = run_app_auto_cleanup(paths, emit_log=False)

    assert active.read_text(encoding="utf-8") == content
    assert result.failed_count == 0
    assert result.processed_files == 0
    assert not list(active.parent.glob(".app.log.*.tmp"))


def test_auto_cleanup_schedule_is_single_flight_and_throttled_for_one_hour(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path)
    started = datetime(2026, 7, 21, 8, 0, 0)

    assert claim_auto_cleanup(paths, "task-1", now=started) is True
    assert claim_auto_cleanup(paths, "task-2", now=started + timedelta(minutes=1)) is False
    finish_auto_cleanup(paths, "task-1", succeeded=True, now=started + timedelta(minutes=2))
    assert claim_auto_cleanup(paths, "task-3", now=started + timedelta(minutes=59)) is False
    assert claim_auto_cleanup(paths, "task-4", now=started + timedelta(hours=2)) is True


def test_non_whitelisted_runtime_log_name_is_never_removed(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path)
    unknown = paths.logs_dir / "random.log"
    unknown.parent.mkdir(parents=True, exist_ok=True)
    unknown.write_text("2026-07-01 10:00:00 | INFO | OLD | old\n", encoding="utf-8")

    result = run_app_auto_cleanup(paths, emit_log=False)

    assert unknown.exists()
    assert result.deleted_log_records == 0


def _set_mtime_days_ago(path: Path, days: int) -> None:
    timestamp = (datetime.now() - timedelta(days=days)).timestamp()
    os.utime(path, (timestamp, timestamp))
