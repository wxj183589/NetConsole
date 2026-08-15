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
from netconsole.repositories.task_repository import TaskRepository
from netconsole.services.job_center.task_application_service import (
    TaskApplicationService,
)
from netconsole.services.job_center.query_service import JobCenterQueryService


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


def test_terminal_result_is_canonical_deterministic_idempotent_and_immutable(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tasks.db"
    repository = TaskRepository(path)
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


def test_large_terminal_result_round_trips_without_changing_producer_contract(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tasks.db"
    repository = TaskRepository(path)
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


def test_artifact_projection_does_not_mutate_authoritative_terminal_result(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tasks.db"
    repository = TaskRepository(path)
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
    assert current.result_id == terminal.result_id
    assert authority_after == authority_before
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM task_results").fetchone()[0] == 1
