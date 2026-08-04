from __future__ import annotations

import json
from bisect import bisect_left
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

import numpy as np
from matplotlib.dates import date2num

from netconsole.models.mesh_log_models import LINK_STATE_ACTIVE


class MeshChartSelectionLimitError(ValueError):
    """The requested chart window cannot contain all critical samples safely."""

    def __init__(self, *, critical_count: int, max_points: int) -> None:
        self.critical_count = int(critical_count)
        self.max_points = int(max_points)
        super().__init__(
            "MESH 图表关键业务点超过安全渲染上限，已停止返回不完整结果；请缩小时间窗口。"
            f"关键点 {self.critical_count} 个，安全上限 {self.max_points} 个。"
        )


@dataclass(frozen=True)
class ActiveRun:
    peer_mac: str
    start_sample_index: int
    end_sample_index: int
    active_sample_indices: tuple[int, ...]


_METRIC_KEYS = (
    "local_rssi_db",
    "peer_rssi_db",
    "local_noise_raw",
    "peer_noise_raw",
    "local_tx_busy",
    "peer_tx_busy",
    "local_rx_busy",
    "peer_rx_busy",
    "local_signal_dbm",
    "peer_signal_dbm",
)


def build_chart_payload(peer_segment: dict[str, object], run_segment: dict[str, object]) -> dict[str, object]:
    peer_rows = [row for row in peer_segment.get("rows", []) if isinstance(row, dict)]
    run_rows = [row for row in run_segment.get("rows", []) if isinstance(row, dict)]
    events = [event for event in run_segment.get("events", []) if isinstance(event, dict)]
    anchor = peer_segment.get("anchor") if isinstance(peer_segment.get("anchor"), dict) else run_segment.get("anchor")
    anchor_time = str(anchor.get("sample_time")) if isinstance(anchor, dict) and anchor.get("sample_time") else ""
    anchor_key = _sample_key(anchor) if isinstance(anchor, dict) and anchor_time else ""
    master_times = sorted({_sample_key(row) for row in run_rows if row.get("sample_time")}, key=_sample_sort_key)
    if not master_times:
        master_times = sorted({_sample_key(row) for row in peer_rows if row.get("sample_time")}, key=_sample_sort_key)
    time_index = {sample_key: index for index, sample_key in enumerate(master_times)}
    timestamps = [_parse_time(_sample_time(value)) for value in master_times]
    timestamp_numeric = np.asarray([date2num(value) for value in timestamps], dtype=np.float64)
    count = len(master_times)
    peer_series = _empty_peer_series(count)
    peer_macs = [""] * count
    peer_ap_names = [""] * count
    peer_sites = [""] * count
    peer_radios = [""] * count
    peer_link_states = [""] * count
    peer_establish_times = [""] * count
    peer_session_ids = [""] * count
    peer_links_by_index = [{} for _ in range(count)]
    session_bounds: dict[str, list[str]] = {}
    for row in peer_rows:
        index = time_index.get(_sample_key(row))
        if index is None:
            continue
        session_id = str(row.get("session_id") or "")
        peer_macs[index] = str(row.get("peer_mac_normalized") or row.get("peer_mac_raw") or "")
        peer_ap_names[index] = str(row.get("peer_ap_name") or "")
        peer_sites[index] = str(row.get("peer_site") or "")
        peer_radios[index] = str(row.get("peer_radio") or row.get("peer_radio_label") or "")
        peer_link_states[index] = str(row.get("link_state") or "")
        peer_establish_times[index] = str(row.get("establish_time") or "")
        peer_session_ids[index] = session_id
        peer_links_by_index[index] = _link_context_summary(row)
        if session_id:
            bounds = session_bounds.setdefault(session_id, [str(row.get("sample_time")), str(row.get("sample_time"))])
            bounds[0] = min(bounds[0], str(row.get("sample_time")))
            bounds[1] = max(bounds[1], str(row.get("sample_time")))
        metrics = _metrics(row)
        peer_series["local_rssi"][index] = _float(metrics.get("local_rssi_db"))
        peer_series["peer_rssi"][index] = _float(metrics.get("peer_rssi_db"))
        peer_series["local_noise"][index] = _float(metrics.get("local_noise_raw"))
        peer_series["peer_noise"][index] = _float(metrics.get("peer_noise_raw"))
        peer_series["local_tx_busy"][index] = _float(metrics.get("local_tx_busy"))
        peer_series["peer_tx_busy"][index] = _float(metrics.get("peer_tx_busy"))
        peer_series["local_rx_busy"][index] = _float(metrics.get("local_rx_busy"))
        peer_series["peer_rx_busy"][index] = _float(metrics.get("peer_rx_busy"))
        peer_series["local_signal"][index] = _float(metrics.get("local_signal_dbm"))
        peer_series["peer_signal"][index] = _float(metrics.get("peer_signal_dbm"))
        peer_series["state"][index] = 1 if row.get("link_state") == LINK_STATE_ACTIVE else 0
    rows_by_time, rows_by_time_and_peer = _index_rows_by_time(run_rows)
    unique_active_by_index, no_active_indices, multi_active_indices = build_unique_active_samples(master_times, rows_by_time)
    active_runs = build_active_runs(master_times, unique_active_by_index)
    active_series = _empty_active_series(count)
    active_peer_macs = [""] * count
    active_peer_ap_names = [""] * count
    active_peer_sites = [""] * count
    active_peer_radios = [""] * count
    active_source_file_ids = [""] * count
    active_peer_rssi = np.full(count, np.nan, dtype=np.float32)
    active_peer_tx_busy = np.full(count, np.nan, dtype=np.float32)
    active_peer_rx_busy = np.full(count, np.nan, dtype=np.float32)
    active_local_signal = np.full(count, np.nan, dtype=np.float32)
    active_peer_signal = np.full(count, np.nan, dtype=np.float32)
    standby_links_by_index = [[] for _ in range(count)]
    main_links_by_index = [{} for _ in range(count)]
    peer_change_indices = [run.start_sample_index for run in active_runs[1:]]
    rapid_flaps = detect_rapid_flaps(active_runs, master_times, peer_segment.get("estimated_interval_seconds") or run_segment.get("estimated_interval_seconds"))
    rapid_flap_indices = [int(item["return_sample_index"]) for item in rapid_flaps]
    assign_active_series(
        active_runs,
        master_times,
        rows_by_time_and_peer,
        active_series,
        active_peer_macs,
        active_peer_ap_names,
        active_peer_sites,
        active_peer_radios,
        active_peer_rssi,
        active_peer_tx_busy,
        active_peer_rx_busy,
        active_local_signal,
        active_peer_signal,
    )
    assign_standby_links(master_times, rows_by_time, standby_links_by_index, unique_active_by_index, main_links_by_index)
    for index, row in unique_active_by_index.items():
        active_source_file_ids[index] = str(row.get("source_file_id") or "")
    for index, context in enumerate(main_links_by_index):
        if context and not active_source_file_ids[index]:
            active_source_file_ids[index] = str(context.get("source_file_id") or "")
    estimated_interval = peer_segment.get("estimated_interval_seconds") or run_segment.get("estimated_interval_seconds")
    events_by_index = _events_by_index(
        events,
        master_times,
        active_peer_macs,
        active_peer_ap_names,
        active_peer_sites,
        max_delta_seconds=_sampling_tolerance_seconds(estimated_interval),
    )
    switch_indices = [index for index, items in events_by_index.items() if any(item.get("event_type") == "ACTIVE_SWITCH" for item in items)]
    anchor_index = _nearest_time_index(master_times, anchor_key or anchor_time)
    return {
        "metadata": {
            "anchor": anchor,
            "anchor_sample_time": anchor_time,
            "anchor_index": anchor_index,
            "segment_start": peer_segment.get("segment_start") or run_segment.get("segment_start"),
            "segment_end": peer_segment.get("segment_end") or run_segment.get("segment_end"),
            "estimated_interval_seconds": peer_segment.get("estimated_interval_seconds") or run_segment.get("estimated_interval_seconds"),
            "continuity_gap_seconds": peer_segment.get("continuity_gap_seconds") or run_segment.get("continuity_gap_seconds"),
            "sample_count": count,
            "peer_sample_count": len(peer_rows),
            "backend": "matplotlib-cpu",
            "partial": bool(peer_segment.get("partial") or run_segment.get("partial")),
            "full_loading": bool(peer_segment.get("full_loading") or run_segment.get("full_loading")),
            "full_active_payload": bool(peer_segment.get("full_active_payload") or run_segment.get("full_active_payload")),
            "query_active_count": int(peer_segment.get("query_active_count") or run_segment.get("query_active_count") or 0),
        },
        "timestamps": timestamps,
        "timestamp_labels": [_sample_time(value) for value in master_times],
        "timestamp_tags": [_sample_tag(value) for value in master_times],
        "sample_source_file_ids": [_sample_source(value) for value in master_times],
        "sample_radios": [_sample_radio(value) for value in master_times],
        "timestamp_numeric": timestamp_numeric,
        "peer_series": peer_series,
        "active_series": active_series,
        "active_peer_macs": active_peer_macs,
        "active_peer_ap_names": active_peer_ap_names,
        "active_peer_sites": active_peer_sites,
        "active_peer_radios": active_peer_radios,
        "active_source_file_ids": active_source_file_ids,
        "active_peer_rssi": active_peer_rssi,
        "active_peer_tx_busy": active_peer_tx_busy,
        "active_peer_rx_busy": active_peer_rx_busy,
        "active_local_signal": active_local_signal,
        "active_peer_signal": active_peer_signal,
        "main_links_by_index": main_links_by_index,
        "standby_links_by_index": standby_links_by_index,
        "backup_links_by_index": standby_links_by_index,
        "peer_macs": peer_macs,
        "peer_ap_names": peer_ap_names,
        "peer_sites": peer_sites,
        "peer_radios": peer_radios,
        "peer_link_states": peer_link_states,
        "peer_establish_times": peer_establish_times,
        "peer_session_ids": peer_session_ids,
        "peer_links_by_index": peer_links_by_index,
        "session_options": [
            {"session_id": session_id, "first_sample_time": bounds[0], "last_sample_time": bounds[1]}
            for session_id, bounds in sorted(session_bounds.items(), key=lambda item: item[1][0])
        ],
        "active_runs": [
            {
                "peer_mac": run.peer_mac,
                "start_sample_index": run.start_sample_index,
                "end_sample_index": run.end_sample_index,
                "active_sample_indices": list(run.active_sample_indices),
            }
            for run in active_runs
        ],
        "rapid_flaps": rapid_flaps,
        "rapid_flap_indices": np.asarray(sorted(set(rapid_flap_indices)), dtype=np.int32),
        "events_by_index": events_by_index,
        "switch_indices": np.asarray(sorted(set(switch_indices)), dtype=np.int32),
        "no_active_indices": np.asarray(sorted(set(no_active_indices)), dtype=np.int32),
        "multi_active_indices": np.asarray(sorted(set(multi_active_indices)), dtype=np.int32),
        "peer_change_indices": np.asarray(sorted(set(peer_change_indices)), dtype=np.int32),
        "important_indices": np.asarray(sorted({anchor_index, *switch_indices, *no_active_indices, *multi_active_indices, *peer_change_indices, *rapid_flap_indices} - {-1}), dtype=np.int32),
    }


