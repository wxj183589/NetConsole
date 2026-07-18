from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from netconsole.services import device_command_profile_service
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.services.device_command_profile_service import (
    DEVICE_INVENTORY_OPERATION_ID,
    DeviceCommandProfileError,
    DeviceCommandProfileNotFound,
    device_command_profile_path,
    default_device_inventory_profile,
    load_device_command_profiles,
    resolve_device_command_profile,
    resolve_device_inventory_profile,
)
from scripts.maintenance.audit_commands import (
    load_device_profile_commands,
    matches_profile_command,
)


RESOURCE_PATH = Path(__file__).parents[1] / "resources" / "device_command_profiles.json"
EXPECTED_COMMANDS = (
    "screen-length disable",
    "display current-configuration | include sysname",
    "display version",
    "display device",
    "display device manuinfo",
    "display boot-loader",
    "display interface",
    "display transceiver interface",
    "display transceiver manuinfo interface",
    "display transceiver diagnosis interface",
    "display lldp neighbor-information list",
    "display lldp neighbor-information verbose",
)


def test_device_inventory_profile_preserves_verified_command_order() -> None:
    profile = default_device_inventory_profile()

    assert profile.operation_id == DEVICE_INVENTORY_OPERATION_ID
    assert profile.profile_id == "h3c.comware.switch.generic.device-inventory.v1"
    assert profile.profile_version == 1
    assert profile.compatibility == "generic_read_only"
    assert profile.risk == "read_only"
    assert profile.fixture_versions == ("7.1.070",)
    assert profile.real_device_status == "real_device_pending"
    assert profile.commands == EXPECTED_COMMANDS
    assert [step.order for step in profile.steps] == list(range(10, 121, 10))
    assert len({step.step_id for step in profile.steps}) == len(profile.steps)
    assert len({step.selector for step in profile.steps}) == len(profile.steps)
    assert all(
        step.parser_contract
        and step.dto_contract
        and step.risk == "read_only"
        and step.guard_context == DEVICE_INVENTORY_OPERATION_ID
        and step.verification_evidence
        for step in profile.steps
    )


@pytest.mark.parametrize(
    ("vendor", "role", "platform"),
    (
        ("Huawei", "switch", "vrp"),
        ("ZTE", "switch", "zxr10"),
        ("H3C", "router", "comware"),
        ("H3C", "switch", "unknown"),
        ("", "switch", "comware"),
    ),
)
def test_profile_resolution_fails_closed_without_h3c_fallback(
    vendor: str,
    role: str,
    platform: str,
) -> None:
    with pytest.raises(DeviceCommandProfileNotFound):
        resolve_device_command_profile(
            operation_id=DEVICE_INVENTORY_OPERATION_ID,
            vendor=vendor,
            role=role,
            platform=platform,
        )


def test_unknown_comware_version_uses_only_explicit_generic_read_only_profile() -> None:
    profile = resolve_device_command_profile(
        operation_id=DEVICE_INVENTORY_OPERATION_ID,
        vendor="H3C",
        role="switch",
        platform="comware",
        software_version="Comware V9",
    )

    assert profile.selector.software_version == "*"
    assert profile.compatibility == "generic_read_only"
    assert "v9" not in profile.profile_id


def test_command_audit_recognizes_profiles_by_exact_command_only() -> None:
    commands = load_device_profile_commands()

    assert matches_profile_command("display interface", commands)
    assert not matches_profile_command(
        "display interface GigabitEthernet1/0/1",
        commands,
    )


def test_device_resolution_only_accepts_h3c_switch() -> None:
    h3c_switch = Device(name="SW", device_vendor="H3C", device_type="SW")
    assert resolve_device_inventory_profile(h3c_switch).selector.platform == "comware"

    with pytest.raises(DeviceCommandProfileNotFound, match="仅支持 H3C"):
        resolve_device_inventory_profile(
            Device(name="HW", device_vendor="Huawei", device_type="SW")
        )
    with pytest.raises(DeviceCommandProfileNotFound, match="仅支持交换机"):
        resolve_device_inventory_profile(
            Device(name="AC", device_vendor="H3C", device_type="AC")
        )


