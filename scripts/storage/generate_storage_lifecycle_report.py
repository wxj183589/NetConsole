"""Generate read-only lifecycle governance Markdown from storage reports."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


LIFECYCLE_REPORT_FILE_NAME = "STORAGE_LIFECYCLE_REPORT.md"
GOVERNANCE_MATRIX_FILE_NAME = "STORAGE_GOVERNANCE_MATRIX.md"
REPORT_NAMES = (
    "SITE_STORAGE_ANALYSIS.json",
    "RAIL_TRANSIT_ANALYSIS.json",
    "RAIL_TRANSIT_TIMELINE.json",
    "BACKUP_ANALYSIS.json",
    "BACKUP_DUPLICATE_ANALYSIS.json",
    "HISTORY_DB_ANALYSIS.json",
    "TOP_TABLE_USAGE.json",
)


class StorageLifecycleReportError(ValueError):
    """Raised when lifecycle input cannot be resolved."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _load_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _resolve_reports(input_directory: Path, overrides: dict[str, Path | None]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    reports: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for name in REPORT_NAMES:
        path = overrides.get(name) or input_directory / name
        report = _load_json(path)
        reports[name] = report
        if not report:
            missing.append(name)
    return reports, missing


def _format_bytes(value: int | float | None) -> str:
    amount = float(value or 0)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if amount < 1024 or unit == "TiB":
            return f"{int(amount)} {unit}" if unit == "B" else f"{amount:.2f} {unit}"
        amount /= 1024
    return f"{amount:.2f} TiB"


def _integer(report: dict[str, Any], key: str, fallback: int = 0) -> int:
    try:
        return int(report.get(key, fallback) or fallback)
    except (TypeError, ValueError):
        return fallback


def _rail_classification(item: dict[str, Any]) -> str:
    path = str(item.get("path", "")).casefold()
    extension = str(item.get("extension", "")).casefold()
    if extension == ".log":
        return "LOG"
    if extension == ".zip":
        return "ARCHIVE"
    if extension in {".sqlite", ".db"}:
        return "ANALYSIS_DATABASE"
    if any(token in path for token in ("mr_raw_mesh", "online_mr", "ground_unattended")):
        return "RAW_DATA"
    if extension in {".json", ".csv"}:
        return "EXPORT_DATA"
    return "UNKNOWN"


def _rail_lifecycle(report: dict[str, Any]) -> dict[str, Any]:
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for item in report.get("files", []):
        category = _rail_classification(item)
        bucket = totals[category]
        bucket[0] += _integer(item, "size_bytes")
        bucket[1] += 1
    if not report.get("files"):
        for item in report.get("extension_summary", []):
            extension = str(item.get("extension", "")).casefold()
            category = "RAW_DATA" if extension == "other" else _rail_classification({"extension": extension, "path": ""})
            bucket = totals[category]
            bucket[0] += _integer(item, "size_bytes")
            bucket[1] += _integer(item, "file_count")
    categories = [
        {"category": category, "size_bytes": values[0], "file_count": values[1]}
        for category, values in totals.items()
    ]
    categories.sort(key=lambda item: (-item["size_bytes"], item["category"]))
    total = _integer(report, "total_size_bytes")
    return {
        "total_size_bytes": total,
        "total_files": _integer(report, "total_files"),
        "categories": categories,
        "timeline": report.get("timeline", []),
        "errors": report.get("errors", []),
    }


def _backup_lifecycle(report: dict[str, Any]) -> dict[str, Any]:
    items = report.get("backups", report.get("files", []))
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    mtimes: list[str] = []
    for item in items:
        category = str(item.get("backup_type", "UNKNOWN"))
        bucket = totals[category]
        bucket[0] += _integer(item, "size_bytes")
        bucket[1] += 1
        if item.get("mtime"):
            mtimes.append(str(item["mtime"]))
    categories = [
        {"category": category, "size_bytes": values[0], "file_count": values[1]}
        for category, values in totals.items()
    ]
    categories.sort(key=lambda item: (-item["size_bytes"], item["category"]))
    return {
        "total_size_bytes": _integer(report, "total_size_bytes"),
        "total_files": _integer(report, "total_files"),
        "categories": categories,
        "oldest_mtime": min(mtimes) if mtimes else "",
        "newest_mtime": max(mtimes) if mtimes else "",
        "duplicates": report.get("duplicates", []),
        "errors": report.get("errors", []),
    }


def _history_lifecycle(report: dict[str, Any]) -> dict[str, Any]:
    databases = report.get("databases", [])
    tables: list[dict[str, Any]] = []
    for database in databases:
        for table in database.get("tables", []):
            item = dict(table)
            item["database"] = database.get("path", database.get("filename", ""))
            tables.append(item)
    tables.sort(key=lambda item: (-_integer(item, "size_bytes"), str(item.get("database", "")), str(item.get("table_name", ""))))
    return {
        "total_size_bytes": _integer(report, "total_size_bytes"),
        "database_count": _integer(report, "total_files", len(databases)),
        "databases": databases,
        "tables": tables,
        "errors": report.get("errors", []),
    }


