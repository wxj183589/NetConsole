from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from netconsole.core.paths import PathResolver
from netconsole.models.task_snapshot import TaskEvent, TaskSnapshot
from netconsole.models.task_state import TaskState
from netconsole.repositories.task_cleanup_schema import (
    TaskCleanupSchemaError,
    inspect_task_cleanup_schema,
    upgrade_task_cleanup_schema,
)
from netconsole.repositories.task_repository import TaskRepository
from netconsole.services.job_center.task_cleanup_service import TaskCleanupService
from scripts.maintenance.cleanup_retired_tasks import _preview_site
from scripts.maintenance.profile_task_schema import profile_task_schema_root


def _repository(tmp_path: Path, *, site: str = "sxl1") -> tuple[PathResolver, Path, TaskRepository]:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    database = paths.site_tasks_db_path(site)
    return paths, database, TaskRepository(database)


def _save_terminal_tasks(repository: TaskRepository, count: int) -> list[str]:
    task_ids: list[str] = []
    for index in range(count):
        task_id = f"legacy-task-{index:02d}"
        timestamp = f"2026-09-01T00:{index:02d}:00Z"
        snapshot = TaskSnapshot(
            task_id=task_id,
            task_type="site_import",
            task_name=task_id,
            status=TaskState.COMPLETED,
            created_time=timestamp,
            started_time=timestamp,
            finished_time=timestamp,
            updated_time=timestamp,
            dismissed_at="2026-09-02T00:00:00Z",
            dismissed_by="test",
            dismiss_reason="legacy-contract-test",
            result={"task_id": task_id, "ok": True},
            site_name="sxl1",
        )
        assert repository.record(
            snapshot,
            TaskEvent(
                event_id=f"event-{task_id}",
                task_id=task_id,
                type="finished",
                time=timestamp,
                payload={"result": {"task_id": task_id, "ok": True}},
            ),
        )
        task_ids.append(task_id)
    return task_ids


def _drop_tombstones(database: Path) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TABLE task_retention_tombstones")
        connection.commit()


def _counts(database: Path) -> dict[str, int | None]:
    with sqlite3.connect(database) as connection:
        names = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_schema WHERE type='table'"
            ).fetchall()
        }
        return {
            table: (
                int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                if table in names
                else None
            )
            for table in (
                "task_events",
                "task_snapshots",
                "task_results",
                "task_retention_tombstones",
            )
        }


def _assert_sqlite_healthy(database: Path) -> None:
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_task_cleanup_schema_contract_profiles_current_and_legacy(tmp_path: Path) -> None:
    _paths, database, repository = _repository(tmp_path)
    _save_terminal_tasks(repository, 1)

    current = inspect_task_cleanup_schema(database)
    assert current["preview_compatible"] is True
    assert current["apply_compatible"] is True
    assert current["migration_required"] is False
    assert current["tables"]["task_retention_tombstones"]["status"] == "PASS"

    _drop_tombstones(database)
    legacy = inspect_task_cleanup_schema(database)
    assert legacy["preview_compatible"] is True
    assert legacy["apply_compatible"] is False
    assert legacy["status"] == "SAFE_BUT_SCHEMA_BLOCKED"
    assert legacy["migration_required"] is True

    upgraded = upgrade_task_cleanup_schema(database)
    assert upgraded["apply_compatible"] is True
    assert inspect_task_cleanup_schema(database)["cleanup_ready"] is True
    second = upgrade_task_cleanup_schema(database)
    assert second["apply_compatible"] is True


def test_task_cleanup_schema_upgrade_preserves_rows_and_repairs_partial_table(
    tmp_path: Path,
) -> None:
    _paths, database, repository = _repository(tmp_path / "existing")
    _save_terminal_tasks(repository, 1)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO task_retention_tombstones(task_id, retired_at, reason) "
            "VALUES ('already-retired', '2026-09-01T00:00:00Z', 'test')"
        )
        connection.commit()
    assert upgrade_task_cleanup_schema(database)["apply_compatible"] is True
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM task_retention_tombstones WHERE task_id='already-retired'"
        ).fetchone()[0] == 1

    _paths, partial_database, partial_repository = _repository(tmp_path / "partial")
    _save_terminal_tasks(partial_repository, 1)
    with sqlite3.connect(partial_database) as connection:
        connection.execute("DROP TABLE task_retention_tombstones")
        connection.execute(
            "CREATE TABLE task_retention_tombstones("
            "task_id TEXT PRIMARY KEY, retired_at TEXT NOT NULL DEFAULT '')"
        )
        connection.commit()
    assert inspect_task_cleanup_schema(partial_database)["apply_compatible"] is False
    assert upgrade_task_cleanup_schema(partial_database)["apply_compatible"] is True
    with sqlite3.connect(partial_database) as connection:
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(task_retention_tombstones)")
        }
    assert columns == {"task_id", "retired_at", "reason"}


def test_task_cleanup_schema_upgrade_is_atomic_on_failure(tmp_path: Path) -> None:
    _paths, database, repository = _repository(tmp_path)
    _save_terminal_tasks(repository, 1)
    _drop_tombstones(database)

    def fail(stage: str) -> None:
        if stage == "before_commit":
            raise RuntimeError("injected schema-upgrade failure")

    with pytest.raises(RuntimeError, match="injected schema-upgrade failure"):
        upgrade_task_cleanup_schema(database, fault_injector=fail)
    profile = inspect_task_cleanup_schema(database)
    assert profile["apply_compatible"] is False
    assert profile["tables"]["task_retention_tombstones"]["present"] is False
    _assert_sqlite_healthy(database)


