"""Generate a read-only storage retention policy proposal from audit reports."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


POLICY_FILE_NAME = "STORAGE_RETENTION_POLICY.md"
PRIORITY_FILE_NAME = "STORAGE_GOVERNANCE_PRIORITY.md"
JSON_INPUTS = (
    "RAIL_TRANSIT_ANALYSIS.json",
    "BACKUP_ANALYSIS.json",
    "HISTORY_DB_ANALYSIS.json",
    "TOP_TABLE_USAGE.json",
)
REQUIRED_INPUTS = JSON_INPUTS + ("STORAGE_LIFECYCLE_REPORT.md", "STORAGE_GOVERNANCE_MATRIX.md")


class RetentionPolicyError(ValueError):
    """Raised when the policy input directory is invalid."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def _bytes(value: int | float) -> str:
    amount = float(value or 0)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if amount < 1024 or unit == "TiB":
            return f"{int(amount)} {unit}" if unit == "B" else f"{amount:.2f} {unit}"
        amount /= 1024
    return f"{amount:.2f} TiB"


def _rail(rail: dict[str, Any]) -> dict[str, Any]:
    total = _int(rail.get("total_size_bytes"))
    extension = {str(item.get("extension", "")): item for item in rail.get("extension_summary", [])}
    sqlite = _int(extension.get(".sqlite", {}).get("size_bytes")) + _int(extension.get(".db", {}).get("size_bytes"))
    logs = _int(extension.get(".log", {}).get("size_bytes"))
    exports = _int(extension.get(".json", {}).get("size_bytes")) + _int(extension.get(".csv", {}).get("size_bytes"))
    archives = _int(extension.get(".zip", {}).get("size_bytes"))
    raw = max(total - sqlite - logs - exports - archives, 0)
    return {"total": total, "sqlite": sqlite, "logs": logs, "exports": exports, "archives": archives, "raw": raw}


def _backup(backups: dict[str, Any]) -> dict[str, Any]:
    totals: dict[str, int] = {}
    counts: dict[str, int] = {}
    items = backups.get("backups", backups.get("files", []))
    for item in items:
        category = str(item.get("backup_type", "UNKNOWN"))
        totals[category] = totals.get(category, 0) + _int(item.get("size_bytes"))
        counts[category] = counts.get(category, 0) + 1
    return {"total": _int(backups.get("total_size_bytes")), "totals": totals, "counts": counts}


def _history(history: dict[str, Any]) -> dict[str, Any]:
    tables: list[dict[str, Any]] = []
    for database in history.get("databases", []):
        for table in database.get("tables", []):
            item = dict(table)
            item["database"] = database.get("path", database.get("filename", ""))
            tables.append(item)
    tables.sort(key=lambda item: (-_int(item.get("size_bytes")), str(item.get("database", "")), str(item.get("table_name", ""))))
    return {"total": _int(history.get("total_size_bytes")), "count": _int(history.get("total_files", len(history.get("databases", [])))), "tables": tables}


def _tasks(tasks: dict[str, Any]) -> list[dict[str, Any]]:
    result = [item for item in tasks.get("tables", []) if str(item.get("database", "")).casefold().endswith("tasks.db")]
    result.sort(key=lambda item: (-_int(item.get("size_bytes")), str(item.get("table_name", ""))))
    return result


