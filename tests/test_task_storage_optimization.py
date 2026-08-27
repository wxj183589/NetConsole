from __future__ import annotations

import json
import sqlite3
import zlib
from pathlib import Path

import pytest

from netconsole.core.paths import PathResolver
from netconsole.models.task_snapshot import TaskEvent, TaskSnapshot
from netconsole.models.task_state import TaskState
from netconsole.repositories.ground_unattended_repository import GroundUnattendedRepository
from netconsole.repositories.task_repository import TaskRepository
from netconsole.services.job_center.query_service import JobCenterQueryService
from netconsole.services.job_center.task_cleanup_service import TaskCleanupService


def _terminal(task_id: str, *, result: dict[str, object] | None = None, result_path: str = "") -> tuple[TaskSnapshot, TaskEvent]:
    timestamp = "2026-08-27T01:00:00Z"
    value = dict(result or {})
    return (
        TaskSnapshot(
            task_id=task_id,
            task_type="storage_test",
            task_name=task_id,
            status=TaskState.COMPLETED,
            created_time=timestamp,
            finished_time=timestamp,
            updated_time=timestamp,
            progress=100,
            result=value,
            result_path=result_path,
            site_name="demo",
        ),
        TaskEvent(
            event_id=f"finished-{task_id}",
            task_id=task_id,
            type="finished",
            time=timestamp,
            source="pytest",
            payload={"message": "done", "result": value},
        ),
    )


def test_terminal_result_uses_one_shared_blob_without_reinflating_full_payload(tmp_path: Path) -> None:
    repository = TaskRepository(tmp_path / "tasks.db")
    payload = {"status": "SUCCESS", "rows": 3, "message": "中文结果"}
    for task_id in ("same-result-a", "same-result-b"):
        snapshot, event = _terminal(task_id, result=payload)
        assert repository.record(snapshot, event)

    with sqlite3.connect(tmp_path / "tasks.db") as conn:
        results = conn.execute(
            "SELECT result_id, task_id, canonical_json, content_sha256, blob_codec, blob_ready "
            "FROM task_results ORDER BY task_id"
        ).fetchall()
        blobs = conn.execute(
            "SELECT content_sha256, compressed_bytes, uncompressed_bytes "
            "FROM task_result_blobs"
        ).fetchall()
        snapshots = conn.execute(
            "SELECT task_id, result_json, result_id, result_summary_json FROM task_snapshots"
        ).fetchall()
        events = [
            json.loads(row[0])
            for row in conn.execute("SELECT payload_json FROM task_events")
        ]

    assert len(results) == 2
    # New result-reference rows retain metadata in task_results and keep the
    # full body only once in the shared blob.  Pre-existing full legacy rows
    # remain readable through the compatibility path.
    assert all(row[2] == "" for row in results)
    assert all(row[3] and row[4] == "zlib" and row[5] == 1 for row in results)
    assert len(blobs) == 1
    assert blobs[0][1] > 0 and blobs[0][2] == len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    assert all(row[1] == "{}" and row[2] for row in snapshots)
    assert all("result" not in event and event["result_id"] for event in events)
    assert repository.get_result(
        next(row[0] for row in results if row[0].startswith("tr-"))
    )["result"] == payload


def test_new_terminal_result_does_not_reinflate_after_body_retirement(tmp_path: Path) -> None:
    path = tmp_path / "tasks.db"
    repository = TaskRepository(path)
    old_snapshot, old_event = _terminal(
        "retired-body", result={"status": "SUCCESS", "rows": 1}
    )
    assert repository.record(old_snapshot, old_event)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE task_results SET canonical_json='' WHERE task_id=?",
            (old_snapshot.task_id,),
        )
        conn.commit()

    new_snapshot, new_event = _terminal(
        "after-retirement", result={"status": "SUCCESS", "rows": 1}
    )
    assert repository.record(new_snapshot, new_event)

    with sqlite3.connect(path) as conn:
        rows = conn.execute(
            "SELECT canonical_json, content_sha256, blob_ready FROM task_results "
            "ORDER BY task_id"
        ).fetchall()
        old_result_id = conn.execute(
            "SELECT result_id FROM task_results WHERE task_id=?",
            (old_snapshot.task_id,),
        ).fetchone()[0]
        assert conn.execute("SELECT COUNT(*) FROM task_result_blobs").fetchone()[0] == 1

    assert all(row[0] == "" and row[1] and row[2] == 1 for row in rows)
    assert repository.get_result(old_result_id)["result"] == {
        "status": "SUCCESS",
        "rows": 1,
    }


