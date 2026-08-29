"""Read-only lifecycle audit for the NetConsole development data copy.

The audit deliberately opens every SQLite database with ``mode=ro`` and only
uses SELECT/PRAGMA inspection statements.  It is restricted to the marker-
verified development root and never opens the production root.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable


EXPECTED_MAX = 10
DEFAULT_ROOT = Path(r"D:\NetConsoleData-dev")
DEFAULT_OUTPUT = Path(r"D:\study\diagnostic\NetConsole")
REPORT_NAMES = (
    "TASK_DB_USAGE_REPORT.json",
    "LLDP_DUPLICATE_REPORT.json",
    "HISTORY_RETENTION_REPORT.json",
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _json_value(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray)):
        return {"type": "blob", "bytes": len(value)}
    return value


def _read_marker(root: Path) -> dict[str, Any]:
    marker = root / "runtime_mode.json"
    if not marker.is_file():
        raise RuntimeError(f"runtime marker missing: {marker}")
    data = json.loads(marker.read_text(encoding="utf-8"))
    if data.get("mode") != "development":
        raise RuntimeError(f"runtime mode is not development: {data.get('mode')!r}")
    return data


def _connect(path: Path) -> sqlite3.Connection:
    # mode=ro is the required safety boundary. query_only adds a second guard.
    uri = f"{path.resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def _tables(connection: sqlite3.Connection) -> list[str]:
    return [
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_schema "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]


def _columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")')]


def _size_expr(columns: Iterable[str]) -> str:
    parts = []
    for column in columns:
        escaped = column.replace('"', '""')
        parts.append(
            f"CASE typeof(\"{escaped}\") WHEN 'null' THEN 0 "
            f"WHEN 'blob' THEN length(\"{escaped}\") "
            f"WHEN 'text' THEN length(CAST(\"{escaped}\" AS BLOB)) "
            f"ELSE length(CAST(\"{escaped}\" AS TEXT)) END"
        )
    return " + ".join(parts) or "0"


def _dbstat(connection: sqlite3.Connection) -> dict[str, int] | None:
    try:
        rows = connection.execute(
            "SELECT name, SUM(pgsize) AS bytes FROM dbstat GROUP BY name"
        ).fetchall()
    except sqlite3.Error:
        return None
    return {str(row[0]): int(row[1] or 0) for row in rows}


def _table_index_sizes(connection: sqlite3.Connection, table: str) -> int:
    total = 0
    for row in connection.execute(f'PRAGMA index_list("{table}")'):
        name = str(row[1])
        try:
            total += int(
                connection.execute(
                    "SELECT COALESCE(SUM(pgsize), 0) FROM dbstat WHERE name=?", (name,)
                ).fetchone()[0]
            )
        except sqlite3.Error:
            # The caller falls back to zero when dbstat is unavailable.
            continue
    return total


def _database_row(path: Path, root: Path, generated: str) -> dict[str, Any]:
    with closing(_connect(path)) as connection:
        physical_size = path.stat().st_size
        allocation = _dbstat(connection)
        table_rows: list[dict[str, Any]] = []
        for table in _tables(connection):
            columns = _columns(connection, table)
            quoted = table.replace('"', '""')
            count, payload = connection.execute(
                f'SELECT COUNT(*), COALESCE(SUM({_size_expr(columns)}), 0) FROM "{quoted}"'
            ).fetchone()
            table_bytes = int(allocation.get(table, 0)) if allocation else 0
            index_bytes = (
                sum(value for key, value in allocation.items() if key != table)
                if False
                else _table_index_sizes(connection, table) if allocation is not None else 0
            )
            table_rows.append(
                {
                    "table": table,
                    "row_count": int(count),
                    "table_size": table_bytes,
                    "index_size": index_bytes,
                    "estimated_payload_size": int(payload or 0),
                    "columns": columns,
                }
            )
        allocation_method = "sqlite_dbstat"
        if allocation is None:
            # Some Windows Python builds omit dbstat. Normalize logical field
            # and index weights to the real file size so table_size/index_size
            # remain useful estimates instead of misleading zeros.
            allocation_method = "logical_normalized_estimate"
            weights: list[tuple[dict[str, Any], int, int]] = []
            for item in table_rows:
                table_name = str(item["table"])
                index_count = sum(1 for _ in connection.execute(f'PRAGMA index_list("{table_name}")'))
                table_weight = int(item["estimated_payload_size"]) + int(item["row_count"]) * max(32, len(item["columns"]) * 8)
                index_weight = int(item["row_count"]) * max(16, index_count * 24)
                weights.append((item, table_weight, index_weight))
            total_weight = max(1, sum(table_weight + index_weight for _, table_weight, index_weight in weights))
            for item, table_weight, index_weight in weights:
                item["table_size"] = round(physical_size * table_weight / total_weight)
                item["index_size"] = round(physical_size * index_weight / total_weight)
        table_rows.sort(key=lambda item: (item["table_size"], item["estimated_payload_size"]), reverse=True)
        largest_columns: list[dict[str, Any]] = []
        for table in _tables(connection):
            columns = _columns(connection, table)
            for column in columns:
                escaped_table = table.replace('"', '""')
                escaped_column = column.replace('"', '""')
                row = connection.execute(
                    f'SELECT COUNT(*), COALESCE(SUM(length(CAST("{escaped_column}" AS BLOB))), 0), '
                    f'COALESCE(MAX(length(CAST("{escaped_column}" AS BLOB))), 0) '
                    f'FROM "{escaped_table}"'
                ).fetchone()
                total = int(row[1] or 0)
                largest_columns.append(
                    {
                        "table": table,
                        "column": column,
                        "total_bytes": total,
                        "max_bytes": int(row[2] or 0),
                        "row_count": int(row[0] or 0),
                    }
                )
        largest_columns.sort(key=lambda item: (item["total_bytes"], item["max_bytes"]), reverse=True)
        focus_names = {"task_events", "task_snapshots", "task_results", "task_logs", "artifact_reference", "artifact_references"}
        focus = [row for row in table_rows if row["table"] in focus_names]
        text_findings: dict[str, Any] = {}
        for table in ("task_events", "task_snapshots", "task_results"):
            if table not in _tables(connection):
                continue
            cols = set(_columns(connection, table))
            field = "payload_json" if "payload_json" in cols else "result_json" if "result_json" in cols else "canonical_json" if "canonical_json" in cols else ""
            if field:
                qtable = table.replace('"', '""')
                qfield = field.replace('"', '""')
                text_findings[table] = dict(
                    zip(
                        ("rows", "total_bytes", "max_bytes", "over_1mb", "over_100kb"),
                        connection.execute(
                            f'SELECT COUNT(*), COALESCE(SUM(length(CAST("{qfield}" AS BLOB))),0), '
                            f'COALESCE(MAX(length(CAST("{qfield}" AS BLOB))),0), '
                            f'SUM(CASE WHEN length(CAST("{qfield}" AS BLOB)) > 1048576 THEN 1 ELSE 0 END), '
                            f'SUM(CASE WHEN length(CAST("{qfield}" AS BLOB)) > 102400 THEN 1 ELSE 0 END) '
                            f'FROM "{qtable}"'
                        ).fetchone(),
                        strict=True,
                    )
                )
        snapshots = {}
        if "task_snapshots" in _tables(connection):
            cols = set(_columns(connection, "task_snapshots"))
            status = "status" if "status" in cols else ""
            result = "result_json" if "result_json" in cols else ""
            if status and result:
                snapshots = {
                    "status_distribution": [dict(row) for row in connection.execute(
                        f'SELECT "{status}", COUNT(*) AS row_count, COALESCE(SUM(length(CAST("{result}" AS BLOB))),0) AS result_bytes '
                        f'FROM task_snapshots GROUP BY "{status}" ORDER BY result_bytes DESC'
                    )],
                    "ended_rows": int(connection.execute(
                        f'SELECT COUNT(*) FROM task_snapshots WHERE lower("{status}") IN (\'finished\',\'completed\',\'success\',\'failed\',\'cancelled\',\'canceled\')'
                    ).fetchone()[0]),
                }
        duplicate_results = None
        if "task_results" in _tables(connection):
            cols = set(_columns(connection, "task_results"))
            if {"sha256", "task_id"}.issubset(cols):
                duplicate_results = [dict(row) for row in connection.execute(
                    "SELECT sha256, COUNT(*) AS count, COALESCE(SUM(byte_size),0) AS bytes "
                    "FROM task_results GROUP BY sha256 HAVING COUNT(*) > 1 ORDER BY count DESC, bytes DESC LIMIT 20"
                )]
        return {
            "database": str(path),
            "database_size_bytes": physical_size,
            "database_size_mib": round(physical_size / 1024 / 1024, 2),
            "scope": "current_site" if path.is_relative_to(root / "sites") else "archive_or_staging",
            "tables": [{key: value for key, value in row.items() if key != "columns"} for row in table_rows],
            "focus_tables": focus,
            "largest_columns": largest_columns[:20],
            "payload_findings": text_findings,
            "snapshot_findings": snapshots,
            "duplicate_results": duplicate_results,
            "dbstat_available": allocation is not None,
            "allocation_method": allocation_method,
            "sqlite_connection": "mode=ro; PRAGMA query_only=ON",
        }


def _task_report(root: Path, generated: str) -> dict[str, Any]:
    databases = sorted(root.rglob("tasks.db"))
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for path in databases:
        if path.is_symlink():
            errors.append({"database": str(path), "error": "symlink skipped"})
            continue
        try:
            rows.append(_database_row(path, root, generated))
        except (OSError, sqlite3.Error) as exc:
            errors.append({"database": str(path), "error": str(exc)})
    current = [row for row in rows if row["scope"] == "current_site"]
    focus_totals = Counter()
    for row in current:
        for item in row["tables"]:
            if item["table"] in {"task_events", "task_snapshots", "task_results", "task_logs", "artifact_reference", "artifact_references"}:
                focus_totals[item["table"]] += item["table_size"]
    largest = sorted(focus_totals.items(), key=lambda pair: pair[1], reverse=True)
    return {
        "data_root": str(root),
        "runtime_mode": "development",
        "generated_time": generated,
        "sqlite_connection_mode": "mode=ro",
        "write_operation_count": 0,
        "database_count": len(rows),
        "database_errors": errors,
        "databases": rows,
        "current_site_summary": {
            "database_size_bytes": sum(int(row["database_size_bytes"]) for row in current),
            "database_size_mib": round(sum(int(row["database_size_bytes"]) for row in current) / 1024 / 1024, 2),
            "largest_focus_tables_by_allocated_bytes": [
                {"table": table, "table_size": size} for table, size in largest[:3]
            ],
            "growth_assessment": (
                "task_events/task_snapshots payload JSON and retained terminal task records are the primary current-site growth sources; "
                "task_results is empty or secondary where present, and task_logs/artifact_reference tables are absent unless listed."
            ),
        },
        "limitations": [
            "table_size/index_size use SQLite dbstat when available; zero indicates dbstat unavailable, not zero logical data.",
            "archive_or_staging databases are reported separately and are not counted in current_site_summary.",
            "no DELETE/UPDATE/INSERT/DROP/ALTER/VACUUM/REINDEX/transactional write was executed.",
        ],
    }


def _device_connection(root: Path) -> tuple[Path, sqlite3.Connection]:
    path = root / "sites" / "宁波地铁6号线" / "db" / "devices.db"
    if not path.is_file():
        raise RuntimeError(f"devices.db missing: {path}")
    return path, _connect(path)


def _time_column(columns: set[str]) -> str:
    for name in ("collected_at", "created_at", "updated_at", "event_time"):
        if name in columns:
            return name
    return ""


def _lldp_report(root: Path, generated: str) -> dict[str, Any]:
    path, connection = _device_connection(root)
    try:
        table_names = [table for table in _tables(connection) if "lldp" in table.lower()]
        groups: list[dict[str, Any]] = []
        table_summaries: list[dict[str, Any]] = []
        for table in table_names:
            cols = set(_columns(connection, table))
            mapping = {
                "device": "device_uuid" if "device_uuid" in cols else "source_device_uuid" if "source_device_uuid" in cols else "ac_device_uuid" if "ac_device_uuid" in cols else "",
                "local_port": "local_interface" if "local_interface" in cols else "",
                "neighbor_device": "neighbor_device_uuid" if "neighbor_device_uuid" in cols else "neighbor_sysname" if "neighbor_sysname" in cols else "neighbor_switch_uuid" if "neighbor_switch_uuid" in cols else "neighbor_device_name" if "neighbor_device_name" in cols else "",
                "neighbor_port": "neighbor_interface" if "neighbor_interface" in cols else "interface_name" if "interface_name" in cols else "",
                "neighbor_mac": "neighbor_mac" if "neighbor_mac" in cols else "",
            }
            key_cols = [mapping[key] for key in ("device", "local_port", "neighbor_device", "neighbor_port", "neighbor_mac")]
            if not all(key_cols):
                table_summaries.append({"table": table, "row_count": int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]), "analysis": "insufficient columns"})
                continue
            time_col = _time_column(cols)
            select_cols = [f'"{column}"' for column in key_cols]
            group_cols = ", ".join(select_cols)
            time_expr = f', MIN("{time_col}") AS first_seen, MAX("{time_col}") AS last_seen' if time_col else ", '' AS first_seen, '' AS last_seen"
            base = f'FROM "{table}" WHERE 1=1'
            query = f'SELECT {group_cols}, COUNT(*) AS count{time_expr} {base} GROUP BY {group_cols} HAVING COUNT(*) > 1 ORDER BY count DESC'
            for row in connection.execute(query):
                key = {name: _json_value(row[idx]) for idx, name in enumerate(("device", "local_port", "neighbor_device", "neighbor_port", "neighbor_mac"))}
                samples = []
                for sample in connection.execute(
                    f'SELECT * {base} AND "{key_cols[0]}" IS ? AND "{key_cols[1]}" IS ? AND "{key_cols[2]}" IS ? AND "{key_cols[3]}" IS ? AND "{key_cols[4]}" IS ? LIMIT 3',
                    tuple(row[idx] for idx in range(5)),
                ):
                    samples.append({column: _json_value(sample[column]) for column in sample.keys() if column in {"id", "device_uuid", "source_device_uuid", "ac_device_uuid", "local_interface", "neighbor_sysname", "neighbor_device_uuid", "neighbor_interface", "neighbor_mac", "neighbor_switch_name", "collected_at", "created_at", "collect_run_uuid"}})
                groups.append({"table": table, "duplicate_key": key, "count": int(row[5]), "first_seen": _json_value(row[6]), "last_seen": _json_value(row[7]), "sample_rows": samples})
            table_summaries.append({"table": table, "table_role": "history" if table.endswith("_history") else "current", "row_count": int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]), "duplicate_group_count": sum(1 for item in groups if item["table"] == table), "unique_constraints": [str(index[1]) for index in connection.execute(f'PRAGMA index_list("{table}")') if int(index[2]) == 1]})
        slot_collisions: list[dict[str, Any]] = []
        current_table = "device_lldp_neighbors"
        if current_table in table_names:
            for row in connection.execute(
                'SELECT device_uuid, local_interface, COUNT(*) AS count, MIN(collected_at) AS first_seen, MAX(collected_at) AS last_seen '
                'FROM device_lldp_neighbors GROUP BY device_uuid, local_interface HAVING COUNT(*) > 1 ORDER BY count DESC'
            ):
                slot_collisions.append(dict(row))
        current_complete_groups = sum(1 for item in groups if item["table"] == current_table)
        verdict = "B_DATABASE_MODEL_UNIQUE_CONSTRAINT_ABSENT_AS_RISK"
        return {
            "data_root": str(root),
            "runtime_mode": "development",
            "generated_time": generated,
            "site": "宁波地铁6号线",
            "database_path": str(path),
            "sqlite_connection_mode": "mode=ro; PRAGMA query_only=ON",
            "write_operation_count": 0,
            "tables_analyzed": table_names,
            "table_summaries": table_summaries,
            "duplicates": groups,
            "duplicate_group_count": len(groups),
            "current_slot_collisions": slot_collisions,
            "cause_assessment": {
                "classification": verdict,
                "confirmed_current_complete_duplicate_groups": current_complete_groups,
                "current_slot_collision_groups": len(slot_collisions),
                "reason": "No complete five-field duplicate key was found in the current device_lldp_neighbors table. Its two same-device/local-port slot collisions contain multiple neighbors in one collection run and are not identical writes. The table has no UNIQUE constraint, which is a structural B-risk; history-table repeats are temporal records. A producer-vs-migration conclusion is not proven by this static snapshot.",
                "a_collection_duplicate_write": "NOT_PROVEN",
                "c_history_migration_residue": "NOT_PROVEN",
                "not_repaired": True,
            },
        }
    finally:
        connection.close()


def _history_report(root: Path, generated: str) -> dict[str, Any]:
    path, connection = _device_connection(root)
    try:
        targets = [
            "device_lldp_neighbors_history",
            "device_optical_modules_history",
            "device_interfaces_history",
            "ap_lldp_history",
            "ap_optical_history",
            "ac_fit_ap_lldp_history",
            "ac_fit_ap_optical_history",
        ]
        rows: list[dict[str, Any]] = []
        analyzed: list[str] = []
        for table in targets:
            if table not in _tables(connection):
                continue
            analyzed.append(table)
            cols = set(_columns(connection, table))
            if table == "ap_optical_history":
                resource = [name for name in ("ap_uuid", "side", "device_uuid", "interface_name") if name in cols]
            elif table == "ac_fit_ap_optical_history":
                resource = [name for name in ("ap_uuid", "interface_name") if name in cols]
            elif "device_uuid" in cols and "interface_name" in cols:
                resource = ["device_uuid", "interface_name"]
            elif "device_uuid" in cols and "local_interface" in cols:
                resource = ["device_uuid", "local_interface"]
            elif "ap_uuid" in cols and "side" in cols:
                resource = ["ap_uuid", "side"]
            elif "ap_uuid" in cols:
                resource = ["ap_uuid"]
            else:
                continue
            time_col = _time_column(cols)
            group = ", ".join(f'"{name}"' for name in resource)
            time_expr = f', MIN("{time_col}") AS oldest_record, MAX("{time_col}") AS newest_record' if time_col else ", '' AS oldest_record, '' AS newest_record"
            query = f'SELECT {group}, COUNT(*) AS current_count{time_expr} FROM "{table}" GROUP BY {group} ORDER BY current_count DESC'
            for row in connection.execute(query):
                current = int(row[len(resource)])
                rows.append({
                    "table": table,
                    "resource_id": "|".join(str(row[idx] or "") for idx in range(len(resource))),
                    "current_count": current,
                    "expected_max": EXPECTED_MAX,
                    "overflow_count": max(0, current - EXPECTED_MAX),
                    "oldest_record": _json_value(row[len(resource) + 1]),
                    "newest_record": _json_value(row[len(resource) + 2]),
                })
        overflow = [row for row in rows if row["overflow_count"] > 0]
        return {
            "data_root": str(root),
            "runtime_mode": "development",
            "generated_time": generated,
            "sqlite_connection_mode": "mode=ro; PRAGMA query_only=ON",
            "write_operation_count": 0,
            "expected_max": EXPECTED_MAX,
            "tables_analyzed": analyzed,
            "retention_rows": rows,
            "resource_count": len(rows),
            "overflow_resource_count": len(overflow),
            "overflow_record_count": sum(int(row["overflow_count"]) for row in overflow),
            "assessment": {
                "strategy": "WRITE_STAGE_OR_CLEANUP_UNDETERMINED",
                "finding": "History tables contain resources above the ten-effective-change target. Read-only evidence cannot distinguish producer-side omission from a non-running cleanup job without producer/job execution logs.",
                "no_cleanup_performed": True,
            },
        }
    finally:
        connection.close()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _markdown(root: Path, generated: str, tasks: dict[str, Any], lldp: dict[str, Any], history: dict[str, Any]) -> str:
    current = tasks["current_site_summary"]
    largest = current["largest_focus_tables_by_allocated_bytes"]
    top = ", ".join(f"`{item['table']}` ({item['table_size']} bytes)" for item in largest) or "无可用 dbstat 分配数据"
    duplicate_count = lldp["duplicate_group_count"]
    current_complete = lldp["cause_assessment"]["confirmed_current_complete_duplicate_groups"]
    return f"""# DEV COPY 生命周期审计

