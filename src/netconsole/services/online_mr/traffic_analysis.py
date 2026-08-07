from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import datetime
from typing import Any


_SUMMARY_ROLES = {"sum", "sum_sent", "sum_received", "sender", "receiver"}


def _number(value: object) -> float | None:
    try:
        parsed = float(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None
    return parsed if parsed is not None and parsed == parsed else None


def _integer(value: object) -> int | None:
    parsed = _number(value)
    return int(parsed) if parsed is not None else None


def _time(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    text = str(value).replace("T", " ")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _direction_label(direction: object) -> str:
    text = str(direction or "").strip().lower()
    if text in {"download", "down", "downlink", "reverse", "server_to_mr"}:
        return "下行"
    if text in {"upload", "up", "uplink", "mr_to_server"}:
        return "上行"
    if text in {"bidirectional", "both", "full"}:
        return "双向"
    return str(direction or "未注明")


def _protocol(value: object) -> str:
    return str(value or "").strip().upper() or "未知"


def _interval_duration(row: dict[str, Any]) -> float:
    start = _number(row.get("interval_start_sec"))
    end = _number(row.get("interval_end_sec"))
    if start is not None and end is not None and end > start:
        return end - start
    return 0.0


def _preferred_rows(rows: list[dict[str, Any]], direction: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    measurements = [row for row in rows if str(row.get("role") or "interval").strip().lower() not in _SUMMARY_ROLES]
    summaries = [row for row in rows if str(row.get("role") or "").strip().lower() in _SUMMARY_ROLES]
    return (measurements or summaries, summaries)


def _summary_row(rows: list[dict[str, Any]], roles: set[str]) -> dict[str, Any] | None:
    candidates = [row for row in rows if str(row.get("role") or "").strip().lower() in roles]
    if not candidates:
        return None
    return max(candidates, key=lambda row: (_number(row.get("interval_end_sec")) or 0.0, _number(row.get("transfer_bytes")) or 0.0))


def _stats(rows: list[dict[str, Any]], summaries: list[dict[str, Any]], direction: str, protocol: str) -> dict[str, Any]:
    rates = [(float(row["bitrate_mbps"]), _interval_duration(row)) for row in rows if _number(row.get("bitrate_mbps")) is not None]
    weighted_duration = sum(duration for _, duration in rates)
    average = (
        sum(rate * (duration or 1.0) for rate, duration in rates) / (weighted_duration or len(rates))
        if rates
        else None
    )
    durations = [_interval_duration(row) for row in rows]
    duration_seconds = sum(durations) if any(durations) else None
    sent_summary = _summary_row(summaries, {"sum_sent", "sender"})
    received_summary = _summary_row(summaries, {"sum_received", "receiver"})
    sent_bytes = _number(sent_summary.get("transfer_bytes")) if sent_summary else None
    received_bytes = _number(received_summary.get("transfer_bytes")) if received_summary else None
    if sent_bytes is None and direction in {"upload", "up", "uplink", "mr_to_server"}:
        sent_values = [_number(row.get("transfer_bytes")) for row in rows]
        sent_bytes = sum(value for value in sent_values if value is not None) if any(value is not None for value in sent_values) else None
    if received_bytes is None and direction in {"download", "down", "downlink", "reverse", "server_to_mr"}:
        received_values = [_number(row.get("transfer_bytes")) for row in rows]
        received_bytes = sum(value for value in received_values if value is not None) if any(value is not None for value in received_values) else None

    packet_rows = [row for row in rows if _integer(row.get("total_packets")) is not None]
    sent_packets = sum(_integer(row.get("total_packets")) or 0 for row in packet_rows) if packet_rows else None
    lost_packets = sum(_integer(row.get("lost_packets")) or 0 for row in packet_rows) if packet_rows else None
    received_packets = sent_packets - lost_packets if sent_packets is not None and lost_packets is not None else None
    loss_percent = (lost_packets * 100.0 / sent_packets) if sent_packets else None
    if loss_percent is None:
        loss_values = [(float(row["loss_percent"]), _interval_duration(row)) for row in rows if _number(row.get("loss_percent")) is not None]
        loss_duration = sum(duration for _, duration in loss_values)
        loss_percent = sum(value * (duration or 1.0) for value, duration in loss_values) / (loss_duration or len(loss_values)) if loss_values else None

    jitter = [_number(row.get("jitter_ms")) for row in rows]
    jitter_values = [value for value in jitter if value is not None]
    jitter_duration = sum(_interval_duration(row) for row in rows if _number(row.get("jitter_ms")) is not None)
    jitter_average = (
        sum(value * (_interval_duration(row) or 1.0) for row, value in zip(rows, jitter) if value is not None)
        / (jitter_duration or len(jitter_values))
        if jitter_values
        else None
    )
    retransmit_values = [_integer(row.get("retransmits")) for row in rows]
    retransmits = sum(value or 0 for value in retransmit_values) if any(value is not None for value in retransmit_values) else None
    is_udp = protocol == "UDP"
    return {
        "record_count": len(rows),
        "duration_seconds": duration_seconds,
        "average_mbps": average,
        "minimum_mbps": min((rate for rate, _ in rates), default=None),
        "maximum_mbps": max((rate for rate, _ in rates), default=None),
        "sent_bytes": sent_bytes,
        "received_bytes": received_bytes,
        "lost_bytes": None,
        "sent_packets": sent_packets if is_udp else None,
        "received_packets": received_packets if is_udp else None,
        "lost_packets": lost_packets if is_udp else None,
        "loss_percent": loss_percent if is_udp else None,
        "average_jitter_ms": jitter_average if is_udp else None,
        "minimum_jitter_ms": min(jitter_values, default=None) if is_udp else None,
        "maximum_jitter_ms": max(jitter_values, default=None) if is_udp else None,
        "retransmits": retransmits if not is_udp else None,
        "loss_source": "iperf3 interval packets" if is_udp and loss_percent is not None else None,
        "jitter_source": "iperf3 interval jitter" if is_udp and jitter_average is not None else None,
        "retransmit_source": "iperf3 interval retransmits" if not is_udp and retransmits is not None else None,
    }


def _read_rows(conn: sqlite3.Connection, start_time: str | None, end_time: str | None) -> list[dict[str, Any]]:
    tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "iperf_intervals" not in tables:
        return []
    interval_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(iperf_intervals)")}
    run_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(iperf_runs)")} if "iperf_runs" in tables else set()
    time_candidates = [
        f"NULLIF(i.{name}, '')"
        for name in ("device_interval_center_time", "device_aligned_time", "interval_center_time", "collector_time")
        if name in interval_columns
    ]
    if not time_candidates:
        return []
    time_expr = time_candidates[0] if len(time_candidates) == 1 else f"COALESCE({', '.join(time_candidates)})"
    where = [f"{time_expr} IS NOT NULL"]
    params: list[Any] = []
    if start_time:
        where.append(f"{time_expr} >= ?")
        params.append(start_time)
    if end_time:
        where.append(f"{time_expr} <= ?")
        params.append(end_time)
    run_select_parts: list[str] = []
    for name in ("protocol", "direction", "server_ip", "port", "parallel", "target_bandwidth", "status", "started_at", "ended_at"):
        if name in run_columns:
            run_select_parts.append(f"r.{name} AS run_{name}")
        elif name in interval_columns:
            run_select_parts.append(f"i.{name} AS run_{name}")
    run_select = ", ".join(run_select_parts)
    interval_select = ", ".join(
        f"i.{name} AS {name}" for name in ("run_id", "interval_start_sec", "interval_end_sec", "transfer_bytes", "bitrate_mbps", "jitter_ms", "lost_packets", "total_packets", "loss_percent", "retransmits", "role", "source_event_key") if name in interval_columns
    )
    if not interval_select:
        return []
    select = interval_select + (f", {run_select}" if run_select else "")
    join = " LEFT JOIN iperf_runs r ON r.run_id = i.run_id" if run_columns else ""
    order_column = "i.id" if "id" in interval_columns else "sample_time"
    cursor = conn.execute(
        f"SELECT {select}, {time_expr} AS sample_time FROM iperf_intervals i{join} WHERE {' AND '.join(where)} ORDER BY sample_time, {order_column}",
        params,
    )
    columns = [str(item[0]) for item in cursor.description or ()]
    return [dict(row) if isinstance(row, sqlite3.Row) else dict(zip(columns, row)) for row in cursor.fetchall()]


def _aggregate_stats(items: list[dict[str, Any]], protocol: str) -> dict[str, Any]:
    durations = [_number(item.get("duration_seconds")) or 0.0 for item in items]
    rates = [(_number(item.get("average_mbps")), duration) for item, duration in zip(items, durations) if _number(item.get("average_mbps")) is not None]
    total_duration = sum(durations) or None
    sent_values = [_number(item.get("sent_bytes")) for item in items]
    received_values = [_number(item.get("received_bytes")) for item in items]
    packet_values = [(item.get("sent_packets"), item.get("lost_packets")) for item in items]
    packet_values = [(int(sent), int(lost)) for sent, lost in packet_values if sent is not None and lost is not None]
    jitter_items = [(_number(item.get("average_jitter_ms")), duration) for item, duration in zip(items, durations) if _number(item.get("average_jitter_ms")) is not None]
    retransmit_values = [_integer(item.get("retransmits")) for item in items]
    is_udp = protocol == "UDP"
    return {
        "record_count": sum(int(item.get("record_count") or 0) for item in items),
        "duration_seconds": total_duration,
        "average_mbps": sum(value * (duration or 1.0) for value, duration in rates) / (sum(duration for _, duration in rates) or len(rates)) if rates else None,
        "minimum_mbps": min((_number(item.get("minimum_mbps")) for item in items if _number(item.get("minimum_mbps")) is not None), default=None),
        "maximum_mbps": max((_number(item.get("maximum_mbps")) for item in items if _number(item.get("maximum_mbps")) is not None), default=None),
        "sent_bytes": sum(value for value in sent_values if value is not None) if any(value is not None for value in sent_values) else None,
        "received_bytes": sum(value for value in received_values if value is not None) if any(value is not None for value in received_values) else None,
        "lost_bytes": None,
        "sent_packets": sum(sent for sent, _ in packet_values) if is_udp and packet_values else None,
        "received_packets": sum(sent - lost for sent, lost in packet_values) if is_udp and packet_values else None,
        "lost_packets": sum(lost for _, lost in packet_values) if is_udp and packet_values else None,
        "loss_percent": (sum(lost for _, lost in packet_values) * 100.0 / sum(sent for sent, _ in packet_values)) if is_udp and packet_values and sum(sent for sent, _ in packet_values) else None,
        "average_jitter_ms": sum(value * (duration or 1.0) for value, duration in jitter_items) / (sum(duration for _, duration in jitter_items) or len(jitter_items)) if is_udp and jitter_items else None,
        "minimum_jitter_ms": min((value for value, _ in jitter_items), default=None) if is_udp else None,
        "maximum_jitter_ms": max((value for value, _ in jitter_items), default=None) if is_udp else None,
        "retransmits": sum(value or 0 for value in retransmit_values) if not is_udp and any(value is not None for value in retransmit_values) else None,
        "loss_source": "iperf3 interval packets" if is_udp and packet_values else None,
        "jitter_source": "iperf3 interval jitter" if is_udp and jitter_items else None,
        "retransmit_source": "iperf3 interval retransmits" if not is_udp and any(value is not None for value in retransmit_values) else None,
    }


def build_iperf_traffic_overview(
    conn: sqlite3.Connection,
    *,
    start_time: str | None = None,
    end_time: str | None = None,
) -> dict[str, Any]:
    rows = _read_rows(conn, start_time, end_time)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("run_id") or "default")].append(row)
    directions: list[dict[str, Any]] = []
    for run_id, run_rows in grouped.items():
        first = run_rows[0]
        protocol = _protocol(first.get("run_protocol"))
        direction = str(first.get("run_direction") or "").strip().lower()
        selected, summaries = _preferred_rows(run_rows, direction)
        stats = _stats(selected, summaries, direction, protocol)
        samples = [row.get("sample_time") for row in selected if row.get("sample_time")]
        directions.append({
            **stats,
            "run_id": run_id,
            "label": _direction_label(direction),
            "protocol": protocol,
            "direction": direction,
            "status": str(first.get("run_status") or "未知"),
            "server_ip": str(first.get("run_server_ip") or ""),
            "port": _integer(first.get("run_port")),
            "parallel": _integer(first.get("run_parallel")),
            "target_bandwidth": first.get("run_target_bandwidth"),
            "started_at": min(samples) if samples else first.get("run_started_at"),
            "ended_at": max(samples) if samples else first.get("run_ended_at"),
        })
    directions.sort(key=lambda item: (str(item.get("started_at") or ""), str(item.get("run_id") or "")))
    overall_protocols: set[str] = set()
    overall_directions: set[str] = set()
    for run_id, run_rows in grouped.items():
        first = run_rows[0]
        direction = str(first.get("run_direction") or "").strip().lower()
        overall_protocols.add(_protocol(first.get("run_protocol")))
        overall_directions.add(_direction_label(direction))
    overall_protocol = next(iter(overall_protocols)) if len(overall_protocols) == 1 else ""
    overall = _aggregate_stats(directions, overall_protocol)
    started = min((item.get("started_at") for item in directions if item.get("started_at")), default=None)
    ended = max((item.get("ended_at") for item in directions if item.get("ended_at")), default=None)
    note = ""
    if not rows:
        note = "暂无可靠统计"
    elif overall.get("sent_bytes") is None or overall.get("received_bytes") is None:
        note = "接收、丢失数据仅在 iperf3 原始结果提供对应字段时统计"
    return {
        "protocol": next(iter(overall_protocols)) if len(overall_protocols) == 1 else ("多协议" if overall_protocols else ""),
        "direction": "、".join(sorted(overall_directions)) if overall_directions else "",
        "status": "完成" if directions and all(item.get("status") in {"COMPLETED", "PARSED", "STOPPED", "SUCCEEDED"} for item in directions) else ("部分" if directions else "无数据"),
        "server_ip": str(directions[0].get("server_ip") or "") if directions else "",
        "port": directions[0].get("port") if directions else None,
        "parallel": max((item.get("parallel") or 0 for item in directions), default=None) or None,
        "started_at": started,
        "ended_at": ended,
        "overall": overall,
        "directions": directions,
        "data_quality_note": note,
    }
