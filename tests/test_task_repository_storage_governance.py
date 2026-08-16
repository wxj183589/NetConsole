from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from netconsole.core.paths import PathResolver
from netconsole.models.task_snapshot import TaskEvent, TaskSnapshot
from netconsole.models.task_state import TaskState
from netconsole.repositories.history_store import TaskHistoryStore
from netconsole.repositories.task_repository import TaskRepository
from netconsole.services.job_center.task_application_service import (
    TaskApplicationService,
)
from netconsole.services.job_center.query_service import JobCenterQueryService
from netconsole.services.job_center.task_result_rollout import (
    TaskResultRolloutService,
)


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


def _event_rows(path: Path) -> list[tuple[int, str, str]]:
    with sqlite3.connect(path) as conn:
        return [
            (int(sequence), str(event_id), str(event_time))
            for sequence, event_id, event_time in conn.execute(
                "SELECT sequence, event_id, event_time FROM task_events ORDER BY sequence"
            ).fetchall()
        ]


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


def test_concurrent_duplicate_event_id_updates_snapshot_and_sequence_once(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tasks.db"
    repository = TaskRepository(path)
    barrier = threading.Barrier(2)
    event = _event(
        "event-concurrent",
        "2026-08-15T00:00:01Z",
        {"current": 1, "total": 10},
    )

    def write(message: str, current: int) -> bool:
        barrier.wait(timeout=5)
        return repository.record(
            _snapshot(
                message=message,
                current=current,
                updated_time=f"2026-08-15T00:00:0{current}Z",
            ),
            event,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(lambda args: write(*args), [("writer-a", 1), ("writer-b", 2)])
        )

    assert sorted(results) == [False, True]
    persisted = repository.get("task-1")
    assert persisted is not None
    assert (persisted.message, persisted.current) in {("writer-a", 1), ("writer-b", 2)}
    assert _event_rows(path) == [(1, "event-concurrent", "2026-08-15T00:00:01Z")]


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

    assert repository.record(
        snapshot, _event("event-1", "2026-08-15T00:00:00Z", payload)
    )
    second_snapshot = replace(snapshot, updated_time="2026-08-15T00:00:01Z")
    assert repository.record(
        second_snapshot,
        _event("event-2", "2026-08-15T00:00:01Z", payload),
    )

    persisted = repository.get(snapshot.task_id)
    assert persisted is not None
    assert (persisted.current, persisted.total, persisted.message) == (
        1,
        10,
        "正在采集",
    )
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


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("progress", 20),
        ("message", "changed"),
        ("stage", "verify"),
        ("current", 2),
        ("total", 20),
        ("details", {"ap": "ap-2"}),
    ],
)
def test_changed_progress_payload_is_always_durable(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    path = tmp_path / "tasks.db"
    repository = TaskRepository(path)
    snapshot = _snapshot()
    payload: dict[str, object] = {
        "progress": 10,
        "stage": "collect",
        "current": 1,
        "total": 10,
        "message": "same",
        "details": {"ap": "ap-1"},
    }
    assert repository.record(
        snapshot,
        _event("progress-1", "2026-08-15T00:00:00Z", payload),
    )

    changed = {**payload, field: value}
    assert repository.record(
        replace(snapshot, updated_time="2026-08-15T00:00:01Z"),
        _event("progress-2", "2026-08-15T00:00:01Z", changed),
    )
    assert _event_count(path) == 2


def test_identical_progress_recovery_lag_is_bounded_by_heartbeat(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tasks.db"
    repository = TaskRepository(path)
    snapshot = _snapshot()
    payload = {"current": 1, "total": 10, "message": "same"}
    times = (
        "2026-08-15T00:00:00Z",
        "2026-08-15T00:00:29.999000Z",
        "2026-08-15T00:00:30Z",
        "2026-08-15T00:00:59.999000Z",
        "2026-08-15T00:01:00Z",
    )
    for index, event_time in enumerate(times):
        assert repository.record(
            replace(snapshot, updated_time=event_time),
            _event(f"progress-{index}", event_time, payload),
        )

    rows = _event_rows(path)
    assert [row[2] for row in rows] == [times[0], times[2], times[4]]
    persisted = TaskRepository(path).get(snapshot.task_id)
    assert persisted is not None
    assert persisted.updated_time == times[4]
    persisted_times = [
        datetime.fromisoformat(row[2].replace("Z", "+00:00")) for row in rows
    ]
    assert (
        max(
            (current - previous).total_seconds()
            for previous, current in zip(persisted_times, persisted_times[1:])
        )
        <= 30
    )


def test_more_than_two_hundred_distinct_progress_facts_are_preserved(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tasks.db"
    repository = TaskRepository(path)
    snapshot = _snapshot()
    started = datetime(2026, 8, 15, tzinfo=UTC)

    for index in range(205):
        event_time = (started + timedelta(seconds=index)).isoformat().replace("+00:00", "Z")
        assert repository.record(
            replace(snapshot, current=index, updated_time=event_time),
            _event(
                f"distinct-progress-{index}",
                event_time,
                {"current": index, "total": 205, "message": f"step-{index}"},
            ),
        )

    events = TaskRepository(path).list_events(snapshot.task_id, limit=500)
    assert len(events) == 205
    assert [event["id"] for event in events] == [
        f"distinct-progress-{index}" for index in range(205)
    ]


@pytest.mark.parametrize("replay_count", [100, 1_000, 10_000])
def test_identical_progress_replay_does_not_reinflate_operational_history(
    tmp_path: Path, replay_count: int
) -> None:
    path = tmp_path / f"tasks-{replay_count}.db"
    repository = TaskRepository(path)
    snapshot = _snapshot()
    payload = {"current": 1, "total": replay_count, "message": "same"}
    event_time = "2026-08-15T00:00:00Z"

    for index in range(replay_count):
        assert repository.record(
            snapshot,
            _event(f"replayed-progress-{index}", event_time, payload),
        )

    assert _event_count(path) == 1
    assert TaskRepository(path).list_events(snapshot.task_id, limit=10)[0]["id"] == (
        "replayed-progress-0"
    )


@pytest.mark.parametrize(
    "event_type",
    [
        "state",
        "finished",
        "error",
        "cancelled",
        "log",
        "notification",
        "artifact_finalized",
    ],
)
def test_non_progress_events_are_never_sampled(
    tmp_path: Path,
    event_type: str,
) -> None:
    path = tmp_path / "tasks.db"
    repository = TaskRepository(path)
    snapshot = _snapshot()
    first = TaskEvent(
        event_id=f"{event_type}-1",
        task_id=snapshot.task_id,
        type=event_type,
        time="2026-08-15T00:00:00Z",
        payload={"message": "same"},
    )
    second = replace(
        first,
        event_id=f"{event_type}-2",
        time="2026-08-15T00:00:01Z",
    )

    assert repository.record(snapshot, first)
    assert repository.record(snapshot, second)
    assert _event_count(path) == 2


def test_intervening_event_breaks_progress_run(tmp_path: Path) -> None:
    path = tmp_path / "tasks.db"
    repository = TaskRepository(path)
    snapshot = _snapshot()
    payload = {"current": 1, "total": 10, "message": "same"}
    assert repository.record(
        snapshot, _event("progress-1", "2026-08-15T00:00:00Z", payload)
    )
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
    assert repository.record(
        snapshot, _event("progress-2", "2026-08-15T00:00:02Z", payload)
    )
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


@pytest.mark.parametrize(
    ("first_time", "second_time"),
    [
        ("2026-08-15T00:00:10Z", "2026-08-15T00:00:09Z"),
        ("invalid", "2026-08-15T00:00:01Z"),
        ("2026-08-15T00:00:00Z", "invalid"),
    ],
)
def test_clock_rollback_or_invalid_timestamp_is_always_durable(
    tmp_path: Path,
    first_time: str,
    second_time: str,
) -> None:
    path = tmp_path / "tasks.db"
    repository = TaskRepository(path)
    snapshot = _snapshot()
    payload = {"current": 1, "total": 10, "message": "same"}

    assert repository.record(snapshot, _event("progress-1", first_time, payload))
    assert repository.record(snapshot, _event("progress-2", second_time, payload))
    assert _event_count(path) == 2


def test_sampled_progress_is_still_broadcast_to_live_task_subscribers(
    tmp_path: Path,
) -> None:
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


def test_three_thousand_sampled_progress_events_are_all_broadcast_live(
    tmp_path: Path,
) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path / "data")
    service = TaskApplicationService(paths, site_name="demo", reconcile_on_start=False)
    service.create_external_task(
        task_id="task-live-3000",
        task_type="trackside_ap_optical_update",
        task_name="轨旁 AP 光衰更新",
        source="agent",
    )
    stream = service.events.open_stream(max_events=3_100)
    payload = {"stage": "collect", "current": 1, "total": 10, "message": "same"}
    started = datetime(2026, 8, 15, tzinfo=UTC)

    for index in range(3_000):
        event_time = (
            (started + timedelta(milliseconds=index)).isoformat().replace("+00:00", "Z")
        )
        service.record_external_event(
            "task-live-3000",
            "progress",
            payload,
            event_id=f"live-progress-{index}",
            event_time=event_time,
        )

    received = [stream.get(timeout=2)["id"] for _ in range(3_000)]
    assert received == [f"live-progress-{index}" for index in range(3_000)]
    persisted = service.repository("demo").list_events("task-live-3000", limit=3_100)
    assert [event["type"] for event in persisted] == ["state", "progress"]
    assert persisted[1]["id"] == "live-progress-0"
    stream.close()


def _terminal_event(
    task_id: str,
    event_id: str,
    result: dict[str, object],
    *,
    event_type: str = "finished",
    event_time: str = "2026-08-15T01:00:00Z",
) -> TaskEvent:
    return TaskEvent(
        event_id=event_id,
        task_id=task_id,
        type=event_type,
        time=event_time,
        source="worker",
        payload={"message": "done", "result": result},
    )


def _terminal_snapshot(
    task_id: str,
    result: dict[str, object],
    *,
    status: TaskState = TaskState.COMPLETED,
) -> TaskSnapshot:
    return _snapshot(
        task_id=task_id,
        status=status,
        progress=100,
        result=result,
        finished_time="2026-08-15T01:00:00Z",
        updated_time="2026-08-15T01:00:00Z",
    )


def _enable_dual_write(path: Path) -> None:
    TaskResultRolloutService(path).enable_dual_write(
        expected_revision=1,
        reason="B3 compatibility fixture",
        updated_by="pytest",
    )


def test_terminal_result_is_canonical_deterministic_idempotent_and_immutable(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tasks.db"
    repository = TaskRepository(path)
    _enable_dual_write(path)
    first_result = {"中文": "正常", "nested": {"z": 2, "a": 1}, "items": [3, 2, 1]}
    second_result = {"items": [3, 2, 1], "nested": {"a": 1, "z": 2}, "中文": "正常"}

    assert repository.record(
        _terminal_snapshot("task-canonical", first_result),
        _terminal_event("task-canonical", "finished-1", first_result),
    )
    assert repository.record(
        _terminal_snapshot("task-canonical", second_result),
        _terminal_event(
            "task-canonical",
            "finished-2",
            second_result,
            event_time="2026-08-15T01:00:01Z",
        ),
    )

    expected = json.dumps(
        first_result,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    expected_hash = hashlib.sha256(expected.encode("utf-8")).hexdigest()
    expected_id = (
        "tr-"
        + hashlib.sha256(
            f"task-canonical\0finished\0{expected_hash}".encode("utf-8")
        ).hexdigest()
    )
    with sqlite3.connect(path) as conn:
        row = conn.execute("SELECT * FROM task_results").fetchone()
        assert conn.execute("SELECT COUNT(*) FROM task_results").fetchone()[0] == 1
        assert row is not None
        assert (row[0], row[3], row[4], row[5], row[6]) == (
            expected_id,
            expected,
            expected_hash,
            len(expected.encode("utf-8")),
            1,
        )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute(
                "UPDATE task_results SET canonical_json='{}' WHERE result_id=?",
                (expected_id,),
            )


def test_terminal_result_identity_conflict_rolls_back_snapshot_and_event(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tasks.db"
    repository = TaskRepository(path)
    _enable_dual_write(path)
    result = {"status": "OK", "count": 3}
    canonical = TaskRepository._canonical_result_json(result)
    result_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    result_id = (
        "tr-"
        + hashlib.sha256(
            f"task-conflict\0finished\0{result_hash}".encode("utf-8")
        ).hexdigest()
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
                "task-conflict",
                "finished",
                '{"tampered":true}',
                result_hash,
                len(canonical.encode("utf-8")),
                1,
                "2026-08-15T00:00:00Z",
            ),
        )
        conn.commit()

    with pytest.raises(sqlite3.DatabaseError, match="hash mismatch"):
        repository.record(
            _terminal_snapshot("task-conflict", result),
            _terminal_event("task-conflict", "finished-conflict", result),
        )
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM task_snapshots").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM task_events").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM task_results").fetchone()[0] == 1


def test_old_dual_write_and_ref_only_results_remain_readable(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path / "data")
    path = paths.site_tasks_db_path("demo")
    repository = TaskRepository(path)
    repository.save(
        _terminal_snapshot("task-old-only", {"mode": "old-only", "count": 1})
    )
    dual_result = {"mode": "dual-write", "count": 2}
    _enable_dual_write(path)
    assert repository.record(
        _terminal_snapshot("task-ref", dual_result),
        _terminal_event("task-ref", "finished-ref", dual_result),
    )
    dual = repository.get("task-ref")
    assert dual is not None and dual.result == dual_result and dual.result_id

    with sqlite3.connect(path) as conn:
        event = conn.execute(
            "SELECT event_id, payload_json FROM task_events WHERE event_id='finished-ref'"
        ).fetchone()
        assert event is not None
        payload = json.loads(str(event[1]))
        payload.pop("result", None)
        conn.execute(
            "UPDATE task_snapshots SET result_json='' WHERE task_id='task-ref'"
        )
        conn.execute(
            "UPDATE task_events SET payload_json=? WHERE event_id=?",
            (json.dumps(payload, ensure_ascii=False, separators=(",", ":")), event[0]),
        )
        conn.commit()

    assert repository.get("task-old-only").result == {"mode": "old-only", "count": 1}
    ref_only = TaskRepository(path).get("task-ref")
    assert ref_only is not None and ref_only.result == dual_result
    events = TaskRepository(path).list_events("task-ref")
    assert events[-1]["payload"]["result"] == dual_result
    results = JobCenterQueryService(paths).list_task_results(
        "demo", task_type="trackside_ap_optical_update"
    )
    assert {item[0]["mode"] for item in results} == {"old-only", "dual-write"}


def test_job_center_reads_archived_result_and_events_after_typed_retention(
    tmp_path: Path,
) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path / "data")
    path = paths.site_tasks_db_path("demo")
    repository = TaskRepository(path)
    _enable_dual_write(path)
    result = {"mode": "archived-authority", "count": 2}
    assert repository.record(
        _terminal_snapshot("task-archived", result),
        _terminal_event("task-archived", "finished-archived", result),
    )
    snapshot = repository.get("task-archived")
    assert snapshot is not None and snapshot.result_id

    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        event_rows = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM task_events WHERE task_id='task-archived'"
            ).fetchall()
        ]
        result_rows = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM task_results WHERE task_id='task-archived'"
            ).fetchall()
        ]
    history = TaskHistoryStore(path, site_id="demo")
    assert history.archive_event_rows(event_rows)[1] == len(event_rows)
    assert history.archive_result_rows(result_rows)[1] == 1
    history.store.seal_open_shards()

    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE task_snapshots SET result_json='{}' WHERE task_id='task-archived'"
        )
        conn.execute("DROP TABLE task_events")
        conn.execute("DELETE FROM task_results WHERE task_id='task-archived'")
        conn.commit()

    restored = TaskRepository(path).get("task-archived")
    assert restored is not None and restored.result == result
    query = JobCenterQueryService(paths)
    listed = query.list_task_results(
        "demo", task_type="trackside_ap_optical_update"
    )
    assert listed == [(result, "2026-08-15T01:00:00Z")]
    assert query.get_task("demo", "task-archived") is not None
    logs = query.get_logs("demo", "task-archived")
    assert logs is not None and logs.lines


