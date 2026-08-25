"""Aggregate read-only storage facts for a NetConsole ``sites`` root."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .analyze_sqlite_size import SQLiteSpaceReportError, analyze_sqlite_size


SITES_SUMMARY_FILE_NAME = "SITES_SUMMARY.json"
BACKUP_INVENTORY_FILE_NAME = "BACKUP_INVENTORY.json"
ALL_SQLITE_DATABASES_FILE_NAME = "ALL_SQLITE_DATABASES.json"
TOP_TABLE_USAGE_FILE_NAME = "TOP_TABLE_USAGE.json"
ROOT_STORAGE_FINDINGS_FILE_NAME = "ROOT_STORAGE_FINDINGS.md"
SQLITE_EXTENSIONS = {".db", ".sqlite", ".sqlite3"}
BACKUP_KEYWORDS = ("backup", "migration", "rollback", "staging")
DIRECTORY_CONTRIBUTION_PATHS = (
    "files/backups",
    "db/history",
    "HistoryStore",
    "rail_transit",
    "files/rail_transit",
    "db",
    "files",
)


class SitesRootAnalysisError(ValueError):
    """Raised when a sites-root inventory cannot be analyzed."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _load_inventory(source: Path | str | Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(source, Mapping):
        return source
    path = Path(source).expanduser().resolve()
    if not path.is_file():
        raise SitesRootAnalysisError(f"inventory report does not exist: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SitesRootAnalysisError(f"cannot read inventory report: {path}") from exc
    if not isinstance(value, Mapping):
        raise SitesRootAnalysisError("inventory report must contain a JSON object")
    return value


def _segments(value: object) -> list[str]:
    return [part for part in str(value or "").replace("\\", "/").split("/") if part]


def _inventory_errors(inventory: Mapping[str, Any]) -> list[str]:
    raw = inventory.get("errors", []) or []
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        return [str(item) for item in raw]
    return [str(raw)]


def analyze_sites_root(
    source: Path | str | Mapping[str, Any],
    *,
    top_count: int = 50,
) -> dict[str, Any]:
    """Return stable size and file-count rankings for direct Site directories."""

    if top_count < 0:
        raise SitesRootAnalysisError("top_count must be non-negative")
    inventory = _load_inventory(source)
    total_size = int(inventory.get("total_size_bytes", inventory.get("total_bytes", 0)) or 0)
    total_files = int(inventory.get("total_files", inventory.get("file_count", 0)) or 0)
    by_path: dict[str, Mapping[str, Any]] = {}
    errors = _inventory_errors(inventory)
    directories = inventory.get("directories", [])
    if not isinstance(directories, list):
        raise SitesRootAnalysisError("inventory directories must be a list")
    for entry in directories:
        if not isinstance(entry, Mapping):
            errors.append("invalid directory entry: expected object")
            continue
        path = "/".join(_segments(entry.get("path")))
        if path:
            by_path[path] = entry

    sites: list[dict[str, Any]] = []
    for path, entry in by_path.items():
        if len(_segments(path)) != 1:
            continue
        size_bytes = int(entry.get("size_bytes", 0) or 0)
        sites.append(
            {
                "site_name": path,
                "total_size_bytes": size_bytes,
                "total_files": int(entry.get("file_count", 0) or 0),
                "percentage": round(size_bytes * 100 / total_size, 2) if total_size else 0.0,
            }
        )
    sites.sort(key=lambda item: (-item["total_size_bytes"], item["site_name"]))
    errors.sort()
    return {
        "generated_at": _now(),
        "root_path": str(inventory.get("root_path", inventory.get("root", ""))),
        "total_size_bytes": total_size,
        "total_files": total_files,
        "sites": sites[:top_count],
        "errors": errors,
    }


def directory_contribution(
    source: Path | str | Mapping[str, Any],
    *,
    paths: Sequence[str] = DIRECTORY_CONTRIBUTION_PATHS,
) -> dict[str, Any]:
    """Aggregate the named relative paths across all Site directories."""

    inventory = _load_inventory(source)
    total_size = int(inventory.get("total_size_bytes", inventory.get("total_bytes", 0)) or 0)
    aggregates = {"/".join(_segments(path)): 0 for path in paths if _segments(path)}
    errors = _inventory_errors(inventory)
    directories = inventory.get("directories", [])
    if not isinstance(directories, list):
        raise SitesRootAnalysisError("inventory directories must be a list")
    for entry in directories:
        if not isinstance(entry, Mapping):
            errors.append("invalid directory entry: expected object")
            continue
        segments = _segments(entry.get("path"))
        if len(segments) < 2:
            continue
        relative = "/".join(segments[1:])
        if relative in aggregates:
            aggregates[relative] += int(entry.get("size_bytes", 0) or 0)
    top_directories = [
        {
            "path": path,
            "size_bytes": size,
            "percentage": round(size * 100 / total_size, 2) if total_size else 0.0,
        }
        for path, size in aggregates.items()
    ]
    top_directories.sort(key=lambda item: (-item["size_bytes"], item["path"]))
    errors.sort()
    return {
        "generated_at": _now(),
        "root_path": str(inventory.get("root_path", inventory.get("root", ""))),
        "total_size_bytes": total_size,
        "top_directories": top_directories,
        "errors": errors,
    }


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _excluded(path: Path, excluded: Path | None) -> bool:
    if excluded is None:
        return False
    try:
        path.relative_to(excluded)
    except ValueError:
        return False
    return True


def _walk_files(root: Path, excluded: Path | None) -> tuple[list[Path], list[str]]:
    files: list[Path] = []
    errors: list[str] = []
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda item: item.name.casefold())
        except OSError as exc:
            errors.append(f"{_relative(directory, root)}: {exc.__class__.__name__}: {exc}")
            continue
        for entry in entries:
            candidate = Path(entry.path).resolve()
            try:
                if entry.is_symlink() or _excluded(candidate, excluded):
                    continue
                if entry.is_dir(follow_symlinks=False):
                    pending.append(candidate)
                elif entry.is_file(follow_symlinks=False):
                    files.append(candidate)
            except OSError as exc:
                errors.append(f"{_relative(candidate, root)}: {exc.__class__.__name__}: {exc}")
    files.sort(key=lambda path: _relative(path, root).casefold())
    errors.sort()
    return files, errors


