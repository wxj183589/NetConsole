from __future__ import annotations

import re

from netconsole.core.optical_severity_engine import compute_optical_severity


INTERFACE_NAME = r"(?:[A-Za-z][A-Za-z-]*Ethernet|FortyGigE|Ten-GigabitEthernet|Twenty-FiveGigE|HundredGigE|GigabitEthernet|XGE|GE)[\d/.:]+"
NUMBER_PATTERN = re.compile(r"[-+]?\d+(?:\.\d+)?")


def parse_transceivers(output: str) -> list[dict[str, object | None]]:
    modules: list[dict[str, object | None]] = []
    current: dict[str, object | None] | None = None
    for raw_line in (output or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        iface = re.match(rf"^({INTERFACE_NAME})\s+transceiver information", line, re.IGNORECASE)
        if iface:
            if current:
                modules.append(current)
            current = {"interface_name": iface.group(1)}
            continue
        if current is None:
            continue
        _set_if_match(current, "module_model", line, r"(?i)(?:Transceiver Type|Part Number|Model)\s*[:\uff1a]\s*(.+)")
        _set_if_match(current, "module_model", line, r"(?i)Ordering Name\s*[:\uff1a]\s*(.+)", overwrite=True)
        _set_if_match(current, "module_serial_number", line, r"(?i)(?:Serial Number|S/N)\s*[:\uff1a]\s*(.+)")
        _set_if_match(current, "module_vendor", line, r"(?i)(?:Vendor Name|Vendor)\s*[:\uff1a]\s*(.+)")
        _set_if_match(current, "wavelength", line, r"(?i)Wavelength(?:\(nm\))?\s*[:\uff1a]\s*(.+)", formatter=_format_wavelength)
        _set_if_match(current, "transmission_distance", line, r"(?i)(?:Transfer Distance|Transmission Distance|Distance)(?:\(km\))?\s*[:\uff1a]\s*(.+)", formatter=_format_distance)
        _set_if_match(current, "connector_type", line, r"(?i)Connector Type\s*[:\uff1a]\s*(.+)")
        _set_if_match(current, "status", line, r"(?i)Status\s*[:\uff1a]\s*(.+)")
    if current:
        modules.append(current)
    return modules


def parse_transceiver_manuinfo(output: str) -> list[dict[str, object | None]]:
    modules: list[dict[str, object | None]] = []
    current: dict[str, object | None] | None = None
    for raw_line in (output or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        iface = re.match(rf"^({INTERFACE_NAME})\s+transceiver manufacture information", line, re.IGNORECASE)
        if iface:
            if current:
                modules.append(current)
            current = {"interface_name": iface.group(1)}
            continue
        if current is None:
            continue
        _set_if_match(current, "module_serial_number", line, r"(?i)Manu\.\s*Serial Number\s*[:\uff1a]\s*(.+)")
        _set_if_match(current, "module_vendor", line, r"(?i)Vendor Name\s*[:\uff1a]\s*(.+)")
    if current:
        modules.append(current)
    return modules


def parse_transceiver_diagnosis(output: str) -> list[dict[str, object | None]]:
    modules: list[dict[str, object | None]] = []
    current: dict[str, object | None] | None = None
    section = ""
    for raw_line in (output or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        iface = re.match(rf"^({INTERFACE_NAME})\s+transceiver diagnostic information", line, re.IGNORECASE)
        if iface:
            if current:
                modules.append(current)
            current = {"interface_name": iface.group(1)}
            section = ""
            continue
        if current is None:
            continue
        lowered = line.lower()
        if lowered.startswith("current diagnostic parameters"):
            section = "current"
            continue
        if lowered.startswith("alarm thresholds"):
            section = "alarm"
            continue
        if lowered.startswith("warning thresholds"):
            section = "warning"
            continue
        if lowered.startswith(("temp.", "temperature")):
            continue
        if _parse_current_diagnostic_row(current, section, line):
            continue
        if _parse_threshold_row(current, section, line):
            continue
        _set_if_match(current, "temperature", line, r"(?i)Temperature\s*[:\uff1a]\s*(.+)")
        _set_if_match(current, "voltage", line, r"(?i)Voltage\s*[:\uff1a]\s*(.+)")
        _set_if_match(current, "bias_current", line, r"(?i)(?:Bias Current|Current)\s*[:\uff1a]\s*(.+)")
        _set_if_match(current, "rx_power", line, r"(?i)(?:RX Power|Rx Power|Receive Power)\s*[:\uff1a]\s*(.+)")
        _set_if_match(current, "tx_power", line, r"(?i)(?:TX Power|Tx Power|Transmit Power)\s*[:\uff1a]\s*(.+)")
        _set_if_match(current, "rx_low_alarm", line, r"(?i)Rx low alarm\s*[:\uff1a]\s*(.+)")
        _set_if_match(current, "rx_high_alarm", line, r"(?i)Rx high alarm\s*[:\uff1a]\s*(.+)")
        _set_if_match(current, "tx_low_alarm", line, r"(?i)Tx low alarm\s*[:\uff1a]\s*(.+)")
        _set_if_match(current, "tx_high_alarm", line, r"(?i)Tx high alarm\s*[:\uff1a]\s*(.+)")
        _set_if_match(current, "status", line, r"(?i)Status\s*[:\uff1a]\s*(.+)")
    if current:
        modules.append(current)
    return modules


def merge_transceiver_data(*sources: list[dict[str, object | None]]) -> list[dict[str, object | None]]:
    merged: dict[str, dict[str, object | None]] = {}
    for source in sources:
        for item in source:
            name = str(item.get("interface_name") or "")
            if not name:
                continue
            merged.setdefault(name, {"interface_name": name}).update({key: value for key, value in item.items() if value})
    return list(merged.values())


def evaluate_optical_status(optical: dict[str, object | None], interface: dict[str, object | None] | None) -> dict[str, str | None]:
    interface_name = str(optical.get("interface_name") or "")
    description = str((interface or {}).get("description") or "")
    if "OLT" in interface_name.upper() or "ONU" in interface_name.upper() or "OLT" in description.upper() or "ONU" in description.upper():
        return {"status": "skipped", "reason": "OLT/ONU interface skipped"}
    if interface and str(interface.get("port_status") or "").casefold() == "shutdown":
        return {"status": "skipped", "reason": "interface shutdown"}

    port_status = "DOWN" if interface and str(interface.get("link_status") or "").upper() != "UP" else "UP"
    result = compute_optical_severity(
        {
            "rx_power": optical.get("rx_power"),
            "tx_power": optical.get("tx_power"),
            "port_status": port_status,
            "alarm_low": optical.get("rx_low_alarm"),
            "alarm_high": optical.get("rx_high_alarm"),
            "warning_low": optical.get("rx_low_warning") or optical.get("rx_low_alarm"),
            "tx_low_alarm": optical.get("tx_low_alarm"),
            "tx_high_alarm": optical.get("tx_high_alarm"),
        }
    )
    return {"status": result.severity, "reason": result.reason}


def _set_if_match(
    target: dict[str, object | None],
    field: str,
    text: str,
    pattern: str,
    overwrite: bool = False,
    formatter=None,
) -> None:
    match = re.search(pattern, text)
    if match and (overwrite or not target.get(field)):
        value = match.group(1).strip()
        target[field] = formatter(value) if formatter else value


def _format_wavelength(value: str) -> str:
    text = value.strip()
    return text if re.search(r"(?i)\bnm\b", text) else f"{text} nm"


def _format_distance(value: str) -> str:
    text = value.strip()
    return text if re.search(r"(?i)\bkm\b", text) else f"{text} km"


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    match = NUMBER_PATTERN.search(str(value))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _parse_current_diagnostic_row(target: dict[str, object | None], section: str, text: str) -> bool:
    if section != "current":
        return False
    values = NUMBER_PATTERN.findall(text)
    if len(values) < 5:
        return False
    target["temperature"] = values[0]
    target["voltage"] = values[1]
    target["bias_current"] = values[2]
    target["rx_power"] = values[3]
    target["tx_power"] = values[4]
    return True


def _parse_threshold_row(
    target: dict[str, object | None],
    section: str,
    text: str,
) -> bool:
    if section not in {"alarm", "warning"}:
        return False
    match = re.match(r"(?i)^(high|low)\s+(.+)$", text.strip())
    if not match:
        return False
    values = NUMBER_PATTERN.findall(match.group(2))
    if len(values) < 5:
        return False
    prefix = match.group(1).lower()
    rx_value = values[3]
    tx_value = values[4]
    if section == "alarm":
        target[f"rx_{prefix}_alarm"] = rx_value
        target[f"tx_{prefix}_alarm"] = tx_value
    else:
        target[f"rx_{prefix}_warning"] = rx_value
        target[f"tx_{prefix}_warning"] = tx_value
    return True
