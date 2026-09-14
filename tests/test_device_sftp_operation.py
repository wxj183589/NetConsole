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
from netconsole.services.job_center.task_application_service import TaskApplicationService


def test_sftp_operation_starts_provisional_family_task_when_version_is_missing(tmp_path: Path) -> None:
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

        @staticmethod
        def current_site_id():
            return "demo"

    paths = PathResolver(tmp_path)
    paths.ensure_site_dirs("demo")
    task_service = TaskApplicationService(paths=paths, site_name="demo")

    class FakeProcessAdapter:
        def start_job(self, job: BackgroundJob) -> str:
            task_service.prepare(job)
            return job.job_id

    service = DeviceOperationService(
        paths,
        FakeGateway(),  # type: ignore[arg-type]
        task_service,
        FakeProcessAdapter(),  # type: ignore[arg-type]
    )

    task = service.start(str(device.device_uuid), "device.sftp.enable", allow_excluded=True)
    assert task.profile_id == "h3c.comware.switch.family.sftp-enable.v1"
    assert task.status in {"PENDING", "STARTING", "RUNNING"}


def test_sftp_operation_skips_non_h3c_without_starting_a_write_task(tmp_path: Path) -> None:
    device = Device(
        name="Huawei-AC",
        device_uuid=Device.new_uuid(),
        device_vendor="Huawei",
        device_type="AC",
    )

    class FakeGateway:
        @staticmethod
        def get_device(_device_uuid: str):
            return device

        @staticmethod
        def get_fact(_device_uuid: str):
            return {"software_version": "Version 9.1.081"}

        @staticmethod
        def current_site_id():
            return "demo"

    paths = PathResolver(tmp_path)
    paths.ensure_site_dirs("demo")
    task_service = TaskApplicationService(paths=paths, site_name="demo")
    started: list[str] = []

    class FakeProcessAdapter:
        def start_job(self, job: BackgroundJob) -> str:
            started.append(job.job_id)
            task_service.prepare(job)
            return job.job_id

    service = DeviceOperationService(
        paths,
        FakeGateway(),  # type: ignore[arg-type]
        task_service,
        FakeProcessAdapter(),  # type: ignore[arg-type]
    )

    task = service.start(str(device.device_uuid), "device.sftp.enable", allow_excluded=True)

    assert task.status == "SKIPPED"
    assert task.reason_code == "UNSUPPORTED_VENDOR"
    assert started == []


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


