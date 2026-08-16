from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from netconsole.core.paths import PathResolver
from netconsole.models.task_result_rollout import TaskResultStorageState
from netconsole.models.task_snapshot import TaskEvent, TaskSnapshot
from netconsole.models.task_state import TaskState
from netconsole.repositories.task_repository import TaskRepository
from netconsole.services.job_center.task_application_service import (
    TaskApplicationService,
)
from netconsole.services.job_center.task_result_rollout import (
    TaskResultRolloutError,
    TaskResultRolloutService,
)
from scripts.maintenance.task_result_maintenance import (
    TaskResultMaintenanceService,
)
from netconsole.services.site_storage import SiteRecord, SiteRegistryRepository
from scripts.maintenance.manage_task_result_rollout import main as rollout_cli_main


def _terminal(task_id: str) -> tuple[TaskSnapshot, TaskEvent]:
    result = {"task": task_id, "rows": 3, "status": "ok"}
    timestamp = "2026-08-16T03:00:00Z"
    return (
        TaskSnapshot(
            task_id=task_id,
            task_type="rollout_test",
            task_name="Rollout Test",
            status=TaskState.COMPLETED,
            created_time=timestamp,
            finished_time=timestamp,
            updated_time=timestamp,
            progress=100,
            result=result,
        ),
        TaskEvent(
            event_id=f"finished-{task_id}",
            task_id=task_id,
            type="finished",
            time=timestamp,
            source="test",
            payload={"message": "done", "result": result},
        ),
    )


def _enable(service: TaskResultRolloutService) -> None:
    service.enable_dual_write(
        expected_revision=1,
        reason="isolated rollout test",
        updated_by="pytest",
    )


def test_new_database_defaults_to_legacy_dual_full(tmp_path: Path) -> None:
    service = TaskResultRolloutService(tmp_path / "tasks.db")
    status = service.status()

    assert status == {
        "schema_version": 4,
        "task_result_storage_state": "LEGACY_DUAL_FULL",
        "revision": 1,
        "updated_at": status["updated_at"],
        "task_results_rows": 0,
        "dual_write_active": False,
        "ref_authority_active": False,
    }
    assert str(status["updated_at"])


