from __future__ import annotations

import re


def parse_device_model(device_output: str) -> str | None:
    lines = [line.rstrip() for line in (device_output or "").splitlines()]
    for index, line in enumerate(lines):
        lower = line.lower()
        if "board type" in lower:
            model = _first_data_value(lines[index + 1 :], 1)
            if model:
                return model
        if re.search(r"\bslot\s+type\b", lower):
            model = _first_data_value(lines[index + 1 :], 1)
            if model:
                return model
    for line in lines:
        match = re.search(r"(?i)(?:Device|Chassis|Product)\s+(?:Model|Name)\s*[:：]\s*(.+)", line)
        if match:
            return match.group(1).strip()
    return None


def parse_device(version_output: str, device_output: str = "", manuinfo_output: str = "") -> dict[str, object | None]:
    from netconsole.parsers.h3c.version_parser import parse_version

    facts = parse_version(version_output, device_output, manuinfo_output)
    facts["model"] = parse_device_model(device_output) or facts.get("model")
    return facts


def _first_data_value(lines: list[str], column_index: int) -> str | None:
    for line in lines:
        stripped = line.strip()
        if not stripped or set(stripped) <= {"-"}:
            continue
        parts = re.split(r"\s+", stripped)
        if len(parts) > column_index:
            return parts[column_index].strip()
    return None
