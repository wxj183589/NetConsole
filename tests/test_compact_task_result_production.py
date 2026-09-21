from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

import netconsole.services.production_database_maintenance as maintenance_module
import scripts.maintenance.compact_task_result_production as compaction
from netconsole.models.task_snapshot import TaskEvent, TaskSnapshot
from netconsole.models.task_state import TaskState
from netconsole.repositories.task_repository import TaskRepository
from netconsole.services.production_database_maintenance import (
    PRODUCTION_SITE_ALLOWLIST,
    ProductionMaintenanceError,
)


def _write_registry(root: Path, *, include_unlisted: bool = False) -> None:
    sites = [
        {
            "site_id": site_id,
            "display_name": display_name,
            "relative_path": f"sites/{site_id}",
        }
        for site_id, display_name in PRODUCTION_SITE_ALLOWLIST.items()
    ]
    if include_unlisted:
        sites.append(
            {
                "site_id": "unlisted-site",
                "display_name": "合法但未登记局点",
                "relative_path": "sites/unlisted-site",
            }
        )
    config = root / "config"
    config.mkdir(parents=True, exist_ok=True)
    (config / "site_registry.json").write_text(
        json.dumps({"schema_version": 2, "sites": sites}, ensure_ascii=False),
        encoding="utf-8",
    )


def _production_fixture(
    tmp_path: Path, *, include_unlisted: bool = False
) -> tuple[Path, dict[str, Path]]:
    root = tmp_path / "production-fixture"
    _write_registry(root, include_unlisted=include_unlisted)
    databases: dict[str, Path] = {}
    for site_id in PRODUCTION_SITE_ALLOWLIST:
        database = root / "sites" / site_id / "db" / "tasks.db"
        database.parent.mkdir(parents=True, exist_ok=True)
        TaskRepository(database)
        with sqlite3.connect(database) as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        databases[site_id] = database
    if include_unlisted:
        database = root / "sites" / "unlisted-site" / "db" / "tasks.db"
        database.parent.mkdir(parents=True, exist_ok=True)
        repository = TaskRepository(database)
        _record_task(
            repository,
            "unlisted-completed",
            TaskState.COMPLETED,
            result={"ok": True},
        )
        with sqlite3.connect(database) as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        databases["unlisted-site"] = database
    return root, databases


def _use_fixture_production_root(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    monkeypatch.setattr(compaction, "PRODUCTION_ROOT", root)


def _record_task(
    repository: TaskRepository,
    task_id: str,
    status: TaskState,
    *,
    result: dict[str, object] | None = None,
) -> None:
    timestamp = "2026-09-21T00:00:00Z"
    event_type = "finished" if result is not None else "started"
    repository.record(
        TaskSnapshot(
            task_id=task_id,
            task_type="compaction-test",
            task_name="compaction-test",
            status=status,
            created_time=timestamp,
            finished_time=timestamp if result is not None else "",
            updated_time=timestamp,
            progress=100 if result is not None else 1,
            result=result,
        ),
        TaskEvent(
            event_id=f"event-{task_id}",
            task_id=task_id,
            type=event_type,
            time=timestamp,
            source="test",
            payload={"result": result} if result is not None else {},
        ),
    )


def test_all_nine_allowlisted_sites_authorize_from_canonical_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, databases = _production_fixture(tmp_path)
    _use_fixture_production_root(monkeypatch, root)

    for site_id, database in databases.items():
        plan = compaction.build_compaction_plan(
            database,
            site_id=site_id,
            data_root=root,
            generated_at="2026-09-21T00:00:00Z",
        )
        assert plan["site_id"] == site_id
        assert plan["database"] == str(database.resolve())


def test_unlisted_site_with_valid_database_rejects_before_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, databases = _production_fixture(tmp_path, include_unlisted=True)
    _use_fixture_production_root(monkeypatch, root)

    def unexpected_snapshot(*args, **kwargs):
        raise AssertionError("authorization must precede database reads")

    monkeypatch.setattr(compaction, "_snapshot", unexpected_snapshot)
    with pytest.raises(compaction.TaskResultCompactionError, match="NOT_ALLOWLISTED"):
        compaction.build_compaction_plan(
            databases["unlisted-site"],
            site_id="unlisted-site",
            data_root=root,
        )


def test_apply_unlisted_tampered_plan_rejects_before_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, databases = _production_fixture(tmp_path)
    _use_fixture_production_root(monkeypatch, root)
    plan = compaction.build_compaction_plan(
        databases["sxl1"], site_id="sxl1", data_root=root
    )
    plan["site_id"] = "unlisted-site"
    plan["plan_digest"] = compaction._digest(
        {key: value for key, value in plan.items() if key != "plan_digest"}
    )
    plan_path = tmp_path / "tampered-plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    monkeypatch.setattr(
        compaction,
        "_backup",
        lambda *args, **kwargs: pytest.fail("backup must not run before authorization"),
    )

    with pytest.raises(compaction.TaskResultCompactionError, match="NOT_ALLOWLISTED"):
        compaction.apply_compaction_plan(
            plan_path,
            expected_plan_digest=plan["plan_digest"],
            backup_path=tmp_path / "backup.db",
            authorization=compaction.AUTHORIZATION,
        )


