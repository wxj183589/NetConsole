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
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from netconsole.core.backend_instance_lock import (
    BackendInstanceInUseError,
    BackendInstanceLock,
)
from netconsole.core.build_metadata import current_build_metadata
from netconsole.core.paths import PathResolver
from netconsole.services.database_footprint_maintenance import (
    assert_development_path,
    sqlite_quick_profile,
)
from netconsole.services.database_upgrade.coordinator import (
    database_maintenance_lock,
    site_database_maintenance_key,
)
from netconsole.services.database_upgrade.journal import DatabaseUpgradeJournal
from netconsole.services.database_upgrade.sqlite_consistency import fsync_file
from netconsole.services.site_storage import SiteRegistryRepository


PRODUCTION_SITE_ALLOWLIST: dict[str, str] = {
    "legacy-dfd356e96ea0": "宁波地铁12号线",
}
PRODUCTION_DATABASE_ALLOWLIST = frozenset({"devices.db", "tasks.db"})
PRODUCTION_AUTHORIZATION_TOKEN = "PRODUCTION_MAINTENANCE_AUTHORIZED"
DEFAULT_MANIFEST_BLOCKERS = (
    "PRODUCTION_ROLLBACK_OWNER",
    "PRODUCTION_BACKUP_VERIFIED",
    "PRODUCTION_WRITER_QUIESCENCE",
    "FINAL_CURRENT_HEAD_GATES",
    "PRODUCTION_CUTOVER_AUTHORIZATION",
)
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
    "targeted",
    "fast",
    "consumer",
    "renderer",
    "electron",
    "architecture",
    "no_reinflation",
    "full",
)
_HEX64 = frozenset("0123456789abcdef")


class ProductionMaintenanceError(RuntimeError):
    """A production maintenance precondition failed; no mutation was attempted."""


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _is_sha256(value: object) -> bool:
    text = str(value or "").casefold()
    return len(text) == 64 and set(text) <= _HEX64


def _is_git_head(value: object) -> bool:
    text = str(value or "").casefold()
    return len(text) == 40 and set(text) <= _HEX64


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _actual_implementation_head(implementation_root: Path) -> str:
    metadata = current_build_metadata(implementation_root)
    head = str(metadata.get("git_commit_full") or "").casefold()
    if not _is_git_head(head):
        raise ProductionMaintenanceError(
            "CURRENT_HEAD_UNAVAILABLE: repository/build HEAD is not verifiable"
        )
    if metadata.get("build_dirty") is not False:
        raise ProductionMaintenanceError(
            "CURRENT_HEAD_DIRTY: repository/build content is not bound to HEAD"
        )
    component_heads = {
        str(metadata.get("frontend_commit") or "").casefold(),
        str(metadata.get("backend_commit") or "").casefold(),
    }
    if component_heads != {head}:
        raise ProductionMaintenanceError(
            "CURRENT_HEAD_MISMATCH: build component HEADs do not match"
        )
    return head


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


def _assert_sidecars_quiescent(path: Path) -> dict[str, Any]:
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
    if wal.exists() or shm.exists():
        raise ProductionMaintenanceError("SQLite sidecar quiescence could not be verified")
    return {
        "wal_zero": True,
        "sqlite_sidecars_quiescent": True,
        "wal_path": str(wal),
        "shm_path": str(shm),
    }


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


