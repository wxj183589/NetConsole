from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

from netconsole.core.database import (  # noqa: E402
    AP_EXTENSION_IMPORT_BATCHES_SCHEMA,
    AP_EXTENSION_POINTS_SCHEMA,
    CURRENT_SCHEMA_VERSION,
    SCHEMA_METADATA_SCHEMA,
)


SUPPORTED_SOURCE_VERSIONS = {
    "2026.06.23.device_ap_rebuild_mac",
}


def upgrade_database(path: Path, *, backup: bool = True, force: bool = False) -> Path | None:
    db_path = Path(path)
    if not db_path.exists():
        raise FileNotFoundError(f"数据库不存在：{db_path}")
    backup_path = _backup_database(db_path) if backup else None
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        version = _schema_version(conn)
        if version == CURRENT_SCHEMA_VERSION:
            return backup_path
        if version not in SUPPORTED_SOURCE_VERSIONS and not force:
            supported = "、".join(sorted(SUPPORTED_SOURCE_VERSIONS))
            raise RuntimeError(f"不支持从版本 {version or '未知'} 升级。支持版本：{supported}。如确认仅需补本次新表，可加 --force。")
        _assert_required_base_tables(conn)
        conn.executescript("\n".join((SCHEMA_METADATA_SCHEMA, AP_EXTENSION_POINTS_SCHEMA, AP_EXTENSION_IMPORT_BATCHES_SCHEMA)))
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


def upgrade_all_site_databases(data_dir: Path, *, backup: bool = True, force: bool = False) -> list[tuple[Path, Path | None]]:
    sites_dir = Path(data_dir) / "sites"
    databases = sorted(sites_dir.glob("*/db/devices.db"))
    if not databases:
        raise FileNotFoundError(f"未找到局点数据库：{sites_dir}\\*/db/devices.db")
    upgraded: list[tuple[Path, Path | None]] = []
    for database_path in databases:
        backup_path = upgrade_database(database_path, backup=backup, force=force)
        upgraded.append((database_path, backup_path))
    return upgraded


def _backup_database(path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = path.with_name(f"{path.stem}.before_ap_extension_schema_{timestamp}{path.suffix}")
    shutil.copy2(path, backup_path)
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


def main() -> int:
    parser = argparse.ArgumentParser(description="离线补齐 NetConsole AP 扩展信息 schema。")
    parser.add_argument("--db", type=Path, help="单个 devices.db 路径")
    parser.add_argument("--data-dir", type=Path, default=Path(r"D:\NetConsoleData"), help="NetConsole 数据根，默认 D:\\NetConsoleData")
    parser.add_argument("--all-sites", action="store_true", help="升级数据根 sites/ 下所有局点数据库")
    parser.add_argument("--no-backup", action="store_true", help="不自动备份数据库")
    parser.add_argument("--force", action="store_true", help="跳过源版本检查，仅补本次新增表并写入当前版本")
    args = parser.parse_args()
    try:
        if args.all_sites:
            results = upgrade_all_site_databases(args.data_dir, backup=not args.no_backup, force=args.force)
        elif args.db:
            results = [(args.db, upgrade_database(args.db, backup=not args.no_backup, force=args.force))]
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
