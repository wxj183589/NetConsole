"""Read-only attribution analysis for Site ``db/history`` databases."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .analyze_sqlite_size import SQLiteSpaceReportError, analyze_sqlite_size


REPORT_FILE_NAME = "HISTORY_DB_ANALYSIS.json"
SQLITE_EXTENSIONS = {".db", ".sqlite", ".sqlite3"}


class HistoryDbAnalysisError(ValueError):
    """Raised when a history tree cannot be inspected."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _find_roots(path: Path) -> list[tuple[Path, str]]:
    if not path.is_dir():
        raise HistoryDbAnalysisError(f"path is not a directory: {path}")
    direct = path / "db" / "history"
    if direct.is_dir():
        return [(direct, path.name)]
    roots: list[tuple[Path, str]] = []
    for child in sorted(path.iterdir(), key=lambda item: item.name.casefold()):
        if child.is_dir() and (child / "db" / "history").is_dir():
            roots.append((child / "db" / "history", child.name))
    return roots


def analyze_history_db(path: Path | str) -> dict[str, Any]:
    root = Path(path).expanduser().resolve()
    database_roots = _find_roots(root)
    databases: list[dict[str, Any]] = []
    errors: list[str] = []
    for history_root, site in database_roots:
        try:
            entries = sorted(history_root.iterdir(), key=lambda item: item.name.casefold())
        except OSError as exc:
            errors.append(f"{history_root}: {exc.__class__.__name__}: {exc}")
            continue
        for database in entries:
            if not database.is_file() or database.is_symlink() or database.suffix.casefold() not in SQLITE_EXTENSIONS:
                continue
            relative = database.relative_to(root).as_posix()
            stat_result = None
            try:
                stat_result = database.stat()
                report = analyze_sqlite_size(database)
            except (OSError, SQLiteSpaceReportError) as exc:
                errors.append(f"{relative}: {exc}")
                try:
                    size_bytes = database.stat().st_size
                except OSError:
                    size_bytes = 0
                databases.append(
                    {
                        "filename": database.name,
                        "path": relative,
                        "site": site,
                        "size_bytes": int(size_bytes),
                        "mtime": datetime.fromtimestamp(stat_result.st_mtime, tz=UTC).isoformat(timespec="seconds") if stat_result else "",
                        "tables": [],
                        "errors": [str(exc)],
                    }
                )
                continue
            databases.append(
                {
                    "filename": database.name,
                    "path": relative,
                    "site": site,
                    "size_bytes": int(stat_result.st_size),
                    "mtime": datetime.fromtimestamp(stat_result.st_mtime, tz=UTC).isoformat(timespec="seconds"),
                    "allocation_source": report.get("allocation_source", "unknown"),
                    "tables": report.get("tables", []),
                    "errors": report.get("errors", []),
                }
            )
            errors.extend(f"{relative}: {error}" for error in report.get("errors", []))
    databases.sort(key=lambda item: (-item["size_bytes"], item["path"]))
    errors.sort()
    return {
        "generated_at": _now(),
        "root_path": str(root),
        "total_size_bytes": sum(item["size_bytes"] for item in databases),
        "total_files": len(databases),
        "databases": databases,
        "errors": errors,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", "--site-path", dest="path", type=Path, required=True)
    parser.add_argument("--output", type=Path, help=f"output path (default: {REPORT_FILE_NAME})")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        report = analyze_history_db(args.path)
    except HistoryDbAnalysisError as exc:
        parser.error(str(exc))
    output = args.output.expanduser().resolve() if args.output else Path(REPORT_FILE_NAME).resolve()
    _write_json(output, report)
    print(json.dumps({"output": str(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
