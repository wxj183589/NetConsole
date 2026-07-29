from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import threading

from fastapi.testclient import TestClient
import pytest

from netconsole.backend.api.main import create_app
from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.models.online_mr_application import (
    OnlineMrExecutorKind,
    OnlineMrMappingState,
    OnlineMrPhase,
    OnlineMrTaskSessionMapping,
)
from netconsole.models.task_snapshot import TaskEvent, TaskSnapshot
from netconsole.models.task_state import TaskState
from netconsole.repositories.online_mr_task_session_repository import (
    OnlineMrTaskSessionRepository,
)
from netconsole.repositories.task_repository import TaskRepository
from netconsole.services.background_job import BackgroundJob
from netconsole.services.config_collection_job_handlers import _artifact_target
from netconsole.services.export.export_job import ExportJob
from netconsole.services.file_management_service import (
    FileManagementApplicationService,
    run_file_management_download,
)
from netconsole.services.job_center.job_context import JobContext
from netconsole.services.job_center.query_service import JobCenterQueryService
from netconsole.services.job_center.task_application_service import (
    TaskApplicationService,
)
from netconsole.services.job_center.web_export_event_safety import redact_web_task_text


def _sqlite_snapshot(path: Path) -> tuple[str, ...]:
    uri = f"{path.resolve().as_uri()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        conn.execute("PRAGMA query_only = ON")
        return tuple(conn.iterdump())


def _text_values(value: object) -> list[str]:
    if isinstance(value, dict):
        return [text for item in value.values() for text in _text_values(item)]
    if isinstance(value, list):
        return [text for item in value for text in _text_values(item)]
    return [value] if isinstance(value, str) else []


def test_job_center_point_table_generate_details_are_whitelisted() -> None:
    details = JobCenterQueryService._task_details(
        "car_network_generate_point_table",
        {},
        {
            "nodes": [{"node_name": "TC1-MR", "password": "must-not-leak"}],
            "nodes_count": 6,
            "generated_nodes_count": 6,
            "target_train": "train:01",
            "target_train_display": "列车01",
            "preview_status": "PENDING_SAVE",
            "preview_message": "已生成点表预览，等待用户保存",
        },
    )

    assert details == {
        "nodes_count": 6,
        "generated_nodes_count": 6,
        "target_train": "train:01",
        "target_train_display": "列车01",
        "preview_status": "PENDING_SAVE",
        "preview_message": "已生成点表预览，等待用户保存",
    }


class _FakeExportProcess:
    stdout = None

    def __init__(
        self, poll_values: tuple[int | None, ...] = (None,), on_poll=None
    ) -> None:
        self._poll_values = poll_values
        self._on_poll = on_poll
        self._poll_count = 0
        self.returncode: int | None = None

    def poll(self) -> int | None:
        self._poll_count += 1
        if self._on_poll is not None:
            self._on_poll(self._poll_count)
        if self.returncode is not None:
            return self.returncode
        value = self._poll_values[min(self._poll_count - 1, len(self._poll_values) - 1)]
        if value is not None:
            self.returncode = value
        return value

    def terminate(self) -> None:
        self.returncode = -15

    def kill(self) -> None:
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        _ = timeout
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


class _NoopThread:
    def __init__(self, *args, **kwargs) -> None:
        _ = (args, kwargs)

    def start(self) -> None:
        return None


class _OwnerCancelAdapter:
    def __init__(
        self, task_service: TaskApplicationService, *, site_name: str, accept: bool
    ) -> None:
        self.task_service = task_service
        self.site_name = site_name
        self.accept = accept
        self.calls: list[str] = []

    def cancel_job(self, task_id: str) -> bool:
        self.calls.append(task_id)
        if not self.accept:
            return False
        self.task_service.record_external_event(
            task_id,
            "state",
            {
                "state": TaskState.STOPPING.value,
                "message": "owner accepted cancellation",
            },
            site_name=self.site_name,
        )
        return True

    def is_running(self, task_id: str) -> bool:
        return bool(task_id)


def _install_device_export(
    app,
    db_path: Path,
    *,
    task_id: str = "device-export-running",
    process: _FakeExportProcess | None = None,
    install_spec: bool = True,
    install_process: bool = True,
) -> tuple[Path, _FakeExportProcess]:
    repository = TaskRepository(db_path)
    repository.save(
        TaskSnapshot(
            task_id=task_id,
            task_type="device_export_device_csv",
            task_name="设备导出",
            status=TaskState.RUNNING,
            created_time="2026-07-14T09:00:00Z",
            updated_time="2026-07-14T09:00:01Z",
            owner="web_device_management",
            source="local",
            site_name="demo",
        )
    )
    service = app.state.device_management_service
    job_dir = service.paths.runtime_cache_dir / "export_jobs"
    job_dir.mkdir(parents=True, exist_ok=True)
    cancel_path = job_dir / f"{task_id}.cancel"
    job_path = job_dir / f"{task_id}.json"
    target = service._artifact_root("demo") / "device-production.csv"
    job = ExportJob(
        job_id=task_id,
        job_type="device_csv",
        site_name="demo",
        output_path=str(target),
        db_path=str(service.paths.site_db_path("demo")),
    ).with_runtime_paths(
        tmp_path=str(target.with_suffix(".tmp")), cancel_path=str(cancel_path)
    )
    job_path.write_text(json.dumps(job.to_dict(), ensure_ascii=False), encoding="utf-8")
    if install_spec:
        service._export_artifacts[task_id] = {
            "task_id": task_id,
            "site": "demo",
            "artifact_id": "device-artifact",
            "job_path": job_path,
            "cancel_path": cancel_path,
            "target": target,
        }
    selected_process = process or _FakeExportProcess()
    if install_process:
        service._export_processes[task_id] = selected_process
    return cancel_path, selected_process