def render_indices(
    total_count: int,
    start_index: int,
    visible_count: int,
    important_indices: Iterable[int],
    max_points: int,
    pinned_indices: Iterable[int] = (),
) -> np.ndarray:
    if total_count <= 0:
        return np.asarray([], dtype=np.int32)
    if visible_count > 0:
        start = max(start_index - 2, 0)
        end = min(start_index + visible_count + 2, total_count)
        return np.arange(start, end, dtype=np.int32)
    important = {int(index) for index in important_indices if 0 <= int(index) < total_count}
    pinned = {int(index) for index in pinned_indices if 0 <= int(index) < total_count}
    if total_count <= max_points:
        return np.arange(total_count, dtype=np.int32)
    limit = max(int(max_points), 2)
    pinned.update({0, total_count - 1})
    required = sorted({*pinned, *important})
    if len(required) >= limit:
        if len(pinned) >= limit:
            return _spread_indices(pinned, limit, pinned=(0, total_count - 1))
        sampled = _spread_indices((index for index in required if index not in pinned), limit - len(pinned))
        return np.asarray(sorted({*pinned, *(int(index) for index in sampled)}), dtype=np.int32)
    excluded = set(required)
    candidates = (index for index in range(total_count) if index not in excluded)
    sampled = _spread_indices(candidates, limit - len(required))
    return np.asarray(sorted({*required, *(int(index) for index in sampled)}), dtype=np.int32)


