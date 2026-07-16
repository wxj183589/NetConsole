from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import threading

from fastapi.testclient import TestClient
import pytest

from netconsole.backend.api.main import create_app
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
from netconsole.repositories.online_mr_task_session_repository import OnlineMrTaskSessionRepository
from netconsole.repositories.task_repository import TaskRepository
from netconsole.services.background_job import BackgroundJob
from netconsole.services.config_collection_job_handlers import _artifact_target
from netconsole.services.export.export_job import ExportJob
from netconsole.services.file_management_service import FileManagementApplicationService, run_file_management_download
from netconsole.services.job_center.job_context import JobContext
from netconsole.services.job_center.query_service import JobCenterQueryService
from netconsole.services.job_center.task_application_service import TaskApplicationService


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text_values(value: object) -> list[str]:
    if isinstance(value, dict):
        return [text for item in value.values() for text in _text_values(item)]
    if isinstance(value, list):
        return [text for item in value for text in _text_values(item)]
    return [value] if isinstance(value, str) else []


class _FakeExportProcess:
    stdout = None

    def __init__(self, poll_values: tuple[int | None, ...] = (None,), on_poll=None) -> None:
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
    def __init__(self, task_service: TaskApplicationService, *, site_name: str, accept: bool) -> None:
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
            {"state": TaskState.STOPPING.value, "message": "owner accepted cancellation"},
            site_name=self.site_name,
        )
        return True


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
    ).with_runtime_paths(tmp_path=str(target.with_suffix(".tmp")), cancel_path=str(cancel_path))
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
    paths = PathResolver(tmp_path)
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
            payload={"traceback": "failed at C:\\private\\worker.py and \\\\server\\share\\secret.log"},
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
    return create_app(RuntimeMode.SERVER, paths=paths, task_service=service, frontend_dist=tmp_path / "missing"), db_path


def test_job_center_get_api_is_read_only_and_returns_associations(tmp_path: Path) -> None:
    app, db_path = _app_with_tasks(tmp_path)

    with TestClient(app) as client:
        before_hash = _sha256(db_path)
        before_mtime = db_path.stat().st_mtime_ns
        listing = client.get("/api/job-center/tasks")
        detail = client.get("/api/job-center/tasks/online-mr-task")
        logs = client.get("/api/job-center/tasks/online-mr-task/logs?tail=300")
        summary = client.get("/api/job-center/summary")
        after_hash = _sha256(db_path)
        after_mtime = db_path.stat().st_mtime_ns

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
    assert logs.json()["lines"][1]["message"] == "failed at <redacted-path>"
    assert "C:\\private" not in logs.text
    assert "server\\share" not in logs.text
    assert "must-not-leak" not in logs.text
    assert summary.json() == {"total": 2, "active": 0, "completed": 1, "failed": 1, "warning": 1}
    assert (after_hash, after_mtime) == (before_hash, before_mtime)


def test_job_center_logs_missing_and_unknown_task_are_explicit(tmp_path: Path) -> None:
    app, _db_path = _app_with_tasks(tmp_path)

    with TestClient(app) as client:
        empty_logs = client.get("/api/job-center/tasks/quiet-task/logs")
        missing = client.get("/api/job-center/tasks/not-found")

    assert empty_logs.status_code == 200
    assert empty_logs.json() == {"task_id": "quiet-task", "lines": [], "message": "暂无日志"}
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


def test_job_center_rejects_cancel_without_owner_capability(tmp_path: Path) -> None:
    app, _db_path = _app_with_tasks(tmp_path)

    with TestClient(app) as client:
        response = client.post("/api/job-center/tasks/online-mr-task/cancel")

    assert response.status_code == 409


