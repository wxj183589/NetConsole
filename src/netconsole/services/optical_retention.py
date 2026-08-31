from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import uuid4

from netconsole.services.ap_business_optical import evaluate_ap_business_rx
from netconsole.services.ap_identity.normalizers import normalize_mac_key


OPTICAL_HISTORY_LIMIT = 10
OPTICAL_RETENTION_AUTHORITY = "bounded_v1"
OPTICAL_ISSUE_STATUSES = frozenset(
    {"abnormal", "alarm", "link_abnormal", "link_down", "no_light", "notice", "warning"}
)
OPTICAL_NO_DATA_STATUSES = frozenset(
    {
        "",
        "unknown",
        "not_collected",
        "not_applicable",
        "skipped",
        "offline",
        "no_module",
        "failed",
        "timeout",
        "stale",
        "collection_failed",
        "connection_failed",
        "authentication_failed",
        "empty_configured_port",
    }
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


def _source_observation_is_non_valid(source_row: dict[str, Any]) -> bool:
    for field in (
        "status",
        "ap_optical_status",
        "switch_optical_status",
        "neighbor_optical_status",
        "collection_status",
        "connection_status",
    ):
        value = _canonical_status(source_row.get(field))
        if value and value in OPTICAL_NO_DATA_STATUSES:
            return True
    for field in ("primary_reason_code", "reason_code", "failure_stage"):
        if _canonical_status(source_row.get(field)) == "empty_configured_port":
            return True
    return False


_EVENT_SEVERITY_ORDER = {
    "notice": 1,
    "warning": 2,
    "abnormal": 3,
    "link_abnormal": 4,
    "link_down": 4,
    "no_light": 5,
    "alarm": 6,
}
_EVENT_METADATA_FIELDS = (
    "ap_uuid",
    "ap_name",
    "ap_mac",
    "ap_mac_normalized",
    "serial_number",
    "ap_id",
    "station_id",
    "station_name",
    "section_name",
    "direction",
    "switch_device_id",
    "switch_name",
    "switch_interface",
)


def _event_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {field: metadata.get(field, "") for field in _EVENT_METADATA_FIELDS}


def _event_issue_status(*statuses: str) -> str:
    valid = [status for status in statuses if status in OPTICAL_ISSUE_STATUSES]
    if not valid:
        return ""
    return max(valid, key=lambda status: _EVENT_SEVERITY_ORDER.get(status, 0))


def _event_worse_rx(previous: object, current: object) -> str:
    previous_text = _number_text(previous)
    current_text = _number_text(current)
    if not previous_text:
        return current_text
    if not current_text:
        return previous_text
    try:
        return previous_text if Decimal(previous_text) <= Decimal(current_text) else current_text
    except InvalidOperation:
        return previous_text


def _event_join_revisions(previous: object, current: object) -> str:
    values: list[str] = []
    for value in (previous, current):
        for token in _text(value).split(";"):
            if token and token not in values:
                values.append(token)
    return ";".join(values)


def _event_side_name(ap_abnormal: bool, switch_abnormal: bool) -> str:
    if ap_abnormal and switch_abnormal:
        return "BOTH"
    if ap_abnormal:
        return "AP"
    if switch_abnormal:
        return "SWITCH"
    return "NONE"


def _event_merge_side(previous: object, current: object) -> str:
    sides = {
        value
        for value in (_text(previous).upper(), _text(current).upper())
        if value in {"AP", "SWITCH", "BOTH"}
    }
    if "BOTH" in sides or len(sides) > 1:
        return "BOTH"
    return next(iter(sides), "UNKNOWN")


def _event_fingerprint(
    rows: dict[str, dict[str, Any]],
    source_row: dict[str, Any],
) -> str:
    payload = {
        "source_revision": _text(
            source_row.get("source_revision") or source_row.get("collect_run_uuid")
        ),
        "sides": {
            side: {
                "state_fingerprint": _text(row.get("state_fingerprint")),
                "status": _canonical_status(row.get("status")),
                "rx_dbm": _text(row.get("rx_dbm")),
                "tx_dbm": _text(row.get("tx_dbm")),
                "collected_at": _text(row.get("collected_at")),
            }
            for side, row in sorted(rows.items())
        },
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _event_count(conn, site_id: str, ap_identity: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS count FROM ap_optical_treatment_events "
        "WHERE site_id=? AND ap_identity=?",
        (site_id, ap_identity),
    ).fetchone()
    return int(row["count"] or 0) if row else 0


def _event_summary_seed(conn, site_id: str, ap_identity: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM ap_optical_treatment_events "
        "WHERE site_id=? AND ap_identity=? ORDER BY first_detected_at, id LIMIT 1",
        (site_id, ap_identity),
    ).fetchone()
    return dict(row) if row else None


def _record_ap_optical_treatment_event(
    conn,
    *,
    site_id: str,
    ap_identity: str,
    source_row: dict[str, Any],
    rows: dict[str, dict[str, Any]],
    metadata: dict[str, Any],
    abnormal_side: str,
    latest_collected: str,
    now: str,
) -> dict[str, Any] | None:
    """Persist one valid optical lifecycle transition.

    This function is deliberately called from the bounded optical writer.  It
    never treats no-data/failure rows as lifecycle boundaries and keeps the
    one-open-event invariant in SQLite as a final concurrency guard.
    """

    ap_row = rows.get("AP") or {}
    switch_row = rows.get("SWITCH") or {}
    ap_status = _canonical_status(ap_row.get("status"))
    switch_status = _canonical_status(switch_row.get("status"))
    ap_abnormal = ap_status in OPTICAL_ISSUE_STATUSES
    switch_abnormal = switch_status in OPTICAL_ISSUE_STATUSES
    source_revision = _text(
        source_row.get("source_revision") or source_row.get("collect_run_uuid")
    )
    observation_fingerprint = _event_fingerprint(rows, source_row)
    issue_type = _event_issue_status(ap_status, switch_status)
    severity = issue_type
    first_ap_rx = _side_rx(rows, "AP") if ap_abnormal else ""
    first_switch_rx = _side_rx(rows, "SWITCH") if switch_abnormal else ""
    current_ap_rx = _side_rx(rows, "AP")
    current_switch_rx = _side_rx(rows, "SWITCH")

    open_row = conn.execute(
        "SELECT * FROM ap_optical_treatment_events "
        "WHERE site_id=? AND ap_identity=? AND event_status='OPEN' "
        "ORDER BY id DESC LIMIT 1",
        (site_id, ap_identity),
    ).fetchone()
    if abnormal_side != "NONE":
        if open_row is not None:
            current = dict(open_row)
            if current.get("last_observation_fingerprint") == observation_fingerprint:
                return current
            values = {
                **current,
                **_event_metadata(metadata),
                "event_status": "OPEN",
                "last_abnormal_at": max(
                    _text(current.get("last_abnormal_at")), latest_collected
                ),
                "last_abnormal_side": abnormal_side,
                "worst_abnormal_side": _event_merge_side(
                    current.get("worst_abnormal_side"), abnormal_side
                ),
                "issue_type": issue_type or _text(current.get("issue_type")),
                "worst_severity": max(
                    _text(current.get("worst_severity")), severity,
                    key=lambda value: _EVENT_SEVERITY_ORDER.get(value, 0),
                ),
                "first_ap_rx_dbm": _text(current.get("first_ap_rx_dbm")) or first_ap_rx,
                "worst_ap_rx_dbm": _event_worse_rx(
                    current.get("worst_ap_rx_dbm"), first_ap_rx
                ),
                "first_switch_rx_dbm": _text(current.get("first_switch_rx_dbm"))
                or first_switch_rx,
                "worst_switch_rx_dbm": _event_worse_rx(
                    current.get("worst_switch_rx_dbm"),
                    first_switch_rx,
                ),
                "first_rx_dbm": _text(current.get("first_rx_dbm"))
                or first_ap_rx
                or first_switch_rx,
                "worst_rx_dbm": _event_worse_rx(
                    current.get("worst_rx_dbm"), first_ap_rx or first_switch_rx
                ),
                "source_revision_last": _event_join_revisions(
                    current.get("source_revision_last"), source_revision
                ),
                "last_observation_fingerprint": observation_fingerprint,
                "updated_at": now,
            }
            fields = tuple(
                field
                for field in values
                if field not in {"id", "event_uuid", "site_id", "ap_identity", "created_at"}
            )
            conn.execute(
                "UPDATE ap_optical_treatment_events SET "
                + ", ".join(f"{field}=?" for field in fields)
                + " WHERE id=?",
                [values[field] for field in fields] + [current["id"]],
            )
            return values

        values = {
            **_event_metadata(metadata),
            "event_uuid": uuid4().hex,
            "site_id": site_id,
            "ap_identity": ap_identity,
            "first_abnormal_side": abnormal_side,
            "worst_abnormal_side": abnormal_side,
            "last_abnormal_side": abnormal_side,
            "issue_type": issue_type,
            "initial_severity": severity,
            "worst_severity": severity,
            "first_detected_at": latest_collected,
            "last_abnormal_at": latest_collected,
            "resolved_at": "",
            "first_ap_rx_dbm": first_ap_rx,
            "worst_ap_rx_dbm": first_ap_rx,
            "recovered_ap_rx_dbm": "",
            "first_switch_rx_dbm": first_switch_rx,
            "worst_switch_rx_dbm": first_switch_rx,
            "recovered_switch_rx_dbm": "",
            "first_rx_dbm": first_ap_rx or first_switch_rx,
            "worst_rx_dbm": first_ap_rx or first_switch_rx,
            "recovered_rx_dbm": "",
            "event_status": "OPEN",
            "treatment_status": "PENDING",
            "remark": "",
            "source_revision_first": source_revision,
            "source_revision_last": source_revision,
            "backfill_key": "",
            "backfill_source": "",
            "evidence_quality": "RUNTIME",
            "evidence_json": json.dumps(
                {"backfill_keys": [], "source": "RUNTIME"},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            "last_observation_fingerprint": observation_fingerprint,
            "created_at": now,
            "updated_at": now,
        }
        fields = tuple(values)
        conn.execute(
            "INSERT INTO ap_optical_treatment_events ("
            + ", ".join(fields)
            + ") VALUES ("
            + ", ".join("?" for _ in fields)
            + ")",
            [values[field] for field in fields],
        )
        return values

    if open_row is None:
        return None
    current = dict(open_row)
    if current.get("last_observation_fingerprint") == observation_fingerprint:
        return current
    values = {
        **current,
        **_event_metadata(metadata),
        "event_status": "RESOLVED",
        "resolved_at": latest_collected,
        "recovered_ap_rx_dbm": current_ap_rx,
        "recovered_switch_rx_dbm": current_switch_rx,
        "recovered_rx_dbm": current_ap_rx or current_switch_rx,
        "last_abnormal_side": _text(current.get("last_abnormal_side")) or abnormal_side,
        "source_revision_last": _event_join_revisions(
            current.get("source_revision_last"), source_revision
        ),
        "last_observation_fingerprint": observation_fingerprint,
        "updated_at": now,
    }
    fields = tuple(
        field
        for field in values
        if field not in {"id", "event_uuid", "site_id", "ap_identity", "created_at"}
    )
    conn.execute(
        "UPDATE ap_optical_treatment_events SET "
        + ", ".join(f"{field}=?" for field in fields)
        + " WHERE id=?",
        [values[field] for field in fields] + [current["id"]],
    )
    return values


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
    if not (ap_abnormal or switch_abnormal) and _source_observation_is_non_valid(source_row):
        return None
    if not (ap_abnormal or switch_abnormal) and any(
        _canonical_status(row.get("status")) in OPTICAL_NO_DATA_STATUSES
        for row in rows.values()
    ):
        return None
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
    station_name = _text(
        source_row.get("station_name")
        or source_row.get("station")
        or source_row.get("site")
        or (ap_row or {}).get("station_name")
    )
    if station_name.casefold() == _text(site_id).casefold():
        station_name = ""
    station_name = station_name or _text((previous or {}).get("station_name"))
    previous_data = previous or {}
    metadata = {
        "site_id": site_id,
        "ap_identity": ap_identity,
        "ap_uuid": _text(source_row.get("ap_uuid")) or _text((ap_row or {}).get("ap_uuid")) or _text(previous_data.get("ap_uuid")),
        "ap_name": _text(source_row.get("ap_name")) or _text((ap_row or {}).get("ap_name")) or _text(previous_data.get("ap_name")),
        "ap_mac": _text(source_row.get("ap_mac")) or _text((ap_row or {}).get("ap_mac")) or _text(previous_data.get("ap_mac")),
        "ap_mac_normalized": normalize_mac_key(
            source_row.get("ap_mac")
            or (ap_row or {}).get("ap_mac")
            or previous_data.get("ap_mac")
        ) or _text(previous_data.get("ap_mac_normalized")),
        "serial_number": _text(source_row.get("serial_number")) or _text((ap_row or {}).get("serial_number")) or _text(previous_data.get("serial_number")),
        "ap_id": _text(source_row.get("ap_id") or source_row.get("apid")) or _text((ap_row or {}).get("ap_id")) or _text(previous_data.get("ap_id")),
        "section_name": _text(source_row.get("section_name") or source_row.get("belong_section")) or _text((ap_row or {}).get("section_name")) or _text(previous_data.get("section_name")),
        "direction": _text(source_row.get("direction")) or _text((ap_row or {}).get("direction")) or _text(previous_data.get("direction")),
        "station_id": _text(source_row.get("station_id")) or _text(previous_data.get("station_id")),
        "station_name": station_name,
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
    _record_ap_optical_treatment_event(
        conn,
        site_id=site_id,
        ap_identity=ap_identity,
        source_row=source_row,
        rows=rows,
        metadata=metadata,
        abnormal_side=abnormal_side,
        latest_collected=latest_collected,
        now=now,
    )
    recurrence_count = max(_event_count(conn, site_id, ap_identity) - 1, 0)
    event_seed = _event_summary_seed(conn, site_id, ap_identity)
    if abnormal_side != "NONE":
        if previous is None:
            seeded_first_detected = _text((event_seed or {}).get("first_detected_at"))
            seeded_first_resolved = _text((event_seed or {}).get("resolved_at"))
            values = {
                **metadata,
                "first_detected_at": seeded_first_detected or latest_collected,
                "last_abnormal_at": latest_collected,
                "first_ap_rx_dbm": _text((event_seed or {}).get("first_ap_rx_dbm"))
                or metadata["current_ap_rx_dbm"],
                "first_switch_rx_dbm": _text((event_seed or {}).get("first_switch_rx_dbm"))
                or metadata["current_switch_rx_dbm"],
                "recovered_ap_rx_dbm": "",
                "recovered_switch_rx_dbm": "",
                "first_abnormal_side": _text((event_seed or {}).get("first_abnormal_side"))
                or abnormal_side,
                "current_status": current_status,
                "treatment_status": "RECURRENT" if recurrence_count else "PENDING",
                "first_resolved_at": seeded_first_resolved,
                "last_resolved_at": seeded_first_resolved,
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
            "treatment_status": "RECURRENT" if recurrence_count else str(previous.get("treatment_status") or "PENDING"),
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