def test_old_database_upgrade_adds_capability_but_keeps_rollout_off(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tasks.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE task_schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO task_schema_meta VALUES ('schema_version', '3');
            CREATE TABLE task_snapshots (
                task_id TEXT PRIMARY KEY, task_type TEXT NOT NULL, task_name TEXT NOT NULL,
                created_time TEXT NOT NULL, started_time TEXT NOT NULL DEFAULT '',
                finished_time TEXT NOT NULL DEFAULT '', status TEXT NOT NULL,
                progress INTEGER NOT NULL DEFAULT 0, stage TEXT NOT NULL DEFAULT '',
                current INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL DEFAULT 0,
                message TEXT NOT NULL DEFAULT '', owner TEXT NOT NULL DEFAULT '',
                device TEXT NOT NULL DEFAULT '', agent TEXT NOT NULL DEFAULT '',
                result_path TEXT NOT NULL DEFAULT '', error_message TEXT NOT NULL DEFAULT '',
                result_json TEXT NOT NULL DEFAULT '{}', source TEXT NOT NULL DEFAULT 'local',
                site_name TEXT NOT NULL DEFAULT 'demo', owner_pid INTEGER NOT NULL DEFAULT 0,
                resource_keys_json TEXT NOT NULL DEFAULT '[]', updated_time TEXT NOT NULL
            );
            CREATE TABLE task_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE, task_id TEXT NOT NULL,
                event_type TEXT NOT NULL, event_time TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'service',
                payload_json TEXT NOT NULL DEFAULT '{}'
            );
            """
        )

    repository = TaskRepository(path)
    status = repository.task_result_rollout_status()
    snapshot, event = _terminal("upgraded-task")
    assert repository.record(snapshot, event)

    with sqlite3.connect(path) as conn:
        schema_version = conn.execute(
            "SELECT value FROM task_schema_meta WHERE key='schema_version'"
        ).fetchone()[0]
        result_count = conn.execute("SELECT COUNT(*) FROM task_results").fetchone()[0]
    assert schema_version == "4"
    assert result_count == 0
    assert status.state == TaskResultStorageState.LEGACY_DUAL_FULL
    assert repository.get("upgraded-task").result == snapshot.result


@pytest.mark.parametrize("count", [10, 100, 1_000])
def test_default_terminal_tasks_never_write_task_results(
    tmp_path: Path,
    count: int,
) -> None:
    path = tmp_path / f"tasks-{count}.db"
    repository = TaskRepository(path)
    for index in range(count):
        snapshot, event = _terminal(f"task-{index:04d}")
        assert repository.record(snapshot, event)

    with sqlite3.connect(path) as conn:
        result_count = conn.execute("SELECT COUNT(*) FROM task_results").fetchone()[0]
        snapshot_count = conn.execute(
            "SELECT COUNT(*) FROM task_snapshots"
        ).fetchone()[0]
        event_count = conn.execute("SELECT COUNT(*) FROM task_events").fetchone()[0]
        snapshot_result = json.loads(
            conn.execute(
                "SELECT result_json FROM task_snapshots ORDER BY task_id LIMIT 1"
            ).fetchone()[0]
        )
        event_result = json.loads(
            conn.execute(
                "SELECT payload_json FROM task_events ORDER BY sequence LIMIT 1"
            ).fetchone()[0]
        )["result"]
    assert result_count == 0
    assert snapshot_count == event_count == count
    assert snapshot_result == event_result


def test_explicit_dual_write_is_persisted_revision_safe_and_audited(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tasks.db"
    service = TaskResultRolloutService(path)
    _enable(service)
    restarted = TaskResultRolloutService(path)
    status = restarted.status()
    assert status["task_result_storage_state"] == "TASK_RESULTS_DUAL_WRITE"
    assert status["revision"] == 2

    snapshot, event = _terminal("dual-task")
    assert restarted.repository.record(snapshot, event)
    assert not restarted.repository.record(snapshot, event)
    persisted = restarted.repository.get("dual-task")
    assert persisted is not None and persisted.result_id
    assert restarted.repository.task_result_count() == 1
    authority = restarted.repository.get_result(persisted.result_id)
    assert authority is not None and authority["result"] == snapshot.result
    assert restarted.repository.list_task_result_rollout_audit() == [
        {
            "revision": 2,
            "from_state": "LEGACY_DUAL_FULL",
            "to_state": "TASK_RESULTS_DUAL_WRITE",
            "changed_at": status["updated_at"],
            "changed_by": "pytest",
            "reason": "isolated rollout test",
            "schema_version": 4,
        }
    ]

    with pytest.raises(TaskResultRolloutError) as stale:
        restarted.disable_dual_write(
            expected_revision=1,
            reason="stale rollback",
            updated_by="pytest",
        )
    assert stale.value.code == "TASK_RESULT_ROLLOUT_REVISION_CONFLICT"


def test_dual_write_rollback_keeps_existing_results_and_stops_future_writes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tasks.db"
    service = TaskResultRolloutService(path)
    _enable(service)
    first_snapshot, first_event = _terminal("before-rollback")
    assert service.repository.record(first_snapshot, first_event)
    first = service.repository.get("before-rollback")
    assert first is not None and first.result_id

    service.disable_dual_write(
        expected_revision=2,
        reason="stop compatibility writes",
        updated_by="pytest",
    )
    second_snapshot, second_event = _terminal("after-rollback")
    assert service.repository.record(second_snapshot, second_event)

    assert service.repository.task_result_count() == 1
    assert service.repository.get_result(first.result_id)["result"] == first_snapshot.result
    assert service.repository.get("after-rollback").result_id == ""
    assert service.status()["revision"] == 3


@pytest.mark.parametrize(
    ("target", "code"),
    [
        (
            TaskResultStorageState.TASK_RESULTS_VERIFIED,
            "TASK_RESULT_VERIFIED_APPLY_DISABLED",
        ),
        (
            TaskResultStorageState.RESULT_REF_AUTHORITY,
            "TASK_RESULT_REF_AUTHORITY_DISABLED",
        ),
    ],
)
def test_future_rollout_states_cannot_be_applied(
    tmp_path: Path,
    target: TaskResultStorageState,
    code: str,
) -> None:
    service = TaskResultRolloutService(tmp_path / "tasks.db")
    with pytest.raises(TaskResultRolloutError) as blocked:
        service.transition(
            target,
            expected_revision=1,
            reason="must remain blocked",
            updated_by="pytest",
        )
    assert blocked.value.code == code
    assert service.status()["task_result_storage_state"] == "LEGACY_DUAL_FULL"


def test_historical_backfill_is_classified_idempotent_and_ref_read_through(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tasks.db"
    repository = TaskRepository(path)

    matched_snapshot, matched_event = _terminal("matched")
    assert repository.record(matched_snapshot, matched_event)
    snapshot_only, snapshot_event = _terminal("snapshot-only")
    snapshot_event = replace(snapshot_event, payload={"message": "done"})
    assert repository.record(snapshot_only, snapshot_event)
    event_only, event_only_event = _terminal("event-only")
    event_only = replace(event_only, result={})
    assert repository.record(event_only, event_only_event)
    conflict, conflict_event = _terminal("conflict")
    conflict_event = replace(
        conflict_event,
        payload={"result": {"task": "conflict", "rows": 999}},
    )
    assert repository.record(conflict, conflict_event)
    invalid, invalid_event = _terminal("invalid")
    invalid = replace(invalid, result={})
    invalid_event = replace(invalid_event, payload={"message": "done"})
    assert repository.record(invalid, invalid_event)

    TaskResultRolloutService(path).enable_dual_write(
        expected_revision=1,
        reason="isolated historical backfill",
        updated_by="pytest",
    )
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path / "runtime")
    maintenance = TaskResultMaintenanceService(
        paths,
        site_id="line-12",
        tasks_database=path,
        development_root=tmp_path,
    )
    analysis = maintenance.analyze_backfill()
    assert analysis["classifications"] == {
        "CONFLICT": 1,
        "EVENT_ONLY": 1,
        "INVALID": 1,
        "MATCHED": 1,
        "SNAPSHOT_ONLY": 1,
    }
    first = maintenance.backfill(
        apply=True,
        allow_development_root_only=True,
    )
    second = maintenance.backfill(
        apply=True,
        allow_development_root_only=True,
    )
    assert first["new_result_rows"] == 3
    assert second["new_result_rows"] == 0
    assert second["idempotent"] is True

    ref = maintenance.enable_ref_authority(
        expected_revision=2,
        reason="isolated ref authority rehearsal",
        updated_by="pytest",
        apply=True,
        allow_development_root_only=True,
    )
    assert ref["state"] == "RESULT_REF_AUTHORITY"
    assert ref["revision"] == 4
    assert ref["snapshot_full_results_removed"] == 2
    with sqlite3.connect(path) as connection:
        stored = connection.execute(
            "SELECT result_json FROM task_snapshots WHERE task_id='matched'"
        ).fetchone()[0]
        event_payload = json.loads(
            connection.execute(
                "SELECT payload_json FROM task_events WHERE task_id='matched'"
            ).fetchone()[0]
        )
    assert stored == "{}"
    assert "result" not in event_payload and event_payload["result_id"]
    restarted = TaskRepository(path)
    assert restarted.get("matched").result == matched_snapshot.result
    assert restarted.list_events("matched")[0]["payload"]["result"] == (
        matched_snapshot.result
    )
    assert restarted.get("conflict").result == conflict.result


def test_backfill_binds_only_final_finished_result_after_null_error(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tasks.db"
    repository = TaskRepository(path)
    final_snapshot, finished_event = _terminal("error-then-finished")
    error_snapshot = replace(
        final_snapshot,
        status=TaskState.RUNNING,
        progress=50,
        result={},
        finished_time="",
        updated_time="2026-08-16T02:59:00Z",
    )
    error_event = replace(
        finished_event,
        event_id="error-before-finished",
        type="error",
        time="2026-08-16T02:59:00Z",
        payload={"message": "transient", "result": None},
    )
    assert repository.record(error_snapshot, error_event)
    assert repository.record(final_snapshot, finished_event)

    TaskResultRolloutService(path).enable_dual_write(
        expected_revision=1,
        reason="event binding regression",
        updated_by="pytest",
    )
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path / "runtime")
    maintenance = TaskResultMaintenanceService(
        paths,
        site_id="line-12",
        tasks_database=path,
        development_root=tmp_path,
    )
    first = maintenance.backfill(
        apply=True,
        allow_development_root_only=True,
    )
    with sqlite3.connect(path) as connection:
        finished_payload = json.loads(
            connection.execute(
                "SELECT payload_json FROM task_events "
                "WHERE event_id='finished-error-then-finished'"
            ).fetchone()[0]
        )
        error_payload = json.loads(
            connection.execute(
                "SELECT payload_json FROM task_events "
                "WHERE event_id='error-before-finished'"
            ).fetchone()[0]
        )
        error_payload.update(
            {
                key: finished_payload[key]
                for key in ("result_id", "result_hash", "result_summary")
            }
        )
        connection.execute(
            "UPDATE task_events SET payload_json=? "
            "WHERE event_id='error-before-finished'",
            (json.dumps(error_payload, ensure_ascii=False, separators=(",", ":")),),
        )
        connection.commit()
    repaired = maintenance.backfill(
        apply=True,
        allow_development_root_only=True,
    )
    maintenance.enable_ref_authority(
        expected_revision=2,
        reason="event binding regression",
        updated_by="pytest",
        apply=True,
        allow_development_root_only=True,
    )
    second = maintenance.backfill(
        apply=True,
        allow_development_root_only=True,
    )

    assert first["new_result_rows"] == 1
    assert first["invalid_event_refs_removed"] == 0
    assert repaired["invalid_event_refs_removed"] == 1
    assert repaired["idempotent"] is False
    assert second["idempotent"] is True
    with sqlite3.connect(path) as connection:
        raw_events = {
            str(event_id): json.loads(str(payload_json))
            for event_id, payload_json in connection.execute(
                "SELECT event_id, payload_json FROM task_events ORDER BY sequence"
            )
        }
    assert raw_events["error-before-finished"] == {
        "message": "transient",
        "result": None,
    }
    assert "result" not in raw_events["finished-error-then-finished"]
    assert raw_events["finished-error-then-finished"]["result_id"]
    events = TaskRepository(path).list_events("error-then-finished")
    assert events[0]["payload"]["result"] is None
    assert events[1]["payload"]["result"] == final_snapshot.result
    assert TaskRepository(path).get("error-then-finished").result == (
        final_snapshot.result
    )


def test_backfill_preserves_failed_snapshot_result_from_finished_event(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tasks.db"
    repository = TaskRepository(path)
    TaskResultRolloutService(path).enable_dual_write(
        expected_revision=1,
        reason="legacy failed snapshot fixture",
        updated_by="pytest",
    )
    result = {"data_persisted": False, "worker_exit_code": 1}
    snapshot, finished_event = _terminal("failed-with-finished-result")
    snapshot = replace(
        snapshot,
        status=TaskState.FAILED,
        result=result,
        error_message="legacy producer reported failure after persisting a result",
    )
    finished_event = replace(
        finished_event,
        payload={"message": "legacy terminal result", "result": result},
    )
    assert repository.record(snapshot, finished_event)

    maintenance = TaskResultMaintenanceService(
        PathResolver(app_root=tmp_path, data_root=tmp_path / "runtime"),
        site_id="line-12",
        tasks_database=path,
        development_root=tmp_path,
    )
    backfill = maintenance.backfill(
        apply=True,
        allow_development_root_only=True,
    )
    maintenance.enable_ref_authority(
        expected_revision=2,
        reason="legacy failed snapshot fixture",
        updated_by="pytest",
        apply=True,
        allow_development_root_only=True,
    )

    assert backfill["classifications"]["MATCHED"] == 1
    assert backfill["referenced_tasks"] == 1
    restarted = TaskRepository(path)
    stored = restarted.get(snapshot.task_id)
    assert stored is not None
    assert stored.status == TaskState.FAILED
    assert stored.result == result
    assert restarted.get_result(stored.result_id)["terminal_event_type"] == "finished"
    assert restarted.list_events(snapshot.task_id)[0]["payload"]["result"] == result


def test_backfill_does_not_replace_empty_cancelled_result_from_later_event(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tasks.db"
    repository = TaskRepository(path)
    timestamp = "2026-08-16T03:00:00Z"
    cancelled_snapshot = TaskSnapshot(
        task_id="cancelled-with-later-event",
        task_type="vehicle_mr_online_collection_start",
        task_name="Cancelled Collection",
        status=TaskState.CANCELLED,
        created_time=timestamp,
        finished_time=timestamp,
        updated_time=timestamp,
        result={},
    )
    cancelled_diagnostic = {"data_persisted": None, "worker_exit_code": 1}
    cancelled_event = TaskEvent(
        event_id="cancelled-empty",
        task_id=cancelled_snapshot.task_id,
        type="cancelled",
        time=timestamp,
        source="test",
        payload={"message": "cancelled", "result": cancelled_diagnostic},
    )
    later_result = {"data_persisted": True, "worker_exit_code": 0}
    later_finished = TaskEvent(
        event_id="finished-after-cancelled",
        task_id=cancelled_snapshot.task_id,
        type="finished",
        time="2026-08-16T03:00:01Z",
        source="test",
        payload={"message": "late", "result": later_result},
    )
    assert repository.record(cancelled_snapshot, cancelled_event)
    assert repository.record(cancelled_snapshot, later_finished)
    TaskResultRolloutService(path).enable_dual_write(
        expected_revision=1,
        reason="cancelled binding regression",
        updated_by="pytest",
    )
    maintenance = TaskResultMaintenanceService(
        PathResolver(app_root=tmp_path, data_root=tmp_path / "runtime"),
        site_id="line-12",
        tasks_database=path,
        development_root=tmp_path,
    )
    canonical = json.dumps(
        later_result,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    encoded = canonical.encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    result_id = "tr-" + hashlib.sha256(
        f"{cancelled_snapshot.task_id}\0finished\0{digest}".encode("utf-8")
    ).hexdigest()
    summary = repository._result_summary(later_result, byte_size=len(encoded))
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            INSERT INTO task_results (
                result_id, task_id, terminal_event_type, canonical_json,
                sha256, byte_size, schema_version, created_time
            ) VALUES (?, ?, 'finished', ?, ?, ?, 1, ?)
            """,
            (
                result_id,
                cancelled_snapshot.task_id,
                canonical,
                digest,
                len(encoded),
                later_finished.time,
            ),
        )
        connection.execute(
            "UPDATE task_snapshots SET result_id=?, result_hash=?, "
            "result_summary_json=? WHERE task_id=?",
            (
                result_id,
                digest,
                json.dumps(summary, ensure_ascii=False, separators=(",", ":")),
                cancelled_snapshot.task_id,
            ),
        )
        finished_payload = dict(later_finished.payload)
        finished_payload.update(
            {
                "result_id": result_id,
                "result_hash": digest,
                "result_summary": summary,
            }
        )
        connection.execute(
            "UPDATE task_events SET payload_json=? WHERE event_id=?",
            (
                json.dumps(
                    finished_payload, ensure_ascii=False, separators=(",", ":")
                ),
                later_finished.event_id,
            ),
        )
        connection.commit()

    first = maintenance.backfill(
        apply=True,
        allow_development_root_only=True,
    )
    second = maintenance.backfill(
        apply=True,
        allow_development_root_only=True,
    )

    assert first["classifications"]["CONFLICT"] == 1
    assert first["new_result_rows"] == 0
    assert first["referenced_tasks"] == 0
    assert first["invalid_snapshot_refs_removed"] == 1
    assert second["idempotent"] is True
    assert TaskRepository(path).get(cancelled_snapshot.task_id).result == {}
    events = TaskRepository(path).list_events(cancelled_snapshot.task_id)
    assert events[0]["payload"]["result"] == cancelled_diagnostic
    assert events[1]["payload"]["result"] == later_result


