from __future__ import annotations

from ipaddress import ip_address
from typing import Any


class DeviceAddressError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


class InvalidDeviceAddressError(DeviceAddressError):
    def __init__(self, value: object, *, field: str = "主地址") -> None:
        text = str(value or "").strip()
        super().__init__(
            "INVALID_PRIMARY_IP",
            f"{field}不是有效的 IPv4 或 IPv6 地址：{text or '空值'}",
            details={"field": field, "value": text},
        )


class DevicePrimaryAddressConflictError(DeviceAddressError):
    def __init__(
        self,
        normalized_address: str,
        *,
        device_id: int | None = None,
        device_name: str = "",
        site_name: str = "",
    ) -> None:
        location = f"当前局点“{site_name}”" if site_name else "当前局点"
        target = (
            f"设备“{device_name}”（ID {device_id}）"
            if device_name and device_id is not None
            else f"设备 ID {device_id}"
            if device_id is not None
            else "其他设备"
        )
        super().__init__(
            "DEVICE_PRIMARY_IP_CONFLICT",
            f"主地址 {normalized_address} 在{location}内已由{target}使用",
            details={
                "site_name": site_name,
                "normalized_primary_address": normalized_address,
                "conflict_device_id": device_id,
                "conflict_device_name": device_name,
            },
        )


def normalize_ip_address(
    value: object,
    *,
    field: str = "主地址",
    allow_empty: bool = True,
) -> str | None:
    text = str(value or "").strip()
    if not text:
        if allow_empty:
            return None
        raise InvalidDeviceAddressError(value, field=field)
    try:
        return str(ip_address(text))
    except ValueError as exc:
        raise InvalidDeviceAddressError(value, field=field) from exc
