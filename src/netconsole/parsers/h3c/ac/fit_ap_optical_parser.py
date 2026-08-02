from __future__ import annotations

import re

from netconsole.parsers.h3c.transceiver_parser import merge_transceiver_data, parse_transceiver_diagnosis, parse_transceiver_manuinfo, parse_transceivers
from netconsole.parsers.h3c.ac.fit_ap_lldp_neighbor_parser import (
    has_fit_ap_lldp_table_header,
    parse_fit_ap_lldp_neighbor,
)
from netconsole.services.fit_ap_link_info import normalize_interface_key, resolve_optical_match_status
from netconsole.utils.interface_normalize import normalize_interface_name


MAC_RE = re.compile(r"\b[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}\b", re.IGNORECASE)
INTERFACE_RE = re.compile(r"\b(?:[A-Za-z]+Ethernet|GE|XGE|Ten-GigabitEthernet|TenGigabitEthernet|Ten-GE|Ten|XGigabitEthernet|GigabitEthernet)\S+\b", re.IGNORECASE)


def parse_fit_ap_optical(
    lldp_output: str,
    transceiver_output: str,
    transceiver_interface_output: str = "",
    transceiver_manuinfo_output: str = "",
) -> dict[str, object | None]:
    lldp = parse_fit_ap_lldp(lldp_output)
    transceiver = parse_fit_ap_transceiver(
        transceiver_output,
        transceiver_interface_output,
        transceiver_manuinfo_output,
        preferred_interface=lldp.get("lldp_local_interface") or lldp.get("interface_name"),
    )
    link_match_status = resolve_optical_match_status(lldp, transceiver)
    return {
        **lldp,
        **transceiver,
        "interface_name": transceiver.get("interface_name") or lldp.get("interface_name") or lldp.get("lldp_local_interface"),
        "optical_interface": transceiver.get("interface_name"),
        "optical_interface_normalized": normalize_interface_key(transceiver.get("interface_name")),
        "link_match_status": link_match_status,
        "source": "ap_optical_diag",
    }


