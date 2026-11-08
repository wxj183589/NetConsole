"""Read-only workbench over Ground's existing durable indexes.

Raw Syslog entries here are registered files, not individual datagrams. Their
record count, revision, digest and archive location remain visible in details;
the existing raw-query service owns record-level access.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator


HISTORY_DATA_TYPES = (
    "run", "train", "heartbeat", "quick_ping", "syslog_raw", "syslog_parsed",
    "ac_snapshot", "deep", "timeline",
)


class GroundHistoryQueryError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.code, self.message, self.status_code = code, message, status_code


@dataclass(frozen=True)
class _Source:
    data_type: str
    table: str
    identity: str
    timestamp: str
    train: str = "''"
    mr: str = "''"
    role: str = "''"
    status: str = "''"
    summary: str = "''"
    event: str = "''"
    predicate: str = "1=1"


_SOURCES = (
    _Source("run", "runs", "s.run_id", "COALESCE(NULLIF(s.actual_started_at,''),s.created_at)", status="s.state", summary="s.run_date || ' ' || s.state"),
    _Source("train", "train_runs", "s.run_id || ':' || s.train_id", "s.updated_at", train="s.train_id", status="s.coverage_status", summary="s.train_no || ' ' || s.coverage_status"),
    _Source("heartbeat", "ping_summaries", "CAST(s.id AS TEXT)", "s.bucket_start", train="s.train_id", mr="s.mr_id", role="s.mr_position_code", status="'AGGREGATE'", summary="s.target_ip || ' ' || s.bucket_kind || ' sent=' || s.sent_count || ' lost=' || s.loss_count"),
    _Source("heartbeat", "heartbeat_states", "s.run_id || ':' || s.entity_id", "s.updated_at", train="COALESCE(json_extract(s.snapshot_json,'$.train_id'),'')", mr="s.entity_id", role="COALESCE(json_extract(s.snapshot_json,'$.role'),'')", status="s.status", summary="'MR ' || s.entity_id || ' ' || s.status", predicate="s.entity_type='MR'"),
    _Source("quick_ping", "quick_ping_runs", "s.run_id", "s.started_at", status="s.state", summary="s.run_id || ' ' || s.state"),
    _Source("syslog_raw", "raw_files", "s.file_id", "s.start_time", train="s.train_id", mr="s.device_uuid", role="s.mr_role", status="s.status", summary="s.relative_path || ' (' || s.record_count || ' records)'", predicate="s.data_type='syslog'"),
    _Source("syslog_parsed", "wmesh_events", "CAST(s.id AS TEXT)", "s.receive_time", train="s.train_id", mr="s.device_uuid", role="s.mr_role", status="s.data_quality", summary="s.event_type || ' ' || s.hostname", event="s.event_type"),
    _Source("ac_snapshot", "ac_snapshots", "CAST(s.id AS TEXT)", "s.received_at", train="s.train_id", mr="s.mr_id", role="s.mr_position_code", status="s.freshness_status", summary="s.peer_ap_name || ' ' || s.mr_online_status"),
    _Source("deep", "deep_operations", "s.operation_id", "s.started_at", train="s.train_id", mr="s.mr_id", role="s.mr_position_code", status="s.state", summary="s.session_id || ' ' || s.state"),
    _Source("timeline", "events", "CAST(s.id AS TEXT)", "s.ts", train="s.train_id", mr="s.mr_id", role="COALESCE(NULLIF(json_extract(s.details_json,'$.mr_role'),''),json_extract(s.details_json,'$.mr_position_code'),'')", status="s.severity", summary="s.title || ' ' || s.message", event="s.event_type"),
)


class GroundHistoryQueryService:
    def __init__(self, db_path: Path, *, site_id: str) -> None:
        # Construction must work inside Export Process without creating a DB,
        # a directory, a schema or another collection runtime.
        self.db_path = Path(db_path)
        self.site_id = str(site_id)

    @contextmanager
    def _read_snapshot(self) -> Iterator[sqlite3.Connection | None]:
        if not self.db_path.is_file():
            yield None
            return
        connection = sqlite3.connect(self.db_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=15)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            yield connection
        except sqlite3.DatabaseError as exc:
            raise GroundHistoryQueryError("GROUND_HISTORY_INDEX_UNREADABLE", "历史索引无法读取", status_code=503) from exc
        finally:
            connection.rollback()
            connection.close()

    @staticmethod
    def _validate(filters: dict[str, Any]) -> None:
        if filters["data_type"] and filters["data_type"] not in HISTORY_DATA_TYPES:
            raise GroundHistoryQueryError("GROUND_HISTORY_TYPE_INVALID", "历史数据类型无效")
        if filters["mr_role"] and filters["mr_role"] not in {"CT", "CW"}:
            raise GroundHistoryQueryError("GROUND_HISTORY_ROLE_INVALID", "MR 角色必须为 CT 或 CW")
        if filters["sort_order"] not in {"asc", "desc"}:
            raise GroundHistoryQueryError("GROUND_HISTORY_SORT_INVALID", "历史排序必须为 asc 或 desc")
        times = []
        for name in ("start_at", "end_at"):
            value = filters[name]
            if not value:
                times.append(None)
                continue
            try:
                stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if stamp.tzinfo is None:
                    raise ValueError("timezone required")
                times.append(stamp)
            except (ValueError, TypeError) as exc:
                raise GroundHistoryQueryError("GROUND_HISTORY_TIME_INVALID", "历史时间范围必须包含时区") from exc
        if all(times) and times[0] > times[1]:
            raise GroundHistoryQueryError("GROUND_HISTORY_TIME_RANGE_INVALID", "历史开始时间不能晚于结束时间")

    @staticmethod
    def validate_filters(
        *, data_type: str = "", run_id: str = "", train_id: str = "", mr_id: str = "",
        mr_role: str = "", event_type: str = "", start_at: str = "", end_at: str = "",
        sort_order: str = "desc",
    ) -> None:
        """Validate export submission without opening/counting the index."""
        GroundHistoryQueryService._validate(dict(locals()))

    def _plan(self, conn: sqlite3.Connection, filters: dict[str, Any]) -> tuple[str, list[Any], list[tuple[str, list[Any]]], dict[str, str]]:
        tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        sources = {name: "UNAVAILABLE" for name in HISTORY_DATA_TYPES}
        queries: list[str] = []
        params: list[Any] = []
        counts: list[tuple[str, list[Any]]] = []
        for source in _SOURCES:
            table = "ground_unattended_" + source.table
            if table not in tables:
                continue
            sources[source.data_type] = "AVAILABLE"
            if filters["data_type"] and source.data_type != filters["data_type"]:
                continue
            where = ["s.site_id=?", source.predicate]
            values: list[Any] = [self.site_id]
            if filters["run_id"]:
                where.append("s.run_id=?")
                values.append(filters["run_id"])
            for name, operator in (("start_at", ">="), ("end_at", "<=")):
                if filters[name]:
                    where.append(f"julianday({source.timestamp}){operator}julianday(?)")
                    values.append(filters[name])
            if filters["event_type"]:
                where.append(f"{source.event}=?")
                values.append(filters["event_type"])
            self._identity_filter(source, filters, where, values)
            base = f"FROM {table} s WHERE " + " AND ".join(where)
            counts.append(("SELECT COUNT(*) " + base, values))
            queries.append(
                f"SELECT s.rowid AS source_rowid, '{table}' AS source_table, "
                f"'{source.data_type}' AS data_type, {source.identity} AS source_identity, "
                f"{source.timestamp} AS ts, s.run_id, {source.train} AS train_id, "
                f"{source.mr} AS mr_id, {source.role} AS mr_role, {source.status} AS status, "
                f"{source.summary} AS summary, {source.event} AS event_type " + base
            )
            params.extend(values)
        return " UNION ALL ".join(queries), params, counts, sources

    @staticmethod
    def _identity_filter(source: _Source, filters: dict[str, Any], where: list[str], params: list[Any]) -> None:
        if source.data_type == "quick_ping":
            fields = [("train_id", "train_id"), ("mr_id", "mr_id"), ("mr_role", "mr_role")]
            clauses = []
            for name, key in fields:
                if filters[name]:
                    clauses.append(f"json_extract(target.value,'$.{key}')=?")
                    params.append(filters[name])
            if clauses:
                where.append("EXISTS (SELECT 1 FROM json_each(s.targets_json) target WHERE " + " AND ".join(clauses) + ")")
            return
        if source.data_type in {"run", "train"}:
            clauses = []
            if filters["train_id"]:
                clauses.append("t.train_id=?")
                params.append(filters["train_id"])
            endpoints = []
            for name, expression in (
                ("mr_id", "COALESCE(json_extract(e.value,'$.mr_id'),json_extract(e.value,'$.device_uuid'),'')"),
                ("mr_role", "COALESCE(json_extract(e.value,'$.endpoint'),json_extract(e.value,'$.mr_role'),json_extract(e.value,'$.mr_position_code'),'')"),
            ):
                if filters[name]:
                    endpoints.append(expression + "=?")
                    params.append(filters[name])
            if endpoints:
                clauses.append("EXISTS (SELECT 1 FROM json_each(t.endpoints_json) e WHERE " + " AND ".join(endpoints) + ")")
            if clauses:
                identity = "t.site_id=s.site_id AND t.run_id=s.run_id"
                if source.data_type == "train":
                    identity += " AND t.train_id=s.train_id"
                where.append("EXISTS (SELECT 1 FROM ground_unattended_train_runs t WHERE " + identity + " AND " + " AND ".join(clauses) + ")")
            return
        for name, expression in (("train_id", source.train), ("mr_id", source.mr), ("mr_role", source.role)):
            if filters[name]:
                where.append(expression + "=?")
                params.append(filters[name])

    def _item(self, conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        # Table names originate exclusively from the source whitelist above.
        raw = conn.execute(f"SELECT * FROM {row['source_table']} WHERE rowid=? AND site_id=?", (row["source_rowid"], self.site_id)).fetchone()
        details: dict[str, Any] = {}
        for key, value in dict(raw or {}).items():
            if key.endswith("_json"):
                try:
                    details[key[:-5]] = json.loads(value)
                except (ValueError, TypeError):
                    details[key[:-5]] = value
            else:
                details[key] = value
        return {
            "record_id": f"{row['source_table']}:{row['source_identity']}",
            **{key: str(row[key] or "") for key in ("data_type", "ts", "run_id", "train_id", "mr_id", "mr_role", "status", "summary", "event_type")},
            "details": details,
        }

    def query(
        self, *, data_type: str = "", run_id: str = "", train_id: str = "", mr_id: str = "",
        mr_role: str = "", event_type: str = "", start_at: str = "", end_at: str = "",
        sort_order: str = "desc",
        page: int = 1, page_size: int = 100,
    ) -> dict[str, Any]:
        filters = {name: value for name, value in locals().items() if name not in {"self", "page", "page_size"}}
        self._validate(filters)
        page, page_size = max(1, int(page)), max(1, min(500, int(page_size)))
        result: dict[str, Any] = {"items": [], "total": 0, "page": page, "page_size": page_size, "sources": {name: "UNAVAILABLE" for name in HISTORY_DATA_TYPES}}
        with self._read_snapshot() as conn:
            if conn is None:
                return result
            sql, params, counts, result["sources"] = self._plan(conn, filters)
            result["total"] = sum(int(conn.execute(query, values).fetchone()[0]) for query, values in counts)
            if sql:
                rows = conn.execute("SELECT * FROM (" + sql + f") ORDER BY julianday(ts) {sort_order.upper()}, data_type, source_table, source_identity LIMIT ? OFFSET ?", (*params, page_size, (page - 1) * page_size)).fetchall()
                result["items"] = [self._item(conn, row) for row in rows]
        return result

    def iter_export_rows(
        self, *, data_type: str = "", run_id: str = "", train_id: str = "", mr_id: str = "",
        mr_role: str = "", event_type: str = "", start_at: str = "", end_at: str = "",
        sort_order: str = "desc",
    ) -> Iterator[dict[str, Any]]:
        """Export every matching indexed row in one read snapshot, without page caps."""
        filters = {name: value for name, value in locals().items() if name != "self"}
        self._validate(filters)
        with self._read_snapshot() as conn:
            if conn is None:
                return
            sql, params, _counts, _sources = self._plan(conn, filters)
            if not sql:
                return
            cursor = conn.execute("SELECT * FROM (" + sql + f") ORDER BY julianday(ts) {sort_order.upper()}, data_type, source_table, source_identity", params)
            while rows := cursor.fetchmany(500):
                for row in rows:
                    yield self._item(conn, row)
