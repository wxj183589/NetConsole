from __future__ import annotations

from dataclasses import dataclass

from netconsole.models.device import Device
from netconsole.models.device_detail import DevicePlatformFacts, identify_device_platform, normalize_device_role
from netconsole.core.paths import PathResolver
from netconsole.services.device_command_profile_service import (
    DeviceCommandProfileNotFound,
    resolve_device_operation_profile,
)


@dataclass(frozen=True)
class DeviceCollectionSupport:
    supported: bool
    driver_key: str | None
    vendor_key: str
    reason_code: str | None = None
    reason_message: str | None = None


def resolve_device_collection_support(
    device: Device,
    operation_id: str,
    *,
    platform_facts: DevicePlatformFacts | None = None,
    paths: PathResolver | None = None,
) -> DeviceCollectionSupport:
    """Resolve collection capability before opening a network connection.

    The resolver intentionally has no default driver. New vendors become
    collectable only after an explicit profile is registered for their key.
    """

    vendor_key = device.vendor_key
    vendor_label = str(device.device_vendor or "").strip()
    if vendor_key not in {"h3c", "zte"}:
        return DeviceCollectionSupport(
            supported=False,
            driver_key=None,
            vendor_key=vendor_key,
            reason_code="UNSUPPORTED_VENDOR",
            reason_message=f'当前设备厂商“{vendor_label}”暂未适配采集命令，本次已跳过。',
        )

    role = normalize_device_role(device.device_type)
    supported_roles = (
        {"switch", "wireless_controller", "mobile_router"}
        if vendor_key == "h3c"
        else {"switch"}
    )
    if role not in supported_roles:
        return DeviceCollectionSupport(
            supported=False,
            driver_key=None,
            vendor_key=vendor_key,
            reason_code="UNSUPPORTED_DEVICE_TYPE",
            reason_message=f'当前设备类型“{device.device_type or "未指定"}”暂未适配采集命令，本次已跳过。',
        )

    facts = platform_facts or identify_device_platform(
        vendor=vendor_key,
        device_type=device.device_type,
    )
    try:
        profile = resolve_device_operation_profile(
            device,
            operation_id,
            platform_facts=facts,
            paths=paths,
        )
    except DeviceCommandProfileNotFound:
        return DeviceCollectionSupport(
            supported=False,
            driver_key=None,
            vendor_key=vendor_key,
            reason_code="UNSUPPORTED_COMMAND_PROFILE",
            reason_message="当前设备没有可靠的采集命令模板，本次已跳过。",
        )
    return DeviceCollectionSupport(
        supported=True,
        driver_key=profile.profile_id,
        vendor_key=vendor_key,
    )


__all__ = ["DeviceCollectionSupport", "resolve_device_collection_support"]
