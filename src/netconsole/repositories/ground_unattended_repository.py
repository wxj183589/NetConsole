from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from netconsole.models.api.ground_unattended import GroundUnattendedProfileDTO
from netconsole.core.database import Database
from netconsole.core.sqlite_utils import configure_sqlite_connection, initialize_sqlite_wal


SCHEMA = """
CREATE TABLE IF NOT EXISTS ground_unattended_schema (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ground_unattended_profiles (
    site_id TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 0,
    schedule_start_time TEXT NOT NULL DEFAULT '07:00',
    schedule_end_time TEXT NOT NULL DEFAULT '23:00',
    timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
    ac_poll_interval_seconds INTEGER NOT NULL DEFAULT 10,
    stationary_exclusion_minutes INTEGER NOT NULL DEFAULT 10,
    ac_stale_grace_seconds INTEGER NOT NULL DEFAULT 120,
    ac_ping_correlation_tolerance_seconds INTEGER NOT NULL DEFAULT 15,
    ap_switch_before_seconds INTEGER NOT NULL DEFAULT 5,
    ap_switch_after_seconds INTEGER NOT NULL DEFAULT 5,
    max_active_trains INTEGER NOT NULL DEFAULT 2,
    max_active_mrs INTEGER NOT NULL DEFAULT 4,
    max_starting_mrs INTEGER NOT NULL DEFAULT 2,
    max_finalizing_mrs INTEGER NOT NULL DEFAULT 2,
    deep_collection_master_enabled INTEGER NOT NULL DEFAULT 1,
    fleet_ping_interval_ms INTEGER NOT NULL DEFAULT 1000,
    fleet_ping_timeout_ms INTEGER NOT NULL DEFAULT 4000,
    fleet_ping_packet_size INTEGER NOT NULL DEFAULT 64,
    fleet_ping_shard_size INTEGER NOT NULL DEFAULT 12,
    fleet_ping_warmup_seconds INTEGER NOT NULL DEFAULT 10,
    ping_depot_trains_enabled INTEGER NOT NULL DEFAULT 0,
    udp_listen_host TEXT NOT NULL DEFAULT '0.0.0.0',
    udp_listen_port INTEGER NOT NULL DEFAULT 514,
    udp_queue_capacity INTEGER NOT NULL DEFAULT 20000,
    raw_flush_interval_seconds REAL NOT NULL DEFAULT 1.0,
    raw_flush_record_count INTEGER NOT NULL DEFAULT 100,
    event_batch_size INTEGER NOT NULL DEFAULT 100,
    event_batch_interval_seconds REAL NOT NULL DEFAULT 1.0,
    boot_time_tolerance_seconds INTEGER NOT NULL DEFAULT 120,
    config_check_cooldown_seconds INTEGER NOT NULL DEFAULT 1800,
    syslog_server_ip TEXT NOT NULL DEFAULT '',
    syslog_server_port INTEGER NOT NULL DEFAULT 514,
    syslog_auto_repair_enabled INTEGER NOT NULL DEFAULT 1,
    allow_external_syslog_address INTEGER NOT NULL DEFAULT 0,
    ping_raw_retention_days INTEGER NOT NULL DEFAULT 30,
    syslog_raw_retention_days INTEGER NOT NULL DEFAULT 30,
    minimum_valid_collection_minutes INTEGER NOT NULL DEFAULT 10,
    preferred_collection_minutes INTEGER NOT NULL DEFAULT 20,
    maximum_collection_minutes INTEGER NOT NULL DEFAULT 30,
    start_jitter_seconds INTEGER NOT NULL DEFAULT 3,
    start_batch_size INTEGER NOT NULL DEFAULT 1,
    detail_retention_days INTEGER NOT NULL DEFAULT 30,
    summary_retention_days INTEGER NOT NULL DEFAULT 180,
    storage_warning_free_gb REAL NOT NULL DEFAULT 5.0,
    storage_critical_free_gb REAL NOT NULL DEFAULT 1.0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ground_unattended_priority_trains (
    site_id TEXT NOT NULL,
    train_id TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (site_id, train_id)
);

CREATE TABLE IF NOT EXISTS ground_unattended_runs (
    run_id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL,
    run_date TEXT NOT NULL,
    state TEXT NOT NULL,
    paused INTEGER NOT NULL DEFAULT 0,
    requested_action TEXT NOT NULL DEFAULT '',
    scheduled_start_at TEXT NOT NULL DEFAULT '',
    scheduled_end_at TEXT NOT NULL DEFAULT '',
    actual_started_at TEXT NOT NULL DEFAULT '',
    actual_ended_at TEXT NOT NULL DEFAULT '',
    ac_last_updated_at TEXT NOT NULL DEFAULT '',
    ac_freshness_status TEXT NOT NULL DEFAULT 'NO_DATA',
    ping_sample_count INTEGER NOT NULL DEFAULT 0,
    summary_json TEXT NOT NULL DEFAULT '{}',
    error_code TEXT NOT NULL DEFAULT '',
    error_message TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (site_id, run_date)
);
CREATE INDEX IF NOT EXISTS idx_ground_runs_site_state
ON ground_unattended_runs(site_id, state, updated_at DESC);

CREATE TABLE IF NOT EXISTS ground_unattended_train_runs (
    site_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    run_date TEXT NOT NULL,
    train_id TEXT NOT NULL,
    train_no TEXT NOT NULL DEFAULT '',
    train_name TEXT NOT NULL DEFAULT '',
    location_class TEXT NOT NULL DEFAULT 'UNKNOWN',
    mainline_eligible INTEGER NOT NULL DEFAULT 0,
    coverage_status TEXT NOT NULL DEFAULT 'NOT_SEEN',
    priority INTEGER NOT NULL DEFAULT 0,
    ping_eligible INTEGER NOT NULL DEFAULT 0,
    deep_collection_eligible INTEGER NOT NULL DEFAULT 0,
    ping_inclusion_reason TEXT NOT NULL DEFAULT '',
    ping_exclusion_reason TEXT NOT NULL DEFAULT '',
    deep_exclusion_reason TEXT NOT NULL DEFAULT '',
    eligibility_status TEXT NOT NULL DEFAULT 'AC_UNKNOWN',
    exclusion_reason TEXT NOT NULL DEFAULT '',
    location_match_level TEXT NOT NULL DEFAULT 'UNMATCHED',
    location_match_reason TEXT NOT NULL DEFAULT '',
    resolved_ap_id TEXT NOT NULL DEFAULT '',
    resolved_ap_name TEXT NOT NULL DEFAULT '',
    raw_peer_ap_name TEXT NOT NULL DEFAULT '',
    raw_peer_ap_mac TEXT NOT NULL DEFAULT '',
    canonical_station_name TEXT NOT NULL DEFAULT '',
    current_ap_identity TEXT NOT NULL DEFAULT '',
    current_ap_name TEXT NOT NULL DEFAULT '',
    current_ap_mac TEXT NOT NULL DEFAULT '',
    station TEXT NOT NULL DEFAULT '',
    section TEXT NOT NULL DEFAULT '',
    mileage TEXT NOT NULL DEFAULT '',
    rssi INTEGER,
    same_ap_since TEXT NOT NULL DEFAULT '',
    same_ap_duration_seconds INTEGER NOT NULL DEFAULT 0,
    ac_snapshot_id INTEGER,
    ac_received_at TEXT NOT NULL DEFAULT '',
    endpoints_json TEXT NOT NULL DEFAULT '[]',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    covered_rounds INTEGER NOT NULL DEFAULT 0,
    selection_reason TEXT NOT NULL DEFAULT '',
    failure_reason TEXT NOT NULL DEFAULT '',
    collection_started_at TEXT NOT NULL DEFAULT '',
    valid_duration_minutes REAL NOT NULL DEFAULT 0,
    operations_json TEXT NOT NULL DEFAULT '{}',
    sessions_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (site_id, run_id, train_id)
);
CREATE INDEX IF NOT EXISTS idx_ground_train_runs_coverage
ON ground_unattended_train_runs(site_id, run_id, coverage_status, priority DESC, attempt_count);

CREATE TABLE IF NOT EXISTS ground_unattended_daily_queues (
    site_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    run_date TEXT NOT NULL,
    random_seed INTEGER NOT NULL,
    generated_at TEXT NOT NULL,
    candidate_train_ids_json TEXT NOT NULL,
    queue_order_json TEXT NOT NULL,
    PRIMARY KEY (site_id, run_id)
);

CREATE TABLE IF NOT EXISTS ground_unattended_ac_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id TEXT NOT NULL,
    site_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    ac_device_id TEXT NOT NULL DEFAULT '',
    source_snapshot_id INTEGER,
    device_time TEXT NOT NULL DEFAULT '',
    received_at TEXT NOT NULL,
    train_id TEXT NOT NULL DEFAULT '',
    train_no TEXT NOT NULL DEFAULT '',
    mr_id TEXT NOT NULL DEFAULT '',
    mr_position_code TEXT NOT NULL DEFAULT '',
    mr_online_status TEXT NOT NULL DEFAULT 'unknown',
    peer_ap_name TEXT NOT NULL DEFAULT '',
    peer_ap_mac TEXT NOT NULL DEFAULT '',
    station TEXT NOT NULL DEFAULT '',
    section TEXT NOT NULL DEFAULT '',
    mileage TEXT NOT NULL DEFAULT '',
    rssi INTEGER,
    freshness_status TEXT NOT NULL DEFAULT 'no_data',
    raw_source_reference TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_ground_ac_received
ON ground_unattended_ac_snapshots(site_id, run_id, received_at, train_id, mr_id);

CREATE TABLE IF NOT EXISTS ground_unattended_ping_segments (
    segment_id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    shard_id TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT NOT NULL DEFAULT '',
    target_count INTEGER NOT NULL DEFAULT 0,
    sample_count INTEGER NOT NULL DEFAULT 0,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    sha256 TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'OPEN',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ground_ping_segments_run
ON ground_unattended_ping_segments(site_id, run_id, started_at);

CREATE TABLE IF NOT EXISTS ground_unattended_ping_target_activations (
    site_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    target_ip TEXT NOT NULL,
    activated_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    removed_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (site_id, run_id, target_ip)
);
CREATE INDEX IF NOT EXISTS idx_ground_ping_target_activations
ON ground_unattended_ping_target_activations(site_id, run_id, active, updated_at);

CREATE TABLE IF NOT EXISTS ground_unattended_ping_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    bucket_kind TEXT NOT NULL,
    bucket_start TEXT NOT NULL,
    bucket_end TEXT NOT NULL,
    target_ip TEXT NOT NULL DEFAULT '',
    train_id TEXT NOT NULL DEFAULT '',
    train_no TEXT NOT NULL DEFAULT '',
    mr_id TEXT NOT NULL DEFAULT '',
    mr_position_code TEXT NOT NULL DEFAULT '',
    ac_snapshot_id INTEGER,
    ap_identity TEXT NOT NULL DEFAULT '',
    raw_sample_count INTEGER NOT NULL DEFAULT 0,
    warmup_ignored_count INTEGER NOT NULL DEFAULT 0,
    sent_count INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    loss_count INTEGER NOT NULL DEFAULT 0,
    loss_rate_percent REAL NOT NULL DEFAULT 0,
    min_rtt_ms REAL,
    avg_rtt_ms REAL,
    max_rtt_ms REAL,
    continuous_loss_max_count INTEGER NOT NULL DEFAULT 0,
    continuous_loss_max_seconds REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE (site_id, run_id, bucket_kind, bucket_start, target_ip, ap_identity)
);
CREATE INDEX IF NOT EXISTS idx_ground_ping_summary_query
ON ground_unattended_ping_summaries(site_id, run_id, bucket_kind, train_id, mr_id, bucket_start DESC);

CREATE TABLE IF NOT EXISTS ground_unattended_deep_operations (
    operation_id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    train_id TEXT NOT NULL,
    mr_id TEXT NOT NULL,
    mr_position_code TEXT NOT NULL,
    session_id TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT 'STARTING',
    started_at TEXT NOT NULL,
    ended_at TEXT NOT NULL DEFAULT '',
    stop_reason TEXT NOT NULL DEFAULT '',
    error_summary TEXT NOT NULL DEFAULT '',
    finalization_complete INTEGER NOT NULL DEFAULT 0,
    package_verified INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ground_deep_active
ON ground_unattended_deep_operations(site_id, run_id, state, train_id);

CREATE TABLE IF NOT EXISTS ground_unattended_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id TEXT NOT NULL,
    run_id TEXT NOT NULL DEFAULT '',
    ts TEXT NOT NULL,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'info',
    train_id TEXT NOT NULL DEFAULT '',
    mr_id TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL DEFAULT '',
    details_json TEXT NOT NULL DEFAULT '{}',
    dedup_key TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_ground_events_timeline
ON ground_unattended_events(site_id, run_id, ts DESC, event_type);

CREATE TABLE IF NOT EXISTS ground_unattended_archives (
    archive_id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    run_date TEXT NOT NULL,
    relative_path TEXT NOT NULL DEFAULT '',
    archive_status TEXT NOT NULL DEFAULT 'PENDING',
    archive_size_bytes INTEGER NOT NULL DEFAULT 0,
    sha256 TEXT NOT NULL DEFAULT '',
    manifest_sha256 TEXT NOT NULL DEFAULT '',
    retention_until TEXT NOT NULL DEFAULT '',
    active_cleanup_pending INTEGER NOT NULL DEFAULT 0,
    summary_json TEXT NOT NULL DEFAULT '{}',
    message TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (site_id, run_id)
);
CREATE INDEX IF NOT EXISTS idx_ground_archives_site_date
ON ground_unattended_archives(site_id, run_date DESC);

CREATE TABLE IF NOT EXISTS ground_unattended_operations (
    operation_id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    operation_type TEXT NOT NULL,
    operation_state TEXT NOT NULL DEFAULT 'PENDING',
    operation_stage TEXT NOT NULL DEFAULT 'STOP_REQUESTED',
    progress_percent INTEGER NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT NOT NULL DEFAULT '',
    failure_code TEXT NOT NULL DEFAULT '',
    failure_reason TEXT NOT NULL DEFAULT '',
    result_summary_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_ground_operations_active
ON ground_unattended_operations(site_id, run_id, operation_state, updated_at DESC);

CREATE TABLE IF NOT EXISTS ground_unattended_train_inventory (
    site_id TEXT NOT NULL,
    train_id TEXT NOT NULL,
    train_no TEXT NOT NULL DEFAULT '',
    train_name TEXT NOT NULL DEFAULT '',
    inventory_status TEXT NOT NULL DEFAULT 'ACTIVE',
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    removed_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (site_id, train_id)
);
CREATE INDEX IF NOT EXISTS idx_ground_inventory_site_status
ON ground_unattended_train_inventory(site_id, inventory_status, train_no);

CREATE TABLE IF NOT EXISTS ground_unattended_train_endpoints (
    site_id TEXT NOT NULL,
    device_uuid TEXT NOT NULL,
    device_id INTEGER,
    train_id TEXT NOT NULL,
    mr_role TEXT NOT NULL,
    device_name TEXT NOT NULL DEFAULT '',
    management_ip TEXT NOT NULL DEFAULT '',
    protocol TEXT NOT NULL DEFAULT '',
    port INTEGER,
    source_hostname TEXT NOT NULL DEFAULT '',
    last_syslog_source_ip TEXT NOT NULL DEFAULT '',
    syslog_hostname TEXT NOT NULL DEFAULT '',
    last_syslog_identity_verified_at TEXT NOT NULL DEFAULT '',
    binding_status TEXT NOT NULL DEFAULT 'ACTIVE',
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    removed_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (site_id, device_uuid)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_ground_endpoints_active_role
ON ground_unattended_train_endpoints(site_id, train_id, mr_role)
WHERE binding_status='ACTIVE';
CREATE INDEX IF NOT EXISTS idx_ground_endpoints_ip
ON ground_unattended_train_endpoints(site_id, management_ip, binding_status);

CREATE TABLE IF NOT EXISTS ground_unattended_train_policies (
    site_id TEXT NOT NULL,
    train_id TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    priority INTEGER NOT NULL DEFAULT 0,
    scheduling_priority INTEGER NOT NULL DEFAULT 0,
    deep_collection_enabled INTEGER NOT NULL DEFAULT 1,
    monitor_only INTEGER NOT NULL DEFAULT 0,
    remark TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (site_id, train_id)
);

CREATE TABLE IF NOT EXISTS ground_unattended_boot_sessions (
    boot_session_id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL,
    device_uuid TEXT NOT NULL,
    device_id INTEGER,
    train_id TEXT NOT NULL DEFAULT '',
    mr_role TEXT NOT NULL DEFAULT '',
    first_detected_at TEXT NOT NULL,
    last_checked_at TEXT NOT NULL,
    estimated_boot_time TEXT NOT NULL,
    first_uptime_seconds INTEGER NOT NULL,
    last_uptime_seconds INTEGER NOT NULL,
    device_clock_before TEXT NOT NULL DEFAULT '',
    device_clock_after TEXT NOT NULL DEFAULT '',
    boot_time_uncertainty_seconds INTEGER NOT NULL DEFAULT 60,
    reboot_reason TEXT NOT NULL DEFAULT '',
    timezone_name TEXT NOT NULL DEFAULT '',
    utc_offset_seconds INTEGER,
    time_quality TEXT NOT NULL DEFAULT 'LOCAL_FALLBACK',
    clock_jump_seconds REAL,
    version_evidence_path TEXT NOT NULL DEFAULT '',
    config_status TEXT NOT NULL DEFAULT 'NOT_CHECKED',
    config_checked_at TEXT NOT NULL DEFAULT '',
    config_applied_at TEXT NOT NULL DEFAULT '',
    first_syslog_received_at TEXT NOT NULL DEFAULT '',
    last_syslog_received_at TEXT NOT NULL DEFAULT '',
    config_fingerprint TEXT NOT NULL DEFAULT '',
    info_center_metrics_json TEXT NOT NULL DEFAULT '{}',
    expected_change_operation_id TEXT NOT NULL DEFAULT '',
    expected_change_started_at TEXT NOT NULL DEFAULT '',
    expected_change_until TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ground_boot_device
ON ground_unattended_boot_sessions(site_id, device_uuid, last_checked_at DESC);

CREATE TABLE IF NOT EXISTS ground_unattended_syslog_config_audits (
    audit_id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL,
    boot_session_id TEXT NOT NULL DEFAULT '',
    device_uuid TEXT NOT NULL,
    train_id TEXT NOT NULL DEFAULT '',
    mr_role TEXT NOT NULL DEFAULT '',
    checked_at TEXT NOT NULL,
    target_ip TEXT NOT NULL DEFAULT '',
    target_port INTEGER,
    status TEXT NOT NULL,
    missing_commands_json TEXT NOT NULL DEFAULT '[]',
    applied_commands_json TEXT NOT NULL DEFAULT '[]',
    evidence_path TEXT NOT NULL DEFAULT '',
    evidence_sha256 TEXT NOT NULL DEFAULT '',
    error_code TEXT NOT NULL DEFAULT '',
    error_message TEXT NOT NULL DEFAULT '',
    managed_profile_version INTEGER NOT NULL DEFAULT 2,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ground_config_audit_device
ON ground_unattended_syslog_config_audits(site_id, device_uuid, checked_at DESC);

CREATE TABLE IF NOT EXISTS ground_unattended_wmesh_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id TEXT NOT NULL,
    run_id TEXT NOT NULL DEFAULT '',
    device_uuid TEXT NOT NULL DEFAULT '',
    device_id INTEGER,
    train_id TEXT NOT NULL DEFAULT '',
    mr_role TEXT NOT NULL DEFAULT '',
    event_type TEXT NOT NULL,
    device_time TEXT NOT NULL DEFAULT '',
    receive_time TEXT NOT NULL,
    source_ip TEXT NOT NULL DEFAULT '',
    hostname TEXT NOT NULL DEFAULT '',
    peer_name TEXT NOT NULL DEFAULT '',
    peer_mac TEXT NOT NULL DEFAULT '',
    previous_peer_name TEXT NOT NULL DEFAULT '',
    previous_peer_mac TEXT NOT NULL DEFAULT '',
    station TEXT NOT NULL DEFAULT '',
    section TEXT NOT NULL DEFAULT '',
    data_quality TEXT NOT NULL DEFAULT 'COMPLETE',
    receive_delay_ms REAL,
    clock_offset_ms REAL,
    raw_file_id TEXT NOT NULL DEFAULT '',
    raw_line_number INTEGER,
    event_family TEXT NOT NULL DEFAULT '',
    event_time TEXT NOT NULL DEFAULT '',
    event_time_source TEXT NOT NULL DEFAULT 'RECEIVE_TIME',
    dedup_key TEXT NOT NULL DEFAULT '',
    duplicate_count INTEGER NOT NULL DEFAULT 0,
    interface_name TEXT NOT NULL DEFAULT '',
    interface_type TEXT NOT NULL DEFAULT '',
    physical_state TEXT NOT NULL DEFAULT '',
    cfg_event_index TEXT NOT NULL DEFAULT '',
    cfg_command_source TEXT NOT NULL DEFAULT '',
    cfg_source TEXT NOT NULL DEFAULT '',
    cfg_destination TEXT NOT NULL DEFAULT '',
    expected_internal_change INTEGER NOT NULL DEFAULT 0,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ground_wmesh_timeline
ON ground_unattended_wmesh_events(site_id, run_id, receive_time DESC, train_id);

CREATE TABLE IF NOT EXISTS ground_unattended_radio_interface_states (
    site_id TEXT NOT NULL,
    device_uuid TEXT NOT NULL,
    train_id TEXT NOT NULL DEFAULT '',
    mr_role TEXT NOT NULL DEFAULT '',
    interface_name TEXT NOT NULL,
    current_state TEXT NOT NULL DEFAULT 'UNKNOWN',
    stable_state TEXT NOT NULL DEFAULT 'UNKNOWN',
    previous_state TEXT NOT NULL DEFAULT 'UNKNOWN',
    last_changed_at TEXT NOT NULL DEFAULT '',
    down_since TEXT NOT NULL DEFAULT '',
    last_up_at TEXT NOT NULL DEFAULT '',
    last_down_at TEXT NOT NULL DEFAULT '',
    latest_outage_duration_ms INTEGER,
    transition_count_5m INTEGER NOT NULL DEFAULT 0,
    snmp_related_transition_count_5m INTEGER NOT NULL DEFAULT 0,
    transition_times_json TEXT NOT NULL DEFAULT '[]',
    snmp_transition_times_json TEXT NOT NULL DEFAULT '[]',
    snmp_transition_event_ids_json TEXT NOT NULL DEFAULT '[]',
    last_cfg_event_index TEXT NOT NULL DEFAULT '',
    last_command_source TEXT NOT NULL DEFAULT '',
    correlation_confidence TEXT NOT NULL DEFAULT 'UNCONFIRMED',
    last_event_id INTEGER,
    last_down_event_id INTEGER,
    last_up_event_id INTEGER,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (site_id, device_uuid, interface_name)
);
CREATE INDEX IF NOT EXISTS idx_ground_radio_state_query
ON ground_unattended_radio_interface_states(site_id, current_state, updated_at DESC);

CREATE TABLE IF NOT EXISTS ground_unattended_mr_runtime_states (
    site_id TEXT NOT NULL,
    device_uuid TEXT NOT NULL,
    train_id TEXT NOT NULL DEFAULT '',
    mr_role TEXT NOT NULL DEFAULT '',
    radio_overall_state TEXT NOT NULL DEFAULT 'UNKNOWN',
    snmp_radio_control_state TEXT NOT NULL DEFAULT 'NONE',
    last_radio_event_at TEXT NOT NULL DEFAULT '',
    last_cfg_event_at TEXT NOT NULL DEFAULT '',
    last_cfg_event_index TEXT NOT NULL DEFAULT '',
    last_command_source TEXT NOT NULL DEFAULT '',
    last_config_source TEXT NOT NULL DEFAULT '',
    last_config_destination TEXT NOT NULL DEFAULT '',
    last_cfg_event_id INTEGER,
    last_correlation_confidence TEXT NOT NULL DEFAULT 'UNCONFIRMED',
    last_snmp_control_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (site_id, device_uuid)
);
CREATE INDEX IF NOT EXISTS idx_ground_mr_runtime_query
ON ground_unattended_mr_runtime_states(site_id, radio_overall_state, updated_at DESC);

CREATE TABLE IF NOT EXISTS ground_unattended_radio_correlations (
    correlation_id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL,
    run_id TEXT NOT NULL DEFAULT '',
    device_uuid TEXT NOT NULL,
    train_id TEXT NOT NULL DEFAULT '',
    mr_role TEXT NOT NULL DEFAULT '',
    interface_name TEXT NOT NULL,
    cfg_event_id INTEGER NOT NULL,
    ifnet_event_id INTEGER NOT NULL,
    delta_ms INTEGER NOT NULL,
    confidence TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (site_id, cfg_event_id, ifnet_event_id)
);
CREATE INDEX IF NOT EXISTS idx_ground_radio_correlations_device
ON ground_unattended_radio_correlations(site_id, device_uuid, created_at DESC);

CREATE TABLE IF NOT EXISTS ground_unattended_ping_loss_intervals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    target_ip TEXT NOT NULL,
    train_id TEXT NOT NULL DEFAULT '',
    mr_id TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL,
    ended_at TEXT NOT NULL DEFAULT '',
    loss_count INTEGER NOT NULL DEFAULT 0,
    duration_seconds REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ground_unattended_raw_files (
    file_id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL,
    run_id TEXT NOT NULL DEFAULT '',
    train_id TEXT NOT NULL DEFAULT '',
    device_id INTEGER,
    device_uuid TEXT NOT NULL DEFAULT '',
    mr_role TEXT NOT NULL DEFAULT '',
    data_type TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    start_time TEXT NOT NULL DEFAULT '',
    end_time TEXT NOT NULL DEFAULT '',
    record_count INTEGER NOT NULL DEFAULT 0,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    sha256 TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'OPEN',
    archive_status TEXT NOT NULL DEFAULT 'PENDING',
    parse_status TEXT NOT NULL DEFAULT 'PENDING',
    compressed_path TEXT NOT NULL DEFAULT '',
    revision INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (site_id, relative_path)
);
CREATE INDEX IF NOT EXISTS idx_ground_raw_files_query
ON ground_unattended_raw_files(site_id, data_type, start_time DESC, status);
CREATE INDEX IF NOT EXISTS idx_ground_raw_files_run_query
ON ground_unattended_raw_files(
    site_id, run_id, data_type, train_id, device_uuid, mr_role, start_time, end_time
);

CREATE TABLE IF NOT EXISTS ground_unattended_delete_operations (
    operation_id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    mode TEXT NOT NULL,
    filters_json TEXT NOT NULL DEFAULT '{}',
    selected_count INTEGER NOT NULL DEFAULT 0,
    matched_count INTEGER NOT NULL DEFAULT 0,
    affected_file_count INTEGER NOT NULL DEFAULT 0,
    deleted_record_count INTEGER NOT NULL DEFAULT 0,
    deleted_event_count INTEGER NOT NULL DEFAULT 0,
    revision_before_json TEXT NOT NULL DEFAULT '{}',
    revision_after_json TEXT NOT NULL DEFAULT '{}',
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'PREVIEWED',
    failure_code TEXT NOT NULL DEFAULT '',
    failure_message TEXT NOT NULL DEFAULT '',
    confirmation_source TEXT NOT NULL DEFAULT '',
    task_id TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ground_delete_operations_run
ON ground_unattended_delete_operations(site_id, run_id, started_at DESC);

CREATE TABLE IF NOT EXISTS ground_unattended_health_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id TEXT NOT NULL,
    run_id TEXT NOT NULL DEFAULT '',
    ts TEXT NOT NULL,
    component TEXT NOT NULL,
    severity TEXT NOT NULL,
    code TEXT NOT NULL,
    message TEXT NOT NULL DEFAULT '',
    details_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_ground_health_events
ON ground_unattended_health_events(site_id, ts DESC, severity);
"""


