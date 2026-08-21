"""Generate a complete, read-only NetConsole Site storage audit report."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .analyze_site_storage import analyze_site_storage
from .analyze_sqlite_size import SQLiteSpaceReportError, analyze_sqlite_size
from .audit_site import AuditError, audit_site
from .report_large_files import LargeFileReportError, large_files_report


REPORT_DIRECTORY_NAME = "storage-audit-report"
INVENTORY_FILE_NAME = "SITE_STORAGE_INVENTORY.json"
ANALYSIS_REPORT_FILE_NAME = "SITE_STORAGE_ANALYSIS.json"
LARGE_FILES_FILE_NAME = "LARGE_FILES_REPORT.json"
SQLITE_FILE_NAME = "SQLITE_SPACE_REPORT.json"
SQLITE_EXTENSIONS = {".db", ".sqlite", ".sqlite3"}
DIRECTORY_PATHS = (
    "db",
    "db/history",
    "HistoryStore",
    "files",
    "files/backups",
    "files/backups/production-maintenance",
    "files/backups/database-migrations",
    "rail_transit",
    "imports",
    "sync",
)


class StorageReportError(ValueError):
    """Raised when a complete report cannot be started safely."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _is_under(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _discover_sqlite_files(root: Path, excluded_path: Path | None) -> tuple[list[Path], list[str]]:
    files: list[Path] = []
    errors: list[str] = []
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name.casefold())
        except OSError as exc:
            errors.append(f"{directory}: {exc.__class__.__name__}: {exc}")
            continue

        for entry in entries:
            candidate = Path(entry.path).resolve()
            if excluded_path is not None and _is_under(candidate, excluded_path):
                continue
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    pending.append(candidate)
                elif entry.is_file(follow_symlinks=False) and candidate.suffix.casefold() in SQLITE_EXTENSIONS:
                    files.append(candidate)
            except OSError as exc:
                errors.append(f"{candidate}: {exc.__class__.__name__}: {exc}")
    files.sort(key=lambda path: path.as_posix().casefold())
    errors.sort()
    return files, errors


def _sqlite_report(
    root: Path,
    output_directory: Path,
) -> tuple[dict[str, Any], list[str]]:
    database_paths, discovery_errors = _discover_sqlite_files(root, output_directory)
    reports: list[dict[str, Any]] = []
    errors = list(discovery_errors)
    for database_path in database_paths:
        try:
            report = analyze_sqlite_size(database_path)
        except SQLiteSpaceReportError as exc:
            reason = str(exc)
            error = f"{database_path.relative_to(root).as_posix()}: {reason}"
            errors.append(error)
            try:
                database_size_bytes = database_path.stat().st_size
            except OSError:
                database_size_bytes = 0
            report = {
                "database_path": str(database_path),
                "database_size_bytes": database_size_bytes,
                "tables": [],
                "indexes": [],
                "errors": [reason],
                "error": reason,
            }
        for report_error in report.get("errors", []):
            errors.append(
                f"{database_path.relative_to(root).as_posix()}: {report_error}"
            )
        reports.append(report)

    flattened_tables: list[dict[str, Any]] = []
    for report in reports:
        for table in report.get("tables", []):
            item = dict(table)
            item["database_path"] = report["database_path"]
            flattened_tables.append(item)
    flattened_tables.sort(
        key=lambda item: (-int(item.get("size_bytes", 0)), item["database_path"], item["table_name"])
    )
    database_summary: dict[str, Any] = {
        "count": len(reports),
        "tables": flattened_tables,
    }
    if len(reports) == 1:
        database_summary["path"] = reports[0]["database_path"]

    return {
        "generated_at": _now(),
        "database": database_summary,
        "databases": reports,
        "errors": sorted(errors),
    }, sorted(errors)


def _format_bytes(value: int) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    amount = float(value)
    unit = units[0]
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            break
        amount /= 1024
    if unit == "B":
        return f"{int(amount)} {unit}"
    return f"{amount:.2f} {unit}"


def _format_directory_lines(analysis: dict[str, Any]) -> list[str]:
    lines = ["## Directory contribution", ""]
    for item in analysis.get("top_directories", []):
        lines.append(
            f"- `{item['path']}`: {_format_bytes(int(item['size_bytes']))} "
            f"({item['percentage']:.2f}%)"
        )
    if len(lines) == 2:
        lines.append("- No directories found.")
    lines.append("")
    return lines


