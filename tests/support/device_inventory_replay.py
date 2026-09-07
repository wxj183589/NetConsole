from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from netconsole.adapters.h3c.h3c_parser import H3CParser
from netconsole.parsers.h3c.boot_loader_parser import parse_boot_loader
from netconsole.parsers.h3c.device_parser import parse_device
from netconsole.parsers.h3c.sysname_parser import parse_sysname
from netconsole.parsers.zte.vlan import (
    merge_interface_vlan_facts,
    parse_switchvlan_running_config,
    parse_vlan_table,
)
from netconsole.parsers.zte.zxr10 import (
    merge_lldp_neighbors,
    parse_device_identity,
    parse_lldp_brief,
    parse_lldp_entries,
    parse_optical_summary,
)
from netconsole.parsers.zte.zxr10 import (
    parse_interfaces as parse_zte_interfaces,
)

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "device_cli"
FIXTURE_TYPES = frozenset({"REAL_CAPTURE", "SYNTHETIC"})

H3C_FACT_FIELDS = (
    "vendor",
    "platform_family",
    "software_family",
    "software_version",
    "software_train",
    "software_release",
    "software_major_version",
    "platform_major_version",
    "model",
    "serial_number",
    "mac_address",
    "sysname",
    "bootrom_version",
    "uptime_seconds",
    "uptime_precision_seconds",
)
H3C_INTERFACE_FIELDS = (
    "interface_name",
    "link_status",
    "protocol_status",
    "description",
    "speed",
    "duplex",
    "pvid",
    "interface_type",
    "port_status",
    "vlan",
)
H3C_OPTICAL_FIELDS = (
    "interface_name",
    "module_model",
    "module_serial_number",
    "module_vendor",
    "wavelength",
    "transmission_distance",
    "connector_type",
    "status",
    "rx_power",
    "tx_power",
    "temperature",
    "voltage",
    "bias_current",
)
H3C_LLDP_FIELDS = (
    "local_interface",
    "neighbor_mac",
    "neighbor_interface",
    "neighbor_sysname",
    "neighbor_ip",
)
ZTE_FACT_FIELDS = (
    "vendor",
    "platform",
    "platform_family",
    "product_family",
    "model",
    "software_version",
    "base_version",
    "system_name",
    "uptime_seconds",
    "sysname",
)
ZTE_INTERFACE_FIELDS = (
    "interface_name",
    "normalized_name",
    "media_type",
    "speed",
    "duplex",
    "admin_status",
    "physical_status",
    "protocol_status",
    "oper_status",
    "description",
    "pvid",
    "pvid_source",
    "pvid_verified",
    "port_mode",
    "native_vlan",
    "tagged_vlans",
    "untagged_vlans",
    "vlan_config_status",
)
ZTE_OPTICAL_FIELDS = (
    "interface_name",
    "module_present",
    "module_online",
    "dom_supported",
    "module_model",
    "wavelength_nm",
    "rx_power_dbm",
    "tx_power_dbm",
    "rx_low_threshold_dbm",
    "rx_high_threshold_dbm",
    "tx_low_threshold_dbm",
    "tx_high_threshold_dbm",
    "vendor_status",
    "normalized_status",
    "status",
    "severity_reason",
)
ZTE_LLDP_FIELDS = (
    "local_interface",
    "scope",
    "chassis_id",
    "neighbor_mac",
    "neighbor_interface",
    "neighbor_sysname",
    "holdtime",
    "ttl",
    "neighbor_ip",
    "port_description",
    "system_capabilities",
    "pvid",
)


@dataclass(frozen=True)
class DeviceInventoryFixture:
    fixture_id: str
    operation_id: str
    fixture_type: str
    source_note: str
    vendor: str
    role: str
    platform: str
    software_version: str
    profile_id: str
    outputs: dict[str, str]