@pytest.mark.parametrize(
    ("version_output", "expected_major", "expected_profile"),
    (
        (
            "H3C Comware Software, Version 9.1.081, Release 1615P01\n[AC]",
            "V9",
            "h3c.comware.wireless_controller.family.sftp-enable.v1",
        ),
        (
            "H3C Comware Software, Version 7.1.070, Release R2619P08\n[AC]",
            "V7",
            "h3c.comware.wireless_controller.v7.sftp-enable.v1",
        ),
    ),
)
def test_sftp_worker_preflights_version_and_audits_supported_major(
    tmp_path: Path,
    monkeypatch,
    version_output: str,
    expected_major: str,
    expected_profile: str,
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
            name="AC-preflight",
            device_uuid=Device.new_uuid(),
            device_vendor="H3C",
            device_type="AC",
            primary_address="192.0.2.11",
            ssh_username="ops_01",
            ssh_password="secret",
        )
    )
    commands: list[str] = []
    events: list[dict[str, object]] = []

    def fake_safe_send(_connection, command, **_kwargs):
        commands.append(command)
        return version_output if command == "display version" else "ok"

    monkeypatch.setattr(
        "netconsole.services.device_operation_service.safe_send_command",
        fake_safe_send,
    )
    monkeypatch.setattr(
        "netconsole.services.device_operation_service.netmiko_connection.run_netmiko_with_retry",
        lambda _device, operation: operation(object(), object()),
    )
    job = BackgroundJob(
        job_id=f"device-sftp-preflight-{expected_major}",
        task_type="device_sftp_enable",
        params={
            "site_name": "demo",
            "device_uuids": [device.device_uuid],
            "operation_id": "device.sftp.enable",
            "profile_id": "h3c.comware.wireless_controller.family.sftp-enable.v1",
            "profile_version": 1,
            "platform_vendor": "H3C",
            "platform_role": "wireless_controller",
            "platform": "comware",
            "software_version": None,
            "platform_source": "fixture",
            "platform_confidence": "medium",
            "app_root": str(paths.app_root),
            "data_root": str(paths.data_root),
        },
    )

    result = run_device_sftp_enable(
        JobContext.from_job(
            job,
            progress_callback=lambda _stage, _current, _total, message: events.append(
                dict(message) if isinstance(message, dict) else {"message": message}
            ),
        )
    )

    assert result["detected_major"] == expected_major
    assert result["profile_id"] == expected_profile
    assert commands == [
        "display version",
        "system-view",
        "sftp server enable",
        "ssh user ops_01 service-type all authentication-type any",
        "return",
        "quit",
    ]
    assert [event["message"] for event in events] == [
        "SFTP_PREFLIGHT_STARTED",
        "SFTP_PREFLIGHT_VERSION",
        "SFTP_PROFILE_RESOLVED",
        "SFTP_ENABLE_STARTED",
        "SFTP_ENABLE_STEP",
        "SFTP_ENABLE_STEP",
        "SFTP_ENABLE_STEP",
        "SFTP_ENABLE_STEP",
        "SFTP_ENABLE_STEP",
        "SFTP_ENABLE_STEP",
        "SFTP_ENABLE_STEP",
        "SFTP_ENABLE_STEP",
        "SFTP_ENABLE_STEP",
        "SFTP_ENABLE_STEP",
        "SFTP_ENABLE_COMPLETED",
    ]
    assert all("secret" not in str(event) for event in events)


@pytest.mark.parametrize(
    "version_output",
    (
        "H3C Comware Software, Version 5.2.1, Release R0001P01\n[AC]",
        "display version\n[AC]",
    ),
)
def test_sftp_worker_fails_closed_without_writing_for_unsupported_or_unknown_major(
    tmp_path: Path,
    monkeypatch,
    version_output: str,
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
            name="AC-reject",
            device_uuid=Device.new_uuid(),
            device_vendor="H3C",
            device_type="AC",
            primary_address="192.0.2.12",
            ssh_username="ops_01",
            ssh_password="secret",
        )
    )
    commands: list[str] = []
    events: list[dict[str, object]] = []

    def fake_safe_send(_connection, command, **_kwargs):
        commands.append(command)
        return version_output

    monkeypatch.setattr(
        "netconsole.services.device_operation_service.safe_send_command",
        fake_safe_send,
    )
    monkeypatch.setattr(
        "netconsole.services.device_operation_service.netmiko_connection.run_netmiko_with_retry",
        lambda _device, operation: operation(object(), object()),
    )
    job = BackgroundJob(
        job_id="device-sftp-preflight-reject",
        task_type="device_sftp_enable",
        params={
            "site_name": "demo",
            "device_uuids": [device.device_uuid],
            "operation_id": "device.sftp.enable",
            "profile_id": "h3c.comware.wireless_controller.family.sftp-enable.v1",
            "profile_version": 1,
            "platform_vendor": "H3C",
            "platform_role": "wireless_controller",
            "platform": "comware",
            "software_version": None,
            "platform_source": "fixture",
            "platform_confidence": "medium",
            "app_root": str(paths.app_root),
            "data_root": str(paths.data_root),
        },
    )

    with pytest.raises(DeviceSftpEnableProfileUnresolved):
        run_device_sftp_enable(
            JobContext.from_job(
                job,
                progress_callback=lambda _stage, _current, _total, message: events.append(
                    dict(message) if isinstance(message, dict) else {"message": message}
                ),
            )
        )

    assert commands == ["display version"]
    assert events[-1]["message"] == "SFTP_ENABLE_FAILED"
    assert events[-1]["step"] == "sftp.preflight.version"
    assert events[-1]["reason"] == "unsupported_or_unrecognized_comware_major"
    assert all("secret" not in str(event) for event in events)