def test_device_remark_cannot_select_an_exact_software_profile(tmp_path: Path) -> None:
    payload = json.loads(RESOURCE_PATH.read_text(encoding="utf-8"))
    exact = deepcopy(payload["profiles"][0])
    exact["profile_id"] = "h3c.comware.switch.v9.device-inventory.v1"
    exact["selector"]["software_version"] = "V9"
    exact["compatibility"] = "fixture_verified"
    exact["verification"]["fixture_versions"] = ["9.1.001"]
    payload["profiles"].append(exact)
    resources = tmp_path / "resources"
    resources.mkdir()
    (resources / "device_command_profiles.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path / "runtime")
    device = Device(
        name="SW",
        device_vendor="H3C",
        device_type="SW",
        remark="Comware V9",
    )

    generic = resolve_device_inventory_profile(device, paths=paths)
    exact_match = resolve_device_inventory_profile(
        device,
        software_version="Comware V9",
        paths=paths,
    )

    assert generic.selector.software_version == "*"
    assert exact_match.selector.software_version == "V9"


@pytest.mark.parametrize(
    "mutation",
    (
        "schema",
        "duplicate_profile",
        "duplicate_step",
        "step_order",
        "dangerous_command",
        "illegal_step_selector",
        "illegal_profile_selector",
        "missing_contract",
        "extra_profile_key",
        "extra_step_key",
        "empty_fixture_versions",
        "duplicate_fixture_version",
        "wrong_required_selector",
        "mismatched_exact_fixture",
    ),
)
def test_invalid_profile_catalog_is_rejected(tmp_path: Path, mutation: str) -> None:
    payload = json.loads(RESOURCE_PATH.read_text(encoding="utf-8"))
    profile = payload["profiles"][0]
    if mutation == "schema":
        payload["schema_version"] = "unsupported"
    elif mutation == "duplicate_profile":
        payload["profiles"].append(deepcopy(profile))
    elif mutation == "duplicate_step":
        profile["steps"].append(deepcopy(profile["steps"][0]))
    elif mutation == "step_order":
        profile["steps"][0]["order"] = 25
    elif mutation == "dangerous_command":
        profile["steps"][0]["command"] = "save force"
    elif mutation == "illegal_step_selector":
        profile["steps"][0]["selector"] = "../session"
    elif mutation == "illegal_profile_selector":
        profile["selector"]["fallback_vendor"] = "H3C"
    elif mutation == "missing_contract":
        profile["steps"][0]["dto_contract"] = ""
    elif mutation == "extra_profile_key":
        profile["fallback"] = True
    elif mutation == "extra_step_key":
        profile["steps"][0]["shell"] = True
    elif mutation == "empty_fixture_versions":
        profile["verification"]["fixture_versions"] = []
    elif mutation == "duplicate_fixture_version":
        profile["verification"]["fixture_versions"].append("7.1.070")
    elif mutation == "wrong_required_selector":
        profile["steps"][5]["selector"] = "inventory.bootloader"
    else:
        profile["profile_id"] = "h3c.comware.switch.v9.device-inventory.v1"
        profile["selector"]["software_version"] = "V9"
        profile["compatibility"] = "fixture_verified"
    resources = tmp_path / "resources"
    resources.mkdir()
    (resources / "device_command_profiles.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with pytest.raises(DeviceCommandProfileError):
        load_device_command_profiles(
            PathResolver(app_root=tmp_path, data_root=tmp_path / "runtime")
        )


def test_duplicate_json_key_is_rejected(tmp_path: Path) -> None:
    resources = tmp_path / "resources"
    resources.mkdir()
    (resources / "device_command_profiles.json").write_text(
        '{"schema_version":"2026.07.device-command-profiles.v1",'
        '"schema_version":"2026.07.device-command-profiles.v1","profiles":[]}',
        encoding="utf-8",
    )

    with pytest.raises(DeviceCommandProfileError, match="重复键"):
        load_device_command_profiles(
            PathResolver(app_root=tmp_path, data_root=tmp_path / "runtime")
        )


def test_packaged_profile_fallback_is_used_when_source_resource_is_absent(
    monkeypatch,
    tmp_path: Path,
) -> None:
    packaged = tmp_path / "_internal" / "netconsole" / "assets" / RESOURCE_PATH.name
    packaged.parent.mkdir(parents=True)
    packaged.write_text(RESOURCE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(
        device_command_profile_service,
        "package_resource_path",
        lambda *_parts: packaged,
    )
    paths = PathResolver(
        app_root=tmp_path / "packaged-app",
        data_root=tmp_path / "runtime",
    )

    assert device_command_profile_path(paths) == packaged
    assert load_device_command_profiles(paths)[0].operation_id == DEVICE_INVENTORY_OPERATION_ID
