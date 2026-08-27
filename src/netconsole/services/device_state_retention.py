"""Bounded Current + Recent10 storage for device LLDP and optical facts."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from netconsole.utils.interface_normalize import normalize_interface_name

DEVICE_LLDP_HISTORY_LIMIT = 10
DEVICE_OPTICAL_HISTORY_LIMIT = 10
RETENTION_AUTHORITY = "bounded_v1"

LLDP_COLUMNS = (
    "device_uuid", "local_interface", "scope", "chassis_type", "chassis_id",
    "neighbor_sysname", "neighbor_mac", "port_id_type", "neighbor_interface",
    "neighbor_ip", "holdtime", "ttl", "port_description", "system_description",
    "system_capabilities", "pvid", "operational_mau", "max_frame_size",
    "neighbor_device_uuid", "collected_at", "collect_run_uuid", "raw_log_path",
    "updated_at",
)
LLDP_STATE_COLUMNS = tuple(
    field for field in LLDP_COLUMNS
    if field not in {"collected_at", "collect_run_uuid", "raw_log_path", "updated_at"}
)
OPTICAL_COLUMNS = (
    "device_uuid", "interface_name", "rx_power", "tx_power", "temperature", "voltage",
    "bias_current", "module_model", "module_serial_number", "module_vendor", "wavelength",
    "transmission_distance", "connector_type", "device_vendor", "device_reported_status",
    "threshold_source", "transceiver_mode", "vendor_part_number", "vendor_revision",
    "vendor_serial_number", "rx_low_alarm", "rx_high_alarm", "tx_low_alarm", "tx_high_alarm",
    "rx_low_warning", "rx_high_warning", "tx_low_warning", "tx_high_warning", "status",
    "collected_at", "collect_run_uuid", "raw_log_path", "updated_at",
)
OPTICAL_STATE_COLUMNS = tuple(
    field for field in OPTICAL_COLUMNS
    if field not in {"collected_at", "collect_run_uuid", "raw_log_path", "updated_at"}
)


def _text(value: object) -> str:
    return str(value or "").strip()


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _json_value(value: object) -> object:
    if isinstance(value, (list, tuple, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return value


def _state_json(row: dict[str, Any], fields: tuple[str, ...]) -> str:
    return json.dumps(
        {field: _json_value(row.get(field)) for field in fields},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _fingerprint(state_json: str) -> str:
    return hashlib.sha256(state_json.encode("utf-8")).hexdigest()


def _authority_enabled(conn, table: str) -> bool:
    try:
        row = conn.execute(
            f"SELECT value FROM {table} WHERE key='authority'"
        ).fetchone()
    except Exception:
        return False
    return _text(row[0] if row is not None else "") == RETENTION_AUTHORITY


def device_lldp_retention_authority_enabled(conn) -> bool:
    return _authority_enabled(conn, "device_lldp_retention_meta")


def device_optical_retention_authority_enabled(conn) -> bool:
    return _authority_enabled(conn, "device_optical_retention_meta")


def _set_authority(conn, table: str) -> None:
    conn.execute(
        f"INSERT INTO {table}(key,value) VALUES ('authority',?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (RETENTION_AUTHORITY,),
    )


def _projection(row: dict[str, Any], *, site_id: str, fields: tuple[str, ...], state_fields: tuple[str, ...], now: str) -> dict[str, Any]:
    result = {field: _json_value(row.get(field)) for field in fields}
    result["site_id"] = _text(site_id)
    result["collected_at"] = _text(row.get("collected_at")) or now
    result["updated_at"] = _text(row.get("updated_at")) or now
    state = _state_json(result, state_fields)
    result["state_json"] = state
    result["state_fingerprint"] = _fingerprint(state)
    result["source_revision"] = _text(row.get("source_revision") or row.get("collect_run_uuid"))
    return result


def _lldp_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        _text(row.get("device_uuid")),
        normalize_interface_name(row.get("local_interface")).casefold(),
        _text(row.get("chassis_id") or row.get("neighbor_mac")).casefold(),
        normalize_interface_name(row.get("neighbor_interface")).casefold(),
    )


def _history_key_sql(prefix: str = "") -> str:
    return (
        f"{prefix}site_id, {prefix}device_uuid, {prefix}local_interface, "
        f"{prefix}chassis_id, {prefix}neighbor_interface"
    )


def _insert_history(conn, table: str, fields: tuple[str, ...], projection: dict[str, Any], *, previous_state_json: str, now: str) -> None:
    all_fields = (*fields, "site_id", "state_json", "state_fingerprint", "previous_state_json", "changed_at", "source_revision", "change_kind", "created_at")
    values = [projection.get(field) for field in fields]
    values.extend([projection["site_id"], projection["state_json"], projection["state_fingerprint"], previous_state_json, projection["collected_at"], projection["source_revision"], "change", now])
    conn.execute(
        f"INSERT INTO {table} ({', '.join(all_fields)}) VALUES ({', '.join('?' for _ in all_fields)})",
        values,
    )


def upsert_device_lldp_current_and_history(
    conn,
    row: dict[str, Any],
    *,
    site_id: str,
    now: str = "",
    replace_local: bool = False,
) -> dict[str, Any]:
    timestamp = now or _now()
    projection = _projection(row, site_id=site_id, fields=LLDP_COLUMNS, state_fields=LLDP_STATE_COLUMNS, now=timestamp)
    _set_authority(conn, "device_lldp_retention_meta")
    key = _lldp_key(projection)
    candidates = conn.execute(
        "SELECT * FROM device_lldp_neighbors WHERE device_uuid=?",
        (key[0],),
    ).fetchall()
    current = next((item for item in candidates if _lldp_key(dict(item)) == key), None)
    if current is None and replace_local:
        same_interface = [
            item
            for item in candidates
            if normalize_interface_name(dict(item).get("local_interface")).casefold() == key[1]
        ]
        if len(same_interface) == 1:
            current = same_interface[0]
    if current is None:
        fields = (*LLDP_COLUMNS, "site_id", "state_json", "state_fingerprint", "first_seen_at", "last_seen_at", "changed_at", "source_revision")
        values = [projection.get(field) for field in fields]
        values[fields.index("first_seen_at")] = projection["collected_at"]
        values[fields.index("last_seen_at")] = projection["collected_at"]
        values[fields.index("changed_at")] = None
        conn.execute(f"INSERT INTO device_lldp_neighbors ({', '.join(fields)}) VALUES ({', '.join('?' for _ in fields)})", values)
        return projection
    current_data = dict(current)
    changed = _text(current_data.get("state_fingerprint")) != projection["state_fingerprint"]
    if changed:
        _insert_history(conn, "device_lldp_neighbors_history", LLDP_COLUMNS, projection, previous_state_json=_text(current_data.get("state_json")) or "{}", now=timestamp)
    fields = (*LLDP_COLUMNS, "site_id", "state_json", "state_fingerprint", "last_seen_at", "changed_at", "source_revision")
    values = [projection.get(field) for field in LLDP_COLUMNS]
    values.extend([projection["site_id"], projection["state_json"], projection["state_fingerprint"], projection["collected_at"], projection["collected_at"] if changed else current_data.get("changed_at"), projection["source_revision"], current_data["id"]])
    assignments = ", ".join(f"{field}=?" for field in fields)
    conn.execute(f"UPDATE device_lldp_neighbors SET {assignments} WHERE id=?", values)
    if changed:
        history_key = (projection["site_id"], *key)
        history_rows = conn.execute(
            "SELECT * FROM device_lldp_neighbors_history "
            "WHERE site_id=? AND device_uuid=? ORDER BY changed_at DESC, id DESC",
            (history_key[0], history_key[1]),
        ).fetchall()
        matching_ids = [
            int(item["id"])
            for item in history_rows
            if _lldp_key(dict(item)) == key
        ]
        drop_ids = matching_ids[DEVICE_LLDP_HISTORY_LIMIT:]
        if drop_ids:
            placeholders = ", ".join("?" for _ in drop_ids)
            conn.execute(
                "DELETE FROM device_lldp_neighbors_history "
                f"WHERE site_id=? AND device_uuid=? AND id IN ({placeholders})",
                (history_key[0], history_key[1], *drop_ids),
            )
    return {**current_data, **projection, "last_seen_at": projection["collected_at"]}


def _optical_key(row: dict[str, Any]) -> tuple[str, str]:
    return (_text(row.get("device_uuid")), _text(row.get("interface_name")).casefold())


def upsert_device_optical_current_and_history(conn, row: dict[str, Any], *, site_id: str, now: str = "") -> dict[str, Any]:
    timestamp = now or _now()
    projection = _projection(row, site_id=site_id, fields=OPTICAL_COLUMNS, state_fields=OPTICAL_STATE_COLUMNS, now=timestamp)
    _set_authority(conn, "device_optical_retention_meta")
    key = _optical_key(projection)
    current = conn.execute(
        "SELECT * FROM device_optical_modules WHERE device_uuid=? AND lower(interface_name)=? ORDER BY id DESC LIMIT 1",
        key,
    ).fetchone()
    if current is None:
        fields = (*OPTICAL_COLUMNS, "site_id", "state_json", "state_fingerprint", "first_seen_at", "last_seen_at", "changed_at", "source_revision")
        values = [projection.get(field) for field in fields]
        values[fields.index("first_seen_at")] = projection["collected_at"]
        values[fields.index("last_seen_at")] = projection["collected_at"]
        values[fields.index("changed_at")] = None
        conn.execute(f"INSERT INTO device_optical_modules ({', '.join(fields)}) VALUES ({', '.join('?' for _ in fields)})", values)
        return projection
    current_data = dict(current)
    changed = _text(current_data.get("state_fingerprint")) != projection["state_fingerprint"]
    if changed:
        _insert_history(conn, "device_optical_modules_history", OPTICAL_COLUMNS, projection, previous_state_json=_text(current_data.get("state_json")) or "{}", now=timestamp)
    fields = (*OPTICAL_COLUMNS, "site_id", "state_json", "state_fingerprint", "last_seen_at", "changed_at", "source_revision")
    values = [projection.get(field) for field in OPTICAL_COLUMNS]
    values.extend([projection["site_id"], projection["state_json"], projection["state_fingerprint"], projection["collected_at"], projection["collected_at"] if changed else current_data.get("changed_at"), projection["source_revision"], current_data["id"]])
    assignments = ", ".join(f"{field}=?" for field in fields)
    conn.execute(f"UPDATE device_optical_modules SET {assignments} WHERE id=?", values)
    if changed:
        history_key = (projection["site_id"], *key)
        conn.execute(
            "DELETE FROM device_optical_modules_history WHERE site_id=? AND device_uuid=? "
            "AND lower(interface_name)=? AND id NOT IN (SELECT id FROM device_optical_modules_history "
            "WHERE site_id=? AND device_uuid=? AND lower(interface_name)=? "
            "ORDER BY changed_at DESC, id DESC LIMIT ?)",
            (*history_key, *history_key, DEVICE_OPTICAL_HISTORY_LIMIT),
        )
    return {**current_data, **projection, "last_seen_at": projection["collected_at"]}


__all__ = [
    "DEVICE_LLDP_HISTORY_LIMIT",
    "DEVICE_OPTICAL_HISTORY_LIMIT",
    "device_lldp_retention_authority_enabled",
    "device_optical_retention_authority_enabled",
    "upsert_device_lldp_current_and_history",
    "upsert_device_optical_current_and_history",
]
