"""Fail-closed routing policy for the scoped interface discovery migration."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping

from netconsole.core.paths import PathResolver
from netconsole.models.device_detail import DevicePlatformFacts
from netconsole.services.device_command_profile_service import (
    DEVICE_INVENTORY_OPERATION_ID,
    DeviceCommandProfile,
)


INTERFACE_DISCOVERY_CAPABILITY = "interface.discovery"
INTERFACE_DISCOVERY_ROLLOUT_FILENAME = "interface_discovery_rollout.json"
INTERFACE_DISCOVERY_ROLLOUT_SCHEMA_VERSION = 1
LEGACY_ROUTE = "LEGACY"
CAPABILITY_PRIMARY_ROUTE = "CAPABILITY_PRIMARY"
RouteName = Literal["LEGACY", "CAPABILITY_PRIMARY"]
_POLICY_KEYS = frozenset({"schema_version", "mode", "device_uuids"})
_VERSION_PATTERN = re.compile(r"\b(?:version|v)\s*([1-9][0-9]*)\b", re.IGNORECASE)


@dataclass(frozen=True)
class InterfaceDiscoveryRolloutPolicy:
    """A minimal internal activation policy; an empty allowlist is disabled."""

    activated_device_uuids: frozenset[str] = frozenset()
    source: str = "missing"
    mode: Literal["disabled", "scoped"] = "disabled"

    @classmethod
    def disabled(cls, source: str = "missing") -> "InterfaceDiscoveryRolloutPolicy":
        return cls(frozenset(), str(source or "missing"), "disabled")

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any],
        *,
        source: str = "runtime",
    ) -> "InterfaceDiscoveryRolloutPolicy":
        if not isinstance(payload, Mapping):
            raise ValueError("interface discovery rollout policy must be an object")
        unknown = set(payload) - _POLICY_KEYS
        if unknown:
            raise ValueError("interface discovery rollout policy has unknown fields")
        schema_version = payload.get("schema_version")
        if (
            isinstance(schema_version, bool)
            or not isinstance(schema_version, int)
            or schema_version != INTERFACE_DISCOVERY_ROLLOUT_SCHEMA_VERSION
        ):
            raise ValueError("unsupported interface discovery rollout policy schema")
        mode = str(payload.get("mode") or "").strip().casefold()
        raw_ids = payload.get("device_uuids")
        if not isinstance(raw_ids, list):
            raise ValueError("interface discovery rollout device_uuids must be a list")
        device_uuids = frozenset(
            value.strip()
            for value in raw_ids
            if isinstance(value, str) and value.strip()
        )
        if len(device_uuids) != len(raw_ids):
            raise ValueError("interface discovery rollout device_uuids contains invalid values")
        if mode == "disabled" and device_uuids:
            raise ValueError("disabled interface discovery rollout cannot have targets")
        if mode == "scoped" and not device_uuids:
            raise ValueError("scoped interface discovery rollout requires targets")
        if mode not in {"disabled", "scoped"}:
            raise ValueError("unsupported interface discovery rollout mode")
        return cls(device_uuids, str(source or "runtime"), mode)  # type: ignore[arg-type]

    def is_activated_for(self, device_uuid: object) -> bool:
        return (
            self.mode == "scoped"
            and str(device_uuid or "").strip() in self.activated_device_uuids
        )


@dataclass(frozen=True)
class InterfaceDiscoveryRouteDecision:
    route: RouteName
    reason_code: str
    envelope_eligible: bool
    activation_enabled: bool
    policy_source: str


def rollout_policy_path(paths: PathResolver) -> Path:
    return paths.runtime_dir / INTERFACE_DISCOVERY_ROLLOUT_FILENAME


def load_interface_discovery_rollout_policy(
    paths: PathResolver,
) -> InterfaceDiscoveryRolloutPolicy:
    """Read the internal policy without creating or repairing it."""

    path = rollout_policy_path(paths)
    if not path.is_file():
        return InterfaceDiscoveryRolloutPolicy.disabled("missing")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return InterfaceDiscoveryRolloutPolicy.from_mapping(payload, source="runtime")
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return InterfaceDiscoveryRolloutPolicy.disabled("invalid")


def parse_comware_major(software_version: object) -> str | None:
    """Parse the conservative major-version forms used by H3C facts."""

    match = _VERSION_PATTERN.search(str(software_version or ""))
    return f"V{match.group(1)}" if match else None


def evaluate_interface_discovery_route(
    *,
    device_uuid: object,
    operation_id: object,
    capability: object,
    platform_facts: DevicePlatformFacts,
    profile: DeviceCommandProfile | None,
    policy: InterfaceDiscoveryRolloutPolicy,
) -> InterfaceDiscoveryRouteDecision:
    """Return a route decision; every unknown condition falls back to Legacy."""

    def legacy(reason: str, *, envelope_eligible: bool = False) -> InterfaceDiscoveryRouteDecision:
        return InterfaceDiscoveryRouteDecision(
            LEGACY_ROUTE,
            reason,
            envelope_eligible,
            False,
            policy.source,
        )

    if str(operation_id or "").strip() != DEVICE_INVENTORY_OPERATION_ID:
        return legacy("LEGACY_OUT_OF_SCOPE_OPERATION")
    if str(capability or "").strip() != INTERFACE_DISCOVERY_CAPABILITY:
        return legacy("LEGACY_OUT_OF_SCOPE_CAPABILITY")
    if str(platform_facts.vendor or "").strip().casefold() != "h3c":
        return legacy("LEGACY_OUT_OF_SCOPE_VENDOR")
    if str(platform_facts.role or "").strip().casefold() != "switch":
        return legacy("LEGACY_OUT_OF_SCOPE_ROLE")
    if str(platform_facts.platform or "").strip().casefold() != "comware":
        return legacy("LEGACY_OUT_OF_SCOPE_PLATFORM")
    software_version = str(platform_facts.software_version or "").strip()
    parsed_major = parse_comware_major(software_version)
    reported_major = str(platform_facts.software_major or "").strip().upper()
    if not software_version or not parsed_major or reported_major != parsed_major:
        return legacy("LEGACY_UNKNOWN_VERSION")
    if parsed_major != "V7":
        return legacy("LEGACY_OUT_OF_SCOPE_COMWARE_MAJOR")
    if (
        str(platform_facts.source or "").strip() != "device_fact.software_version"
        or str(platform_facts.confidence or "").strip().casefold() != "high"
    ):
        return legacy("LEGACY_UNTRUSTED_VERSION")
    if profile is None:
        return legacy("LEGACY_PROFILE_MISSING")
    selector = profile.selector
    if (
        str(profile.operation_id or "").strip() != DEVICE_INVENTORY_OPERATION_ID
        or str(selector.vendor or "").strip().casefold() != "h3c"
        or str(selector.role or "").strip().casefold() != "switch"
        or str(selector.platform or "").strip().casefold() != "comware"
        or str(profile.risk or "").strip().casefold() != "read_only"
        or not any(step.selector == "inventory.interfaces" for step in profile.steps)
    ):
        return legacy("LEGACY_PROFILE_MISMATCH")
    if not policy.is_activated_for(device_uuid):
        if policy.source == "missing":
            reason = "LEGACY_DEFAULT"
        elif policy.source == "invalid":
            reason = "LEGACY_POLICY_FAILURE"
        elif policy.mode == "disabled":
            reason = "LEGACY_AFTER_ROLLBACK"
        else:
            reason = "LEGACY_ROLLOUT_DISABLED"
        return legacy(reason, envelope_eligible=True)
    return InterfaceDiscoveryRouteDecision(
        CAPABILITY_PRIMARY_ROUTE,
        "CAPABILITY_PRIMARY",
        True,
        True,
        policy.source,
    )


__all__ = [
    "CAPABILITY_PRIMARY_ROUTE",
    "INTERFACE_DISCOVERY_CAPABILITY",
    "INTERFACE_DISCOVERY_ROLLOUT_FILENAME",
    "INTERFACE_DISCOVERY_ROLLOUT_SCHEMA_VERSION",
    "InterfaceDiscoveryRolloutPolicy",
    "InterfaceDiscoveryRouteDecision",
    "LEGACY_ROUTE",
    "evaluate_interface_discovery_route",
    "load_interface_discovery_rollout_policy",
    "parse_comware_major",
    "rollout_policy_path",
]
