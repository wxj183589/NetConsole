from __future__ import annotations

import hashlib

import json

from pathlib import Path

import pytest

from fastapi.testclient import TestClient

from tests.support.job_process_test_support import FakeExportProcessAdapter, FakeLocalProcessAdapter

from netconsole.application.rail_transit.web_application_service import (
    RailTransitWebApplicationService,
    RailTransitWebError,
)

from netconsole.application.web_export_process_adapter import WebExportProcessAdapter

from netconsole.backend.api.main import create_app

from netconsole.core.database import Database

from netconsole.core.paths import PathResolver

from netconsole.core.runtime_mode import RuntimeMode

from netconsole.models.task_state import TaskState

from netconsole.services.job_center.task_application_service import (
    TaskApplicationService,
)

from netconsole.services.online_mr.query_service import OnlineMrQueryService

from netconsole.repositories.online_mr_diagnosis_repository import OnlineMrDiagnosisRepository

from netconsole.services.rail_transit.online_mr_diagnosis_parser import PARSER_VERSION

RAIL_FEATURE_IDS = (
    "module.train_communication",
    "capability.online_mr.report_export",
    "capability.online_mr.parse",
    "capability.online_mr.open_location",
    "capability.online_mr.session_delete",
    "capability.desktop_native_integration",
    "online_mr.collection_notes",
    "capability.mesh.import",
    "capability.mesh.report_export",
    "capability.mesh.source_open_location",
    "capability.train_communication.diagnostic_execute",
    "capability.rail_transit.task_control",
    "capability.train_communication.point_table_write",
    "capability.train_communication.point_table_export",
    "module.trackside_ap",
    "capability.trackside_ap.update",
)

class _NoopAsyncService:
    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

def _service(paths: PathResolver, mesh_query=None):
    paths.ensure_site_dirs("demo")
    tasks = TaskApplicationService(paths=paths, site_name="demo")
    normal = FakeLocalProcessAdapter(tasks)
    export = FakeExportProcessAdapter(tasks)
    service = RailTransitWebApplicationService(
        paths,
        tasks,
        process_adapter=normal,  # type: ignore[arg-type]
        export_adapter=export,  # type: ignore[arg-type]
        query_service=OnlineMrQueryService(paths),
        mesh_query_service=mesh_query,
    )
    return service, normal, export, tasks

def _enable_features(app) -> None:
    for feature_id in RAIL_FEATURE_IDS:
        app.state.feature_gate.features[feature_id] = {
            "visible": True,
            "enabled": True,
            "client_package": True,
            "internal_only": False,
        }

def _mark_online_mr_parsed_ready(session_dir: Path, session_id: str) -> None:
    repository = OnlineMrDiagnosisRepository(session_dir / "parsed" / "online_diagnosis.sqlite")
    repository.initialize()
    raw_root = session_dir / "raw"
    fingerprint = json.dumps(
        [
            {
                "path": path.relative_to(raw_root).as_posix(),
                "size": path.stat().st_size,
                "mtime_ns": path.stat().st_mtime_ns,
            }
            for path in sorted(raw_root.rglob("*"))
            if path.is_file() and not path.is_symlink()
        ],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ) if raw_root.is_dir() else "[]"
    repository.replace_parse_metadata(
        (session_id, "2026-07-20 12:00:00", PARSER_VERSION, fingerprint, "{}", "OK", "")
    )

