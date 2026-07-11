from __future__ import annotations

from collections.abc import Iterable

from netconsole.services.online_mr.core.event_model import OnlineMrEvent
from netconsole.services.online_mr.core.realtime_cache import OnlineMrParsedEvent, OnlineMrRawEvent
from netconsole.services.online_mr.parser.event_parser_engine import EventParserEngine


class OnlineMrRealtimeParser:
    def __init__(self) -> None:
        self._parser = EventParserEngine()
        self._interface_direction_by_session: dict[str, str] = {}

    def parse_raw_event(self, event: OnlineMrEvent | OnlineMrRawEvent) -> OnlineMrParsedEvent | None:
        original_raw = event.raw
        parsed_event = self._coerce_event(event)
        payload = self._parse_payload(parsed_event)
        if payload is None:
            return None
        return OnlineMrParsedEvent(
            timestamp=parsed_event.timestamp,
            session_id=parsed_event.session_id,
            device_id=parsed_event.device_id,
            module=parsed_event.module,
            payload=payload,
            raw=original_raw,
        )

    def parse_events(self, events: Iterable[OnlineMrEvent | OnlineMrRawEvent]) -> list[OnlineMrParsedEvent]:
        parsed: list[OnlineMrParsedEvent] = []
        for event in events:
            sample = self.parse_raw_event(event)
            if sample is not None:
                parsed.append(sample)
        return parsed

    def _parse_payload(self, event: OnlineMrEvent) -> dict[str, object] | None:
        if event.module == "mesh":
            payload = self._parser.parse_mesh_line_stream(event)
            if not any(payload.get(key) not in (None, "") for key in ("peer_mac", "peer_name", "mr_rssi", "link_state")):
                return None
            return payload
        if event.module == "busy":
            payload = self._parser.parse_busy(event)
            if not any(payload.get(key) is not None for key in ("channel_busy_total", "ctl_busy", "tx_busy", "rx_busy")):
                return None
            return payload
        if event.module == "stats":
            payload = self._parser.parse_stats(event)
            counters = payload.get("counters")
            has_busy = any(payload.get(key) is not None for key in ("channel_busy_total", "ctl_busy", "tx_busy", "rx_busy"))
            if (not isinstance(counters, dict) or not counters) and not has_busy:
                return None
            return payload
        if event.module == "interface_rate":
            raw = str(event.raw or "")
            lowered = raw.lower()
            if "inbound interface" in lowered:
                self._interface_direction_by_session[event.session_id] = "inbound"
                return None
            if "outbound interface" in lowered:
                self._interface_direction_by_session[event.session_id] = "outbound"
                return None
            direction = self._interface_direction_by_session.get(event.session_id)
            if not direction:
                return None
            direction_header = "Inbound interface" if direction == "inbound" else "Outbound interface"
            enriched = OnlineMrEvent(
                timestamp=event.timestamp,
                session_id=event.session_id,
                device_id=event.device_id,
                source=event.source,
                module=event.module,
                event_type=event.event_type,
                payload=event.payload,
                raw=f"{direction_header}\n{raw}",
            )
            payload = self._parser.parse_interface_rate(enriched)
            rows = payload.get("rows")
            if not isinstance(rows, list) or not rows:
                return None
            latest = rows[-1]
            if isinstance(latest, dict):
                payload.update(latest)
            return payload
        return None

    @staticmethod
    def _coerce_event(event: OnlineMrEvent | OnlineMrRawEvent) -> OnlineMrEvent:
        if isinstance(event, OnlineMrEvent):
            parser_line = event.payload.get("line")
            if parser_line is None or str(parser_line) == str(event.raw or ""):
                return event
            return OnlineMrEvent(
                timestamp=event.timestamp,
                session_id=event.session_id,
                device_id=event.device_id,
                source=event.source,
                module=event.module,
                event_type=event.event_type,
                payload=event.payload,
                raw=str(parser_line),
            )
        task_type = str(event.task_type or "")
        module = {
            "mesh_link": "mesh",
            "channel_busy": "busy",
            "ap_radio_statistics": "stats",
            "interface_rate": "interface_rate",
        }.get(task_type, task_type)
        return OnlineMrEvent(
            timestamp=event.timestamp,
            session_id=event.session_id,
            device_id=event.device_id,
            source=event.source,
            module=module,
            event_type=task_type,
            payload={"task_type": task_type, "line": event.raw},
            raw=event.raw,
        )
