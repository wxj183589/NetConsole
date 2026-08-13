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
from tests.support.web_parity_test_support import FakeLocalProcessAdapter


def _bundle_bytes() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("01CTmeshlog.log", b"preview")
    return output.getvalue()


def _mesh_log(timestamp: str) -> bytes:
    active_timestamp = timestamp.rsplit(".", 1)[0]
    return (
        f"[1] {timestamp}\n"
        f"[1] Active 30f5-277a-5a2f {active_timestamp} 0d 00h 00m 03s 1 "
        "36/43 2%/4% 45%/47% 3/1 15/27 60/72060 88/105 0/5000 "
        "2/297 314/0 0/93 0/0 0/0 0/0\n"
    ).encode()


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
        "skipped_count": 0,
        "warnings": [],
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


def test_prepare_import_context_skips_one_invalid_mr_and_keeps_other_profiles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    tasks = TaskApplicationService(paths=paths, site_name="demo")
    base_query = _VehicleMrPages()
    application = MeshBundleApplicationService(
        paths,
        tasks,
        FakeLocalProcessAdapter(tasks),  # type: ignore[arg-type]
        base_query,  # type: ignore[arg-type]
    )
    original = MeshStorageService.ensure_mr_profile_for_asset

    def fail_one_profile(self, *, device_id: int, device_uuid: str, display_name: str):
        if device_id == 6:
            raise ValueError("invalid fixture MR")
        return original(
            self,
            device_id=device_id,
            device_uuid=device_uuid,
            display_name=display_name,
        )

    monkeypatch.setattr(MeshStorageService, "ensure_mr_profile_for_asset", fail_one_profile)

    result = application.prepare_import_context("demo")
    profiles = MeshStorageService("demo", paths).catalog.list_profiles()

    assert result["created_count"] == 1
    assert result["skipped_count"] == 1
    assert result["warnings"] == ["一条基础资料 MR 同步失败，已跳过该记录。"]
    assert [profile.display_name for profile in profiles] == ["列车34-MR-CT"]


def test_manual_profile_creation_rejects_duplicate_linked_mr(tmp_path: Path) -> None:
    storage = MeshStorageService("demo", PathResolver(app_root=tmp_path, data_root=tmp_path))
    storage.create_mr_profile(
        "列车34-MR-CT",
        linked_device_id=34,
        linked_device_uuid="vehicle-34-ct",
    )

    with pytest.raises(ValueError, match="MR already linked"):
        storage.create_mr_profile(
            "列车34-MR-CT-重复",
            linked_device_id=34,
            linked_device_uuid="vehicle-34-ct",
        )


def test_preview_files_accepts_duplicate_basenames_and_reserves_daily_sequences(
    tmp_path: Path,
) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    profile = MeshStorageService("demo", paths).create_mr_profile("列车34-MR-CT")
    tasks = TaskApplicationService(paths=paths, site_name="demo")
    application = MeshBundleApplicationService(
        paths,
        tasks,
        FakeLocalProcessAdapter(tasks),  # type: ignore[arg-type]
    )
    timestamps = (
        "2026/07/27 08:10:01.001",
        "2026/07/28 00:18:56.311",
        "2026/07/28 13:20:16.625",
        "2026/07/29 00:03:11.002",
    )

    preview = application.preview_files(
        "demo",
        [
            ("meshlog.log", io.BytesIO(_mesh_log(timestamp)))
            for timestamp in timestamps
        ],
    )
    items = preview["items"]

    assert len(items) == 4
    assert len({str(item["member_id"]) for item in items}) == 4
    assert [item["original_name"] for item in items] == ["meshlog.log"] * 4
    assert [item["stored_filename"] for item in items] == [
        "2026_07_27_1meshlog.log",
        "2026_07_28_1meshlog.log",
        "2026_07_28_2meshlog.log",
        "2026_07_29_1meshlog.log",
    ]
    assert all("__uploads__" not in str(item["stored_filename"]) for item in items)

    service = MeshBundleImportService("demo", paths)
    _preview_dir, _archive, _meta, manifest = service.load_preview(str(preview["preview_id"]))
    assert len({member.internal_member_name for member in manifest.members}) == 4
    assert all(member.internal_member_name.startswith("__uploads__/") for member in manifest.members)
    assert all(member.original_name == "meshlog.log" for member in manifest.members)
    assert all(profile.mr_id in {state["profile_id"] for state in item["profile_import_states"]} for item in items)
    mappings = [
        {
            "member_id": item["member_id"],
            "train_number": "34",
            "role": "CT",
            "profile_id": profile.mr_id,
        }
        for item in items
    ]
    _manifest, approved = service.approve_preview(
        str(preview["preview_id"]),
        mappings,
        [profile.mr_id],
    )

    result = service.import_approved_preview(
        str(preview["preview_id"]),
        approved,
        job_id="mesh-duplicate-basename-import",
    )

    assert result["imported_count"] == 4
    assert sorted(
        str(item["stored_filename"])
        for item in result["source_results"]
    ) == [
        "2026_07_27_1meshlog.log",
        "2026_07_28_1meshlog.log",
        "2026_07_28_2meshlog.log",
        "2026_07_29_1meshlog.log",
    ]


def test_preview_files_marks_same_content_as_batch_duplicate_despite_duplicate_names(
    tmp_path: Path,
) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    profile = MeshStorageService("demo", paths).create_mr_profile("列车34-MR-CT")
    tasks = TaskApplicationService(paths=paths, site_name="demo")
    application = MeshBundleApplicationService(
        paths,
        tasks,
        FakeLocalProcessAdapter(tasks),  # type: ignore[arg-type]
    )
    body = _mesh_log("2026/07/28 00:18:56.311")

    preview = application.preview_files(
        "demo",
        [("meshlog.log", io.BytesIO(body)), ("meshlog.log", io.BytesIO(body))],
    )

    assert [item["duplicate_status"] for item in preview["items"]] == [
        "new",
        "duplicate_in_current_batch",
    ]
    assert preview["items"][1]["batch_duplicate_of"] == preview["items"][0]["member_id"]
    assert preview["items"][1]["stored_filename"] == preview["items"][0]["stored_filename"]
    mappings = [
        {
            "member_id": item["member_id"],
            "train_number": "34",
            "role": "CT",
            "profile_id": profile.mr_id,
        }
        for item in preview["items"]
    ]
    service = MeshBundleImportService("demo", paths)
    _manifest, approved = service.approve_preview(
        str(preview["preview_id"]),
        mappings,
        [profile.mr_id],
    )

    result = service.import_approved_preview(
        str(preview["preview_id"]),
        approved,
        job_id="mesh-duplicate-content-import",
    )

    assert result["imported_count"] == 1
    assert result["duplicate_count"] == 1
    assert [
        str(item["stored_filename"])
        for item in result["source_results"]
    ] == ["2026_07_28_1meshlog.log"]


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
    member_id = str(preview["items"][0]["member_id"])
    mappings = [
        {
            "member_id": member_id,
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
