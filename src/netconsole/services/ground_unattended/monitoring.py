"""Read-only correlation of durable MR evidence; never changes reachability."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import sqlite3
from pathlib import Path
from typing import Any
from contextlib import closing
from netconsole.services.ap_identity.normalizers import normalize_mac_key


def monitoring_range(start: str, end: str) -> tuple[datetime, datetime]:
    finish = _time(end) if end else datetime.now(timezone.utc)
    begin = _time(start) if start else finish - timedelta(hours=1)
    if begin >= finish or (finish - begin).total_seconds() > 86_400:
        raise ValueError("监测时间范围必须为正且不超过 24 小时")
    return begin, finish


def normalize_rssi(raw_value: object) -> tuple[float | None, str]:
    """Normalize a Syslog RSSI value whose source contract allows magnitude."""
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        return None, "MISSING"
    value = float(raw_value)
    if -120 <= value <= 0:
        return value, "NATIVE_DBM"
    if 0 < value <= 120:
        return -value, "ABSOLUTE_MAGNITUDE"
    return value, "OUT_OF_RANGE"


def normalize_ac_rssi(raw_value: object) -> tuple[float | None, str]:
    """AC snapshots have no verified magnitude contract; never guess positives."""

    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        return None, "MISSING"
    value = float(raw_value)
    if -120 <= value <= 0:
        return value, "NATIVE_DBM"
    return None, "OUT_OF_RANGE"


def mesh_evidence(rows: list[dict[str, Any]], start: datetime, end: datetime) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Only adjacent MESH_ACTIVELINK_SWITCH records prove an interval."""
    evidence = []
    for row in rows:
        if str(row.get("event_type") or "").upper() != "MESH_ACTIVELINK_SWITCH":
            continue
        details = row.get("details") or row.get("parsed_details") or {}
        device_time = str(row.get("device_time") or details.get("device_time") or "")
        receive_time = str(row.get("receive_time") or "")
        try:
            event_time = _time(str(row.get("event_time") or device_time or receive_time))
        except ValueError:
            continue
        raw_rssi = details.get("rssi")
        if raw_rssi is None:
            raw_rssi = details.get("new_rssi")
        exit_rssi = details.get("old_rssi", row.get("previous_rssi"))
        if exit_rssi is None:
            exit_rssi = details.get("previous_rssi")
        normalized_rssi, rssi_semantics = normalize_rssi(raw_rssi)
        station = str(details.get("station") or row.get("station") or "")
        section = str(details.get("section") or row.get("section") or "")
        # AP identity is the canonical/raw peer MAC.  The radio MAC is only a
        # fallback for legacy rows that predate the AP identity projection.
        old_ap_mac = (
            details.get("previous_peer_ap_mac")
            or details.get("old_peer_mac")
            or row.get("previous_peer_mac")
            or details.get("previous_peer_radio_mac")
            or details.get("old_peer_radio_mac")
            or ""
        )
        new_ap_mac = (
            details.get("peer_ap_mac")
            or details.get("new_peer_mac")
            or row.get("peer_mac")
            or details.get("peer_radio_mac")
            or details.get("new_peer_radio_mac")
            or ""
        )
        evidence.append({
            "id": row.get("id", ""), "event_time": event_time.isoformat(),
            "device_time": device_time, "receive_time": receive_time,
            "event_type": str(row.get("event_type") or ""), "source": "SYSLOG",
            "old_ap_name": str(row.get("previous_peer_name") or details.get("previous_peer_ap_name") or ""),
            "new_ap_name": str(row.get("peer_name") or details.get("peer_ap_name") or ""),
            "old_bssid": str(old_ap_mac),
            "bssid": str(new_ap_mac),
            "rssi": normalized_rssi, "raw_rssi": raw_rssi,
            "previous_rssi": exit_rssi,
            "entry_rssi": raw_rssi, "exit_rssi": exit_rssi,
            "rssi_semantics": rssi_semantics,
            "raw_text": str(row.get("raw_text") or ""),
            "raw_file_id": str(row.get("raw_file_id") or ""), "raw_line_number": row.get("raw_line_number"),
            "event_time_source": str(row.get("event_time_source") or ""),
            "data_quality": str(row.get("data_quality") or ""),
            "identity_status": str(details.get("identity_status") or row.get("identity_status") or "unknown"),
            "station": station, "section": section,
        })
    evidence.sort(key=lambda item: item["event_time"])
    intervals = []
    for current, following in zip(evidence, evidence[1:]):
        # A later event must confirm the previous peer. Missing/disagreeing evidence is a gap.
        if (normalize_mac_key(current["bssid"]) and normalize_mac_key(current["bssid"]) == normalize_mac_key(following["old_bssid"])
                and _time(current["event_time"]) < end
                and _time(following["event_time"]) > start):
            intervals.append({
                "start": max(start, _time(current["event_time"])).isoformat(),
                "end": min(end, _time(following["event_time"])).isoformat(),
                "peer_name": current["new_ap_name"], "bssid": current["bssid"],
                "rssi": current["rssi"], "raw_rssi": current["raw_rssi"],
                "entry_rssi": current.get("entry_rssi"),
                # The next switch describes the AP being left. Do not copy
                # the entry RSSI when the source has no exit value.
                "exit_rssi": following.get("exit_rssi"),
                "rssi_semantics": current["rssi_semantics"], "source": "SYSLOG",
                "device_time": current["device_time"], "receive_time": current["receive_time"],
                "station": current.get("station", ""), "section": current.get("section", ""),
            })
    events = [item for item in evidence if start <= _time(item["event_time"]) <= end]
    return events, intervals


