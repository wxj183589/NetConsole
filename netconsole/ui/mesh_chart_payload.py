from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

import numpy as np
from matplotlib.dates import date2num

from netconsole.models.mesh_log_models import LINK_STATE_ACTIVE


@dataclass(frozen=True)
class ActiveRun:
    peer_mac: str
    start_sample_index: int
    end_sample_index: int
    active_sample_indices: tuple[int, ...]


def build_chart_payload(peer_segment: dict[str, object], run_segment: dict[str, object]) -> dict[str, object]:
    peer_rows = [row for row in peer_segment.get("rows", []) if isinstance(row, dict)]
    run_rows = [row for row in run_segment.get("rows", []) if isinstance(row, dict)]
    events = [event for event in run_segment.get("events", []) if isinstance(event, dict)]
    anchor = peer_segment.get("anchor") if isinstance(peer_segment.get("anchor"), dict) else run_segment.get("anchor")
    anchor_time = str(anchor.get("sample_time")) if isinstance(anchor, dict) and anchor.get("sample_time") else ""
    master_times = sorted({str(row.get("sample_time")) for row in run_rows if row.get("sample_time")})
    if not master_times:
        master_times = sorted({str(row.get("sample_time")) for row in peer_rows if row.get("sample_time")})
    time_index = {sample_time: index for index, sample_time in enumerate(master_times)}
    timestamps = [_parse_time(value) for value in master_times]
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
    session_bounds: dict[str, list[str]] = {}
    for row in peer_rows:
        index = time_index.get(str(row.get("sample_time")))
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
        if session_id:
            bounds = session_bounds.setdefault(session_id, [str(row.get("sample_time")), str(row.get("sample_time"))])
            bounds[0] = min(bounds[0], str(row.get("sample_time")))
            bounds[1] = max(bounds[1], str(row.get("sample_time")))
        metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
        peer_series["local_rssi"][index] = _float(metrics.get("local_rssi_db"))
        peer_series["peer_rssi"][index] = _float(metrics.get("peer_rssi_db"))
        peer_series["local_noise"][index] = _float(metrics.get("local_noise_raw"))
        peer_series["peer_noise"][index] = _float(metrics.get("peer_noise_raw"))
        peer_series["local_tx_busy"][index] = _float(metrics.get("local_tx_busy"))
        peer_series["peer_tx_busy"][index] = _float(metrics.get("peer_tx_busy"))
        peer_series["local_rx_busy"][index] = _float(metrics.get("local_rx_busy"))
        peer_series["peer_rx_busy"][index] = _float(metrics.get("peer_rx_busy"))
        peer_series["state"][index] = 1 if row.get("link_state") == LINK_STATE_ACTIVE else 0
    rows_by_time, rows_by_time_and_peer = _index_rows_by_time(run_rows)
    unique_active_by_index, no_active_indices, multi_active_indices = build_unique_active_samples(master_times, rows_by_time)
    active_runs = build_active_runs(master_times, unique_active_by_index)
    active_series = _empty_active_series(count)
    active_peer_macs = [""] * count
    active_peer_ap_names = [""] * count
    active_peer_sites = [""] * count
    active_peer_radios = [""] * count
    active_peer_rssi = np.full(count, np.nan, dtype=np.float32)
    standby_links_by_index = [[] for _ in range(count)]
    peer_change_indices = [run.start_sample_index for run in active_runs[1:]]
    rapid_flaps = detect_rapid_flaps(active_runs, master_times, peer_segment.get("estimated_interval_seconds") or run_segment.get("estimated_interval_seconds"))
    rapid_flap_indices = [int(item["return_sample_index"]) for item in rapid_flaps]
    assign_active_series(active_runs, master_times, rows_by_time_and_peer, active_series, active_peer_macs, active_peer_ap_names, active_peer_sites, active_peer_radios, active_peer_rssi)
    assign_standby_links(master_times, rows_by_time, standby_links_by_index)
    events_by_index = _events_by_index(events, time_index, active_peer_macs, active_peer_ap_names, active_peer_sites)
    switch_indices = [index for index, items in events_by_index.items() if any(item.get("event_type") == "ACTIVE_SWITCH" for item in items)]
    anchor_index = _nearest_time_index(master_times, anchor_time)
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
        "timestamp_labels": master_times,
        "timestamp_numeric": timestamp_numeric,
        "peer_series": peer_series,
        "active_series": active_series,
        "active_peer_macs": active_peer_macs,
        "active_peer_ap_names": active_peer_ap_names,
        "active_peer_sites": active_peer_sites,
        "active_peer_radios": active_peer_radios,
        "active_peer_rssi": active_peer_rssi,
        "standby_links_by_index": standby_links_by_index,
        "peer_macs": peer_macs,
        "peer_ap_names": peer_ap_names,
        "peer_sites": peer_sites,
        "peer_radios": peer_radios,
        "peer_link_states": peer_link_states,
        "peer_establish_times": peer_establish_times,
        "peer_session_ids": peer_session_ids,
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


