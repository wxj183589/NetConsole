from __future__ import annotations


def device_write_resource_key(site_id: str, device_uuid: str) -> str:
    site = str(site_id or "").strip().casefold()
    device = str(device_uuid or "").strip().casefold()
    if not site or not device:
        raise ValueError("设备写操作资源键缺少局点或设备标识")
    return f"device-write:v1:{site}:{device}"


__all__ = ["device_write_resource_key"]