def prioritized_render_indices(
    total_count: int,
    max_points: int,
    *,
    critical_indices: Iterable[int] = (),
    trend_indices: Iterable[int] = (),
    ordinary_indices: Iterable[int] = (),
) -> np.ndarray:
    """Select samples with a strict critical > trend > ordinary priority."""
    if total_count <= 0:
        return np.asarray([], dtype=np.int32)
    limit = max(int(max_points), 2)

    def valid(values: Iterable[int]) -> set[int]:
        return {int(value) for value in values if 0 <= int(value) < total_count}

    critical = valid(critical_indices)
    critical.update({0, total_count - 1})
    if len(critical) > limit:
        raise MeshChartSelectionLimitError(
            critical_count=len(critical),
            max_points=limit,
        )

    trend = valid(trend_indices) - critical
    ordinary = valid(ordinary_indices) - critical - trend
    selected = set(critical)
    remaining = limit - len(selected)
    for tier in (trend, ordinary):
        if remaining <= 0:
            break
        selected.update(int(value) for value in _spread_indices(tier, remaining))
        remaining = limit - len(selected)
    if remaining > 0:
        selected.update(
            int(value)
            for value in _spread_indices(set(range(total_count)) - selected, remaining)
        )
    return np.asarray(sorted(selected), dtype=np.int32)


