from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import Any

from netconsole.services.ap_business_optical import evaluate_ap_business_rx
from netconsole.services.ap_identity.normalizers import normalize_mac_key


OPTICAL_HISTORY_LIMIT = 10
OPTICAL_RETENTION_AUTHORITY = "bounded_v1"
OPTICAL_ISSUE_STATUSES = frozenset(
    {"abnormal", "alarm", "link_abnormal", "link_down", "no_light", "notice", "warning"}
)
OPTICAL_NO_DATA_STATUSES = frozenset(
    {"", "unknown", "not_collected", "not_applicable", "skipped", "offline", "no_module", "failed", "timeout"}
)
_OPTICAL_KEYS = ("site_id", "ap_identity", "side")
_OPTICAL_COLUMNS = (
    "site_id", "ap_identity", "ap_uuid", "ap_name", "ap_mac", "ap_mac_normalized",
    "serial_number", "side", "switch_device_id", "switch_name", "switch_interface",
    "rx_dbm", "tx_dbm", "status", "source", "collected_at", "last_seen_at",
    "state_json", "state_fingerprint", "payload_json", "source_revision",
)


def _text(value: object) -> str:
    return str(value or "").strip()


def _first(row: dict[str, Any], *fields: str) -> object:
    for field in fields:
        value = row.get(field)
        if value not in (None, ""):
            return value
    return ""


def _number_text(value: object) -> str:
    text = _text(value)
    if not text:
        return ""
    token = text.split()[0]
    try:
        number = Decimal(token)
    except InvalidOperation:
        return text
    normalized = format(number.normalize(), "f")
    return normalized.rstrip("0").rstrip(".") if "." in normalized else normalized


def _canonical_status(value: object) -> str:
    return _text(value).casefold()


def optical_ap_identity(row: dict[str, Any]) -> str:
    ap_uuid = _text(row.get("ap_uuid"))
    if ap_uuid:
        return ap_uuid
    ap_mac = normalize_mac_key(row.get("ap_mac"))
    if ap_mac:
        return f"mac:{ap_mac}"
    raise ValueError("optical resource identity is missing ap_uuid and normalized ap_mac")


def _status_for_side(row: dict[str, Any], side: str, rx: object) -> str:
    if side == "AP":
        reported = _first(row, "ap_optical_status", "optical_alarm_status", "status")
    else:
        reported = _first(row, "switch_optical_status", "neighbor_optical_status", "neighbor_status")
        if reported in (None, ""):
            reported = _first(row, "optical_alarm_status", "status")
    status = _canonical_status(reported)
    if status in {"success", "ok"}:
        status = ""
    if not status and rx not in (None, ""):
        return str(evaluate_ap_business_rx(rx))
    return status or "unknown"


