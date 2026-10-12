"""Current + change-only Recent10 projections for retired HistoryStore kinds.

The tables in this module are local, bounded projections in ``devices.db``.
They are deliberately independent from the external HistoryStore and from
``history_outbox`` so ordinary collection/query paths cannot recreate the
legacy ``db/history`` directory.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Iterable

MAX_RECENT_PER_RESOURCE = 10
RETENTION_AUTHORITY = "bounded_v1"

DEVICE_FACT_RECENT_TABLE = "device_fact_recent"
FIT_AP_RESOURCE_RECENT_TABLE = "fit_ap_resource_recent"
FIT_AP_UNAUTHENTICATED_RECENT_TABLE = "fit_ap_unauthenticated_recent"
STATION_SUMMARY_CURRENT_TABLE = "station_online_summary_current"
STATION_SUMMARY_RECENT_TABLE = "station_online_summary_recent"

DEVICE_FACT_META_TABLE = "device_fact_retention_meta"
FIT_AP_RESOURCE_META_TABLE = "fit_ap_resource_retention_meta"
FIT_AP_UNAUTH_META_TABLE = "fit_ap_unauthenticated_retention_meta"
STATION_SUMMARY_META_TABLE = "station_online_summary_retention_meta"

_COMMON_IGNORED_FIELDS = frozenset(
    {
        "id",
        "created_at",
        "updated_at",
        "collected_at",
        "collect_run_uuid",
        "raw_log_path",
        "changed_at",
        "first_seen_at",
        "last_seen_at",
        "site_name",
        "lldp_collected_at",
        "optical_collected_at",
        "source_revision",
        "previous_state_json",
        "state_json",
        "state_fingerprint",
        "change_kind",
        "payload_json",
    }
)
_DEVICE_FACT_IGNORED_FIELDS = _COMMON_IGNORED_FIELDS | {"uptime"}


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _text(value: object) -> str:
    return str(value or "").strip()


def _json_value(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, bytes):
        return value.hex()
    return value


def canonical_state(payload: dict[str, Any], *, ignored: Iterable[str] = ()) -> dict[str, object]:
    ignored_fields = _COMMON_IGNORED_FIELDS | {str(field) for field in ignored}
    return {
        str(key): _json_value(value)
        for key, value in sorted(payload.items())
        if str(key) not in ignored_fields
    }


def canonical_state_json(payload: dict[str, Any], *, ignored: Iterable[str] = ()) -> str:
    return json.dumps(
        canonical_state(payload, ignored=ignored),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def state_fingerprint(payload: dict[str, Any], *, ignored: Iterable[str] = ()) -> str:
    return hashlib.sha256(
        canonical_state_json(payload, ignored=ignored).encode("utf-8")
    ).hexdigest()


def _payload_json(payload: dict[str, Any]) -> str:
    return json.dumps(
        _json_value(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _decode_payload(row: dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(str(row.get("payload_json") or "{}"))
    except (TypeError, ValueError):
        value = {}
    payload = dict(value) if isinstance(value, dict) else {}
    payload.setdefault("collected_at", row.get("collected_at"))
    payload.setdefault("created_at", row.get("created_at"))
    payload["state_json"] = row.get("state_json") or payload.get("state_json") or "{}"
    payload["state_fingerprint"] = row.get("state_fingerprint") or payload.get("state_fingerprint") or ""
    payload["changed_at"] = row.get("changed_at") or payload.get("changed_at")
    payload["change_kind"] = row.get("change_kind") or payload.get("change_kind") or "change"
    if row.get("id") is not None:
        payload["id"] = row["id"]
    return payload


def _set_authority(conn, table: str, model: str) -> None:
    conn.execute(
        f"INSERT INTO {table}(key,value) VALUES ('authority',?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (RETENTION_AUTHORITY,),
    )
    conn.execute(
        f"INSERT INTO {table}(key,value) VALUES ('model',?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (model,),
    )


def _latest_recent(conn, table: str, where: str, params: tuple[object, ...]) -> dict[str, Any] | None:
    row = conn.execute(
        f"SELECT * FROM {table} WHERE {where} ORDER BY changed_at DESC, id DESC LIMIT 1",
        params,
    ).fetchone()
    return dict(row) if row is not None else None


def _trim_recent(conn, table: str, where: str, params: tuple[object, ...]) -> None:
    rows = conn.execute(
        f"SELECT id FROM {table} WHERE {where} ORDER BY changed_at DESC, id DESC",
        params,
    ).fetchall()
    stale = [int(row[0]) for row in rows[MAX_RECENT_PER_RESOURCE:]]
    if stale:
        placeholders = ", ".join("?" for _ in stale)
        conn.execute(
            f"DELETE FROM {table} WHERE id IN ({placeholders})",
            stale,
        )


def _record_recent(
    conn,
    *,
    table: str,
    where: str,
    where_params: tuple[object, ...],
    identity_fields: tuple[str, ...],
    payload: dict[str, Any],
    previous: dict[str, Any] | None,
    ignored: Iterable[str] = (),
    now: str,
) -> bool:
    state_json = canonical_state_json(payload, ignored=ignored)
    fingerprint = hashlib.sha256(state_json.encode("utf-8")).hexdigest()
    previous_state_json = canonical_state_json(previous or {}, ignored=ignored)
    previous_fingerprint = (
        state_fingerprint(previous, ignored=ignored) if previous is not None else ""
    )
    initial = False
    if previous is None:
        latest = _latest_recent(conn, table, where, where_params)
        if latest is None:
            initial = True
        else:
            previous_fingerprint = _text(latest.get("state_fingerprint"))
            previous_state_json = _text(latest.get("state_json")) or "{}"
    if previous_fingerprint == fingerprint:
        return False
    observed_at = _text(payload.get("collected_at")) or now
    values = [payload.get(field) for field in identity_fields]
    values.extend(
        [
            _payload_json(payload),
            state_json,
            fingerprint,
            previous_state_json,
            observed_at,
            "initial" if initial else "change",
            now,
        ]
    )
    columns = (
        *identity_fields,
        "payload_json",
        "state_json",
        "state_fingerprint",
        "previous_state_json",
        "changed_at",
        "change_kind",
        "created_at",
    )
    conn.execute(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
        values,
    )
    _trim_recent(conn, table, where, where_params)
    return True


def record_device_fact_change(conn, payload: dict[str, Any], *, previous: dict[str, Any] | None, now: str = "") -> bool:
    timestamp = now or _now()
    _set_authority(conn, DEVICE_FACT_META_TABLE, "device_fact")
    identity = {"device_uuid": _text(payload.get("device_uuid"))}
    if not identity["device_uuid"]:
        return False
    return _record_recent(
        conn,
        table=DEVICE_FACT_RECENT_TABLE,
        where="device_uuid=?",
        where_params=(identity["device_uuid"],),
        identity_fields=("device_uuid",),
        payload={**payload, **identity},
        previous=previous,
        ignored=_DEVICE_FACT_IGNORED_FIELDS,
        now=timestamp,
    )


def list_device_fact_recent(conn, device_uuid: str, *, limit: int = MAX_RECENT_PER_RESOURCE) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM device_fact_recent WHERE device_uuid=? ORDER BY changed_at DESC, id DESC LIMIT ?",
        (_text(device_uuid), max(1, min(int(limit), MAX_RECENT_PER_RESOURCE))),
    ).fetchall()
    return [_decode_payload(dict(row)) for row in rows]


def record_fit_ap_resource_change(conn, payload: dict[str, Any], *, previous: dict[str, Any] | None, now: str = "") -> bool:
    timestamp = now or _now()
    identity = {
        "ac_device_uuid": _text(payload.get("ac_device_uuid")),
        "ap_uuid": _text(payload.get("ap_uuid")),
    }
    if not identity["ac_device_uuid"] or not identity["ap_uuid"]:
        return False
    _set_authority(conn, FIT_AP_RESOURCE_META_TABLE, "fit_ap_resource")
    return _record_recent(
        conn,
        table=FIT_AP_RESOURCE_RECENT_TABLE,
        where="ac_device_uuid=? AND ap_uuid=?",
        where_params=(identity["ac_device_uuid"], identity["ap_uuid"]),
        identity_fields=("ac_device_uuid", "ap_uuid"),
        payload={**payload, **identity},
        previous=previous,
        now=timestamp,
    )


def list_fit_ap_resource_recent(conn, ac_device_uuid: str | None = None, *, limit: int = MAX_RECENT_PER_RESOURCE) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[object] = []
    if ac_device_uuid:
        clauses.append("ac_device_uuid=?")
        params.append(_text(ac_device_uuid))
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(max(1, min(int(limit), 100_000)))
    rows = conn.execute(
        f"SELECT * FROM fit_ap_resource_recent {where} ORDER BY changed_at DESC, id DESC LIMIT ?",
        params,
    ).fetchall()
    return [_decode_payload(dict(row)) for row in rows]


def unauthenticated_identity_key(payload: dict[str, Any]) -> str:
    for field in ("inferred_ap_mac", "serial_number", "apid", "ap_name"):
        value = _text(payload.get(field))
        if value:
            return f"{field}:{value.casefold()}"
    return ""


def record_fit_ap_unauthenticated_change(
    conn,
    payload: dict[str, Any],
    *,
    previous: dict[str, Any] | None,
    identity_key: str | None = None,
    now: str = "",
) -> bool:
    timestamp = now or _now()
    identity = {
        "ac_device_uuid": _text(payload.get("ac_device_uuid")),
        "identity_key": _text(identity_key) or unauthenticated_identity_key(payload),
    }
    if not identity["ac_device_uuid"] or not identity["identity_key"]:
        return False
    _set_authority(conn, FIT_AP_UNAUTH_META_TABLE, "fit_ap_unauthenticated")
    return _record_recent(
        conn,
        table=FIT_AP_UNAUTHENTICATED_RECENT_TABLE,
        where="ac_device_uuid=? AND identity_key=?",
        where_params=(identity["ac_device_uuid"], identity["identity_key"]),
        identity_fields=("ac_device_uuid", "identity_key"),
        payload={**payload, **identity},
        previous=previous,
        now=timestamp,
    )


def list_fit_ap_unauthenticated_recent(conn, ac_device_uuid: str | None = None, *, limit: int = 100_000) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[object] = []
    if ac_device_uuid:
        clauses.append("ac_device_uuid=?")
        params.append(_text(ac_device_uuid))
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(max(1, min(int(limit), 100_000)))
    rows = conn.execute(
        f"SELECT * FROM fit_ap_unauthenticated_recent {where} ORDER BY changed_at DESC, id DESC LIMIT ?",
        params,
    ).fetchall()
    return [_decode_payload(dict(row)) for row in rows]


def _station_payload(row: dict[str, Any], *, collected_at: str) -> dict[str, Any]:
    return {
        "site_name": _text(row.get("site") or row.get("site_name")),
        "ap_total": int(row.get("total") or row.get("ap_total") or 0),
        "online_count": int(row.get("online") or row.get("online_count") or 0),
        "offline_count": int(row.get("offline") or row.get("offline_count") or 0),
        "online_rate": _text(row.get("online_rate")),
        "remark": _text(row.get("remark")),
        "collected_at": _text(row.get("collected_at")) or collected_at,
        "updated_at": _text(row.get("updated_at")) or collected_at,
    }


def upsert_station_online_summary(conn, row: dict[str, Any], *, collected_at: str | None = None, now: str = "") -> bool:
    timestamp = now or _now()
    payload = _station_payload(row, collected_at=collected_at or timestamp)
    site_name = payload["site_name"]
    if not site_name:
        return False
    _set_authority(conn, STATION_SUMMARY_META_TABLE, "station_online_summary")
    current = conn.execute(
        "SELECT * FROM station_online_summary_current WHERE site_name=?",
        (site_name,),
    ).fetchone()
    previous = None
    if current is not None:
        previous = _decode_payload(dict(current))
    changed = previous is None or state_fingerprint(previous) != state_fingerprint(payload)
    first_seen = _text(previous.get("first_seen_at")) if previous else _text(payload["collected_at"])
    changed_at = payload["collected_at"] if changed else _text(previous.get("changed_at"))
    conn.execute(
        """
        INSERT INTO station_online_summary_current (
            site_name, payload_json, state_json, state_fingerprint,
            first_seen_at, last_seen_at, changed_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(site_name) DO UPDATE SET
            payload_json=excluded.payload_json,
            state_json=excluded.state_json,
            state_fingerprint=excluded.state_fingerprint,
            last_seen_at=excluded.last_seen_at,
            changed_at=excluded.changed_at,
            updated_at=excluded.updated_at
        """,
        (
            site_name,
            _payload_json(payload),
            canonical_state_json(payload),
            state_fingerprint(payload),
            first_seen,
            payload["collected_at"],
            changed_at,
            _text(previous.get("created_at")) if previous else timestamp,
            timestamp,
        ),
    )
    if not changed:
        return False
    return _record_recent(
        conn,
        table=STATION_SUMMARY_RECENT_TABLE,
        where="site_name=?",
        where_params=(site_name,),
        identity_fields=("site_name",),
        payload=payload,
        previous=previous,
        now=timestamp,
    )


def list_station_online_summary_recent(conn, site_name: str | None = None, *, limit: int = 500, offset: int = 0) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[object] = []
    if site_name:
        clauses.append("site_name=?")
        params.append(_text(site_name))
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    safe_limit = max(1, int(limit))
    safe_offset = max(0, int(offset))
    params.extend((safe_limit, safe_offset))
    rows = conn.execute(
        f"SELECT * FROM station_online_summary_recent {where} ORDER BY changed_at DESC, id DESC LIMIT ? OFFSET ?",
        params,
    ).fetchall()
    return [_decode_payload(dict(row)) for row in rows]


def count_station_online_summary_recent(conn, site_name: str | None = None) -> int:
    if site_name:
        row = conn.execute(
            "SELECT COUNT(*) FROM station_online_summary_recent WHERE site_name=?",
            (_text(site_name),),
        ).fetchone()
    else:
        row = conn.execute("SELECT COUNT(*) FROM station_online_summary_recent").fetchone()
    return int(row[0] if row else 0)


__all__ = [
    "DEVICE_FACT_RECENT_TABLE",
    "FIT_AP_RESOURCE_RECENT_TABLE",
    "FIT_AP_UNAUTHENTICATED_RECENT_TABLE",
    "MAX_RECENT_PER_RESOURCE",
    "RETENTION_AUTHORITY",
    "STATION_SUMMARY_CURRENT_TABLE",
    "STATION_SUMMARY_RECENT_TABLE",
    "count_station_online_summary_recent",
    "list_device_fact_recent",
    "list_fit_ap_resource_recent",
    "list_fit_ap_unauthenticated_recent",
    "list_station_online_summary_recent",
    "record_device_fact_change",
    "record_fit_ap_resource_change",
    "record_fit_ap_unauthenticated_change",
    "state_fingerprint",
    "unauthenticated_identity_key",
    "upsert_station_online_summary",
]
