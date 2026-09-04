from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from tests.support.device_inventory_replay import (
    H3C_FACT_FIELDS,
    H3C_INTERFACE_FIELDS,
    H3C_LLDP_FIELDS,
    H3C_OPTICAL_FIELDS,
    ZTE_FACT_FIELDS,
    ZTE_INTERFACE_FIELDS,
    ZTE_LLDP_FIELDS,
    ZTE_OPTICAL_FIELDS,
)

SNAPSHOT_REQUIRED_FIELDS = frozenset(
    {
        "fixture_id",
        "fixture_type",
        "operation_id",
        "device",
        "parser_contract",
        "facts",
        "interfaces",
        "optical_modules",
        "lldp_neighbors",
        "statuses",
        "warning_counts",
    }
)
SNAPSHOT_DEVICE_REQUIRED_FIELDS = frozenset(
    {"vendor", "role", "platform", "software_version", "profile_id"}
)
SNAPSHOT_COLLECTION_FIELDS = frozenset(
    {"interfaces", "optical_modules", "lldp_neighbors"}
)
SNAPSHOT_IGNORED_FIELDS = frozenset(
    {
        "raw",
        "raw_output",
        "raw_output_ref",
        "collected_at",
        "observed_at",
        "timestamp",
        "started_at",
        "ended_at",
        "duration_ms",
        "execution_duration_ms",
        "session_id",
        "collect_run_uuid",
        "task_id",
        "machine_path",
        "runtime_metadata",
    }
)

_FIELDS_BY_VENDOR = {
    "H3C": {
        "facts": frozenset(H3C_FACT_FIELDS),
        "interfaces": frozenset(H3C_INTERFACE_FIELDS),
        "optical_modules": frozenset(H3C_OPTICAL_FIELDS),
        "lldp_neighbors": frozenset(H3C_LLDP_FIELDS),
        "statuses": frozenset({"facts", "interfaces", "optical", "lldp"}),
        "warning_counts": frozenset({"facts", "interfaces", "optical", "lldp"}),
    },
    "ZTE": {
        "facts": frozenset(ZTE_FACT_FIELDS),
        "interfaces": frozenset(ZTE_INTERFACE_FIELDS),
        "optical_modules": frozenset(ZTE_OPTICAL_FIELDS),
        "lldp_neighbors": frozenset(ZTE_LLDP_FIELDS),
        "statuses": frozenset(
            {
                "identity",
                "interfaces",
                "optical",
                "switchvlan",
                "vlan_table",
                "lldp_brief",
                "lldp_entry",
            }
        ),
        "warning_counts": frozenset(
            {
                "identity",
                "interfaces",
                "optical",
                "switchvlan",
                "vlan_table",
                "vlan_merge",
                "lldp_brief",
                "lldp_entry",
            }
        ),
    },
}


def validate_snapshot_contract(snapshot: Mapping[str, Any]) -> None:
    _assert_keys(snapshot, SNAPSHOT_REQUIRED_FIELDS, "snapshot")
    _assert_no_ignored_fields(snapshot)

    device = _mapping(snapshot["device"], "snapshot.device")
    _assert_keys(device, SNAPSHOT_DEVICE_REQUIRED_FIELDS, "snapshot.device")
    vendor = device["vendor"]
    if vendor not in _FIELDS_BY_VENDOR:
        raise ValueError(f"unsupported snapshot vendor: {vendor}")

    contract = _FIELDS_BY_VENDOR[vendor]
    facts = _mapping(snapshot["facts"], "snapshot.facts")
    _assert_keys(facts, contract["facts"], "snapshot.facts")

    for collection_name in SNAPSHOT_COLLECTION_FIELDS:
        collection = snapshot[collection_name]
        if not isinstance(collection, list):
            raise TypeError(f"{collection_name} must be a list")
        item_fields = contract[collection_name]
        for index, item in enumerate(collection):
            _assert_keys(
                _mapping(item, f"snapshot.{collection_name}[{index}]"),
                item_fields,
                f"snapshot.{collection_name}[{index}]",
            )

    for field_name in ("statuses", "warning_counts"):
        values = _mapping(snapshot[field_name], f"snapshot.{field_name}")
        _assert_keys(values, contract[field_name], f"snapshot.{field_name}")
        if field_name == "warning_counts" and not all(
            isinstance(value, int) and not isinstance(value, bool)
            for value in values.values()
        ):
            raise TypeError("snapshot.warning_counts values must be integers")


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be an object")
    return value


def _assert_keys(value: Mapping[str, Any], expected: frozenset[str], name: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise ValueError(f"{name} fields mismatch: missing={missing}, unexpected={unexpected}")


def _assert_no_ignored_fields(value: Any) -> None:
    if isinstance(value, Mapping):
        unexpected = SNAPSHOT_IGNORED_FIELDS.intersection(value)
        if unexpected:
            raise ValueError(f"ignored runtime fields in snapshot: {sorted(unexpected)}")
        for child in value.values():
            _assert_no_ignored_fields(child)
    elif isinstance(value, list):
        for child in value:
            _assert_no_ignored_fields(child)
