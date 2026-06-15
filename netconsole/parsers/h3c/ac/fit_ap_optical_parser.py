from __future__ import annotations

import re


MAC_RE = re.compile(r"\b[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}\b", re.IGNORECASE)
INTERFACE_RE = re.compile(r"\b(?:[A-Za-z]+Ethernet|GE|XGE|Ten-GigabitEthernet|GigabitEthernet)\S+\b", re.IGNORECASE)


def parse_fit_ap_optical(lldp_output: str, transceiver_output: str) -> dict[str, object | None]:
    return {
        **parse_fit_ap_lldp(lldp_output),
        **parse_fit_ap_transceiver(transceiver_output),
    }


def parse_fit_ap_lldp(output: str) -> dict[str, object | None]:
    for line in (output or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("-") or stripped.lower().startswith(("chassis id", "system name")):
            continue
        parts = re.split(r"\s{2,}", stripped)
        if len(parts) >= 4:
            return {
                "lldp_neighbor": parts[0],
                "neighbor_interface": parts[3],
                "neighbor_mac": _first_mac(stripped) or parts[2],
            }

    result: dict[str, object | None] = {"lldp_neighbor": None, "neighbor_interface": None, "neighbor_mac": None}
    current_system = None
    for line in (output or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if re.search(r"System\s+name|Neighbor", stripped, re.IGNORECASE) and ":" in stripped:
            current_system = stripped.split(":", 1)[1].strip()
            result["lldp_neighbor"] = current_system
        elif re.search(r"Port\s+ID|Neighbor\s+interface", stripped, re.IGNORECASE) and ":" in stripped:
            result["neighbor_interface"] = stripped.split(":", 1)[1].strip()
        mac = _first_mac(stripped)
        if mac:
            result["neighbor_mac"] = mac
    if current_system:
        result["lldp_neighbor"] = current_system
    return result


def parse_fit_ap_transceiver(output: str) -> dict[str, object | None]:
    result: dict[str, object | None] = {
        "interface_name": None,
        "temperature": None,
        "tx_power": None,
        "rx_power": None,
    }
    lines = [line.rstrip() for line in (output or "").splitlines()]
    for line in lines:
        iface_match = re.search(r"^([A-Za-z][A-Za-z-]*Ethernet\S+)\s+transceiver diagnostic information", line, re.IGNORECASE)
        if iface_match:
            result["interface_name"] = iface_match.group(1)
            continue
        if result["interface_name"] is None:
            generic = INTERFACE_RE.search(line)
            if generic and "diagnostic" in line.lower():
                result["interface_name"] = generic.group(0).rstrip(":")

        inline = _parse_inline_value(line)
        if inline:
            result.update({key: value for key, value in inline.items() if value is not None})

    if not any(result.get(field) for field in ("temperature", "tx_power", "rx_power")):
        for index, line in enumerate(lines):
            if "rx power" in line.lower() and "tx power" in line.lower() and index + 1 < len(lines):
                values = re.findall(r"[-+]?\d+(?:\.\d+)?", lines[index + 1])
                if len(values) >= 5:
                    result["temperature"] = values[0]
                    result["rx_power"] = values[3]
                    result["tx_power"] = values[4]
                    break
    return result


def _parse_inline_value(line: str) -> dict[str, str | None] | None:
    if "dBm" not in line and "Temp" not in line and "Temperature" not in line:
        return None
    data: dict[str, str | None] = {}
    temp = re.search(r"(?:Temp\.?\(C\)|Temperature)\s*[:：]?\s*([-+]?\d+(?:\.\d+)?)", line, re.IGNORECASE)
    rx = re.search(r"(?:RX\s+power|Receive\s+Power)\s*[:：]?\s*([-+]?\d+(?:\.\d+)?)\s*dBm?", line, re.IGNORECASE)
    tx = re.search(r"(?:TX\s+power|Transmit\s+Power)\s*[:：]?\s*([-+]?\d+(?:\.\d+)?)\s*dBm?", line, re.IGNORECASE)
    if temp:
        data["temperature"] = temp.group(1)
    if rx:
        data["rx_power"] = rx.group(1)
    if tx:
        data["tx_power"] = tx.group(1)
    return data or None


def _first_mac(text: str) -> str | None:
    match = MAC_RE.search(text or "")
    return match.group(0) if match else None
