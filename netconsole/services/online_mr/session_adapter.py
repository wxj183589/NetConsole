from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Iterable

from netconsole.core.ping.fping_v5_parser import parse_fping_v5_json_line
from netconsole.services.network_tools.iperf_parser import parse_iperf_lines, read_iperf_text
from netconsole.services.online_mr.core.event_model import (
    EVENT_BUSY_SAMPLE,
    EVENT_FPING_V5_SAMPLE,
    EVENT_INTERFACE_SAMPLE,
    EVENT_IPERF3_SAMPLE,
    EVENT_MESH_SAMPLE,
    EVENT_STATS_SAMPLE,
    OnlineMrEvent,
)
from netconsole.services.rail_transit.online_mr_diagnosis_parser import OnlineMrRawBlockSplitter


class SessionAdapter:
    def __init__(self, session_dir: Path, session_id: str = "", device_id: int | None = None) -> None:
        self.session_dir = Path(session_dir)
        self.raw_dir = self.session_dir / "raw"
        self.session_id = session_id or self.session_dir.name
        self.device_id = device_id

    def iter_events(self) -> Iterable[OnlineMrEvent]:
        yield from self._iter_ssh_raw_events("mesh_link_raw.log", "mesh", EVENT_MESH_SAMPLE)
        yield from self._iter_ssh_raw_events("channel_busy_raw.log", "busy", EVENT_BUSY_SAMPLE)
        yield from self._iter_ssh_raw_events("ap_radio_statistics_raw.log", "stats", EVENT_STATS_SAMPLE)
        yield from self._iter_ssh_raw_events("interface_rate_raw.log", "interface_rate", EVENT_INTERFACE_SAMPLE)
        yield from self._iter_fping_v5_events()
        yield from self._iter_iperf3_events()

    def _iter_ssh_raw_events(self, filename: str, module: str, event_type: str) -> Iterable[OnlineMrEvent]:
        path = self.raw_dir / filename
        if not path.exists():
            return
        splitter = OnlineMrRawBlockSplitter()
        for block in splitter.split(path):
            yield OnlineMrEvent(
                timestamp=block.collected_at,
                session_id=self.session_id,
                device_id=self.device_id,
                source="ssh",
                module=module,
                event_type=event_type,
                payload={"command": block.command, "raw_file": filename, "offset_start": block.offset_start, "offset_end": block.offset_end},
                raw=block.text,
            )

    def _iter_fping_v5_events(self) -> Iterable[OnlineMrEvent]:
        path = self.raw_dir / "fping_v5_samples.jsonl"
        if not path.exists():
            return
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            ts = str(payload.get("ts") or datetime.now().isoformat(timespec="milliseconds"))
            sample = parse_fping_v5_json_line(json.dumps(payload.get("raw") or payload, ensure_ascii=False), ts, int(payload.get("timeout_ms") or 100))
            event_payload = payload
            if sample is not None:
                event_payload = sample.as_dict()
            yield OnlineMrEvent(
                timestamp=datetime.fromisoformat(ts),
                session_id=self.session_id,
                device_id=self.device_id,
                source="fping_v5",
                module="fping",
                event_type=EVENT_FPING_V5_SAMPLE,
                payload=event_payload,
                raw=line,
            )

    def _iter_iperf3_events(self) -> Iterable[OnlineMrEvent]:
        for filename in ("iperf3.json", "iperf_client_raw.json", "iperf_client_raw.log"):
            path = self.raw_dir / filename
            if not path.exists():
                continue
            text = read_iperf_text(path)
            if path.suffix.lower() == ".json":
                try:
                    payload = json.loads(text or "{}")
                except json.JSONDecodeError:
                    continue
                yield OnlineMrEvent(
                    timestamp=datetime.now(),
                    session_id=self.session_id,
                    device_id=self.device_id,
                    source="iperf3",
                    module="iperf",
                    event_type=EVENT_IPERF3_SAMPLE,
                    payload=payload if isinstance(payload, dict) else {"value": payload},
                    raw=text,
                )
                continue
            for row in parse_iperf_lines(text.splitlines()):
                yield OnlineMrEvent(
                    timestamp=datetime.now(),
                    session_id=self.session_id,
                    device_id=self.device_id,
                    source="iperf3",
                    module="iperf",
                    event_type=EVENT_IPERF3_SAMPLE,
                    payload=row,
                    raw=str(row.get("raw_line") or ""),
                )
