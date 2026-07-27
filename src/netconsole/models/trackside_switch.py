from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import NotRequired, TypedDict


class CommandCapabilityState(StrEnum):
    DOCUMENTED = "DOCUMENTED"
    IMPLEMENTED = "IMPLEMENTED"
    SAMPLE_REQUIRED = "SAMPLE_REQUIRED"
    VERIFIED = "VERIFIED"
    UNSUPPORTED = "UNSUPPORTED"


class ParserVerificationStatus(StrEnum):
    DOCUMENT_SAMPLE_ONLY = "DOCUMENT_SAMPLE_ONLY"
    REAL_DEVICE_PENDING = "REAL_DEVICE_PENDING"
    SAMPLE_REQUIRED = "SAMPLE_REQUIRED"
    VERIFIED = "VERIFIED"


class ParseStatus(StrEnum):
    PARSED = "PARSED"
    EMPTY = "EMPTY"
    PARTIAL = "PARTIAL"
    SAMPLE_REQUIRED = "SAMPLE_REQUIRED"
    UNSUPPORTED = "UNSUPPORTED"
    FAILED = "FAILED"


class _ParserMetadata(TypedDict):
    warnings: list[str]
    raw_output_ref: str
    parser_version: str
    verification_status: str


class SwitchIdentity(_ParserMetadata):
    vendor: str
    platform: str
    model: str
    product_family: str
    software_version: str | None
    build_version: str | None
    uptime: str | None
    raw_command: str
    parse_status: str
    base_version: NotRequired[str | None]
    build_time: NotRequired[str | None]
    image_file: NotRequired[str | None]
    uptime_seconds: NotRequired[int | None]


class SwitchInterface(_ParserMetadata):
    interface_name: str
    normalized_name: str
    media_type: str | None
    bandwidth: str | None
    admin_status: str | None
    physical_status: str | None
    protocol_status: str | None
    description: str
    raw_line: str
    parse_status: str


class LldpNeighbor(_ParserMetadata):
    local_interface: str
    chassis_id: str | None
    remote_port_id: str | None
    remote_system_name: str | None
    remote_system_description: str | None
    management_address: str | None
    capabilities: list[str]
    raw_output: str
    parse_status: str


class OpticalModule(_ParserMetadata):
    interface_name: str
    module_present: bool
    dom_supported: bool
    module_type: str | None
    wavelength_nm: float | int | None
    rx_power_dbm: float | int | None
    tx_power_dbm: float | int | None
    rx_low_threshold_dbm: float | int | None
    rx_high_threshold_dbm: float | int | None
    tx_low_threshold_dbm: float | int | None
    tx_high_threshold_dbm: float | int | None
    temperature_c: float | int | None
    voltage_v: float | int | None
    vendor_name: str | None
    vendor_part_number: str | None
    vendor_serial_number: str | None
    status: str
    raw_output: str
    parse_status: str


@dataclass(frozen=True)
class TracksideCapabilityDescriptor:
    key: str
    label: str
    status: CommandCapabilityState
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "key": self.key,
            "label": self.label,
            "status": self.status.value,
            "message": self.message,
        }


@dataclass(frozen=True)
class TracksideCommandPlanItem:
    selector: str
    command: str
    output_file: str
    status: CommandCapabilityState
    candidate: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "selector": self.selector,
            "command": self.command,
            "output_file": self.output_file,
            "status": self.status.value,
            "candidate": self.candidate,
        }


@dataclass(frozen=True)
class TracksideCommandPlan:
    profile_id: str
    selected_interface: str
    items: tuple[TracksideCommandPlanItem, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "profile_id": self.profile_id,
            "selected_interface": self.selected_interface,
            "items": [item.to_dict() for item in self.items],
        }


@dataclass(frozen=True)
class TracksideCommandProfile:
    profile_id: str
    vendor: str
    platform: str
    product_family: str
    reference_version: str
    privilege_required: bool = False
    enable_command: str = "enable 15"
    enable_level: int = 15
    enable_secret_configured: bool = False
    device_version: tuple[str, ...] = ()
    interface_brief: tuple[str, ...] = ()
    interface_detail: tuple[str, ...] = ()
    optical_brief: tuple[str, ...] = ()
    optical_detail: tuple[str, ...] = ()
    lldp_global_candidates: tuple[str, ...] = ()
    lldp_interface_candidates: tuple[str, ...] = ()
    lldp_config_candidates: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "profile_id": self.profile_id,
            "vendor": self.vendor,
            "platform": self.platform,
            "product_family": self.product_family,
            "reference_version": self.reference_version,
            "privilege_required": self.privilege_required,
            "enable_command": self.enable_command,
            "enable_level": self.enable_level,
            "enable_secret_configured": self.enable_secret_configured,
            "device_version": list(self.device_version),
            "interface_brief": list(self.interface_brief),
            "interface_detail": list(self.interface_detail),
            "optical_brief": list(self.optical_brief),
            "optical_detail": list(self.optical_detail),
            "lldp_global_candidates": list(self.lldp_global_candidates),
            "lldp_interface_candidates": list(self.lldp_interface_candidates),
            "lldp_config_candidates": list(self.lldp_config_candidates),
        }


@dataclass(frozen=True)
class TracksideAdapterDescription:
    vendor: str
    vendor_label: str
    platform: str
    product_family: str
    adaptation_status: str
    verification_status: ParserVerificationStatus
    profile: TracksideCommandProfile
    capabilities: tuple[TracksideCapabilityDescriptor, ...] = field(
        default_factory=tuple
    )
    pending_items: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {
            "vendor": self.vendor,
            "vendor_label": self.vendor_label,
            "platform": self.platform,
            "product_family": self.product_family,
            "adaptation_status": self.adaptation_status,
            "verification_status": self.verification_status.value,
            "profile": self.profile.to_dict(),
            "capabilities": [item.to_dict() for item in self.capabilities],
            "pending_items": list(self.pending_items),
        }


__all__ = [
    "CommandCapabilityState",
    "LldpNeighbor",
    "OpticalModule",
    "ParseStatus",
    "ParserVerificationStatus",
    "SwitchIdentity",
    "SwitchInterface",
    "TracksideAdapterDescription",
    "TracksideCapabilityDescriptor",
    "TracksideCommandPlan",
    "TracksideCommandPlanItem",
    "TracksideCommandProfile",
]
