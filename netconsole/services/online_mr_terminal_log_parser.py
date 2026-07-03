from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime


EMPTY_LINK_NAME = "NA"
EMPTY_LINK_MAC = "0000-0000-0000"
EMPTY_LINK_DISPLAY = "空链路"

SWITCH_REASON_TEXT = {
    1: "首个 Mesh 链路建立",
    2: "主动切换（未开启移动链路优化）",
    3: "主动切换（已开启移动链路优化）",
    4: "被动切换或强制断开后切换",
}

MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

ACTIVE_LINK_SWITCH_RE = re.compile(
    r"^%(?P<month>[A-Za-z]{3})\s+(?P<day>\d{1,2})\s+"
    r"(?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2}):(?P<millisecond>\d{1,3})"
    r"(?:\s+(?P<year>\d{4}))?\s+"
    r"(?P<device>\S+)\s+WMESH/5/MESH_ACTIVELINK_SWITCH:\s+"
    r"Switch an active link from (?P<from>\S+) to (?P<to>\S+):\s+"
    r"peer quantity\s*=\s*(?P<peer_quantity>\d+),\s+"
    r"link quantity\s*=\s*(?P<link_quantity>\d+),\s+"
    r"switch reason\s*=\s*(?P<reason>\d+)\.",
    re.IGNORECASE,
)

ENDPOINT_RE = re.compile(r"^(?P<peer_name>.+)_(?P<radio_mac>[0-9A-Fa-f]{4}[-:.][0-9A-Fa-f]{4}[-:.][0-9A-Fa-f]{4})\((?P<rssi>-?\d+)\)$")


@dataclass(frozen=True)
class ActiveLinkEndpoint:
    peer_name: str
    radio_mac: str
    rssi: int | None
    is_empty_link: bool = False

    @property
    def display_peer_name(self) -> str:
        return EMPTY_LINK_DISPLAY if self.is_empty_link else self.peer_name

    @property
    def radio_mac_display(self) -> str:
        return "-" if self.is_empty_link else self.radio_mac

    @property
    def rssi_display(self) -> str:
        return "-" if self.is_empty_link else "" if self.rssi is None else str(self.rssi)


@dataclass(frozen=True)
class ActiveLinkSwitchLog:
    log_time: datetime
    device_name: str
    raw_line: str
    from_peer_name: str
    from_peer_mac: str
    from_peer_rssi: int | None
    to_peer_name: str
    to_peer_mac: str
    to_peer_rssi: int | None
    peer_quantity: int | None
    link_quantity: int | None
    switch_reason_code: int | None
    switch_reason_text: str
    from_station: str = "-"
    to_station: str = "-"
    from_serial_number: str = "-"
    to_serial_number: str = "-"
    from_resolve_rule: str = ""
    to_resolve_rule: str = ""
    source: str = "terminal_monitor"
    from_is_empty_link: bool = False
    to_is_empty_link: bool = False

    @property
    def from_display_name(self) -> str:
        return EMPTY_LINK_DISPLAY if self.from_is_empty_link else self.from_peer_name

    @property
    def to_display_name(self) -> str:
        return EMPTY_LINK_DISPLAY if self.to_is_empty_link else self.to_peer_name

    @property
    def from_radio_mac_display(self) -> str:
        return "-" if self.from_is_empty_link else self.from_peer_mac

    @property
    def to_radio_mac_display(self) -> str:
        return "-" if self.to_is_empty_link else self.to_peer_mac

    @property
    def from_rssi_display(self) -> str:
        return "-" if self.from_is_empty_link else "" if self.from_peer_rssi is None else str(self.from_peer_rssi)

    @property
    def to_rssi_display(self) -> str:
        return "-" if self.to_is_empty_link else "" if self.to_peer_rssi is None else str(self.to_peer_rssi)


def switch_reason_text(code: int | None) -> str:
    if code in SWITCH_REASON_TEXT:
        return SWITCH_REASON_TEXT[int(code)]
    return f"未知原因({code})" if code is not None else "未知原因"


def parse_h3c_log_datetime(match: re.Match[str], fallback_year: int | None = None) -> datetime:
    month = MONTHS.get(match.group("month").lower())
    if month is None:
        raise ValueError(f"unsupported month: {match.group('month')}")
    year_text = match.group("year")
    year = int(year_text) if year_text else int(fallback_year or datetime.now().year)
    millisecond = int(match.group("millisecond").ljust(3, "0")[:3])
    return datetime(
        year,
        month,
        int(match.group("day")),
        int(match.group("hour")),
        int(match.group("minute")),
        int(match.group("second")),
        millisecond * 1000,
    )


def parse_active_link_endpoint(text: str) -> ActiveLinkEndpoint:
    match = ENDPOINT_RE.match(str(text or "").strip())
    if not match:
        return ActiveLinkEndpoint("", "", None)
    peer_name = match.group("peer_name").strip()
    radio_mac = match.group("radio_mac").strip()
    rssi = int(match.group("rssi"))
    is_empty = peer_name.upper() == EMPTY_LINK_NAME and _normalize_mac(radio_mac) == "0" * 12
    return ActiveLinkEndpoint(peer_name, radio_mac, rssi, is_empty)


def parse_active_link_switch_logs(text: str, device_name: str | None = None, fallback_year: int | None = None) -> list[ActiveLinkSwitchLog]:
    rows: list[ActiveLinkSwitchLog] = []
    for line in str(text or "").splitlines():
        if "WMESH/5/MESH_ACTIVELINK_SWITCH" not in line:
            continue
        match = ACTIVE_LINK_SWITCH_RE.match(line.strip())
        if not match:
            continue
        from_endpoint = parse_active_link_endpoint(match.group("from"))
        to_endpoint = parse_active_link_endpoint(match.group("to"))
        reason_code = int(match.group("reason"))
        rows.append(
            ActiveLinkSwitchLog(
                log_time=parse_h3c_log_datetime(match, fallback_year=fallback_year),
                device_name=str(device_name or match.group("device") or ""),
                raw_line=line.strip(),
                from_peer_name=from_endpoint.peer_name,
                from_peer_mac=from_endpoint.radio_mac,
                from_peer_rssi=from_endpoint.rssi,
                to_peer_name=to_endpoint.peer_name,
                to_peer_mac=to_endpoint.radio_mac,
                to_peer_rssi=to_endpoint.rssi,
                peer_quantity=int(match.group("peer_quantity")),
                link_quantity=int(match.group("link_quantity")),
                switch_reason_code=reason_code,
                switch_reason_text=switch_reason_text(reason_code),
                from_station="-" if from_endpoint.is_empty_link else "",
                to_station="-" if to_endpoint.is_empty_link else "",
                from_serial_number="-" if from_endpoint.is_empty_link else "",
                to_serial_number="-" if to_endpoint.is_empty_link else "",
                from_resolve_rule="empty_link" if from_endpoint.is_empty_link else "",
                to_resolve_rule="empty_link" if to_endpoint.is_empty_link else "",
                from_is_empty_link=from_endpoint.is_empty_link,
                to_is_empty_link=to_endpoint.is_empty_link,
            )
        )
    return sorted(rows, key=lambda item: item.log_time)


def _normalize_mac(value: object) -> str:
    return re.sub(r"[^0-9A-Fa-f]", "", str(value or "")).lower()
