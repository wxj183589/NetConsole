from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from netconsole.services.ap_identity.normalizers import normalize_mac_key
from netconsole.services.fit_ap_link_info import (
    format_h3c_mac,
    normalize_interface_key,
    normalize_lldp_payload,
)


LLDP_CANONICAL_STATE_FIELDS = (
    "local_interface_normalized",
    "neighbor_mac_normalized",
    "neighbor_interface_normalized",
    "neighbor_name",
    "match_status",
)
LLDP_PROJECTION_FIELDS = (
    "resource_key",
    "ac_device_uuid",
    "ap_uuid",
    "ap_name",
    "ap_mac",
    "ap_mac_normalized",
    "source",
    "lldp_confidence",
    "local_interface",
    "local_interface_normalized",
    "lldp_neighbor",
    "neighbor_interface",
    "neighbor_interface_normalized",
    "neighbor_mac",
    "neighbor_mac_normalized",
    "neighbor_device_name",
    "neighbor_name",
    "lldp_match_status",
    "conflict_flag",
    "collected_at",
    "collect_run_uuid",
    "raw_log_path",
)


def _text(value: object) -> str:
    return str(value or "").strip()


def _first(row: dict[str, Any], *fields: str) -> object:
    for field in fields:
        value = row.get(field)
        if value not in (None, ""):
            return value
    return ""


def _timestamp(row: dict[str, Any], fallback: str = "") -> str:
    return _text(
        _first(row, "lldp_collected_at", "collected_at", "last_seen_at", "updated_at")
    ) or fallback


def canonical_lldp_state(row: dict[str, Any]) -> dict[str, str]:
    normalized = normalize_lldp_payload(
        {
            **row,
            "lldp_local_interface": _first(
                row, "lldp_local_interface", "local_interface", "interface_name"
            ),
            "lldp_neighbor_name": _first(
                row,
                "lldp_neighbor_name",
                "neighbor_name",
                "lldp_neighbor",
                "neighbor_device_name",
            ),
            "lldp_neighbor_mac": _first(row, "lldp_neighbor_mac", "neighbor_mac"),
            "lldp_neighbor_interface": _first(
                row, "lldp_neighbor_interface", "neighbor_interface"
            ),
        },
        _text(_first(row, "lldp_source", "source")) or "unknown",
    )
    return {
        "local_interface_normalized": _text(
            normalized.get("lldp_local_interface_normalized")
        ),
        "neighbor_mac_normalized": _text(
            normalized.get("lldp_neighbor_mac_normalized")
        ),
        "neighbor_interface_normalized": normalize_interface_key(
            normalized.get("lldp_neighbor_interface")
        ),
        "neighbor_name": _text(normalized.get("lldp_neighbor_name")),
        "match_status": _text(normalized.get("lldp_match_status")).casefold(),
    }


