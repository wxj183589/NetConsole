from __future__ import annotations

from datetime import datetime

import pytest

from netconsole.core.paths import PathResolver
from netconsole.services.site_database_recovery import SiteDatabaseRecoveryService


def _service(tmp_path) -> SiteDatabaseRecoveryService:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    return SiteDatabaseRecoveryService(
        paths,
        now=lambda: datetime(2026, 7, 18, 10, 30, 45),
        retry_delay_seconds=0,
    )


def test_site_database_recovery_backs_up_all_site_databases(tmp_path) -> None:
    service = _service(tmp_path)
    first = service.paths.site_db_path("site-a")
    second = service.paths.site_tasks_db_path("site-b")
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_bytes(b"devices")
    second.write_bytes(b"tasks")
    (first.parent / "ignored.sqlite").write_bytes(b"ignored")

    backups = service.backup_databases()

    assert [path.name for path in backups] == [
        "devices_20260718_103045.db",
        "tasks_20260718_103045.db",
    ]
    assert [path.read_bytes() for path in backups] == [b"devices", b"tasks"]
    assert first.read_bytes() == b"devices"
    assert second.read_bytes() == b"tasks"


def test_site_database_recovery_removes_sources_only_after_backup(tmp_path) -> None:
    service = _service(tmp_path)
    database = service.paths.site_db_path("site-a")
    database.parent.mkdir(parents=True)
    database.write_bytes(b"devices")

    backups = service.backup_and_remove_databases()

    assert len(backups) == 1
    assert backups[0].read_bytes() == b"devices"
    assert not database.exists()


def test_site_database_recovery_uses_one_database_snapshot(tmp_path, monkeypatch) -> None:
    service = _service(tmp_path)
    database = service.paths.site_db_path("site-a")
    database.parent.mkdir(parents=True)
    database.write_bytes(b"devices")
    calls = 0
    original = service.list_databases

    def list_once():
        nonlocal calls
        calls += 1
        return original()

    monkeypatch.setattr(service, "list_databases", list_once)

    service.backup_and_remove_databases()

    assert calls == 1


def test_site_database_recovery_keeps_sources_when_backup_fails(tmp_path, monkeypatch) -> None:
    service = _service(tmp_path)
    database = service.paths.site_db_path("site-a")
    database.parent.mkdir(parents=True)
    database.write_bytes(b"devices")

    def fail_copy(*_args, **_kwargs):
        raise OSError("backup failed")

    monkeypatch.setattr("netconsole.services.site_database_recovery.shutil.copy2", fail_copy)

    with pytest.raises(OSError, match="backup failed"):
        service.backup_and_remove_databases()

    assert database.read_bytes() == b"devices"


def test_site_database_recovery_rejects_paths_outside_site_database_dirs(tmp_path) -> None:
    service = _service(tmp_path)
    outside = tmp_path / "outside.db"
    outside.write_bytes(b"protected")

    with pytest.raises(ValueError, match="拒绝删除"):
        service.remove_databases([outside])

    assert outside.read_bytes() == b"protected"
