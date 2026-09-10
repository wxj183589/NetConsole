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
from dataclasses import dataclass, replace
from datetime import UTC, datetime
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
    "legacy-784dcd2b63e3": "宁波地铁10号线",
    "legacy-dfd356e96ea0": "宁波地铁12号线",
    "legacy-422faf1196ef": "宁波地铁1号线",
    "legacy-0d1a8935839e": "宁波地铁6号线",
    "hzl10": "杭州地铁10号线",
    "legacy-6fef62d71cfd": "杭州地铁4号线-信号-A网",
    "legacy-59b885329893": "杭州地铁4号线-信号-B网",
    "hzdt-09": "杭州地铁9号线",
    "sxl1": "绍兴地铁1号线",
}
PRODUCTION_DATABASE_ALLOWLIST = frozenset({"devices.db", "tasks.db"})
PRODUCTION_AUTHORIZATION_TOKEN = "PRODUCTION_MAINTENANCE_AUTHORIZED"
PRODUCTION_TASK_OPERATIONAL_GC = "TASK_OPERATIONAL_GC"
PRODUCTION_ROLLBACK_SCOPE_KIND = "resource-set"
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
_FINAL_GATE_REQUIRED_SUITES: dict[str, frozenset[str]] = {
    "targeted": frozenset({"storage-targeted"}),
    "fast": frozenset(
        {
            "change-impact",
            "ruff-changed",
            "python-direct",
            "renderer-direct",
            "electron-direct",
            "architecture-targeted",
            "git-diff-check",
        }
    ),
    "consumer": frozenset(
        {
            "change-impact",
            "ruff-changed",
            "python-direct",
            "renderer-direct",
            "electron-direct",
            "architecture-targeted",
            "git-diff-check",
            "renderer-full",
            "python-full",
            "electron-contract",
            "architecture-guards",
            "main-contract-smoke",
        }
    ),
    "full": frozenset(
        {
            "renderer-full",
            "python-full",
            "electron-contract",
            "architecture-guards",
            "main-contract-smoke",
            "ruff-full",
            "docs-path-guards",
            "git-diff-check",
        }
    ),
}
_NO_REINFLATION_SCENARIOS = frozenset(
    {
        "task_progress_and_result",
        "ground_current_state",
        "online_mr_raw_authority",
        "ground_ping_syslog_raw_growth",
        "device_lldp_ap_state",
        "mesh_source_and_reparse",
        "site_package_staging",
        "backup_same_revision",
    }
)
_HISTORY_SOURCE_TABLES = frozenset(
    {
        "ac_fit_ap_lldp_history",
        "ac_fit_ap_optical_history",
        "ac_fit_ap_radio_history",
        "ac_fit_ap_resource_history",
        "ap_lldp_history",
        "ap_optical_history",
        "device_facts_history",
        "device_interfaces_history",
        "device_lldp_neighbors_history",
        "device_optical_modules_history",
    }
)
_DEDICATED_GATE_ARTIFACTS = {
    "production_rollback_owner": "PRODUCTION_ROLLBACK_OWNER",
    "production_backup_verified": "PRODUCTION_BACKUP_VERIFIED",
    "production_maintenance_gate": "PRODUCTION_MAINTENANCE_PREFLIGHT",
    "restart": "PRODUCTION_RESTART_EVIDENCE",
}


class ProductionMaintenanceError(RuntimeError):
    """A production maintenance precondition failed; no mutation was attempted."""


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def normalize_rollback_resource_path(value: str | Path) -> str:
    """Return one stable, case-insensitive path identity for scope comparison."""

    text = str(value or "").replace("\\", "/").strip()
    if not text:
        raise ProductionMaintenanceError("rollback resource path is empty")
    drive, remainder = os.path.splitdrive(text)
    normalized = f"{drive.lower()}{remainder}".replace("//", "/")
    while "/./" in normalized:
        normalized = normalized.replace("/./", "/")
    if normalized.endswith("/."):
        normalized = normalized[:-2]
    return normalized.casefold()


def _safe_scope_identifier(value: object, *, field: str) -> str:
    text = str(value or "").strip()
    if (
        not text
        or text in {".", ".."}
        or any(
            char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
            for char in text
        )
    ):
        raise ProductionMaintenanceError(f"{field} is unsafe")
    return text


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


def _sqlite_foreign_key_check(path: Path) -> str:
    _assert_no_nonempty_wal(path)
    uri = f"{path.resolve().as_uri()}?mode=ro&immutable=1"
    with closing(sqlite3.connect(uri, uri=True, timeout=30)) as connection:
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        rows = connection.execute("PRAGMA foreign_key_check").fetchall()
    return "ok" if not rows else json.dumps([tuple(row) for row in rows], ensure_ascii=False)


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
    _assert_no_nonempty_wal(source)
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
        if _sqlite_foreign_key_check(temporary) != "ok":
            raise ProductionMaintenanceError("rollback backup foreign_key_check failed")
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


def _source_status_and_head(value: Mapping[str, Any]) -> tuple[str, str]:
    status = str(
        value.get("result") or value.get("status") or value.get("overall_status") or ""
    ).upper()
    head = str(
        value.get("current_implementation_head")
        or value.get("git_head")
        or value.get("head_sha")
        or ""
    ).casefold()
    return status, head


def _suite_pass(value: Mapping[str, Any], suite_id: str) -> bool:
    suites = value.get("executed_suites")
    return isinstance(suites, list) and any(
        isinstance(item, Mapping)
        and str(item.get("suite_id") or "") == suite_id
        and str(item.get("status") or "").upper() == "PASS"
        for item in suites
    )


def _all_true_mapping(value: object) -> bool:
    return isinstance(value, Mapping) and bool(value) and all(
        item is True for item in value.values()
    )


def _require_current_head_pass(
    key: str,
    reports: Sequence[Mapping[str, Any]],
    binding: ProductionEvidenceBinding,
) -> None:
    for report in reports:
        status, head = _source_status_and_head(report)
        if status != "PASS" or head != binding.current_implementation_head:
            raise ProductionMaintenanceError(
                f"production gate source report is not current-HEAD PASS: {key}"
            )