@pytest.mark.parametrize(
    "site_id",
    [
        "../fake",
        r"..\fake",
        "./fake",
        "valid/../fake",
        r"valid\..\fake",
        r"C:\xxx",
        r"D:\NetConsoleData",
        "/tmp/foo",
        r"\\server\share",
        "//server/share",
        "file://server/share",
        "%2e%2e",
        "valid/..\\fake",
        "sxl1/",
        " sxl1.",
    ],
)
def test_site_path_injection_is_not_an_authorization_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    site_id: str,
) -> None:
    root, databases = _production_fixture(tmp_path)
    _use_fixture_production_root(monkeypatch, root)
    with pytest.raises(compaction.TaskResultCompactionError):
        compaction.build_compaction_plan(
            databases["sxl1"], site_id=site_id, data_root=root
        )


def test_case_and_whitespace_follow_canonical_site_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, databases = _production_fixture(tmp_path)
    _use_fixture_production_root(monkeypatch, root)
    plan = compaction.build_compaction_plan(
        databases["sxl1"], site_id="  SXL1  ", data_root=root
    )
    assert plan["site_id"] == "sxl1"


def test_malformed_registry_fails_closed_without_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, databases = _production_fixture(tmp_path)
    _use_fixture_production_root(monkeypatch, root)
    registry = root / "config" / "site_registry.json"
    registry.write_text("{broken", encoding="utf-8")
    before = hashlib.sha256(registry.read_bytes()).hexdigest()

    with pytest.raises(
        compaction.TaskResultCompactionError, match="REGISTRY_UNAVAILABLE"
    ):
        compaction.build_compaction_plan(
            databases["sxl1"], site_id="sxl1", data_root=root
        )

    assert hashlib.sha256(registry.read_bytes()).hexdigest() == before


def test_empty_allowlist_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, databases = _production_fixture(tmp_path)
    _use_fixture_production_root(monkeypatch, root)
    monkeypatch.setattr(maintenance_module, "PRODUCTION_SITE_ALLOWLIST", {})

    with pytest.raises(compaction.TaskResultCompactionError, match="NOT_ALLOWLISTED"):
        compaction.build_compaction_plan(
            databases["sxl1"], site_id="sxl1", data_root=root
        )


def test_site_reparse_point_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, databases = _production_fixture(tmp_path)
    _use_fixture_production_root(monkeypatch, root)
    site_root = root / "sites" / "sxl1"
    monkeypatch.setattr(
        maintenance_module,
        "_is_link_or_reparse_point",
        lambda path: path == site_root,
    )

    with pytest.raises(
        compaction.TaskResultCompactionError, match="REGISTRY_IDENTITY_MISMATCH"
    ):
        compaction.build_compaction_plan(
            databases["sxl1"], site_id="sxl1", data_root=root
        )


def test_candidate_reparse_point_is_rejected_before_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, databases = _production_fixture(tmp_path)
    _use_fixture_production_root(monkeypatch, root)
    plan = compaction.build_compaction_plan(
        databases["sxl1"], site_id="sxl1", data_root=root
    )
    plan["physical_compaction_recommended"] = True
    plan["plan_digest"] = compaction._digest(
        {key: value for key, value in plan.items() if key != "plan_digest"}
    )
    plan_path = tmp_path / "candidate-plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    monkeypatch.setattr(compaction, "_has_link_or_reparse_ancestor", lambda *args: True)
    monkeypatch.setattr(
        compaction,
        "_backup",
        lambda *args, **kwargs: pytest.fail("backup must not run for unsafe staging"),
    )

    with pytest.raises(compaction.TaskResultCompactionError, match="staging path"):
        compaction.apply_compaction_plan(
            plan_path,
            expected_plan_digest=plan["plan_digest"],
            backup_path=tmp_path / "backup.db",
            authorization=compaction.AUTHORIZATION,
        )


