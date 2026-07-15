from __future__ import annotations

import csv
import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping
from uuid import uuid4

from openpyxl import Workbook

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.wireless_scan_models import WirelessAdapter, WirelessNetwork, WirelessScanResult
from netconsole.repositories.ac_repository import AcRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.repositories.wireless_scan_repository import WirelessScanRepository
from netconsole.services.network_tools.hybrid_wireless_scanner import HybridWirelessScanner
from netconsole.services.network_tools.trackside_bssid_resolver import TracksideApBssidResolver
from netconsole.services.network_tools.wireless_channel_analyzer import format_h3c_mac
from netconsole.services.network_tools.windows_wlan_scanner import SCAN_SOURCE_AUTO, SCAN_SOURCE_HYBRID, WindowsWlanScanner


WIRELESS_SCAN_DISPLAY_COLUMNS: tuple[tuple[str, str], ...] = (
    ("wireless_scan.ssid", "display_ssid"),
    ("wireless_scan.mac_address", "display_mac_address"),
    ("wireless_scan.ap_mac", "display_ap_mac"),
    ("wireless_scan.ap_name", "display_ap_name"),
    ("wireless_scan.radio_id", "display_radio_id"),
    ("wireless_scan.station", "display_station"),
    ("wireless_scan.section", "display_section"),
    ("wireless_scan.belong_type", "display_belong_type"),
    ("wireless_scan.belonging_source", "display_belonging_source"),
    ("wireless_scan.location_mileage", "display_location_mileage"),
    ("wireless_scan.rssi", "display_rssi"),
    ("wireless_scan.signal_quality", "display_signal_quality"),
    ("wireless_scan.channel", "display_channel"),
    ("wireless_scan.frequency", "display_frequency"),
    ("wireless_scan.band", "display_band"),
    ("wireless_scan.channel_width", "display_channel_width"),
    ("wireless_scan.mimo", "display_mimo"),
    ("wireless_scan.encryption_method", "display_encryption_method"),
    ("wireless_scan.encryption", "display_encryption"),
    ("wireless_scan.auth_method", "display_auth_method"),
)
WIRELESS_SCAN_EXPORT_COLUMNS = WIRELESS_SCAN_DISPLAY_COLUMNS


@dataclass
class WirelessScanRunResult:
    scan_id: str
    started_at: str
    ended_at: str
    raw_file: Path
    results: list[WirelessScanResult]


class WirelessScanService:
    def __init__(self, site_name: str, paths: PathResolver, scanner: WindowsWlanScanner | None = None, scan_source: str = SCAN_SOURCE_AUTO) -> None:
        self.site_name = site_name
        self.paths = paths
        self.scanner = scanner or (HybridWirelessScanner() if scan_source in {SCAN_SOURCE_AUTO, SCAN_SOURCE_HYBRID} else WindowsWlanScanner(scan_source=scan_source))
        self.repository = WirelessScanRepository(paths.wireless_scan_db_path(site_name))

    def list_adapters(self) -> list[WirelessAdapter]:
        return self.scanner.list_adapters()

    def scan(self, adapter: WirelessAdapter | None = None, *, project_id: str = "") -> WirelessScanRunResult:
        started = datetime.now()
        networks, raw = self.scanner.scan(adapter)
        raw_dir = self.paths.wireless_scan_raw_dir(self.site_name)
        raw_dir.mkdir(parents=True, exist_ok=True)
        scan_id = f"scan_{started.strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"
        raw_file = raw_dir / f"{scan_id}.txt"
        raw_temp = raw_file.with_name(f".{raw_file.name}.{uuid4().hex}.tmp")
        try:
            with raw_temp.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(raw_temp, raw_file)
        finally:
            try:
                raw_temp.unlink(missing_ok=True)
            except OSError:
                pass
        resolver = self._trackside_resolver()
        results = [WirelessScanResult(network=network, match=resolver.resolve(network.bssid)) for network in networks]
        results.sort(key=lambda item: (not bool(item.match.ap_name and item.match.ap_name != "-"), -(item.network.rssi_dbm or -999), item.match.station, item.match.ap_name, item.network.bssid))
        ended = datetime.now()
        self.repository.save_scan(
            scan_id=scan_id,
            site=self.site_name,
            adapter_name=adapter.name if adapter else "",
            adapter_guid=adapter.guid if adapter else "",
            started_at=started.isoformat(sep=" ", timespec="seconds"),
            ended_at=ended.isoformat(sep=" ", timespec="seconds"),
            status="success",
            raw_file=str(raw_file),
            results=results,
            project_id=str(project_id or ""),
        )
        return WirelessScanRunResult(scan_id, started.isoformat(sep=" ", timespec="seconds"), ended.isoformat(sep=" ", timespec="seconds"), raw_file, results)

    def _trackside_resolver(self) -> TracksideApBssidResolver:
        device_repo = DeviceRepository(Database(self.paths.site_db_path(self.site_name)))
        return TracksideApBssidResolver.from_ac_repository(AcRepository(device_repo.database))


