from __future__ import annotations

import re


def parse_transceivers(output: str) -> list[dict[str, object | None]]:
    modules: list[dict[str, object | None]] = []
    current: dict[str, object | None] | None = None
    for raw_line in (output or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        iface = re.match(r"^([A-Za-z][A-Za-z-]*Ethernet[\d/.:]+)\s+transceiver information", line, re.IGNORECASE)
        if iface:
            if current:
                modules.append(current)
            current = {"interface_name": iface.group(1)}
            continue
        if current is None:
            continue
        _set_if_match(current, "module_model", line, r"(?i)(?:Transceiver Type|Part Number|Model)\s*[:：]\s*(.+)")
        _set_if_match(current, "module_serial_number", line, r"(?i)(?:Serial Number|S/N)\s*[:：]\s*(.+)")
        _set_if_match(current, "module_vendor", line, r"(?i)(?:Vendor Name|Vendor)\s*[:：]\s*(.+)")
        _set_if_match(current, "wavelength", line, r"(?i)Wavelength\s*[:：]\s*(.+)")
        _set_if_match(current, "transmission_distance", line, r"(?i)(?:Transfer Distance|Transmission Distance|Distance)\s*[:：]\s*(.+)")
        _set_if_match(current, "connector_type", line, r"(?i)Connector Type\s*[:：]\s*(.+)")
    if current:
        modules.append(current)
    return modules


def parse_transceiver_diagnosis(output: str) -> list[dict[str, object | None]]:
    modules: list[dict[str, object | None]] = []
    current: dict[str, object | None] | None = None
    for raw_line in (output or "").splitlines():
        line = raw_line.strip()
        iface = re.match(r"^([A-Za-z][A-Za-z-]*Ethernet[\d/.:]+)\s+transceiver diagnostic information", line, re.IGNORECASE)
        if iface:
            if current:
                modules.append(current)
            current = {"interface_name": iface.group(1)}
            continue
        if current is None:
            continue
        _set_if_match(current, "temperature", line, r"(?i)Temperature\s*[:：]\s*(.+)")
        _set_if_match(current, "voltage", line, r"(?i)Voltage\s*[:：]\s*(.+)")
        _set_if_match(current, "bias_current", line, r"(?i)(?:Bias Current|Current)\s*[:：]\s*(.+)")
        _set_if_match(current, "rx_power", line, r"(?i)(?:RX Power|Rx Power|Receive Power)\s*[:：]\s*(.+)")
        _set_if_match(current, "tx_power", line, r"(?i)(?:TX Power|Tx Power|Transmit Power)\s*[:：]\s*(.+)")
        _set_if_match(current, "rx_low_alarm", line, r"(?i)Rx low alarm\s*[:：]\s*(.+)")
        _set_if_match(current, "rx_high_alarm", line, r"(?i)Rx high alarm\s*[:：]\s*(.+)")
        _set_if_match(current, "tx_low_alarm", line, r"(?i)Tx low alarm\s*[:：]\s*(.+)")
        _set_if_match(current, "tx_high_alarm", line, r"(?i)Tx high alarm\s*[:：]\s*(.+)")
        _set_if_match(current, "status", line, r"(?i)Status\s*[:：]\s*(.+)")
    if current:
        modules.append(current)
    return modules


def merge_transceiver_data(base: list[dict[str, object | None]], diagnosis: list[dict[str, object | None]]) -> list[dict[str, object | None]]:
    merged: dict[str, dict[str, object | None]] = {}
    for item in base + diagnosis:
        name = str(item.get("interface_name") or "")
        if not name:
            continue
        merged.setdefault(name, {"interface_name": name}).update({key: value for key, value in item.items() if value})
    return list(merged.values())


def _set_if_match(target: dict[str, object | None], field: str, text: str, pattern: str) -> None:
    match = re.search(pattern, text)
    if match:
        target[field] = match.group(1).strip()
