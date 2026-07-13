from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from netconsole.core.paths import PathResolver
from netconsole.models.online_mr_application import (
    OnlineMrExecutorKind,
    OnlineMrMappingState,
    OnlineMrPhase,
    OnlineMrStartRequest,
    OnlineMrTaskSessionMapping,
)
from netconsole.models.online_mr_models import FpingConfig, OnlineMrConnectionConfig, OnlineMrTaskToggles
from netconsole.models.task_snapshot import utc_now_iso
from netconsole.repositories.online_mr_task_session_repository import OnlineMrTaskSessionRepository
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.online_mr.application_service import OnlineMrApplicationService
from netconsole.services.online_mr.errors import OnlineMrApplicationError, OnlineMrApplicationErrorCode


class FakeProcessAdapter:
    def __init__(self, task_service: TaskApplicationService, *, failure: str = "") -> None:
        self.task_service = task_service
        self.failure = failure
        self.jobs = []

    def start_job(self, job, *, on_complete=None) -> str:
        del on_complete
        self.jobs.append(job)
        if self.failure == "before_prepare":
            raise RuntimeError("create failed")
        launch = self.task_service.prepare(job)
        if self.failure == "after_prepare":
            self.task_service.fail_start(launch.job.job_id, "submit failed")
            raise RuntimeError("submit failed")
        self.task_service.mark_running(launch.job.job_id)
        return launch.job.job_id


def _paths(tmp_path: Path) -> PathResolver:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    paths.site_dir("site-a").mkdir(parents=True, exist_ok=True)
    paths.site_dir("site-b").mkdir(parents=True, exist_ok=True)
    return paths


def _config(site: str = "site-a") -> OnlineMrConnectionConfig:
    return OnlineMrConnectionConfig(
        site=site,
        mr_id="7",
        mr_name="MR-07",
        safe_mr_name="MR-07__7",
        device_id=7,
        device_name="列车07 MR",
        host="192.0.2.7",
        username="operator",
        password="secret-password",
        fping=FpingConfig(enabled=False),
        tasks=OnlineMrTaskToggles(
            mesh_link=False,
            channel_busy=False,
            ap_radio_statistics=False,
            switch_history=False,
            interface_rate=False,
            wireless_status=False,
        ),
    )


def _request(site: str = "site-a", *, executor: OnlineMrExecutorKind = OnlineMrExecutorKind.LOCAL) -> OnlineMrStartRequest:
    return OnlineMrStartRequest(
        site_id=site,
        device_id=7,
        device_name="列车07 MR",
        mr_name="MR-07",
        config=_config(site),
        executor_kind=executor,
        enabled_collectors=("terminal_monitor",),
    )


def _service(tmp_path: Path, *, failure: str = "") -> tuple[OnlineMrApplicationService, TaskApplicationService, FakeProcessAdapter]:
    paths = _paths(tmp_path)
    task_service = TaskApplicationService(paths, site_name="site-a")
    adapter = FakeProcessAdapter(task_service, failure=failure)
    service = OnlineMrApplicationService(
        paths,
        site_name="site-a",
        task_service=task_service,
        process_adapter=adapter,
        device_validator=lambda _site, device_id: str(device_id) == "7",
    )
    return service, task_service, adapter


def _mapping(task_id: str, *, site: str = "site-a", session_id: str | None = None) -> OnlineMrTaskSessionMapping:
    now = utc_now_iso()
    return OnlineMrTaskSessionMapping(
        controller_task_id=task_id,
        session_id=session_id,
        site_id=site,
        device_id="7",
        device_name="列车07 MR",
        mr_name="MR-07",
        executor_kind=OnlineMrExecutorKind.LOCAL,
        phase=OnlineMrPhase.PREPARING_SESSION,
        mapping_state=OnlineMrMappingState.LINKED if session_id else OnlineMrMappingState.PENDING_SESSION,
        created_at=now,
        updated_at=now,
    )


def _event(task_id: str, event_type: str, *, stage: str = "", details: dict[str, object] | None = None, error: str = "") -> dict[str, object]:
    return {
        "type": event_type,
        "task_id": task_id,
        "time": utc_now_iso(),
        "payload": {
            "type": event_type,
            "stage": stage,
            "message": json.dumps(details, ensure_ascii=False) if details is not None else error,
            "error": error,
        },
    }