def test_job_center_routes_device_export_cancel_to_real_owner(tmp_path: Path, monkeypatch) -> None:
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
    assert not (app.state.task_service.paths.runtime_cache_dir / "background_jobs" / "device-export-running.cancel").exists()


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
        job_path = app.state.task_service.paths.runtime_cache_dir / "export_jobs" / (
            f"device-export-{failure}.json"
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


@pytest.mark.parametrize(
    ("owner", "task_type", "service_name", "accept", "expected_status"),
    [
        ("web_config_collection", "config_web_snapshot_fetch", "config_collection_service", True, 200),
        ("web_config_collection", "config_web_snapshot_fetch", "config_collection_service", False, 409),
        ("web_file_management", "file_management_download", "file_management_service", True, 200),
        ("web_file_management", "file_management_download", "file_management_service", False, 409),
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
    adapter = _OwnerCancelAdapter(app.state.task_service, site_name="demo", accept=accept)
    getattr(app.state, service_name).process_adapter = adapter

    with TestClient(app) as client:
        response = client.post(f"/api/job-center/tasks/{task_id}/cancel")
        persisted = TaskRepository(db_path).get(task_id)

    assert response.status_code == expected_status
    assert adapter.calls == [task_id]
    assert persisted is not None
    assert persisted.status is (TaskState.STOPPING if accept else TaskState.RUNNING)


def test_job_center_dto_hides_paths_and_builds_owner_artifact_capabilities(tmp_path: Path) -> None:
    app, db_path = _app_with_tasks(tmp_path)
    repository = TaskRepository(db_path)
    device_service = app.state.device_management_service
    device_root = device_service._artifact_root("demo")
    device_target = device_root / "device-production.csv"
    device_target.write_bytes(b"device export")
    device_result = device_service._finalize_export_artifact(
        {
            "artifact_id": "device-abc", "artifact_root": device_root,
            "artifact_name": device_target.name, "display_name": "设备:清单?.csv",
            "export_type": "device_csv", "target": device_target, "tmp_path": device_target,
        },
        {"path": str(device_target)},
    )
    config_context = JobContext.from_job(BackgroundJob(
        job_id="config-artifact", task_type="config_web_export_snapshots",
        params={"site_name": "demo", "app_root": str(tmp_path), "data_root": str(tmp_path)},
    ))
    config_id, _config_path, config_name = _artifact_target(config_context, ".zip", "配置:快照?")
    files_root = app.state.task_service.paths.site_files_dir("demo") / "outputs"
    files_root.mkdir(parents=True, exist_ok=True)
    source = files_root / "中文报告.zip"
    source.write_bytes(b"capture")
    file_service = FileManagementApplicationService(app.state.task_service.paths)
    file_ref = next(item.file_ref for item in file_service.list_files("demo").items if item.name == source.name)
    file_result = run_file_management_download(JobContext.from_job(BackgroundJob(
        job_id="file-artifact", task_type="file_management_download",
        params={"site_name": "demo", "file_ref": file_ref, "app_root": str(tmp_path), "data_root": str(tmp_path)},
    )))
    historical_device_result = dict(device_result)
    historical_device_result.pop("display_name")
    fixtures = [
        ("device-artifact", "device_export_device_csv", "web_device_management", device_result),
        ("device-history", "device_export_device_csv", "web_device_management", historical_device_result),
        ("config-artifact", "config_web_export_snapshots", "web_config_collection", {"artifact_id": config_id, "display_name": config_name, "size": 34, "output_path": "C:\\private\\configs.zip"}),
        ("file-artifact", "file_management_download", "web_file_management", file_result),
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
                result={**result, "result_path": "C:\\secret\\result", "session_dir": "C:\\secret\\session", "raw_output_reference": "C:\\secret\\raw.log"},
            )
        )

    with TestClient(app) as client:
        payloads = {task_id: client.get(f"/api/job-center/tasks/{task_id}").json() for task_id, *_rest in fixtures}

    device = payloads["device-artifact"]["artifact_download"]
    device_history = payloads["device-history"]["artifact_download"]
    config = payloads["config-artifact"]["artifact_download"]
    file = payloads["file-artifact"]["artifact_download"]
    assert device == {
        "artifact_id": "device-abc", "display_name": "设备_清单.csv", "size_bytes": len(b"device export"),
        "media_type": "application/vnd.ms-excel",
        "api_path": "/api/device-management/exports/device-artifact/download", "query": {"artifact_id": "device-abc"},
    }
    assert device_history["display_name"] == "设备清单.csv"
    assert device_history["display_name"] != historical_device_result["artifact_name"]
    assert config["display_name"].startswith("配置_快照_") and config["display_name"].endswith(".zip")
    assert config["size_bytes"] == 34
    assert config["api_path"].endswith(f"/artifacts/{config_id}")
    assert file["artifact_id"] == file_ref
    assert file["display_name"] == "中文报告.zip"
    assert file["size_bytes"] == len(b"capture")
    assert file["api_path"] == "/api/file-management/downloads/file-artifact/file"
    for payload in payloads.values():
        assert not {"result_path", "output_dir", "package_path", "session_path", "raw_output_reference"} & payload.keys()
        assert "C:\\secret" not in str(payload)


def test_job_center_router_exposes_only_owner_checked_cancel_mutation(tmp_path: Path) -> None:
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
        ("/api/job-center/tasks/{task_id}/cancel", "POST")
    }
    assert all(not path.endswith(("/stop", "/force-stop", "/retry")) for path, _method in routes)
    assert all("delete" not in path for path, _method in routes)


def test_job_center_artifact_names_are_safe_and_duplicate_names_keep_distinct_ids() -> None:
    name = JobCenterQueryService._artifact_display_name("同名:报告?.xlsx")
    first = JobCenterQueryService._artifact_dto("artifact-1", name, 1, "/api/files/1")
    second = JobCenterQueryService._artifact_dto("artifact-2", name, 1, "/api/files/2")

    assert name == "同名_报告.xlsx"
    assert JobCenterQueryService._artifact_display_name(r"C:\private\report.xlsx") == ""
    assert JobCenterQueryService._artifact_display_name(r"\\server\share\report.xlsx") == ""
    assert first.display_name == second.display_name
    assert first.artifact_id != second.artifact_id
