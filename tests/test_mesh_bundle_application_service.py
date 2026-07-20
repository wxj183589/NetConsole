from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from netconsole.application.rail_transit.mesh_bundle_application_service import (
    MeshBundleApplicationError,
    MeshBundleApplicationService,
)
from netconsole.core.paths import PathResolver
from netconsole.models.api.rail_transit_base_data import VehicleMrDTO, VehicleMrPageDTO
from netconsole.services.background_job import BackgroundJob
from netconsole.services.job_center.job_registry import dispatch_job, registered_task_types
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.mesh_bundle_import_service import MeshBundleImportService
from netconsole.services.mesh_storage_service import MeshStorageService
from tests.web_parity_test_support import FakeLocalProcessAdapter


def _bundle_bytes() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("01CTmeshlog.log", b"preview")
    return output.getvalue()


class _VehicleMrPages:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []
        self.first_name = "列车06-MR-CW"

    def list_mrs(self, _site_id: str, *, page: int, page_size: int) -> VehicleMrPageDTO:
        self.calls.append((page, page_size))
        rows = {
            1: [VehicleMrDTO(id="uuid-06-cw", device_id=6, name=self.first_name, train_no="06", role="CW")],
            2: [VehicleMrDTO(id="uuid-34-ct", device_id=34, name="列车34-MR-CT", train_no="34", role="CT")],
        }.get(page, [])
        return VehicleMrPageDTO(items=rows, total=2, page=page, page_size=page_size)


def test_prepare_import_context_is_paged_idempotent_and_keeps_safe_folder_on_rename(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    tasks = TaskApplicationService(paths=paths, site_name="demo")
    base_query = _VehicleMrPages()
    application = MeshBundleApplicationService(
        paths,
        tasks,
        FakeLocalProcessAdapter(tasks),  # type: ignore[arg-type]
        base_query,  # type: ignore[arg-type]
    )

    first = application.prepare_import_context("demo")
    storage = MeshStorageService("demo", paths)
    profiles = storage.catalog.list_profiles()
    original = next(item for item in profiles if item.linked_device_uuid == "uuid-06-cw")

    assert first == {
        "site_id": "demo",
        "vehicle_mr_count": 2,
        "profile_count": 2,
        "created_count": 2,
        "updated_count": 0,
    }
    assert base_query.calls == [(1, 200), (2, 200)]
    assert original.display_name == "列车06-MR-CW"

    base_query.calls.clear()
    base_query.first_name = "列车06-MR-CW-正式名"
    second = application.prepare_import_context("demo")
    renamed = storage.catalog.get_by_linked_device_uuid("uuid-06-cw")

    assert second["created_count"] == 0
    assert second["updated_count"] == 1
    assert len(storage.catalog.list_profiles()) == 2
    assert renamed is not None
    assert renamed.display_name == "列车06-MR-CW-正式名"
    assert renamed.safe_folder_name == original.safe_folder_name


def test_application_preview_confirmation_and_serializable_job_params(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    profile = MeshStorageService("demo", paths).create_mr_profile("01-MR-CT")
    tasks = TaskApplicationService(paths=paths, site_name="demo")
    adapter = FakeLocalProcessAdapter(tasks)
    application = MeshBundleApplicationService(paths, tasks, adapter)  # type: ignore[arg-type]

    preview = application.preview_bundle(
        "demo",
        file_name="bundle.zip",
        source=io.BytesIO(_bundle_bytes()),
    )
    mappings = [
        {
            "member_id": "01CTmeshlog.log",
            "train_number": "01",
            "role": "CT",
            "profile_id": profile.mr_id,
        }
    ]
    with pytest.raises(MeshBundleApplicationError) as confirmation:
        application.start_import(
            "demo",
            preview_id=str(preview["preview_id"]),
            mappings=mappings,
            explicit_confirmation=False,
        )
    assert confirmation.value.code == "CONFIRMATION_REQUIRED"

    task = application.start_import(
        "demo",
        preview_id=str(preview["preview_id"]),
        mappings=mappings,
        explicit_confirmation=True,
    )

    assert task.status == "RUNNING"
    assert task.action == "mesh_bundle_import"
    job = adapter.jobs[task.task_id]
    assert job.task_type == "mesh_bundle_import"
    assert "archive_path" not in job.params
    assert job.params["preview_id"] == preview["preview_id"]
    json.dumps(job.params)


def test_preview_token_expiry_is_enforced(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    profile = MeshStorageService("demo", paths).create_mr_profile("01-MR-CT")
    service = MeshBundleImportService("demo", paths)
    preview = service.create_preview("bundle.zip", io.BytesIO(_bundle_bytes()), [profile])
    preview_dir = paths.runtime_cache_dir / "mesh_bundle_previews" / "demo" / str(preview["preview_id"])
    meta_path = preview_dir / "preview.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["expires_at"] = 0
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    with pytest.raises(Exception, match="已过期"):
        service.load_preview(str(preview["preview_id"]))
    assert not preview_dir.exists()


def test_mesh_bundle_handler_is_registered_and_uses_job_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    events: list[tuple[str, int, int, object]] = []

    def fake_import(self, preview_id, mappings, **kwargs):
        assert self.site_name == "demo"
        assert preview_id == "a" * 32
        assert mappings[0]["member_id"] == "01CTmeshlog.log"
        kwargs["progress"]("mesh_bundle_import", 1, 1, "done")
        return {"imported_count": 1}

    monkeypatch.setattr(MeshBundleImportService, "import_approved_preview", fake_import)
    assert "mesh_bundle_import" in registered_task_types()
    result = dispatch_job(
        BackgroundJob(
            job_id="mesh-bundle-handler",
            task_type="mesh_bundle_import",
            params={
                "site_name": "demo",
                "app_root": str(paths.app_root),
                "data_root": str(paths.data_root),
                "preview_id": "a" * 32,
                "mappings": [
                    {
                        "member_id": "01CTmeshlog.log",
                        "train_number": "01",
                        "role": "CT",
                        "profile_id": "profile-1",
                    }
                ],
            },
        ),
        progress_callback=lambda stage, current, total, message: events.append(
            (stage, current, total, message)
        ),
    )

    assert result == {"imported_count": 1}
    assert events[-1][:3] == ("mesh_bundle_import", 1, 1)
