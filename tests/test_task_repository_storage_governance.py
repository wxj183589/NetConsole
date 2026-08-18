from __future__ import annotations

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
