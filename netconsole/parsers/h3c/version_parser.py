from __future__ import annotations

import re


def parse_version(version_output: str, device_output: str = "", manuinfo_output: str = "") -> dict[str, object | None]:
    text = "\n".join([version_output or "", device_output or "", manuinfo_output or ""])
    chassis = _parse_chassis_manuinfo(manuinfo_output)
    return {
        "sysname": _first_match(version_output or "", r"^\s*([A-Za-z0-9_.-]+)\s+uptime is\b", re.MULTILINE),
        "model": chassis.get("model") or _parse_model_from_uptime(version_output or "") or _first_match(text, r"(?i)(?:Device|Chassis|Product)\s+(?:Model|Name)\s*[:：]\s*(.+)"),
        "serial_number": chassis.get("serial_number") or _first_match(text, r"(?i)(?:Serial Number|DEVICE_SERIAL_NUMBER|SN)\s*[:：]\s*(\S+)"),
        "mac_address": chassis.get("mac_address") or normalize_device_mac(_first_match(text, r"(?i)MAC_ADDRESS\s*[:\uff1a]\s*([0-9A-Fa-f]{4}[-:][0-9A-Fa-f]{4}[-:][0-9A-Fa-f]{4}|[0-9A-Fa-f]{12})")),
        "software_version": _parse_comware_version(version_output or "") or _first_match(text, r"(?i)Software Version\s*[:：]\s*(.+)"),
        "bootrom_version": _first_match(text, r"(?i)Boot(?:Rom|Ware)?\s+(?:Version|version)\s*[:：]?\s*(.+)"),
        "vendor": chassis.get("vendor") or "H3C",
        "uptime": _parse_uptime(version_output or ""),
    }


def _first_match(text: str, pattern: str, flags: int = 0) -> str | None:
    match = re.search(pattern, text, flags)
    return match.group(1).strip() if match else None


def normalize_device_mac(value: object) -> str | None:
    hex_text = re.sub(r"[^0-9a-fA-F]", "", str(value or ""))
    if len(hex_text) != 12:
        return None
    hex_text = hex_text.casefold()
    return f"{hex_text[0:4]}-{hex_text[4:8]}-{hex_text[8:12]}"


def _parse_comware_version(version_output: str) -> str | None:
    match = re.search(
        r"(?i)(?:H3C\s+)?Comware Software,\s*Version\s+([0-9.]+),\s*Release\s+([A-Za-z0-9]+)",
        version_output,
    )
    if match:
        return f"Version {match.group(1)} Release {match.group(2)}"
    legacy = re.search(r"(?i)((?:H3C\s+)?Comware Software,\s*Version\s+.+)", version_output)
    return legacy.group(1).strip() if legacy else None


def _parse_uptime(version_output: str) -> str | None:
    lines = version_output.splitlines()
    for index, line in enumerate(lines):
        match = re.search(r"(?i)\buptime is\b\s*(.*)$", line)
        if not match:
            continue
        value = match.group(1).strip()
        if value:
            return value
        for next_line in lines[index + 1 :]:
            stripped = next_line.strip()
            if stripped:
                return stripped
    return None


def _parse_model_from_uptime(version_output: str) -> str | None:
    match = re.search(r"(?im)^\s*H3C\s+(\S+)\s+uptime is\b", version_output)
    return match.group(1).strip() if match else None


def _parse_chassis_manuinfo(manuinfo_output: str) -> dict[str, str]:
    result: dict[str, str] = {}
    in_chassis = False
    for raw_line in manuinfo_output.splitlines():
        line = raw_line.strip()
        lower = line.lower()
        if lower.startswith("chassis self"):
            in_chassis = True
            continue
        if in_chassis and re.match(r"(?i)^(slot|fan|power|module)\b", line):
            break
        if not in_chassis or ":" not in line:
            continue
        key, value = [part.strip() for part in line.split(":", 1)]
        if key == "DEVICE_NAME":
            result["model"] = value
        elif key == "DEVICE_SERIAL_NUMBER":
            result["serial_number"] = value
        elif key == "MAC_ADDRESS":
            normalized = normalize_device_mac(value)
            if normalized:
                result["mac_address"] = normalized
        elif key == "VENDOR_NAME":
            result["vendor"] = value
    return result