def _task_lifecycle(report: dict[str, Any], history: dict[str, Any]) -> dict[str, Any]:
    tables = [item for item in report.get("tables", []) if str(item.get("database", "")).casefold().endswith("tasks.db")]
    if not tables:
        tables = [item for item in history.get("tables", []) if str(item.get("database", "")).casefold().endswith("tasks.db")]
    tables.sort(key=lambda item: (-_integer(item, "size_bytes"), str(item.get("database", "")), str(item.get("table_name", ""))))
    return {"tables": tables, "databases": report.get("databases", []), "errors": report.get("errors", [])}


def _summary(
    reports: dict[str, dict[str, Any]],
    missing: list[str],
) -> tuple[str, str]:
    site = reports["SITE_STORAGE_ANALYSIS.json"]
    rail = _rail_lifecycle(reports["RAIL_TRANSIT_ANALYSIS.json"])
    timeline = reports["RAIL_TRANSIT_TIMELINE.json"]
    backups = _backup_lifecycle(reports["BACKUP_ANALYSIS.json"])
    duplicate_report = reports["BACKUP_DUPLICATE_ANALYSIS.json"]
    history = _history_lifecycle(reports["HISTORY_DB_ANALYSIS.json"])
    tasks = _task_lifecycle(reports["TOP_TABLE_USAGE.json"], history)
    total = _integer(site, "total_size_bytes")
    lines = [
        "# Storage Lifecycle Governance Analysis",
        "",
        f"- Generated at: `{_now()}`",
        f"- Source report directory: `{reports['RAIL_TRANSIT_ANALYSIS.json'].get('root_path', site.get('root_path', ''))}`",
        f"- Current total represented by input: **{_format_bytes(total)}**",
        "",
        "This report describes observed data characteristics and lifecycle topics for evaluation. It is an analysis artifact only.",
        "",
    ]
    if missing:
        lines.extend(["## Input Gaps", "", *[f"- `{name}` was not available; affected values are shown as zero or unavailable." for name in missing], ""])

    lines.extend(["## rail_transit Lifecycle", "", f"- Current capacity: **{_format_bytes(rail['total_size_bytes'])}**", f"- Files: **{rail['total_files']}**", "", "### Classification", ""])
    for item in rail["categories"]:
        lines.append(f"- `{item['category']}`: {_format_bytes(item['size_bytes'])} ({item['file_count']} files)")
    lines.extend(["", "### Time Distribution", ""])
    for item in timeline.get("timeline", rail.get("timeline", [])):
        lines.append(f"- `{item.get('period', 'unknown')}`: {_format_bytes(_integer(item, 'size_bytes'))} ({_integer(item, 'file_count')} files)")
    lines.extend(["", "### Observed Nature", "", "- The path and extension distribution describes a mixture of operational raw/analysis data, logs, archives, and export-like files.", "- The time buckets describe when files were modified; they do not establish retention eligibility.", "- Lifecycle topic:建议评估 raw data、analysis database、log 和 export data 的保留周期与归档边界。", ""])

    lines.extend(["## Backup Lifecycle", "", f"- Count: **{backups['total_files']}**", f"- Capacity: **{_format_bytes(backups['total_size_bytes'])}**", f"- Observed time range: `{backups['oldest_mtime'] or 'unavailable'}` to `{backups['newest_mtime'] or 'unavailable'}`", ""])
    for item in backups["categories"]:
        lines.append(f"- `{item['category']}`: {_format_bytes(item['size_bytes'])} ({item['file_count']} files)")
    lines.extend(["", "### Observed Nature", "", "- Production maintenance entries describe a maintenance-chain object by path classification.", "- Database migration entries describe historical migration-process artifacts by path classification.", f"- Exact duplicate groups reported: **{len(duplicate_report.get('duplicates', []))}**.", "- Lifecycle topic:建议评估维护链路、迁移过程和 rollback/snapshot 对象的保留周期。", ""])

    lines.extend(["## History Lifecycle", "", f"- Database count: **{history['database_count']}**", f"- Capacity: **{_format_bytes(history['total_size_bytes'])}**"])
    if history["databases"]:
        largest = max(history["databases"], key=lambda item: _integer(item, "size_bytes"))
        lines.append(f"- Largest database: `{largest.get('path', largest.get('filename', ''))}` ({_format_bytes(_integer(largest, 'size_bytes'))})")
    lines.extend(["", "### Largest Tables", ""])
    for item in history["tables"][:10]:
        lines.append(f"- `{item.get('database', '')}` / `{item.get('table_name', '')}`: {_format_bytes(_integer(item, 'size_bytes'))} ({_integer(item, 'row_count')} rows)")
    lines.extend(["", "### Observed Growth Objects", "", "- `history_events_v2` is the dominant measured table in the largest history databases.", "- `history_event_provenance_v2` is the next measured table in the same databases.", "- Lifecycle topic:建议评估 event、provenance、legacy history 和 catalog 对象的分层保留周期。", ""])

    lines.extend(["## Task Storage Lifecycle", ""])
    for item in tasks["tables"][:10]:
        lines.append(f"- `{item.get('database', '')}` / `{item.get('table_name', '')}`: {_format_bytes(_integer(item, 'size_bytes'))} ({_integer(item, 'percentage')}% of database, {_integer(item, 'row_count')} rows)")
    if not tasks["tables"]:
        lines.append("- No tasks.db table usage was available in the input reports.")
    lines.extend(["", "- The observed task tables are runtime/task-record objects; the reports do not establish a disposition decision.", "- Lifecycle topic:建议评估 task_results、task_events 和 task_snapshots 的保留周期与审计要求。", ""])

    lines.extend(["## Lifecycle Topics", "", "- 必须长期保留候选：审计所需的历史事件、任务结果、生产维护链路和原始分析证据；具体期限需结合业务/合规确认。", "- 可归档候选：已完成周期的 raw/analysis 数据、历史迁移过程文件和不再活跃的日志/导出对象；这里只记录评估方向。", "- 建议优先评估：`files/rail_transit` 中的 analysis SQLite、`files/backups` 中的维护/迁移链路、`db/history` 中 event/provenance 表，以及 tasks.db 的结果/事件表。", "- 本报告不判定任何文件的处置方式。", ""])
    if any(report.get("errors") for report in reports.values()):
        lines.extend(["## Report Errors", "", "- Input reports contain recorded errors; review those facts before lifecycle decisions.", ""])

    matrix = [
        ("rail_transit sqlite", next((item["size_bytes"] for item in rail["categories"] if item["category"] == "ANALYSIS_DATABASE"), 0), "采集/分析数据库", "建议评估 raw、analysis database 与归档层级", "高"),
        ("rail_transit logs/archives", sum(item["size_bytes"] for item in rail["categories"] if item["category"] in {"LOG", "ARCHIVE"}), "运行日志/导出归档", "建议评估日志与导出保留周期", "中"),
        ("files/backups", backups["total_size_bytes"], "维护保障数据", "建议评估维护链路与迁移过程的生命周期", "高"),
        ("db/history", history["total_size_bytes"], "审计历史", "建议评估 event/provenance 分层与归档策略", "中"),
        ("tasks.db", sum(_integer(item, "size_bytes") for item in tasks["tables"]), "任务运行/历史记录", "建议评估 task_results、task_events、task_snapshots 保留周期", "中"),
    ]
    matrix_lines = [
        "# Storage Governance Matrix", "", "| 对象 | 当前大小 | 性质 | 建议关注方向 | 风险 |", "| -- | --: | -- | -- | -- |"
    ]
    matrix_lines.extend(f"| {name} | {_format_bytes(size)} | {nature} | {focus} | {risk} |" for name, size, nature, focus, risk in matrix)
    return "\n".join(lines), "\n".join(matrix_lines) + "\n"