@dataclass(frozen=True)
class ProductionEvidenceBinding:
    """Runtime-derived implementation identity plus rehearsal provenance."""

    current_implementation_head: str
    rehearsal_evidence_head: str
    storage_registry_sha256: str
    production_maintenance_script_sha256: str
    implementation_root: Path
    storage_registry_path: Path
    production_maintenance_script_path: Path

    @classmethod
    def from_runtime(
        cls,
        paths: PathResolver,
        *,
        claimed_current_head: str,
        rehearsal_evidence_head: str,
        storage_registry: str | Path,
        production_maintenance_script: str | Path,
    ) -> "ProductionEvidenceBinding":
        implementation_root = Path(paths.app_root).resolve()
        actual = _actual_implementation_head(implementation_root)
        claimed = str(claimed_current_head or "").casefold()
        if claimed != actual:
            raise ProductionMaintenanceError(
                "CURRENT_HEAD_MISMATCH: caller HEAD does not match repository/build HEAD"
            )
        rehearsal = str(rehearsal_evidence_head or "").casefold()
        if not _is_git_head(rehearsal):
            raise ProductionMaintenanceError("rehearsal evidence HEAD is invalid")
        registry = Path(storage_registry).resolve(strict=True)
        script = Path(production_maintenance_script).resolve(strict=True)
        if not registry.is_file() or not script.is_file():
            raise ProductionMaintenanceError("production evidence source is not a file")
        return cls(
            current_implementation_head=actual,
            rehearsal_evidence_head=rehearsal,
            storage_registry_sha256=_sha256_file(registry),
            production_maintenance_script_sha256=_sha256_file(script),
            implementation_root=implementation_root,
            storage_registry_path=registry,
            production_maintenance_script_path=script,
        )

    def assert_current(self, paths: PathResolver | None = None) -> None:
        if (
            paths is not None
            and Path(paths.app_root).resolve() != self.implementation_root
        ):
            raise ProductionMaintenanceError(
                "CURRENT_HEAD_MISMATCH: implementation root changed during execution"
            )
        if (
            _actual_implementation_head(self.implementation_root)
            != self.current_implementation_head
        ):
            raise ProductionMaintenanceError(
                "CURRENT_HEAD_MISMATCH: repository/build HEAD changed during execution"
            )
        try:
            registry_sha256 = _sha256_file(self.storage_registry_path)
            script_sha256 = _sha256_file(self.production_maintenance_script_path)
        except OSError as exc:
            raise ProductionMaintenanceError(
                "EVIDENCE_BINDING_CHANGED: bound source is unavailable"
            ) from exc
        if (
            registry_sha256 != self.storage_registry_sha256
            or script_sha256 != self.production_maintenance_script_sha256
        ):
            raise ProductionMaintenanceError(
                "EVIDENCE_BINDING_CHANGED: registry or maintenance script changed"
            )

    def authorization_evidence(
        self,
        manifest: "ProductionManifest",
    ) -> dict[str, str]:
        return {
            "current_implementation_head": self.current_implementation_head,
            "rehearsal_evidence_head": self.rehearsal_evidence_head,
            "source_snapshot_identity": manifest.database_identity,
            "manifest_generated_head": manifest.generated_git_head,
            "storage_registry_sha256": self.storage_registry_sha256,
            "production_maintenance_script_sha256": (
                self.production_maintenance_script_sha256
            ),
        }


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
    manifest_digest: str = ""
    immutable: bool = True
    execution_status: str = "NOT_EXECUTABLE"
    blocking_prerequisites: tuple[str, ...] = DEFAULT_MANIFEST_BLOCKERS

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
            "execution_status",
            "blocking_prerequisites",
        }
        missing = sorted(key for key in required if key not in value)
        if missing:
            raise ProductionMaintenanceError(
                f"manifest is missing required fields: {', '.join(missing)}"
            )
        row_identity = value["row_identity"]
        if not isinstance(row_identity, Mapping):
            raise ProductionMaintenanceError("manifest row_identity must be an object")
        raw_blockers = value["blocking_prerequisites"]
        if not isinstance(raw_blockers, Sequence) or isinstance(
            raw_blockers, (str, bytes)
        ):
            raise ProductionMaintenanceError(
                "manifest blocking_prerequisites must be an array"
            )
        blockers = tuple(str(item).strip() for item in raw_blockers)
        if any(not item for item in blockers) or len(blockers) != len(set(blockers)):
            raise ProductionMaintenanceError(
                "manifest blocking_prerequisites are invalid"
            )
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
            manifest_digest=str(value.get("manifest_digest") or ""),
            immutable=bool(value.get("immutable", True)),
            execution_status=str(value["execution_status"]),
            blocking_prerequisites=blockers,
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
        if not _is_sha256(result.plan_digest):
            raise ProductionMaintenanceError("manifest plan_digest is invalid")
        if result.manifest_digest and not _is_sha256(result.manifest_digest):
            raise ProductionMaintenanceError("manifest_digest is invalid")
        if result.execution_status not in {"NOT_EXECUTABLE", "EXECUTABLE"}:
            raise ProductionMaintenanceError("manifest execution_status is invalid")
        if result.execution_status == "EXECUTABLE" and result.blocking_prerequisites:
            raise ProductionMaintenanceError(
                "executable manifest still has blocking prerequisites"
            )
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
            "plan_digest": self.plan_digest,
            "generated_git_head": self.generated_git_head,
            "execution_status": self.execution_status,
            "blocking_prerequisites": list(self.blocking_prerequisites),
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