def _app_with_tasks(tmp_path: Path):
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    Database(paths.site_db_path("demo")).initialize()
    db_path = paths.site_tasks_db_path("demo")
    repository = TaskRepository(db_path)
    repository.record(
        TaskSnapshot(
            task_id="online-mr-task",
            task_type="online_mr_collection_start",
            task_name="车载 MR 在线收集",
            status=TaskState.COMPLETED,
            created_time="2026-07-14T08:00:00Z",
            started_time="2026-07-14T08:00:01Z",
            finished_time="2026-07-14T08:02:01Z",
            updated_time="2026-07-14T08:02:01Z",
            progress=100,
            owner="legacy_qt",
            device="列车12-MR-CT",
            source="external",
            site_name="demo",
            result={
                "session_id": "session-12",
                "session_dir": "online_mr/MR-12/sessions/session-12",
                "package_path": "online_mr/MR-12/sessions/session-12/outputs/session-12.zip",
                "password": "must-not-leak",
            },
        ),
        TaskEvent(
            event_id="event-1",
            task_id="online-mr-task",
            type="log",
            time="2026-07-14T08:01:00Z",
            source="worker",
            payload={"message": "采集运行中", "password": "must-not-leak"},
        ),
    )
    repository.record(
        repository.get("online-mr-task"),
        TaskEvent(
            event_id="event-paths",
            task_id="online-mr-task",
            type="error",
            time="2026-07-14T08:01:01Z",
            source="worker",
            payload={
                "traceback": "failed at C:\\private\\worker.py and \\\\server\\share\\secret.log"
            },
        ),
    )
    repository.save(
        TaskSnapshot(
            task_id="quiet-task",
            task_type="demo_task",
            task_name="无日志任务",
            status=TaskState.FAILED,
            created_time="2026-07-14T07:00:00Z",
            finished_time="2026-07-14T07:00:01Z",
            updated_time="2026-07-14T07:00:01Z",
            error_message="测试失败摘要",
            site_name="demo",
        )
    )
    OnlineMrTaskSessionRepository(db_path, site_id="demo").create(
        OnlineMrTaskSessionMapping(
            controller_task_id="online-mr-task",
            session_id="session-12",
            site_id="demo",
            device_id="12",
            device_name="列车12-MR-CT",
            mr_id="mr-12",
            mr_name="MR-12",
            executor_kind=OnlineMrExecutorKind.AGENT,
            phase=OnlineMrPhase.TERMINAL,
            mapping_state=OnlineMrMappingState.TERMINAL,
            created_at="2026-07-14T08:00:00Z",
            updated_at="2026-07-14T08:02:01Z",
            error_summary="Agent 包设备身份已按本地映射",
            error_code="IDENTITY_OVERRIDDEN",
        )
    )
    service = TaskApplicationService(paths=paths, site_name="demo")
    return create_app(
        RuntimeMode.SERVER,
        paths=paths,
        task_service=service,
        frontend_dist=tmp_path / "missing",
    ), db_path


def test_job_center_get_api_is_read_only_and_returns_associations(
    tmp_path: Path,
) -> None:
    app, db_path = _app_with_tasks(tmp_path)

    with TestClient(app) as client:
        before = _sqlite_snapshot(db_path)
        listing = client.get("/api/job-center/tasks")
        detail = client.get("/api/job-center/tasks/online-mr-task")
        logs = client.get("/api/job-center/tasks/online-mr-task/logs?tail=300")
        summary = client.get("/api/job-center/summary")
        after = _sqlite_snapshot(db_path)

    assert listing.status_code == 200
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["session_id"] == "session-12"
    assert payload["executor"] == "AGENT"
    assert payload["device_id"] == "12"
    assert payload["error_summary"] == "Agent 包设备身份已按本地映射"
    assert payload["has_warning"] is True
    assert "package_path" not in payload
    assert payload["cancellable"] is False
    assert payload["retryable"] is False
    assert payload["artifact_download"] is None
    assert "result" not in payload
    assert "must-not-leak" not in detail.text
    assert logs.status_code == 200
    assert logs.json()["lines"][0]["message"] == "采集运行中"
    assert (
        logs.json()["lines"][1]["message"]
        == "failed at <redacted-path> and <redacted-path>"
    )
    assert "C:\\private" not in logs.text
    assert "server\\share" not in logs.text
    assert "must-not-leak" not in logs.text
    assert summary.json() == {
        "total": 2,
        "active": 0,
        "completed": 1,
        "failed": 1,
        "warning": 1,
        "unacknowledged_failed": 1,
        "unacknowledged_warning": 1,
    }
    assert after == before


def test_job_center_logs_missing_and_unknown_task_are_explicit(tmp_path: Path) -> None:
    app, _db_path = _app_with_tasks(tmp_path)

    with TestClient(app) as client:
        empty_logs = client.get("/api/job-center/tasks/quiet-task/logs")
        missing = client.get("/api/job-center/tasks/not-found")

    assert empty_logs.status_code == 200
    assert empty_logs.json() == {
        "task_id": "quiet-task",
        "lines": [],
        "message": "暂无日志",
    }
    assert missing.status_code == 404
    assert missing.json()["detail"] == "任务不存在"


