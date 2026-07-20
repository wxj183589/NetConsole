from __future__ import annotations

import json
import logging
import re
import sqlite3
from collections import defaultdict
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from netconsole.core.paths import PathResolver
from netconsole.models.api.online_mr import (
    OnlineMrArtifactDTO,
    OnlineMrCollectorStatusDTO,
    OnlineMrDatabaseSummaryDTO,
    OnlineMrDataIntegrity,
    OnlineMrDownsampleMode,
    OnlineMrLogChunkDTO,
    OnlineMrLogLineDTO,
    OnlineMrManualNoteDTO,
    OnlineMrMetricPointDTO,
    OnlineMrMetricPageDTO,
    OnlineMrMetricSeriesDTO,
    OnlineMrMetricSummaryDTO,
    OnlineMrMetricType,
    OnlineMrParsedStatus,
    OnlineMrRawFileDTO,
    OnlineMrRawTailDTO,
    OnlineMrRealtimePreviewDTO,
    OnlineMrSessionDetailDTO,
    OnlineMrSessionSummaryDTO,
    OnlineMrSwitchRssiPageDTO,
    OnlineMrSwitchRssiSource,
    OnlineMrSwitchRssiWindowDTO,
    OnlineMrTimelineEventDTO,
)
from netconsole.services.online_mr.collection_paths import OnlineMrCollectionPaths
from netconsole.services.online_mr.errors import OnlineMrQueryError, OnlineMrQueryErrorCode
from netconsole.services.online_mr_session_store import OnlineMrSessionStore
from netconsole.services.rail_transit.online_mr_diagnosis_parser import PARSER_VERSION


LOGGER = logging.getLogger(__name__)
MAX_QUERY_LIMIT = 10_000
MAX_LOG_LIMIT = 1_000
MAX_LOG_LINE_BYTES = 1024 * 1024
MAX_WEB_TAIL_LIMIT = 500
MAX_WEB_TAIL_BYTES = 4 * 1024 * 1024
_TIMESTAMP_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?)")
_LEVEL_RE = re.compile(r"\[(DEBUG|INFO|WARNING|ERROR|CRITICAL)\]", re.IGNORECASE)

_PARSED_CAPABILITY_TABLES = {
    "mesh_link": frozenset({"main_link_samples"}),
    "channel_busy": frozenset({"channel_busy_records"}),
    "radio_statistics": frozenset({"radio_statistics_samples"}),
    "interface_rate": frozenset({"interface_rate_samples"}),
    "switch_history": frozenset({"switch_history_events"}),
    "switch_realtime": frozenset({"switch_realtime_events"}),
    "fping_rtt": frozenset({"fping_samples"}),
    "fping_loss": frozenset({"fping_1s_summary"}),
    "iperf": frozenset({"iperf_runs", "iperf_intervals"}),
    "timeline": frozenset({"analysis_events"}),
}
_CURRENT_PARSED_TABLES = frozenset().union(
    *_PARSED_CAPABILITY_TABLES.values(),
    {"online_parse_metadata", "online_parse_issues", "time_sync_samples", "active_segments", "active_segment_metrics"},
)


