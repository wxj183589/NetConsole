from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from netconsole.core.database import CONFIG_SNAPSHOTS_SCHEMA, Database


@dataclass(frozen=True)
class ConfigSnapshot:
    id: int | None
    device_id: int | None
    device_uuid: str
    timestamp: str
    type: str
    file_path: str
    hash: str
    raw_log_path: str | None = None
    error_message: str | None = None
    created_at: str | None = None


class ConfigSnapshotRepository:
    def __init__(self, database: Database, *, ensure_schema: bool = True) -> None:
        self.database = database
        if ensure_schema:
            self.ensure_schema()

    def ensure_schema(self) -> None:
        with self.database.connect() as conn:
            conn.executescript(CONFIG_SNAPSHOTS_SCHEMA)
            conn.commit()

    def create(self, snapshot: ConfigSnapshot) -> ConfigSnapshot:
        created_at = snapshot.created_at or datetime.now().isoformat(timespec="seconds")
        with self.database.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO config_snapshots (
                    device_id, device_uuid, timestamp, type, file_path, hash,
                    raw_log_path, error_message, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.device_id,
                    snapshot.device_uuid,
                    snapshot.timestamp,
                    snapshot.type,
                    snapshot.file_path,
                    snapshot.hash,
                    snapshot.raw_log_path,
                    snapshot.error_message,
                    created_at,
                ),
            )
            conn.commit()
            return self.get(int(cursor.lastrowid))

    def get(self, snapshot_id: int) -> ConfigSnapshot:
        with self.database.connect() as conn:
            row = conn.execute("SELECT * FROM config_snapshots WHERE id = ?", (snapshot_id,)).fetchone()
        if row is None:
            raise KeyError(f"Config snapshot not found: {snapshot_id}")
        return self._from_row(dict(row))

    def list_for_device(self, device_uuid: str, snapshot_type: str | None = None) -> list[ConfigSnapshot]:
        clauses = ["device_uuid = ?"]
        params: list[object] = [device_uuid]
        if snapshot_type:
            clauses.append("type = ?")
            params.append(snapshot_type)
        where = " AND ".join(clauses)
        with self.database.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM config_snapshots WHERE {where} ORDER BY timestamp DESC, id DESC",
                params,
            ).fetchall()
        return [self._from_row(dict(row)) for row in rows]

    def delete(self, snapshot_id: int) -> ConfigSnapshot:
        snapshot = self.get(snapshot_id)
        with self.database.connect() as conn:
            conn.execute("DELETE FROM config_snapshots WHERE id = ?", (snapshot_id,))
            conn.commit()
        return snapshot

    @staticmethod
    def _from_row(row: dict[str, object]) -> ConfigSnapshot:
        return ConfigSnapshot(
            id=int(row["id"]) if row.get("id") is not None else None,
            device_id=int(row["device_id"]) if row.get("device_id") is not None else None,
            device_uuid=str(row["device_uuid"]),
            timestamp=str(row["timestamp"]),
            type=str(row["type"]),
            file_path=str(row["file_path"]),
            hash=str(row["hash"]),
            raw_log_path=str(row["raw_log_path"]) if row.get("raw_log_path") is not None else None,
            error_message=str(row["error_message"]) if row.get("error_message") is not None else None,
            created_at=str(row["created_at"]) if row.get("created_at") is not None else None,
        )
