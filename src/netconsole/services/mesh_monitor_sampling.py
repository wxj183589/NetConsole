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


def monitor_identity(row: dict[str, Any]) -> tuple:
    return tuple(row.get(field) for field in (
        "source_file_id", "radio", "peer_mac_normalized", "establish_time",
        "peer_radio_mac", "peer_radio_label", "peer_ap_mac", "local_ap_mac",
    ))


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
    intervals: dict[tuple, deque[float]] = {}
    total = zero = 0
    for row in rows:
        row = dict(row)
        total += 1
        zero += row.get("link_count") == 0
        key = monitor_identity(row)
        old_counter = counters.get(key)
        if group == "counters":
            interval = (datetime.fromisoformat(row["sample_time"]) - datetime.fromisoformat(old_counter["sample_time"])).total_seconds() if old_counter else None
            row["counter_samples"] = {}
            for field in fields:
                value, before = row.get(field), old_counter.get(field) if old_counter else None
                if old_counter is not None and (value is None) != (before is None):
                    boundaries[row["id"]] = row
                    boundaries[old_counter["id"]] = old_counter
                if value is not None and before is not None and value < before:
                    boundaries[row["id"]] = row
                    boundaries[old_counter["id"]] = old_counter
                row[field + "_delta"] = value - before if (value is not None and before is not None and value >= before and row.get("link_count") != 0 and row["sample_time"] > old_counter["sample_time"]) else None
                state = ("missing" if value is None else "first" if old_counter is None else
                         "invalid_interval" if interval is None or interval <= 0 else
                         "missing" if before is None else "reset" if value < before else "valid")
                delta = row[field + "_delta"]
                row["counter_samples"][field] = {"current": value, "previous": before,
                    "delta": delta, "interval_seconds": interval,
                    "per_second": delta / interval if delta is not None and interval is not None and interval > 0 else None,
                    "status": state}
            # Duplicate/out-of-order records must not replace the last valid baseline.
            if old_counter is None or interval > 0:
                counters[key] = row
            else:
                boundaries[row["id"]] = row
                boundaries[old_counter["id"]] = old_counter
            if len(counters) > budget:
                raise ValueError("当前窗口链路过多，请缩小时间范围或选择单个 AP")
        lane = (row.get("source_file_id"), row.get("radio"), row.get("link_state"))
        physical_old = physical_previous.get(key)
        if physical_old is not None and physical_old.get("link_state") != row.get("link_state"):
            boundaries[physical_old["id"]] = physical_old
            boundaries[row["id"]] = row
        if physical_old is None or row["sample_time"] > physical_old["sample_time"]:
            physical_previous[key] = row
        if len(physical_previous) > budget:
            raise ValueError("当前窗口链路过多，请缩小时间范围或选择单个 AP")
        old = previous.get(lane)
        if group == "counters" and old_counter is None:
            boundaries[row["id"]] = row
        gap_old = old_counter if group == "counters" else old
        gap = (datetime.fromisoformat(row["sample_time"]) - datetime.fromisoformat(gap_old["sample_time"])).total_seconds() if gap_old else 0
        cadence = intervals.setdefault(key if group == "counters" else lane, deque(maxlen=101))
        threshold = min(max((median(cadence) if cadence else 1.0) * 5, 5.0), 60.0)
        row["monitor_gap_before"] = gap > threshold
        lane_changed = old is not None and monitor_identity(old) != key
        lane_changed = lane_changed or bool(row.get("monitor_raw_lane_changed"))
        raw_role_changed = row.get("monitor_raw_physical_role") not in (None, row.get("link_state"))
        if group == "counters" and (lane_changed or raw_role_changed):
            boundaries[row["id"]] = row
            if old is not None:
                boundaries[old["id"]] = old
        if group == "counters" and (row["monitor_gap_before"] or lane_changed or raw_role_changed or row.get("link_count") == 0 or (physical_old is not None and physical_old.get("link_state") != row.get("link_state"))):
            for field in fields:
                row[field + "_delta"] = None
                row["counter_samples"][field].update(delta=None, per_second=None,
                    status="gap" if row["monitor_gap_before"] else "link_changed")
        if row.get("link_count") == 0:
            for counter_key in tuple(counters):
                if counter_key[:2] == key[:2]:
                    del counters[counter_key]
        if gap > 0:
            cadence.append(gap)
        if old is None or row["monitor_gap_before"] or (old.get("peer_mac_normalized"), old.get("establish_time"), old.get("link_count"), old.get("link_state")) != (row.get("peer_mac_normalized"), row.get("establish_time"), row.get("link_count"), row.get("link_state")):
            boundaries[row["id"]] = row
            if old is not None:
                boundaries[old["id"]] = old
        if old is None or row["sample_time"] > old["sample_time"]:
            previous[lane] = row
        if len(boundaries) > budget // 2:
            raise ValueError("当前窗口切换事件过密，请缩小时间范围；未丢弃切换边界")
        stamp = datetime.fromisoformat(row["sample_time"]).timestamp()
        bucket = min(buckets - 1, max(0, int((stamp - low) / max(1, high - low) * buckets)))
        for field in fields:
            effective = field + "_per_second" if group == "counters" else field
            if group == "counters":
                row[effective] = row["counter_samples"][field]["per_second"]
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
