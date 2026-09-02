from __future__ import annotations

import re


_COMWARE_VERSION_RE = re.compile(
    r"(?i)(?:\bcomware\s+(?:software|platform\s+software)\s*,\s*)?"
    r"\bversion\s+([0-9]+(?:\.[0-9]+)+)\s*,?\s*"
    r"\brelease\s+([A-Za-z0-9]+)"
)


def parse_version(version_output: str, device_output: str = "", manuinfo_output: str = "") -> dict[str, object | None]:
    text = "\n".join([version_output or "", device_output or "", manuinfo_output or ""])
    chassis = _parse_chassis_manuinfo(manuinfo_output)
    comware = parse_comware_version_details(version_output or "")
    return {
        "sysname": _first_match(version_output or "", r"^\s*([A-Za-z0-9_.-]+)\s+uptime is\b", re.MULTILINE),
        "model": chassis.get("model") or _parse_model_from_uptime(version_output or "") or _first_match(text, r"(?i)(?:Device|Chassis|Product)\s+(?:Model|Name)\s*[:：]\s*(.+)"),
        "serial_number": chassis.get("serial_number") or _first_match(text, r"(?i)(?:Serial Number|DEVICE_SERIAL_NUMBER|SN)\s*[:：]\s*(\S+)"),
        "mac_address": chassis.get("mac_address") or normalize_device_mac(_first_match(text, r"(?i)MAC_ADDRESS\s*[:\uff1a]\s*([0-9A-Fa-f]{4}[-:][0-9A-Fa-f]{4}[-:][0-9A-Fa-f]{4}|[0-9A-Fa-f]{12})")),
        "software_version": (
            str(comware["software_version"])
            if comware
            else _first_match(text, r"(?i)Software Version\s*[:：]\s*(.+)")
        ),
        "software_family": comware.get("software_family") if comware else None,
        "software_major_version": comware.get("software_major_version") if comware else None,
        "software_train": comware.get("software_train") if comware else None,
        "software_release": comware.get("software_release") if comware else None,
        "platform_family": "comware" if comware else None,
        "platform_major_version": comware.get("software_major_version") if comware else None,
        "bootrom_version": _first_match(text, r"(?i)Boot(?:Rom|Ware)?\s+(?:Version|version)\s*[:：]?\s*(.+)"),
        "vendor": chassis.get("vendor") or "H3C",
        "uptime": _parse_uptime(version_output or ""),
        "uptime_seconds": parse_uptime_seconds(_parse_uptime(version_output or "")),
        "uptime_precision_seconds": uptime_precision_seconds(
            _parse_uptime(version_output or "")
        ),
        "last_reboot_reason": _first_match(
            version_output or "",
            r"(?im)^\s*Last\s+reboot\s+reason\s*[:：]\s*(.+?)\s*$",
        ),
    }


def parse_uptime_seconds(value: object) -> int | None:
    """解析 Comware v7/v9 display version 的英文 uptime 文本。"""

    text = str(value or "").strip().casefold()
    if not text:
        return None
    units = {
        "year": 365 * 24 * 3600,
        "week": 7 * 24 * 3600,
        "day": 24 * 3600,
        "hour": 3600,
        "minute": 60,
        "second": 1,
    }
    matches = re.findall(
        r"(\d+)\s*(years?|weeks?|days?|hours?|minutes?|seconds?)\b", text
    )
    if not matches:
        return None
    return sum(int(number) * units[unit.removesuffix("s")] for number, unit in matches)


def uptime_precision_seconds(value: object) -> int | None:
    text = str(value or "").strip().casefold()
    if not text:
        return None
    units = [unit.removesuffix("s") for _number, unit in re.findall(
        r"(\d+)\s*(years?|weeks?|days?|hours?|minutes?|seconds?)\b", text
    )]
    if not units:
        return None
    precision = {
        "year": 365 * 24 * 3600,
        "week": 7 * 24 * 3600,
        "day": 24 * 3600,
        "hour": 3600,
        "minute": 60,
        "second": 1,
    }
    return min(precision[unit] for unit in units)


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
    details = parse_comware_version_details(version_output)
    if details:
        return str(details["software_version"])
    legacy = re.search(r"(?i)((?:H3C\s+)?Comware Software,\s*Version\s+.+)", version_output)
    return legacy.group(1).strip() if legacy else None


def parse_comware_version_details(value: object) -> dict[str, object] | None:
    """解析完整或简写的 Comware 软件版本行。"""

    text = str(value or "")
    match = _COMWARE_VERSION_RE.search(text)
    if not match:
        return None
    version = match.group(1)
    release = match.group(2)
    parts = version.split(".")
    major = int(parts[0])
    train = ".".join(parts[:2]) if len(parts) >= 2 else parts[0]
    return {
        "software_family": "Comware",
        "software_version": f"Version {version} Release {release}",
        "software_major_version": major,
        "software_train": train,
        "software_release": release,
    }


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


__all__ = [
    "normalize_device_mac",
    "parse_comware_version_details",
    "parse_version",
    "parse_uptime_seconds",
    "uptime_precision_seconds",
]
