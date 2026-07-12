import sqlite3

from netconsole.core.database import CURRENT_SCHEMA_VERSION, Database
from scripts.maintenance.upgrade_ap_extension_schema import upgrade_database


OLD_VERSION = "2026.06.23.device_ap_rebuild_mac"


def test_upgrade_ap_extension_schema_preserves_existing_rows(tmp_path):
    database = Database(tmp_path / "devices.db")
    database.initialize()
    with database.connect() as conn:
        conn.execute(
            """
            INSERT INTO devices (device_uuid, name, device_vendor, primary_address, created_at, updated_at)
            VALUES ('device-1', 'AC-1', 'H3C', '10.0.0.1', '2026-07-01T00:00:00', '2026-07-01T00:00:00')
            """
        )
        conn.execute(
            """
            UPDATE schema_metadata
            SET value = ?
            WHERE key = 'schema_version'
            """,
            (OLD_VERSION,),
        )
        conn.execute("DROP TABLE ap_extension_points")
        conn.execute("DROP TABLE ap_extension_import_batches")
        conn.commit()

    backup_path = upgrade_database(database.path)

    assert backup_path is not None
    assert backup_path.exists()
    with sqlite3.connect(database.path) as conn:
        version = conn.execute("SELECT value FROM schema_metadata WHERE key = 'schema_version'").fetchone()[0]
        device_count = conn.execute("SELECT COUNT(*) FROM devices WHERE device_uuid = 'device-1'").fetchone()[0]
        extension_table = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'ap_extension_points'").fetchone()
        batch_table = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'ap_extension_import_batches'").fetchone()

    assert version == CURRENT_SCHEMA_VERSION
    assert device_count == 1
    assert extension_table is not None
    assert batch_table is not None