def _session_dir(paths: PathResolver, session_id: str, *, site: str = "site-a", status: str = "COLLECTING") -> Path:
    path = paths.online_mr_session_dir(site, "MR-07__7", session_id)
    (path / "raw").mkdir(parents=True, exist_ok=True)
    (path / "raw" / "terminal_monitor_raw.log").write_text("raw evidence\n", encoding="utf-8")
    (path / "session_meta.json").write_text(
        json.dumps(
            {
                "session_id": session_id,
                "site": site,
                "device_id": 7,
                "device_name": "列车07 MR",
                "mr_name": "MR-07",
                "status": status,
                "started_at": "2026-07-13 10:00:00",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def test_mapping_repository_uses_tasks_db_and_is_idempotent(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    task_service = TaskApplicationService(paths, site_name="site-a")
    repository = OnlineMrTaskSessionRepository(paths.site_tasks_db_path("site-a"), site_id="site-a")
    repository.initialize()
    mapping = _mapping("task-1")
    repository.create(mapping)

    with repository._connect() as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        journal_mode = str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        busy_timeout = int(conn.execute("PRAGMA busy_timeout").fetchone()[0])
        foreign_keys = int(conn.execute("PRAGMA foreign_keys").fetchone()[0])

    assert task_service.repository("site-a").db_path == repository.db_path
    assert {"task_snapshots", "online_mr_task_sessions", "online_mr_task_session_schema"} <= tables
    assert repository.schema_version() == 1
    assert journal_mode == "wal"
    assert busy_timeout > 0
    assert foreign_keys == 1
    assert repository.get_by_task("task-1") == mapping


def test_mapping_repository_links_session_and_rejects_conflicts(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    repository = OnlineMrTaskSessionRepository(paths.site_tasks_db_path("site-a"), site_id="site-a")
    first = repository.create(_mapping("task-1"))
    linked = repository.save(replace(first, session_id="session-1", mapping_state=OnlineMrMappingState.LINKED))
    assert repository.get_by_session("session-1") == linked

    with pytest.raises(sqlite3.IntegrityError):
        repository.create(_mapping("task-1"))
    with pytest.raises(sqlite3.IntegrityError):
        repository.create(_mapping("task-2", session_id="session-1"))
    assert OnlineMrTaskSessionRepository(paths.site_tasks_db_path("site-b"), site_id="site-b").get_by_task("task-1") is None


def test_mapping_database_never_stores_credentials_or_arbitrary_config(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    repository = OnlineMrTaskSessionRepository(paths.site_tasks_db_path("site-a"), site_id="site-a")
    repository.create(_mapping("task-sensitive"))
    database_bytes = repository.db_path.read_bytes()
    assert b"secret-password" not in database_bytes
    with sqlite3.connect(repository.db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(online_mr_task_sessions)")}
    assert "password" not in columns
    assert "config" not in columns


def test_application_start_places_task_in_explicit_site_with_device_metadata(tmp_path: Path) -> None:
    service, task_service, adapter = _service(tmp_path)

    operation = service.start_local_collection(_request())

    assert operation.site_id == "site-a"
    assert operation.device_name == "列车07 MR"
    assert operation.phase == OnlineMrPhase.PREPARING_SESSION
    assert operation.task_status == "RUNNING"
    snapshot = task_service.repository("site-a").get(operation.controller_task_id)
    assert snapshot is not None
    assert snapshot.site_name == "site-a"
    assert snapshot.device == "列车07 MR"
    assert not service.paths.site_tasks_db_path("demo").exists()
    assert adapter.jobs[0].params["config"]["password"] == "secret-password"
    assert "secret-password" not in json.dumps(snapshot.result)
    assert "secret-password" not in json.dumps(operation.model_dump(mode="json"), ensure_ascii=False)


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        ("before_prepare", OnlineMrApplicationErrorCode.TASK_CREATE_FAILED),
        ("after_prepare", OnlineMrApplicationErrorCode.TASK_SUBMIT_FAILED),
    ],
)
def test_application_start_failure_closes_mapping(tmp_path: Path, failure: str, code: OnlineMrApplicationErrorCode) -> None:
    service, _task_service, _adapter = _service(tmp_path, failure=failure)
    with pytest.raises(OnlineMrApplicationError) as error:
        service.start_local_collection(_request())
    assert error.value.code == code
    mapping = service.repository("site-a").list(limit=1)[0]
    assert mapping.mapping_state == OnlineMrMappingState.TASK_ONLY_FAILED
    assert mapping.phase == OnlineMrPhase.TERMINAL
    assert mapping.session_id is None
    assert mapping.error_code == code


def test_agent_executor_is_explicitly_unsupported(tmp_path: Path) -> None:
    service, task_service, _adapter = _service(tmp_path)
    with pytest.raises(OnlineMrApplicationError) as error:
        service.start_local_collection(_request(executor=OnlineMrExecutorKind.AGENT))
    assert error.value.code == OnlineMrApplicationErrorCode.EXECUTOR_UNSUPPORTED


def test_structured_session_and_started_events_are_idempotent(tmp_path: Path) -> None:
    service, _task_service, _adapter = _service(tmp_path)
    operation = service.start_local_collection(_request())
    details = {
        "controller_task_id": operation.controller_task_id,
        "session_id": "session-1",
        "site_id": "site-a",
        "device_id": 7,
        "mr_name": "MR-07",
    }

    service.reconcile_task_event(_event(operation.controller_task_id, "progress", stage="online_mr_session_created", details=details))
    linked = service.get_operation(operation.controller_task_id, site_id="site-a")
    assert linked.session_id == "session-1"
    assert linked.phase == OnlineMrPhase.CONNECTING
    assert linked.mapping_state == OnlineMrMappingState.LINKED

    started = _event(operation.controller_task_id, "progress", stage="online_mr_started", details=details)
    service.reconcile_task_event(started)
    service.reconcile_task_event(started)
    assert service.get_operation_by_session("session-1", site_id="site-a").phase == OnlineMrPhase.COLLECTING


def test_out_of_order_and_unknown_events_do_not_revive_terminal_mapping(tmp_path: Path) -> None:
    service, _task_service, _adapter = _service(tmp_path)
    operation = service.start_local_collection(_request())
    service.reconcile_task_event(_event(operation.controller_task_id, "log", stage="config_warning", details={"warning": True}))
    assert service.get_operation(operation.controller_task_id, site_id="site-a").phase == OnlineMrPhase.PREPARING_SESSION
    service.reconcile_task_event(_event(operation.controller_task_id, "cancelled", error="cancelled"))
    terminal = service.get_operation(operation.controller_task_id, site_id="site-a")
    service.reconcile_task_event(
        _event(
            operation.controller_task_id,
            "progress",
            stage="online_mr_started",
            details={"session_id": "late-session", "site_id": "site-a", "device_id": 7},
        )
    )
    assert service.get_operation(operation.controller_task_id, site_id="site-a") == terminal


def test_finished_event_sets_terminal_without_changing_stop_or_packaging(tmp_path: Path) -> None:
    service, task_service, _adapter = _service(tmp_path)
    operation = service.start_local_collection(_request())
    task_service.events.publish(
        {
            "type": "finished",
            "job_id": operation.controller_task_id,
            "result": {"status": "STOPPED", "session_id": "session-1"},
        }
    )
    terminal = service.get_operation(operation.controller_task_id, site_id="site-a")
    assert terminal.phase == OnlineMrPhase.TERMINAL
    assert terminal.mapping_state == OnlineMrMappingState.TERMINAL
    assert terminal.task_status == "COMPLETED"


def test_startup_failure_after_session_keeps_raw_and_aligns_failed_status(tmp_path: Path) -> None:
    service, _task_service, _adapter = _service(tmp_path)
    operation = service.start_local_collection(_request())
    session_dir = _session_dir(service.paths, "session-failed", status="STOPPED")
    details = {
        "controller_task_id": operation.controller_task_id,
        "session_id": "session-failed",
        "site_id": "site-a",
        "device_id": 7,
    }
    service.reconcile_task_event(_event(operation.controller_task_id, "progress", stage="online_mr_session_created", details=details))
    service.reconcile_task_event(_event(operation.controller_task_id, "error", error="SSH connection failed"))

    failed = service.get_operation(operation.controller_task_id, site_id="site-a")
    meta = json.loads((session_dir / "session_meta.json").read_text(encoding="utf-8"))
    assert failed.mapping_state == OnlineMrMappingState.TERMINAL
    assert failed.error_code == OnlineMrApplicationErrorCode.STARTUP_CONNECTION_FAILED
    assert meta["status"] == "FAILED"
    assert meta["error_code"] == OnlineMrApplicationErrorCode.STARTUP_CONNECTION_FAILED
    assert (session_dir / "raw" / "terminal_monitor_raw.log").read_text(encoding="utf-8") == "raw evidence\n"


def test_recover_mappings_aborts_stale_sessions_without_parsing_or_deleting_raw(tmp_path: Path) -> None:
    service, task_service, _adapter = _service(tmp_path)
    stale_with_task = _session_dir(service.paths, "session-linked", status="FINALIZING")
    task_service.create_external_task(
        task_id="task-linked",
        task_type="online_mr_collection_start",
        task_name="Online MR",
        source="local",
        site_name="site-a",
        device="列车07 MR",
    )
    task_service.record_external_event("task-linked", "error", {"error": "host exited"}, site_name="site-a")
    service.repository("site-a").create(_mapping("task-linked", session_id="session-linked"))
    stale_without_task = _session_dir(service.paths, "session-recovered", status="PACKAGING")
    _session_dir(service.paths, "session-complete", status="STOPPED")
    broken = service.paths.online_mr_session_dir("site-a", "MR-07__7", "broken")
    broken.mkdir(parents=True)
    (broken / "session_meta.json").write_text("{", encoding="utf-8")

    changed = service.recover_mappings(site_id="site-a")

    assert {row.session_id for row in changed} == {"session-linked", "session-recovered"}
    linked = service.get_operation_by_session("session-linked", site_id="site-a")
    recovered = service.get_operation_by_session("session-recovered", site_id="site-a")
    assert linked.mapping_state == OnlineMrMappingState.TERMINAL
    assert recovered.mapping_state == OnlineMrMappingState.SESSION_ONLY_RECOVERED
    for session_dir in (stale_with_task, stale_without_task):
        meta = json.loads((session_dir / "session_meta.json").read_text(encoding="utf-8"))
        assert meta["status"] == "ABORTED"
        assert (session_dir / "raw" / "terminal_monitor_raw.log").exists()
        assert not (session_dir / "outputs").exists()


@pytest.mark.parametrize("status", ["CONNECTING", "COLLECTING", "STOPPING", "FINALIZING", "PACKAGING"])
def test_recovery_recognizes_all_frozen_stale_phases(tmp_path: Path, status: str) -> None:
    service, _task_service, _adapter = _service(tmp_path)
    session_id = f"stale-{status.lower()}"
    session_dir = _session_dir(service.paths, session_id, status=status)
    changed = service.recover_mappings(site_id="site-a")
    assert [row.session_id for row in changed] == [session_id]
    meta = json.loads((session_dir / "session_meta.json").read_text(encoding="utf-8"))
    assert meta["status"] == "ABORTED"
    assert meta["recovery_previous_status"] == status


def test_recovery_does_not_abort_current_active_task_or_repeat_terminal_mapping(tmp_path: Path) -> None:
    service, task_service, _adapter = _service(tmp_path)
    operation = service.start_local_collection(_request())
    session_dir = _session_dir(service.paths, "session-live", status="CONNECTING")
    mapping = service.repository("site-a").get_by_task(operation.controller_task_id)
    assert mapping is not None
    service.repository("site-a").save(
        replace(mapping, session_id="session-live", mapping_state=OnlineMrMappingState.LINKED)
    )
    assert service.recover_mappings(site_id="site-a") == []
    assert json.loads((session_dir / "session_meta.json").read_text(encoding="utf-8"))["status"] == "CONNECTING"

    task_service.events.publish(
        {"type": "cancelled", "job_id": operation.controller_task_id, "message": "cancelled", "error": "cancelled"}
    )
    before = service.get_operation(operation.controller_task_id, site_id="site-a")
    service.recover_mappings(site_id="site-a")
    after = service.get_operation(operation.controller_task_id, site_id="site-a")
    assert after == before
    assert json.loads((session_dir / "session_meta.json").read_text(encoding="utf-8"))["status"] == "ABORTED"


def test_application_boundary_has_no_qt_fastapi_or_worker_imports() -> None:
    source = Path("src/netconsole/services/online_mr/application_service.py").read_text(encoding="utf-8")
    repository_source = Path("src/netconsole/repositories/online_mr_task_session_repository.py").read_text(encoding="utf-8")
    assert "PySide6" not in source + repository_source
    assert "FastAPI" not in source
    assert "online_mr_collector_worker" not in source
