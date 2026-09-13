from __future__ import annotations

from pathlib import Path

import pytest

from netconsole.models.device import Device
from netconsole.core.paths import PathResolver
from netconsole.services import netmiko_connection
from netconsole.services.device_command_profile_service import DeviceCommandProfileNotFound
from netconsole.services.h3c_capability_bootstrap import probe_h3c_comware_version


ROOT = Path(__file__).resolve().parents[1]


class _ProbeConnection:
    def __init__(self, output: str) -> None:
        self.output = output
        self.commands: list[str] = []

    def send_command_timing(self, command: str, **_kwargs) -> str:
        self.commands.append(command)
        return self.output

    def disconnect(self) -> None:
        return None


def _device() -> Device:
    return Device(
        device_uuid="00000000-0000-4000-8000-000000000009",
        name="H3C-AC",
        primary_address="192.0.2.251",
        device_vendor="H3C",
        device_type="AC",
        ssh_enabled=1,
        ssh_username="test-user",
        ssh_password="test-password",
    )


def test_version_bootstrap_parses_actual_v9_release_before_capability_plan(
    monkeypatch, tmp_path: Path
) -> None:
    output = (
        "H3C WX3540X uptime is 3 weeks, 2 days\n"
        "H3C Comware Software, Version 9.1.081, Release 1615P01"
    )
    connection = _ProbeConnection(output)
    monkeypatch.setattr(
        netmiko_connection,
        "ConnectHandler",
        lambda **_kwargs: connection,
    )

    probe = probe_h3c_comware_version(
        _device(),
        paths=PathResolver(
            app_root=ROOT,
            data_root=tmp_path / "data",
        ),
        site_id="demo",
        collector="test",
        context="ac_info_collect",
    )

    assert connection.commands == ["display version"]
    assert probe.facts.platform == "comware"
    assert probe.facts.software_major == "V9"
    assert probe.facts.software_release == "R1615P01"


def test_version_bootstrap_rejects_unresolved_major_without_v7_fallback(
    monkeypatch, tmp_path: Path
) -> None:
    connection = _ProbeConnection("H3C WX3540X uptime is 3 weeks, 2 days")
    monkeypatch.setattr(
        netmiko_connection,
        "ConnectHandler",
        lambda **_kwargs: connection,
    )

    with pytest.raises(DeviceCommandProfileNotFound, match="H3C_COMWARE_MAJOR_UNRESOLVED"):
        probe_h3c_comware_version(
            _device(),
            paths=PathResolver(
                app_root=ROOT,
                data_root=tmp_path / "data",
            ),
            site_id="demo",
            collector="test",
            context="ac_info_collect",
        )
