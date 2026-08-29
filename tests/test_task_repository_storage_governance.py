from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

from netconsole.core.paths import PathResolver
from netconsole.models.task_snapshot import TaskEvent, TaskSnapshot
from netconsole.models.task_state import TaskState
from netconsole.repositories.history_store import TaskHistoryStore
from netconsole.repositories.task_repository import TaskRepository
from netconsole.services.job_center.task_application_service import TaskApplicationService


def _snapshot(task_id: str = "task-1", **changes) -> TaskSnapshot:
    values = {
        "task_id": task_id,
        "task_type": "trackside_ap_optical_update",
        "task_name": "轨旁 AP 光衰更新",
        "status": TaskState.RUNNING,
        "created_time": "2026-08-15T00:00:00Z",
        "updated_time": "2026-08-15T00:00:00Z",
        "stage": "collect",
        "current": 1,
        "total": 10,
        "message": "正在采集",
    }
    values.update(changes)
    return TaskSnapshot(**values)


def _event(event_id: str, event_time: str, payload: dict[str, object]) -> TaskEvent:
    return TaskEvent(
        event_id=event_id,
        task_id="task-1",
        type="progress",
        time=event_time,
        source="worker",
        payload=payload,
    )


def _event_count(path: Path) -> int:
    with sqlite3.connect(path) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM task_events").fetchone()[0])


