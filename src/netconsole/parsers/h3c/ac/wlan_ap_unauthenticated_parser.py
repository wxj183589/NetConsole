from __future__ import annotations

import re

from netconsole.parsers.h3c.ac.state_mapper import map_fit_ap_state
from netconsole.services.ap_identity.normalizers import normalize_mac_key


WLAN_AP_UNAUTHENTICATED_SOURCE = "wlan_ap_unauthenticated"

SUMMARY_FIELD_PATTERNS = {
    "total_aps": r"Total number of APs:\s*(\d+)",
    "connected_aps": r"Total number of connected APs:\s*(\d+)",
    "connected_manual_aps": r"Total number of connected manual APs:\s*(\d+)",
    "connected_auto_aps": r"Total number of connected auto APs:\s*(\d+)",
    "connected_common_aps": r"Total number of connected common APs:\s*(\d+)",
    "connected_wtus": r"Total number of connected WTUs:\s*(\d+)",
    "inside_aps": r"Total number of inside APs:\s*(\d+)",
    "maximum_supported_aps": r"Maximum supported APs:\s*(\d+)",
    "remaining_aps": r"Remaining APs:\s*(\d+)",
    "total_ap_licenses": r"Total AP licenses:\s*(\d+)",
    "local_ap_licenses": r"Local AP licenses:\s*(\d+)",
    "server_ap_licenses": r"Server AP licenses:\s*(\d+)",
    "remaining_local_ap_licenses": r"Remaining local AP licenses:\s*(\d+)",
    "sync_ap_licenses": r"Sync AP licenses:\s*(\d+)",
}


def parse_wlan_ap_unauthenticated_summary(output: str) -> dict[str, int | None]:
    text = str(output or "")
    summary: dict[str, int | None] = {field: None for field in SUMMARY_FIELD_PATTERNS}
    for field, pattern in SUMMARY_FIELD_PATTERNS.items():
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            summary[field] = int(match.group(1))
    return summary


def classify_wlan_ap_unauthenticated_snapshot(
    output: str,
    rows: list[dict[str, object | None]] | None = None,
) -> str:
    """Classify one command output without turning parser failures into empty data."""

    if not is_wlan_ap_unauthenticated_output_parseable(output):
        return "FAILED"
    parsed_rows = rows if rows is not None else parse_wlan_ap_unauthenticated_rows(output)
    expected = parse_wlan_ap_unauthenticated_summary(output).get("connected_auto_aps")
    if expected is not None and expected != len(parsed_rows):
        return "FAILED"
    return "SUCCESS_WITH_ROWS" if parsed_rows else "SUCCESS_EMPTY"


def is_wlan_ap_unauthenticated_output_parseable(output: str) -> bool:
    in_ap_information = False
    for raw_line in str(output or "").splitlines():
        line = raw_line.strip()
        if line.casefold().startswith("ap information"):
            in_ap_information = True
            continue
        if in_ap_information and _is_unauthenticated_ap_header(line):
            return True
    return False


def parse_wlan_ap_unauthenticated_rows(
    output: str,
    *,
    collected_at: object | None = None,
    ac_id: object | None = None,
    site_key: object | None = None,
) -> list[dict[str, object | None]]:
    rows: list[dict[str, object | None]] = []
    state = "waiting_ap_information"
    for raw_line in str(output or "").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("<", "[")) or stripped.endswith(">"):
            continue
        lowered = stripped.casefold()
        if lowered.startswith("ap information"):
            state = "waiting_header"
            continue
        if state == "waiting_ap_information":
            continue
        if state == "waiting_header":
            if _is_unauthenticated_ap_header(stripped):
                state = "in_table"
            continue
        if lowered.startswith("ap name") or lowered.startswith("----") or lowered.startswith("state"):
            continue
        if lowered.startswith("total number"):
            continue
        parts = stripped.split()
        if not _is_valid_unauthenticated_ap_row(parts):
            continue
        ap_name, apid, state_raw, model, serial_number, dev_type, work_mode = parts[:7]
        normalized_mac = normalize_mac_key(ap_name) or None
        rows.append(
            {
                "ap_name": ap_name,
                "apid": apid,
                "ap_id": apid,
                "state": state_raw,
                "state_raw": state_raw,
                "state_display": map_fit_ap_state(state_raw),
                "model": model,
                "serial_number": serial_number,
                "serial_id": serial_number,
                "dev_type": dev_type,
                "work_mode": work_mode,
                "ap_mac": normalized_mac,
                # Retain the legacy field; the normalized MAC is now explicit.
                "inferred_ap_mac": None,
                "source": WLAN_AP_UNAUTHENTICATED_SOURCE,
                "ac_id": str(ac_id or "").strip(),
                "site_key": str(site_key or "").strip(),
                "collected_at": str(collected_at or "").strip(),
                "raw_line": stripped,
            }
        )
    return rows


def _is_unauthenticated_ap_header(line: str) -> bool:
    normalized = re.sub(r"\s+", " ", line.casefold())
    return all(token in normalized for token in ("ap name", "apid", "state", "model", "serial id", "dev-type", "work-mode"))


def _is_valid_unauthenticated_ap_row(parts: list[str]) -> bool:
    if len(parts) < 7:
        return False
    ap_name, apid, state_raw, model, serial_number, dev_type, work_mode = parts[:7]
    bad_tokens = {"", "-", "=", "c", "r", "m", "dc", "state", "ap", "total", "config", "datacheck", "run"}
    if ap_name.strip().casefold().rstrip(",") in bad_tokens:
        return False
    if not apid.isdigit():
        return False
    if model == "=" or serial_number == "=":
        return False
    state_text = state_raw.strip().casefold().rstrip(",")
    if state_text in {"config", "datacheck", "run", "master", "backup", "idle", "join"}:
        return False
    if work_mode.strip().casefold().rstrip(",") in bad_tokens:
        return False
    return True
