"""Bounded streaming selection for the existing MESH links query."""
from __future__ import annotations

from collections import deque
from datetime import datetime
from statistics import median
from typing import Any, Iterable

METRIC_FIELDS = {
    "rssi": ("local_rssi_db", "peer_rssi_db"),
    "cpu": ("local_cpu_percent", "peer_cpu_percent"),
    "memory": ("local_mem_percent", "peer_mem_percent"),
    "busy": ("local_tx_busy", "peer_tx_busy", "local_rx_busy", "peer_rx_busy"),
    "rate": ("local_rate_raw", "peer_rate_raw"),
    "noise": ("local_noise_dbm", "peer_noise_dbm"),
    "tx_des_free_cnt": ("local_tx_des_free_cnt", "peer_tx_des_free_cnt"),
    "counters": ("local_tx", "peer_tx", "local_rx", "peer_rx", "local_retry", "peer_retry",
                 "local_err", "peer_err", "local_tx_garp", "peer_rx_garp", "local_tx_mul_join", "peer_rx_mul_join"),
}


def select_monitor_rows(rows: Iterable[dict[str, Any]], group: str, start: str, end: str, budget: int):
    """Keep bucket extrema/nulls and both sides of every identity/role boundary.

    Memory is bounded by the response budget. Dense boundary windows fail explicitly
    instead of silently deleting switching evidence. Counters are differenced BEFORE
    sampling, partitioned by physical link/build and historical role is left intact.
    """
    fields = METRIC_FIELDS[group]
    low, high = datetime.fromisoformat(start).timestamp(), datetime.fromisoformat(end).timestamp()
    buckets = max(1, budget // (8 * (len(fields) + 2)))
    extrema: dict[tuple, dict[str, Any]] = {}
    boundaries: dict[int, dict[str, Any]] = {}
    previous: dict[tuple, dict[str, Any]] = {}
    physical_previous: dict[tuple, dict[str, Any]] = {}
    counters: dict[tuple, dict[str, Any]] = {}
    intervals: deque[float] = deque(maxlen=101)
    total = zero = 0
    for row in rows:
        row = dict(row)
        total += 1
        zero += row.get("link_count") == 0
        key = (row.get("source_file_id"), row.get("radio"), row.get("peer_mac_normalized"), row.get("establish_time"))
        old_counter = counters.get(key)
        if group == "counters":
            for field in fields:
                value, before = row.get(field), old_counter.get(field) if old_counter else None
                if value is not None and before is not None and value < before:
                    boundaries[row["id"]] = row
                    boundaries[old_counter["id"]] = old_counter
                row[field + "_delta"] = value - before if (value is not None and before is not None and value >= before and row.get("link_count") != 0 and row["sample_time"] > old_counter["sample_time"]) else None
            counters[key] = row
            if len(counters) > budget:
                raise ValueError("当前窗口链路过多，请缩小时间范围或选择单个 AP")
        lane = (row.get("source_file_id"), row.get("radio"), row.get("link_state"))
        physical_old = physical_previous.get(key)
        if physical_old is not None and physical_old.get("link_state") != row.get("link_state"):
            boundaries[physical_old["id"]] = physical_old
            boundaries[row["id"]] = row
        physical_previous[key] = row
        if len(physical_previous) > budget:
            raise ValueError("当前窗口链路过多，请缩小时间范围或选择单个 AP")
        old = previous.get(lane)
        gap = (datetime.fromisoformat(row["sample_time"]) - datetime.fromisoformat(old["sample_time"])).total_seconds() if old else 0
        threshold = min(max((median(intervals) if intervals else 1.0) * 5, 5.0), 60.0)
        row["monitor_gap_before"] = gap > threshold
        if group == "counters" and (row["monitor_gap_before"] or (physical_old is not None and physical_old.get("link_state") != row.get("link_state"))):
            for field in fields:
                row[field + "_delta"] = None
        if row.get("link_count") == 0:
            for counter_key in tuple(counters):
                if counter_key[:2] == key[:2]:
                    del counters[counter_key]
        if 0 < gap <= threshold:
            intervals.append(gap)
        if old is None or row["monitor_gap_before"] or (old.get("peer_mac_normalized"), old.get("establish_time"), old.get("link_count"), old.get("link_state")) != (row.get("peer_mac_normalized"), row.get("establish_time"), row.get("link_count"), row.get("link_state")):
            boundaries[row["id"]] = row
            if old is not None:
                boundaries[old["id"]] = old
        previous[lane] = row
        if len(boundaries) > budget // 2:
            raise ValueError("当前窗口切换事件过密，请缩小时间范围；未丢弃切换边界")
        stamp = datetime.fromisoformat(row["sample_time"]).timestamp()
        bucket = min(buckets - 1, max(0, int((stamp - low) / max(1, high - low) * buckets)))
        for field in fields:
            effective = field + "_delta" if group == "counters" else field
            value = row.get(effective)
            if value is None:
                extrema.setdefault((lane, bucket, field, "null"), row)
                continue
            for direction in ("min", "max"):
                entry = (lane, bucket, field, direction)
                current = extrema.get(entry)
                if current is None or (value < current[effective] if direction == "min" else value > current[effective]):
                    extrema[entry] = row
        extrema.setdefault((lane, bucket, "first"), row)
        extrema[(lane, bucket, "last")] = row
    selected = {row["id"]: row for row in extrema.values()}
    selected.update(boundaries)
    for row in previous.values():
        selected[row["id"]] = row
    if len(selected) > budget:
        raise ValueError("当前窗口数据边界超过图表预算，请缩小时间范围")
    return sorted(selected.values(), key=lambda row: (row["sample_time"], row["id"])), total, zero