_PROFILE_MIGRATION_COLUMNS = {
    "deep_collection_master_enabled": "INTEGER NOT NULL DEFAULT 1",
    "fleet_ping_warmup_seconds": "INTEGER NOT NULL DEFAULT 10",
    "ping_depot_trains_enabled": "INTEGER NOT NULL DEFAULT 0",
    "udp_listen_host": "TEXT NOT NULL DEFAULT '0.0.0.0'",
    "udp_listen_port": "INTEGER NOT NULL DEFAULT 514",
    "udp_queue_capacity": "INTEGER NOT NULL DEFAULT 20000",
    "raw_flush_interval_seconds": "REAL NOT NULL DEFAULT 1.0",
    "raw_flush_record_count": "INTEGER NOT NULL DEFAULT 100",
    "event_batch_size": "INTEGER NOT NULL DEFAULT 100",
    "event_batch_interval_seconds": "REAL NOT NULL DEFAULT 1.0",
    "boot_time_tolerance_seconds": "INTEGER NOT NULL DEFAULT 120",
    "config_check_cooldown_seconds": "INTEGER NOT NULL DEFAULT 1800",
    "syslog_server_ip": "TEXT NOT NULL DEFAULT ''",
    "syslog_server_port": "INTEGER NOT NULL DEFAULT 514",
    "syslog_auto_repair_enabled": "INTEGER NOT NULL DEFAULT 1",
    "allow_external_syslog_address": "INTEGER NOT NULL DEFAULT 0",
    "ping_raw_retention_days": "INTEGER NOT NULL DEFAULT 30",
    "syslog_raw_retention_days": "INTEGER NOT NULL DEFAULT 30",
}

_PING_SUMMARY_MIGRATION_COLUMNS = {
    "raw_sample_count": "INTEGER NOT NULL DEFAULT 0",
    "warmup_ignored_count": "INTEGER NOT NULL DEFAULT 0",
}