def _spread_indices(values: Iterable[int], limit: int, *, pinned: tuple[int, ...] = ()) -> np.ndarray:
    ordered = sorted({int(value) for value in values})
    if limit <= 0 or not ordered:
        return np.asarray([], dtype=np.int32)
    if len(ordered) <= limit:
        return np.asarray(ordered, dtype=np.int32)
    fixed = [value for value in dict.fromkeys(pinned) if value in ordered]
    if len(fixed) >= limit:
        return np.asarray(fixed[:limit], dtype=np.int32)
    remaining = [value for value in ordered if value not in fixed]
    positions = np.linspace(0, len(remaining) - 1, limit - len(fixed), dtype=np.int32)
    return np.asarray(sorted({*fixed, *(remaining[int(position)] for position in positions)}), dtype=np.int32)


def preserve_extrema_indices(base_indices: np.ndarray, values: np.ndarray, max_points: int) -> np.ndarray:
    if len(base_indices) <= max_points:
        return base_indices
    finite_positions = [int(index) for index in base_indices if np.isfinite(values[int(index)])]
    if not finite_positions:
        return base_indices[:max_points]
    keep = {int(base_indices[0]), int(base_indices[-1])}
    bucket_count = max((max_points - 2) // 2, 1)
    bucket_size = max((len(finite_positions) + bucket_count - 1) // bucket_count, 1)
    for start in range(0, len(finite_positions), bucket_size):
        bucket = finite_positions[start : start + bucket_size]
        if not bucket:
            continue
        keep.add(min(bucket, key=lambda index: values[index]))
        keep.add(max(bucket, key=lambda index: values[index]))
    return np.asarray(sorted(keep), dtype=np.int32)


def _empty_peer_series(count: int) -> dict[str, np.ndarray]:
    float_keys = (
        "local_rssi",
        "peer_rssi",
        "local_noise",
        "peer_noise",
        "local_tx_busy",
        "peer_tx_busy",
        "local_rx_busy",
        "peer_rx_busy",
        "local_signal",
        "peer_signal",
    )
    series = {key: np.full(count, np.nan, dtype=np.float32) for key in float_keys}
    series["state"] = np.full(count, -1, dtype=np.int8)
    return series


def _empty_active_series(count: int) -> dict[str, np.ndarray]:
    return {
        key: np.full(count, np.nan, dtype=np.float32)
        for key in (
            "active_local_rssi",
            "active_local_tx_busy",
            "active_local_rx_busy",
        )
    }


def canonical_mesh_mac(value_or_row: object) -> str:
    if isinstance(value_or_row, dict):
        value = value_or_row.get("peer_mac_normalized") or value_or_row.get("peer_mac_raw") or ""
    else:
        value = value_or_row or ""
    return "".join(character for character in str(value).lower() if character in "0123456789abcdef")


def _index_rows_by_time(run_rows: list[dict[str, object]]) -> tuple[dict[str, list[dict[str, object]]], dict[str, dict[str, dict[str, object]]]]:
    rows_by_time: dict[str, list[dict[str, object]]] = {}
    rows_by_time_and_peer: dict[str, dict[str, dict[str, object]]] = {}
    for row in sorted(run_rows, key=lambda item: (str(item.get("sample_time") or ""), int(item.get("id") or 0))):
        sample_time = str(row.get("sample_time") or "")
        if not sample_time:
            continue
        sample_key = _sample_key(row)
        rows_by_time.setdefault(sample_key, []).append(row)
        peer = canonical_mesh_mac(row)
        if peer:
            rows_by_time_and_peer.setdefault(sample_key, {})[peer] = row
    return rows_by_time, rows_by_time_and_peer


def build_unique_active_samples(master_times: list[str], rows_by_time: dict[str, list[dict[str, object]]]) -> tuple[dict[int, dict[str, object]], list[int], list[int]]:
    unique_active_by_index: dict[int, dict[str, object]] = {}
    no_active_indices: list[int] = []
    multi_active_indices: list[int] = []
    for index, sample_time in enumerate(master_times):
        active = [row for row in rows_by_time.get(sample_time, []) if row.get("link_state") == LINK_STATE_ACTIVE]
        if len(active) == 1:
            unique_active_by_index[index] = active[0]
        elif len(active) == 0:
            no_active_indices.append(index)
        else:
            multi_active_indices.append(index)
    return unique_active_by_index, no_active_indices, multi_active_indices


def build_active_runs(master_times: list[str], unique_active_by_index: dict[int, dict[str, object]]) -> list[ActiveRun]:
    runs: list[ActiveRun] = []
    current_peer = ""
    current_indices: list[int] = []
    for index in range(len(master_times)):
        row = unique_active_by_index.get(index)
        peer = canonical_mesh_mac(row) if row else ""
        if not peer:
            if current_indices:
                runs.append(ActiveRun(current_peer, current_indices[0], current_indices[-1], tuple(current_indices)))
                current_indices = []
                current_peer = ""
            continue
        if current_indices and peer != current_peer:
            runs.append(ActiveRun(current_peer, current_indices[0], current_indices[-1], tuple(current_indices)))
            current_indices = []
        current_peer = peer
        current_indices.append(index)
    if current_indices:
        runs.append(ActiveRun(current_peer, current_indices[0], current_indices[-1], tuple(current_indices)))
    return runs


def assign_active_series(
    active_runs: list[ActiveRun],
    master_times: list[str],
    rows_by_time_and_peer: dict[str, dict[str, dict[str, object]]],
    active_series: dict[str, np.ndarray],
    active_peer_macs: list[str],
    active_peer_ap_names: list[str],
    active_peer_sites: list[str],
    active_peer_radios: list[str],
    active_peer_rssi: np.ndarray,
    active_peer_tx_busy: np.ndarray,
    active_peer_rx_busy: np.ndarray,
    active_local_signal: np.ndarray,
    active_peer_signal: np.ndarray,
) -> None:
    for run in active_runs:
        for sample_index in run.active_sample_indices:
            sample_time = master_times[sample_index]
            active_row = rows_by_time_and_peer.get(sample_time, {}).get(run.peer_mac)
            active_peer_macs[sample_index] = run.peer_mac
            if active_row:
                active_peer_ap_names[sample_index] = str(active_row.get("peer_ap_name") or "")
                active_peer_sites[sample_index] = str(active_row.get("peer_site") or "")
                active_peer_radios[sample_index] = str(active_row.get("peer_radio") or active_row.get("peer_radio_label") or "")
                metrics = _metrics(active_row)
                active_series["active_local_rssi"][sample_index] = _float(metrics.get("local_rssi_db"))
                active_peer_rssi[sample_index] = _float(metrics.get("peer_rssi_db"))
                active_series["active_local_tx_busy"][sample_index] = _float(metrics.get("local_tx_busy"))
                active_series["active_local_rx_busy"][sample_index] = _float(metrics.get("local_rx_busy"))
                active_peer_tx_busy[sample_index] = _float(metrics.get("peer_tx_busy"))
                active_peer_rx_busy[sample_index] = _float(metrics.get("peer_rx_busy"))
                active_local_signal[sample_index] = _float(metrics.get("local_signal_dbm"))
                active_peer_signal[sample_index] = _float(metrics.get("peer_signal_dbm"))


def assign_standby_links(
    master_times: list[str],
    rows_by_time: dict[str, list[dict[str, object]]],
    standby_links_by_index: list[list[dict[str, object]]],
    unique_active_by_index: dict[int, dict[str, object]],
    main_links_by_index: list[dict[str, object]],
) -> None:
    for index, sample_time in enumerate(master_times):
        active_row = unique_active_by_index.get(index)
        if not active_row:
            continue
        main_links_by_index[index] = _link_context_summary(active_row)
        active_source = _source_key(active_row)
        active_peer = canonical_mesh_mac(active_row)
        standby_rows = [
            row
            for row in rows_by_time.get(sample_time, [])
            if row.get("link_state") == "STANDBY" and _source_key(row) == active_source and canonical_mesh_mac(row) != active_peer
        ]
        items = [_standby_summary(row) for row in standby_rows]
        items.sort(key=_standby_sort_key)
        standby_links_by_index[index] = items


def _standby_summary(row: dict[str, object]) -> dict[str, object]:
    return _link_context_summary(row)


def _link_context_summary(row: dict[str, object]) -> dict[str, object]:
    metrics = _metrics(row)
    return {
        "link_id": row.get("id") or row.get("link_id"),
        "peer_mac": row.get("peer_mac_normalized") or row.get("peer_mac_raw") or "",
        "ap_mac": row.get("peer_ap_mac") or "",
        "ap_name": row.get("peer_ap_name") or "",
        "site": row.get("peer_site") or "",
        "station_name": row.get("peer_site") or "",
        "radio": row.get("radio") or "",
        "peer_radio": row.get("peer_radio") or row.get("peer_radio_label") or "",
        "peer_radio_mac": row.get("peer_radio_mac") or "",
        "identity_status": row.get("peer_identity_status") or row.get("identity_status") or "",
        "identity_source": row.get("peer_identity_source") or row.get("identity_source") or row.get("peer_resolve_source") or "",
        "identity_rule": row.get("peer_match_rule") or row.get("identity_rule") or row.get("match_rule") or "",
        "identity_confidence": row.get("peer_match_confidence") or row.get("identity_confidence") or 0,
        "identity_reason": row.get("peer_identity_reason") or row.get("identity_reason") or "",
        "mr_rssi": metrics.get("local_rssi_db"),
        "ap_rssi": metrics.get("peer_rssi_db"),
        "local_signal": metrics.get("local_signal_dbm"),
        "peer_signal": metrics.get("peer_signal_dbm"),
        "local_tx_busy": metrics.get("local_tx_busy"),
        "peer_tx_busy": metrics.get("peer_tx_busy"),
        "local_rx_busy": metrics.get("local_rx_busy"),
        "peer_rx_busy": metrics.get("peer_rx_busy"),
        "status": row.get("link_state") or "",
        "sample_time": row.get("sample_time") or "",
        "timestamp_tag": row.get("timestamp_tag") or "",
        "source_file_id": row.get("source_file_id") or "",
        "establish_time": row.get("establish_time") or "",
    }


def _standby_sort_key(item: dict[str, object]) -> tuple[int, str, float]:
    try:
        radio = int(item.get("radio") or 9999)
    except (TypeError, ValueError):
        radio = 9999
    peer = canonical_mesh_mac(item.get("peer_mac") or "")
    return radio, peer, -_sort_rssi(item.get("mr_rssi"))


def _source_key(row: dict[str, object]) -> str:
    return str(row.get("source_file_id") or "")


def _standby_fallback_index(rows_by_time: dict[str, list[dict[str, object]]]) -> dict[str, tuple[list[float], list[list[dict[str, object]]]]]:
    grouped: dict[str, dict[str, list[dict[str, object]]]] = {}
    for sample_time, rows in rows_by_time.items():
        for row in rows:
            if row.get("link_state") != "STANDBY":
                continue
            grouped.setdefault(_source_key(row), {}).setdefault(sample_time, []).append(row)
    indexed: dict[str, tuple[list[float], list[list[dict[str, object]]]]] = {}
    for source, rows_by_sample_time in grouped.items():
        entries: list[tuple[float, list[dict[str, object]]]] = []
        for sample_time, rows in rows_by_sample_time.items():
            try:
                entries.append((_parse_time(sample_time).timestamp(), rows))
            except (TypeError, ValueError):
                continue
        entries.sort(key=lambda item: item[0])
        indexed[source] = ([item[0] for item in entries], [item[1] for item in entries])
    return indexed


def _nearest_standby_rows(
    fallback_index: dict[str, tuple[list[float], list[list[dict[str, object]]]]],
    source: str,
    sample_time: str,
    active_peer: str,
) -> list[dict[str, object]]:
    try:
        target = _parse_time(sample_time).timestamp()
    except (TypeError, ValueError):
        return []
    times, rows_by_position = fallback_index.get(source, ([], []))
    if not times:
        return []
    candidates: list[tuple[float, list[dict[str, object]]]] = []
    position = bisect_left(times, target)
    for candidate in (position - 1, position, position + 1):
        if 0 <= candidate < len(times):
            delta = abs(times[candidate] - target)
            if delta <= 1.0:
                rows = [row for row in rows_by_position[candidate] if canonical_mesh_mac(row) != active_peer]
                if rows:
                    candidates.append((delta, rows))
    if not candidates:
        return []
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def _active_fallback_index(rows_by_time: dict[str, list[dict[str, object]]]) -> dict[str, tuple[list[float], list[list[dict[str, object]]]]]:
    grouped: dict[str, dict[str, list[dict[str, object]]]] = {}
    for sample_time, rows in rows_by_time.items():
        for row in rows:
            if row.get("link_state") != LINK_STATE_ACTIVE:
                continue
            grouped.setdefault(_source_key(row), {}).setdefault(sample_time, []).append(row)
    indexed: dict[str, tuple[list[float], list[list[dict[str, object]]]]] = {}
    for source, rows_by_sample_time in grouped.items():
        entries: list[tuple[float, list[dict[str, object]]]] = []
        for sample_time, rows in rows_by_sample_time.items():
            try:
                entries.append((_parse_time(sample_time).timestamp(), sorted(rows, key=lambda row: (int(row.get("radio") or 0), canonical_mesh_mac(row), int(row.get("id") or 0)))))
            except (TypeError, ValueError):
                continue
        entries.sort(key=lambda item: item[0])
        indexed[source] = ([item[0] for item in entries], [item[1] for item in entries])
    return indexed


def _nearest_active_row(
    fallback_index: dict[str, tuple[list[float], list[list[dict[str, object]]]]],
    source: str,
    sample_time: str,
) -> dict[str, object] | None:
    if not source:
        return None
    try:
        target = _parse_time(sample_time).timestamp()
    except (TypeError, ValueError):
        return None
    times, rows_by_position = fallback_index.get(source, ([], []))
    if not times:
        return None
    candidates: list[tuple[float, dict[str, object]]] = []
    position = bisect_left(times, target)
    for candidate in (position - 1, position, position + 1):
        if 0 <= candidate < len(times):
            delta = abs(times[candidate] - target)
            if delta <= 1.0 and rows_by_position[candidate]:
                candidates.append((delta, rows_by_position[candidate][0]))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], int(item[1].get("radio") or 0), canonical_mesh_mac(item[1])))
    return candidates[0][1]


