from __future__ import annotations

import re


def parse_version(version_output: str, device_output: str = "", manuinfo_output: str = "") -> dict[str, object | None]:
    text = "\n".join([version_output or "", device_output or "", manuinfo_output or ""])
    return {
        "sysname": _first_match(text, r"^\s*([A-Za-z0-9_.-]+)\s+uptime is\b", re.MULTILINE),
        "model": _first_match(text, r"(?i)(?:Device|Chassis|Product)\s+(?:Model|Name)\s*[:：]\s*(.+)"),
        "serial_number": _first_match(text, r"(?i)(?:Serial Number|DEVICE_SERIAL_NUMBER|SN)\s*[:：]\s*(\S+)"),
        "software_version": _first_match(text, r"(?i)((?:H3C\s+)?Comware Software, Version .+)")
        or _first_match(text, r"(?i)Software Version\s*[:：]\s*(.+)"),
        "bootrom_version": _first_match(text, r"(?i)Boot(?:Rom|Ware)?\s+(?:Version|version)\s*[:：]?\s*(.+)"),
        "vendor": "H3C",
        "uptime": _first_match(text, r"(?i)uptime is\s+(.+)"),
    }


def _first_match(text: str, pattern: str, flags: int = 0) -> str | None:
    match = re.search(pattern, text, flags)
    return match.group(1).strip() if match else None
