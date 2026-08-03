from __future__ import annotations

import json
from pathlib import Path

import pytest

from netconsole.adapters.trackside_switch import (
    H3CTracksideSwitchAdapter,
    ZTE_PROFILE_ID,
    ZteZxr10TracksideSwitchAdapter,
    resolve_trackside_switch_adapter,
    trackside_switch_command_profile,
)
from netconsole.models.trackside_switch import CommandCapabilityState
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
    manifest = zte.capability_manifest()
    assert manifest["vendor"] == "ZTE"
    assert manifest["platform_family"] == "ZXR10"
    assert manifest["model_family"] == "5960X-ES"
    assert manifest["command_profile_version"] == ZTE_PROFILE_ID
    assert manifest["adaptation_status"] == (
        "C89E-4 Release 已验证；其他 ZXR10/5960X 型号需逐型号复核"
    )
    assert manifest["verification_status"] == "REAL_DEVICE_PENDING"
    assert manifest["capabilities"]["lldp_neighbors"] is True
    assert manifest["capabilities"]["lldp_interface_neighbor"] is False
    assert manifest["capabilities"]["bidirectional_attenuation"] is False
    assert manifest["capabilities"]["configuration_write"] is False
    statuses = {
        item["key"]: item["status"]
        for item in manifest["capability_statuses"]
    }
    assert statuses["lldp"] == CommandCapabilityState.VERIFIED.value
    assert statuses["bidirectional_attenuation"] == (
        CommandCapabilityState.SAMPLE_REQUIRED.value
    )
    profile = trackside_switch_command_profile(ZTE_PROFILE_ID)
    assert profile.product_family == "5960X-ES"
    assert profile.reference_version == "V2.00.20.03"

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
        "show lldp neighbor brief": _fixture(
            "hzdt10_show_lldp_neighbor_brief.txt"
        ),
        "show lldp entry": _fixture("hzdt10_show_lldp_entry.txt"),
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
        "show lldp neighbor brief",
        "show lldp entry",
    ]
    assert "terminal length 0" not in connection.commands
    assert result.identity["software_version"] == "V2.00.20.03B07"
    assert result.interfaces[0]["interface_name"] == "xgei-0/1/1/2"
    assert result.interfaces[0]["ifindex"] == 101
    assert result.optical_modules[0]["rx_power"] == -11.904
    assert result.optical_modules[0]["status"] == "no_light"
    assert result.lldp_status == "VERIFIED"
    assert len(result.lldp_neighbors) == 36
    assert (artifact_dir / "version.txt").read_text(encoding="utf-8").startswith(
        "ZXR10#show version"
    )
    manifest = json.loads(
        (artifact_dir / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["device_uuid"] == device.device_uuid
    assert manifest["lldp_status"] == "VERIFIED"
    assert manifest["capabilities"]["configuration_write"] is False
    assert "password" not in json.dumps(manifest, ensure_ascii=False).casefold()


def test_zte_optical_fast_path_uses_one_brief_for_many_modules(
    tmp_path: Path,
) -> None:
    device = Device(
        device_uuid="11111111-1111-4111-8111-222222222222",
        name="ZTE-FAST",
        device_vendor="ZTE",
        device_type="SW",
    )
    rows = [
        (
            f"xgei-0/1/1/{index} 10G-10km-SFP+ 1310nm "
            "-7.0/[-28.2,0.0] -5.0/[-10.0,-0.5] Normal"
        )
        for index in range(1, 31)
    ]
    interface_rows = [
        f"xgei-0/1/1/{index} optical Duplex/full 10G up up up Trackside-AP"
        for index in range(1, 31)
    ]
    connection = _FakeConnection(
        {
            "show version": _fixture("zte_5960x_show_version.txt"),
            "show interface brief": "\n".join(
                [
                    "Interface Attribute Mode BW Admin Phy Prot Description",
                    *interface_rows,
                ]
            ),
            "show opticalinfo brief": "\n".join(
                [
                    "Interface Type Wavelength RxPower(dBm) TxPower(dBm) Status",
                    *rows,
                ]
            ),
        }
    )

    result = ZteZxr10TracksideSwitchAdapter(device).collect(
        connection,
        artifact_dir=tmp_path / "fast",
        optical_fast_only=True,
    )

    assert connection.commands == [
        "show version",
        "show interface brief",
        "show opticalinfo brief",
    ]
    assert len(result.optical_modules) == 30
    assert len(result.interfaces) == 30
    assert result.interfaces[0]["link_status"] == "UP"
    assert result.interface_snapshot_status == "OK"
    assert result.optical_snapshot_status == "OK"
    assert result.lldp_neighbors == []


def test_zte_lldp_sampling_chain_is_fixed_and_interface_is_validated() -> None:
    adapter = ZteZxr10TracksideSwitchAdapter(
        Device(name="ZTE", device_vendor="ZTE", device_type="SW")
    )

    assert adapter.lldp_sampling_commands("xgei-0/1/1/2") == (
        "show lldp neighbor brief",
        "show lldp entry",
    )
    plan = adapter.build_command_plan(
        selected_interface="xgei-0/1/1/2",
        requested_commands=("lldp_global", "lldp_interface"),
    )
    assert [item.command for item in plan.items] == [
        "show lldp neighbor brief",
        "show lldp entry",
    ]
    assert all(
        item.status is CommandCapabilityState.IMPLEMENTED
        and not item.candidate
        for item in plan.items
    )
    with pytest.raises(ValueError, match="不安全"):
        adapter.lldp_sampling_commands("xgei-0/1/1/2; reload")