class OnlineMrQueryService:
    """Online MR 会话文件与解析库的纯 Python 只读边界。"""

    _LOG_SOURCES = {
        "init": "raw/init_raw.log",
        "config_collect": "raw/config_collect_raw.log",
        "terminal_monitor": "raw/terminal_monitor_raw.log",
        "mesh_link": "raw/mesh_link_raw.log",
        "ap_radio_statistics": "raw/ap_radio_statistics_raw.log",
        "channel_busy": "raw/channel_busy_raw.log",
        "switch_history": "raw/switch_history_latest.log",
        "wireless_status": "raw/wireless_status_raw.log",
        "interface_rate": "raw/interface_rate_raw.log",
        "collector_output": "raw/collector_output_raw.log",
        "reconnect": "raw/reconnect.log",
        "fping": "raw/fping_v5_raw.log",
        "iperf_client": "raw/iperf_client_raw.log",
        "collector": "logs/collector.log",
    }
    _WEB_RAW_SOURCES = {
        "mesh_link": "raw/mesh_link_raw.log",
        "channel_busy": "raw/channel_busy_raw.log",
        "fping_samples": "raw/fping_v5_samples.jsonl",
        "fping_summary": "raw/fping_v5_final_summary.json",
        "fping_raw": "raw/fping_v5_raw.log",
        "iperf_client": "raw/iperf_client_raw.log",
        "switch_history": "raw/switch_history_latest.log",
        "collector_output": "raw/collector_output_raw.log",
        "wireless_status": "raw/wireless_status_raw.log",
    }
    _COLLECTORS = {
        "init": ("初始化", "raw/init_raw.log"),
        "terminal_monitor": ("终端实时日志", "raw/terminal_monitor_raw.log"),
        "mesh_link": ("主链路信息", "raw/mesh_link_raw.log"),
        "channel_busy": ("信道繁忙度", "raw/channel_busy_raw.log"),
        "ap_radio_statistics": ("AP 射频统计", "raw/ap_radio_statistics_raw.log"),
        "wireless_status": ("无线状态", "raw/wireless_status_raw.log"),
        "interface_rate": ("接口速率", "raw/interface_rate_raw.log"),
        "switch_history": ("主链路切换历史", "raw/switch_history_latest.log"),
        "fping_v5": ("高频 Ping", "raw/fping_v5_raw.log"),
        "iperf_client": ("iPerf Client", "raw/iperf_client_raw.log"),
    }
    _ACTIVE_WEB_STATES = {"CREATED", "CONNECTING", "INITIALIZING", "COLLECTING", "RECONNECTING", "RUNNING", "STOPPING"}

    def __init__(self, paths: PathResolver, store: OnlineMrSessionStore | None = None) -> None:
        self.paths = paths
        self.store = store or OnlineMrSessionStore(paths)

    def list_sessions(
        self,
        site_id: str,
        *,
        mr_name: str | None = None,
        status: str | None = None,
        created_after: str | datetime | None = None,
        created_before: str | datetime | None = None,
        has_package: bool | None = None,
        limit: int = 100,
        offset: int = 0,
        sort: str = "started_desc",
    ) -> list[OnlineMrSessionSummaryDTO]:
        self._validate_site_id(site_id)
        limit, offset = self._pagination(limit, offset)
        after = self._as_datetime(created_after)
        before = self._as_datetime(created_before)
        rows: list[OnlineMrSessionSummaryDTO] = []
        for session_dir in self.store.list_session_dirs(site_id):
            meta = self._read_metadata(session_dir, tolerate_errors=True)
            if meta is None:
                continue
            row = self._summary(site_id, session_dir, meta)
            started = self._as_datetime(row.started_at)
            if mr_name and row.mr_name != mr_name:
                continue
            if status and row.status != status:
                continue
            if after and (started is None or started < after):
                continue
            if before and (started is None or started > before):
                continue
            if has_package is not None and row.has_package is not has_package:
                continue
            rows.append(row)
        reverse = sort != "started_asc"
        rows.sort(key=lambda row: (row.started_at or "", row.session_id), reverse=reverse)
        return rows[offset : offset + limit]

    def get_session(self, site_id: str, session_id: str) -> OnlineMrSessionDetailDTO:
        session_dir = self._find_session(site_id, session_id)
        meta = self._read_metadata(session_dir)
        assert meta is not None
        summary = self._summary(site_id, session_dir, meta)
        artifacts = self.list_artifacts(site_id, session_id)
        database = self.get_database_summary(site_id, session_id)
        raw_count = sum(1 for item in artifacts if item.kind == "raw")
        integrity = self._data_integrity(meta, summary)
        return OnlineMrSessionDetailDTO(
            **summary.model_dump(),
            session_path_reference=session_dir.relative_to(self.paths.online_mr_root(site_id)).as_posix(),
            connection_summary={
                key: meta.get(key)
                for key in ("host", "protocol", "port", "connection_method")
                if meta.get(key) not in (None, "")
            },
            collection_config={
                "intervals": meta.get("intervals") or {},
                "radio": meta.get("radio") or {},
                "duration_minutes": meta.get("configured_duration_minutes"),
                "session_type": meta.get("session_type"),
                "config_collect_enabled": meta.get("config_collect_enabled"),
                "config_collect_status": meta.get("config_collect_status"),
            },
            enabled_collectors=self._enabled_collectors(meta),
            traffic_summary=dict(
                meta.get("traffic_summary")
                or {"fping": meta.get("fping") or {}, "iperf": meta.get("iperf") or {}}
            ),
            file_summary={"artifact_count": len(artifacts), "raw_file_count": raw_count},
            database_summary=database,
            notes_count=self._count_notes(session_dir),
            latest_metric_time=self._latest_metric_time(session_dir),
            data_integrity=integrity,
        )

    def get_current_session(self, site_id: str) -> OnlineMrSessionDetailDTO | None:
        for row in self.list_sessions(site_id, limit=100):
            if row.status.upper() in self._ACTIVE_WEB_STATES:
                return self.get_session(site_id, row.session_id)
        return None

    def list_collectors(self, site_id: str, session_id: str) -> list[OnlineMrCollectorStatusDTO]:
        session_dir = self._find_session(site_id, session_id)
        meta = self._read_metadata(session_dir)
        assert meta is not None
        active = str(meta.get("status") or "").upper() in self._ACTIVE_WEB_STATES
        view = self._read_view_json(session_dir, "live_mr_status.json")
        view_collectors = view.get("collectors") if isinstance(view.get("collectors"), dict) else {}
        enabled = set(self._enabled_collectors(meta))
        enabled.update({"init", "terminal_monitor"})
        if "fping" in enabled:
            enabled.add("fping_v5")
        if "iperf" in enabled:
            enabled.add("iperf_client")
        rows: list[OnlineMrCollectorStatusDTO] = []
        for name, (label, relative_name) in self._COLLECTORS.items():
            item = view_collectors.get(name) if isinstance(view_collectors.get(name), dict) else {}
            path = self._safe_session_file(session_dir, str(item.get("raw_file") or relative_name))
            exists = bool(path and path.is_file() and not path.is_symlink())
            size = path.stat().st_size if exists and path else 0
            status = str(item.get("status") or "").lower()
            is_enabled = name in enabled or (bool(item) and status != "disabled")
            if not is_enabled:
                status = "disabled"
            elif not active and status in {"running", "starting", "stopping", ""}:
                status = "stopped" if exists else "missing"
            elif not status:
                status = "running" if active and size else "starting" if active else "stopped" if exists else "missing"
            rows.append(
                OnlineMrCollectorStatusDTO(
                    name=name,
                    label=str(item.get("label") or label),
                    status=status,
                    enabled=is_enabled,
                    raw_file=relative_name,
                    exists=exists,
                    size_bytes=size,
                    error=str(item.get("error") or ""),
                    started_at=self._text_or_none(item.get("started_at")),
                    ended_at=self._text_or_none(item.get("ended_at")),
                    updated_at=self._text_or_none(item.get("updated_at")) or self._text_or_none(view.get("updated_at")),
                )
            )
        return rows

    def get_realtime_preview(self, site_id: str, session_id: str) -> OnlineMrRealtimePreviewDTO:
        session_dir = self._find_session(site_id, session_id)
        meta = self._read_metadata(session_dir)
        assert meta is not None
        mr_view = self._read_view_json(session_dir, "live_mr_status.json")
        link = self._read_view_json(session_dir, "live_link_status.json")
        fping = self._read_view_json(session_dir, "live_fping_status.json")
        iperf = self._read_view_json(session_dir, "live_iperf_status.json")
        if str(meta.get("status") or "").upper() not in self._ACTIVE_WEB_STATES:
            for item in (fping, iperf):
                if str(item.get("status") or "").lower() in {"running", "starting", "stopping"}:
                    item["status"] = "stopped"
        timestamps = [
            str(item.get("updated_at"))
            for item in (mr_view, link, fping, iperf)
            if item.get("updated_at")
        ]
        display_context = link.get("display_context") or mr_view.get("display_context") or {}
        available = any(bool(item) for item in (link, fping, iperf))
        message = str(link.get("message") or ("实时预览已更新" if available else "暂无实时链路数据"))
        return OnlineMrRealtimePreviewDTO(
            session_id=session_id,
            available=available,
            updated_at=max(timestamps) if timestamps else None,
            message=message,
            display_context=display_context if isinstance(display_context, dict) else {},
            link=link,
            fping=fping,
            iperf=iperf,
        )

    def read_raw_tail(self, site_id: str, session_id: str, name: str, *, tail: int = 200) -> OnlineMrRawTailDTO:
        if name not in self._WEB_RAW_SOURCES:
            raise OnlineMrQueryError(OnlineMrQueryErrorCode.LOG_SOURCE_INVALID, "不支持的原始日志来源")
        if tail < 1 or tail > MAX_WEB_TAIL_LIMIT:
            raise OnlineMrQueryError(OnlineMrQueryErrorCode.QUERY_LIMIT_EXCEEDED, f"日志行数必须在 1 到 {MAX_WEB_TAIL_LIMIT} 之间")
        session_dir = self._find_session(site_id, session_id)
        path = self._safe_session_file(session_dir, self._WEB_RAW_SOURCES[name])
        if path is None or not path.is_file() or path.is_symlink():
            return OnlineMrRawTailDTO(name=name, message="文件不存在或尚未生成")
        stat = path.stat()
        if stat.st_size == 0:
            return OnlineMrRawTailDTO(name=name, message="文件不存在或尚未生成")
        lines: list[str] = []
        consumed = 0
        with path.open("rb") as handle:
            handle.seek(self._tail_cursor(path, tail))
            for _ in range(tail):
                raw = handle.readline(MAX_LOG_LINE_BYTES)
                if not raw:
                    break
                consumed += len(raw)
                if consumed > MAX_WEB_TAIL_BYTES:
                    break
                lines.append(raw.decode("utf-8", errors="replace").rstrip("\r\n"))
        summary: dict[str, Any] = {}
        if name == "fping_summary" and lines:
            try:
                parsed = json.loads("\n".join(lines))
                summary = parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                summary = {}
        return OnlineMrRawTailDTO(
            name=name,
            exists=True,
            lines=lines,
            message="" if lines else "文件存在但暂无内容",
            size_bytes=stat.st_size,
            modified_at=datetime.fromtimestamp(stat.st_mtime).isoformat(sep=" ", timespec="seconds"),
            summary=summary,
        )

    def get_raw_summary(self, site_id: str, session_id: str) -> list[OnlineMrRawFileDTO]:
        session_dir = self._find_session(site_id, session_id)
        rows: list[OnlineMrRawFileDTO] = []
        for name, relative_name in self._WEB_RAW_SOURCES.items():
            path = self._safe_session_file(session_dir, relative_name)
            exists = bool(path and path.is_file() and not path.is_symlink())
            stat = path.stat() if exists and path else None
            rows.append(
                OnlineMrRawFileDTO(
                    name=name,
                    relative_name=relative_name,
                    exists=exists,
                    size_bytes=stat.st_size if stat else 0,
                    modified_at=datetime.fromtimestamp(stat.st_mtime).isoformat(sep=" ", timespec="seconds") if stat else None,
                )
            )
        return rows

    def list_artifacts(self, site_id: str, session_id: str) -> list[OnlineMrArtifactDTO]:
        session_dir = self._find_session(site_id, session_id)
        candidates: list[tuple[Path, str, bool, bool]] = [
            (session_dir / "session_meta.json", "metadata", True, False),
            (session_dir / "manual_notes.jsonl", "note", True, False),
            (session_dir / "manual_notes.txt", "note", True, True),
        ]
        for directory, kind, fact, rebuildable in (
            (session_dir / "raw", "raw", True, False),
            (session_dir / "logs", "log", True, False),
            (session_dir / "outputs", "output", False, True),
        ):
            if directory.is_dir():
                candidates.extend((path, kind, fact, rebuildable) for path in directory.iterdir())
        candidates.append((session_dir / "parsed" / "online_diagnosis.sqlite", "parsed", False, True))
        rows: list[OnlineMrArtifactDTO] = []
        root = session_dir.resolve()
        for path, kind, fact, rebuildable in candidates:
            if not path.is_file() or path.is_symlink() or self._is_temporary(path):
                continue
            try:
                resolved = path.resolve(strict=True)
                resolved.relative_to(root)
            except (OSError, ValueError):
                continue
            stat = resolved.stat()
            relative = resolved.relative_to(root).as_posix()
            rows.append(
                OnlineMrArtifactDTO(
                    name=resolved.name,
                    kind=kind,
                    relative_name=relative,
                    size_bytes=stat.st_size,
                    modified_at=datetime.fromtimestamp(stat.st_mtime).isoformat(sep=" ", timespec="seconds"),
                    is_fact_source=fact,
                    is_rebuildable=rebuildable,
                )
            )
        return sorted(rows, key=lambda item: (item.kind, item.relative_name))

    def read_log_chunk(
        self,
        site_id: str,
        session_id: str,
        source: str,
        *,
        cursor: int = 0,
        limit: int = 200,
        tail: bool = False,
    ) -> OnlineMrLogChunkDTO:
        if source not in self._LOG_SOURCES:
            raise OnlineMrQueryError(OnlineMrQueryErrorCode.LOG_SOURCE_INVALID, "不支持的日志来源")
        if cursor < 0:
            raise OnlineMrQueryError(OnlineMrQueryErrorCode.LOG_CURSOR_INVALID, "日志游标不能小于 0")
        if limit < 1 or limit > MAX_LOG_LIMIT:
            raise OnlineMrQueryError(OnlineMrQueryErrorCode.QUERY_LIMIT_EXCEEDED, f"日志行数必须在 1 到 {MAX_LOG_LIMIT} 之间")
        session_dir = self._find_session(site_id, session_id)
        path = session_dir / self._LOG_SOURCES[source]
        if not path.is_file() or path.is_symlink():
            raise OnlineMrQueryError(OnlineMrQueryErrorCode.ARTIFACT_NOT_FOUND, "日志文件不存在")
        size = path.stat().st_size
        start = self._tail_cursor(path, limit) if tail else cursor
        if start > size:
            raise OnlineMrQueryError(OnlineMrQueryErrorCode.LOG_CURSOR_INVALID, "日志游标超过文件末尾")
        lines: list[OnlineMrLogLineDTO] = []
        with path.open("rb") as handle:
            handle.seek(start)
            for _ in range(limit):
                sequence = handle.tell()
                raw = handle.readline(MAX_LOG_LINE_BYTES)
                if not raw:
                    break
                text = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                match = _TIMESTAMP_RE.match(text)
                level = _LEVEL_RE.search(text)
                lines.append(
                    OnlineMrLogLineDTO(
                        sequence=sequence,
                        timestamp=match.group(1) if match else None,
                        source=source,
                        text=text,
                        level=level.group(1).upper() if level else None,
                    )
                )
            next_cursor = handle.tell()
        return OnlineMrLogChunkDTO(source=source, cursor=start, next_cursor=next_cursor, has_more=next_cursor < path.stat().st_size, lines=lines)

    def get_database_summary(self, site_id: str, session_id: str) -> OnlineMrDatabaseSummaryDTO:
        session_dir = self._find_session(site_id, session_id)
        path = session_dir / "parsed" / "online_diagnosis.sqlite"
        if not path.is_file():
            return OnlineMrDatabaseSummaryDTO(
                status=OnlineMrParsedStatus.MISSING,
                compatible=False,
                error_code=OnlineMrQueryErrorCode.DATABASE_NOT_FOUND,
                message="当前会话尚未生成解析数据库，原始日志仍可查看。",
                action="parse_session",
                missing_capabilities=sorted(_PARSED_CAPABILITY_TABLES),
                missing_tables=sorted(_CURRENT_PARSED_TABLES),
            )
        stat = path.stat()
        try:
            with closing(self._connect_readonly(path)) as conn:
                tables = [
                    str(row[0])
                    for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
                ]
                table_set = set(tables)
                row_counts: dict[str, int] = {}
                parser_version: str | None = None
                parse_status = ""
                raw_fingerprint = ""
                metadata_columns = self._table_columns(conn, "online_parse_metadata")
                if metadata_columns:
                    selected = [name for name in ("parser_version", "status", "raw_fingerprint", "row_counts") if name in metadata_columns]
                    order = " ORDER BY id DESC" if "id" in metadata_columns else " ORDER BY parsed_at DESC" if "parsed_at" in metadata_columns else ""
                    row = conn.execute(f"SELECT {', '.join(selected)} FROM online_parse_metadata{order} LIMIT 1").fetchone() if selected else None
                    values = dict(row) if row else {}
                    parser_version = self._text_or_none(values.get("parser_version"))
                    parse_status = str(values.get("status") or "").upper()
                    raw_fingerprint = str(values.get("raw_fingerprint") or "")
                    parsed_counts = self._json_object(values.get("row_counts"))
                    row_counts = {str(key): int(value) for key, value in parsed_counts.items() if isinstance(value, int)}
                capabilities = sorted(
                    name for name, required in _PARSED_CAPABILITY_TABLES.items() if required.issubset(table_set)
                )
                missing_capabilities = sorted(set(_PARSED_CAPABILITY_TABLES) - set(capabilities))
                missing_tables = sorted(_CURRENT_PARSED_TABLES - table_set)
                schema_version = self._database_schema_version(conn) or parser_version
            status = OnlineMrParsedStatus.READY
            error_code: str | None = None
            action: str | None = None
            message = "解析数据库可用。"
            if parse_status in {"RUNNING", "PARSING", "REBUILDING"}:
                status = OnlineMrParsedStatus.PARSING
                error_code = OnlineMrQueryErrorCode.PARSE_REQUIRED
                action = "open_task_center"
                message = "当前会话正在解析，原始日志仍可查看。"
            elif missing_tables or not parser_version or parser_version != PARSER_VERSION:
                status = OnlineMrParsedStatus.LEGACY
                error_code = OnlineMrQueryErrorCode.SCHEMA_INCOMPLETE if missing_tables else OnlineMrQueryErrorCode.SCHEMA_LEGACY
                action = "force_reparse"
                message = "当前解析数据库为旧版本，兼容能力之外的指标不可用。"
            elif parse_status and parse_status != "OK":
                status = OnlineMrParsedStatus.STALE
                error_code = OnlineMrQueryErrorCode.PARSE_REQUIRED
                action = "force_reparse"
                message = "当前解析结果未完成，需要重新解析。"
            elif raw_fingerprint and raw_fingerprint != self._raw_fingerprint(session_dir / "raw"):
                status = OnlineMrParsedStatus.STALE
                error_code = OnlineMrQueryErrorCode.PARSE_REQUIRED
                action = "force_reparse"
                message = "原始日志已变化，当前解析结果已过期。"
            return OnlineMrDatabaseSummaryDTO(
                status=status,
                available=True,
                compatible=bool(capabilities),
                size_bytes=stat.st_size,
                modified_at=datetime.fromtimestamp(stat.st_mtime).isoformat(sep=" ", timespec="seconds"),
                schema_version=schema_version,
                parser_version=parser_version,
                tables=tables,
                row_counts=row_counts,
                available_capabilities=capabilities,
                missing_capabilities=missing_capabilities,
                missing_tables=missing_tables,
                error_code=error_code,
                message=message,
                action=action,
            )
        except OnlineMrQueryError as exc:
            return OnlineMrDatabaseSummaryDTO(
                status=OnlineMrParsedStatus.UNREADABLE,
                available=True,
                compatible=False,
                size_bytes=stat.st_size,
                modified_at=datetime.fromtimestamp(stat.st_mtime).isoformat(sep=" ", timespec="seconds"),
                error_code=exc.code,
                message=exc.message,
                action="force_reparse",
                missing_capabilities=sorted(_PARSED_CAPABILITY_TABLES),
            )
        except sqlite3.Error as exc:
            error = self._database_error(exc)
            return OnlineMrDatabaseSummaryDTO(
                status=OnlineMrParsedStatus.UNREADABLE,
                available=True,
                compatible=False,
                size_bytes=stat.st_size,
                modified_at=datetime.fromtimestamp(stat.st_mtime).isoformat(sep=" ", timespec="seconds"),
                error_code=error.code,
                message=error.message,
                action="force_reparse",
                missing_capabilities=sorted(_PARSED_CAPABILITY_TABLES),
            )

    def query_metrics(
        self,
        site_id: str,
        session_id: str,
        metric_types: Iterable[OnlineMrMetricType | str],
        *,
        start_time: str | None = None,
        end_time: str | None = None,
        limit: int = 5_000,
        downsample: OnlineMrDownsampleMode | str = OnlineMrDownsampleMode.NONE,
        bucket_seconds: int = 1,
    ) -> list[OnlineMrMetricSeriesDTO]:
        limit, _ = self._pagination(limit, 0)
        mode = OnlineMrDownsampleMode(downsample)
        self._validate_bucket_seconds(bucket_seconds)
        path = self._parsed_database_path(site_id, session_id)
        requested = self._metric_types(metric_types)
        try:
            with closing(self._connect_readonly(path)) as conn:
                series = [
                    row
                    for metric in requested
                    for row in self._query_metric(conn, metric, start_time, end_time, limit)
                ]
        except OnlineMrQueryError:
            raise
        except sqlite3.Error as exc:
            raise self._database_error(exc) from exc
        return [self._downsample(row, mode, bucket_seconds) for row in series]

    def query_metric_page(
        self,
        site_id: str,
        session_id: str,
        metric_types: Iterable[OnlineMrMetricType | str],
        *,
        start_time: str | None = None,
        end_time: str | None = None,
        limit: int = 1_000,
        offset: int = 0,
        downsample: OnlineMrDownsampleMode | str = OnlineMrDownsampleMode.NONE,
        bucket_seconds: int = 1,
    ) -> OnlineMrMetricPageDTO:
        limit, offset = self._pagination(limit, offset)
        mode = OnlineMrDownsampleMode(downsample)
        self._validate_bucket_seconds(bucket_seconds)
        path = self._parsed_database_path(site_id, session_id)
        requested = self._metric_types(metric_types)
        if limit < len(requested):
            raise OnlineMrQueryError(
                OnlineMrQueryErrorCode.QUERY_LIMIT_EXCEEDED,
                "分页条数不能小于指标数量",
            )
        page_size_per_metric = max(1, limit // len(requested))
        try:
            with closing(self._connect_readonly(path)) as conn:
                pages = [
                    self._query_metric(conn, metric, start_time, end_time, page_size_per_metric + 1, offset)
                    for metric in requested
                ]
        except OnlineMrQueryError:
            raise
        except sqlite3.Error as exc:
            raise self._database_error(exc) from exc
        has_more = any(sum(len(row.points) for row in page) > page_size_per_metric for page in pages)
        series: list[OnlineMrMetricSeriesDTO] = []
        for page in pages:
            remaining = page_size_per_metric
            for row in page:
                if remaining <= 0:
                    break
                points = row.points[:remaining]
                remaining -= len(points)
                if points:
                    series.append(row.model_copy(update={"points": points, "summary": self._metric_summary(points)}))
        sampled = [self._downsample(row, mode, bucket_seconds) for row in series]
        return OnlineMrMetricPageDTO(
            series=sampled,
            limit=limit,
            offset=offset,
            page_size_per_metric=page_size_per_metric,
            next_offset=offset + page_size_per_metric,
            returned_points=sum(len(row.points) for row in sampled),
            has_more=has_more,
        )

    def _parsed_database_path(self, site_id: str, session_id: str) -> Path:
        path = self._find_session(site_id, session_id) / "parsed" / "online_diagnosis.sqlite"
        if not path.is_file():
            raise OnlineMrQueryError(OnlineMrQueryErrorCode.DATABASE_NOT_FOUND, "Online MR 解析数据库不存在")
        return path

    @staticmethod
    def _metric_types(metric_types: Iterable[OnlineMrMetricType | str]) -> list[OnlineMrMetricType]:
        requested: list[OnlineMrMetricType] = []
        for item in metric_types:
            try:
                requested.append(OnlineMrMetricType(item))
            except ValueError as exc:
                raise OnlineMrQueryError(OnlineMrQueryErrorCode.METRIC_UNSUPPORTED, "不支持的 Online MR 指标") from exc
        requested = list(dict.fromkeys(requested))
        if not requested:
            raise OnlineMrQueryError(OnlineMrQueryErrorCode.METRIC_UNSUPPORTED, "至少选择一个 Online MR 指标")
        return requested

    @staticmethod
    def _validate_bucket_seconds(bucket_seconds: int) -> None:
        if bucket_seconds < 1:
            raise OnlineMrQueryError(OnlineMrQueryErrorCode.QUERY_LIMIT_EXCEEDED, "降采样时间桶必须大于 0")

    def query_switch_rssi_windows(
        self,
        site_id: str,
        session_id: str,
        source: OnlineMrSwitchRssiSource | str,
        *,
        start_time: str | None = None,
        end_time: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> OnlineMrSwitchRssiPageDTO:
        limit, offset = self._pagination(limit, offset)
        source = OnlineMrSwitchRssiSource(source)
        session_dir = self._find_session(site_id, session_id)
        path = session_dir / "parsed" / "online_diagnosis.sqlite"
        if not path.is_file():
            raise OnlineMrQueryError(OnlineMrQueryErrorCode.DATABASE_NOT_FOUND, "Online MR 解析数据库不存在")
        try:
            with closing(self._connect_readonly(path)) as conn:
                rows = self._query_switch_rows(conn, source, start_time, end_time, limit + 1, offset)
        except OnlineMrQueryError:
            raise
        except sqlite3.Error as exc:
            raise self._database_error(exc) from exc
        items = rows[:limit]
        return OnlineMrSwitchRssiPageDTO(items=items, limit=limit, offset=offset, has_more=len(rows) > limit)

    def list_notes(self, site_id: str, session_id: str, *, limit: int = 200, offset: int = 0) -> list[OnlineMrManualNoteDTO]:
        limit, offset = self._pagination(limit, offset)
        session_dir = self._find_session(site_id, session_id)
        path = session_dir / "manual_notes.jsonl"
        if not path.is_file():
            return []
        rows: list[OnlineMrManualNoteDTO] = []
        valid_index = 0
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for sequence, line in enumerate(handle):
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if valid_index < offset:
                    valid_index += 1
                    continue
                rows.append(
                    OnlineMrManualNoteDTO(
                        event_id=f"note-{sequence}",
                        session_id=str(data.get("session_id") or session_id),
                        local_time=self._text_or_none(data.get("local_time")),
                        device_time=self._text_or_none(data.get("device_aligned_time")),
                        title=str(data.get("note") or ""),
                        payload={key: value for key, value in data.items() if key not in {"session_id", "local_time", "device_aligned_time", "note"}},
                    )
                )
                valid_index += 1
                if len(rows) >= limit:
                    break
        return rows

    def query_timeline(self, site_id: str, session_id: str, *, limit: int = 500, offset: int = 0) -> list[OnlineMrTimelineEventDTO]:
        limit, offset = self._pagination(limit, offset)
        fetch_limit = min(MAX_QUERY_LIMIT, offset + limit)
        notes = self.list_notes(site_id, session_id, limit=fetch_limit)
        rows = [OnlineMrTimelineEventDTO(**note.model_dump()) for note in notes]
        session_dir = self._find_session(site_id, session_id)
        path = session_dir / "parsed" / "online_diagnosis.sqlite"
        if path.is_file():
            try:
                with closing(self._connect_readonly(path)) as conn:
                    rows.extend(self._database_timeline(conn, session_id, fetch_limit))
            except OnlineMrQueryError:
                raise
            except sqlite3.Error as exc:
                raise self._database_error(exc) from exc
        rows.sort(key=lambda item: (item.local_time or item.device_time or "", item.event_id))
        return rows[offset : offset + limit]

    def _find_session(self, site_id: str, session_id: str) -> Path:
        self._validate_site_id(site_id)
        if not session_id or Path(session_id).name != session_id or session_id in {".", ".."}:
            raise OnlineMrQueryError(OnlineMrQueryErrorCode.SESSION_NOT_FOUND, "Online MR 会话不存在")
        for session_dir in self.store.list_session_dirs(site_id):
            if session_dir.name == session_id:
                return session_dir
        raise OnlineMrQueryError(OnlineMrQueryErrorCode.SESSION_NOT_FOUND, "Online MR 会话不存在")

    @staticmethod
    def _validate_site_id(site_id: str) -> None:
        if not site_id or Path(site_id).name != site_id or site_id in {".", ".."}:
            raise OnlineMrQueryError(OnlineMrQueryErrorCode.SESSION_NOT_FOUND, "Online MR 局点不存在")

    def _read_metadata(self, session_dir: Path, *, tolerate_errors: bool = False) -> dict[str, Any] | None:
        path = session_dir / "session_meta.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError
            return data
        except FileNotFoundError as exc:
            if tolerate_errors:
                LOGGER.warning("跳过缺少 metadata 的 Online MR 会话：%s", session_dir.name)
                return None
            raise OnlineMrQueryError(OnlineMrQueryErrorCode.SESSION_INCOMPLETE, "Online MR 会话缺少 metadata") from exc
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            if tolerate_errors:
                LOGGER.warning("跳过 metadata 损坏的 Online MR 会话：%s", session_dir.name)
                return None
            raise OnlineMrQueryError(OnlineMrQueryErrorCode.METADATA_INVALID, "Online MR 会话 metadata 无效") from exc

    def _read_view_json(self, session_dir: Path, name: str) -> dict[str, Any]:
        path = self._safe_session_file(session_dir, f"view/{name}")
        if path is None or not path.is_file() or path.is_symlink() or path.stat().st_size > 1024 * 1024:
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _safe_session_file(session_dir: Path, relative_name: str) -> Path | None:
        relative = Path(str(relative_name or ""))
        if not relative_name or relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
            return None
        try:
            root = session_dir.resolve(strict=True)
            candidate = (session_dir / relative).resolve(strict=False)
            candidate.relative_to(root)
        except (OSError, ValueError):
            return None
        return candidate

    def _operation_status(self, site_id: str, session_id: str, task_id: str | None) -> tuple[str | None, str | None, float | None, str | None]:
        path = self.paths.site_tasks_db_path(site_id)
        if not path.is_file() or path.is_symlink():
            return None, None, None, None
        try:
            with closing(self._connect_readonly(path)) as conn:
                tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
                mapping_state = None
                duration_minutes = None
                stop_reason = None
                if "online_mr_task_sessions" in tables:
                    row = conn.execute(
                        "SELECT mapping_state, duration_minutes, stop_reason, controller_task_id "
                        "FROM online_mr_task_sessions WHERE session_id = ? AND site_id = ? LIMIT 1",
                        (session_id, site_id),
                    ).fetchone()
                    if row:
                        mapping_state = self._text_or_none(row["mapping_state"])
                        duration_minutes = float(row["duration_minutes"]) if row["duration_minutes"] is not None else None
                        stop_reason = self._text_or_none(row["stop_reason"])
                        task_id = task_id or self._text_or_none(row["controller_task_id"])
                task_status = None
                if task_id and "task_snapshots" in tables:
                    row = conn.execute("SELECT status FROM task_snapshots WHERE task_id = ? LIMIT 1", (task_id,)).fetchone()
                    task_status = self._text_or_none(row["status"]) if row else None
                return task_status, mapping_state, duration_minutes, stop_reason
        except (OnlineMrQueryError, sqlite3.Error):
            LOGGER.debug("读取 Online MR Task/Mapping 状态失败：%s", session_id, exc_info=True)
            return None, None, None, None

    def _summary(self, site_id: str, session_dir: Path, meta: dict[str, Any]) -> OnlineMrSessionSummaryDTO:
        paths = OnlineMrCollectionPaths.from_session_dir(session_dir)
        started_at = self._text_or_none(meta.get("started_at"))
        stopped_at = self._text_or_none(meta.get("ended_at"))
        started = self._as_datetime(started_at)
        stopped = self._as_datetime(stopped_at)
        status = str(meta.get("status") or "")
        elapsed_end = stopped or (datetime.now() if started and status.upper() in self._ACTIVE_WEB_STATES else None)
        duration_seconds = max(0.0, (elapsed_end - started).total_seconds()) if started and elapsed_end else None
        task_id = self._text_or_none(meta.get("controller_task_id"))
        task_status, mapping_state, mapped_duration, mapped_reason = self._operation_status(site_id, session_dir.name, task_id)
        explicit_duration = meta.get("duration_minutes")
        duration_minutes = (
            float(explicit_duration)
            if isinstance(explicit_duration, (int, float))
            else mapped_duration if mapped_duration is not None else round(duration_seconds / 60, 3) if duration_seconds is not None else None
        )
        packages = [paths.package_path] if paths.package_path.is_file() and not paths.package_path.is_symlink() else []
        return OnlineMrSessionSummaryDTO(
            session_id=str(meta.get("session_id") or session_dir.name),
            site_id=site_id,
            mr_name=str(meta.get("mr_name") or session_dir.parent.parent.name),
            device_id=meta.get("device_id"),
            device_name=str(meta.get("device_name") or ""),
            status=status,
            phase=self._text_or_none(meta.get("phase")),
            created_at=self._text_or_none(meta.get("created_at")),
            started_at=started_at,
            stopped_at=stopped_at,
            duration_seconds=duration_seconds,
            duration_minutes=duration_minutes,
            controller_task_id=task_id,
            executor_kind=self._text_or_none(meta.get("executor_kind")),
            agent_id=self._text_or_none(meta.get("agent_id")),
            has_raw_data=paths.raw_dir.is_dir() and any(path.is_file() for path in paths.raw_dir.iterdir()),
            has_parsed_data=(session_dir / "parsed" / "online_diagnosis.sqlite").is_file(),
            has_package=bool(packages),
            package_name=packages[0].name if packages else None,
            package_reference=f"outputs/{packages[0].name}" if packages else None,
            force_stopped=meta.get("force_stopped") if isinstance(meta.get("force_stopped"), bool) else None,
            finalization_complete=meta.get("finalization_complete") if isinstance(meta.get("finalization_complete"), bool) else None,
            stop_reason=self._text_or_none(meta.get("stop_reason")) or mapped_reason,
            task_status=task_status,
            mapping_state=mapping_state,
            error_code=self._text_or_none(meta.get("error_code")),
            error_message=self._text_or_none(meta.get("error_message") or meta.get("error_summary") or meta.get("config_error")),
        )

    def _connect_readonly(self, path: Path) -> sqlite3.Connection:
        try:
            conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA query_only=ON")
            return conn
        except sqlite3.Error as exc:
            raise self._database_error(exc) from exc

    @staticmethod
    def _database_error(exc: sqlite3.Error) -> OnlineMrQueryError:
        detail = str(exc).lower()
        if "locked" in detail or "busy" in detail:
            return OnlineMrQueryError(OnlineMrQueryErrorCode.DATABASE_BUSY, "Online MR 解析数据库正忙")
        if "malformed" in detail or "not a database" in detail or "file is encrypted" in detail:
            return OnlineMrQueryError(OnlineMrQueryErrorCode.DATABASE_CORRUPT, "Online MR 解析数据库已损坏")
        if "no such table" in detail or "no such column" in detail:
            return OnlineMrQueryError(OnlineMrQueryErrorCode.SCHEMA_INCOMPLETE, "Online MR 解析数据库结构不完整")
        return OnlineMrQueryError(OnlineMrQueryErrorCode.DATABASE_UNREADABLE, "Online MR 解析数据库无法打开")

    @staticmethod
    def _database_schema_version(conn: sqlite3.Connection) -> str | None:
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'").fetchone():
            columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(meta)")}
            if {"key", "value"}.issubset(columns):
                row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version' LIMIT 1").fetchone()
                if row and row[0] not in (None, ""):
                    return str(row[0])
        user_version = int(conn.execute("PRAGMA user_version").fetchone()[0] or 0)
        return str(user_version) if user_version else None

    @staticmethod
    def _raw_fingerprint(raw_root: Path) -> str:
        items: list[dict[str, object]] = []
        if raw_root.is_dir():
            for path in sorted(raw_root.rglob("*")):
                if not path.is_file() or path.is_symlink():
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    continue
                items.append(
                    {
                        "path": path.relative_to(raw_root).as_posix(),
                        "size": stat.st_size,
                        "mtime_ns": stat.st_mtime_ns,
                    }
                )
        return json.dumps(items, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def _query_metric(
        self,
        conn: sqlite3.Connection,
        metric: OnlineMrMetricType,
        start_time: str | None,
        end_time: str | None,
        limit: int,
        offset: int = 0,
    ) -> list[OnlineMrMetricSeriesDTO]:
        specs = {
            OnlineMrMetricType.RSSI: ("main_link_samples", "mr_rssi", ("device_time", "device_clock", "collector_time"), ("radio", "resolved_peer_name", "peer_name", "peer_mac"), None, "dBm"),
            OnlineMrMetricType.MAIN_LINK: ("main_link_samples", None, ("device_time", "device_clock", "collector_time"), ("radio", "resolved_peer_name", "peer_name", "peer_mac"), "resolved_peer_name", ""),
            OnlineMrMetricType.CTL_BUSY: ("channel_busy_records", "ctl_busy", ("device_time", "device_clock"), ("radio",), None, "%"),
            OnlineMrMetricType.TX_BUSY: ("channel_busy_records", "tx_busy", ("device_time", "device_clock"), ("radio",), None, "%"),
            OnlineMrMetricType.RX_BUSY: ("channel_busy_records", "rx_busy", ("device_time", "device_clock"), ("radio",), None, "%"),
            OnlineMrMetricType.INTERFACE_IN_PPS: ("interface_rate_samples", "total_pps", ("device_time", "device_clock"), ("interface_normalized", "interface_name"), None, "pps"),
            OnlineMrMetricType.INTERFACE_OUT_PPS: ("interface_rate_samples", "total_pps", ("device_time", "device_clock"), ("interface_normalized", "interface_name"), None, "pps"),
            OnlineMrMetricType.PING_RTT: ("fping_samples", "latency_ms", ("device_aligned_time", "collector_time", "local_time"), ("target_ip", "target_name"), None, "ms"),
            OnlineMrMetricType.PING_LOSS: ("fping_1s_summary", "loss_percent", ("device_bucket_time", "bucket_time", "local_bucket_time"), ("target_ip", "target_name"), None, "%"),
            OnlineMrMetricType.IPERF_BITRATE: ("iperf_intervals", "bitrate_mbps", ("device_interval_center_time", "device_aligned_time", "interval_center_time", "collector_time"), ("run_id",), None, "Mbps"),
            OnlineMrMetricType.RADIO_STATISTICS: ("radio_statistics_samples", "metric_value", ("collector_time", "device_clock"), ("radio", "metric_name", "metric_unit"), "metric_name", ""),
        }
        table, value_column, time_candidates, dimensions, text_column, unit = specs[metric]
        columns = self._table_columns(conn, table)
        if not columns:
            return []
        time_columns = [name for name in time_candidates if name in columns]
        available_dimensions = [name for name in dimensions if name in columns]
        if not time_columns or (value_column and value_column not in columns):
            return []
        if text_column not in columns:
            text_column = next((name for name in ("peer_name", "peer_mac") if name in columns), None)
        time_parts = [f"NULLIF({name}, '')" for name in time_columns]
        time_expr = time_parts[0] if len(time_parts) == 1 else f"COALESCE({', '.join(time_parts)})"
        selects = [f"{time_expr} AS metric_time"]
        selects.append(f"{value_column} AS metric_value" if value_column else "NULL AS metric_value")
        selects.append(f"{text_column} AS text_value" if text_column else "NULL AS text_value")
        evidence_dimensions = [name for name in ("raw_file", "raw_line_start", "raw_line_end") if name in columns]
        selects.extend(f"{name} AS dim_{name}" for name in (*available_dimensions, *evidence_dimensions))
        where = [f"{time_expr} IS NOT NULL"]
        params: list[Any] = []
        if metric == OnlineMrMetricType.PING_RTT and "success" in columns:
            where.extend(["success = 1", "latency_ms IS NOT NULL"])
        if metric in {OnlineMrMetricType.CTL_BUSY, OnlineMrMetricType.TX_BUSY, OnlineMrMetricType.RX_BUSY} and "row_index" in columns:
            where.append("COALESCE(row_index, 1) = 1")
        if metric in {OnlineMrMetricType.INTERFACE_IN_PPS, OnlineMrMetricType.INTERFACE_OUT_PPS} and "direction" in columns:
            where.append("LOWER(direction) = ?")
            params.append("inbound" if metric == OnlineMrMetricType.INTERFACE_IN_PPS else "outbound")
        if start_time:
            where.append(f"{time_expr} >= ?")
            params.append(start_time)
        if end_time:
            where.append(f"{time_expr} <= ?")
            params.append(end_time)
        params.extend((limit, offset))
        sql = f"SELECT {', '.join(selects)} FROM {table} WHERE {' AND '.join(where)} ORDER BY metric_time, rowid LIMIT ? OFFSET ?"
        grouped: dict[str, list[OnlineMrMetricPointDTO]] = defaultdict(list)
        for row in conn.execute(sql, params):
            dimension_values = {name: row[f"dim_{name}"] for name in (*available_dimensions, *evidence_dimensions) if row[f"dim_{name}"] not in (None, "")}
            key = "|".join(f"{name}={dimension_values[name]}" for name in sorted(available_dimensions) if name in dimension_values) or "default"
            value = row["metric_value"]
            grouped[key].append(
                OnlineMrMetricPointDTO(
                    timestamp=str(row["metric_time"]) if row["metric_time"] is not None else None,
                    value=float(value) if value is not None else None,
                    text_value=self._text_or_none(row["text_value"]),
                    dimensions=dimension_values,
                )
            )
        return [
            OnlineMrMetricSeriesDTO(
                metric_type=metric,
                series_key=key,
                unit=unit or str(points[0].dimensions.get("metric_unit") or ""),
                points=points,
                summary=self._metric_summary(points),
            )
            for key, points in grouped.items()
        ]

    def _query_switch_rows(
        self,
        conn: sqlite3.Connection,
        source: OnlineMrSwitchRssiSource,
        start_time: str | None,
        end_time: str | None,
        limit: int,
        offset: int,
    ) -> list[OnlineMrSwitchRssiWindowDTO]:
        table = "switch_history_events" if source == OnlineMrSwitchRssiSource.HISTORY else "switch_realtime_events"
        columns = self._table_columns(conn, table)
        if not columns:
            return []
        required = {
            "id", "radio", "old_peer_name", "old_peer_mac", "old_rssi",
            "new_peer_name", "new_peer_mac", "new_rssi", "switch_reason_text",
            "raw_file", "raw_line_start", "raw_line_end",
        }
        if not required.issubset(columns):
            return []
        time_candidates = (
            ("event_time_local", "event_time_device", "snapshot_collector_time")
            if source == OnlineMrSwitchRssiSource.HISTORY
            else ("device_time",)
        )
        available_times = [name for name in time_candidates if name in columns]
        if not available_times:
            return []
        time_parts = [f"NULLIF({name}, '')" for name in available_times]
        time_expr = time_parts[0] if len(time_parts) == 1 else f"COALESCE({', '.join(time_parts)})"
        where = [f"{time_expr} IS NOT NULL"]
        params: list[Any] = []
        if start_time:
            where.append(f"{time_expr} >= ?")
            params.append(start_time)
        if end_time:
            where.append(f"{time_expr} <= ?")
            params.append(end_time)
        params.extend((limit, offset))
        rows = conn.execute(
            f"SELECT id, {time_expr} AS event_time, radio, old_peer_name, old_peer_mac, old_rssi, "
            "new_peer_name, new_peer_mac, new_rssi, switch_reason_text, raw_file, raw_line_start, raw_line_end "
            f"FROM {table} WHERE {' AND '.join(where)} ORDER BY event_time, id LIMIT ? OFFSET ?",
            params,
        )
        return [
            OnlineMrSwitchRssiWindowDTO(
                event_id=f"{source.value}-{row['id']}",
                source=source,
                event_time=self._text_or_none(row["event_time"]),
                radio=int(row["radio"]) if row["radio"] is not None else None,
                reason=str(row["switch_reason_text"] or "主链路切换"),
                old_peer_name=str(row["old_peer_name"] or ""),
                old_peer_mac=str(row["old_peer_mac"] or ""),
                old_rssi_dbm=float(row["old_rssi"]) if row["old_rssi"] is not None else None,
                new_peer_name=str(row["new_peer_name"] or ""),
                new_peer_mac=str(row["new_peer_mac"] or ""),
                new_rssi_dbm=float(row["new_rssi"]) if row["new_rssi"] is not None else None,
                raw_file=str(row["raw_file"] or ""),
                raw_line_start=int(row["raw_line_start"]) if row["raw_line_start"] is not None else None,
                raw_line_end=int(row["raw_line_end"]) if row["raw_line_end"] is not None else None,
            )
            for row in rows
        ]

    @staticmethod
    def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
        return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}

    def _database_timeline(
        self,
        conn: sqlite3.Connection,
        session_id: str,
        fetch_limit: int,
    ) -> list[OnlineMrTimelineEventDTO]:
        rows: list[OnlineMrTimelineEventDTO] = []
        if self._table_columns(conn, "analysis_events"):
            for row in conn.execute(
                "SELECT id, collector_time, event_type, severity, summary_text, details_json "
                "FROM analysis_events ORDER BY collector_time LIMIT ?",
                (fetch_limit,),
            ):
                rows.append(
                    OnlineMrTimelineEventDTO(
                        event_id=f"analysis-{row['id']}",
                        session_id=session_id,
                        local_time=self._text_or_none(row["collector_time"]),
                        source="analysis",
                        event_type=str(row["event_type"] or "analysis"),
                        severity=self._text_or_none(row["severity"]),
                        title=str(row["summary_text"] or ""),
                        payload=self._json_object(row["details_json"]),
                    )
                )
        if self._table_columns(conn, "switch_history_events"):
            for row in conn.execute(
                "SELECT id, event_time_local, event_time_device, radio, old_peer_name, new_peer_name, switch_reason_text "
                "FROM switch_history_events ORDER BY event_time_local, event_time_device LIMIT ?",
                (fetch_limit,),
            ):
                rows.append(
                    OnlineMrTimelineEventDTO(
                        event_id=f"switch-{row['id']}",
                        session_id=session_id,
                        local_time=self._text_or_none(row["event_time_local"]),
                        device_time=self._text_or_none(row["event_time_device"]),
                        source="switch_history",
                        event_type="link_switch",
                        title=str(row["switch_reason_text"] or "主链路切换"),
                        payload={"radio": row["radio"], "old_peer_name": row["old_peer_name"], "new_peer_name": row["new_peer_name"]},
                    )
                )
        if self._table_columns(conn, "switch_realtime_events"):
            for row in conn.execute(
                "SELECT id, device_time, radio, old_peer_name, old_peer_mac, old_rssi, "
                "new_peer_name, new_peer_mac, new_rssi, switch_reason_text, "
                "raw_file, raw_line_start, raw_line_end FROM switch_realtime_events "
                "ORDER BY device_time LIMIT ?",
                (fetch_limit,),
            ):
                rows.append(
                    OnlineMrTimelineEventDTO(
                        event_id=f"switch-realtime-{row['id']}",
                        session_id=session_id,
                        device_time=self._text_or_none(row["device_time"]),
                        source="switch_realtime",
                        event_type="link_switch",
                        title=str(row["switch_reason_text"] or "实时主链路切换"),
                        payload={
                            "radio": row["radio"],
                            "old_peer_name": row["old_peer_name"],
                            "old_peer_mac": row["old_peer_mac"],
                            "old_rssi_dbm": row["old_rssi"],
                            "new_peer_name": row["new_peer_name"],
                            "new_peer_mac": row["new_peer_mac"],
                            "new_rssi_dbm": row["new_rssi"],
                            "raw_file": row["raw_file"],
                            "raw_line_start": row["raw_line_start"],
                            "raw_line_end": row["raw_line_end"],
                        },
                    )
                )
        return rows

    def _latest_metric_time(self, session_dir: Path) -> str | None:
        path = session_dir / "parsed" / "online_diagnosis.sqlite"
        if not path.is_file():
            return None
        values: list[str] = []
        try:
            with closing(self._connect_readonly(path)) as conn:
                for table, candidates in (
                    ("main_link_samples", ("device_time", "collector_time")),
                    ("channel_busy_records", ("device_time", "device_clock")),
                    ("fping_samples", ("device_aligned_time", "collector_time")),
                    ("iperf_intervals", ("device_interval_center_time", "collector_time")),
                ):
                    columns = self._table_columns(conn, table)
                    available = [name for name in candidates if name in columns]
                    if not available:
                        continue
                    parts = [f"NULLIF({name}, '')" for name in available]
                    expr = parts[0] if len(parts) == 1 else f"COALESCE({', '.join(parts)})"
                    row = conn.execute(f"SELECT MAX({expr}) FROM {table}").fetchone()
                    if row and row[0]:
                        values.append(str(row[0]))
        except (OnlineMrQueryError, sqlite3.Error):
            LOGGER.debug("读取 Online MR 最新指标时间失败", exc_info=True)
            return None
        return max(values) if values else None

    @staticmethod
    def _tail_cursor(path: Path, line_count: int) -> int:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            end = handle.tell()
            position = end
            lower_bound = max(0, end - max(65_536, min(line_count, MAX_LOG_LIMIT) * 4_096))
            found = 0
            while position > lower_bound and found <= line_count:
                size = min(8192, position - lower_bound)
                position -= size
                handle.seek(position)
                found += handle.read(size).count(b"\n")
            handle.seek(position)
            data = handle.read()
        offsets = [0]
        offsets.extend(index + 1 for index, byte in enumerate(data) if byte == 10 and index + 1 < len(data))
        return position + offsets[max(0, len(offsets) - line_count)]

    @staticmethod
    def _pagination(limit: int, offset: int) -> tuple[int, int]:
        if limit < 1 or limit > MAX_QUERY_LIMIT or offset < 0:
            raise OnlineMrQueryError(OnlineMrQueryErrorCode.QUERY_LIMIT_EXCEEDED, f"查询条数必须在 1 到 {MAX_QUERY_LIMIT} 之间")
        return limit, offset

    @staticmethod
    def _as_datetime(value: str | datetime | None) -> datetime | None:
        if isinstance(value, datetime):
            return value
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return parsed.astimezone().replace(tzinfo=None) if parsed.tzinfo else parsed
        except ValueError:
            return None

    @staticmethod
    def _text_or_none(value: Any) -> str | None:
        text = str(value).strip() if value is not None else ""
        return text or None

    @staticmethod
    def _count_notes(session_dir: Path) -> int:
        path = session_dir / "manual_notes.jsonl"
        if not path.is_file():
            return 0
        with path.open("rb") as handle:
            return sum(1 for line in handle if line.strip())

    @staticmethod
    def _enabled_collectors(meta: dict[str, Any]) -> list[str]:
        rows = [name for name, value in (meta.get("intervals") or {}).items() if value]
        if meta.get("config_collect_enabled"):
            rows.append("config_collect")
        if (meta.get("fping") or {}).get("enabled"):
            rows.append("fping")
        if (meta.get("iperf") or {}).get("enabled"):
            rows.append("iperf")
        return sorted(set(rows))

    @staticmethod
    def _data_integrity(meta: dict[str, Any], summary: OnlineMrSessionSummaryDTO) -> OnlineMrDataIntegrity:
        explicit = meta.get("data_integrity")
        if explicit in {item.value for item in OnlineMrDataIntegrity}:
            return OnlineMrDataIntegrity(explicit)
        if summary.finalization_complete is True and summary.has_package:
            return OnlineMrDataIntegrity.COMPLETE
        if summary.force_stopped is True or summary.finalization_complete is False:
            return OnlineMrDataIntegrity.PARTIAL
        return OnlineMrDataIntegrity.UNKNOWN

    @staticmethod
    def _is_temporary(path: Path) -> bool:
        lower = path.name.lower()
        return lower.endswith((".tmp", ".lock", ".lck")) or lower.startswith("~$")

    @staticmethod
    def _metric_summary(points: list[OnlineMrMetricPointDTO]) -> OnlineMrMetricSummaryDTO:
        values = [point.value for point in points if point.value is not None]
        if not values:
            return OnlineMrMetricSummaryDTO(count=len(points))
        return OnlineMrMetricSummaryDTO(count=len(points), minimum=min(values), maximum=max(values), average=sum(values) / len(values))

    def _downsample(
        self,
        series: OnlineMrMetricSeriesDTO,
        mode: OnlineMrDownsampleMode,
        bucket_seconds: int,
    ) -> OnlineMrMetricSeriesDTO:
        if mode == OnlineMrDownsampleMode.NONE or len(series.points) < 2:
            return series
        buckets: dict[int, list[OnlineMrMetricPointDTO]] = defaultdict(list)
        unbucketed: list[OnlineMrMetricPointDTO] = []
        for point in series.points:
            stamp = self._as_datetime(point.timestamp)
            if stamp is None:
                unbucketed.append(point)
            else:
                buckets[int(stamp.timestamp()) // bucket_seconds].append(point)
        result: list[OnlineMrMetricPointDTO] = []
        for points in buckets.values():
            if mode == OnlineMrDownsampleMode.LATEST_PER_BUCKET:
                result.append(points[-1])
                continue
            numeric = [point for point in points if point.value is not None]
            if not numeric:
                result.append(points[-1])
            elif mode == OnlineMrDownsampleMode.BUCKET_AVG:
                base = numeric[-1]
                result.append(base.model_copy(update={"value": sum(point.value for point in numeric if point.value is not None) / len(numeric)}))
            else:
                minimum = min(numeric, key=lambda point: point.value if point.value is not None else float("inf"))
                maximum = max(numeric, key=lambda point: point.value if point.value is not None else float("-inf"))
                result.extend(
                    [
                        minimum.model_copy(update={"dimensions": {**minimum.dimensions, "statistic": "min"}}),
                        maximum.model_copy(update={"dimensions": {**maximum.dimensions, "statistic": "max"}}),
                    ]
                )
        result.extend(unbucketed)
        result.sort(key=lambda point: point.timestamp or "")
        return series.model_copy(update={"points": result, "summary": self._metric_summary(result)})

    @staticmethod
    def _json_object(value: Any) -> dict[str, Any]:
        try:
            parsed = json.loads(str(value or "{}"))
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}


__all__ = ["OnlineMrQueryService"]
