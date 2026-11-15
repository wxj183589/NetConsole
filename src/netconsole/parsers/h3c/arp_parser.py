from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field

from netconsole.utils.mac_utils import normalize_mac


_MAC_RE = re.compile(
    r"(?i)(?:[0-9a-f]{4}[-:.]){2}[0-9a-f]{4}|"
    r"(?:[0-9a-f]{2}[-:.]){5}[0-9a-f]{2}|[0-9a-f]{12}"
)
_IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_MORE_RE = re.compile(r"(?i)(?:--+\s*more\s*--+|----\s*more\s*----|press\s+.+\s+to\s+continue)")
_INCOMPLETE_RE = re.compile(
    r"(?i)(?:truncat(?:ed|ion)|output\s+too\s+long|too\s+many\s+entries|"
    r"incomplete\s+output|command\s+timed\s+out|%\s*(?:unrecognized|incomplete|wrong))"
)


@dataclass(frozen=True)
class ArpRecord:
    ip_address: str
    mac_address: str
    vlan: str = ""
    interface_name: str = ""
    aging: str = ""
    entry_type: str = ""
    raw_line: str = ""


@dataclass(frozen=True)
class ArpParseResult:
    records: tuple[ArpRecord, ...] = ()
    status: str = "SUCCESS"
    completeness: str = "COMPLETE"
    pagination_detected: bool = False
    truncation_detected: bool = False
    header_detected: bool = False
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def complete(self) -> bool:
        return self.status == "SUCCESS" and self.completeness == "COMPLETE"


def parse_h3c_arp(output: str, *, explicit_complete: bool | None = None) -> ArpParseResult:
    """Parse Comware V5/V7/V9 ``display arp`` output without inventing rows.

    The collector owns the query scope and snapshot decision. The parser only
    reports rows plus evidence that pagination/truncation or command failure
    made the response unsafe to use as a complete snapshot.
    """

    text = str(output or "")
    header_detected = bool(
        re.search(r"(?i)\bip\s+address\b.*\bmac\s+address\b", text)
        or re.search(r"(?i)\bmac\s+address\b.*\bvlan\b", text)
    )
    pagination = bool(_MORE_RE.search(text))
    incomplete = bool(_INCOMPLETE_RE.search(text))
    records: list[ArpRecord] = []
    seen: set[tuple[str, str, str, str]] = set()
    for line in text.splitlines():
        stripped = _MORE_RE.sub("", line).strip()
        if not stripped or stripped.startswith(("<", "#", "=", "-")):
            continue
        parsed = _parse_arp_line(stripped)
        if parsed is None:
            continue
        key = (parsed.ip_address, parsed.mac_address, parsed.vlan, parsed.interface_name)
        if key not in seen:
            records.append(parsed)
            seen.add(key)

    if explicit_complete is False:
        incomplete = True
    if pagination or incomplete:
        return ArpParseResult(
            tuple(records), status="TRUNCATED" if pagination or incomplete else "PARTIAL",
            completeness="INCOMPLETE", pagination_detected=pagination,
            truncation_detected=incomplete, header_detected=header_detected,
            warnings=("ARP 回显不完整，未更新缺席状态",),
        )
    if not records and not header_detected:
        return ArpParseResult(
            tuple(), status="PARTIAL", completeness="UNKNOWN",
            header_detected=False, warnings=("ARP 回显未包含可识别表头",),
        )
    return ArpParseResult(
        tuple(records), status="SUCCESS", completeness="COMPLETE",
        header_detected=header_detected,
    )


def _parse_arp_line(line: str) -> ArpRecord | None:
    ip_match = _IP_RE.search(line)
    mac_match = _MAC_RE.search(line, ip_match.end() if ip_match else 0)
    if ip_match is None or mac_match is None:
        return None
    try:
        ip_value = str(ipaddress.ip_address(ip_match.group(0)))
        mac_value = normalize_mac(mac_match.group(0))
    except ValueError:
        return None
    tail = line[mac_match.end():].strip()
    tokens = tail.split()
    vlan = ""
    vlan_index = -1
    for index, token in enumerate(tokens[:4]):
        if token.isdigit() and 1 <= int(token) <= 4094:
            vlan, vlan_index = token, index
            break
    remaining = tokens[vlan_index + 1:] if vlan_index >= 0 else tokens
    aging = ""
    aging_index = -1
    for index, token in enumerate(remaining):
        if token.isdigit() or token == "-":
            aging, aging_index = token, index
            break
    before_aging = remaining[:aging_index] if aging_index >= 0 else remaining
    interface = before_aging[0] if before_aging else ""
    entry_type = " ".join(remaining[aging_index + 1:]) if aging_index >= 0 else ""
    return ArpRecord(
        ip_address=ip_value, mac_address=mac_value, vlan=vlan,
        interface_name=interface, aging=aging, entry_type=entry_type,
        raw_line=line,
    )


__all__ = ["ArpParseResult", "ArpRecord", "parse_h3c_arp"]
