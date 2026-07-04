from __future__ import annotations

import re


MAC_RE = re.compile(r"\b[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}\b", re.IGNORECASE)


def parse_wlan_ap_radio_verbose_bbssid(output: str) -> dict[str, dict[str, object | None]]:
    rows: dict[str, dict[str, object | None]] = {}
    in_table = False
    for line in output.splitlines():
        stripped = line.strip()
        lower = stripped.casefold()
        if not stripped or stripped.startswith(("<", "-", "=")) or "---- more ----" in lower:
            continue
        if not in_table:
            compact = " ".join(stripped.split()).casefold()
            if compact.startswith("ap name rid bbssid"):
                in_table = True
            continue
        if lower.startswith(("ap name", "total ", "radio filtered information", "bbssid =")):
            continue
        mac_matches = list(MAC_RE.finditer(stripped))
        if not mac_matches:
            continue
        mac_match = mac_matches[-1]
        before = stripped[: mac_match.start()].strip()
        parts = before.split()
        if len(parts) < 2:
            continue
        rid_text = parts[-1]
        if not rid_text.isdigit():
            continue
        rid = int(rid_text)
        if rid not in (1, 2, 3):
            continue
        ap_name = " ".join(parts[:-1]).strip()
        if not ap_name:
            continue
        row = rows.setdefault(ap_name, {"ap_name": ap_name})
        row[f"rid{rid}_bbssid"] = mac_match.group(0)
    return rows
