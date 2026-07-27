from __future__ import annotations

import json
from pathlib import Path

import pytest

from netconsole.adapters.trackside_switch import (
    H3CTracksideSwitchAdapter,
    ZteZxr10TracksideSwitchAdapter,
    resolve_trackside_switch_adapter,
)
from netconsole.models.device import Device


FIXTURES = Path(__file__).parent / "fixtures" / "zte"


class _FakeConnection:
    def __init__(self, outputs: dict[str, str]) -> None:
        self.outputs = outputs
        self.commands: list[str] = []

    def send_command_timing(self, command: str, **_kwargs) -> str:
        self.commands.append(command)
        try:
            return self.outputs[command]
        except KeyError as exc:
            raise AssertionError(f"unexpected command: {command}") from exc


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_adapter_registry_keeps_vendor_selection_out_of_application_service() -> None:
    h3c = resolve_trackside_switch_adapter(
        Device(name="H3C", device_vendor="H3C", device_type="SW")
    )
    zte = resolve_trackside_switch_adapter(
        Device(name="ZTE", device_vendor="ZTE", device_type="SW")
    )

    assert isinstance(h3c, H3CTracksideSwitchAdapter)
    assert isinstance(zte, ZteZxr10TracksideSwitchAdapter)
    assert zte.capability_manifest() == {
        "vendor": "ZTE",
        "platform_family": "ZXR10",
        "model_family": "5960X-ES",
        "command_profile_version": "zte_zxr10_5960x_es_v2",
        "capabilities": {
            "ssh_readonly": True,
            "device_identity": True,
            "interface_inventory": True,
            "interface_status": True,
            "interface_detail": True,
            "lldp_neighbors": True,
            "lldp_interface_neighbor": True,
            "optical_dom_summary": True,
            "optical_dom_detail": True,
            "bidirectional_attenuation": False,
            "configuration_write": False,
        },
    }

    with pytest.raises(ValueError, match="vendor_not_supported"):
        resolve_trackside_switch_adapter(
            Device(name="HW", device_vendor="Huawei", device_type="SW")
        )


def test_zte_adapter_uses_confirmed_commands_and_writes_raw_artifacts(
    tmp_path: Path,
) -> None:
    device = Device(
        device_uuid="11111111-1111-4111-8111-111111111111",
        name="ZTE-SW",
        device_vendor="ZTE",
        device_type="SW",
    )
    adapter = ZteZxr10TracksideSwitchAdapter(device)
    interface_brief = "\n".join(
        (
            "ZXR10#show interface brief",
            "Interface Attribute Mode BW Admin Phy Prot Description",
            "xgei-0/1/1/2 optical Duplex/full 10G up up up Trackside AP 01",
            "ZXR10#",
        )
    )
    optical_brief = "\n".join(
        (
            "ZXR10#show opticalinfo brief",
            "Interface Type Wavelength RxPower(dBm) TxPower(dBm) Status",
            "xgei-0/1/1/2 10G-300m-SFP+ 850nm "
            "-11.9/[-11.1,0.5] -2.8/[-7.3,-1.0] Unknown",
            "ZXR10#",
        )
    )
    interface_detail = "\n".join(
        (
            "xgei-0/1/1/2 is up, ifindex: 101",
            "Line protocol is up, IPv4 protocol is down, IPv6 protocol is down,",
            "detected status is RX-OK/TX-OK",
            "Last physical up time : 2026-07-28 10:00:00",
            "The port is optical",
            "Negotiation auto",
            "Hardware is Ethernet, address is 0011.2233.4455",
            "BW 10000 Mbit/s",
        )
    )
    outputs = {
        "show version": _fixture("zte_5960x_show_version.txt"),
        "show interface brief": interface_brief,
        "show opticalinfo brief": optical_brief,
        "show interface xgei-0/1/1/2": interface_detail,
        "show opticalinfo xgei-0/1/1/2": _fixture(
            "zte_5960x_show_opticalinfo_detail.txt"
        ),
        "show lldp config": "LLDP is enabled",
        "show lldp entry interface xgei-0/1/1/2": (
            "Local Interface: xgei-0/1/1/2\nRemote System Name: AP-01"
        ),
    }
    connection = _FakeConnection(outputs)
    artifact_dir = tmp_path / "raw" / "zte-switch"

    result = adapter.collect(connection, artifact_dir=artifact_dir)

    assert connection.commands == [
        "show version",
        "show interface brief",
        "show opticalinfo brief",
        "show interface xgei-0/1/1/2",
        "show opticalinfo xgei-0/1/1/2",
        "show lldp config",
        "show lldp entry interface xgei-0/1/1/2",
    ]
    assert "terminal length 0" not in connection.commands
    assert result.identity["software_version"] == "V2.00.20.03B07"
    assert result.interfaces[0]["interface_name"] == "xgei-0/1/1/2"
    assert result.interfaces[0]["ifindex"] == 101
    assert result.optical_modules[0]["rx_power"] == -11.904
    assert result.optical_modules[0]["status"] == "unverified"
    assert result.lldp_status == "SAMPLE_REQUIRED"
    assert result.lldp_neighbors == []
    assert (artifact_dir / "version.txt").read_text(encoding="utf-8").startswith(
        "ZXR10#show version"
    )
    manifest = json.loads(
        (artifact_dir / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["device_uuid"] == device.device_uuid
    assert manifest["lldp_status"] == "SAMPLE_REQUIRED"
    assert manifest["capabilities"]["configuration_write"] is False
    assert "password" not in json.dumps(manifest, ensure_ascii=False).casefold()


def test_zte_lldp_sampling_chain_is_fixed_and_interface_is_validated() -> None:
    adapter = ZteZxr10TracksideSwitchAdapter(
        Device(name="ZTE", device_vendor="ZTE", device_type="SW")
    )

    assert adapter.lldp_sampling_commands("xgei-0/1/1/2") == (
        "show lldp config",
        "show lldp config interface xgei-0/1/1/2",
        "show lldp entry interface xgei-0/1/1/2",
        "show lldp statistic interface xgei-0/1/1/2",
    )
    with pytest.raises(ValueError, match="不安全"):
        adapter.lldp_sampling_commands("xgei-0/1/1/2; reload")