def _policy(reports: dict[str, dict[str, Any]], missing: list[str]) -> str:
    rail = _rail(reports["RAIL_TRANSIT_ANALYSIS.json"])
    backup = _backup(reports["BACKUP_ANALYSIS.json"])
    history = _history(reports["HISTORY_DB_ANALYSIS.json"])
    tasks = _tasks(reports["TOP_TABLE_USAGE.json"])
    lines = [
        "# NetConsole Storage Retention Policy Proposal",
        "",
        f"- Generated at: `{_now()}`",
        "- Status: read-only方案阶段，所有条目需要人工与业务确认。",
        "",
        "本文件是治理策略设计，不执行任何文件处置、归档、压缩、迁移或数据库优化操作。",
        "",
    ]
    if missing:
        lines.extend(["## Input Gaps", "", *[f"- `{name}` unavailable; related policy values require business confirmation." for name in missing], ""])
    lines.extend([
        "## rail_transit Storage Policy", "",
        f"- 当前容量：**{_bytes(rail['total'])}**",
        f"- 主要类型：analysis SQLite {_bytes(rail['sqlite'])}；raw/other {_bytes(rail['raw'])}；LOG {_bytes(rail['logs'])}；EXPORT {_bytes(rail['exports'])}；ARCHIVE {_bytes(rail['archives'])}。",
        "- 增长来源：现有报告显示占用集中在 analysis SQLite、raw/other 和日志文件；是否为原始数据、是否可重建、是否需要长期在线，均需要业务确认。",
        "",
        "### 分类管理方式", "",
        "| 分类 | 当前容量 | 建议管理方式 | 需要确认 |",
        "| -- | --: | -- | -- |",
        f"| RAW_DATA | {_bytes(rail['raw'])} | 长期保留评估；可结合原始证据价值评估周期归档 | 数据是否可由设备/采集重新获得 |",
        f"| ANALYSIS_DATABASE | {_bytes(rail['sqlite'])} | 周期归档评估、压缩评估、重建能力评估 | 是否属于派生数据、是否需要长期在线 |",
        f"| LOG | {_bytes(rail['logs'])} | 周期保留与压缩评估 | 运行审计和故障追溯期限 |",
        f"| EXPORT | {_bytes(rail['exports'])} | 周期归档评估 | 是否为正式交付物 |",
        f"| ARCHIVE | {_bytes(rail['archives'])} | 长期归档属性确认 | 是否存在独立归档副本 |",
        "",
        "analysis SQLite 的重建能力和在线需求不能仅由文件扩展名判断，需要业务确认。",
        "",
        "## Backup Storage Policy", "",
        f"- 当前容量：**{_bytes(backup['total'])}**；文件数：**{sum(backup['counts'].values())}**。",
        "| 分类 | 当前容量 | 作用 | 风险 | 建议确认事项 |",
        "| -- | --: | -- | -- | -- |",
    ])
    backup_rows = {
        "PRODUCTION_MAINTENANCE": ("生产维护链路", "影响维护追溯和恢复判断", "确认维护链路保留周期"),
        "DATABASE_MIGRATION": ("数据库升级/迁移过程", "影响升级回溯和变更审计", "确认迁移完成后的保留期限"),
        "ROLLBACK": ("升级回滚保障", "影响故障恢复", "确认回滚窗口和恢复验证要求"),
        "SNAPSHOT": ("状态快照", "影响状态追踪", "确认快照有效期和查询需求"),
        "UNKNOWN": ("未明确分类对象", "性质与恢复作用未确认", "补充业务归属和生命周期"),
    }
    for category in ("PRODUCTION_MAINTENANCE", "DATABASE_MIGRATION", "ROLLBACK", "SNAPSHOT", "UNKNOWN"):
        nature, risk, confirm = backup_rows[category]
        lines.append(f"| {category} | {_bytes(backup['totals'].get(category, 0))} | {nature} | {risk} | {confirm} |")
    lines.extend(["", "不生成自动清理规则；生产维护、升级回滚和故障恢复对象的保留策略需要人工确认。", ""])
    lines.extend([
        "## History Storage Policy", "",
        f"- db/history 数据库数量：**{history['count']}**；总容量：**{_bytes(history['total'])}**。",
        "- 重点对象：`history_events_v2`、`history_event_provenance_v2`。",
        "- 需要确认：保留周期、查询需求、审计要求、是否冷热分层。",
        "- 不建议直接改变历史数据；先确认审计完整性、查询窗口和恢复能力。",
        "",
        "### Largest History Tables", "",
    ])
    for item in history["tables"][:10]:
        lines.append(f"- `{item.get('database', '')}` / `{item.get('table_name', '')}`: {_bytes(_int(item.get('size_bytes')))} ({_int(item.get('row_count'))} rows)")
    lines.extend(["", "## Task Storage Policy", "", "- Task Center 相关数据应区分运行态记录、历史记录和归档候选；恢复能力与审计需求需要人工确认。"])
    for item in tasks[:10]:
        name = str(item.get("table_name", ""))
        nature = "运行态数据" if name in {"task_events", "task_snapshots"} else "历史/结果数据"
        lines.append(f"- `{name}`：{_bytes(_int(item.get('size_bytes')))}，{nature}；建议评估保留周期和归档边界。")
    if not tasks:
        lines.append("- 未提供 tasks.db 表空间数据，需要业务确认。")
    lines.extend(["", "## Governance Principles", "", "- 必须长期保留候选：审计所需历史、恢复所需备份、不可重建的原始证据；具体期限需要人工确认。", "- 可归档候选：已完成周期的派生分析库、迁移过程文件、日志和导出对象；这里只提出评估方向。", "- 所有建议均需要人工确认，不自动生成执行计划。", "", "## Current Stage Restrictions", "", "- 未执行：删除。", "- 未执行：压缩。", "- 未执行：归档。", "- 未执行：迁移。", "- 未执行：数据库优化。", "- 未执行：VACUUM、compact 或 schema 修改。", ""])
    return "\n".join(lines)


