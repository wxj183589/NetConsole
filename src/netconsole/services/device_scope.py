"""Shared current-debug device scope contract."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, TypeVar

from netconsole.models.device import Device, is_device_eligible_for_automatic_collection


T = TypeVar("T", bound=Device)


class DeviceRepositoryLike(Protocol):
    def list(self, **filters: object) -> list[Device]: ...


class DeviceOutOfCurrentDebugScopeError(ValueError):
    code = "DEVICE_OUT_OF_CURRENT_DEBUG_SCOPE"

    def __init__(self, device: Device) -> None:
        self.device_uuid = str(device.device_uuid or "")
        self.device_name = str(device.name or self.device_uuid)
        super().__init__(f"设备 {self.device_name} 当前未参与调试")


def is_current_debug_device(device: Device) -> bool:
    """The one canonical predicate for automatic/current-debug consumers."""

    return is_device_eligible_for_automatic_collection(device)


def filter_current_debug_devices(devices: Iterable[T]) -> list[T]:
    return [device for device in devices if is_current_debug_device(device)]


def list_current_debug_devices(
    repository: DeviceRepositoryLike,
    **filters: object,
) -> list[Device]:
    """List devices for an operational consumer with scope enforced in SQL."""

    return repository.list(**filters, work_scope_status="included")


def require_current_debug_device(device: T | None) -> T:
    if device is None:
        raise KeyError("Device not found")
    if not is_current_debug_device(device):
        raise DeviceOutOfCurrentDebugScopeError(device)
    return device


__all__ = [
    "DeviceOutOfCurrentDebugScopeError",
    "filter_current_debug_devices",
    "is_current_debug_device",
    "list_current_debug_devices",
    "require_current_debug_device",
]
