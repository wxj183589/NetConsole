from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from netconsole.services.online_mr_parser import parse_channel_busy_text


@dataclass(frozen=True)
class ChartSeries:
    name: str
    points: list[tuple[object, object]]


@dataclass(frozen=True)
class ChartData:
    title: str
    y_label: str
    series: list[ChartSeries] = field(default_factory=list)
    tooltip_rows: list[dict[str, object]] = field(default_factory=list)
    empty_message: str = "无数据"

    @property
    def has_data(self) -> bool:
        return any(series.points for series in self.series)


@dataclass(frozen=True)
class InteractiveChartPoint:
    timestamp: datetime
    timestamp_label: str
    device_name: str = ""
    radio_id: object = None
    peer_name: str = ""
    peer_mac: str = ""
    bssid: str = ""
    mesh_interface: str = ""
    station: str = ""
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
    raw: str = ""


class OnlineMrChartBuilder:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)

    def build_active_rssi_series(self) -> ChartData:
        rows = self._query(
            """
            SELECT s.collected_at, l.radio, l.peer_mac_raw, l.local_rssi_db, l.link_state
            FROM live_samples s
            JOIN live_mesh_links l ON l.sample_id = s.id
            WHERE UPPER(l.link_state) LIKE 'ACTIVE%' AND l.local_rssi_db IS NOT NULL
            ORDER BY s.collected_at ASC
            LIMIT 5000
            """
        )
        return ChartData(
            title="主链路 RSSI",
            y_label="RSSI",
            series=[ChartSeries("当前Active MR侧RSSI", [(row[0], abs(float(row[3]))) for row in rows])],
            tooltip_rows=[{"time": row[0], "radio": row[1], "peer_mac": row[2], "rssi": row[3], "status": row[4]} for row in rows],
            empty_message="未解析到主链路RSSI",
        )

    def build_active_rssi_interactive_points(self, session_id: str | None = None, device_filter: object = None, time_range: tuple[object, object] | None = None) -> list[InteractiveChartPoint]:
        _ = device_filter
        meta = self._read_session_meta()
        params: list[object] = []
        where = ["UPPER(l.link_state) LIKE 'ACTIVE%'", "l.local_rssi_db IS NOT NULL"]
        if session_id:
            where.append("s.session_id = ?")
            params.append(session_id)
        if time_range:
            if time_range[0] is not None:
                where.append("s.collected_at >= ?")
                params.append(str(time_range[0]))
            if time_range[1] is not None:
                where.append("s.collected_at <= ?")
                params.append(str(time_range[1]))
        rows = self._query(
            f"""
            SELECT s.collected_at, s.session_id, l.radio, l.link_state, l.peer_mac_raw, l.peer_mac_normalized,
                   l.establish_time, l.duration_seconds, l.link_count, l.local_rssi_db, l.peer_rssi_db
            FROM live_samples s
            JOIN live_mesh_links l ON l.sample_id = s.id
            WHERE {" AND ".join(where)}
            ORDER BY s.collected_at ASC
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
            ping = _nearest_by_time(pings, timestamp, max_seconds=10)
            pps = _nearest_by_time(interface, timestamp, max_seconds=10)
            points.append(
                InteractiveChartPoint(
                    timestamp=timestamp,
                    timestamp_label=str(row[0] or ""),
                    device_name=str(meta.get("device_name") or ""),
                    radio_id=radio,
                    peer_name=str(row[4] or ""),
                    peer_mac=str(row[4] or row[5] or ""),
                    bssid="",
                    mesh_interface="",
                    station="",
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
            SELECT s.collected_at, cb.radio, cb.tx_busy, cb.rx_busy, cb.raw_text
            FROM live_channel_busy cb
            JOIN live_samples s ON s.id = cb.sample_id
            ORDER BY s.collected_at ASC
            LIMIT 5000
            """
        )
        ctl_values: list[tuple[object, object]] = []
        tx_values: list[tuple[object, object]] = []
        rx_values: list[tuple[object, object]] = []
        tooltips: list[dict[str, object]] = []
        for collected_at, radio, tx_busy, rx_busy, raw_text in rows:
            parsed = parse_channel_busy_text(str(raw_text or ""))
            ctl_busy = parsed[0].get("ctl_busy") if parsed else None
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
            SELECT collected_at, target_ip, latency_ms
            FROM ping_samples
            WHERE success = 1 AND latency_ms IS NOT NULL
            ORDER BY collected_at ASC
            LIMIT 5000
            """
        )
        return ChartData(
            title="Ping 延迟",
            y_label="ms",
            series=[ChartSeries("RTT", [(row[0], row[2]) for row in rows])],
            tooltip_rows=[{"time": row[0], "target": row[1], "latency_ms": row[2]} for row in rows],
            empty_message="未解析到Ping数据",
        )

    def build_ping_loss_series(self) -> ChartData:
        rows = self._query(
            """
            SELECT collected_at, target_ip, success
            FROM ping_samples
            ORDER BY collected_at ASC
            LIMIT 5000
            """
        )
        points = [(row[0], 0 if int(row[2] or 0) else 100) for row in rows]
        return ChartData(
            title="Ping 丢包率",
            y_label="%",
            series=[ChartSeries("丢包率", points)],
            tooltip_rows=[{"time": row[0], "target": row[1], "loss_percent": 0 if int(row[2] or 0) else 100} for row in rows],
            empty_message="未解析到Ping数据",
        )

    def build_interface_rate_series(self) -> ChartData:
        rows = self._query(
            """
            SELECT collected_at, direction, total_pps, broadcast_pps, multicast_pps, interface_name, sample_id
            FROM live_interface_rates
            WHERE direction IS NOT NULL AND total_pps IS NOT NULL
            ORDER BY collected_at ASC, sample_id ASC
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
        totals: dict[tuple[str, object], float] = {}
        tooltips: dict[tuple[str, object], dict[str, object]] = {}
        for item in grouped.values():
            key = (str(item["direction"]), item["time"])
            totals[key] = totals.get(key, 0.0) + float(item["total_pps"] or 0)
            tooltip = tooltips.setdefault(
                key,
                {"time": item["time"], "direction": item["direction"], "interfaces": [], "total_pps": 0.0, "broadcast_pps": 0.0, "multicast_pps": 0.0},
            )
            if item["interface"]:
                tooltip["interfaces"].append(item["interface"])
            tooltip["total_pps"] = float(tooltip["total_pps"] or 0) + float(item["total_pps"] or 0)
            tooltip["broadcast_pps"] = float(tooltip["broadcast_pps"] or 0) + float(item["broadcast_pps"] or 0)
            tooltip["multicast_pps"] = float(tooltip["multicast_pps"] or 0) + float(item["multicast_pps"] or 0)

        def point_sort_key(point: tuple[object, object]) -> tuple[datetime, str]:
            parsed = _parse_time(point[0])
            return (parsed or datetime.max, str(point[0] or ""))

        inbound = sorted([(time_value, value) for (direction, time_value), value in totals.items() if direction == "inbound"], key=point_sort_key)
        outbound = sorted([(time_value, value) for (direction, time_value), value in totals.items() if direction == "outbound"], key=point_sort_key)
        tooltip_rows = [tooltips[key] for key in sorted(tooltips, key=lambda item: (_parse_time(item[1]) or datetime.max, item[0], str(item[1] or "")))]
        return ChartData(
            title="接口 PPS",
            y_label="pps",
            series=[ChartSeries("入方向总PPS", inbound), ChartSeries("出方向总PPS", outbound)],
            tooltip_rows=tooltip_rows,
            empty_message="未解析到接口PPS",
        )

    def build_switch_rssi_series(self) -> ChartData:
        switch_rows = self._query(
            """
            SELECT log_time, source, device_name, from_peer_name, from_peer_mac, from_peer_rssi, from_resolve_rule,
                   to_peer_name, to_peer_mac, to_peer_rssi, to_resolve_rule, switch_reason_code, switch_reason_text,
                   peer_quantity, link_quantity
            FROM live_active_link_switch_logs
            WHERE source = 'terminal_monitor'
            ORDER BY log_time ASC, id ASC
            LIMIT 5000
            """
        )
        active_rows = self._query(
            """
            SELECT s.collected_at, l.peer_mac_raw, l.local_rssi_db
            FROM live_samples s
            JOIN live_mesh_links l ON l.sample_id = s.id
            WHERE UPPER(l.link_state) LIKE 'ACTIVE%' AND l.local_rssi_db IS NOT NULL
            ORDER BY s.collected_at ASC
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
            before_rssi = _normalize_rssi(row[5])
            after_rssi = _normalize_rssi(row[9])
            if row[6] != "empty_link" and before_rssi is not None:
                before_by_time[row[0]] = (row[0], before_rssi)
            if row[10] != "empty_link" and after_rssi is not None:
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
                    "from_peer_name": "空链路" if row[6] == "empty_link" else row[3],
                    "from_peer_mac": "-" if row[6] == "empty_link" else row[4],
                    "from_rssi": None if row[6] == "empty_link" else before_rssi,
                    "to_peer_name": "空链路" if row[10] == "empty_link" else row[7],
                    "to_peer_mac": "-" if row[10] == "empty_link" else row[8],
                    "to_rssi": None if row[10] == "empty_link" else after_rssi,
                    "reason_code": row[11],
                    "reason_text": row[12],
                    "peer_quantity": row[13],
                    "link_quantity": row[14],
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

    def build_switch_reason_summary(self) -> ChartData:
        rows = self._query(
            """
            SELECT COALESCE(switch_reason_code, 0), COALESCE(switch_reason_text, '未知原因'), COUNT(*)
            FROM live_active_link_switch_logs
            WHERE source = 'terminal_monitor'
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
            SELECT s.collected_at, cb.radio, cb.tx_busy, cb.rx_busy, cb.raw_text
            FROM live_channel_busy cb
            JOIN live_samples s ON s.id = cb.sample_id
            ORDER BY s.collected_at ASC
            LIMIT 10000
            """
        )
        result: list[dict[str, object]] = []
        for collected_at, radio, tx_busy, rx_busy, raw_text in rows:
            timestamp = _parse_time(collected_at)
            if timestamp is None:
                continue
            parsed = parse_channel_busy_text(str(raw_text or ""))
            ctl_busy = parsed[0].get("ctl_busy") if parsed else None
            result.append({"timestamp": timestamp, "radio": radio, "ctl_busy": ctl_busy, "tx_busy": tx_busy, "rx_busy": rx_busy})
        return result

    def _nearest_ping_index(self) -> list[dict[str, object]]:
        rows = self._query(
            """
            SELECT collected_at, success, latency_ms
            FROM ping_samples
            ORDER BY collected_at ASC
            LIMIT 10000
            """
        )
        result: list[dict[str, object]] = []
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
            SELECT collected_at, direction, total_pps
            FROM live_interface_rates
            WHERE direction IS NOT NULL AND total_pps IS NOT NULL
            ORDER BY collected_at ASC
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


def _nearest_by_time(rows: list[dict[str, object]], timestamp: datetime, *, max_seconds: int, predicate=None) -> dict[str, object] | None:
    candidates = rows if predicate is None else [row for row in rows if predicate(row)]
    if not candidates:
        return None
    nearest = min(candidates, key=lambda row: abs((row["timestamp"] - timestamp).total_seconds()))  # type: ignore[operator]
    delta = abs((nearest["timestamp"] - timestamp).total_seconds())  # type: ignore[operator]
    return nearest if delta <= max_seconds else None