def _backup_classification(extension: str, keywords: list[str]) -> str:
    if "migration" in keywords:
        return "MIGRATION"
    if "rollback" in keywords:
        return "ROLLBACK"
    if "staging" in keywords:
        return "STAGING"
    if "backup" in keywords or extension in {".bak", ".backup"}:
        return "BACKUP"
    return "UNKNOWN"


def backup_inventory(
    root: Path | str,
    *,
    excluded_path: Path | str | None = None,
) -> dict[str, Any]:
    """List every file below ``files/backups`` in every Site."""

    root_path = Path(root).expanduser().resolve()
    excluded = Path(excluded_path).expanduser().resolve() if excluded_path is not None else None
    try:
        all_files, errors = _walk_files(root_path, excluded)
    except OSError as exc:
        raise SitesRootAnalysisError(f"cannot scan sites root: {root_path}") from exc
    items: list[dict[str, Any]] = []
    for path in all_files:
        relative = _relative(path, root_path)
        segments = _segments(relative)
        if len(segments) < 3 or segments[1].casefold() != "files" or segments[2].casefold() != "backups":
            continue
        try:
            stat_result = path.stat()
        except OSError as exc:
            errors.append(f"{relative}: {exc.__class__.__name__}: {exc}")
            continue
        lower = relative.casefold()
        keywords = sorted(keyword for keyword in BACKUP_KEYWORDS if keyword in lower)
        extension = path.suffix.casefold()
        items.append(
            {
                "path": relative,
                "size_bytes": int(stat_result.st_size),
                "mtime": datetime.fromtimestamp(stat_result.st_mtime, tz=UTC).isoformat(timespec="seconds"),
                "extension": extension,
                "parent_site": segments[0],
                "keywords": keywords,
                "classification": _backup_classification(extension, keywords),
            }
        )
    items.sort(key=lambda item: (-item["size_bytes"], item["path"]))
    errors.sort()
    return {"generated_at": _now(), "root_path": str(root_path), "files": items, "errors": errors}


def all_sqlite_databases(
    root: Path | str,
    *,
    excluded_path: Path | str | None = None,
) -> dict[str, Any]:
    """List all SQLite-looking files below the sites root without opening them."""

    root_path = Path(root).expanduser().resolve()
    excluded = Path(excluded_path).expanduser().resolve() if excluded_path is not None else None
    files, errors = _walk_files(root_path, excluded)
    databases: list[dict[str, Any]] = []
    for path in files:
        if path.suffix.casefold() not in SQLITE_EXTENSIONS:
            continue
        relative = _relative(path, root_path)
        try:
            size_bytes = int(path.stat().st_size)
        except OSError as exc:
            errors.append(f"{relative}: {exc.__class__.__name__}: {exc}")
            continue
        segments = _segments(relative)
        databases.append(
            {
                "database": relative,
                "site": segments[0] if segments else "",
                "size_bytes": size_bytes,
            }
        )
    databases.sort(key=lambda item: (-item["size_bytes"], item["database"]))
    errors.sort()
    return {"generated_at": _now(), "root_path": str(root_path), "databases": databases, "errors": errors}


