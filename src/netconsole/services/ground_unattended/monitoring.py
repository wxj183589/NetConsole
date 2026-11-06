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
    return min(begin, finish - timedelta(hours=1)), finish


def mesh_evidence(rows: list[dict[str, Any]], start: datetime, end: datetime) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Only adjacent confirmed switches prove an interval. No terminal carry-forward."""
    events = []
    for row in rows:
        details = row.get("details") or row.get("parsed_details") or {}
        device_time = str(row.get("device_time") or details.get("device_time") or "")
        receive_time = str(row.get("receive_time") or "")
        try:
            event_time = _time(str(row.get("event_time") or device_time or receive_time))
        except ValueError:
            continue
        if not start <= event_time <= end:
            continue
        events.append({
            "id": row.get("id", ""), "event_time": event_time.isoformat(),
            "device_time": device_time, "receive_time": receive_time,
            "event_type": str(row.get("event_type") or ""), "source": "SYSLOG",
            "old_ap_name": str(row.get("previous_peer_name") or ""),
            "new_ap_name": str(row.get("peer_name") or ""),
            "old_bssid": str(details.get("previous_peer_radio_mac") or details.get("old_peer_radio_mac") or row.get("previous_peer_mac") or ""),
            "bssid": str(details.get("peer_radio_mac") or details.get("new_peer_radio_mac") or row.get("peer_mac") or ""),
            "rssi": details.get("rssi", details.get("new_rssi")), "raw_text": str(row.get("raw_text") or ""),
            "raw_file_id": str(row.get("raw_file_id") or ""), "raw_line_number": row.get("raw_line_number"),
            "event_time_source": str(row.get("event_time_source") or ""),
            "data_quality": str(row.get("data_quality") or ""),
            "identity_status": str(details.get("identity_status") or row.get("identity_status") or "unknown"),
        })
    events.sort(key=lambda item: item["event_time"])
    intervals = []
    for current, following in zip(events, events[1:]):
        # A later event must confirm the previous peer. Missing/disagreeing evidence is a gap.
        if (normalize_mac_key(current["bssid"]) and normalize_mac_key(current["bssid"]) == normalize_mac_key(following["old_bssid"])
                and current["event_type"] == "MESH_ACTIVELINK_SWITCH"
                and following["event_type"] == "MESH_ACTIVELINK_SWITCH"):
            intervals.append({
                "start": current["event_time"], "end": following["event_time"],
                "peer_name": current["new_ap_name"], "bssid": current["bssid"],
                "rssi": current["rssi"], "source": "SYSLOG",
                "device_time": current["device_time"], "receive_time": current["receive_time"],
            })
    return events, intervals


def indexed_evidence(db_path: Path, *, site_id: str, run_id: str, mr_uuid: str, start: datetime, end: datetime) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    """Read bounded indexed facts in one read-only snapshot, respecting UTC offsets."""
    with closing(sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        mesh_rows = connection.execute(
            "SELECT * FROM ground_unattended_wmesh_events WHERE site_id=? AND run_id=? AND device_uuid=? "
            "AND (event_family='WMESH' OR (event_family='' AND event_type LIKE 'MESH_%')) "
            "AND receive_time>=? AND receive_time<=? ORDER BY receive_time DESC,id DESC LIMIT 501",
            (site_id, run_id, mr_uuid, (start - timedelta(hours=14)).isoformat()[:19], (end + timedelta(hours=14)).isoformat()[:19] + "~"),
        ).fetchall()
        ac_rows = connection.execute(
            "SELECT * FROM ground_unattended_ac_snapshots WHERE site_id=? AND run_id=? AND mr_id=? "
            "AND received_at>=? AND received_at<=? ORDER BY received_at DESC,id DESC LIMIT 501",
            (site_id, run_id, mr_uuid, (start - timedelta(hours=14)).isoformat()[:19], (end + timedelta(hours=14)).isoformat()[:19] + "~"),
        ).fetchall()
    def within(row: sqlite3.Row, key: str) -> bool:
        try:
            return start <= _time(str(row[key])) <= end
        except ValueError:
            return False
    mesh = [dict(row) for row in mesh_rows[:500] if within(row, "receive_time")]
    for row in mesh:
        row["details"] = json.loads(row.get("details_json") or "{}")
    return mesh, [dict(row) for row in ac_rows[:500] if within(row, "received_at")], len(mesh_rows) > 500 or len(ac_rows) > 500


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
        result.append({"start": start.isoformat(), "end": end.isoformat(), "peer_name": str(row.get("peer_ap_name") or ""),
                       "bssid": "", "peer_mac": str(row.get("peer_ap_mac") or ""), "rssi": row.get("rssi"), "source": "AC",
                       "device_time": str(row.get("device_time") or ""), "receive_time": str(row.get("received_at") or ""),
                       "data_status": str(row.get("freshness_status") or ""), "sampled_interval": True})
    return result


def _time(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("监测时间必须包含时区")
    return result.astimezone(timezone.utc)
