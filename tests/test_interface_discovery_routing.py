from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.models.device_detail import DevicePlatformFacts, identify_device_platform
from netconsole.repositories.device_fact_repository import DeviceFactRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services import h3c_collect_service
from netconsole.services.device_command_profile_service import (
    default_device_inventory_profile,
)
from netconsole.services.h3c_collect_service import CommandResult, collect_h3c_device_details
from netconsole.services.interface_discovery_routing import (
    CAPABILITY_PRIMARY_ROUTE,
    INTERFACE_DISCOVERY_CAPABILITY,
    INTERFACE_DISCOVERY_ROLLOUT_SCHEMA_VERSION,
    LEGACY_ROUTE,
    InterfaceDiscoveryRolloutPolicy,
    evaluate_interface_discovery_route,
    load_interface_discovery_rollout_policy,
    parse_comware_major,
    rollout_policy_path,
)
from netconsole.services.job_center.job_context import JobContext
from netconsole.services.device_operation_service import run_device_inventory_refresh


PROJECT_ROOT = Path(__file__).resolve().parents[1]
H3C_FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "h3c"
PROFILE = default_device_inventory_profile(PathResolver(app_root=PROJECT_ROOT))
COLLECT_COMMANDS = PROFILE.commands[1:]


def _facts(
    *,
    vendor: str = "H3C",
    role: str = "switch",
    platform: str = "comware",
    version: str | None = "H3C Comware Software, Version 7.1.070, Release 7756P20",
    major: str | None = "V7",
    source: str = "device_fact.software_version",
    confidence: str = "high",
) -> DevicePlatformFacts:
    return DevicePlatformFacts(
        vendor=vendor,
        role=role,  # type: ignore[arg-type]
        platform=platform,
        software_version=version,
        software_major=major,
        source=source,
        confidence=confidence,  # type: ignore[arg-type]
        collected_at="2026-09-07T00:00:00",
    )


def _policy(device_uuid: str) -> InterfaceDiscoveryRolloutPolicy:
    return InterfaceDiscoveryRolloutPolicy.from_mapping(
        {
            "schema_version": INTERFACE_DISCOVERY_ROLLOUT_SCHEMA_VERSION,
            "mode": "scoped",
            "device_uuids": [device_uuid],
        }
    )


@pytest.mark.parametrize(
    ("facts", "profile", "expected_reason"),
    [
        (_facts(), PROFILE, "CAPABILITY_PRIMARY_SCOPED_ACTIVATION"),
        (_facts(version="H3C Comware Software, Version 9.1.081, Release 1612P01", major="V9"), PROFILE, "LEGACY_OUT_OF_SCOPE_COMWARE_MAJOR"),
        (_facts(role="wireless_controller"), PROFILE, "LEGACY_OUT_OF_SCOPE_ROLE"),
        (_facts(role="mobile_router"), PROFILE, "LEGACY_OUT_OF_SCOPE_ROLE"),
        (_facts(vendor="ZTE", platform="zxr10", major="V7"), PROFILE, "LEGACY_OUT_OF_SCOPE_VENDOR"),
        (_facts(vendor="", role="unknown", platform="unknown", version=None, major=None), None, "LEGACY_OUT_OF_SCOPE_VENDOR"),
        (_facts(version=None, major=None), PROFILE, "LEGACY_UNKNOWN_VERSION"),
        (_facts(version="not a software version", major=None), PROFILE, "LEGACY_UNKNOWN_VERSION"),
        (_facts(source="submitted_job"), PROFILE, "LEGACY_UNTRUSTED_VERSION"),
    ],
)
def test_migration_envelope_is_conservative(
    facts: DevicePlatformFacts,
    profile,
    expected_reason: str,
) -> None:
    decision = evaluate_interface_discovery_route(
        device_uuid="c7-target",
        operation_id="device.inventory.collect",
        capability=INTERFACE_DISCOVERY_CAPABILITY,
        platform_facts=facts,
        profile=profile,
        policy=_policy("c7-target"),
    )

    if expected_reason == "CAPABILITY_PRIMARY_SCOPED_ACTIVATION":
        assert decision.route == CAPABILITY_PRIMARY_ROUTE
        assert decision.envelope_eligible is True
        assert decision.activation_enabled is True
    else:
        assert decision.route == LEGACY_ROUTE
        assert decision.reason_code == expected_reason