def render_indices(total_count: int, start_index: int, visible_count: int, important_indices: Iterable[int], max_points: int) -> np.ndarray:
    if total_count <= 0:
        return np.asarray([], dtype=np.int32)
    if visible_count > 0:
        start = max(start_index - 2, 0)
        end = min(start_index + visible_count + 2, total_count)
        return np.arange(start, end, dtype=np.int32)
    important = {int(index) for index in important_indices if 0 <= int(index) < total_count}
    if total_count <= max_points:
        return np.arange(total_count, dtype=np.int32)
    keep = {0, total_count - 1, *important}
    bucket_count = max((max_points - len(keep)) // 2, 1)
    bucket_size = max(total_count // bucket_count, 1)
    for start in range(0, total_count, bucket_size):
        end = min(start + bucket_size, total_count)
        keep.add(start)
        keep.add(end - 1)
    return np.asarray(sorted(keep), dtype=np.int32)


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
        rows_by_time.setdefault(sample_time, []).append(row)
        peer = canonical_mesh_mac(row)
        if peer:
            rows_by_time_and_peer.setdefault(sample_time, {})[peer] = row
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
                metrics = active_row.get("metrics") if isinstance(active_row.get("metrics"), dict) else {}
                active_series["active_local_rssi"][sample_index] = _float(metrics.get("local_rssi_db"))
                active_peer_rssi[sample_index] = _float(metrics.get("peer_rssi_db"))
                active_series["active_local_tx_busy"][sample_index] = _float(metrics.get("local_tx_busy"))
                active_series["active_local_rx_busy"][sample_index] = _float(metrics.get("local_rx_busy"))


def assign_standby_links(
    master_times: list[str],
    rows_by_time: dict[str, list[dict[str, object]]],
    standby_links_by_index: list[list[dict[str, object]]],
) -> None:
    for index, sample_time in enumerate(master_times):
        standby_rows = [row for row in rows_by_time.get(sample_time, []) if row.get("link_state") == "STANDBY"]
        items = [_standby_summary(row) for row in standby_rows]
        items.sort(key=lambda item: _sort_rssi(item.get("mr_rssi")), reverse=True)
        standby_links_by_index[index] = items[:3]


def _standby_summary(row: dict[str, object]) -> dict[str, object]:
    metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
    return {
        "peer_mac": row.get("peer_mac_normalized") or row.get("peer_mac_raw") or "",
        "ap_name": row.get("peer_ap_name") or "",
        "site": row.get("peer_site") or "",
        "radio": row.get("radio") or "",
        "peer_radio": row.get("peer_radio") or row.get("peer_radio_label") or "",
        "mr_rssi": metrics.get("local_rssi_db"),
        "ap_rssi": metrics.get("peer_rssi_db"),
    }


def _sort_rssi(value: object) -> float:
    parsed = _float(value)
    return parsed if np.isfinite(parsed) else float("-inf")


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
    time_index: dict[str, int],
    active_peer_macs: list[str] | None = None,
    active_peer_ap_names: list[str] | None = None,
    active_peer_sites: list[str] | None = None,
) -> dict[int, list[dict[str, object]]]:
    by_index: dict[int, list[dict[str, object]]] = {}
    for event in events:
        sample_time = str(event.get("event_time") or event.get("current_sample_time") or "")
        if sample_time in time_index:
            index = time_index[sample_time]
            by_index.setdefault(index, []).append(_enrich_switch_event(event, index, active_peer_macs or [], active_peer_ap_names or [], active_peer_sites or []))
            continue
        nearest = _nearest_time_index(list(time_index), sample_time)
        if nearest >= 0:
            by_index.setdefault(nearest, []).append(_enrich_switch_event(event, nearest, active_peer_macs or [], active_peer_ap_names or [], active_peer_sites or []))
    return by_index


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
    return datetime.fromisoformat(str(value))


def _seconds_between(previous: str, current: str) -> float:
    try:
        return (datetime.fromisoformat(current) - datetime.fromisoformat(previous)).total_seconds()
    except (TypeError, ValueError):
        return 0.0
