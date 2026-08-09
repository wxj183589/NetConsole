from __future__ import annotations


PARSER_SCHEMA_VERSION = 12
PARSER_VERSION = "online_mr_business_tables_v12_identity_channel_busy"

PARSER_CAPABILITY_TABLES: dict[str, frozenset[str]] = {
    "main_link": frozenset({"main_link_samples"}),
    "link_detail": frozenset({"main_link_samples"}),
    "channel_busy": frozenset({"channel_busy_records"}),
    "interface_rate": frozenset({"interface_rate_samples"}),
    "switch_history": frozenset({"switch_history_events"}),
    "switch_realtime": frozenset({"switch_realtime_events"}),
    "fping_rtt": frozenset({"fping_samples"}),
    "fping_loss": frozenset({"fping_1s_summary"}),
    "iperf": frozenset({"iperf_runs", "iperf_intervals"}),
    "timeline": frozenset({"analysis_events"}),
}
PARSER_CAPABILITIES = tuple(sorted(PARSER_CAPABILITY_TABLES))
ONLINE_MR_REQUIRED_CAPABILITIES = frozenset(PARSER_CAPABILITIES)
CURRENT_PARSED_TABLES = frozenset().union(
    *PARSER_CAPABILITY_TABLES.values(),
    {
        "online_parse_metadata",
        "online_parse_issues",
        "online_schema_meta",
        "time_sync_samples",
        "radio_statistics_samples",
        "active_segments",
        "active_segment_metrics",
    },
)
