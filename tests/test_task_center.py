from __future__ import annotations

import json
import queue
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from netconsole.backend.api.main import create_app
from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.models.task_history_policy import project_business_result
from netconsole.models.task_snapshot import TaskSnapshot, utc_now_iso
from netconsole.models.task_state import TaskState
from netconsole.repositories.task_repository import TaskRepository
from netconsole.services.background_job import BackgroundJob
from netconsole.services.job_center.job_events import finished_event, log_event, progress_event
from netconsole.services.job_center.task_application_service import (
    TaskApplicationService,
    TaskResourceConflictError,
)
from netconsole.services.job_center.query_service import JobCenterQueryService
from netconsole.services.job_center.worker_protocol import (
    WORKER_PROTOCOL_MAX_FRAME_BYTES,
    WorkerProtocolFrameTooLarge,
    encode_event,
    encode_event_bytes,
)


def _service(tmp_path: Path) -> TaskApplicationService:
    return TaskApplicationService(paths=PathResolver(tmp_path), site_name="demo")


def _app_for_service(
    service: TaskApplicationService,
    *,
    frontend_dist: Path,
):
    Database(service.paths.site_db_path("demo")).initialize()
    return create_app(
        RuntimeMode.SERVER,
        paths=service.paths,
        task_service=service,
        frontend_dist=frontend_dist,
    )


def _complete_task(service: TaskApplicationService, task_id: str = "task-complete") -> None:
    service.prepare(
        BackgroundJob(
            job_id=task_id,
            task_type="demo_task",
            params={"task_name": "演示任务", "site_name": "demo", "owner": "tester", "device_name": "设备A"},
        )
    )
    service.mark_running(task_id)
    service.feed_stdout(task_id, encode_event(progress_event(task_id, "collect", 3, 4, "采集中")).encode("utf-8"))
    service.feed_stdout(
        task_id,
        encode_event(finished_event(task_id, {"count": 3, "result_path": "outputs/result.json"})).encode("utf-8"),
    )
    service.complete(task_id, 0)


@pytest.mark.parametrize(
    ("result", "lifecycle_status", "expected"),
    [
        (
            {"status": "SUCCESS", "success_count": 4},
            "COMPLETED",
            ("SUCCESS", 4, 0, 0, 0, False),
        ),
        (
            {"success_count": 3, "failed_count": 1},
            "COMPLETED",
            ("PARTIAL_SUCCESS", 3, 1, 0, 0, True),
        ),
        (
            {"business_outcome": "WARNING", "warning_count": 2},
            "COMPLETED",
            ("WARNING", 0, 0, 0, 2, False),
        ),
        (
            {"status": "NO_TARGET", "skipped_count": 5},
            "COMPLETED",
            ("NO_EFFECTIVE_TARGET", 0, 0, 5, 0, False),
        ),
        (
            {
                "collection": {
                    "partial_success": True,
                    "success_count": 2,
                    "failed_count": 1,
                }
            },
            "COMPLETED",
            ("PARTIAL_SUCCESS", 2, 1, 0, 0, True),
        ),
        (
            {"failure_reason_counts": {"timeout": 3, "auth_failed": 1}},
            "FAILED",
            ("FAILED", 0, 0, 0, 0, False),
        ),
    ],
)
def test_business_result_projection_normalizes_legacy_results(
    result: dict[str, object],
    lifecycle_status: str,
    expected: tuple[str, int, int, int, int, bool],
) -> None:
    projection = project_business_result(
        result,
        lifecycle_status=lifecycle_status,
    )

    assert (
        projection.business_status,
        projection.success_count,
        projection.failed_count,
        projection.skipped_count,
        projection.warning_count,
        projection.partial_success,
    ) == expected
    if lifecycle_status == "FAILED":
        assert projection.primary_failure_reason == "timeout"


