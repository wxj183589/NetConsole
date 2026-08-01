from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta
from typing import Any

from netconsole.repositories.ground_unattended_repository import (
    GroundUnattendedRepository,
)


HIGH_CONFIDENCE_SECONDS = 3.0
MAX_CORRELATION_SECONDS = 10.0
FLAPPING_WINDOW_SECONDS = 60.0
FLAPPING_TRANSITION_COUNT = 3
SNMP_FLAPPING_WINDOW_SECONDS = 300.0
SNMP_FLAPPING_TRANSITION_COUNT = 3
BOUNCE_MAX_SECONDS = 5.0


class GroundRadioControlCorrelationService:
    """Project IFNET radio state and correlate it with nearby SNMP CFGMAN events."""

    def __init__(self, repository: GroundUnattendedRepository) -> None:
        self.repository = repository
        self._rebuild_seen_event_ids: set[int] | None = None

    def process(self, values: dict[str, Any]) -> dict[str, Any]:
        saved, inserted = self.repository.record_control_syslog_event(values)
        if not inserted:
            return saved
        self._project(saved)
        return saved

    def rebuild(self, *, device_uuid: str = "", run_id: str = "") -> int:
        events = self.repository.list_control_events(
            device_uuid=device_uuid, run_id=run_id
        )
        self.repository.clear_radio_projections(device_uuid=device_uuid)
        self._rebuild_seen_event_ids = set()
        try:
            for event in events:
                self._rebuild_seen_event_ids.add(int(event["id"]))
                self._project(event)
        finally:
            self._rebuild_seen_event_ids = None
        return len(events)

    def _project(self, event: dict[str, Any]) -> None:
        family = str(event.get("event_family") or "").upper()
        if family == "CFGMAN":
            self._project_cfgman(event)
        elif (
            family == "IFNET"
            and str(event.get("interface_type") or "").upper() == "RADIO"
        ):
            self._project_ifnet(event)

    def _project_cfgman(self, event: dict[str, Any]) -> None:
        device_uuid = str(event.get("device_uuid") or "")
        if not device_uuid:
            return
        command_source = str(event.get("cfg_command_source") or "").casefold()
        current = self.repository.get_mr_runtime_state(device_uuid) or {}
        current.update(
            {
                "device_uuid": device_uuid,
                "train_id": str(event.get("train_id") or ""),
                "mr_role": str(event.get("mr_role") or ""),
                "last_cfg_event_at": str(event.get("event_time") or ""),
                "last_cfg_event_index": str(
                    event.get("cfg_event_index") or ""
                ),
                "last_command_source": command_source,
                "last_config_source": str(event.get("cfg_source") or ""),
                "last_config_destination": str(
                    event.get("cfg_destination") or ""
                ),
                "last_cfg_event_id": int(event["id"]),
            }
        )
        is_expected = bool(event.get("expected_internal_change"))
        if command_source == "snmp":
            current["snmp_radio_control_state"] = "RECENT_CHANGE"
            current["last_snmp_control_at"] = str(event.get("event_time") or "")
            self.repository.add_event_once(
                dedup_key=f"cfgman-snmp:{event['id']}",
                run_id=str(event.get("run_id") or ""),
                event_type="cfgman_snmp_change",
                severity="info",
                train_id=str(event.get("train_id") or ""),
                mr_id=device_uuid,
                title="检测到 SNMP 配置变更",
                message=_cfg_message(event),
                ts=str(event.get("event_time") or event.get("receive_time") or ""),
                details=_source_details(event),
            )
        self.repository.upsert_mr_runtime_state(current)
        if command_source != "snmp" or is_expected:
            return
        for ifnet in self.repository.find_control_events(
            device_uuid=device_uuid,
            event_family="IFNET",
            event_time=str(event.get("event_time") or ""),
            window_seconds=MAX_CORRELATION_SECONDS,
        ):
            if not self._event_is_visible(ifnet):
                continue
            if str(ifnet.get("interface_type") or "").upper() != "RADIO":
                continue
            self._correlate(event, ifnet)

    def _project_ifnet(self, event: dict[str, Any]) -> None:
        device_uuid = str(event.get("device_uuid") or "")
        interface = str(event.get("interface_name") or "")
        physical_state = str(event.get("physical_state") or "").upper()
        if not device_uuid or not interface or physical_state not in {"UP", "DOWN"}:
            return
        event_time = _event_datetime(event)
        current = self.repository.get_radio_interface_state(
            device_uuid, interface
        ) or {}
        previous_state = str(current.get("stable_state") or "UNKNOWN").upper()
        if previous_state == physical_state:
            self._refresh_mr_summary(event)
            self._correlate_nearby_cfgman(event)
            return

        transition_times = _recent_times(
            current.get("transition_times") or [],
            event_time,
            SNMP_FLAPPING_WINDOW_SECONDS,
        )
        transition_times.append(event_time.isoformat(timespec="milliseconds"))
        transitions_60s = sum(
            event_time - _parse_time(value)
            <= timedelta(seconds=FLAPPING_WINDOW_SECONDS)
            for value in transition_times
            if _parse_time(value) is not None
        )
        projected_state = (
            "FLAPPING"
            if transitions_60s >= FLAPPING_TRANSITION_COUNT
            else physical_state
        )
        down_since = str(current.get("down_since") or "")
        outage_ms: int | None = None
        if physical_state == "DOWN":
            down_since = str(event.get("event_time") or "")
        elif previous_state == "DOWN":
            down_at = _parse_time(down_since)
            if down_at is not None:
                outage_ms = max(
                    0, round((event_time - down_at).total_seconds() * 1000)
                )
            down_since = ""

        values = {
            **current,
            "device_uuid": device_uuid,
            "train_id": str(event.get("train_id") or ""),
            "mr_role": str(event.get("mr_role") or ""),
            "interface_name": interface,
            "current_state": projected_state,
            "stable_state": physical_state,
            "previous_state": previous_state,
            "last_changed_at": str(event.get("event_time") or ""),
            "down_since": down_since,
            "last_up_at": (
                str(event.get("event_time") or "")
                if physical_state == "UP"
                else str(current.get("last_up_at") or "")
            ),
            "last_down_at": (
                str(event.get("event_time") or "")
                if physical_state == "DOWN"
                else str(current.get("last_down_at") or "")
            ),
            "latest_outage_duration_ms": outage_ms,
            "transition_count_5m": len(transition_times),
            "transition_times": transition_times,
            "last_event_id": int(event["id"]),
            "last_down_event_id": (
                int(event["id"])
                if physical_state == "DOWN"
                else current.get("last_down_event_id")
            ),
            "last_up_event_id": (
                int(event["id"])
                if physical_state == "UP"
                else current.get("last_up_event_id")
            ),
        }
        saved = self.repository.upsert_radio_interface_state(values)
        self._emit_interface_event(event, saved, outage_ms)
        if projected_state == "FLAPPING":
            first = transition_times[-transitions_60s]
            self.repository.add_event_once(
                dedup_key=(
                    f"radio-flapping:{device_uuid}:{interface}:{first}"
                ),
                run_id=str(event.get("run_id") or ""),
                event_type="radio_interface_flapping",
                severity="warning",
                train_id=str(event.get("train_id") or ""),
                mr_id=device_uuid,
                title="射频接口频繁切换",
                message=f"{interface} 在 60 秒内发生 {transitions_60s} 次状态转换",
                ts=str(event.get("event_time") or ""),
                details={
                    **_source_details(event),
                    "interface_name": interface,
                    "transition_count": transitions_60s,
                    "current_state": physical_state,
                    "window_started_at": first,
                },
            )
        self._refresh_mr_summary(event)
        self._correlate_nearby_cfgman(event)

    def _emit_interface_event(
        self,
        event: dict[str, Any],
        state: dict[str, Any],
        outage_ms: int | None,
    ) -> None:
        physical_state = str(event.get("physical_state") or "").upper()
        previous_state = str(state.get("previous_state") or "UNKNOWN").upper()
        interface = str(event.get("interface_name") or "")
        if physical_state == "DOWN":
            event_type = "radio_interface_down"
            title = "射频接口关闭"
            message = f"{interface} changed to down"
            severity = "warning"
        elif previous_state == "DOWN":
            is_bounce = outage_ms is not None and outage_ms <= BOUNCE_MAX_SECONDS * 1000
            event_type = (
                "radio_interface_bounce"
                if is_bounce
                else "radio_interface_recovered"
            )
            title = "射频接口短暂中断" if is_bounce else "射频接口恢复"
            message = (
                f"{interface} 已恢复，中断 {_duration_label(outage_ms)}"
                if outage_ms is not None
                else f"{interface} 已恢复"
            )
            severity = "info" if (outage_ms or 0) < 1000 else "warning"
        else:
            event_type = "radio_interface_up"
            title = "射频接口开启"
            message = f"{interface} changed to up"
            severity = "info"
        self.repository.add_event_once(
            dedup_key=f"radio-interface:{event['id']}:{event_type}",
            run_id=str(event.get("run_id") or ""),
            event_type=event_type,
            severity=severity,
            train_id=str(event.get("train_id") or ""),
            mr_id=str(event.get("device_uuid") or ""),
            title=title,
            message=message,
            ts=str(event.get("event_time") or ""),
            details={
                **_source_details(event),
                "interface_name": interface,
                "physical_state": physical_state,
                "previous_state": previous_state,
                "outage_duration_ms": outage_ms,
            },
        )

    def _correlate_nearby_cfgman(self, event: dict[str, Any]) -> None:
        device_uuid = str(event.get("device_uuid") or "")
        for cfg in self.repository.find_control_events(
            device_uuid=device_uuid,
            event_family="CFGMAN",
            event_time=str(event.get("event_time") or ""),
            window_seconds=MAX_CORRELATION_SECONDS,
        ):
            if not self._event_is_visible(cfg):
                continue
            if str(cfg.get("cfg_command_source") or "").casefold() != "snmp":
                continue
            if bool(cfg.get("expected_internal_change")):
                continue
            self._correlate(cfg, event)

    def _correlate(
        self, cfg_event: dict[str, Any], ifnet_event: dict[str, Any]
    ) -> None:
        cfg_time = _event_datetime(cfg_event)
        ifnet_time = _event_datetime(ifnet_event)
        delta_ms = round(abs((cfg_time - ifnet_time).total_seconds()) * 1000)
        if delta_ms > MAX_CORRELATION_SECONDS * 1000:
            return
        confidence = (
            "HIGH"
            if delta_ms <= HIGH_CONFIDENCE_SECONDS * 1000
            else "MEDIUM"
        )
        correlation, inserted = self.repository.insert_radio_correlation(
            {
                "correlation_id": f"radio_corr_{uuid.uuid4().hex}",
                "run_id": str(ifnet_event.get("run_id") or cfg_event.get("run_id") or ""),
                "device_uuid": str(ifnet_event.get("device_uuid") or ""),
                "train_id": str(ifnet_event.get("train_id") or ""),
                "mr_role": str(ifnet_event.get("mr_role") or ""),
                "interface_name": str(ifnet_event.get("interface_name") or ""),
                "cfg_event_id": int(cfg_event["id"]),
                "ifnet_event_id": int(ifnet_event["id"]),
                "delta_ms": delta_ms,
                "confidence": confidence,
            }
        )
        if not inserted:
            return
        device_uuid = str(ifnet_event.get("device_uuid") or "")
        interface = str(ifnet_event.get("interface_name") or "")
        state = self.repository.get_radio_interface_state(
            device_uuid, interface
        ) or {
            "device_uuid": device_uuid,
            "train_id": str(ifnet_event.get("train_id") or ""),
            "mr_role": str(ifnet_event.get("mr_role") or ""),
            "interface_name": interface,
        }
        event_ids = [
            int(value)
            for value in state.get("snmp_transition_event_ids") or []
        ]
        ifnet_id = int(ifnet_event["id"])
        snmp_times = _recent_times(
            state.get("snmp_transition_times") or [],
            ifnet_time,
            SNMP_FLAPPING_WINDOW_SECONDS,
        )
        if ifnet_id not in event_ids:
            event_ids.append(ifnet_id)
            snmp_times.append(ifnet_time.isoformat(timespec="milliseconds"))
        state.update(
            {
                "last_cfg_event_index": str(
                    cfg_event.get("cfg_event_index") or ""
                ),
                "last_command_source": "snmp",
                "correlation_confidence": confidence,
                "snmp_related_transition_count_5m": len(snmp_times),
                "snmp_transition_times": snmp_times,
                "snmp_transition_event_ids": event_ids[-100:],
            }
        )
        saved_state = self.repository.upsert_radio_interface_state(state)
        event_type, title, message, outage_ms = self._snmp_event(
            cfg_event, ifnet_event, saved_state
        )
        details = {
            **_source_details(ifnet_event),
            "correlation_id": correlation["correlation_id"],
            "correlation_confidence": confidence,
            "correlation_delta_ms": delta_ms,
            "cfg_event_id": int(cfg_event["id"]),
            "cfg_event_index": str(cfg_event.get("cfg_event_index") or ""),
            "cfgman_time": str(cfg_event.get("event_time") or ""),
            "ifnet_event_id": ifnet_id,
            "interface_name": interface,
            "physical_state": str(ifnet_event.get("physical_state") or ""),
            "outage_duration_ms": outage_ms,
            "source_event_ids": [int(cfg_event["id"]), ifnet_id],
        }
        severity = "info" if outage_ms is not None and outage_ms < 1000 else "warning"
        if event_type == "radio_snmp_up":
            severity = "info"
        self.repository.add_event_once(
            dedup_key=f"radio-snmp:{cfg_event['id']}:{ifnet_id}:{event_type}",
            run_id=str(ifnet_event.get("run_id") or ""),
            event_type=event_type,
            severity=severity,
            train_id=str(ifnet_event.get("train_id") or ""),
            mr_id=device_uuid,
            title=title,
            message=message,
            ts=str(ifnet_event.get("event_time") or ""),
            details=details,
        )
        snmp_state = (
            "RADIO_DOWN"
            if event_type == "radio_snmp_down"
            else "RADIO_RECOVERED"
        )
        if len(snmp_times) >= SNMP_FLAPPING_TRANSITION_COUNT:
            snmp_state = "FREQUENT_SWITCHING"
            self.repository.add_event_once(
                dedup_key=(
                    f"radio-snmp-flapping:{device_uuid}:{interface}:"
                    f"{snmp_times[0]}"
                ),
                run_id=str(ifnet_event.get("run_id") or ""),
                event_type="radio_snmp_flapping",
                severity="warning",
                train_id=str(ifnet_event.get("train_id") or ""),
                mr_id=device_uuid,
                title="SNMP 射频控制频繁切换",
                message=(
                    f"{interface} 在 5 分钟内出现 {len(snmp_times)} 次 "
                    "SNMP 相关状态转换"
                ),
                ts=str(ifnet_event.get("event_time") or ""),
                details=details,
            )
        runtime = self.repository.get_mr_runtime_state(device_uuid) or {}
        runtime.update(
            {
                "device_uuid": device_uuid,
                "train_id": str(ifnet_event.get("train_id") or ""),
                "mr_role": str(ifnet_event.get("mr_role") or ""),
                "snmp_radio_control_state": snmp_state,
                "last_correlation_confidence": confidence,
                "last_snmp_control_at": str(ifnet_event.get("event_time") or ""),
            }
        )
        self.repository.upsert_mr_runtime_state(runtime)
        self._refresh_mr_summary(ifnet_event)

    def _event_is_visible(self, event: dict[str, Any]) -> bool:
        return (
            self._rebuild_seen_event_ids is None
            or int(event["id"]) in self._rebuild_seen_event_ids
        )

    @staticmethod
    def _snmp_event(
        cfg_event: dict[str, Any],
        ifnet_event: dict[str, Any],
        state: dict[str, Any],
    ) -> tuple[str, str, str, int | None]:
        interface = str(ifnet_event.get("interface_name") or "")
        physical_state = str(ifnet_event.get("physical_state") or "").upper()
        outage_ms = state.get("latest_outage_duration_ms")
        previous_state = str(state.get("previous_state") or "UNKNOWN").upper()
        if physical_state == "DOWN":
            return (
                "radio_snmp_down",
                "SNMP 操作导致射频接口关闭",
                f"{interface} changed to down",
                None,
            )
        if previous_state == "DOWN" and outage_ms is not None:
            return (
                "radio_snmp_bounce",
                "SNMP 操作触发射频接口短暂重启",
                f"{interface} · DOWN → UP · 中断 {_duration_label(outage_ms)}",
                int(outage_ms),
            )
        return (
            "radio_snmp_up",
            "SNMP 操作导致射频接口开启",
            f"{interface} changed to up",
            None,
        )

    def _refresh_mr_summary(self, event: dict[str, Any]) -> None:
        device_uuid = str(event.get("device_uuid") or "")
        states = self.repository.list_radio_interface_states(
            device_uuid=device_uuid
        )
        projected = {str(row.get("current_state") or "UNKNOWN") for row in states}
        stable = {str(row.get("stable_state") or "UNKNOWN") for row in states}
        overall = (
            "FLAPPING"
            if "FLAPPING" in projected
            else "DOWN"
            if "DOWN" in stable
            else "UP"
            if "UP" in stable
            else "UNKNOWN"
        )
        runtime = self.repository.get_mr_runtime_state(device_uuid) or {}
        runtime.update(
            {
                "device_uuid": device_uuid,
                "train_id": str(event.get("train_id") or ""),
                "mr_role": str(event.get("mr_role") or ""),
                "radio_overall_state": overall,
                "last_radio_event_at": str(event.get("event_time") or ""),
            }
        )
        self.repository.upsert_mr_runtime_state(runtime)


