from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


LINK_STATE_ACTIVE = "ACTIVE"
LINK_STATE_STANDBY = "STANDBY"
EVENT_ACTIVE_SWITCH = "ACTIVE_SWITCH"
EVENT_NO_ACTIVE = "NO_ACTIVE"
EVENT_MULTI_ACTIVE = "MULTI_ACTIVE"
EVENT_LINK_REESTABLISHED = "LINK_REESTABLISHED"
EVENT_COUNTER_RESET = "COUNTER_RESET"


def normalize_link_state(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return "UNKNOWN"
    lowered = text.lower()
    if "active" in lowered or "主链路" in text:
        return LINK_STATE_ACTIVE
    if "standby" in lowered or "standy" in lowered or "backup" in lowered or "备链" in text:
        return LINK_STATE_STANDBY
    return "UNKNOWN"


PAIRED_METRICS: tuple[tuple[str, str, str], ...] = (
    ("rssi", "local_rssi_db", "peer_rssi_db"),
    ("cpu", "local_cpu_percent", "peer_cpu_percent"),
    ("mem", "local_mem_percent", "peer_mem_percent"),
    ("tx_busy", "local_tx_busy", "peer_tx_busy"),
    ("rx_busy", "local_rx_busy", "peer_rx_busy"),
    ("rate", "local_rate_raw", "peer_rate_raw"),
    ("noise", "local_noise_raw", "peer_noise_raw"),
    ("tx_des_free_cnt", "local_tx_des_free_cnt", "peer_tx_des_free_cnt"),
    ("tx", "local_tx", "peer_tx"),
    ("rx", "local_rx", "peer_rx"),
    ("retry", "local_retry", "peer_retry"),
    ("err", "local_err", "peer_err"),
    ("garp", "local_tx_garp", "peer_rx_garp"),
    ("mul_join", "local_tx_mul_join", "peer_rx_mul_join"),
)


@dataclass
class ParseIssue:
    source_file: str
    line_number: int
    issue_type: str
    message: str
    raw_line: str
    severity: str = "WARNING"
    field_name: str = ""


def summarize_parse_issues(issues: list[ParseIssue]) -> dict[str, int]:
    """Return severity counts under the user-facing MESH diagnostic contract."""

    counts = {"info": 0, "warning": 0, "error": 0}
    for issue in issues:
        severity = str(issue.severity or "WARNING").strip().upper()
        if severity == "INFO":
            counts["info"] += 1
        elif severity == "ERROR":
            counts["error"] += 1
        else:
            # Unknown legacy values remain conservative and actionable.
            counts["warning"] += 1
    counts["actionable"] = counts["warning"] + counts["error"]
    counts["total"] = counts["info"] + counts["actionable"]
    return counts


@dataclass
class MeshMrProfile:
    mr_id: str
    display_name: str
    safe_folder_name: str
    relative_folder_path: str
    linked_device_id: int | None = None
    linked_device_uuid: str | None = None
    earliest_sample_time: datetime | None = None
    latest_sample_time: datetime | None = None
    source_file_count: int = 0
    sample_count: int = 0
    link_record_count: int = 0
    session_count: int = 0
    event_count: int = 0
    last_import_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    notes: str = ""


@dataclass
class ImportedLogFile:
    path: Path
    source_label: str
    size: int = 0
    modified_time: datetime | None = None
    file_hash: str = ""
    status: str = "pending"
    record_count: int = 0
    skipped_count: int = 0
    duplicate_count: int = 0
    info_count: int = 0
    warning_count: int = 0
    error_count: int = 0
    lines_read: int = 0
    encoding: str = ""
    archived_path: Path | None = None
    imported_at: datetime | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    error_message: str = ""


@dataclass
class MeshLogRecord:
    source_label: str
    source_file: str
    source_line_number: int
    raw_line: str
    radio: int
    sample_time: datetime
    timestamp_tag: str | None
    link_state_raw: str
    link_state: str
    peer_mac_raw: str
    peer_mac_normalized: str | None
    establish_time: datetime | None
    duration_text: str
    duration_seconds: int | None
    link_count: int | None
    metrics: dict[str, int | None] = field(default_factory=dict)
    local_noise_dbm: int | None = None
    peer_noise_dbm: int | None = None
    local_signal_dbm: int | None = None
    peer_signal_dbm: int | None = None
    duplicate_hash: str = ""
    source_file_id: int | None = None
    sample_id: int | None = None
    session_id: str | None = None
    sample_time_epoch_ms: int | None = None
    expected_duration_seconds: int | None = None
    duration_deviation_seconds: int | None = None
    deltas: dict[str, int | None] = field(default_factory=dict)
    source_file_order: int = 0
    record_seq: int = 0
    raw_line_start: int = 0
    raw_line_end: int = 0
    raw_offset_start: int = 0
    raw_offset_end: int = 0

    def peer_mac_h3c(self) -> str:
        return format_mac_h3c(self.peer_mac_normalized) if self.peer_mac_normalized else self.peer_mac_raw


@dataclass
class MeshSwitchEvent:
    event_type: str
    source_label: str
    radio: int
    previous_sample_time: datetime | None = None
    current_sample_time: datetime | None = None
    observed_window_ms: int | None = None
    from_peer_mac: str | None = None
    to_peer_mac: str | None = None
    from_local_rssi: int | None = None
    from_peer_rssi: int | None = None
    from_local_signal_dbm: int | None = None
    from_peer_signal_dbm: int | None = None
    from_local_rate: int | None = None
    from_peer_rate: int | None = None
    to_local_rssi: int | None = None
    to_peer_rssi: int | None = None
    to_local_signal_dbm: int | None = None
    to_peer_signal_dbm: int | None = None
    to_local_rate: int | None = None
    to_peer_rate: int | None = None
    source_file: str = ""
    source_line_number: int = 0


@dataclass
class MeshAnalysisSummary:
    file_count: int = 0
    source_count: int = 0
    start_time: datetime | None = None
    end_time: datetime | None = None
    sample_count: int = 0
    record_count: int = 0
    radio_count: int = 0
    peer_count: int = 0
    active_switch_count: int = 0
    no_active_count: int = 0
    multi_active_count: int = 0
    info_count: int = 0
    warning_count: int = 0
    error_count: int = 0
    issue_count: int = 0
    raw_record_count: int = 0
    duplicate_record_count: int = 0


@dataclass
class MeshAnalysisResult:
    analysis_id: str
    site_id: str
    analysis_name: str
    files: list[ImportedLogFile]
    records: list[MeshLogRecord]
    switch_events: list[MeshSwitchEvent]
    issues: list[ParseIssue]
    summary: MeshAnalysisSummary
    analysis_dir: Path | None = None


@dataclass(frozen=True)
class MeshPeerResolution:
    ap_id: str | None = None
    ap_name: str | None = None
    station_name: str | None = None
    location: str | None = None
    line_name: str | None = None
    track_section: str | None = None
    radio_id: str | None = None


class MeshPeerResolver:
    def resolve(self, site_name: str, mr_id: str, peer_mac_normalized: str | None, sample_time: datetime) -> MeshPeerResolution:
        raise NotImplementedError


class NullMeshPeerResolver(MeshPeerResolver):
    def resolve(self, site_name: str, mr_id: str, peer_mac_normalized: str | None, sample_time: datetime) -> MeshPeerResolution:
        return MeshPeerResolution()


def format_mac_h3c(value: str | None) -> str:
    if not value or len(value) != 12:
        return value or ""
    return f"{value[0:4]}-{value[4:8]}-{value[8:12]}"


def dataclass_to_json_dict(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, list):
        return [dataclass_to_json_dict(item) for item in value]
    if isinstance(value, dict):
        return {key: dataclass_to_json_dict(item) for key, item in value.items()}
    if hasattr(value, "__dataclass_fields__"):
        return {key: dataclass_to_json_dict(getattr(value, key)) for key in value.__dataclass_fields__}
    return value
