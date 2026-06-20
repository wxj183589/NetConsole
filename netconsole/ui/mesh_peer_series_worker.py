from __future__ import annotations

import json
import time
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from netconsole.core import app_logger
from netconsole.repositories.mesh_mr_repository import MeshMrRepository
from netconsole.ui.mesh_chart_payload import build_chart_payload


class MeshPeerSeriesWorker(QThread):
    loaded = Signal(object)
    failed = Signal(str)

    def __init__(self, db_path: Path, peer_mac: str, radio: int | None = None, session_id: str | None = None, parent=None, anchor_link_id: int | None = None) -> None:
        super().__init__(parent)
        self.db_path = db_path
        self.peer_mac = peer_mac
        self.radio = radio
        self.session_id = session_id or None
        self.anchor_link_id = anchor_link_id

    def run(self) -> None:
        try:
            repo = MeshMrRepository(self.db_path)
            if self.anchor_link_id is None:
                rows = repo.query_peer_series(self.peer_mac, self.radio, self.session_id)
                self.loaded.emit([_decode_row(row) for row in rows])
                return
            query_started = time.perf_counter()
            segments = repo.query_peer_chart_segments(self.anchor_link_id)
            query_elapsed = time.perf_counter() - query_started
            peer_segment = _decode_segment(segments.get("peer_segment", {}))
            run_segment = _decode_segment(segments.get("run_segment", {}))
            app_logger.log_info(
                "MESH_CHART_QUERY_COMPLETE",
                f"anchor_link_id={self.anchor_link_id}, segment_start={run_segment.get('segment_start')}, segment_end={run_segment.get('segment_end')}, rows={len(run_segment.get('rows', []))}, elapsed_ms={query_elapsed * 1000:.1f}",
            )
            payload_started = time.perf_counter()
            chart_payload = build_chart_payload(peer_segment, run_segment)
            payload_elapsed = time.perf_counter() - payload_started
            app_logger.log_info(
                "MESH_CHART_PAYLOAD_BUILT",
                f"anchor_link_id={self.anchor_link_id}, raw_samples={chart_payload['metadata']['sample_count']}, peer_samples={chart_payload['metadata']['peer_sample_count']}, elapsed_ms={payload_elapsed * 1000:.1f}, backend={chart_payload['metadata']['backend']}",
            )
            self.loaded.emit({"peer_segment": {key: value for key, value in peer_segment.items() if key != "rows"}, "chart_payload": chart_payload})
        except Exception as exc:
            self.failed.emit(str(exc))


def _decode_row(row: dict[str, object]) -> dict[str, object]:
    decoded = dict(row)
    decoded["metrics"] = _json_dict(row.get("metrics_json"))
    decoded["deltas"] = _json_dict(row.get("deltas_json"))
    return decoded


def _decode_segment(segment: dict[str, object]) -> dict[str, object]:
    decoded = dict(segment)
    decoded["rows"] = [_decode_row(row) for row in segment.get("rows", []) if isinstance(row, dict)]
    if isinstance(segment.get("anchor"), dict):
        decoded["anchor"] = _decode_row(segment["anchor"])
    return decoded


def _json_dict(value: object) -> dict[str, object]:
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
