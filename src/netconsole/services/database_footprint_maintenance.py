from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from netconsole.core.paths import PathResolver
from netconsole.services.database_upgrade.sqlite_consistency import fsync_file, sha256_file
from netconsole.services.site_storage import SiteRecord, SiteStorageError, validate_site_id


DEVELOPMENT_ROOT = Path("D:/study")
SNAPSHOT_FORMAT = "netconsole-sqlite-online-backup-v1"


def assert_development_path(
    path: str | Path,
    *,
    development_root: str | Path = DEVELOPMENT_ROOT,
) -> Path:
    """Fail closed unless a destructive target is inside the development root."""

    target = Path(path).resolve()
    root = Path(development_root).resolve()
    if target == root:
        raise ValueError("development root itself is not a valid maintenance target")
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"maintenance target must be under {root}") from exc
    return target


def resolve_registered_active_site_readonly(paths: PathResolver) -> SiteRecord:
    """Resolve the configured site using JSON metadata without discovery or writes."""

    application = _read_json_object(paths.app_config_path, "application config")
    registry_path = paths.config_dir / "site_registry.json"
    registry = _read_json_object(registry_path, "site registry")
    current = str(application.get("current_site") or "").strip()
    if not current:
        raise SiteStorageError("ACTIVE_SITE_AMBIGUOUS", "application config has no current_site")

    candidates: list[SiteRecord] = []
    sites_root = paths.sites_dir.resolve()
    for item in registry.get("sites", []):
        if not isinstance(item, dict):
            continue
        site_id = str(item.get("site_id") or "").strip()
        display_name = str(item.get("display_name") or "").strip()
        relative_text = str(item.get("relative_path") or "").strip()
        relative = Path(relative_text)
        if (
            not site_id
            or not display_name
            or not relative_text
            or relative.is_absolute()
            or any(part in {"", ".", ".."} for part in relative.parts)
        ):
            continue
        try:
            validate_site_id(site_id)
        except SiteStorageError:
            continue
        root = (paths.data_root / relative).resolve()
        try:
            root.relative_to(sites_root)
        except ValueError:
            continue
        if root.parent != sites_root or root.is_symlink() or not root.is_dir():
            continue
        aliases = {site_id.casefold(), display_name.casefold(), root.name.casefold()}
        if current.casefold() not in aliases:
            continue
        candidates.append(
            SiteRecord(
                site_id=site_id,
                display_name=display_name,
                root_path=root,
                created_at=str(item.get("created_at") or ""),
                updated_at=str(item.get("updated_at") or ""),
                remark=str(item.get("remark") or ""),
                line_name=_optional_text(item.get("line_name")),
                project_type=_optional_text(item.get("project_type")),
            )
        )
    if len(candidates) != 1:
        raise SiteStorageError(
            "ACTIVE_SITE_AMBIGUOUS",
            f"registered active site must resolve exactly once; matched={len(candidates)}",
        )
    record = candidates[0]
    for name in ("devices.db", "tasks.db"):
        database = record.root_path / "db" / name
        if database.is_symlink() or not database.is_file() or database.stat().st_size <= 0:
            raise SiteStorageError(
                "ACTIVE_SITE_DATABASE_INVALID", f"active site database is missing: {name}"
            )
    return record