def test_event_result_read_through_rejects_different_task_authority(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tasks.db"
    repository = TaskRepository(path)
    _enable_dual_write(path)
    result = {"status": "OK", "count": 2}
    assert repository.record(
        _terminal_snapshot("authority-task", result),
        _terminal_event("authority-task", "authority-finished", result),
    )
    target_result = {"status": "OK", "count": 3}
    assert repository.record(
        _terminal_snapshot("target-task", target_result),
        _terminal_event("target-task", "target-finished", target_result),
    )
    authority = repository.get("authority-task")
    assert authority is not None
    with sqlite3.connect(path) as conn:
        payload = json.loads(
            conn.execute(
                "SELECT payload_json FROM task_events WHERE event_id='target-finished'"
            ).fetchone()[0]
        )
        payload.pop("result", None)
        payload["result_id"] = authority.result_id
        payload["result_hash"] = authority.result_hash
        conn.execute(
            "UPDATE task_events SET payload_json=? WHERE event_id='target-finished'",
            (json.dumps(payload, ensure_ascii=False, separators=(",", ":")),),
        )
        conn.commit()

    with pytest.raises(sqlite3.DatabaseError, match="task binding mismatch"):
        TaskRepository(path).list_events("target-task")


def test_event_result_read_through_rejects_different_terminal_event_type(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tasks.db"
    repository = TaskRepository(path)
    _enable_dual_write(path)
    result = {"status": "OK", "count": 2}
    snapshot = _terminal_snapshot("terminal-type-task", result)
    assert repository.record(
        snapshot,
        _terminal_event("terminal-type-task", "terminal-finished", result),
    )
    authority = repository.get("terminal-type-task")
    assert authority is not None
    assert repository.record(
        snapshot,
        TaskEvent(
            event_id="terminal-error",
            task_id="terminal-type-task",
            type="error",
            time="2026-08-15T01:00:01Z",
            source="worker",
            payload={"message": "transient", "result": None},
        ),
    )
    with sqlite3.connect(path) as conn:
        payload = {
            "message": "transient",
            "result_id": authority.result_id,
            "result_hash": authority.result_hash,
        }
        conn.execute(
            "UPDATE task_events SET payload_json=? WHERE event_id='terminal-error'",
            (json.dumps(payload, ensure_ascii=False, separators=(",", ":")),),
        )
        conn.commit()

    with pytest.raises(
        sqlite3.DatabaseError, match="terminal event binding mismatch"
    ):
        TaskRepository(path).list_events("terminal-type-task")


def test_snapshot_result_read_through_accepts_actual_terminal_event_type(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tasks.db"
    repository = TaskRepository(path)
    _enable_dual_write(path)
    result = {"status": "FAILED", "data_persisted": True}
    snapshot = _terminal_snapshot(
        "legacy-failed-finished",
        result,
        status=TaskState.FAILED,
    )
    assert repository.record(
        snapshot,
        _terminal_event("legacy-failed-finished", "legacy-finished", result),
    )
    with sqlite3.connect(path) as conn:
        result_row = conn.execute(
            "SELECT result_id, sha256 FROM task_results "
            "WHERE task_id='legacy-failed-finished' AND terminal_event_type='finished'"
        ).fetchone()
        assert result_row is not None
        conn.execute(
            "UPDATE task_snapshots SET result_json='{}', result_id=?, result_hash=? "
            "WHERE task_id='legacy-failed-finished'",
            result_row,
        )
        conn.commit()

    restarted = TaskRepository(path)
    stored = restarted.get("legacy-failed-finished")
    assert stored is not None
    assert stored.status == TaskState.FAILED
    assert stored.result == result


def test_dual_write_keeps_event_only_result_out_of_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "tasks.db"
    repository = TaskRepository(path)
    _enable_dual_write(path)
    result = {"data_persisted": None, "worker_exit_code": 1}
    snapshot = _terminal_snapshot(
        "event-only-live",
        {},
        status=TaskState.CANCELLED,
    )
    event = TaskEvent(
        event_id="event-only-cancelled",
        task_id=snapshot.task_id,
        type="cancelled",
        time="2026-08-15T01:00:00Z",
        source="worker",
        payload={"message": "worker stopped", "result": result},
    )

    assert repository.record(snapshot, event)

    persisted = repository.get(snapshot.task_id)
    assert persisted is not None
    assert persisted.result == {}
    assert persisted.result_id == ""
    stored_event = repository.list_events(snapshot.task_id)[0]
    assert stored_event["payload"]["result"] == result
    assert stored_event["payload"]["result_id"]
    assert repository.task_result_count() == 1


def test_large_terminal_result_round_trips_without_changing_producer_contract(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tasks.db"
    repository = TaskRepository(path)
    _enable_dual_write(path)
    result = {
        "producer": "vehicle_mr_online_refresh_all",
        "payload": "x" * (4 * 1024 * 1024 + 512 * 1024),
    }
    assert repository.record(
        _terminal_snapshot("task-large-result", result),
        _terminal_event("task-large-result", "finished-large", result),
    )
    persisted = repository.get("task-large-result")
    assert persisted is not None and persisted.result == result
    authority = repository.get_result(persisted.result_id)
    assert authority is not None
    assert 4 * 1024 * 1024 <= int(authority["byte_size"]) <= 5 * 1024 * 1024


def test_live_terminal_event_uses_persisted_result_identity(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path / "data")
    service = TaskApplicationService(paths, site_name="demo", reconcile_on_start=False)
    _enable_dual_write(paths.site_tasks_db_path("demo"))
    service.create_external_task(
        task_id="task-live-result",
        task_type="ac_fit_ap_resources_refresh",
        task_name="FIT-AP 资源刷新",
        source="agent",
    )
    stream = service.events.open_stream()
    result = {"status": "COMPLETED", "resources": [{"ap": "ap-1"}]}
    snapshot = service.record_external_event(
        "task-live-result",
        "finished",
        {"message": "done", "result": result},
        source="agent",
        event_id="live-finished-result",
        event_time="2026-08-15T01:00:00Z",
    )
    live = stream.get()
    authority = service.repository("demo").get_result(snapshot.result_id)
    assert authority is not None
    assert live["payload"]["result"] == authority["result"] == result
    assert live["payload"]["result_id"] == snapshot.result_id == authority["result_id"]
    assert live["payload"]["result_hash"] == snapshot.result_hash == authority["sha256"]
    stream.close()


def test_artifact_projection_rebinds_snapshot_without_mutating_terminal_result(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tasks.db"
    repository = TaskRepository(path)
    _enable_dual_write(path)
    terminal_result = {"artifact_id": "report-1", "available": False, "rows": 12}
    assert repository.record(
        _terminal_snapshot("task-artifact", terminal_result),
        _terminal_event("task-artifact", "finished-artifact", terminal_result),
    )
    terminal = repository.get("task-artifact")
    assert terminal is not None
    authority_before = repository.get_result(terminal.result_id)
    projection = {"artifact_id": "report-1", "available": True, "rows": 12}
    assert repository.record(
        replace(
            terminal,
            result=projection,
            updated_time="2026-08-15T01:01:00Z",
        ),
        TaskEvent(
            event_id="artifact-finalized",
            task_id="task-artifact",
            type="artifact_finalized",
            time="2026-08-15T01:01:00Z",
            source="artifact_reconciliation",
            payload={"message": "ready", "result": projection},
        ),
    )
    current = repository.get("task-artifact")
    authority_after = repository.get_result(terminal.result_id)
    assert current is not None and current.result == projection
    assert current.result_id != terminal.result_id
    current_authority = repository.get_result(current.result_id)
    assert current_authority is not None
    assert current_authority["terminal_event_type"] == "artifact_finalized"
    assert current_authority["result"] == projection
    assert authority_after == authority_before
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM task_results").fetchone()[0] == 2


def test_artifact_rejection_rebinds_failed_snapshot_result(tmp_path: Path) -> None:
    path = tmp_path / "tasks.db"
    repository = TaskRepository(path)
    _enable_dual_write(path)
    terminal_result = {"artifact_id": "report-2", "available": False}
    assert repository.record(
        _terminal_snapshot("task-artifact-rejected", terminal_result),
        _terminal_event(
            "task-artifact-rejected", "finished-artifact-rejected", terminal_result
        ),
    )
    terminal = repository.get("task-artifact-rejected")
    assert terminal is not None
    rejected_result = {
        "error_code": "ARTIFACT_INTEGRITY_FAILED",
        "error_message": "digest mismatch",
    }
    assert repository.record(
        replace(
            terminal,
            status=TaskState.FAILED,
            result=rejected_result,
            updated_time="2026-08-15T01:02:00Z",
        ),
        TaskEvent(
            event_id="artifact-rejected",
            task_id="task-artifact-rejected",
            type="artifact_rejected",
            time="2026-08-15T01:02:00Z",
            source="artifact_reconciliation",
            payload={"message": "invalid", "result": rejected_result},
        ),
    )

    current = repository.get("task-artifact-rejected")
    assert current is not None and current.status is TaskState.FAILED
    assert current.result_id != terminal.result_id
    authority = repository.get_result(current.result_id)
    assert authority is not None
    assert authority["terminal_event_type"] == "artifact_rejected"
    assert authority["result"] == rejected_result


def test_non_authority_event_cannot_diverge_snapshot_from_result_ref(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tasks.db"
    repository = TaskRepository(path)
    _enable_dual_write(path)
    canonical = {"rows": 12, "status": "complete"}
    assert repository.record(
        _terminal_snapshot("task-ref-preserved", canonical),
        _terminal_event("task-ref-preserved", "finished-ref-preserved", canonical),
    )
    terminal = repository.get("task-ref-preserved")
    assert terminal is not None and terminal.result_id

    assert repository.record(
        replace(
            terminal,
            result={"rows": 999, "status": "must-not-win"},
            result_id="",
            result_hash="",
            result_summary={},
            updated_time="2026-08-15T01:03:00Z",
        ),
        TaskEvent(
            event_id="post-terminal-log",
            task_id="task-ref-preserved",
            type="log",
            time="2026-08-15T01:03:00Z",
            source="worker",
            payload={"message": "late log"},
        ),
    )

    current = repository.get("task-ref-preserved")
    assert current is not None
    assert current.result_id == terminal.result_id
    assert current.result == canonical


def test_snapshot_read_rejects_nonempty_full_result_ref_mismatch(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tasks.db"
    repository = TaskRepository(path)
    _enable_dual_write(path)
    canonical = {"rows": 12}
    assert repository.record(
        _terminal_snapshot("task-ref-mismatch", canonical),
        _terminal_event("task-ref-mismatch", "finished-ref-mismatch", canonical),
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE task_snapshots SET result_json=? WHERE task_id=?",
            ('{"rows":999}', "task-ref-mismatch"),
        )
        connection.commit()

    with pytest.raises(sqlite3.DatabaseError, match="does not match result reference"):
        repository.get("task-ref-mismatch")


def test_batch_event_read_does_not_truncate_archived_history_at_10000(
    tmp_path: Path, monkeypatch
) -> None:
    repository = TaskRepository(tmp_path / "tasks.db")
    archived = [
        {
            "event_id": hashlib.sha256(f"archive-{sequence}".encode()).hexdigest(),
            "source_event_id": f"event-{sequence}",
            "sequence": sequence,
            "task_id": "task-archive",
            "task_event_type": "log",
            "event_time": f"2026-08-15T00:00:{sequence % 60:02d}Z",
            "source": "worker",
            "payload": {"message": f"row-{sequence}"},
        }
        for sequence in range(1, 10_002)
    ]
    monkeypatch.setattr(
        repository.task_history.store,
        "query_events_for_entities",
        lambda **_kwargs: archived,
    )

    grouped = repository.list_events_for_tasks(["task-archive"])

    assert len(grouped["task-archive"]) == len(archived)
    assert grouped["task-archive"][0]["id"] == "event-1"
    assert grouped["task-archive"][-1]["id"] == "event-10001"


def test_batch_event_read_queries_archive_once_and_pushes_down_type_filter(
    tmp_path: Path, monkeypatch
) -> None:
    repository = TaskRepository(tmp_path / "tasks.db")
    calls: list[dict[str, object]] = []

    def query_events_for_entities(**kwargs):
        calls.append(kwargs)
        return [
            {
                "event_id": "archive-id",
                "source_event_id": "event-1",
                "sequence": 1,
                "task_id": "task-1",
                "task_event_type": "finished",
                "event_time": "2026-08-15T00:00:00Z",
                "source": "worker",
                "payload": {"message": "done"},
            }
        ]

    monkeypatch.setattr(
        repository.task_history.store,
        "query_events_for_entities",
        query_events_for_entities,
    )

    grouped = repository.list_events_for_tasks(
        ["task-2", "task-1", "task-1"], event_types=["finished"]
    )

    assert len(calls) == 1
    assert calls[0]["entity_keys"] == ["task-1", "task-2"]
    assert calls[0]["event_types"] == ["finished"]
    assert [event["id"] for event in grouped["task-1"]] == ["event-1"]
    assert grouped["task-2"] == []


def test_batch_event_read_filters_multiple_entities_in_v2_archive(tmp_path: Path) -> None:
    path = tmp_path / "tasks.db"
    repository = TaskRepository(path)
    first = _snapshot("task-1")
    second = _snapshot("task-2")
    assert repository.record(
        first,
        _event("task-1-log", "2026-08-15T00:00:00Z", {"message": "one"}),
    )
    assert repository.record(
        replace(first, updated_time="2026-08-15T00:00:01Z"),
        TaskEvent(
            event_id="task-1-finished",
            task_id="task-1",
            type="finished",
            time="2026-08-15T00:00:01Z",
            source="worker",
            payload={"message": "done"},
        ),
    )
    assert repository.record(
        second,
        TaskEvent(
            event_id="task-2-finished",
            task_id="task-2",
            type="finished",
            time="2026-08-15T00:00:02Z",
            source="worker",
            payload={"message": "done"},
        ),
    )
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        rows = [dict(row) for row in conn.execute("SELECT * FROM task_events")]
    assert repository.task_history.archive_event_rows(rows) == (3, 3)
    repository.task_history.store.seal_open_shards()
    with sqlite3.connect(path) as conn:
        conn.execute("DELETE FROM task_events")
        conn.commit()

    grouped = repository.list_events_for_tasks(
        ["task-2", "task-1"], event_types=["finished"]
    )

    assert [event["id"] for event in grouped["task-1"]] == ["task-1-finished"]
    assert [event["id"] for event in grouped["task-2"]] == ["task-2-finished"]
