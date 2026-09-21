from __future__ import annotations

import argparse
from contextlib import closing, nullcontext
import hashlib
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

from netconsole.core.runtime_environment import (
    data_root_for_path,
    data_environment,
    enable_production_write_flag,
    production_write_allowed,
)

ROOT = Path(__file__).resolve().parents[2]

from netconsole.core.database import (  # noqa: E402
    AP_EXTENSION_IMPORT_BATCHES_SCHEMA,
    AP_EXTENSION_POINTS_SCHEMA,
    CURRENT_SCHEMA_VERSION,
    SCHEMA_METADATA_SCHEMA,
)
from netconsole.core.paths import PathResolver  # noqa: E402
from netconsole.services.production_database_maintenance import (  # noqa: E402
    PRODUCTION_SITE_ALLOWLIST,
    ProductionMaintenanceError,
    resolve_production_database_scope,
)
from netconsole.services.database_upgrade.coordinator import (  # noqa: E402
    database_maintenance_lock,
    site_database_maintenance_key,
)


SUPPORTED_SOURCE_VERSIONS = {
    "2026.06.23.device_ap_rebuild_mac",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sqlite_snapshot_fingerprint(path: Path) -> tuple[str, int]:
    """Hash the SQLite-consistent image, including committed WAL pages."""

    with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as connection:
        snapshot = bytearray(connection.serialize())
    # SQLite backup rewrites the change-counter, schema-cookie and
    # version-valid-for header fields even when the logical page image is
    # unchanged. Normalize only those volatile header fields so source and
    # backup fingerprints compare the same consistent database snapshot.
    if len(snapshot) >= 96:
        snapshot[24:28] = b"\x00" * 4
        snapshot[40:44] = b"\x00" * 4
        snapshot[92:96] = b"\x00" * 4
    return hashlib.sha256(snapshot).hexdigest(), len(snapshot)


def _validate_operation_id(value: str) -> str:
    operation_id = str(value or "").strip()
    if not operation_id:
        return f"ap-extension-schema-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    if any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for char in operation_id):
        raise ProductionMaintenanceError("operation_id is unsafe")
    return operation_id


def _preflight(path: Path, *, force: bool) -> dict[str, object]:
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(f"数据库不存在或为符号链接：{path}")
    source_sha256, source_size = _sqlite_snapshot_fingerprint(path)
    with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        version = _schema_version(conn)
        if version == CURRENT_SCHEMA_VERSION:
            return {
                "noop": True,
                "version": version,
                "source_sha256": source_sha256,
                "source_size": source_size,
            }
        if version not in SUPPORTED_SOURCE_VERSIONS and not force:
            supported = "、".join(sorted(SUPPORTED_SOURCE_VERSIONS))
            raise RuntimeError(
                f"不支持从版本 {version or '未知'} 升级。支持版本：{supported}。"
                "如确认仅需补本次新表，可加 --force。"
            )
        _assert_required_base_tables(conn)
    return {
        "noop": False,
        "version": version,
        "source_sha256": source_sha256,
        "source_size": source_size,
    }


def _upgrade_database_locked(
    path: Path,
    *,
    backup: bool = True,
    force: bool = False,
    production: bool = False,
    site_id: str = "",
    operation_id: str = "",
) -> Path | None:
    db_path = Path(path)
    preflight = _preflight(db_path, force=force)
    if bool(preflight["noop"]):
        return None
    if production and not backup:
        raise ProductionMaintenanceError(
            "Production schema mutation requires an identity-bound backup"
        )
    if production and not production_write_allowed():
        raise ProductionMaintenanceError(
            "explicit Production authorization is required for schema mutation"
        )
    if _sqlite_snapshot_fingerprint(db_path)[0] != str(preflight["source_sha256"]):
        raise ProductionMaintenanceError("database changed during schema preflight")
    backup_path = (
        _backup_database(
            db_path,
            site_id=site_id,
            operation_id=_validate_operation_id(operation_id),
            source_sha256=str(preflight["source_sha256"]),
            source_size=int(preflight["source_size"]),
        )
        if backup
        else None
    )
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        version = _schema_version(conn)
        if version == CURRENT_SCHEMA_VERSION:
            return None
        if version != str(preflight["version"]):
            raise ProductionMaintenanceError("database changed during schema preflight")
        _assert_required_base_tables(conn)
        conn.executescript(
            "BEGIN IMMEDIATE;\n"
            + "\n".join(
                (SCHEMA_METADATA_SCHEMA, AP_EXTENSION_POINTS_SCHEMA, AP_EXTENSION_IMPORT_BATCHES_SCHEMA)
            )
        )
        now = datetime.now().isoformat(timespec="seconds")
        conn.execute(
            """
            INSERT INTO schema_metadata (key, value, created_at, updated_at)
            VALUES ('schema_version', ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (CURRENT_SCHEMA_VERSION, now, now),
        )
        conn.commit()
    return backup_path


def upgrade_database(
    path: Path,
    *,
    backup: bool = True,
    force: bool = False,
    production: bool = False,
    site_id: str = "",
    operation_id: str = "",
    maintenance_paths: PathResolver | None = None,
) -> Path | None:
    operation_id = _validate_operation_id(operation_id)
    lock = (
        database_maintenance_lock(
            maintenance_paths,
            site_database_maintenance_key(site_id),
        )
        if production and maintenance_paths is not None
        else nullcontext()
    )
    with lock:
        return _upgrade_database_locked(
            path,
            backup=backup,
            force=force,
            production=production,
            site_id=site_id,
            operation_id=operation_id,
        )


def upgrade_all_site_databases(
    data_dir: Path,
    *,
    backup: bool = True,
    force: bool = False,
    production: bool = False,
    operation_id: str = "",
) -> list[tuple[Path, Path | None]]:
    sites_dir = Path(data_dir) / "sites"
    if production:
        paths = PathResolver(app_root=ROOT, data_root=data_dir)
        databases = []
        for site_id in sorted(PRODUCTION_SITE_ALLOWLIST):
            _canonical_site_id, database, _site = resolve_production_database_scope(
                paths, site_id, "devices.db"
            )
            databases.append((site_id, database))
    else:
        databases = [
            (path.parent.parent.name, path)
            for path in sorted(sites_dir.glob("*/db/devices.db"))
        ]
    if not databases:
        raise FileNotFoundError(f"未找到局点数据库：{sites_dir}\\*/db/devices.db")
    upgraded: list[tuple[Path, Path | None]] = []
    for site_id, database_path in databases:
        backup_path = upgrade_database(
            database_path,
            backup=backup,
            force=force,
            production=production,
            site_id=site_id,
            operation_id=operation_id,
            maintenance_paths=(paths if production else None),
        )
        upgraded.append((database_path, backup_path))
    return upgraded


def _backup_database(
    path: Path,
    *,
    site_id: str = "",
    operation_id: str,
    source_sha256: str,
    source_size: int,
) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = f"_{site_id}" if site_id else ""
    backup_path = path.with_name(
        f"{path.stem}.before_ap_extension_schema{suffix}_{timestamp}_{source_sha256[:16]}{path.suffix}"
    )
    if backup_path.exists():
        raise ProductionMaintenanceError("identity-bound schema backup target already exists")
    try:
        with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as source:
            with closing(sqlite3.connect(backup_path)) as destination:
                source.backup(destination)
        backup_snapshot_sha256, backup_snapshot_size = _sqlite_snapshot_fingerprint(
            backup_path
        )
    except Exception:
        backup_path.unlink(missing_ok=True)
        raise
    if (
        backup_snapshot_sha256 != source_sha256
        or backup_snapshot_size != source_size
    ):
        backup_path.unlink(missing_ok=True)
        raise ProductionMaintenanceError("identity-bound schema backup verification failed")
    backup_sha256 = _sha256(backup_path)
    backup_size = backup_path.stat().st_size
    backup_path.with_suffix(backup_path.suffix + ".json").write_text(
        json.dumps(
            {
                "operation_id": operation_id,
                "site_id": site_id,
                "database": path.name,
                "source_path": str(path),
                "source_sha256": source_sha256,
                "source_size": source_size,
                "backup_snapshot_sha256": backup_snapshot_sha256,
                "backup_snapshot_size": backup_snapshot_size,
                "backup_sha256": backup_sha256,
                "backup_size": backup_size,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return backup_path


def _schema_version(conn: sqlite3.Connection) -> str:
    if not _table_exists(conn, "schema_metadata"):
        return ""
    row = conn.execute("SELECT value FROM schema_metadata WHERE key = 'schema_version'").fetchone()
    return str(row["value"]) if row else ""


def _assert_required_base_tables(conn: sqlite3.Connection) -> None:
    required = {"devices", "ac_fit_ap_resources", "ap_entities", "schema_metadata"}
    missing = sorted(table for table in required if not _table_exists(conn, table))
    if missing:
        raise RuntimeError(f"数据库缺少基础表，拒绝升级：{', '.join(missing)}")


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1", (table_name,)).fetchone()
    return row is not None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="离线补齐 NetConsole AP 扩展信息 schema。")
    parser.add_argument("--db", type=Path, help="单个 devices.db 路径")
    parser.add_argument("--data-dir", type=Path, help="NetConsole 数据根；未指定 --db 时默认为 D:\\NetConsoleData")
    parser.add_argument("--all-sites", action="store_true", help="升级数据根 sites/ 下所有局点数据库")
    parser.add_argument("--site", help="Production 模式下的 canonical site_id；与 --db 互斥")
    parser.add_argument("--no-backup", action="store_true", help="不自动备份数据库")
    parser.add_argument("--force", action="store_true", help="跳过源版本检查，仅补本次新增表并写入当前版本")
    parser.add_argument(
        "--allow-production-write",
        action="store_true",
        help="明确授权对 production 数据根执行 schema 补齐",
    )
    parser.add_argument("--operation-id", default="", help="绑定备份证据的操作标识")
    args = parser.parse_args(argv)
    try:
        if args.all_sites and (args.db or args.site):
            parser.error("--all-sites 不得与 --db/--site 同时使用")
        if args.db and args.site:
            parser.error("Production 模式下 --db 与 --site 互斥")
        if args.data_dir:
            data_root = Path(args.data_dir).expanduser().resolve()
        elif args.db:
            data_root = data_root_for_path(args.db)
        else:
            data_root = Path(r"D:\NetConsoleData").resolve()
        environment = data_environment(data_root)
        enable_production_write_flag(bool(args.allow_production_write))
        production = environment.is_production
        if production:
            if not args.allow_production_write:
                raise ProductionMaintenanceError(
                    "explicit Production authorization is required for schema mutation"
                )
            if args.no_backup:
                raise ProductionMaintenanceError(
                    "Production schema mutation requires an identity-bound backup"
                )
            paths = PathResolver(app_root=ROOT, data_root=data_root)
            if args.all_sites:
                results = upgrade_all_site_databases(
                    data_root,
                    backup=True,
                    force=args.force,
                    production=True,
                    operation_id=args.operation_id,
                )
            elif args.site:
                _canonical_site_id, database_path, _site = resolve_production_database_scope(
                    paths, args.site, "devices.db"
                )
                results = [
                    (
                        database_path,
                        upgrade_database(
                            database_path,
                            backup=True,
                            force=args.force,
                            production=True,
                            site_id=_canonical_site_id,
                            operation_id=args.operation_id,
                            maintenance_paths=paths,
                        ),
                    )
                ]
            elif args.db:
                raise ProductionMaintenanceError(
                    "Production --db is not an authority; specify canonical --site"
                )
            else:
                parser.error("Production 模式下请指定 --site 或 --all-sites")
        elif args.all_sites:
            results = upgrade_all_site_databases(
                data_root,
                backup=not args.no_backup,
                force=args.force,
                operation_id=args.operation_id,
            )
        elif args.db:
            database_root = data_root_for_path(args.db)
            if database_root != data_root:
                raise ProductionMaintenanceError("database is outside the selected data root")
            results = [
                (
                    args.db,
                    upgrade_database(
                        args.db,
                        backup=not args.no_backup,
                        force=args.force,
                        operation_id=args.operation_id,
                    ),
                )
            ]
        else:
            parser.error("请指定 --db 或 --all-sites")
        for database_path, backup_path in results:
            backup_text = f"，备份：{backup_path}" if backup_path else ""
            print(f"已升级：{database_path}{backup_text}")
    except Exception as exc:
        print(f"升级失败：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