def _source_for_time(rows_by_time: dict[str, list[dict[str, object]]], sample_time: str) -> str:
    rows = rows_by_time.get(sample_time) or []
    return _source_key(rows[0]) if rows else ""


def _sort_rssi(value: object) -> float:
    parsed = _float(value)
    return parsed if np.isfinite(parsed) else float("-inf")


def _metrics(row: dict[str, object]) -> dict[str, object]:
    metrics = row.get("metrics")
    if isinstance(metrics, dict) and metrics:
        merged = dict(metrics)
        for key in _METRIC_KEYS:
            if key not in merged and row.get(key) is not None:
                merged[key] = row.get(key)
        return merged
    metrics_json = row.get("metrics_json")
    if isinstance(metrics_json, str) and metrics_json.strip():
        try:
            parsed = json.loads(metrics_json)
        except json.JSONDecodeError:
            parsed = {}
        if isinstance(parsed, dict):
            merged = dict(parsed)
            for key in _METRIC_KEYS:
                if key not in merged and row.get(key) is not None:
                    merged[key] = row.get(key)
            return merged
    return {key: row.get(key) for key in _METRIC_KEYS if row.get(key) is not None}


def detect_rapid_flaps(active_runs: list[ActiveRun], master_times: list[str], estimated_interval_seconds: object) -> list[dict[str, object]]:
    try:
        interval = float(estimated_interval_seconds or 1.0)
    except (TypeError, ValueError):
        interval = 1.0
    window_seconds = max(interval * 5, 5.0)
    flaps: list[dict[str, object]] = []
    for index in range(len(active_runs) - 2):
        first, middle, third = active_runs[index], active_runs[index + 1], active_runs[index + 2]
        if first.peer_mac != third.peer_mac or first.peer_mac == middle.peer_mac:
            continue
        elapsed = _seconds_between(master_times[middle.start_sample_index], master_times[third.start_sample_index])
        if 0 <= elapsed <= window_seconds:
            flaps.append(
                {
                    "from_peer_mac": first.peer_mac,
                    "middle_peer_mac": middle.peer_mac,
                    "return_peer_mac": third.peer_mac,
                    "leave_sample_index": middle.start_sample_index,
                    "return_sample_index": third.start_sample_index,
                    "elapsed_ms": int(elapsed * 1000),
                    "is_rapid_flap": True,
                }
            )
    return flaps