_TRAIN_RUN_MIGRATION_COLUMNS = {
    "location_class": "TEXT NOT NULL DEFAULT 'UNKNOWN'",
    "mainline_eligible": "INTEGER NOT NULL DEFAULT 0",
    "ping_inclusion_reason": "TEXT NOT NULL DEFAULT ''",
    "ping_exclusion_reason": "TEXT NOT NULL DEFAULT ''",
    "deep_exclusion_reason": "TEXT NOT NULL DEFAULT ''",
    "location_match_level": "TEXT NOT NULL DEFAULT 'UNMATCHED'",
    "location_match_reason": "TEXT NOT NULL DEFAULT ''",
    "resolved_ap_id": "TEXT NOT NULL DEFAULT ''",
    "resolved_ap_name": "TEXT NOT NULL DEFAULT ''",
    "raw_peer_ap_name": "TEXT NOT NULL DEFAULT ''",
    "raw_peer_ap_mac": "TEXT NOT NULL DEFAULT ''",
    "canonical_station_name": "TEXT NOT NULL DEFAULT ''",
}

_ENDPOINT_MIGRATION_COLUMNS = {
    "last_syslog_source_ip": "TEXT NOT NULL DEFAULT ''",
    "syslog_hostname": "TEXT NOT NULL DEFAULT ''",
    "last_syslog_identity_verified_at": "TEXT NOT NULL DEFAULT ''",
}

_BOOT_SESSION_MIGRATION_COLUMNS = {
    "device_clock_before": "TEXT NOT NULL DEFAULT ''",
    "device_clock_after": "TEXT NOT NULL DEFAULT ''",
    "boot_time_uncertainty_seconds": "INTEGER NOT NULL DEFAULT 60",
    "reboot_reason": "TEXT NOT NULL DEFAULT ''",
    "timezone_name": "TEXT NOT NULL DEFAULT ''",
    "utc_offset_seconds": "INTEGER",
    "time_quality": "TEXT NOT NULL DEFAULT 'LOCAL_FALLBACK'",
    "clock_jump_seconds": "REAL",
    "info_center_metrics_json": "TEXT NOT NULL DEFAULT '{}'",
    "expected_change_operation_id": "TEXT NOT NULL DEFAULT ''",
    "expected_change_started_at": "TEXT NOT NULL DEFAULT ''",
    "expected_change_until": "TEXT NOT NULL DEFAULT ''",
}

_WMESH_EVENT_MIGRATION_COLUMNS = {
    "clock_offset_ms": "REAL",
    "event_family": "TEXT NOT NULL DEFAULT ''",
    "event_time": "TEXT NOT NULL DEFAULT ''",
    "event_time_source": "TEXT NOT NULL DEFAULT 'RECEIVE_TIME'",
    "dedup_key": "TEXT NOT NULL DEFAULT ''",
    "duplicate_count": "INTEGER NOT NULL DEFAULT 0",
    "interface_name": "TEXT NOT NULL DEFAULT ''",
    "interface_type": "TEXT NOT NULL DEFAULT ''",
    "physical_state": "TEXT NOT NULL DEFAULT ''",
    "cfg_event_index": "TEXT NOT NULL DEFAULT ''",
    "cfg_command_source": "TEXT NOT NULL DEFAULT ''",
    "cfg_source": "TEXT NOT NULL DEFAULT ''",
    "cfg_destination": "TEXT NOT NULL DEFAULT ''",
    "expected_internal_change": "INTEGER NOT NULL DEFAULT 0",
}

_EVENT_MIGRATION_COLUMNS = {
    "dedup_key": "TEXT NOT NULL DEFAULT ''",
}

_CONFIG_AUDIT_MIGRATION_COLUMNS = {
    "managed_profile_version": "INTEGER NOT NULL DEFAULT 2",
}

_RAW_FILE_MIGRATION_COLUMNS = {
    "revision": "INTEGER NOT NULL DEFAULT 0",
}


_RUN_STATES_ACTIVE = {
    "STARTING",
    "RUNNING",
    "PAUSED",
    "STOPPING",
    "FINALIZING",
    "ARCHIVING",
    "ERROR",
}