def _summary_markdown(
    inventory: dict[str, Any],
    analysis: dict[str, Any],
    large_files: dict[str, Any],
    sqlite_report: dict[str, Any],
    errors: Iterable[str],
) -> str:
    total_size = int(inventory.get("total_size_bytes", 0) or 0)
    lines = [
        "# NetConsole Site Storage Audit Report",
        "",
        f"- Scan path: `{inventory.get('root_path', '')}`",
        f"- Generated at: `{inventory.get('generated_at', '')}`",
        f"- Total capacity: **{_format_bytes(total_size)}**",
        f"- Total files: **{int(inventory.get('total_files', 0) or 0)}**",
        "",
    ]
    lines.extend(_format_directory_lines(analysis))

    lines.extend(["## Largest files TOP20", ""])
    largest = inventory.get("largest_files", [])[:20]
    if largest:
        for item in largest:
            lines.append(f"- `{item['path']}`: {_format_bytes(int(item['size_bytes']))}")
    else:
        lines.append("- No files found.")
    lines.append("")

    lines.extend(["## SQLite TOP10 tables", ""])
    tables = sqlite_report.get("database", {}).get("tables", [])[:10]
    if tables:
        for item in tables:
            database_path = Path(item["database_path"])
            try:
                database_label = database_path.relative_to(Path(inventory["root_path"])).as_posix()
            except ValueError:
                database_label = str(database_path)
            lines.append(
                f"- `{database_label}` / `{item['table_name']}`: "
                f"{_format_bytes(int(item['size_bytes']))}, "
                f"{int(item.get('row_count', 0))} rows ({item.get('percentage', 0):.2f}%)"
            )
    else:
        lines.append("- No readable SQLite tables found.")
    lines.append("")

    lines.extend(["## Exceptions", ""])
    unique_errors = sorted(set(str(error) for error in errors if error))
    if unique_errors:
        lines.extend(f"- {error}" for error in unique_errors)
    else:
        lines.append("- None.")
    lines.append("")

    lines.extend(
        [
            "## Conclusion",
            "",
            "This report records observed file, directory, and SQLite space usage "
            "for the scanned Site at generation time.",
            "",
        ]
    )
    return "\n".join(lines)


def generate_storage_report(
    site_path: Path | str,
    output_directory: Path | str = REPORT_DIRECTORY_NAME,
) -> dict[str, Any]:
    """Generate all reports without modifying files below ``site_path``."""

    root = Path(site_path).expanduser().resolve()
    output = Path(output_directory).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise StorageReportError(f"site path is not a directory: {root}")
    if output == root:
        raise StorageReportError("report directory cannot be the Site directory")

    try:
        inventory = audit_site(root, excluded_path=output)
        analysis = analyze_site_storage(inventory, paths=DIRECTORY_PATHS)
        large_files = large_files_report(root, excluded_path=output)
        sqlite_report, sqlite_errors = _sqlite_report(root, output)
    except (AuditError, LargeFileReportError, OSError) as exc:
        raise StorageReportError(str(exc)) from exc

    try:
        output.mkdir(parents=True, exist_ok=True)
        _write_json(output / INVENTORY_FILE_NAME, inventory)
        _write_json(output / ANALYSIS_REPORT_FILE_NAME, analysis)
        _write_json(output / LARGE_FILES_FILE_NAME, large_files)
        _write_json(output / SQLITE_FILE_NAME, sqlite_report)
    except OSError as exc:
        raise StorageReportError(f"cannot write report directory: {output}") from exc

    all_errors = [
        *inventory.get("errors", []),
        *analysis.get("errors", []),
        *large_files.get("errors", []),
        *sqlite_report.get("errors", []),
        *sqlite_errors,
    ]
    summary = _summary_markdown(inventory, analysis, large_files, sqlite_report, all_errors)
    try:
        (output / "SUMMARY.md").write_text(summary, encoding="utf-8")
    except OSError as exc:
        raise StorageReportError(f"cannot write report summary: {output / 'SUMMARY.md'}") from exc
    return {
        "output_directory": str(output),
        "inventory": inventory,
        "analysis": analysis,
        "large_files": large_files,
        "sqlite": sqlite_report,
        "summary": summary,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-path", type=Path, required=True, help="Site directory to inspect")
    parser.add_argument(
        "--output",
        "--output-dir",
        dest="output_directory",
        type=Path,
        default=Path(REPORT_DIRECTORY_NAME),
        help=f"report directory (default: {REPORT_DIRECTORY_NAME})",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        result = generate_storage_report(args.site_path, args.output_directory)
    except StorageReportError as exc:
        parser.error(str(exc))
    print(json.dumps({"output_directory": result["output_directory"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