def _events_by_index(
    events: list[dict[str, object]],
    sample_keys: list[str],
    active_peer_macs: list[str] | None = None,
    active_peer_ap_names: list[str] | None = None,
    active_peer_sites: list[str] | None = None,
    max_delta_seconds: float | None = None,
) -> dict[int, list[dict[str, object]]]:
    by_index: dict[int, list[dict[str, object]]] = {}
    exact: dict[tuple[str, str, str], int] = {}
    by_source_time: dict[tuple[str, str], int] = {}
    by_radio_time: dict[tuple[str, str], int] = {}
    by_time: dict[str, int] = {}
    scoped_rows: dict[tuple[str, str], list[tuple[str, int]]] = {}
    for index, key in enumerate(sample_keys):
        source, sample_time, _tag, radio = _sample_parts(key)
        exact.setdefault((source, radio, sample_time), index)
        by_source_time.setdefault((source, sample_time), index)
        by_radio_time.setdefault((radio, sample_time), index)
        by_time.setdefault(sample_time, index)
        scoped_rows.setdefault((source, radio), []).append((sample_time, index))
    for event in events:
        sample_time = str(event.get("event_time") or event.get("current_sample_time") or "")
        source = str(event.get("source_file_id") or "")
        radio = str(event.get("radio") or "")
        index = (
            exact.get((source, radio, sample_time))
            if source and radio
            else by_source_time.get((source, sample_time))
            if source
            else by_radio_time.get((radio, sample_time))
            if radio
            else by_time.get(sample_time)
        )
        if index is not None:
            by_index.setdefault(index, []).append(_enrich_switch_event(event, index, active_peer_macs or [], active_peer_ap_names or [], active_peer_sites or []))
            continue
        scoped = scoped_rows.get((source, radio), []) if source and radio else [
            (str(_sample_time(key)), candidate)
            for candidate, key in enumerate(sample_keys)
            if (not source or _sample_source(key) == source) and (not radio or _sample_radio(key) == radio)
        ]
        nearest = _nearest_scoped_index(scoped, sample_time, max_delta_seconds=max_delta_seconds)
        if nearest >= 0:
            by_index.setdefault(nearest, []).append(_enrich_switch_event(event, nearest, active_peer_macs or [], active_peer_ap_names or [], active_peer_sites or []))
    return by_index


