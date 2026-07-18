from __future__ import annotations

import re
import subprocess
from datetime import datetime

from netconsole.models.wireless_scan_models import WirelessAdapter, WirelessNetwork
from netconsole.services.network_tools.wireless_channel_analyzer import band_from_frequency, frequency_to_channel, quality_to_rssi_dbm
from netconsole.utils.text_encoding import decode_bytes_with_fallback


class NetshWirelessScanner:
    def list_adapters(self) -> list[WirelessAdapter]:
        result = _run_netsh_text(["netsh", "wlan", "show", "interfaces"])
        if result.returncode != 0:
            return []
        return parse_netsh_interfaces(result.stdout)

    def scan(self, adapter: WirelessAdapter | None = None) -> tuple[list[WirelessNetwork], str]:
        cmd = ["netsh", "wlan", "show", "networks", "mode=bssid"]
        result = _run_netsh_text(cmd)
        raw = result.stdout or result.stderr
        if result.returncode != 0:
            raise RuntimeError(raw.strip() or "netsh wlan scan failed")
        return parse_netsh_networks(raw), raw


def _run_netsh_text(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmd, capture_output=True, check=False)
    return subprocess.CompletedProcess(
        result.args,
        result.returncode,
        stdout=decode_bytes_with_fallback(result.stdout or b"").text,
        stderr=decode_bytes_with_fallback(result.stderr or b"").text,
    )


def parse_netsh_interfaces(text: str) -> list[WirelessAdapter]:
    adapters: list[WirelessAdapter] = []
    current: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            if current:
                adapters.append(_adapter_from_fields(current))
                current = {}
            continue
        key, value = _split_netsh_line(line)
        key_l = key.casefold()
        if key_l in {"name", "名称"}:
            if current:
                adapters.append(_adapter_from_fields(current))
            current = {"name": value}
        elif key_l in {"guid"}:
            current["guid"] = value
        elif key_l in {"state", "状态"}:
            current["state"] = value
        elif key_l in {"ssid"}:
            current["connected_ssid"] = value
    if current:
        adapters.append(_adapter_from_fields(current))
    return [adapter for adapter in adapters if adapter.name]


def parse_netsh_networks(text: str) -> list[WirelessNetwork]:
    networks: list[WirelessNetwork] = []
    current_ssid = ""
    auth = ""
    encryption = ""
    current_bssid: dict[str, object] | None = None
    last_seen = datetime.now().isoformat(sep=" ", timespec="seconds")
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        ssid_match = re.match(r"SSID\s+\d+\s*:\s*(.*)$", line, re.IGNORECASE)
        if ssid_match:
            if current_bssid:
                networks.append(_network_from_fields(current_ssid, auth, encryption, current_bssid, last_seen))
                current_bssid = None
            current_ssid = ssid_match.group(1).strip()
            auth = ""
            encryption = ""
            continue
        key, value = _split_netsh_line(line)
        key_l = key.casefold()
        if key_l in {"authentication", "身份验证"}:
            auth = value
        elif key_l in {"encryption", "加密"}:
            encryption = value
        elif key_l.startswith("bssid"):
            if current_bssid:
                networks.append(_network_from_fields(current_ssid, auth, encryption, current_bssid, last_seen))
            current_bssid = {"bssid": value}
        elif current_bssid is not None:
            if key_l in {"signal", "信号"}:
                current_bssid["quality"] = _parse_percent(value)
            elif key_l in {"radio type", "无线电类型"}:
                current_bssid["phy_type"] = value
            elif key_l in {"channel", "频道"}:
                current_bssid["channel"] = _parse_int(value)
            elif key_l in {"basic rates (mbps)", "other rates (mbps)", "基本速率(mbps)", "其他速率(mbps)"}:
                current_bssid.setdefault("rates", []).append(value)
            elif key_l in {"frequency", "频率"}:
                current_bssid["frequency_mhz"] = _parse_int(value)
    if current_bssid:
        networks.append(_network_from_fields(current_ssid, auth, encryption, current_bssid, last_seen))
    return networks


def _network_from_fields(ssid: str, auth: str, encryption: str, fields: dict[str, object], last_seen: str) -> WirelessNetwork:
    quality = fields.get("quality") if isinstance(fields.get("quality"), int) else None
    channel = fields.get("channel") if isinstance(fields.get("channel"), int) else None
    frequency = fields.get("frequency_mhz") if isinstance(fields.get("frequency_mhz"), int) else None
    if frequency is None and channel:
        frequency = _frequency_from_channel(channel)
    if channel is None:
        channel = frequency_to_channel(frequency)
    ssid_text = ssid.strip()
    hidden = not ssid_text or ssid_text.casefold() in {"hidden network", "<hidden network>", "隐藏的网络"}
    return WirelessNetwork(
        ssid="" if hidden else ssid_text,
        bssid=str(fields.get("bssid") or ""),
        rssi_dbm=quality_to_rssi_dbm(quality),
        quality=quality,
        band=band_from_frequency(frequency),
        channel=channel,
        frequency_mhz=frequency,
        channel_width_mhz=None,
        channel_width_text="-",
        channel_width_source="unavailable",
        channel_width="-",
        phy_type=str(fields.get("phy_type") or ""),
        auth=auth,
        encryption=encryption,
        is_hidden=hidden,
        last_seen=last_seen,
        mimo=None,
        mimo_source="unavailable",
        mimo_note="scan_source_unavailable",
        scan_source="netsh",
        raw_ie_available=False,
        parse_warnings=["netsh_no_ie_blob"],
        raw=dict(fields),
    )


def _adapter_from_fields(fields: dict[str, str]) -> WirelessAdapter:
    return WirelessAdapter(name=fields.get("name", ""), guid=fields.get("guid", ""), state=fields.get("state", ""), connected_ssid=fields.get("connected_ssid", ""))


def _split_netsh_line(line: str) -> tuple[str, str]:
    if ":" not in line:
        return line, ""
    key, value = line.split(":", 1)
    return key.strip(), value.strip()


def _parse_percent(value: str) -> int | None:
    match = re.search(r"(\d+)", value)
    return int(match.group(1)) if match else None


def _parse_int(value: str) -> int | None:
    match = re.search(r"(\d+)", value)
    return int(match.group(1)) if match else None


def _frequency_from_channel(channel: int) -> int | None:
    if 1 <= channel <= 13:
        return 2407 + channel * 5
    if channel == 14:
        return 2484
    if 32 <= channel <= 196:
        return 5000 + channel * 5
    return None
