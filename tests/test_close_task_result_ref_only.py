from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
import scripts.maintenance.close_task_result_ref_only as ref_only

from netconsole.models.task_snapshot import TaskEvent, TaskSnapshot
from netconsole.models.task_state import TaskState
from netconsole.repositories.task_repository import TaskRepository
from netconsole.repositories.task_result_blob_repository import read_blob
from scripts.maintenance.close_task_result_ref_only import (
    TaskResultClosureError,
    apply_ref_only_plan,
    build_ref_only_plan,
    write_ref_only_plan,
)


def _make_db(path: Path) -> None:
    repository = TaskRepository(path)
    timestamp = "2026-08-29T01:00:00Z"
    for index in range(2):
        task_id = f"task-{index}"
        result = {"task": task_id, "value": index}
        repository.record(
            TaskSnapshot(
                task_id=task_id,
                task_type="test",
                task_name="test",
                status=TaskState.COMPLETED,
                created_time=timestamp,
                finished_time=timestamp,
                updated_time=timestamp,
                progress=100,
                result=result,
            ),
            TaskEvent(
                event_id=f"event-{index}",
                task_id=task_id,
                type="finished",
                time=timestamp,
                source="test",
                payload={"result": result},
            ),
        )
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        trigger = connection.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE type='trigger' AND name='trg_task_results_immutable'"
        ).fetchone()[0]
        connection.execute("DROP TRIGGER trg_task_results_immutable")
        for row in connection.execute(
            "SELECT result_id, content_sha256, byte_size FROM task_results"
        ).fetchall():
            canonical = read_blob(
                connection, content_sha256=row[1], expected_bytes=row[2]
            )
            connection.execute(
                "UPDATE task_results SET canonical_json=? WHERE result_id=?",
                (canonical, row[0]),
            )
        connection.execute(trigger)
        connection.commit()
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def test_ref_only_apply_is_digest_bound_and_semantically_idempotent(
    tmp_path: Path,
) -> None:
    db = tmp_path / "sites" / "demo" / "db" / "tasks.db"
    db.parent.mkdir(parents=True)
    _make_db(db)
    plan = build_ref_only_plan(db, site_id="demo", data_root=tmp_path)
    plan_path = write_ref_only_plan(plan, tmp_path / "plan.json")

    with pytest.raises(TaskResultClosureError, match="PLAN_DIGEST"):
        apply_ref_only_plan(
            plan_path,
            expected_plan_digest="wrong-digest",
            backup_path=tmp_path.parent / "rejected-backup.db",
            authorization="PRODUCTION_MAINTENANCE_AUTHORIZED",
        )

    result = apply_ref_only_plan(
        plan_path,
        expected_plan_digest=plan["plan_digest"],
        backup_path=tmp_path.parent / "backup.db",
        authorization="PRODUCTION_MAINTENANCE_AUTHORIZED",
    )

    assert result["task_result_authority"] == "PASS"
    assert result["released_rows"] == 2
    assert result["logical_bytes_reclaimed"] > 0
    with sqlite3.connect(db) as connection:
        assert connection.execute("SELECT COUNT(*) FROM task_results").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM task_result_blobs").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM task_events").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM task_snapshots").fetchone()[0] == 2
        assert connection.execute(
            "SELECT COUNT(*) FROM task_results WHERE canonical_json<>''"
        ).fetchone()[0] == 0
    with sqlite3.connect(db) as connection:
        result_id = connection.execute(
            "SELECT result_id FROM task_results ORDER BY result_id LIMIT 1"
        ).fetchone()[0]
    assert TaskRepository(db).get_result(result_id)["result"]
    with sqlite3.connect(db) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    second = build_ref_only_plan(db, site_id="demo", data_root=tmp_path)
    assert second["candidate_count"] == 0

    replay = apply_ref_only_plan(
        plan_path,
        expected_plan_digest=plan["plan_digest"],
        backup_path=tmp_path.parent / "replay-backup.db",
        authorization="PRODUCTION_MAINTENANCE_AUTHORIZED",
    )
    assert replay["no_op"] is True


def test_ref_only_preview_fails_closed_when_blob_is_missing(tmp_path: Path) -> None:
    db = tmp_path / "sites" / "demo" / "db" / "tasks.db"
    db.parent.mkdir(parents=True)
    _make_db(db)
    with sqlite3.connect(db) as connection:
        connection.execute("DELETE FROM task_result_blobs")
        connection.commit()
    with sqlite3.connect(db) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    with pytest.raises(TaskResultClosureError, match="TASK_RESULT_AUTHORITY_INVALID"):
        build_ref_only_plan(db, site_id="demo", data_root=tmp_path)


def test_ref_only_postcheck_failure_restores_external_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "sites" / "demo" / "db" / "tasks.db"
    db.parent.mkdir(parents=True)
    _make_db(db)
    plan = build_ref_only_plan(db, site_id="demo", data_root=tmp_path)
    plan_path = write_ref_only_plan(plan, tmp_path / "plan.json")

    def fail_postcheck(_path: Path) -> dict[str, object]:
        raise TaskResultClosureError("forced post-check failure")

    monkeypatch.setattr(ref_only, "_collect", fail_postcheck)
    with pytest.raises(TaskResultClosureError, match="forced post-check failure"):
        apply_ref_only_plan(
            plan_path,
            expected_plan_digest=plan["plan_digest"],
            backup_path=tmp_path.parent / f"{tmp_path.name}-postcheck-backup.db",
            authorization="PRODUCTION_MAINTENANCE_AUTHORIZED",
        )

    with sqlite3.connect(db) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM task_results WHERE canonical_json<>''"
        ).fetchone()[0] == 2
