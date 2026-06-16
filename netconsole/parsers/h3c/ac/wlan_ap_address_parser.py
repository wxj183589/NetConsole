from __future__ import annotations

import re


IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
MAC_RE = re.compile(r"\b[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}\b", re.IGNORECASE)


def parse_wlan_ap_addresses(output: str) -> dict[str, dict[str, object | None]]:
    rows: dict[str, dict[str, object | None]] = {}
    for line in output.splitlines():
        stripped = line.strip()
        if (
            not stripped
            or stripped.startswith(("-", "=", "<"))
            or stripped.lower().startswith(("total ", "ap name", "apname"))
        ):
            continue
        ip_match = IP_RE.search(stripped)
        mac_match = MAC_RE.search(stripped)
        if not ip_match and not mac_match:
            continue
        before = stripped[: ip_match.start() if ip_match else mac_match.start()].strip()
        ap_name = before.split()[0] if before.split() else ""
        if not ap_name:
            continue
        rows[ap_name] = {
            "ap_name": ap_name,
            "ap_ip": ip_match.group(0) if ip_match else None,
            "ap_mac": mac_match.group(0) if mac_match else None,
        }
    return rows
