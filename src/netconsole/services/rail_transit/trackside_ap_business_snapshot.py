from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from netconsole.core.database import Database
from netconsole.services.ap_identity import ApIdentityQueryService


TRACKSIDE_AP_BUSINESS_RULE_VERSION = "2026.08.snapshot.v2"
TRACKSIDE_AP_EXPORT_SNAPSHOT_SCHEMA_VERSION = 1
TRACKSIDE_AP_SORT_CONTRACT = (
    "site",
    "device_name",
    "interface_name",
    "ap_name",
    "ap_mac",
)

_SAFE_SEGMENT = re.compile(r"^(?!\.\.?$)[^<>:\"/\\|?*\x00-\x1f\x7f]{1,100}$")
_CURRENT_SOURCE_TABLES: dict[str, tuple[str, ...]] = {
    "switch_facts_revision": (
        "device_facts",
        "device_interfaces",
        "device_optical_modules",
    ),
    "lldp_revision": ("device_lldp_neighbors",),
    "fit_ap_resource_revision": (
        "ac_fit_ap_resources",
        "ac_fit_ap_metadata",
        "ac_fit_ap_unauthenticated",
    ),
    "optical_data_revision": ("ac_fit_ap_optical",),
    "ap_history_revision": (
        "ap_lldp_history",
        "ac_fit_ap_lldp_history",
        "ac_fit_ap_unauthenticated_history",
        # Phase 2 history compatibility: only the current DB's small outbox
        # lineage participates here. Monthly shards are never scanned.
        "history_outbox",
        "history_state",
    ),
}
_SOURCE_REVISION_METADATA_KEYS = {
    "switch_facts_revision": "trackside_ap_switch_facts_revision",
    "lldp_revision": "trackside_ap_lldp_revision",
    "fit_ap_resource_revision": "trackside_ap_fit_ap_resource_revision",
    "optical_data_revision": "trackside_ap_optical_revision",
    "ap_history_revision": "trackside_ap_history_revision",
}
_BUSINESS_REVISION_EXCLUDED_KEYS = {
    "ap_history_revision",
    "export_history_revision",
}
_EXPORT_HISTORY_TABLES = (
    "ac_fit_ap_resource_history",
    "ac_fit_ap_optical_history",
    "device_optical_modules_history",
)
_SENSITIVE_COLUMN_MARKERS = (
    "password",
    "credential",
    "community",
    "secret",
    "private_key",
)


