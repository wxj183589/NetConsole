from __future__ import annotations

import re
from datetime import datetime, timedelta

from netconsole.models.mesh_log_models import LINK_STATE_ACTIVE, MeshLogRecord
from netconsole.parsers.mesh_log_parser import normalize_peer_mac, parse_link_state, parse_mesh_link_table


COLLECTOR_RX_PREFIX_RE = re.compile(
    r"^(?P<stamp>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?)\s+\[collector=[^\]]+\]\s+RX\s?(?P<payload>.*)$"
)
CHANNEL_BUSY_RE = re.compile(
    r"(?P<key>channelbusy|channel\s*busy|totalbusy|total\s*busy|ctlbusy|txbusy|rxbusy|ctl\s*busy|tx\s*busy|rx\s*busy)\D+(?P<value>\d+)",
    re.IGNORECASE,
)
CHANNEL_BUSY_ROW_RE = re.compile(
    r"^\s*(?P<idx>\d+)\s+"
    r"(?P<time>\d{2}:\d{2}:\d{2})\s+"
    r"(?P<ctl>\d+|-)\s+"
    r"(?P<tx>\d+|-)\s+"
    r"(?P<rx>\d+|-)"
    r"(?:\s+(?P<ext>\d+|-))?\s*$"
)
CHANNEL_BUSY_DATE_RE = re.compile(r"Date/Month/Year:\s*(?P<day>\d{1,2})/(?P<month>\d{1,2})/(?P<year>\d{4})", re.IGNORECASE)
CHANNEL_BUSY_CTL_CHANNEL_RE = re.compile(r"\bCtl\s+Channel\s*:\s*(?P<value>\d+)", re.IGNORECASE)
CHANNEL_BUSY_BANDWIDTH_RE = re.compile(r"\bBandWidth\s*:\s*(?P<value>\d+)", re.IGNORECASE)
CHANNEL_BUSY_INTERVAL_RE = re.compile(r"\bRecord\s+Interval\(s\)\s*:\s*(?P<value>\d+)", re.IGNORECASE)
CHANNEL_BUSY_CURRENT_TIME_RE = re.compile(r"\bCurrentTime\s*:\s*(?P<value>\d{2}:\d{2}:\d{2})", re.IGNORECASE)
INTERFACE_RATE_ROW_RE = re.compile(
    r"^\s*(?P<interface>\S+)\s+"
    r"(?P<usage>\d+(?:\.\d+)?|-)\s+"
    r"(?P<total>\d+|-)\s+"
    r"(?P<broadcast>\d+|-)\s+"
    r"(?P<multicast>\d+|-)\s*$"
)
AP_RADIO_STAT_COUNTERS = (
    "TxFrameAllCnt",
    "TxFrameAllBytes",
    "RxFrameAllCnt",
    "RxFrameAllBytes",
    "TxRetryFrmCnt",
    "TxErrFrmCnt",
    "TxDiscardFrmCnt",
)
AP_RADIO_STAT_RE = re.compile(
    r"^\s*(?P<key>TxFrameAllCnt|TxFrameAllBytes|RxFrameAllCnt|RxFrameAllBytes|TxRetryFrmCnt|TxErrFrmCnt|TxDiscardFrmCnt)\s*:\s*(?P<values>[-\d\s]+)",
    re.IGNORECASE,
)
SWITCH_HISTORY_ROW_RE = re.compile(
    r"^\s*(?P<peer_name>(?:[0-9a-fA-F]{4}[-:.][0-9a-fA-F]{4}[-:.][0-9a-fA-F]{4})?)\s+"
    r"(?P<peer_mac>[0-9a-fA-F]{4}[-:.][0-9a-fA-F]{4}[-:.][0-9a-fA-F]{4})(?:\((?P<role>[^)]+)\))?\s+"
    r"(?P<reason>.+?)\s+"
    r"(?P<in_rssi>-?\d+)\s*/\s*(?P<out_rssi>-?\d+)\s+"
    r"(?P<switched_at>\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+"
    r"(?P<active_time>\d{2}h\s+\d{2}m\s+\d{2}s)\s*$",
    re.IGNORECASE,
)
MESH_PEER_TABLE_RE = re.compile(
    r"^\s*(?:(?P<peer_name>\S+)\s+)?"
    r"(?P<peer_mac>[0-9a-fA-F]{4}[-:.][0-9a-fA-F]{4}[-:.][0-9a-fA-F]{4})\s+"
    r"(?P<rssi>-?\d{1,3})\s+"
    r"(?P<bssid>[0-9a-fA-F]{4}[-:.][0-9a-fA-F]{4}[-:.][0-9a-fA-F]{4})\s+"
    r"(?P<interface>\S+)\s+"
    r"(?P<link_state>\S+(?:\([^)]+\))?)\s*"
    r"(?P<online_time>.*)?$"
)
LINK_STATE_WITH_MODE_RE = re.compile(r"^(?P<state>[A-Za-z]+)(?:\((?P<mode>[^)]+)\))?$")
MESH_PEER_FIELD_RE = re.compile(r"^\s*(?P<key>[A-Za-z][A-Za-z ]+)\s*[:：]\s*(?P<value>.*?)\s*$")
MESH_PEER_FIELD_ALIASES = {
    "peer name": "peer_name",
    "peer mac": "peer_mac",
    "peer radio": "bssid",
    "bssid": "bssid",
    "rssi": "rssi",
    "interface": "interface",
    "link state": "link_state_raw",
    "online time": "online_time",
}