def wireless_scanner_external_path(paths: PathResolver, configured_path: str = "") -> Path | None:
    candidates = []
    if configured_path:
        candidates.append(Path(configured_path))
    candidates.append(paths.app_root / "_internal" / "tools" / "wifi_scanner" / "WiFiScannerPortable.exe")
    candidates.append(paths.app_root / "tools" / "wifi_scanner" / "WiFiScannerPortable.exe")
    path_candidate = shutil.which("WiFiScannerPortable.exe")
    if path_candidate:
        candidates.append(Path(path_candidate))
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def export_wireless_scan_xlsx(path: Path, rows: list[dict[str, object]], headers: list[str]) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Wireless Scan"
    sheet.append(headers)
    for row in rows:
        sheet.append([_export_value(row.get(field)) for _key, field in WIRELESS_SCAN_EXPORT_COLUMNS])
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    workbook.save(path)


def export_wireless_scan_csv(path: Path, rows: list[dict[str, object]], headers: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        for row in rows:
            writer.writerow([_export_value(row.get(field)) for _key, field in WIRELESS_SCAN_EXPORT_COLUMNS])


def result_to_row(result: WirelessScanResult) -> dict[str, object]:
    network = result.network
    match = result.match
    location = match.mileage or match.location
    encryption_method = network.encryption or "-"
    encryption = _security_display(network.auth)
    auth_method = _auth_method(network.auth)
    return {
        "match_status": match.match_status,
        "matched_trackside_ap": 1 if match.matched else 0,
        "matched_ap_name": match.ap_name,
        "matched_station": match.station,
        "matched_section": match.section,
        "matched_belong_type": match.belong_type,
        "matched_belonging_source": match.belonging_source or match.match_rule,
        "matched_location": location,
        "matched_direction": match.direction,
        "matched_radio_id": match.radio_id,
        "matched_ap_mac": match.ap_mac,
        "bssid": format_h3c_mac(network.bssid) or network.bssid,
        "rssi_dbm": network.rssi_dbm,
        "channel": network.channel,
        "frequency_mhz": network.frequency_mhz,
        "channel_width_mhz": network.channel_width_mhz,
        "channel_width_text": network.channel_width_text or network.channel_width,
        "channel_width_source": network.channel_width_source or "unavailable",
        "channel_width": network.channel_width_text or network.channel_width,
        "band": network.band,
        "ssid": network.ssid,
        "is_hidden": 1 if network.is_hidden else 0,
        "match_rule": match.match_rule,
        "last_seen": network.last_seen,
        "auth": network.auth,
        "encryption": network.encryption,
        "security": encryption,
        "auth_method": auth_method,
        "encryption_method": encryption_method,
        "phy_type": network.phy_type,
        "vendor": network.vendor,
        "quality": network.quality,
        "match_candidates_json": json.dumps(list(match.candidates), ensure_ascii=False),
        "mimo": network.mimo or "-",
        "mimo_source": network.mimo_source or "unavailable",
        "mimo_note": network.mimo_note or "scan_source_unavailable",
        "scan_source": network.scan_source or "unknown",
        "has_wlan_api_data": 1 if network.has_wlan_api_data else 0,
        "has_netsh_data": 1 if network.has_netsh_data else 0,
        "source_flags": dict(network.source_flags),
        "raw_ie_available": 1 if network.raw_ie_available else 0,
        "raw_ie_hex": network.raw_ie_hex,
        "parse_warnings": list(network.parse_warnings),
        "display_ssid": "Hidden" if network.is_hidden or not network.ssid else network.ssid,
        "display_mac_address": format_h3c_mac(network.bssid) or network.bssid or "-",
        "display_ap_mac": match.ap_mac or "-",
        "display_ap_name": match.ap_name if match.ap_name and match.ap_name != "-" else "-",
        "display_radio_id": match.radio_id or "-",
        "display_station": match.station or "-",
        "display_section": match.section or "-",
        "display_belong_type": _belong_type_display(match.belong_type),
        "display_belonging_source": match.belonging_source or match.match_rule or "-",
        "display_location_mileage": location or "-",
        "display_rssi": network.rssi_dbm if network.rssi_dbm is not None else "-",
        "display_signal_quality": network.quality if network.quality is not None else "-",
        "display_channel": network.channel if network.channel is not None else "-",
        "display_frequency": network.frequency_mhz if network.frequency_mhz is not None else "-",
        "display_band": network.band or "Unknown",
        "display_channel_width": network.channel_width_text if network.channel_width_text and network.channel_width_text != "-" else (f"{network.channel_width_mhz} MHz" if network.channel_width_mhz else "-"),
        "display_mimo": _mimo_display(network),
        "display_encryption_method": encryption_method,
        "display_encryption": encryption,
        "display_auth_method": auth_method,
    }


def repository_row_to_display_row(row: Mapping[str, object]) -> dict[str, object]:
    location = row.get("matched_location")
    encryption_method = row.get("encryption_method") or row.get("encryption") or "-"
    encryption = row.get("security") or _security_display(str(row.get("auth") or ""))
    auth_method = row.get("auth_method") or _auth_method(str(row.get("auth") or ""))
    is_hidden = bool(int(row.get("is_hidden") or 0))
    channel_width_mhz = row.get("channel_width_mhz")
    channel_width_text = str(row.get("channel_width_text") or row.get("channel_width") or "")
    display_channel_width = channel_width_text if channel_width_text and channel_width_text != "-" else (f"{channel_width_mhz} MHz" if channel_width_mhz else "-")
    return {
        **dict(row),
        "matched_trackside_ap": int(row.get("matched_trackside_ap") or 0),
        "matched_location": location,
        "display_ssid": "Hidden" if is_hidden or not row.get("ssid") else row.get("ssid"),
        "display_mac_address": format_h3c_mac(row.get("bssid")) or row.get("bssid") or "-",
        "display_ap_mac": row.get("matched_ap_mac") or "-",
        "display_ap_name": row.get("matched_ap_name") if row.get("matched_ap_name") and row.get("matched_ap_name") != "-" else "-",
        "display_radio_id": row.get("matched_radio_id") or "-",
        "display_station": row.get("matched_station") or "-",
        "display_section": row.get("matched_section") or "-",
        "display_belong_type": _belong_type_display(row.get("matched_belong_type")),
        "display_belonging_source": row.get("matched_belonging_source") or row.get("match_rule") or "-",
        "display_location_mileage": location or "-",
        "display_rssi": row.get("rssi_dbm") if row.get("rssi_dbm") is not None else "-",
        "display_signal_quality": row.get("quality") if row.get("quality") is not None else "-",
        "display_channel": row.get("channel") if row.get("channel") is not None else "-",
        "display_frequency": row.get("frequency_mhz") if row.get("frequency_mhz") is not None else "-",
        "display_band": row.get("band") or "Unknown",
        "display_channel_width": display_channel_width,
        "display_mimo": row.get("mimo") or "-",
        "display_encryption_method": encryption_method,
        "display_encryption": encryption,
        "display_auth_method": auth_method,
    }


def _export_value(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return value


def _belong_type_display(value: object) -> str:
    text = str(value or "").strip().casefold()
    return {
        "station": "站点",
        "section": "区间",
        "yard": "场段/库内",
        "unknown": "未知",
    }.get(text, str(value or "").strip() or "-")


def _security_display(auth: str) -> str:
    value = str(auth or "").strip()
    if not value:
        return "-"
    lower = value.casefold()
    if "open" in lower:
        return "Open"
    if "wep" in lower:
        return "WEP"
    if "wpa3" in lower:
        return "WPA3-Personal" if "personal" in lower or "psk" in lower or "sae" in lower else "WPA3"
    if "wpa2" in lower:
        return "WPA2-Personal" if "personal" in lower or "psk" in lower else "WPA2"
    if "wpa" in lower:
        return "WPA"
    return value


def _auth_method(auth: str) -> str:
    value = str(auth or "").strip()
    lower = value.casefold()
    if not value:
        return "-"
    if "open" in lower:
        return "Open"
    if "sae" in lower or "wpa3" in lower:
        return "SAE"
    if "802.1x" in lower or "enterprise" in lower:
        return "802.1X"
    if "psk" in lower or "personal" in lower or "wpa" in lower:
        return "PSK"
    return "-"


def _mimo_display(network: WirelessNetwork) -> str:
    import re

    if network.mimo:
        return network.mimo
    for value in (network.raw.get("mimo"), network.raw.get("MIMO"), network.phy_type):
        match = re.search(r"\b[1-8]x[1-8]\b", str(value or ""), re.IGNORECASE)
        if match:
            return match.group(0).lower()
    return "-"