def _validate_exact_manifest_source(
    report: Mapping[str, Any],
    binding: ProductionEvidenceBinding,
) -> str:
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
        "manifest_digest",
        "manifest_version",
        "immutable",
        "execution_status",
        "blocking_prerequisites",
    }
    if not required <= set(report):
        raise ProductionMaintenanceError("production exact manifest source is incomplete")
    database = Path(str(report.get("database") or "")).name
    candidate = report.get("candidate_identity")
    row_identity = report.get("row_identity")
    manifest_digest = str(report.get("manifest_digest") or "").casefold()
    plan_digest = str(report.get("plan_digest") or "").casefold()
    manifest_body = dict(report)
    manifest_body.pop("manifest_digest", None)
    plan_body = dict(manifest_body)
    plan_body.pop("plan_digest", None)
    if (
        database not in PRODUCTION_DATABASE_ALLOWLIST
        or str(report.get("generated_git_head") or "").casefold()
        != binding.current_implementation_head
        or int(report.get("manifest_version") or 0) != 2
        or report.get("immutable") is not True
        or str(report.get("execution_status") or "") != "NOT_EXECUTABLE"
        or not _is_sha256(str(report.get("database_identity") or ""))
        or int(report.get("source_size") or 0) <= 0
        or not _is_sha256(str(report.get("source_sha256") or ""))
        or str(report.get("source_revision") or "") != str(report.get("source_sha256") or "")
        or not _is_sha256(str(report.get("schema_fingerprint") or ""))
        or not isinstance(row_identity, Mapping)
        or not isinstance(candidate, Mapping)
        or int(report.get("expected_count") or 0) <= 0
        or not _is_sha256(str(candidate.get("sha256") or ""))
        or int(candidate.get("size_bytes") or 0) <= 0
        or not _is_sha256(str(candidate.get("schema_fingerprint") or ""))
        or not isinstance(candidate.get("table_counts"), Mapping)
        or not _is_sha256(plan_digest)
        or not _is_sha256(manifest_digest)
        or plan_digest != _digest(plan_body)
        or manifest_digest != _digest(manifest_body)
    ):
        raise ProductionMaintenanceError("production exact manifest source is invalid")
    return database