def strip_collector_prefix(line: str) -> tuple[datetime | None, str]:
    match = COLLECTOR_RX_PREFIX_RE.match(str(line or ""))
    if not match:
        return None, str(line or "")
    stamp = match.group("stamp").replace("T", " ")
    try:
        collector_time = datetime.fromisoformat(stamp)
    except ValueError:
        collector_time = None
    return collector_time, match.group("payload")


def _clean_collector_text(raw_text: str) -> tuple[str, datetime | None]:
    lines: list[str] = []
    first_collector_time: datetime | None = None
    for line in str(raw_text or "").splitlines():
        collector_time, payload = strip_collector_prefix(line)
        if first_collector_time is None and collector_time is not None:
            first_collector_time = collector_time
        lines.append(payload)
    return "\n".join(lines), first_collector_time


def parse_mesh_link_text(raw_text: str, collected_at: datetime) -> tuple[list[MeshLogRecord], str, str]:
    clean_text, _collector_time = _clean_collector_text(raw_text)
    field_records = _parse_mesh_peer_field_blocks(clean_text, collected_at)
    if field_records:
        return field_records, "OK", ""
    if _looks_like_mesh_peer_table(clean_text):
        table_records = _parse_mesh_peer_table(clean_text, collected_at)
        if table_records:
            return table_records, "OK", ""
    records, issues = parse_mesh_link_table(clean_text, source_label="online", sample_time=collected_at, radio=1)
    if not records:
        table_records = _parse_mesh_peer_table(clean_text, collected_at)
        if table_records:
            return table_records, "OK", ""
        field_records = _parse_mesh_peer_field_blocks(clean_text, collected_at)
        if field_records:
            return field_records, "OK", ""
        message = "; ".join(issue.message for issue in issues[:3]) or "no mesh link records parsed"
        return [], "FAILED", message
    if issues:
        return records, "PARTIAL", "; ".join(issue.message for issue in issues[:3])
    return records, "OK", ""


def _looks_like_mesh_peer_table(text: str) -> bool:
    normalized = " ".join(str(text or "").split()).casefold()
    return "peer mac" in normalized and "rssi" in normalized and "online time" in normalized


