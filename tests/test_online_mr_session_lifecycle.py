from __future__ import annotations

from pathlib import Path

import pytest

from netconsole.core.paths import PathResolver
from netconsole.models.task_snapshot import TaskSnapshot
from netconsole.models.task_state import TaskState
from netconsole.repositories.online_mr_task_session_repository import (
    OnlineMrTaskSessionRepository,
)
from netconsole.repositories.task_repository import TaskRepository
from netconsole.services.online_mr.session_lifecycle import (
    OnlineMrSessionLifecycleError,
    OnlineMrSessionLifecycleService,
    online_mr_session_resource_key,
)


def _paths(tmp_path: Path) -> PathResolver:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    paths.ensure_site_dirs("demo")
    return paths


def _session(paths: PathResolver, session_id: str = "session-1") -> Path:
    session = paths.online_mr_session_dir("demo", "MR-1", session_id)
    for name in ("raw", "parsed", "view", "logs", "outputs"):
        (session / name).mkdir(parents=True, exist_ok=True)
    (session / "raw" / "mesh_link_raw.log").write_text("managed", encoding="utf-8")
    (session / "parsed" / "online_diagnosis.sqlite").write_bytes(b"sqlite")
    return session


def test_delete_session_removes_only_managed_session_and_associated_artifacts(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    session = _session(paths)
    outside = tmp_path / "external-source.log"
    outside.write_text("must remain", encoding="utf-8")
    report = paths.online_mr_root("demo") / "reports" / "session-1_online_mr.xlsx"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_bytes(b"xlsx")
    manifest = (
        paths.rail_transit_root("demo")
        / "web_artifacts"
        / "manifests"
        / "artifact-1.json"
    )
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text("{}", encoding="utf-8")

    result = OnlineMrSessionLifecycleService(paths).delete_session(
        site_id="demo",
        session_id="session-1",
        session_dir=session,
        artifact_items=[
            {
                "path": str(report),
                "manifest_path": str(manifest),
                "task_id": "report-1",
            }
        ],
        related_task_ids=["report-1"],
    )

    assert result["status"] == "SUCCESS"
    assert result["session_deleted"] is True
    assert result["parsed_data_deleted"] is True
    assert result["artifacts_deleted"] is True
    assert result["managed_files_deleted"] is True
    assert not session.exists()
    assert not report.exists()
    assert not manifest.exists()
    assert outside.read_text(encoding="utf-8") == "must remain"


@pytest.mark.parametrize(
    "candidate",
    ("managed-root", "outside"),
)
def test_delete_session_rejects_root_and_outside_paths(
    tmp_path: Path,
    candidate: str,
) -> None:
    paths = _paths(tmp_path)
    _session(paths)
    selected = (
        paths.online_mr_root("demo")
        if candidate == "managed-root"
        else tmp_path / "external-session"
    )
    selected.mkdir(parents=True, exist_ok=True)

    with pytest.raises(OnlineMrSessionLifecycleError) as raised:
        OnlineMrSessionLifecycleService(paths).delete_session(
            site_id="demo",
            session_id="session-1",
            session_dir=selected,
        )

    assert raised.value.code in {
        "SESSION_PATH_PROTECTED",
        "SESSION_PATH_OUTSIDE_MANAGED_ROOT",
    }
    assert selected.exists()


def test_delete_session_rejects_active_task_resource(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    session = _session(paths)
    TaskRepository(paths.site_tasks_db_path("demo")).save(
        TaskSnapshot(
            task_id="parse-running",
            task_type="online_mr_parse",
            task_name="解析 Online MR",
            status=TaskState.RUNNING,
            created_time="2026-07-23T10:00:00Z",
            updated_time="2026-07-23T10:00:01Z",
            site_name="demo",
            resource_keys=[online_mr_session_resource_key("demo", "session-1")],
        )
    )

    with pytest.raises(OnlineMrSessionLifecycleError) as raised:
        OnlineMrSessionLifecycleService(paths).delete_session(
            site_id="demo",
            session_id="session-1",
            session_dir=session,
        )

    assert raised.value.code == "ONLINE_MR_SESSION_TASK_ACTIVE"
    assert session.exists()


def test_database_failure_restores_original_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _paths(tmp_path)
    session = _session(paths)

    def fail_database(*_args, **_kwargs):
        raise RuntimeError("database locked")

    monkeypatch.setattr(
        OnlineMrTaskSessionRepository,
        "delete_session_records",
        fail_database,
    )
    result = OnlineMrSessionLifecycleService(paths).delete_session(
        site_id="demo",
        session_id="session-1",
        session_dir=session,
    )

    assert result["terminal_state"] == "FAILED"
    assert result["session_deleted"] is False
    assert result["failed_items"] == ["database_records"]
    assert session.is_dir()
    assert (session / "raw" / "mesh_link_raw.log").is_file()


def test_file_cleanup_failure_returns_partial_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _paths(tmp_path)
    session = _session(paths)
    service = OnlineMrSessionLifecycleService(paths)

    def fail_cleanup(_path: Path) -> None:
        raise OSError("file busy")

    monkeypatch.setattr(service, "_safe_remove_tree", fail_cleanup)
    result = service.delete_session(
        site_id="demo",
        session_id="session-1",
        session_dir=session,
    )

    assert result["status"] == "PARTIAL_SUCCESS"
    assert result["session_deleted"] is True
    assert result["managed_files_deleted"] is False
    assert result["failed_items"] == ["managed_session_files"]
    assert not session.exists()
    quarantine = paths.online_mr_root("demo") / ".deleted_sessions"
    assert any(quarantine.iterdir())