def test_job_center_redacts_all_renderer_visible_task_text(tmp_path: Path) -> None:
    app, db_path = _app_with_tasks(tmp_path)
    TaskRepository(db_path).save(
        TaskSnapshot(
            task_id="renderer-path-task",
            task_type="demo_task",
            task_name=r"任务 C:\private\task.json",
            status=TaskState.FAILED,
            created_time="2026-07-14T07:00:00Z",
            finished_time="2026-07-14T07:00:01Z",
            updated_time="2026-07-14T07:00:01Z",
            stage=r"stage \\server\share\stage.log",
            message=r"message C:\private\message.log",
            device=r"device \\server\share\device.cfg",
            agent=r"agent C:\private\agent.json",
            error_message=r"error \\server\share\error.txt",
            source=r"worker C:\private\source.exe",
            result={
                "session_id": r"C:\private\session",
                "executor_kind": r"\\server\share\executor",
                "error_code": r"C:\private\error.code",
                "parser_version": r"\\server\share\parser.json",
            },
            site_name="demo",
        )
    )

    with TestClient(app) as client:
        response = client.get("/api/job-center/tasks/renderer-path-task")

    assert response.status_code == 200
    payload = response.json()
    for field in (
        "name",
        "phase",
        "stage",
        "message",
        "device_name",
        "agent",
        "session_id",
        "executor",
        "error_code",
        "error_summary",
        "parser_version",
        "source",
    ):
        assert "redacted-path" in payload[field].casefold()
    renderer_text = "\n".join(_text_values(payload))
    assert "C:\\" not in renderer_text
    assert r"\\server" not in renderer_text


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("message", {"nested": {"path": r"C:\private\nested.log"}}),
        ("error", r"failed at C:\private\error.log"),
        ("traceback", r"trace at \\server\share\traceback.py"),
        ("diagnostic", {"detail": r"\\server\share\diagnostic.json"}),
        ("state", r"state C:\private\state.txt"),
        ("stage", r"stage \\server\share\stage.txt"),
    ],
)
def test_job_center_redacts_nested_and_direct_log_paths(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    app, db_path = _app_with_tasks(tmp_path)
    repository = TaskRepository(db_path)
    repository.record(
        repository.get("quiet-task"),
        TaskEvent(
            event_id=f"event-{field}",
            task_id="quiet-task",
            type="error" if field in {"error", "traceback"} else "log",
            time="2026-07-14T07:00:00Z",
            source=r"worker C:\private\worker.exe",
            payload={field: value},
        ),
    )

    with TestClient(app) as client:
        response = client.get("/api/job-center/tasks/quiet-task/logs")

    assert response.status_code == 200
    renderer_text = "\n".join(_text_values(response.json()))
    assert "redacted-path" in renderer_text.casefold()
    assert "C:\\" not in renderer_text
    assert r"\\server" not in renderer_text


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (
            r"读取 C:\Program Files\NetConsole\secret.log 完成 42 条记录",
            "读取 <redacted-path> 完成 42 条记录",
        ),
        (
            r"路径 C:\采集 结果\设备 一\秘密 日志.txt，业务 ID device-42",
            "路径 <redacted-path>，业务 ID device-42",
        ),
        (
            r"UNC \\server\share\中文 空格\secret.log 已归档",
            "UNC <redacted-path> 已归档",
        ),
        (
            r"C:\Program Files\NetConsole",
            "<redacted-path>",
        ),
        (
            r"\\server\share\中文 空格",
            "<redacted-path>",
        ),
        (
            r"""引号 "C:\Program Files\NetConsole\secret.log" 和 '\\server\share\raw data.log' 完成""",
            "引号 <redacted-path> 和 <redacted-path> 完成",
        ),
        (
            r"复制 C:\first path\a.log 到 \\server\share\second path\b.log，时间 2026-07-17T01:02:03Z",
            "复制 <redacted-path> 到 <redacted-path>，时间 2026-07-17T01:02:03Z",
        ),
    ],
)
def test_redact_web_task_text_handles_complete_spaced_paths(
    message: str,
    expected: str,
) -> None:
    assert redact_web_task_text(message) == expected


def test_job_center_path_redaction_preserves_business_text(tmp_path: Path) -> None:
    app, db_path = _app_with_tasks(tmp_path)
    repository = TaskRepository(db_path)
    message = (
        r"业务 ID task-42 读取 C:\Program Files\NetConsole\secret.log 完成 "
        r"42 条记录，时间 2026-07-17T01:02:03Z；中文 C:\采集 结果\设备 一\日志.txt 已归档；"
        r"""UNC "\\server\share\raw data.log" 已上传；多路径 C:\first path\a.log 到 \\server\share\second path\b.log 完成"""
    )
    repository.record(
        repository.get("quiet-task"),
        TaskEvent(
            event_id="event-preserve-business-text",
            task_id="quiet-task",
            type="log",
            time="2026-07-17T01:02:03Z",
            source="worker",
            payload={"message": message},
        ),
    )

    with TestClient(app) as client:
        response = client.get("/api/job-center/tasks/quiet-task/logs")

    text = response.json()["lines"][-1]["message"]
    assert text.count("<redacted-path>") == 5
    assert "业务 ID task-42" in text
    assert "42 条记录" in text
    assert "2026-07-17T01:02:03Z" in text
    assert "已归档" in text
    assert "已上传" in text
    assert "C:\\" not in text
    assert r"\\server" not in text


