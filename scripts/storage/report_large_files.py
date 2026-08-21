"""Read-only classification report for large storage files."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPORT_FILE_NAME = "LARGE_FILES_REPORT.json"
DATABASE_EXTENSIONS = {".db", ".sqlite", ".sqlite3"}
BACKUP_EXTENSIONS = {".bak", ".backup", ".candidate", ".rollback"}
ARCHIVE_EXTENSIONS = {".zip"}
LOG_EXTENSIONS = {".log"}
TEMP_EXTENSIONS = {".tmp"}
PATH_KEYWORDS = ("backup", "migration", "staging", "snapshot", "rollback", "candidate")
ALL_EXTENSIONS = (
    DATABASE_EXTENSIONS
    | BACKUP_EXTENSIONS
    | ARCHIVE_EXTENSIONS
    | LOG_EXTENSIONS
    | TEMP_EXTENSIONS
)


class LargeFileReportError(ValueError):
    """Raised when a large-file report cannot be generated."""


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _classify(extension: str, matched_keywords: list[str]) -> str:
    if extension in BACKUP_EXTENSIONS or matched_keywords:
        return "BACKUP_LIKE"
    if extension in DATABASE_EXTENSIONS:
        return "DATABASE"
    if extension in LOG_EXTENSIONS:
        return "LOG"
    if extension in ARCHIVE_EXTENSIONS:
        return "ARCHIVE"
    if extension in TEMP_EXTENSIONS:
        return "TEMP"
    return "UNKNOWN"


def scan_large_files(path: Path | str) -> tuple[list[dict[str, Any]], list[str]]:
    root = Path(path).expanduser().resolve()
    if not root.exists():
        raise LargeFileReportError(f"path does not exist: {root}")
    if not root.is_dir():
        raise LargeFileReportError(f"path is not a directory: {root}")

    files: list[dict[str, Any]] = []
    errors: list[str] = []
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda item: item.name.casefold())
        except OSError as exc:
            if directory == root:
                raise LargeFileReportError(f"cannot read directory: {directory}") from exc
            errors.append(f"{_relative(directory, root)}: {exc.__class__.__name__}: {exc}")
            continue
        for entry in entries:
            candidate = Path(entry.path)
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    pending.append(candidate)
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                stat_result = entry.stat(follow_symlinks=False)
            except OSError as exc:
                errors.append(
                    f"{_relative(candidate, root)}: {exc.__class__.__name__}: {exc}"
                )
                continue

            relative = _relative(candidate, root)
            extension = candidate.suffix.casefold()
            path_lower = relative.casefold()
            matched_keywords = sorted(
                {keyword for keyword in PATH_KEYWORDS if keyword in path_lower}
            )
            if extension not in ALL_EXTENSIONS and not matched_keywords:
                continue
            files.append(
                {
                    "path": relative,
                    "size": int(stat_result.st_size),
                    "extension": extension,
                    "matched_keywords": matched_keywords,
                    "classification": _classify(extension, matched_keywords),
                }
            )

    files.sort(key=lambda item: (-item["size"], item["path"]))
    errors.sort()
    return files, errors


def large_files_report(path: Path | str) -> dict[str, Any]:
    root = Path(path).expanduser().resolve()
    files, errors = scan_large_files(root)
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "root_path": str(root),
        "large_files": files,
        "errors": errors,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, required=True, help="directory to inspect")
    parser.add_argument("--output", type=Path, help=f"output path (default name: {REPORT_FILE_NAME})")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        report = large_files_report(args.path)
    except LargeFileReportError as exc:
        parser.error(str(exc))

    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        output = args.output.expanduser().resolve()
        try:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(payload, encoding="utf-8")
        except OSError:
            parser.error(f"cannot write large-file report: {output}")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
