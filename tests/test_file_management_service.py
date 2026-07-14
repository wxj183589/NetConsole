from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from netconsole.backend.api.file_management_router import router
from netconsole.core.feature_flags import FeatureGate
from netconsole.core.paths import PathResolver
from netconsole.models.task_state import TaskState
from netconsole.services.background_job import BackgroundJob
from netconsole.services.file_management_service import (
    FileManagementApplicationService,
    FileReferenceNotFound,
    run_file_management_download,
)
from netconsole.services.job_center.job_context import JobContext
from netconsole.services.job_center.job_registry import dispatch_job
from netconsole.services.job_center.task_application_service import TaskApplicationService


def _fixture(tmp_path: Path) -> tuple[PathResolver, Path]:
    paths = PathResolver(tmp_path)
    paths.ensure_site_dirs("demo")
    source = paths.site_files_dir("demo") / "rail_transit" / "online_mr" / "MR-01" / "sessions" / "s1" / "raw" / "collector.log"
    source.parent.mkdir(parents=True)
    source.write_text("sample", encoding="utf-8")
    (source.parent.parent / "outputs").mkdir()
    (source.parent.parent / "outputs" / "report.xlsx").write_bytes(b"report")
    return paths, source


def _app(service: FileManagementApplicationService) -> FastAPI:
    app = FastAPI()
    app.state.paths = service.paths
    app.state.file_management_service = service
    app.state.feature_gate = FeatureGate(service.paths.app_root)
    app.include_router(router, prefix="/api")
    return app


def test_local_file_refs_are_opaque_and_path_escape_or_symlink_is_rejected(tmp_path: Path) -> None:
    paths, source = _fixture(tmp_path)
    service = FileManagementApplicationService(paths)
    page = service.list_files("demo")

    row = next(item for item in page.items if item.name == source.name)
    assert row.file_ref.startswith("fm1_")
    assert len(row.file_ref) == 36
    assert str(tmp_path) not in row.model_dump_json()
    assert service.resolve_ref("demo", row.file_ref).path == source.resolve()
    with pytest.raises(FileReferenceNotFound):
        service.resolve_ref("demo", "../outside")
    with pytest.raises(FileReferenceNotFound):
        service.resolve_ref("demo", "fm1_" + "0" * 32)

    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = paths.site_files_dir("demo") / "rail_transit" / "outside-link.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("当前 Windows 环境不允许创建测试符号链接")
    assert all(item.name != link.name for item in service.list_files("demo").items)


def test_local_file_index_excludes_databases_runtime_files_and_unknown_formats(tmp_path: Path) -> None:
    paths, _source = _fixture(tmp_path)
    files_root = paths.site_files_dir("demo")
    blocked = [
        files_root / "parsed" / "online_diagnosis.sqlite",
        files_root / "outputs" / "active.db-wal",
        files_root / "outputs" / "unknown.bin",
        files_root / "raw" / "private.key",
        files_root / "rail_transit" / "online_mr" / "imports" / "unknown.bin",
    ]
    for path in blocked:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"private")

    service = FileManagementApplicationService(paths)
    page = service.list_files("demo")

    assert not {path.name for path in blocked} & {item.name for item in page.items}
    for path in blocked:
        ref = service._file_ref("demo", path.relative_to(files_root).as_posix())
        with pytest.raises(FileReferenceNotFound):
            service.resolve_ref("demo", ref)


def test_download_job_only_validates_and_returns_original_ref_without_creating_files(tmp_path: Path) -> None:
    paths, source = _fixture(tmp_path)
    service = FileManagementApplicationService(paths)
    source_ref = next(item.file_ref for item in service.list_files("demo").items if item.name == source.name)
    before = {path.relative_to(paths.site_dir("demo")).as_posix() for path in paths.site_dir("demo").rglob("*") if path.is_file()}
    job = BackgroundJob(
        job_id="download-test",
        task_type="file_management_download",
        params={"site_name": "demo", "file_ref": source_ref, "app_root": str(paths.app_root), "data_root": str(paths.data_root)},
    )

    result = dispatch_job(job)

    after = {path.relative_to(paths.site_dir("demo")).as_posix() for path in paths.site_dir("demo").rglob("*") if path.is_file()}
    assert result == {"download_ref": source_ref, "name": source.name, "size_bytes": source.stat().st_size}
    assert before == after
    assert run_file_management_download(JobContext.from_job(job)) == result


def test_file_management_api_lists_filters_and_uses_controlled_download_task(tmp_path: Path) -> None:
    paths, source = _fixture(tmp_path)
    task_service = TaskApplicationService(paths=paths, site_name="demo")

    class FakeProcessAdapter:
        def start_job(self, job: BackgroundJob) -> str:
            task_service.prepare(job)
            return job.job_id

    service = FileManagementApplicationService(paths, task_service=task_service, process_adapter=FakeProcessAdapter())
    with TestClient(_app(service)) as client:
        response = client.get("/api/file-management/files", params={"site_id": "demo", "category": "raw"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["items"][0]["name"] == source.name
        assert str(tmp_path) not in response.text

        file_ref = payload["items"][0]["file_ref"]
        started = client.post("/api/file-management/downloads", params={"site_id": "demo"}, json={"file_ref": file_ref})
        assert started.status_code == 202
        task_id = started.json()["task_id"]
        assert started.json()["status"] in {TaskState.STARTING.value, TaskState.PENDING.value}
        snapshot = task_service.repository("demo").get(task_id)
        assert snapshot is not None
        assert snapshot.source == "local"
        assert snapshot.owner == "web_file_management"
        assert client.get(f"/api/file-management/downloads/{task_id}", params={"site_id": "demo"}).status_code == 200
        result = run_file_management_download(
            JobContext.from_job(
                BackgroundJob(
                    job_id=task_id,
                    task_type="file_management_download",
                    params={"site_name": "demo", "file_ref": file_ref, "app_root": str(paths.app_root), "data_root": str(paths.data_root)},
                )
            )
        )
        task_service.record_external_event(task_id, "finished", {"result": result}, site_name="demo")
        before_download = {path.relative_to(paths.site_dir("demo")).as_posix() for path in paths.site_dir("demo").rglob("*") if path.is_file()}
        downloaded = client.get(f"/api/file-management/downloads/{task_id}/file", params={"site_id": "demo"})
        after_download = {path.relative_to(paths.site_dir("demo")).as_posix() for path in paths.site_dir("demo").rglob("*") if path.is_file()}
        assert downloaded.status_code == 200
        assert downloaded.content == source.read_bytes()
        assert str(tmp_path) not in downloaded.headers.get("content-disposition", "")
        assert before_download == after_download
        assert client.post("/api/file-management/downloads", params={"site_id": "demo"}, json={"file_ref": "../outside"}).status_code == 422