def build_exact_manifest(
    database: str | Path,
    *,
    candidate: str | Path,
    site_id: str,
    row_identity: Mapping[str, Any],
    expected_count: int,
    evidence_binding: ProductionEvidenceBinding,
    plan_kind: str,
    execution_status: str = "NOT_EXECUTABLE",
    blocking_prerequisites: Sequence[str] = DEFAULT_MANIFEST_BLOCKERS,
) -> dict[str, Any]:
    """Build a deterministic manifest from a rehearsal database profile."""

    evidence_binding.assert_current()
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
        "generated_git_head": evidence_binding.current_implementation_head,
        "plan_kind": str(plan_kind),
        "execution_status": str(execution_status),
        "blocking_prerequisites": [
            str(item).strip() for item in blocking_prerequisites
        ],
    }
    body["plan_digest"] = _digest(body)
    body["manifest_digest"] = _digest(body)
    evidence_binding.assert_current()
    return body


def write_exact_manifest(
    path: str | Path,
    manifest: Mapping[str, Any],
    *,
    evidence_binding: ProductionEvidenceBinding,
) -> Path:
    evidence_binding.assert_current()
    target = assert_development_path(path)
    if target.exists():
        raise FileExistsError(f"manifest already exists: {target}")
    parsed = ProductionManifest.from_mapping(manifest)
    if parsed.generated_git_head != evidence_binding.current_implementation_head:
        raise ProductionMaintenanceError(
            "CURRENT_HEAD_MISMATCH: manifest generation HEAD is not current"
        )
    evidence_binding.assert_current()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(parsed.as_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


class ProductionMaintenanceCapability:
    """The only production-capable database replacement boundary."""

    def __init__(
        self,
        paths: PathResolver,
        *,
        site_id: str,
        evidence_binding: ProductionEvidenceBinding,
        rollback_owners: Mapping[tuple[str, str], ProductionRollbackOwner] | None = None,
        journal_factory: Callable[[PathResolver, str], DatabaseUpgradeJournal] = DatabaseUpgradeJournal,
        runtime_lock_factory: Callable[[PathResolver], Any] = BackendInstanceLock,
    ) -> None:
        self.paths = paths
        self.site_id = str(site_id).strip()
        self.evidence_binding = evidence_binding
        self._rollback_owners = dict(rollback_owners or {})
        self._journal_factory = journal_factory
        self._runtime_lock_factory = runtime_lock_factory
        if self.site_id not in PRODUCTION_SITE_ALLOWLIST:
            raise ProductionMaintenanceError("site is not in the production allowlist")
        self.evidence_binding.assert_current(self.paths)

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
        name = Path(str(database)).name
        if Path(str(database)).name != str(database) or name not in PRODUCTION_DATABASE_ALLOWLIST:
            raise ProductionMaintenanceError("database is not in the production allowlist")
        site = SiteRegistryRepository(self.paths).get(self.site_id)
        expected_display = PRODUCTION_SITE_ALLOWLIST[self.site_id]
        if site.display_name != expected_display:
            raise ProductionMaintenanceError("SiteRegistry identity does not match production allowlist")
        target = (site.root_path / "db" / name).resolve()
        raw_target = site.root_path / "db" / name
        if raw_target.is_symlink() or target.parent != (site.root_path / "db").resolve():
            raise ProductionMaintenanceError("production database path is not a registered direct child")
        if not target.is_file() or target.stat().st_size <= 0:
            raise ProductionMaintenanceError("production database is missing or empty")
        return target, site

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
        backup_set_id = owner.backup_set_id
        if (
            not backup_set_id
            or backup_set_id in {".", ".."}
            or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for char in backup_set_id)
        ):
            raise ProductionMaintenanceError("rollback owner backup_set_id is unsafe")
        expected_relative = (
            Path("files")
            / "backups"
            / "production-maintenance"
            / backup_set_id
            / "database.sqlite"
        )
        if Path(owner.backup_relative_path) != expected_relative:
            raise ProductionMaintenanceError("rollback owner path is not canonical")
        raw_target = site.root_path / expected_relative
        target = raw_target.resolve()
        if raw_target.is_symlink():
            raise ProductionMaintenanceError("rollback database cannot be a symlink")
        return target

    def _read_manifest(self, path: str | Path) -> ProductionManifest:
        self.evidence_binding.assert_current(self.paths)
        source = Path(path).resolve()
        raw = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(raw, Mapping):
            raise ProductionMaintenanceError("manifest must contain a JSON object")
        manifest = ProductionManifest.from_mapping(raw)
        if manifest.site_id != self.site_id:
            raise ProductionMaintenanceError("manifest site_id mismatch")
        if (
            manifest.generated_git_head
            != self.evidence_binding.current_implementation_head
        ):
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

    def _acquire_runtime_quiescence_lock(self) -> Any:
        runtime_lock = self._runtime_lock_factory(self.paths)
        try:
            runtime_lock.acquire()
        except BackendInstanceInUseError as exc:
            raise ProductionMaintenanceError(
                "EXECUTION_QUIESCENCE_FAILED: runtime writer or database owner is active"
            ) from exc
        except Exception as exc:
            raise ProductionMaintenanceError(
                "EXECUTION_QUIESCENCE_FAILED: runtime inactivity cannot be verified"
            ) from exc
        return runtime_lock

    def _validate_rollback_owner(
        self,
        manifest: ProductionManifest,
        site: Any,
        owner: ProductionRollbackOwner,
    ) -> tuple[Path, dict[str, Any]]:
        rollback_path = self._rollback_path(site, owner)
        profile = _sqlite_immutable_profile(rollback_path)
        if (
            not profile["valid"]
            or owner.source_identity != manifest.database_identity
            or owner.source_sha256 != manifest.source_sha256
            or owner.source_revision != manifest.source_revision
            or owner.schema_fingerprint != manifest.schema_fingerprint
            or owner.backup_sha256 != str(profile["sha256"])
            or owner.backup_size != int(profile["size_bytes"])
            or str(profile["schema_digest"]) != manifest.schema_fingerprint
            or _validate_row_identity(rollback_path, manifest.row_identity)
            != manifest.expected_count
        ):
            raise ProductionMaintenanceError(
                "VERIFIED rollback owner does not match current source"
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

    def _validate_gate_evidence(
        self,
        gates: Mapping[str, Mapping[str, Any]],
    ) -> dict[str, dict[str, str]]:
        missing = [key for key in PRODUCTION_GATE_KEYS if key not in gates]
        extras = sorted(set(gates) - set(PRODUCTION_GATE_KEYS))
        if missing or extras:
            details = [*(f"missing:{key}" for key in missing), *(f"unknown:{key}" for key in extras)]
            raise ProductionMaintenanceError(
                "production gate evidence is incomplete: " + ", ".join(details)
            )
        validated: dict[str, dict[str, str]] = {}
        for key in PRODUCTION_GATE_KEYS:
            item = gates[key]
            if not isinstance(item, Mapping):
                raise ProductionMaintenanceError(
                    f"production gate evidence is invalid: {key}"
                )
            head = str(item.get("current_implementation_head") or "").casefold()
            digest = str(item.get("evidence_sha256") or "").casefold()
            if (
                str(item.get("status") or "") != "PASS"
                or head != self.evidence_binding.current_implementation_head
                or not _is_sha256(digest)
            ):
                raise ProductionMaintenanceError(
                    f"production gate is not current-HEAD PASS: {key}"
                )
            validated[key] = {
                "status": "PASS",
                "current_implementation_head": head,
                "evidence_sha256": digest,
            }
        return validated

    def _execution_time_recheck(
        self,
        manifest: ProductionManifest,
        database: Path,
        preflight: Mapping[str, Any],
    ) -> dict[str, Any]:
        self.evidence_binding.assert_current(self.paths)
        sidecars = _assert_sidecars_quiescent(database)
        source = self._validate_source(manifest, database)
        if (
            str(source["sha256"]) != str(preflight["source_sha256"])
            or int(source["size_bytes"]) != int(preflight["source_size"])
            or str(source["schema_digest"]) != str(preflight["schema_fingerprint"])
        ):
            raise ProductionMaintenanceError(
                "STALE_SOURCE: source identity changed after static preflight"
            )
        return {
            "runtime_writer_stopped": True,
            "database_owner_inactive": True,
            "wal_zero": sidecars["wal_zero"],
            "sqlite_sidecars_quiescent": sidecars["sqlite_sidecars_quiescent"],
            "source_sha256": str(source["sha256"]),
            "source_size": int(source["size_bytes"]),
            "schema_fingerprint": str(source["schema_digest"]),
            "status": "PASS",
        }

    def preflight(
        self,
        manifest_path: str | Path,
        *,
        mode: str,
        writer_quiescent: bool,
        gates: Mapping[str, Mapping[str, Any]],
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

    def _preflight_locked(
        self,
        manifest_path: str | Path,
        *,
        mode: str,
        writer_quiescent: bool,
        gates: Mapping[str, Mapping[str, Any]],
    ) -> dict[str, Any]:
        if mode != "production":
            raise ProductionMaintenanceError("production capability requires explicit mode=production")
        if writer_quiescent is not True:
            raise ProductionMaintenanceError("writer/runtime quiescence preflight failed")
        validated_gates = self._validate_gate_evidence(gates)
        manifest = self._read_manifest(manifest_path)
        if manifest.execution_status != "EXECUTABLE":
            blockers = ", ".join(manifest.blocking_prerequisites) or "UNSPECIFIED"
            raise ProductionMaintenanceError(
                f"manifest is NOT_EXECUTABLE: {blockers}"
            )
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
            "gates": validated_gates,
            "evidence_binding": self.evidence_binding.authorization_evidence(manifest),
            "second_source_verification": "PASS",
            "mutation": "NONE",
        }

    def execute_replace(
        self,
        manifest_path: str | Path,
        *,
        candidate: str | Path,
        rollback: str | Path,
        mode: str,
        authorization: str,
        writer_quiescent: bool,
        gates: Mapping[str, Mapping[str, Any]],
        operation_id: str,
        restart_verifier: Callable[[], bool],
        functional_gate: Callable[[], bool],
    ) -> dict[str, Any]:
        if authorization != PRODUCTION_AUTHORIZATION_TOKEN:
            raise ProductionMaintenanceError("explicit production authorization is required")
        manifest = self._read_manifest(manifest_path)
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
                runtime_lock = self._acquire_runtime_quiescence_lock()
                execution_recheck: dict[str, Any] | None = None
                try:
                    execution_recheck = self._execution_time_recheck(
                        manifest,
                        database,
                        preflight,
                    )
                    _assert_sidecars_quiescent(candidate_path)
                    second_candidate = self._validate_candidate(
                        manifest,
                        candidate_path,
                    )
                    if second_candidate["sha256"] != candidate_profile["sha256"]:
                        raise ProductionMaintenanceError(
                            "STALE_PLAN: candidate identity changed during execution recheck"
                        )
                    journal.update(
                        "execution_quiescence_verified",
                        execution_time_recheck=execution_recheck,
                    )
                    _atomic_replace(candidate_path, database)
                    switched = True
                finally:
                    runtime_lock.release()
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
                    rollback_runtime_lock = self._acquire_runtime_quiescence_lock()
                    try:
                        self.evidence_binding.assert_current(self.paths)
                        self._validate_rollback_owner(manifest, site, owner)
                        _assert_sidecars_quiescent(database)
                        self._rollback_locked(database, rollback_path, journal)
                    finally:
                        rollback_runtime_lock.release()
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
                "execution_time_recheck": execution_recheck,
                "evidence_binding": self.evidence_binding.authorization_evidence(
                    manifest
                ),
            }

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
            self.evidence_binding.assert_current(self.paths)
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
            runtime_lock = self._acquire_runtime_quiescence_lock()
            try:
                _assert_sidecars_quiescent(active)
                rollback_profile = _sqlite_immutable_profile(rollback_path)
                if (
                    not rollback_profile["valid"]
                    or str(rollback_profile["schema_digest"])
                    != owner.schema_fingerprint
                    or str(rollback_profile["sha256"]) != owner.backup_sha256
                    or int(rollback_profile["size_bytes"]) != owner.backup_size
                    or rollback_path != self._rollback_path(site, owner)
                ):
                    raise ProductionMaintenanceError(
                        "rollback owner identity does not match rollback database"
                    )
                result = self._rollback_locked(active, rollback_path, journal)
            finally:
                runtime_lock.release()
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
    "ProductionEvidenceBinding",
    "ProductionMaintenanceCapability",
    "ProductionMaintenanceError",
    "ProductionManifest",
    "ProductionRollbackOwner",
    "build_exact_manifest",
    "write_exact_manifest",
]