def _validate_gate_source_semantics(
    key: str,
    reports: Sequence[Mapping[str, Any]],
    *,
    binding: ProductionEvidenceBinding,
) -> None:
    if not reports:
        raise ProductionMaintenanceError(f"production gate evidence has no source reports: {key}")
    if key == "current_exact_plans":
        if len(reports) != 2 or {
            _validate_exact_manifest_source(report, binding) for report in reports
        } != PRODUCTION_DATABASE_ALLOWLIST:
            raise ProductionMaintenanceError(
                "production exact plan gate is missing devices or tasks"
            )
        return
    if key == "current_snapshot_rehearsal":
        if len(reports) != 1:
            raise ProductionMaintenanceError("production snapshot rehearsal report is invalid")
        report = reports[0]
        profiles = [report.get(name) for name in ("devices", "tasks")]
        if (
            report.get("source_preserved") is not True
            or any(not isinstance(profile, Mapping) for profile in profiles)
            or any(
                str(profile.get("format") or "") != "netconsole-sqlite-online-backup-v1"
                or profile.get("valid") is not True
                or str(profile.get("quick_check") or "").casefold() != "ok"
                or int(profile.get("size_bytes") or 0) <= 0
                or not _is_sha256(profile.get("sha256"))
                or not isinstance(profile.get("table_counts"), Mapping)
                for profile in profiles
                if isinstance(profile, Mapping)
            )
        ):
            raise ProductionMaintenanceError("production snapshot rehearsal report is incomplete")
        return
    if key == "current_history_copy_verify":
        tables: set[str] = set()
        for report in reports:
            query = report.get("target_query")
            table = str(report.get("source_table") or "")
            health = query.get("history_health") if isinstance(query, Mapping) else None
            if (
                str(report.get("result") or "").upper() != "PASS"
                or report.get("post_delete") is not True
                or table not in _HISTORY_SOURCE_TABLES
                or not isinstance(query, Mapping)
                or str(query.get("query_mode") or "")
                != "POST_DELETE_CANONICAL_TARGET_REQUERY"
                or not isinstance(health, Mapping)
                or str(health.get("status") or "")
                != "ready"
                or int(query.get("expected_rows") or -1) != int(query.get("target_rows") or -2)
                or int(query.get("page_one_rows") or 0) <= 0
                or int(query.get("page_two_rows") or 0) <= 0
            ):
                raise ProductionMaintenanceError("production history verification report is invalid")
            tables.add(table)
        if tables != _HISTORY_SOURCE_TABLES:
            raise ProductionMaintenanceError("production history verification is incomplete")
        return
    if key == "current_task_rollout":
        if len(reports) != 1:
            raise ProductionMaintenanceError("production task rollout report is invalid")
        report = reports[0]
        consumers = {
            "Agent",
            "Artifact",
            "Ground",
            "Online MR",
            "REST",
            "Site Package",
            "Task Center",
            "WebSocket",
        }
        counts = report.get("site_package_counts")
        if (
            any(str(report.get(consumer) or "") != "PASS" for consumer in consumers)
            or str(report.get("restart") or "") != "PASS"
            or int(report.get("task_results_verified") or 0) <= 0
            or not isinstance(counts, Mapping)
            or int(counts.get("task_results") or 0)
            != int(report.get("task_results_verified") or -1)
        ):
            raise ProductionMaintenanceError("production task rollout report is incomplete")
        return

    _require_current_head_pass(key, reports, binding)
    if key in _FINAL_GATE_REQUIRED_SUITES:
        if len(reports) != 1 or str(reports[0].get("mode") or "").casefold() != key:
            raise ProductionMaintenanceError(
                f"production gate source report mode does not match gate: {key}"
            )
        report = reports[0]
        required = _FINAL_GATE_REQUIRED_SUITES[key]
        passed = {str(item) for item in report.get("passed", [])}
        declared = {str(item) for item in report.get("required_suites", [])}
        suites = report.get("executed_suites")
        if (
            report.get("failed")
            or report.get("not_run")
            or declared != required
            or not required <= passed
            or (
                isinstance(suites, list)
                and any(
                    not isinstance(item, Mapping)
                    or str(item.get("status") or "").upper() != "PASS"
                    for item in suites
                )
            )
        ):
            raise ProductionMaintenanceError(
                f"production gate source report suites failed: {key}"
            )
        return
    if key in {"renderer", "electron", "architecture"}:
        required_suite = {
            "renderer": "renderer-full",
            "electron": "electron-contract",
            "architecture": "architecture-guards",
        }[key]
        if len(reports) != 1 or not _suite_pass(reports[0], required_suite):
            raise ProductionMaintenanceError(
                f"production gate source report is missing PASS suite: {key}"
            )
        return
    if key == "functional_compatibility":
        if len(reports) != 1:
            raise ProductionMaintenanceError("production functional compatibility report is invalid")
        report = reports[0]
        summary = report.get("summary")
        matrix = report.get("consumer_matrix")
        final_evidence = report.get("final_evidence")
        generator = report.get("generator")
        if (
            str(report.get("artifact") or "") != "FUNCTIONAL_COMPATIBILITY"
            or str(report.get("audit_mode") or "") != "FINAL_EVIDENCE"
            or not isinstance(summary, Mapping)
            or int(summary.get("consumer_check_count") or 0) != 29
            or int(summary.get("passed_count") or 0) != 29
            or int(summary.get("failed_count") or 0) != 0
            or not isinstance(matrix, list)
            or len(matrix) != 29
            or len({str(item.get("id") or "") for item in matrix if isinstance(item, Mapping)}) != 29
            or any(
                not isinstance(item, Mapping)
                or str(item.get("status") or "").upper() != "PASS"
                for item in matrix
            )
            or not isinstance(final_evidence, Mapping)
            or str(final_evidence.get("git_head") or "").casefold()
            != binding.current_implementation_head
            or not isinstance(generator, Mapping)
            or str(generator.get("git_head") or "").casefold()
            != binding.current_implementation_head
        ):
            raise ProductionMaintenanceError("production functional compatibility report is incomplete")
        return
    if key == "site_package":
        if len(reports) != 1:
            raise ProductionMaintenanceError("production Site Package report is invalid")
        report = reports[0]
        parity = report.get("parity")
        cleanup = report.get("staging_cleanup")
        interruption = cleanup.get("interruption_recovery") if isinstance(cleanup, Mapping) else None
        package = report.get("package")
        registered_storage = parity.get("registered_storage") if isinstance(parity, Mapping) else None
        imported = report.get("imported")
        if (
            str(report.get("format") or "")
            != "netconsole-integrated-site-package-validation-v1"
            or not isinstance(package, Mapping)
            or not _is_sha256(package.get("sha256"))
            or not isinstance(parity, Mapping)
            or not _all_true_mapping(parity.get("operational"))
            or not _all_true_mapping(parity.get("authorities"))
            or not _all_true_mapping(parity.get("repository_api"))
            or not isinstance(registered_storage, Mapping)
            or str(registered_storage.get("status") or "") != "PASS"
            or not isinstance(imported, Mapping)
            or str(imported.get("restart") or "") != "PASS"
            or not isinstance(cleanup, Mapping)
            or any(
                cleanup.get(name) is not True
                for name in (
                    "export_success",
                    "import_success",
                    "import_failure",
                    "failure_rollback",
                )
            )
            or not isinstance(interruption, Mapping)
            or str(interruption.get("status") or "") != "PASS"
            or not isinstance(cleanup.get("interruption_remaining"), list)
            or cleanup.get("interruption_remaining")
        ):
            raise ProductionMaintenanceError("production Site Package report is incomplete")
        return
    if key == "no_reinflation":
        if len(reports) != 1:
            raise ProductionMaintenanceError("production No-Reinflation report is invalid")
        report = reports[0]
        summary = report.get("summary")
        scenarios = report.get("scenarios")
        generator = report.get("generator")
        if (
            str(report.get("format") or "") != "netconsole-storage-no-reinflation"
            or not isinstance(summary, Mapping)
            or int(summary.get("scenario_count") or 0) != 8
            or int(summary.get("passed") or 0) != 8
            or int(summary.get("failed") or 0) != 0
            or not isinstance(generator, Mapping)
            or str(generator.get("git_head") or "").casefold()
            != binding.current_implementation_head
            or not isinstance(scenarios, list)
            or {str(item.get("scenario_id") or "") for item in scenarios if isinstance(item, Mapping)}
            != _NO_REINFLATION_SCENARIOS
            or any(
                not isinstance(item, Mapping)
                or str(item.get("status") or "") != "PASS"
                or not isinstance(item.get("storage_amplification"), Mapping)
                or not isinstance(item.get("cleanup"), Mapping)
                or str(item["storage_amplification"].get("measurement_status") or "")
                != "PASS"
                or int(item["storage_amplification"].get("total_physical_bytes") or 0)
                <= 0
                or str(item["cleanup"].get("status") or "") != "PASS"
                for item in scenarios
            )
        ):
            raise ProductionMaintenanceError("production No-Reinflation report is incomplete")
        return
    if key in _DEDICATED_GATE_ARTIFACTS:
        if len(reports) != 1:
            raise ProductionMaintenanceError(f"production gate source report is invalid: {key}")
        report = reports[0]
        if (
            str(report.get("artifact") or "") != _DEDICATED_GATE_ARTIFACTS[key]
            or not _is_sha256(str(report.get("source_snapshot_identity") or ""))
            or not str(report.get("site_id") or "").strip()
            or not str(report.get("database") or "").strip()
        ):
            raise ProductionMaintenanceError(
                f"production gate source report is not canonical: {key}"
            )
        return
    raise ProductionMaintenanceError(f"production gate source report is unsupported: {key}")