def test_blob_ready_result_fails_closed_without_canonical_fallback(tmp_path: Path) -> None:
    path = tmp_path / "tasks.db"
    repository = TaskRepository(path)
    snapshot, event = _terminal("corrupt-blob", result={"status": "SUCCESS", "rows": 1})
    assert repository.record(snapshot, event)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE task_result_blobs SET compressed_blob=?, compressed_bytes=?",
            (zlib.compress(b"not-json"), len(zlib.compress(b"not-json"))),
        )
        conn.commit()

    with sqlite3.connect(path) as conn:
        result_id = conn.execute(
            "SELECT result_id FROM task_results WHERE task_id=?", (snapshot.task_id,)
        ).fetchone()[0]
    with pytest.raises(sqlite3.DatabaseError, match="task result blob"):
        repository.get_result(result_id)


def test_task_center_list_does_not_select_full_result_body(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    repository = TaskRepository(paths.site_tasks_db_path("demo"))
    snapshot, event = _terminal("list-boundary", result={"status": "SUCCESS", "rows": 2})
    assert repository.record(snapshot, event)
    query = JobCenterQueryService(paths)
    with sqlite3.connect(paths.site_tasks_db_path("demo")) as conn:
        conn.row_factory = sqlite3.Row
        sql = query._task_select(conn, detail=False)
    assert "canonical_json" not in sql
    assert "task.result_json AS legacy_result_json" not in sql
    listed = query.list_tasks("demo")
    detail = query.get_task("demo", "list-boundary")
    assert listed[0].details == {}
    assert detail is not None
    assert query.list_task_results(
        "demo", task_type="storage_test", status="COMPLETED"
    )[0][0] == {"status": "SUCCESS", "rows": 2}


def test_task_cleanup_protects_active_references_and_deletes_only_explicit_safe_rows(
    tmp_path: Path,
) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    repository = TaskRepository(paths.site_tasks_db_path("demo"))
    safe_snapshot, safe_event = _terminal("safe-cleanup")
    protected_snapshot, protected_event = _terminal(
        "artifact-cleanup",
        result={"artifact_id": "artifact-1"},
    )
    ground_snapshot, ground_event = _terminal("ground-cleanup")
    manifest_snapshot, manifest_event = _terminal("manifest-cleanup")
    active = TaskSnapshot(
        task_id="active-cleanup",
        task_type="storage_test",
        task_name="active-cleanup",
        status=TaskState.RUNNING,
        created_time="2026-08-27T01:00:00Z",
        updated_time="2026-08-27T01:00:00Z",
        site_name="demo",
    )
    assert repository.record(safe_snapshot, safe_event)
    assert repository.record(protected_snapshot, protected_event)
    assert repository.record(ground_snapshot, ground_event)
    assert repository.record(manifest_snapshot, manifest_event)
    repository.save(active)
    GroundUnattendedRepository(
        paths.ground_unattended_db_path("demo"), site_id="demo"
    ).save_delete_operation(
        {
            "operation_id": "ground-operation-1",
            "run_id": "run-1",
            "mode": "delete",
            "task_id": ground_snapshot.task_id,
        }
    )
    manifest_root = paths.rail_transit_root("demo") / "web_artifacts" / "manifests"
    manifest_root.mkdir(parents=True, exist_ok=True)
    (manifest_root / "artifact-manifest.json").write_text(
        json.dumps({"task_id": manifest_snapshot.task_id}), encoding="utf-8"
    )
    cleanup = TaskCleanupService(repository, paths=paths, site_name="demo")

    preview = cleanup.preview_cleanup(
        [
            "safe-cleanup",
            "artifact-cleanup",
            "ground-cleanup",
            "manifest-cleanup",
            "active-cleanup",
        ]
    )
    decisions = {item["task_id"]: item for item in preview["decisions"]}
    assert decisions["safe-cleanup"]["can_cleanup"] is True
    assert decisions["artifact-cleanup"]["can_cleanup"] is False
    assert "DURABLE_RESULT_REFERENCE" in decisions["artifact-cleanup"]["reasons"]
    assert decisions["ground-cleanup"]["can_cleanup"] is False
    assert "GROUND_CURRENT_MAPPING" in decisions["ground-cleanup"]["reasons"]
    assert decisions["manifest-cleanup"]["can_cleanup"] is False
    assert "ARTIFACT_MANIFEST_REFERENCE" in decisions["manifest-cleanup"]["reasons"]
    assert decisions["active-cleanup"]["can_cleanup"] is False
    assert "ACTIVE_TASK" in decisions["active-cleanup"]["reasons"]

    result = cleanup.cleanup_tasks(
        [
            "safe-cleanup",
            "artifact-cleanup",
            "ground-cleanup",
            "manifest-cleanup",
            "active-cleanup",
        ]
    )
    assert result["deleted_task_ids"] == ["safe-cleanup"]
    assert result["quick_check"] == "ok"
    assert repository.get("safe-cleanup") is None
    assert repository.get("artifact-cleanup") is not None
    assert repository.get("ground-cleanup") is not None
    assert repository.get("manifest-cleanup") is not None
    assert repository.get("active-cleanup") is not None