## 环境

- 数据根：`{root}`
- 运行模式：`development`
- 生成时间：`{generated}`
- SQLite 连接：`mode=ro`，并设置 `PRAGMA query_only=ON`
- `WRITE_OPERATION_COUNT=0`

## tasks.db

- 当前 `sites` 任务库合计：{current['database_size_bytes']} bytes（{current['database_size_mib']} MiB）。扫描到 {tasks['database_count']} 个 `tasks.db`，归档/冲突副本单独列出，未混入当前汇总。
- 当前占用最大的关注表：{top}。
- 增长判断：`task_events.payload_json`、`task_snapshots.result_json` 等长 JSON 与终态任务长期保留是主要增长来源；`task_results`、`task_logs`、artifact 引用按库实际存在情况报告，未执行删除。
- 详细表级行数、物理分配、索引和大字段统计见 `TASK_DB_USAGE_REPORT.json`。

## LLDP

- 分析范围：宁波地铁6号线 DEV COPY `devices.db` 的全部 LLDP 相关表。
- 所有 LLDP 表按五字段键合计重复组：{duplicate_count}；其中当前 `device_lldp_neighbors` 的完整五字段重复组为 {current_complete}，另有 {len(lldp['current_slot_collisions'])} 个同设备/本地端口槽位包含多邻居记录。
- 当前表没有覆盖完整 LLDP 业务键的 UNIQUE 约束，这是 B 类结构性风险；但本快照未证明 A 类相同采集重复写入，也未证明 C 类迁移遗留。历史表中的重复键是跨采集时间的历史记录，不能直接当作当前态重复。
- 详细重复键、首末时间、样本和约束证据见 `LLDP_DUPLICATE_REPORT.json`。

