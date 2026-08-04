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
    OnlineMrBusinessSummaryDTO,
    OnlineMrBusinessTable,
    OnlineMrBusinessTablePageDTO,
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
from netconsole.services.online_mr_parser import parse_mesh_link_text
from netconsole.services.online_mr_session_store import OnlineMrSessionStore
from netconsole.services.ap_identity.normalizers import normalize_mac
from netconsole.services.rail_transit.online_mr_diagnosis_parser import PARSER_VERSION


LOGGER = logging.getLogger(__name__)
MAX_QUERY_LIMIT = 10_000
MAX_LOG_LIMIT = 1_000
MAX_LOG_LINE_BYTES = 1024 * 1024
MAX_WEB_TAIL_LIMIT = 500
MAX_WEB_TAIL_BYTES = 4 * 1024 * 1024
MAX_PREVIEW_RAW_TAIL_BYTES = 128 * 1024
_TIMESTAMP_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?)")
_LEVEL_RE = re.compile(r"\[(DEBUG|INFO|WARNING|ERROR|CRITICAL)\]", re.IGNORECASE)

_PARSED_CAPABILITY_TABLES = {
    "main_link": frozenset({"main_link_samples"}),
    "link_detail": frozenset({"main_link_samples"}),
    "channel_busy": frozenset({"channel_busy_records"}),
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
    {
        "online_parse_metadata",
        "online_parse_issues",
        "online_schema_meta",
        "time_sync_samples",
        "radio_statistics_samples",
        "active_segments",
        "active_segment_metrics",
    },
)
_DEPRECATED_BUSINESS_TABLE_ALIASES = {
    OnlineMrBusinessTable.MESH_LINK: OnlineMrBusinessTable.MAIN_LINK,
    OnlineMrBusinessTable.MESH_DETAIL: OnlineMrBusinessTable.LINK_DETAIL,
}
_BUSINESS_SOURCE_FIELDS = {
    "raw_file",
    "source_file",
    "source_path",
    "relative_file",
    "relative_path",
    "raw_path",
    "raw_line",
    "raw_line_start",
    "raw_line_end",
    "line_number",
    "evidence",
}
_RADIO_STAT_METRIC_NAMES = (
    "TxFrameAllCnt",
    "TxFrameAllBytes",
    "RxFrameAllCnt",
    "RxFrameAllBytes",
    "TxRetryFrmCnt",
    "TxErrFrmCnt",
    "TxDiscardFrmCnt",
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
        "terminal_monitor": "raw/terminal_monitor_raw.log",
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
                "startup_timeline": meta.get("startup_timeline") or [],
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

    def get_current_session(
        self,
        site_id: str,
        *,
        session_id: str | None = None,
    ) -> OnlineMrSessionDetailDTO | None:
        if not session_id:
            session_id = self._current_session_id_from_task_mapping(site_id)
        if not session_id:
            return None
        detail = self.get_session(site_id, session_id)
        return detail if detail.status.upper() in self._ACTIVE_WEB_STATES else None

    def _current_session_id_from_task_mapping(self, site_id: str) -> str | None:
        path = self.paths.site_tasks_db_path(site_id)
        if not path.is_file():
            return None
        try:
            with closing(self._connect_readonly(path)) as conn:
                columns = self._table_columns(conn, "online_mr_task_sessions")
                if not columns or "session_id" not in columns or "mapping_state" not in columns:
                    return None
                if "updated_at" in columns:
                    order = "updated_at DESC, controller_task_id DESC"
                elif "created_at" in columns:
                    order = "created_at DESC, controller_task_id DESC"
                else:
                    order = "controller_task_id DESC"
                row = conn.execute(
                    f"""
                    SELECT session_id
                    FROM online_mr_task_sessions
                    WHERE site_id = ?
                      AND session_id IS NOT NULL
                      AND session_id <> ''
                      AND mapping_state IN ('PENDING_SESSION', 'LINKED')
                    ORDER BY {order}
                    LIMIT 1
                    """,
                    (site_id,),
                ).fetchone()
        except OnlineMrQueryError:
            return None
        return self._text_or_none(row[0]) if row and row[0] not in (None, "") else None

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
            updated_at = self._collector_updated_at(
                session_dir,
                name=name,
                path=path if exists else None,
                item=item,
                view=view,
            )
            health_status, stale_seconds = self._collector_health(
                active=active,
                enabled=is_enabled,
                status=status,
                updated_at=updated_at,
            )
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
                    updated_at=updated_at,
                    health_status=health_status,
                    stale_seconds=stale_seconds,
                )
            )
        return rows

    def get_realtime_preview(self, site_id: str, session_id: str) -> OnlineMrRealtimePreviewDTO:
        session_dir = self._find_session(site_id, session_id)
        meta = self._read_metadata(session_dir)
        assert meta is not None
        mr_view = self._read_view_json(session_dir, "live_mr_status.json")
        link = self._read_view_json(session_dir, "live_link_status.json")
        raw_link: dict[str, Any] = {}
        if not link:
            link = self._latest_live_link(session_dir)
        if link and any(not link.get(key) for key in ("interface", "online_time", "local_rssi_db", "link_state")):
            raw_link = self._latest_raw_link(session_dir)
            link = self._merge_preview_link(link, raw_link)
        if not link:
            raw_link = raw_link or self._latest_raw_link(session_dir)
            link = raw_link
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

    def _collector_updated_at(
        self,
        session_dir: Path,
        *,
        name: str,
        path: Path | None,
        item: dict[str, Any],
        view: dict[str, Any],
    ) -> str | None:
        candidates = [
            self._text_or_none(item.get("updated_at")),
            self._text_or_none(view.get("updated_at")),
        ]
        if path is not None:
            try:
                candidates.append(datetime.fromtimestamp(path.stat().st_mtime).isoformat(sep=" ", timespec="milliseconds"))
            except OSError:
                pass
        sample_time = self._latest_live_sample_time(session_dir, name)
        if sample_time:
            candidates.append(sample_time)
        values = [(self._as_datetime(value), value) for value in candidates if value]
        valid = [(stamp, value) for stamp, value in values if stamp is not None]
        return max(valid, key=lambda row: row[0])[1] if valid else None

    def _latest_live_sample_time(self, session_dir: Path, collector_name: str) -> str | None:
        task_name = "fping" if collector_name == "fping_v5" else "iperf" if collector_name == "iperf_client" else collector_name
        db_path = session_dir / "parsed" / "online_diagnosis.sqlite"
        if not db_path.is_file() or db_path.is_symlink():
            return None
        try:
            with closing(self._connect_readonly(db_path)) as conn:
                tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
                if "live_samples" not in tables:
                    return None
                row = conn.execute(
                    "SELECT MAX(collected_at) FROM live_samples WHERE task_type = ?",
                    (task_name,),
                ).fetchone()
                return self._text_or_none(row[0]) if row else None
        except (OnlineMrQueryError, sqlite3.Error):
            return None

    @classmethod
    def _collector_health(
        cls,
        *,
        active: bool,
        enabled: bool,
        status: str,
        updated_at: str | None,
    ) -> tuple[str, float | None]:
        if not active or not enabled:
            return "unknown", None
        if status in {"failed", "error", "missing"}:
            return "interrupted", None
        stamp = cls._as_datetime(updated_at)
        if stamp is None:
            return "unknown", None
        if stamp.tzinfo is not None:
            stamp = stamp.astimezone().replace(tzinfo=None)
        age = max(0.0, (datetime.now() - stamp).total_seconds())
        if age > 120:
            return "interrupted", round(age, 3)
        if age > 30:
            return "stale", round(age, 3)
        return "normal", round(age, 3)

    def _latest_live_link(self, session_dir: Path) -> dict[str, Any]:
        db_path = session_dir / "parsed" / "online_diagnosis.sqlite"
        if not db_path.is_file() or db_path.is_symlink():
            return {}
        try:
            with closing(self._connect_readonly(db_path)) as conn:
                tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
                if not {"live_samples", "live_mesh_links"}.issubset(tables):
                    return {}
                sample = conn.execute(
                    "SELECT id, collected_at FROM live_samples WHERE task_type = 'mesh_link' ORDER BY id DESC LIMIT 1"
                ).fetchone()
                if not sample:
                    return {}
                row = conn.execute(
                    """
                    SELECT radio, link_state, resolved_peer_name, peer_name, peer_mac_normalized,
                           peer_mac_raw, belong_station, belong_section, local_signal_dbm, local_rssi_db
                    FROM live_mesh_links
                    WHERE sample_id = ?
                    ORDER BY CASE WHEN UPPER(link_state) = 'ACTIVE' THEN 0 ELSE 1 END, radio
                    LIMIT 1
                    """,
                    (sample["id"],),
                ).fetchone()
                if not row:
                    return {}
                peer_name = str(row["resolved_peer_name"] or row["peer_name"] or "")
                peer_mac = str(row["peer_mac_raw"] or row["peer_mac_normalized"] or "")
                rssi = self._preview_rssi_dbm(row["local_signal_dbm"], row["local_rssi_db"])
                return {
                    "status": str(row["link_state"] or "unknown").lower(),
                    "link_state": str(row["link_state"] or ""),
                    "link_state_normalized": str(row["link_state"] or ""),
                    "updated_at": self._text_or_none(sample["collected_at"]),
                    "master": peer_name or peer_mac or "未关联",
                    "master_ap": peer_name or peer_mac or "未关联",
                    "peer_name": peer_name,
                    "peer_mac": peer_mac,
                    "peer_mac_normalized": str(row["peer_mac_normalized"] or ""),
                    "rssi_dbm": rssi,
                    "local_rssi_db": row["local_rssi_db"],
                    "radio": row["radio"],
                    "source": "parsed_sqlite_latest",
                    "message": "已从结构化实时库识别 ACTIVE 主链路",
                    "display_context": {
                        "station": str(row["belong_station"] or ""),
                        "section": str(row["belong_section"] or ""),
                        "match_source": "parsed_sqlite" if row["belong_station"] or row["belong_section"] else "none",
                        "match_key": "peer_mac" if peer_mac else "none",
                    },
                }
        except (OnlineMrQueryError, sqlite3.Error):
            LOGGER.debug("读取 Online MR 轻量链路预览失败：%s", session_dir.name, exc_info=True)
            return {}

    def _latest_raw_link(self, session_dir: Path) -> dict[str, Any]:
        path = self._safe_session_file(session_dir, self._WEB_RAW_SOURCES["mesh_link"])
        if path is None or not path.is_file() or path.is_symlink():
            return {}
        try:
            stat = path.stat()
            raw_text = self._read_tail_text(path, MAX_PREVIEW_RAW_TAIL_BYTES)
            if not raw_text:
                return {}
            collected_at = datetime.fromtimestamp(stat.st_mtime)
            records, _status, _error = parse_mesh_link_text(raw_text, collected_at)
            active_records = [record for record in records if record.link_state == "ACTIVE"]
            active = next(reversed(active_records), None) if active_records else None
            if active is None:
                return {}
            metrics = active.metrics
            peer_name = str(metrics.get("resolved_peer_name") or metrics.get("peer_name") or "")
            peer_mac = str(active.peer_mac_raw or active.peer_mac_normalized or "")
            master_ap = peer_name or peer_mac or "未关联"
            rssi = self._preview_rssi_dbm(active.local_signal_dbm, metrics.get("local_rssi_db"))
            message = "已从主链路原始日志尾部识别 ACTIVE 主链路"
            if len(active_records) > 1:
                message = f"{message}；检测到 {len(active_records)} 条 ACTIVE，已按尾部最新记录显示"
            return {
                "status": "active",
                "updated_at": collected_at.isoformat(sep=" ", timespec="seconds"),
                "master": master_ap,
                "master_ap": master_ap,
                "peer_name": peer_name,
                "peer_mac": peer_mac,
                "peer_mac_raw": active.peer_mac_raw,
                "peer_mac_normalized": active.peer_mac_normalized,
                "peer_radio_mac": str(metrics.get("bssid") or ""),
                "bssid": str(metrics.get("bssid") or ""),
                "interface": str(metrics.get("interface") or ""),
                "link_state": str(active.link_state_raw or active.link_state),
                "link_state_normalized": active.link_state,
                "online_time": str(metrics.get("online_time") or ""),
                "local_rssi_db": metrics.get("local_rssi_db"),
                "rssi_dbm": rssi,
                "radio": active.radio,
                "source": "mesh_link_raw_tail",
                "raw_file": "mesh_link_raw.log",
                "display_context": {
                    "station": "",
                    "section": "",
                    "match_source": "none",
                    "match_key": "peer_mac" if peer_mac else "none",
                },
                "message": message,
            }
        except OSError:
            LOGGER.debug("读取 Online MR 原始链路尾部失败：%s", session_dir.name, exc_info=True)
            return {}

    @classmethod
    def _merge_preview_link(cls, primary: dict[str, Any], supplement: dict[str, Any]) -> dict[str, Any]:
        if not primary:
            return dict(supplement)
        if not supplement:
            return dict(primary)
        primary_mac = cls._compact_mac_key(primary.get("peer_mac") or primary.get("peer_mac_raw"))
        supplement_mac = cls._compact_mac_key(supplement.get("peer_mac") or supplement.get("peer_mac_raw"))
        if primary_mac and supplement_mac and primary_mac != supplement_mac:
            return dict(primary)
        merged = dict(primary)
        for key in (
            "master_ap",
            "peer_name",
            "peer_mac",
            "peer_mac_raw",
            "peer_mac_normalized",
            "peer_radio_mac",
            "bssid",
            "interface",
            "link_state",
            "link_state_normalized",
            "online_time",
            "local_rssi_db",
            "rssi_dbm",
            "radio",
            "raw_file",
        ):
            if not cls._has_value(merged.get(key)) and cls._has_value(supplement.get(key)):
                merged[key] = supplement[key]
        if cls._has_value(supplement.get("source")) and supplement.get("source") != merged.get("source"):
            merged["supplement_source"] = supplement["source"]
        primary_context = merged.get("display_context") if isinstance(merged.get("display_context"), dict) else {}
        supplement_context = supplement.get("display_context") if isinstance(supplement.get("display_context"), dict) else {}
        context = dict(supplement_context)
        context.update({key: value for key, value in primary_context.items() if cls._has_value(value)})
        merged["display_context"] = context
        if not cls._has_value(merged.get("message")) and cls._has_value(supplement.get("message")):
            merged["message"] = supplement["message"]
        return merged

    @staticmethod
    def _compact_mac_key(value: object) -> str:
        normalized = normalize_mac(value)
        return normalized.replace(":", "") if normalized else ""

    @staticmethod
    def _has_value(value: object) -> bool:
        return value not in (None, "")

    @staticmethod
    def _preview_rssi_dbm(signal_dbm: object, raw_rssi: object) -> float | int | None:
        if isinstance(signal_dbm, (int, float)):
            return signal_dbm
        if not isinstance(raw_rssi, (int, float)):
            return None
        # H3C 的在线 Peer 表以正数幅值展示 RSSI；详细 Mesh 记录有噪声时
        # 已由 parser 计算 signal_dbm，只有缺少该值时才按幅值转为 dBm。
        return -abs(raw_rssi) if raw_rssi > 0 else raw_rssi

    @staticmethod
    def _read_tail_text(path: Path, maximum_bytes: int) -> str:
        size = max(1, int(maximum_bytes))
        with path.open("rb") as handle:
            handle.seek(0, 2)
            end = handle.tell()
            start = max(0, end - size)
            handle.seek(start)
            data = handle.read(size)
        if start:
            separator = data.find(b"\n")
            data = data[separator + 1 :] if separator >= 0 else b""
        return data.decode("utf-8", errors="replace")

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

    def get_business_summary(self, site_id: str, session_id: str) -> OnlineMrBusinessSummaryDTO:
        path = self._parsed_database_path(site_id, session_id)
        try:
            with closing(self._connect_readonly(path)) as conn:
                return self._business_summary(conn, session_id)
        except OnlineMrQueryError:
            raise
        except sqlite3.Error as exc:
            raise self._database_error(exc) from exc

    def query_business_table(
        self,
        site_id: str,
        session_id: str,
        table: OnlineMrBusinessTable | str,
        *,
        start_time: str | None = None,
        end_time: str | None = None,
        limit: int = 1_000,
        offset: int = 0,
    ) -> OnlineMrBusinessTablePageDTO:
        limit, offset = self._pagination(limit, offset)
        try:
            business_table = OnlineMrBusinessTable(table)
        except ValueError as exc:
            raise OnlineMrQueryError(OnlineMrQueryErrorCode.METRIC_UNSUPPORTED, "不支持的 Online MR 业务表") from exc
        business_table = _DEPRECATED_BUSINESS_TABLE_ALIASES.get(business_table, business_table)
        path = self._parsed_database_path(site_id, session_id)
        try:
            with closing(self._connect_readonly(path)) as conn:
                rows = self._business_table_rows(
                    conn,
                    business_table,
                    start_time=start_time,
                    end_time=end_time,
                    limit=limit + 1,
                    offset=offset,
                )
        except OnlineMrQueryError:
            raise
        except sqlite3.Error as exc:
            raise self._database_error(exc) from exc
        items = [self._strip_business_source_fields(row) for row in rows[:limit]]
        next_offset = offset + len(items)
        return OnlineMrBusinessTablePageDTO(
            table=business_table,
            rows=items,
            limit=limit,
            offset=offset,
            returned_count=len(items),
            next_offset=next_offset,
            has_more=len(rows) > limit,
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

    def _business_summary(self, conn: sqlite3.Connection, session_id: str) -> OnlineMrBusinessSummaryDTO:
        main_columns = self._table_columns(conn, "main_link_samples")
        sample_time_expr = self._time_expr(main_columns, ("collector_time", "device_time", "device_clock"))
        first_sample_time, last_sample_time = self._time_bounds(conn, "main_link_samples", sample_time_expr)
        estimated_interval_seconds = self._estimated_interval_seconds(
            conn,
            "main_link_samples",
            sample_time_expr,
        )
        current = self._latest_active_link_row(conn, main_columns, sample_time_expr)
        segment_columns = self._table_columns(conn, "active_segments")
        current_segment = self._latest_segment_row(conn, segment_columns)
        time_sync_status, time_sync_avg_offset_ms = self._time_sync_summary(conn)
        sample_count = self._count_rows(conn, "main_link_samples")
        if "link_state" in main_columns:
            active_count = self._count_rows(conn, "main_link_samples", "UPPER(link_state) LIKE 'ACTIVE%'")
            standby_count = self._count_rows(conn, "main_link_samples", "UPPER(link_state) LIKE 'STANDBY%'")
        else:
            active_count = 0
            standby_count = 0
        active_segment_count = self._count_rows(conn, "active_segments")
        switch_count = self._count_rows(conn, "switch_history_events") + self._count_rows(conn, "switch_realtime_events")
        fping_point_count = self._count_rows(conn, "fping_1s_summary") or self._count_rows(conn, "fping_samples")
        iperf_point_count = self._count_rows(conn, "iperf_intervals")
        channel_busy_columns = self._table_columns(conn, "channel_busy_records")
        channel_busy_count = (
            self._count_rows(conn, "channel_busy_records", "COALESCE(row_index, 1) = 1")
            if "row_index" in channel_busy_columns
            else self._count_rows(conn, "channel_busy_records")
        )
        interface_pps_count = self._count_rows(conn, "interface_rate_samples")
        diagnosis_count = (
            self._count_rows(conn, "analysis_events")
            + self._count_rows(conn, "online_parse_issues")
            + active_segment_count
        )
        return OnlineMrBusinessSummaryDTO(
            session_id=session_id,
            sample_count=sample_count,
            active_count=active_count,
            standby_count=standby_count,
            active_segment_count=active_segment_count,
            switch_count=switch_count,
            fping_point_count=fping_point_count,
            iperf_point_count=iperf_point_count,
            channel_busy_count=channel_busy_count,
            interface_pps_count=interface_pps_count,
            diagnosis_count=diagnosis_count,
            first_sample_time=first_sample_time,
            last_sample_time=last_sample_time,
            estimated_interval_seconds=estimated_interval_seconds,
            time_sync_status=time_sync_status,
            time_sync_avg_offset_ms=time_sync_avg_offset_ms,
            current_radio=int(current.get("radio")) if current.get("radio") is not None else None,
            current_link_state=str(current.get("link_state") or ""),
            current_peer_mac=str(current.get("peer_mac") or ""),
            current_peer_name=str(current.get("peer_name") or ""),
            current_ap_mac=normalize_mac(
                current.get("canonical_ap_mac") or current.get("peer_ap_mac")
            ) or "",
            current_peer_radio_mac=str(current.get("bssid") or ""),
            current_station=str(current.get("belong_station") or ""),
            current_section=str(current.get("belong_section") or ""),
            current_rssi=float(current["mr_rssi"]) if current.get("mr_rssi") is not None else None,
            current_segment_start=str(current_segment.get("start_time") or "") or None,
            current_segment_end=str(current_segment.get("end_time") or "") or None,
            current_segment_duration_seconds=self._duration_seconds(
                current_segment.get("start_time"),
                current_segment.get("end_time"),
            ),
        )

    def _business_table_rows(
        self,
        conn: sqlite3.Connection,
        table: OnlineMrBusinessTable,
        *,
        start_time: str | None,
        end_time: str | None,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        if table == OnlineMrBusinessTable.MAIN_LINK:
            return self._business_main_link_rows(conn, start_time=start_time, end_time=end_time, limit=limit, offset=offset)
        if table == OnlineMrBusinessTable.LINK_DETAIL:
            return self._business_link_detail_rows(conn, start_time=start_time, end_time=end_time, limit=limit, offset=offset)
        if table == OnlineMrBusinessTable.CHANNEL_BUSY:
            return self._business_channel_busy_rows(conn, start_time=start_time, end_time=end_time, limit=limit, offset=offset)
        if table == OnlineMrBusinessTable.SWITCH_HISTORY:
            return self._business_switch_rows(conn, "switch_history_events", start_time=start_time, end_time=end_time, limit=limit, offset=offset)
        if table == OnlineMrBusinessTable.SWITCH_REALTIME:
            return self._business_switch_rows(conn, "switch_realtime_events", start_time=start_time, end_time=end_time, limit=limit, offset=offset)
        if table == OnlineMrBusinessTable.INTERFACE_RATE:
            return self._business_interface_rate_rows(conn, start_time=start_time, end_time=end_time, limit=limit, offset=offset)
        if table == OnlineMrBusinessTable.FPING_1S:
            return self._business_fping_1s_rows(conn, start_time=start_time, end_time=end_time, limit=limit, offset=offset)
        if table == OnlineMrBusinessTable.IPERF:
            return self._business_iperf_rows(conn, start_time=start_time, end_time=end_time, limit=limit, offset=offset)
        if table == OnlineMrBusinessTable.DIAGNOSTICS:
            return self._business_diagnostics_rows(conn, start_time=start_time, end_time=end_time, limit=limit, offset=offset)
        return []

    def _business_main_link_rows(
        self,
        conn: sqlite3.Connection,
        *,
        start_time: str | None,
        end_time: str | None,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        columns = self._table_columns(conn, "main_link_samples")
        if not columns:
            return []
        time_expr = self._time_expr(columns, ("collector_time", "device_time", "device_clock"))
        if not time_expr:
            return []
        where, params = self._time_where(time_expr, start_time, end_time)
        order_by = f"{time_expr} ASC, id ASC" if "id" in columns else f"{time_expr} ASC"

        def make_item(row_data: dict[str, Any]) -> dict[str, Any]:
            device_time = self._text_or_none(row_data.get("device_time") or row_data.get("device_clock"))
            peer_mac = self._text_or_none(row_data.get("peer_mac") or row_data.get("peer_mac_normalized"))
            canonical_ap_mac = normalize_mac(
                row_data.get("canonical_ap_mac") or row_data.get("peer_ap_mac")
            ) or ""
            identity_status = self._text_or_none(row_data.get("identity_status")) or ("matched" if canonical_ap_mac else "unresolved")
            peer_name = self._business_peer_name(
                row_data.get("resolved_peer_name") if canonical_ap_mac else "",
                row_data.get("peer_name") if canonical_ap_mac else "",
            ) or ("未关联" if not canonical_ap_mac else None)
            return {
                "device_time": device_time,
                "radio": row_data.get("radio"),
                "link_state": self._text_or_none(row_data.get("link_state")) or "ACTIVE",
                "peer_name": peer_name,
                "peer_mac": peer_mac,
                "canonical_ap_mac": canonical_ap_mac,
                "identity_status": identity_status,
                "identity_source": row_data.get("identity_source") or "",
                "identity_reason": row_data.get("identity_reason") or ("缺少明确 AP MAC 映射" if not canonical_ap_mac else ""),
                "mr_rssi": row_data.get("mr_rssi"),
                "bssid": self._text_or_none(row_data.get("bssid")),
                "belong_station": self._text_or_none(row_data.get("belong_station")),
                "belong_section": self._text_or_none(row_data.get("belong_section")),
                "online_time": self._text_or_none(row_data.get("online_time")),
            }

        state_filter = "AND UPPER(link_state) LIKE 'ACTIVE%'" if "link_state" in columns else ""
        rows = conn.execute(
            f"""
            SELECT *
            FROM main_link_samples
            WHERE {where}
              {state_filter}
            ORDER BY {order_by}
            LIMIT ? OFFSET ?
            """,
            (*params, limit, offset),
        ).fetchall()
        return [make_item(dict(row)) for row in rows]

    def _business_link_detail_rows(
        self,
        conn: sqlite3.Connection,
        *,
        start_time: str | None,
        end_time: str | None,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        columns = self._table_columns(conn, "main_link_samples")
        if not columns:
            return []
        time_expr = self._time_expr(columns, ("collector_time", "device_time", "device_clock"))
        if not time_expr:
            return []
        where, params = self._time_where(time_expr, start_time, end_time)
        order_by = f"{time_expr} ASC, id ASC" if "id" in columns else f"{time_expr} ASC"
        rows = conn.execute(
            f"""
            SELECT *
            FROM main_link_samples
            WHERE {where}
            ORDER BY {order_by}
            LIMIT ? OFFSET ?
            """,
            (*params, limit, offset),
        ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            row_data = dict(row)
            sample_time = self._text_or_none(row_data.get("collector_time"))
            device_time = self._text_or_none(row_data.get("device_time") or row_data.get("device_clock"))
            peer_mac = self._text_or_none(row_data.get("peer_mac") or row_data.get("peer_mac_normalized"))
            canonical_ap_mac = normalize_mac(
                row_data.get("canonical_ap_mac") or row_data.get("peer_ap_mac")
            ) or ""
            identity_status = self._text_or_none(row_data.get("identity_status")) or ("matched" if canonical_ap_mac else "unresolved")
            peer_name = self._business_peer_name(
                row_data.get("resolved_peer_name") if canonical_ap_mac else "",
                row_data.get("peer_name") if canonical_ap_mac else "",
            ) or ("未关联" if not canonical_ap_mac else None)
            items.append(
                {
                    "sample_time": sample_time,
                    "device_time": device_time,
                    "radio": row_data.get("radio"),
                    "link_state": self._text_or_none(row_data.get("link_state")),
                    "peer_mac": peer_mac,
                    "peer_name": peer_name,
                    "ap_mac": canonical_ap_mac,
                    "canonical_ap_mac": canonical_ap_mac,
                    "identity_status": identity_status,
                    "identity_source": row_data.get("identity_source") or "",
                    "identity_reason": row_data.get("identity_reason") or ("缺少明确 AP MAC 映射" if not canonical_ap_mac else ""),
                    "belong_station": self._text_or_none(row_data.get("belong_station")),
                    "belong_section": self._text_or_none(row_data.get("belong_section")),
                    "mr_rx_signal": row_data.get("mr_rssi") or row_data.get("local_signal_dbm"),
                    "mesh_interface": self._text_or_none(row_data.get("mesh_interface") or row_data.get("bssid")),
                    "online_time": self._text_or_none(row_data.get("online_time")),
                }
            )
        return self._apply_business_paging(items, limit, offset)

    def _business_channel_busy_rows(
        self,
        conn: sqlite3.Connection,
        *,
        start_time: str | None,
        end_time: str | None,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        columns = self._table_columns(conn, "channel_busy_records")
        if not columns:
            return []
        time_expr = self._time_expr(columns, ("device_time", "device_clock"))
        if not time_expr:
            return []
        where, params = self._time_where(time_expr, start_time, end_time)
        if "row_index" in columns:
            where = f"{where} AND COALESCE(row_index, 1) = 1"
        order_by = f"{time_expr} ASC, id ASC" if "id" in columns else f"{time_expr} ASC"
        rows = conn.execute(
            f"""
            SELECT *
            FROM channel_busy_records
            WHERE {where}
            ORDER BY {order_by}
            LIMIT ? OFFSET ?
            """,
            (*params, limit, offset),
        ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            row_data = dict(row)
            items.append(
                {
                    "device_time": self._text_or_none(row_data.get("device_time")),
                    "radio": row_data.get("radio"),
                    "ctl_channel": row_data.get("ctl_channel"),
                    "bandwidth": row_data.get("bandwidth"),
                    "record_interval": row_data.get("record_interval"),
                    "ctl_busy": row_data.get("ctl_busy"),
                    "tx_busy": row_data.get("tx_busy"),
                    "rx_busy": row_data.get("rx_busy"),
                }
            )
        return self._apply_business_paging(items, limit, offset)

    def _business_switch_rows(
        self,
        conn: sqlite3.Connection,
        table: str,
        *,
        start_time: str | None,
        end_time: str | None,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        columns = self._table_columns(conn, table)
        if not columns:
            return []
        time_candidates = ("event_time_local", "event_time_device", "snapshot_collector_time") if table == "switch_history_events" else ("device_time",)
        time_expr = self._time_expr(columns, time_candidates)
        if not time_expr:
            return []
        where, params = self._time_where(time_expr, start_time, end_time)
        order_by = f"{time_expr} ASC, id ASC" if "id" in columns else f"{time_expr} ASC"
        sql = f"""
            SELECT *
            FROM {table}
            WHERE {where}
            ORDER BY {order_by}
            LIMIT ? OFFSET ?
        """
        rows = conn.execute(sql, (*params, limit, offset)).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            row_data = dict(row)
            event_time = self._text_or_none(
                row_data.get("event_time_local")
                or row_data.get("event_time_device")
                or row_data.get("snapshot_collector_time")
                or row_data.get("device_time")
            )
            reason_code = row_data.get("switch_reason_code")
            reason_text = self._switch_reason_text(row_data.get("switch_reason_text"), reason_code)
            if table == "switch_history_events":
                items.append(
                    {
                        "device_switch_time": self._text_or_none(row_data.get("event_time_device")) or event_time,
                        "radio": row_data.get("radio"),
                        "from_peer_name": self._text_or_none(row_data.get("old_peer_name")),
                        "to_peer_name": self._text_or_none(row_data.get("new_peer_name")),
                        "from_rssi": row_data.get("old_rssi"),
                        "to_rssi": row_data.get("new_rssi"),
                        "from_station": self._text_or_none(row_data.get("old_belong_station")),
                        "to_station": self._text_or_none(row_data.get("new_belong_station")),
                        "reason_text": reason_text,
                        "active_duration": self._text_or_none(row_data.get("active_duration")),
                    }
                )
            else:
                items.append(
                    {
                        "device_time": event_time,
                        "device_name": self._text_or_none(row_data.get("device_name")),
                        "radio": row_data.get("radio"),
                        "from_peer_name": self._text_or_none(row_data.get("old_peer_name")),
                        "from_peer_mac": self._text_or_none(row_data.get("old_peer_mac")),
                        "from_rssi": row_data.get("old_rssi"),
                        "from_station": self._text_or_none(row_data.get("old_belong_station")),
                        "from_section": self._text_or_none(row_data.get("old_belong_section")),
                        "to_peer_name": self._text_or_none(row_data.get("new_peer_name")),
                        "to_peer_mac": self._text_or_none(row_data.get("new_peer_mac")),
                        "to_rssi": row_data.get("new_rssi"),
                        "to_station": self._text_or_none(row_data.get("new_belong_station")),
                        "to_section": self._text_or_none(row_data.get("new_belong_section")),
                        "peer_quantity": row_data.get("peer_quantity"),
                        "link_quantity": row_data.get("link_quantity"),
                        "reason_code": reason_code,
                        "reason_text": reason_text,
                    }
                )
        return self._apply_business_paging(items, limit, offset)

    def _business_interface_rate_rows(
        self,
        conn: sqlite3.Connection,
        *,
        start_time: str | None,
        end_time: str | None,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        columns = self._table_columns(conn, "interface_rate_samples")
        if not columns:
            return []
        time_expr = self._time_expr(columns, ("device_time", "device_clock"))
        if not time_expr:
            return []
        where, params = self._time_where(time_expr, start_time, end_time)
        order_by = f"{time_expr} ASC, id ASC" if "id" in columns else f"{time_expr} ASC"
        rows = conn.execute(
            f"""
            SELECT *
            FROM interface_rate_samples
            WHERE {where}
            ORDER BY {order_by}
            LIMIT ? OFFSET ?
            """,
            (*params, limit, offset),
        ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            row_data = dict(row)
            items.append(
                {
                    "device_time": self._text_or_none(row_data.get("device_time")),
                    "interface": self._text_or_none(row_data.get("interface_normalized") or row_data.get("interface_name")),
                    "direction": self._interface_direction_label(row_data.get("direction")),
                    "total_pps": row_data.get("total_pps"),
                    "broadcast_pps": row_data.get("broadcast_pps"),
                    "multicast_pps": row_data.get("multicast_pps"),
                    "usage_percent": row_data.get("usage_percent"),
                }
            )
        return self._apply_business_paging(items, limit, offset)

    def _business_fping_1s_rows(
        self,
        conn: sqlite3.Connection,
        *,
        start_time: str | None,
        end_time: str | None,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        columns = self._table_columns(conn, "fping_1s_summary")
        if not columns:
            return []
        time_expr = self._time_expr(columns, ("device_bucket_time", "bucket_time", "local_bucket_time"))
        if not time_expr:
            return []
        where, params = self._time_where(time_expr, start_time, end_time)
        order_by = f"{time_expr} ASC, target_ip ASC, id ASC" if "id" in columns and "target_ip" in columns else f"{time_expr} ASC"
        rows = conn.execute(
            f"""
            SELECT *
            FROM fping_1s_summary
            WHERE {where}
            ORDER BY {order_by}
            LIMIT ? OFFSET ?
            """,
            (*params, limit, offset),
        ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            row_data = dict(row)
            sent = row_data.get("sent")
            received = row_data.get("received")
            lost = row_data.get("lost")
            loss_count = lost if lost is not None else (sent - received if sent is not None and received is not None else None)
            status = self._fping_status_label(row_data.get("status"))
            if sent and received == 0:
                status = "全部丢包"
            elif loss_count:
                status = "部分丢包"
            items.append(
                {
                    "time": self._text_or_none(row_data.get("bucket_time") or row_data.get("local_bucket_time") or row_data.get("device_bucket_time")),
                    "device_time": self._text_or_none(row_data.get("device_bucket_time")),
                    "local_time": self._text_or_none(row_data.get("local_bucket_time")),
                    "target_ip": self._text_or_none(row_data.get("target_ip")),
                    "sent": sent,
                    "received": received,
                    "loss_count": loss_count,
                    "loss_rate": row_data.get("loss_percent"),
                    "avg_rtt": row_data.get("avg_latency_ms"),
                    "min_rtt": row_data.get("min_latency_ms"),
                    "max_rtt": row_data.get("max_latency_ms"),
                    "jitter_ms": row_data.get("jitter_ms"),
                    "status": status,
                }
            )
        return self._apply_business_paging(items, limit, offset)

    def _business_iperf_rows(
        self,
        conn: sqlite3.Connection,
        *,
        start_time: str | None,
        end_time: str | None,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        columns = self._table_columns(conn, "iperf_intervals")
        if not columns:
            return []
        time_expr = self._time_expr(columns, ("device_interval_center_time", "device_aligned_time", "interval_center_time", "collector_time"))
        if not time_expr:
            return []
        where, params = self._time_where(time_expr, start_time, end_time)
        order_by = f"{time_expr} ASC, id ASC" if "id" in columns else f"{time_expr} ASC"
        rows = conn.execute(
            f"""
            SELECT *
            FROM iperf_intervals
            WHERE {where}
            ORDER BY {order_by}
            LIMIT ? OFFSET ?
            """,
            (*params, limit, offset),
        ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            row_data = dict(row)
            sample_time = self._text_or_none(
                row_data.get("interval_center_time") or row_data.get("collector_time")
            )
            items.append(
                {
                    "local_time": sample_time,
                    "runtime": self._iperf_runtime_label(row_data.get("interval_start_sec"), row_data.get("interval_end_sec")),
                    "transfer": self._transfer_label(row_data.get("transfer_bytes")),
                    "bitrate": self._mbps_label(row_data.get("bitrate_mbps")),
                    "jitter_ms": row_data.get("jitter_ms"),
                    "lost_packets": row_data.get("lost_packets"),
                    "total_packets": row_data.get("total_packets"),
                    "loss_percent": row_data.get("loss_percent"),
                }
            )
        return self._apply_business_paging(items, limit, offset)

    def _business_diagnostics_rows(
        self,
        conn: sqlite3.Connection,
        *,
        start_time: str | None,
        end_time: str | None,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        analysis_columns = self._table_columns(conn, "analysis_events")
        if analysis_columns:
            time_expr = self._time_expr(analysis_columns, ("collector_time",))
            if time_expr:
                where, params = self._time_where(time_expr, start_time, end_time)
                order_by = f"{time_expr} ASC, id ASC" if "id" in analysis_columns else f"{time_expr} ASC"
                rows = conn.execute(
                    f"""
                    SELECT *
                    FROM analysis_events
                    WHERE {where}
                    ORDER BY {order_by}
                    LIMIT ? OFFSET ?
                    """,
                    (*params, limit + 1, offset),
                ).fetchall()
                for row in rows:
                    row_data = dict(row)
                    details = self._json_object(row_data.get("details_json"))
                    items.append(
                        {
                            "sample_time": self._text_or_none(row_data.get("collector_time")),
                            "start_time": self._text_or_none(row_data.get("collector_time")),
                            "end_time": self._text_or_none(details.get("end_time")),
                            "issue_type": self._text_or_none(row_data.get("event_type")),
                            "severity": self._text_or_none(row_data.get("severity")),
                            "summary": self._text_or_none(row_data.get("summary_text")),
                            "description": self._text_or_none(details.get("description") or details.get("summary") or row_data.get("summary_text")),
                            "radio": details.get("radio"),
                            "peer_name": self._text_or_none(details.get("peer_name") or details.get("active_peer") or details.get("peer_mac")),
                            "peer_mac": self._text_or_none(details.get("peer_mac")),
                            "station": self._text_or_none(details.get("station")),
                            "section": self._text_or_none(details.get("section")),
                            "evidence": self._text_or_none(row_data.get("raw_file")),
                            "raw_file": self._text_or_none(row_data.get("raw_file")),
                            "raw_line_start": row_data.get("raw_line_start"),
                            "raw_line_end": row_data.get("raw_line_end"),
                            "recommendation": self._text_or_none(details.get("recommendation")),
                        }
                    )
        issue_columns = self._table_columns(conn, "online_parse_issues")
        if issue_columns:
            order_by = "raw_file ASC, line_number ASC, id ASC" if "id" in issue_columns else "raw_file ASC, line_number ASC"
            rows = conn.execute(
                f"""
                SELECT *
                FROM online_parse_issues
                ORDER BY {order_by}
                LIMIT ? OFFSET ?
                """,
                (limit + 1, offset),
            ).fetchall()
            for row in rows:
                row_data = dict(row)
                items.append(
                    {
                        "sample_time": None,
                        "start_time": None,
                        "end_time": None,
                        "issue_type": self._text_or_none(row_data.get("issue_type")),
                        "severity": self._text_or_none(row_data.get("severity")),
                        "summary": self._text_or_none(row_data.get("message")),
                        "description": self._text_or_none(row_data.get("raw_text")),
                        "radio": None,
                        "peer_name": "",
                        "peer_mac": "",
                        "station": "",
                        "section": "",
                        "evidence": self._text_or_none(row_data.get("raw_file")),
                        "raw_file": self._text_or_none(row_data.get("raw_file")),
                        "raw_line_start": row_data.get("line_number"),
                        "raw_line_end": row_data.get("line_number"),
                        "recommendation": "",
                    }
                )
        return self._apply_business_paging(items, limit, offset)

    @staticmethod
    def _strip_business_source_fields(row: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in row.items() if key not in _BUSINESS_SOURCE_FIELDS}

    def _apply_business_paging(self, rows: list[dict[str, Any]], limit: int, offset: int) -> list[dict[str, Any]]:
        return rows[:limit]

    @classmethod
    def _business_peer_name(cls, *candidates: object) -> str | None:
        for candidate in candidates:
            text = cls._text_or_none(candidate)
            if text and not cls._is_mac_like(text):
                return text
        return None

    @staticmethod
    def _is_mac_like(value: object) -> bool:
        text = str(value or "").strip()
        compact = re.sub(r"[^0-9A-Fa-f]", "", text)
        return len(compact) == 12 and bool(re.fullmatch(r"[0-9A-Fa-f:.-]+", text))

    @classmethod
    def _switch_reason_text(cls, reason: object, code: object) -> str | None:
        text = cls._text_or_none(reason)
        if text:
            return text
        code_text = cls._text_or_none(code)
        return f"未知原因码：{code_text}" if code_text else None

    @staticmethod
    def _interface_direction_label(value: object) -> str | None:
        text = str(value or "").strip().lower()
        if text in {"in", "inbound", "rx", "receive", "received", "input"}:
            return "接收"
        if text in {"out", "outbound", "tx", "send", "sent", "output"}:
            return "发送"
        return OnlineMrQueryService._text_or_none(value)

    @staticmethod
    def _fping_status_label(value: object) -> str | None:
        text = str(value or "").strip()
        if not text:
            return None
        upper = text.upper()
        if upper in {"OK", "SUCCESS", "NORMAL"}:
            return "正常"
        if upper in {"LOSS", "PARTIAL_LOSS"}:
            return "丢包"
        if upper in {"TIMEOUT", "FAILED", "ERROR"}:
            return "超时"
        return OnlineMrQueryService._text_or_none(value)

    @staticmethod
    def _iperf_runtime_label(start: object, end: object) -> str | None:
        start_value = OnlineMrQueryService._float_or_none(start)
        end_value = OnlineMrQueryService._float_or_none(end)
        if start_value is None or end_value is None:
            return None
        return f"{start_value:.2f}-{end_value:.2f} s"

    @staticmethod
    def _transfer_label(value: object) -> str | None:
        number = OnlineMrQueryService._float_or_none(value)
        if number is None:
            return None
        units = ("B", "KiB", "MiB", "GiB")
        index = 0
        while abs(number) >= 1024 and index < len(units) - 1:
            number /= 1024.0
            index += 1
        return f"{number:.2f} {units[index]}"

    @staticmethod
    def _mbps_label(value: object) -> str | None:
        number = OnlineMrQueryService._float_or_none(value)
        if number is None:
            return None
        return f"{number:g} Mbps"

    def _time_expr(self, columns: set[str], candidates: Iterable[str]) -> str | None:
        parts = [f"NULLIF({name}, '')" for name in candidates if name in columns]
        if not parts:
            return None
        if len(parts) == 1:
            return parts[0]
        return f"COALESCE({', '.join(parts)})"

    def _time_bounds(self, conn: sqlite3.Connection, table: str, time_expr: str | None) -> tuple[str | None, str | None]:
        if not time_expr or not self._table_columns(conn, table):
            return None, None
        row = conn.execute(f"SELECT MIN({time_expr}), MAX({time_expr}) FROM {table}").fetchone()
        return self._text_or_none(row[0]) if row and row[0] is not None else None, self._text_or_none(row[1]) if row and row[1] is not None else None

    def _estimated_interval_seconds(self, conn: sqlite3.Connection, table: str, time_expr: str | None) -> float | None:
        if not time_expr or not self._table_columns(conn, table):
            return None
        rows = conn.execute(
            f"SELECT {time_expr} AS sample_time FROM {table} WHERE {time_expr} IS NOT NULL ORDER BY sample_time ASC, id ASC LIMIT 2000"
        ).fetchall()
        stamps = [self._as_datetime(self._text_or_none(row[0])) for row in rows]
        values = [stamp for stamp in stamps if stamp is not None]
        if len(values) < 2:
            return None
        deltas = [
            (right - left).total_seconds()
            for left, right in zip(values, values[1:])
            if right > left
        ]
        if not deltas:
            return None
        return round(sum(deltas) / len(deltas), 3)

    def _time_where(self, time_expr: str, start_time: str | None, end_time: str | None, *, table_alias: str | None = None) -> tuple[str, list[Any]]:
        prefix = f"{table_alias}." if table_alias else ""
        where = [f"{prefix}{time_expr} IS NOT NULL"]
        params: list[Any] = []
        if start_time:
            where.append(f"{prefix}{time_expr} >= ?")
            params.append(start_time)
        if end_time:
            where.append(f"{prefix}{time_expr} <= ?")
            params.append(end_time)
        return " AND ".join(where), params

    def _count_rows(self, conn: sqlite3.Connection, table: str, where: str | None = None, params: tuple[object, ...] = ()) -> int:
        if not self._table_columns(conn, table):
            return 0
        sql = f"SELECT COUNT(*) FROM {table}"
        if where:
            sql = f"{sql} WHERE {where}"
        row = conn.execute(sql, params).fetchone()
        return int(row[0] or 0) if row else 0

    def _latest_active_link_row(self, conn: sqlite3.Connection, columns: set[str], time_expr: str | None) -> dict[str, Any]:
        if not columns:
            return {}
        select_columns = [
            name
            for name in (
                "collector_time",
                "device_time",
                "device_clock",
                "radio",
                "link_state",
                "peer_mac",
                "peer_mac_normalized",
                "resolved_peer_name",
                "peer_ap_mac",
                "canonical_ap_mac",
                "peer_radio_mac",
                "identity_status",
                "identity_source",
                "identity_reason",
                "peer_name",
                "mr_rssi",
                "bssid",
                "mesh_interface",
                "belong_station",
                "belong_section",
                "belong_type",
                "belonging_source",
                "online_time",
            )
            if name in columns
        ]
        if not select_columns:
            return {}
        time_order = time_expr or ("id" if "id" in columns else select_columns[0])
        order_by = f"{time_order} DESC, id DESC" if "id" in columns else f"{time_order} DESC"
        where = "WHERE UPPER(link_state) LIKE 'ACTIVE%'" if "link_state" in columns else ""
        row = conn.execute(
            f"""
            SELECT {', '.join(select_columns)}
            FROM main_link_samples
            {where}
            ORDER BY {order_by}
            LIMIT 1
            """
        ).fetchone()
        if not row:
            return {}
        return dict(row)

    def _latest_segment_row(self, conn: sqlite3.Connection, columns: set[str]) -> dict[str, Any]:
        if not columns:
            return {}
        row = conn.execute(
            """
            SELECT *
            FROM active_segments
            ORDER BY COALESCE(NULLIF(end_time, ''), NULLIF(start_time, '')) DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
        return dict(row) if row else {}

    def _time_sync_summary(self, conn: sqlite3.Connection) -> tuple[str, float | None]:
        columns = self._table_columns(conn, "time_sync_samples")
        if not columns:
            return "unknown", None
        row = conn.execute("SELECT COUNT(*), AVG(offset_ms) FROM time_sync_samples").fetchone()
        count = int(row[0] or 0) if row else 0
        avg_offset = float(row[1]) if row and row[1] is not None else None
        if count <= 0:
            return "unknown", None
        return "已建立", avg_offset

    @staticmethod
    def _duration_seconds(start: object, end: object) -> float | None:
        start_time = OnlineMrQueryService._as_datetime(start) if not isinstance(start, datetime) else start
        end_time = OnlineMrQueryService._as_datetime(end) if not isinstance(end, datetime) else end
        if start_time is None or end_time is None:
            return None
        return round(max(0.0, (end_time - start_time).total_seconds()), 3)

    @staticmethod
    def _switch_severity(reason: object, code: object) -> str:
        text = str(reason or "").casefold()
        code_text = str(code or "").strip()
        if code_text in {"4", "5"} or "fault" in text or "断开" in text or "强制" in text:
            return "warning"
        if "better" in text or "rssi" in text:
            return "info"
        return "info"

    @staticmethod
    def _stat_delta(value: object, rows: list[sqlite3.Row], metric_name: str) -> float | None:
        values = [
            float(row["metric_value"])
            for row in rows
            if str(row["metric_name"] or "") == metric_name and row["metric_value"] is not None
        ]
        if not values:
            return None
        if len(values) == 1:
            return values[0]
        return round(values[-1] - values[0], 3)

    @staticmethod
    def _float_or_none(value: object) -> float | None:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @classmethod
    def _counter_sum(cls, values: dict[str, object], keys: Iterable[str]) -> float | None:
        numbers = [number for key in keys if (number := cls._float_or_none(values.get(key))) is not None]
        return sum(numbers) if numbers else None

    @classmethod
    def _counter_delta(cls, current: object, previous: object) -> float | None:
        current_value = cls._float_or_none(current)
        previous_value = cls._float_or_none(previous)
        if current_value is None or previous_value is None:
            return None
        delta = current_value - previous_value
        return round(delta, 3) if delta >= 0 else None

    @staticmethod
    def _iperf_local_endpoint(row: sqlite3.Row) -> str:
        parts = [str(value) for value in (row["device_id"], row["parallel"]) if value not in (None, "")]
        return ":".join(parts) if parts else ""

    @staticmethod
    def _iperf_remote_endpoint(row: sqlite3.Row) -> str:
        host = str(row["server_ip"] or "")
        port = str(row["port"] or "")
        if host and port:
            return f"{host}:{port}"
        return host or port

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
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='online_schema_meta'").fetchone():
            columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(online_schema_meta)")}
            if {"key", "value"}.issubset(columns):
                row = conn.execute("SELECT value FROM online_schema_meta WHERE key = 'schema_version' LIMIT 1").fetchone()
                if row and row[0] not in (None, ""):
                    return str(row[0])
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
        selects.extend(f"{name} AS dim_{name}" for name in available_dimensions)
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
            dimension_values = {name: row[f"dim_{name}"] for name in available_dimensions if row[f"dim_{name}"] not in (None, "")}
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
            "new_peer_name, new_peer_mac, new_rssi, switch_reason_text "
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
                "new_peer_name, new_peer_mac, new_rssi, switch_reason_text "
                "FROM switch_realtime_events "
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