def test_legacy_cleanup_is_schema_blocked_before_any_delete(tmp_path: Path) -> None:
    paths, database, repository = _repository(tmp_path)
    task_ids = _save_terminal_tasks(repository, 1)
    _drop_tombstones(database)
    before = _counts(database)

    service = TaskCleanupService(repository, paths=paths, site_name="sxl1")
    with pytest.raises(TaskCleanupSchemaError, match="TASK_SCHEMA_COMPATIBILITY"):
        service.cleanup_tasks(task_ids)
    assert _counts(database) == before
    _assert_sqlite_healthy(database)

    preview = _preview_site(paths, "sxl1", database, apply=False)
    assert preview["schema_compatibility"]["status"] == "SAFE_BUT_SCHEMA_BLOCKED"
    assert preview["cleanup_ready"] is False
    assert preview["safe_to_retire_count"] == 0
    assert preview["candidates"][0]["classification"] == "SAFE_BUT_SCHEMA_BLOCKED"


def test_tombstone_write_failure_rolls_back_all_task_rows(tmp_path: Path) -> None:
    paths, database, repository = _repository(tmp_path)
    task_ids = _save_terminal_tasks(repository, 1)
    before = _counts(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TRIGGER fail_tombstone_insert "
            "BEFORE INSERT ON task_retention_tombstones BEGIN "
            "SELECT RAISE(ABORT, 'injected tombstone failure'); END"
        )
        connection.commit()

    service = TaskCleanupService(repository, paths=paths, site_name="sxl1")
    with pytest.raises(sqlite3.DatabaseError, match="injected tombstone failure"):
        service.cleanup_tasks(task_ids)
    assert _counts(database) == before
    _assert_sqlite_healthy(database)


def test_task_delete_failure_rolls_back_before_tombstone_write(tmp_path: Path) -> None:
    paths, database, repository = _repository(tmp_path)
    task_ids = _save_terminal_tasks(repository, 1)
    before = _counts(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TRIGGER fail_task_event_delete "
            "BEFORE DELETE ON task_events BEGIN "
            "SELECT RAISE(ABORT, 'injected task delete failure'); END"
        )
        connection.commit()

    service = TaskCleanupService(repository, paths=paths, site_name="sxl1")
    with pytest.raises(sqlite3.DatabaseError, match="injected task delete failure"):
        service.cleanup_tasks(task_ids)
    assert _counts(database) == before
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM task_retention_tombstones"
        ).fetchone()[0] == 0
    _assert_sqlite_healthy(database)


def test_legacy_ten_task_regression_after_explicit_schema_upgrade(tmp_path: Path) -> None:
    paths, database, repository = _repository(tmp_path)
    task_ids = _save_terminal_tasks(repository, 10)
    _drop_tombstones(database)
    blocked = _preview_site(paths, "sxl1", database, apply=False)
    assert blocked["safe_to_retire_count"] == 0
    assert blocked["schema_compatibility"]["status"] == "SAFE_BUT_SCHEMA_BLOCKED"

    assert upgrade_task_cleanup_schema(database)["apply_compatible"] is True
    ready = _preview_site(paths, "sxl1", database, apply=False)
    assert ready["schema_compatibility"]["status"] == "PASS"
    assert ready["safe_to_retire_count"] == 10

    service = TaskCleanupService(repository, paths=paths, site_name="sxl1")
    result = service.cleanup_tasks(task_ids)
    assert set(result["deleted_task_ids"]) == set(task_ids)
    assert result["deleted"] == {
        "task_events": 10,
        "task_snapshots": 10,
        "task_results": 10,
    }
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM task_retention_tombstones"
        ).fetchone()[0] == 10
        assert connection.execute(
            "SELECT COUNT(*) FROM task_events"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM task_snapshots"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM task_results"
        ).fetchone()[0] == 0
    _assert_sqlite_healthy(database)


def test_read_only_root_profile_reports_legacy_sites_without_mutation(tmp_path: Path) -> None:
    _paths, current_database, current_repository = _repository(tmp_path, site="current")
    _save_terminal_tasks(current_repository, 1)
    _legacy_paths, legacy_database, legacy_repository = _repository(tmp_path, site="legacy")
    _save_terminal_tasks(legacy_repository, 1)
    _drop_tombstones(legacy_database)
    with sqlite3.connect(legacy_database) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    with sqlite3.connect(current_database) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    before = legacy_database.stat().st_mtime_ns

    report = profile_task_schema_root(tmp_path, immutable=True)

    assert report["DATABASE_COUNT"] == 2
    assert report["LEGACY_DB_COUNT"] == 1
    assert report["LEGACY_SITES"] == ["legacy"]
    assert report["TASK_SCHEMA_COMPATIBILITY"] == {
        "required": 2,
        "passed": 1,
        "status": "BLOCKED",
    }
    assert report["production_data_mutated"] is False
    assert legacy_database.stat().st_mtime_ns == before
    assert inspect_task_cleanup_schema(current_database)["cleanup_ready"] is True