def load_fixture(path: str | Path) -> DeviceInventoryFixture:
    fixture_path = Path(path).resolve()
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    fixture_type = str(payload.get("fixture_type") or "").strip().upper()
    if fixture_type not in FIXTURE_TYPES:
        raise ValueError(f"unsupported fixture_type: {fixture_type}")
    if payload.get("operation_id") != "device.inventory.collect":
        raise ValueError("replay fixtures must target device.inventory.collect")
    vendor = str(payload.get("vendor") or "").strip().upper()
    if vendor not in {"H3C", "ZTE"}:
        raise ValueError(f"unsupported inventory fixture vendor: {vendor}")
    outputs: dict[str, str] = {}
    for selector, spec in dict(payload.get("outputs") or {}).items():
        if not isinstance(spec, Mapping):
            raise TypeError(f"invalid output spec: {selector}")
        if "file" in spec:
            output_path = (fixture_path.parent / str(spec["file"])).resolve()
            _assert_under(output_path, FIXTURE_ROOT.parent.resolve())
            outputs[str(selector)] = output_path.read_text(encoding="utf-8")
        elif "text" in spec:
            outputs[str(selector)] = str(spec["text"] or "")
        else:
            raise ValueError(f"output spec has no file/text: {selector}")
    return DeviceInventoryFixture(
        fixture_id=str(payload["fixture_id"]),
        operation_id="device.inventory.collect",
        fixture_type=fixture_type,
        source_note=str(payload.get("source_note") or ""),
        vendor=vendor,
        role=str(payload.get("role") or ""),
        platform=str(payload.get("platform") or ""),
        software_version=str(payload.get("software_version") or ""),
        profile_id=str(payload.get("profile_id") or ""),
        outputs=outputs,
    )


def replay_fixture(path: str | Path) -> dict[str, Any]:
    return replay_case(load_fixture(path))


def replay_case(case: DeviceInventoryFixture) -> dict[str, Any]:
    if case.vendor == "H3C":
        return _replay_h3c(case)
    if case.vendor == "ZTE":
        return _replay_zte(case)
    raise ValueError(f"unsupported inventory fixture vendor: {case.vendor}")


def _replay_h3c(case: DeviceInventoryFixture) -> dict[str, Any]:
    outputs = case.outputs
    facts = parse_device(
        outputs.get("inventory.version", ""),
        outputs.get("inventory.device", ""),
        outputs.get("inventory.manuinfo", ""),
    )
    facts["sysname"] = (
        parse_sysname(outputs.get("inventory.sysname", ""))
        or facts.get("sysname")
    )
    boot_loader = parse_boot_loader(outputs.get("inventory.boot_loader", ""))
    if boot_loader:
        # 与当前生产 collector 的事实字段绑定保持一致；不新增 DTO。
        facts["bootrom_version"] = boot_loader

    parser = H3CParser()
    interfaces = parser.parse_interfaces(outputs.get("inventory.interfaces", ""))
    optical = parser.parse_optical_repository(
        "\n".join(
            [
                outputs.get("inventory.transceivers", ""),
                outputs.get("inventory.transceiver_manuinfo", ""),
                outputs.get("inventory.transceiver_diagnosis", ""),
            ]
        )
    )
    lldp = parser.parse_lldp(
        outputs.get("inventory.lldp_list", ""),
        outputs.get("inventory.lldp_verbose", ""),
    )
    return _normalized_result(
        case,
        parser_contract="netconsole.h3c.device-inventory.v1",
        facts=_pick(facts, H3C_FACT_FIELDS),
        interfaces=[_pick(item, H3C_INTERFACE_FIELDS) for item in interfaces],
        optical_modules=[_pick(item, H3C_OPTICAL_FIELDS) for item in optical],
        lldp_neighbors=[_pick(item, H3C_LLDP_FIELDS) for item in lldp],
        statuses={
            "facts": "OK" if any(value is not None for value in facts.values()) else "EMPTY",
            "interfaces": "OK" if interfaces else "EMPTY",
            "optical": "OK" if optical else "EMPTY",
            "lldp": "OK" if lldp else "EMPTY",
        },
        warning_counts={"facts": 0, "interfaces": 0, "optical": 0, "lldp": 0},
    )


