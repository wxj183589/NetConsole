from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

from netconsole.core.log_policy import LOG_POLICY
from netconsole.core.paths import PathResolver
from netconsole.services.log_housekeeper import LogHousekeeper


def test_housekeeper_expires_rotated_logs_and_protects_active_and_audit_files(
    tmp_path: Path,
) -> None:
    paths = PathResolver(tmp_path)
    now = datetime(2026, 8, 10, 12, 0, 0)
    active_electron = _write(paths.logs_dir / "electron.log", 64)
    active_app = _write(paths.logs_dir / "app.log", 64)
    audit = _write(paths.logs_dir / "database_upgrade_audit.jsonl", 64)
    rotated_electron = _write(
        paths.logs_dir / "electron-20260801-000000-0001.log", 64
    )
    rotated_app = _write(paths.logs_dir / "app-20260801-000000-0001.log", 64)
    old_wps = _write(paths.logs_dir / "wps-desktop-20260801.stdout.log", 64)
    recent_wps = _write(paths.logs_dir / "wps-desktop-20260810.stderr.log", 64)
    for path in (active_electron, active_app, audit, rotated_electron, rotated_app, old_wps):
        _set_mtime(path, now - timedelta(days=10))
    _set_mtime(recent_wps, now - timedelta(minutes=1))

    result = LogHousekeeper(paths).clean(now=now)

    assert result.deleted_files == 3
    assert not rotated_electron.exists()
    assert not rotated_app.exists()
    assert not old_wps.exists()
    assert all(path.exists() for path in (active_electron, active_app, audit, recent_wps))


def test_housekeeper_capacity_deletes_oldest_category_until_target_watermark(
    tmp_path: Path,
) -> None:
    paths = PathResolver(tmp_path)
    now = datetime(2026, 8, 10, 12, 0, 0)
    electron = _write_sparse(
        paths.logs_dir / "electron-20260810-010000-0001.log",
        120 * 1024 * 1024,
    )
    app = _write_sparse(
        paths.logs_dir / "app-20260810-010000-0001.log",
        100 * 1024 * 1024,
    )
    wps = _write_sparse(
        paths.logs_dir / "wps-desktop-20260810.stdout.log",
        90 * 1024 * 1024,
    )
    for index, path in enumerate((electron, app, wps), start=1):
        _set_mtime(path, now - timedelta(hours=index))

    scan = LogHousekeeper(paths).scan(now=now)
    result = LogHousekeeper(paths).clean(now=now)

    assert scan.total_bytes > LOG_POLICY.housekeeper.max_total_bytes
    assert [candidate.path for candidate in scan.candidates] == [electron]
    assert not electron.exists()
    assert app.exists() and wps.exists()
    assert result.total_bytes_after <= LOG_POLICY.housekeeper.target_total_bytes


def test_housekeeper_permission_error_is_best_effort(tmp_path: Path, monkeypatch) -> None:
    paths = PathResolver(tmp_path)
    now = datetime(2026, 8, 10, 12, 0, 0)
    rotated = _write(paths.logs_dir / "electron-20260801-000000-0001.log", 64)
    _set_mtime(rotated, now - timedelta(days=10))
    original_unlink = Path.unlink

    def fail_unlink(path: Path, *args, **kwargs) -> None:
        if path == rotated:
            raise PermissionError("locked")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_unlink)

    result = LogHousekeeper(paths).clean(now=now)

    assert rotated.exists()
    assert result.deleted_files == 0
    assert result.failures and result.failures[0][0] == rotated


def test_log_policy_keeps_raw_collection_outside_application_truncation() -> None:
    assert LOG_POLICY.application_log.max_event_bytes == 16 * 1024
    assert LOG_POLICY.electron.max_file_bytes == 20 * 1024 * 1024
    assert LOG_POLICY.backend.max_file_bytes == 20 * 1024 * 1024
    assert LOG_POLICY.housekeeper.max_total_bytes == 300 * 1024 * 1024
    assert LOG_POLICY.housekeeper.target_total_bytes == 250 * 1024 * 1024
    assert LOG_POLICY.raw_collection_truncate is False


def _write(path: Path, size: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path.resolve()


def _write_sparse(path: Path, size: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.truncate(size)
    return path.resolve()


def _set_mtime(path: Path, value: datetime) -> None:
    timestamp = value.timestamp()
    os.utime(path, (timestamp, timestamp))