def test_default_route_is_legacy_even_for_c7_switch() -> None:
    decision = evaluate_interface_discovery_route(
        device_uuid="c7-target",
        operation_id="device.inventory.collect",
        capability=INTERFACE_DISCOVERY_CAPABILITY,
        platform_facts=_facts(),
        profile=PROFILE,
        policy=InterfaceDiscoveryRolloutPolicy.disabled(),
    )

    assert decision.route == LEGACY_ROUTE
    assert decision.envelope_eligible is True
    assert decision.reason_code == "LEGACY_DEFAULT"


def test_c9_and_other_roles_remain_legacy_when_c7_scope_is_activated() -> None:
    policy = _policy("c7-target")
    for device_uuid, facts in (
        ("c9-target", _facts(version="Version 9.1.081 Release 1612P01", major="V9")),
        ("ac-target", _facts(role="wireless_controller")),
        ("mr-target", _facts(role="mobile_router")),
        ("zte-target", _facts(vendor="ZTE", platform="zxr10")),
    ):
        decision = evaluate_interface_discovery_route(
            device_uuid=device_uuid,
            operation_id="device.inventory.collect",
            capability=INTERFACE_DISCOVERY_CAPABILITY,
            platform_facts=facts,
            profile=PROFILE,
            policy=policy,
        )
        assert decision.route == LEGACY_ROUTE


def test_policy_file_missing_or_invalid_fails_closed(tmp_path: Path) -> None:
    paths = PathResolver(app_root=PROJECT_ROOT, data_root=tmp_path)
    assert load_interface_discovery_rollout_policy(paths).source == "missing"

    policy_path = rollout_policy_path(paths)
    policy_path.parent.mkdir(parents=True)
    policy_path.write_text("{invalid", encoding="utf-8")
    policy = load_interface_discovery_rollout_policy(paths)
    assert policy.activated_device_uuids == frozenset()
    assert policy.source == "invalid"


@pytest.mark.parametrize(
    "version,expected",
    [
        ("Version 7.1.070 Release 7756P10", "V7"),
        ("H3C Comware Software, Version 9.1.081, Release 1612P01", "V9"),
        ("V7.1.070", "V7"),
        ("unknown", None),
    ],
)
def test_comware_major_parser(version: str, expected: str | None) -> None:
    assert parse_comware_major(version) == expected


class _FakeConnection:
    def __init__(self) -> None:
        self.commands: list[str] = []
        self.disconnected = False

    def send_command(self, command: str, **_kwargs: object) -> str:
        self.commands.append(command)
        return _OUTPUTS[command]

    def disconnect(self) -> None:
        self.disconnected = True


def _fixture(name: str) -> str:
    return (H3C_FIXTURE_ROOT / name).read_text(encoding="utf-8")


_OUTPUTS = {
    "screen-length disable": "",
    "display current-configuration | include sysname": _fixture(
        "display_current_configuration_sysname.txt"
    ),
    "display version": _fixture("display_version.txt"),
    "display device": _fixture("display_device_sw.txt"),
    "display device manuinfo": _fixture("display_device_manuinfo.txt"),
    "display boot-loader": _fixture("display_boot_loader_sw.txt"),
    "display interface": _fixture("display_interface.txt"),
    "display transceiver interface": _fixture("display_transceiver_interface.txt"),
    "display transceiver manuinfo interface": (
        "GigabitEthernet1/0/1 transceiver manufacture information:\n"
        "  Manu. Serial Number : OPT-MANU-0001\n"
        "  Vendor Name         : H3C\n"
    ),
    "display transceiver diagnosis interface": _fixture(
        "display_transceiver_diagnosis_interface.txt"
    ),
    "display lldp neighbor-information list": _fixture(
        "display_lldp_neighbor_information_list.txt"
    ),
    "display lldp neighbor-information verbose": _fixture(
        "display_lldp_neighbor_information_verbose.txt"
    ),
}


def _paths(tmp_path: Path) -> PathResolver:
    return PathResolver(app_root=PROJECT_ROOT, data_root=tmp_path)


