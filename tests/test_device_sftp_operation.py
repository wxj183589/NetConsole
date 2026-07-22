from __future__ import annotations

from pathlib import Path

import pytest

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.background_job import BackgroundJob
from netconsole.services.device_operation_service import (
    DeviceOperationService,
    DeviceSftpEnableProfileUnresolved,
    run_device_sftp_enable,
)
from netconsole.services.job_center.job_context import JobContext


def test_sftp_operation_refuses_write_when_software_version_is_unresolved(tmp_path: Path) -> None:
    device = Device(
        name="SW-unknown-version",
        device_uuid=Device.new_uuid(),
        device_vendor="H3C",
        device_type="SW",
    )

    class FakeGateway:
        @staticmethod
        def get_device(_device_uuid: str):
            return device

        @staticmethod
        def get_fact(_device_uuid: str):
            return {"vendor": "H3C", "software_version": None}

    service = DeviceOperationService(
        PathResolver(tmp_path),
        FakeGateway(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
    )

    with pytest.raises(DeviceSftpEnableProfileUnresolved, match="无法确认设备的软件版本"):
        service.start(str(device.device_uuid), "device.sftp.enable")


def test_sftp_worker_binds_username_only_inside_worker_and_keeps_profile_order(
    tmp_path: Path, monkeypatch
) -> None:
    paths = PathResolver(tmp_path)
    paths.ensure_site_dirs("demo")
    profile_source = Path(__file__).parents[1] / "resources" / "device_command_profiles.json"
    profile_target = paths.app_root / "resources" / profile_source.name
    profile_target.parent.mkdir(parents=True, exist_ok=True)
    profile_target.write_bytes(profile_source.read_bytes())
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    device = DeviceRepository(database).create(
        Device(
            name="MR-01",
            device_uuid=Device.new_uuid(),
            device_vendor="H3C",
            device_type="MR",
            primary_address="192.0.2.10",
            ssh_username="ops_01",
            ssh_password="secret",
        )
    )
    commands: list[str] = []

    monkeypatch.setattr(
        "netconsole.services.device_operation_service.safe_send_command",
        lambda _connection, command, **_kwargs: commands.append(command) or "ok",
    )

    def run_with_retry(_device, operation):
        return operation(object(), object())

    monkeypatch.setattr(
        "netconsole.services.device_operation_service.netmiko_connection.run_netmiko_with_retry",
        run_with_retry,
    )
    job = BackgroundJob(
        job_id="device-sftp-worker",
        task_type="device_sftp_enable",
        params={
            "site_name": "demo",
            "device_uuids": [device.device_uuid],
            "operation_id": "device.sftp.enable",
            "profile_id": "h3c.comware.mobile_router.v7.sftp-enable.v1",
            "profile_version": 1,
            "platform_vendor": "H3C",
            "platform_role": "mobile_router",
            "platform": "comware",
            "software_version": "V7",
            "platform_source": "fixture",
            "platform_confidence": "high",
            "app_root": str(paths.app_root),
            "data_root": str(paths.data_root),
        },
    )

    result = run_device_sftp_enable(JobContext.from_job(job))

    assert result["operation_id"] == "device.sftp.enable"
    assert commands == [
        "system-view",
        "sftp server enable",
        "ssh user ops_01 service-type all authentication-type any",
        "return",
        "quit",
    ]
    assert "secret" not in str(result)