def canonical_state_json(state: dict[str, str]) -> str:
    return json.dumps(
        {field: _text(state.get(field)) for field in LLDP_CANONICAL_STATE_FIELDS},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_state_fingerprint(state: dict[str, str]) -> str:
    return hashlib.sha256(canonical_state_json(state).encode("utf-8")).hexdigest()


def build_lldp_projection(
    row: dict[str, Any],
    *,
    source_revision: str = "",
    fallback_time: str = "",
) -> dict[str, Any]:
    source = _text(_first(row, "lldp_source", "source")) or "unknown"
    normalized = normalize_lldp_payload(
        {
            **row,
            "lldp_local_interface": _first(
                row, "lldp_local_interface", "local_interface", "interface_name"
            ),
            "lldp_neighbor_name": _first(
                row,
                "lldp_neighbor_name",
                "neighbor_name",
                "lldp_neighbor",
                "neighbor_device_name",
            ),
            "lldp_neighbor_mac": _first(row, "lldp_neighbor_mac", "neighbor_mac"),
            "lldp_neighbor_interface": _first(
                row, "lldp_neighbor_interface", "neighbor_interface"
            ),
        },
        source,
    )
    ap_uuid = _text(row.get("ap_uuid"))
    if not ap_uuid:
        raise ValueError("LLDP resource identity is missing ap_uuid")
    local_interface = _text(normalized.get("lldp_local_interface"))
    neighbor_name = _text(normalized.get("lldp_neighbor_name"))
    neighbor_interface = _text(normalized.get("lldp_neighbor_interface"))
    neighbor_mac = _text(normalized.get("lldp_neighbor_mac"))
    match_status = _text(
        row.get("lldp_match_status") or normalized.get("lldp_match_status")
    ).casefold()
    state = canonical_lldp_state(row)
    return {
        "resource_key": ap_uuid,
        "ac_device_uuid": _text(row.get("ac_device_uuid")),
        "ap_uuid": ap_uuid,
        "ap_name": _text(row.get("ap_name")),
        "ap_mac": _text(row.get("ap_mac")) or format_h3c_mac(row.get("ap_mac")),
        "ap_mac_normalized": normalize_mac_key(row.get("ap_mac")) or "",
        "source": source,
        "lldp_confidence": int(row.get("lldp_confidence") or 0),
        "local_interface": local_interface,
        "local_interface_normalized": state["local_interface_normalized"],
        "lldp_neighbor": neighbor_name,
        "neighbor_interface": neighbor_interface,
        "neighbor_interface_normalized": state["neighbor_interface_normalized"],
        "neighbor_mac": neighbor_mac,
        "neighbor_mac_normalized": state["neighbor_mac_normalized"],
        "neighbor_device_name": _text(
            row.get("neighbor_device_name") or neighbor_name
        ),
        "neighbor_name": neighbor_name,
        "lldp_match_status": match_status,
        "conflict_flag": int(
            bool(row.get("conflict_flag")) or match_status == "conflict"
        ),
        "collected_at": _timestamp(row, fallback_time),
        "collect_run_uuid": _text(row.get("collect_run_uuid") or row.get("session_id")),
        "raw_log_path": _text(row.get("raw_log_path")),
        "source_revision": _text(source_revision),
        "state_json": canonical_state_json(state),
        "state_fingerprint": canonical_state_fingerprint(state),
    }


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _insert_projection(conn, table: str, projection: dict[str, Any], **extra: Any) -> None:
    values = {**projection, **extra}
    fields = (
        "resource_key",
        "ac_device_uuid",
        "ap_uuid",
        "ap_name",
        "ap_mac",
        "ap_mac_normalized",
        "source",
        "lldp_confidence",
        "local_interface",
        "local_interface_normalized",
        "lldp_neighbor",
        "neighbor_interface",
        "neighbor_interface_normalized",
        "neighbor_mac",
        "neighbor_mac_normalized",
        "neighbor_device_name",
        "neighbor_name",
        "lldp_match_status",
        "conflict_flag",
        "collected_at",
        "collect_run_uuid",
        "raw_log_path",
    )
    if table == "fit_ap_lldp_current":
        fields += (
            "state_json",
            "state_fingerprint",
            "first_seen_at",
            "last_seen_at",
            "changed_at",
            "source_revision",
            "created_at",
            "updated_at",
        )
    else:
        fields += (
            "previous_state_json",
            "state_json",
            "state_fingerprint",
            "changed_at",
            "source_revision",
            "change_kind",
            "created_at",
        )
    columns = ", ".join(fields)
    placeholders = ", ".join("?" for _ in fields)
    conn.execute(
        f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",
        [values.get(field) for field in fields],
    )


def upsert_lldp_current_and_history(
    conn,
    row: dict[str, Any],
    *,
    source_revision: str = "",
    now: str = "",
) -> dict[str, Any]:
    """Update bounded LLDP current/history in the caller's transaction."""

    timestamp = _timestamp(row, fallback=now or _now_iso())
    updated_at = now or _now_iso()
    projection = build_lldp_projection(
        row,
        source_revision=source_revision,
        fallback_time=timestamp,
    )
    conn.execute(
        """
        INSERT INTO fit_ap_lldp_retention_meta(key, value)
        VALUES ('authority', 'bounded_v1')
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """
    )
    current = conn.execute(
        "SELECT * FROM fit_ap_lldp_current "
        "WHERE ac_device_uuid = ? AND ap_uuid = ?",
        (projection["ac_device_uuid"], projection["ap_uuid"]),
    ).fetchone()
    if current is None:
        _insert_projection(
            conn,
            "fit_ap_lldp_current",
            projection,
            first_seen_at=timestamp,
            last_seen_at=timestamp,
            changed_at=None,
            created_at=updated_at,
            updated_at=updated_at,
        )
        return {**projection, "first_seen_at": timestamp, "last_seen_at": timestamp}

    current_data = dict(current)
    if str(current_data.get("state_fingerprint") or "") == projection["state_fingerprint"]:
        conn.execute(
            """
            UPDATE fit_ap_lldp_current SET
                ac_device_uuid=?, ap_uuid=?, ap_name=?, ap_mac=?, ap_mac_normalized=?,
                source=?, lldp_confidence=?, local_interface=?, local_interface_normalized=?,
                lldp_neighbor=?, neighbor_interface=?, neighbor_interface_normalized=?,
                neighbor_mac=?, neighbor_mac_normalized=?, neighbor_device_name=?,
                neighbor_name=?, lldp_match_status=?, conflict_flag=?, collected_at=?,
                collect_run_uuid=?, raw_log_path=?, last_seen_at=?, source_revision=?,
                state_json=?, state_fingerprint=?, updated_at=?
            WHERE ac_device_uuid=? AND ap_uuid=?
            """,
            (
                projection["ac_device_uuid"], projection["ap_uuid"], projection["ap_name"],
                projection["ap_mac"], projection["ap_mac_normalized"], projection["source"],
                projection["lldp_confidence"], projection["local_interface"],
                projection["local_interface_normalized"], projection["lldp_neighbor"],
                projection["neighbor_interface"], projection["neighbor_interface_normalized"],
                projection["neighbor_mac"], projection["neighbor_mac_normalized"],
                projection["neighbor_device_name"], projection["neighbor_name"],
                projection["lldp_match_status"], projection["conflict_flag"],
                projection["collected_at"], projection["collect_run_uuid"],
                projection["raw_log_path"], timestamp, projection["source_revision"],
                projection["state_json"], projection["state_fingerprint"], updated_at,
                projection["ac_device_uuid"], projection["ap_uuid"],
            ),
        )
        return {**current_data, **projection, "last_seen_at": timestamp}

    _insert_projection(
        conn,
        "fit_ap_lldp_history",
        projection,
        previous_state_json=str(current_data.get("state_json") or "{}"),
        changed_at=timestamp,
        change_kind="change",
        created_at=updated_at,
    )
    conn.execute(
        """
        UPDATE fit_ap_lldp_current SET
            ac_device_uuid=?, ap_uuid=?, ap_name=?, ap_mac=?, ap_mac_normalized=?,
            source=?, lldp_confidence=?, local_interface=?, local_interface_normalized=?,
            lldp_neighbor=?, neighbor_interface=?, neighbor_interface_normalized=?,
            neighbor_mac=?, neighbor_mac_normalized=?, neighbor_device_name=?,
            neighbor_name=?, lldp_match_status=?, conflict_flag=?, collected_at=?,
            collect_run_uuid=?, raw_log_path=?, last_seen_at=?, changed_at=?,
            source_revision=?, state_json=?, state_fingerprint=?, updated_at=?
        WHERE ac_device_uuid=? AND ap_uuid=?
        """,
        (
            projection["ac_device_uuid"], projection["ap_uuid"], projection["ap_name"],
            projection["ap_mac"], projection["ap_mac_normalized"], projection["source"],
            projection["lldp_confidence"], projection["local_interface"],
            projection["local_interface_normalized"], projection["lldp_neighbor"],
            projection["neighbor_interface"], projection["neighbor_interface_normalized"],
            projection["neighbor_mac"], projection["neighbor_mac_normalized"],
            projection["neighbor_device_name"], projection["neighbor_name"],
            projection["lldp_match_status"], projection["conflict_flag"],
            projection["collected_at"], projection["collect_run_uuid"],
            projection["raw_log_path"], timestamp, timestamp, projection["source_revision"],
            projection["state_json"], projection["state_fingerprint"], updated_at,
            projection["ac_device_uuid"], projection["ap_uuid"],
        ),
    )
    conn.execute(
        """
        DELETE FROM fit_ap_lldp_history
        WHERE ac_device_uuid=? AND ap_uuid=? AND id NOT IN (
            SELECT id FROM fit_ap_lldp_history
            WHERE ac_device_uuid=? AND ap_uuid=?
            ORDER BY changed_at DESC, id DESC
            LIMIT 10
        )
        """,
        (
            projection["ac_device_uuid"],
            projection["ap_uuid"],
            projection["ac_device_uuid"],
            projection["ap_uuid"],
        ),
    )
    return {**current_data, **projection, "last_seen_at": timestamp, "changed_at": timestamp}


__all__ = [
    "LLDP_CANONICAL_STATE_FIELDS",
    "LLDP_PROJECTION_FIELDS",
    "build_lldp_projection",
    "canonical_lldp_state",
    "canonical_state_fingerprint",
    "canonical_state_json",
    "upsert_lldp_current_and_history",
]
