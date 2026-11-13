from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any


_POSITION_EVENT_TYPES = {
    "MESH_LINKUP",
    "MESH_LINKDOWN",
    "MESH_ACTIVELINK_SWITCH",
}
_VALID_IDENTITY_STATUSES = {
    "matched",
    "verified",
    "unconfirmed_source_ip",
    "unconfirmed_hostname",
}
_VALID_RESOLUTION_STATUSES = {"PHYSICAL_AP", "RADIO_BSSID"}
_MAX_DEDUP_HISTORY = 256


@dataclass(frozen=True)
class PositionApplyResult:
    state: dict[str, Any]
    accepted: bool = False
    position_changed: bool = False
    duplicate: bool = False
    out_of_order: bool = False
    ignored: bool = False
    reason: str = ""


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def _parse_time(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.astimezone()


def _text(value: object) -> str:
    return str(value or "").strip()


def _identity_key(state: Mapping[str, Any]) -> str:
    return (
        _text(state.get("current_ap_id"))
        or _text(state.get("current_ap_mac"))
        or _text(state.get("current_ap_name"))
    )


def _event_identity_key(event: Mapping[str, Any]) -> str:
    details = event.get("details")
    details = details if isinstance(details, Mapping) else {}
    return (
        _text(details.get("peer_ap_id"))
        or _text(details.get("peer_ap_mac"))
        or _text(event.get("peer_mac"))
        or _text(details.get("peer_ap_name"))
        or _text(event.get("peer_name"))
    )


def _default_state(device_uuid: str) -> dict[str, Any]:
    return {
        "device_uuid": device_uuid,
        "run_id": "",
        "train_id": "",
        "mr_role": "",
        "current_ap_id": "",
        "current_ap_name": "",
        "current_ap_mac": "",
        "previous_ap_id": "",
        "previous_ap_name": "",
        "previous_ap_mac": "",
        "station": "",
        "section": "",
        "rssi": None,
        "position_status": "UNKNOWN",
        "position_quality": "UNKNOWN",
        "position_source": "SYSLOG",
        "last_event_type": "",
        "last_event_time": "",
        "last_event_time_source": "RECEIVE_TIME",
        "last_event_time_precision": "RECEIVE_TIME_ONLY",
        "last_receive_time": "",
        "last_raw_persist_time": "",
        "last_parse_complete_time": "",
        "last_switch_time": "",
        "last_position_commit_time": "",
        "last_position_latency_ms": None,
        "last_position_dedup_key": "",
        "recent_position_dedup_keys": [],
        "last_position_sequence": 0,
        "last_observed_identity_status": "",
        "last_observed_ap_name": "",
        "last_observed_ap_mac": "",
        "position_event_count": 0,
        "duplicate_event_count": 0,
        "out_of_order_event_count": 0,
        "updated_at": "",
    }


class PositionEngine:
    """Project the latest exact Syslog AP state for each MR.

    The engine deliberately keeps only a bounded Current projection. The full
    WMESH event history is persisted by the Repository separately, so batching
    here can suppress repeated state writes without dropping meaningful
    transitions.
    """

    def __init__(self, *, duplicate_window_seconds: float = 60.0) -> None:
        self.duplicate_window_seconds = max(1.0, float(duplicate_window_seconds))
        self._states: dict[str, dict[str, Any]] = {}

    def restore(self, rows: Iterable[Mapping[str, Any]]) -> None:
        self._states.clear()
        for row in rows:
            device_uuid = _text(row.get("device_uuid"))
            if not device_uuid:
                continue
            state = _default_state(device_uuid)
            state.update(dict(row))
            state["recent_position_dedup_keys"] = self._dedup_history(state)
            last_key = _text(state.get("last_position_dedup_key"))
            if last_key and not any(
                entry.get("key") == last_key
                for entry in state["recent_position_dedup_keys"]
            ):
                state["recent_position_dedup_keys"] = (
                    state["recent_position_dedup_keys"]
                    + [
                        {
                            "key": last_key,
                            "event_time": _text(state.get("last_event_time")),
                            "event_time_source": _text(
                                state.get("last_event_time_source")
                            ),
                        }
                    ]
                )[-_MAX_DEDUP_HISTORY:]
            self._states[device_uuid] = state

    def states(self) -> dict[str, dict[str, Any]]:
        return {key: dict(value) for key, value in self._states.items()}

    def state(self, device_uuid: str) -> dict[str, Any] | None:
        value = self._states.get(_text(device_uuid))
        return dict(value) if value is not None else None

    def mark_committed(
        self,
        device_uuid: str,
        *,
        committed_at: str,
        latency_ms: float | None,
    ) -> dict[str, Any] | None:
        state = self._states.get(_text(device_uuid))
        if state is None:
            return None
        state["last_position_commit_time"] = committed_at
        state["last_position_latency_ms"] = latency_ms
        return dict(state)

    def apply(
        self,
        event: Mapping[str, Any],
        *,
        raw_persist_time: str = "",
        parse_complete_time: str = "",
        now: str | None = None,
    ) -> PositionApplyResult:
        device_uuid = _text(event.get("device_uuid"))
        event_type = _text(event.get("event_type")).upper()
        if not device_uuid or event_type not in _POSITION_EVENT_TYPES:
            return PositionApplyResult(
                state=dict(
                    self._states.get(device_uuid) or _default_state(device_uuid)
                ),
                ignored=True,
                reason="NOT_A_POSITION_EVENT",
            )

        state = self._states.setdefault(device_uuid, _default_state(device_uuid))
        before = dict(state)
        details = event.get("details")
        details = details if isinstance(details, Mapping) else {}
        event_time = _text(event.get("event_time")) or _text(event.get("receive_time"))
        event_source = _text(event.get("event_time_source")) or "RECEIVE_TIME"
        event_precision = _text(event.get("event_time_precision")) or (
            "DEVICE_TIMESTAMP" if event_source == "DEVICE_TIME" else "RECEIVE_TIME_ONLY"
        )
        event_dt = _parse_time(event_time)
        last_dt = _parse_time(state.get("last_event_time"))
        try:
            sequence = int(
                details.get("global_receive_sequence")
                or event.get("global_receive_sequence")
                or 0
            )
        except (TypeError, ValueError):
            sequence = 0
        try:
            previous_sequence = int(state.get("last_position_sequence") or 0)
        except (TypeError, ValueError):
            previous_sequence = 0
        dedup_key = _text(event.get("position_dedup_key")) or self._dedup_key(event)

        if dedup_key and self._is_duplicate(
            state,
            dedup_key=dedup_key,
            event_source=event_source,
            event_dt=event_dt,
        ):
            state["duplicate_event_count"] = (
                int(state.get("duplicate_event_count") or 0) + 1
            )
            state["run_id"] = _text(event.get("run_id")) or _text(state.get("run_id"))
            state["updated_at"] = now or _now()
            return PositionApplyResult(
                state=dict(state),
                accepted=False,
                duplicate=True,
                reason="DUPLICATE_POSITION_EVENT",
            )

        if event_dt is not None and last_dt is not None:
            older = event_dt < last_dt
            same_time_older_sequence = (
                event_dt == last_dt
                and sequence > 0
                and previous_sequence > 0
                and sequence < previous_sequence
            )
            if older or same_time_older_sequence:
                self._remember_dedup(
                    state,
                    dedup_key=dedup_key,
                    event_time=event_time,
                    event_time_source=event_source,
                )
                state["out_of_order_event_count"] = (
                    int(state.get("out_of_order_event_count") or 0) + 1
                )
                state["updated_at"] = now or _now()
                return PositionApplyResult(
                    state=dict(state),
                    accepted=False,
                    out_of_order=True,
                    reason="OUT_OF_ORDER_POSITION_EVENT",
                )

        identity_status = _text(details.get("identity_status")).casefold()
        resolution_status = _text(details.get("resolution_status")).upper()
        current_ap = {
            "id": _text(details.get("peer_ap_id")),
            "name": _text(details.get("peer_ap_name")) or _text(event.get("peer_name")),
            "mac": _text(details.get("peer_ap_mac")),
        }
        current_valid = bool(
            identity_status in _VALID_IDENTITY_STATUSES
            and resolution_status in _VALID_RESOLUTION_STATUSES
            and (current_ap["id"] or current_ap["mac"] or current_ap["name"])
        )
        current_key = _identity_key(state)
        incoming_key = current_ap["id"] or current_ap["mac"] or current_ap["name"]
        stale_linkdown = bool(
            event_type == "MESH_LINKDOWN"
            and current_valid
            and current_key
            and current_key != incoming_key
        )

        state.update(
            {
                "run_id": _text(event.get("run_id")) or _text(state.get("run_id")),
                "train_id": _text(event.get("train_id"))
                or _text(state.get("train_id")),
                "mr_role": _text(event.get("mr_role")) or _text(state.get("mr_role")),
                "last_observed_identity_status": identity_status or "unknown",
                "last_observed_ap_name": current_ap["name"],
                "last_observed_ap_mac": current_ap["mac"]
                or _text(event.get("peer_mac")),
                "position_event_count": int(state.get("position_event_count") or 0) + 1,
                "position_source": "SYSLOG",
                "updated_at": now or _now(),
            }
        )
        self._remember_dedup(
            state,
            dedup_key=dedup_key,
            event_time=event_time,
            event_time_source=event_source,
        )

        if current_valid and not stale_linkdown:
            state.update(
                {
                    "last_event_type": event_type,
                    "last_event_time": event_time,
                    "last_event_time_source": event_source,
                    "last_event_time_precision": event_precision,
                    "last_receive_time": _text(event.get("receive_time")),
                    "last_raw_persist_time": _text(raw_persist_time),
                    "last_parse_complete_time": _text(parse_complete_time),
                    "last_position_dedup_key": dedup_key,
                    "last_position_sequence": sequence,
                }
            )

        position_changed = False
        if not current_valid:
            # An unresolved observation is retained for diagnostics, but it is
            # not a new position fact and must not advance the freshness/order
            # anchor used by the last valid Syslog identity.
            state["position_quality"] = "UNRESOLVED_IDENTITY"
            state["position_status"] = "STALE" if _identity_key(state) else "UNRESOLVED"
        elif event_type == "MESH_LINKDOWN":
            # A disconnect is evidence about the previous AP, but it is not a
            # license to erase the last known exact AP. If the Current is empty,
            # retain the exact endpoint carried by the disconnect as a bounded
            # last-known position.
            if not current_key:
                self._set_current(state, current_ap)
                state["station"] = _text(event.get("station"))
                state["section"] = _text(event.get("section"))
                state["rssi"] = (
                    details.get("rssi")
                    if details.get("rssi") is not None
                    else details.get("new_rssi")
                )
                position_changed = True
                state["position_status"] = "DISCONNECTED"
                state["position_quality"] = "EXACT_IDENTITY"
            elif current_key == incoming_key:
                state["rssi"] = (
                    details.get("rssi")
                    if details.get("rssi") is not None
                    else state.get("rssi")
                )
                state["position_status"] = "DISCONNECTED"
                state["position_quality"] = "EXACT_IDENTITY"
        else:
            previous_key = _identity_key(state)
            if incoming_key != previous_key:
                if previous_key:
                    self._copy_current_to_previous(state)
                else:
                    previous = {
                        "id": _text(details.get("previous_peer_ap_id")),
                        "name": _text(details.get("previous_peer_ap_name"))
                        or _text(event.get("previous_peer_name")),
                        "mac": _text(details.get("previous_peer_ap_mac"))
                        or _text(event.get("previous_peer_mac")),
                    }
                    if previous["id"] or previous["mac"] or previous["name"]:
                        self._set_previous(state, previous)
                self._set_current(state, current_ap)
                position_changed = True
            if _text(event.get("station")):
                state["station"] = _text(event.get("station"))
            if _text(event.get("section")):
                state["section"] = _text(event.get("section"))
            if details.get("rssi") is not None or details.get("new_rssi") is not None:
                state["rssi"] = (
                    details.get("rssi")
                    if details.get("rssi") is not None
                    else details.get("new_rssi")
                )
            state["position_status"] = "VALID"
            state["position_quality"] = "EXACT_IDENTITY"
            if event_type == "MESH_ACTIVELINK_SWITCH":
                state["last_switch_time"] = event_time

        return PositionApplyResult(
            state=dict(state),
            accepted=True,
            position_changed=position_changed
            or before.get("position_status") != state.get("position_status"),
            reason="POSITION_UPDATED"
            if current_valid
            else "POSITION_RETAINED_UNRESOLVED",
        )

    @staticmethod
    def _set_current(state: dict[str, Any], value: Mapping[str, Any]) -> None:
        state["current_ap_id"] = _text(value.get("id"))
        state["current_ap_name"] = _text(value.get("name"))
        state["current_ap_mac"] = _text(value.get("mac"))

    @staticmethod
    def _set_previous(state: dict[str, Any], value: Mapping[str, Any]) -> None:
        state["previous_ap_id"] = _text(value.get("id"))
        state["previous_ap_name"] = _text(value.get("name"))
        state["previous_ap_mac"] = _text(value.get("mac"))

    @classmethod
    def _copy_current_to_previous(cls, state: dict[str, Any]) -> None:
        cls._set_previous(
            state,
            {
                "id": state.get("current_ap_id"),
                "name": state.get("current_ap_name"),
                "mac": state.get("current_ap_mac"),
            },
        )

    def _is_duplicate(
        self,
        state: Mapping[str, Any],
        *,
        dedup_key: str,
        event_source: str,
        event_dt: datetime | None,
    ) -> bool:
        for entry in self._dedup_history(state):
            if entry.get("key") != dedup_key:
                continue
            previous_source = _text(entry.get("event_time_source"))
            if event_source == "DEVICE_TIME" or previous_source == "DEVICE_TIME":
                return True
            previous_dt = _parse_time(entry.get("event_time"))
            return bool(
                event_dt is not None
                and previous_dt is not None
                and abs((event_dt - previous_dt).total_seconds())
                <= self.duplicate_window_seconds
            )
        return False

    @staticmethod
    def _dedup_history(state: Mapping[str, Any]) -> list[dict[str, str]]:
        raw = state.get("recent_position_dedup_keys")
        if not isinstance(raw, list):
            return []
        result: list[dict[str, str]] = []
        for item in raw:
            if isinstance(item, Mapping):
                key = _text(item.get("key"))
                if key:
                    result.append(
                        {
                            "key": key,
                            "event_time": _text(item.get("event_time")),
                            "event_time_source": _text(item.get("event_time_source")),
                        }
                    )
            elif _text(item):
                result.append(
                    {"key": _text(item), "event_time": "", "event_time_source": ""}
                )
        return result[-_MAX_DEDUP_HISTORY:]

    def _remember_dedup(
        self,
        state: dict[str, Any],
        *,
        dedup_key: str,
        event_time: str,
        event_time_source: str,
    ) -> None:
        if not dedup_key:
            return
        history = [
            entry
            for entry in self._dedup_history(state)
            if entry.get("key") != dedup_key
        ]
        history.append(
            {
                "key": dedup_key,
                "event_time": _text(event_time),
                "event_time_source": _text(event_time_source),
            }
        )
        state["recent_position_dedup_keys"] = history[-_MAX_DEDUP_HISTORY:]

    @staticmethod
    def _dedup_key(event: Mapping[str, Any]) -> str:
        details = event.get("details")
        details = details if isinstance(details, Mapping) else {}
        source = _text(event.get("event_time_source"))
        payload = {
            "device_uuid": _text(event.get("device_uuid")),
            "event_type": _text(event.get("event_type")).upper(),
            "event_time": _text(event.get("event_time"))
            if source == "DEVICE_TIME"
            else "",
            "peer_ap_id": _text(details.get("peer_ap_id")),
            "peer_ap_mac": _text(details.get("peer_ap_mac")),
            "previous_peer_ap_id": _text(details.get("previous_peer_ap_id")),
            "previous_peer_ap_mac": _text(details.get("previous_peer_ap_mac")),
            "raw_text": _text(event.get("raw_text")) if source != "DEVICE_TIME" else "",
        }
        return hashlib.sha256(
            json.dumps(
                payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()


__all__ = ["PositionApplyResult", "PositionEngine"]