def test_task_source_write_boundary_rejects_uncontrolled_value(tmp_path: Path) -> None:
    service = TaskApplicationService(paths=PathResolver(tmp_path), site_name="demo")

    with pytest.raises(ValueError, match="source"):
        service.prepare(
            BackgroundJob(
                job_id="invalid-source",
                task_type="demo_task",
                params={"site_name": "demo", "task_source": r"C:\private\worker.exe"},
            )
        )

    assert service.repository("demo").get("invalid-source") is None


def test_job_center_rejects_cancel_without_owner_capability(tmp_path: Path) -> None:
    app, _db_path = _app_with_tasks(tmp_path)

    with TestClient(app) as client:
        response = client.post("/api/job-center/tasks/online-mr-task/cancel")

    assert response.status_code == 409


def test_job_center_routes_device_export_cancel_to_real_owner(
    tmp_path: Path, monkeypatch
) -> None:
    app, db_path = _app_with_tasks(tmp_path)
    cancel_path, _process = _install_device_export(app, db_path)
    monkeypatch.setattr(
        "netconsole.services.device_management_web_service.threading",
        SimpleNamespace(Thread=_NoopThread, Event=threading.Event),
    )

    with TestClient(app) as client:
        response = client.post("/api/job-center/tasks/device-export-running/cancel")
        persisted = TaskRepository(db_path).get("device-export-running")

    assert response.status_code == 200
    assert response.json()["status"] == "STOPPING"
    assert persisted is not None and persisted.status is TaskState.STOPPING
    assert cancel_path.read_text(encoding="utf-8") == "cancelled"
    assert not (
        app.state.task_service.paths.runtime_cache_dir
        / "background_jobs"
        / "device-export-running.cancel"
    ).exists()


def test_job_center_routes_ac_cancel_to_real_owner(tmp_path: Path) -> None:
    app, db_path = _app_with_tasks(tmp_path)
    TaskRepository(db_path).save(
        TaskSnapshot(
            task_id="ac-refresh-running",
            task_type="ac_fit_ap_resources_refresh",
            task_name="更新 FIT-AP 资源",
            status=TaskState.RUNNING,
            created_time="2026-07-17T09:00:00Z",
            updated_time="2026-07-17T09:00:01Z",
            owner="web_ac",
            source="local",
            site_name="demo",
        )
    )
    calls: list[tuple[str, str]] = []

    def cancel_task(site_id: str, task_id: str) -> None:
        calls.append((site_id, task_id))
        app.state.task_service.record_external_event(
            task_id,
            "state",
            {
                "state": TaskState.STOPPING.value,
                "message": "AC owner accepted cancellation",
            },
            site_name=site_id,
        )

    app.state.ac_web_application_service = SimpleNamespace(cancel_task=cancel_task)

    with TestClient(app) as client:
        detail = client.get("/api/job-center/tasks/ac-refresh-running")
        response = client.post("/api/job-center/tasks/ac-refresh-running/cancel")

    assert detail.status_code == 200
    assert detail.json()["module"] == "ac"
    assert detail.json()["cancellable"] is True
    assert response.status_code == 200
    assert response.json()["status"] == "STOPPING"
    assert calls == [("demo", "ac-refresh-running")]


def test_job_center_routes_rail_cancel_to_real_owner(tmp_path: Path) -> None:
    app, db_path = _app_with_tasks(tmp_path)
    TaskRepository(db_path).save(
        TaskSnapshot(
            task_id="rail-parse-running",
            task_type="online_mr_parse",
            task_name="Online MR 会话解析",
            status=TaskState.RUNNING,
            created_time="2026-07-17T09:00:00Z",
            updated_time="2026-07-17T09:00:01Z",
            owner="web_rail_transit",
            source="local",
            site_name="demo",
        )
    )
    calls: list[tuple[str, str]] = []

    def cancel_task(site_id: str, task_id: str) -> None:
        calls.append((site_id, task_id))
        app.state.task_service.record_external_event(
            task_id,
            "state",
            {"state": TaskState.STOPPING.value, "message": "轨交 owner 已接收停止请求"},
            site_name=site_id,
        )

    app.state.rail_transit_web_application_service = SimpleNamespace(
        cancel_task=cancel_task
    )

    with TestClient(app) as client:
        detail = client.get("/api/job-center/tasks/rail-parse-running")
        response = client.post("/api/job-center/tasks/rail-parse-running/cancel")

    assert detail.status_code == 200
    assert detail.json()["module"] == "rail"
    assert detail.json()["cancellable"] is True
    assert response.status_code == 200
    assert response.json()["status"] == "STOPPING"
    assert calls == [("demo", "rail-parse-running")]


