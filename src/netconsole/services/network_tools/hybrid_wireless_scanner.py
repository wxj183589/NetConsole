from __future__ import annotations

from netconsole.models.wireless_scan_models import WirelessAdapter, WirelessNetwork
from netconsole.services.network_tools.netsh_wireless_scanner import NetshWirelessScanner
from netconsole.services.network_tools.wireless_channel_analyzer import (
    band_from_frequency,
    normalize_mac,
)
from netconsole.services.network_tools.windows_wlan_scanner import SCAN_SOURCE_WLAN_API, WindowsWlanScanner


class HybridWirelessScanner:
    def __init__(
        self,
        wlan_scanner: WindowsWlanScanner | None = None,
        netsh_scanner: NetshWirelessScanner | None = None,
    ) -> None:
        self.wlan_scanner = wlan_scanner or WindowsWlanScanner(scan_source=SCAN_SOURCE_WLAN_API)
        self.netsh_scanner = netsh_scanner or NetshWirelessScanner()

    def list_adapters(self) -> list[WirelessAdapter]:
        try:
            adapters = self.wlan_scanner.list_adapters()
            if adapters:
                return adapters
        except Exception:
            pass
        return self.netsh_scanner.list_adapters()

    def scan(self, adapter: WirelessAdapter | None = None) -> tuple[list[WirelessNetwork], str]:
        wlan_networks: list[WirelessNetwork] = []
        netsh_networks: list[WirelessNetwork] = []
        wlan_raw = ""
        netsh_raw = ""
        wlan_error = ""
        netsh_error = ""
        try:
            wlan_networks, wlan_raw = self.wlan_scanner.scan(adapter)
        except Exception as exc:
            wlan_error = str(exc)
        try:
            netsh_networks, netsh_raw = self.netsh_scanner.scan(adapter)
        except Exception as exc:
            netsh_error = str(exc)
        if wlan_error and netsh_error:
            raise RuntimeError(f"WLAN API failed: {wlan_error}; netsh failed: {netsh_error}")
        merged = merge_wireless_networks(wlan_networks, netsh_networks)
        raw = _raw_sections(wlan_raw, netsh_raw, wlan_error, netsh_error)
        return merged, raw


def merge_wireless_networks(wlan_networks: list[WirelessNetwork], netsh_networks: list[WirelessNetwork]) -> list[WirelessNetwork]:
    wlan_by_bssid = _deduplicate_by_bssid(wlan_networks, "wlan_api")
    netsh_by_bssid = _deduplicate_by_bssid(netsh_networks, "netsh")
    keys = list(wlan_by_bssid)
    keys.extend(key for key in netsh_by_bssid if key not in wlan_by_bssid)
    return [_merge_pair(wlan_by_bssid.get(key), netsh_by_bssid.get(key), key) for key in keys]


def _deduplicate_by_bssid(networks: list[WirelessNetwork], source: str) -> dict[str, WirelessNetwork]:
    by_bssid: dict[str, WirelessNetwork] = {}
    for network in networks:
        key = normalize_mac(network.bssid)
        if not key:
            continue
        marked = _mark_source(network, source)
        by_bssid[key] = _merge_same_source(by_bssid[key], marked, key) if key in by_bssid else marked
    return by_bssid


def _merge_pair(wlan: WirelessNetwork | None, netsh: WirelessNetwork | None, bssid: str) -> WirelessNetwork:
    source_flags = {"wlan_api": bool(wlan), "netsh": bool(netsh), "merged": bool(wlan and netsh)}
    if wlan and netsh:
        frequency = wlan.frequency_mhz if wlan.frequency_mhz is not None else netsh.frequency_mhz
        channel = wlan.channel if wlan.channel is not None else netsh.channel
        band = band_from_frequency(frequency) or wlan.band or netsh.band
        if not band and channel:
            band = band_from_frequency(_frequency_from_channel(channel))
        raw = {**wlan.raw, "wlan_api_raw": wlan.raw, "netsh_raw": netsh.raw, "source_flags": source_flags}
        return WirelessNetwork(
            ssid=_preferred_ssid(netsh.ssid, wlan.ssid),
            bssid=bssid,
            rssi_dbm=wlan.rssi_dbm if wlan.rssi_dbm is not None else netsh.rssi_dbm,
            quality=netsh.quality if netsh.quality is not None else wlan.quality,
            band=band,
            channel=channel,
            frequency_mhz=frequency,
            channel_width_mhz=wlan.channel_width_mhz,
            channel_width_text=wlan.channel_width_text,
            channel_width_source=wlan.channel_width_source,
            channel_width=wlan.channel_width,
            phy_type=netsh.phy_type or wlan.phy_type,
            auth=netsh.auth or wlan.auth,
            encryption=netsh.encryption or wlan.encryption,
            vendor=wlan.vendor if wlan.vendor != "-" else netsh.vendor,
            is_hidden=not bool(_preferred_ssid(netsh.ssid, wlan.ssid)),
            last_seen=wlan.last_seen or netsh.last_seen,
            mimo=wlan.mimo,
            mimo_source=wlan.mimo_source,
            mimo_note=wlan.mimo_note,
            scan_source="hybrid",
            has_wlan_api_data=True,
            has_netsh_data=True,
            source_flags=source_flags,
            raw_ie_hex=wlan.raw_ie_hex,
            raw_ie_available=wlan.raw_ie_available,
            parse_warnings=list(wlan.parse_warnings),
            raw=raw,
        )
    network = wlan or netsh
    assert network is not None
    source = "wlan_api" if wlan else "netsh"
    return _mark_source(network, source, bssid)