def _repository(tmp_path: Path) -> DeviceFactRepository:
    database = Database(tmp_path / "sites" / "demo" / "db" / "devices.db")
    database.initialize()
    return DeviceFactRepository(database)


def _device() -> Device:
    return Device(
        device_uuid="11111111-1111-4111-8111-111111111111",
        name="C7-test-switch",
        device_vendor="H3C",
        device_type="SW",
        ip_address="192.0.2.7",
        ssh_enabled=1,
        ssh_username="readonly",
        ssh_password="test-only",
    )


def _capability_result(output: str, *, success: bool = True) -> CommandResult:
    return CommandResult(
        command="display interface",
        success=success,
        selector="inventory.interfaces",
        output=output,
        error_message=None if success else "CAPABILITY_EXECUTION_ERROR",
    )


def _collect_with_route(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capability_output: str,
    *,
    capability_success: bool = True,
) -> tuple[object, _FakeConnection, list[list[dict[str, object | None]]]]:
    connection = _FakeConnection()
    monkeypatch.setattr(
        h3c_collect_service.netmiko_connection,
        "ConnectHandler",
        lambda **_kwargs: connection,
    )
    repository = _repository(tmp_path)
    writes: list[list[dict[str, object | None]]] = []
    original_write = repository.replace_device_interfaces

    def counted_write(device_uuid: str, rows: list[dict[str, object | None]]) -> None:
        writes.append(rows)
        original_write(device_uuid, rows)

    monkeypatch.setattr(repository, "replace_device_interfaces", counted_write)

    result = collect_h3c_device_details(
        _device(),
        "demo",
        repository=repository,
        paths=_paths(tmp_path),
        interface_discovery_route=CAPABILITY_PRIMARY_ROUTE,
        interface_discovery_platform_facts=_facts(),
        interface_discovery_executor=lambda _connection, _step: _capability_result(
            capability_output,
            success=capability_success,
        ),
    )
    return result, connection, writes


def test_capability_success_uses_existing_parser_and_single_writer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    result, connection, writes = _collect_with_route(
        monkeypatch, tmp_path, _fixture("display_interface.txt")
    )

    assert result.success is True
    assert result.interfaces_updated == 2
    assert len(writes) == 1
    assert "display interface" not in connection.commands
    assert connection.disconnected is True


@pytest.mark.parametrize(
    ("output", "success"),
    [
        ("", True),
        ("not an interface result", True),
        (_fixture("display_interface.txt") * 2, True),
        ("ignored", False),
    ],
)
def test_capability_failure_or_invalid_result_falls_back_before_single_writer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    output: str,
    success: bool,
) -> None:
    result, connection, writes = _collect_with_route(
        monkeypatch,
        tmp_path,
        output,
        capability_success=success,
    )

    assert result.success is True
    assert result.interfaces_updated == 2
    assert connection.commands.count("display interface") == 1
    assert len(writes) == 1


def test_capability_command_guard_violation_stops_without_legacy_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    connection = _FakeConnection()
    monkeypatch.setattr(
        h3c_collect_service.netmiko_connection,
        "ConnectHandler",
        lambda **_kwargs: connection,
    )
    repository = _repository(tmp_path)

    result = collect_h3c_device_details(
        _device(),
        "demo",
        repository=repository,
        paths=_paths(tmp_path),
        interface_discovery_route=CAPABILITY_PRIMARY_ROUTE,
        interface_discovery_platform_facts=_facts(),
        interface_discovery_executor=lambda _connection, _step: CommandResult(
            command="system-view",
            success=True,
            selector="inventory.interfaces",
            output=_fixture("display_interface.txt"),
        ),
    )

    assert result.success is False
    assert "system-view" in (result.error_message or "")
    assert "display interface" not in connection.commands