@pytest.mark.parametrize(
    ("owner", "task_type", "module", "service_name", "method_name", "expects_site"),
    [
        (
            "web_network_tools",
            "network_tools.continuous_ping",
            "network",
            "network_tools_service",
            "cancel_network_task",
            False,
        ),
        (
            "web_command_reference",
            "web_export_command_reference_markdown",
            "command-reference",
            "command_reference_application_service",
            "cancel_task",
            False,
        ),
        (
            "web_system_maintenance",
            "system_maintenance_cleanup",
            "logs",
            "system_maintenance_service",
            "cancel_task",
            True,
        ),
    ],
)
def test_job_center_routes_wave2_cancel_to_real_owner(
    tmp_path: Path,
    owner: str,
    task_type: str,
    module: str,
    service_name: str,
    method_name: str,
    expects_site: bool,
) -> None:
    app, db_path = _app_with_tasks(tmp_path)
    task_id = f"{module}-running"
    TaskRepository(db_path).save(
        TaskSnapshot(
            task_id=task_id,
            task_type=task_type,
            task_name=f"{module} running",
            status=TaskState.RUNNING,
            created_time="2026-07-17T09:00:00Z",
            updated_time="2026-07-17T09:00:01Z",
            owner=owner,
            source="local",
            site_name="demo",
        )
    )
    calls: list[tuple[object, ...]] = []

    def cancel(*args: object) -> None:
        calls.append(args)
        app.state.task_service.record_external_event(
            task_id,
            "state",
            {
                "state": TaskState.STOPPING.value,
                "message": "owner accepted cancellation",
            },
            site_name="demo",
        )

    setattr(app.state, service_name, SimpleNamespace(**{method_name: cancel}))

    with TestClient(app) as client:
        detail = client.get(f"/api/job-center/tasks/{task_id}")
        response = client.post(f"/api/job-center/tasks/{task_id}/cancel")

    assert detail.status_code == 200
    assert detail.json()["module"] == module
    assert detail.json()["cancellable"] is True
    assert response.status_code == 200
    assert response.json()["status"] == "STOPPING"
    expected_calls = [("demo", task_id)] if expects_site else [(task_id,)]
    assert calls == expected_calls


@pytest.mark.parametrize(
    "task_type", ["traffic_local_fping", "traffic_agent_iperf_client"]
)
def test_job_center_routes_traffic_controller_cancel_to_real_service(
    tmp_path: Path,
    task_type: str,
) -> None:
    app, db_path = _app_with_tasks(tmp_path)
    task_id = f"{task_type}-running"
    source = "agent" if task_type.startswith("traffic_agent_") else "local"
    TaskRepository(db_path).save(
        TaskSnapshot(
            task_id=task_id,
            task_type=task_type,
            task_name="Traffic running",
            status=TaskState.RUNNING,
            created_time="2026-07-17T09:00:00Z",
            updated_time="2026-07-17T09:00:01Z",
            owner="controller",
            source=source,
            site_name="demo",
        )
    )
    calls: list[str] = []

    async def cancel_controller_task(controller_task_id: str) -> None:
        calls.append(controller_task_id)
        app.state.task_service.record_external_event(
            controller_task_id,
            "state",
            {
                "state": TaskState.STOPPING.value,
                "message": "Traffic accepted cancellation",
            },
            site_name="demo",
        )

    app.state.traffic_web_application_service = SimpleNamespace(
        cancel_controller_task=cancel_controller_task
    )

    with TestClient(app) as client:
        detail = client.get(f"/api/job-center/tasks/{task_id}")
        response = client.post(f"/api/job-center/tasks/{task_id}/cancel")

    assert detail.status_code == 200
    assert detail.json()["module"] == "network"
    assert detail.json()["cancellable"] is True
    assert response.status_code == 200
    assert response.json()["status"] == "STOPPING"
    assert calls == [task_id]


def test_job_center_does_not_treat_unrelated_controller_task_as_network(
    tmp_path: Path,
) -> None:
    app, db_path = _app_with_tasks(tmp_path)
    TaskRepository(db_path).save(
        TaskSnapshot(
            task_id="online-mr-controller-task",
            task_type="online_mr_collection_start",
            task_name="Online MR",
            status=TaskState.RUNNING,
            created_time="2026-07-17T09:00:00Z",
            updated_time="2026-07-17T09:00:01Z",
            owner="controller",
            source="local",
            site_name="demo",
        )
    )

    with TestClient(app) as client:
        detail = client.get("/api/job-center/tasks/online-mr-controller-task")

    assert detail.status_code == 200
    assert detail.json()["module"] == "other"
    assert detail.json()["cancellable"] is False


def test_job_center_exposes_network_export_artifact_in_shared_window() -> None:
    artifact_id = "a" * 32
    artifact = JobCenterQueryService._artifact_download(
        "web_network_tools",
        "network_tools.toolbox_export",
        "network-export-task",
        "demo",
        "COMPLETED",
        {"result_id": artifact_id, "filename": "ping-results.csv", "size": 123},
    )

    assert artifact is not None
    assert artifact.artifact_id == artifact_id
    assert artifact.display_name == "ping-results.csv"
    assert artifact.api_path == f"/api/network-tools/artifacts/{artifact_id}"