def sqlite_online_backup_readonly(
    source: str | Path,
    destination: str | Path,
    *,
    development_root: str | Path = DEVELOPMENT_ROOT,
) -> dict[str, Any]:
    """Create one consistent SQLite snapshot while opening the source read-only."""

    source_path = Path(source).resolve()
    destination_path = assert_development_path(
        destination, development_root=development_root
    )
    if source_path.is_symlink() or not source_path.is_file() or source_path.stat().st_size <= 0:
        raise ValueError("SQLite snapshot source does not exist or is empty")
    if destination_path.exists():
        raise FileExistsError(f"SQLite snapshot destination already exists: {destination_path}")
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination_path.with_name(f".{destination_path.name}.{os.getpid()}.tmp")
    if temporary.exists():
        raise FileExistsError(f"SQLite snapshot temporary file already exists: {temporary}")
    source_connection: sqlite3.Connection | None = None
    target_connection: sqlite3.Connection | None = None
    try:
        source_uri = f"{source_path.as_uri()}?mode=ro"
        source_connection = sqlite3.connect(source_uri, uri=True, timeout=30)
        source_connection.execute("PRAGMA query_only = ON")
        source_connection.execute("PRAGMA busy_timeout = 30000")
        target_connection = sqlite3.connect(temporary, timeout=30)
        source_connection.backup(target_connection, pages=2048, sleep=0.05)
        target_connection.commit()
        target_connection.close()
        target_connection = None
        validation = sqlite_quick_profile(temporary)
        if not validation["valid"]:
            raise sqlite3.DatabaseError("SQLite Online Backup validation failed")
        fsync_file(temporary)
        os.replace(temporary, destination_path)
    finally:
        if target_connection is not None:
            target_connection.close()
        if source_connection is not None:
            source_connection.close()
        if temporary.exists():
            temporary.unlink()
    profile = sqlite_quick_profile(destination_path)
    return {
        "format": SNAPSHOT_FORMAT,
        "source": str(source_path),
        "destination": str(destination_path),
        **profile,
    }


def sqlite_quick_profile(path: str | Path) -> dict[str, Any]:
    database = Path(path).resolve()
    result: dict[str, Any] = {
        "size_bytes": database.stat().st_size if database.is_file() else 0,
        "sha256": "",
        "quick_check": "missing",
        "schema_version": "unknown",
        "page_count": 0,
        "page_size": 0,
        "freelist_count": 0,
        "schema_digest": "",
        "table_counts": {},
        "valid": False,
    }
    if database.is_symlink() or not database.is_file() or result["size_bytes"] <= 0:
        return result
    with closing(_connect_readonly(database)) as connection:
        result["quick_check"] = str(connection.execute("PRAGMA quick_check").fetchone()[0])
        result["page_count"] = int(connection.execute("PRAGMA page_count").fetchone()[0])
        result["page_size"] = int(connection.execute("PRAGMA page_size").fetchone()[0])
        result["freelist_count"] = int(
            connection.execute("PRAGMA freelist_count").fetchone()[0]
        )
        schema_rows = connection.execute(
            "SELECT type, name, tbl_name, COALESCE(sql, '') FROM sqlite_schema "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        ).fetchall()
        result["schema_digest"] = _stable_digest([tuple(row) for row in schema_rows])
        table_names = [str(row[1]) for row in schema_rows if str(row[0]) == "table"]
        counts: dict[str, int] = {}
        for table in table_names:
            if table.replace("_", "").isalnum():
                counts[table] = int(
                    connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                )
        result["table_counts"] = counts
        for metadata in ("schema_metadata", "task_schema_meta", "schema_meta", "meta"):
            if metadata not in counts:
                continue
            try:
                row = connection.execute(
                    f'SELECT value FROM "{metadata}" WHERE key = ? LIMIT 1',
                    ("schema_version",),
                ).fetchone()
            except sqlite3.Error:
                continue
            if row is not None:
                result["schema_version"] = str(row[0])
                break
    result["sha256"] = sha256_file(database)
    result["valid"] = result["quick_check"] == "ok"
    return result


@dataclass(frozen=True)
class CompactResult:
    source: str
    compacted: str
    before: dict[str, Any]
    after: dict[str, Any]


