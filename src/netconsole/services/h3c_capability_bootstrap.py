from __future__ import annotations

from dataclasses import dataclass

from netconsole.models.device import Device
from netconsole.models.device_detail import DevicePlatformFacts, identify_device_platform
from netconsole.parsers.h3c.device_parser import parse_device
from netconsole.services import command_guard, netmiko_connection
from netconsole.services.device_command_profile_service import DeviceCommandProfileNotFound
from netconsole.services.netmiko_connection import (
    build_netmiko_params,
    choose_connection_target,
    safe_send_command,
)
from netconsole.utils.text_encoding import clean_h3c_device_text


H3C_VERSION_PROBE_COMMAND = "display version"


@dataclass(frozen=True)
class H3cVersionProbe:
    output: str
    facts: DevicePlatformFacts


def probe_h3c_comware_version(
    device: Device,
    *,
    paths,
    site_id: str,
    collector: str,
    context: str,
) -> H3cVersionProbe:
    """Read the live Comware version before building a H3C capability plan."""

    if device.vendor_key != "h3c":
        raise DeviceCommandProfileNotFound(
            f"H3C Comware version probe requires vendor=H3C, got {device.device_vendor}"
        )
    target = choose_connection_target(device)
    if target is None:
        raise DeviceCommandProfileNotFound("H3C_COMWARE_MAJOR_UNRESOLVED: 未启用连接方式")
    # Version discovery is a shared read-only precondition.  Validate it
    # against the existing AC information context rather than widening each
    # purpose-specific resource/action command set.
    command_guard.validate_command_list(
        (H3C_VERSION_PROBE_COMMAND,), "ac_info_collect"
    )
    connection = None
    try:
        with netmiko_connection.ssh_connection_context(
            collector,
            "collect",
            device_uuid=str(device.device_uuid or ""),
            paths=paths,
            site_id=site_id,
        ):
            connection = netmiko_connection.ConnectHandler(**build_netmiko_params(target))
        output = safe_send_command(
            connection,
            H3C_VERSION_PROBE_COMMAND,
            read_timeout=30,
            strip_prompt=False,
            strip_command=False,
            use_timing=True,
            encoding=netmiko_connection.encoding_for_vendor(device.device_vendor),
        )
    except Exception as exc:
        raise DeviceCommandProfileNotFound(
            f"H3C_COMWARE_MAJOR_UNRESOLVED: version bootstrap failed: {exc}"
        ) from exc
    finally:
        if connection is not None:
            try:
                connection.disconnect()
            except Exception:
                pass

    cleaned = clean_h3c_device_text(output)
    parsed = parse_device(cleaned)
    software_version = str(parsed.get("software_version") or "").strip() or None
    facts = identify_device_platform(
        vendor=device.device_vendor,
        device_type=device.device_type,
        software_version=software_version,
    )
    if facts.software_major is None:
        raise DeviceCommandProfileNotFound(
            "H3C_COMWARE_MAJOR_UNRESOLVED: display version 未解析出 Comware major"
        )
    return H3cVersionProbe(output=cleaned, facts=facts)


__all__ = ["H3C_VERSION_PROBE_COMMAND", "H3cVersionProbe", "probe_h3c_comware_version"]