@pytest.mark.parametrize(
    ("failure", "install_spec", "install_process", "poll_values"),
    [
        ("service-restart", False, False, (None,)),
        ("missing-spec", False, True, (None,)),
        ("missing-process", True, False, (None,)),
        ("stopped-process", True, True, (0,)),
        ("invalid-job", True, True, (None,)),
        ("wrong-cancel-path", True, True, (None,)),
    ],
)
def test_job_center_device_export_cancel_fails_without_live_receiver(
    tmp_path: Path,
    failure: str,
    install_spec: bool,
    install_process: bool,
    poll_values: tuple[int | None, ...],
) -> None:
    app, db_path = _app_with_tasks(tmp_path)
    cancel_path, _process = _install_device_export(
        app,
        db_path,
        task_id=f"device-export-{failure}",
        process=_FakeExportProcess(poll_values),
        install_spec=install_spec,
        install_process=install_process,
    )
    if failure == "invalid-job":
        job_path = (
            app.state.task_service.paths.runtime_cache_dir
            / "export_jobs"
            / (f"device-export-{failure}.json")
        )
        job_path.write_text("{}", encoding="utf-8")
    elif failure == "wrong-cancel-path":
        app.state.device_management_service._export_artifacts[
            f"device-export-{failure}"
        ]["cancel_path"] = tmp_path / "outside.cancel"

    with TestClient(app) as client:
        response = client.post(f"/api/job-center/tasks/device-export-{failure}/cancel")
        persisted = TaskRepository(db_path).get(f"device-export-{failure}")
        assert response.status_code == 409
        assert "导出任务" in response.json()["detail"]
        assert persisted is not None and persisted.status is TaskState.RUNNING
        assert not cancel_path.exists()


def test_job_center_device_export_cancel_rejects_terminal_race(tmp_path: Path) -> None:
    app, db_path = _app_with_tasks(tmp_path)
    task_id = "device-export-terminal-race"

    def finish_on_second_poll(count: int) -> None:
        if count != 2:
            return
        snapshot = TaskRepository(db_path).get(task_id)
        assert snapshot is not None
        TaskRepository(db_path).save(
            TaskSnapshot(
                **{
                    **snapshot.__dict__,
                    "status": TaskState.COMPLETED,
                    "finished_time": "2026-07-14T09:00:02Z",
                    "updated_time": "2026-07-14T09:00:02Z",
                }
            )
        )

    cancel_path, _process = _install_device_export(
        app,
        db_path,
        task_id=task_id,
        process=_FakeExportProcess(on_poll=finish_on_second_poll),
    )
    with TestClient(app) as client:
        response = client.post(f"/api/job-center/tasks/{task_id}/cancel")
        persisted = TaskRepository(db_path).get(task_id)
        assert response.status_code == 409
        assert persisted is not None and persisted.status is TaskState.COMPLETED
        assert not cancel_path.exists()