def test_wrong_authorization_is_rejected_without_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, databases = _production_fixture(tmp_path)
    _use_fixture_production_root(monkeypatch, root)
    plan = compaction.build_compaction_plan(
        databases["sxl1"], site_id="sxl1", data_root=root
    )
    plan_path = compaction.write_compaction_plan(plan, tmp_path / "plan.json")
    monkeypatch.setattr(
        compaction,
        "_backup",
        lambda *args, **kwargs: pytest.fail("backup must not run"),
    )

    with pytest.raises(compaction.TaskResultCompactionError, match="authorization"):
        compaction.apply_compaction_plan(
            plan_path,
            expected_plan_digest=plan["plan_digest"],
            backup_path=tmp_path / "backup.db",
            authorization="ALLOW_ANYTHING",
        )


def test_dev_fixture_does_not_enter_production_compactor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, databases = _production_fixture(tmp_path)
    monkeypatch.setattr(compaction, "PRODUCTION_ROOT", root)
    dev_root = tmp_path / "dev-fixture"
    dev_root.mkdir()
    with pytest.raises(compaction.TaskResultCompactionError, match="production compaction"):
        compaction.build_compaction_plan(
            databases["sxl1"], site_id="sxl1", data_root=dev_root
        )


def test_existing_below_threshold_flow_uses_authorized_canonical_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, databases = _production_fixture(tmp_path)
    _use_fixture_production_root(monkeypatch, root)
    plan = compaction.build_compaction_plan(
        databases["sxl1"],
        site_id="sxl1",
        data_root=root,
        generated_at="2026-09-21T01:00:00Z",
    )
    plan_path = compaction.write_compaction_plan(plan, tmp_path / "plan.json")
    result = compaction.apply_compaction_plan(
        plan_path,
        expected_plan_digest=plan["plan_digest"],
        backup_path=tmp_path / "backup.db",
        authorization=compaction.AUTHORIZATION,
    )
    assert result["mode"] == "SKIPPED_BELOW_THRESHOLD"
    assert result["database"] == str(databases["sxl1"].resolve())
    assert not (tmp_path / "backup.db").exists()


def test_physical_compaction_preserves_active_tasks_and_shared_blob_references(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, databases = _production_fixture(tmp_path)
    _use_fixture_production_root(monkeypatch, root)
    database = databases["sxl1"]
    repository = TaskRepository(database)
    _record_task(repository, "active-running", TaskState.RUNNING)
    shared_result = {"shared": True, "payload": "x" * 256}
    _record_task(repository, "completed-a", TaskState.COMPLETED, result=shared_result)
    _record_task(repository, "completed-b", TaskState.COMPLETED, result=shared_result)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE compaction_padding (id INTEGER PRIMARY KEY, payload BLOB NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO compaction_padding(id, payload) VALUES (?, ?)",
            ((index, b"x" * (512 * 1024)) for index in range(40)),
        )
        connection.execute("DELETE FROM compaction_padding")
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    connection.close()

    plan = compaction.build_compaction_plan(
        database, site_id="sxl1", data_root=root
    )
    assert plan["physical_compaction_recommended"] is True
    plan_path = compaction.write_compaction_plan(plan, tmp_path / "physical-plan.json")
    result = compaction.apply_compaction_plan(
        plan_path,
        expected_plan_digest=plan["plan_digest"],
        backup_path=tmp_path / "physical-backup.db",
        authorization=compaction.AUTHORIZATION,
    )
    assert result["compacted"] is True
    assert repository.get("active-running").status == TaskState.RUNNING
    assert repository.get_result(
        repository.get("completed-a").result_id
    )["result"] == shared_result
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM task_result_blobs").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM task_results").fetchone()[0] == 2
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"

    second_plan = compaction.build_compaction_plan(
        database, site_id="sxl1", data_root=root
    )
    assert second_plan["physical_compaction_recommended"] is False


def test_database_scope_rejects_non_allowlisted_database_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _databases = _production_fixture(tmp_path)
    _use_fixture_production_root(monkeypatch, root)
    paths = compaction.PathResolver(data_root=root)
    with pytest.raises(ProductionMaintenanceError, match="DATABASE_NOT_ALLOWLISTED"):
        maintenance_module.resolve_production_database_scope(
            paths, "sxl1", "../tasks.db"
        )
