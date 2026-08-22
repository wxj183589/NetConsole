"""Read-only attribution analysis for a Site's ``files/rail_transit`` tree."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPORT_FILE_NAME = "RAIL_TRANSIT_ANALYSIS.json"
TIMELINE_FILE_NAME = "RAIL_TRANSIT_TIMELINE.json"
EXTENSIONS = (".log", ".zip", ".db", ".sqlite", ".json", ".csv", "other")
PERIODS = (
    ("last_7_days", 7),
    ("last_30_days", 30),
    ("last_90_days", 90),
    ("last_180_days", 180),
    ("last_365_days", 365),
    ("over_365_days", None),
)


class RailTransitAnalysisError(ValueError):
    """Raised when a rail-transit tree cannot be analyzed."""


def _now() -> datetime:
    return datetime.now(UTC)


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


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
            errors.append(f"{_relative(directory, root)}: {exc.__class__.__name__}: {exc}")
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
                errors.append(f"{_relative(candidate, root)}: {exc.__class__.__name__}: {exc}")
    files.sort(key=lambda item: _relative(item[0], root).casefold())
    errors.sort()
    return files, errors


def _rail_root(site_path: Path | str) -> tuple[Path, str]:
    site = Path(site_path).expanduser().resolve()
    if not site.is_dir():
        raise RailTransitAnalysisError(f"site path is not a directory: {site}")
    root = site / "files" / "rail_transit"
    return root, str(site)


def _extension(path: Path) -> str:
    suffix = path.suffix.casefold()
    return suffix if suffix in EXTENSIONS[:-1] else "other"


def _period(age_days: float) -> str:
    if age_days <= 7:
        return PERIODS[0][0]
    if age_days <= 30:
        return PERIODS[1][0]
    if age_days <= 90:
        return PERIODS[2][0]
    if age_days <= 180:
        return PERIODS[3][0]
    if age_days <= 365:
        return PERIODS[4][0]
    return PERIODS[5][0]


def analyze_rail_transit(site_path: Path | str) -> dict[str, Any]:
    root, site = _rail_root(site_path)
    errors: list[str] = []
    if root.exists():
        files, errors = _walk(root)
    else:
        files = []

    total_size = sum(int(stat.st_size) for _, stat in files)
    directory_stats: dict[str, list[int]] = {}
    extension_stats = {extension: [0, 0] for extension in EXTENSIONS}
    timeline_stats = {period: [0, 0] for period, _ in PERIODS}
    now = _now()
    for path, stat in files:
        relative = _relative(path, root)
        parts = relative.split("/")
        for depth in (1, 2):
            if len(parts) >= depth + 1:
                directory = "/".join(parts[:depth])
                bucket = directory_stats.setdefault(directory, [0, 0])
                bucket[0] += int(stat.st_size)
                bucket[1] += 1
        extension_bucket = extension_stats[_extension(path)]
        extension_bucket[0] += int(stat.st_size)
        extension_bucket[1] += 1
        age_days = (now - datetime.fromtimestamp(stat.st_mtime, tz=UTC)).total_seconds() / 86400
        period_bucket = timeline_stats[_period(age_days)]
        period_bucket[0] += int(stat.st_size)
        period_bucket[1] += 1

    directories = [
        {
            "path": path,
            "size_bytes": size,
            "file_count": count,
            "percentage": round(size * 100 / total_size, 2) if total_size else 0.0,
        }
        for path, (size, count) in directory_stats.items()
    ]
    directories.sort(key=lambda item: (-item["size_bytes"], item["path"]))
    extension_summary = [
        {
            "extension": extension,
            "size_bytes": values[0],
            "file_count": values[1],
            "percentage": round(values[0] * 100 / total_size, 2) if total_size else 0.0,
        }
        for extension, values in extension_stats.items()
    ]
    extension_summary.sort(key=lambda item: (-item["size_bytes"], item["extension"]))
    timeline = [
        {
            "period": period,
            "size_bytes": values[0],
            "file_count": values[1],
            "percentage": round(values[0] * 100 / total_size, 2) if total_size else 0.0,
        }
        for period, values in timeline_stats.items()
    ]
    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "site_path": site,
        "root_path": str(root),
        "total_size_bytes": total_size,
        "total_files": len(files),
        "directories": directories,
        "extension_summary": extension_summary,
        "timeline": timeline,
        "errors": sorted(errors),
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-path", "--path", dest="site_path", type=Path, required=True)
    parser.add_argument("--output", type=Path, help=f"output path (default: {REPORT_FILE_NAME})")
    parser.add_argument("--timeline-output", type=Path, help=f"timeline output (default: {TIMELINE_FILE_NAME})")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        report = analyze_rail_transit(args.site_path)
    except RailTransitAnalysisError as exc:
        parser.error(str(exc))
    output = args.output.expanduser().resolve() if args.output else Path(REPORT_FILE_NAME).resolve()
    _write_json(output, report)
    timeline_output = args.timeline_output.expanduser().resolve() if args.timeline_output else output.parent / TIMELINE_FILE_NAME
    _write_json(
        timeline_output,
        {
            "generated_at": report["generated_at"],
            "site_path": report["site_path"],
            "root_path": report["root_path"],
            "total_size_bytes": report["total_size_bytes"],
            "timeline": report["timeline"],
            "errors": report["errors"],
        },
    )
    print(json.dumps({"output": str(output), "timeline_output": str(timeline_output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
