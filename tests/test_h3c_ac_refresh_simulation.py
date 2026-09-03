from __future__ import annotations

from pathlib import Path

import netmiko
import paramiko

from netconsole.core import app_logger
from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.repositories.ac_repository import AcRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.background_job import BackgroundJob
from netconsole.services.job_center.job_runner import run_job
from netconsole.adapters.h3c.h3c_command_profile import H3cAcCommandProfile


ROOT = Path(__file__).resolve().parents[1]


class _FakeH3cR1612P01Connection:
    outputs = {
        "screen-length disable": "<HZDT09X-WX3540X-AC1>",
        "display cpu-usage": (
            "0% in last 5 seconds\n"
            "1% in last 1 minute\n"
            "2% in last 5 minutes"
        ),
        "display memory": "Mem: 100000 40000 60000 60%",
        "display version": (
            "H3C WX3540X uptime is 3 weeks, 2 days\n"
            "H3C Comware Software, Version 9.1.081, Release 1612P01"
        ),
        "display device": (
            "Slot No. Board Type Status Software Version\n"
            "1 WX3540X Master Normal COMWAREV900R001"
        ),
        "display device manuinfo": (
            "Chassis self\n"
            "DEVICE_NAME          : H3C WX3540X\n"
            "DEVICE_SERIAL_NUMBER : WX3540X-SN-001\n"
            "MAC_ADDRESS          : 105E-AE3E-0700\n"
            "VENDOR_NAME          : H3C\n"
            "Slot 1"
        ),
        "display ip https": "HTTPS port : 443",
        "display ip https | include port": "HTTPS port : 443",
    }

    def __init__(self, commands: list[str]) -> None:
        self.commands = commands

    def send_command_timing(self, command: str, **_kwargs) -> str:
        self.commands.append(command)
        return self.outputs.get(command, "<HZDT09X-WX3540X-AC1>")

    def disconnect(self) -> None:
        return None


def test_simulated_h3c_r1612p01_ac_refresh_uses_legacy_retry_and_persists(
    monkeypatch, tmp_path: Path
) -> None:
    paths = PathResolver(app_root=ROOT, data_root=tmp_path / "data")
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    device = DeviceRepository(database).create(
        Device(
            device_uuid="00000000-0000-4000-8000-000000001612",
            name="HZDT09X-WX3540X-AC1",
            primary_address="192.0.2.209",
            device_vendor="H3C",
            device_type="AC",
            ssh_enabled=1,
            ssh_port=22,
            ssh_username="admin",
            ssh_password="test-password",
        )
    )

    calls: list[dict[str, object]] = []
    commands: list[str] = []
    events: list[tuple[str, str]] = []

    def fake_connect_handler(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise paramiko.SSHException("server only offered ssh-rsa")
        return _FakeH3cR1612P01Connection(commands)

    monkeypatch.setattr(netmiko, "ConnectHandler", fake_connect_handler)
    monkeypatch.setattr(
        app_logger,
        "log_info",
        lambda event, detail="", **_kwargs: events.append((event, detail)),
    )
    monkeypatch.setattr(
        app_logger,
        "log_warning",
        lambda event, detail="", **_kwargs: events.append((event, detail)),
    )

    progress: list[str] = []
    result = run_job(
        BackgroundJob(
            job_id="simulated-h3c-r1612p01-refresh",
            task_type="ac_info_refresh",
            params={
        "device_uuid": device.device_uuid,
                "site_name": "demo",
                "db_path": str(database.path),
                "app_root": str(paths.app_root),
                "data_root": str(paths.data_root),
            },
        ),
        progress_callback=lambda _stage, _current, _total, message: progress.append(
            str(message)
        ),
    )

    assert isinstance(result.result, dict)
    assert result.ok is True
    assert result.result["success"] is True
    assert result.result["business_outcome"] == "SUCCESS"
    assert result.result["persisted_components"] == ["AC_BASIC"]
    assert result.result["failed_components"] == []
    assert result.result["data_persisted"] is True
    assert "AC 信息已持久化" in progress
    assert len(calls) == 2
    assert "disabled_algorithms" not in calls[0]
    assert calls[1]["disabled_algorithms"] == {
        "keys": ["rsa-sha2-512", "rsa-sha2-256"]
    }
    command_profile = H3cAcCommandProfile(device)
    assert command_profile.version == "V9"
    assert commands == list(command_profile.ac_info_commands)

    connection_events = [
        detail for event, detail in events if event == "ssh_connection_attempt"
    ]
    assert any(
        "collector=ac_basic" in detail
        and "phase=collect" in detail
        and "device_uuid=00000000-0000-4000-8000-000000001612" in detail
        and "host=192.0.2.209" in detail
        and "ssh_mode=normal" in detail
        and "attempt=1" in detail
        and "result=negotiation_failed" in detail
        for detail in connection_events
    )
    assert any(
        "collector=ac_basic" in detail
        and "ssh_mode=legacy_ssh_rsa" in detail
        and "attempt=2" in detail
        and "result=success" in detail
        for detail in connection_events
    )

    summary = AcRepository(database).get_ac_ap_summary(device.device_uuid)
    assert summary is not None
    assert summary["model"] == "H3C WX3540X"
    assert summary["software_version"] == "Version 9.1.081 Release 1612P01"
    assert DeviceRepository(database).get_by_uuid(device.device_uuid).https_port == 443
