from __future__ import annotations

from pathlib import Path
import sqlite3

from PySide6.QtCore import QThread, Signal

from netconsole.services.vehicle_mr_offline_analysis import build_vehicle_mr_analysis_chart_payload
from netconsole.core.paths import PathResolver
from netconsole.services.online_mr_session_store import OnlineMrSessionStore


class OnlineMrAnalysisLoadWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)
    progress = Signal(str, int, int, str)

    def __init__(self, session_dir: Path, parent=None) -> None:
        super().__init__(parent)
        self.session_dir = Path(session_dir)

    def _progress(self, stage: str, current: int, total: int, message: str) -> None:
        self.progress.emit(stage, int(current), int(total), str(message or stage))

    def run(self) -> None:
        try:
            self._progress("打开解析缓存", 1, 3, "打开 parsed 数据库")
            self._progress("构建图表数据", 2, 3, "后台构建分析图表数据")
            payload = build_vehicle_mr_analysis_chart_payload(self.session_dir)
            table_rows, table_errors = _load_analysis_table_rows(self.session_dir, limit=500)
            payload["table_rows"] = table_rows
            payload["table_errors"] = table_errors
            self._progress("加载完成", 3, 3, "分析图表数据构建完成")
            self.completed.emit(payload)
        except Exception as exc:
            self.failed.emit(str(exc))


class OnlineMrHistoryLoadWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, paths: PathResolver, site_name: str, *, limit: int = 500, parent=None) -> None:
        super().__init__(parent)
        self.app_root = Path(paths.app_root)
        self.data_root = Path(paths.data_root)
        self.site_name = site_name
        self.limit = max(1, min(int(limit), 2000))

    def run(self) -> None:
        try:
            paths = PathResolver(app_root=self.app_root, data_root=self.data_root)
            rows = OnlineMrSessionStore(paths).list_sessions(self.site_name, None)[: self.limit]
            self.completed.emit(rows)
        except Exception as exc:
            self.failed.emit(str(exc))


