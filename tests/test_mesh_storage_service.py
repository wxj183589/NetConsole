from __future__ import annotations

from datetime import datetime
from hashlib import sha256

import pytest

from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.services.mesh_storage_service import MeshStorageService


def test_mr_profile_identity_for_device_never_opens_parsed_repository(tmp_path, monkeypatch) -> None:
    paths = PathResolver(data_root=tmp_path)
    storage = MeshStorageService("demo", paths)
    opened: list[object] = []

    def fail_if_opened(*args, **kwargs):
        opened.append((args, kwargs))
        raise AssertionError("identity sync must not open parsed MESH database")

    monkeypatch.setattr("netconsole.services.mesh_storage_service.MeshMrRepository", fail_if_opened)
    device = Device(id=1, device_uuid=Device.new_uuid(), name="列车01-MR-CT", device_type="MR")

    profile = storage.ensure_mr_profile_identity_for_device(device)
    same_profile = storage.ensure_mr_profile_identity_for_device(
        Device(id=1, device_uuid=device.device_uuid, name="列车01-MR-CT-改名", device_type="MR")
    )

    assert opened == []
    assert same_profile.mr_id == profile.mr_id
    assert same_profile.display_name == "列车01-MR-CT-改名"
    assert paths.mesh_mr_raw_dir("demo", profile.safe_folder_name).is_dir()
    assert paths.mesh_mr_parsed_dir("demo", profile.safe_folder_name).is_dir()


@pytest.mark.parametrize("size", [10 * 1024, 64 * 1024, 256 * 1024, 1024 * 1024])
def test_raw_collection_archive_preserves_full_sha256(tmp_path, size: int) -> None:
    paths = PathResolver(data_root=tmp_path)
    storage = MeshStorageService("demo", paths)
    device = Device(
        id=1,
        device_uuid=Device.new_uuid(),
        name="列车01-MR-CT",
        device_type="MR",
    )
    profile = storage.ensure_mr_profile_identity_for_device(device)
    source = tmp_path / "meshlog.log"
    payload = bytes(index % 251 for index in range(size))
    source.write_bytes(payload)

    archived = storage.archive_raw_file_with_metadata(
        profile,
        source,
        datetime(2026, 8, 10, 12, 0, 0),
    )

    assert archived.path.stat().st_size == size
    assert sha256(archived.path.read_bytes()).digest() == sha256(payload).digest()
