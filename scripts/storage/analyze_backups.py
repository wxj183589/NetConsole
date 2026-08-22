"""Read-only backup inventory and SHA-256 duplicate analysis."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


BACKUP_REPORT_FILE_NAME = "BACKUP_ANALYSIS.json"
DUPLICATE_REPORT_FILE_NAME = "BACKUP_DUPLICATE_ANALYSIS.json"
HASH_SIZE_THRESHOLD = 50 * 1024 * 1024
BACKUP_TYPES = (
    "PRODUCTION_MAINTENANCE",
    "DATABASE_MIGRATION",
    "ROLLBACK",
    "SNAPSHOT",
    "UNKNOWN",
)


class BackupAnalysisError(ValueError):
    """Raised when a backup tree cannot be scanned."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _find_roots(path: Path) -> list[tuple[Path, str]]:
    if not path.is_dir():
        raise BackupAnalysisError(f"path is not a directory: {path}")
    direct = path / "files" / "backups"
    if direct.is_dir():
        return [(direct, path.name)]
    roots: list[tuple[Path, str]] = []
    for child in sorted(path.iterdir(), key=lambda item: item.name.casefold()):
        if child.is_dir() and (child / "files" / "backups").is_dir():
            roots.append((child / "files" / "backups", child.name))
    return roots


def _classification(relative: str) -> str:
    value = relative.casefold()
    if "production-maintenance" in value:
        return "PRODUCTION_MAINTENANCE"
    if "database-migrations" in value or "migration" in value:
        return "DATABASE_MIGRATION"
    if "rollback" in value:
        return "ROLLBACK"
    if "snapshot" in value:
        return "SNAPSHOT"
    return "UNKNOWN"


def _walk(root: Path) -> tuple[list[tuple[Path, os.stat_result]], list[str]]:
    files: list[tuple[Path, os.stat_result]] = []
    errors: list[str] = []
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda item: item.name.casefold())
        except OSError as exc:
            errors.append(f"{directory}: {exc.__class__.__name__}: {exc}")
            continue
        for entry in entries:
            candidate = Path(entry.path).resolve()
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    pending.append(candidate)
                elif entry.is_file(follow_symlinks=False):
                    files.append((candidate, entry.stat(follow_symlinks=False)))
            except OSError as exc:
                errors.append(f"{candidate}: {exc.__class__.__name__}: {exc}")
    return files, errors


def analyze_backups(path: Path | str) -> dict[str, Any]:
    root = Path(path).expanduser().resolve()
    roots = _find_roots(root)
    all_files: list[dict[str, Any]] = []
    errors: list[str] = []
    for backup_root, site in roots:
        files, root_errors = _walk(backup_root)
        errors.extend(root_errors)
        report_root = root
        for file_path, stat in files:
            relative = _relative(file_path, report_root)
            all_files.append(
                {
                    "path": relative,
                    "size_bytes": int(stat.st_size),
                    "mtime": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(timespec="seconds"),
                    "site": site,
                    "backup_type": _classification(relative),
                }
            )
    all_files.sort(key=lambda item: (-item["size_bytes"], item["path"]))
    errors.sort()
    return {
        "generated_at": _now(),
        "root_path": str(root),
        "total_size_bytes": sum(item["size_bytes"] for item in all_files),
        "total_files": len(all_files),
        "backups": all_files,
        "files": all_files,
        "errors": errors,
    }


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def analyze_backup_duplicates(path: Path | str, inventory: dict[str, Any] | None = None) -> dict[str, Any]:
    root = Path(path).expanduser().resolve()
    report = inventory or analyze_backups(root)
    groups: dict[tuple[int, str], list[str]] = {}
    errors = list(report.get("errors", []))
    for item in report.get("backups", []):
        relative = str(item["path"])
        candidate = root / Path(relative)
        try:
            size = int(item["size_bytes"])
            if candidate.name.casefold() != "database.sqlite" and candidate.suffix.casefold() not in {".db", ".sqlite"} and size <= HASH_SIZE_THRESHOLD:
                continue
            digest = _hash_file(candidate)
        except (OSError, ValueError) as exc:
            errors.append(f"{relative}: {exc.__class__.__name__}: {exc}")
            continue
        groups.setdefault((size, digest), []).append(relative)
    duplicates = [
        {"hash": digest, "size": size, "files": sorted(files)}
        for (size, digest), files in groups.items()
        if len(files) > 1
    ]
    duplicates.sort(key=lambda item: (-item["size"], item["hash"]))
    errors.sort()
    return {
        "generated_at": _now(),
        "root_path": str(root),
        "candidate_count": sum(
            1
            for item in report.get("backups", [])
            if Path(str(item["path"])).name.casefold() == "database.sqlite"
            or Path(str(item["path"])).suffix.casefold() in {".db", ".sqlite"}
            or int(item.get("size_bytes", 0)) > HASH_SIZE_THRESHOLD
        ),
        "duplicates": duplicates,
        "errors": errors,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", "--site-path", dest="path", type=Path, required=True)
    parser.add_argument("--output", type=Path, help=f"backup output (default: {BACKUP_REPORT_FILE_NAME})")
    parser.add_argument("--duplicate-output", type=Path, help=f"duplicate output (default: {DUPLICATE_REPORT_FILE_NAME})")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        report = analyze_backups(args.path)
        duplicates = analyze_backup_duplicates(args.path, report)
    except BackupAnalysisError as exc:
        parser.error(str(exc))
    output = args.output.expanduser().resolve() if args.output else Path(BACKUP_REPORT_FILE_NAME).resolve()
    duplicate_output = args.duplicate_output.expanduser().resolve() if args.duplicate_output else output.parent / DUPLICATE_REPORT_FILE_NAME
    _write_json(output, report)
    _write_json(duplicate_output, duplicates)
    print(json.dumps({"output": str(output), "duplicate_output": str(duplicate_output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
