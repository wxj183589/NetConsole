from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class WirelessAdapter:
    name: str
    guid: str = ""
    state: str = ""
    connected_ssid: str = ""

    @property
    def display_name(self) -> str:
        parts = [self.name]
        if self.connected_ssid:
            parts.append(f"SSID: {self.connected_ssid}")
        if self.guid:
            parts.append(self.guid)
        return " | ".join(part for part in parts if part)


@dataclass
class WirelessNetwork:
    ssid: str = ""
    bssid: str = ""
    rssi_dbm: int | None = None
    quality: int | None = None
    band: str = ""
    channel: int | None = None
    frequency_mhz: int | None = None
    channel_width_mhz: int | None = None
    channel_width_text: str = "-"
    channel_width_source: str = "unavailable"
    channel_width: str = "-"
    phy_type: str = ""
    auth: str = ""
    encryption: str = ""
    vendor: str = "-"
    is_hidden: bool = False
    last_seen: str = ""
    mimo: str | None = None
    mimo_source: str | None = None
    mimo_note: str | None = None
    scan_source: str = "unknown"
    has_wlan_api_data: bool = False
    has_netsh_data: bool = False
    source_flags: dict[str, bool] = field(default_factory=dict)
    raw_ie_hex: str = ""
    raw_ie_available: bool = False
    parse_warnings: list[str] = field(default_factory=list)
    raw: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class TracksideBssidMatch:
    matched: bool
    match_status: str
    ap_name: str = "-"
    point_code: str = ""
    ap_mac: str = ""
    station: str = ""
    section: str = ""
    section_start_station: str = ""
    section_end_station: str = ""
    belong_type: str = "unknown"
    belonging_source: str = ""
    serial_number: str = ""
    location: str = ""
    mileage: str = ""
    direction: str = ""
    radio_id: int | None = None
    match_rule: str = ""
    confidence: int = 0
    candidates: tuple[dict[str, object], ...] = ()


@dataclass
class WirelessScanResult:
    network: WirelessNetwork
    match: TracksideBssidMatch