def top_table_usage(
    root: Path | str,
    *,
    excluded_path: Path | str | None = None,
) -> dict[str, Any]:
    """Analyze readable ``tasks.db`` and ``devices.db`` files read-only."""

    root_path = Path(root).expanduser().resolve()
    database_report = all_sqlite_databases(root_path, excluded_path=excluded_path)
    errors = list(database_report["errors"])
    reports: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    for database in database_report["databases"]:
        if Path(database["database"]).name.casefold() not in {"tasks.db", "devices.db"}:
            continue
        path = root_path / Path(database["database"])
        try:
            report = analyze_sqlite_size(path)
        except SQLiteSpaceReportError as exc:
            errors.append(f"{database['database']}: {exc}")
            continue
        item = {
            "database": database["database"],
            "site": database["site"],
            "size_bytes": database["size_bytes"],
            "allocation_source": report.get("allocation_source", "unknown"),
            "tables": report.get("tables", []),
            "errors": report.get("errors", []),
        }
        reports.append(item)
        errors.extend(f"{database['database']}: {error}" for error in report.get("errors", []))
        for table in report.get("tables", []):
            flattened = dict(table)
            flattened.update({"database": database["database"], "site": database["site"]})
            tables.append(flattened)
    tables.sort(key=lambda item: (-int(item.get("size_bytes", 0)), item["database"], item["table_name"]))
    errors.sort()
    return {
        "generated_at": _now(),
        "root_path": str(root_path),
        "databases": reports,
        "tables": tables,
        "errors": errors,
    }


def _format_bytes(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1024 or unit == "TB":
            return f"{int(amount)} {unit}" if unit == "B" else f"{amount:.2f} {unit}"
        amount /= 1024
    return f"{amount:.2f} TB"


def render_root_findings(
    inventory: Mapping[str, Any],
    sites: Mapping[str, Any],
    directories: Mapping[str, Any],
    backups: Mapping[str, Any],
    sqlite_databases: Mapping[str, Any],
    table_usage: Mapping[str, Any],
) -> str:
    """Render a factual Markdown summary without recommendations."""

    lines = [
        "# NetConsole Sites Storage Findings",
        "",
        "## Total",
        "",
        f"- Scan path: `{inventory.get('root_path', '')}`",
        f"- Generated at: `{inventory.get('generated_at', '')}`",
        f"- Total: **{_format_bytes(int(inventory.get('total_size_bytes', 0) or 0))}**",
        f"- Files: **{int(inventory.get('total_files', 0) or 0)}**",
        "",
        "## Site contribution",
        "",
    ]
    for index, item in enumerate(sites.get("sites", []), start=1):
        lines.append(
            f"{index}. `{item['site_name']}`: {_format_bytes(int(item['total_size_bytes']))} "
            f"({item['percentage']:.2f}%, {int(item['total_files'])} files)"
        )
    if not sites.get("sites"):
        lines.append("- No Site directories found.")
    lines.extend(["", "## Directory contribution", ""])
    for item in directories.get("top_directories", []):
        lines.append(
            f"- `{item['path']}`: {_format_bytes(int(item['size_bytes']))} "
            f"({item['percentage']:.2f}%)"
        )
    lines.extend(["", "## Largest files", ""])
    largest_files = inventory.get("largest_files", [])[:50]
    for index, item in enumerate(largest_files, start=1):
        lines.append(f"{index}. `{item['path']}`: {_format_bytes(int(item['size_bytes']))}")
    if not largest_files:
        lines.append("- No files found.")
    lines.extend(["", "## SQLite usage", ""])
    for item in table_usage.get("tables", [])[:10]:
        lines.append(
            f"- `{item['database']}` / `{item['table_name']}`: "
            f"{_format_bytes(int(item.get('size_bytes', 0)))} "
            f"({int(item.get('row_count', 0))} rows, {item.get('percentage', 0):.2f}%)"
        )
    if not table_usage.get("tables"):
        lines.append("- No readable tasks.db or devices.db tables found.")
    lines.extend(["", "## Observations", ""])
    if sites.get("sites"):
        largest = sites["sites"][0]
        lines.append(
            f"- `{largest['site_name']}` is the largest listed Site at "
            f"{_format_bytes(int(largest['total_size_bytes']))}."
        )
    for item in directories.get("top_directories", []):
        if item["size_bytes"]:
            lines.append(
                f"- `{item['path']}` contains {_format_bytes(int(item['size_bytes']))} "
                "across the scanned Sites."
            )
    if backups.get("files"):
        backup_size = sum(int(item["size_bytes"]) for item in backups["files"])
        lines.append(f"- `files/backups` contains {_format_bytes(backup_size)} across all Sites.")
    if sqlite_databases.get("databases"):
        lines.append(f"- {len(sqlite_databases['databases'])} SQLite-looking files were found.")
    errors = sorted(
        set(
            str(error)
            for report in (inventory, sites, directories, backups, sqlite_databases, table_usage)
            for error in report.get("errors", [])
            if error
        )
    )
    lines.extend(["", "## Errors", ""])
    lines.extend(f"- {error}" for error in errors) if errors else lines.append("- None.")
    lines.append("")
    return "\n".join(lines)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="SITE_STORAGE_INVENTORY.json")
    parser.add_argument("--output", type=Path, help=f"output path (default: {SITES_SUMMARY_FILE_NAME})")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        report = analyze_sites_root(args.input)
    except SitesRootAnalysisError as exc:
        parser.error(str(exc))
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        output = args.output.expanduser().resolve()
        try:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(payload, encoding="utf-8")
        except OSError:
            parser.error(f"cannot write sites summary: {output}")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