class DevelopmentDatabaseCompactService:
    """VACUUM INTO and atomic replacement restricted to the development root."""

    def __init__(
        self,
        *,
        development_root: str | Path = DEVELOPMENT_ROOT,
    ) -> None:
        self.development_root = Path(development_root).resolve()

    def compact(self, source: str | Path, destination: str | Path) -> CompactResult:
        source_path = assert_development_path(
            source, development_root=self.development_root
        )
        destination_path = assert_development_path(
            destination, development_root=self.development_root
        )
        if source_path == destination_path:
            raise ValueError("VACUUM INTO destination must differ from source")
        if destination_path.exists():
            raise FileExistsError(f"compact destination already exists: {destination_path}")
        before = sqlite_quick_profile(source_path)
        if not before["valid"]:
            raise sqlite3.DatabaseError("source database quick_check failed")
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(source_path, timeout=60)) as connection:
            connection.execute("PRAGMA busy_timeout = 60000")
            connection.execute("VACUUM INTO ?", (str(destination_path),))
        fsync_file(destination_path)
        after = sqlite_quick_profile(destination_path)
        self._assert_equivalent(before, after)
        return CompactResult(str(source_path), str(destination_path), before, after)

    def replace(
        self,
        source: str | Path,
        compacted: str | Path,
        rollback: str | Path,
    ) -> dict[str, Any]:
        source_path = assert_development_path(source, development_root=self.development_root)
        compacted_path = assert_development_path(
            compacted, development_root=self.development_root
        )
        rollback_path = assert_development_path(
            rollback, development_root=self.development_root
        )
        if len({source_path, compacted_path, rollback_path}) != 3:
            raise ValueError("source, compacted, and rollback paths must differ")
        if rollback_path.exists():
            raise FileExistsError(f"rollback path already exists: {rollback_path}")
        before = sqlite_quick_profile(source_path)
        candidate = sqlite_quick_profile(compacted_path)
        self._assert_equivalent(before, candidate)
        os.replace(source_path, rollback_path)
        try:
            os.replace(compacted_path, source_path)
            active = sqlite_quick_profile(source_path)
            self._assert_equivalent(before, active)
        except Exception:
            if source_path.exists():
                failed = source_path.with_name(f"{source_path.name}.failed-replacement")
                if failed.exists():
                    failed.unlink()
                os.replace(source_path, failed)
            os.replace(rollback_path, source_path)
            raise
        return {
            "replaced": True,
            "active": str(source_path),
            "rollback": str(rollback_path),
            "active_profile": active,
        }

    def rollback(self, source: str | Path, rollback: str | Path) -> dict[str, Any]:
        source_path = assert_development_path(source, development_root=self.development_root)
        rollback_path = assert_development_path(
            rollback, development_root=self.development_root
        )
        current = sqlite_quick_profile(source_path)
        previous = sqlite_quick_profile(rollback_path)
        self._assert_equivalent(current, previous)
        displaced = source_path.with_name(f"{source_path.name}.pre-rollback")
        if displaced.exists():
            raise FileExistsError(f"rollback displacement already exists: {displaced}")
        os.replace(source_path, displaced)
        try:
            os.replace(rollback_path, source_path)
            restored = sqlite_quick_profile(source_path)
            self._assert_equivalent(previous, restored)
        except Exception:
            if not source_path.exists() and displaced.exists():
                os.replace(displaced, source_path)
            raise
        return {
            "rolled_back": True,
            "active": str(source_path),
            "displaced": str(displaced),
            "active_profile": restored,
        }

    @staticmethod
    def _assert_equivalent(before: dict[str, Any], after: dict[str, Any]) -> None:
        if not before.get("valid") or not after.get("valid"):
            raise sqlite3.DatabaseError("database validation failed")
        for field in ("schema_version", "schema_digest", "table_counts"):
            if before.get(field) != after.get(field):
                raise sqlite3.DatabaseError(f"database compact fingerprint mismatch: {field}")


def _connect_readonly(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=30)
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    return connection


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise SiteStorageError("SITE_METADATA_INVALID", f"{label} is missing")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SiteStorageError("SITE_METADATA_INVALID", f"{label} is invalid") from exc
    if not isinstance(value, dict):
        raise SiteStorageError("SITE_METADATA_INVALID", f"{label} must be an object")
    return value


def _optional_text(value: object) -> str | None:
    selected = str(value or "").strip()
    return selected or None


def _stable_digest(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = [
    "CompactResult",
    "DEVELOPMENT_ROOT",
    "DevelopmentDatabaseCompactService",
    "assert_development_path",
    "resolve_registered_active_site_readonly",
    "sqlite_online_backup_readonly",
    "sqlite_quick_profile",
]
