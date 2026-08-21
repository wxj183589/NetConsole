"""Analyze directory shares from a SITE_STORAGE_INVENTORY.json report."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ANALYSIS_FILE_NAME = "SITE_STORAGE_ANALYSIS.json"


class SiteStorageAnalysisError(ValueError):
    """Raised when an inventory report cannot be analyzed."""


def _load_inventory(source: Path | str | Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(source, Mapping):
        return source
    path = Path(source).expanduser().resolve()
    if not path.is_file():
        raise SiteStorageAnalysisError(f"inventory report does not exist: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SiteStorageAnalysisError(f"cannot read inventory report: {path}") from exc
    if not isinstance(value, Mapping):
        raise SiteStorageAnalysisError("inventory report must contain a JSON object")
    return value


def _relative_segments(value: object) -> list[str]:
    path = str(value or "").replace("\\", "/").strip("/")
    return [segment for segment in path.split("/") if segment]


def analyze_site_storage(
    source: Path | str | Mapping[str, Any],
    *,
    depth: int = 1,
    top_count: int = 20,
    paths: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Return non-overlapping directory shares from an inventory report.

    ``depth=1`` selects direct children of the audited root.  Set ``depth=2``
    to compare second-level paths such as ``files/backups`` and
    ``files/imports`` without adding their parent directory again.  When
    ``paths`` is provided, those exact relative paths are returned, including
    zero-sized entries for directories that were not present in the inventory.
    """

    if depth < 1:
        raise SiteStorageAnalysisError("depth must be at least 1")
    if top_count < 0:
        raise SiteStorageAnalysisError("top_count must be non-negative")

    inventory = _load_inventory(source)
    directories = inventory.get("directories", [])
    if not isinstance(directories, list):
        raise SiteStorageAnalysisError("inventory directories must be a list")

    total_size = int(inventory.get("total_size_bytes", inventory.get("total_bytes", 0)) or 0)
    raw_errors = inventory.get("errors", []) or []
    if isinstance(raw_errors, Sequence) and not isinstance(raw_errors, (str, bytes)):
        errors = [str(item) for item in raw_errors]
    else:
        errors = [str(raw_errors)]

    directory_by_path: dict[str, Mapping[str, Any]] = {}
    for item in directories:
        if not isinstance(item, Mapping):
            errors.append("invalid directory entry: expected object")
            continue
        normalized = "/".join(_relative_segments(item.get("path")))
        directory_by_path[normalized] = item

    selected: list[dict[str, Any]] = []
    if paths is None:
        candidates = [
            "/".join(_relative_segments(item.get("path")))
            for item in directories
            if isinstance(item, Mapping)
            and len(_relative_segments(item.get("path"))) == depth
        ]
    else:
        candidates = sorted(
            {"/".join(_relative_segments(value)) for value in paths if _relative_segments(value)}
        )

    for path in candidates:
        item = directory_by_path.get(path, {})
        size_bytes = int(item.get("size_bytes", 0) or 0)
        selected.append(
            {
                "path": path,
                "size_bytes": size_bytes,
                "percentage": round(size_bytes * 100 / total_size, 2) if total_size else 0.0,
            }
        )

    selected.sort(key=lambda item: (-item["size_bytes"], item["path"]))
    errors.sort()
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "root_path": str(inventory.get("root_path", inventory.get("root", ""))),
        "total_size_bytes": total_size,
        "directory_depth": depth,
        "top_directories": selected[:top_count],
        "errors": errors,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="SITE_STORAGE_INVENTORY.json")
    parser.add_argument("--output", type=Path, help=f"output path (default name: {ANALYSIS_FILE_NAME})")
    parser.add_argument("--depth", type=int, default=1, help="directory depth to compare (default: 1)")
    parser.add_argument("--top", type=int, default=20, help="maximum entries to include (default: 20)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        report = analyze_site_storage(args.input, depth=args.depth, top_count=args.top)
    except SiteStorageAnalysisError as exc:
        parser.error(str(exc))

    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        output = args.output.expanduser().resolve()
        input_path = args.input.expanduser().resolve()
        if output == input_path:
            parser.error("analysis output cannot overwrite the inventory input")
        try:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(payload, encoding="utf-8")
        except OSError:
            parser.error(f"cannot write analysis report: {output}")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
