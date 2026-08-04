from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from netconsole.application.web_artifacts import WebArtifactStore
from netconsole.backend.api.main import create_app
from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.models.task_snapshot import TaskSnapshot
from netconsole.models.task_state import TaskState
from netconsole.repositories.task_repository import TaskRepository
from netconsole.services.job_center.artifact_reconciliation import (
    ArtifactReconciliationService,
    ArtifactTaskBinding,
)
from netconsole.services.job_center.query_service import JobCenterQueryService
from netconsole.services.job_center.task_application_service import (
    TaskApplicationService,
)


OWNER = "web_command_reference"
SOURCE = "command_reference_export"
TASK_TYPE = "web_export_command_reference_markdown"
SOURCE_TASK_TYPES = {SOURCE: TASK_TYPE}


def _runtime(tmp_path: Path) -> tuple[
    PathResolver,
    TaskApplicationService,
    TaskRepository,
    WebArtifactStore,
]:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    Database(paths.site_db_path("demo")).initialize()
    task_service = TaskApplicationService(paths=paths, site_name="demo")
    repository = task_service.repository("demo")
    return paths, task_service, repository, WebArtifactStore(paths, task_service)


def _reserve(
    paths: PathResolver,
    store: WebArtifactStore,
    task_id: str,
):
    return store.reserve(
        site_id="demo",
        owner=OWNER,
        source=SOURCE,
        artifact_type="md",
        task_id=task_id,
        task_type=TASK_TYPE,
        output_root=(
            paths.site_files_dir("demo")
            / "command_reference"
            / "exports"
            / task_id
        ),
        preferred_name="NetConsole_命令说明.md",
    )


def _snapshot(task_id: str, status: TaskState, *, error: str = "") -> TaskSnapshot:
    return TaskSnapshot(
        task_id=task_id,
        task_type=TASK_TYPE,
        task_name="命令说明导出",
        status=status,
        created_time="2026-08-04T10:00:00Z",
        finished_time="2026-08-04T10:00:01Z",
        updated_time="2026-08-04T10:00:01Z",
        owner=OWNER,
        source="local",
        site_name="demo",
        error_message=error,
    )


def _completed_artifact(tmp_path: Path, task_id: str = "artifact-completed"):
    paths, task_service, repository, store = _runtime(tmp_path)
    reservation = _reserve(paths, store, task_id)
    reservation.output_path.write_text("命令说明", encoding="utf-8")
    repository.save(_snapshot(task_id, TaskState.COMPLETED))
    store.complete(reservation)
    return paths, task_service, repository, store, reservation


def test_completed_artifact_availability_tracks_delete_and_restore(
    tmp_path: Path,
) -> None:
    paths, _task_service, repository, _store, reservation = _completed_artifact(
        tmp_path
    )
    query = JobCenterQueryService(paths)

    available = query.get_task("demo", reservation.task_id)
    assert available is not None
    assert available.status == "COMPLETED"
    assert available.artifact_availability == "AVAILABLE"
    assert available.artifact_available is True
    assert available.downloadable is True
    assert available.artifact_download is not None

    reservation.output_path.unlink()
    missing = query.get_task("demo", reservation.task_id)
    assert missing is not None
    assert missing.status == "COMPLETED"
    assert missing.error_summary == ""
    assert missing.artifact_availability == "MISSING"
    assert missing.artifact_available is False
    assert missing.downloadable is False
    assert missing.artifact_download is None
    assert missing.missing_reason == "输出文件已不存在，可能已在资源管理器中删除。"

    reservation.output_path.write_text("命令说明", encoding="utf-8")
    restored = query.get_task("demo", reservation.task_id)
    assert restored is not None
    assert restored.artifact_availability == "AVAILABLE"
    assert restored.artifact_download is not None
    assert repository.get(reservation.task_id).status is TaskState.COMPLETED


def test_deleted_artifact_directory_and_unsafe_manifest_degrade_without_500(
    tmp_path: Path,
) -> None:
    paths, _task_service, _repository, store, reservation = _completed_artifact(
        tmp_path,
        "artifact-directory",
    )
    query = JobCenterQueryService(paths)

    shutil.rmtree(reservation.output_path.parent)
    missing = query.get_task("demo", reservation.task_id)
    assert missing is not None
    assert missing.artifact_availability == "MISSING"

    reservation.output_path.parent.mkdir(parents=True)
    reservation.output_path.write_text("命令说明", encoding="utf-8")
    manifest_path = store._manifest_path("demo", reservation.artifact_id)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["relative_path"] = "database/netconsole.db"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )

    invalid = query.get_task("demo", reservation.task_id)
    assert invalid is not None
    assert invalid.status == "COMPLETED"
    assert invalid.artifact_availability == "INVALID"
    assert invalid.artifact_download is None
    assert "受控目录" in str(invalid.missing_reason)


