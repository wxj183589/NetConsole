"""Explicit, fail-closed production database maintenance capability.

The existing :class:`DevelopmentDatabaseCompactService` deliberately remains
development-root-only.  This module is the separate production boundary: it
does not make production paths generally writable, and every mutating method
requires an exact site/database identity, a verified rollback owner, an
immutable manifest, a second source check, writer quiescence, and explicit
authorization.
"""

from __future__ import annotations

import hashlib
import json
import gc
import os
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Mapping

from netconsole.core.paths import PathResolver
from netconsole.core.backend_instance_lock import BackendInstanceLock
from netconsole.services.database_footprint_maintenance import (
    assert_development_path,
    sqlite_content_fingerprint,
    sqlite_quick_profile,
)
from netconsole.services.database_upgrade.coordinator import (
    database_maintenance_lock,
    site_database_maintenance_key,
)
from netconsole.services.database_upgrade.journal import DatabaseUpgradeJournal
from netconsole.services.database_upgrade.sqlite_consistency import fsync_file
from netconsole.services.history_legacy_migration import (
    HistoryLegacyMigrationService,
    SUPPORTED_SPECS,
)
from netconsole.services.site_storage import SiteRegistryRepository
from scripts.maintenance.task_result_maintenance import (
    TaskResultMaintenanceService,
    _PRODUCTION_ROLLOUT_PERMIT,
)


PRODUCTION_SITE_ALLOWLIST: dict[str, str] = {
    "legacy-dfd356e96ea0": "宁波地铁12号线",
}
PRODUCTION_DATABASE_ALLOWLIST = frozenset({"devices.db", "tasks.db"})
PRODUCTION_AUTHORIZATION_TOKEN = "PRODUCTION_MAINTENANCE_AUTHORIZED"
PRODUCTION_GATE_KEYS = (
    "current_snapshot_rehearsal",
    "current_history_copy_verify",
    "current_task_rollout",
    "current_exact_plans",
    "production_rollback_owner",
    "production_backup_verified",
    "production_maintenance_gate",
    "functional_compatibility",
    "site_package",
    "restart",
    "no_reinflation",
    "full",
)
_HEX64 = frozenset("0123456789abcdef")
_SAFE_COMPONENT = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
)
_PRODUCTION_CAPABILITY_PERMIT = object()


class ProductionMaintenanceError(RuntimeError):
    """A production maintenance precondition failed; no mutation was attempted."""


def _now_utc() -> str:
    return datetime.now(UTC).isoformat()


