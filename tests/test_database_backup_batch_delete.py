from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from netconsole.core.paths import PathResolver
from netconsole.services.database_upgrade.backup_store import DatabaseBackupStore
from netconsole.services.database_upgrade.journal import DatabaseUpgradeJournal
from netconsole.services.database_upgrade.management_service import DatabaseUpgradeManagementService
from netconsole.services.job_center.handlers.database_jobs import database_backup_batch_delete
from netconsole.services.job_center.job_context import JobContext
from netconsole.services.job_center.query_service import JobCenterQueryService


def _paths(tmp_path: Path) -> PathResolver:
    return PathResolver(app_root=tmp_path / "app", data_root=tmp_path / "data")


def _create_database(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE marker (value TEXT NOT NULL)")
        connection.execute("INSERT INTO marker(value) VALUES (?)", (value,))
        connection.commit()


def _create_backup(paths: PathResolver, tmp_path: Path, value: str) -> dict[str, object]:
    source = tmp_path / f"{value}.sqlite"
    _create_database(source, value)
    return DatabaseBackupStore(paths).create(
        source_path=source,
        database_kind="mesh_derived",
        scope_type="site_profile",
        scope_id="demo:profile",
        task_id="seed",
        old_version="old",
        target_version="new",
        strategy="SCHEMA_MIGRATION",
    )


def test_batch_delete_deduplicates_ids_and_keeps_per_item_partial_results(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    first = _create_backup(paths, tmp_path, "first")
    second = _create_backup(paths, tmp_path, "second")
    first_path = Path(str(first["path"]))
    second_path = Path(str(second["path"]))

    result = DatabaseUpgradeManagementService(paths).delete_backups(
        [str(first["backup_id"]), str(first["backup_id"]), str(second["backup_id"]), "missing"],
        confirmed=True,
        site_id="demo",
        task_id="batch-task",
    )

    assert result["requested"] == 3
    assert result["deleted"] == 2
    assert result["failed"] == 1
    assert result["skipped"] == 0
    assert result["partial_success"] is True
    assert result["released_bytes"] == int(first["database_size"]) + int(second["database_size"])
    assert [item["status"] for item in result["items"]] == ["deleted", "deleted", "failed"]
    assert result["items"][-1]["code"] == "BACKUP_NOT_FOUND"
    assert not first_path.exists()
    assert not second_path.exists()


def test_batch_delete_with_empty_selection_is_a_noop(tmp_path: Path) -> None:
    result = DatabaseUpgradeManagementService(_paths(tmp_path)).delete_backups([], confirmed=True, site_id="demo")

    assert result["requested"] == 0
    assert result["deleted"] == 0
    assert result["failed"] == 0
    assert result["skipped"] == 0
    assert result["items"] == []


def test_batch_delete_protects_preparing_and_journal_in_use_backups(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    preparing = _create_backup(paths, tmp_path, "preparing")
    in_use = _create_backup(paths, tmp_path, "in-use")
    preparing_manifest = Path(str(preparing["path"])) / "manifest.json"
    manifest = json.loads(preparing_manifest.read_text(encoding="utf-8"))
    manifest.update(result_status="CREATING", authority_status="PREPARING")
    preparing_manifest.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    DatabaseUpgradeJournal(paths, "operation-in-use").update(
        "switched",
        backup_id=str(in_use["backup_id"]),
    )

    result = DatabaseUpgradeManagementService(paths).delete_backups(
        [str(preparing["backup_id"]), str(in_use["backup_id"])],
        confirmed=True,
        site_id="demo",
    )

    assert result["deleted"] == 0
    assert result["failed"] == 0
    assert result["skipped"] == 2
    assert {item["code"] for item in result["items"]} == {"BACKUP_IN_USE"}
    assert Path(str(preparing["path"])).exists()
    assert Path(str(in_use["path"])).exists()


def test_batch_delete_rejects_manifest_path_outside_controlled_root(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    backup = _create_backup(paths, tmp_path, "outside")
    outside = tmp_path / "outside" / "database.sqlite"
    _create_database(outside, "must-keep")
    manifest_path = Path(str(backup["path"])) / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["backup_database_path"] = str(outside)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    result = DatabaseUpgradeManagementService(paths).delete_backups(
        [str(backup["backup_id"])],
        confirmed=True,
        site_id="demo",
    )

    assert result["failed"] == 1
    assert result["items"][0]["code"] == "BACKUP_PATH_INVALID"
    assert outside.exists()
    assert Path(str(backup["path"])).exists()


def test_batch_delete_preserves_active_database_guard(tmp_path: Path, monkeypatch) -> None:
    paths = _paths(tmp_path)
    backup = _create_backup(paths, tmp_path, "active")
    service = DatabaseUpgradeManagementService(paths)
    monkeypatch.setattr(
        service,
        "_active_mesh_paths",
        lambda _scope_id: (Path(str(backup["path"])) / "database.sqlite",),
    )

    result = service.delete_backups([str(backup["backup_id"])], confirmed=True, site_id="demo")

    assert result["deleted"] == 0
    assert result["skipped"] == 1
    assert result["items"][0]["code"] == "BACKUP_IN_USE"
    assert Path(str(backup["path"])).exists()


def test_batch_delete_handler_exposes_counts_and_released_bytes(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    backup = _create_backup(paths, tmp_path, "handler")
    progress: list[tuple[str, int, int, object]] = []
    context = JobContext(
        job_id="batch-task",
        task_type="database_backup_batch_delete",
        params={
            "backup_ids": [str(backup["backup_id"])],
            "confirmed": True,
            "site_id": "demo",
        },
        progress_callback=lambda stage, current, total, message: progress.append((stage, current, total, message)),
        should_cancel=lambda: False,
        paths=paths,
    )

    result = database_backup_batch_delete(context)

    assert result["deleted"] == 1
    assert result["released_bytes"] == int(backup["database_size"])
    assert progress[-1][:3] == ("database_backup_batch_delete", 1, 1)
    assert isinstance(progress[-1][3], dict)
    assert progress[-1][3]["released_bytes"] == result["released_bytes"]


def test_job_center_details_keep_batch_delete_summary_bounded() -> None:
    details = JobCenterQueryService._task_details(
        "database_backup_batch_delete",
        {},
        {
            "requested": 3,
            "deleted": 2,
            "failed": 1,
            "skipped": 0,
            "released_bytes": 2048,
            "partial_success": True,
            "items": [{"backup_id": "backup-1", "status": "deleted", "path": "must-not-leak"}],
        },
    )

    assert details["released_bytes"] == 2048
    assert details["items"] == [{"backup_id": "backup-1", "status": "deleted"}]
    assert "path" not in details["items"][0]