def _result_reference(
    task_id: str,
    result: dict[str, object],
    *,
    terminal_event_type: str = "finished",
    created_time: str = "2026-08-15T00:01:00Z",
) -> dict[str, object]:
    canonical = json.dumps(
        result,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    encoded = canonical.encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    result_id = "tr-" + hashlib.sha256(
        f"{task_id}\0{terminal_event_type}\0{digest}".encode("utf-8")
    ).hexdigest()
    return {
        "result_id": result_id,
        "task_id": task_id,
        "terminal_event_type": terminal_event_type,
        "canonical_json": canonical,
        "sha256": digest,
        "byte_size": len(encoded),
        "schema_version": 1,
        "created_time": created_time,
    }


def test_duplicate_event_id_does_not_rewrite_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "tasks.db"
    repository = TaskRepository(path)
    original = _snapshot(message="first")
    event = _event("event-stable", "2026-08-15T00:00:01Z", {"current": 1, "total": 10})

    assert repository.record(original, event)
    changed = replace(
        original,
        message="must-not-win",
        current=9,
        updated_time="2026-08-15T00:00:09Z",
    )
    assert not repository.record(changed, event)

    persisted = repository.get(original.task_id)
    assert persisted is not None
    assert (persisted.message, persisted.current, persisted.updated_time) == (
        "first",
        1,
        "2026-08-15T00:00:00Z",
    )
    assert _event_count(path) == 1


def test_concurrent_duplicate_event_id_commits_one_snapshot_and_event(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tasks.db"
    repository = TaskRepository(path)
    event = _event(
        "event-concurrent-duplicate",
        "2026-08-15T00:00:01Z",
        {"current": 1, "total": 10},
    )
    candidates = [
        replace(_snapshot(message="winner-a"), updated_time="2026-08-15T00:00:01Z"),
        replace(_snapshot(message="winner-b"), updated_time="2026-08-15T00:00:02Z"),
    ]
    barrier = threading.Barrier(2)

    def record_after_barrier(snapshot: TaskSnapshot) -> bool:
        barrier.wait()
        return repository.record(snapshot, event)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(record_after_barrier, candidates)
        )

    assert sorted(results) == [False, True]
    persisted = repository.get(event.task_id)
    assert persisted is not None
    assert persisted.message in {"winner-a", "winner-b"}
    assert _event_count(path) == 1


def test_identical_progress_keeps_current_snapshot_and_samples_event_history(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tasks.db"
    repository = TaskRepository(path)
    snapshot = _snapshot()
    payload = {
        "stage": "collect",
        "current": 1,
        "total": 10,
        "message": "正在采集",
        "details": {"ap": "ap-1"},
    }

    assert repository.record(snapshot, _event("event-1", "2026-08-15T00:00:00Z", payload))
    second_snapshot = replace(snapshot, updated_time="2026-08-15T00:00:01Z")
    assert repository.record(
        second_snapshot,
        _event("event-2", "2026-08-15T00:00:01Z", payload),
    )

    persisted = repository.get(snapshot.task_id)
    assert persisted is not None
    assert (persisted.current, persisted.total, persisted.message) == (1, 10, "正在采集")
    assert persisted.updated_time == "2026-08-15T00:00:00Z"
    assert _event_count(path) == 1

    assert repository.record(
        replace(snapshot, updated_time="2026-08-15T00:00:30Z"),
        _event("event-3", "2026-08-15T00:00:30Z", payload),
    )
    changed_payload = {**payload, "current": 2}
    assert repository.record(
        replace(snapshot, current=2, updated_time="2026-08-15T00:00:31Z"),
        _event("event-4", "2026-08-15T00:00:31Z", changed_payload),
    )
    assert _event_count(path) == 3


def test_identical_progress_heartbeat_boundaries_are_exact(tmp_path: Path) -> None:
    path = tmp_path / "tasks.db"
    repository = TaskRepository(path)
    snapshot = _snapshot()
    payload = {"stage": "collect", "current": 1, "total": 10, "message": "same"}
    timestamps = [
        "2026-08-15T00:00:00.000Z",
        "2026-08-15T00:00:29.999Z",
        "2026-08-15T00:00:30.000Z",
        "2026-08-15T00:00:59.999Z",
        "2026-08-15T00:01:00.000Z",
    ]
    expected_event_counts = [1, 1, 2, 2, 3]

    for index, (timestamp, expected_count) in enumerate(
        zip(timestamps, expected_event_counts, strict=True), start=1
    ):
        assert repository.record(
            replace(snapshot, updated_time=timestamp),
            _event(f"heartbeat-{index}", timestamp, payload),
        )
        assert _event_count(path) == expected_count

    persisted = repository.get(snapshot.task_id)
    assert persisted is not None
    assert persisted.updated_time == timestamps[-1]


def test_progress_payload_field_change_is_durable(tmp_path: Path) -> None:
    path = tmp_path / "tasks.db"
    repository = TaskRepository(path)
    snapshot = _snapshot()
    first_payload = {
        "stage": "collect",
        "current": 1,
        "total": 10,
        "message": "正在采集",
        "details": {"ap": "ap-1", "rssi": -61},
    }
    changed_payload = {**first_payload, "details": {"ap": "ap-1", "rssi": -62}}

    assert repository.record(
        snapshot,
        _event("payload-field-1", "2026-08-15T00:00:00Z", first_payload),
    )
    assert repository.record(
        replace(snapshot, updated_time="2026-08-15T00:00:01Z"),
        _event("payload-field-2", "2026-08-15T00:00:01Z", changed_payload),
    )

    assert _event_count(path) == 2
    events = repository.list_events(snapshot.task_id)
    assert events[-1]["payload"] == changed_payload


@pytest.mark.parametrize(
    "event_type",
    ["state", "finished", "error", "cancelled", "log", "notification", "artifact_finalized"],
)
def test_non_progress_events_are_never_sampled(
    tmp_path: Path, event_type: str
) -> None:
    path = tmp_path / "tasks.db"
    repository = TaskRepository(path)
    snapshot = _snapshot()
    first = TaskEvent(
        event_id="log-1",
        task_id=snapshot.task_id,
        type=event_type,
        time="2026-08-15T00:00:00Z",
        payload={"message": "same"},
    )
    second = replace(first, event_id="log-2", time="2026-08-15T00:00:01Z")

    assert repository.record(snapshot, first)
    assert repository.record(snapshot, second)
    assert _event_count(path) == 2


def test_intervening_event_breaks_progress_run(tmp_path: Path) -> None:
    path = tmp_path / "tasks.db"
    repository = TaskRepository(path)
    snapshot = _snapshot()
    payload = {"current": 1, "total": 10, "message": "same"}
    assert repository.record(snapshot, _event("progress-1", "2026-08-15T00:00:00Z", payload))
    assert repository.record(
        snapshot,
        TaskEvent(
            event_id="log-1",
            task_id=snapshot.task_id,
            type="log",
            time="2026-08-15T00:00:01Z",
            payload={"message": "audit"},
        ),
    )
    assert repository.record(snapshot, _event("progress-2", "2026-08-15T00:00:02Z", payload))
    assert _event_count(path) == 3


def test_progress_source_change_is_a_durable_audit_event(tmp_path: Path) -> None:
    path = tmp_path / "tasks.db"
    repository = TaskRepository(path)
    snapshot = _snapshot()
    payload = {"current": 1, "total": 10, "message": "same"}
    first = _event("progress-1", "2026-08-15T00:00:00Z", payload)
    second = replace(
        first,
        event_id="progress-2",
        time="2026-08-15T00:00:01Z",
        source="agent",
    )

    assert repository.record(snapshot, first)
    assert repository.record(snapshot, second)
    assert _event_count(path) == 2


def test_sampled_progress_is_still_broadcast_to_live_task_subscribers(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path / "data")
    service = TaskApplicationService(paths, site_name="demo", reconcile_on_start=False)
    service.create_external_task(
        task_id="task-live",
        task_type="trackside_ap_optical_update",
        task_name="轨旁 AP 光衰更新",
        source="agent",
    )
    stream = service.events.open_stream()
    payload = {"stage": "collect", "current": 1, "total": 10, "message": "same"}

    service.record_external_event(
        "task-live",
        "progress",
        payload,
        event_id="live-progress-1",
        event_time="2026-08-15T00:00:00Z",
    )
    service.record_external_event(
        "task-live",
        "progress",
        payload,
        event_id="live-progress-2",
        event_time="2026-08-15T00:00:01Z",
    )

    assert [stream.get().get("id"), stream.get().get("id")] == [
        "live-progress-1",
        "live-progress-2",
    ]
    persisted = service.repository("demo").list_events("task-live")
    assert [event["type"] for event in persisted] == ["state", "progress"]
    assert persisted[1]["id"] == "live-progress-1"
    stream.close()


def test_task_results_rows_are_immutable(tmp_path: Path) -> None:
    path = tmp_path / "tasks.db"
    repository = TaskRepository(path)
    reference = _result_reference("immutable-result-task", {"rows": 2})

    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            INSERT INTO task_results (
                result_id, task_id, terminal_event_type, canonical_json,
                sha256, byte_size, schema_version, created_time
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            tuple(reference.values()),
        )
        conn.commit()

    with pytest.raises(sqlite3.IntegrityError, match="task_results rows are immutable"):
        with sqlite3.connect(path) as conn:
            conn.execute(
                "UPDATE task_results SET canonical_json=? WHERE result_id=?",
                ('{"rows":3}', reference["result_id"]),
            )
            conn.commit()

    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT canonical_json, sha256 FROM task_results WHERE result_id=?",
            (reference["result_id"],),
        ).fetchone()
    assert row == (reference["canonical_json"], reference["sha256"])
    assert repository.get_result(str(reference["result_id"]))["result"] == {"rows": 2}


def test_list_resolves_immutable_task_result_reference(tmp_path: Path) -> None:
    path = tmp_path / "tasks.db"
    repository = TaskRepository(path)
    canonical_result = '{"rows":2}'
    result_hash = hashlib.sha256(canonical_result.encode("utf-8")).hexdigest()
    result_id = "tr-" + hashlib.sha256(
        f"task-with-result\0finished\0{result_hash}".encode("utf-8")
    ).hexdigest()
    snapshot = _snapshot(
        task_id="task-with-result",
        status=TaskState.COMPLETED,
        finished_time="2026-08-15T00:01:00Z",
        updated_time="2026-08-15T00:01:00Z",
        result={"rows": 2},
        result_id=result_id,
        result_hash=result_hash,
    )

    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            INSERT INTO task_results (
                result_id, task_id, terminal_event_type, canonical_json,
                sha256, byte_size, schema_version, created_time
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result_id,
                "task-with-result",
                "finished",
                canonical_result,
                result_hash,
                len(canonical_result.encode("utf-8")),
                1,
                "2026-08-15T00:01:00Z",
            ),
        )
        conn.execute(
            """
            INSERT INTO task_snapshots (
                task_id, task_type, task_name, created_time, started_time,
                finished_time, status, progress, stage, current, total, message,
                owner, device, agent, result_path, error_message, result_json,
                result_id, result_hash, result_summary_json, source, site_name,
                owner_pid, resource_keys_json, text_integrity,
                text_integrity_reason, text_integrity_updated_at, text_schema_version,
                producer_kind, producer_version, producer_commit, expires_at,
                acknowledged_at, dismissed_at, dismissed_by, dismiss_reason,
                updated_time
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                      ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot.task_id,
                snapshot.task_type,
                snapshot.task_name,
                snapshot.created_time,
                snapshot.started_time,
                snapshot.finished_time,
                snapshot.status.value,
                snapshot.progress,
                snapshot.stage,
                snapshot.current,
                snapshot.total,
                snapshot.message,
                snapshot.owner,
                snapshot.device,
                snapshot.agent,
                snapshot.result_path,
                snapshot.error_message,
                '{"rows":2}',
                snapshot.result_id,
                snapshot.result_hash,
                "{}",
                snapshot.source,
                snapshot.site_name,
                snapshot.owner_pid,
                "[]",
                snapshot.text_integrity,
                snapshot.text_integrity_reason,
                snapshot.text_integrity_updated_at,
                snapshot.text_schema_version,
                snapshot.producer_kind,
                snapshot.producer_version,
                snapshot.producer_commit,
                snapshot.expires_at,
                snapshot.acknowledged_at,
                snapshot.dismissed_at,
                snapshot.dismissed_by,
                snapshot.dismiss_reason,
                snapshot.updated_time,
            ),
        )
        conn.commit()

    listed = repository.list()
    assert len(listed) == 1
    assert listed[0].result == {"rows": 2}


def test_snapshot_and_event_do_not_resolve_result_from_history_store_fallback(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tasks.db"
    repository = TaskRepository(path)
    task_id = "history-result-task"
    result = {"rows": 4, "status": "ok", "设备": "宁波"}
    reference = _result_reference(task_id, result)
    summary = repository._result_summary(
        result, byte_size=int(reference["byte_size"])
    )
    snapshot = _snapshot(
        task_id=task_id,
        status=TaskState.COMPLETED,
        finished_time=str(reference["created_time"]),
        updated_time=str(reference["created_time"]),
        result={},
        result_id=str(reference["result_id"]),
        result_hash=str(reference["sha256"]),
        result_summary={},
    )
    event = TaskEvent(
        event_id="history-result-event",
        task_id=task_id,
        type="finished",
        time=str(reference["created_time"]),
        source="test",
        payload={
            "message": "done",
            "result_id": str(reference["result_id"]),
            "result_hash": str(reference["sha256"]),
            "result_summary": summary,
        },
    )

    assert repository.record(snapshot, event)
    inserted, verified = TaskHistoryStore(
        path, history_root=tmp_path / "legacy-history"
    ).archive_result_rows([reference])
    assert (inserted, verified) == (1, 1)

    with pytest.raises(sqlite3.DatabaseError, match="task snapshot result reference is missing"):
        repository.get(task_id)


def test_full_snapshot_replacement_clears_stale_result_reference_without_event_result(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tasks.db"
    repository = TaskRepository(path)
    task_id = "stale-result-replacement"
    original = {"rows": 1}
    replacement = {"rows": 2}
    reference = _result_reference(task_id, original)
    TaskHistoryStore(path, history_root=tmp_path / "legacy-history").archive_result_rows(
        [reference]
    )
    timestamp = str(reference["created_time"])
    initial = _snapshot(
        task_id=task_id,
        status=TaskState.COMPLETED,
        finished_time=timestamp,
        updated_time=timestamp,
        result={},
        result_id=str(reference["result_id"]),
        result_hash=str(reference["sha256"]),
    )
    assert repository.record(
        initial,
        TaskEvent(
            event_id="stale-result-initial",
            task_id=task_id,
            type="finished",
            time=timestamp,
            source="test",
            payload={"message": "done"},
        ),
    )

    updated = replace(
        initial,
        result=replacement,
        updated_time="2026-08-15T00:02:00Z",
        message="updated",
    )
    assert repository.record(
        updated,
        TaskEvent(
            event_id="stale-result-artifact",
            task_id=task_id,
            type="artifact_finalized",
            time="2026-08-15T00:02:00Z",
            source="test",
            payload={"message": "updated"},
        ),
    )

    persisted = repository.get(task_id)
    assert persisted is not None
    assert persisted.result == replacement
    assert persisted.result_id == ""
    assert persisted.result_hash == ""
    assert persisted.result_summary == {}
    assert repository.task_result_count() == 0
    assert TaskHistoryStore(
        path, history_root=tmp_path / "legacy-history"
    ).get_result(str(reference["result_id"])) is not None


def test_ref_only_snapshot_update_does_not_read_history_result_reference(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tasks.db"
    repository = TaskRepository(path)
    task_id = "ref-only-progress"
    result = {"rows": 1}
    reference = _result_reference(task_id, result)
    TaskHistoryStore(path, history_root=tmp_path / "legacy-history").archive_result_rows(
        [reference]
    )
    timestamp = str(reference["created_time"])
    snapshot = _snapshot(
        task_id=task_id,
        status=TaskState.COMPLETED,
        finished_time=timestamp,
        updated_time=timestamp,
        result={},
        result_id=str(reference["result_id"]),
        result_hash=str(reference["sha256"]),
    )
    assert repository.record(
        snapshot,
        TaskEvent(
            event_id="ref-only-finished",
            task_id=task_id,
            type="finished",
            time=timestamp,
            source="test",
            payload={"message": "done"},
        ),
    )
    assert repository.record(
        replace(snapshot, message="still available", updated_time="2026-08-15T00:02:00Z"),
        TaskEvent(
            event_id="ref-only-progress",
            task_id=task_id,
            type="progress",
            time="2026-08-15T00:02:00Z",
            source="test",
            payload={"message": "still available"},
        ),
    )

    with pytest.raises(sqlite3.DatabaseError, match="task snapshot result reference is missing"):
        repository.get(task_id)


def test_full_snapshot_matching_result_reference_clears_retired_reference(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tasks.db"
    repository = TaskRepository(path)
    task_id = "same-result-reference"
    result = {"rows": 1}
    reference = _result_reference(task_id, result)
    TaskHistoryStore(path, history_root=tmp_path / "legacy-history").archive_result_rows(
        [reference]
    )
    timestamp = str(reference["created_time"])
    snapshot = _snapshot(
        task_id=task_id,
        status=TaskState.COMPLETED,
        finished_time=timestamp,
        updated_time=timestamp,
        result={},
        result_id=str(reference["result_id"]),
        result_hash=str(reference["sha256"]),
    )
    assert repository.record(
        snapshot,
        TaskEvent(
            event_id="same-result-finished",
            task_id=task_id,
            type="finished",
            time=timestamp,
            source="test",
            payload={"message": "done"},
        ),
    )
    assert repository.record(
        replace(snapshot, result=result, updated_time="2026-08-15T00:02:00Z"),
        TaskEvent(
            event_id="same-result-artifact",
            task_id=task_id,
            type="artifact_finalized",
            time="2026-08-15T00:02:00Z",
            source="test",
            payload={"message": "same result"},
        ),
    )

    persisted = repository.get(task_id)
    assert persisted is not None
    assert persisted.result == result
    assert persisted.result_id == ""
    assert persisted.result_hash == ""


def test_result_reference_missing_from_task_db_and_history_fails_loudly(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tasks.db"
    repository = TaskRepository(path)
    task_id = "missing-history-result"
    reference = _result_reference(task_id, {"rows": 1})
    snapshot = _snapshot(
        task_id=task_id,
        status=TaskState.COMPLETED,
        finished_time=str(reference["created_time"]),
        updated_time=str(reference["created_time"]),
        result={},
        result_id=str(reference["result_id"]),
        result_hash=str(reference["sha256"]),
    )
    event = TaskEvent(
        event_id="missing-history-event",
        task_id=task_id,
        type="finished",
        time=str(reference["created_time"]),
        source="test",
        payload={
            "result_id": str(reference["result_id"]),
            "result_hash": str(reference["sha256"]),
        },
    )
    assert repository.record(snapshot, event)

    with pytest.raises(sqlite3.DatabaseError, match="task snapshot result reference is missing"):
        repository.get(task_id)
    with pytest.raises(sqlite3.DatabaseError, match="task snapshot result reference is missing"):
        repository.list()
    with pytest.raises(sqlite3.DatabaseError, match="task event result reference is missing"):
        repository.list_events(task_id)


def test_history_store_result_task_binding_is_not_a_runtime_authority(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tasks.db"
    repository = TaskRepository(path)
    reference = _result_reference("original-task", {"rows": 2})
    TaskHistoryStore(path, history_root=tmp_path / "legacy-history").archive_result_rows(
        [reference]
    )
    mismatched_task = "different-task"
    snapshot = _snapshot(
        task_id=mismatched_task,
        status=TaskState.COMPLETED,
        finished_time=str(reference["created_time"]),
        updated_time=str(reference["created_time"]),
        result={},
        result_id=str(reference["result_id"]),
        result_hash=str(reference["sha256"]),
    )
    event = TaskEvent(
        event_id="mismatched-history-event",
        task_id=mismatched_task,
        type="finished",
        time=str(reference["created_time"]),
        source="test",
        payload={},
    )
    assert repository.record(snapshot, event)
    with pytest.raises(sqlite3.DatabaseError, match="task snapshot result reference is missing"):
        repository.get(mismatched_task)


def _record_retention_terminal(
    repository: TaskRepository,
    path: Path,
    *,
    task_id: str,
    ordinal: int,
    site_name: str,
    task_type: str = "ordinary_collect",
    result: dict[str, object] | None = None,
    resource_keys: tuple[str, ...] = (),
) -> None:
    timestamp = f"2026-08-16T00:00:{ordinal:02d}Z"
    payload = dict(result or {})
    snapshot = TaskSnapshot(
        task_id=task_id,
        task_type=task_type,
        task_name=task_id,
        status=TaskState.COMPLETED,
        created_time=timestamp,
        finished_time=timestamp,
        updated_time=timestamp,
        result=payload,
        resource_keys=resource_keys,
        site_name=site_name,
    )
    assert repository.record(
        snapshot,
        TaskEvent(
            event_id=f"finished-{task_id}",
            task_id=task_id,
            type="finished",
            time=timestamp,
            source="pytest",
            payload={"result": payload},
        ),
    )
    reference = _result_reference(task_id, payload, created_time=timestamp)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO task_results (
                result_id, task_id, terminal_event_type, canonical_json,
                sha256, byte_size, schema_version, created_time
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            tuple(reference.values()),
        )
        conn.commit()


def test_terminal_history_retention_keeps_ten_per_site_and_type_and_protects_business_links(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tasks.db"
    repository = TaskRepository(path)
    ordinary_ids = [f"ordinary-{index:02d}" for index in range(1, 16)]
    empty_site_ids = [f"empty-site-{index:02d}" for index in range(1, 16)]
    for index, task_id in enumerate(ordinary_ids, start=1):
        _record_retention_terminal(
            repository,
            path,
            task_id=task_id,
            ordinal=index,
            site_name="site-a",
        )
    for index, task_id in enumerate(empty_site_ids, start=1):
        _record_retention_terminal(
            repository,
            path,
            task_id=task_id,
            ordinal=index,
            site_name="",
        )
    _record_retention_terminal(
        repository,
        path,
        task_id="other-site-old",
        ordinal=1,
        site_name="site-b",
    )
    _record_retention_terminal(
        repository,
        path,
        task_id="other-type-old",
        ordinal=1,
        site_name="site-a",
        task_type="different_collect",
    )
    _record_retention_terminal(
        repository,
        path,
        task_id="mapped-online-mr",
        ordinal=1,
        site_name="site-a",
    )
    _record_retention_terminal(
        repository,
        path,
        task_id="mesh-source-linked",
        ordinal=1,
        site_name="site-a",
        result={"mesh_source_id": "mesh-source-1"},
    )
    _record_retention_terminal(
        repository,
        path,
        task_id="ground-session-linked",
        ordinal=1,
        site_name="site-a",
        resource_keys=("ground-unattended:site-a:run-1",),
    )
    repository.save(
        TaskSnapshot(
            task_id="active-old",
            task_type="ordinary_collect",
            task_name="active-old",
            status=TaskState.RUNNING,
            created_time="2026-08-16T00:00:01Z",
            updated_time="2026-08-16T00:00:01Z",
            site_name="site-a",
        )
    )
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE online_mr_task_sessions (
                controller_task_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT INTO online_mr_task_sessions VALUES (?, ?)",
            ("mapped-online-mr", "online-session-1"),
        )
        conn.commit()

    result = repository.enforce_terminal_history_retention()

    expected_deleted = {
        *ordinary_ids[:5],
        *empty_site_ids[:5],
    }
    assert result["limit_per_scope"] == 10
    assert set(result["deleted_task_ids"]) == expected_deleted
    assert result["deleted"] == {
        "task_snapshots": 10,
        "task_events": 10,
        "task_results": 10,
    }
    assert result["protected"] == {
        "active": 1,
        "online_mr_mapping": 1,
        "long_term_reference": 2,
        "unreadable_metadata": 0,
    }
    with sqlite3.connect(path) as conn:
        remaining_snapshots = {
            str(row[0]) for row in conn.execute("SELECT task_id FROM task_snapshots")
        }
        event_task_ids = {
            str(row[0]) for row in conn.execute("SELECT DISTINCT task_id FROM task_events")
        }
        result_task_ids = {
            str(row[0]) for row in conn.execute("SELECT DISTINCT task_id FROM task_results")
        }
        mapped_rows = conn.execute(
            "SELECT controller_task_id FROM online_mr_task_sessions"
        ).fetchall()

    assert not expected_deleted & remaining_snapshots
    assert not expected_deleted & event_task_ids
    assert not expected_deleted & result_task_ids
    assert {"active-old", "mapped-online-mr", "mesh-source-linked", "ground-session-linked"} <= remaining_snapshots
    assert {"other-site-old", "other-type-old", *ordinary_ids[5:], *empty_site_ids[5:]} <= remaining_snapshots
    assert mapped_rows == [("mapped-online-mr",)]


def test_terminal_history_retention_rolls_back_events_results_and_snapshots_together(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tasks.db"
    repository = TaskRepository(path)
    task_ids = [f"rollback-{index:02d}" for index in range(1, 16)]
    for index, task_id in enumerate(task_ids, start=1):
        _record_retention_terminal(
            repository,
            path,
            task_id=task_id,
            ordinal=index,
            site_name="site-a",
        )
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TRIGGER abort_terminal_retention
            BEFORE DELETE ON task_snapshots
            WHEN OLD.task_id = 'rollback-01'
            BEGIN
                SELECT RAISE(ABORT, 'retention rollback fixture');
            END
            """
        )
        conn.commit()

    with pytest.raises(sqlite3.IntegrityError, match="retention rollback fixture"):
        repository.enforce_terminal_history_retention()

    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM task_snapshots").fetchone()[0] == 15
        assert conn.execute("SELECT COUNT(*) FROM task_events").fetchone()[0] == 15
        assert conn.execute("SELECT COUNT(*) FROM task_results").fetchone()[0] == 15


def test_terminal_history_retention_tombstone_blocks_old_event_reinflation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tasks.db"
    repository = TaskRepository(path)
    task_ids = ["retired"] + [f"retained-{index:02d}" for index in range(10)]
    for ordinal, task_id in enumerate(task_ids):
        _record_retention_terminal(
            repository,
            path,
            task_id=task_id,
            ordinal=ordinal + 1,
            site_name="site-a",
        )

    retention = repository.enforce_terminal_history_retention()
    assert retention["deleted_task_ids"] == ["retired"]

    snapshot = _snapshot(
        task_id="retired",
        status=TaskState.COMPLETED,
        finished_time="2026-08-16T00:00:01Z",
        updated_time="2026-08-16T00:00:01Z",
        result={},
    )
    event = TaskEvent(
        event_id="replayed-retired-original",
        task_id="retired",
        type="finished",
        time="2026-08-16T00:00:01Z",
        source="pytest",
        payload={},
    )
    assert not repository.record(
        snapshot,
        replace(event, event_id="replayed-retired"),
    )
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM task_snapshots WHERE task_id='retired'"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM task_results WHERE task_id='retired'"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT reason FROM task_retention_tombstones WHERE task_id='retired'"
        ).fetchone()[0] == "terminal_history_retention"