def _nearest_scoped_index(
    scoped: list[tuple[str, int]],
    sample_time: str,
    *,
    max_delta_seconds: float | None = None,
) -> int:
    if not scoped or not sample_time:
        return -1
    ordered = sorted(scoped)
    times = [value for value, _index in ordered]
    position = bisect_left(times, sample_time)
    candidates = ordered[max(position - 1, 0) : min(position + 1, len(ordered))]
    if not candidates:
        return -1
    target = _parse_time(sample_time)
    nearest = min(candidates, key=lambda item: abs((_parse_time(item[0]) - target).total_seconds()))
    delta_seconds = abs((_parse_time(nearest[0]) - target).total_seconds())
    if max_delta_seconds is not None and delta_seconds > max_delta_seconds:
        return -1
    return nearest[1]


def _sampling_tolerance_seconds(value: object) -> float:
    try:
        interval = float(value)
    except (TypeError, ValueError):
        return 0.0
    if interval <= 0:
        return 0.0
    return max(interval * 1.5, 0.25)


def _enrich_switch_event(
    event: dict[str, object],
    index: int,
    active_peer_macs: list[str],
    active_peer_ap_names: list[str],
    active_peer_sites: list[str],
) -> dict[str, object]:
    if event.get("event_type") != "ACTIVE_SWITCH":
        return event
    enriched = dict(event)
    from_peer = canonical_mesh_mac(enriched.get("from_peer_mac"))
    to_peer = canonical_mesh_mac(enriched.get("to_peer_mac"))
    if not str(enriched.get("to_peer_ap_name") or "").strip():
        enriched["to_peer_ap_name"] = _peer_name_near_index(to_peer, index, active_peer_macs, active_peer_ap_names)
    if not str(enriched.get("to_peer_site") or "").strip():
        enriched["to_peer_site"] = _peer_name_near_index(to_peer, index, active_peer_macs, active_peer_sites)
    if not str(enriched.get("from_peer_ap_name") or "").strip():
        enriched["from_peer_ap_name"] = _peer_name_near_index(from_peer, index - 1, active_peer_macs, active_peer_ap_names)
    if not str(enriched.get("from_peer_site") or "").strip():
        enriched["from_peer_site"] = _peer_name_near_index(from_peer, index - 1, active_peer_macs, active_peer_sites)
    return enriched


