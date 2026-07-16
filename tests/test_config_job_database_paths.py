from pathlib import Path

import pytest

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.repositories.config_snapshot_repository import ConfigSnapshotRepository
from netconsole.services.config_lifecycle_service import ConfigLifecycleService
from netconsole.services.job_center.handlers import config_jobs
from netconsole.services.job_center.job_context import JobContext


def test_config_snapshot_delete_many_resolves_relative_db_path_with_site_fallback(tmp_path):
    paths = PathResolver(tmp_path)
    db = Database(paths.site_db_path("demo"))
    db.initialize()
    repository = ConfigSnapshotRepository(db)
    service = ConfigLifecycleService("demo", db, paths, repository)
    device = Device(id=1, device_uuid=Device.new_uuid(), name="SW01", primary_address="192.0.2.10")
    snapshot = service._write_snapshot(device, "diff", "20260618_101200", "")

    result = config_jobs.config_snapshot_delete_many(
        JobContext(
            job_id="config_20260717_101500",
            task_type="config_snapshot_delete_many",
            params={
                "app_root": str(tmp_path),
                "data_root": str(tmp_path),
                "site_name": "demo",
                "db_path": "missing/devices.db",
                "snapshot_ids": [snapshot.id],
            },
            progress_callback=None,
            should_cancel=None,
            paths=paths,
        )
    )

    assert result["deleted"] == 1
    assert result["failed"] == 0
    assert not (paths.site_dir("demo") / snapshot.file_path).exists()
    with pytest.raises(KeyError):
        repository.get(int(snapshot.id or 0))


def test_site_database_from_params_reports_site_and_candidates_when_missing(tmp_path):
    paths = PathResolver(tmp_path)

    with pytest.raises(RuntimeError) as error:
        config_jobs._database(
            JobContext(
                job_id="config-db-test",
                task_type="config_snapshot_load_content",
                params={
                    "app_root": str(tmp_path),
                    "data_root": str(tmp_path),
                    "site_name": "missing-site",
                    "db_path": "relative/devices.db",
                },
                progress_callback=None,
                should_cancel=None,
                paths=paths,
            )
        )

    message = str(error.value)
    assert "无法打开局点数据库" in message
    assert "site=missing-site" in message
    assert str((tmp_path / "relative" / "devices.db").resolve()) in message
    assert str(paths.site_db_path("missing-site").resolve()) in message


def test_config_jobs_no_longer_delegate_to_legacy_handlers():
    source = Path(config_jobs.__file__).read_text(encoding="utf-8")

    assert "legacy_tasks" not in source