def _parse_mesh_peer_table(raw_text: str, collected_at: datetime) -> list[MeshLogRecord]:
    records: list[MeshLogRecord] = []
    for line_number, line in enumerate(raw_text.splitlines(), start=1):
        parsed = parse_mesh_link_row(line)
        if parsed is None:
            continue
        state = _normalize_online_link_state(str(parsed["link_state_raw"]))
        peer_mac_raw = str(parsed["peer_mac"])
        peer_mac = normalize_peer_mac(peer_mac_raw)
        rssi = _busy_int(str(parsed["rssi"]))
        records.append(
            MeshLogRecord(
                source_label="online",
                source_file="<online>",
                source_line_number=line_number,
                raw_line=line.strip(),
                radio=1,
                sample_time=collected_at,
                timestamp_tag=None,
                link_state_raw=str(parsed["link_state_raw"]),
                link_state=state,
                peer_mac_raw=peer_mac_raw,
                peer_mac_normalized=peer_mac,
                establish_time=None,
                duration_text="",
                duration_seconds=None,
                link_count=None,
                metrics={
                    "peer_name": parsed["peer_name"],
                    "resolved_peer_name": parsed["peer_name"] or peer_mac_raw,
                    "bssid": parsed["bssid"],
                    "interface": parsed["interface"],
                    "online_time": parsed["online_time"],
                    "radio_mode": parsed["radio_mode"],
                    "local_rssi_db": rssi,
                    "peer_rssi_db": None,
                    "local_retry": None,
                    "peer_retry": None,
                    "local_tx_busy": None,
                    "local_rx_busy": None,
                },
            )
        )
    return records


def _parse_mesh_peer_field_blocks(raw_text: str, collected_at: datetime) -> list[MeshLogRecord]:
    records: list[MeshLogRecord] = []
    current: dict[str, object] = {}
    start_line = 0
    raw_lines: list[str] = []

    def flush(end_line: int) -> None:
        nonlocal current, start_line, raw_lines
        if _mesh_field_block_complete(current):
            record = _mesh_field_block_record(current, raw_lines, start_line or end_line, end_line, collected_at)
            if record is not None:
                records.append(record)
        current = {}
        start_line = 0
        raw_lines = []

    for line_number, line in enumerate(raw_text.splitlines(), start=1):
        match = MESH_PEER_FIELD_RE.match(line)
        if not match:
            if current and line.strip() == "":
                flush(line_number)
            continue
        key = MESH_PEER_FIELD_ALIASES.get(match.group("key").strip().casefold())
        if key is None:
            continue
        if key == "peer_name" and current:
            flush(line_number - 1)
        elif key in current and _mesh_field_block_complete(current):
            flush(line_number - 1)
        if not current:
            start_line = line_number
            raw_lines = []
        current[key] = match.group("value").strip()
        raw_lines.append(line.strip())
    if current:
        flush(len(raw_text.splitlines()))
    return records


def _mesh_field_block_complete(block: dict[str, object]) -> bool:
    return all(block.get(key) not in (None, "") for key in ("peer_mac", "rssi", "interface", "link_state_raw"))


def _mesh_field_block_record(
    block: dict[str, object],
    raw_lines: list[str],
    start_line: int,
    end_line: int,
    collected_at: datetime,
) -> MeshLogRecord | None:
    peer_mac_raw = str(block.get("peer_mac") or "")
    peer_mac = normalize_peer_mac(peer_mac_raw)
    rssi = _int_or_none(block.get("rssi"))
    link_state_raw = str(block.get("link_state_raw") or "")
    state_match = LINK_STATE_WITH_MODE_RE.match(link_state_raw.strip())
    radio_mode = (state_match.group("mode") if state_match else "") or ""
    if rssi is None:
        return None
    peer_name = str(block.get("peer_name") or "").strip()
    return MeshLogRecord(
        source_label="online",
        source_file="<online>",
        source_line_number=start_line,
        raw_line=" | ".join(raw_lines).strip(),
        radio=1,
        sample_time=collected_at,
        timestamp_tag=None,
        link_state_raw=link_state_raw,
        link_state=_normalize_online_link_state(link_state_raw),
        peer_mac_raw=peer_mac_raw,
        peer_mac_normalized=peer_mac,
        establish_time=None,
        duration_text="",
        duration_seconds=None,
        link_count=None,
        metrics={
            "peer_name": peer_name,
            "resolved_peer_name": peer_name or peer_mac_raw,
            "bssid": str(block.get("bssid") or ""),
            "interface": str(block.get("interface") or ""),
            "online_time": str(block.get("online_time") or ""),
            "radio_mode": radio_mode.strip(),
            "local_rssi_db": rssi,
            "peer_rssi_db": None,
            "local_retry": None,
            "peer_retry": None,
            "local_tx_busy": None,
            "local_rx_busy": None,
        },
        raw_line_start=start_line,
        raw_line_end=end_line,
    )