def parse_fit_ap_lldp(output: str) -> dict[str, object | None]:
    direct = parse_fit_ap_lldp_neighbor(output)
    if has_fit_ap_lldp_table_header(output) or any(
        direct.get(field)
        for field in (
            "lldp_neighbor_name",
            "lldp_local_interface",
            "lldp_neighbor_mac",
            "lldp_neighbor_interface",
        )
    ):
        return {
            **direct,
            "lldp_neighbor": direct.get("lldp_neighbor_name"),
            "interface_name": direct.get("lldp_local_interface"),
            "neighbor_interface": direct.get("lldp_neighbor_interface"),
            "neighbor_mac": direct.get("lldp_neighbor_mac"),
            "neighbor_device_name": direct.get("lldp_neighbor_name"),
        }
    for line in (output or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("-") or stripped.lower().startswith(("chassis id", "system name")):
            continue
        parts = re.split(r"\s{2,}", stripped)
        if len(parts) >= 4:
            return {
                "lldp_neighbor": parts[0],
                "interface_name": normalize_interface_name(parts[1]),
                "neighbor_interface": normalize_interface_name(parts[3]),
                "neighbor_mac": _first_mac(stripped) or parts[2],
            }
        tokens = stripped.split()
        if len(tokens) >= 4 and _looks_like_interface(tokens[1]):
            return {
                "lldp_neighbor": tokens[0],
                "interface_name": normalize_interface_name(tokens[1]),
                "neighbor_interface": normalize_interface_name(tokens[3]),
                "neighbor_mac": _first_mac(stripped) or tokens[2],
            }

    result: dict[str, object | None] = {"lldp_neighbor": None, "interface_name": None, "neighbor_interface": None, "neighbor_mac": None}
    current_system = None
    for line in (output or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if re.search(r"System\s+name|Neighbor", stripped, re.IGNORECASE) and ":" in stripped:
            current_system = stripped.split(":", 1)[1].strip()
            result["lldp_neighbor"] = current_system
        elif re.search(r"Port\s+ID|Neighbor\s+interface", stripped, re.IGNORECASE) and ":" in stripped:
            result["neighbor_interface"] = normalize_interface_name(stripped.split(":", 1)[1].strip())
        elif re.search(r"Local\s+interface", stripped, re.IGNORECASE) and ":" in stripped:
            result["interface_name"] = normalize_interface_name(stripped.split(":", 1)[1].strip())
        mac = _first_mac(stripped)
        if mac:
            result["neighbor_mac"] = mac
    if current_system:
        result["lldp_neighbor"] = current_system
    return result


def parse_fit_ap_transceiver(
    output: str,
    interface_output: str = "",
    manuinfo_output: str = "",
    preferred_interface: object = None,
) -> dict[str, object | None]:
    result: dict[str, object | None] = {
        "interface_name": None,
        "temperature": None,
        "tx_power": None,
        "rx_power": None,
        "rx_low_alarm": None,
        "rx_high_alarm": None,
        "tx_low_alarm": None,
        "tx_high_alarm": None,
        "rx_low_warning": None,
        "rx_high_warning": None,
        "tx_low_warning": None,
        "tx_high_warning": None,
        "module_model": None,
        "module_serial_number": None,
        "module_vendor": None,
        "wavelength": None,
        "transmission_distance": None,
        "connector_type": None,
    }
    merged = merge_transceiver_data(
        parse_transceiver_diagnosis(output),
        parse_transceivers(interface_output),
        parse_transceiver_manuinfo(manuinfo_output),
    )
    selected = _select_transceiver_module(merged, preferred_interface)
    if selected:
        result.update({key: value for key, value in selected.items() if value is not None})
        _normalize_numeric_fields(result)
        return result

    lines = [line.rstrip() for line in (output or "").splitlines()]
    for line in lines:
        iface_match = re.search(r"^([A-Za-z][A-Za-z-]*Ethernet\S+)\s+transceiver diagnostic information", line, re.IGNORECASE)
        if iface_match:
            result["interface_name"] = normalize_interface_name(iface_match.group(1))
            continue
        if result["interface_name"] is None:
            generic = INTERFACE_RE.search(line)
            if generic and "diagnostic" in line.lower():
                result["interface_name"] = normalize_interface_name(generic.group(0).rstrip(":"))

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
    _normalize_numeric_fields(result)
    return result


def parse_fit_ap_transceiver_diagnosis_snapshots(output: str) -> list[dict[str, object | None]]:
    snapshots = []
    for item in parse_transceiver_diagnosis(output):
        row = dict(item)
        row["optical_interface"] = row.get("interface_name")
        row["optical_interface_normalized"] = normalize_interface_key(row.get("interface_name"))
        _normalize_numeric_fields(row)
        snapshots.append(row)
    return snapshots


def _select_transceiver_module(
    modules: list[dict[str, object | None]],
    preferred_interface: object = None,
) -> dict[str, object | None] | None:
    if not modules:
        return None
    preferred_key = normalize_interface_name(preferred_interface).casefold()
    valid_modules = [module for module in modules if _has_optical_data(module)]
    if preferred_key:
        for module in valid_modules:
            if normalize_interface_name(module.get("interface_name")).casefold() == preferred_key:
                return module
    if len(valid_modules) == 1:
        return valid_modules[0]
    if valid_modules:
        return valid_modules[0]
    if preferred_key:
        for module in modules:
            if normalize_interface_name(module.get("interface_name")).casefold() == preferred_key:
                return module
    return modules[0]


def _has_optical_data(module: dict[str, object | None]) -> bool:
    return any(
        module.get(field) not in (None, "")
        for field in (
            "rx_power",
            "tx_power",
            "temperature",
            "module_model",
            "module_serial_number",
            "module_vendor",
        )
    )


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


def _looks_like_interface(value: object) -> bool:
    return bool(INTERFACE_RE.search(str(value or "")))


def _normalize_numeric_fields(result: dict[str, object | None]) -> None:
    for field in (
        "temperature",
        "tx_power",
        "rx_power",
        "rx_low_alarm",
        "rx_high_alarm",
        "tx_low_alarm",
        "tx_high_alarm",
        "rx_low_warning",
        "rx_high_warning",
        "tx_low_warning",
        "tx_high_warning",
    ):
        value = result.get(field)
        if value in (None, ""):
            continue
        match = re.search(r"[-+]?\d+(?:\.\d+)?", str(value))
        if match:
            result[field] = match.group(0)
