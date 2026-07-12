from __future__ import annotations

import json
import time
import traceback
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from netconsole.core import app_logger
from netconsole.repositories.mesh_mr_repository import MeshMrRepository
from netconsole.ui.mesh_chart_payload import build_chart_payload


class MeshPeerSeriesWorker(QThread):
    loaded = Signal(object)
    loaded_initial = Signal(object)
    loaded_full = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        db_path: Path,
        peer_mac: str,
        radio: int | None = None,
        session_id: str | None = None,
        parent=None,
        anchor_link_id: int | None = None,
        source_file_id: int | str | None = None,
        active_only: bool = False,
    ) -> None:
        super().__init__(parent)
        self.db_path = db_path
        self.peer_mac = peer_mac
        self.radio = radio
        self.session_id = session_id or None
        self.anchor_link_id = anchor_link_id
        self.source_file_id = source_file_id
        self.active_only = active_only

    def run(self) -> None:
        app_logger.log_info(
            "MESH_CHART_WORKER_START",
            (
                f"db_path={self.db_path}, peer_mac={self.peer_mac}, radio={self.radio}, "
                f"session_id={self.session_id or ''}, anchor_link_id={self.anchor_link_id}, "
                f"source_file_id={self.source_file_id}, active_only={self.active_only}"
            ),
        )
        try:
            repo = MeshMrRepository(self.db_path)
            if self.active_only:
                query_started = time.perf_counter()
                segments = repo.query_active_link_chart_segments(self.source_file_id, self.radio)
                query_elapsed = time.perf_counter() - query_started
                peer_segment = _decode_segment(segments.get("peer_segment", {}))
                run_segment = _decode_segment(segments.get("run_segment", {}))
                payload_started = time.perf_counter()
                chart_payload = build_chart_payload(peer_segment, run_segment)
                payload_elapsed = time.perf_counter() - payload_started
                metadata = chart_payload.get("metadata", {})
                app_logger.log_info(
                    "MESH_FULL_ACTIVE_CHART_PAYLOAD",
                    (
                        f"source_file_id={self.source_file_id or 'ALL'}, radio={self.radio if self.radio is not None else 'ALL'}, "
                        f"query_active_count={metadata.get('query_active_count')}, raw_count={metadata.get('sample_count')}, "
                        f"rendered_count=deferred, full_payload={metadata.get('full_active_payload')}, "
                        f"pagination=False, source=MeshMrRepository.query_active_link_chart_segments, "
                        f"query_ms={query_elapsed * 1000:.1f}, payload_ms={payload_elapsed * 1000:.1f}"
                    ),
                )
                self.loaded.emit({"kind": "full_active", "peer_segment": {key: value for key, value in peer_segment.items() if key != "rows"}, "chart_payload": chart_payload})
                return
            if self.anchor_link_id is None:
                rows = repo.query_peer_series(self.peer_mac, self.radio, self.session_id, source_file_id=self.source_file_id)
                self.loaded.emit([_decode_row(row) for row in rows])
                return
            if self.source_file_id in (None, ""):
                app_logger.log_warning("MESH_CHART_EMPTY_PAYLOAD", f"reason=missing_source_file_id, anchor_link_id={self.anchor_link_id}, peer_mac={self.peer_mac}")
                self.loaded_initial.emit(_empty_payload("当前单 AP 图表缺少源文件ID，无法定位单日志数据。"))
                return
            if hasattr(repo, "query_peer_chart_initial_segments"):
                initial_started = time.perf_counter()
                initial_segments = _call_with_optional_source(repo.query_peer_chart_initial_segments, self.anchor_link_id, self.source_file_id)
                initial_query_elapsed = time.perf_counter() - initial_started
                initial_peer_segment = _decode_segment(initial_segments.get("peer_segment", {}))
                initial_run_segment = _decode_segment(initial_segments.get("run_segment", {}))
                initial_payload_started = time.perf_counter()
                initial_chart_payload = build_chart_payload(initial_peer_segment, initial_run_segment)
                initial_payload_elapsed = time.perf_counter() - initial_payload_started
                self.loaded_initial.emit(
                    {
                        "kind": "initial",
                        "message": initial_segments.get("message") or initial_run_segment.get("message") or "",
                        "peer_segment": {key: value for key, value in initial_peer_segment.items() if key != "rows"},
                        "chart_payload": initial_chart_payload,
                    }
                )
                app_logger.log_info(
                    "MESH_CHART_INITIAL_PAYLOAD_BUILT",
                    f"anchor_link_id={self.anchor_link_id}, rows={len(initial_run_segment.get('rows', []))}, query_ms={initial_query_elapsed * 1000:.1f}, payload_ms={initial_payload_elapsed * 1000:.1f}",
                )
            if self.isInterruptionRequested():
                return
            query_started = time.perf_counter()
            segments = _call_with_optional_source(repo.query_peer_chart_segments, self.anchor_link_id, self.source_file_id)
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
            payload = {
                "kind": "full",
                "message": segments.get("message") or run_segment.get("message") or "",
                "peer_segment": {key: value for key, value in peer_segment.items() if key != "rows"},
                "chart_payload": chart_payload,
            }
            self.loaded_full.emit(payload)
        except Exception as exc:
            detail = traceback.format_exc()
            app_logger.log_error(
                "MESH_CHART_WORKER_FAILED",
                (
                    f"peer_mac={self.peer_mac}, radio={self.radio}, anchor_link_id={self.anchor_link_id}, "
                    f"source_file_id={self.source_file_id}, error={exc}, traceback={detail}"
                ),
            )
            self.failed.emit(f"{exc}\n{detail}")
        finally:
            app_logger.log_info(
                "MESH_CHART_WORKER_FINISHED",
                f"peer_mac={self.peer_mac}, radio={self.radio}, anchor_link_id={self.anchor_link_id}, source_file_id={self.source_file_id}",
            )


def _decode_row(row: dict[str, object]) -> dict[str, object]:
    decoded = dict(row)
    metrics = _json_dict(row.get("metrics_json"))
    if metrics:
        decoded["metrics"] = metrics
    elif not isinstance(decoded.get("metrics"), dict):
        decoded.pop("metrics", None)
    decoded["deltas"] = {}
    return decoded


def _empty_payload(message: str) -> dict[str, object]:
    return {
        "kind": "empty",
        "message": message,
        "peer_segment": {},
        "chart_payload": build_chart_payload(
            {"anchor": None, "rows": []},
            {"anchor": None, "rows": [], "events": [], "message": message},
        ),
    }


def _call_with_optional_source(method, anchor_link_id: int, source_file_id: int | str | None) -> dict[str, object]:
    if source_file_id in (None, ""):
        return method(anchor_link_id)
    try:
        return method(anchor_link_id, source_file_id=source_file_id)
    except TypeError:
        return method(anchor_link_id)


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