def validate_bound_production_gate(
    key: str,
    value: Mapping[str, Any],
    *,
    binding: ProductionEvidenceBinding,
) -> dict[str, str]:
    if (
        str(value.get("evidence_type") or "") != "production-current-head-gate-v2"
        or str(value.get("gate") or "") != key
        or str(value.get("status") or "") != "PASS"
        or str(value.get("current_implementation_head") or "").casefold()
        != binding.current_implementation_head
        or str(value.get("rehearsal_evidence_head") or "").casefold()
        != binding.rehearsal_evidence_head
        or not str(value.get("verified_at") or "").strip()
    ):
        raise ProductionMaintenanceError(f"production gate evidence is not current-HEAD PASS: {key}")
    source_specs = value.get("source_reports")
    if not isinstance(source_specs, list) or not source_specs:
        raise ProductionMaintenanceError(f"production gate evidence is not source-bound: {key}")
    source_values: list[Mapping[str, Any]] = []
    source_hashes: list[str] = []
    for source_spec in source_specs:
        if not isinstance(source_spec, Mapping):
            raise ProductionMaintenanceError(f"production gate source binding is invalid: {key}")
        raw_path = Path(str(source_spec.get("path") or ""))
        expected_sha256 = str(source_spec.get("sha256") or "").casefold()
        if not raw_path.is_absolute() or not _is_sha256(expected_sha256):
            raise ProductionMaintenanceError(f"production gate source binding is invalid: {key}")
        report_path = assert_development_path(raw_path)
        if not report_path.is_file() or _sha256_file(report_path) != expected_sha256:
            raise ProductionMaintenanceError(
                f"production gate source report is missing or changed: {key}"
            )
        try:
            source_value = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProductionMaintenanceError(
                f"production gate source report is invalid: {key}"
            ) from exc
        if not isinstance(source_value, Mapping):
            raise ProductionMaintenanceError(
                f"production gate source report must be an object: {key}"
            )
        status, head = _source_status_and_head(source_value)
        if (
            str(source_spec.get("status") or "").upper() != status
            or str(source_spec.get("current_implementation_head") or "").casefold()
            != head
        ):
            raise ProductionMaintenanceError(
                f"production gate source binding does not match report: {key}"
            )
        source_values.append(source_value)
        source_hashes.append(expected_sha256)
    _validate_gate_source_semantics(key, source_values, binding=binding)
    evidence_sha256 = _digest(source_hashes)
    if str(value.get("evidence_sha256") or "").casefold() != evidence_sha256:
        raise ProductionMaintenanceError(f"production gate evidence digest is invalid: {key}")
    return {
        "status": "PASS",
        "current_implementation_head": binding.current_implementation_head,
        "evidence_sha256": evidence_sha256,
    }


