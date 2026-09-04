from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from tests.support.device_inventory_snapshot_contract import SNAPSHOT_IGNORED_FIELDS

EQUIVALENCE_REQUIRED_SECTIONS = frozenset(
    {
        "device_identity",
        "model",
        "version",
        "interfaces",
        "optical_modules",
        "neighbors",
        "capabilities",
    }
)
EQUIVALENCE_IGNORED_FIELDS = SNAPSHOT_IGNORED_FIELDS


def normalized_device_inventory_projection(
    snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    """Project replay or future collector output to comparable normalized facts."""

    device = _mapping(snapshot.get("device"))
    facts = _mapping(snapshot.get("facts"))
    return {
        "device_identity": {
            "vendor": facts.get("vendor") or device.get("vendor"),
            "platform": facts.get("platform") or device.get("platform"),
            "system_name": (
                facts.get("sysname")
                or facts.get("system_name")
                or device.get("system_name")
            ),
            "serial_number": facts.get("serial_number"),
            "mac_address": facts.get("mac_address"),
        },
        "model": facts.get("model") or device.get("model"),
        "version": facts.get("software_version") or device.get("software_version"),
        "interfaces": snapshot.get("interfaces", []),
        "optical_modules": snapshot.get("optical_modules", []),
        "neighbors": snapshot.get("lldp_neighbors", []),
        # 当前 Parser replay 不拥有 capability resolver；未来比较调用方显式提供。
        "capabilities": snapshot.get("capabilities", []),
    }


def compare_normalized_device_inventory(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
) -> bool:
    """Compare normalized DTO projections, excluding only runtime fields."""

    return _without_ignored_fields(normalized_device_inventory_projection(left)) == (
        _without_ignored_fields(normalized_device_inventory_projection(right))
    )


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _without_ignored_fields(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _without_ignored_fields(child)
            for key, child in value.items()
            if key not in EQUIVALENCE_IGNORED_FIELDS
        }
    if isinstance(value, list):
        return [_without_ignored_fields(child) for child in value]
    return value