def test_backfill_keeps_event_only_result_out_of_empty_cancelled_snapshot(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tasks.db"
    repository = TaskRepository(path)
    timestamp = "2026-08-16T03:00:00Z"
    task_id = "cancelled-event-only-result"
    event_result = {"data_persisted": None, "worker_exit_code": 1}
    snapshot = TaskSnapshot(
        task_id=task_id,
        task_type="vehicle_mr_online_collection_start",
        task_name="Cancelled Collection",
        status=TaskState.CANCELLED,
        created_time=timestamp,
        finished_time=timestamp,
        updated_time=timestamp,
        result={},
    )
    event = TaskEvent(
        event_id="cancelled-event-only",
        task_id=task_id,
        type="cancelled",
        time=timestamp,
        source="test",
        payload={"message": "worker stopped", "result": event_result},
    )
    assert repository.record(snapshot, event)
    TaskResultRolloutService(path).enable_dual_write(
        expected_revision=1,
        reason="event-only result regression",
        updated_by="pytest",
    )
    maintenance = TaskResultMaintenanceService(
        PathResolver(app_root=tmp_path, data_root=tmp_path / "runtime"),
        site_id="line-12",
        tasks_database=path,
        development_root=tmp_path,
    )

    first = maintenance.backfill(apply=True, allow_development_root_only=True)
    second = maintenance.backfill(apply=True, allow_development_root_only=True)

    assert first["classifications"]["EVENT_ONLY"] == 1
    assert first["new_result_rows"] == 1
    assert first["referenced_tasks"] == 0
    assert second["idempotent"] is True
    with sqlite3.connect(path) as connection:
        stored_snapshot = connection.execute(
            "SELECT result_json, result_id, result_hash, result_summary_json "
            "FROM task_snapshots WHERE task_id=?",
            (task_id,),
        ).fetchone()
        stored_event = json.loads(
            connection.execute(
                "SELECT payload_json FROM task_events WHERE event_id=?",
                (event.event_id,),
            ).fetchone()[0]
        )
    assert stored_snapshot == ("{}", "", "", "{}")
    assert stored_event["result"] == event_result
    assert stored_event["result_id"]
    assert TaskRepository(path).get(task_id).result == {}
    assert TaskRepository(path).list_events(task_id)[0]["payload"]["result"] == (
        event_result
    )


def test_ref_authority_keeps_terminal_and_artifact_live_payloads_full(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    paths = PathResolver(app_root=tmp_path, data_root=data_root)
    task_db = paths.site_tasks_db_path("demo")
    TaskResultRolloutService(task_db).enable_dual_write(
        expected_revision=1,
        reason="isolated ref fixture",
        updated_by="pytest",
    )
    TaskResultMaintenanceService(
        paths,
        site_id="demo",
        tasks_database=task_db,
        development_root=tmp_path,
    ).enable_ref_authority(
        expected_revision=2,
        reason="isolated ref fixture",
        updated_by="pytest",
        apply=True,
        allow_development_root_only=True,
    )
    service = TaskApplicationService(paths, site_name="demo", reconcile_on_start=False)
    service.create_external_task(
        task_id="ref-live-result",
        task_type="agent_task",
        task_name="Ref Live Result",
        source="agent",
    )
    stream = service.events.open_stream()
    result = {"status": "COMPLETED", "rows": 11}
    snapshot = service.record_external_event(
        "ref-live-result",
        "finished",
        {"message": "done", "result": result},
        source="agent",
        event_id="ref-live-finished",
        event_time="2026-08-16T03:00:00Z",
    )
    live = stream.get(timeout=1)
    stream.close()

    assert snapshot.result == result and snapshot.result_id
    assert live["payload"]["result"] == result
    artifact_stream = service.events.open_stream()
    projection = {"artifact_id": "report-ref", "available": True, "rows": 11}
    projected = service.record_external_event(
        "ref-live-result",
        "artifact_finalized",
        {"message": "ready", "result": projection},
        source="artifact_store",
        event_id="ref-live-artifact",
        event_time="2026-08-16T03:01:00Z",
    )
    artifact_live = artifact_stream.get(timeout=1)
    artifact_stream.close()

    assert projected.result == projection
    assert projected.result_id and projected.result_id != snapshot.result_id
    assert artifact_live["payload"]["result"] == projection
    authority = service.repository("demo").get_result(projected.result_id)
    assert authority is not None
    assert authority["terminal_event_type"] == "artifact_finalized"
    assert authority["result"] == projection
    with sqlite3.connect(task_db) as connection:
        stored_snapshot = connection.execute(
            "SELECT result_json FROM task_snapshots WHERE task_id='ref-live-result'"
        ).fetchone()[0]
        stored_event = json.loads(
            connection.execute(
                "SELECT payload_json FROM task_events WHERE event_id='ref-live-finished'"
            ).fetchone()[0]
        )
        stored_artifact_event = json.loads(
            connection.execute(
                "SELECT payload_json FROM task_events WHERE event_id='ref-live-artifact'"
            ).fetchone()[0]
        )
    assert stored_snapshot == "{}"
    assert "result" not in stored_event and stored_event["result_id"]
    assert "result" not in stored_artifact_event
    assert stored_artifact_event["result_id"] == projected.result_id


def test_default_websocket_terminal_payload_remains_full(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path / "data")
    service = TaskApplicationService(paths, site_name="demo", reconcile_on_start=False)
    service.create_external_task(
        task_id="default-live-result",
        task_type="agent_task",
        task_name="Default Live Result",
        source="agent",
    )
    stream = service.events.open_stream()
    result = {"status": "COMPLETED", "rows": 7}
    snapshot = service.record_external_event(
        "default-live-result",
        "finished",
        {"message": "done", "result": result},
        source="agent",
        event_id="default-live-finished",
        event_time="2026-08-16T03:00:00Z",
    )
    live = stream.get(timeout=1)
    stream.close()

    assert snapshot.result == result and snapshot.result_id == ""
    assert live["payload"]["result"] == result
    assert service.repository("demo").task_result_count() == 0


def test_rollout_cli_requires_explicit_apply_and_persists_state(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data_root = tmp_path / "data"
    paths = PathResolver(app_root=tmp_path, data_root=data_root)
    site_root = paths.site_dir("demo")
    (site_root / "db").mkdir(parents=True)
    SiteRegistryRepository(paths).register(SiteRecord("demo", "Demo", site_root))

    common = ["--data-root", str(data_root), "--site-id", "demo"]
    assert rollout_cli_main(["status", *common]) == 0
    assert json.loads(capsys.readouterr().out)["task_result_storage_state"] == (
        "LEGACY_DUAL_FULL"
    )

    with pytest.raises(SystemExit, match="explicit --apply"):
        rollout_cli_main(
            [
                "enable-dual-write",
                *common,
                "--expected-revision",
                "1",
                "--reason",
                "controlled test rollout",
            ]
        )
    assert rollout_cli_main(
        [
            "enable-dual-write",
            *common,
            "--expected-revision",
            "1",
            "--reason",
            "controlled test rollout",
            "--apply",
        ]
    ) == 0
    enabled = json.loads(capsys.readouterr().out)
    assert enabled["task_result_storage_state"] == "TASK_RESULTS_DUAL_WRITE"
    assert enabled["revision"] == 2
