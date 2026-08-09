from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

@dataclass(frozen=True)
class ChartSeries:
    name: str
    points: list[tuple[object, object]]


@dataclass(frozen=True)
class ChartEvent:
    time: datetime
    event_type: str
    label: str
    severity: str = "info"
    tooltip: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ChartData:
    title: str
    y_label: str
    series: list[ChartSeries] = field(default_factory=list)
    tooltip_rows: list[dict[str, object]] = field(default_factory=list)
    events: list[ChartEvent] = field(default_factory=list)
    empty_message: str = "无数据"

    @property
    def has_data(self) -> bool:
        return any(series.points for series in self.series)


@dataclass(frozen=True)
class InteractiveChartPoint:
    timestamp: datetime
    timestamp_label: str
    device_name: str = ""
    series_name: str = ""
    metric_label: str = ""
    metric_value: object = None
    radio_id: object = None
    peer_name: str = ""
    peer_mac: str = ""
    bssid: str = ""
    mesh_interface: str = ""
    station: str = ""
    section: str = ""
    belong_type: str = ""
    belonging_source: str = ""
    rssi: float | None = None
    link_state: str = ""
    online_time: object = None
    ctl_busy: object = None
    tx_busy: object = None
    rx_busy: object = None
    ping_loss: object = None
    ping_avg_latency: object = None
    ping_max_latency: object = None
    inbound_pps: object = None
    outbound_pps: object = None
    traffic_direction: str = ""
    traffic_rate_mbps: object = None
    traffic_protocol: str = ""
    traffic_role: str = ""
    traffic_jitter_ms: object = None
    traffic_loss_percent: object = None
    traffic_retransmits: object = None
    traffic_transfer_bytes: object = None
    raw: str = ""