def control_event_dedup_key(
    *,
    device_uuid: str,
    event_type: str,
    device_time: str,
    raw_text: str,
    interface_name: str = "",
    physical_state: str = "",
    cfg_event_index: str = "",
    cfg_command_source: str = "",
) -> str:
    raw_hash = hashlib.sha256(str(raw_text or "").encode("utf-8")).hexdigest()
    if str(event_type).upper() == "CFGMAN_CFGCHANGED":
        parts = (
            device_uuid,
            event_type,
            cfg_event_index,
            device_time,
            cfg_command_source.casefold(),
            raw_hash if not cfg_event_index else "",
        )
    else:
        parts = (
            device_uuid,
            event_type,
            interface_name.casefold(),
            physical_state.upper(),
            device_time,
            raw_hash,
        )
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _source_details(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "structured_event_id": int(event["id"]),
        "raw_file_id": str(event.get("raw_file_id") or ""),
        "raw_line_number": event.get("raw_line_number"),
        "device_time": str(event.get("device_time") or ""),
        "receive_time": str(event.get("receive_time") or ""),
        "event_time_source": str(event.get("event_time_source") or ""),
    }


def _cfg_message(event: dict[str, Any]) -> str:
    index = str(event.get("cfg_event_index") or "")
    source = str(event.get("cfg_source") or "")
    destination = str(event.get("cfg_destination") or "")
    parts = [f"EventIndex {index}" if index else "配置发生变化"]
    if source or destination:
        parts.append(f"{source or '未知'} → {destination or '未知'}")
    return " · ".join(parts)


def _event_datetime(event: dict[str, Any]) -> datetime:
    return (
        _parse_time(str(event.get("event_time") or ""))
        or _parse_time(str(event.get("receive_time") or ""))
        or datetime.now().astimezone()
    )


def _parse_time(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or ""))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.astimezone()


def _recent_times(
    values: list[object], now: datetime, window_seconds: float
) -> list[str]:
    result: list[str] = []
    for value in values:
        parsed = _parse_time(value)
        if parsed is not None and abs(now - parsed) <= timedelta(
            seconds=window_seconds
        ):
            result.append(parsed.isoformat(timespec="milliseconds"))
    return result


def _duration_label(value: int | None) -> str:
    milliseconds = max(0, int(value or 0))
    if milliseconds < 1000:
        return f"{milliseconds} ms"
    return f"{milliseconds / 1000:.3f} s"


__all__ = [
    "GroundRadioControlCorrelationService",
    "control_event_dedup_key",
]
