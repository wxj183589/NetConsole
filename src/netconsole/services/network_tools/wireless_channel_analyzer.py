from __future__ import annotations

import re


def normalize_mac(value: object) -> str | None:
    text = re.sub(r"[^0-9a-fA-F]", "", str(value or ""))
    return text.casefold() if len(text) == 12 else None


def format_h3c_mac(value: object) -> str:
    mac = normalize_mac(value)
    if not mac:
        return ""
    return f"{mac[0:4]}-{mac[4:8]}-{mac[8:12]}"


def band_from_frequency(frequency_mhz: int | None) -> str:
    if frequency_mhz is None:
        return ""
    if 2400 <= frequency_mhz <= 2500:
        return "2.4G"
    if 4900 <= frequency_mhz <= 5900:
        return "5G"
    if 5900 <= frequency_mhz <= 7200:
        return "6G"
    return ""


def frequency_to_channel(frequency_mhz: int | None) -> int | None:
    if frequency_mhz is None:
        return None
    if 2412 <= frequency_mhz <= 2484:
        if frequency_mhz == 2484:
            return 14
        return round((frequency_mhz - 2407) / 5)
    if 4900 <= frequency_mhz <= 5900:
        return round((frequency_mhz - 5000) / 5)
    if 5955 <= frequency_mhz <= 7115:
        return round((frequency_mhz - 5950) / 5)
    return None


def quality_to_rssi_dbm(quality: int | None) -> int | None:
    if quality is None:
        return None
    quality = max(0, min(100, int(quality)))
    return int(round((quality / 2) - 100))


def rssi_level(rssi_dbm: int | None) -> str:
    if rssi_dbm is None:
        return "unknown"
    if rssi_dbm >= -50:
        return "strong"
    if rssi_dbm >= -65:
        return "good"
    if rssi_dbm >= -75:
        return "fair"
    return "weak"
