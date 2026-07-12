from __future__ import annotations

import re

from netconsole.models.device import Device
from netconsole.models.snmp_models import DeviceSnmpProfileResult, SnmpProfile
from netconsole.services.comware_version_service import parse_comware_version
from netconsole.services.snmp_client import SnmpClient


class DeviceSnmpDetectService:
    def __init__(self, client: SnmpClient | None = None) -> None:
        self.client = client or SnmpClient()

    def detect(self, device: Device, *, cancel_checker=None) -> DeviceSnmpProfileResult:
        profile = SnmpProfile.from_device(device)
        result = self.client.test_device(profile, cancel_checker=cancel_checker)
        if result.get("status") != "success":
            return DeviceSnmpProfileResult(
                device_name=device.name,
                vendor=device.device_vendor or "",
                device_type=device.device_type or "",
                status=str(result.get("status") or "failed"),
                error_message=str(result.get("error_message") or ""),
                latency_ms=int(result.get("latency_ms") or 0),
            )
        sys_descr = str(result.get("sysDescr") or "")
        vendor = device.device_vendor or _infer_vendor(sys_descr)
        model = _infer_model(sys_descr)
        system, version = _infer_system(sys_descr)
        comware = parse_comware_version(sys_descr)
        if comware.vendor:
            vendor = comware.vendor
        if comware.os_family:
            system = comware.os_family
            version = comware.software_version
        return DeviceSnmpProfileResult(
            device_name=str(result.get("sysName") or device.name or ""),
            vendor=vendor,
            device_type=device.device_type or "",
            model=model,
            system=system,
            system_version=version,
            os_family=comware.os_family,
            os_major=comware.os_major,
            release=comware.release,
            release_number=comware.release_number,
            release_patch=comware.release_patch,
            release_series=comware.release_series,
            sys_name=str(result.get("sysName") or ""),
            sys_object_id=str(result.get("sysObjectID") or ""),
            sys_descr=sys_descr,
            sys_up_time=str(result.get("sysUpTime") or ""),
            source="SNMP",
            status="success",
            latency_ms=int(result.get("latency_ms") or 0),
            interface_count=int(result.get("interface_count") or 0),
        )


def _infer_vendor(text: str) -> str:
    upper = text.upper()
    for vendor in ("H3C", "HUAWEI", "CISCO", "RUIJIE"):
        if vendor in upper:
            return "Huawei" if vendor == "HUAWEI" else ("Ruijie" if vendor == "RUIJIE" else vendor)
    return ""


def _infer_model(text: str) -> str:
    patterns = (r"\b(WX[0-9A-Za-z-]+)\b", r"\b(S[0-9][0-9A-Za-z-]+)\b", r"\b(AR[0-9A-Za-z-]+)\b", r"\b(Catalyst\s+[0-9A-Za-z-]+)\b")
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
    return ""


def _infer_system(text: str) -> tuple[str, str]:
    if "Comware" in text:
        match = re.search(r"Comware\s+Software.*?Version\s+([^\s,]+)", text, re.IGNORECASE)
        return "Comware", match.group(1) if match else ""
    if "VRP" in text:
        return "VRP", ""
    if "IOS" in text:
        return "IOS", ""
    return "", ""