def indexed_evidence(db_path: Path, *, site_id: str, run_id: str | None, mr_uuid: str, start: datetime, end: datetime) -> tuple[list[dict[str, Any]], bool]:
    """Read bounded indexed facts in one read-only snapshot, respecting UTC offsets."""
    # DEV playback is business-read-only, but it may read a live WAL snapshot.
    # Ordinary mode=ro lets SQLite resolve WAL state; query_only prevents writes.
    with closing(sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        run_clause = " AND run_id=?" if run_id is not None else ""
        params = (site_id, *((run_id,) if run_id is not None else ()), mr_uuid, start.isoformat(), end.isoformat())
        mesh_rows = connection.execute(
            f"SELECT * FROM ground_unattended_wmesh_events WHERE site_id=?{run_clause} AND device_uuid=? "
            "AND event_type='MESH_ACTIVELINK_SWITCH' "
            "AND julianday(COALESCE(NULLIF(event_time,''),NULLIF(device_time,''),receive_time))>=julianday(?) "
            "AND julianday(COALESCE(NULLIF(event_time,''),NULLIF(device_time,''),receive_time))<=julianday(?) "
            "ORDER BY julianday(COALESCE(NULLIF(event_time,''),NULLIF(device_time,''),receive_time)) DESC,id DESC LIMIT 501",
            params,
        ).fetchall()
        prelude_params = (site_id, *((run_id,) if run_id is not None else ()), mr_uuid, start.isoformat())
        prelude = connection.execute(
            f"SELECT * FROM ground_unattended_wmesh_events WHERE site_id=?{run_clause} AND device_uuid=? "
            "AND event_type='MESH_ACTIVELINK_SWITCH' "
            "AND julianday(COALESCE(NULLIF(event_time,''),NULLIF(device_time,''),receive_time))<julianday(?) "
            "ORDER BY julianday(COALESCE(NULLIF(event_time,''),NULLIF(device_time,''),receive_time)) DESC,id DESC LIMIT 1",
            prelude_params,
        ).fetchall()
    # Return only records in the requested window plus the preceding record
    # needed to close an interval that starts before the window. A following
    # record outside the window is intentionally not exposed as playback data.
    mesh = [dict(row) for row in (*prelude, *mesh_rows[:500])]
    for row in mesh:
        row["details"] = json.loads(row.get("details_json") or "{}")
    return mesh, len(mesh_rows) > 500


def ac_peer_intervals(rows: list[dict[str, Any]], syslog_intervals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Consecutive fresh AC observations corroborate at most a 30-second span."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(str(row.get("received_at") or ""), []).append(row)
    observations = []
    for stamp, group in groups.items():
        identities = {normalize_mac_key(row.get("peer_ap_mac")) for row in group}
        row = group[0]
        valid = len(identities) == 1 and bool(next(iter(identities))) and all(str(item.get("freshness_status") or "").casefold() in {"fresh", "recent"} for item in group)
        try:
            instant = _time(stamp)
        except ValueError:
            continue
        observations.append((instant, row if valid else {}))
    observations.sort(key=lambda item: item[0])
    result = []
    for (start, row), (end, following) in zip(observations, observations[1:]):
        if not row or not following or not 0 < (end - start).total_seconds() <= 30 or normalize_mac_key(row.get("peer_ap_mac")) != normalize_mac_key(following.get("peer_ap_mac")):
            continue
        # Syslog wins the entire overlap; do not fabricate a finer boundary.
        if any(start < _time(item["end"]) and end > _time(item["start"]) for item in syslog_intervals):
            continue
        normalized_rssi, rssi_semantics = normalize_ac_rssi(row.get("rssi"))
        result.append({"start": start.isoformat(), "end": end.isoformat(), "peer_name": str(row.get("peer_ap_name") or ""),
                       "bssid": "", "peer_mac": str(row.get("peer_ap_mac") or ""), "rssi": normalized_rssi,
                       "raw_rssi": row.get("rssi"), "rssi_semantics": rssi_semantics, "source": "AC",
                       "device_time": str(row.get("device_time") or ""), "receive_time": str(row.get("received_at") or ""),
                       "data_status": str(row.get("freshness_status") or ""), "sampled_interval": True,
                       "station": str(row.get("station") or ""), "section": str(row.get("section") or "")})
    return result


def _time(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("监测时间必须包含时区")
    return result.astimezone(timezone.utc)