def _peer_name_near_index(peer: str, index: int, peers: list[str], values: list[str]) -> str:
    if not peer:
        return ""
    for candidate in (index, index - 1, index + 1):
        if 0 <= candidate < len(peers) and canonical_mesh_mac(peers[candidate]) == peer:
            return str(values[candidate] or "")
    for candidate_peer, value in zip(peers, values):
        if canonical_mesh_mac(candidate_peer) == peer and value:
            return str(value)
    return ""


def _nearest_time_index(times: list[str], sample_time: str) -> int:
    if not times or not sample_time:
        return -1
    if sample_time in times:
        return times.index(sample_time)
    parsed = _parse_time(sample_time)
    distances = [abs((_parse_time(value) - parsed).total_seconds()) for value in times]
    return int(min(range(len(distances)), key=lambda index: distances[index]))


def _float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(_sample_time(str(value)))


def _seconds_between(previous: str, current: str) -> float:
    try:
        return (_parse_time(current) - _parse_time(previous)).total_seconds()
    except (TypeError, ValueError):
        return 0.0


_SAMPLE_KEY_SEPARATOR = "\x1f"


def _sample_key(row: dict[str, object]) -> str:
    return _SAMPLE_KEY_SEPARATOR.join(
        (
            str(row.get("source_file_id") or ""),
            str(row.get("sample_time") or ""),
            str(row.get("timestamp_tag") or ""),
            str(row.get("radio") or ""),
        )
    )


def _sample_parts(value: str) -> tuple[str, str, str, str]:
    parts = str(value).split(_SAMPLE_KEY_SEPARATOR)
    if len(parts) == 4:
        return parts[0], parts[1], parts[2], parts[3]
    return "", str(value), "", ""


def _sample_source(value: str) -> str:
    return _sample_parts(value)[0]


def _sample_time(value: str) -> str:
    return _sample_parts(value)[1]


def _sample_tag(value: str) -> str:
    return _sample_parts(value)[2]


def _sample_radio(value: str) -> str:
    return _sample_parts(value)[3]


def _sample_sort_key(value: str) -> tuple[str, str, int, int]:
    source, sample_time, tag, radio = _sample_parts(value)
    digits = "".join(character for character in tag if character.isdigit())
    try:
        radio_number = int(radio)
    except ValueError:
        radio_number = 0
    return source, sample_time, int(digits or 0), radio_number
