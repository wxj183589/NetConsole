"""Read-only profile for the Task Center cleanup schema across a data root."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from netconsole.repositories.task_cleanup_schema import inspect_task_cleanup_schema


def _task_databases(data_root: Path, site: str | None) -> list[tuple[str, Path]]:
    sites_root = Path(data_root).resolve() / "sites"
    if site:
        return [(site, sites_root / site / "db" / "tasks.db")]
    if not sites_root.is_dir():
        return []
    return [
        (item.name, item / "db" / "tasks.db")
        for item in sorted(sites_root.iterdir(), key=lambda path: path.name.casefold())
        if item.is_dir() and (item / "db" / "tasks.db").is_file()
    ]


def profile_task_schema_root(
    data_root: str | Path,
    *,
    site: str | None = None,
    immutable: bool = True,
) -> dict[str, Any]:
    root = Path(data_root).resolve()
    profiles: list[dict[str, Any]] = []
    for site_name, database in _task_databases(root, site):
        profile = inspect_task_cleanup_schema(database, immutable=immutable)
        profiles.append(
            {
                "site": site_name,
                "database": str(database.resolve()),
                "schema_compatibility": "PASS"
                if profile.get("apply_compatible")
                else "SAFE_BUT_SCHEMA_BLOCKED",
                "migration_required": bool(profile.get("migration_required")),
                "cleanup_ready": bool(profile.get("cleanup_ready")),
                "profile": profile,
            }
        )
    legacy = [item for item in profiles if not item["cleanup_ready"]]
    return {
        "format": "netconsole-task-schema-profile-v1",
        "data_root": str(root),
        "read_only": True,
        "production_data_mutated": False,
        "databases": profiles,
        "DATABASE_COUNT": len(profiles),
        "LEGACY_DB_COUNT": len(legacy),
        "LEGACY_SITES": [str(item["site"]) for item in legacy],
        "TASK_SCHEMA_COMPATIBILITY": {
            "required": len(profiles),
            "passed": len(profiles) - len(legacy),
            "status": "PASS" if not legacy else "BLOCKED",
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--site")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--include-wal",
        action="store_true",
        help="read the active read-only view instead of immutable main-file mode",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = args.data_root.resolve()
    output = args.output.resolve()
    if output.is_relative_to(root):
        raise SystemExit("schema profile output must remain outside the data root")
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")
    report = profile_task_schema_root(
        root,
        site=args.site,
        immutable=not args.include_wal,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({key: report[key] for key in ("LEGACY_DB_COUNT", "LEGACY_SITES", "TASK_SCHEMA_COMPATIBILITY")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