def _priority(reports: dict[str, dict[str, Any]]) -> str:
    rail = _rail(reports["RAIL_TRANSIT_ANALYSIS.json"])
    backup = _backup(reports["BACKUP_ANALYSIS.json"])
    history = _history(reports["HISTORY_DB_ANALYSIS.json"])
    tasks = _tasks(reports["TOP_TABLE_USAGE.json"])
    task_size = sum(_int(item.get("size_bytes")) for item in tasks)
    rows = [
        ("rail_transit analysis sqlite", rail["sqlite"], "高", "P1", "确认原始/派生边界、重建能力与生命周期"),
        ("files/backups", backup["total"], "高", "P1", "确认维护、迁移、回滚保留规则"),
        ("db/history", history["total"], "中", "P2", "评估 event/provenance 查询与冷热分层"),
        ("tasks.db", task_size, "中", "P2", "确认 task_results/task_events/task_snapshots 保留周期"),
        ("rail_transit logs/export", rail["logs"] + rail["exports"], "中", "P2", "评估日志、导出交付和追溯需求"),
    ]
    lines = ["# Storage Governance Priority", "", "| 对象 | 容量 | 风险 | 优先级 | 下一步 |", "| -- | --: | -- | -- | -- |"]
    lines.extend(f"| {name} | {_bytes(size)} | {risk} | {priority} | {next_step} |" for name, size, risk, priority, next_step in rows)
    lines.extend(["", "所有下一步均为人工评审事项；本矩阵不构成执行授权。", ""])
    return "\n".join(lines)


def generate_storage_retention_policy(input_directory: Path | str, output_directory: Path | str) -> dict[str, Any]:
    input_path = Path(input_directory).expanduser().resolve()
    output_path = Path(output_directory).expanduser().resolve()
    if not input_path.is_dir():
        raise RetentionPolicyError(f"input report directory does not exist: {input_path}")
    reports = {name: _read_json(input_path / name) for name in JSON_INPUTS}
    missing = [name for name, value in reports.items() if not value]
    lifecycle_path = input_path / "STORAGE_LIFECYCLE_REPORT.md"
    matrix_path = input_path / "STORAGE_GOVERNANCE_MATRIX.md"
    if lifecycle_path.is_file():
        reports["STORAGE_LIFECYCLE_REPORT.md"] = {"available": True}
    else:
        missing.append("STORAGE_LIFECYCLE_REPORT.md")
    if matrix_path.is_file():
        reports["STORAGE_GOVERNANCE_MATRIX.md"] = {"available": True}
    else:
        missing.append("STORAGE_GOVERNANCE_MATRIX.md")
    output_path.mkdir(parents=True, exist_ok=True)
    policy = _policy(reports, missing)
    priority = _priority(reports)
    (output_path / POLICY_FILE_NAME).write_text(policy, encoding="utf-8")
    (output_path / PRIORITY_FILE_NAME).write_text(priority, encoding="utf-8")
    return {"output_directory": str(output_path), "missing_reports": missing, "policy": policy, "priority": priority}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", "--input", dest="input_directory", type=Path, required=True)
    parser.add_argument("--output-dir", "--output", dest="output_directory", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        result = generate_storage_retention_policy(args.input_directory, args.output_directory)
    except RetentionPolicyError as exc:
        parser.error(str(exc))
    print(json.dumps({"output_directory": result["output_directory"], "missing_reports": result["missing_reports"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