def _online_mr_session(
    paths: PathResolver, session_id: str = "session-actions"
) -> Path:
    session = paths.online_mr_session_dir("demo", "MR-01", session_id)
    for name in ("raw", "parsed", "view", "logs", "outputs"):
        (session / name).mkdir(parents=True, exist_ok=True)
    (session / "session_meta.json").write_text(
        json.dumps(
            {
                "session_id": session_id,
                "site": "demo",
                "mr_name": "MR-01",
                "device_id": 7,
                "device_name": "列车07 MR",
                "status": "STOPPED",
                "started_at": "2026-07-17 10:00:00",
                "ended_at": "2026-07-17 10:05:00",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (session / "raw" / "mesh_link_raw.log").write_text("sample", encoding="utf-8")
    return session


def test_online_mr_note_and_parse_use_real_session_and_task(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    service, normal, _export, _tasks = _service(paths)
    session = _online_mr_session(paths)

    with pytest.raises(RailTransitWebError) as confirmation:
        service.add_online_mr_note(
            "demo", "session-actions", note="进入区间", explicit_confirmation=False
        )
    assert confirmation.value.code == "CONFIRMATION_REQUIRED"

    note = service.add_online_mr_note(
        "demo",
        "session-actions",
        note="进入区间",
        explicit_confirmation=True,
        audit={"source": "伪造来源", "action": "伪造动作", "operator": "tester"},
    )
    assert note.title == "进入区间"
    persisted = json.loads((session / "manual_notes.jsonl").read_text(encoding="utf-8"))
    assert persisted["audit"]["source"] == "electron_online_mr"
    assert persisted["audit"]["action"] == "add_note"
    assert persisted["audit"]["operator"] == "tester"
    assert service.notes("demo", "session-actions")[0].title == "进入区间"

    task = service.start_online_mr_parse("demo", "session-actions", force_reparse=True)
    assert normal.jobs[task.task_id].task_type == "online_mr_parse"
    assert normal.jobs[task.task_id].params["session_dir"] == str(session.resolve())
    assert normal.jobs[task.task_id].params["force_reparse"] is True
    assert normal.jobs[task.task_id].params["resource_keys"] == [
        "online_mr_session:demo:session-actions"
    ]


def test_online_mr_ensure_current_reuses_one_inflight_upgrade_task(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    service, _normal, _export, tasks = _service(paths)
    _online_mr_session(paths, "session-auto-upgrade")

    first = service.ensure_online_mr_parsed_database_current("demo", "session-auto-upgrade")
    second = service.ensure_online_mr_parsed_database_current("demo", "session-auto-upgrade")

    assert first.status == "UPGRADING"
    assert first.task is not None
    assert second.status == "UPGRADING"
    assert second.task is not None
    assert second.task.task_id == first.task.task_id
    active = tasks.repository("demo").list(
        statuses={TaskState.PENDING, TaskState.STARTING, TaskState.RUNNING, TaskState.STOPPING},
        limit=20,
    )
    assert [item.task_id for item in active if item.task_type == "online_mr_parse"] == [first.task.task_id]


def test_online_mr_ensure_current_is_noop_for_current_contract(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    service, normal, _export, _tasks = _service(paths)
    session = _online_mr_session(paths, "session-current")
    _mark_online_mr_parsed_ready(session, "session-current")

    result = service.ensure_online_mr_parsed_database_current("demo", "session-current")

    assert result.status == "CURRENT"
    assert result.missing_capabilities == []
    assert result.task is None
    assert normal.jobs == {}


def test_online_mr_ensure_current_persists_missing_raw_without_starting_task(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    service, normal, _export, _tasks = _service(paths)
    session = _online_mr_session(paths, "session-no-raw")
    (session / "raw" / "mesh_link_raw.log").write_text("", encoding="utf-8")

    first = service.ensure_online_mr_parsed_database_current("demo", "session-no-raw")
    second = service.ensure_online_mr_parsed_database_current("demo", "session-no-raw")

    assert first.status == "RAW_DATA_MISSING"
    assert second.status == "RAW_DATA_MISSING"
    assert second.retry_suppressed is True
    assert normal.jobs == {}


def test_online_mr_location_report_and_delete_share_session_resource(
    tmp_path: Path,
) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    service, normal, export, tasks = _service(paths)
    session = _online_mr_session(paths, "session-actions")
    _mark_online_mr_parsed_ready(session, "session-actions")
    resource_key = "online_mr_session:demo:session-actions"

    location = service.online_mr_desktop_location("demo", "session-actions")
    assert location == {
        "target_type": "file",
        "path": str((session / "raw" / "mesh_link_raw.log").resolve()),
    }
    (session / "outputs" / "session-actions.zip").write_bytes(b"package")
    package_location = service.online_mr_desktop_location("demo", "session-actions")
    assert package_location == {
        "target_type": "file",
        "path": str((session / "outputs" / "session-actions.zip").resolve()),
    }

    report = service.start_online_mr_report("demo", "session-actions", "")
    snapshot = tasks.repository("demo").get(report.task_id)
    assert snapshot is not None
    assert snapshot.resource_keys == [resource_key]
    with pytest.raises(RailTransitWebError) as report_conflict:
        service.start_online_mr_delete(
            "demo",
            "session-actions",
            expected_session_id="session-actions",
            explicit_confirmation=True,
        )
    assert report_conflict.value.code == "ONLINE_MR_SESSION_TASK_ACTIVE"

    report_path = Path(str(export.jobs[report.task_id].output_path))
    export.complete(report.task_id)
    (session / "outputs" / "session-actions.zip").unlink()
    (session / "raw" / "mesh_link_raw.log").unlink()
    fallback_location = service.online_mr_desktop_location(
        "demo", "session-actions"
    )
    assert fallback_location == {
        "target_type": "directory",
        "path": str((session / "raw").resolve()),
    }
    artifact = service.artifact_store.online_mr_session_artifacts(
        "demo",
        "session-actions",
        owner=service._OWNER,
        task_type=service._ARTIFACT_TASK_TYPES["online_mr_report"],
    )[0]
    manifest_path = Path(str(artifact["manifest_path"]))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["context"]["session_id"] = "missing-session-with-report"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    report_location = service.online_mr_desktop_location(
        "demo", "missing-session-with-report"
    )
    assert report_location == {
        "target_type": "file",
        "path": str(report_path.resolve()),
    }
    with pytest.raises(RailTransitWebError) as missing_location:
        service.online_mr_desktop_location("demo", "missing-session")
    assert missing_location.value.code == "ONLINE_MR_LOCAL_FILES_MISSING"

    manifest["context"]["session_id"] = "session-actions"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    deletion = service.start_online_mr_delete(
        "demo",
        "session-actions",
        expected_session_id="session-actions",
        explicit_confirmation=True,
    )
    job = normal.jobs[deletion.task_id]
    assert deletion.action == "online_mr_session_delete"
    assert deletion.result_summary["session_id"] == "session-actions"
    assert job.params["resource_keys"] == [resource_key]
    assert job.params["session_dir"] == str(session.resolve())
    assert all(
        Path(str(item["path"])).is_relative_to(paths.online_mr_root("demo"))
        for item in job.params["artifact_items"]
    )
    with pytest.raises(RailTransitWebError) as cancel_rejected:
        service.cancel_task("demo", deletion.task_id)
    assert cancel_rejected.value.code == "TASK_NOT_CANCELLABLE"


@pytest.mark.parametrize(
    ("field", "value", "expected_code", "expected_message"),
    [
        ("status", "RUNNING", "ONLINE_MR_SESSION_RUNNING", "采集或停止处理中"),
        ("status", "STOPPING", "ONLINE_MR_SESSION_RUNNING", "采集或停止处理中"),
        ("phase", "STOPPING_TRAFFIC", "ONLINE_MR_SESSION_RUNNING", "采集或停止处理中"),
        ("phase", "PACKAGING", "ONLINE_MR_SESSION_FINALIZING", "归档、解析或打包"),
        ("phase", "ARCHIVING", "ONLINE_MR_SESSION_FINALIZING", "归档、解析或打包"),
        ("phase", "RECOVERING", "ONLINE_MR_SESSION_FINALIZING", "归档、解析或打包"),
    ],
)
def test_online_mr_delete_rejects_active_collection_and_finalization_states(
    tmp_path: Path,
    field: str,
    value: str,
    expected_code: str,
    expected_message: str,
) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    service, _normal, _export, _tasks = _service(paths)
    session = _online_mr_session(paths, f"session-{field}")
    metadata = json.loads((session / "session_meta.json").read_text(encoding="utf-8"))
    metadata[field] = value
    (session / "session_meta.json").write_text(
        json.dumps(metadata, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(RailTransitWebError) as raised:
        service.start_online_mr_delete(
            "demo",
            f"session-{field}",
            expected_session_id=f"session-{field}",
            explicit_confirmation=True,
        )

    assert raised.value.code == expected_code
    assert expected_message in str(raised.value)
    assert session.is_dir()


def test_online_mr_session_action_api_rejects_browser_location_and_confirms_delete(
    tmp_path: Path,
) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    paths.ensure_site_dirs("demo")
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.app_config_path.write_text('{"current_site":"demo"}', encoding="utf-8")
    Database(paths.site_db_path("demo")).initialize()
    session = _online_mr_session(paths, "session-api-delete")
    app = create_app(
        RuntimeMode.SERVER,
        paths=paths,
        agent_service=_NoopAsyncService(),  # type: ignore[arg-type]
        traffic_service=_NoopAsyncService(),  # type: ignore[arg-type]
        frontend_dist=tmp_path / "missing",
    )
    normal = FakeLocalProcessAdapter(app.state.task_service)
    app.state.rail_transit_web_application_service = RailTransitWebApplicationService(
        paths,
        app.state.task_service,
        process_adapter=normal,  # type: ignore[arg-type]
        export_adapter=FakeExportProcessAdapter(app.state.task_service),  # type: ignore[arg-type]
        query_service=app.state.online_mr_query_service,
        mesh_query_service=app.state.mesh_analysis_query_service,
    )
    _enable_features(app)

    with TestClient(app, base_url="http://127.0.0.1") as client:
        browser_location = client.post(
            "/api/online-mr/sessions/session-api-delete/desktop-location"
        )
        mismatch = client.request(
            "DELETE",
            "/api/online-mr/sessions/session-api-delete",
            json={
                "expected_session_id": "other-session",
                "explicit_confirmation": True,
            },
        )
        accepted = client.request(
            "DELETE",
            "/api/online-mr/sessions/session-api-delete",
            json={
                "expected_session_id": "session-api-delete",
                "explicit_confirmation": True,
            },
        )

    assert browser_location.status_code == 403
    assert mismatch.status_code == 422
    assert mismatch.json()["detail"]["code"] == "CONFIRMATION_REQUIRED"
    assert accepted.status_code == 202
    assert accepted.json()["action"] == "online_mr_session_delete"
    assert str(session.resolve()) not in accepted.text


def test_online_mr_export_manifest_hash_download_cancel_and_ownership(
    tmp_path: Path,
) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    service, _normal, export, tasks = _service(paths)
    session_dir = paths.online_mr_session_dir("demo", "MR-01", "session-1")
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "session_meta.json").write_text(
        json.dumps(
            {
                "session_id": "session-1",
                "site": "demo",
                "mr_name": "MR-01",
                "status": "COMPLETED",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RailTransitWebError) as parse_required:
        service.start_online_mr_report("demo", "session-1", "blocked.xlsx")
    assert parse_required.value.code == "PARSE_REQUIRED"
    _mark_online_mr_parsed_ready(session_dir, "session-1")
    started = service.start_online_mr_report("demo", "session-1", "report.xlsx")
    content = b"fixture-xlsx"
    output = export.complete(started.task_id, content)
    completed = service.get_task("demo", started.task_id)
    opened, name = service.open_online_mr_report("demo", completed.artifact_id)

    assert output == opened
    assert name.endswith(".xlsx")
    assert completed.available is True
    assert completed.sha256 == hashlib.sha256(content).hexdigest()
    assert completed.size_bytes == len(content)
    assert "path" not in completed.model_dump()
    with pytest.raises(RailTransitWebError):
        service.open_mesh_report("demo", completed.artifact_id)

    cancelled = service.start_online_mr_report("demo", "session-1", "cancelled.xlsx")
    cancelled_output = Path(export.jobs[cancelled.task_id].output_path)
    after_cancel = service.cancel_task("demo", cancelled.task_id)
    assert after_cancel.status == "CANCELLED"
    assert not cancelled_output.exists()
    with pytest.raises(RailTransitWebError):
        service.open_online_mr_report("demo", cancelled.artifact_id)

    tasks.create_external_task(
        task_id="wrong-owner",
        task_type="car_network_refresh_all",
        task_name="wrong",
        source="local",
        site_name="demo",
        owner="other",
    )
    with pytest.raises(RailTransitWebError) as wrong_owner:
        service.get_task("demo", "wrong-owner")
    assert wrong_owner.value.code == "TASK_NOT_FOUND"


def test_online_mr_report_runs_in_independent_export_process(tmp_path: Path) -> None:
    from test_online_mr_collection import _config
    from netconsole.services.online_mr_session_store import OnlineMrSessionStore
    from netconsole.services.rail_transit.online_mr_diagnosis_parser import (
        OnlineMrDiagnosisParser,
    )

    paths, config = _config(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)
    OnlineMrDiagnosisParser(session.session_dir)._ensure_tables()
    _mark_online_mr_parsed_ready(session.session_dir, session.meta.session_id)
    service, _normal, _fake_export, tasks = _service(paths)
    adapter = WebExportProcessAdapter(tasks)
    service.export_adapter = adapter
    try:
        started = service.start_online_mr_report(
            "demo", session.meta.session_id, "online-report.xlsx"
        )
        assert adapter.wait(started.task_id, timeout=30)
        completed = service.get_task("demo", started.task_id)
        path, _name = service.open_online_mr_report("demo", completed.artifact_id)
    finally:
        adapter.shutdown()

    assert completed.status == "COMPLETED"
    assert completed.available is True
    assert path.is_file() and path.stat().st_size > 0