def validate_production_gate_evidence(
    gates: Mapping[str, Mapping[str, Any]],
    *,
    binding: ProductionEvidenceBinding,
) -> dict[str, dict[str, str]]:
    missing = [key for key in PRODUCTION_GATE_KEYS if key not in gates]
    extras = sorted(set(gates) - set(PRODUCTION_GATE_KEYS))
    if missing or extras:
        details = [
            *(f"missing:{key}" for key in missing),
            *(f"unknown:{key}" for key in extras),
        ]
        raise ProductionMaintenanceError(
            "production gate evidence is incomplete: " + ", ".join(details)
        )
    return {
        key: validate_bound_production_gate(key, gates[key], binding=binding)
        for key in PRODUCTION_GATE_KEYS
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
class ProductionRollbackResource:
    site_id: str
    site: str
    database_role: str
    source_path: str
    normalized_path: str
    source_identity: str
    source_sha256: str
    source_revision: str
    source_size: int
    schema_fingerprint: str
    quick_check: str
    foreign_key_check: str
    backup_relative_path: str = ""
    backup_sha256: str = ""
    backup_size: int = 0
    verified_at: str = ""
    status: str = "PENDING_PRODUCTION_BACKUP"

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ProductionRollbackResource":
        required = (
            "site_id",
            "site",
            "database_role",
            "source_path",
            "normalized_path",
            "source_identity",
            "source_sha256",
            "source_revision",
            "source_size",
            "schema_fingerprint",
            "quick_check",
            "foreign_key_check",
        )
        missing = [field for field in required if field not in value]
        if missing:
            raise ProductionMaintenanceError(
                "rollback resource is missing required fields: " + ", ".join(missing)
            )
        try:
            source_size = int(value["source_size"])
            backup_size = int(value.get("backup_size") or 0)
        except (TypeError, ValueError) as exc:
            raise ProductionMaintenanceError("rollback resource size is invalid") from exc
        resource = cls(
            site_id=str(value["site_id"]),
            site=str(value["site"]),
            database_role=str(value["database_role"]),
            source_path=str(value["source_path"]),
            normalized_path=normalize_rollback_resource_path(value["normalized_path"]),
            source_identity=str(value["source_identity"]),
            source_sha256=str(value["source_sha256"]),
            source_revision=str(value["source_revision"]),
            source_size=source_size,
            schema_fingerprint=str(value["schema_fingerprint"]),
            quick_check=str(value["quick_check"]),
            foreign_key_check=str(value["foreign_key_check"]),
            backup_relative_path=str(value.get("backup_relative_path") or ""),
            backup_sha256=str(value.get("backup_sha256") or ""),
            backup_size=backup_size,
            verified_at=str(value.get("verified_at") or ""),
            status=str(value.get("status") or "PENDING_PRODUCTION_BACKUP"),
        )
        if (
            resource.database_role not in PRODUCTION_DATABASE_ALLOWLIST
            or resource.source_size <= 0
            or not _is_sha256(resource.source_identity)
            or not _is_sha256(resource.source_sha256)
            or resource.source_revision != resource.source_sha256
            or not _is_sha256(resource.schema_fingerprint)
            or resource.normalized_path != normalize_rollback_resource_path(resource.source_path)
        ):
            raise ProductionMaintenanceError("rollback resource identity is invalid")
        if resource.status not in {"PENDING_PRODUCTION_BACKUP", "VERIFIED"}:
            raise ProductionMaintenanceError("rollback resource status is invalid")
        return resource

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.site_id, self.database_role, self.normalized_path)

    def as_dict(self) -> dict[str, Any]:
        return {
            "site_id": self.site_id,
            "site": self.site,
            "database_role": self.database_role,
            "source_path": self.source_path,
            "normalized_path": self.normalized_path,
            "source_identity": self.source_identity,
            "source_sha256": self.source_sha256,
            "source_revision": self.source_revision,
            "source_size": self.source_size,
            "schema_fingerprint": self.schema_fingerprint,
            "quick_check": self.quick_check,
            "foreign_key_check": self.foreign_key_check,
            "backup_relative_path": self.backup_relative_path,
            "backup_sha256": self.backup_sha256,
            "backup_size": self.backup_size,
            "verified_at": self.verified_at,
            "status": self.status,
        }

    def verified(self) -> bool:
        return bool(
            self.site_id in PRODUCTION_SITE_ALLOWLIST
            and self.database_role == "tasks.db"
            and self.source_size > 0
            and _is_sha256(self.source_identity)
            and _is_sha256(self.source_sha256)
            and self.source_revision == self.source_sha256
            and _is_sha256(self.schema_fingerprint)
            and self.quick_check == "ok"
            and self.foreign_key_check == "ok"
            and self.backup_relative_path
            and _is_sha256(self.backup_sha256)
            and self.backup_size > 0
            and self.verified_at
            and self.status == "VERIFIED"
        )


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
    owner: str = "ProductionMaintenanceCapability"
    maintenance_id: str = ""
    maintenance_type: str = ""
    scope_kind: str = "single-resource"
    resources: tuple[ProductionRollbackResource, ...] = ()

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
            owner=str(value.get("owner") or "ProductionMaintenanceCapability"),
            maintenance_id=str(value.get("maintenance_id") or ""),
            maintenance_type=str(value.get("maintenance_type") or ""),
            scope_kind=str(value.get("scope_kind") or "single-resource"),
            resources=tuple(
                ProductionRollbackResource.from_mapping(item)
                for item in value.get("resources", [])
            ),
        )

    def verified(self) -> bool:
        if self.resources:
            keys = [resource.key for resource in self.resources]
            return bool(
                self.owner == "ProductionMaintenanceCapability"
                and self.maintenance_id
                and self.maintenance_type == PRODUCTION_TASK_OPERATIONAL_GC
                and self.scope_kind == PRODUCTION_ROLLBACK_SCOPE_KIND
                and len(keys) == len(set(keys))
                and len(self.resources) == 9
                and all(resource.verified() for resource in self.resources)
                and self.backup_set_id
                and self.operation_id
                and self.verified_at
                and self.rollback_required
                and self.observation_state == "VERIFIED"
                and self.retire_state == "PROTECT"
            )
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
        value: dict[str, Any] = {
            "owner": self.owner,
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
        if self.resources:
            value.update(
                {
                    "maintenance_id": self.maintenance_id,
                    "maintenance_type": self.maintenance_type,
                    "scope_kind": self.scope_kind,
                    "resources": [resource.as_dict() for resource in self.resources],
                }
            )
        return value

    def resource_for(self, site_id: str, database: str) -> ProductionRollbackResource | None:
        for resource in self.resources:
            if resource.site_id == site_id and resource.database_role == database:
                return resource
        return None


def _scope_resources(scope: Mapping[str, Any]) -> tuple[ProductionRollbackResource, ...]:
    raw_resources = scope.get("resources")
    if not isinstance(raw_resources, Sequence) or isinstance(raw_resources, (str, bytes)):
        raise ProductionMaintenanceError("rollback scope resources must be an array")
    resources = tuple(
        item if isinstance(item, ProductionRollbackResource)
        else ProductionRollbackResource.from_mapping(item)
        for item in raw_resources
    )
    keys = [resource.key for resource in resources]
    if len(keys) != len(set(keys)):
        raise ProductionMaintenanceError("rollback scope contains duplicate resources")
    if len(resources) != 9:
        raise ProductionMaintenanceError("production tasks rollback scope must contain 9 resources")
    if {resource.site_id for resource in resources} != set(PRODUCTION_SITE_ALLOWLIST):
        raise ProductionMaintenanceError("rollback scope does not cover the production site allowlist")
    if {resource.database_role for resource in resources} != {"tasks.db"}:
        raise ProductionMaintenanceError("rollback scope contains a non-tasks database role")
    return resources


def _scope_key_text(key: tuple[str, str, str]) -> str:
    return "|".join(key)


def verify_rollback_owner_scope(
    owner: ProductionRollbackOwner,
    requested_resources: Sequence[Mapping[str, Any] | ProductionRollbackResource],
) -> dict[str, Any]:
    requested = tuple(
        item if isinstance(item, ProductionRollbackResource)
        else ProductionRollbackResource.from_mapping(item)
        for item in requested_resources
    )
    requested_keys = [resource.key for resource in requested]
    if len(requested_keys) != len(set(requested_keys)):
        raise ProductionMaintenanceError("requested rollback scope contains duplicate resources")
    owner_keys = [resource.key for resource in owner.resources]
    if len(owner_keys) != len(set(owner_keys)):
        raise ProductionMaintenanceError("registered rollback scope contains duplicate resources")
    requested_set = set(requested_keys)
    requested_by_key = {resource.key: resource for resource in requested}
    covered_set = {
        resource.key
        for resource in owner.resources
        if resource.key in requested_set
        and resource.verified()
        and resource.source_identity == requested_by_key[resource.key].source_identity
        and resource.source_sha256 == requested_by_key[resource.key].source_sha256
        and resource.source_size == requested_by_key[resource.key].source_size
        and resource.schema_fingerprint == requested_by_key[resource.key].schema_fingerprint
    }
    missing = sorted(requested_set - covered_set)
    extra = sorted(set(owner_keys) - requested_set)
    scope_complete = bool(
        owner.verified()
        and not missing
        and not extra
        and len(requested) == 9
        and len(owner.resources) == 9
    )
    return {
        "maintenance_id": owner.maintenance_id,
        "owner_status": "VERIFIED" if owner.verified() else "NOT_VERIFIED",
        "requested_count": len(requested),
        "covered_count": len(covered_set),
        "missing": [_scope_key_text(key) for key in missing],
        "extra": [_scope_key_text(key) for key in extra],
        "scope_complete": scope_complete,
    }


def _read_registry_document(path: str | Path) -> dict[str, Any]:
    source = Path(path).resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProductionMaintenanceError(f"cannot read storage registry: {source}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("production_rollback_owners"), list):
        raise ProductionMaintenanceError("storage registry has no production rollback owners")
    return value


def _write_registry_document(path: str | Path, value: Mapping[str, Any]) -> None:
    target = Path(path).resolve()
    try:
        original_text = target.read_text(encoding="utf-8")
        original_value = json.loads(original_text)
    except (OSError, json.JSONDecodeError) as exc:
        raise ProductionMaintenanceError("cannot preserve storage registry formatting") from exc
    original_owners = original_value.get("production_rollback_owners")
    updated_owners = value.get("production_rollback_owners")
    if not isinstance(original_owners, list) or not isinstance(updated_owners, list):
        raise ProductionMaintenanceError("storage registry owner list is invalid")

    def entry_key(item: Mapping[str, Any]) -> tuple[str, ...]:
        maintenance_id = str(item.get("maintenance_id") or "")
        if maintenance_id:
            return ("scope", maintenance_id)
        return (
            "legacy",
            str(item.get("site_id") or ""),
            str(item.get("database") or ""),
        )

    original_by_key = {
        entry_key(item): item for item in original_owners if isinstance(item, Mapping)
    }
    updated_by_key = {
        entry_key(item): item for item in updated_owners if isinstance(item, Mapping)
    }
    added = [key for key in updated_by_key if key not in original_by_key]
    removed = [key for key in original_by_key if key not in updated_by_key]
    changed = [
        key
        for key in updated_by_key.keys() & original_by_key.keys()
        if updated_by_key[key] != original_by_key[key]
    ]
    if removed or len(added) > 1 or len(changed) > 1 or (added and changed):
        raise ProductionMaintenanceError("storage registry update is not a single owner append/replace")
    if not added and not changed:
        return

    marker = '"production_rollback_owners"'
    marker_position = original_text.find(marker)
    array_start = original_text.find("[", marker_position)
    decoder = json.JSONDecoder()
    _array, array_end_offset = decoder.raw_decode(original_text[array_start:])
    array_end = array_start + array_end_offset
    object_spans: list[tuple[Mapping[str, Any], int, int]] = []
    position = array_start + 1
    while position < array_end - 1:
        while position < array_end - 1 and original_text[position] in " \t\r\n,":
            position += 1
        if position >= array_end - 1 or original_text[position] == "]":
            break
        item_start = position
        item, item_end = decoder.raw_decode(original_text[item_start:])
        if not isinstance(item, Mapping):
            raise ProductionMaintenanceError("storage registry owner entry is invalid")
        object_spans.append((item, item_start, item_start + item_end))
        position = item_start + item_end

    def formatted_entry(item: Mapping[str, Any]) -> str:
        return "\n".join(
            "    " + line
            for line in json.dumps(item, ensure_ascii=False, indent=2).splitlines()
        )

    if added:
        item = updated_by_key[added[0]]
        insert_at = array_end - 1
        while insert_at > array_start and original_text[insert_at - 1] in " \t\r\n":
            insert_at -= 1
        has_previous = bool(original_text[array_start + 1 : insert_at].strip())
        insertion = (",\n" if has_previous else "\n") + formatted_entry(item) + "\n"
        updated_text = original_text[:insert_at] + insertion + original_text[insert_at:]
    else:
        key = changed[0]
        target_span = next(
            (span for item, *span in object_spans if entry_key(item) == key),
            None,
        )
        if target_span is None:
            raise ProductionMaintenanceError("storage registry owner entry disappeared")
        item_start, item_end = target_span
        line_start = original_text.rfind("\n", 0, item_start) + 1
        updated_text = (
            original_text[:line_start]
            + formatted_entry(updated_by_key[key])
            + original_text[item_end:]
        )
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    if temporary.exists():
        raise ProductionMaintenanceError("storage registry temporary file already exists")
    try:
        temporary.write_text(updated_text, encoding="utf-8")
        fsync_file(temporary)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _find_resource_set_owner(
    owners: Mapping[tuple[str, str], ProductionRollbackOwner],
    maintenance_id: str,
) -> ProductionRollbackOwner | None:
    matches = [
        owner
        for owner in owners.values()
        if owner.resources and owner.maintenance_id == maintenance_id
    ]
    if len(matches) > 1:
        raise ProductionMaintenanceError("duplicate production rollback resource-set owner")
    return matches[0] if matches else None


def discover_production_tasks_scope(
    paths: PathResolver,
    *,
    maintenance_id: str,
    source_code_revision: str,
) -> dict[str, Any]:
    """Discover the exact registered production tasks.db resource set read-only."""

    maintenance_id = _safe_scope_identifier(maintenance_id, field="maintenance_id")
    if not _is_git_head(source_code_revision):
        raise ProductionMaintenanceError("source_code_revision is invalid")
    records = SiteRegistryRepository(paths).list()
    by_id = {record.site_id: record for record in records}
    if set(by_id) != set(PRODUCTION_SITE_ALLOWLIST):
        raise ProductionMaintenanceError("SiteRegistry does not resolve the exact production site scope")
    resources: list[dict[str, Any]] = []
    for site_id in sorted(PRODUCTION_SITE_ALLOWLIST):
        site = by_id[site_id]
        expected_display = PRODUCTION_SITE_ALLOWLIST[site_id]
        if site.display_name != expected_display:
            raise ProductionMaintenanceError("SiteRegistry identity does not match production allowlist")
        database = (site.root_path / "db" / "tasks.db").resolve()
        raw_database = site.root_path / "db" / "tasks.db"
        if raw_database.is_symlink() or database.parent != (site.root_path / "db").resolve():
            raise ProductionMaintenanceError("production tasks database path is not a registered direct child")
        profile = _sqlite_immutable_profile(database)
        if not profile["valid"]:
            raise ProductionMaintenanceError(f"production tasks database is invalid: {site_id}")
        foreign_key_check = _sqlite_foreign_key_check(database)
        if foreign_key_check != "ok":
            raise ProductionMaintenanceError(f"production tasks foreign key check failed: {site_id}")
        relative = database.relative_to(paths.data_root.resolve()).as_posix()
        identity = _digest(
            {
                "site_id": site_id,
                "database_role": "tasks.db",
                "normalized_path": normalize_rollback_resource_path(relative),
                "source_sha256": profile["sha256"],
                "schema_fingerprint": profile["schema_digest"],
                "source_revision": profile["sha256"],
            }
        )
        resources.append(
            {
                "site_id": site_id,
                "site": site.display_name,
                "database_role": "tasks.db",
                "database_path": str(database),
                "source_path": relative,
                "normalized_path": normalize_rollback_resource_path(relative),
                "source_identity": identity,
                "source_sha256": str(profile["sha256"]),
                "source_revision": str(profile["sha256"]),
                "source_size": int(profile["size_bytes"]),
                "schema_fingerprint": str(profile["schema_digest"]),
                "schema_version": str(profile["schema_version"]),
                "quick_check": str(profile["quick_check"]),
                "foreign_key_check": foreign_key_check,
                "status": "PENDING_PRODUCTION_BACKUP",
            }
        )
    scope_digest = _digest(
        {
            "maintenance_type": PRODUCTION_TASK_OPERATIONAL_GC,
            "database_role": "tasks.db",
            "resources": resources,
        }
    )
    return {
        "scope_version": 1,
        "maintenance_id": maintenance_id,
        "maintenance_type": PRODUCTION_TASK_OPERATIONAL_GC,
        "database_role": "tasks.db",
        "source_data_root": str(paths.data_root.resolve()),
        "source_code_revision": source_code_revision,
        "resource_count": len(resources),
        "scope_digest": scope_digest,
        "resources": resources,
    }


def register_rollback_scope(
    registry_path: str | Path,
    scope: Mapping[str, Any],
) -> ProductionRollbackOwner:
    """Register a resource-set intent without creating or trusting backups."""

    maintenance_id = _safe_scope_identifier(scope.get("maintenance_id"), field="maintenance_id")
    if scope.get("maintenance_type") != PRODUCTION_TASK_OPERATIONAL_GC:
        raise ProductionMaintenanceError("rollback scope maintenance_type is invalid")
    resources = _scope_resources(scope)
    document = _read_registry_document(registry_path)
    existing = [
        ProductionRollbackOwner.from_mapping(item)
        for item in document["production_rollback_owners"]
        if isinstance(item, Mapping)
    ]
    if any(owner.maintenance_id == maintenance_id for owner in existing):
        raise ProductionMaintenanceError("rollback scope maintenance_id is already registered")
    scope_digest = str(scope.get("scope_digest") or "")
    if not _is_sha256(scope_digest):
        raise ProductionMaintenanceError("rollback scope digest is invalid")
    if not _is_git_head(scope.get("source_code_revision")):
        raise ProductionMaintenanceError("rollback scope source_code_revision is invalid")
    now = datetime.now(UTC).isoformat()
    owner = ProductionRollbackOwner(
        backup_set_id=f"{maintenance_id}-tasks",
        site_id="*",
        operation_id=maintenance_id,
        database="tasks.db",
        source_identity=scope_digest,
        source_sha256=scope_digest,
        source_revision=str(scope.get("source_code_revision") or ""),
        created_at=now,
        verified_at="",
        quick_check="pending",
        schema_fingerprint=scope_digest,
        rollback_required=True,
        observation_state="PENDING_PRODUCTION_BACKUP",
        superseded_by="",
        retire_state="PROTECT",
        owner="ProductionMaintenanceCapability",
        maintenance_id=maintenance_id,
        maintenance_type=PRODUCTION_TASK_OPERATIONAL_GC,
        scope_kind=PRODUCTION_ROLLBACK_SCOPE_KIND,
        resources=resources,
    )
    document["production_rollback_owners"].append(owner.as_dict())
    _write_registry_document(registry_path, document)
    return owner


def create_and_verify_rollback_scope(
    paths: PathResolver,
    registry_path: str | Path,
    scope: Mapping[str, Any],
) -> ProductionRollbackOwner:
    """Create and verify the registered resource-set using SQLite Online Backup."""

    maintenance_id = _safe_scope_identifier(scope.get("maintenance_id"), field="maintenance_id")
    requested = _scope_resources(scope)
    owners = ProductionMaintenanceCapability.load_rollback_owners(registry_path)
    owner = _find_resource_set_owner(owners, maintenance_id)
    if owner is None:
        raise ProductionMaintenanceError("rollback scope must be registered before backup creation")
    if {resource.key for resource in owner.resources} != {
        resource.key for resource in requested
    }:
        raise ProductionMaintenanceError("registered rollback scope does not match requested scope")
    registry_document = _read_registry_document(registry_path)
    updated_resources: list[ProductionRollbackResource] = []
    for resource in requested:
        site = SiteRegistryRepository(paths).get(resource.site_id)
        if site.display_name != resource.site:
            raise ProductionMaintenanceError("rollback resource SiteRegistry identity mismatch")
        source = (site.root_path / "db" / resource.database_role).resolve()
        relative = source.relative_to(paths.data_root.resolve()).as_posix()
        if normalize_rollback_resource_path(relative) != resource.normalized_path:
            raise ProductionMaintenanceError("rollback resource path identity mismatch")
        source_profile = _sqlite_immutable_profile(source)
        source_fk = _sqlite_foreign_key_check(source)
        if (
            not source_profile["valid"]
            or source_fk != "ok"
            or str(source_profile["sha256"]) != resource.source_sha256
            or int(source_profile["size_bytes"]) != resource.source_size
            or str(source_profile["schema_digest"]) != resource.schema_fingerprint
        ):
            raise ProductionMaintenanceError("rollback source changed after scope registration")
        backup_relative = (
            Path("files")
            / "backups"
            / "production-maintenance"
            / owner.backup_set_id
            / "database.sqlite"
        )
        backup = (site.root_path / backup_relative).resolve()
        if backup.exists():
            backup_profile = _sqlite_immutable_profile(backup)
        else:
            backup_profile = _sqlite_backup_readonly(source, backup)
        backup_fk = _sqlite_foreign_key_check(backup)
        if (
            not backup_profile["valid"]
            or backup_fk != "ok"
            or str(backup_profile["schema_digest"]) != resource.schema_fingerprint
            or backup_profile["table_counts"] != source_profile["table_counts"]
            or int(backup_profile["size_bytes"]) <= 0
        ):
            raise ProductionMaintenanceError("rollback backup verification failed")
        updated_resources.append(
            replace(
                resource,
                backup_relative_path=backup_relative.as_posix(),
                backup_sha256=str(backup_profile["sha256"]),
                backup_size=int(backup_profile["size_bytes"]),
                verified_at=datetime.now(UTC).isoformat(),
                status="VERIFIED",
            )
        )
    verified_at = datetime.now(UTC).isoformat()
    updated = replace(
        owner,
        verified_at=verified_at,
        quick_check="ok",
        observation_state="VERIFIED",
        resources=tuple(updated_resources),
        backup_size=sum(resource.backup_size for resource in updated_resources),
    )
    if not updated.verified():
        raise ProductionMaintenanceError("rollback owner did not reach VERIFIED")
    replaced = False
    for index, item in enumerate(registry_document["production_rollback_owners"]):
        if isinstance(item, Mapping) and str(item.get("maintenance_id") or "") == maintenance_id:
            registry_document["production_rollback_owners"][index] = updated.as_dict()
            replaced = True
            break
    if not replaced:
        raise ProductionMaintenanceError("registered rollback scope disappeared")
    _write_registry_document(registry_path, registry_document)
    return updated


def verify_registered_rollback_scope(
    registry_path: str | Path,
    scope: Mapping[str, Any],
) -> dict[str, Any]:
    owners = ProductionMaintenanceCapability.load_rollback_owners(registry_path)
    owner = _find_resource_set_owner(owners, str(scope.get("maintenance_id") or ""))
    if owner is None:
        return {
            "maintenance_id": str(scope.get("maintenance_id") or ""),
            "owner_status": "NOT_REGISTERED",
            "requested_count": len(scope.get("resources") or []),
            "covered_count": 0,
            "missing": ["OWNER_NOT_REGISTERED"],
            "extra": [],
            "scope_complete": False,
        }
    return verify_rollback_owner_scope(owner, scope.get("resources") or [])


def build_rollback_scope_manifest(
    paths: PathResolver,
    owner: ProductionRollbackOwner,
    *,
    source_code_revision: str,
) -> dict[str, Any]:
    if not owner.resources or not owner.verified():
        raise ProductionMaintenanceError("cannot manifest an unverified rollback scope")
    if not _is_git_head(source_code_revision):
        raise ProductionMaintenanceError("source_code_revision is invalid")
    resources: list[dict[str, Any]] = []
    for resource in owner.resources:
        site = SiteRegistryRepository(paths).get(resource.site_id)
        source = (paths.data_root / Path(resource.source_path)).resolve()
        backup = (site.root_path / Path(resource.backup_relative_path)).resolve()
        resources.append(
            {
                **resource.as_dict(),
                "source_relative_path": resource.source_path,
                "source_path": str(source),
                "backup_path": str(backup),
                "status": resource.status,
            }
        )
    return {
        "manifest_version": 1,
        "maintenance_id": owner.maintenance_id,
        "maintenance_type": owner.maintenance_type,
        "rollback_owner": owner.owner,
        "created_at": owner.created_at,
        "verified_at": owner.verified_at,
        "source_data_root": str(paths.data_root.resolve()),
        "source_code_revision": source_code_revision,
        "resource_count": len(resources),
        "resources": resources,
        "owner_status": "VERIFIED",
        "scope_complete": True,
        "rollback_total_bytes": sum(int(item["backup_size"]) for item in resources),
    }


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
        value = _read_registry_document(path)
        raw = value["production_rollback_owners"]
        owners: dict[tuple[str, str], ProductionRollbackOwner] = {}
        for item in raw:
            if not isinstance(item, Mapping):
                raise ProductionMaintenanceError("rollback owner entry must be an object")
            owner = ProductionRollbackOwner.from_mapping(item)
            key = (
                ("scope:" + owner.maintenance_id, owner.database)
                if owner.resources
                else (owner.site_id, owner.database)
            )
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
        scope_owners = [
            candidate
            for candidate in self._rollback_owners.values()
            if candidate.resources and candidate.resource_for(self.site_id, database) is not None
        ]
        verified_scopes = [candidate for candidate in scope_owners if candidate.verified()]
        if len(verified_scopes) > 1:
            raise ProductionMaintenanceError("ambiguous production rollback resource-set owner")
        if verified_scopes:
            return verified_scopes[0]
        if owner is None and not scope_owners:
            raise ProductionMaintenanceError("production rollback owner is not registered")
        if owner is not None and (owner.site_id != self.site_id or owner.database != database):
            raise ProductionMaintenanceError("production rollback owner identity mismatch")
        if owner is None:
            owner = scope_owners[0]
        if not owner.verified():
            raise ProductionMaintenanceError("production rollback owner is not VERIFIED")
        return owner

    def _rollback_path(
        self,
        site: Any,
        owner: ProductionRollbackOwner,
        database: str | None = None,
    ) -> Path:
        resource = (
            owner.resource_for(site.site_id, database or "")
            if owner.resources and database
            else None
        )
        if resource is not None:
            expected_relative = Path(resource.backup_relative_path)
            if (
                expected_relative.parts[:3]
                != ("files", "backups", "production-maintenance")
                or expected_relative.name != "database.sqlite"
            ):
                raise ProductionMaintenanceError("rollback owner path is not canonical")
            raw_target = site.root_path / expected_relative
            target = raw_target.resolve()
            if raw_target.is_symlink():
                raise ProductionMaintenanceError("rollback database cannot be a symlink")
            return target
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
        resource = owner.resource_for(site.site_id, manifest.database)
        rollback_path = self._rollback_path(site, owner, manifest.database)
        profile = _sqlite_immutable_profile(rollback_path)
        foreign_key_check = _sqlite_foreign_key_check(rollback_path)
        source_identity = resource.source_identity if resource is not None else owner.source_identity
        source_sha256 = resource.source_sha256 if resource is not None else owner.source_sha256
        source_revision = resource.source_revision if resource is not None else owner.source_revision
        schema_fingerprint = (
            resource.schema_fingerprint if resource is not None else owner.schema_fingerprint
        )
        backup_sha256 = resource.backup_sha256 if resource is not None else owner.backup_sha256
        backup_size = resource.backup_size if resource is not None else owner.backup_size
        if (
            not profile["valid"]
            or foreign_key_check != "ok"
            or (
                resource is None
                and source_identity != manifest.database_identity
            )
            or source_sha256 != manifest.source_sha256
            or source_revision != manifest.source_revision
            or schema_fingerprint != manifest.schema_fingerprint
            or backup_sha256 != str(profile["sha256"])
            or backup_size != int(profile["size_bytes"])
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
        return validate_production_gate_evidence(
            gates,
            binding=self.evidence_binding,
        )

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
                "production_preflight",
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
                if rollback_path != self._rollback_path(site, owner, manifest.database):
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
                # A validated production replacement is safe for the normal
                # startup recovery scanner to observe while the external
                # restart/functional callbacks run.  The capability still
                # rolls it back if either callback fails.
                journal.update("production_switched", switched=True)
                if not restart_verifier():
                    raise ProductionMaintenanceError("restart verification failed")
                journal.update("production_switched", restart_verified=True)
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
                    or rollback_path != self._rollback_path(site, owner, database)
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
    "PRODUCTION_TASK_OPERATIONAL_GC",
    "PRODUCTION_ROLLBACK_SCOPE_KIND",
    "ProductionEvidenceBinding",
    "ProductionMaintenanceCapability",
    "ProductionMaintenanceError",
    "ProductionManifest",
    "ProductionRollbackResource",
    "ProductionRollbackOwner",
    "build_rollback_scope_manifest",
    "build_exact_manifest",
    "create_and_verify_rollback_scope",
    "discover_production_tasks_scope",
    "normalize_rollback_resource_path",
    "register_rollback_scope",
    "verify_registered_rollback_scope",
    "verify_rollback_owner_scope",
    "write_exact_manifest",
]