class GroundUnattendedRepository:
    def __init__(self, db_path: Path, *, site_id: str) -> None:
        self.db_path = Path(db_path)
        self.site_id = str(site_id)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def initialize(self) -> None:
        with self._connection() as conn:
            conn.executescript(SCHEMA)
            self._ensure_columns(conn, "ground_unattended_profiles", _PROFILE_MIGRATION_COLUMNS)
            self._ensure_columns(
                conn,
                "ground_unattended_ping_summaries",
                _PING_SUMMARY_MIGRATION_COLUMNS,
            )
            self._ensure_columns(
                conn, "ground_unattended_train_runs", _TRAIN_RUN_MIGRATION_COLUMNS
            )
            self._migrate_train_run_location_decisions(conn)
            self._ensure_columns(conn, "ground_unattended_train_endpoints", _ENDPOINT_MIGRATION_COLUMNS)
            self._ensure_columns(conn, "ground_unattended_boot_sessions", _BOOT_SESSION_MIGRATION_COLUMNS)
            self._ensure_columns(conn, "ground_unattended_wmesh_events", _WMESH_EVENT_MIGRATION_COLUMNS)
            self._ensure_columns(
                conn,
                "ground_unattended_raw_files",
                _RAW_FILE_MIGRATION_COLUMNS,
            )
            self._ensure_columns(conn, "ground_unattended_events", _EVENT_MIGRATION_COLUMNS)
            self._ensure_columns(
                conn,
                "ground_unattended_syslog_config_audits",
                _CONFIG_AUDIT_MIGRATION_COLUMNS,
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_ground_syslog_control_events
                ON ground_unattended_wmesh_events(
                    site_id, device_uuid, event_family, event_time DESC
                )
                """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_ground_syslog_event_dedup
                ON ground_unattended_wmesh_events(site_id, dedup_key)
                WHERE dedup_key <> ''
                """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_ground_events_dedup
                ON ground_unattended_events(site_id, dedup_key)
                WHERE dedup_key <> ''
                """
            )
            conn.execute(
                """
                INSERT INTO ground_unattended_schema(key, value, updated_at)
                VALUES('schema_version', '9', ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """,
                (_now(),),
            )
            conn.execute(
                """
                UPDATE ground_unattended_profiles
                SET timezone='Asia/Shanghai', updated_at=?
                WHERE TRIM(timezone)='' OR LOWER(TRIM(timezone))='system'
                """,
                (_now(),),
            )

    @staticmethod
    def _ensure_columns(
        conn: sqlite3.Connection, table: str, columns: dict[str, str]
    ) -> None:
        existing = {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}
        for name, declaration in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")

    @staticmethod
    def _migrate_train_run_location_decisions(
        conn: sqlite3.Connection,
    ) -> None:
        conn.execute(
            """
            UPDATE ground_unattended_train_runs
            SET location_class = CASE eligibility_status
                    WHEN 'MAINLINE' THEN 'MAINLINE'
                    WHEN 'MAINLINE_STATIONARY' THEN 'MAINLINE'
                    WHEN 'DEPOT' THEN 'DEPOT'
                    WHEN 'PARKING_LOT' THEN 'PARKING_YARD'
                    WHEN 'STORAGE_TRACK' THEN 'STABLING'
                    WHEN 'DEPOT_CONNECTION' THEN 'DEPOT_CONNECTION'
                    WHEN 'NON_MAIN_PATH' THEN 'NON_MAINLINE'
                    WHEN 'OFFLINE' THEN 'OFFLINE'
                    ELSE location_class
                END,
                mainline_eligible = CASE
                    WHEN eligibility_status IN (
                        'MAINLINE',
                        'MAINLINE_STATIONARY'
                    ) THEN 1
                    ELSE mainline_eligible
                END
            WHERE location_class = 'UNKNOWN'
              AND eligibility_status IN (
                    'MAINLINE',
                    'MAINLINE_STATIONARY',
                    'DEPOT',
                    'PARKING_LOT',
                    'STORAGE_TRACK',
                    'DEPOT_CONNECTION',
                    'NON_MAIN_PATH',
                    'OFFLINE'
              )
            """
        )

    def get_profile(self) -> GroundUnattendedProfileDTO:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM ground_unattended_profiles WHERE site_id=?",
                (self.site_id,),
            ).fetchone()
        if row is None:
            profile = GroundUnattendedProfileDTO(site_id=self.site_id)
            payload = profile.model_dump(mode="json")
            fields = tuple(payload)
            values = [
                int(value) if isinstance(value, bool) else value
                for value in payload.values()
            ]
            with self._transaction() as conn:
                conn.execute(
                    f"INSERT INTO ground_unattended_profiles ({', '.join(fields)}) "
                    f"VALUES ({', '.join('?' for _ in fields)}) "
                    "ON CONFLICT(site_id) DO NOTHING",
                    values,
                )
                row = conn.execute(
                    "SELECT * FROM ground_unattended_profiles WHERE site_id=?",
                    (self.site_id,),
                ).fetchone()
            if row is None:
                raise RuntimeError("ground unattended profile was not created")
        return GroundUnattendedProfileDTO.model_validate(dict(row))

    def save_profile(
        self, profile: GroundUnattendedProfileDTO
    ) -> GroundUnattendedProfileDTO:
        if profile.site_id != self.site_id:
            raise ValueError("profile site_id mismatch")
        now = _now()
        payload = profile.model_copy(
            update={"created_at": profile.created_at or now, "updated_at": now}
        ).model_dump(mode="json")
        fields = tuple(payload)
        values = [
            int(value) if isinstance(value, bool) else value
            for value in payload.values()
        ]
        updates = ", ".join(
            f"{field}=excluded.{field}"
            for field in fields
            if field not in {"site_id", "created_at"}
        )
        with self._transaction() as conn:
            conn.execute(
                f"INSERT INTO ground_unattended_profiles ({', '.join(fields)}) "
                f"VALUES ({', '.join('?' for _ in fields)}) "
                f"ON CONFLICT(site_id) DO UPDATE SET {updates}",
                values,
            )
        return GroundUnattendedProfileDTO.model_validate(payload)

    def list_priority_train_ids(self) -> set[str]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT train_id FROM ground_unattended_priority_trains WHERE site_id=? AND priority=1 "
                "UNION SELECT train_id FROM ground_unattended_train_policies WHERE site_id=? AND priority=1",
                (self.site_id, self.site_id),
            ).fetchall()
        return {str(row[0]) for row in rows}

    def set_priority(self, train_id: str, priority: bool) -> None:
        now = _now()
        with self._transaction() as conn:
            if priority:
                conn.execute(
                    """
                    INSERT INTO ground_unattended_priority_trains(site_id, train_id, priority, updated_at)
                    VALUES(?, ?, 1, ?)
                    ON CONFLICT(site_id, train_id) DO UPDATE SET priority=1, updated_at=excluded.updated_at
                    """,
                    (self.site_id, train_id, now),
                )
            else:
                conn.execute(
                    "DELETE FROM ground_unattended_priority_trains WHERE site_id=? AND train_id=?",
                    (self.site_id, train_id),
                )
            conn.execute(
                """
                INSERT INTO ground_unattended_train_policies(
                    site_id, train_id, priority, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(site_id, train_id) DO UPDATE SET
                    priority=excluded.priority, updated_at=excluded.updated_at
                """,
                (self.site_id, train_id, int(priority), now, now),
            )

    def sync_inventory(
        self,
        *,
        trains: list[dict[str, Any]],
        endpoints: list[dict[str, Any]],
    ) -> dict[str, int]:
        """增量保存设备绑定快照；设备凭据和设备主体始终不进入本库。"""

        now = _now()
        active_train_ids = {str(row["train_id"]) for row in trains}
        active_device_ids = {str(row["device_uuid"]) for row in endpoints}
        with self._transaction() as conn:
            previous_endpoints = {
                str(row["device_uuid"]): dict(row)
                for row in conn.execute(
                    "SELECT * FROM ground_unattended_train_endpoints WHERE site_id=?",
                    (self.site_id,),
                ).fetchall()
            }
            previous_trains = {
                str(row["train_id"]): dict(row)
                for row in conn.execute(
                    "SELECT * FROM ground_unattended_train_inventory WHERE site_id=?",
                    (self.site_id,),
                ).fetchall()
            }
            conn.execute(
                "UPDATE ground_unattended_train_endpoints SET binding_status='REMOVED', "
                "removed_at=?, updated_at=? WHERE site_id=? AND binding_status='ACTIVE'",
                (now, now, self.site_id),
            )
            for train in trains:
                train_id = str(train["train_id"])
                conn.execute(
                    """
                    INSERT INTO ground_unattended_train_inventory(
                        site_id, train_id, train_no, train_name, inventory_status,
                        first_seen_at, last_seen_at, removed_at, updated_at
                    ) VALUES(?, ?, ?, ?, 'ACTIVE', ?, ?, '', ?)
                    ON CONFLICT(site_id, train_id) DO UPDATE SET
                        train_no=excluded.train_no,
                        train_name=excluded.train_name,
                        inventory_status='ACTIVE',
                        last_seen_at=excluded.last_seen_at,
                        removed_at='',
                        updated_at=excluded.updated_at
                    """,
                    (
                        self.site_id,
                        train_id,
                        str(train.get("train_no") or ""),
                        str(train.get("train_name") or train_id),
                        now,
                        now,
                        now,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO ground_unattended_train_policies(
                        site_id, train_id, created_at, updated_at
                    ) VALUES(?, ?, ?, ?)
                    ON CONFLICT(site_id, train_id) DO NOTHING
                    """,
                    (self.site_id, train_id, now, now),
                )
            for endpoint in endpoints:
                conn.execute(
                    """
                    INSERT INTO ground_unattended_train_endpoints(
                        site_id, device_uuid, device_id, train_id, mr_role,
                        device_name, management_ip, protocol, port, source_hostname,
                        binding_status, first_seen_at, last_seen_at, removed_at, updated_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?, '', ?)
                    ON CONFLICT(site_id, device_uuid) DO UPDATE SET
                        device_id=excluded.device_id,
                        train_id=excluded.train_id,
                        mr_role=excluded.mr_role,
                        device_name=excluded.device_name,
                        management_ip=excluded.management_ip,
                        protocol=excluded.protocol,
                        port=excluded.port,
                        source_hostname=excluded.source_hostname,
                        binding_status='ACTIVE',
                        last_seen_at=excluded.last_seen_at,
                        removed_at='',
                        updated_at=excluded.updated_at
                    """,
                    (
                        self.site_id,
                        str(endpoint["device_uuid"]),
                        endpoint.get("device_id"),
                        str(endpoint["train_id"]),
                        str(endpoint["mr_role"]),
                        str(endpoint.get("device_name") or ""),
                        str(endpoint.get("management_ip") or ""),
                        str(endpoint.get("protocol") or ""),
                        endpoint.get("port"),
                        str(endpoint.get("source_hostname") or ""),
                        now,
                        now,
                        now,
                    ),
                )
            if active_train_ids:
                placeholders = ",".join("?" for _ in active_train_ids)
                conn.execute(
                    f"UPDATE ground_unattended_train_inventory SET inventory_status='REMOVED', "
                    f"removed_at=?, updated_at=? WHERE site_id=? AND train_id NOT IN ({placeholders}) "
                    "AND inventory_status='ACTIVE'",
                    (now, now, self.site_id, *sorted(active_train_ids)),
                )
            else:
                conn.execute(
                    "UPDATE ground_unattended_train_inventory SET inventory_status='REMOVED', "
                    "removed_at=?, updated_at=? WHERE site_id=? AND inventory_status='ACTIVE'",
                    (now, now, self.site_id),
                )
            added = sum(key not in previous_endpoints for key in active_device_ids)
            updated = sum(
                key in previous_endpoints
                and any(
                    str(previous_endpoints[key].get(field) or "")
                    != str(next(row for row in endpoints if str(row["device_uuid"]) == key).get(field) or "")
                    for field in ("train_id", "mr_role", "management_ip", "device_name")
                )
                for key in active_device_ids
            )
            removed = sum(
                key not in active_device_ids and row.get("binding_status") == "ACTIVE"
                for key, row in previous_endpoints.items()
            )
            removed_trains = sum(
                key not in active_train_ids and row.get("inventory_status") == "ACTIVE"
                for key, row in previous_trains.items()
            )
        return {
            "added_endpoint_count": added,
            "updated_endpoint_count": updated,
            "removed_endpoint_count": removed,
            "removed_train_count": removed_trains,
        }

    def list_inventory(self, *, include_removed: bool = True) -> list[dict[str, Any]]:
        where = "" if include_removed else "AND i.inventory_status='ACTIVE'"
        with self._connection() as conn:
            trains = conn.execute(
                f"""
                SELECT i.*, p.enabled, p.priority, p.scheduling_priority,
                       p.deep_collection_enabled, p.monitor_only, p.remark
                FROM ground_unattended_train_inventory i
                LEFT JOIN ground_unattended_train_policies p
                  ON p.site_id=i.site_id AND p.train_id=i.train_id
                WHERE i.site_id=? {where}
                ORDER BY COALESCE(p.priority, 0) DESC,
                         COALESCE(p.scheduling_priority, 0) DESC,
                         i.train_no, i.train_id
                """,
                (self.site_id,),
            ).fetchall()
            endpoints = conn.execute(
                "SELECT * FROM ground_unattended_train_endpoints WHERE site_id=? "
                "ORDER BY train_id, mr_role",
                (self.site_id,),
            ).fetchall()
        by_train: dict[str, list[dict[str, Any]]] = {}
        for row in endpoints:
            by_train.setdefault(str(row["train_id"]), []).append(_decode_row(row))
        result = []
        for row in trains:
            item = _decode_row(row)
            item["endpoints"] = by_train.get(str(item["train_id"]), [])
            result.append(item)
        return result

    def get_inventory_endpoint(self, device_uuid: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM ground_unattended_train_endpoints "
                "WHERE site_id=? AND device_uuid=?",
                (self.site_id, device_uuid),
            ).fetchone()
        return _decode_row(row) if row else None

    def save_train_policy(self, train_id: str, values: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "enabled",
            "priority",
            "scheduling_priority",
            "deep_collection_enabled",
            "monitor_only",
            "remark",
        }
        payload = {key: values[key] for key in allowed if key in values}
        now = _now()
        defaults = {
            "enabled": True,
            "priority": False,
            "scheduling_priority": 0,
            "deep_collection_enabled": True,
            "monitor_only": False,
            "remark": "",
        }
        current = self.get_train_policy(train_id) or defaults
        current.update(payload)
        with self._transaction() as conn:
            conn.execute(
                """
                INSERT INTO ground_unattended_train_policies(
                    site_id, train_id, enabled, priority, scheduling_priority,
                    deep_collection_enabled, monitor_only, remark, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(site_id, train_id) DO UPDATE SET
                    enabled=excluded.enabled,
                    priority=excluded.priority,
                    scheduling_priority=excluded.scheduling_priority,
                    deep_collection_enabled=excluded.deep_collection_enabled,
                    monitor_only=excluded.monitor_only,
                    remark=excluded.remark,
                    updated_at=excluded.updated_at
                """,
                (
                    self.site_id,
                    train_id,
                    int(bool(current["enabled"])),
                    int(bool(current["priority"])),
                    int(current["scheduling_priority"]),
                    int(bool(current["deep_collection_enabled"])),
                    int(bool(current["monitor_only"])),
                    str(current["remark"]),
                    now,
                    now,
                ),
            )
        return self.get_train_policy(train_id) or {}

    def get_train_policy(self, train_id: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM ground_unattended_train_policies WHERE site_id=? AND train_id=?",
                (self.site_id, train_id),
            ).fetchone()
        return _decode_row(row) if row else None

    def create_or_get_run(
        self,
        *,
        run_id: str,
        run_date: str,
        scheduled_start_at: str,
        scheduled_end_at: str,
        state: str = "STARTING",
    ) -> dict[str, Any]:
        now = _now()
        with self._transaction() as conn:
            conn.execute(
                """
                INSERT INTO ground_unattended_runs(
                    run_id, site_id, run_date, state, scheduled_start_at, scheduled_end_at,
                    actual_started_at, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(site_id, run_date) DO NOTHING
                """,
                (
                    run_id,
                    self.site_id,
                    run_date,
                    state,
                    scheduled_start_at,
                    scheduled_end_at,
                    now,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM ground_unattended_runs WHERE site_id=? AND run_date=?",
                (self.site_id, run_date),
            ).fetchone()
        if row is None:
            raise RuntimeError("ground unattended run was not created")
        return _decode_row(row)

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM ground_unattended_runs WHERE site_id=? AND run_id=?",
                (self.site_id, run_id),
            ).fetchone()
        return _decode_row(row) if row else None

    def get_active_run(self) -> dict[str, Any] | None:
        placeholders = ",".join("?" for _ in _RUN_STATES_ACTIVE)
        with self._connection() as conn:
            row = conn.execute(
                f"SELECT * FROM ground_unattended_runs WHERE site_id=? AND UPPER(state) IN ({placeholders}) "
                "ORDER BY updated_at DESC LIMIT 1",
                (self.site_id, *sorted(_RUN_STATES_ACTIVE)),
            ).fetchone()
        return _decode_row(row) if row else None

    def latest_run(self) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM ground_unattended_runs WHERE site_id=? ORDER BY run_date DESC, updated_at DESC LIMIT 1",
                (self.site_id,),
            ).fetchone()
        return _decode_row(row) if row else None

    def list_runs(self, *, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT r.*, a.archive_id, a.archive_status, a.relative_path AS archive_relative_path
                FROM ground_unattended_runs r
                LEFT JOIN ground_unattended_archives a
                  ON a.site_id=r.site_id AND a.run_id=r.run_id
                WHERE r.site_id=?
                ORDER BY r.run_date DESC, r.updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (
                    self.site_id,
                    max(1, min(int(limit), 500)),
                    max(0, int(offset)),
                ),
            ).fetchall()
        return [_decode_row(row) for row in rows]

    def count_runs(self) -> int:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM ground_unattended_runs WHERE site_id=?",
                (self.site_id,),
            ).fetchone()
        return int(row[0] if row else 0)

    def update_run(self, run_id: str, **values: Any) -> None:
        allowed = {
            "state",
            "paused",
            "requested_action",
            "scheduled_start_at",
            "scheduled_end_at",
            "actual_started_at",
            "actual_ended_at",
            "ac_last_updated_at",
            "ac_freshness_status",
            "ping_sample_count",
            "summary_json",
            "error_code",
            "error_message",
        }
        payload = {key: value for key, value in values.items() if key in allowed}
        if not payload:
            return
        payload["updated_at"] = _now()
        params = [
            json.dumps(value, ensure_ascii=False)
            if key == "summary_json" and not isinstance(value, str)
            else int(value)
            if isinstance(value, bool)
            else value
            for key, value in payload.items()
        ]
        with self._transaction() as conn:
            conn.execute(
                f"UPDATE ground_unattended_runs SET {', '.join(f'{key}=?' for key in payload)} "
                "WHERE site_id=? AND run_id=?",
                (*params, self.site_id, run_id),
            )

    def upsert_train_state(
        self,
        run_id: str,
        run_date: str,
        values: dict[str, Any],
        *,
        ap_identity: str,
        same_ap_since: str,
    ) -> None:
        now = _now()
        priority = values.get("priority", False)
        endpoints = values.get("endpoints", [])
        row = {
            "site_id": self.site_id,
            "run_id": run_id,
            "run_date": run_date,
            "train_id": values["train_id"],
            "train_no": values.get("train_no", ""),
            "train_name": values.get("train_name", ""),
            "location_class": values.get("location_class", "UNKNOWN"),
            "mainline_eligible": int(bool(values.get("mainline_eligible"))),
            "coverage_status": values.get("coverage_status", "NOT_SEEN"),
            "priority": int(bool(priority)),
            "ping_eligible": int(bool(values.get("ping_eligible"))),
            "deep_collection_eligible": int(
                bool(values.get("deep_collection_eligible"))
            ),
            "ping_inclusion_reason": values.get("ping_inclusion_reason", ""),
            "ping_exclusion_reason": values.get("ping_exclusion_reason", ""),
            "deep_exclusion_reason": values.get("deep_exclusion_reason", ""),
            "eligibility_status": values.get("eligibility_status", "AC_UNKNOWN"),
            "exclusion_reason": values.get("exclusion_reason", ""),
            "location_match_level": values.get(
                "location_match_level", "UNMATCHED"
            ),
            "location_match_reason": values.get("location_match_reason", ""),
            "resolved_ap_id": values.get("resolved_ap_id", ""),
            "resolved_ap_name": values.get("resolved_ap_name", ""),
            "raw_peer_ap_name": values.get("raw_peer_ap_name", ""),
            "raw_peer_ap_mac": values.get("raw_peer_ap_mac", ""),
            "canonical_station_name": values.get("canonical_station_name", ""),
            "current_ap_identity": ap_identity,
            "current_ap_name": values.get("current_ap_name", ""),
            "current_ap_mac": values.get("current_ap_mac", ""),
            "station": values.get("station", ""),
            "section": values.get("section", ""),
            "mileage": values.get("mileage", ""),
            "rssi": values.get("rssi"),
            "same_ap_since": same_ap_since,
            "same_ap_duration_seconds": values.get("same_ap_duration_seconds", 0),
            "ac_snapshot_id": values.get("ac_snapshot_id"),
            "ac_received_at": values.get("ac_received_at", ""),
            "endpoints_json": json.dumps(endpoints, ensure_ascii=False),
            "created_at": now,
            "updated_at": now,
        }
        fields = tuple(row)
        updates = ", ".join(
            f"{field}=excluded.{field}"
            for field in fields
            if field not in {"site_id", "run_id", "train_id", "run_date", "created_at"}
        )
        with self._transaction() as conn:
            conn.execute(
                f"INSERT INTO ground_unattended_train_runs ({', '.join(fields)}) "
                f"VALUES ({', '.join('?' for _ in fields)}) "
                f"ON CONFLICT(site_id, run_id, train_id) DO UPDATE SET {updates}",
                tuple(row.values()),
            )

    def list_train_runs(self, run_id: str) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM ground_unattended_train_runs WHERE site_id=? AND run_id=? "
                "ORDER BY priority DESC, train_no, train_id",
                (self.site_id, run_id),
            ).fetchall()
        return [_decode_row(row) for row in rows]

    def get_train_run(self, run_id: str, train_id: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM ground_unattended_train_runs WHERE site_id=? AND run_id=? AND train_id=?",
                (self.site_id, run_id, train_id),
            ).fetchone()
        return _decode_row(row) if row else None

    def update_train_run(self, run_id: str, train_id: str, **values: Any) -> None:
        allowed = {
            "coverage_status",
            "priority",
            "attempt_count",
            "covered_rounds",
            "selection_reason",
            "failure_reason",
            "collection_started_at",
            "valid_duration_minutes",
            "operations_json",
            "sessions_json",
        }
        payload = {key: value for key, value in values.items() if key in allowed}
        if not payload:
            return
        payload["updated_at"] = _now()
        params = []
        for key, value in payload.items():
            if key in {"operations_json", "sessions_json"} and not isinstance(
                value, str
            ):
                value = json.dumps(value, ensure_ascii=False)
            elif isinstance(value, bool):
                value = int(value)
            params.append(value)
        with self._transaction() as conn:
            conn.execute(
                f"UPDATE ground_unattended_train_runs SET {', '.join(f'{key}=?' for key in payload)} "
                "WHERE site_id=? AND run_id=? AND train_id=?",
                (*params, self.site_id, run_id, train_id),
            )

    def save_daily_queue(
        self,
        *,
        run_id: str,
        run_date: str,
        random_seed: int,
        candidate_train_ids: list[str],
        queue_order: list[str],
    ) -> None:
        with self._transaction() as conn:
            conn.execute(
                """
                INSERT INTO ground_unattended_daily_queues(
                    site_id, run_id, run_date, random_seed, generated_at,
                    candidate_train_ids_json, queue_order_json
                ) VALUES(?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(site_id, run_id) DO UPDATE SET
                    generated_at=excluded.generated_at,
                    candidate_train_ids_json=excluded.candidate_train_ids_json,
                    queue_order_json=excluded.queue_order_json
                """,
                (
                    self.site_id,
                    run_id,
                    run_date,
                    int(random_seed),
                    _now(),
                    json.dumps(candidate_train_ids, ensure_ascii=False),
                    json.dumps(queue_order, ensure_ascii=False),
                ),
            )

    def get_daily_queue(self, run_id: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM ground_unattended_daily_queues WHERE site_id=? AND run_id=?",
                (self.site_id, run_id),
            ).fetchone()
        return _decode_row(row) if row else None

    def insert_ac_rows(
        self, rows: Iterable[dict[str, Any]]
    ) -> dict[tuple[str, str], int]:
        ids: dict[tuple[str, str], int] = {}
        with self._transaction() as conn:
            for row in rows:
                fields = tuple(row)
                cursor = conn.execute(
                    f"INSERT INTO ground_unattended_ac_snapshots ({', '.join(fields)}) "
                    f"VALUES ({', '.join('?' for _ in fields)})",
                    tuple(row.values()),
                )
                ids[(str(row.get("train_id") or ""), str(row.get("mr_id") or ""))] = (
                    int(cursor.lastrowid)
                )
        return ids

    def latest_ac_snapshot(
        self, run_id: str, train_id: str = "", mr_id: str = ""
    ) -> dict[str, Any] | None:
        where = ["site_id=?", "run_id=?"]
        params: list[Any] = [self.site_id, run_id]
        if train_id:
            where.append("train_id=?")
            params.append(train_id)
        if mr_id:
            where.append("mr_id=?")
            params.append(mr_id)
        with self._connection() as conn:
            row = conn.execute(
                f"SELECT * FROM ground_unattended_ac_snapshots WHERE {' AND '.join(where)} "
                "ORDER BY received_at DESC, id DESC LIMIT 1",
                params,
            ).fetchone()
        return _decode_row(row) if row else None

    def upsert_ping_segment(self, values: dict[str, Any]) -> None:
        fields = tuple(values)
        updates = ", ".join(
            f"{field}=excluded.{field}"
            for field in fields
            if field not in {"segment_id", "created_at"}
        )
        with self._transaction() as conn:
            conn.execute(
                f"INSERT INTO ground_unattended_ping_segments ({', '.join(fields)}) "
                f"VALUES ({', '.join('?' for _ in fields)}) "
                f"ON CONFLICT(segment_id) DO UPDATE SET {updates}",
                tuple(values.values()),
            )

    def list_open_ping_segments(self, run_id: str) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM ground_unattended_ping_segments WHERE site_id=? AND run_id=? AND status='OPEN'",
                (self.site_id, run_id),
            ).fetchall()
        return [_decode_row(row) for row in rows]

    def ensure_ping_target_activation(
        self, run_id: str, target_ip: str, activated_at: str
    ) -> str:
        now = _now()
        with self._transaction() as conn:
            row = conn.execute(
                """
                SELECT activated_at, active
                FROM ground_unattended_ping_target_activations
                WHERE site_id=? AND run_id=? AND target_ip=?
                """,
                (self.site_id, run_id, target_ip),
            ).fetchone()
            if row is not None and bool(row["active"]):
                return str(row["activated_at"])
            conn.execute(
                """
                INSERT INTO ground_unattended_ping_target_activations(
                    site_id, run_id, target_ip, activated_at, active, removed_at, updated_at
                ) VALUES(?, ?, ?, ?, 1, '', ?)
                ON CONFLICT(site_id, run_id, target_ip) DO UPDATE SET
                    activated_at=excluded.activated_at,
                    active=1,
                    removed_at='',
                    updated_at=excluded.updated_at
                """,
                (self.site_id, run_id, target_ip, activated_at, now),
            )
        return activated_at

    def deactivate_ping_targets(
        self, run_id: str, target_ips: Iterable[str], *, removed_at: str
    ) -> int:
        targets = tuple({str(value) for value in target_ips if str(value)})
        if not targets:
            return 0
        placeholders = ", ".join("?" for _ in targets)
        with self._transaction() as conn:
            cursor = conn.execute(
                "UPDATE ground_unattended_ping_target_activations "
                "SET active=0, removed_at=?, updated_at=? "
                f"WHERE site_id=? AND run_id=? AND target_ip IN ({placeholders}) AND active=1",
                (removed_at, _now(), self.site_id, run_id, *targets),
            )
        return int(cursor.rowcount)

    def upsert_ping_summary(self, values: dict[str, Any]) -> None:
        fields = tuple(values)
        updates = ", ".join(
            f"{field}=excluded.{field}"
            for field in fields
            if field
            not in {
                "id",
                "site_id",
                "run_id",
                "bucket_kind",
                "bucket_start",
                "target_ip",
                "ap_identity",
            }
        )
        with self._transaction() as conn:
            conn.execute(
                f"INSERT INTO ground_unattended_ping_summaries ({', '.join(fields)}) "
                f"VALUES ({', '.join('?' for _ in fields)}) "
                "ON CONFLICT(site_id, run_id, bucket_kind, bucket_start, target_ip, ap_identity) "
                f"DO UPDATE SET {updates}",
                tuple(values.values()),
            )

    def list_ping_summaries(
        self, run_id: str, *, bucket_kind: str | None = "daily"
    ) -> list[dict[str, Any]]:
        where = "WHERE site_id=? AND run_id=?"
        params: list[Any] = [self.site_id, run_id]
        if bucket_kind:
            where += " AND bucket_kind=?"
            params.append(bucket_kind)
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM ground_unattended_ping_summaries "
                f"{where} ORDER BY bucket_start, train_no, mr_position_code",
                params,
            ).fetchall()
        return [_decode_row(row) for row in rows]

    def save_deep_operation(self, values: dict[str, Any]) -> None:
        fields = tuple(values)
        updates = ", ".join(
            f"{field}=excluded.{field}"
            for field in fields
            if field not in {"operation_id", "started_at"}
        )
        with self._transaction() as conn:
            conn.execute(
                f"INSERT INTO ground_unattended_deep_operations ({', '.join(fields)}) "
                f"VALUES ({', '.join('?' for _ in fields)}) "
                f"ON CONFLICT(operation_id) DO UPDATE SET {updates}",
                tuple(values.values()),
            )

    def list_deep_operations(
        self, run_id: str, *, active_only: bool = False
    ) -> list[dict[str, Any]]:
        clause = (
            " AND state NOT IN ('COMPLETED','PARTIAL','FAILED')" if active_only else ""
        )
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM ground_unattended_deep_operations WHERE site_id=? AND run_id=?"
                + clause
                + " ORDER BY started_at",
                (self.site_id, run_id),
            ).fetchall()
        return [_decode_row(row) for row in rows]

    def add_event(
        self,
        *,
        run_id: str = "",
        event_type: str,
        title: str,
        message: str = "",
        severity: str = "info",
        train_id: str = "",
        mr_id: str = "",
        details: dict[str, Any] | None = None,
        ts: str | None = None,
    ) -> int:
        with self._transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO ground_unattended_events(
                    site_id, run_id, ts, event_type, severity, train_id, mr_id,
                    title, message, details_json
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.site_id,
                    run_id,
                    ts or _now(),
                    event_type,
                    severity,
                    train_id,
                    mr_id,
                    title,
                    message,
                    json.dumps(details or {}, ensure_ascii=False),
                ),
            )
            return int(cursor.lastrowid)

    def add_event_once(
        self,
        *,
        dedup_key: str,
        run_id: str = "",
        event_type: str,
        title: str,
        message: str = "",
        severity: str = "info",
        train_id: str = "",
        mr_id: str = "",
        details: dict[str, Any] | None = None,
        ts: str | None = None,
    ) -> tuple[int, bool]:
        key = str(dedup_key or "")
        if not key:
            raise ValueError("timeline event requires dedup_key")
        with self._transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO ground_unattended_events(
                    site_id, run_id, ts, event_type, severity, train_id, mr_id,
                    title, message, details_json, dedup_key
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(site_id, dedup_key) WHERE dedup_key <> '' DO NOTHING
                """,
                (
                    self.site_id,
                    run_id,
                    ts or _now(),
                    event_type,
                    severity,
                    train_id,
                    mr_id,
                    title,
                    message,
                    json.dumps(details or {}, ensure_ascii=False),
                    key,
                ),
            )
            row = conn.execute(
                """
                SELECT id FROM ground_unattended_events
                WHERE site_id=? AND dedup_key=?
                """,
                (self.site_id, key),
            ).fetchone()
        if row is None:
            raise RuntimeError("timeline projection was not saved")
        return int(row["id"]), bool(cursor.rowcount)

    def radio_runtime_statistics(
        self, *, run_id: str = "", day_start: str = ""
    ) -> dict[str, Any]:
        where = ["site_id=?"]
        params: list[Any] = [self.site_id]
        if run_id:
            where.append("run_id=?")
            params.append(run_id)
        if day_start:
            where.append("ts>=?")
            params.append(day_start)
        with self._connection() as conn:
            radio_down = conn.execute(
                """
                SELECT COUNT(DISTINCT device_uuid)
                FROM ground_unattended_radio_interface_states
                WHERE site_id=? AND stable_state='DOWN'
                """,
                (self.site_id,),
            ).fetchone()
            flapping = conn.execute(
                """
                SELECT COUNT(DISTINCT device_uuid)
                FROM ground_unattended_radio_interface_states
                WHERE site_id=? AND current_state='FLAPPING'
                """,
                (self.site_id,),
            ).fetchone()
            counts = {
                str(row["event_type"]): int(row["count"])
                for row in conn.execute(
                    f"""
                    SELECT event_type, COUNT(*) AS count
                    FROM ground_unattended_events
                    WHERE {' AND '.join(where)}
                      AND event_type IN (
                        'radio_interface_bounce'
                      )
                    GROUP BY event_type
                    """,
                    params,
                ).fetchall()
            }
            correlation_where = ["c.site_id=?"]
            correlation_params: list[Any] = [self.site_id]
            if run_id:
                correlation_where.append("c.run_id=?")
                correlation_params.append(run_id)
            if day_start:
                correlation_where.append("cfg.event_time>=?")
                correlation_params.append(day_start)
            snmp_controls = conn.execute(
                f"""
                SELECT COUNT(DISTINCT c.cfg_event_id)
                FROM ground_unattended_radio_correlations AS c
                JOIN ground_unattended_wmesh_events AS cfg
                  ON cfg.id=c.cfg_event_id AND cfg.site_id=c.site_id
                WHERE {' AND '.join(correlation_where)}
                """,
                correlation_params,
            ).fetchone()
            unrecovered = conn.execute(
                """
                SELECT COUNT(*)
                FROM ground_unattended_mr_runtime_states
                WHERE site_id=? AND snmp_radio_control_state='RADIO_DOWN'
                """,
                (self.site_id,),
            ).fetchone()
            latest = conn.execute(
                """
                SELECT MAX(last_snmp_control_at)
                FROM ground_unattended_mr_runtime_states
                WHERE site_id=?
                """,
                (self.site_id,),
            ).fetchone()
        return {
            "radio_down_mr_count": int(radio_down[0] if radio_down else 0),
            "radio_flapping_mr_count": int(flapping[0] if flapping else 0),
            "radio_bounce_today_count": counts.get(
                "radio_interface_bounce", 0
            ),
            "snmp_radio_control_today_count": int(
                snmp_controls[0] if snmp_controls else 0
            ),
            "snmp_unrecovered_count": int(
                unrecovered[0] if unrecovered else 0
            ),
            "last_snmp_radio_control_at": str(
                latest[0] if latest and latest[0] else ""
            ),
        }

    def list_events(
        self,
        run_id: str,
        *,
        train_id: str = "",
        event_type: str = "",
        query: str = "",
        limit: int = 500,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        where = ["site_id=?", "run_id=?"]
        params: list[Any] = [self.site_id, run_id]
        if train_id:
            where.append("train_id=?")
            params.append(train_id)
        if event_type:
            where.append("event_type=?")
            params.append(event_type)
        if query:
            where.append(
                "LOWER(train_id || ' ' || mr_id || ' ' || title || ' ' || "
                "message || ' ' || details_json) LIKE ?"
            )
            params.append(f"%{query.casefold()}%")
        params.extend(
            [max(1, min(int(limit), 500)), max(0, int(offset))]
        )
        with self._connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM ground_unattended_events WHERE {' AND '.join(where)} "
                "ORDER BY ts DESC, id DESC LIMIT ? OFFSET ?",
                params,
            ).fetchall()
        return [_decode_row(row) for row in rows]

    def count_events(
        self,
        run_id: str,
        *,
        train_id: str = "",
        event_type: str = "",
        query: str = "",
    ) -> int:
        where = ["site_id=?", "run_id=?"]
        params: list[Any] = [self.site_id, run_id]
        if train_id:
            where.append("train_id=?")
            params.append(train_id)
        if event_type:
            where.append("event_type=?")
            params.append(event_type)
        if query:
            where.append(
                "LOWER(train_id || ' ' || mr_id || ' ' || title || ' ' || "
                "message || ' ' || details_json) LIKE ?"
            )
            params.append(f"%{query.casefold()}%")
        with self._connection() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) FROM ground_unattended_events WHERE {' AND '.join(where)}",
                params,
            ).fetchone()
        return int(row[0] if row else 0)

    def upsert_archive(self, values: dict[str, Any]) -> None:
        fields = tuple(values)
        updates = ", ".join(
            f"{field}=excluded.{field}"
            for field in fields
            if field not in {"archive_id", "created_at"}
        )
        with self._transaction() as conn:
            conn.execute(
                f"INSERT INTO ground_unattended_archives ({', '.join(fields)}) "
                f"VALUES ({', '.join('?' for _ in fields)}) "
                f"ON CONFLICT(archive_id) DO UPDATE SET {updates}",
                tuple(values.values()),
            )

    def list_archives(self) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT a.*, r.actual_started_at, r.actual_ended_at
                FROM ground_unattended_archives a
                LEFT JOIN ground_unattended_runs r ON r.run_id=a.run_id AND r.site_id=a.site_id
                WHERE a.site_id=? ORDER BY a.run_date DESC
                """,
                (self.site_id,),
            ).fetchall()
        return [_decode_row(row) for row in rows]

    def get_archive(self, archive_id: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT a.*, r.actual_started_at, r.actual_ended_at
                FROM ground_unattended_archives a
                LEFT JOIN ground_unattended_runs r ON r.run_id=a.run_id AND r.site_id=a.site_id
                WHERE a.site_id=? AND a.archive_id=?
                """,
                (self.site_id, archive_id),
            ).fetchone()
        return _decode_row(row) if row else None

    def get_archive_by_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT a.*, r.actual_started_at, r.actual_ended_at
                FROM ground_unattended_archives a
                LEFT JOIN ground_unattended_runs r ON r.run_id=a.run_id AND r.site_id=a.site_id
                WHERE a.site_id=? AND a.run_id=?
                """,
                (self.site_id, run_id),
            ).fetchone()
        return _decode_row(row) if row else None

    def save_operation(self, values: dict[str, Any]) -> dict[str, Any]:
        row = dict(values)
        row.setdefault("site_id", self.site_id)
        row.setdefault("started_at", _now())
        row.setdefault("updated_at", _now())
        if "result_summary_json" not in row:
            row["result_summary_json"] = json.dumps(
                row.pop("result_summary", {}), ensure_ascii=False
            )
        fields = tuple(row)
        updates = ", ".join(
            f"{field}=excluded.{field}"
            for field in fields
            if field not in {"operation_id", "site_id", "started_at"}
        )
        with self._transaction() as conn:
            conn.execute(
                f"INSERT INTO ground_unattended_operations ({', '.join(fields)}) "
                f"VALUES ({', '.join('?' for _ in fields)}) "
                f"ON CONFLICT(operation_id) DO UPDATE SET {updates}",
                tuple(row[field] for field in fields),
            )
        saved = self.get_operation(str(row["operation_id"]))
        if saved is None:
            raise RuntimeError("ground unattended operation was not saved")
        return saved

    def get_operation(self, operation_id: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM ground_unattended_operations "
                "WHERE site_id=? AND operation_id=?",
                (self.site_id, operation_id),
            ).fetchone()
        return _decode_row(row) if row else None

    def latest_operation(
        self, *, run_id: str = "", active_only: bool = False
    ) -> dict[str, Any] | None:
        where = ["site_id=?"]
        params: list[Any] = [self.site_id]
        if run_id:
            where.append("run_id=?")
            params.append(run_id)
        if active_only:
            where.append("UPPER(operation_state) IN ('PENDING','RUNNING')")
        with self._connection() as conn:
            row = conn.execute(
                f"SELECT * FROM ground_unattended_operations WHERE {' AND '.join(where)} "
                "ORDER BY updated_at DESC LIMIT 1",
                params,
            ).fetchone()
        return _decode_row(row) if row else None

    def latest_terminal_operation(
        self, *, run_id: str = ""
    ) -> dict[str, Any] | None:
        where = [
            "site_id=?",
            "UPPER(operation_state) IN ('COMPLETED','FAILED')",
        ]
        params: list[Any] = [self.site_id]
        if run_id:
            where.append("run_id=?")
            params.append(run_id)
        with self._connection() as conn:
            row = conn.execute(
                f"SELECT * FROM ground_unattended_operations WHERE {' AND '.join(where)} "
                "ORDER BY updated_at DESC LIMIT 1",
                params,
            ).fetchone()
        return _decode_row(row) if row else None

    def list_operations(
        self,
        *,
        run_id: str = "",
        active_only: bool = False,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        where = ["site_id=?"]
        params: list[Any] = [self.site_id]
        if run_id:
            where.append("run_id=?")
            params.append(run_id)
        if active_only:
            where.append("UPPER(operation_state) IN ('PENDING','RUNNING')")
        params.append(max(1, min(int(limit), 500)))
        with self._connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM ground_unattended_operations WHERE {' AND '.join(where)} "
                "ORDER BY updated_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [_decode_row(row) for row in rows]

    def update_operation(self, operation_id: str, **values: Any) -> dict[str, Any]:
        if not values:
            current = self.get_operation(operation_id)
            if current is None:
                raise ValueError("ground unattended operation not found")
            return current
        row = dict(values)
        if "result_summary" in row:
            row["result_summary_json"] = json.dumps(
                row.pop("result_summary"), ensure_ascii=False
            )
        row["updated_at"] = _now()
        assignments = ", ".join(f"{field}=?" for field in row)
        with self._transaction() as conn:
            cursor = conn.execute(
                f"UPDATE ground_unattended_operations SET {assignments} "
                "WHERE site_id=? AND operation_id=?",
                (*row.values(), self.site_id, operation_id),
            )
            if not cursor.rowcount:
                raise ValueError("ground unattended operation not found")
        current = self.get_operation(operation_id)
        if current is None:
            raise RuntimeError("ground unattended operation disappeared")
        return current

    def delete_archive_record(self, archive_id: str) -> None:
        with self._transaction() as conn:
            conn.execute(
                "DELETE FROM ground_unattended_archives WHERE site_id=? AND archive_id=?",
                (self.site_id, archive_id),
            )

    def upsert_raw_file(self, values: dict[str, Any]) -> None:
        allowed = {
            "file_id",
            "site_id",
            "run_id",
            "train_id",
            "device_id",
            "device_uuid",
            "mr_role",
            "data_type",
            "relative_path",
            "start_time",
            "end_time",
            "record_count",
            "size_bytes",
            "sha256",
            "status",
            "archive_status",
            "parse_status",
            "compressed_path",
            "created_at",
            "updated_at",
        }
        row = {key: value for key, value in values.items() if key in allowed}
        row.setdefault("site_id", self.site_id)
        now = _now()
        row.setdefault("created_at", now)
        row["updated_at"] = now
        fields = tuple(row)
        updates = ", ".join(
            f"{field}=excluded.{field}"
            for field in fields
            if field not in {"file_id", "site_id", "created_at"}
        )
        with self._transaction() as conn:
            conn.execute(
                f"INSERT INTO ground_unattended_raw_files ({', '.join(fields)}) "
                f"VALUES ({', '.join('?' for _ in fields)}) "
                f"ON CONFLICT(file_id) DO UPDATE SET {updates}",
                tuple(row[field] for field in fields),
            )

    def list_raw_files(
        self,
        *,
        data_type: str = "",
        status: str = "",
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        where = ["site_id=?"]
        params: list[Any] = [self.site_id]
        if data_type:
            where.append("data_type=?")
            params.append(data_type)
        if status:
            where.append("status=?")
            params.append(status)
        with self._connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM ground_unattended_raw_files WHERE {' AND '.join(where)} "
                "ORDER BY start_time DESC, created_at DESC LIMIT ? OFFSET ?",
                (*params, max(1, min(int(limit), 1000)), max(0, int(offset))),
            ).fetchall()
        return [_decode_row(row) for row in rows]

    def list_raw_files_for_query(
        self,
        *,
        data_type: str,
        start_time: str,
        end_time: str,
        run_id: str = "",
        train_id: str = "",
        device_uuid: str = "",
        mr_role: str = "",
        limit: int = 256,
        newest_first: bool = False,
    ) -> list[dict[str, Any]]:
        where = ["site_id=?", "data_type=?"]
        params: list[Any] = [self.site_id, data_type]
        if run_id:
            where.append("run_id=?")
            params.append(run_id)
        if train_id:
            where.append("train_id=?")
            params.append(train_id)
        if device_uuid:
            where.append("device_uuid=?")
            params.append(device_uuid)
        if mr_role:
            where.append("mr_role=?")
            params.append(mr_role)
        if start_time:
            where.append(
                "(end_time='' OR julianday(end_time) IS NULL "
                "OR julianday(end_time)>=julianday(?))"
            )
            params.append(start_time)
        if end_time:
            where.append(
                "(start_time='' OR julianday(start_time) IS NULL "
                "OR julianday(start_time)<=julianday(?))"
            )
            params.append(end_time)
        with self._connection() as conn:
            order = (
                "COALESCE(NULLIF(end_time, ''), start_time) DESC, "
                "start_time DESC, created_at DESC"
                if newest_first
                else "start_time, created_at"
            )
            rows = conn.execute(
                f"SELECT * FROM ground_unattended_raw_files WHERE {' AND '.join(where)} "
                f"ORDER BY {order} LIMIT ?",
                (*params, max(1, min(int(limit), 1000))),
            ).fetchall()
        result = []
        for row in rows:
            decoded = _decode_row(row)
            if _raw_file_overlaps(
                decoded, start_time=start_time, end_time=end_time
            ):
                result.append(decoded)
        return result

    def list_raw_files_for_run(self, run_id: str) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM ground_unattended_raw_files
                WHERE site_id=? AND run_id=?
                ORDER BY start_time, created_at
                """,
                (self.site_id, run_id),
            ).fetchall()
        return [_decode_row(row) for row in rows]

    def get_raw_file(self, file_id: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM ground_unattended_raw_files "
                "WHERE site_id=? AND file_id=?",
                (self.site_id, file_id),
            ).fetchone()
        return _decode_row(row) if row else None

    def count_raw_files(self, *, data_type: str = "", status: str = "") -> int:
        where = ["site_id=?"]
        params: list[Any] = [self.site_id]
        if data_type:
            where.append("data_type=?")
            params.append(data_type)
        if status:
            where.append("status=?")
            params.append(status)
        with self._connection() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) FROM ground_unattended_raw_files WHERE {' AND '.join(where)}",
                params,
            ).fetchone()
        return int(row[0] if row else 0)

    def list_open_raw_files(self, run_id: str) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM ground_unattended_raw_files
                WHERE site_id=? AND run_id=? AND status='OPEN'
                ORDER BY start_time, created_at
                """,
                (self.site_id, run_id),
            ).fetchall()
        return [_decode_row(row) for row in rows]

    def count_unarchived_raw_files(self, run_id: str) -> int:
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) FROM ground_unattended_raw_files
                WHERE site_id=? AND run_id=? AND archive_status!='ARCHIVED'
                """,
                (self.site_id, run_id),
            ).fetchone()
        return int(row[0] if row else 0)

    def mark_raw_files_archived(self, run_id: str, compressed_path: str) -> int:
        with self._transaction() as conn:
            cursor = conn.execute(
                "UPDATE ground_unattended_raw_files SET archive_status='ARCHIVED', "
                "compressed_path=?, updated_at=? WHERE site_id=? AND run_id=? "
                "AND status IN ('CLOSED','RECOVERED')",
                (compressed_path, _now(), self.site_id, run_id),
            )
        return int(cursor.rowcount)

    def update_raw_file_after_rewrite(
        self,
        file_id: str,
        *,
        base_revision: int,
        record_count: int,
        size_bytes: int,
        sha256: str,
        start_time: str,
        end_time: str,
    ) -> int:
        with self._transaction() as conn:
            cursor = conn.execute(
                "UPDATE ground_unattended_raw_files SET "
                "record_count=?, size_bytes=?, sha256=?, start_time=?, "
                "end_time=?, revision=revision+1, updated_at=? "
                "WHERE site_id=? AND file_id=? AND revision=?",
                (
                    max(0, int(record_count)),
                    max(0, int(size_bytes)),
                    str(sha256 or ""),
                    str(start_time or ""),
                    str(end_time or ""),
                    _now(),
                    self.site_id,
                    file_id,
                    int(base_revision),
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("RAW_FILE_REVISION_CONFLICT")
        return int(base_revision) + 1

    def save_delete_operation(self, values: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "operation_id",
            "site_id",
            "run_id",
            "mode",
            "filters_json",
            "selected_count",
            "matched_count",
            "affected_file_count",
            "deleted_record_count",
            "deleted_event_count",
            "revision_before_json",
            "revision_after_json",
            "started_at",
            "completed_at",
            "status",
            "failure_code",
            "failure_message",
            "confirmation_source",
            "task_id",
            "updated_at",
        }
        row = {key: value for key, value in values.items() if key in allowed}
        row.setdefault("site_id", self.site_id)
        row.setdefault("started_at", _now())
        row["updated_at"] = _now()
        fields = tuple(row)
        updates = ", ".join(
            f"{field}=excluded.{field}"
            for field in fields
            if field not in {"operation_id", "site_id", "started_at"}
        )
        with self._transaction() as conn:
            conn.execute(
                f"INSERT INTO ground_unattended_delete_operations "
                f"({', '.join(fields)}) VALUES "
                f"({', '.join('?' for _ in fields)}) "
                f"ON CONFLICT(operation_id) DO UPDATE SET {updates}",
                tuple(row[field] for field in fields),
            )
        saved = self.get_delete_operation(str(row["operation_id"]))
        if saved is None:
            raise RuntimeError("Syslog 删除操作审计未保存")
        return saved

    def get_delete_operation(
        self, operation_id: str
    ) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM ground_unattended_delete_operations "
                "WHERE site_id=? AND operation_id=?",
                (self.site_id, operation_id),
            ).fetchone()
        return _decode_row(row) if row else None

    def update_delete_operation(
        self, operation_id: str, **values: Any
    ) -> dict[str, Any]:
        current = self.get_delete_operation(operation_id)
        if current is None:
            raise ValueError("Syslog 删除操作不存在")
        merged = {
            **current,
            **values,
            "operation_id": operation_id,
            "site_id": self.site_id,
            "filters_json": json.dumps(
                values.get("filters", current.get("filters", {})),
                ensure_ascii=False,
            ),
            "revision_before_json": json.dumps(
                values.get(
                    "revision_before",
                    current.get("revision_before", {}),
                ),
                ensure_ascii=False,
            ),
            "revision_after_json": json.dumps(
                values.get(
                    "revision_after",
                    current.get("revision_after", {}),
                ),
                ensure_ascii=False,
            ),
        }
        return self.save_delete_operation(merged)

    def syslog_derived_effects(
        self,
        run_id: str,
        record_refs: Iterable[dict[str, Any]],
        *,
        apply: bool,
        include_derived_events: bool,
    ) -> dict[str, int]:
        references = list(record_refs)
        if not references:
            return {"wmesh": 0, "timeline": 0}
        wmesh_count = 0
        timeline_count = 0
        with self._transaction() as conn:
            wmesh_ids, timeline_ids = _find_syslog_derived_ids(
                conn,
                site_id=self.site_id,
                run_id=run_id,
                references=references,
            )
            wmesh_count = len(wmesh_ids)
            timeline_count = len(timeline_ids)
            if not apply:
                return {
                    "wmesh": wmesh_count,
                    "timeline": timeline_count,
                }
            if include_derived_events:
                _delete_ids(
                    conn,
                    "ground_unattended_wmesh_events",
                    wmesh_ids,
                )
                _delete_ids(
                    conn,
                    "ground_unattended_events",
                    timeline_ids,
                )
            else:
                _mark_source_deleted(
                    conn,
                    "ground_unattended_wmesh_events",
                    wmesh_ids,
                )
                _mark_source_deleted(
                    conn,
                    "ground_unattended_events",
                    timeline_ids,
                )
        return {"wmesh": wmesh_count, "timeline": timeline_count}

    def apply_syslog_deletion_metadata(
        self,
        run_id: str,
        *,
        file_updates: Iterable[dict[str, Any]],
        record_refs: Iterable[dict[str, Any]],
        include_derived_events: bool,
    ) -> dict[str, Any]:
        updates = list(file_updates)
        references = list(record_refs)
        revision_after: dict[str, int] = {}
        with self._transaction() as conn:
            for update in updates:
                file_id = str(update.get("file_id") or "")
                base_revision = int(update.get("base_revision") or 0)
                cursor = conn.execute(
                    "UPDATE ground_unattended_raw_files SET "
                    "record_count=?, size_bytes=?, sha256=?, start_time=?, "
                    "end_time=?, revision=revision+1, updated_at=? "
                    "WHERE site_id=? AND run_id=? AND data_type='syslog' "
                    "AND file_id=? AND revision=?",
                    (
                        max(0, int(update.get("record_count") or 0)),
                        max(0, int(update.get("size_bytes") or 0)),
                        str(update.get("sha256") or ""),
                        str(update.get("start_time") or ""),
                        str(update.get("end_time") or ""),
                        _now(),
                        self.site_id,
                        run_id,
                        file_id,
                        base_revision,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ValueError("RAW_FILE_REVISION_CONFLICT")
                revision_after[file_id] = base_revision + 1
            wmesh_ids, timeline_ids = _find_syslog_derived_ids(
                conn,
                site_id=self.site_id,
                run_id=run_id,
                references=references,
            )
            if include_derived_events:
                _delete_ids(
                    conn,
                    "ground_unattended_wmesh_events",
                    wmesh_ids,
                )
                _delete_ids(
                    conn,
                    "ground_unattended_events",
                    timeline_ids,
                )
            else:
                _mark_source_deleted(
                    conn,
                    "ground_unattended_wmesh_events",
                    wmesh_ids,
                )
                _mark_source_deleted(
                    conn,
                    "ground_unattended_events",
                    timeline_ids,
                )
        return {
            "revision_after": revision_after,
            "wmesh": len(wmesh_ids),
            "timeline": len(timeline_ids),
        }

    def insert_wmesh_events(self, rows: Iterable[dict[str, Any]]) -> int:
        values = list(rows)
        if not values:
            return 0
        fields = (
            "site_id",
            "run_id",
            "device_uuid",
            "device_id",
            "train_id",
            "mr_role",
            "event_type",
            "device_time",
            "receive_time",
            "source_ip",
            "hostname",
            "peer_name",
            "peer_mac",
            "previous_peer_name",
            "previous_peer_mac",
            "station",
            "section",
            "data_quality",
            "receive_delay_ms",
            "clock_offset_ms",
            "raw_file_id",
            "raw_line_number",
            "event_family",
            "event_time",
            "event_time_source",
            "dedup_key",
            "duplicate_count",
            "interface_name",
            "interface_type",
            "physical_state",
            "cfg_event_index",
            "cfg_command_source",
            "cfg_source",
            "cfg_destination",
            "expected_internal_change",
            "details_json",
            "created_at",
        )
        now = _now()
        with self._transaction() as conn:
            conn.executemany(
                f"INSERT INTO ground_unattended_wmesh_events ({', '.join(fields)}) "
                f"VALUES ({', '.join('?' for _ in fields)})",
                [
                    tuple(
                        json.dumps(row.get("details") or {}, ensure_ascii=False)
                        if field == "details_json"
                        else int(bool(row.get(field)))
                        if field == "expected_internal_change"
                        else int(row.get(field) or 0)
                        if field == "duplicate_count"
                        else row.get(
                            field,
                            self.site_id
                            if field == "site_id"
                            else now
                            if field == "created_at"
                            else "",
                        )
                        for field in fields
                    )
                    for row in values
                ],
            )
        return len(values)

    def record_control_syslog_event(
        self, values: dict[str, Any]
    ) -> tuple[dict[str, Any], bool]:
        """Persist one deduplicated IFNET/CFGMAN event.

        Raw NDJSON is written before this call. A duplicate therefore increments
        only the structured projection counter and never removes source evidence.
        """

        row = dict(values)
        dedup_key = str(row.get("dedup_key") or "")
        if not dedup_key:
            raise ValueError("structured Syslog event requires dedup_key")
        now = _now()
        fields = (
            "site_id",
            "run_id",
            "device_uuid",
            "device_id",
            "train_id",
            "mr_role",
            "event_type",
            "device_time",
            "receive_time",
            "source_ip",
            "hostname",
            "peer_name",
            "peer_mac",
            "previous_peer_name",
            "previous_peer_mac",
            "station",
            "section",
            "data_quality",
            "receive_delay_ms",
            "clock_offset_ms",
            "raw_file_id",
            "raw_line_number",
            "event_family",
            "event_time",
            "event_time_source",
            "dedup_key",
            "duplicate_count",
            "interface_name",
            "interface_type",
            "physical_state",
            "cfg_event_index",
            "cfg_command_source",
            "cfg_source",
            "cfg_destination",
            "expected_internal_change",
            "details_json",
            "created_at",
        )
        row.setdefault("site_id", self.site_id)
        row.setdefault("created_at", now)
        row.setdefault("duplicate_count", 0)
        row["expected_internal_change"] = int(
            bool(row.get("expected_internal_change"))
        )
        row["details_json"] = json.dumps(
            row.pop("details", row.get("details_json") or {}),
            ensure_ascii=False,
        )
        with self._transaction() as conn:
            existing = conn.execute(
                """
                SELECT * FROM ground_unattended_wmesh_events
                WHERE site_id=? AND dedup_key=?
                """,
                (self.site_id, dedup_key),
            ).fetchone()
            if existing is not None:
                conn.execute(
                    """
                    UPDATE ground_unattended_wmesh_events
                    SET duplicate_count=duplicate_count+1
                    WHERE id=?
                    """,
                    (int(existing["id"]),),
                )
                saved = conn.execute(
                    "SELECT * FROM ground_unattended_wmesh_events WHERE id=?",
                    (int(existing["id"]),),
                ).fetchone()
                if saved is None:
                    raise RuntimeError("structured Syslog event disappeared")
                return _decode_row(saved), False
            cursor = conn.execute(
                f"INSERT INTO ground_unattended_wmesh_events ({', '.join(fields)}) "
                f"VALUES ({', '.join('?' for _ in fields)})",
                tuple(row.get(field, "") for field in fields),
            )
            saved = conn.execute(
                "SELECT * FROM ground_unattended_wmesh_events WHERE id=?",
                (int(cursor.lastrowid),),
            ).fetchone()
        if saved is None:
            raise RuntimeError("structured Syslog event was not saved")
        return _decode_row(saved), True

    def get_structured_syslog_event(self, event_id: int) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM ground_unattended_wmesh_events WHERE site_id=? AND id=?",
                (self.site_id, int(event_id)),
            ).fetchone()
        return _decode_row(row) if row else None

    def find_control_events(
        self,
        *,
        device_uuid: str,
        event_family: str,
        event_time: str,
        window_seconds: float,
        interface_name: str = "",
        exclude_event_id: int | None = None,
    ) -> list[dict[str, Any]]:
        where = [
            "site_id=?",
            "device_uuid=?",
            "event_family=?",
            "event_time<>''",
            "ABS((julianday(event_time)-julianday(?))*86400.0)<=?",
        ]
        params: list[Any] = [
            self.site_id,
            device_uuid,
            event_family,
            event_time,
            max(0.0, float(window_seconds)),
        ]
        if interface_name:
            where.append("interface_name=?")
            params.append(interface_name)
        if exclude_event_id is not None:
            where.append("id<>?")
            params.append(int(exclude_event_id))
        with self._connection() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM ground_unattended_wmesh_events
                WHERE {' AND '.join(where)}
                ORDER BY ABS((julianday(event_time)-julianday(?))*86400.0), id
                """,
                (*params, event_time),
            ).fetchall()
        return [_decode_row(row) for row in rows]

    def list_control_events(
        self, *, device_uuid: str = "", run_id: str = ""
    ) -> list[dict[str, Any]]:
        where = ["site_id=?", "event_family IN ('IFNET','CFGMAN')"]
        params: list[Any] = [self.site_id]
        if device_uuid:
            where.append("device_uuid=?")
            params.append(device_uuid)
        if run_id:
            where.append("run_id=?")
            params.append(run_id)
        with self._connection() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM ground_unattended_wmesh_events
                WHERE {' AND '.join(where)}
                ORDER BY event_time, receive_time, id
                """,
                params,
            ).fetchall()
        return [_decode_row(row) for row in rows]

    def insert_radio_correlation(
        self, values: dict[str, Any]
    ) -> tuple[dict[str, Any], bool]:
        row = dict(values)
        row.setdefault("site_id", self.site_id)
        row.setdefault("created_at", _now())
        fields = (
            "correlation_id",
            "site_id",
            "run_id",
            "device_uuid",
            "train_id",
            "mr_role",
            "interface_name",
            "cfg_event_id",
            "ifnet_event_id",
            "delta_ms",
            "confidence",
            "created_at",
        )
        with self._transaction() as conn:
            cursor = conn.execute(
                f"""
                INSERT INTO ground_unattended_radio_correlations
                    ({', '.join(fields)})
                VALUES ({', '.join('?' for _ in fields)})
                ON CONFLICT(site_id, cfg_event_id, ifnet_event_id) DO NOTHING
                """,
                tuple(row.get(field, "") for field in fields),
            )
            saved = conn.execute(
                """
                SELECT * FROM ground_unattended_radio_correlations
                WHERE site_id=? AND cfg_event_id=? AND ifnet_event_id=?
                """,
                (
                    self.site_id,
                    int(row["cfg_event_id"]),
                    int(row["ifnet_event_id"]),
                ),
            ).fetchone()
        if saved is None:
            raise RuntimeError("radio correlation was not saved")
        return _decode_row(saved), bool(cursor.rowcount)

    def list_radio_correlations(
        self, *, event_ids: Iterable[int]
    ) -> list[dict[str, Any]]:
        values = tuple(sorted({int(value) for value in event_ids}))
        if not values:
            return []
        placeholders = ", ".join("?" for _ in values)
        with self._connection() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM ground_unattended_radio_correlations
                WHERE site_id=?
                  AND (cfg_event_id IN ({placeholders})
                       OR ifnet_event_id IN ({placeholders}))
                ORDER BY created_at, correlation_id
                """,
                (self.site_id, *values, *values),
            ).fetchall()
        return [_decode_row(row) for row in rows]

    def structured_syslog_events_by_raw_files(
        self, raw_file_ids: Iterable[str]
    ) -> list[dict[str, Any]]:
        values = tuple(sorted({str(value) for value in raw_file_ids if str(value)}))
        if not values:
            return []
        placeholders = ", ".join("?" for _ in values)
        with self._connection() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM ground_unattended_wmesh_events
                WHERE site_id=? AND raw_file_id IN ({placeholders})
                """,
                (self.site_id, *values),
            ).fetchall()
        return [_decode_row(row) for row in rows]

    def control_event_raw_positions(
        self,
        *,
        correlation_status: str = "",
        correlation_confidence: str = "",
    ) -> set[tuple[str, int]]:
        status = str(correlation_status or "").strip().upper()
        confidence = str(correlation_confidence or "").strip().upper()
        if status not in {"", "CORRELATED", "UNCORRELATED"}:
            return set()
        if confidence not in {"", "HIGH", "MEDIUM"}:
            return set()
        if status == "UNCORRELATED" and confidence:
            return set()
        where = [
            "event.site_id=?",
            "event.event_family IN ('IFNET','CFGMAN')",
            "event.raw_file_id<>''",
            "event.raw_line_number IS NOT NULL",
        ]
        params: list[Any] = [self.site_id]
        correlation_exists = """
            EXISTS (
                SELECT 1
                FROM ground_unattended_radio_correlations AS correlation
                WHERE correlation.site_id=event.site_id
                  AND (
                    correlation.cfg_event_id=event.id
                    OR correlation.ifnet_event_id=event.id
                  )
        """
        if confidence:
            correlation_exists += " AND correlation.confidence=?)"
            params.append(confidence)
            where.append(correlation_exists)
        elif status == "CORRELATED":
            where.append(correlation_exists + ")")
        elif status == "UNCORRELATED":
            where.append("NOT " + correlation_exists + ")")
        with self._connection() as conn:
            rows = conn.execute(
                f"""
                SELECT event.raw_file_id, event.raw_line_number
                FROM ground_unattended_wmesh_events AS event
                WHERE {' AND '.join(where)}
                """,
                params,
            ).fetchall()
        return {
            (str(row["raw_file_id"]), int(row["raw_line_number"]))
            for row in rows
        }

    def get_radio_interface_state(
        self, device_uuid: str, interface_name: str
    ) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM ground_unattended_radio_interface_states
                WHERE site_id=? AND device_uuid=? AND interface_name=?
                """,
                (self.site_id, device_uuid, interface_name),
            ).fetchone()
        return _decode_row(row) if row else None

    def upsert_radio_interface_state(self, values: dict[str, Any]) -> dict[str, Any]:
        row = dict(values)
        row.setdefault("site_id", self.site_id)
        row["updated_at"] = _now()
        for field in (
            "transition_times_json",
            "snmp_transition_times_json",
            "snmp_transition_event_ids_json",
        ):
            source = field.removesuffix("_json")
            if source in row and field not in row:
                row[field] = json.dumps(row.pop(source), ensure_ascii=False)
            elif isinstance(row.get(field), (list, dict)):
                row[field] = json.dumps(row[field], ensure_ascii=False)
        fields = tuple(row)
        updates = ", ".join(
            f"{field}=excluded.{field}"
            for field in fields
            if field not in {"site_id", "device_uuid", "interface_name"}
        )
        with self._transaction() as conn:
            conn.execute(
                f"""
                INSERT INTO ground_unattended_radio_interface_states
                    ({', '.join(fields)})
                VALUES ({', '.join('?' for _ in fields)})
                ON CONFLICT(site_id, device_uuid, interface_name)
                DO UPDATE SET {updates}
                """,
                tuple(row.values()),
            )
        saved = self.get_radio_interface_state(
            str(row["device_uuid"]), str(row["interface_name"])
        )
        if saved is None:
            raise RuntimeError("radio interface projection was not saved")
        return saved

    def list_radio_interface_states(
        self, *, device_uuid: str = ""
    ) -> list[dict[str, Any]]:
        where = ["site_id=?"]
        params: list[Any] = [self.site_id]
        if device_uuid:
            where.append("device_uuid=?")
            params.append(device_uuid)
        with self._connection() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM ground_unattended_radio_interface_states
                WHERE {' AND '.join(where)}
                ORDER BY device_uuid, interface_name
                """,
                params,
            ).fetchall()
        return [_decode_row(row) for row in rows]

    def get_mr_runtime_state(self, device_uuid: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM ground_unattended_mr_runtime_states
                WHERE site_id=? AND device_uuid=?
                """,
                (self.site_id, device_uuid),
            ).fetchone()
        return _decode_row(row) if row else None

    def upsert_mr_runtime_state(self, values: dict[str, Any]) -> dict[str, Any]:
        row = dict(values)
        row.setdefault("site_id", self.site_id)
        row["updated_at"] = _now()
        fields = tuple(row)
        updates = ", ".join(
            f"{field}=excluded.{field}"
            for field in fields
            if field not in {"site_id", "device_uuid"}
        )
        with self._transaction() as conn:
            conn.execute(
                f"""
                INSERT INTO ground_unattended_mr_runtime_states
                    ({', '.join(fields)})
                VALUES ({', '.join('?' for _ in fields)})
                ON CONFLICT(site_id, device_uuid)
                DO UPDATE SET {updates}
                """,
                tuple(row.values()),
            )
        saved = self.get_mr_runtime_state(str(row["device_uuid"]))
        if saved is None:
            raise RuntimeError("MR runtime projection was not saved")
        return saved

    def list_mr_runtime_states(self) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM ground_unattended_mr_runtime_states
                WHERE site_id=? ORDER BY train_id, mr_role, device_uuid
                """,
                (self.site_id,),
            ).fetchall()
        return [_decode_row(row) for row in rows]

    def clear_radio_projections(self, *, device_uuid: str = "") -> None:
        with self._transaction() as conn:
            if device_uuid:
                conn.execute(
                    """
                    DELETE FROM ground_unattended_radio_correlations
                    WHERE site_id=? AND device_uuid=?
                    """,
                    (self.site_id, device_uuid),
                )
                conn.execute(
                    """
                    DELETE FROM ground_unattended_radio_interface_states
                    WHERE site_id=? AND device_uuid=?
                    """,
                    (self.site_id, device_uuid),
                )
                conn.execute(
                    """
                    DELETE FROM ground_unattended_mr_runtime_states
                    WHERE site_id=? AND device_uuid=?
                    """,
                    (self.site_id, device_uuid),
                )
            else:
                for table in (
                    "ground_unattended_radio_correlations",
                    "ground_unattended_radio_interface_states",
                    "ground_unattended_mr_runtime_states",
                ):
                    conn.execute(
                        f"DELETE FROM {table} WHERE site_id=?", (self.site_id,)
                    )

    def mark_expected_config_change(
        self,
        *,
        device_uuid: str,
        operation_id: str,
        expected_started_at: str = "",
        expected_until: str,
    ) -> None:
        started_at = expected_started_at or _now()
        with self._transaction() as conn:
            conn.execute(
                """
                UPDATE ground_unattended_boot_sessions
                SET expected_change_operation_id=?,
                    expected_change_started_at=?,
                    expected_change_until=?,
                    updated_at=?
                WHERE boot_session_id=(
                    SELECT boot_session_id
                    FROM ground_unattended_boot_sessions
                    WHERE site_id=? AND device_uuid=?
                    ORDER BY last_checked_at DESC LIMIT 1
                )
                """,
                (
                    operation_id,
                    started_at,
                    expected_until,
                    started_at,
                    self.site_id,
                    device_uuid,
                ),
            )

    def expected_config_change_at(
        self, *, device_uuid: str, event_time: str
    ) -> bool:
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT expected_change_started_at, expected_change_until
                FROM ground_unattended_boot_sessions
                WHERE site_id=? AND device_uuid=?
                ORDER BY last_checked_at DESC LIMIT 1
                """,
                (self.site_id, device_uuid),
            ).fetchone()
        if row is None or not str(row["expected_change_until"] or ""):
            return False
        event = _parse_datetime(event_time)
        expected_started_at = _parse_datetime(
            str(row["expected_change_started_at"] or "")
        )
        expected_until = _parse_datetime(str(row["expected_change_until"]))
        return bool(
            event
            and expected_started_at
            and expected_until
            and expected_started_at <= event <= expected_until
        )

    def list_wmesh_events(
        self, *, run_id: str = "", train_id: str = "", limit: int = 200, offset: int = 0
    ) -> list[dict[str, Any]]:
        where = [
            "site_id=?",
            "(event_family='WMESH' OR (event_family='' AND event_type LIKE 'MESH_%'))",
        ]
        params: list[Any] = [self.site_id]
        if run_id:
            where.append("run_id=?")
            params.append(run_id)
        if train_id:
            where.append("train_id=?")
            params.append(train_id)
        with self._connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM ground_unattended_wmesh_events WHERE {' AND '.join(where)} "
                "ORDER BY receive_time DESC LIMIT ? OFFSET ?",
                (*params, max(1, min(int(limit), 500)), max(0, int(offset))),
            ).fetchall()
        return [_decode_row(row) for row in rows]

    def latest_wmesh_event(self, device_uuid: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM ground_unattended_wmesh_events "
                "WHERE site_id=? AND device_uuid=? "
                "AND (event_family='WMESH' "
                "OR (event_family='' AND event_type LIKE 'MESH_%')) "
                "ORDER BY receive_time DESC LIMIT 1",
                (self.site_id, device_uuid),
            ).fetchone()
        return _decode_row(row) if row else None

    def latest_boot_session(self, device_uuid: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM ground_unattended_boot_sessions WHERE site_id=? AND device_uuid=? "
                "ORDER BY last_checked_at DESC LIMIT 1",
                (self.site_id, device_uuid),
            ).fetchone()
        return _decode_row(row) if row else None

    def upsert_boot_session(self, values: dict[str, Any]) -> None:
        fields = (
            "boot_session_id",
            "site_id",
            "device_uuid",
            "device_id",
            "train_id",
            "mr_role",
            "first_detected_at",
            "last_checked_at",
            "estimated_boot_time",
            "first_uptime_seconds",
            "last_uptime_seconds",
            "device_clock_before",
            "device_clock_after",
            "boot_time_uncertainty_seconds",
            "reboot_reason",
            "timezone_name",
            "utc_offset_seconds",
            "time_quality",
            "clock_jump_seconds",
            "version_evidence_path",
            "config_status",
            "config_checked_at",
            "config_applied_at",
            "first_syslog_received_at",
            "last_syslog_received_at",
            "config_fingerprint",
            "info_center_metrics_json",
            "expected_change_operation_id",
            "expected_change_started_at",
            "expected_change_until",
            "created_at",
            "updated_at",
        )
        now = _now()
        row = dict(values)
        row.setdefault("site_id", self.site_id)
        row.setdefault("created_at", now)
        row["updated_at"] = now
        if "info_center_metrics" in row and "info_center_metrics_json" not in row:
            row["info_center_metrics_json"] = json.dumps(
                row.pop("info_center_metrics") or {}, ensure_ascii=False
            )
        elif isinstance(row.get("info_center_metrics_json"), (dict, list)):
            row["info_center_metrics_json"] = json.dumps(
                row["info_center_metrics_json"], ensure_ascii=False
            )
        with self._transaction() as conn:
            conn.execute(
                f"INSERT INTO ground_unattended_boot_sessions ({', '.join(fields)}) "
                f"VALUES ({', '.join('?' for _ in fields)}) "
                "ON CONFLICT(boot_session_id) DO UPDATE SET "
                + ", ".join(
                    f"{field}=excluded.{field}"
                    for field in fields
                    if field not in {"boot_session_id", "site_id", "created_at"}
                ),
                tuple(row.get(field, "") for field in fields),
            )

    def save_syslog_config_audit(self, values: dict[str, Any]) -> None:
        fields = (
            "audit_id",
            "site_id",
            "boot_session_id",
            "device_uuid",
            "train_id",
            "mr_role",
            "checked_at",
            "target_ip",
            "target_port",
            "status",
            "missing_commands_json",
            "applied_commands_json",
            "evidence_path",
            "evidence_sha256",
            "error_code",
            "error_message",
            "managed_profile_version",
            "created_at",
        )
        row = dict(values)
        now = _now()
        row.setdefault("site_id", self.site_id)
        row.setdefault("created_at", now)
        row.setdefault("managed_profile_version", 2)
        for field in ("missing_commands_json", "applied_commands_json"):
            if field not in row:
                row[field] = json.dumps(
                    row.get(field.removesuffix("_json"), []), ensure_ascii=False
                )
        with self._transaction() as conn:
            conn.execute(
                f"INSERT INTO ground_unattended_syslog_config_audits ({', '.join(fields)}) "
                f"VALUES ({', '.join('?' for _ in fields)})",
                tuple(row.get(field, "") for field in fields),
            )

    def latest_syslog_config_audit(self, device_uuid: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM ground_unattended_syslog_config_audits "
                "WHERE site_id=? AND device_uuid=? ORDER BY checked_at DESC LIMIT 1",
                (self.site_id, device_uuid),
            ).fetchone()
        return _decode_row(row) if row else None

    def confirm_syslog_identity(
        self,
        *,
        device_uuid: str,
        source_ip: str,
        hostname: str,
        verified_at: str,
    ) -> None:
        with self._transaction() as conn:
            conn.execute(
                "UPDATE ground_unattended_train_endpoints SET last_syslog_source_ip=?, "
                "syslog_hostname=?, last_syslog_identity_verified_at=?, updated_at=? "
                "WHERE site_id=? AND device_uuid=?",
                (source_ip, hostname, verified_at, _now(), self.site_id, device_uuid),
            )

    def touch_boot_syslog(
        self,
        device_uuid: str,
        received_at: str,
        *,
        source_ip: str = "",
        hostname: str = "",
        identity_verified: bool = False,
    ) -> None:
        if not identity_verified:
            return
        with self._transaction() as conn:
            row = conn.execute(
                "SELECT boot_session_id, first_syslog_received_at, config_status FROM ground_unattended_boot_sessions "
                "WHERE site_id=? AND device_uuid=? ORDER BY last_checked_at DESC LIMIT 1",
                (self.site_id, device_uuid),
            ).fetchone()
            if row is None:
                return
            if str(row["config_status"] or "") not in {"WAITING_FIRST_LOG", "LOG_ACTIVE"}:
                return
            first = str(row["first_syslog_received_at"] or received_at)
            conn.execute(
                "UPDATE ground_unattended_boot_sessions SET first_syslog_received_at=?, "
                "last_syslog_received_at=?, config_status='LOG_ACTIVE', updated_at=? "
                "WHERE boot_session_id=?",
                (first, received_at, _now(), str(row["boot_session_id"])),
            )
        self.confirm_syslog_identity(
            device_uuid=device_uuid,
            source_ip=source_ip,
            hostname=hostname,
            verified_at=received_at,
        )

    def add_health_event(
        self,
        *,
        run_id: str = "",
        component: str,
        severity: str,
        code: str,
        message: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        with self._transaction() as conn:
            conn.execute(
                "INSERT INTO ground_unattended_health_events(site_id, run_id, ts, component, "
                "severity, code, message, details_json) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    self.site_id,
                    run_id,
                    _now(),
                    component,
                    severity,
                    code,
                    message,
                    json.dumps(details or {}, ensure_ascii=False),
                ),
            )

    def add_events_batch(self, rows: Iterable[dict[str, Any]]) -> int:
        values = list(rows)
        if not values:
            return 0
        with self._transaction() as conn:
            conn.executemany(
                """
                INSERT INTO ground_unattended_events(
                    site_id, run_id, ts, event_type, severity, train_id, mr_id,
                    title, message, details_json
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        self.site_id,
                        str(row.get("run_id") or ""),
                        str(row.get("ts") or _now()),
                        str(row.get("event_type") or "event"),
                        str(row.get("severity") or "info"),
                        str(row.get("train_id") or ""),
                        str(row.get("mr_id") or ""),
                        str(row.get("title") or ""),
                        str(row.get("message") or ""),
                        json.dumps(row.get("details") or {}, ensure_ascii=False),
                    )
                    for row in values
                ],
            )
        return len(values)

    def latest_health_event(self) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM ground_unattended_health_events WHERE site_id=? "
                "ORDER BY ts DESC LIMIT 1",
                (self.site_id,),
            ).fetchone()
        return _decode_row(row) if row else None

    def purge_run_details(self, run_id: str) -> None:
        with self._transaction() as conn:
            for table in (
                "ground_unattended_ac_snapshots",
                "ground_unattended_ping_segments",
                "ground_unattended_deep_operations",
                "ground_unattended_events",
            ):
                conn.execute(
                    f"DELETE FROM {table} WHERE site_id=? AND run_id=?",
                    (self.site_id, run_id),
                )
            conn.execute(
                "DELETE FROM ground_unattended_ping_summaries "
                "WHERE site_id=? AND run_id=? AND bucket_kind!='daily'",
                (self.site_id, run_id),
            )

    def delete_summaries_before(self, cutoff: str) -> int:
        with self._transaction() as conn:
            cursor = conn.execute(
                """
                DELETE FROM ground_unattended_ping_summaries
                WHERE site_id=? AND run_id IN (
                    SELECT run_id FROM ground_unattended_runs WHERE site_id=? AND run_date < ?
                )
                """,
                (self.site_id, self.site_id, cutoff),
            )
            old_runs = [
                str(row[0])
                for row in conn.execute(
                    "SELECT run_id FROM ground_unattended_runs WHERE site_id=? AND run_date < ?",
                    (self.site_id, cutoff),
                ).fetchall()
            ]
            for run_id in old_runs:
                conn.execute(
                    "DELETE FROM ground_unattended_train_runs WHERE site_id=? AND run_id=?",
                    (self.site_id, run_id),
                )
                conn.execute(
                    "DELETE FROM ground_unattended_daily_queues WHERE site_id=? AND run_id=?",
                    (self.site_id, run_id),
                )
                conn.execute(
                    "DELETE FROM ground_unattended_runs WHERE site_id=? AND run_id=? "
                    "AND NOT EXISTS(SELECT 1 FROM ground_unattended_archives WHERE site_id=? AND run_id=?)",
                    (self.site_id, run_id, self.site_id, run_id),
                )
            return int(cursor.rowcount)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = Database(self.db_path).connect()
        configure_sqlite_connection(
            conn,
            busy_timeout_ms=10_000,
            foreign_keys=True,
            temp_store_memory=True,
        )
        initialize_sqlite_wal(conn)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except Exception:
                conn.rollback()
                raise


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def _raw_file_overlaps(
    row: dict[str, Any], *, start_time: str, end_time: str
) -> bool:
    query_start = _parse_datetime(start_time)
    query_end = _parse_datetime(end_time)
    file_start = _parse_datetime(str(row.get("start_time") or ""))
    file_end = _parse_datetime(str(row.get("end_time") or ""))
    if query_end is not None and file_start is not None and file_start > query_end:
        return False
    if query_start is not None and file_end is not None and file_end < query_start:
        return False
    return True


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.astimezone()


def _syslog_reference_matches(
    references: list[dict[str, Any]],
    *,
    raw_file_id: str = "",
    raw_line_number: object = None,
    details_json: str,
) -> bool:
    try:
        details = json.loads(details_json or "{}")
    except json.JSONDecodeError:
        details = {}
    if not isinstance(details, dict):
        details = {}
    candidate_file_id = str(
        raw_file_id or details.get("raw_file_id") or ""
    )
    candidate_line = _optional_int(
        raw_line_number
        if raw_line_number not in {None, ""}
        else details.get("raw_line_number")
    )
    candidate_global = _optional_int(
        details.get("global_receive_sequence")
    )
    candidate_source = _optional_int(
        details.get("source_receive_sequence")
    )
    for reference in references:
        expected_file_id = str(reference.get("raw_file_id") or "")
        if expected_file_id and candidate_file_id != expected_file_id:
            continue
        matched_discriminator = False
        mismatch = False
        for expected, candidate in (
            (
                _optional_int(reference.get("raw_line_number")),
                candidate_line,
            ),
            (
                _optional_int(
                    reference.get("global_receive_sequence")
                ),
                candidate_global,
            ),
            (
                _optional_int(
                    reference.get("source_receive_sequence")
                ),
                candidate_source,
            ),
        ):
            if expected is None or candidate is None:
                continue
            if expected != candidate:
                mismatch = True
                break
            matched_discriminator = True
        if not mismatch and matched_discriminator:
            return True
    return False


def _find_syslog_derived_ids(
    conn: sqlite3.Connection,
    *,
    site_id: str,
    run_id: str,
    references: list[dict[str, Any]],
) -> tuple[list[int], list[int]]:
    wmesh_rows = conn.execute(
        "SELECT id, raw_file_id, raw_line_number, details_json "
        "FROM ground_unattended_wmesh_events "
        "WHERE site_id=? AND run_id=?",
        (site_id, run_id),
    ).fetchall()
    wmesh_ids = [
        int(row["id"])
        for row in wmesh_rows
        if _syslog_reference_matches(
            references,
            raw_file_id=str(row["raw_file_id"] or ""),
            raw_line_number=row["raw_line_number"],
            details_json=str(row["details_json"] or "{}"),
        )
    ]
    timeline_rows = conn.execute(
        "SELECT id, event_type, details_json "
        "FROM ground_unattended_events "
        "WHERE site_id=? AND run_id=? AND event_type IN "
        "('mesh_linkup', 'mesh_linkdown', "
        "'mesh_activelink_switch', 'ifnet_phy_updown')",
        (site_id, run_id),
    ).fetchall()
    timeline_ids = [
        int(row["id"])
        for row in timeline_rows
        if _syslog_reference_matches(
            references,
            details_json=str(row["details_json"] or "{}"),
        )
    ]
    return wmesh_ids, timeline_ids


def _delete_ids(
    conn: sqlite3.Connection,
    table: str,
    ids: list[int],
) -> None:
    if not ids:
        return
    placeholders = ",".join("?" for _ in ids)
    conn.execute(
        f"DELETE FROM {table} WHERE id IN ({placeholders})",
        ids,
    )


def _mark_source_deleted(
    conn: sqlite3.Connection,
    table: str,
    ids: list[int],
) -> None:
    if not ids:
        return
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT id, details_json FROM {table} "
        f"WHERE id IN ({placeholders})",
        ids,
    ).fetchall()
    for row in rows:
        try:
            details = json.loads(str(row["details_json"] or "{}"))
        except json.JSONDecodeError:
            details = {}
        if not isinstance(details, dict):
            details = {}
        details["source_deleted"] = True
        details["source_deleted_reason"] = "SYSLOG_RAW_DELETED"
        conn.execute(
            f"UPDATE {table} SET details_json=? WHERE id=?",
            (json.dumps(details, ensure_ascii=False), int(row["id"])),
        )


def _optional_int(value: object) -> int | None:
    if value in {None, ""}:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _decode_row(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    for key in tuple(result):
        if key.endswith("_json"):
            value = result.pop(key)
            try:
                result[key.removesuffix("_json")] = json.loads(str(value or "{}"))
            except json.JSONDecodeError:
                result[key.removesuffix("_json")] = (
                    {} if str(value).startswith("{") else []
                )
    for key in (
        "enabled",
        "paused",
        "priority",
        "mainline_eligible",
        "ping_eligible",
        "deep_collection_eligible",
        "finalization_complete",
        "package_verified",
        "active_cleanup_pending",
        "deep_collection_enabled",
        "deep_collection_master_enabled",
        "ping_depot_trains_enabled",
        "monitor_only",
        "syslog_auto_repair_enabled",
        "expected_internal_change",
    ):
        if key in result:
            result[key] = bool(result[key])
    return result


__all__ = ["GroundUnattendedRepository"]
