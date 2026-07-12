from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from netconsole.core.paths import PathResolver
from netconsole.models.task_state import TaskState
from netconsole.models.traffic_test import (
    ExecutionTargetKind,
    TrafficEvent,
    TrafficEventType,
    TrafficRun,
    TrafficTestType,
)
from netconsole.repositories.traffic_run_repository import TrafficRunRepository
from netconsole.services.traffic.event_hub import (
    TrafficEventHub,
    TrafficEventStreamOverflow,
)
from netconsole.services.traffic.event_store import TrafficEventStore


NOW = "2026-07-12T12:00:00.000Z"


def _store(tmp_path):
    paths = PathResolver(tmp_path)
    repository = TrafficRunRepository(paths.traffic_runs_db_path("demo"))
    repository.create(
        TrafficRun(
            traffic_run_id="run-1",
            controller_task_id="task-1",
            test_type=TrafficTestType.HIGH_FREQUENCY_PING,
            role="probe",
            executor_kind=ExecutionTargetKind.AGENT,
            agent_id="agent-1",
            normalized_config={"targets": ["192.0.2.1"]},
            status=TaskState.RUNNING,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    return paths, repository, TrafficEventStore(paths, repository)


def _event(event_type: TrafficEventType, *, remote_sequence: int | None = None, value: int = 1) -> TrafficEvent:
    return TrafficEvent(
        traffic_run_id="run-1",
        controller_task_id="task-1",
        source="agent",
        type=event_type,
        payload={"value": value, "message": "中文事件"},
        timestamp=NOW,
        remote_sequence=remote_sequence,
    )


def test_event_store_sequences_remote_dedup_restart_and_partial_line_tolerance(tmp_path) -> None:
    paths, repository, store = _store(tmp_path)
    first = store.append(_event(TrafficEventType.STATE, remote_sequence=1))
    assert first is not None and first.sequence == 1
    assert store.append(_event(TrafficEventType.STATE, remote_sequence=1)) is None
    second = store.append(_event(TrafficEventType.SAMPLE, remote_sequence=2, value=2))
    assert second is not None and second.sequence == 2

    path = paths.traffic_run_events_path("demo", "run-1")
    with path.open("a", encoding="utf-8") as file:
        file.write('{"sequence":')
    restarted = TrafficEventStore(paths, repository)
    third = restarted.append(_event(TrafficEventType.SUMMARY, value=3))
    assert third is not None and third.sequence == 3
    events = restarted.list_events("run-1", after_sequence=1)
    assert [event.sequence for event in events] == [2, 3]
    assert events[-1].payload["message"] == "中文事件"
    assert repository.get("run-1").last_event_sequence == 3


def test_event_store_atomic_summary_remote_result_and_secret_guard(tmp_path) -> None:
    paths, _repository, store = _store(tmp_path)
    summary_path = store.write_summary("run-1", {"sent": 10, "loss": 0})
    result_path = store.write_remote_result("run-1", {"status": "completed"})
    assert store.read_summary("run-1") == {"sent": 10, "loss": 0}
    assert store.read_remote_result("run-1") == {"status": "completed"}
    assert json.loads(summary_path.read_text(encoding="utf-8"))["sent"] == 10
    assert result_path == paths.traffic_run_remote_result_path("demo", "run-1")
    assert not list(summary_path.parent.glob("*.tmp"))
    with pytest.raises(ValueError):
        store.write_summary("run-1", {"agent_token": "secret"})


def test_event_store_redacts_absolute_paths_from_payload(tmp_path) -> None:
    _paths, _repository, store = _store(tmp_path)
    event = store.append(
        TrafficEvent(
            traffic_run_id="run-1",
            controller_task_id="task-1",
            source="local",
            type=TrafficEventType.ERROR,
            payload={
                "windows": r"C:\NetConsole\runtime\task.log",
                "unc": r"\\server\share\task.log",
                "uri": "file:///C:/NetConsole/runtime/task.log",
                "path_object": tmp_path / "task.log",
            },
            timestamp=NOW,
        )
    )
    assert event is not None
    assert set(event.payload.values()) == {"<redacted-path>"}
    assert "NetConsole" not in store.paths.traffic_run_events_path("demo", "run-1").read_text(encoding="utf-8")


def test_event_store_concurrent_append_keeps_unique_sequence_and_fast_tail_cursor(tmp_path) -> None:
    paths, _repository, store = _store(tmp_path)

    def append(index: int):
        return store.append(_event(TrafficEventType.SAMPLE, value=index))

    with ThreadPoolExecutor(max_workers=8) as executor:
        accepted = list(executor.map(append, range(40)))
    assert sorted(event.sequence for event in accepted if event is not None) == list(range(1, 41))
    tail = store.list_events("run-1", after_sequence=35)
    assert [event.sequence for event in tail] == [36, 37, 38, 39, 40]
    assert store._start_offset("run-1", 40, paths.traffic_run_events_path("demo", "run-1").stat().st_size) > 0


def test_event_hub_is_bounded_drops_samples_and_preserves_control_events(tmp_path) -> None:
    _paths, _repository, store = _store(tmp_path)
    hub = TrafficEventHub()
    stream = hub.open_stream(max_events=2)
    for value in (1, 2, 3):
        hub.publish(store.append(_event(TrafficEventType.SAMPLE, value=value)))
    error = store.append(_event(TrafficEventType.ERROR, value=4))
    hub.publish(error)
    received = [stream.get(0.1), stream.get(0.1)]
    assert [event.type for event in received] == [TrafficEventType.SAMPLE, TrafficEventType.ERROR]
    assert received[0].payload["value"] == 3


def test_event_hub_disconnects_critical_only_slow_subscriber_for_store_recovery(tmp_path) -> None:
    _paths, _repository, store = _store(tmp_path)
    hub = TrafficEventHub()
    stream = hub.open_stream(max_events=1)
    state = store.append(_event(TrafficEventType.STATE, value=1))
    error = store.append(_event(TrafficEventType.ERROR, value=2))
    hub.publish(state)
    hub.publish(error)
    assert stream.get(0.1) == state
    with pytest.raises(TrafficEventStreamOverflow):
        stream.get(0.1)
    assert [event.type for event in store.list_events("run-1")] == [TrafficEventType.STATE, TrafficEventType.ERROR]