def test_runtime_policy_payload_is_scope_aware(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    policy_path = rollout_policy_path(paths)
    policy_path.parent.mkdir(parents=True)
    policy_path.write_text(
        json.dumps(
            {
                "schema_version": INTERFACE_DISCOVERY_ROLLOUT_SCHEMA_VERSION,
                "mode": "scoped",
                "device_uuids": ["c7-target"],
            }
        ),
        encoding="utf-8",
    )
    policy = load_interface_discovery_rollout_policy(paths)
    assert policy.is_activated_for("c7-target") is True
    assert policy.is_activated_for("c9-target") is False


def test_worker_rechecks_policy_and_forwards_only_scoped_capability_route(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    paths = _paths(tmp_path)
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    device = _device()
    DeviceRepository(database).create(device)
    profile = default_device_inventory_profile(paths)
    policy_path = rollout_policy_path(paths)
    policy_path.parent.mkdir(parents=True)
    policy_path.write_text(
        json.dumps(
            {
                "schema_version": INTERFACE_DISCOVERY_ROLLOUT_SCHEMA_VERSION,
                "mode": "scoped",
                "device_uuids": [str(device.device_uuid)],
            }
        ),
        encoding="utf-8",
    )
    calls: list[dict[str, object]] = []

    def fake_collect(_device, _site, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            success=True,
            collect_run_uuid="worker-route-run",
            facts_updated=False,
            interfaces_updated=2,
            optical_modules_updated=0,
            lldp_neighbors_updated=0,
            error_message=None,
        )

    monkeypatch.setattr(
        "netconsole.services.h3c_collect_service.collect_h3c_device_details",
        fake_collect,
    )
    detected = identify_device_platform(
        vendor=device.vendor_key,
        device_type=device.device_type,
        software_version="H3C Comware Software, Version 7.1.070, Release 7756P20",
    )
    params = {
        "site_name": "demo",
        "device_uuids": [str(device.device_uuid)],
        "operation_id": "device.inventory.collect",
        "profile_id": profile.profile_id,
        "profile_version": profile.profile_version,
        "software_version": detected.software_version,
        "platform_vendor": detected.vendor,
        "platform_role": detected.role,
        "platform": detected.platform,
        "platform_source": detected.source,
        "platform_confidence": detected.confidence,
        "platform_collected_at": detected.collected_at,
        "allow_excluded": False,
    }

    result = run_device_inventory_refresh(
        JobContext(
            "worker-route-test",
            "device_detail_collect",
            params,
            None,
            lambda: False,
            paths,
        )
    )

    assert result["success"] == 1
    assert calls[0]["interface_discovery_route"] == CAPABILITY_PRIMARY_ROUTE
    assert isinstance(calls[0]["interface_discovery_platform_facts"], DevicePlatformFacts)


def test_worker_policy_rollback_returns_to_legacy_without_restart(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    paths = _paths(tmp_path)
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    device = _device()
    DeviceRepository(database).create(device)
    profile = default_device_inventory_profile(paths)
    policy_path = rollout_policy_path(paths)
    policy_path.parent.mkdir(parents=True)
    policy_path.write_text(
        json.dumps(
            {
                "schema_version": INTERFACE_DISCOVERY_ROLLOUT_SCHEMA_VERSION,
                "mode": "disabled",
                "device_uuids": [],
            }
        ),
        encoding="utf-8",
    )
    calls: list[dict[str, object]] = []

    def fake_collect(_device, _site, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            success=True,
            collect_run_uuid="legacy-route-run",
            facts_updated=False,
            interfaces_updated=2,
            optical_modules_updated=0,
            lldp_neighbors_updated=0,
            error_message=None,
        )

    monkeypatch.setattr(
        "netconsole.services.h3c_collect_service.collect_h3c_device_details",
        fake_collect,
    )
    detected = identify_device_platform(
        vendor=device.vendor_key,
        device_type=device.device_type,
        software_version="Version 7.1.070 Release 7756P10",
    )
    params = {
        "site_name": "demo",
        "device_uuids": [str(device.device_uuid)],
        "operation_id": "device.inventory.collect",
        "profile_id": profile.profile_id,
        "profile_version": profile.profile_version,
        "software_version": detected.software_version,
        "platform_vendor": detected.vendor,
        "platform_role": detected.role,
        "platform": detected.platform,
        "platform_source": detected.source,
        "platform_confidence": detected.confidence,
        "allow_excluded": False,
    }

    result = run_device_inventory_refresh(
        JobContext(
            "worker-rollback-test",
            "device_detail_collect",
            params,
            None,
            lambda: False,
            paths,
        )
    )

    assert result["success"] == 1
    assert len(calls) == 1
    assert "interface_discovery_route" not in calls[0]
    assert calls[0]["paths"] is paths
