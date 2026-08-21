"""Read-only directory inventory for NetConsole storage investigations."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import MutableMapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


INVENTORY_FILE_NAME = "SITE_STORAGE_INVENTORY.json"


class AuditError(RuntimeError):
    """Raised when the requested directory cannot be audited safely."""


def _modified_time(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=UTC).isoformat(timespec="seconds")


def _relative_path(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _is_excluded(path: Path, excluded_path: Path | None) -> bool:
    if excluded_path is None:
        return False
    try:
        path.relative_to(excluded_path)
    except ValueError:
        return False
    return True


def _scan_directory(
    directory: Path,
    root: Path,
    directories: list[dict[str, Any]],
    largest_files: list[dict[str, Any]],
    extensions: MutableMapping[str, list[int]],
    errors: list[str],
    excluded_path: Path | None,
) -> tuple[int, int]:
    total_bytes = 0
    file_count = 0

    try:
        entries = os.scandir(directory)
    except OSError as exc:
        if directory == root:
            raise AuditError(f"cannot read directory: {directory}") from exc
        errors.append(f"{_relative_path(directory, root)}: {exc.__class__.__name__}: {exc}")
        return 0, 0

    with entries:
        for entry in entries:
            candidate = Path(entry.path)
            try:
                if entry.is_symlink():
                    continue
                if _is_excluded(candidate, excluded_path):
                    continue
                if entry.is_dir(follow_symlinks=False):
                    child_bytes, child_count = _scan_directory(
                        candidate,
                        root,
                        directories,
                        largest_files,
                        extensions,
                        errors,
                        excluded_path,
                    )
                    total_bytes += child_bytes
                    file_count += child_count
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                stat_result = entry.stat(follow_symlinks=False)
            except OSError as exc:
                errors.append(
                    f"{_relative_path(candidate, root)}: {exc.__class__.__name__}: {exc}"
                )
                continue

            size_bytes = stat_result.st_size
            total_bytes += size_bytes
            file_count += 1
            largest_files.append(
                {
                    "path": _relative_path(candidate, root),
                    "size_bytes": size_bytes,
                    "modified_time": _modified_time(stat_result.st_mtime),
                }
            )
            extension = candidate.suffix.casefold()
            bucket = extensions.setdefault(extension, [0, 0])
            bucket[0] += size_bytes
            bucket[1] += 1

    if directory != root:
        try:
            directory_stat = directory.stat(follow_symlinks=False)
        except OSError as exc:
            errors.append(
                f"{_relative_path(directory, root)}: {exc.__class__.__name__}: {exc}"
            )
            directory_modified_time = ""
        else:
            directory_modified_time = _modified_time(directory_stat.st_mtime)
        directories.append(
            {
                "path": _relative_path(directory, root),
                "size_bytes": total_bytes,
                "file_count": file_count,
                "modified_time": directory_modified_time,
            }
        )
    return total_bytes, file_count


def audit_site(
    path: Path | str,
    *,
    largest_file_count: int = 20,
    excluded_path: Path | str | None = None,
) -> dict[str, Any]:
    """Return a read-only inventory for ``path``.

    ``excluded_path`` is intended for an output report located below the
    audited root, so the report itself does not affect a later inventory.
    Symbolic links are skipped and never followed.
    """

    if largest_file_count < 0:
        raise AuditError("largest_file_count must be non-negative")

    root = Path(path).expanduser().resolve()
    if not root.exists():
        raise AuditError(f"path does not exist: {root}")
    if not root.is_dir():
        raise AuditError(f"path is not a directory: {root}")

    excluded = Path(excluded_path).expanduser().resolve() if excluded_path is not None else None
    directories: list[dict[str, Any]] = []
    largest_files: list[dict[str, Any]] = []
    extensions: dict[str, list[int]] = {}
    errors: list[str] = []
    total_bytes, file_count = _scan_directory(
        root,
        root,
        directories,
        largest_files,
        extensions,
        errors,
        excluded,
    )

    directories.sort(key=lambda item: (-item["size_bytes"], item["path"]))
    largest_files.sort(key=lambda item: (-item["size_bytes"], item["path"]))
    extension_items = [
        {
            "extension": extension,
            "size_bytes": values[0],
            "file_count": values[1],
        }
        for extension, values in extensions.items()
    ]
    extension_items.sort(key=lambda item: (-item["size_bytes"], item["extension"]))
    errors.sort()
    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "root_path": str(root),
        "total_size_bytes": total_bytes,
        "total_files": file_count,
        "directories": directories,
        "largest_files": largest_files[:largest_file_count],
        "extensions": extension_items,
        "errors": errors,
    }
    # Keep the original Python/CLI result keys for callers of the first version.
    report.update(
        {
            "root": str(root),
            "total_bytes": total_bytes,
            "file_count": file_count,
        }
    )
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, required=True, help="directory to inspect")
    parser.add_argument(
        "--output",
        type=Path,
        help=(
            f"JSON report path (for example {INVENTORY_FILE_NAME}); "
            "when omitted, the report is written to stdout only"
        ),
    )
    parser.add_argument(
        "--top",
        type=int,
        default=20,
        help="maximum number of largest files to include (default: 20)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.top < 0:
        parser.error("--top must be non-negative")

    try:
        report = audit_site(args.path, largest_file_count=args.top, excluded_path=args.output)
    except AuditError as exc:
        parser.error(str(exc))

    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        output = args.output.expanduser().resolve()
        try:
            if output == Path(args.path).expanduser().resolve():
                parser.error("report output cannot overwrite the audited directory")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(payload, encoding="utf-8")
        except OSError:
            parser.error(f"cannot write report: {output}")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
