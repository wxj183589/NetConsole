from __future__ import annotations

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