def parse_mesh_link_row(line: str) -> dict[str, object] | None:
    match = MESH_PEER_TABLE_RE.match(line)
    if not match:
        return None
    link_state_raw = match.group("link_state") or ""
    state_match = LINK_STATE_WITH_MODE_RE.match(link_state_raw.strip())
    radio_mode = (state_match.group("mode") if state_match else "") or ""
    return {
        "peer_name": (match.group("peer_name") or "").strip(),
        "peer_mac": match.group("peer_mac"),
        "peer_mac_normalized": normalize_peer_mac(match.group("peer_mac")),
        "rssi": int(match.group("rssi")),
        "bssid": match.group("bssid"),
        "interface": match.group("interface"),
        "link_state_raw": link_state_raw,
        "link_state": _normalize_online_link_state(link_state_raw),
        "radio_mode": radio_mode.strip(),
        "online_time": (match.group("online_time") or "").strip(),
    }


def parse_channel_busy_text(raw_text: str, collected_at: datetime | None = None) -> list[dict[str, int | str | None]]:
    raw_text, collector_time = _clean_collector_text(raw_text)
    collected_at = collected_at or collector_time
    table_rows: list[dict[str, int | str | None]] = []
    sample_date = ""
    date_match = CHANNEL_BUSY_DATE_RE.search(raw_text)
    if date_match:
        sample_date = f"{int(date_match.group('year')):04d}-{int(date_match.group('month')):02d}-{int(date_match.group('day')):02d}"
    elif collected_at is not None:
        sample_date = collected_at.date().isoformat()
    ctl_channel = _first_int_match(CHANNEL_BUSY_CTL_CHANNEL_RE, raw_text)
    bandwidth = _first_int_match(CHANNEL_BUSY_BANDWIDTH_RE, raw_text)
    record_interval = _first_int_match(CHANNEL_BUSY_INTERVAL_RE, raw_text)
    current_time = _first_text_match(CHANNEL_BUSY_CURRENT_TIME_RE, raw_text)
    for line in raw_text.splitlines():
        row = CHANNEL_BUSY_ROW_RE.match(line)
        if not row:
            continue
        raw_time = row.group("time")
        sample_time = _channel_busy_sample_time(sample_date, raw_time, current_time)
        ctl_busy = _busy_int(row.group("ctl"))
        tx_busy = _busy_int(row.group("tx"))
        rx_busy = _busy_int(row.group("rx"))
        summary = f"display ar5drv 1 channelbusy | CtlBusy={ctl_busy} TxBusy={tx_busy} RxBusy={rx_busy}"
        table_rows.append(
            {
                "radio": 1,
                "channel_busy_total": ctl_busy,
                "tx_busy": tx_busy,
                "rx_busy": rx_busy,
                "raw_text": summary,
                "raw_line": line.strip(),
                "sample_time": sample_time,
                "channel_busy_sample_time": sample_time,
                "collector_time": collected_at.isoformat(sep=" ", timespec="milliseconds") if collected_at else None,
                "ctl_busy": ctl_busy,
                "ctl_channel": ctl_channel,
                "bandwidth": bandwidth,
                "record_interval": record_interval,
                "row_index": int(row.group("idx")),
                "idx": int(row.group("idx")),
            }
        )
    if table_rows:
        return table_rows
    values = _extract_busy_values(raw_text)
    return [
        {
            "radio": 1,
            "channel_busy_total": values.get("ctl_busy"),
            "tx_busy": values.get("tx_busy"),
            "rx_busy": values.get("rx_busy"),
            "ctl_busy": values.get("ctl_busy"),
            "ctl_channel": ctl_channel,
            "bandwidth": bandwidth,
            "record_interval": record_interval,
            "row_index": 1,
            "sample_time": collected_at.isoformat(sep=" ", timespec="seconds") if collected_at else "",
            "channel_busy_sample_time": collected_at.isoformat(sep=" ", timespec="seconds") if collected_at else "",
            "collector_time": collected_at.isoformat(sep=" ", timespec="milliseconds") if collected_at else None,
            "raw_text": f"display ar5drv 1 channelbusy | CtlBusy={values.get('ctl_busy')} TxBusy={values.get('tx_busy')} RxBusy={values.get('rx_busy')}",
        }
    ]


