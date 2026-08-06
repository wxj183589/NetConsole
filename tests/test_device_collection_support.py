from __future__ import annotations

from netconsole.models.device import Device, normalize_device_vendor_key
from netconsole.services.device_collection_support import resolve_device_collection_support


def test_vendor_text_is_preserved_and_driver_key_is_shared() -> None:
    values = {
        "Huawei": "huawei",
        "华为": "huawei",
        "Mexon": "mexon",
        "兆越": "mexon",
        "现场自研厂商": "unknown",
    }
    for raw, key in values.items():
        device = Device(name="设备", device_vendor=raw, device_type="SW")
        assert device.device_vendor == raw
        assert device.vendor_key == key
        assert normalize_device_vendor_key(raw) == key


def test_unsupported_vendors_fail_closed_before_collection() -> None:
    for raw in ("Huawei", "华为", "Mexon", "兆越", "未知厂商"):
        support = resolve_device_collection_support(
            Device(name="设备", device_vendor=raw, device_type="SW"),
            "device.inventory.collect",
        )
        assert support.supported is False
        assert support.driver_key is None
        assert support.reason_code == "UNSUPPORTED_VENDOR"


def test_supported_profiles_are_explicit_and_unsupported_type_is_skipped() -> None:
    h3c = resolve_device_collection_support(
        Device(name="H3C", device_vendor="H3C", device_type="SW"),
        "device.inventory.collect",
    )
    zte = resolve_device_collection_support(
        Device(name="ZTE", device_vendor="ZTE", device_type="SW"),
        "device.inventory.collect",
    )
    zte_ac = resolve_device_collection_support(
        Device(name="ZTE-AC", device_vendor="ZTE", device_type="AC"),
        "device.inventory.collect",
    )
    assert h3c.supported is True
    assert h3c.driver_key and h3c.driver_key.startswith("h3c.comware")
    assert zte.supported is True
    assert zte.driver_key == "zte.zxr10.switch.generic.device-inventory.v3"
    assert zte_ac.supported is False
    assert zte_ac.reason_code == "UNSUPPORTED_DEVICE_TYPE"