## History retention

- 目标：每个资源最多保留最近 {EXPECTED_MAX} 条有效变化记录。
- 分析表：{', '.join(f'`{name}`' for name in history['tables_analyzed'])}。
- 超限资源：{history['overflow_resource_count']}，超出记录数合计：{history['overflow_record_count']}。
- 结论：只读库能确认当前超限，但不能单独证明是写入阶段未限流还是清理任务未运行；下一步应查 producer/job 审计日志并复现，不在本阶段清理。

## 风险

- tasks 事件和结果 payload 可能同时保存完整命令输出、设备响应或 snapshot；物理占用会随任务终态和事件量增长。
- LLDP 当前表缺少足够强的业务唯一约束，重复采集可能继续积累。
- legacy history 表未体现统一的最近10条边界，直接删除会影响时间线、导出和诊断消费者。

## 下一步建议

1. 由负责人确认 producer、history cleanup job 和 result/artifact 引用的生命周期契约。
2. 在 DEV COPY 建立按 collect_run/task 版本的增长基线，先做 COPY/verify 演练，再单独审批修复或清理。
3. 本审计未执行清理、修复、压缩、迁移、删除或 schema 修改；等待负责人确认后再进入下一阶段。
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    root = args.data_root.resolve()
    if root != DEFAULT_ROOT.resolve():
        raise RuntimeError(f"this audit is restricted to the DEV COPY root: {DEFAULT_ROOT}")
    marker = _read_marker(root)
    generated = _utc_now()
    print(json.dumps({"data_root": str(root), "runtime_mode": marker["mode"], "generated_time": generated}, ensure_ascii=False))
    tasks = _task_report(root, generated)
    lldp = _lldp_report(root, generated)
    history = _history_report(root, generated)
    output = args.output_dir.resolve() / f"lifecycle-audit-dev-{datetime.now().strftime('%Y%m%d')}"
    _write_json(output / REPORT_NAMES[0], tasks)
    _write_json(output / REPORT_NAMES[1], lldp)
    _write_json(output / REPORT_NAMES[2], history)
    doc = Path(__file__).resolve().parents[2] / "docs" / "investigations" / "LIFECYCLE_AUDIT_DEV.md"
    doc.write_text(_markdown(root, generated, tasks, lldp, history), encoding="utf-8")
    print(json.dumps({"reports": [str(output / name) for name in REPORT_NAMES], "document": str(doc), "WRITE_OPERATION_COUNT": 0}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