def _first_int_match(pattern: re.Pattern[str], text: str) -> int | None:
    match = pattern.search(text)
    return int(match.group("value")) if match else None


def _first_text_match(pattern: re.Pattern[str], text: str) -> str:
    match = pattern.search(text)
    return match.group("value") if match else ""


def _extract_busy_values(raw_text: str) -> dict[str, int]:
    values: dict[str, int] = {}
    for line in str(raw_text or "").splitlines():
        for match in CHANNEL_BUSY_RE.finditer(line):
            key = match.group("key").lower().replace(" ", "")
            normalized = {
                "channelbusy": "ctl_busy",
                "totalbusy": "ctl_busy",
                "ctlbusy": "ctl_busy",
                "txbusy": "tx_busy",
                "rxbusy": "rx_busy",
            }.get(key)
            if normalized:
                values[normalized] = int(match.group("value"))
    return values


def _channel_busy_sample_time(sample_date: str, raw_time: str, current_time: str) -> str:
    if not sample_date:
        return raw_time
    try:
        sample_dt = datetime.fromisoformat(f"{sample_date} {raw_time}")
    except ValueError:
        return f"{sample_date} {raw_time}"
    if current_time:
        try:
            current_dt = datetime.fromisoformat(f"{sample_date} {current_time}")
            if sample_dt - current_dt > timedelta(hours=12):
                sample_dt -= timedelta(days=1)
            elif current_dt - sample_dt > timedelta(hours=12):
                sample_dt += timedelta(days=1)
        except ValueError:
            pass
    return sample_dt.isoformat(sep=" ", timespec="seconds")


def _busy_int(value: str) -> int | None:
    return None if value == "-" else int(value)


def _int_or_none(value: object) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _normalize_online_link_state(value: str) -> str:
    normalized = parse_link_state(value)
    if normalized:
        return normalized
    lowered = (value or "").casefold()
    if "active" in lowered:
        return LINK_STATE_ACTIVE
    if "standby" in lowered:
        return "STANDBY"
    return "UNKNOWN"


