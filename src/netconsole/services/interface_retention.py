"""Bounded Current + change-only History for device interfaces."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

INTERFACE_HISTORY_LIMIT = 10
INTERFACE_RETENTION_AUTHORITY = "bounded_v1"
INTERFACE_COLUMNS = (
    "device_uuid",
    "interface_name",
    "link_status",
    "admin_status",
    "physical_status",
    "protocol_status",
    "media_attribute",
    "media_type",
    "category",
    "speed",
    "duplex",
    "interface_type",
    "port_status",
    "port_mode",
    "pvid",
    "native_vlan",
    "tagged_vlans",
    "untagged_vlans",
    "pvid_source",
    "pvid_verified",
    "vlan_config_status",
    "vlan_config_collected_at",
    "vlan_warnings",
    "description",
    "ip_address",
    "mac_address",
    "vlan",
    "last_change",
    "collected_at",
    "collect_run_uuid",
    "raw_log_path",
    "updated_at",
)
INTERFACE_STATE_FIELDS = tuple(
    field
    for field in INTERFACE_COLUMNS
    if field
    not in {
        "collected_at",
        "collect_run_uuid",
        "raw_log_path",
        "updated_at",
        "vlan_config_collected_at",
    }
)
_INTERFACE_KEY_COLUMNS = ("device_uuid", "interface_name")


def _text(value: object) -> str:
    return str(value or "").strip()


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _db_value(value: object) -> object:
    if isinstance(value, (list, tuple, dict)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return value


def _state_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return str(value).strip()


def canonical_interface_state(row: dict[str, Any]) -> dict[str, str]:
    return {field: _state_value(row.get(field)) for field in INTERFACE_STATE_FIELDS}


def canonical_state_json(state: dict[str, str]) -> str:
    return json.dumps(
        {field: _state_value(state.get(field)) for field in INTERFACE_STATE_FIELDS},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_state_fingerprint(state: dict[str, str]) -> str:
    return hashlib.sha256(canonical_state_json(state).encode("utf-8")).hexdigest()


def build_interface_projection(
    row: dict[str, Any],
    *,
    site_id: str,
    now: str,
) -> dict[str, Any]:
    device_uuid = _text(row.get("device_uuid"))
    interface_name = _text(row.get("interface_name"))
    if not device_uuid or not interface_name:
        raise ValueError("Interface identity requires device_uuid and interface_name")
    projection = {field: _db_value(row.get(field)) for field in INTERFACE_COLUMNS}
    projection["device_uuid"] = device_uuid
    projection["interface_name"] = interface_name
    projection["collected_at"] = _text(row.get("collected_at")) or now
    projection["updated_at"] = _text(row.get("updated_at")) or now
    projection["source_revision"] = _text(row.get("source_revision") or row.get("collect_run_uuid"))
    state = canonical_interface_state(projection)
    projection["state_json"] = canonical_state_json(state)
    projection["state_fingerprint"] = canonical_state_fingerprint(state)
    projection["site_id"] = _text(site_id)
    return projection


def interface_retention_authority_enabled(conn) -> bool:
    try:
        row = conn.execute(
            "SELECT value FROM device_interface_retention_meta WHERE key='authority'"
        ).fetchone()
    except Exception:
        return False
    return _text(row[0] if row is not None else "") == INTERFACE_RETENTION_AUTHORITY


def _insert_current(conn, projection: dict[str, Any], *, now: str) -> None:
    fields = (
        *INTERFACE_COLUMNS,
        "site_id",
        "state_json",
        "state_fingerprint",
        "first_seen_at",
        "last_seen_at",
        "changed_at",
        "source_revision",
    )
    values = [projection.get(field) for field in fields]
    values[fields.index("first_seen_at")] = projection["collected_at"]
    values[fields.index("last_seen_at")] = projection["collected_at"]
    values[fields.index("changed_at")] = None
    conn.execute(
        f"INSERT INTO device_interfaces ({', '.join(fields)}) VALUES ({', '.join('?' for _ in fields)})",
        values,
    )


def _insert_history(
    conn,
    projection: dict[str, Any],
    *,
    previous_state_json: str,
    now: str,
) -> None:
    fields = (
        *INTERFACE_COLUMNS,
        "site_id",
        "state_json",
        "state_fingerprint",
        "previous_state_json",
        "changed_at",
        "source_revision",
        "change_kind",
        "created_at",
    )
    values = [projection.get(field) for field in fields]
    values[fields.index("previous_state_json")] = previous_state_json
    values[fields.index("changed_at")] = projection["collected_at"]
    values[fields.index("source_revision")] = projection["source_revision"]
    values[fields.index("change_kind")] = "change"
    values[fields.index("created_at")] = now
    conn.execute(
        f"INSERT INTO device_interfaces_history ({', '.join(fields)}) VALUES ({', '.join('?' for _ in fields)})",
        values,
    )


def upsert_interface_current_and_history(
    conn,
    row: dict[str, Any],
    *,
    site_id: str,
    now: str = "",
) -> dict[str, Any]:
    timestamp = now or _now_iso()
    projection = build_interface_projection(row, site_id=site_id, now=timestamp)
    conn.execute(
        "INSERT INTO device_interface_retention_meta(key,value) VALUES ('authority',?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (INTERFACE_RETENTION_AUTHORITY,),
    )
    key_values = tuple(projection[key] for key in _INTERFACE_KEY_COLUMNS)
    current = conn.execute(
        "SELECT * FROM device_interfaces WHERE device_uuid=? AND interface_name=?",
        key_values,
    ).fetchone()
    if current is None:
        _insert_current(conn, projection, now=timestamp)
        return projection
    current_data = dict(current)
    changed = str(current_data.get("state_fingerprint") or "") != projection["state_fingerprint"]
    if changed:
        _insert_history(
            conn,
            projection,
            previous_state_json=str(current_data.get("state_json") or "{}"),
            now=timestamp,
        )
    update_fields = (*INTERFACE_COLUMNS, "site_id", "state_json", "state_fingerprint", "last_seen_at", "changed_at", "source_revision")
    assignments = ", ".join(f"{field}=?" for field in update_fields)
    values = [projection.get(field) for field in INTERFACE_COLUMNS]
    values.extend(
        [
            projection["site_id"],
            projection["state_json"],
            projection["state_fingerprint"],
            projection["collected_at"],
            projection["collected_at"] if changed else current_data.get("changed_at"),
            projection["source_revision"],
            *key_values,
        ]
    )
    conn.execute(
        f"UPDATE device_interfaces SET {assignments} WHERE device_uuid=? AND interface_name=?",
        values,
    )
    if changed:
        conn.execute(
            "DELETE FROM device_interfaces_history WHERE site_id=? AND device_uuid=? AND interface_name=? "
            "AND id NOT IN (SELECT id FROM device_interfaces_history "
            "WHERE site_id=? AND device_uuid=? AND interface_name=? "
            "ORDER BY changed_at DESC, id DESC LIMIT ?)",
            (projection["site_id"], *key_values, projection["site_id"], *key_values, INTERFACE_HISTORY_LIMIT),
        )
    return {**current_data, **projection, "last_seen_at": projection["collected_at"]}


__all__ = [
    "INTERFACE_COLUMNS",
    "INTERFACE_HISTORY_LIMIT",
    "INTERFACE_RETENTION_AUTHORITY",
    "INTERFACE_STATE_FIELDS",
    "build_interface_projection",
    "canonical_interface_state",
    "canonical_state_fingerprint",
    "canonical_state_json",
    "interface_retention_authority_enabled",
    "upsert_interface_current_and_history",
]
