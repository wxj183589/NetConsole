from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

from netconsole.core import app_logger
from netconsole.core.paths import PathResolver
from netconsole.services.app_auto_cleanup import APP_CLEANUP_RETENTION_DAYS, run_app_auto_cleanup


def test_app_auto_cleanup_removes_only_old_runtime_logs_and_cache(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path)
    old_log = paths.logs_dir / "app_20260701.log"
    fresh_log = paths.logs_dir / "app_20260708.log"
    old_cache = paths.runtime_cache_dir / "chart_preview_xxx.png"
    fresh_cache = paths.runtime_cache_dir / "fresh_preview.png"
    user_data = paths.site_files_dir("demo") / "mesh_analysis" / "列车07-MR-CT.log.gz"
    for path in (old_log, fresh_log, old_cache, fresh_cache, user_data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(path.name, encoding="utf-8")
    _set_mtime_days_ago(old_log, 5)
    _set_mtime_days_ago(old_cache, 4)
    _set_mtime_days_ago(fresh_log, 1)
    _set_mtime_days_ago(fresh_cache, 1)
    _set_mtime_days_ago(user_data, 10)

    result = run_app_auto_cleanup(paths, APP_CLEANUP_RETENTION_DAYS, emit_log=False)

    assert result.deleted_log_files == 1
    assert result.deleted_cache_files == 1
    assert not old_log.exists()
    assert not old_cache.exists()
    assert fresh_log.exists()
    assert fresh_cache.exists()
    assert user_data.exists()


def test_app_auto_cleanup_writes_summary_log(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path)
    app_logger.configure_path_resolver(paths)
    old_cache = paths.runtime_cache_dir / "old.tmp"
    old_cache.parent.mkdir(parents=True, exist_ok=True)
    old_cache.write_text("cache", encoding="utf-8")
    _set_mtime_days_ago(old_cache, 5)

    run_app_auto_cleanup(paths)

    logs = app_logger.read_logs()
    assert logs[0]["event"] == "APP_AUTO_CLEANUP_COMPLETED"
    assert "deleted_cache_files=1" in logs[0]["detail"]


def _set_mtime_days_ago(path: Path, days: int) -> None:
    timestamp = (datetime.now() - timedelta(days=days)).timestamp()
    os.utime(path, (timestamp, timestamp))
