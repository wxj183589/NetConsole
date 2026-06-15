from __future__ import annotations

import re

from netconsole.utils.text_encoding import clean_h3c_device_text


INTERFACE_NAME = r"(?:[A-Za-z][A-Za-z-]*Ethernet|FortyGigE|Ten-GigabitEthernet|Twenty-FiveGigE|HundredGigE|GigabitEthernet)[\d/.:]+|Vlan-interface\d+|Bridge-Aggregation\d+|LoopBack\d+|NULL\d+"
INTERFACE_HEADER = re.compile(rf"^({INTERFACE_NAME})\s+current state:\s+(.+)$", re.IGNORECASE)
INTERFACE_NAME_ONLY = re.compile(rf"^({INTERFACE_NAME})$", re.IGNORECASE)


def parse_interfaces(output: str) -> list[dict[str, object | None]]:
    interfaces: list[dict[str, object | None]] = []
    current: dict[str, object | None] | None = None
    pending_name: str | None = None
    for raw_line in (output or "").splitlines():
        line = raw_line.rstrip()
        header = INTERFACE_HEADER.match(line.strip())
        if header:
            if current:
                interfaces.append(_finalize_interface(current))
            current = {
                "interface_name": header.group(1),
                "link_status": header.group(2).strip(),
            }
            pending_name = None
            continue
        name_only = INTERFACE_NAME_ONLY.match(line.strip())
        if name_only:
            if current:
                interfaces.append(_finalize_interface(current))
            pending_name = name_only.group(1)
            current = None
            continue
        if pending_name and line.strip().lower().startswith("current state:"):
            current = {
                "interface_name": pending_name,
                "link_status": line.split(":", 1)[1].strip(),
            }
            pending_name = None
            continue
        if current is None:
            continue
        stripped = line.strip()
        if stripped.startswith("Line protocol current state:") or stripped.startswith("Line protocol state:"):
            current["protocol_status"] = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("Description:"):
            current["description"] = clean_h3c_device_text(stripped.split(":", 1)[1].strip())
        elif stripped.lower().startswith("internet address"):
            address = _parse_internet_address(stripped)
            if address:
                current.setdefault("_ip_candidates", []).append(address)
        elif stripped.lower().startswith("ip packet frame type:"):
            mac = re.search(r"hardware address:\s*([0-9A-Fa-f.-]+)", stripped, re.IGNORECASE)
            if mac:
                current["mac_address"] = mac.group(1)
        elif stripped.startswith("PVID:"):
            current["pvid"] = stripped.split(":", 1)[1].strip()
            current["_has_l2"] = True
        elif stripped.startswith("Port link-type:"):
            current["_link_type"] = stripped.split(":", 1)[1].strip().lower()
            current["_has_l2"] = True
        elif vlan_value := _parse_vlan_line(stripped):
            current.setdefault("_vlan_values", {})[vlan_value[0]] = vlan_value[1]
            current["_has_l2"] = True
        elif stripped.startswith("The Maximum Transmit Unit"):
            pass
        elif "Media type is" in stripped:
            pass
        elif stripped.startswith("Speed :"):
            current["speed"] = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("Duplex:"):
            current["duplex"] = stripped.split(":", 1)[1].strip()
        else:
            speed_duplex = re.search(r"([0-9]+[GMK]?bps)-speed mode,\s*([A-Za-z-]+)-duplex mode", stripped, re.IGNORECASE)
            if speed_duplex:
                current["speed"] = speed_duplex.group(1)
                current["duplex"] = speed_duplex.group(2)
    if current:
        interfaces.append(_finalize_interface(current))
    return interfaces


def _parse_internet_address(line: str) -> dict[str, object] | None:
    match = re.search(r"(?i)internet address(?: is)?\s*:\s*([0-9a-fA-F:.]+/\d+)\s*(.*)$", line)
    if not match:
        match = re.search(r"(?i)internet address is\s+([0-9a-fA-F:.]+/\d+)\s*(.*)$", line)
    if not match:
        return None
    suffix = match.group(2) or ""
    return {"value": match.group(1), "primary": "primary" in suffix.lower()}


def _parse_vlan_line(line: str) -> tuple[str, str] | None:
    match = re.match(r"(?i)^(tagged vlans|untagged vlans|vlan passing|vlan permitted)\s*:?\s*(.+)$", line)
    if not match:
        return None
    key = match.group(1).strip().lower().replace(" ", "_")
    if key == "vlan_passing":
        key = "passing"
    elif key == "vlan_permitted":
        key = "permitted"
    elif key == "tagged_vlans":
        key = "tagged"
    elif key == "untagged_vlans":
        key = "untagged"
    return key, match.group(2).strip()


def _finalize_interface(item: dict[str, object | None]) -> dict[str, object | None]:
    ip_candidates = item.pop("_ip_candidates", []) or []
    vlan_values = item.pop("_vlan_values", {}) or {}
    has_l2 = bool(item.pop("_has_l2", False))
    link_type = str(item.pop("_link_type", "") or "").strip().lower()
    if ip_candidates:
        primary = next((candidate for candidate in ip_candidates if candidate.get("primary")), ip_candidates[0])
        item["ip_address"] = primary.get("value")
        item["interface_type"] = "三层"
    elif has_l2:
        item["interface_type"] = "二层"
    vlan = _select_vlan_summary(link_type, vlan_values)
    if vlan:
        item["vlan"] = vlan
    link_state = str(item.get("link_status") or "").lower()
    description = str(item.get("description") or "").lower()
    if "administratively down" in link_state or "shutdown" in description:
        item["port_status"] = "shutdown"
    elif item.get("interface_type") == "三层":
        item["port_status"] = "route"
    elif link_type in {"access", "hybrid", "trunk"}:
        item["port_status"] = link_type
    return item


def _select_vlan_summary(link_type: str, values: dict[str, str]) -> str | None:
    if link_type == "access":
        return values.get("untagged") or values.get("permitted")
    if link_type == "trunk":
        return values.get("passing") or values.get("permitted")
    if link_type == "hybrid":
        summary: list[str] = []
        if values.get("tagged"):
            summary.append(f"Tagged: {values['tagged']}")
        if values.get("untagged"):
            summary.append(f"Untagged: {values['untagged']}")
        return "; ".join(summary) or values.get("permitted")
    if values.get("untagged"):
        return values["untagged"]
    if values.get("passing"):
        return values["passing"]
    if values.get("tagged") or values.get("untagged"):
        summary = []
        if values.get("tagged"):
            summary.append(f"Tagged: {values['tagged']}")
        if values.get("untagged"):
            summary.append(f"Untagged: {values['untagged']}")
        return "; ".join(summary)
    return values.get("permitted")