def _safe_component(value: object, *, field: str) -> str:
    text = str(value or "")
    if not text or text in {".", ".."} or any(char not in _SAFE_COMPONENT for char in text):
        raise ProductionMaintenanceError(f"{field} is unsafe")
    return text


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> Path:
    target = path.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as output:
            json.dump(dict(value), output, ensure_ascii=False, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _is_sha256(value: object) -> bool:
    text = str(value or "").casefold()
    return len(text) == 64 and set(text) <= _HEX64


def _safe_identifier(value: object) -> str:
    text = str(value or "")
    if not text or not text.replace("_", "").isalnum():
        raise ProductionMaintenanceError("row identity contains an invalid SQL identifier")
    return text


def _validate_row_identity(database: Path, identity: Mapping[str, Any]) -> int:
    _assert_no_nonempty_wal(database)
    uri = f"{database.resolve().as_uri()}?mode=ro&immutable=1"
    with closing(sqlite3.connect(uri, uri=True, timeout=30)) as connection:
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        if isinstance(identity.get("table_counts"), Mapping):
            expected = {
                _safe_identifier(table): int(count)
                for table, count in identity["table_counts"].items()
            }
            actual = {
                table: int(
                    connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                )
                for table in expected
            }
            if actual != expected:
                raise ProductionMaintenanceError("STALE_SOURCE: table count identity mismatch")
            return sum(actual.values())

        if isinstance(identity.get("tables"), Mapping):
            total = 0
            for raw_table, raw_spec in identity["tables"].items():
                if not isinstance(raw_spec, Mapping):
                    raise ProductionMaintenanceError("row identity table spec must be an object")
                table = _safe_identifier(raw_table)
                key = _safe_identifier(raw_spec.get("key") or "id")
                row = connection.execute(
                    f'SELECT COUNT(*), MIN("{key}"), MAX("{key}") FROM "{table}"'
                ).fetchone()
                count = int(row[0] or 0)
                if count != int(raw_spec.get("count") or 0):
                    raise ProductionMaintenanceError("STALE_SOURCE: table row identity mismatch")
                if "min_key" in raw_spec and int(row[1] or 0) != int(raw_spec["min_key"]):
                    raise ProductionMaintenanceError("STALE_SOURCE: minimum key mismatch")
                if "max_key" in raw_spec and int(row[2] or 0) != int(raw_spec["max_key"]):
                    raise ProductionMaintenanceError("STALE_SOURCE: maximum key mismatch")
                total += count
            return total

        if identity.get("table"):
            table = _safe_identifier(identity["table"])
            key = _safe_identifier(identity.get("key") or "id")
            row = connection.execute(
                f'SELECT COUNT(*), MIN("{key}"), MAX("{key}") FROM "{table}"'
            ).fetchone()
            if "min_key" in identity and int(row[1] or 0) != int(identity["min_key"]):
                raise ProductionMaintenanceError("STALE_SOURCE: minimum key mismatch")
            if "max_key" in identity and int(row[2] or 0) != int(identity["max_key"]):
                raise ProductionMaintenanceError("STALE_SOURCE: maximum key mismatch")
            return int(row[0] or 0)
    raise ProductionMaintenanceError("row identity has no supported exact selector")


def _assert_no_nonempty_wal(path: Path) -> dict[str, Any]:
    wal = path.with_name(f"{path.name}-wal")
    shm = path.with_name(f"{path.name}-shm")
    try:
        wal_bytes = wal.stat().st_size if wal.is_file() else 0
    except FileNotFoundError:
        wal_bytes = 0
    if wal_bytes > 0:
        raise ProductionMaintenanceError(
            f"SQLite writer/runtime sidecars are active: {wal.name}"
        )
    return {
        "wal_exists": wal.exists(),
        "wal_bytes": wal_bytes,
        "shm_exists": shm.exists(),
        "shm_bytes": shm.stat().st_size if shm.is_file() else 0,
    }


def _sqlite_immutable_profile(path: Path) -> dict[str, Any]:
    _assert_no_nonempty_wal(path)
    return sqlite_quick_profile(path, immutable=True)


def _candidate_identity(profile: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "size_bytes": int(profile["size_bytes"]),
        "sha256": str(profile["sha256"]),
        "schema_fingerprint": str(profile["schema_digest"]),
        "table_counts": {
            str(table): int(count)
            for table, count in dict(profile["table_counts"]).items()
        },
    }


def _assert_sidecars_quiescent(path: Path) -> None:
    wal = path.with_name(f"{path.name}-wal")
    shm = path.with_name(f"{path.name}-shm")
    if wal.is_file() and wal.stat().st_size > 0:
        raise ProductionMaintenanceError(
            f"SQLite writer/runtime sidecars are active: {wal.name}"
        )
    for sidecar in (wal, shm):
        try:
            sidecar.unlink(missing_ok=True)
        except OSError as exc:
            raise ProductionMaintenanceError(
                f"SQLite writer/runtime sidecars are active: {sidecar.name}"
            ) from exc


def _atomic_replace(source: Path, destination: Path) -> None:
    gc.collect()
    for attempt in range(5):
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if os.name != "nt" or attempt == 4:
                raise
            time.sleep(0.05 * (attempt + 1))


def _sqlite_backup_readonly(source: Path, destination: Path) -> dict[str, Any]:
    if destination.exists():
        raise ProductionMaintenanceError("rollback destination already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    if temporary.exists():
        raise ProductionMaintenanceError("rollback temporary destination already exists")
    source_connection: sqlite3.Connection | None = None
    target_connection: sqlite3.Connection | None = None
    try:
        source_connection = sqlite3.connect(
            f"{source.as_uri()}?mode=ro", uri=True, timeout=30
        )
        source_connection.execute("PRAGMA query_only = ON")
        source_connection.execute("PRAGMA busy_timeout = 30000")
        target_connection = sqlite3.connect(temporary, timeout=30)
        source_connection.backup(target_connection, pages=2048, sleep=0.05)
        target_connection.commit()
        target_connection.close()
        target_connection = None
        profile = _sqlite_immutable_profile(temporary)
        if not profile["valid"]:
            raise ProductionMaintenanceError("rollback backup quick_check failed")
        fsync_file(temporary)
        os.replace(temporary, destination)
    finally:
        if target_connection is not None:
            target_connection.close()
        if source_connection is not None:
            source_connection.close()
        gc.collect()
        temporary.unlink(missing_ok=True)
    return _sqlite_immutable_profile(destination)


def _checkpoint_database(path: Path) -> dict[str, Any]:
    with closing(sqlite3.connect(path, timeout=60)) as connection:
        connection.execute("PRAGMA busy_timeout = 60000")
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    # CPython may defer finalization of SQLite statement objects on Windows;
    # collect them before removing the now-empty sidecars.
    gc.collect()
    _assert_sidecars_quiescent(path)
    return _sqlite_immutable_profile(path)


def _rowid_dependency_fingerprint(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=30)) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT name, COALESCE(sql, '') AS sql FROM sqlite_schema "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        for row in rows:
            table = str(row["name"])
            if "WITHOUT ROWID" in str(row["sql"]).upper():
                continue
            columns = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
            primary = [column for column in columns if int(column[5] or 0)]
            if len(primary) == 1 and str(primary[0][2] or "").upper() == "INTEGER":
                continue
            digest = hashlib.sha256()
            cursor = connection.execute(f'SELECT rowid, * FROM "{table}" ORDER BY rowid')
            while True:
                batch = cursor.fetchmany(500)
                if not batch:
                    break
                for item in batch:
                    digest.update(_canonical(tuple(item)).encode("utf-8"))
                    digest.update(b"\n")
            result[table] = digest.hexdigest()
    return result


@dataclass(frozen=True)
class ProductionManifest:
    """Exact identity contract generated from one isolated snapshot."""

    site_id: str
    database: str
    database_identity: str
    source_size: int
    source_sha256: str
    schema_fingerprint: str
    source_revision: str
    row_identity: Mapping[str, Any]
    expected_count: int
    candidate_identity: Mapping[str, Any]
    plan_digest: str
    generated_git_head: str
    plan_kind: str = ""
    execution_status: str = "NOT_EXECUTABLE"
    blocking_prerequisites: tuple[str, ...] = ()
    promotion_evidence: Mapping[str, Any] | None = None
    promoted_at: str = ""
    manifest_digest: str = ""
    immutable: bool = True

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ProductionManifest":
        required = {
            "site_id",
            "database",
            "database_identity",
            "source_size",
            "source_sha256",
            "schema_fingerprint",
            "source_revision",
            "row_identity",
            "expected_count",
            "candidate_identity",
            "plan_digest",
            "generated_git_head",
        }
        missing = sorted(key for key in required if key not in value)
        if missing:
            raise ProductionMaintenanceError(
                f"manifest is missing required fields: {', '.join(missing)}"
            )
        row_identity = value["row_identity"]
        if not isinstance(row_identity, Mapping):
            raise ProductionMaintenanceError("manifest row_identity must be an object")
        raw_candidate_identity = value["candidate_identity"]
        if not isinstance(raw_candidate_identity, Mapping):
            raise ProductionMaintenanceError("manifest candidate_identity must be an object")
        candidate_fields = {
            "size_bytes",
            "sha256",
            "schema_fingerprint",
            "table_counts",
        }
        missing_candidate = sorted(candidate_fields - set(raw_candidate_identity))
        if missing_candidate:
            raise ProductionMaintenanceError(
                "manifest candidate_identity is missing required fields: "
                + ", ".join(missing_candidate)
            )
        raw_table_counts = raw_candidate_identity["table_counts"]
        if not isinstance(raw_table_counts, Mapping):
            raise ProductionMaintenanceError(
                "manifest candidate_identity table_counts must be an object"
            )
        try:
            source_size = int(value["source_size"])
            expected_count = int(value["expected_count"])
            candidate_size = int(raw_candidate_identity["size_bytes"])
            candidate_table_counts = {
                _safe_identifier(table): int(count)
                for table, count in raw_table_counts.items()
            }
        except (TypeError, ValueError) as exc:
            raise ProductionMaintenanceError("manifest numeric identity is invalid") from exc
        if (
            source_size <= 0
            or expected_count < 0
            or candidate_size <= 0
            or any(count < 0 for count in candidate_table_counts.values())
        ):
            raise ProductionMaintenanceError("manifest numeric identity is out of range")
        candidate_identity = {
            "size_bytes": candidate_size,
            "sha256": str(raw_candidate_identity["sha256"]),
            "schema_fingerprint": str(raw_candidate_identity["schema_fingerprint"]),
            "table_counts": candidate_table_counts,
        }
        result = cls(
            site_id=str(value["site_id"]),
            database=str(value["database"]),
            database_identity=str(value["database_identity"]),
            source_size=source_size,
            source_sha256=str(value["source_sha256"]),
            schema_fingerprint=str(value["schema_fingerprint"]),
            source_revision=str(value["source_revision"]),
            row_identity=dict(row_identity),
            expected_count=expected_count,
            candidate_identity=candidate_identity,
            plan_digest=str(value["plan_digest"]),
            generated_git_head=str(value["generated_git_head"]),
            plan_kind=str(value.get("plan_kind") or ""),
            execution_status=str(value.get("execution_status") or "NOT_EXECUTABLE"),
            blocking_prerequisites=tuple(
                str(item) for item in value.get("blocking_prerequisites", ())
            ),
            promotion_evidence=(
                dict(value["promotion_evidence"])
                if isinstance(value.get("promotion_evidence"), Mapping)
                else None
            ),
            promoted_at=str(value.get("promoted_at") or ""),
            manifest_digest=str(value.get("manifest_digest") or ""),
            immutable=bool(value.get("immutable", True)),
        )
        if not result.immutable:
            raise ProductionMaintenanceError("destructive manifest is not immutable")
        if not result.manifest_digest:
            raise ProductionMaintenanceError("immutable manifest_digest is required")
        if not _is_sha256(result.source_sha256):
            raise ProductionMaintenanceError("manifest source_sha256 is invalid")
        if not _is_sha256(result.candidate_identity["sha256"]):
            raise ProductionMaintenanceError("manifest candidate SHA-256 is invalid")
        if not _is_sha256(result.candidate_identity["schema_fingerprint"]):
            raise ProductionMaintenanceError("manifest candidate schema fingerprint is invalid")
        if not result.database_identity or not result.schema_fingerprint:
            raise ProductionMaintenanceError("manifest database identity is incomplete")
        if not result.source_revision or not result.generated_git_head:
            raise ProductionMaintenanceError("manifest revision or Git HEAD is empty")
        if result.execution_status not in {"NOT_EXECUTABLE", "EXECUTABLE"}:
            raise ProductionMaintenanceError("manifest execution_status is invalid")
        if result.execution_status == "EXECUTABLE" and (
            result.blocking_prerequisites
            or not result.promoted_at
            or not result.promotion_evidence
        ):
            raise ProductionMaintenanceError("executable manifest promotion evidence is incomplete")
        if not _is_sha256(result.plan_digest):
            raise ProductionMaintenanceError("manifest plan_digest is invalid")
        if result.manifest_digest and not _is_sha256(result.manifest_digest):
            raise ProductionMaintenanceError("manifest_digest is invalid")
        return result

    def as_dict(self) -> dict[str, Any]:
        return {
            "manifest_version": 2,
            "immutable": True,
            "site_id": self.site_id,
            "database": self.database,
            "database_identity": self.database_identity,
            "source_size": self.source_size,
            "source_sha256": self.source_sha256,
            "schema_fingerprint": self.schema_fingerprint,
            "source_revision": self.source_revision,
            "row_identity": dict(self.row_identity),
            "expected_count": self.expected_count,
            "candidate_identity": dict(self.candidate_identity),
            "plan_kind": self.plan_kind,
            "execution_status": self.execution_status,
            "blocking_prerequisites": list(self.blocking_prerequisites),
            "promotion_evidence": dict(self.promotion_evidence or {}),
            "promoted_at": self.promoted_at,
            "plan_digest": self.plan_digest,
            "generated_git_head": self.generated_git_head,
            "manifest_digest": self.manifest_digest,
        }


@dataclass(frozen=True)
class ProductionRollbackOwner:
    backup_set_id: str
    site_id: str
    operation_id: str
    database: str
    source_identity: str
    source_sha256: str
    source_revision: str
    created_at: str
    verified_at: str
    quick_check: str
    schema_fingerprint: str
    rollback_required: bool
    observation_state: str
    superseded_by: str
    retire_state: str
    backup_sha256: str = ""
    backup_size: int = 0
    backup_relative_path: str = ""

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ProductionRollbackOwner":
        fields = (
            "backup_set_id", "site_id", "operation_id", "database",
            "source_identity", "source_sha256", "source_revision", "created_at",
            "verified_at", "quick_check", "schema_fingerprint", "rollback_required",
            "observation_state", "superseded_by", "retire_state",
        )
        missing = [field for field in fields if field not in value]
        if missing:
            raise ProductionMaintenanceError(
                f"rollback owner is missing required fields: {', '.join(missing)}"
            )
        return cls(
            backup_set_id=str(value["backup_set_id"]),
            site_id=str(value["site_id"]),
            operation_id=str(value["operation_id"]),
            database=str(value["database"]),
            source_identity=str(value["source_identity"]),
            source_sha256=str(value["source_sha256"]),
            source_revision=str(value["source_revision"]),
            created_at=str(value["created_at"]),
            verified_at=str(value["verified_at"]),
            quick_check=str(value["quick_check"]),
            schema_fingerprint=str(value["schema_fingerprint"]),
            rollback_required=bool(value["rollback_required"]),
            observation_state=str(value["observation_state"]),
            superseded_by=str(value["superseded_by"]),
            retire_state=str(value["retire_state"]),
            backup_sha256=str(value.get("backup_sha256") or ""),
            backup_size=int(value.get("backup_size") or 0),
            backup_relative_path=str(value.get("backup_relative_path") or ""),
        )

    def verified(self) -> bool:
        return bool(
            self.backup_set_id
            and self.operation_id
            and self.source_identity
            and _is_sha256(self.source_sha256)
            and self.source_revision
            and self.verified_at
            and self.quick_check == "ok"
            and _is_sha256(self.schema_fingerprint)
            and self.rollback_required
            and self.observation_state == "VERIFIED"
            and self.retire_state == "PROTECT"
            and _is_sha256(self.backup_sha256)
            and self.backup_size > 0
            and self.backup_relative_path
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "owner": "ProductionMaintenanceCapability",
            "backup_set_id": self.backup_set_id,
            "site_id": self.site_id,
            "operation_id": self.operation_id,
            "database": self.database,
            "source_identity": self.source_identity,
            "source_sha256": self.source_sha256,
            "source_revision": self.source_revision,
            "backup_sha256": self.backup_sha256,
            "backup_size": self.backup_size,
            "backup_relative_path": self.backup_relative_path,
            "created_at": self.created_at,
            "verified_at": self.verified_at,
            "quick_check": self.quick_check,
            "schema_fingerprint": self.schema_fingerprint,
            "rollback_required": self.rollback_required,
            "observation_state": self.observation_state,
            "superseded_by": self.superseded_by,
            "retire_state": self.retire_state,
        }


def build_exact_manifest(
    database: str | Path,
    *,
    candidate: str | Path,
    site_id: str,
    row_identity: Mapping[str, Any],
    expected_count: int,
    generated_git_head: str,
    plan_kind: str,
) -> dict[str, Any]:
    """Build a deterministic manifest from a rehearsal database profile."""

    source_path = Path(database).resolve()
    candidate_path = Path(candidate).resolve()
    profile = _sqlite_immutable_profile(source_path)
    if not profile["valid"]:
        raise ProductionMaintenanceError("cannot manifest an invalid SQLite database")
    candidate_profile = _sqlite_immutable_profile(candidate_path)
    if not candidate_profile["valid"]:
        raise ProductionMaintenanceError("cannot manifest an invalid replacement candidate")
    actual_count = _validate_row_identity(source_path, row_identity)
    if actual_count != int(expected_count):
        raise ProductionMaintenanceError("expected_count does not match row_identity")
    source_sha = str(profile["sha256"])
    body: dict[str, Any] = {
        "manifest_version": 2,
        "immutable": True,
        "site_id": str(site_id),
        "database": Path(database).name,
        "database_identity": _digest(
            {
                "site_id": str(site_id),
                "database": Path(database).name,
                "source_sha256": source_sha,
                "schema_fingerprint": profile["schema_digest"],
                "source_revision": source_sha,
                "row_identity": dict(row_identity),
                "expected_count": int(expected_count),
            }
        ),
        "source_size": int(profile["size_bytes"]),
        "source_sha256": source_sha,
        "schema_fingerprint": str(profile["schema_digest"]),
        "source_revision": source_sha,
        "row_identity": dict(row_identity),
        "expected_count": int(expected_count),
        "candidate_identity": _candidate_identity(candidate_profile),
        "generated_git_head": str(generated_git_head),
        "plan_kind": str(plan_kind),
        "execution_status": "NOT_EXECUTABLE",
        "blocking_prerequisites": [
            "VERIFIED_ROLLBACK_OWNER",
            "HISTORY_MIGRATION_COMPLETE",
            "TASK_ROLLOUT_COMPLETE",
            "EXACT_RETIREMENT_COMPLETE",
            "CANDIDATE_VERIFIED",
            "CURRENT_PRODUCTION_GATES",
        ],
        "promotion_evidence": {},
        "promoted_at": "",
    }
    body["plan_digest"] = _digest(body)
    body["manifest_digest"] = _digest(body)
    return body


def write_exact_manifest(path: str | Path, manifest: Mapping[str, Any]) -> Path:
    target = assert_development_path(path)
    if target.exists():
        raise FileExistsError(f"manifest already exists: {target}")
    parsed = ProductionManifest.from_mapping(manifest)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(parsed.as_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def _registered_database(
    paths: PathResolver, site_id: str, database: str
) -> tuple[Path, Any]:
    name = Path(str(database)).name
    if name != str(database) or name not in PRODUCTION_DATABASE_ALLOWLIST:
        raise ProductionMaintenanceError("database is not in the production allowlist")
    if site_id not in PRODUCTION_SITE_ALLOWLIST:
        raise ProductionMaintenanceError("site is not in the production allowlist")
    site = SiteRegistryRepository(paths).get(site_id)
    if site.display_name != PRODUCTION_SITE_ALLOWLIST[site_id]:
        raise ProductionMaintenanceError("SiteRegistry identity does not match production allowlist")
    raw_target = site.root_path / "db" / name
    target = raw_target.resolve()
    if raw_target.is_symlink() or target.parent != (site.root_path / "db").resolve():
        raise ProductionMaintenanceError("production database path is not a registered direct child")
    if not target.is_file() or target.stat().st_size <= 0:
        raise ProductionMaintenanceError("production database is missing or empty")
    return target, site


def _owner_path(site: Any, owner: ProductionRollbackOwner) -> Path:
    backup_set_id = _safe_component(owner.backup_set_id, field="backup_set_id")
    expected = (
        Path("files")
        / "backups"
        / "production-maintenance"
        / backup_set_id
        / "database.sqlite"
    )
    if Path(owner.backup_relative_path) != expected:
        raise ProductionMaintenanceError("rollback owner path is not canonical")
    raw_target = site.root_path / expected
    if raw_target.is_symlink():
        raise ProductionMaintenanceError("rollback database cannot be a symlink")
    return raw_target.resolve()


def _require_execution(
    *, mode: str, authorization: str, writer_quiescent: bool
) -> None:
    if mode != "production":
        raise ProductionMaintenanceError("production capability requires explicit mode=production")
    if authorization != PRODUCTION_AUTHORIZATION_TOKEN:
        raise ProductionMaintenanceError("explicit production authorization is required")
    if writer_quiescent is not True:
        raise ProductionMaintenanceError("writer/runtime quiescence preflight failed")


def _backend_exclusive(method: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(method)
    def guarded(self: Any, *args: Any, **kwargs: Any) -> Any:
        depth = int(getattr(self, "_backend_lock_depth", 0))
        if depth:
            return method(self, *args, **kwargs)
        with BackendInstanceLock(self.paths):
            self._backend_lock_depth = 1
            try:
                return method(self, *args, **kwargs)
            finally:
                self._backend_lock_depth = 0

    return guarded


class ProductionRollbackBootstrap:
    """Create or re-verify one registered rollback owner from a locked source."""

    def __init__(
        self,
        paths: PathResolver,
        *,
        site_id: str,
        owner_contract: ProductionRollbackOwner,
        journal_factory: Callable[[PathResolver, str], DatabaseUpgradeJournal] = DatabaseUpgradeJournal,
        _capability_permit: object | None = None,
    ) -> None:
        if _capability_permit is not _PRODUCTION_CAPABILITY_PERMIT:
            raise ProductionMaintenanceError(
                "rollback bootstrap must be created by ProductionMaintenanceCapability"
            )
        self.paths = paths
        self.site_id = str(site_id)
        self.owner_contract = owner_contract
        self._journal_factory = journal_factory

    def bootstrap(
        self,
        *,
        operation_id: str,
        mode: str,
        authorization: str,
        writer_quiescent: bool,
    ) -> ProductionRollbackOwner:
        _require_execution(
            mode=mode,
            authorization=authorization,
            writer_quiescent=writer_quiescent,
        )
        operation = _safe_component(operation_id, field="operation_id")
        contract = self.owner_contract
        if contract.site_id != self.site_id:
            raise ProductionMaintenanceError("rollback owner site identity mismatch")
        source, site = _registered_database(self.paths, self.site_id, contract.database)
        rollback = _owner_path(site, contract)
        journal = self._journal_factory(self.paths, f"{operation}-rollback-{contract.database}")
        lock_key = site_database_maintenance_key(site.site_id)
        with database_maintenance_lock(self.paths, lock_key):
            _assert_sidecars_quiescent(source)
            before = _sqlite_immutable_profile(source)
            if not before["valid"]:
                raise ProductionMaintenanceError("source quick_check failed")
            content_before = sqlite_content_fingerprint(source, immutable=True)
            pending_contract = contract.observation_state == "PENDING_PRODUCTION_BACKUP"
            if not pending_contract and (
                contract.source_sha256 != str(before["sha256"])
                or contract.schema_fingerprint != str(before["schema_digest"])
            ):
                raise ProductionMaintenanceError("STALE_SOURCE: rollback contract source mismatch")
            source_identity = _digest(
                {
                    "site_id": self.site_id,
                    "database": contract.database,
                    "sha256": before["sha256"],
                    "schema_fingerprint": before["schema_digest"],
                    "table_counts": before["table_counts"],
                    "content_fingerprint": content_before,
                }
            )
            journal.update(
                "rollback_bootstrap_started",
                recovery_strategy="component_resume",
                source_path=str(source),
                rollback_path=str(rollback),
                source_sha256=str(before["sha256"]),
                source_identity=source_identity,
                maintenance_lock=lock_key,
                switched=False,
            )
            reused = rollback.is_file()
            backup = (
                _sqlite_immutable_profile(rollback)
                if reused
                else _sqlite_backup_readonly(source, rollback)
            )
            if not backup["valid"]:
                raise ProductionMaintenanceError("rollback backup quick_check failed")
            content_backup = sqlite_content_fingerprint(rollback, immutable=True)
            after = _sqlite_immutable_profile(source)
            if (
                str(after["sha256"]) != str(before["sha256"])
                or int(after["size_bytes"]) != int(before["size_bytes"])
                or after["table_counts"] != before["table_counts"]
            ):
                raise ProductionMaintenanceError("source changed during rollback bootstrap")
            if (
                backup["schema_digest"] != before["schema_digest"]
                or backup["table_counts"] != before["table_counts"]
                or content_backup != content_before
                or int(backup["size_bytes"]) <= 0
                or not _is_sha256(backup["sha256"])
            ):
                raise ProductionMaintenanceError("rollback backup business identity mismatch")
            now = _now_utc()
            owner = ProductionRollbackOwner(
                backup_set_id=contract.backup_set_id,
                site_id=self.site_id,
                operation_id=operation,
                database=contract.database,
                source_identity=source_identity,
                source_sha256=str(before["sha256"]),
                source_revision=str(before["sha256"]),
                created_at=contract.created_at or now,
                verified_at=now,
                quick_check="ok",
                schema_fingerprint=str(before["schema_digest"]),
                rollback_required=True,
                observation_state="VERIFIED",
                superseded_by="",
                retire_state="PROTECT",
                backup_sha256=str(backup["sha256"]),
                backup_size=int(backup["size_bytes"]),
                backup_relative_path=contract.backup_relative_path,
            )
            evidence_path = rollback.with_name(
                f"rollback-owner-{_safe_component(operation, field='operation_id')}.json"
            )
            evidence = owner.as_dict() | {
                "evidence_format": "netconsole-production-rollback-owner-v1",
                "reused": reused,
                "content_fingerprint": content_backup,
            }
            if evidence_path.exists():
                existing = json.loads(evidence_path.read_text(encoding="utf-8"))
                if not isinstance(existing, Mapping) or any(
                    existing.get(key) != evidence.get(key)
                    for key in (
                        "site_id",
                        "database",
                        "source_sha256",
                        "backup_sha256",
                        "backup_size",
                    )
                ):
                    raise ProductionMaintenanceError("existing rollback owner evidence is stale")
                existing_owner = ProductionRollbackOwner.from_mapping(existing)
                if not existing_owner.verified() or existing_owner.operation_id != operation:
                    raise ProductionMaintenanceError("existing rollback owner evidence is invalid")
                owner = existing_owner
            else:
                _write_json_atomic(evidence_path, evidence)
            journal.update(
                "rollback_bootstrap_completed",
                owner=owner.as_dict(),
                evidence_path=str(evidence_path),
                reused=reused,
            )
            return owner


class ProductionCompactCandidateBuilder:
    """Build a verified VACUUM INTO candidate without replacing the active DB."""

    def __init__(
        self,
        paths: PathResolver,
        *,
        site_id: str,
        authoritative_git_head: str,
        journal_factory: Callable[[PathResolver, str], DatabaseUpgradeJournal] = DatabaseUpgradeJournal,
        _capability_permit: object | None = None,
    ) -> None:
        if _capability_permit is not _PRODUCTION_CAPABILITY_PERMIT:
            raise ProductionMaintenanceError(
                "compact candidate builder must be created by ProductionMaintenanceCapability"
            )
        self.paths = paths
        self.site_id = str(site_id)
        self.authoritative_git_head = str(authoritative_git_head)
        self._journal_factory = journal_factory

    def build(
        self,
        database: str,
        *,
        operation_id: str,
        rollback_owner: ProductionRollbackOwner,
        expected_source_sha256: str,
        generated_git_head: str,
        mode: str,
        authorization: str,
        writer_quiescent: bool,
    ) -> dict[str, Any]:
        _require_execution(
            mode=mode,
            authorization=authorization,
            writer_quiescent=writer_quiescent,
        )
        if generated_git_head != self.authoritative_git_head:
            raise ProductionMaintenanceError("STALE_PLAN: generated Git HEAD mismatch")
        if not rollback_owner.verified() or rollback_owner.database != database:
            raise ProductionMaintenanceError("VERIFIED rollback owner is required")
        operation = _safe_component(operation_id, field="operation_id")
        source, site = _registered_database(self.paths, self.site_id, database)
        candidate = (
            self.paths.staging_dir
            / "production-maintenance"
            / operation
            / f"{database}.candidate"
        ).resolve()
        staging_root = (self.paths.staging_dir / "production-maintenance").resolve()
        if candidate.is_symlink() or not candidate.is_relative_to(staging_root):
            raise ProductionMaintenanceError("candidate path is not registered staging")
        lock_key = site_database_maintenance_key(site.site_id)
        journal = self._journal_factory(self.paths, f"{operation}-compact-{database}")
        with database_maintenance_lock(self.paths, lock_key):
            _assert_sidecars_quiescent(source)
            before = _sqlite_immutable_profile(source)
            if str(before.get("sha256")) != str(expected_source_sha256):
                raise ProductionMaintenanceError("STALE_SOURCE: compact source revision mismatch")
            before_content = sqlite_content_fingerprint(source, immutable=True)
            before_rowids = _rowid_dependency_fingerprint(source)
            if candidate.exists():
                existing = _sqlite_immutable_profile(candidate)
                existing_content = sqlite_content_fingerprint(candidate, immutable=True)
                existing_rowids = _rowid_dependency_fingerprint(candidate)
                if (
                    not existing["valid"]
                    or existing["schema_version"] != before["schema_version"]
                    or existing["schema_digest"] != before["schema_digest"]
                    or existing["table_counts"] != before["table_counts"]
                    or existing_content != before_content
                    or existing_rowids != before_rowids
                ):
                    raise ProductionMaintenanceError("existing compact candidate is stale")
                result = {
                    "status": "VERIFIED",
                    "database": database,
                    "candidate": str(candidate),
                    "source_sha256": str(before["sha256"]),
                    "candidate_identity": _candidate_identity(existing),
                    "content_fingerprint": existing_content,
                    "rowid_dependency": existing_rowids,
                    "wal_dependency": "NONE",
                    "resumed": True,
                }
                journal.update("compact_candidate_completed", **result)
                return result
            candidate.parent.mkdir(parents=True, exist_ok=True)
            journal.update(
                "compact_candidate_started",
                recovery_strategy="component_resume",
                active_path=str(source),
                shadow_path=str(candidate),
                database_kind=database,
                maintenance_lock=lock_key,
                switched=False,
            )
            try:
                with closing(sqlite3.connect(source, timeout=60)) as connection:
                    connection.execute("PRAGMA busy_timeout = 60000")
                    connection.execute("VACUUM INTO ?", (str(candidate),))
                fsync_file(candidate)
                _assert_sidecars_quiescent(candidate)
                after = _sqlite_immutable_profile(candidate)
                after_content = sqlite_content_fingerprint(candidate, immutable=True)
                after_rowids = _rowid_dependency_fingerprint(candidate)
                for field in ("schema_version", "schema_digest", "table_counts"):
                    if before.get(field) != after.get(field):
                        raise ProductionMaintenanceError(
                            f"compact candidate fingerprint mismatch: {field}"
                        )
                if before_content != after_content:
                    raise ProductionMaintenanceError(
                        "compact candidate content fingerprint mismatch"
                    )
                if before_rowids != after_rowids:
                    raise ProductionMaintenanceError(
                        "compact candidate rowid dependency mismatch"
                    )
                result = {
                    "status": "VERIFIED",
                    "database": database,
                    "candidate": str(candidate),
                    "source_sha256": str(before["sha256"]),
                    "candidate_identity": _candidate_identity(after),
                    "content_fingerprint": after_content,
                    "rowid_dependency": after_rowids,
                    "wal_dependency": "NONE",
                }
                journal.update("compact_candidate_completed", **result)
                return result
            except Exception as exc:
                journal.update(
                    "compact_candidate_failed",
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                raise


class ProductionHistoryRetirementExecutor:
    """Apply only exact History delete-plan keys with resumable batch evidence."""

    def __init__(
        self,
        paths: PathResolver,
        *,
        site_id: str,
        migration: HistoryLegacyMigrationService,
        authoritative_git_head: str,
        journal_factory: Callable[[PathResolver, str], DatabaseUpgradeJournal] = DatabaseUpgradeJournal,
        _capability_permit: object | None = None,
    ) -> None:
        if _capability_permit is not _PRODUCTION_CAPABILITY_PERMIT:
            raise ProductionMaintenanceError(
                "History retirement must be created by ProductionMaintenanceCapability"
            )
        self.paths = paths
        self.site_id = str(site_id)
        self.migration = migration
        self.authoritative_git_head = str(authoritative_git_head)
        self._journal_factory = journal_factory

    @staticmethod
    def _planned_keys(table: Mapping[str, Any]) -> list[int]:
        keys: list[int] = []
        for range_item in table.get("ranges", []):
            if not isinstance(range_item, Mapping):
                raise ProductionMaintenanceError("retirement range is invalid")
            for key_range in range_item.get("source_key_ranges", []):
                start = int(key_range.get("start") or 0)
                end = int(key_range.get("end") or 0)
                if start <= 0 or end < start:
                    raise ProductionMaintenanceError("retirement source range is invalid")
                keys.extend(range(start, end + 1))
        if len(keys) != len(set(keys)):
            raise ProductionMaintenanceError("retirement source ranges overlap")
        return sorted(keys)

    @staticmethod
    def _resume_absent_count(
        planned: list[int],
        existing_keys: list[int],
        *,
        rows_before: int,
        before_count: int,
    ) -> int:
        absent = len(planned) - len(existing_keys)
        total_delta = int(rows_before) - int(before_count)
        if absent != total_delta or existing_keys != planned[absent:]:
            raise ProductionMaintenanceError(
                "retirement resume proof detected out-of-plan deletion"
            )
        return absent

    def execute(
        self,
        plan: Mapping[str, Any],
        *,
        operation_id: str,
        rollback_owner: ProductionRollbackOwner,
        expected_source_sha256: str,
        expected_schema_fingerprint: str,
        generated_git_head: str,
        mode: str,
        authorization: str,
        writer_quiescent: bool,
        batch_rows: int = 500,
    ) -> dict[str, Any]:
        _require_execution(
            mode=mode,
            authorization=authorization,
            writer_quiescent=writer_quiescent,
        )
        if generated_git_head != self.authoritative_git_head:
            raise ProductionMaintenanceError("STALE_PLAN: generated Git HEAD mismatch")
        if (
            not rollback_owner.verified()
            or rollback_owner.database != "devices.db"
            or rollback_owner.source_sha256 != expected_source_sha256
            or rollback_owner.schema_fingerprint != expected_schema_fingerprint
        ):
            raise ProductionMaintenanceError("VERIFIED devices.db rollback owner is required")
        if self.migration.source_database != _registered_database(
            self.paths, self.site_id, "devices.db"
        )[0]:
            raise ProductionMaintenanceError("history source is not the registered devices.db")
        safe_batch = int(batch_rows)
        if safe_batch not in {250, 500, 1000}:
            raise ProductionMaintenanceError("retirement batch_rows must be 250, 500, or 1000")
        operation = _safe_component(operation_id, field="operation_id")
        digest = str(plan.get("plan_digest") or "")
        if not _is_sha256(digest):
            raise ProductionMaintenanceError("retirement plan digest is invalid")
        tables = list(plan.get("tables") or [])
        if not tables or any(not isinstance(item, Mapping) for item in tables):
            raise ProductionMaintenanceError("retirement plan has no exact tables")
        if any(not bool(item.get("eligibility")) for item in tables):
            raise ProductionMaintenanceError("retirement plan contains an ineligible table")
        journal = self._journal_factory(self.paths, f"{operation}-history-retirement")
        existing = journal.data
        if existing.get("stage") == "history_retirement_completed":
            if existing.get("plan_digest") != digest:
                raise ProductionMaintenanceError("retirement journal plan digest mismatch")
            return dict(existing.get("result") or {})
        if existing.get("stage") == "created":
            self.migration.validate_delete_plan(dict(plan))
        elif existing.get("plan_digest") != digest:
            raise ProductionMaintenanceError("retirement journal plan digest mismatch")
        source = self.migration.source_database
        profile = _sqlite_immutable_profile(source)
        progress = dict(existing.get("table_progress") or {})
        if not progress:
            if str(profile.get("sha256")) != str(expected_source_sha256):
                raise ProductionMaintenanceError("STALE_SOURCE: retirement source SHA mismatch")
            if str(profile.get("schema_digest")) != str(expected_schema_fingerprint):
                raise ProductionMaintenanceError("STALE_SOURCE: retirement schema mismatch")
            progress = {
                str(item["source_table"]): {
                    "rows_before": int(profile["table_counts"].get(str(item["source_table"]), 0)),
                    "deleted_rows": 0,
                    "batches": 0,
                }
                for item in tables
            }
            journal.update(
                "history_retirement_started",
                recovery_strategy="component_resume",
                active_path=str(source),
                database_kind="devices.db",
                maintenance_lock=site_database_maintenance_key(self.site_id),
                plan_digest=digest,
                source_sha256=expected_source_sha256,
                schema_fingerprint=expected_schema_fingerprint,
                table_progress=progress,
                switched=False,
            )
        lock_key = site_database_maintenance_key(self.site_id)
        with database_maintenance_lock(self.paths, lock_key):
            try:
                for item in tables:
                    table = str(item["source_table"])
                    if table not in SUPPORTED_SPECS or not table.replace("_", "").isalnum():
                        raise ProductionMaintenanceError(f"invalid retirement table: {table}")
                    planned = self._planned_keys(item)
                    if len(planned) != int(item.get("row_count") or 0):
                        raise ProductionMaintenanceError("retirement exact key count mismatch")
                    state = dict(progress[table])
                    # Prove the already-missing keys once per table, then delete
                    # the remaining planned prefix in bounded batches. Repeating
                    # the full planned-key scan for every batch is O(n^2).
                    with closing(sqlite3.connect(source, timeout=60)) as connection:
                        connection.execute("PRAGMA busy_timeout = 60000")
                        connection.execute("PRAGMA foreign_keys = ON")
                        connection.execute("BEGIN IMMEDIATE")
                        before_count = int(
                            connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                        )
                        existing_keys: list[int] = []
                        for offset in range(0, len(planned), safe_batch):
                            chunk = planned[offset : offset + safe_batch]
                            rows = connection.execute(
                                f'SELECT id FROM "{table}" WHERE id IN '
                                f'({",".join("?" for _ in chunk)}) ORDER BY id',
                                chunk,
                            ).fetchall()
                            existing_keys.extend(int(row[0]) for row in rows)
                        try:
                            absent = self._resume_absent_count(
                                planned,
                                existing_keys,
                                rows_before=int(state["rows_before"]),
                                before_count=before_count,
                            )
                        except ProductionMaintenanceError:
                            connection.rollback()
                            raise
                        connection.rollback()
                    state["deleted_rows"] = absent
                    while int(state["deleted_rows"]) < len(planned):
                        start = int(state["deleted_rows"])
                        batch = planned[start : start + safe_batch]
                        with closing(sqlite3.connect(source, timeout=60)) as connection:
                            connection.execute("PRAGMA busy_timeout = 60000")
                            connection.execute("PRAGMA foreign_keys = ON")
                            connection.execute("BEGIN IMMEDIATE")
                            rows = connection.execute(
                                f'SELECT id FROM "{table}" WHERE id IN '
                                f'({",".join("?" for _ in batch)}) ORDER BY id',
                                batch,
                            ).fetchall()
                            if [int(row[0]) for row in rows] != batch:
                                connection.rollback()
                                raise ProductionMaintenanceError(
                                    "retirement batch identity mismatch"
                                )
                            cursor = connection.execute(
                                f'DELETE FROM "{table}" WHERE id IN '
                                f'({",".join("?" for _ in batch)})',
                                batch,
                            )
                            if int(cursor.rowcount or 0) != len(batch):
                                connection.rollback()
                                raise ProductionMaintenanceError(
                                    "retirement batch affected-row mismatch"
                                )
                            connection.commit()
                        state["deleted_rows"] = start + len(batch)
                        state["batches"] = int(state.get("batches") or 0) + 1
                        progress[table] = state
                        journal.update(
                            "history_retirement_batch",
                            plan_digest=digest,
                            table_progress=progress,
                            last_table=table,
                            last_batch_rows=len(batch),
                        )
                    progress[table] = state
                    if int(state["deleted_rows"]) != len(planned):
                        raise ProductionMaintenanceError("retirement table count verification failed")
                finalized: list[dict[str, Any]] = []
                migration_id = str(plan.get("migration_id") or "")
                for item in tables:
                    table = str(item["source_table"])
                    checkpoint = self.migration.journal.table_checkpoint(migration_id, table)
                    if checkpoint is None:
                        raise ProductionMaintenanceError("history retirement checkpoint is missing")
                    if checkpoint.authority_state != "SOURCE_DELETED":
                        checkpoint = self.migration.journal.transition_authority(
                            migration_id,
                            table,
                            to_state="SOURCE_DELETED",
                            expected_revision=int(item["cutover_revision"]),
                            reason=f"production exact plan {digest}",
                            now=self.migration._now(),
                        )
                    finalized.append(
                        {
                            "source_table": table,
                            **progress[table],
                            "rows_after": int(progress[table]["rows_before"])
                            - int(progress[table]["deleted_rows"]),
                            "authority_state": checkpoint.authority_state,
                            "cutover_revision": checkpoint.cutover_revision,
                        }
                    )
                result = {
                    "status": "COMPLETED",
                    "operation_id": operation,
                    "plan_digest": digest,
                    "deleted_rows": sum(int(item["deleted_rows"]) for item in progress.values()),
                    "tables": finalized,
                }
                journal.update(
                    "history_retirement_completed",
                    plan_digest=digest,
                    table_progress=progress,
                    result=result,
                )
                return result
            except Exception as exc:
                journal.update(
                    "history_retirement_failed",
                    plan_digest=digest,
                    table_progress=progress,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                raise


class ProductionTaskRolloutExecutor:
    """Run deterministic task-result backfill and authority transition."""

    def __init__(
        self,
        paths: PathResolver,
        *,
        site_id: str,
        authoritative_git_head: str,
        service_factory: Callable[..., Any] | None = None,
        journal_factory: Callable[[PathResolver, str], DatabaseUpgradeJournal] = DatabaseUpgradeJournal,
        _capability_permit: object | None = None,
    ) -> None:
        if _capability_permit is not _PRODUCTION_CAPABILITY_PERMIT:
            raise ProductionMaintenanceError(
                "Task rollout must be created by ProductionMaintenanceCapability"
            )
        self.paths = paths
        self.site_id = str(site_id)
        self.authoritative_git_head = str(authoritative_git_head)
        self._service_factory = service_factory or TaskResultMaintenanceService
        self._journal_factory = journal_factory

    def execute(
        self,
        *,
        operation_id: str,
        rollback_owner: ProductionRollbackOwner,
        expected_source_sha256: str,
        generated_git_head: str,
        mode: str,
        authorization: str,
        writer_quiescent: bool,
        batch_rows: int = 250,
    ) -> dict[str, Any]:
        _require_execution(
            mode=mode,
            authorization=authorization,
            writer_quiescent=writer_quiescent,
        )
        if generated_git_head != self.authoritative_git_head:
            raise ProductionMaintenanceError("STALE_PLAN: generated Git HEAD mismatch")
        if (
            not rollback_owner.verified()
            or rollback_owner.database != "tasks.db"
            or rollback_owner.source_sha256 != expected_source_sha256
        ):
            raise ProductionMaintenanceError("VERIFIED tasks.db rollback owner is required")
        database, _ = _registered_database(self.paths, self.site_id, "tasks.db")
        operation = _safe_component(operation_id, field="operation_id")
        journal = self._journal_factory(self.paths, f"{operation}-task-rollout")
        existing = journal.data
        if existing.get("stage") == "task_rollout_completed":
            if existing.get("initial_source_sha256") != expected_source_sha256:
                raise ProductionMaintenanceError("task rollout journal source mismatch")
            return dict(existing.get("result") or {})
        profile = _sqlite_immutable_profile(database)
        if existing.get("stage") == "created" and str(profile.get("sha256")) != str(expected_source_sha256):
            raise ProductionMaintenanceError("STALE_SOURCE: task rollout source SHA mismatch")
        service = self._service_factory(
            self.paths,
            site_id=self.site_id,
            tasks_database=database,
            _production_permit=_PRODUCTION_ROLLOUT_PERMIT,
        )
        analysis = service.analyze_backfill()
        conflict_count = int(analysis["classifications"].get("CONFLICT", 0))
        protected_invalid_count = int(analysis["classifications"].get("INVALID", 0))
        if conflict_count:
            journal.update(
                "task_rollout_blocked",
                recovery_strategy="component_resume",
                initial_source_sha256=expected_source_sha256,
                analysis=analysis,
                error="CONFLICT",
            )
            raise ProductionMaintenanceError("task rollout contains CONFLICT rows")
        journal.update(
            "task_rollout_started",
            recovery_strategy="component_resume",
            active_path=str(database),
            database_kind="tasks.db",
            maintenance_lock=site_database_maintenance_key(self.site_id),
            initial_source_sha256=expected_source_sha256,
            analysis=analysis,
            protected_invalid_count=protected_invalid_count,
            switched=False,
        )
        try:
            rollout = service.repository.task_result_rollout_status()
            if rollout.state.value == "LEGACY_DUAL_FULL":
                from netconsole.models.task_result_rollout import TaskResultStorageState

                updated = service.repository.compare_and_set_task_result_rollout(
                    expected_state=rollout.state,
                    expected_revision=rollout.revision,
                    target_state=TaskResultStorageState.TASK_RESULTS_DUAL_WRITE,
                    updated_by="ProductionTaskRolloutExecutor",
                    reason=f"production rollout {operation}",
                    allow_advanced=True,
                )
                if updated is None:
                    raise ProductionMaintenanceError("task rollout authority transition conflict")
                rollout = updated
            if rollout.state.value not in {
                "TASK_RESULTS_DUAL_WRITE",
                "TASK_RESULTS_VERIFIED",
                "RESULT_REF_AUTHORITY",
            }:
                raise ProductionMaintenanceError("task rollout state is not eligible")
            current = _checkpoint_database(database)
            backfill = service.backfill_production(
                authorization=authorization,
                expected_source_revision=str(current["sha256"]),
                batch_rows=batch_rows,
            )
            journal.update("task_backfill_completed", backfill=backfill)
            verification = service.analyze_backfill()
            if int(verification["classifications"].get("CONFLICT", 0)):
                raise ProductionMaintenanceError("task backfill verification failed: CONFLICT")
            if int(verification["classifications"].get("INVALID", 0)) != protected_invalid_count:
                raise ProductionMaintenanceError("task backfill verification changed protected INVALID rows")
            rerun_source = _checkpoint_database(database)
            rerun = service.backfill_production(
                authorization=authorization,
                expected_source_revision=str(rerun_source["sha256"]),
                batch_rows=batch_rows,
            )
            if not rerun.get("idempotent"):
                raise ProductionMaintenanceError("task backfill idempotency verification failed")
            rollout = service.repository.task_result_rollout_status()
            authority_source = _checkpoint_database(database)
            authority = service.enable_ref_authority_production(
                authorization=authorization,
                expected_source_revision=str(authority_source["sha256"]),
                expected_revision=rollout.revision,
                reason=f"verified production rollout {operation}",
                updated_by="ProductionTaskRolloutExecutor",
                batch_rows=max(250, int(batch_rows)),
            )
            if authority.get("state") != "RESULT_REF_AUTHORITY":
                raise ProductionMaintenanceError("task result authority did not reach RESULT_REF_AUTHORITY")
            result = {
                "status": "COMPLETED",
                "operation_id": operation,
                "analysis": analysis,
                "backfill": backfill,
                "idempotency_rerun": rerun,
                "verification": verification,
                "authority": authority,
                "protected_invalid_count": protected_invalid_count,
                "protected_active_states": ["PENDING", "RUNNING"],
            }
            journal.update(
                "task_rollout_completed",
                initial_source_sha256=expected_source_sha256,
                result=result,
            )
            return result
        except Exception as exc:
            journal.update(
                "task_rollout_failed",
                initial_source_sha256=expected_source_sha256,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            raise


class ProductionMaintenanceCapability:
    """The only production-capable database replacement boundary."""

    def __init__(
        self,
        paths: PathResolver,
        *,
        site_id: str,
        authoritative_git_head: str,
        rollback_owners: Mapping[tuple[str, str], ProductionRollbackOwner] | None = None,
        journal_factory: Callable[[PathResolver, str], DatabaseUpgradeJournal] = DatabaseUpgradeJournal,
    ) -> None:
        self.paths = paths
        self.site_id = str(site_id).strip()
        self.authoritative_git_head = str(authoritative_git_head).strip()
        self._rollback_owners = dict(rollback_owners or {})
        self._journal_factory = journal_factory
        self._backend_lock_depth = 0
        if self.site_id not in PRODUCTION_SITE_ALLOWLIST:
            raise ProductionMaintenanceError("site is not in the production allowlist")
        if not self.authoritative_git_head:
            raise ProductionMaintenanceError("authoritative Git HEAD is required")

    @staticmethod
    def load_rollback_owners(path: str | Path) -> dict[tuple[str, str], ProductionRollbackOwner]:
        source = Path(path).resolve()
        try:
            value = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProductionMaintenanceError(f"cannot read storage registry: {source}") from exc
        raw = value.get("production_rollback_owners") if isinstance(value, dict) else None
        if not isinstance(raw, list):
            raise ProductionMaintenanceError("storage registry has no production rollback owners")
        owners: dict[tuple[str, str], ProductionRollbackOwner] = {}
        for item in raw:
            if not isinstance(item, Mapping):
                raise ProductionMaintenanceError("rollback owner entry must be an object")
            owner = ProductionRollbackOwner.from_mapping(item)
            key = (owner.site_id, owner.database)
            if key in owners:
                raise ProductionMaintenanceError("duplicate production rollback owner")
            owners[key] = owner
        return owners

    def _site_and_database(self, database: str) -> tuple[Path, Any]:
        return _registered_database(self.paths, self.site_id, database)

    def _owner(self, database: str) -> ProductionRollbackOwner:
        owner = self._rollback_owners.get((self.site_id, database))
        if owner is None:
            raise ProductionMaintenanceError("production rollback owner is not registered")
        if owner.site_id != self.site_id or owner.database != database:
            raise ProductionMaintenanceError("production rollback owner identity mismatch")
        if not owner.verified():
            raise ProductionMaintenanceError("production rollback owner is not VERIFIED")
        return owner

    def _rollback_path(self, site: Any, owner: ProductionRollbackOwner) -> Path:
        return _owner_path(site, owner)

    def _read_manifest(self, path: str | Path) -> ProductionManifest:
        source = Path(path).resolve()
        raw = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(raw, Mapping):
            raise ProductionMaintenanceError("manifest must contain a JSON object")
        manifest = ProductionManifest.from_mapping(raw)
        if manifest.site_id != self.site_id:
            raise ProductionMaintenanceError("manifest site_id mismatch")
        if manifest.generated_git_head != self.authoritative_git_head:
            raise ProductionMaintenanceError("STALE_PLAN: generated Git HEAD mismatch")
        if manifest.manifest_digest:
            body = dict(raw)
            actual = str(body.pop("manifest_digest") or "")
            if actual != _digest(body):
                raise ProductionMaintenanceError("STALE_PLAN: manifest digest mismatch")
            plan = str(body.pop("plan_digest") or "")
            if plan != _digest(body):
                raise ProductionMaintenanceError("STALE_PLAN: plan digest mismatch")
        return manifest

    def _validate_rollback_owner(
        self,
        manifest: ProductionManifest,
        site: Any,
        owner: ProductionRollbackOwner,
    ) -> tuple[Path, dict[str, Any]]:
        rollback_path = self._rollback_path(site, owner)
        profile = _sqlite_immutable_profile(rollback_path)
        promoted_owner_digest = str(
            (manifest.promotion_evidence or {}).get("rollback_owner_digest") or ""
        )
        owner_bound_to_current_source = (
            owner.source_identity == manifest.database_identity
            and owner.source_sha256 == manifest.source_sha256
            and owner.source_revision == manifest.source_revision
        )
        if (
            not profile["valid"]
            or owner.backup_sha256 != str(profile["sha256"])
            or owner.backup_size != int(profile["size_bytes"])
            or owner.schema_fingerprint != str(profile["schema_digest"])
        ):
            raise ProductionMaintenanceError(
                "VERIFIED rollback owner does not match current source"
            )
        if owner_bound_to_current_source:
            if _validate_row_identity(rollback_path, manifest.row_identity) != manifest.expected_count:
                raise ProductionMaintenanceError(
                    "VERIFIED rollback owner row identity does not match current source"
                )
        elif (
            manifest.execution_status != "EXECUTABLE"
            or promoted_owner_digest != _digest(owner.as_dict())
        ):
            raise ProductionMaintenanceError(
                "VERIFIED rollback owner is not bound by executable promotion evidence"
            )
        return rollback_path, profile

    def _validate_source(self, manifest: ProductionManifest, database: Path) -> dict[str, Any]:
        profile = _sqlite_immutable_profile(database)
        if not profile["valid"]:
            raise ProductionMaintenanceError("source quick_check failed")
        if int(profile["size_bytes"]) != manifest.source_size:
            raise ProductionMaintenanceError("STALE_SOURCE: source size mismatch")
        if str(profile["sha256"]) != manifest.source_sha256:
            raise ProductionMaintenanceError("STALE_SOURCE: source SHA-256 mismatch")
        if str(profile["schema_digest"]) != manifest.schema_fingerprint:
            raise ProductionMaintenanceError("STALE_SOURCE: schema fingerprint mismatch")
        if manifest.source_revision != str(profile["sha256"]):
            raise ProductionMaintenanceError("STALE_SOURCE: source revision mismatch")
        if _validate_row_identity(database, manifest.row_identity) != manifest.expected_count:
            raise ProductionMaintenanceError("STALE_SOURCE: expected row count mismatch")
        return profile

    @staticmethod
    def _validate_candidate(
        manifest: ProductionManifest, candidate: Path
    ) -> dict[str, Any]:
        profile = _sqlite_immutable_profile(candidate)
        if not profile["valid"]:
            raise ProductionMaintenanceError("replacement candidate quick_check failed")
        if _candidate_identity(profile) != dict(manifest.candidate_identity):
            raise ProductionMaintenanceError(
                "STALE_PLAN: replacement candidate identity mismatch"
            )
        return profile

    def preflight(
        self,
        manifest_path: str | Path,
        *,
        mode: str,
        writer_quiescent: bool,
        gates: Mapping[str, bool],
    ) -> dict[str, Any]:
        manifest = self._read_manifest(manifest_path)
        _, site = self._site_and_database(manifest.database)
        with database_maintenance_lock(
            self.paths, site_database_maintenance_key(site.site_id)
        ):
            return self._preflight_locked(
                manifest_path,
                mode=mode,
                writer_quiescent=writer_quiescent,
                gates=gates,
            )

    @_backend_exclusive
    def migrate_history(
        self,
        migration: HistoryLegacyMigrationService,
        *,
        migration_id: str,
        operation_id: str,
        mode: str,
        authorization: str,
        writer_quiescent: bool,
        max_chunks: int = 1000,
    ) -> dict[str, Any]:
        """Run bounded COPY/VERIFY chunks through the production boundary."""

        _require_execution(
            mode=mode,
            authorization=authorization,
            writer_quiescent=writer_quiescent,
        )
        source, _ = self._site_and_database("devices.db")
        if migration.source_database != source or migration.site_id != self.site_id:
            raise ProductionMaintenanceError("history migration source is not the registered devices.db")
        operation = _safe_component(operation_id, field="operation_id")
        if int(max_chunks) <= 0:
            raise ProductionMaintenanceError("max_chunks must be positive")
        result: dict[str, Any]
        for index in range(int(max_chunks)):
            if index == 0 and migration.journal.get(migration_id) is None:
                result = migration.start(
                    migration_id=migration_id,
                    chunk_rows=500,
                    max_elapsed_seconds=2.0,
                )
            else:
                result = migration.resume(
                    migration_id,
                    chunk_rows=500,
                    max_elapsed_seconds=2.0,
                )
            status = str(result.get("migration", {}).get("status") or "")
            if status == "VERIFIED":
                return {
                    "status": "COPY_VERIFY_COMPLETED",
                    "operation_id": operation,
                    "migration_id": migration_id,
                    "chunks": index + 1,
                    "result": result,
                }
            if status == "FAILED":
                raise ProductionMaintenanceError("History COPY/VERIFY failed")
        return {
            "status": "COPY_VERIFY_IN_PROGRESS",
            "operation_id": operation,
            "migration_id": migration_id,
            "result": result,
        }

    def _preflight_locked(
        self,
        manifest_path: str | Path,
        *,
        mode: str,
        writer_quiescent: bool,
        gates: Mapping[str, bool],
    ) -> dict[str, Any]:
        if mode != "production":
            raise ProductionMaintenanceError("production capability requires explicit mode=production")
        if writer_quiescent is not True:
            raise ProductionMaintenanceError("writer/runtime quiescence preflight failed")
        missing = [key for key in PRODUCTION_GATE_KEYS if gates.get(key) is not True]
        if missing:
            raise ProductionMaintenanceError(f"production gate failed: {', '.join(missing)}")
        manifest = self._read_manifest(manifest_path)
        database, site = self._site_and_database(manifest.database)
        owner = self._owner(manifest.database)
        first = self._validate_source(manifest, database)
        self._validate_rollback_owner(manifest, site, owner)
        second = self._validate_source(manifest, database)
        if first["sha256"] != second["sha256"] or first["size_bytes"] != second["size_bytes"]:
            raise ProductionMaintenanceError("source identity changed during second verification")
        return {
            "mode": mode,
            "site_id": site.site_id,
            "site_display_name": site.display_name,
            "database": manifest.database,
            "source_identity": manifest.database_identity,
            "source_sha256": manifest.source_sha256,
            "source_size": manifest.source_size,
            "schema_fingerprint": manifest.schema_fingerprint,
            "owner": owner.backup_set_id,
            "gates": {key: True for key in PRODUCTION_GATE_KEYS},
            "second_source_verification": "PASS",
            "mutation": "NONE",
        }

    @_backend_exclusive
    def bootstrap_rollback(
        self,
        database: str,
        *,
        owner_contract: ProductionRollbackOwner,
        operation_id: str,
        mode: str,
        authorization: str,
        writer_quiescent: bool,
    ) -> ProductionRollbackOwner:
        if owner_contract.database != database:
            raise ProductionMaintenanceError("rollback owner database mismatch")
        owner = ProductionRollbackBootstrap(
            self.paths,
            site_id=self.site_id,
            owner_contract=owner_contract,
            journal_factory=self._journal_factory,
            _capability_permit=_PRODUCTION_CAPABILITY_PERMIT,
        ).bootstrap(
            operation_id=operation_id,
            mode=mode,
            authorization=authorization,
            writer_quiescent=writer_quiescent,
        )
        self._rollback_owners[(self.site_id, database)] = owner
        return owner

    @_backend_exclusive
    def promote_executable_manifest(
        self,
        manifest_path: str | Path,
        *,
        operation_id: str,
        candidate: str | Path,
        rollback_owner: ProductionRollbackOwner,
        history_state: str,
        task_state: str,
        retirement_state: str,
        mode: str,
        authorization: str,
        writer_quiescent: bool,
        gates: Mapping[str, bool],
        output_path: str | Path | None = None,
    ) -> dict[str, Any]:
        """Create a new immutable EXECUTABLE manifest from current evidence."""

        _require_execution(
            mode=mode,
            authorization=authorization,
            writer_quiescent=writer_quiescent,
        )
        operation = _safe_component(operation_id, field="operation_id")
        source_path = Path(manifest_path).resolve()
        raw = json.loads(source_path.read_text(encoding="utf-8"))
        if not isinstance(raw, Mapping):
            raise ProductionMaintenanceError("manifest must contain a JSON object")
        manifest = self._read_manifest(source_path)
        if manifest.execution_status != "NOT_EXECUTABLE":
            raise ProductionMaintenanceError("only NOT_EXECUTABLE manifests can be promoted")
        database, site = self._site_and_database(manifest.database)
        if rollback_owner != self._rollback_owners.get((self.site_id, manifest.database)):
            self._rollback_owners[(self.site_id, manifest.database)] = rollback_owner
        if not rollback_owner.verified() or rollback_owner.database != manifest.database:
            raise ProductionMaintenanceError("VERIFIED rollback owner is required")
        rollback_profile = _sqlite_immutable_profile(self._rollback_path(site, rollback_owner))
        blockers: list[str] = []
        if (
            not rollback_profile["valid"]
            or rollback_owner.backup_sha256 != str(rollback_profile["sha256"])
            or rollback_owner.backup_size != int(rollback_profile["size_bytes"])
            or rollback_owner.schema_fingerprint != str(rollback_profile["schema_digest"])
        ):
            blockers.append("VERIFIED_ROLLBACK_OWNER")
        if manifest.database == "devices.db" and history_state not in {"PASS", "COMPLETED"}:
            blockers.append("HISTORY_MIGRATION_COMPLETE")
        if manifest.database == "tasks.db" and task_state not in {
            "PASS",
            "COMPLETED",
            "RESULT_REF_AUTHORITY",
        }:
            blockers.append("TASK_ROLLOUT_COMPLETE")
        if retirement_state not in {"PASS", "COMPLETED", "NOT_APPLICABLE"}:
            blockers.append("EXACT_RETIREMENT_COMPLETE")
        missing_gates = [key for key in PRODUCTION_GATE_KEYS if gates.get(key) is not True]
        blockers.extend(f"GATE:{key}" for key in missing_gates)
        source_profile = self._validate_source(manifest, database)
        candidate_path = Path(candidate).resolve()
        expected_candidate = (
            self.paths.staging_dir
            / "production-maintenance"
            / operation
            / f"{manifest.database}.candidate"
        ).resolve()
        if candidate_path != expected_candidate or candidate_path.is_symlink():
            blockers.append("REGISTERED_CANDIDATE_PATH")
        else:
            try:
                self._validate_candidate(manifest, candidate_path)
            except ProductionMaintenanceError:
                blockers.append("CANDIDATE_VERIFIED")
        if blockers:
            raise ProductionMaintenanceError(
                "manifest promotion blocked: " + ", ".join(sorted(set(blockers)))
            )
        evidence = {
            "operation_id": operation,
            "site_id": self.site_id,
            "database": manifest.database,
            "generated_git_head": self.authoritative_git_head,
            "source_sha256": str(source_profile["sha256"]),
            "candidate_sha256": str(manifest.candidate_identity["sha256"]),
            "rollback_owner_digest": _digest(rollback_owner.as_dict()),
            "history_state": history_state,
            "task_state": task_state,
            "retirement_state": retirement_state,
            "writer_quiescent": True,
            "gates": {key: True for key in PRODUCTION_GATE_KEYS},
        }
        body = dict(raw)
        body.pop("manifest_digest", None)
        body.pop("plan_digest", None)
        body.update(
            execution_status="EXECUTABLE",
            blocking_prerequisites=[],
            promotion_evidence=evidence,
            promoted_at=_now_utc(),
        )
        body["plan_digest"] = _digest(body)
        body["manifest_digest"] = _digest(body)
        promoted = ProductionManifest.from_mapping(body)
        target = (
            Path(output_path).resolve()
            if output_path is not None
            else (
                self.paths.staging_dir
                / "production-maintenance"
                / operation
                / f"{manifest.database}.executable-manifest.json"
            ).resolve()
        )
        expected_target = (
            self.paths.staging_dir
            / "production-maintenance"
            / operation
            / f"{manifest.database}.executable-manifest.json"
        ).resolve()
        if target != expected_target or target.is_symlink():
            raise ProductionMaintenanceError("executable manifest path is not registered staging")
        if target.exists():
            existing_raw = json.loads(target.read_text(encoding="utf-8"))
            if not isinstance(existing_raw, Mapping):
                raise ProductionMaintenanceError("existing executable manifest is invalid")
            existing = ProductionManifest.from_mapping(existing_raw)
            existing_evidence = dict(existing.promotion_evidence or {})
            if (
                existing.execution_status != "EXECUTABLE"
                or existing.site_id != self.site_id
                or existing.database != manifest.database
                or existing.source_sha256 != manifest.source_sha256
                or existing.candidate_identity != manifest.candidate_identity
                or existing_evidence.get("operation_id") != operation
                or existing_evidence.get("rollback_owner_digest")
                != _digest(rollback_owner.as_dict())
            ):
                raise ProductionMaintenanceError("existing executable manifest is stale")
            return {
                "status": "EXECUTABLE",
                "manifest": existing.as_dict(),
                "path": str(target),
                "source_manifest": str(source_path),
                "resumed": True,
            }
        _write_json_atomic(target, promoted.as_dict())
        return {
            "status": "EXECUTABLE",
            "manifest": promoted.as_dict(),
            "path": str(target),
            "source_manifest": str(source_path),
        }

    @_backend_exclusive
    def execute_cutover_chain(
        self,
        database: str,
        *,
        operation_id: str,
        owner_contract: ProductionRollbackOwner,
        row_identity: Mapping[str, Any],
        history_migration: HistoryLegacyMigrationService | None = None,
        history_plan: Mapping[str, Any] | None = None,
        mode: str,
        authorization: str,
        writer_quiescent: bool,
        gates: Mapping[str, bool],
        perform_replace: bool = False,
        restart_verifier: Callable[[], bool] | None = None,
        functional_gate: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        """Run the production chain for one allowlisted database.

        History COPY/VERIFY and its exact plan remain owned by the existing
        migration service.  This method consumes that verified plan and owns
        every mutating step from rollback bootstrap onward.  Rehearsals use
        this same method with a registered site rooted under ``D:\\study``.
        """

        _require_execution(
            mode=mode,
            authorization=authorization,
            writer_quiescent=writer_quiescent,
        )
        operation = _safe_component(operation_id, field="operation_id")
        active, _ = self._site_and_database(database)
        owner = self.bootstrap_rollback(
            database,
            owner_contract=owner_contract,
            operation_id=operation,
            mode=mode,
            authorization=authorization,
            writer_quiescent=writer_quiescent,
        )
        history_state = "NOT_APPLICABLE"
        task_state = "NOT_APPLICABLE"
        retirement_state = "NOT_APPLICABLE"
        history_result: dict[str, Any] | None = None
        task_result: dict[str, Any] | None = None
        if database == "devices.db":
            if history_migration is None or history_plan is None:
                raise ProductionMaintenanceError(
                    "devices.db cutover requires a verified History migration and exact plan"
                )
            history_result = ProductionHistoryRetirementExecutor(
                self.paths,
                site_id=self.site_id,
                migration=history_migration,
                authoritative_git_head=self.authoritative_git_head,
                journal_factory=self._journal_factory,
                _capability_permit=_PRODUCTION_CAPABILITY_PERMIT,
            ).execute(
                history_plan,
                operation_id=operation,
                rollback_owner=owner,
                expected_source_sha256=owner.source_sha256,
                expected_schema_fingerprint=owner.schema_fingerprint,
                generated_git_head=self.authoritative_git_head,
                mode=mode,
                authorization=authorization,
                writer_quiescent=writer_quiescent,
            )
            history_state = str(history_result.get("status") or "")
            retirement_state = history_state
        else:
            task_result = ProductionTaskRolloutExecutor(
                self.paths,
                site_id=self.site_id,
                authoritative_git_head=self.authoritative_git_head,
                journal_factory=self._journal_factory,
                _capability_permit=_PRODUCTION_CAPABILITY_PERMIT,
            ).execute(
                operation_id=operation,
                rollback_owner=owner,
                expected_source_sha256=owner.source_sha256,
                generated_git_head=self.authoritative_git_head,
                mode=mode,
                authorization=authorization,
                writer_quiescent=writer_quiescent,
            )
            task_state = str(
                task_result.get("authority", {}).get("state")
                or task_result.get("status")
                or ""
            )
            retirement_state = str(task_result.get("status") or "")
        post_mutation = _checkpoint_database(active)
        compact = ProductionCompactCandidateBuilder(
            self.paths,
            site_id=self.site_id,
            authoritative_git_head=self.authoritative_git_head,
            journal_factory=self._journal_factory,
            _capability_permit=_PRODUCTION_CAPABILITY_PERMIT,
        ).build(
            database,
            operation_id=operation,
            rollback_owner=owner,
            expected_source_sha256=str(post_mutation["sha256"]),
            generated_git_head=self.authoritative_git_head,
            mode=mode,
            authorization=authorization,
            writer_quiescent=writer_quiescent,
        )
        actual_count = _validate_row_identity(active, row_identity)
        manifest_value = build_exact_manifest(
            active,
            candidate=compact["candidate"],
            site_id=self.site_id,
            row_identity=row_identity,
            expected_count=actual_count,
            generated_git_head=self.authoritative_git_head,
            plan_kind=f"production-cutover-{database}",
        )
        manifest_path = (
            self.paths.staging_dir
            / "production-maintenance"
            / operation
            / f"{database}.not-executable-manifest.json"
        ).resolve()
        if manifest_path.exists():
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
            if existing != manifest_value:
                raise ProductionMaintenanceError("existing immutable manifest is stale")
        else:
            _write_json_atomic(manifest_path, manifest_value)
        promoted = self.promote_executable_manifest(
            manifest_path,
            operation_id=operation,
            candidate=compact["candidate"],
            rollback_owner=owner,
            history_state=history_state,
            task_state=task_state,
            retirement_state=retirement_state,
            mode=mode,
            authorization=authorization,
            writer_quiescent=writer_quiescent,
            gates=gates,
        )
        result: dict[str, Any] = {
            "status": "EXECUTABLE",
            "operation_id": operation,
            "database": database,
            "rollback_owner": owner.as_dict(),
            "history": history_result,
            "task": task_result,
            "compact": compact,
            "manifest": promoted,
            "replacement_performed": False,
        }
        if perform_replace:
            if restart_verifier is None or functional_gate is None:
                raise ProductionMaintenanceError(
                    "replacement requires restart and functional verifiers"
                )
            result["replace"] = self.execute_replace(
                promoted["path"],
                candidate=compact["candidate"],
                rollback=self._rollback_path(
                    self._site_and_database(database)[1], owner
                ),
                mode=mode,
                authorization=authorization,
                writer_quiescent=writer_quiescent,
                gates=gates,
                operation_id=operation,
                restart_verifier=restart_verifier,
                functional_gate=functional_gate,
            )
            result["replacement_performed"] = True
            result["status"] = "COMPLETED"
        return result

    @_backend_exclusive
    def execute_replace(
        self,
        manifest_path: str | Path,
        *,
        candidate: str | Path,
        rollback: str | Path,
        mode: str,
        authorization: str,
        writer_quiescent: bool,
        gates: Mapping[str, bool],
        operation_id: str,
        restart_verifier: Callable[[], bool],
        functional_gate: Callable[[], bool],
    ) -> dict[str, Any]:
        if authorization != PRODUCTION_AUTHORIZATION_TOKEN:
            raise ProductionMaintenanceError("explicit production authorization is required")
        manifest = self._read_manifest(manifest_path)
        if manifest.execution_status != "EXECUTABLE":
            raise ProductionMaintenanceError("replacement requires an EXECUTABLE manifest")
        database, site = self._site_and_database(manifest.database)
        candidate_path = Path(candidate).resolve()
        rollback_path = Path(rollback).resolve()
        if len({database, candidate_path, rollback_path}) != 3:
            raise ProductionMaintenanceError("active, candidate, and rollback paths must differ")
        operation_component = str(operation_id or "")
        if (
            not operation_component
            or operation_component in {".", ".."}
            or any(
                char
                not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
                for char in operation_component
            )
        ):
            raise ProductionMaintenanceError("operation_id is unsafe")
        raw_candidate = (
            self.paths.staging_dir
            / "production-maintenance"
            / operation_component
            / f"{manifest.database}.candidate"
        )
        if raw_candidate.is_symlink() or candidate_path != raw_candidate.resolve():
            raise ProductionMaintenanceError("candidate path is not registered staging")
        with database_maintenance_lock(self.paths, site_database_maintenance_key(site.site_id)):
            preflight = self._preflight_locked(
                manifest_path,
                mode=mode,
                writer_quiescent=writer_quiescent,
                gates=gates,
            )
            candidate_profile = self._validate_candidate(manifest, candidate_path)
            _assert_sidecars_quiescent(database)
            _assert_sidecars_quiescent(candidate_path)
            journal = self._journal_factory(self.paths, operation_id)
            lock_key = site_database_maintenance_key(site.site_id)
            journal.update(
                "created",
                **preflight,
                active_path=str(database),
                shadow_path=str(candidate_path),
                rollback_path=str(rollback_path),
                database_kind=manifest.database,
                scope_type="site",
                scope_id=site.site_id,
                maintenance_lock=lock_key,
                switched=False,
            )
            switched = False
            try:
                owner = self._owner(manifest.database)
                if owner.operation_id != operation_id:
                    raise ProductionMaintenanceError("rollback owner operation_id mismatch")
                if rollback_path != self._rollback_path(site, owner):
                    raise ProductionMaintenanceError("rollback path does not match registered owner")
                self._validate_rollback_owner(manifest, site, owner)
                journal.update("backup_verified")
                second = self._validate_source(manifest, database)
                if second["sha256"] != manifest.source_sha256:
                    raise ProductionMaintenanceError(
                        "STALE_SOURCE: second source identity mismatch"
                    )
                second_candidate = self._validate_candidate(manifest, candidate_path)
                if second_candidate["sha256"] != candidate_profile["sha256"]:
                    raise ProductionMaintenanceError(
                        "STALE_PLAN: candidate identity changed during second verification"
                    )
                _atomic_replace(candidate_path, database)
                switched = True
                journal.update("switched", switched=True)
                if not restart_verifier():
                    raise ProductionMaintenanceError("restart verification failed")
                journal.update("restart_verified")
                if not functional_gate():
                    raise ProductionMaintenanceError("functional gate failed")
                journal.update("completed", functional_gate="PASS")
            except Exception as exc:
                if not switched:
                    journal.update(
                        "failed_before_switch",
                        error_type=type(exc).__name__,
                        error=str(exc),
                    )
                    raise
                try:
                    self._rollback_locked(database, rollback_path, journal)
                except Exception as rollback_exc:
                    journal.update(
                        "failed",
                        switched=True,
                        error_type=type(exc).__name__,
                        error=str(exc),
                        rollback_error_type=type(rollback_exc).__name__,
                        rollback_error=str(rollback_exc),
                    )
                    raise ProductionMaintenanceError(
                        "post-switch verification and rollback both failed"
                    ) from rollback_exc
                journal.update(
                    "failed_rolled_back",
                    switched=True,
                    rollback_performed=True,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                raise ProductionMaintenanceError(
                    f"post-switch verification failed; rollback completed: {exc}"
                ) from exc
            return {
                "operation_id": operation_id,
                "site_id": site.site_id,
                "database": manifest.database,
                "replaced": True,
                "rollback": str(rollback_path),
                "restart": "PASS",
                "functional_gate": "PASS",
            }

    @_backend_exclusive
    def rollback(
        self,
        database: str,
        rollback: str | Path,
        *,
        mode: str,
        authorization: str,
        writer_quiescent: bool,
        operation_id: str,
    ) -> dict[str, Any]:
        if mode != "production" or authorization != PRODUCTION_AUTHORIZATION_TOKEN:
            raise ProductionMaintenanceError("rollback requires explicit production mode and authorization")
        if writer_quiescent is not True:
            raise ProductionMaintenanceError("writer/runtime quiescence preflight failed")
        active, site = self._site_and_database(database)
        owner = self._owner(database)
        rollback_path = Path(rollback).resolve()
        with database_maintenance_lock(self.paths, site_database_maintenance_key(site.site_id)):
            journal = self._journal_factory(self.paths, operation_id)
            journal.update(
                "created",
                active_path=str(active),
                rollback_path=str(rollback_path),
                database_kind=database,
                scope_type="site",
                scope_id=site.site_id,
                maintenance_lock=site_database_maintenance_key(site.site_id),
                switched=True,
            )
            rollback_profile = _sqlite_immutable_profile(rollback_path)
            if (
                not rollback_profile["valid"]
                or str(rollback_profile["schema_digest"]) != owner.schema_fingerprint
                or str(rollback_profile["sha256"]) != owner.backup_sha256
                or int(rollback_profile["size_bytes"]) != owner.backup_size
                or rollback_path != self._rollback_path(site, owner)
            ):
                raise ProductionMaintenanceError("rollback owner identity does not match rollback database")
            result = self._rollback_locked(active, rollback_path, journal)
            journal.update("completed", rollback="PASS")
            return {"operation_id": operation_id, "site_id": site.site_id, **result}

    def _rollback_locked(
        self,
        active: Path,
        rollback: Path,
        journal: DatabaseUpgradeJournal,
    ) -> dict[str, Any]:
        _assert_sidecars_quiescent(active)
        _assert_sidecars_quiescent(rollback)
        if not rollback.is_file() or not _sqlite_immutable_profile(rollback)["valid"]:
            raise ProductionMaintenanceError("rollback database is missing or invalid")
        displaced = active.with_name(f"{active.name}.failed-production-replacement")
        if displaced.exists():
            raise ProductionMaintenanceError("rollback displacement already exists")
        _sqlite_backup_readonly(active, displaced)
        restoration = active.with_name(f".{active.name}.production-rollback-restore")
        if restoration.exists():
            raise ProductionMaintenanceError("rollback restoration candidate already exists")
        _sqlite_backup_readonly(rollback, restoration)
        _assert_sidecars_quiescent(active)
        _assert_sidecars_quiescent(rollback)
        _assert_sidecars_quiescent(restoration)
        _atomic_replace(restoration, active)
        restored = _sqlite_immutable_profile(active)
        authority = _sqlite_immutable_profile(rollback)
        if (
            not restored["valid"]
            or restored["schema_digest"] != authority["schema_digest"]
            or restored["table_counts"] != authority["table_counts"]
        ):
            raise ProductionMaintenanceError("rollback restoration verification failed")
        _assert_sidecars_quiescent(active)
        _assert_sidecars_quiescent(rollback)
        journal.update("production_rolled_back", active_path=str(active), displaced_path=str(displaced))
        return {"rolled_back": True, "active": str(active), "displaced": str(displaced)}


__all__ = [
    "PRODUCTION_AUTHORIZATION_TOKEN",
    "PRODUCTION_DATABASE_ALLOWLIST",
    "PRODUCTION_GATE_KEYS",
    "PRODUCTION_SITE_ALLOWLIST",
    "ProductionMaintenanceCapability",
    "ProductionMaintenanceError",
    "ProductionManifest",
    "ProductionRollbackOwner",
    "ProductionRollbackBootstrap",
    "ProductionHistoryRetirementExecutor",
    "ProductionTaskRolloutExecutor",
    "ProductionCompactCandidateBuilder",
    "build_exact_manifest",
    "write_exact_manifest",
]
