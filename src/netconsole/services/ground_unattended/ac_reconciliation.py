"""AC full-snapshot delta and Syslog position reconciliation.

The AC device currently exposes a complete Mesh-Link snapshot rather than a
device-side change stream.  This module keeps that transport detail explicit:
we calculate a local delta, retain every delta record, and never treat an AC
row as permission to overwrite the Syslog position projection.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

AC_DELTA_ADDED = "ADDED"
AC_DELTA_UPDATED = "UPDATED"
AC_DELTA_REMOVED = "REMOVED"
AC_DELTA_UNCHANGED = "UNCHANGED"
AC_DELTA_UNKNOWN = "UNKNOWN"
AC_DELTA_ACTIONS = frozenset(
    {
        AC_DELTA_ADDED,
        AC_DELTA_UPDATED,
        AC_DELTA_REMOVED,
        AC_DELTA_UNCHANGED,
        AC_DELTA_UNKNOWN,
    }
)

RECONCILIATION_CONSISTENT = "CONSISTENT"
RECONCILIATION_SYSLOG_NEWER = "SYSLOG_NEWER"
RECONCILIATION_AC_NEWER = "AC_NEWER"
RECONCILIATION_CONFLICT = "CONFLICT"
RECONCILIATION_STALE = "STALE"
RECONCILIATION_UNKNOWN = "UNKNOWN"
RECONCILIATION_STATES = frozenset(
    {
        RECONCILIATION_CONSISTENT,
        RECONCILIATION_SYSLOG_NEWER,
        RECONCILIATION_AC_NEWER,
        RECONCILIATION_CONFLICT,
        RECONCILIATION_STALE,
        RECONCILIATION_UNKNOWN,
    }
)

_FRESH_STATUSES = frozenset({"fresh", "success", "complete", "FRESH", "SUCCESS", "COMPLETE"})


def _text(value: object) -> str:
    return str(value or "").strip()


def _parse_time(value: object) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _identity(value: object) -> str:
    """Return a stable AP identity without fuzzy matching."""

    text = _text(value).casefold()
    if not text:
        return ""
    return text.replace(":", "").replace("-", "").replace(".", "")


def _ap_identity(row: Mapping[str, Any]) -> str:
    return _identity(
        row.get("peer_ap_id")
        or row.get("peer_ap_mac")
        or row.get("current_ap_id")
        or row.get("current_ap_mac")
        or row.get("peer_ap_name")
        or row.get("current_ap_name")
    )


def _row_key(row: Mapping[str, Any]) -> tuple[str, bool]:
    mr_id = _text(row.get("mr_id") or row.get("device_uuid") or row.get("mr_device_id"))
    if mr_id:
        return f"mr:{mr_id}", True
    # An unidentified row is retained as evidence, but it is not eligible for
    # a removal/update decision against a known MR.
    digest = hashlib.sha256(
        json.dumps(dict(row), ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:24]
    return f"unknown:{digest}", False


def _fingerprint(row: Mapping[str, Any]) -> str:
    # These values identify the observation envelope, not the entity state.
    # A new full snapshot must therefore be able to produce UNCHANGED when
    # the MR/AP relationship is unchanged but the transport timestamps and
    # source snapshot number advance.
    comparable = {
        key: value
        for key, value in row.items()
        if key
        not in {
            "snapshot_id",
            "source_snapshot_id",
            "received_at",
            "device_time",
            "collected_at",
            "raw_source_reference",
        }
    }
    return hashlib.sha256(
        json.dumps(comparable, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class AcSnapshotEnvelope:
    controller_id: str
    snapshot_id: str
    rows: tuple[Mapping[str, Any], ...] = ()
    device_time: str = ""
    received_at: str = ""
    data_status: str = "fresh"
    complete: bool = True
    revision: str = ""

    @property
    def observation_time(self) -> str:
        return _text(self.device_time) or _text(self.received_at)

    @property
    def is_fresh_complete(self) -> bool:
        return self.complete and _text(self.data_status) in _FRESH_STATUSES


@dataclass(frozen=True)
class AcDeltaRecord:
    controller_id: str
    snapshot_id: str
    entity_key: str
    change_type: str
    before: Mapping[str, Any] = field(default_factory=dict)
    after: Mapping[str, Any] = field(default_factory=dict)
    source_device_time: str = ""
    received_at: str = ""
    freshness_status: str = "UNKNOWN"
    safe_to_apply: bool = False
    reason: str = ""

    def to_record(self, *, site_id: str, run_id: str, created_at: str) -> dict[str, Any]:
        return {
            "site_id": site_id,
            "run_id": run_id,
            "controller_id": self.controller_id,
            "snapshot_id": self.snapshot_id,
            "entity_key": self.entity_key,
            "change_type": self.change_type,
            "before_json": json.dumps(dict(self.before), ensure_ascii=False, sort_keys=True),
            "after_json": json.dumps(dict(self.after), ensure_ascii=False, sort_keys=True),
            "source_device_time": self.source_device_time,
            "received_at": self.received_at,
            "freshness_status": self.freshness_status,
            "safe_to_apply": int(self.safe_to_apply),
            "reason": self.reason,
            "created_at": created_at,
        }


@dataclass(frozen=True)
class AcDeltaResult:
    controller_id: str
    snapshot_id: str
    accepted: bool
    reason: str
    records: tuple[AcDeltaRecord, ...] = ()

    @property
    def counts(self) -> dict[str, int]:
        counts = {action: 0 for action in sorted(AC_DELTA_ACTIONS)}
        for item in self.records:
            counts[item.change_type] = counts.get(item.change_type, 0) + 1
        return counts

    @property
    def safe_records(self) -> tuple[AcDeltaRecord, ...]:
        return tuple(item for item in self.records if item.safe_to_apply)

    def to_payload(self) -> dict[str, Any]:
        return {
            "controller_id": self.controller_id,
            "snapshot_id": self.snapshot_id,
            "accepted": self.accepted,
            "reason": self.reason,
            "counts": self.counts,
            "safe_to_apply_count": len(self.safe_records),
        }


def diff_full_snapshot(
    previous: AcSnapshotEnvelope | None,
    current: AcSnapshotEnvelope,
) -> AcDeltaResult:
    """Calculate a local delta without deleting prior snapshot evidence.

    A stale, incomplete, failed, or older snapshot produces only UNKNOWN
    records and no REMOVED records.  This is the important safety boundary for
    a full snapshot transported over a lossy/slow AC path.
    """

    current_rows: dict[str, tuple[Mapping[str, Any], bool]] = {}
    for row in current.rows:
        key, identified = _row_key(row)
        current_rows[key] = (dict(row), identified)

    previous_rows: dict[str, Mapping[str, Any]] = {}
    if previous is not None:
        previous_rows = {
            _row_key(row)[0]: dict(row)
            for row in previous.rows
            if _row_key(row)[1]
        }

    freshness = _text(current.data_status) or "UNKNOWN"
    safe = current.is_fresh_complete
    current_time = _parse_time(current.observation_time)
    previous_time = _parse_time(previous.observation_time) if previous else None
    older = bool(current_time and previous_time and current_time < previous_time)
    if older:
        safe = False
    if not safe:
        reason = "STALE_OR_INCOMPLETE_SNAPSHOT"
        if older:
            reason = "OLDER_THAN_PREVIOUS_SNAPSHOT"
        records = tuple(
            AcDeltaRecord(
                controller_id=current.controller_id,
                snapshot_id=current.snapshot_id,
                entity_key=key,
                change_type=AC_DELTA_UNKNOWN,
                after=row,
                source_device_time=current.device_time,
                received_at=current.received_at,
                freshness_status=freshness,
                safe_to_apply=False,
                reason=reason,
            )
            for key, (row, _identified) in sorted(current_rows.items())
        )
        return AcDeltaResult(current.controller_id, current.snapshot_id, False, reason, records)

    records: list[AcDeltaRecord] = []
    for key, (row, identified) in sorted(current_rows.items()):
        if not identified:
            records.append(
                AcDeltaRecord(
                    controller_id=current.controller_id,
                    snapshot_id=current.snapshot_id,
                    entity_key=key,
                    change_type=AC_DELTA_UNKNOWN,
                    after=row,
                    source_device_time=current.device_time,
                    received_at=current.received_at,
                    freshness_status=freshness,
                    safe_to_apply=False,
                    reason="MR_IDENTITY_MISSING",
                )
            )
            continue
        before = previous_rows.get(key)
        if before is None:
            action = AC_DELTA_ADDED
        elif _fingerprint(before) != _fingerprint(row):
            action = AC_DELTA_UPDATED
        else:
            action = AC_DELTA_UNCHANGED
        records.append(
            AcDeltaRecord(
                controller_id=current.controller_id,
                snapshot_id=current.snapshot_id,
                entity_key=key,
                change_type=action,
                before=before or {},
                after=row,
                source_device_time=current.device_time,
                received_at=current.received_at,
                freshness_status=freshness,
                safe_to_apply=True,
                reason="FULL_SNAPSHOT_LOCAL_DIFF",
            )
        )

    for key, before in sorted(previous_rows.items()):
        if key in current_rows:
            continue
        records.append(
            AcDeltaRecord(
                controller_id=current.controller_id,
                snapshot_id=current.snapshot_id,
                entity_key=key,
                change_type=AC_DELTA_REMOVED,
                before=before,
                source_device_time=current.device_time,
                received_at=current.received_at,
                freshness_status=freshness,
                safe_to_apply=True,
                reason="FULL_SNAPSHOT_LOCAL_DIFF",
            )
        )
    return AcDeltaResult(
        current.controller_id,
        current.snapshot_id,
        True,
        "FULL_SNAPSHOT_ACCEPTED",
        tuple(records),
    )


def _syslog_time(state: Mapping[str, Any]) -> str:
    if _text(state.get("last_event_time_source")) == "DEVICE_TIME":
        return _text(state.get("last_event_time"))
    return _text(state.get("last_receive_time")) or _text(state.get("last_event_time"))


def _ac_time(row: Mapping[str, Any]) -> str:
    return _text(row.get("device_time")) or _text(row.get("received_at")) or _text(row.get("collected_at"))


@dataclass(frozen=True)
class PositionReconciliation:
    mr_id: str
    state: str
    syslog_identity: str = ""
    ac_identity: str = ""
    syslog_event_time: str = ""
    syslog_receive_time: str = ""
    ac_event_time: str = ""
    ac_received_at: str = ""
    reason: str = ""

    def to_record(self, *, site_id: str, run_id: str, observed_at: str) -> dict[str, Any]:
        return {
            "site_id": site_id,
            "run_id": run_id,
            "mr_id": self.mr_id,
            "state": self.state,
            "syslog_identity": self.syslog_identity,
            "ac_identity": self.ac_identity,
            "syslog_event_time": self.syslog_event_time,
            "syslog_receive_time": self.syslog_receive_time,
            "ac_event_time": self.ac_event_time,
            "ac_received_at": self.ac_received_at,
            "reason": self.reason,
            "observed_at": observed_at,
        }


def reconcile_syslog_ac(
    syslog_state: Mapping[str, Any] | None,
    ac_row: Mapping[str, Any] | None,
    *,
    now: str,
    stale_after_seconds: float = 120.0,
) -> PositionReconciliation:
    """Compare evidence without mutating either source projection."""

    syslog = syslog_state or {}
    ac = ac_row or {}
    mr_id = _text(syslog.get("device_uuid") or ac.get("mr_id") or ac.get("mr_device_id"))
    syslog_identity = _ap_identity(
        {
            "current_ap_id": syslog.get("current_ap_id"),
            "current_ap_mac": syslog.get("current_ap_mac"),
            "current_ap_name": syslog.get("current_ap_name"),
        }
    )
    ac_identity = _ap_identity(ac)
    syslog_event_time = _text(syslog.get("last_event_time"))
    syslog_receive_time = _text(syslog.get("last_receive_time"))
    ac_event_time = _text(ac.get("device_time"))
    ac_received_at = _text(ac.get("received_at") or ac.get("collected_at"))
    syslog_time = _parse_time(_syslog_time(syslog))
    ac_time = _parse_time(_ac_time(ac))
    now_time = _parse_time(now)

    if not syslog_identity or not ac_identity:
        return PositionReconciliation(
            mr_id,
            RECONCILIATION_UNKNOWN,
            syslog_identity,
            ac_identity,
            syslog_event_time,
            syslog_receive_time,
            ac_event_time,
            ac_received_at,
            "MISSING_EXACT_SOURCE_IDENTITY",
        )
    if now_time is not None:
        too_old = []
        for label, value in (("SYSLOG", syslog_time), ("AC", ac_time)):
            if value is not None and (now_time - value).total_seconds() > stale_after_seconds:
                too_old.append(label)
        if too_old:
            return PositionReconciliation(
                mr_id,
                RECONCILIATION_STALE,
                syslog_identity,
                ac_identity,
                syslog_event_time,
                syslog_receive_time,
                ac_event_time,
                ac_received_at,
                "EVIDENCE_OLDER_THAN_STALE_THRESHOLD:" + ",".join(too_old),
            )
    if syslog_identity == ac_identity:
        state = RECONCILIATION_CONSISTENT
        reason = "EXACT_AP_IDENTITY_MATCH"
    elif syslog_time is not None and ac_time is not None and syslog_time > ac_time:
        state = RECONCILIATION_SYSLOG_NEWER
        reason = "SYSLOG_EVENT_IS_NEWER"
    elif syslog_time is not None and ac_time is not None and ac_time > syslog_time:
        state = RECONCILIATION_AC_NEWER
        reason = "AC_OBSERVATION_IS_NEWER"
    else:
        state = RECONCILIATION_CONFLICT
        reason = "DIFFERENT_IDENTITY_WITHOUT_ORDERING"
    return PositionReconciliation(
        mr_id,
        state,
        syslog_identity,
        ac_identity,
        syslog_event_time,
        syslog_receive_time,
        ac_event_time,
        ac_received_at,
        reason,
    )


__all__ = [
    "AC_DELTA_ACTIONS",
    "AC_DELTA_ADDED",
    "AC_DELTA_REMOVED",
    "AC_DELTA_UNCHANGED",
    "AC_DELTA_UNKNOWN",
    "AC_DELTA_UPDATED",
    "AcDeltaRecord",
    "AcDeltaResult",
    "AcSnapshotEnvelope",
    "PositionReconciliation",
    "RECONCILIATION_AC_NEWER",
    "RECONCILIATION_CONFLICT",
    "RECONCILIATION_CONSISTENT",
    "RECONCILIATION_STALE",
    "RECONCILIATION_STATES",
    "RECONCILIATION_SYSLOG_NEWER",
    "RECONCILIATION_UNKNOWN",
    "diff_full_snapshot",
    "reconcile_syslog_ac",
]
