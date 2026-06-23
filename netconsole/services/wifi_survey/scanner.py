from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from statistics import median
from time import sleep

from netconsole.services.network_tools.netsh_wireless_scanner import NetshWirelessScanner


@dataclass(frozen=True)
class WifiObservation:
    ssid: str = ""
    bssid: str = ""
    rssi_dbm: float | None = None
    signal_quality: int | None = None
    channel: int | None = None
    frequency_mhz: int | None = None
    band: str = ""
    security: str = ""
    scan_time: str = ""
    raw_text: str = ""
    raw_json: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def scan_wifi(scan_count: int = 3, interval_seconds: float = 1.0) -> list[WifiObservation]:
    scanner = NetshWirelessScanner()
    grouped: dict[str, list[WifiObservation]] = {}
    last_raw = ""
    attempts = max(1, int(scan_count))
    for index in range(attempts):
        networks, raw = scanner.scan()
        last_raw = raw
        scan_time = datetime.now().isoformat(sep=" ", timespec="seconds")
        for network in networks:
            if not network.bssid:
                continue
            observation = WifiObservation(
                ssid=network.ssid,
                bssid=network.bssid,
                rssi_dbm=float(network.rssi_dbm) if network.rssi_dbm is not None else None,
                signal_quality=network.quality,
                channel=network.channel,
                frequency_mhz=network.frequency_mhz,
                band=network.band,
                security=" / ".join(part for part in (network.auth, network.encryption) if part),
                scan_time=scan_time,
                raw_text=raw,
                raw_json=str(network.raw),
            )
            grouped.setdefault(network.bssid.casefold(), []).append(observation)
        if index < attempts - 1:
            sleep(max(0.0, interval_seconds))
    return [_median_observation(items, last_raw) for items in grouped.values()]


def _median_observation(items: list[WifiObservation], fallback_raw: str) -> WifiObservation:
    first = items[0]
    rssi_values = [item.rssi_dbm for item in items if item.rssi_dbm is not None]
    quality_values = [item.signal_quality for item in items if item.signal_quality is not None]
    return WifiObservation(
        ssid=first.ssid,
        bssid=first.bssid,
        rssi_dbm=float(median(rssi_values)) if rssi_values else None,
        signal_quality=int(median(quality_values)) if quality_values else None,
        channel=first.channel,
        frequency_mhz=first.frequency_mhz,
        band=first.band,
        security=first.security,
        scan_time=items[-1].scan_time,
        raw_text=items[-1].raw_text or fallback_raw,
        raw_json=items[-1].raw_json,
    )