def _merge_same_source(left: WirelessNetwork, right: WirelessNetwork, bssid: str) -> WirelessNetwork:
    ssid = _preferred_ssid(left.ssid, right.ssid)
    preferred = right if ssid and right.ssid == ssid else left
    fallback = left if preferred is right else right
    auth = preferred.auth or fallback.auth
    encryption = preferred.encryption or fallback.encryption
    aliases = sorted({value for value in (left.ssid, right.ssid) if value and value != ssid})
    raw = {**left.raw, **right.raw}
    if aliases:
        raw["ssid_aliases"] = aliases
    return WirelessNetwork(
        ssid=ssid,
        bssid=bssid,
        rssi_dbm=left.rssi_dbm if left.rssi_dbm is not None else right.rssi_dbm,
        quality=left.quality if left.quality is not None else right.quality,
        band=left.band or right.band,
        channel=left.channel if left.channel is not None else right.channel,
        frequency_mhz=left.frequency_mhz if left.frequency_mhz is not None else right.frequency_mhz,
        channel_width_mhz=left.channel_width_mhz if left.channel_width_mhz is not None else right.channel_width_mhz,
        channel_width_text=left.channel_width_text if left.channel_width_text != "-" else right.channel_width_text,
        channel_width_source=left.channel_width_source if left.channel_width_source != "unavailable" else right.channel_width_source,
        channel_width=left.channel_width if left.channel_width != "-" else right.channel_width,
        phy_type=left.phy_type or right.phy_type,
        auth=auth,
        encryption=encryption,
        vendor=left.vendor if left.vendor != "-" else right.vendor,
        is_hidden=not bool(ssid),
        last_seen=left.last_seen or right.last_seen,
        mimo=left.mimo or right.mimo,
        mimo_source=left.mimo_source if left.mimo_source != "unavailable" else right.mimo_source,
        mimo_note=left.mimo_note or right.mimo_note,
        scan_source=left.scan_source,
        has_wlan_api_data=left.has_wlan_api_data or right.has_wlan_api_data,
        has_netsh_data=left.has_netsh_data or right.has_netsh_data,
        source_flags={**left.source_flags, **right.source_flags},
        raw_ie_hex=left.raw_ie_hex or right.raw_ie_hex,
        raw_ie_available=left.raw_ie_available or right.raw_ie_available,
        parse_warnings=list(dict.fromkeys([*left.parse_warnings, *right.parse_warnings])),
        raw=raw,
    )


def _mark_source(network: WirelessNetwork, source: str, bssid: str | None = None) -> WirelessNetwork:
    bssid_value = normalize_mac(bssid or network.bssid) or network.bssid
    return WirelessNetwork(
        ssid=network.ssid,
        bssid=bssid_value,
        rssi_dbm=network.rssi_dbm,
        quality=network.quality,
        band=network.band,
        channel=network.channel,
        frequency_mhz=network.frequency_mhz,
        channel_width_mhz=network.channel_width_mhz,
        channel_width_text=network.channel_width_text,
        channel_width_source=network.channel_width_source,
        channel_width=network.channel_width,
        phy_type=network.phy_type,
        auth=network.auth,
        encryption=network.encryption,
        vendor=network.vendor,
        is_hidden=network.is_hidden,
        last_seen=network.last_seen,
        mimo=network.mimo,
        mimo_source=network.mimo_source,
        mimo_note=network.mimo_note,
        scan_source=source,
        has_wlan_api_data=source == "wlan_api",
        has_netsh_data=source == "netsh",
        source_flags={"wlan_api": source == "wlan_api", "netsh": source == "netsh", "merged": False},
        raw_ie_hex=network.raw_ie_hex,
        raw_ie_available=network.raw_ie_available,
        parse_warnings=list(network.parse_warnings),
        raw={**network.raw, "source_flags": {"wlan_api": source == "wlan_api", "netsh": source == "netsh", "merged": False}},
    )


def _preferred_ssid(*values: str) -> str:
    hidden_values = {"", "hidden", "hidden network", "<hidden network>", "隐藏", "隐藏网络"}
    for value in values:
        text = str(value or "").strip()
        if text and text.casefold() not in hidden_values:
            return text
    return ""


def _frequency_from_channel(channel: int) -> int | None:
    if 1 <= channel <= 13:
        return 2407 + channel * 5
    if channel == 14:
        return 2484
    if 32 <= channel <= 196:
        return 5000 + channel * 5
    return None


def _raw_sections(wlan_raw: str, netsh_raw: str, wlan_error: str, netsh_error: str) -> str:
    return "\n".join(
        [
            "===== Windows WLAN API =====",
            wlan_raw.strip() if wlan_raw else f"ERROR: {wlan_error}" if wlan_error else "-",
            "",
            "===== netsh =====",
            netsh_raw.strip() if netsh_raw else f"ERROR: {netsh_error}" if netsh_error else "-",
        ]
    )
