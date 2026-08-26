"""Bounded Current + change-only History for FIT-AP radios."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from netconsole.services.ap_extension_import import normalize_ap_mac

RADIO_HISTORY_LIMIT = 10
RADIO_RETENTION_AUTHORITY = "bounded_v1"
RADIO_STATE_FIELDS = (
    "status",
    "mode",
    "band",
    "channel",
    "bandwidth",
    "usage",
    "tx_power",
    "clients",
    "bbssid",
)
RADIO_COLUMNS = (
    "site_id",
    "ap_identity",
    "ap_uuid",
    "ap_name",
    "ap_mac",
    "radio_id",
    "status",
    "mode",
    "band",
    "channel",
    "bandwidth",
    "usage",
    "tx_power",
    "clients",
    "bbssid",
    "source",
    "collected_at",
    "state_json",
    "state_fingerprint",
    "payload_json",
    "source_revision",
)
_RADIO_KEY_COLUMNS = ("site_id", "ap_identity", "radio_id")


def _text(value: object) -> str:
    return str(value or "").strip()


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _client_value(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _first(row: dict[str, Any], *fields: str) -> object:
    for field in fields:
        value = row.get(field)
        if value not in (None, ""):
            return value
    return ""


def _state_value(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def canonical_radio_state(row: dict[str, Any]) -> dict[str, str]:
    return {
        field: _state_value(row.get(field))
        for field in RADIO_STATE_FIELDS
    }


def canonical_state_json(state: dict[str, str]) -> str:
    return json.dumps(
        {field: _state_value(state.get(field)) for field in RADIO_STATE_FIELDS},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_state_fingerprint(state: dict[str, str]) -> str:
    return hashlib.sha256(canonical_state_json(state).encode("utf-8")).hexdigest()


def build_radio_projection(
    row: dict[str, Any],
    *,
    site_id: str,
    radio_id: int | str,
    now: str,
) -> dict[str, Any]:
    try:
        normalized_radio_id = int(radio_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("FIT-AP Radio identity is missing radio_id") from exc
    if normalized_radio_id <= 0:
        raise ValueError("FIT-AP Radio identity must be positive")
    ap_uuid = _text(row.get("ap_uuid"))
    if not ap_uuid:
        raise ValueError("FIT-AP Radio identity is missing ap_uuid")
    bbssid_result = normalize_ap_mac(
        _first(row, "bbssid", f"rid{normalized_radio_id}_bbssid")
    )
    bbssid = bbssid_result.display if bbssid_result.normalized else _text(
        _first(row, "bbssid", f"rid{normalized_radio_id}_bbssid")
    )
    projection = {
        "site_id": _text(site_id),
        "ap_identity": ap_uuid,
        "ap_uuid": ap_uuid,
        "ap_name": _text(_first(row, "ap_name")),
        "ap_mac": _text(_first(row, "ap_mac")),
        "radio_id": normalized_radio_id,
        "status": _text(_first(row, "status", f"rid{normalized_radio_id}_status")),
        "mode": _text(_first(row, "mode", f"rid{normalized_radio_id}_mode")),
        "band": _text(
            _first(row, "band", "frequency_band", f"rid{normalized_radio_id}_band")
        ),
        "channel": _text(_first(row, "channel", f"rid{normalized_radio_id}_channel")),
        "bandwidth": _text(
            _first(row, "bandwidth", f"rid{normalized_radio_id}_bandwidth")
        ),
        "usage": _text(_first(row, "usage", "utilization", f"rid{normalized_radio_id}_usage")),
        "tx_power": _text(_first(row, "tx_power", f"rid{normalized_radio_id}_tx_power")),
        "clients": _client_value(_first(row, "clients", f"rid{normalized_radio_id}_clients")),
        "bbssid": bbssid,
        "source": _text(row.get("source") or "fit_ap_resource"),
        "collected_at": _text(
            _first(row, "collected_at", "last_seen_at", "updated_at")
        ) or now,
        "source_revision": _text(row.get("source_revision") or row.get("collect_run_uuid")),
    }
    state = canonical_radio_state(projection)
    projection["state_json"] = canonical_state_json(state)
    projection["state_fingerprint"] = canonical_state_fingerprint(state)
    projection["payload_json"] = json.dumps(
        projection,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return projection


def _insert(
    conn,
    table: str,
    projection: dict[str, Any],
    *,
    now: str,
    previous_state_json: str | None = None,
) -> None:
    if table == "fit_ap_radio_current":
        fields = (*RADIO_COLUMNS, "first_seen_at", "changed_at", "created_at", "updated_at")
        values = [projection.get(field) for field in RADIO_COLUMNS]
        values.extend([projection["collected_at"], None, now, now])
    else:
        fields = (*RADIO_COLUMNS, "previous_state_json", "changed_at", "change_kind", "created_at")
        values = [projection.get(field) for field in RADIO_COLUMNS]
        values.extend([previous_state_json or "{}", projection["collected_at"], "change", now])
    conn.execute(
        f"INSERT INTO {table} ({', '.join(fields)}) VALUES ({', '.join('?' for _ in fields)})",
        values,
    )


def upsert_radio_current_and_history(
    conn,
    row: dict[str, Any],
    *,
    site_id: str,
    radio_id: int | str,
    now: str = "",
) -> dict[str, Any]:
    timestamp = now or _now_iso()
    projection = build_radio_projection(row, site_id=site_id, radio_id=radio_id, now=timestamp)
    conn.execute(
        "INSERT INTO fit_ap_radio_retention_meta(key,value) VALUES ('authority',?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (RADIO_RETENTION_AUTHORITY,),
    )
    key_values = tuple(projection[key] for key in _RADIO_KEY_COLUMNS)
    current = conn.execute(
        "SELECT * FROM fit_ap_radio_current WHERE site_id=? AND ap_identity=? AND radio_id=?",
        key_values,
    ).fetchone()
    if current is None:
        _insert(conn, "fit_ap_radio_current", projection, now=timestamp)
        return projection
    current_data = dict(current)
    changed = str(current_data.get("state_fingerprint") or "") != projection["state_fingerprint"]
    if changed:
        _insert(
            conn,
            "fit_ap_radio_history",
            projection,
            now=timestamp,
            previous_state_json=str(current_data.get("state_json") or "{}"),
        )
    assignments = ", ".join(
        f"{field}=?" for field in RADIO_COLUMNS if field not in _RADIO_KEY_COLUMNS
    )
    values = [projection.get(field) for field in RADIO_COLUMNS if field not in _RADIO_KEY_COLUMNS]
    values.extend(
        [
            projection["collected_at"],
            projection["collected_at"] if changed else current_data.get("changed_at"),
            timestamp,
            *key_values,
        ]
    )
    conn.execute(
        f"UPDATE fit_ap_radio_current SET {assignments}, last_seen_at=?, changed_at=?, updated_at=? "
        "WHERE site_id=? AND ap_identity=? AND radio_id=?",
        values,
    )
    if changed:
        conn.execute(
            "DELETE FROM fit_ap_radio_history WHERE site_id=? AND ap_identity=? AND radio_id=? "
            "AND id NOT IN (SELECT id FROM fit_ap_radio_history "
            "WHERE site_id=? AND ap_identity=? AND radio_id=? "
            "ORDER BY changed_at DESC, id DESC LIMIT ?)",
            (*key_values, *key_values, RADIO_HISTORY_LIMIT),
        )
    return {**current_data, **projection, "last_seen_at": projection["collected_at"]}


__all__ = [
    "RADIO_HISTORY_LIMIT",
    "RADIO_RETENTION_AUTHORITY",
    "build_radio_projection",
    "canonical_radio_state",
    "canonical_state_fingerprint",
    "canonical_state_json",
    "upsert_radio_current_and_history",
]