def _replay_zte(case: DeviceInventoryFixture) -> dict[str, Any]:
    outputs = case.outputs
    identity = parse_device_identity(outputs.get("inventory.version", ""))
    interfaces = parse_zte_interfaces(outputs.get("inventory.interface_brief", ""))
    optical = parse_optical_summary(outputs.get("inventory.optical_brief", ""))

    switchvlan = (
        parse_switchvlan_running_config(outputs["inventory.switchvlan_config"])
        if "inventory.switchvlan_config" in outputs
        else None
    )
    vlan_table = (
        parse_vlan_table(outputs["inventory.vlan_table"])
        if "inventory.vlan_table" in outputs
        else None
    )
    merged_interfaces = merge_interface_vlan_facts(
        interfaces.value,
        switchvlan,
        vlan_table,
        [],
    )

    brief = (
        parse_lldp_brief(outputs["inventory.lldp_list"])
        if "inventory.lldp_list" in outputs
        else None
    )
    entries = (
        parse_lldp_entries(outputs["inventory.lldp_verbose"])
        if "inventory.lldp_verbose" in outputs
        else None
    )
    if brief is not None and brief.status == "OK":
        lldp = merge_lldp_neighbors(
            brief.value,
            entries.value if entries is not None and entries.status == "OK" else [],
        )
    elif entries is not None and entries.status == "OK":
        lldp = entries.value
    else:
        lldp = []

    identity_value = dict(identity.value)
    identity_value["sysname"] = identity_value.get("system_name")
    return _normalized_result(
        case,
        parser_contract="netconsole.zte.zxr10-switch.v3",
        facts=_pick(identity_value, ZTE_FACT_FIELDS),
        interfaces=[
            _normalize_zte_interface(item)
            for item in merged_interfaces.interfaces
        ],
        optical_modules=[
            _pick(item, ZTE_OPTICAL_FIELDS)
            for item in optical.value
        ],
        lldp_neighbors=[_pick(item, ZTE_LLDP_FIELDS) for item in lldp],
        statuses={
            "identity": identity.status,
            "interfaces": interfaces.status,
            "optical": optical.status,
            "switchvlan": switchvlan.status if switchvlan is not None else "MISSING",
            "vlan_table": vlan_table.status if vlan_table is not None else "MISSING",
            "lldp_brief": brief.status if brief is not None else "MISSING",
            "lldp_entry": entries.status if entries is not None else "MISSING",
        },
        warning_counts={
            "identity": len(identity.warnings),
            "interfaces": len(interfaces.warnings),
            "optical": len(optical.warnings),
            "switchvlan": len(switchvlan.warnings) if switchvlan is not None else 0,
            "vlan_table": len(vlan_table.warnings) if vlan_table is not None else 0,
            "vlan_merge": len(merged_interfaces.warnings),
            "lldp_brief": len(brief.warnings) if brief is not None else 0,
            "lldp_entry": len(entries.warnings) if entries is not None else 0,
        },
    )


def _normalized_result(
    case: DeviceInventoryFixture,
    *,
    parser_contract: str,
    facts: dict[str, Any],
    interfaces: list[dict[str, Any]],
    optical_modules: list[dict[str, Any]],
    lldp_neighbors: list[dict[str, Any]],
    statuses: dict[str, str],
    warning_counts: dict[str, int],
) -> dict[str, Any]:
    return {
        "fixture_id": case.fixture_id,
        "fixture_type": case.fixture_type,
        "operation_id": case.operation_id,
        "device": {
            "vendor": case.vendor,
            "role": case.role,
            "platform": case.platform,
            "software_version": case.software_version,
            "profile_id": case.profile_id,
        },
        "parser_contract": parser_contract,
        "facts": facts,
        "interfaces": interfaces,
        "optical_modules": optical_modules,
        "lldp_neighbors": lldp_neighbors,
        "statuses": statuses,
        "warning_counts": warning_counts,
    }


def _pick(value: Mapping[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: value.get(field) for field in fields}


def _normalize_zte_interface(value: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _pick(value, ZTE_INTERFACE_FIELDS)
    tagged_vlans = value.get("tagged_vlans")
    untagged_vlans = value.get("untagged_vlans")
    for field_name, vlan_value in (
        ("tagged_vlans", tagged_vlans),
        ("untagged_vlans", untagged_vlans),
    ):
        values = list(vlan_value or []) if isinstance(vlan_value, list) else []
        normalized[field_name] = {
            "count": len(values),
            "first": values[0] if values else None,
            "last": values[-1] if values else None,
        }
    return normalized


def _assert_under(path: Path, root: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"fixture reference escapes fixture root: {path}") from exc