class TracksideApBusinessSnapshotError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        _json_safe(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def content_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def business_row_id(row: Mapping[str, object]) -> str:
    identity = {
        "device_uuid": str(row.get("device_uuid") or ""),
        "interface_name": str(row.get("interface_name") or ""),
        "ap_uuid": str(row.get("ap_uuid") or ""),
        "ap_mac": str(row.get("ap_mac") or ""),
        "lldp_neighbor_mac": str(row.get("lldp_observed_neighbor_mac") or ""),
    }
    return hashlib.sha256(canonical_json_bytes(identity)).hexdigest()[:24]


def read_trackside_ap_source_revisions(
    database: Database,
    *,
    scope_context: Mapping[str, object] | None = None,
    include_export_history: bool = False,
) -> dict[str, str]:
    identity_state = ApIdentityQueryService(database).revision_state()
    with database.connect_readonly() as connection:
        connection.execute("BEGIN")
        base_revision = _metadata_value(connection, "base_data_revision")
        revisions = {
            "base_data_revision": base_revision,
            "station_binding_revision": base_revision,
            "device_inventory_revision": base_revision,
            "planning_revision": base_revision,
            "business_state_revision": base_revision,
            "scope_context_revision": content_sha256(dict(scope_context or {})),
            "ap_identity_revision": identity_state.revision_token,
        }
        for source, tables in _CURRENT_SOURCE_TABLES.items():
            metadata_key = _SOURCE_REVISION_METADATA_KEYS.get(source)
            if metadata_key:
                revisions[source] = _metadata_value(connection, metadata_key)
            else:
                revisions[source] = _tables_revision(connection, tables)
        if include_export_history:
            revisions["export_history_revision"] = _metadata_value(
                connection,
                "trackside_ap_export_history_revision",
            )
        connection.commit()
    return dict(sorted(revisions.items()))


def build_business_revision(site_id: str, source_revisions: Mapping[str, str]) -> str:
    current_revisions = {
        key: value
        for key, value in source_revisions.items()
        if key not in _BUSINESS_REVISION_EXCLUDED_KEYS
    }
    return content_sha256(
        {
            "site_id": str(site_id or ""),
            "contract_version": TRACKSIDE_AP_BUSINESS_RULE_VERSION,
            "source_revisions": current_revisions,
        }
    )


def write_export_snapshot(
    staging_root: Path,
    *,
    site_id: str,
    task_id: str,
    payload: Mapping[str, object],
) -> tuple[Path, str]:
    root = trackside_ap_export_snapshot_dir(
        staging_root,
        site_id=site_id,
        task_id=task_id,
    )
    root.mkdir(parents=True, exist_ok=True)
    path = (root / "snapshot.json").resolve()
    if root not in path.parents:
        raise ValueError("轨旁 AP 快照路径无效")
    normalized_payload = _json_safe(dict(payload))
    payload_digest = content_sha256(normalized_payload)
    wrapper = {
        "schema_version": TRACKSIDE_AP_EXPORT_SNAPSHOT_SCHEMA_VERSION,
        "payload_sha256": payload_digest,
        "payload": normalized_payload,
    }
    serialized = canonical_json_bytes(wrapper)
    file_digest = hashlib.sha256(serialized).hexdigest()
    pending = path.with_suffix(".json.tmp")
    published = False
    try:
        with pending.open("wb") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(pending, path)
        published = True
        verified = read_export_snapshot(path, expected_sha256=file_digest)
        if content_sha256(verified) != payload_digest:
            raise TracksideApBusinessSnapshotError(
                "TRACKSIDE_AP_SNAPSHOT_INVALID",
                "轨旁 AP 导出快照写入校验失败，请重新导出。",
            )
    except Exception:
        pending.unlink(missing_ok=True)
        if published:
            path.unlink(missing_ok=True)
        raise
    return path, file_digest


def trackside_ap_export_snapshot_dir(
    staging_root: Path,
    *,
    site_id: str,
    task_id: str,
) -> Path:
    if not _SAFE_SEGMENT.fullmatch(str(site_id or "")):
        raise ValueError("轨旁 AP 快照局点标识无效")
    if not _SAFE_SEGMENT.fullmatch(str(task_id or "")):
        raise ValueError("轨旁 AP 快照任务标识无效")
    controlled_root = (Path(staging_root) / "trackside_ap_business").resolve()
    snapshot_dir = (controlled_root / site_id / task_id).resolve()
    if controlled_root not in snapshot_dir.parents:
        raise ValueError("轨旁 AP 快照路径无效")
    return snapshot_dir


def cleanup_export_snapshot(
    staging_root: Path,
    *,
    site_id: str,
    task_id: str,
) -> bool:
    snapshot_dir = trackside_ap_export_snapshot_dir(
        staging_root,
        site_id=site_id,
        task_id=task_id,
    )
    cleaned = False
    for name in ("snapshot.json", "snapshot.json.tmp"):
        path = (snapshot_dir / name).resolve()
        if snapshot_dir not in path.parents:
            raise ValueError("轨旁 AP 快照路径无效")
        try:
            if path.exists():
                path.unlink()
                cleaned = True
        except OSError:
            continue
    for directory in (
        snapshot_dir,
        snapshot_dir.parent,
        snapshot_dir.parent.parent,
    ):
        try:
            directory.rmdir()
        except OSError:
            break
    return cleaned


def read_export_snapshot(path: str | Path, *, expected_sha256: str) -> dict[str, object]:
    snapshot_path = Path(path)
    if not snapshot_path.is_file():
        raise TracksideApBusinessSnapshotError(
            "TRACKSIDE_AP_SNAPSHOT_NOT_FOUND",
            "轨旁 AP 导出快照不存在，请重新导出。",
        )
    serialized = snapshot_path.read_bytes()
    if hashlib.sha256(serialized).hexdigest() != str(expected_sha256 or "").casefold():
        raise TracksideApBusinessSnapshotError(
            "TRACKSIDE_AP_SNAPSHOT_INVALID",
            "轨旁 AP 导出快照校验失败，请重新导出。",
        )
    try:
        wrapper = json.loads(serialized.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TracksideApBusinessSnapshotError(
            "TRACKSIDE_AP_SNAPSHOT_INVALID",
            "轨旁 AP 导出快照格式无效，请重新导出。",
        ) from exc
    if not isinstance(wrapper, dict) or wrapper.get("schema_version") != TRACKSIDE_AP_EXPORT_SNAPSHOT_SCHEMA_VERSION:
        raise TracksideApBusinessSnapshotError(
            "TRACKSIDE_AP_SNAPSHOT_INVALID",
            "轨旁 AP 导出快照版本无效，请重新导出。",
        )
    payload = wrapper.get("payload")
    if not isinstance(payload, dict) or content_sha256(payload) != wrapper.get("payload_sha256"):
        raise TracksideApBusinessSnapshotError(
            "TRACKSIDE_AP_SNAPSHOT_INVALID",
            "轨旁 AP 导出快照内容校验失败，请重新导出。",
        )
    return dict(payload)


def _metadata_value(connection: sqlite3.Connection, key: str) -> str:
    row = connection.execute(
        "SELECT value FROM schema_metadata WHERE key = ?",
        (key,),
    ).fetchone()
    return str(row["value"] or "0") if row else "0"


def _tables_revision(connection: sqlite3.Connection, tables: Sequence[str]) -> str:
    """Return a cheap legacy fallback for databases without counters.

    Current databases use trigger-maintained counters above.  The fallback is
    deliberately an aggregate summary, never a per-row JSON/sha256 scan.
    """
    digest = hashlib.sha256()
    for table in tables:
        digest.update(table.encode("utf-8"))
        if not _table_exists(connection, table):
            digest.update(b"\0missing\0")
            continue
        columns = {
            str(row["name"])
            for row in connection.execute(f'PRAGMA table_info("{table}")').fetchall()
        }
        timestamp_columns = [
            name
            for name in ("updated_at", "collected_at", "created_at", "last_recorded_at")
            if name in columns
        ]
        aggregates = ["COUNT(*) AS row_count", "COALESCE(MAX(rowid), 0) AS max_rowid"]
        aggregates.extend(
            f'MAX("{name}") AS "max_{name}"' for name in timestamp_columns
        )
        row = connection.execute(
            f'SELECT {", ".join(aggregates)} FROM "{table}"'
        ).fetchone()
        digest.update(canonical_json_bytes(dict(row) if row else {}))
    return digest.hexdigest()


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _json_safe(value: object) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return {"__bytes_sha256__": hashlib.sha256(value).hexdigest()}
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_safe(item) for item in value]
    return str(value)


__all__ = [
    "TRACKSIDE_AP_BUSINESS_RULE_VERSION",
    "TRACKSIDE_AP_EXPORT_SNAPSHOT_SCHEMA_VERSION",
    "TRACKSIDE_AP_SORT_CONTRACT",
    "TracksideApBusinessSnapshotError",
    "build_business_revision",
    "business_row_id",
    "canonical_json_bytes",
    "cleanup_export_snapshot",
    "content_sha256",
    "read_export_snapshot",
    "read_trackside_ap_source_revisions",
    "trackside_ap_export_snapshot_dir",
    "write_export_snapshot",
]