def test_reconciliation_rejects_a_site_root_resolved_outside_data_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, _task_service, repository, _store, reservation = _completed_artifact(
        tmp_path,
        "artifact-site-boundary",
    )
    snapshot = repository.get(reservation.task_id)
    assert snapshot is not None
    original = PathResolver.site_dir
    outside = tmp_path.parent / "outside-site-root"

    def escaped_site(resolver: PathResolver, site_name: str = "demo") -> Path:
        if resolver is paths and site_name == "demo":
            return outside
        return original(resolver, site_name)

    monkeypatch.setattr(PathResolver, "site_dir", escaped_site)
    invalid = ArtifactReconciliationService(paths).reconcile_task(
        "demo",
        ArtifactTaskBinding(
            task_id=snapshot.task_id,
            task_type=snapshot.task_type,
            owner=snapshot.owner,
            status=snapshot.status.value,
            result=snapshot.result,
            downloadable=True,
        ),
    )

    assert invalid.artifact_availability.value == "INVALID"
    assert invalid.downloadable is False
    assert invalid.missing_reason == "局点数据目录不在受控数据根"


def test_completed_missing_artifact_recovery_is_idempotent_and_keeps_terminal_state(
    tmp_path: Path,
) -> None:
    paths, _task_service, repository, store = _runtime(tmp_path)
    reservation = _reserve(paths, store, "completed-missing-recovery")
    repository.save(_snapshot(reservation.task_id, TaskState.COMPLETED))
    events_before = repository.list_events(reservation.task_id)

    assert store.recover_task(
        "demo",
        reservation.task_id,
        owner=OWNER,
        source_task_types=SOURCE_TASK_TYPES,
        succeeded=True,
    ) is False
    assert store.recover_task(
        "demo",
        reservation.task_id,
        owner=OWNER,
        source_task_types=SOURCE_TASK_TYPES,
        succeeded=True,
    ) is False

    persisted = repository.get(reservation.task_id)
    assert persisted is not None
    assert persisted.status is TaskState.COMPLETED
    assert persisted.error_message == ""
    assert repository.list_events(reservation.task_id) == events_before


@pytest.mark.parametrize("status", [TaskState.FAILED, TaskState.CANCELLED])
def test_unsuccessful_terminal_recovery_only_discards_partial_artifact(
    tmp_path: Path,
    status: TaskState,
) -> None:
    paths, _task_service, repository, store = _runtime(tmp_path)
    task_id = f"terminal-{status.value.casefold()}"
    reservation = _reserve(paths, store, task_id)
    reservation.output_path.write_text("partial", encoding="utf-8")
    repository.save(_snapshot(task_id, status, error="真实任务失败原因"))
    events_before = repository.list_events(task_id)

    assert store.recover_task(
        "demo",
        task_id,
        owner=OWNER,
        source_task_types=SOURCE_TASK_TYPES,
        succeeded=False,
    ) is True
    assert store.recover_task(
        "demo",
        task_id,
        owner=OWNER,
        source_task_types=SOURCE_TASK_TYPES,
        succeeded=False,
    ) is False

    persisted = repository.get(task_id)
    assert persisted is not None
    assert persisted.status is status
    assert persisted.error_message == "真实任务失败原因"
    assert repository.list_events(task_id) == events_before
    assert not reservation.output_path.exists()


@pytest.mark.parametrize("output_exists", [True, False])
def test_non_terminal_artifact_is_not_finalized_by_terminal_recovery(
    tmp_path: Path,
    output_exists: bool,
) -> None:
    paths, _task_service, repository, store = _runtime(tmp_path)
    task_id = f"running-artifact-{'output' if output_exists else 'missing'}"
    reservation = _reserve(paths, store, task_id)
    if output_exists:
        reservation.output_path.write_text("still-running", encoding="utf-8")
    repository.save(_snapshot(task_id, TaskState.RUNNING))
    events_before = repository.list_events(task_id)

    assert store.recover_task(
        "demo",
        task_id,
        owner=OWNER,
        source_task_types=SOURCE_TASK_TYPES,
        succeeded=False,
    ) is False
    persisted = repository.get(task_id)
    assert persisted is not None and persisted.status is TaskState.RUNNING
    assert repository.list_events(task_id) == events_before
    assert reservation.output_path.exists() is output_exists


def test_job_center_missing_artifact_list_detail_and_download_contract(
    tmp_path: Path,
) -> None:
    paths, task_service, _repository, _store, reservation = _completed_artifact(
        tmp_path,
        "artifact-api-missing",
    )
    app = create_app(
        RuntimeMode.SERVER,
        paths=paths,
        task_service=task_service,
        frontend_dist=tmp_path / "missing-frontend",
    )
    reservation.output_path.unlink()

    with TestClient(app) as client:
        listing = client.get("/api/job-center/tasks")
        detail = client.get(f"/api/job-center/tasks/{reservation.task_id}")
        download = client.get(
            f"/api/job-center/artifacts/{reservation.artifact_id}"
        )

    assert listing.status_code == 200
    listed = next(item for item in listing.json() if item["id"] == reservation.task_id)
    assert listed["status"] == "COMPLETED"
    assert listed["artifact_availability"] == "MISSING"
    assert listed["artifact_download"] is None
    assert detail.status_code == 200
    assert detail.json()["artifact_availability"] == "MISSING"
    assert download.status_code == 404


def test_missing_tasks_database_site_and_data_root_return_empty_state(
    tmp_path: Path,
) -> None:
    empty_root = tmp_path / "new-empty-data-root"
    paths = PathResolver(app_root=tmp_path, data_root=empty_root)
    query = JobCenterQueryService(paths)

    assert query.list_tasks("demo") == []
    assert query.get_task("demo", "old-task") is None
    assert not paths.site_tasks_db_path("demo").exists()
