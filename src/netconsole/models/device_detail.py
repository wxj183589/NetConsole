from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


DeviceRole = Literal[
    "switch",
    "wireless_controller",
    "access_point",
    "mobile_router",
    "router",
    "firewall",
    "other",
    "unknown",
]


@dataclass(frozen=True)
class DevicePlatformFacts:
    vendor: str
    role: DeviceRole
    platform: str
    software_version: str | None
    software_major: str | None
    source: str
    confidence: Literal["high", "medium", "low", "unknown"]
    collected_at: str | None = None


@dataclass(frozen=True)
class DeviceCapability:
    capability_id: str
    available: bool
    executable: bool = False
    source: str = "application"
    reason: str | None = None
    profile_id: str | None = None
    profile_version: int | None = None
    compatibility: str | None = None
    risk: str | None = None
    real_device_status: str | None = None


@dataclass(frozen=True)
class DeviceOperationTask:
    task_id: str
    operation_id: str
    status: str
    reused: bool
    message: str | None = None
    profile_id: str | None = None
    profile_version: int | None = None


def normalize_device_role(device_type: object) -> DeviceRole:
    value = str(device_type or "").strip().casefold().replace("-", "_")
    roles: dict[str, DeviceRole] = {
        "sw": "switch",
        "switch": "switch",
        "ac": "wireless_controller",
        "wireless_controller": "wireless_controller",
        "cloud_ap": "access_point",
        "fit_ap": "access_point",
        "fat_ap": "access_point",
        "ap": "access_point",
        "mr": "mobile_router",
        "mobile_router": "mobile_router",
        "route": "router",
        "router": "router",
        "fw": "firewall",
        "firewall": "firewall",
        "other": "other",
    }
    return roles.get(value, "unknown")


def identify_device_platform(
    *,
    vendor: object,
    device_type: object,
    software_version: object = None,
    collected_at: object = None,
) -> DevicePlatformFacts:
    vendor_text = str(vendor or "").strip()
    version = str(software_version or "").strip() or None
    version_folded = (version or "").casefold()
    platform = "unknown"
    source = "unresolved"
    confidence: Literal["high", "medium", "low", "unknown"] = "unknown"

    signatures = (
        ("comware", "comware"),
        ("vrp", "vrp"),
        ("zxr10", "zxr10"),
        ("zxros", "zxr10"),
        ("rgos", "rgos"),
        ("ios xe", "ios_xe"),
        ("ios-xe", "ios_xe"),
        ("nx-os", "nx_os"),
    )
    for marker, candidate in signatures:
        if marker in version_folded:
            platform = candidate
            source = "device_fact.software_version"
            confidence = "high"
            break

    role = normalize_device_role(device_type)
    if (
        platform == "unknown"
        and vendor_text.casefold() == "h3c"
        and role in {"switch", "mobile_router"}
    ):
        platform = "comware"
        source = "verified_command_profile_selector"
        confidence = "medium"
    if (
        platform == "unknown"
        and vendor_text.casefold() == "zte"
        and role == "switch"
    ):
        platform = "zxr10"
        source = "vendor_command_profile_selector"
        confidence = "medium"

    return DevicePlatformFacts(
        vendor=vendor_text,
        role=role,
        platform=platform,
        software_version=version,
        software_major=_software_major(version),
        source=source,
        confidence=confidence,
        collected_at=str(collected_at or "").strip() or None,
    )


def _software_major(value: object) -> str | None:
    text = str(value or "")
    match = re.search(r"\bV([1-9][0-9]*)\b", text, re.IGNORECASE)
    if not match:
        match = re.search(r"\bVERSION\s+([1-9][0-9]*)", text, re.IGNORECASE)
    return f"V{match.group(1)}" if match else None


__all__ = [
    "DeviceCapability",
    "DeviceOperationTask",
    "DevicePlatformFacts",
    "DeviceRole",
    "identify_device_platform",
    "normalize_device_role",
]