def test_task_snapshot_extracts_display_name_from_device_mapping(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.prepare(
        BackgroundJob(
            job_id="mapping-device",
            task_type="demo_task",
            params={"device": {"name": "映射设备", "device_uuid": "device-1"}},
        )
    )

    snapshot = service.get_task("mapping-device")
    assert snapshot is not None
    assert snapshot.device == "映射设备"


def test_task_repository_persists_snapshot_events_and_wal(tmp_path: Path) -> None:
    service = _service(tmp_path)
    _complete_task(service)

    restored = _service(tmp_path).get_task("task-complete")
    assert restored is not None
    assert restored.status is TaskState.COMPLETED
    assert restored.progress == 100
    assert restored.owner == "tester"
    assert restored.device == "设备A"
    assert restored.result_path == "outputs/result.json"
    assert {event["type"] for event in service.list_events("task-complete")} >= {"state", "progress", "finished"}
    with sqlite3.connect(service.paths.site_tasks_db_path("demo")) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_task_runtime_preserves_chinese_when_utf8_is_split_at_every_byte(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    task_id = "utf8-byte-split"
    service.prepare(
        BackgroundJob(
            job_id=task_id,
            task_type="demo_task",
            params={"task_name": "宁波地铁1号线", "site_name": "demo"},
        )
    )
    service.mark_running(task_id)
    output = (
        encode_event(
            progress_event(task_id, "auth", 1, 2, "SSH 认证失败")
        )
        + encode_event(
            finished_event(
                task_id,
                {"device_name": "中文设备"},
                message="任务已完成",
            )
        )
    ).encode("utf-8")

    for value in output:
        service.feed_stdout(task_id, bytes((value,)))
    service.complete(task_id, 0)

    restored = service.get_task(task_id)
    events = service.list_events(task_id)
    serialized = json.dumps(events, ensure_ascii=False)
    assert restored is not None
    assert restored.status is TaskState.COMPLETED
    assert "SSH 认证失败" in serialized
    assert "任务已完成" in serialized
    assert "中文设备" in serialized
    assert "�" not in serialized


def test_task_runtime_rejects_cp936_worker_protocol_without_persisting_corrupted_text(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    task_id = "cp936-worker-protocol"
    service.prepare(BackgroundJob(job_id=task_id, task_type="demo_task"))
    service.mark_running(task_id)
    legacy_payload = (
        json.dumps(
            progress_event(task_id, "auth", 1, 2, "正在验证设备凭据"),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("cp936")

    service.feed_stdout(task_id, legacy_payload)
    service.complete(task_id, 0)

    restored = service.get_task(task_id)
    events = service.list_events(task_id)
    serialized = json.dumps(events, ensure_ascii=False)
    detail = JobCenterQueryService(service.paths).get_task("demo", task_id)
    assert restored is not None
    assert restored.status is TaskState.FAILED
    assert restored.result["error_code"] == "WORKER_PROTOCOL_CORRUPTED"
    assert "正在验证设备凭据" not in serialized
    assert "�" not in serialized
    assert detail is not None
    assert detail.text_integrity == "current_corrupted"
    assert detail.text_integrity_reason == "worker_protocol_decode_failed"


def test_task_runtime_rejects_replacement_character_from_current_worker_event(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    task_id = "replacement-worker-protocol"
    service.prepare(BackgroundJob(job_id=task_id, task_type="demo_task"))
    service.mark_running(task_id)

    service.feed_stdout(
        task_id,
        encode_event(progress_event(task_id, "auth", 1, 2, "正在验证�设备凭据")).encode("ascii"),
    )
    service.complete(task_id, 0)

    events = service.list_events(task_id)
    assert all("�" not in json.dumps(event, ensure_ascii=False) for event in events)
    restored = service.get_task(task_id)
    assert restored is not None and restored.status is TaskState.FAILED
    assert restored.result["text_integrity_reason"] == "replacement_character_detected_in_current_event"


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (b"{invalid-json}\n", "worker_protocol_json_invalid"),
        (b"[]\n", "worker_protocol_schema_invalid"),
        (
            json.dumps(
                {
                    "type": "progress",
                    "job_id": "schema-invalid",
                    "current": "one",
                }
            ).encode()
            + b"\n",
            "worker_protocol_schema_invalid",
        ),
        (
            json.dumps(
                {"type": "mystery", "job_id": "unexpected-message"}
            ).encode()
            + b"\n",
            "worker_protocol_unexpected_message",
        ),
        (b"x" * 1_048_577, "worker_protocol_frame_too_large"),
    ],
    ids=["json-invalid", "not-object", "schema-invalid", "unexpected", "frame-too-large"],
)
def test_task_runtime_fails_every_fatal_protocol_reason(
    tmp_path: Path,
    payload: bytes,
    reason: str,
) -> None:
    service = _service(tmp_path)
    task_id = (
        "schema-invalid"
        if reason == "worker_protocol_schema_invalid" and b"progress" in payload
        else "unexpected-message"
        if reason == "worker_protocol_unexpected_message"
        else f"fatal-{reason}"
    )
    service.prepare(BackgroundJob(job_id=task_id, task_type="demo_task"))
    service.mark_running(task_id)

    assert service.feed_stdout(task_id, payload) is True

    snapshot = service.get_task(task_id)
    assert snapshot is not None and snapshot.status is TaskState.RUNNING
    assert service.runtime.is_running(task_id)
    terminal = service.complete(task_id, 17)
    assert terminal is not None
    assert terminal["worker_exit_code"] == 17
    snapshot = service.get_task(task_id)
    assert snapshot is not None and snapshot.status is TaskState.FAILED
    assert snapshot.result["error_code"] == "WORKER_PROTOCOL_CORRUPTED"
    assert snapshot.result["text_integrity_reason"] == reason
    assert snapshot.result["worker_exit_code"] == 17
    assert snapshot.result["reason"] == reason
    assert not service.runtime.is_running(task_id)


def test_worker_protocol_writer_rejects_oversized_frame() -> None:
    with pytest.raises(WorkerProtocolFrameTooLarge) as exc_info:
        encode_event_bytes(
            {
                "type": "finished",
                "job_id": "oversized-writer",
                "result": {"payload": "x" * WORKER_PROTOCOL_MAX_FRAME_BYTES},
            }
        )

    assert exc_info.value.frame_bytes > WORKER_PROTOCOL_MAX_FRAME_BYTES
    assert exc_info.value.max_frame_bytes == WORKER_PROTOCOL_MAX_FRAME_BYTES


def test_worker_error_preserves_structured_result_and_exit_code(tmp_path: Path) -> None:
    service = _service(tmp_path)
    task_id = "worker-structured-error"
    service.prepare(BackgroundJob(job_id=task_id, task_type="demo_task"))
    service.mark_running(task_id)

    service.feed_stdout(
        task_id,
        encode_event(
            {
                "type": "error",
                "job_id": task_id,
                "message": "Worker 已持久化数据后失败",
                "error": "worker_protocol_frame_too_large",
                "result": {
                    "reason": "worker_protocol_frame_too_large",
                    "stream": "stdout",
                    "frame_bytes": 2_000_000,
                    "max_frame_bytes": WORKER_PROTOCOL_MAX_FRAME_BYTES,
                    "data_persisted": True,
                },
                "cancelled": False,
            }
        ).encode("utf-8")
    )

    service.complete(task_id, 1)

    snapshot = service.get_task(task_id)
    assert snapshot is not None
    assert snapshot.status is TaskState.FAILED
    assert snapshot.result["reason"] == "worker_protocol_frame_too_large"
    assert snapshot.result["frame_bytes"] == 2_000_000
    assert snapshot.result["data_persisted"] is True
    assert snapshot.result["worker_exit_code"] == 1
    detail = JobCenterQueryService(service.paths).get_task("demo", task_id)
    assert detail is not None
    assert detail.details["reason"] == "worker_protocol_frame_too_large"
    assert detail.details["worker_exit_code"] == 1
    assert detail.details["data_persisted"] is True


def test_malformed_worker_keeps_backend_health_online(tmp_path: Path) -> None:
    service = _service(tmp_path)
    task_id = "worker-health-after-protocol-error"
    service.prepare(BackgroundJob(job_id=task_id, task_type="demo_task"))
    service.mark_running(task_id)
    app = _app_for_service(service, frontend_dist=tmp_path / "missing-dist")

    with TestClient(app) as client:
        before = client.get("/api/health")
        assert service.feed_stdout(task_id, b"\xff") is True
        service.complete(task_id, 1)
        after = client.get("/api/health")

    assert before.status_code == 200
    assert after.status_code == 200


def test_task_persistence_guard_blocks_corrupted_worker_event(tmp_path: Path) -> None:
    service = _service(tmp_path)
    task_id = "persistence-integrity-guard"
    service.prepare(BackgroundJob(job_id=task_id, task_type="demo_task"))
    service.mark_running(task_id)

    service.events.publish(
        progress_event(task_id, "auth", 1, 2, "当前事件�损坏"),
        source="worker",
    )

    restored = service.get_task(task_id)
    events = service.list_events(task_id)
    assert restored is not None and restored.status is TaskState.FAILED
    assert restored.result["error_code"] == "WORKER_PROTOCOL_CORRUPTED"
    assert all("�" not in json.dumps(event, ensure_ascii=False) for event in events)


def test_job_center_reports_backend_text_integrity_for_current_historical_and_ok(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    query = JobCenterQueryService(service.paths)
    now = utc_now_iso()
    service.repository("demo").save(
        TaskSnapshot(
            task_id="current-damaged",
            task_type="demo_task",
            task_name="current-damaged",
            status=TaskState.FAILED,
            created_time=now,
            updated_time=now,
            message="Worker 已停止",
            site_name="demo",
            text_integrity="current_corrupted",
            text_integrity_reason="worker_protocol_decode_failed",
            text_schema_version=2,
            producer_kind="local_worker",
        )
    )
    service.repository("demo").save(
        TaskSnapshot(
            task_id="historical-damaged",
            task_type="demo_task",
            task_name="historical-damaged",
            status=TaskState.COMPLETED,
            created_time=now,
            updated_time=now,
            message="历史损坏记录",
            site_name="demo",
            text_integrity="historical_corrupted",
            text_integrity_reason="legacy_task_before_text_schema_v2",
        )
    )
    service.repository("demo").save(
        TaskSnapshot(
            task_id="normal-text",
            task_type="demo_task",
            task_name="normal-text",
            status=TaskState.COMPLETED,
            created_time=now,
            updated_time=now,
            message="中文正常",
            site_name="demo",
        )
    )

    listing = {item.id: item for item in query.list_tasks("demo")}
    current = query.get_task("demo", "current-damaged")
    historical = query.get_task("demo", "historical-damaged")
    normal = query.get_task("demo", "normal-text")
    assert current is not None and current.text_integrity == "current_corrupted"
    assert current.text_integrity_reason == "worker_protocol_decode_failed"
    assert historical is not None and historical.text_integrity == "historical_corrupted"
    assert historical.text_integrity_reason == "legacy_task_before_text_schema_v2"
    assert normal is not None and normal.text_integrity == "ok"
    assert normal.text_integrity_reason == ""
    assert listing["current-damaged"].text_integrity == current.text_integrity
    assert listing["historical-damaged"].text_integrity == historical.text_integrity
    assert listing["normal-text"].text_integrity == normal.text_integrity


def test_task_runtime_enables_utf8_for_worker_process(tmp_path: Path) -> None:
    service = _service(tmp_path)

    launch = service.prepare(BackgroundJob(job_id="utf8-environment", task_type="demo_task"))

    assert launch.environment["PYTHONUTF8"] == "1"
    assert launch.environment["PYTHONIOENCODING"] == "utf-8"


def test_structured_progress_details_persist_and_can_cap_running_progress(tmp_path: Path) -> None:
    service = _service(tmp_path)
    task_id = "structured-progress"
    service.prepare(BackgroundJob(job_id=task_id, task_type="trackside_ap_optical_update", params={"task_name": "轨旁 AP 光衰"}))
    service.mark_running(task_id)
    service.feed_stdout(
        task_id,
        encode_event(
            progress_event(
                task_id,
                "trackside_ap.fit_ap.collect",
                1000,
                1000,
                "AP 1000/1000 成功",
                details={
                    "phase": "fit_ap_optical",
                    "event": "ap_completed",
                    "ap_name": "AP-1000",
                    "ap_ip": "10.0.0.100",
                    "status": "success",
                    "prevent_running_100": True,
                },
            )
        ).encode("utf-8"),
    )

    snapshot = service.get_task(task_id)
    assert snapshot is not None
    assert snapshot.status is TaskState.RUNNING
    assert snapshot.progress == 99
    events = service.list_events(task_id)
    progress_payload = next(event["payload"] for event in events if event["type"] == "progress")
    assert progress_payload["details"]["ap_name"] == "AP-1000"
    detail = JobCenterQueryService(service.paths).get_task("demo", task_id)
    logs = JobCenterQueryService(service.paths).get_logs("demo", task_id)
    assert detail is not None and detail.details["ap_ip"] == "10.0.0.100"
    assert logs is not None and logs.lines[-1].details["status"] == "success"

    service.feed_stdout(task_id, encode_event(finished_event(task_id, {"success_count": 1})).encode("utf-8"))
    service.complete(task_id, 0)
    finished = service.get_task(task_id)
    assert finished is not None and finished.progress == 100


def test_trackside_business_result_is_exposed_in_task_detail_without_raw_result_leak(tmp_path: Path) -> None:
    service = _service(tmp_path)
    task_id = "trackside-partial-result"
    service.prepare(
        BackgroundJob(
            job_id=task_id,
            task_type="trackside_ap_optical_update",
            params={"task_name": "轨旁 AP 光衰", "site_name": "demo"},
        )
    )
    service.mark_running(task_id)
    result = {
        "status": "PARTIAL_SUCCESS",
        "success_count": 745,
        "failed_count": 0,
        "skipped_count": 1,
        "actionable_skipped_count": 1,
        "ignored_skipped_count": 0,
        "target_count": 746,
        "skipped_reason_counts": {"connection_incomplete": 1},
        "failure_reason_counts": {},
        "skipped": [{"name": "AP-A", "host": "10.0.0.1", "reason": "connection_incomplete"}],
    }
    service.feed_stdout(task_id, encode_event(finished_event(task_id, result)).encode("utf-8"))
    service.complete(task_id, 0)

    query = JobCenterQueryService(service.paths)
    detail = query.get_task("demo", task_id)
    listing = {item.id: item for item in query.list_tasks("demo")}

    assert detail is not None
    assert detail.status == "COMPLETED"
    assert detail.lifecycle_status == "COMPLETED"
    assert detail.business_status == "PARTIAL_SUCCESS"
    assert detail.success_count == 745
    assert detail.failed_count == 0
    assert detail.skipped_count == 1
    assert detail.warning_count == 0
    assert detail.partial_success is True
    assert detail.primary_failure_reason == "connection_incomplete"
    assert detail.has_warning is True
    assert listing[task_id].has_warning is True
    assert listing[task_id].business_status == detail.business_status
    assert listing[task_id].success_count == detail.success_count
    assert listing[task_id].failed_count == detail.failed_count
    assert listing[task_id].skipped_count == detail.skipped_count
    assert listing[task_id].warning_count == detail.warning_count
    assert listing[task_id].partial_success == detail.partial_success
    assert (
        listing[task_id].primary_failure_reason
        == detail.primary_failure_reason
    )
    assert [item.id for item in query.list_tasks("demo", warning_only=True)] == [task_id]
    assert detail.details == {
        "status": "PARTIAL_SUCCESS",
        "success_count": 745,
        "failed_count": 0,
        "skipped_count": 1,
        "actionable_skipped_count": 1,
        "ignored_skipped_count": 0,
        "target_count": 746,
        "skipped_reason_counts": {"connection_incomplete": 1},
        "failure_reason_counts": {},
    }
    assert "skipped" not in detail.details


def test_task_repository_initialization_preserves_existing_tables(tmp_path: Path) -> None:
    db_path = PathResolver(tmp_path).site_tasks_db_path("demo")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE legacy_marker (value TEXT)")
        conn.execute("INSERT INTO legacy_marker VALUES ('keep')")
        conn.commit()

    TaskRepository(db_path)

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT value FROM legacy_marker").fetchone()[0] == "keep"
        assert (
            conn.execute(
                "SELECT value FROM task_schema_meta WHERE key = 'schema_version'"
            ).fetchone()[0]
            == "3"
        )


def test_task_repository_migrates_legacy_text_integrity_once(tmp_path: Path) -> None:
    db_path = PathResolver(tmp_path).site_tasks_db_path("demo")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE task_schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO task_schema_meta VALUES ('schema_version', '1');
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
                sequence INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE,
                task_id TEXT NOT NULL, event_type TEXT NOT NULL, event_time TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'service', payload_json TEXT NOT NULL DEFAULT '{}'
            );
            """
        )
        conn.execute(
            """
            INSERT INTO task_snapshots (
                task_id, task_type, task_name, created_time, status, message, updated_time
            ) VALUES ('legacy-damaged', 'demo_task', '旧任务', '2026-01-01T00:00:00Z',
                      'COMPLETED', '已结束', '2026-01-01T00:01:00Z')
            """
        )
        conn.execute(
            """
            INSERT INTO task_events (
                event_id, task_id, event_type, event_time, source, payload_json
            ) VALUES ('legacy-event', 'legacy-damaged', 'log',
                      '2026-01-01T00:00:30Z', 'worker', ?)
            """,
            (json.dumps({"message": "历史�损坏"}, ensure_ascii=False),),
        )
        conn.commit()

    repository = TaskRepository(db_path)
    migrated = repository.get("legacy-damaged")
    assert migrated is not None
    assert migrated.text_integrity == "historical_corrupted"
    assert migrated.text_integrity_reason == "legacy_task_before_text_schema_v2"
    assert migrated.producer_kind == "legacy"
    assert migrated.text_schema_version == 1

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE task_events SET payload_json = ? WHERE event_id = 'legacy-event'",
            (json.dumps({"message": "后来修改为正常文本"}, ensure_ascii=False),),
        )
        conn.commit()
    TaskRepository(db_path)
    assert repository.get("legacy-damaged").text_integrity == "historical_corrupted"


def test_current_agent_without_version_is_unknown_not_historical(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.create_external_task(
        task_id="agent-current-unknown",
        task_type="traffic_agent_iperf_client",
        task_name="Agent 当前任务",
        source="agent",
        agent="agent-1",
    )
    service.record_external_event(
        "agent-current-unknown",
        "state",
        {"state": TaskState.RUNNING.value},
        source="agent",
    )
    updated = service.record_external_event(
        "agent-current-unknown",
        "finished",
        {"result": {"summary": "Agent 返回�损坏"}},
        source="agent",
    )

    assert updated.status is TaskState.COMPLETED
    assert updated.text_integrity == "unknown_corrupted"
    assert updated.text_integrity_reason == "corrupted_text_producer_version_unknown"
    assert updated.producer_kind == "agent"
    assert updated.producer_version == "unknown"
    query = JobCenterQueryService(service.paths)
    listing = {item.id: item for item in query.list_tasks("demo")}
    detail = query.get_task("demo", "agent-current-unknown")
    assert detail is not None
    assert listing[detail.id].text_integrity == detail.text_integrity == "unknown_corrupted"


def test_known_current_agent_corruption_is_current(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.create_external_task(
        task_id="agent-current-known",
        task_type="traffic_agent_iperf_client",
        task_name="Agent 当前任务",
        source="agent",
        agent="agent-1",
        producer_version="v1.4.3",
        producer_commit="1" * 40,
        text_schema_version=2,
    )
    updated = service.record_external_event(
        "agent-current-known",
        "error",
        {"error": "Agent 当前�损坏"},
        source="agent",
    )

    assert updated.text_integrity == "current_corrupted"
    assert updated.text_integrity_reason == "replacement_character_detected_in_current_agent_event"


def test_task_list_does_not_scan_one_hundred_thousand_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _service(tmp_path)
    now = utc_now_iso()
    service.repository("demo").save(
        TaskSnapshot(
            task_id="large-history",
            task_type="demo_task",
            task_name="大事件历史",
            status=TaskState.COMPLETED,
            created_time=now,
            updated_time=now,
            site_name="demo",
            text_schema_version=2,
            producer_kind="local_backend",
        )
    )
    with sqlite3.connect(service.paths.site_tasks_db_path("demo")) as conn:
        conn.executemany(
            """
            INSERT INTO task_events (
                event_id, task_id, event_type, event_time, source, payload_json
            ) VALUES (?, 'large-history', 'log', ?, 'service', '{"message":"ok"}')
            """,
            ((f"event-{index}", now) for index in range(100_000)),
        )
        conn.commit()

    query = JobCenterQueryService(service.paths)
    statements: list[str] = []
    original_connect = query._connect

    def traced_connect(path: Path):
        connection = original_connect(path)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(query, "_connect", traced_connect)
    listing = query.list_tasks("demo")

    assert listing[0].id == "large-history"
    assert not any("task_events" in statement.casefold() for statement in statements)
    statements.clear()
    detail = query.get_task("demo", "large-history")
    assert detail is not None and detail.text_integrity == "ok"
    assert not any("instr(payload_json" in statement.casefold() for statement in statements)


def test_task_repository_handles_concurrent_event_writes(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.prepare(BackgroundJob(job_id="concurrent", task_type="demo_task"))

    def publish(index: int) -> None:
        service.events.publish(log_event("concurrent", f"日志 {index}"), source="test")

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(publish, range(40)))

    logs = [event for event in service.list_events("concurrent", limit=100) if event["type"] == "log"]
    assert len(logs) == 40


def test_orphaned_local_task_is_reconciled_as_failed(tmp_path: Path) -> None:
    repository = TaskRepository(PathResolver(tmp_path).site_tasks_db_path("demo"))
    now = utc_now_iso()
    repository.save(
        TaskSnapshot(
            task_id="orphan",
            task_type="demo_task",
            task_name="遗留任务",
            status=TaskState.RUNNING,
            created_time=now,
            updated_time=now,
            source="local",
            owner_pid=999999,
        )
    )

    changed = repository.reconcile_orphaned_local_tasks(lambda _pid: False)

    assert [item.task_id for item in changed] == ["orphan"]
    restored = repository.get("orphan")
    assert restored is not None and restored.status is TaskState.FAILED
    assert "非正常中断" in restored.error_message


def test_orphaned_local_export_reports_worker_runtime_lost(tmp_path: Path) -> None:
    repository = TaskRepository(PathResolver(tmp_path).site_tasks_db_path("demo"))
    now = utc_now_iso()
    repository.save(
        TaskSnapshot(
            task_id="orphan-template-export",
            task_type="web_export_device_template_csv",
            task_name="设备导入模板",
            status=TaskState.RUNNING,
            created_time=now,
            updated_time=now,
            source="local",
            owner_pid=999999,
        )
    )

    changed = repository.reconcile_orphaned_local_tasks(lambda _pid: False)

    assert [item.task_id for item in changed] == ["orphan-template-export"]
    restored = repository.get("orphan-template-export")
    assert restored is not None
    assert restored.status is TaskState.FAILED
    assert restored.finished_time
    assert restored.message == "导出任务执行进程已丢失，请重新导出"
    assert restored.error_message == "导出任务执行进程已丢失，请重新导出"
    assert restored.result["error_code"] == "WORKER_RUNTIME_LOST"


def test_task_restores_while_owner_process_is_alive(tmp_path: Path) -> None:
    first = _service(tmp_path)
    first.prepare(BackgroundJob(job_id="running", task_type="demo_task", params={"task_name": "运行任务"}))
    first.mark_running("running")

    restored = _service(tmp_path).get_task("running")

    assert restored is not None and restored.status is TaskState.RUNNING


def test_task_resource_keys_conflict_across_service_instances_and_release_after_terminal(tmp_path: Path) -> None:
    first = _service(tmp_path)
    second = TaskApplicationService(paths=first.paths, site_name="demo", reconcile_on_start=False)
    params = {"site_name": "demo", "resource_keys": ["site:demo|ac:ac-1|fit_ap_optical"]}

    first.prepare(BackgroundJob(job_id="optical-a", task_type="ac_fit_ap_optical_refresh", params=params))

    with pytest.raises(TaskResourceConflictError) as conflict:
        second.prepare(BackgroundJob(job_id="optical-b", task_type="trackside_ap_optical_update", params=params))
    assert conflict.value.task.task_id == "optical-a"

    first.mark_running("optical-a")
    first.feed_stdout(
        "optical-a",
        encode_event(finished_event("optical-a", {"success_count": 1})).encode("utf-8"),
    )
    first.complete("optical-a", 0)

    second.prepare(BackgroundJob(job_id="optical-c", task_type="trackside_ap_optical_update", params=params))
    restored = second.get_task("optical-c")
    assert restored is not None
    assert restored.resource_keys == ["site:demo|ac:ac-1|fit_ap_optical"]


def test_task_resource_keys_are_reserved_atomically_under_parallel_prepare(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path)
    paths.ensure_site_dirs("demo")
    outcomes: queue.Queue[tuple[str, str]] = queue.Queue()

    def prepare(index: int) -> None:
        service = TaskApplicationService(paths=paths, site_name="demo", reconcile_on_start=False)
        job_id = f"optical-race-{index}"
        try:
            service.prepare(
                BackgroundJob(
                    job_id=job_id,
                    task_type="ac_fit_ap_optical_refresh",
                    params={
                        "site_name": "demo",
                        "resource_keys": ["site:demo|ac:ac-1|fit_ap_optical"],
                    },
                )
            )
        except TaskResourceConflictError as exc:
            outcomes.put(("conflict", exc.task.task_id))
        else:
            outcomes.put(("ok", job_id))

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(prepare, range(8)))

    values = list(outcomes.queue)
    winners = [task_id for state, task_id in values if state == "ok"]
    conflicts = [task_id for state, task_id in values if state == "conflict"]
    assert len(winners) == 1
    assert len(conflicts) == 7
    assert set(conflicts) == set(winners)


def test_task_rest_api_lists_details_events_and_cancel(tmp_path: Path) -> None:
    service = _service(tmp_path)
    _complete_task(service)
    service.prepare(BackgroundJob(job_id="task-running", task_type="demo_task", params={"task_name": "运行任务"}))
    service.mark_running("task-running")
    app = _app_for_service(service, frontend_dist=tmp_path / "missing-dist")

    with TestClient(app) as client:
        listing = client.get("/api/tasks")
        detail = client.get("/api/tasks/task-complete")
        events = client.get("/api/tasks/task-complete/events")
        cancelled = client.post("/api/tasks/task-running/cancel")
        conflict = client.post("/api/tasks/task-complete/cancel")

    assert listing.status_code == 200
    assert {item["status"] for item in listing.json()} >= {"RUNNING", "COMPLETED"}
    assert detail.json()["name"] == "演示任务"
    assert events.status_code == 200 and events.json()
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "STOPPING"
    assert conflict.status_code == 409
    assert (service.paths.runtime_cache_dir / "background_jobs" / "task-running.cancel").exists()


def test_external_task_persists_before_broadcast_and_rejects_generic_cancel(tmp_path: Path) -> None:
    service = _service(tmp_path)
    observed: list[TaskState] = []

    def observe(event: dict[str, object]) -> None:
        task_id = str(event.get("task_id") or "")
        snapshot = service.get_task(task_id)
        if snapshot is not None:
            observed.append(snapshot.status)

    service.events.subscribe(observe)
    service.create_external_task(
        task_id="agent-traffic",
        task_type="traffic_agent_iperf_client",
        task_name="Agent iPerf 客户端",
        source="agent",
        agent="agent-1",
    )
    service.record_external_event(
        "agent-traffic",
        "state",
        {"state": TaskState.RUNNING.value, "message": "Agent 已开始执行"},
        source="agent",
    )

    assert observed[-1] is TaskState.RUNNING
    assert service.get_task("agent-traffic").owner_pid == 0
    assert service.cancel_task("agent-traffic") is False
    assert not (service.paths.runtime_cache_dir / "background_jobs" / "agent-traffic.cancel").exists()


@pytest.mark.parametrize("late_event", ["finished", "error"])
def test_cancelled_terminal_rejects_concurrent_late_completion(
    tmp_path: Path,
    monkeypatch,
    late_event: str,
) -> None:
    service = _service(tmp_path)
    task_id = f"device-export-late-{late_event}"
    service.create_external_task(
        task_id=task_id,
        task_type="device_export_device_csv",
        task_name="设备导出终态竞态",
        source="local",
        owner="device_export_process",
    )
    service.record_external_event(
        task_id,
        "state",
        {"state": TaskState.RUNNING.value},
    )
    repository = service.repository("demo")
    original_record = repository.record
    entered = threading.Event()
    release = threading.Event()

    def delay_late_record(snapshot, event, *, allowed_from=None):
        if event.type == late_event:
            entered.set()
            assert release.wait(2)
        return original_record(snapshot, event, allowed_from=allowed_from)

    monkeypatch.setattr(repository, "record", delay_late_record)
    failures: list[BaseException] = []

    def write_late_terminal() -> None:
        try:
            service.record_external_event(
                task_id,
                late_event,
                {"result": {"available": False}}
                if late_event == "finished"
                else {"error": "迟到失败"},
                event_id=f"late-{late_event}",
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            failures.append(exc)

    worker = threading.Thread(target=write_late_terminal)
    worker.start()
    try:
        assert entered.wait(2)
        cancelled = service.record_external_event(
            task_id,
            "cancelled",
            {"message": "导出任务已取消"},
        )
        assert cancelled.status is TaskState.CANCELLED
    finally:
        release.set()
        worker.join(2)

    assert not worker.is_alive()
    assert not failures
    persisted = repository.get(task_id)
    assert persisted is not None and persisted.status is TaskState.CANCELLED
    assert f"late-{late_event}" not in {
        event["id"] for event in repository.list_events(task_id)
    }


@pytest.mark.parametrize(
    ("late_event", "payload"),
    [
        ("finished", {"result": {"available": False}}),
        ("progress", {"current": 99, "total": 100}),
        ("log", {"message": "迟到日志"}),
    ],
)
def test_rejected_late_event_is_not_broadcast(
    tmp_path: Path,
    late_event: str,
    payload: dict[str, object],
) -> None:
    service = _service(tmp_path)
    task_id = "device-export-rejected-broadcast"
    service.create_external_task(
        task_id=task_id,
        task_type="device_export_device_csv",
        task_name="设备导出终态广播",
        source="local",
        owner="device_export_process",
    )
    service.record_external_event(
        task_id,
        "cancelled",
        {"message": "导出任务已取消"},
    )
    observed: list[dict[str, object]] = []
    service.events.subscribe(observed.append)
    stream = service.events.open_stream()
    try:
        service.events.publish(
            {
                "type": late_event,
                "job_id": task_id,
                **payload,
            },
            source="worker",
        )
        with pytest.raises(queue.Empty):
            stream.get(timeout=0.05)
    finally:
        stream.close()

    assert observed == []
    persisted = service.repository("demo").get(task_id)
    assert persisted is not None and persisted.status is TaskState.CANCELLED


@pytest.mark.parametrize(
    ("starting_status", "event_type", "payload", "expected"),
    [
        (TaskState.RUNNING, "finished", {"result": {}}, TaskState.COMPLETED),
        (TaskState.STOPPING, "error", {"error": "owner 失败"}, TaskState.FAILED),
        (TaskState.STOPPING, "cancelled", {"message": "owner 已取消"}, TaskState.CANCELLED),
    ],
)
def test_expected_state_cas_keeps_normal_external_owner_terminal_transitions(
    tmp_path: Path,
    starting_status: TaskState,
    event_type: str,
    payload: dict[str, object],
    expected: TaskState,
) -> None:
    service = _service(tmp_path)
    task_id = f"agent-owner-{starting_status.value.lower()}-{event_type}"
    service.create_external_task(
        task_id=task_id,
        task_type="traffic_agent_iperf_client",
        task_name="Agent owner 状态转换",
        source="agent",
        owner="controller",
    )
    service.record_external_event(
        task_id,
        "state",
        {"state": TaskState.RUNNING.value},
        source="agent",
    )
    if starting_status is TaskState.STOPPING:
        service.record_external_event(
            task_id,
            "state",
            {"state": TaskState.STOPPING.value},
            source="agent",
        )

    updated = service.record_external_event(
        task_id,
        event_type,
        payload,
        source="agent",
    )

    assert updated.status is expected
    persisted = service.repository("demo").get(task_id)
    assert persisted is not None and persisted.status is expected


def test_local_runtime_persists_result_before_single_terminal_state_event(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    task_id = "local-terminal-order"
    observed: list[dict[str, object]] = []
    service.events.subscribe(observed.append)
    service.prepare(
        BackgroundJob(job_id=task_id, task_type="demo_task", params={"task_name": "本地终态顺序"})
    )
    service.mark_running(task_id)
    service.feed_stdout(
        task_id,
        (json.dumps({"type": "finished", "job_id": task_id, "result": {"count": 1}}) + "\n").encode(),
    )

    service.complete(task_id, 0)

    terminal_states = [
        event
        for event in observed
        if event.get("type") == "state"
        and dict(event.get("payload") or {}).get("state") == TaskState.COMPLETED.value
    ]
    assert len(terminal_states) == 1
    persisted = service.get_task(task_id)
    assert persisted is not None
    assert persisted.status is TaskState.COMPLETED
    assert persisted.result == {"count": 1}
    event_types = [event["type"] for event in service.list_events(task_id)]
    assert event_types[-2:] == ["finished", "state"]


def test_local_runtime_honors_finished_terminal_state(tmp_path: Path) -> None:
    service = _service(tmp_path)
    task_id = "local-finished-failed"
    service.prepare(BackgroundJob(job_id=task_id, task_type="demo_task"))
    service.mark_running(task_id)
    service.feed_stdout(
        task_id,
        encode_event(
            finished_event(
                task_id,
                {"count": 1},
                terminal_state=TaskState.FAILED.value,
            )
        ).encode("utf-8"),
    )

    service.complete(task_id, 0)

    persisted = service.get_task(task_id)
    assert persisted is not None
    assert persisted.status is TaskState.FAILED
    assert persisted.result == {"count": 1}
    event_types = [event["type"] for event in service.list_events(task_id)]
    assert event_types[-2:] == ["finished", "state"]


def test_worker_read_only_task_service_does_not_reconcile_parent_owned_task(
    tmp_path: Path,
) -> None:
    owner = _service(tmp_path)
    task_id = "parent-owned-task"
    owner.prepare(BackgroundJob(job_id=task_id, task_type="demo_task"))
    owner.mark_running(task_id)

    worker = TaskApplicationService(
        paths=owner.paths,
        reconcile_on_start=False,
    )

    snapshot = worker.get_task(task_id)
    assert snapshot is not None
    assert snapshot.status is TaskState.RUNNING
    assert not any(event["source"] == "recovery" for event in worker.list_events(task_id))


def test_task_api_marks_external_task_not_cancellable(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.create_external_task(
        task_id="agent-traffic",
        task_type="traffic_agent_fping",
        task_name="Agent 高频 Ping",
        source="agent",
        agent="agent-1",
    )
    app = _app_for_service(service, frontend_dist=tmp_path / "missing-dist")

    with TestClient(app) as client:
        detail = client.get("/api/tasks/agent-traffic")
        cancelled = client.post("/api/tasks/agent-traffic/cancel")

    assert detail.status_code == 200
    assert detail.json()["cancellable"] is False
    assert cancelled.status_code == 409


def test_task_websocket_sends_snapshot_and_hub_event(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.prepare(BackgroundJob(job_id="socket-task", task_type="demo_task", params={"task_name": "Socket任务"}))
    app = _app_for_service(service, frontend_dist=tmp_path / "missing-dist")

    with TestClient(app) as client:
        with client.websocket_connect("/ws/tasks") as socket:
            snapshot = socket.receive_json()
            service.events.publish(log_event("socket-task", "实时日志"), source="test")
            event = socket.receive_json()

    assert snapshot["type"] == "snapshot"
    assert snapshot["payload"]["unicode_probe"] == "宁波地铁1号线 · 任务已完成"
    assert snapshot["payload"]["tasks"][0]["id"] == "socket-task"
    assert event["type"] == "log"
    assert event["payload"]["message"] == "实时日志"


def test_task_events_are_valid_utf8_json(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.prepare(BackgroundJob(job_id="utf8-task", task_type="demo_task", params={"task_name": "中文任务"}))
    service.events.publish(log_event("utf8-task", "中文日志"), source="test")

    payload = json.dumps(service.list_events("utf8-task"), ensure_ascii=False)
    assert "中文日志" in payload


def test_fastapi_serves_vue_spa_routes(tmp_path: Path) -> None:
    dist = tmp_path / "frontend" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text('<div id="app">NetConsole Web</div>', encoding="utf-8")
    service = _service(tmp_path)
    app = _app_for_service(service, frontend_dist=dist)

    with TestClient(app) as client:
        root = client.get("/")
        nested = client.get("/tasks")
        desktop_tasks = client.get("/desktop/tasks")
        health = client.get("/api/health")

    assert root.status_code == 200 and "NetConsole Web" in root.text
    assert nested.status_code == 200 and 'id="app"' in nested.text
    assert desktop_tasks.status_code == 200 and 'id="app"' in desktop_tasks.text
    assert health.status_code == 200