def test_job_center_device_export_cancel_cas_blocks_terminal_overwrite(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app, db_path = _app_with_tasks(tmp_path)
    task_id = "device-export-cas-race"
    cancel_path, _process = _install_device_export(app, db_path, task_id=task_id)
    service = app.state.device_management_service
    entered = threading.Event()
    release = threading.Event()
    original = service.task_service.record_external_event

    def delayed_record(selected_id, event_type, payload, **kwargs):
        if (
            selected_id == task_id
            and event_type == "state"
            and payload.get("state") == "STOPPING"
        ):
            entered.set()
            assert release.wait(2)
        return original(selected_id, event_type, payload, **kwargs)

    class ForbiddenGraceThread:
        def __init__(self, *_args, **_kwargs) -> None:
            raise AssertionError("CAS 失败后不得启动 grace-stop")

    monkeypatch.setattr(service.task_service, "record_external_event", delayed_record)
    monkeypatch.setattr(
        "netconsole.services.device_management_web_service.threading",
        SimpleNamespace(Thread=ForbiddenGraceThread, Event=threading.Event),
    )
    result: dict[str, object] = {}

    with TestClient(app) as client:
        worker = threading.Thread(
            target=lambda: result.setdefault(
                "response", client.post(f"/api/job-center/tasks/{task_id}/cancel")
            )
        )
        worker.start()
        try:
            assert entered.wait(2)
            original(
                task_id,
                "finished",
                {"result": {"available": False}},
                site_name="demo",
            )
        finally:
            release.set()
        worker.join(2)
        assert not worker.is_alive()
        response = result["response"]
        assert response.status_code == 409
        persisted = TaskRepository(db_path).get(task_id)
        assert persisted is not None and persisted.status is TaskState.COMPLETED
        assert not cancel_path.exists()


@pytest.mark.parametrize(
    ("owner", "task_type", "service_name", "accept", "expected_status"),
    [
        (
            "web_config_collection",
            "config_web_snapshot_fetch",
            "config_collection_service",
            True,
            200,
        ),
        (
            "web_config_collection",
            "config_web_snapshot_fetch",
            "config_collection_service",
            False,
            409,
        ),
        (
            "web_file_management",
            "file_management_download",
            "file_management_service",
            True,
            200,
        ),
        (
            "web_file_management",
            "file_management_download",
            "file_management_service",
            False,
            409,
        ),
    ],
)
def test_job_center_config_and_file_cancel_require_owner_confirmation(
    tmp_path: Path,
    owner: str,
    task_type: str,
    service_name: str,
    accept: bool,
    expected_status: int,
) -> None:
    app, db_path = _app_with_tasks(tmp_path)
    task_id = f"{task_type}-{'accept' if accept else 'reject'}"
    TaskRepository(db_path).save(
        TaskSnapshot(
            task_id=task_id,
            task_type=task_type,
            task_name="取消路由测试",
            status=TaskState.RUNNING,
            created_time="2026-07-14T09:00:00Z",
            updated_time="2026-07-14T09:00:01Z",
            owner=owner,
            source="local",
            site_name="demo",
        )
    )
    adapter = _OwnerCancelAdapter(
        app.state.task_service, site_name="demo", accept=accept
    )
    getattr(app.state, service_name).process_adapter = adapter

    with TestClient(app) as client:
        response = client.post(f"/api/job-center/tasks/{task_id}/cancel")
        persisted = TaskRepository(db_path).get(task_id)

    assert response.status_code == expected_status
    assert adapter.calls == [task_id]
    assert persisted is not None
    assert persisted.status is (TaskState.STOPPING if accept else TaskState.RUNNING)


def test_job_center_dto_hides_paths_and_builds_owner_artifact_capabilities(
    tmp_path: Path,
) -> None:
    app, db_path = _app_with_tasks(tmp_path)
    repository = TaskRepository(db_path)
    device_service = app.state.device_management_service
    device_root = device_service._artifact_root("demo")
    device_target = device_root / "device-production.csv"
    device_target.write_bytes(b"device export")
    device_result = device_service._finalize_export_artifact(
        {
            "artifact_id": "device-abc",
            "artifact_root": device_root,
            "artifact_name": device_target.name,
            "display_name": "设备:清单?.csv",
            "export_type": "device_csv",
            "target": device_target,
            "tmp_path": device_target,
        },
        {"path": str(device_target)},
    )
    config_context = JobContext.from_job(
        BackgroundJob(
            job_id="config-artifact",
            task_type="config_web_export_snapshots",
            params={
                "site_name": "demo",
                "app_root": str(tmp_path),
                "data_root": str(tmp_path),
            },
        )
    )
    config_id, _config_path, config_name = _artifact_target(
        config_context, ".zip", "配置:快照?"
    )
    files_root = app.state.task_service.paths.site_files_dir("demo") / "outputs"
    files_root.mkdir(parents=True, exist_ok=True)
    source = files_root / "中文报告.zip"
    source.write_bytes(b"capture")
    file_service = FileManagementApplicationService(app.state.task_service.paths)
    file_ref = next(
        item.file_ref
        for item in file_service.list_files("demo").items
        if item.name == source.name
    )
    file_result = run_file_management_download(
        JobContext.from_job(
            BackgroundJob(
                job_id="file-artifact",
                task_type="file_management_download",
                params={
                    "site_name": "demo",
                    "file_ref": file_ref,
                    "app_root": str(tmp_path),
                    "data_root": str(tmp_path),
                },
            )
        )
    )
    historical_device_result = dict(device_result)
    historical_device_result.pop("display_name")
    template_result = {
        "artifact_id": "device-template-abc",
        "artifact_name": "demo-设备导入模板.csv",
        "artifact_source": "device_csv_export",
        "artifact_type": "csv",
        "sha256": hashlib.sha256(b"template").hexdigest(),
        "size_bytes": len(b"template"),
        "row_count": 0,
    }
    fixtures = [
        (
            "device-artifact",
            "device_export_device_csv",
            "web_device_management",
            device_result,
        ),
        (
            "device-history",
            "device_export_device_csv",
            "web_device_management",
            historical_device_result,
        ),
        (
            "device-template",
            "web_export_device_template_csv",
            "web_device_management",
            template_result,
        ),
        (
            "device-diagnostic",
            "device_diagnostic_download",
            "web_device_management",
            {
                "artifact_id": "device-diagnostic-0123456789abcdef0123456789abcdef",
                "artifact_name": "device-diagnostic-0123456789abcdef0123456789abcdef.zip",
                "available": True,
                "size_bytes": 42,
            },
        ),
        (
            "config-artifact",
            "config_web_export_snapshots",
            "web_config_collection",
            {
                "artifact_id": config_id,
                "display_name": config_name,
                "size": 34,
                "output_path": "C:\\private\\configs.zip",
            },
        ),
        (
            "file-artifact",
            "file_management_download",
            "web_file_management",
            file_result,
        ),
    ]
    for task_id, task_type, owner, result in fixtures:
        repository.save(
            TaskSnapshot(
                task_id=task_id,
                task_type=task_type,
                task_name=task_id,
                status=TaskState.COMPLETED,
                created_time="2026-07-14T10:00:00Z",
                finished_time="2026-07-14T10:00:01Z",
                updated_time="2026-07-14T10:00:01Z",
                owner=owner,
                source="local",
                site_name="demo",
                message="saved C:\\secret\\status.log",
                result={
                    **result,
                    "result_path": "C:\\secret\\result",
                    "session_dir": "C:\\secret\\session",
                    "raw_output_reference": "C:\\secret\\raw.log",
                },
            )
        )

    with TestClient(app) as client:
        payloads = {
            task_id: client.get(f"/api/job-center/tasks/{task_id}").json()
            for task_id, *_rest in fixtures
        }
        list_payloads = {
            item["id"]: item for item in client.get("/api/job-center/tasks").json()
        }

    device = payloads["device-artifact"]["artifact_download"]
    device_history = payloads["device-history"]["artifact_download"]
    device_template = payloads["device-template"]["artifact_download"]
    device_diagnostic = payloads["device-diagnostic"]["artifact_download"]
    config = payloads["config-artifact"]["artifact_download"]
    file = payloads["file-artifact"]["artifact_download"]
    assert device == {
        "artifact_id": "device-abc",
        "display_name": "设备_清单.csv",
        "size_bytes": len(b"device export"),
        "sha256": device_result["sha256"],
        "media_type": "text/csv",
        "api_path": "/api/device-management/exports/device-artifact/download",
        "query": {"artifact_id": "device-abc"},
    }
    assert device_history["display_name"] == "设备清单.csv"
    assert device_history["display_name"] != historical_device_result["artifact_name"]
    assert device_template == {
        "artifact_id": "device-template-abc",
        "display_name": "demo-设备导入模板.csv",
        "size_bytes": len(b"template"),
        "sha256": template_result["sha256"],
        "media_type": "text/csv",
        "api_path": "/api/device-management/exports/device-template/download",
        "query": {"artifact_id": "device-template-abc"},
    }
    assert list_payloads["device-artifact"]["artifact_download"] == device
    assert list_payloads["device-template"]["artifact_download"] == device_template
    assert device_diagnostic == {
        "artifact_id": "device-diagnostic-0123456789abcdef0123456789abcdef",
        "display_name": "设备诊断.zip",
        "size_bytes": 42,
        "sha256": "",
        "media_type": "application/zip",
        "api_path": "/api/device-management/diagnostics/device-diagnostic/download",
        "query": {"artifact_id": "device-diagnostic-0123456789abcdef0123456789abcdef"},
    }
    assert config["display_name"].startswith("配置_快照_") and config[
        "display_name"
    ].endswith(".zip")
    assert config["size_bytes"] == 34
    assert config["media_type"] == "application/zip"
    assert config["api_path"].endswith(f"/artifacts/{config_id}")
    assert file["artifact_id"] == file_ref
    assert file["display_name"] == "中文报告.zip"
    assert file["size_bytes"] == len(b"capture")
    assert file["media_type"] == "application/zip"
    assert file["api_path"] == "/api/file-management/downloads/file-artifact/file"
    for payload in payloads.values():
        assert (
            not {
                "result_path",
                "output_dir",
                "package_path",
                "session_path",
                "raw_output_reference",
            }
            & payload.keys()
        )
        assert "C:\\secret" not in str(payload)


def test_job_center_router_exposes_only_owner_checked_task_mutations(
    tmp_path: Path,
) -> None:
    app, _db_path = _app_with_tasks(tmp_path)
    routes = {
        (path, method.upper())
        for path, operations in app.openapi()["paths"].items()
        if path.startswith("/api/job-center")
        for method in operations
    }

    assert routes
    assert {method for _path, method in routes} == {"GET", "POST"}
    assert {(path, method) for path, method in routes if method == "POST"} == {
        ("/api/job-center/acknowledge", "POST"),
        ("/api/job-center/cleanup", "POST"),
        ("/api/job-center/tasks/{task_id}/acknowledge", "POST"),
        ("/api/job-center/tasks/{task_id}/cancel", "POST"),
        ("/api/job-center/tasks/{task_id}/dismiss", "POST"),
    }
    assert all(
        not path.endswith(("/stop", "/force-stop", "/retry"))
        for path, _method in routes
    )
    assert all("delete" not in path for path, _method in routes)


def test_job_center_artifact_names_are_safe_and_duplicate_names_keep_distinct_ids() -> (
    None
):
    name = JobCenterQueryService._artifact_display_name("同名:报告?.xlsx")
    first = JobCenterQueryService._artifact_dto("artifact-1", name, 1, "/api/files/1")
    second = JobCenterQueryService._artifact_dto("artifact-2", name, 1, "/api/files/2")

    assert name == "同名_报告.xlsx"
    assert JobCenterQueryService._artifact_display_name(r"C:\private\report.xlsx") == ""
    assert (
        JobCenterQueryService._artifact_display_name(r"\\server\share\report.xlsx")
        == ""
    )
    assert first.display_name == second.display_name
    assert first.artifact_id != second.artifact_id


def test_job_center_downloads_generic_web_artifact_without_exposing_physical_name(
    tmp_path: Path,
) -> None:
    app, db_path = _app_with_tasks(tmp_path)
    task_id = "command-reference-export"
    store = app.state.web_artifact_store
    reservation = store.reserve(
        site_id="demo",
        owner="web_command_reference",
        source="command_reference_export",
        artifact_type="md",
        task_id=task_id,
        task_type="web_export_command_reference_markdown",
        output_root=(
            app.state.task_service.paths.site_files_dir("demo")
            / "command_reference"
            / "exports"
        ),
        preferred_name="NetConsole_软件使用命令清单.md",
    )
    reservation.output_path.write_text("命令说明", encoding="utf-8")
    TaskRepository(db_path).save(
        TaskSnapshot(
            task_id=task_id,
            task_type="web_export_command_reference_markdown",
            task_name="命令说明导出",
            status=TaskState.COMPLETED,
            created_time="2026-07-17T10:00:00Z",
            finished_time="2026-07-17T10:00:01Z",
            updated_time="2026-07-17T10:00:01Z",
            owner="web_command_reference",
            source="local",
            site_name="demo",
        )
    )
    manifest = store.complete(reservation)

    with TestClient(app) as client:
        detail = client.get(f"/api/job-center/tasks/{task_id}")
        downloaded = client.get(f"/api/job-center/artifacts/{reservation.artifact_id}")
        missing = client.get("/api/job-center/artifacts/not-an-artifact")

    artifact = detail.json()["artifact_download"]
    assert artifact["display_name"] == "NetConsole_软件使用命令清单.md"
    assert reservation.artifact_id not in artifact["display_name"]
    assert manifest["file_name"] != artifact["display_name"]
    assert downloaded.status_code == 200
    assert downloaded.content == "命令说明".encode()
    assert "NetConsole_" in downloaded.headers["content-disposition"]
    assert missing.status_code == 404