def _state_json(rx_dbm: str, tx_dbm: str, status: str) -> str:
    return json.dumps(
        {"rx_dbm": rx_dbm, "status": status, "tx_dbm": tx_dbm},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _state_fingerprint(rx_dbm: str, tx_dbm: str, status: str) -> str:
    return hashlib.sha256(_state_json(rx_dbm, tx_dbm, status).encode("utf-8")).hexdigest()


def _json_default(value: object) -> object:
    return str(value)


def build_optical_projection(
    row: dict[str, Any],
    *,
    site_id: str,
    side: str,
    now: str,
) -> dict[str, Any] | None:
    normalized_side = _text(side).upper()
    if normalized_side not in {"AP", "SWITCH"}:
        raise ValueError(f"unsupported optical side: {side}")
    identity = optical_ap_identity(row)
    if normalized_side == "AP":
        rx_value = _first(row, "rx_dbm", "ap_rx_power", "rx_power")
        tx_value = _first(row, "tx_dbm", "ap_tx_power", "tx_power")
    else:
        rx_value = _first(row, "switch_rx_power", "neighbor_rx_power", "rx_dbm", "rx_power")
        tx_value = _first(row, "switch_tx_power", "neighbor_tx_power", "tx_dbm", "tx_power")
    status = _status_for_side(row, normalized_side, rx_value)
    has_measurement = any(value not in (None, "") for value in (rx_value, tx_value))
    has_module_metadata = any(
        row.get(field) not in (None, "")
        for field in ("module_model", "module_serial_number", "module_vendor", "temperature", "voltage", "bias_current")
    )
    if not has_measurement and not has_module_metadata and status not in OPTICAL_ISSUE_STATUSES:
        return None
    collected_at = _text(_first(row, "collected_at", "optical_collected_at", "updated_at")) or now
    rx_dbm = _number_text(rx_value)
    tx_dbm = _number_text(tx_value)
    state_json = _state_json(rx_dbm, tx_dbm, status)
    return {
        "site_id": _text(site_id),
        "ap_identity": identity,
        "ap_uuid": _text(row.get("ap_uuid")),
        "ap_name": _text(row.get("ap_name")),
        "ap_mac": _text(row.get("ap_mac")),
        "ap_mac_normalized": normalize_mac_key(row.get("ap_mac")) or "",
        "serial_number": _text(row.get("serial_number")),
        "side": normalized_side,
        "switch_device_id": _text(row.get("switch_device_id") or row.get("device_uuid")),
        "switch_name": _text(row.get("switch_name") or row.get("neighbor_device_name") or row.get("device_name")),
        "switch_interface": _text(row.get("switch_interface") or row.get("neighbor_interface") or row.get("interface_name")),
        "rx_dbm": rx_dbm,
        "tx_dbm": tx_dbm,
        "status": status,
        "source": _text(row.get("source") or row.get("lldp_source")) or "optical_refresh",
        "collected_at": collected_at,
        "last_seen_at": collected_at,
        "state_json": state_json,
        "state_fingerprint": _state_fingerprint(rx_dbm, tx_dbm, status),
        "payload_json": json.dumps(dict(row), ensure_ascii=False, sort_keys=True, default=_json_default, separators=(",", ":")),
        "source_revision": _text(row.get("source_revision") or row.get("collect_run_uuid")),
    }


def _update_current(conn, projection: dict[str, Any], *, now: str) -> None:
    update_columns = tuple(field for field in _OPTICAL_COLUMNS if field not in _OPTICAL_KEYS)
    assignments = ", ".join(f"{field}=?" for field in (*update_columns, "last_seen_at", "updated_at"))
    values = [projection.get(field) for field in update_columns]
    values.extend([projection["collected_at"], now, *(projection[key] for key in _OPTICAL_KEYS)])
    conn.execute(
        f"UPDATE optical_current SET {assignments} WHERE site_id=? AND ap_identity=? AND side=?",
        values,
    )


def _insert_current(conn, projection: dict[str, Any], *, now: str) -> None:
    fields = (*_OPTICAL_COLUMNS, "first_seen_at", "created_at", "updated_at")
    values = [projection.get(field) for field in _OPTICAL_COLUMNS]
    values.extend([projection["collected_at"], now, now])
    conn.execute(
        f"INSERT INTO optical_current ({', '.join(fields)}) VALUES ({', '.join('?' for _ in fields)})",
        values,
    )


def _insert_history(conn, projection: dict[str, Any], *, previous_state_json: str, now: str) -> None:
    fields = (*_OPTICAL_COLUMNS, "previous_state_json", "changed_at", "change_kind", "created_at")
    values = [projection.get(field) for field in _OPTICAL_COLUMNS]
    values.extend([previous_state_json, projection["collected_at"], "change", now])
    conn.execute(
        f"INSERT INTO optical_history ({', '.join(fields)}) VALUES ({', '.join('?' for _ in fields)})",
        values,
    )


def upsert_optical_current_and_history(
    conn,
    row: dict[str, Any],
    *,
    site_id: str,
    side: str,
    now: str,
) -> dict[str, Any] | None:
    projection = build_optical_projection(row, site_id=site_id, side=side, now=now)
    if projection is None:
        return None
    conn.execute(
        "INSERT INTO optical_retention_meta(key, value) VALUES ('authority', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (OPTICAL_RETENTION_AUTHORITY,),
    )
    current = conn.execute(
        "SELECT * FROM optical_current WHERE site_id=? AND ap_identity=? AND side=?",
        tuple(projection[key] for key in _OPTICAL_KEYS),
    ).fetchone()
    if current is None:
        _insert_current(conn, projection, now=now)
        return projection
    current_data = dict(current)
    if str(current_data.get("state_fingerprint") or "") == projection["state_fingerprint"]:
        _update_current(conn, projection, now=now)
        return {**current_data, **projection, "last_seen_at": projection["collected_at"]}
    _insert_history(conn, projection, previous_state_json=str(current_data.get("state_json") or "{}"), now=now)
    _update_current(conn, projection, now=now)
    conn.execute(
        "DELETE FROM optical_history WHERE site_id=? AND ap_identity=? AND side=? AND id NOT IN ("
        "SELECT id FROM optical_history WHERE site_id=? AND ap_identity=? AND side=? "
        "ORDER BY changed_at DESC, id DESC LIMIT ?)",
        (*tuple(projection[key] for key in _OPTICAL_KEYS), *tuple(projection[key] for key in _OPTICAL_KEYS), OPTICAL_HISTORY_LIMIT),
    )
    return {**current_data, **projection, "last_seen_at": projection["collected_at"]}


def _current_side_rows(conn, site_id: str, ap_identity: str) -> dict[str, dict[str, Any]]:
    return {
        str(row["side"]): dict(row)
        for row in conn.execute(
            "SELECT * FROM optical_current WHERE site_id=? AND ap_identity=?",
            (site_id, ap_identity),
        ).fetchall()
    }


def _has_real_data(row: dict[str, Any] | None) -> bool:
    if not row:
        return False
    return bool(
        row.get("rx_dbm") not in (None, "")
        or row.get("tx_dbm") not in (None, "")
        or _canonical_status(row.get("status")) not in OPTICAL_NO_DATA_STATUSES
    )


def _side_rx(rows: dict[str, dict[str, Any]], side: str) -> str:
    return _text(rows.get(side, {}).get("rx_dbm"))


def update_ap_optical_treatment(
    conn,
    *,
    site_id: str,
    ap_identity: str,
    source_row: dict[str, Any],
    now: str,
) -> dict[str, Any] | None:
    rows = _current_side_rows(conn, site_id, ap_identity)
    ap_row = rows.get("AP")
    switch_row = rows.get("SWITCH")
    ap_status = _canonical_status(ap_row.get("status") if ap_row else "")
    switch_status = _canonical_status(switch_row.get("status") if switch_row else "")
    ap_abnormal = ap_status in OPTICAL_ISSUE_STATUSES
    switch_abnormal = switch_status in OPTICAL_ISSUE_STATUSES
    if not (ap_abnormal or switch_abnormal) and not any(_has_real_data(row) for row in rows.values()):
        return None
    abnormal_side = "BOTH" if ap_abnormal and switch_abnormal else "AP" if ap_abnormal else "SWITCH" if switch_abnormal else "NONE"
    current_status = "ABNORMAL" if abnormal_side != "NONE" else "NORMAL"
    identity_params = (site_id, ap_identity)
    current = conn.execute(
        "SELECT * FROM ap_optical_treatment WHERE site_id=? AND ap_identity=?", identity_params
    ).fetchone()
    previous = dict(current) if current is not None else None
    latest_collected = max(
        [_text(row.get("collected_at")) for row in rows.values() if _text(row.get("collected_at"))]
        or [_text(source_row.get("collected_at")) or now]
    )
    metadata = {
        "site_id": site_id,
        "ap_identity": ap_identity,
        "ap_uuid": _text(source_row.get("ap_uuid")) or _text((ap_row or {}).get("ap_uuid")),
        "ap_name": _text(source_row.get("ap_name")) or _text((ap_row or {}).get("ap_name")),
        "ap_mac": _text(source_row.get("ap_mac")) or _text((ap_row or {}).get("ap_mac")),
        "ap_mac_normalized": normalize_mac_key(source_row.get("ap_mac") or (ap_row or {}).get("ap_mac")) or "",
        "serial_number": _text(source_row.get("serial_number")) or _text((ap_row or {}).get("serial_number")),
        "station_id": _text(source_row.get("station_id")),
        "station_name": _text(source_row.get("station_name") or source_row.get("site")),
        "switch_device_id": _text((switch_row or {}).get("switch_device_id")),
        "switch_name": _text((switch_row or {}).get("switch_name")),
        "switch_interface": _text((switch_row or {}).get("switch_interface")),
        "current_ap_rx_dbm": _side_rx(rows, "AP"),
        "current_switch_rx_dbm": _side_rx(rows, "SWITCH"),
        "current_ap_tx_dbm": _text((ap_row or {}).get("tx_dbm")),
        "current_switch_tx_dbm": _text((switch_row or {}).get("tx_dbm")),
        "current_ap_status": ap_status,
        "current_switch_status": switch_status,
        "current_abnormal_side": abnormal_side,
        "last_collected_at": latest_collected,
        "updated_at": now,
    }
    if abnormal_side != "NONE":
        was_resolved = bool(previous and str(previous.get("treatment_status") or "") == "RESOLVED")
        recurrence_count = int(previous.get("recurrence_count") or 0) if previous else 0
        if was_resolved:
            recurrence_count += 1
        if previous is None:
            values = {
                **metadata,
                "first_detected_at": latest_collected,
                "last_abnormal_at": latest_collected,
                "first_ap_rx_dbm": metadata["current_ap_rx_dbm"],
                "first_switch_rx_dbm": metadata["current_switch_rx_dbm"],
                "recovered_ap_rx_dbm": "",
                "recovered_switch_rx_dbm": "",
                "first_abnormal_side": abnormal_side,
                "current_status": current_status,
                "treatment_status": "RECURRENT" if recurrence_count else "PENDING",
                "first_resolved_at": "",
                "last_resolved_at": "",
                "recurrence_count": recurrence_count,
                "remark": "",
                "source_revision": _text(source_row.get("source_revision") or source_row.get("collect_run_uuid")),
                "created_at": now,
            }
            columns = tuple(values)
            conn.execute(
                f"INSERT INTO ap_optical_treatment ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                [values[column] for column in columns],
            )
            return values
        values = {
            **previous,
            **metadata,
            "last_abnormal_at": latest_collected,
            "current_status": current_status,
            "treatment_status": "RECURRENT" if was_resolved else str(previous.get("treatment_status") or "PENDING"),
            "recurrence_count": recurrence_count,
            "source_revision": _text(source_row.get("source_revision") or source_row.get("collect_run_uuid")),
        }
    else:
        if previous is None:
            return None
        was_abnormal = str(previous.get("current_status") or "") == "ABNORMAL"
        values = {
            **previous,
            **metadata,
            "current_status": "RECOVERED" if was_abnormal else "NORMAL",
            "treatment_status": "RESOLVED",
            "recovered_ap_rx_dbm": metadata["current_ap_rx_dbm"],
            "recovered_switch_rx_dbm": metadata["current_switch_rx_dbm"],
            "first_resolved_at": str(previous.get("first_resolved_at") or latest_collected),
            "last_resolved_at": latest_collected,
            "source_revision": _text(source_row.get("source_revision") or source_row.get("collect_run_uuid")),
        }
    update_fields = tuple(field for field in values if field not in {"id", "site_id", "ap_identity", "created_at"})
    conn.execute(
        f"UPDATE ap_optical_treatment SET {', '.join(f'{field}=?' for field in update_fields)} WHERE site_id=? AND ap_identity=?",
        [*[values[field] for field in update_fields], site_id, ap_identity],
    )
    return values


def merge_optical_current_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row.get("site_id") or ""), str(row.get("ap_identity") or ""))
        target = grouped.setdefault(key, {})
        try:
            payload = json.loads(str(row.get("payload_json") or "{}"))
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict):
            target.update(payload)
        target.update({
            "site_id": row.get("site_id"),
            "ap_identity": row.get("ap_identity"),
            "ap_uuid": row.get("ap_uuid") or target.get("ap_uuid"),
            "ap_name": row.get("ap_name") or target.get("ap_name"),
            "ap_mac": row.get("ap_mac") or target.get("ap_mac"),
            "serial_number": row.get("serial_number") or target.get("serial_number"),
        })
        if str(row.get("side") or "") == "AP":
            target.update({
                "rx_power": row.get("rx_dbm"), "tx_power": row.get("tx_dbm"),
                "ap_rx_power": row.get("rx_dbm"), "ap_tx_power": row.get("tx_dbm"),
                "ap_optical_status": row.get("status"), "ap_device_optical_status": row.get("status"),
                "ap_optical_updated_at": row.get("collected_at"), "updated_at": row.get("collected_at"),
            })
        else:
            target.update({
                "neighbor_rx_power": row.get("rx_dbm"), "switch_rx_power": row.get("rx_dbm"),
                "switch_optical_status": row.get("status"), "switch_device_optical_status": row.get("status"),
                "switch_optical_updated_at": row.get("collected_at"),
                "neighbor_device_name": row.get("switch_name") or target.get("neighbor_device_name"),
                "neighbor_interface": row.get("switch_interface") or target.get("neighbor_interface"),
            })
    return sorted(grouped.values(), key=lambda row: (str(row.get("ap_name") or ""), str(row.get("ap_identity") or "")))


__all__ = [
    "OPTICAL_HISTORY_LIMIT",
    "OPTICAL_RETENTION_AUTHORITY",
    "OPTICAL_ISSUE_STATUSES",
    "build_optical_projection",
    "merge_optical_current_rows",
    "optical_ap_identity",
    "update_ap_optical_treatment",
    "upsert_optical_current_and_history",
]