def _load_analysis_table_rows(session_dir: Path, *, limit: int) -> tuple[dict[str, list[list[object]]], dict[str, str]]:
    db_path = Path(session_dir) / "parsed" / "online_diagnosis.sqlite"
    if not db_path.is_file():
        return {}, {}
    queries = {
        "mesh_link": """
            SELECT collector_time, COALESCE(NULLIF(device_time, ''), device_clock, collector_time),
                   radio, link_state, COALESCE(NULLIF(resolved_peer_name, ''), NULLIF(peer_name, ''), peer_mac),
                   peer_mac, mr_rssi, bssid, mesh_interface, belong_station, belong_section, online_time
            FROM main_link_samples WHERE UPPER(COALESCE(link_state, '')) LIKE 'ACTIVE%'
            ORDER BY collector_time ASC, id ASC LIMIT ?
        """,
        "mesh_link_detail": """
            SELECT collector_time, COALESCE(NULLIF(device_time, ''), device_clock, collector_time),
                   radio, link_state, peer_mac,
                   COALESCE(NULLIF(resolved_peer_name, ''), NULLIF(peer_name, ''), peer_mac),
                   peer_mac, belong_station, belong_section, peer_mac, mr_rssi, bssid, mesh_interface, online_time
            FROM main_link_samples ORDER BY collector_time ASC, id ASC LIMIT ?
        """,
        "active_link_switch_logs": """
            SELECT 'terminal_monitor', device_time, device_name,
                   old_peer_name, old_peer_mac, old_rssi, old_belong_station, old_belong_section, '',
                   CASE WHEN old_peer_mac IS NULL OR old_peer_mac = '' OR old_peer_mac LIKE '0000%' THEN 'empty_link' ELSE '' END,
                   new_peer_name, new_peer_mac, new_rssi, new_belong_station, new_belong_section, '',
                   CASE WHEN new_peer_mac IS NULL OR new_peer_mac = '' OR new_peer_mac LIKE '0000%' THEN 'empty_link' ELSE '' END,
                   peer_quantity, link_quantity, switch_reason_code, switch_reason_text
            FROM switch_realtime_events ORDER BY device_time ASC, id ASC LIMIT ?
        """,
        "channel_busy": """
            SELECT device_time, radio, ctl_channel, bandwidth, record_interval, ctl_busy, tx_busy, rx_busy
            FROM channel_busy_records WHERE COALESCE(row_index, 1) = 1
            ORDER BY device_time ASC, COALESCE(row_index, 1) ASC LIMIT ?
        """,
        "interface_rate": """
            SELECT device_time, direction, COALESCE(NULLIF(interface_normalized, ''), interface_name), usage_percent,
                   total_pps, broadcast_pps, multicast_pps
            FROM interface_rate_samples
            WHERE lower(COALESCE(NULLIF(interface_normalized, ''), interface_name, '')) NOT LIKE 'xge%'
              AND lower(COALESCE(NULLIF(interface_normalized, ''), interface_name, '')) NOT LIKE 'xgigabitethernet%'
              AND lower(COALESCE(NULLIF(interface_normalized, ''), interface_name, '')) NOT LIKE 'ten-gigabitethernet%'
              AND lower(COALESCE(NULLIF(interface_normalized, ''), interface_name, '')) NOT LIKE 'tengigabitethernet%'
            ORDER BY device_time ASC LIMIT ?
        """,
        "fping_1s": """
            SELECT COALESCE(NULLIF(device_bucket_time, ''), NULLIF(bucket_time, ''), local_bucket_time),
                   COALESCE(NULLIF(device_bucket_time, ''), '-'),
                   COALESCE(NULLIF(local_bucket_time, ''), NULLIF(bucket_time, ''), '-'),
                   target_ip, COALESCE(target_name, ''), sent, received,
                   COALESCE(lost, sent - received), loss_percent, avg_latency_ms,
                   min_latency_ms, max_latency_ms, jitter_ms, COALESCE(status, '')
            FROM fping_1s_summary ORDER BY 1 ASC, target_ip ASC LIMIT ?
        """,
        "iperf": """
            SELECT COALESCE(NULLIF(device_interval_center_time, ''), NULLIF(device_aligned_time, ''), interval_center_time, collector_time),
                   bitrate_mbps, retransmits, transfer_bytes, raw_line
            FROM iperf_intervals
            ORDER BY COALESCE(NULLIF(device_interval_center_time, ''), NULLIF(device_aligned_time, ''), interval_center_time, collector_time) ASC
            LIMIT ?
        """,
        "radio_statistics": """
            SELECT collector_time, metric_name, metric_value, metric_unit
            FROM radio_statistics_samples ORDER BY collector_time ASC, id ASC LIMIT ?
        """,
        "diagnosis": """
            SELECT s.start_time, s.end_time, s.active_peer_mac, s.avg_mr_rssi, s.min_mr_rssi,
                   m.ping_loss_percent, m.avg_latency_ms, m.max_latency_ms,
                   m.avg_mbps, m.max_mbps, m.avg_tx_busy, m.avg_rx_busy, s.event_type, s.details_json
            FROM active_segments s LEFT JOIN active_segment_metrics m ON m.segment_id = s.id
            ORDER BY s.start_time LIMIT ?
        """,
    }
    result: dict[str, list[list[object]]] = {}
    errors: dict[str, str] = {}
    with sqlite3.connect(db_path) as conn:
        for name, query in queries.items():
            try:
                result[name] = _execute_analysis_query(conn, name, query, limit)
            except Exception as exc:
                result[name] = []
                errors[name] = str(exc)
    return result, errors


def _execute_analysis_query(conn: sqlite3.Connection, name: str, query: str, limit: int) -> list[list[object]]:
    _ = name
    return [list(row) for row in conn.execute(query, (int(limit),)).fetchall()]