def parse_interface_rate_text(raw_text: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    direction = ""
    for line in raw_text.splitlines():
        lowered = line.lower()
        if "inbound interface" in lowered:
            direction = "inbound"
            continue
        if "outbound interface" in lowered:
            direction = "outbound"
            continue
        match = INTERFACE_RATE_ROW_RE.match(line)
        if not match or not direction:
            continue
        rows.append(
            {
                "direction": direction,
                "interface_name": match.group("interface"),
                "usage_percent": _float_or_none(match.group("usage")),
                "total_pps": _busy_int(match.group("total")),
                "broadcast_pps": _busy_int(match.group("broadcast")),
                "multicast_pps": _busy_int(match.group("multicast")),
                "raw_line": line.strip(),
            }
        )
    return rows


def parse_ap_radio_statistics_text(raw_text: str) -> dict[str, object]:
    raw_text, collector_time = _clean_collector_text(raw_text)
    counters: dict[str, int] = {}
    counter_values: dict[str, list[int]] = {}
    canonical_keys = {key.lower(): key for key in AP_RADIO_STAT_COUNTERS}
    for line in raw_text.splitlines():
        match = AP_RADIO_STAT_RE.match(line)
        if not match:
            continue
        key = canonical_keys.get(match.group("key").lower(), match.group("key"))
        values = [int(value) for value in re.findall(r"-?\d+", match.group("values"))]
        if not values:
            continue
        counter_values[key] = values
        counters[key] = sum(values) if len(values) > 1 else values[0]
    busy_values = _extract_busy_values(raw_text)
    sample_time = collector_time.isoformat(sep=" ", timespec="seconds") if collector_time else ""
    return {
        "counters": counters,
        "counter_values": counter_values,
        "channel_busy_total": busy_values.get("ctl_busy"),
        "ctl_busy": busy_values.get("ctl_busy"),
        "tx_busy": busy_values.get("tx_busy"),
        "rx_busy": busy_values.get("rx_busy"),
        "sample_time": sample_time,
        "channel_busy_sample_time": sample_time,
        "collector_time": collector_time.isoformat(sep=" ", timespec="milliseconds") if collector_time else None,
        "tx_frame_count": counters.get("TxFrameAllCnt"),
        "tx_frame_bytes": counters.get("TxFrameAllBytes"),
        "rx_frame_count": counters.get("RxFrameAllCnt"),
        "rx_frame_bytes": counters.get("RxFrameAllBytes"),
        "retry_count": counters.get("TxRetryFrmCnt"),
        "error_count": counters.get("TxErrFrmCnt"),
        "discard_count": counters.get("TxDiscardFrmCnt"),
        "raw_text": raw_text,
    }


def parse_switch_history_text(raw_text: str, collected_at: datetime | None = None) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    year = collected_at.year if collected_at is not None else datetime.now().year
    for line in raw_text.splitlines():
        match = SWITCH_HISTORY_ROW_RE.match(line)
        if not match:
            continue
        peer_name = (match.group("peer_name") or "").strip()
        peer_mac_raw = match.group("peer_mac")
        switch_time = _switch_history_time(year, match.group("switched_at"))
        rows.append(
            {
                "switch_time": switch_time,
                "radio": 1,
                "from_peer_name": "",
                "to_peer_name": peer_name,
                "from_peer_mac": "",
                "from_peer_mac_normalized": "",
                "to_peer_mac": peer_mac_raw,
                "to_peer_mac_normalized": normalize_peer_mac(peer_mac_raw),
                "reason": (match.group("reason") or "").strip(),
                "role": match.group("role") or "",
                "in_rssi": int(match.group("in_rssi")),
                "out_rssi": int(match.group("out_rssi")),
                "active_time": match.group("active_time"),
                "raw_line": line.strip(),
            }
        )
    rows.sort(key=lambda row: str(row.get("switch_time") or ""))
    previous: dict[str, object] | None = None
    for row in rows:
        if previous is not None:
            row["from_peer_name"] = previous.get("to_peer_name") or ""
            row["from_peer_mac"] = previous.get("to_peer_mac") or ""
            row["from_peer_mac_normalized"] = previous.get("to_peer_mac_normalized") or ""
        previous = row
    return rows


def _switch_history_time(year: int, value: str) -> str:
    try:
        parsed = datetime.strptime(f"{year}-{value}", "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return value
    return parsed.isoformat(sep=" ", timespec="seconds")


def _float_or_none(value: str) -> float | None:
    return None if value == "-" else float(value)


def summarize_active(records: list[MeshLogRecord]) -> MeshLogRecord | None:
    active = [record for record in records if record.link_state == LINK_STATE_ACTIVE]
    return active[0] if len(active) == 1 else None