class OnlineMrChartBuilder:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)

    def build_session_summary(self) -> dict[str, object]:
        meta = self._read_session_meta()
        counts = {
            "main_link": self._scalar("SELECT COUNT(*) FROM main_link_samples"),
            "active_link": self._scalar("SELECT COUNT(*) FROM main_link_samples WHERE UPPER(link_state) LIKE 'ACTIVE%'"),
            "switch": self._scalar("SELECT COUNT(*) FROM switch_realtime_events"),
            "fping": self._scalar("SELECT COUNT(*) FROM fping_1s_summary"),
            "iperf": self._scalar("SELECT COUNT(*) FROM iperf_intervals"),
            "channel_busy": self._scalar("SELECT COUNT(*) FROM channel_busy_records"),
            "interface_rate": self._scalar("SELECT COUNT(*) FROM interface_rate_samples"),
        }
        first_last = self._query(
            """
            SELECT MIN(collector_time), MAX(collector_time)
            FROM main_link_samples
            WHERE collector_time IS NOT NULL AND collector_time <> ''
            """
        )
        start_time, end_time = first_last[0] if first_last else (None, None)
        return {
            "device_name": meta.get("device_name") or meta.get("host") or "-",
            "session_start": start_time or meta.get("started_at") or "-",
            "session_end": end_time or meta.get("ended_at") or "-",
            "time_sync": self._time_sync_status_text(),
            **counts,
        }

    def build_switch_events(self) -> list[ChartEvent]:
        rows = self._query(
            """
            SELECT device_time, switch_reason_text, old_peer_name, old_peer_mac,
                   new_peer_name, new_peer_mac, old_rssi, new_rssi, switch_reason_code
            FROM switch_realtime_events
            WHERE device_time IS NOT NULL AND device_time <> ''
            ORDER BY device_time ASC, id ASC
            LIMIT 5000
            """
        )
        events: list[ChartEvent] = []
        for row in rows:
            timestamp = _parse_time(row[0])
            if timestamp is None:
                continue
            reason = str(row[1] or "链路切换").strip() or "链路切换"
            events.append(
                ChartEvent(
                    time=timestamp,
                    event_type="active_link_switch",
                    label=reason,
                    severity=_switch_reason_severity(reason, row[8]),
                    tooltip={
                        "time": row[0],
                        "reason": reason,
                        "from_peer_name": row[2],
                        "from_peer_mac": row[3],
                        "from_rssi": row[6],
                        "to_peer_name": row[4],
                        "to_peer_mac": row[5],
                        "to_rssi": row[7],
                        "reason_code": row[8],
                    },
                )
            )
        return events

    def build_active_rssi_series(self) -> ChartData:
        rows = self._query(
            """
            SELECT collector_time, radio, peer_mac, mr_rssi, link_state,
                   COALESCE(NULLIF(resolved_peer_name, ''), peer_name, peer_mac),
                   belong_station, belong_section
            FROM main_link_samples
            WHERE mr_rssi IS NOT NULL
            ORDER BY collector_time ASC, id ASC
            LIMIT 20000
            """
        )
        channel_busy = self._nearest_channel_busy_index()
        active_rows: list[tuple[object, ...]] = []
        standby_rows: list[dict[str, object]] = []
        for row in rows:
            timestamp = _parse_time(row[0])
            rssi = _normalize_rssi(row[3])
            if timestamp is None or rssi is None:
                continue
            link_state = str(row[4] or "").upper()
            if link_state.startswith("ACTIVE"):
                active_rows.append(row)
            elif "STANDBY" in link_state:
                standby_rows.append(
                    {
                        "timestamp": timestamp,
                        "radio": row[1],
                        "peer_name": row[5] or row[2],
                        "peer_mac": row[2],
                        "station": row[6],
                        "section": row[7],
                        "rssi": rssi,
                    }
                )
        points: list[tuple[object, object]] = []
        tooltips: list[dict[str, object]] = []
        for row in active_rows:
            timestamp = _parse_time(row[0])
            rssi = _normalize_rssi(row[3])
            if timestamp is None or rssi is None:
                continue
            radio = row[1]
            busy = _nearest_by_time(channel_busy, timestamp, max_seconds=5, predicate=lambda item: str(item.get("radio") or "") == str(radio or ""))
            points.append((row[0], rssi))
            tooltips.append(
                {
                    "time": row[0],
                    "sample_time": row[0],
                    "radio": radio,
                    "peer_name": row[5] or row[2],
                    "peer_mac": row[2],
                    "rssi": rssi,
                    "station": row[6],
                    "section": row[7],
                    "tx_busy": busy.get("tx_busy") if busy else None,
                    "rx_busy": busy.get("rx_busy") if busy else None,
                    "standby_links": _standby_links_near(standby_rows, timestamp, radio),
                }
            )
        return ChartData(
            title="主链路 RSSI",
            y_label="RSSI",
            series=[ChartSeries("当前ACTIVE主链路RSSI", points)],
            tooltip_rows=tooltips,
            empty_message="未解析到主链路RSSI",
        )

    def build_active_rssi_interactive_points(self, session_id: str | None = None, device_filter: object = None, time_range: tuple[object, object] | None = None) -> list[InteractiveChartPoint]:
        _ = device_filter
        meta = self._read_session_meta()
        params: list[object] = []
        where = ["UPPER(link_state) LIKE 'ACTIVE%'", "mr_rssi IS NOT NULL"]
        if session_id:
            where.append("session_id = ?")
            params.append(session_id)
        if time_range:
            if time_range[0] is not None:
                where.append("collector_time >= ?")
                params.append(str(time_range[0]))
            if time_range[1] is not None:
                where.append("collector_time <= ?")
                params.append(str(time_range[1]))
        rows = self._query(
            f"""
            SELECT collector_time, session_id, radio, link_state, peer_mac, peer_mac_normalized,
                   NULL AS establish_time, online_time, NULL AS link_count, mr_rssi, NULL AS peer_rssi_db,
                   peer_name, resolved_peer_name, belong_station, belong_section, belong_type, belonging_source
            FROM main_link_samples
            WHERE {" AND ".join(where)}
            ORDER BY collector_time ASC
            LIMIT 20000
            """,
            tuple(params),
        )
        channel_busy = self._nearest_channel_busy_index()
        pings = self._nearest_ping_index()
        interface = self._nearest_interface_index()
        points: list[InteractiveChartPoint] = []
        for row in rows:
            timestamp = _parse_time(row[0])
            rssi = _normalize_rssi(row[9])
            if timestamp is None or rssi is None:
                continue
            radio = row[2]
            busy = _nearest_by_time(channel_busy, timestamp, max_seconds=10, predicate=lambda item: str(item.get("radio") or "") == str(radio or ""))
            ping = _nearest_by_time(pings, timestamp, max_seconds=1.5)
            pps = _nearest_by_time(interface, timestamp, max_seconds=10)
            points.append(
                InteractiveChartPoint(
                    timestamp=timestamp,
                    timestamp_label=str(row[0] or ""),
                    device_name=str(meta.get("device_name") or ""),
                    series_name="当前Active MR侧RSSI",
                    metric_label="MR侧RSSI",
                    metric_value=rssi,
                    radio_id=radio,
                    peer_name=str(row[12] or row[11] or row[4] or ""),
                    peer_mac=str(row[4] or row[5] or ""),
                    bssid="",
                    mesh_interface="",
                    station=str(row[13] or ""),
                    section=str(row[14] or ""),
                    belong_type=str(row[15] or ""),
                    belonging_source=str(row[16] or ""),
                    rssi=rssi,
                    link_state=str(row[3] or ""),
                    online_time=row[7],
                    ctl_busy=busy.get("ctl_busy") if busy else None,
                    tx_busy=busy.get("tx_busy") if busy else None,
                    rx_busy=busy.get("rx_busy") if busy else None,
                    ping_loss=ping.get("loss_percent") if ping else None,
                    ping_avg_latency=ping.get("avg_latency") if ping else None,
                    ping_max_latency=ping.get("max_latency") if ping else None,
                    inbound_pps=pps.get("inbound_pps") if pps else None,
                    outbound_pps=pps.get("outbound_pps") if pps else None,
                    raw=f"peer={row[4] or ''} rssi={row[9] if row[9] is not None else ''}",
                )
            )
        return points

    def build_channel_busy_series(self) -> ChartData:
        rows = self._query(
            """
            SELECT device_time, radio, ctl_busy, tx_busy, rx_busy
            FROM channel_busy_records
            ORDER BY device_time ASC
            LIMIT 5000
            """
        )
        ctl_values: list[tuple[object, object]] = []
        tx_values: list[tuple[object, object]] = []
        rx_values: list[tuple[object, object]] = []
        tooltips: list[dict[str, object]] = []
        for collected_at, radio, ctl_busy, tx_busy, rx_busy in rows:
            if ctl_busy is not None:
                ctl_values.append((collected_at, ctl_busy))
            if tx_busy is not None:
                tx_values.append((collected_at, tx_busy))
            if rx_busy is not None:
                rx_values.append((collected_at, rx_busy))
            tooltips.append({"time": collected_at, "radio": radio, "ctl_busy": ctl_busy, "tx_busy": tx_busy, "rx_busy": rx_busy})
        return ChartData(
            title="信道繁忙度",
            y_label="%",
            series=[ChartSeries("控制信道繁忙度", ctl_values), ChartSeries("发送繁忙度", tx_values), ChartSeries("接收繁忙度", rx_values)],
            tooltip_rows=tooltips,
            empty_message="未解析到信道繁忙度",
        )

    def build_ping_latency_series(self) -> ChartData:
        rows = self._query(
            """
            SELECT COALESCE(NULLIF(device_bucket_time, ''), NULLIF(bucket_time, ''), local_bucket_time),
                   local_bucket_time, device_bucket_time, clock_offset_ms, target_ip, avg_latency_ms
            FROM fping_1s_summary
            WHERE avg_latency_ms IS NOT NULL
            ORDER BY target_ip ASC, COALESCE(NULLIF(device_bucket_time, ''), NULLIF(bucket_time, ''), local_bucket_time) ASC
            LIMIT 5000
            """
        )
        if not rows:
            rows = self._query(
                """
                SELECT COALESCE(NULLIF(device_aligned_time, ''), collector_time, local_time),
                       local_time, device_aligned_time, clock_offset_ms, target_ip, latency_ms
                FROM fping_samples
                WHERE success = 1 AND latency_ms IS NOT NULL
                ORDER BY target_ip ASC, COALESCE(NULLIF(device_aligned_time, ''), collector_time, local_time) ASC
                LIMIT 5000
                """
            )
        grouped: dict[str, list[tuple[object, object]]] = {}
        tooltips: list[dict[str, object]] = []
        for collected_at, local_time, device_time, offset_ms, target_ip, latency_ms in rows:
            target = str(target_ip or "Ping")
            grouped.setdefault(target, []).append((collected_at, latency_ms))
            tooltips.append(
                {
                    "time": collected_at,
                    "device_time": device_time or collected_at,
                    "local_time": local_time,
                    "clock_offset_ms": offset_ms,
                    "target": target_ip,
                    "latency_ms": latency_ms,
                }
            )
        return ChartData(
            title="Ping 延迟",
            y_label="ms",
            series=[ChartSeries(target, points) for target, points in grouped.items()],
            tooltip_rows=tooltips,
            empty_message="未解析到Ping数据",
        )

    def build_ping_loss_series(self) -> ChartData:
        rows = self._query(
            """
            SELECT COALESCE(NULLIF(device_bucket_time, ''), NULLIF(bucket_time, ''), local_bucket_time),
                   local_bucket_time, device_bucket_time, clock_offset_ms, target_ip, loss_percent, avg_latency_ms
            FROM fping_1s_summary
            ORDER BY target_ip ASC, COALESCE(NULLIF(device_bucket_time, ''), NULLIF(bucket_time, ''), local_bucket_time) ASC
            LIMIT 5000
            """
        )
        grouped: dict[str, list[tuple[object, object]]] = {}
        tooltips: list[dict[str, object]] = []
        if rows:
            for collected_at, local_time, device_time, offset_ms, target_ip, loss_percent, avg_latency in rows:
                target = str(target_ip or "Ping")
                grouped.setdefault(target, []).append((collected_at, loss_percent))
                tooltips.append(
                    {
                        "time": collected_at,
                        "device_time": device_time or collected_at,
                        "local_time": local_time,
                        "clock_offset_ms": offset_ms,
                        "target": target_ip,
                        "loss_percent": loss_percent,
                        "avg_latency_ms": avg_latency,
                    }
                )
        else:
            sample_rows = self._query(
                """
                SELECT COALESCE(NULLIF(device_aligned_time, ''), collector_time, local_time),
                       local_time, device_aligned_time, clock_offset_ms, target_ip, success
                FROM fping_samples
                ORDER BY target_ip ASC, COALESCE(NULLIF(device_aligned_time, ''), collector_time, local_time) ASC
                LIMIT 5000
                """
            )
            windows: dict[str, list[int]] = {}
            window_size = 20
            for collected_at, local_time, device_time, offset_ms, target_ip, success in sample_rows:
                target = str(target_ip or "Ping")
                ok = 1 if int(success or 0) else 0
                window = windows.setdefault(target, [])
                window.append(ok)
                if len(window) > window_size:
                    del window[0]
                loss_percent = round((1 - (sum(window) / len(window))) * 100.0, 2) if window else 0.0
                grouped.setdefault(target, []).append((collected_at, loss_percent))
                tooltips.append(
                    {
                        "time": collected_at,
                        "device_time": device_time or collected_at,
                        "local_time": local_time,
                        "clock_offset_ms": offset_ms,
                        "target": target_ip,
                        "success": bool(ok),
                        "loss_percent": loss_percent,
                    }
                )
        return ChartData(
            title="Ping 丢包率",
            y_label="%",
            series=[ChartSeries(target, points) for target, points in grouped.items()],
            tooltip_rows=tooltips,
            empty_message="未解析到Ping数据",
        )

    def build_interface_rate_series(self) -> ChartData:
        rows = self._query(
            """
            SELECT device_time, direction, total_pps, broadcast_pps, multicast_pps,
                   COALESCE(NULLIF(interface_normalized, ''), interface_name), id
            FROM interface_rate_samples
            WHERE direction IS NOT NULL AND total_pps IS NOT NULL
              AND lower(COALESCE(NULLIF(interface_normalized, ''), interface_name, '')) NOT LIKE 'xge%'
              AND lower(COALESCE(NULLIF(interface_normalized, ''), interface_name, '')) NOT LIKE 'xgigabitethernet%'
              AND lower(COALESCE(NULLIF(interface_normalized, ''), interface_name, '')) NOT LIKE 'ten-gigabitethernet%'
              AND lower(COALESCE(NULLIF(interface_normalized, ''), interface_name, '')) NOT LIKE 'tengigabitethernet%'
            ORDER BY device_time ASC, id ASC
            LIMIT 10000
            """
        )
        grouped: dict[tuple[object, str, str], dict[str, object]] = {}
        for collected_at, direction, total_pps, broadcast_pps, multicast_pps, interface_name, _sample_id in rows:
            direction_text = str(direction or "").lower()
            if direction_text not in {"inbound", "outbound"}:
                continue
            grouped[(collected_at, str(interface_name or ""), direction_text)] = {
                "time": collected_at,
                "direction": direction_text,
                "interface": interface_name,
                "total_pps": total_pps,
                "broadcast_pps": broadcast_pps,
                "multicast_pps": multicast_pps,
            }
        series_points: dict[str, list[tuple[object, object]]] = {}
        tooltip_rows: list[dict[str, object]] = []
        for item in grouped.values():
            direction = str(item["direction"])
            direction_label = "入方向" if direction == "inbound" else "出方向"
            interface = str(item["interface"] or "未识别接口")
            label = f"{interface} {direction_label}PPS"
            series_points.setdefault(label, []).append((item["time"], float(item["total_pps"] or 0)))
            tooltip_rows.append(
                {
                    "time": item["time"],
                    "direction": direction,
                    "interface": interface,
                    "total_pps": float(item["total_pps"] or 0),
                    "broadcast_pps": float(item["broadcast_pps"] or 0),
                    "multicast_pps": float(item["multicast_pps"] or 0),
                }
            )

        def point_sort_key(point: tuple[object, object]) -> tuple[datetime, str]:
            parsed = _parse_time(point[0])
            return (parsed or datetime.max, str(point[0] or ""))

        series = [ChartSeries(name, sorted(points, key=point_sort_key)) for name, points in series_points.items()]
        tooltip_rows = sorted(tooltip_rows, key=lambda item: (_parse_time(item["time"]) or datetime.max, str(item.get("interface") or ""), str(item.get("direction") or "")))
        return ChartData(
            title="接口 PPS",
            y_label="pps",
            series=series,
            tooltip_rows=tooltip_rows,
            empty_message="未解析到接口PPS",
        )

    def build_traffic_rate_series(self) -> ChartData:
        rows = self._iperf_traffic_rows()
        upload: list[tuple[object, object]] = []
        download: list[tuple[object, object]] = []
        total_by_time: dict[object, float] = {}
        tooltips: list[dict[str, object]] = []
        for row in rows:
            time_value = row[0] or row[1]
            if not time_value:
                continue
            mbps = float(row[2] or 0)
            direction = _traffic_direction_label(row[10], row[7])
            target = download if direction == "下行" else upload
            target.append((time_value, mbps))
            total_by_time[time_value] = total_by_time.get(time_value, 0.0) + mbps
            tooltips.append(
                {
                    "time": time_value,
                    "direction": direction,
                    "rate_mbps": mbps,
                    "protocol": str(row[9] or "").upper() or "-",
                    "role": row[7],
                    "server_ip": row[11],
                    "server_port": row[12],
                    "jitter_ms": row[4],
                    "loss_percent": row[5],
                    "retransmits": row[3],
                    "transfer_bytes": row[6],
                    "raw": row[8],
                }
            )

        total = sorted(total_by_time.items(), key=lambda point: (_parse_time(point[0]) or datetime.max, str(point[0] or "")))
        return ChartData(
            title="业务打流",
            y_label="速率（Mbps）",
            series=[ChartSeries("上行速率", upload), ChartSeries("下行速率", download), ChartSeries("总吞吐", total)],
            tooltip_rows=tooltips,
            empty_message="当前会话无打流数据",
        )

    def _iperf_traffic_rows(self) -> list[tuple[object, ...]]:
        """Read the stable traffic columns while tolerating older parsed schemas."""
        if not self.db_path.exists():
            return []
        try:
            with sqlite3.connect(self.db_path) as conn:
                interval_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(iperf_intervals)")}
                if "bitrate_mbps" not in interval_columns:
                    return []
                run_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(iperf_runs)")}

                def interval_expr(name: str, alias: str | None = None) -> str:
                    label = alias or name
                    return f"i.{name} AS {label}" if name in interval_columns else f"NULL AS {label}"

                def run_or_interval_expr(name: str) -> str:
                    if name in run_columns:
                        return f"r.{name}"
                    return f"i.{name}" if name in interval_columns else "NULL"

                time_candidates = [
                    f"NULLIF(i.{name}, '')"
                    for name in ("device_interval_center_time", "device_aligned_time", "interval_center_time", "collector_time")
                    if name in interval_columns
                ]
                if not time_candidates:
                    return []
                time_expr = time_candidates[0] if len(time_candidates) == 1 else f"COALESCE({', '.join(time_candidates)})"
                select = [
                    f"{time_expr} AS metric_time",
                    interval_expr("collector_time"),
                    interval_expr("bitrate_mbps"),
                    interval_expr("retransmits"),
                    interval_expr("jitter_ms"),
                    interval_expr("loss_percent"),
                    interval_expr("transfer_bytes"),
                    interval_expr("role"),
                    interval_expr("raw_line"),
                    f"{run_or_interval_expr('protocol')} AS protocol",
                    f"{run_or_interval_expr('direction')} AS direction",
                    f"{run_or_interval_expr('server_ip')} AS server_ip",
                    f"{run_or_interval_expr('port')} AS port",
                ]
                where = ["i.bitrate_mbps IS NOT NULL"]
                if "role" in interval_columns:
                    where.append("(i.role IS NULL OR LOWER(i.role) NOT IN ('sum', 'sum_sent', 'sum_received', 'sender', 'receiver'))")
                from_clause = "iperf_intervals i LEFT JOIN iperf_runs r ON r.run_id = i.run_id" if run_columns else "iperf_intervals i"
                order_id = "i.id" if "id" in interval_columns else "i.rowid"
                return conn.execute(
                    f"SELECT {', '.join(select)} FROM {from_clause} WHERE {' AND '.join(where)} "
                    f"ORDER BY metric_time ASC, {order_id} ASC LIMIT 20000"
                ).fetchall()
        except sqlite3.Error:
            return []

    def build_switch_rssi_series(self) -> ChartData:
        switch_rows = self._query(
            """
            SELECT device_time, 'terminal_monitor', device_name,
                   old_peer_name, old_peer_mac, old_rssi, old_belong_station, old_belong_section,
                   CASE WHEN old_peer_mac IS NULL OR old_peer_mac = '' OR old_peer_mac LIKE '0000%' THEN 'empty_link' ELSE '' END,
                   new_peer_name, new_peer_mac, new_rssi, new_belong_station, new_belong_section,
                   CASE WHEN new_peer_mac IS NULL OR new_peer_mac = '' OR new_peer_mac LIKE '0000%' THEN 'empty_link' ELSE '' END,
                   switch_reason_code, switch_reason_text,
                   peer_quantity, link_quantity
            FROM switch_realtime_events
            ORDER BY device_time ASC, id ASC
            LIMIT 5000
            """
        )
        active_rows = self._query(
            """
            SELECT collector_time, peer_mac, mr_rssi
            FROM main_link_samples
            WHERE UPPER(link_state) LIKE 'ACTIVE%' AND mr_rssi IS NOT NULL
            ORDER BY collector_time ASC
            LIMIT 10000
            """
        )
        active_points: list[tuple[datetime, object, object, float]] = []
        for collected_at, peer_mac, local_rssi in active_rows:
            parsed_time = _parse_time(collected_at)
            rssi = _normalize_rssi(local_rssi)
            if parsed_time is not None and rssi is not None:
                active_points.append((parsed_time, collected_at, peer_mac, rssi))

        before_by_time: dict[object, tuple[object, object]] = {}
        after_by_time: dict[object, tuple[object, object]] = {}
        tooltips: list[dict[str, object]] = []
        window = timedelta(seconds=30)
        for row in switch_rows:
            event_time = _parse_time(row[0])
            reason_code = row[15]
            reason_text = str(row[16] or "链路切换").strip() or "链路切换"
            before_rssi = _normalize_rssi(row[5])
            after_rssi = _normalize_rssi(row[11])
            if row[8] != "empty_link" and before_rssi is not None:
                before_by_time[row[0]] = (row[0], before_rssi)
            if row[14] != "empty_link" and after_rssi is not None:
                after_by_time[row[0]] = (row[0], after_rssi)
            if event_time is not None:
                for sample_time, collected_at, _peer_mac, rssi in active_points:
                    delta = sample_time - event_time
                    if timedelta(0) <= -delta <= window:
                        before_by_time.setdefault(collected_at, (collected_at, rssi))
                    elif timedelta(0) <= delta <= window:
                        after_by_time.setdefault(collected_at, (collected_at, rssi))
            tooltips.append(
                {
                    "time": row[0],
                    "source": row[1],
                    "device_name": row[2],
                    "from_peer_name": "空链路" if row[8] == "empty_link" else row[3],
                    "from_peer_mac": "-" if row[8] == "empty_link" else row[4],
                    "from_rssi": None if row[8] == "empty_link" else before_rssi,
                    "from_station": row[6],
                    "from_section": row[7],
                    "to_peer_name": "空链路" if row[14] == "empty_link" else row[9],
                    "to_peer_mac": "-" if row[14] == "empty_link" else row[10],
                    "to_rssi": None if row[14] == "empty_link" else after_rssi,
                    "to_station": row[12],
                    "to_section": row[13],
                    "reason_code": reason_code,
                    "reason_text": reason_text,
                    "peer_quantity": row[17],
                    "link_quantity": row[18],
                }
            )
        before = sorted(before_by_time.values(), key=lambda point: (_parse_time(point[0]) or datetime.max, str(point[0] or "")))
        after = sorted(after_by_time.values(), key=lambda point: (_parse_time(point[0]) or datetime.max, str(point[0] or "")))
        return ChartData(
            title="主链路切换前后信号趋势",
            y_label="RSSI",
            series=[ChartSeries("切换前RSSI", before), ChartSeries("切换后RSSI", after)],
            tooltip_rows=tooltips,
            empty_message="未解析到主链路切换日志",
        )

    def build_switch_log_rssi_series(self) -> ChartData:
        switch_rows = self._query(
            """
            SELECT device_time, 'terminal_monitor', device_name,
                   old_peer_name, old_peer_mac, old_rssi, old_belong_station, old_belong_section,
                   CASE WHEN old_peer_mac IS NULL OR old_peer_mac = '' OR old_peer_mac LIKE '0000%' THEN 'empty_link' ELSE '' END,
                   new_peer_name, new_peer_mac, new_rssi, new_belong_station, new_belong_section,
                   CASE WHEN new_peer_mac IS NULL OR new_peer_mac = '' OR new_peer_mac LIKE '0000%' THEN 'empty_link' ELSE '' END,
                   switch_reason_code, switch_reason_text,
                   peer_quantity, link_quantity
            FROM switch_realtime_events
            ORDER BY device_time ASC, id ASC
            LIMIT 5000
            """
        )
        before: list[tuple[object, object]] = []
        after: list[tuple[object, object]] = []
        tooltips: list[dict[str, object]] = []
        events: list[ChartEvent] = []
        seen: set[tuple[str, str, str, str]] = set()
        for row in switch_rows:
            event_time_text = str(row[0] or "")
            event_time = _parse_time(event_time_text)
            if event_time is None:
                continue
            reason_code = row[15]
            reason_text = str(row[16] or "链路切换").strip() or "链路切换"
            dedup_key = (event_time_text, str(row[4] or ""), str(row[10] or ""), str(reason_code or ""))
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            before_rssi = _normalize_rssi(row[5])
            after_rssi = _normalize_rssi(row[11])
            if row[8] != "empty_link" and before_rssi is not None:
                before.append((event_time_text, before_rssi))
            if row[14] != "empty_link" and after_rssi is not None:
                after.append((event_time_text, after_rssi))
            tooltips.append(
                {
                    "time": event_time_text,
                    "source": row[1],
                    "device_name": row[2],
                    "from_peer_name": "空链路" if row[8] == "empty_link" else row[3],
                    "from_peer_mac": "-" if row[8] == "empty_link" else row[4],
                    "from_rssi": None if row[8] == "empty_link" else before_rssi,
                    "from_station": row[6],
                    "from_section": row[7],
                    "to_peer_name": "空链路" if row[14] == "empty_link" else row[9],
                    "to_peer_mac": "-" if row[14] == "empty_link" else row[10],
                    "to_rssi": None if row[14] == "empty_link" else after_rssi,
                    "to_station": row[12],
                    "to_section": row[13],
                    "reason_code": reason_code,
                    "reason_text": reason_text,
                    "peer_quantity": row[17],
                    "link_quantity": row[18],
                }
            )
            events.append(ChartEvent(event_time, "active_link_switch", reason_text, _switch_reason_severity(reason_text, reason_code)))
        before = sorted(before, key=lambda point: (_parse_time(point[0]) or datetime.max, str(point[0] or "")))
        after = sorted(after, key=lambda point: (_parse_time(point[0]) or datetime.max, str(point[0] or "")))
        return ChartData(
            title="主链路切换日志RSSI",
            y_label="RSSI",
            series=[ChartSeries("原AP RSSI", before), ChartSeries("新AP RSSI", after)],
            tooltip_rows=tooltips,
            events=events,
            empty_message="未解析到主链路切换日志",
        )

    def build_switch_reason_summary(self) -> ChartData:
        rows = self._query(
            """
            SELECT COALESCE(switch_reason_code, 0), COALESCE(switch_reason_text, '未知原因'), COUNT(*)
            FROM switch_realtime_events
            GROUP BY COALESCE(switch_reason_code, 0), COALESCE(switch_reason_text, '未知原因')
            ORDER BY 1
            """
        )
        return ChartData(
            title="主链路切换原因统计",
            y_label="次数",
            series=[ChartSeries("次数", [(row[1], row[2]) for row in rows])],
            tooltip_rows=[{"reason_code": row[0], "reason_text": row[1], "count": row[2]} for row in rows],
            empty_message="未解析到主链路切换日志",
        )

    def _query(self, sql: str, params: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
        if not self.db_path.exists():
            return []
        with sqlite3.connect(self.db_path) as conn:
            try:
                return conn.execute(sql, params).fetchall()
            except sqlite3.Error:
                return []

    def _scalar(self, sql: str, params: tuple[object, ...] = ()) -> int:
        rows = self._query(sql, params)
        if not rows:
            return 0
        try:
            return int(rows[0][0] or 0)
        except (TypeError, ValueError):
            return 0

    def _read_session_meta(self) -> dict[str, object]:
        meta_path = self.db_path.parent.parent / "session_meta.json"
        if not meta_path.exists():
            return {}
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _nearest_channel_busy_index(self) -> list[dict[str, object]]:
        rows = self._query(
            """
            SELECT device_time, radio, ctl_busy, tx_busy, rx_busy
            FROM channel_busy_records
            ORDER BY device_time ASC
            LIMIT 10000
            """
        )
        result: list[dict[str, object]] = []
        for collected_at, radio, ctl_busy, tx_busy, rx_busy in rows:
            timestamp = _parse_time(collected_at)
            if timestamp is None:
                continue
            result.append({"timestamp": timestamp, "radio": radio, "ctl_busy": ctl_busy, "tx_busy": tx_busy, "rx_busy": rx_busy})
        return result

    def _nearest_ping_index(self) -> list[dict[str, object]]:
        rows = self._query(
            """
            SELECT COALESCE(NULLIF(device_bucket_time, ''), NULLIF(bucket_time, ''), local_bucket_time),
                   loss_percent, avg_latency_ms, max_latency_ms
            FROM fping_1s_summary
            ORDER BY COALESCE(NULLIF(device_bucket_time, ''), NULLIF(bucket_time, ''), local_bucket_time) ASC
            LIMIT 10000
            """
        )
        result: list[dict[str, object]] = []
        if rows:
            for collected_at, loss_percent, avg_latency, max_latency in rows:
                timestamp = _parse_time(collected_at)
                if timestamp is None:
                    continue
                result.append({"timestamp": timestamp, "loss_percent": loss_percent, "avg_latency": avg_latency, "max_latency": max_latency})
            return result
        rows = self._query(
            """
            SELECT COALESCE(NULLIF(device_aligned_time, ''), collector_time, local_time), success, latency_ms
            FROM fping_samples
            ORDER BY COALESCE(NULLIF(device_aligned_time, ''), collector_time, local_time) ASC
            LIMIT 10000
            """
        )
        for collected_at, success, latency_ms in rows:
            timestamp = _parse_time(collected_at)
            if timestamp is None:
                continue
            result.append(
                {
                    "timestamp": timestamp,
                    "loss_percent": 0 if int(success or 0) else 100,
                    "avg_latency": latency_ms if int(success or 0) and latency_ms is not None else None,
                    "max_latency": latency_ms if int(success or 0) and latency_ms is not None else None,
                }
            )
        return result

    def _nearest_interface_index(self) -> list[dict[str, object]]:
        rows = self._query(
            """
            SELECT device_time, direction, total_pps
            FROM interface_rate_samples
            WHERE direction IS NOT NULL AND total_pps IS NOT NULL
              AND lower(COALESCE(NULLIF(interface_normalized, ''), interface_name, '')) NOT LIKE 'xge%'
              AND lower(COALESCE(NULLIF(interface_normalized, ''), interface_name, '')) NOT LIKE 'xgigabitethernet%'
              AND lower(COALESCE(NULLIF(interface_normalized, ''), interface_name, '')) NOT LIKE 'ten-gigabitethernet%'
              AND lower(COALESCE(NULLIF(interface_normalized, ''), interface_name, '')) NOT LIKE 'tengigabitethernet%'
            ORDER BY device_time ASC
            LIMIT 10000
            """
        )
        grouped: dict[datetime, dict[str, object]] = {}
        for collected_at, direction, total_pps in rows:
            timestamp = _parse_time(collected_at)
            if timestamp is None:
                continue
            item = grouped.setdefault(timestamp, {"timestamp": timestamp, "inbound_pps": None, "outbound_pps": None})
            key = "inbound_pps" if str(direction or "").lower() == "inbound" else "outbound_pps" if str(direction or "").lower() == "outbound" else ""
            if key:
                item[key] = float(item[key] or 0) + float(total_pps or 0)
        return [grouped[key] for key in sorted(grouped)]

    def _time_sync_status_text(self) -> str:
        rows = self._query(
            """
            SELECT COUNT(*), MIN(offset_ms), MAX(offset_ms), AVG(offset_ms)
            FROM time_sync_samples
            """
        )
        if not rows or not rows[0] or int(rows[0][0] or 0) <= 0:
            return "时间同步：未建立，fping 使用本地时间"
        count, min_offset, max_offset, avg_offset = rows[0]
        spread = abs(float(max_offset or 0) - float(min_offset or 0))
        status = "偏移波动较大，请检查设备时钟或采集延迟" if spread > 3000 else "已建立"
        aligned_count = self._scalar("SELECT COUNT(*) FROM fping_1s_summary WHERE device_bucket_time IS NOT NULL AND device_bucket_time <> ''")
        align_text = "已使用设备时间" if aligned_count > 0 else "未建立，使用本地时间"
        return (
            f"时间同步：{status}，样本 {int(count or 0)} 个，"
            f"偏移范围：{_format_offset_ms(min_offset)} ~ {_format_offset_ms(max_offset)}，"
            f"平均偏移：{_format_offset_ms(avg_offset)}，fping 对齐：{align_text}"
        )


def _parse_time(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _normalize_rssi(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number == 0:
        return None
    return abs(number)


def _format_offset_ms(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    sign = "+" if number >= 0 else ""
    return f"{sign}{number:.0f}ms"


def _nearest_by_time(rows: list[dict[str, object]], timestamp: datetime, *, max_seconds: float, predicate=None) -> dict[str, object] | None:
    candidates = rows if predicate is None else [row for row in rows if predicate(row)]
    if not candidates:
        return None
    nearest = min(candidates, key=lambda row: abs((row["timestamp"] - timestamp).total_seconds()))  # type: ignore[operator]
    delta = abs((nearest["timestamp"] - timestamp).total_seconds())  # type: ignore[operator]
    return nearest if delta <= max_seconds else None


def _standby_links_near(rows: list[dict[str, object]], timestamp: datetime, radio: object, *, max_seconds: float = 0.5, limit: int = 5) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    radio_text = str(radio or "")
    for row in rows:
        row_time = row.get("timestamp")
        if not isinstance(row_time, datetime):
            continue
        if radio_text and str(row.get("radio") or "") != radio_text:
            continue
        if abs((row_time - timestamp).total_seconds()) > max_seconds:
            continue
        result.append(
            {
                "peer_name": row.get("peer_name") or row.get("peer_mac") or "-",
                "peer_mac": row.get("peer_mac") or "-",
                "belong_station": row.get("station") or "-",
                "belong_section": row.get("section") or "-",
                "rssi": row.get("rssi"),
            }
        )

    def sort_key(item: dict[str, object]) -> float:
        try:
            return float(item.get("rssi") or -9999)
        except (TypeError, ValueError):
            return -9999.0

    return sorted(result, key=sort_key, reverse=True)[:limit]


def _traffic_direction_label(direction: object, role: object) -> str:
    text = str(direction or "").strip().casefold()
    role_text = str(role or "").strip().casefold()
    if text in {"download", "down", "reverse"} or role_text in {"sum_received", "receiver"}:
        return "下行"
    if text in {"bidirectional", "both"}:
        return "双向"
    return "上行"


def _switch_reason_severity(reason: object, code: object) -> str:
    text = str(reason or "").casefold()
    code_text = str(code or "").strip()
    if code_text in {"4", "5"} or "fault" in text or "断开" in text or "强制" in text:
        return "warning"
    if "better" in text or "rssi" in text:
        return "info"
    return "info"
