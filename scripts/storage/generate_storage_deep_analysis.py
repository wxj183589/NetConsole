"""Generate a complete, read-only deep attribution report for Site storage."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .analyze_backups import analyze_backup_duplicates, analyze_backups
from .analyze_history_db import analyze_history_db
from .analyze_rail_transit import analyze_rail_transit
from .audit_site import AuditError, audit_site


REPORT_FILES = (
    "RAIL_TRANSIT_ANALYSIS.json",
    "RAIL_TRANSIT_TIMELINE.json",
    "BACKUP_ANALYSIS.json",
    "BACKUP_DUPLICATE_ANALYSIS.json",
    "HISTORY_DB_ANALYSIS.json",
    "STORAGE_DEEP_ANALYSIS.md",
)


class DeepStorageAnalysisError(ValueError):
    """Raised when a deep report cannot be generated safely."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _site_paths(root: Path) -> list[Path]:
    if root.name.casefold() != "sites":
        return [root]
    try:
        return [child for child in sorted(root.iterdir(), key=lambda item: item.name.casefold()) if child.is_dir()]
    except OSError as exc:
        raise DeepStorageAnalysisError(f"cannot list sites root: {root}") from exc


def _aggregate_rail(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    directory_totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    extension_totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    timeline_totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    errors: list[str] = []
    total_size = 0
    total_files = 0
    for site in _site_paths(root):
        report = analyze_rail_transit(site)
        site_name = site.name if root.name.casefold() == "sites" else ""
        total_size += int(report["total_size_bytes"])
        total_files += int(report["total_files"])
        errors.extend(f"{site_name}: {error}" for error in report.get("errors", []))
        for item in report["directories"]:
            path = f"{site_name}/{item['path']}" if site_name else item["path"]
            bucket = directory_totals[path]
            bucket[0] += int(item["size_bytes"])
            bucket[1] += int(item["file_count"])
        for item in report["extension_summary"]:
            bucket = extension_totals[item["extension"]]
            bucket[0] += int(item["size_bytes"])
            bucket[1] += int(item["file_count"])
        for item in report["timeline"]:
            bucket = timeline_totals[item["period"]]
            bucket[0] += int(item["size_bytes"])
            bucket[1] += int(item["file_count"])
    directories = [
        {
            "path": path,
            "size_bytes": values[0],
            "file_count": values[1],
            "percentage": round(values[0] * 100 / total_size, 2) if total_size else 0.0,
        }
        for path, values in directory_totals.items()
    ]
    directories.sort(key=lambda item: (-item["size_bytes"], item["path"]))
    extensions = [
        {
            "extension": extension,
            "size_bytes": values[0],
            "file_count": values[1],
            "percentage": round(values[0] * 100 / total_size, 2) if total_size else 0.0,
        }
        for extension, values in extension_totals.items()
    ]
    extensions.sort(key=lambda item: (-item["size_bytes"], item["extension"]))
    timeline = [
        {
            "period": period,
            "size_bytes": values[0],
            "file_count": values[1],
            "percentage": round(values[0] * 100 / total_size, 2) if total_size else 0.0,
        }
        for period, values in timeline_totals.items()
    ]
    period_order = {"last_7_days": 0, "last_30_days": 1, "last_90_days": 2, "last_180_days": 3, "last_365_days": 4, "over_365_days": 5}
    timeline.sort(key=lambda item: period_order.get(item["period"], 99))
    rail = {
        "generated_at": _now(),
        "root_path": str(root),
        "total_size_bytes": total_size,
        "total_files": total_files,
        "directories": directories,
        "extension_summary": extensions,
        "errors": sorted(errors),
    }
    timeline_report = {
        "generated_at": rail["generated_at"],
        "root_path": str(root),
        "total_size_bytes": total_size,
        "timeline": timeline,
        "errors": sorted(errors),
    }
    return rail, timeline_report


def _format_bytes(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if amount < 1024 or unit == "TiB":
            return f"{int(amount)} {unit}" if unit == "B" else f"{amount:.2f} {unit}"
        amount /= 1024
    return f"{amount:.2f} TiB"


def _summary(
    inventory: dict[str, Any],
    rail: dict[str, Any],
    timeline: dict[str, Any],
    backups: dict[str, Any],
    duplicates: dict[str, Any],
    history: dict[str, Any],
) -> str:
    lines = [
        "# Storage Deep Analysis",
        "",
        "## Current Total",
        "",
        f"- Scan path: `{inventory.get('root_path', '')}`",
        f"- Generated at: `{inventory.get('generated_at', '')}`",
        f"- Total: **{_format_bytes(int(inventory.get('total_size_bytes', 0)))}**",
        f"- Files: **{int(inventory.get('total_files', 0))}**",
        "",
        "## rail_transit",
        "",
        f"- Occupancy: **{_format_bytes(int(rail['total_size_bytes']))}**",
        f"- Files: **{int(rail['total_files'])}**",
        "",
        "### Main Directories",
        "",
    ]
    for item in rail.get("directories", [])[:10]:
        lines.append(f"- `{item['path']}`: {_format_bytes(int(item['size_bytes']))} ({item['percentage']:.2f}%)")
    lines.extend(["", "### File Types", ""])
    for item in rail.get("extension_summary", []):
        if item["size_bytes"]:
            lines.append(f"- `{item['extension']}`: {_format_bytes(int(item['size_bytes']))} ({item['file_count']} files)")
    lines.extend(["", "### Time Distribution", ""])
    for item in timeline.get("timeline", []):
        lines.append(f"- `{item['period']}`: {_format_bytes(int(item['size_bytes']))} ({item['file_count']} files)")
    lines.extend(["", "## backups", ""])
    lines.append(f"- Occupancy: **{_format_bytes(int(backups.get('total_size_bytes', 0)))}**")
    lines.append(f"- Files: **{int(backups.get('total_files', 0))}**")
    class_totals: dict[str, int] = {}
    for item in backups.get("backups", []):
        class_totals[item["backup_type"]] = class_totals.get(item["backup_type"], 0) + int(item["size_bytes"])
    for name in ("PRODUCTION_MAINTENANCE", "DATABASE_MIGRATION", "ROLLBACK", "SNAPSHOT", "UNKNOWN"):
        lines.append(f"- `{name}`: {_format_bytes(class_totals.get(name, 0))}")
    lines.extend(["", "### Duplicate Files", ""])
    if duplicates.get("duplicates"):
        for item in duplicates["duplicates"][:20]:
            lines.append(f"- `{item['hash']}`: {_format_bytes(int(item['size']))}, {len(item['files'])} files")
    else:
        lines.append("- No exact duplicate groups were found among hashed candidates.")
    lines.extend(["", "## db/history", ""])
    lines.append(f"- Occupancy: **{_format_bytes(int(history.get('total_size_bytes', 0)))}**")
    for database in history.get("databases", [])[:10]:
        lines.append(f"- `{database['path']}`: {_format_bytes(int(database['size_bytes']))}")
        for table in database.get("tables", [])[:3]:
            lines.append(f"  - `{table['table_name']}`: {_format_bytes(int(table['size_bytes']))} ({table.get('row_count', 0)} rows)")
    lines.extend(["", "## Findings", ""])
    if rail["total_size_bytes"]:
        lines.append(f"- `files/rail_transit` contains {_format_bytes(int(rail['total_size_bytes']))} across the scanned Site set.")
    if backups.get("total_size_bytes"):
        lines.append(f"- `files/backups` contains {_format_bytes(int(backups['total_size_bytes']))} across the scanned Site set.")
    if history.get("total_size_bytes"):
        lines.append(f"- `db/history` contains {_format_bytes(int(history['total_size_bytes']))} across the scanned Site set.")
    errors = sorted(
        set(
            str(error)
            for report in (rail, timeline, backups, duplicates, history)
            for error in report.get("errors", [])
            if error
        )
    )
    lines.extend(["", "## Errors", ""])
    lines.extend(f"- {error}" for error in errors) if errors else lines.append("- None.")
    lines.append("")
    return "\n".join(lines)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def generate_deep_analysis(
    site_path: Path | str,
    output_directory: Path | str,
    *,
    inventory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(site_path).expanduser().resolve()
    output = Path(output_directory).expanduser().resolve()
    if not root.is_dir():
        raise DeepStorageAnalysisError(f"site path is not a directory: {root}")
    if output == root:
        raise DeepStorageAnalysisError("report directory cannot be the Site directory")
    try:
        current_inventory = inventory or audit_site(root, largest_file_count=50, excluded_path=output)
    except (AuditError, OSError) as exc:
        raise DeepStorageAnalysisError(str(exc)) from exc
    rail, timeline = _aggregate_rail(root)
    backups = analyze_backups(root)
    duplicates = analyze_backup_duplicates(root, backups)
    history = analyze_history_db(root)
    output.mkdir(parents=True, exist_ok=True)
    _write_json(output / "RAIL_TRANSIT_ANALYSIS.json", rail)
    _write_json(output / "RAIL_TRANSIT_TIMELINE.json", timeline)
    _write_json(output / "BACKUP_ANALYSIS.json", backups)
    _write_json(output / "BACKUP_DUPLICATE_ANALYSIS.json", duplicates)
    _write_json(output / "HISTORY_DB_ANALYSIS.json", history)
    (output / "STORAGE_DEEP_ANALYSIS.md").write_text(
        _summary(current_inventory, rail, timeline, backups, duplicates, history), encoding="utf-8"
    )
    return {
        "output_directory": str(output),
        "inventory": current_inventory,
        "rail_transit": rail,
        "timeline": timeline,
        "backups": backups,
        "duplicates": duplicates,
        "history": history,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-path", "--path", dest="site_path", type=Path, required=True)
    parser.add_argument("--output", "--output-dir", dest="output_directory", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, help="existing SITE_STORAGE_INVENTORY.json")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    existing = None
    if args.inventory:
        try:
            existing = json.loads(args.inventory.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            parser.error(f"cannot read inventory: {args.inventory}: {exc}")
    try:
        result = generate_deep_analysis(args.site_path, args.output_directory, inventory=existing)
    except DeepStorageAnalysisError as exc:
        parser.error(str(exc))
    print(json.dumps({"output_directory": result["output_directory"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