def generate_storage_lifecycle_report(
    input_directory: Path | str,
    output_directory: Path | str,
    *,
    report_paths: dict[str, Path | str] | None = None,
) -> dict[str, Any]:
    input_path = Path(input_directory).expanduser().resolve()
    output_path = Path(output_directory).expanduser().resolve()
    if not input_path.is_dir():
        raise StorageLifecycleReportError(f"input report directory does not exist: {input_path}")
    overrides = {name: None for name in REPORT_NAMES}
    for name, path in (report_paths or {}).items():
        if name in overrides:
            overrides[name] = Path(path).expanduser().resolve()
    reports, missing = _resolve_reports(input_path, overrides)
    lifecycle, matrix = _summary(reports, missing)
    output_path.mkdir(parents=True, exist_ok=True)
    (output_path / LIFECYCLE_REPORT_FILE_NAME).write_text(lifecycle, encoding="utf-8")
    (output_path / GOVERNANCE_MATRIX_FILE_NAME).write_text(matrix, encoding="utf-8")
    return {"output_directory": str(output_path), "missing_reports": missing, "lifecycle": lifecycle, "matrix": matrix}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", "--input", dest="input_directory", type=Path, required=True)
    parser.add_argument("--output-dir", "--output", dest="output_directory", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        result = generate_storage_lifecycle_report(args.input_directory, args.output_directory)
    except StorageLifecycleReportError as exc:
        parser.error(str(exc))
    print(json.dumps({"output_directory": result["output_directory"], "missing_reports": result["missing_reports"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
