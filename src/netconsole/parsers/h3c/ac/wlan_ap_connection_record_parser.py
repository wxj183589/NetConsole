from __future__ import annotations

from datetime import datetime
import re

from netconsole.services.ap_identity.normalizers import normalize_mac_key


_ROW = re.compile(
    r"^(?P<name>.+?)\s+(?P<ip>\S+)\s+(?P<state>Discovery|Join|Offline|Run)\s+"
    r"(?P<time>\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})$",
    re.IGNORECASE,
)


def parse_wlan_ap_connection_record_rows(
    output: str,
    *,
    collected_at: object | None = None,
    ac_id: object | None = None,
    site_key: object | None = None,
) -> list[dict[str, object | None]]:
    """Parse H3C ``connection-record`` into identity-safe observations.

    H3C omits the year from ``Time``.  Keep the device value untouched as
    ``raw_time`` and resolve it against the successful command observation
    time.  The AP name is accepted as a MAC only when it is a valid 12-hex
    address; arbitrary names are never guessed as physical identities.
    """

    reference = _coerce_datetime(collected_at) or datetime.now().astimezone()
    rows: list[dict[str, object | None]] = []
    for line in str(output or "").splitlines():
        match = _ROW.match(line.strip())
        if not match:
            continue
        name = match.group("name").strip()
        raw_time = match.group("time")
        normalized_mac = normalize_mac_key(name) or ""
        state = match.group("state")
        row = {
            "ap_name": name,
            "ap_mac": normalized_mac or None,
            "ip_address": _value(match.group("ip")),
            "state": state,
            "connection_ip": _value(match.group("ip")),
            "connection_state": state,
            "connection_time": raw_time,
            "raw_time": raw_time,
            "resolved_time": resolve_connection_record_time(raw_time, reference),
            "ac_id": str(ac_id or "").strip(),
            "site_key": str(site_key or "").strip(),
            "collected_at": _format_datetime(reference),
            "raw_line": line.strip(),
        }
        rows.append(row)
    return rows


def is_wlan_ap_connection_record_output_parseable(output: str) -> bool:
    """Return whether the command produced its tabular header."""

    for raw_line in str(output or "").splitlines():
        normalized = re.sub(r"\s+", " ", raw_line.strip()).casefold()
        if all(token in normalized for token in ("ap name", "ip address", "state", "time")):
            return True
    return False


def parse_wlan_ap_connection_records(
    output: str,
    *,
    collected_at: object | None = None,
    ac_id: object | None = None,
    site_key: object | None = None,
) -> dict[str, dict[str, object | None]]:
    """Backward-compatible name-indexed view of connection-record rows."""

    rows: dict[str, dict[str, object | None]] = {}
    for row in parse_wlan_ap_connection_record_rows(
        output,
        collected_at=collected_at,
        ac_id=ac_id,
        site_key=site_key,
    ):
        if collected_at is None and ac_id is None and site_key is None:
            rows[str(row.get("ap_name") or "")] = {
                "ap_name": row.get("ap_name"),
                "connection_ip": row.get("connection_ip"),
                "connection_state": row.get("connection_state"),
                "connection_time": row.get("connection_time"),
            }
        else:
            rows[str(row.get("ap_name") or "")] = row
    return rows


def resolve_connection_record_time(raw_time: object, collected_at: object | None = None) -> str:
    """Resolve ``MM-DD HH:MM:SS`` to the calendar year nearest collection."""

    match = re.fullmatch(r"(?P<month>\d{2})-(?P<day>\d{2})\s+(?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2})", str(raw_time or "").strip())
    reference = _coerce_datetime(collected_at) or datetime.now().astimezone()
    if not match:
        return str(raw_time or "").strip()
    month = int(match.group("month"))
    day = int(match.group("day"))
    parts = {
        "month": month,
        "day": day,
        "hour": int(match.group("hour")),
        "minute": int(match.group("minute")),
        "second": int(match.group("second")),
    }
    candidates: list[datetime] = []
    for year in (reference.year - 1, reference.year, reference.year + 1):
        try:
            candidates.append(datetime(year=year, **parts))
        except ValueError:
            continue
    if not candidates:
        return str(raw_time or "").strip()
    selected = min(candidates, key=lambda candidate: abs(candidate - reference.replace(tzinfo=None)))
    return selected.strftime("%Y-%m-%d %H:%M:%S")


def _coerce_datetime(value: object | None) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone().replace(tzinfo=None) if value.tzinfo else value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        return None
    return parsed.astimezone().replace(tzinfo=None) if parsed.tzinfo else parsed


def _format_datetime(value: datetime) -> str:
    return value.replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")


def _value(value: str) -> str | None:
    return None if value.upper() in {"N/A", "NA", "-"} else value
