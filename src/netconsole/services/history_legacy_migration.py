"""Explicit, resumable COPY-only migration for legacy device history tables."""

from __future__ import annotations

import hashlib
import json
import random
import sqlite3
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from netconsole.core.paths import PathResolver
from netconsole.repositories.history_legacy_migration_repository import (
    HistoryLegacyMigrationRepository,
    LegacyHistorySourceRepository,
    MigrationRecord,
    TableCheckpoint,
)
from netconsole.services.database_upgrade.coordinator import (
    SITE_DATABASE_MAINTENANCE_CLASS,
    database_maintenance_lock,
    site_database_maintenance_key,
)
from netconsole.services.database_footprint_maintenance import (
    DEVELOPMENT_ROOT,
    assert_development_path,
)
from netconsole.services.history_store import HistoryStore


MAINTENANCE_EXCLUSIVE_CLASS = SITE_DATABASE_MAINTENANCE_CLASS
INVENTORY_FILE_NAME = "LEGACY_HISTORY_INVENTORY.json"
MIGRATION_REPORT_FILE_NAME = "LEGACY_HISTORY_MIGRATION_REPORT.json"
DELETE_PLAN_FILE_NAME = "LEGACY_HISTORY_DELETE_PLAN.json"


@dataclass(frozen=True)
class LegacyTableSpec:
    entity_type: str
    entity_fields: tuple[str, ...]
    timestamp_column: str = "collected_at"
    canonical_source: str = ""


SUPPORTED_SPECS = {
    "device_facts_history": LegacyTableSpec("device_fact", ("device_uuid",)),
    "device_interfaces_history": LegacyTableSpec(
        "device_interface", ("device_uuid", "interface_name")
    ),
    "device_optical_modules_history": LegacyTableSpec(
        "device_optical", ("device_uuid", "interface_name")
    ),
    "device_lldp_neighbors_history": LegacyTableSpec(
        "device_lldp", ("device_uuid", "local_interface")
    ),
    "ac_fit_ap_resource_history": LegacyTableSpec(
        "fit_ap_resource", ("ac_device_uuid", "ap_uuid")
    ),
    "ac_fit_ap_radio_history": LegacyTableSpec("fit_ap_radio", ("ap_uuid", "rid")),
    "ac_fit_ap_lldp_history": LegacyTableSpec("fit_ap_lldp", ("ap_uuid",)),
    "ac_fit_ap_optical_history": LegacyTableSpec("fit_ap_optical", ("ap_uuid",)),
    "ac_fit_ap_unauthenticated_history": LegacyTableSpec(
        "fit_ap_unauthenticated", ("ac_device_uuid",)
    ),
    "ac_station_online_summary_history": LegacyTableSpec(
        "station_online_summary", ("site_name",)
    ),
    "ap_lldp_history": LegacyTableSpec(
        "fit_ap_lldp", ("ap_uuid",), canonical_source="ac_fit_ap_lldp_history"
    ),
    "ap_optical_history": LegacyTableSpec(
        "fit_ap_optical", ("ap_uuid",), canonical_source="ac_fit_ap_optical_history"
    ),
}
UNSUPPORTED_TABLES: dict[str, str] = {}
SOURCE_ORDER = tuple(
    name for name in SUPPORTED_SPECS if not SUPPORTED_SPECS[name].canonical_source
) + tuple(name for name in SUPPORTED_SPECS if SUPPORTED_SPECS[name].canonical_source)
_AP_IDENTITY_AUTHORITY_PRESERVING_TABLES = {
    "ac_fit_ap_lldp_history",
    "ac_fit_ap_radio_history",
}


@dataclass(frozen=True)
class InventoryEntry:
    table_name: str
    classification: str
    history_entity_type: str
    timestamp_column: str
    identity_key: list[str]
    payload_columns: list[str]
    nullable_columns: list[str]
    primary_key: list[str]
    indexes: list[dict[str, Any]]
    legacy_version: str
    target_shard_schema: int
    row_count: int | None
    min_timestamp: str
    max_timestamp: str
    min_source_key: int
    max_source_key: int
    canonical_source: str
    reason: str
    contract_status: str = ""


class HistoryLegacyMigrationService:
    """Runs a low-priority bounded migration only when explicitly invoked."""

    def __init__(
        self,
        paths: PathResolver,
        *,
        site_id: str,
        source_database: Path,
        history_root: Path,
        diagnostics_dir: Path,
        immutable_source: bool = False,
        isolated_rehearsal: bool = False,
        clock: Callable[[], datetime] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.paths = paths
        self.site_id = str(site_id)
        self.source_database = Path(source_database).resolve()
        self.history_root = Path(history_root).resolve()
        self.diagnostics_dir = Path(diagnostics_dir).resolve()
        self.isolated_rehearsal = bool(isolated_rehearsal)
        if self.isolated_rehearsal:
            if not immutable_source:
                raise ValueError("isolated rehearsal requires immutable_source")
            for path in (
                self.paths.data_root,
                self.source_database,
                self.history_root,
                self.diagnostics_dir,
            ):
                assert_development_path(path)
        self.source = LegacyHistorySourceRepository(
            self.source_database, immutable=immutable_source
        )
        self.store = HistoryStore(
            self.source_database,
            site_id=self.site_id,
            history_root=self.history_root,
            clock=clock,
        )
        self.journal = HistoryLegacyMigrationRepository(self.history_root / "catalog.db")
        self._clock = clock
        self._sleep = sleep or time.sleep
        self._monotonic = time.monotonic

    def inventory(self, *, exact_counts: bool = True, write_report: bool = True) -> dict[str, Any]:
        schema_version = self.source.schema_version()
        entries: list[InventoryEntry] = []
        for table in self.source.history_tables():
            columns = self.source.table_columns(table)
            names = {str(column["name"]) for column in columns}
            spec = SUPPORTED_SPECS.get(table)
            reason = ""
            if table in UNSUPPORTED_TABLES:
                classification = "UNSUPPORTED"
                reason = UNSUPPORTED_TABLES[table]
            elif spec is None:
                classification = "UNKNOWN_SCHEMA"
                reason = "unregistered legacy history schema"
            else:
                required = {"id", spec.timestamp_column, *spec.entity_fields}
                if required.issubset(names) and any(
                    str(column["name"]) == "id" and int(column["pk"]) == 1
                    for column in columns
                ):
                    classification = "SUPPORTED"
                else:
                    classification = "UNKNOWN_SCHEMA"
                    reason = "required primary key, timestamp, or identity column is missing"
            contract_status = {
                "SUPPORTED": "SUPPORTED_CANONICAL"
                if not (spec and spec.canonical_source)
                else "SUPPORTED_PROJECTION",
                "UNSUPPORTED": "UNSUPPORTED_REQUIRED_SOURCE",
                "UNKNOWN_SCHEMA": "PROTECTED_UNKNOWN",
            }[classification]
            timestamp_column = spec.timestamp_column if spec else (
                "collected_at" if "collected_at" in names else "created_at"
            )
            profile: dict[str, Any] = {}
            if exact_counts and timestamp_column in names and "id" in names:
                profile = self.source.table_profile(table, timestamp_column)
            elif "id" in names:
                minimum, maximum = self.source.id_range(table)
                profile = {"min_id": minimum, "max_id": maximum}
            entries.append(
                InventoryEntry(
                    table_name=table,
                    classification=classification,
                    history_entity_type=spec.entity_type if spec else "",
                    timestamp_column=timestamp_column,
                    identity_key=list(spec.entity_fields if spec else ()),
                    payload_columns=[str(column["name"]) for column in columns],
                    nullable_columns=[
                        str(column["name"])
                        for column in columns
                        if not int(column["notnull"]) and not int(column["pk"])
                    ],
                    primary_key=[
                        str(column["name"]) for column in columns if int(column["pk"])
                    ],
                    indexes=self.source.table_indexes(table),
                    legacy_version=schema_version,
                    target_shard_schema=1,
                    row_count=int(profile["rows"]) if profile.get("rows") is not None else None,
                    min_timestamp=str(profile.get("min_time") or ""),
                    max_timestamp=str(profile.get("max_time") or ""),
                    min_source_key=int(profile.get("min_id") or 0),
                    max_source_key=int(profile.get("max_id") or 0),
                    canonical_source=spec.canonical_source if spec else "",
                    reason=reason,
                    contract_status=contract_status,
                )
            )
        result = {
            "generated_at": self._now(),
            "site_id": self.site_id,
            "source_database_name": self.source_database.name,
            "source_schema_version": schema_version,
            "physical": self.source.physical_profile(),
            "classification_counts": {
                name: sum(entry.classification == name for entry in entries)
                for name in ("SUPPORTED", "UNSUPPORTED", "UNKNOWN_SCHEMA")
            },
            "contract_status_counts": {
                name: sum(entry.contract_status == name for entry in entries)
                for name in (
                    "SUPPORTED_CANONICAL",
                    "SUPPORTED_PROJECTION",
                    "UNSUPPORTED_REQUIRED_SOURCE",
                    "PROTECTED_UNKNOWN",
                )
            },
            "tables": [asdict(entry) for entry in entries],
        }
        if write_report:
            self._write_json(INVENTORY_FILE_NAME, result)
        return result

    def source_database_identity(self, inventory: dict[str, Any] | None = None) -> str:
        profile = inventory or self.inventory(exact_counts=False, write_report=False)
        anchors: list[dict[str, Any]] = []
        by_name = {str(item["table_name"]): item for item in profile["tables"]}
        for table in sorted(by_name):
            item = by_name[table]
            anchors.append(
                {
                    "table": table,
                    "classification": item["classification"],
                    "columns": item["payload_columns"],
                    "min_source_key": item["min_source_key"],
                    "max_source_key": item["max_source_key"],
                    "anchor_rows": self.source.anchor_rows(table)
                    if "id" in item["payload_columns"]
                    else [],
                }
            )
        stable = {
            "site_id": self.site_id,
            "source_schema_version": profile["source_schema_version"],
            "page_size": profile["physical"]["page_size"],
            "anchors": anchors,
        }
        encoded = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def start(
        self,
        *,
        migration_id: str | None = None,
        chunk_rows: int = 250,
        max_elapsed_seconds: float = 2.0,
        slow_storage_delay_seconds: float = 0.0,
        unattended_active: Callable[[], bool] | None = None,
        after_target_commit: Callable[[str, int], None] | None = None,
        after_checkpoint: Callable[[str, int], None] | None = None,
    ) -> dict[str, Any]:
        maximum_chunk_rows = 5000 if self.isolated_rehearsal else 500
        safe_chunk_rows = max(1, min(int(chunk_rows), maximum_chunk_rows))
        inventory = self.inventory(exact_counts=True)
        if inventory["classification_counts"]["UNKNOWN_SCHEMA"]:
            return self._not_ready("unknown legacy history schema", inventory=inventory)
        source_identity = self.source_database_identity(inventory)
        identifier = migration_id or f"legacy-history-{source_identity[:20]}"
        now = self._now()
        record = self.journal.create_or_load(
            migration_id=identifier,
            source_database_identity=source_identity,
            source_schema_version=str(inventory["source_schema_version"]),
            site_id=self.site_id,
            chunk_rows=safe_chunk_rows,
            now=now,
        )
        self._ensure_table_checkpoints(record, inventory)
        self.journal.set_requested_state(identifier, "RUNNING", now=now)
        lock_key = site_database_maintenance_key(self.site_id)
        with database_maintenance_lock(self.paths, lock_key):
            result = self._run(
                identifier,
                inventory=inventory,
                chunk_rows=safe_chunk_rows,
                max_elapsed_seconds=max(0.0, float(max_elapsed_seconds)),
                slow_storage_delay_seconds=max(0.0, float(slow_storage_delay_seconds)),
                unattended_active=unattended_active or (lambda: False),
                after_target_commit=after_target_commit,
                after_checkpoint=after_checkpoint,
            )
        self._write_json(MIGRATION_REPORT_FILE_NAME, result)
        return result

    def resume(
        self,
        migration_id: str,
        *,
        chunk_rows: int | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        record = self.journal.get(migration_id)
        if record is None:
            raise ValueError(f"unknown migration: {migration_id}")
        return self.start(
            migration_id=migration_id,
            chunk_rows=record.chunk_rows if chunk_rows is None else chunk_rows,
            **kwargs,
        )

    def pause(self, migration_id: str) -> dict[str, Any]:
        self.journal.set_requested_state(migration_id, "PAUSED", now=self._now())
        return self.status(migration_id)

    def status(self, migration_id: str) -> dict[str, Any]:
        record = self.journal.get(migration_id)
        if record is None:
            return {"migration_id": migration_id, "status": "NOT_FOUND"}
        return {
            "migration": asdict(record),
            "tables": [asdict(item) for item in self.journal.list_table_checkpoints(migration_id)],
            "ranges": self.journal.range_records(migration_id),
            "destructive_operations": {"DELETE": "NO", "DROP": "NO", "VACUUM": "NO"},
        }

    def cutover(
        self,
        migration_id: str,
        source_table: str,
        *,
        expected_revision: int,
        reason: str,
    ) -> dict[str, Any]:
        """Switch one verified source table to shard query authority without deleting it."""

        lock_key = site_database_maintenance_key(self.site_id)
        with database_maintenance_lock(self.paths, lock_key):
            self._assert_current_source(migration_id)
            checkpoint = self._required_table(migration_id, source_table)
            if checkpoint.cutover_revision != int(expected_revision):
                raise ValueError("cutover revision mismatch")
            spec = SUPPORTED_SPECS.get(source_table)
            if spec is None:
                raise ValueError(f"unsupported legacy history source: {source_table}")
            if spec.canonical_source:
                canonical = self._required_table(migration_id, spec.canonical_source)
                if canonical.authority_state not in {
                    "SHARD_AUTHORITY",
                    "SOURCE_DELETE_ELIGIBLE",
                }:
                    raise ValueError(
                        "projection cutover requires canonical source shard authority"
                    )
            if checkpoint.status != "VERIFIED" or checkpoint.error_count:
                raise ValueError("source table copy verification is incomplete")
            if checkpoint.authority_state == "LEGACY_AUTHORITY":
                checkpoint = self.journal.transition_authority(
                    migration_id,
                    source_table,
                    to_state="SHARD_VERIFIED",
                    expected_revision=expected_revision,
                    reason=f"{reason}; restore verified shard candidate",
                    now=self._now(),
                )
            updated = self.journal.transition_authority(
                migration_id,
                source_table,
                to_state="SHARD_AUTHORITY",
                expected_revision=checkpoint.cutover_revision,
                reason=reason,
                now=self._now(),
            )
        return {
            "migration_id": migration_id,
            "table": asdict(updated),
            "source_preserved": True,
            "destructive_operations": {"DELETE": "NO", "DROP": "NO", "VACUUM": "NO"},
        }

    def rollback_cutover(
        self,
        migration_id: str,
        source_table: str,
        *,
        expected_revision: int,
        reason: str,
    ) -> dict[str, Any]:
        """Return one table to legacy query authority while its source still exists."""

        lock_key = site_database_maintenance_key(self.site_id)
        with database_maintenance_lock(self.paths, lock_key):
            self._assert_current_source(migration_id)
            updated = self.journal.transition_authority(
                migration_id,
                source_table,
                to_state="LEGACY_AUTHORITY",
                expected_revision=expected_revision,
                reason=reason,
                now=self._now(),
            )
        return {
            "migration_id": migration_id,
            "table": asdict(updated),
            "source_preserved": True,
            "destructive_operations": {"DELETE": "NO", "DROP": "NO", "VACUUM": "NO"},
        }

    def evaluate_delete_eligibility(
        self,
        migration_id: str,
        source_table: str,
        *,
        expected_revision: int,
        observation: dict[str, Any],
        reason: str,
    ) -> dict[str, Any]:
        """Evaluate the observation gate and mark one source as plan-eligible."""

        lock_key = site_database_maintenance_key(self.site_id)
        with database_maintenance_lock(self.paths, lock_key):
            self._assert_current_source(migration_id)
            checkpoint = self._required_table(migration_id, source_table)
            if checkpoint.authority_state != "SHARD_AUTHORITY":
                raise ValueError("source table is not under shard authority")
            if checkpoint.cutover_revision != int(expected_revision):
                raise ValueError("cutover revision mismatch")
            required = {
                "query_validation": True,
                "consumer_validation": True,
                "integrity_mismatch": False,
            }
            for field, expected in required.items():
                if observation.get(field) is not expected:
                    raise ValueError(f"observation gate failed: {field}")
            table_plan = self._build_delete_plan_table(checkpoint)
            if not bool(table_plan["eligibility"]):
                raise ValueError(str(table_plan["reason"]))
            observation_digest = self._stable_digest(observation)
            updated = self.journal.transition_authority(
                migration_id,
                source_table,
                to_state="SOURCE_DELETE_ELIGIBLE",
                expected_revision=expected_revision,
                reason=f"{reason}; observation={observation_digest}",
                now=self._now(),
            )
        return {
            "migration_id": migration_id,
            "table": asdict(updated),
            "observation_digest": observation_digest,
            "source_preserved": True,
            "delete_executed": False,
        }

    def preview_delete_plan(
        self,
        migration_id: str,
        *,
        source_tables: list[str] | None = None,
    ) -> dict[str, Any]:
        """Generate and persist a deterministic proof plan; never execute DELETE."""

        lock_key = site_database_maintenance_key(self.site_id)
        with database_maintenance_lock(self.paths, lock_key):
            return self._preview_delete_plan_locked(
                migration_id,
                source_tables=source_tables,
            )

    def _preview_delete_plan_locked(
        self,
        migration_id: str,
        *,
        source_tables: list[str] | None,
    ) -> dict[str, Any]:
        record = self._assert_current_source(migration_id)
        checkpoints = self.journal.list_table_checkpoints(migration_id)
        requested = {
            str(value).strip() for value in (source_tables or []) if str(value).strip()
        }
        if requested:
            missing = requested - {item.source_table for item in checkpoints}
            if missing:
                raise ValueError(f"unknown migration source tables: {sorted(missing)}")
            checkpoints = [
                item for item in checkpoints if item.source_table in requested
            ]
        eligible = [
            item
            for item in checkpoints
            if item.authority_state == "SOURCE_DELETE_ELIGIBLE"
        ]
        if not eligible:
            raise ValueError("no source table is delete-plan eligible")
        inventory = self.inventory(exact_counts=True, write_report=False)
        excluded = [
            {
                "source_table": str(item["table_name"]),
                "classification": str(item["classification"]),
                "row_count": item.get("row_count"),
                "reason": str(item.get("reason") or "not supported"),
                "eligibility": False,
            }
            for item in inventory["tables"]
            if item["classification"] != "SUPPORTED"
        ]
        tables = [self._build_delete_plan_table(item) for item in eligible]
        semantic = {
            "format": "netconsole-legacy-history-delete-plan",
            "version": 1,
            "migration_id": migration_id,
            "site_id": self.site_id,
            "source_database_identity": record.source_database_identity,
            "tables": tables,
            "excluded_sources": excluded,
            "source_delete_executor": "DEVELOPMENT_ROOT_ONLY_V1",
        }
        plan_digest = self._stable_digest(semantic)
        plan = {
            **semantic,
            "generated_at": self._now(),
            "plan_digest": plan_digest,
            "source_delete_executed": False,
        }
        for checkpoint in eligible:
            self.journal.set_delete_plan_digest(
                migration_id,
                checkpoint.source_table,
                expected_revision=checkpoint.cutover_revision,
                digest=plan_digest,
                now=self._now(),
            )
        self._write_json(DELETE_PLAN_FILE_NAME, plan)
        return plan

    def validate_delete_plan(self, plan: dict[str, Any]) -> dict[str, Any]:
        """Revalidate a preview against current source/catalog state without deleting."""

        lock_key = site_database_maintenance_key(self.site_id)
        with database_maintenance_lock(self.paths, lock_key):
            return self._validate_delete_plan_locked(plan)

    def _validate_delete_plan_locked(self, plan: dict[str, Any]) -> dict[str, Any]:
        if str(plan.get("format") or "") != "netconsole-legacy-history-delete-plan":
            raise ValueError("invalid legacy history delete plan format")
        semantic = {
            key: plan[key]
            for key in (
                "format",
                "version",
                "migration_id",
                "site_id",
                "source_database_identity",
                "tables",
                "excluded_sources",
                "source_delete_executor",
            )
        }
        digest = self._stable_digest(semantic)
        if digest != str(plan.get("plan_digest") or ""):
            raise ValueError("delete plan digest mismatch")
        migration_id = str(plan["migration_id"])
        record = self._assert_current_source(migration_id)
        if record.source_database_identity != str(plan["source_database_identity"]):
            raise ValueError("delete plan source identity mismatch")
        current_tables: list[dict[str, Any]] = []
        for item in plan.get("tables", []):
            if not isinstance(item, dict):
                raise ValueError("invalid delete plan table")
            checkpoint = self._required_table(
                migration_id, str(item.get("source_table") or "")
            )
            if checkpoint.authority_state != "SOURCE_DELETE_ELIGIBLE":
                raise ValueError("delete plan authority is stale")
            if checkpoint.cutover_revision != int(item.get("cutover_revision") or -1):
                raise ValueError("delete plan cutover revision mismatch")
            if checkpoint.delete_plan_digest != digest:
                raise ValueError("delete plan catalog digest mismatch")
            current_tables.append(self._build_delete_plan_table(checkpoint))
        if current_tables != plan.get("tables"):
            raise ValueError("delete plan source range proof is stale")
        return {
            "valid": True,
            "plan_digest": digest,
            "source_delete_executed": False,
        }

    def delete_source(
        self,
        plan: dict[str, Any],
        *,
        expected_plan_digest: str,
        expected_source_identity: str,
        expected_revision: int | None = None,
        expected_table_revisions: dict[str, int] | None = None,
        batch_rows: int = 500,
        apply: bool = False,
        allow_development_root_only: bool = False,
        development_root: Path = DEVELOPMENT_ROOT,
    ) -> dict[str, Any]:
        """Delete only exact verified source keys from an isolated development copy."""

        if not apply or not allow_development_root_only:
            raise ValueError(
                "source deletion requires --apply and --allow-development-root-only"
            )
        if self.source.immutable:
            raise ValueError("immutable source cannot be deleted")
        assert_development_path(
            self.source_database, development_root=development_root
        )
        safe_batch = int(batch_rows)
        if safe_batch not in {250, 500, 1000}:
            raise ValueError("source delete batch_rows must be 250, 500, or 1000")
        supplied_digest = str(expected_plan_digest or "").strip().lower()
        supplied_identity = str(expected_source_identity or "").strip().lower()
        if supplied_digest != str(plan.get("plan_digest") or "").strip().lower():
            raise ValueError("expected delete plan digest mismatch")
        if supplied_identity != str(
            plan.get("source_database_identity") or ""
        ).strip().lower():
            raise ValueError("expected source identity mismatch")

        lock_key = site_database_maintenance_key(self.site_id)
        with database_maintenance_lock(self.paths, lock_key):
            validation = self._validate_delete_plan_locked(plan)
            if validation["plan_digest"] != supplied_digest:
                raise ValueError("validated delete plan digest mismatch")
            tables = list(plan.get("tables") or [])
            if not tables:
                raise ValueError("delete plan has no tables")
            revisions = {
                str(item.get("source_table") or ""): int(
                    item.get("cutover_revision") or -1
                )
                for item in tables
            }
            if expected_table_revisions is not None:
                normalized = {
                    str(table): int(revision)
                    for table, revision in expected_table_revisions.items()
                }
                if normalized != revisions:
                    raise ValueError("expected table revisions mismatch")
            elif expected_revision is None or any(
                revision != int(expected_revision) for revision in revisions.values()
            ):
                raise ValueError("expected cutover revision mismatch")
            for item in tables:
                if not bool(item.get("eligibility")):
                    raise ValueError("delete plan contains an ineligible table")
            result = self._delete_source_locked(
                str(plan["migration_id"]),
                tables,
                plan_digest=supplied_digest,
                expected_revisions=revisions,
                batch_rows=safe_batch,
            )
        return {
            "migration_id": str(plan["migration_id"]),
            "plan_digest": supplied_digest,
            "source_database_identity": supplied_identity,
            "batch_rows": safe_batch,
            "source_delete_executed": True,
            **result,
        }

    def _delete_source_locked(
        self,
        migration_id: str,
        tables: list[dict[str, Any]],
        *,
        plan_digest: str,
        expected_revisions: dict[str, int],
        batch_rows: int,
    ) -> dict[str, Any]:
        deleted_total = 0
        table_results: list[dict[str, Any]] = []
        connection = sqlite3.connect(self.source_database, timeout=60)
        try:
            connection.execute("PRAGMA busy_timeout = 60000")
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("BEGIN IMMEDIATE")
            self._assert_current_source(migration_id)
            for item in tables:
                table = str(item.get("source_table") or "")
                if table not in SUPPORTED_SPECS or not table.replace("_", "").isalnum():
                    raise ValueError(f"invalid source delete table: {table}")
                checkpoint = self._required_table(migration_id, table)
                expected_revision = int(expected_revisions[table])
                if (
                    checkpoint.authority_state != "SOURCE_DELETE_ELIGIBLE"
                    or checkpoint.cutover_revision != expected_revision
                    or checkpoint.delete_plan_digest != plan_digest
                ):
                    raise ValueError("source delete authority, revision, or digest is stale")
                before = int(
                    connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                )
                expected = int(item.get("row_count") or 0)
                deleted = 0
                batches = 0
                identity_state = None
                if (
                    table in _AP_IDENTITY_AUTHORITY_PRESERVING_TABLES
                    and connection.execute(
                        "SELECT 1 FROM sqlite_master "
                        "WHERE type = 'table' AND name = 'ap_identity_source_state'"
                    ).fetchone()
                ):
                    identity_state = connection.execute(
                        "SELECT revision, updated_at "
                        "FROM ap_identity_source_state WHERE site_id = 'current'"
                    ).fetchone()
                for range_item in item.get("ranges", []):
                    for key_range in range_item.get("source_key_ranges", []):
                        start = int(key_range.get("start") or 0)
                        end = int(key_range.get("end") or 0)
                        if start <= 0 or end < start:
                            raise ValueError("invalid source delete key range")
                        cursor_key = start - 1
                        while True:
                            rows = connection.execute(
                                f'SELECT id FROM "{table}" '
                                "WHERE id BETWEEN ? AND ? AND id > ? "
                                "ORDER BY id LIMIT ?",
                                (start, end, cursor_key, batch_rows),
                            ).fetchall()
                            if not rows:
                                break
                            keys = [int(row[0]) for row in rows]
                            cursor = connection.execute(
                                f'DELETE FROM "{table}" WHERE id IN '
                                f"({','.join('?' for _ in keys)})",
                                keys,
                            )
                            if int(cursor.rowcount or 0) != len(keys):
                                raise RuntimeError("source delete batch count mismatch")
                            deleted += len(keys)
                            batches += 1
                            cursor_key = keys[-1]
                if identity_state is not None:
                    connection.execute(
                        "UPDATE ap_identity_source_state "
                        "SET revision = ?, updated_at = ? "
                        "WHERE site_id = 'current'",
                        (identity_state[0], identity_state[1]),
                    )
                after = int(
                    connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                )
                if deleted != expected or before - after != expected:
                    raise RuntimeError("source delete exact row count mismatch")
                remaining = 0
                for range_item in item.get("ranges", []):
                    for key_range in range_item.get("source_key_ranges", []):
                        remaining += int(
                            connection.execute(
                                f'SELECT COUNT(*) FROM "{table}" WHERE id BETWEEN ? AND ?',
                                (
                                    int(key_range.get("start") or 0),
                                    int(key_range.get("end") or 0),
                                ),
                            ).fetchone()[0]
                        )
                if remaining:
                    raise RuntimeError("planned source keys remain after delete")
                table_results.append(
                    {
                        "source_table": table,
                        "rows_before": before,
                        "deleted_rows": deleted,
                        "rows_after": after,
                        "batches": batches,
                        "expected_revision": expected_revision,
                    }
                )
                deleted_total += deleted
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        finalized_results: list[dict[str, Any]] = []
        for item in table_results:
            updated = self.journal.transition_authority(
                migration_id,
                str(item["source_table"]),
                to_state="SOURCE_DELETED",
                expected_revision=int(item["expected_revision"]),
                reason=f"exact plan {plan_digest} applied under development root",
                now=self._now(),
            )
            finalized_results.append(
                {
                    key: value
                    for key, value in item.items()
                    if key != "expected_revision"
                }
                | {
                    "authority_state": updated.authority_state,
                    "cutover_revision": updated.cutover_revision,
                }
            )
        return {"deleted_rows": deleted_total, "tables": finalized_results}

    def _run(
        self,
        migration_id: str,
        *,
        inventory: dict[str, Any],
        chunk_rows: int,
        max_elapsed_seconds: float,
        slow_storage_delay_seconds: float,
        unattended_active: Callable[[], bool],
        after_target_commit: Callable[[str, int], None] | None,
        after_checkpoint: Callable[[str, int], None] | None,
    ) -> dict[str, Any]:
        target_commits = (
            self.journal.get(migration_id) or MigrationRecord("", "", "", "", "", "", 0)
        ).target_commits
        checkpoint_commits = (
            self.journal.get(migration_id) or MigrationRecord("", "", "", "", "", "", 0)
        ).checkpoint_commits
        invocation_started = self._monotonic()
        budget_exceeded = False
        inventory_by_name = {
            str(item["table_name"]): item for item in inventory["tables"]
        }
        try:
            for table in SOURCE_ORDER:
                item = inventory_by_name.get(table)
                if not item or item["classification"] != "SUPPORTED":
                    continue
                while True:
                    record = self.journal.get(migration_id)
                    if record is None:
                        raise RuntimeError("migration journal disappeared")
                    if record.requested_state != "RUNNING" or unattended_active():
                        self.journal.set_requested_state(
                            migration_id, "PAUSED", now=self._now()
                        )
                        return self._result(
                            migration_id, inventory, budget_exceeded=False
                        )
                    checkpoint = self.journal.table_checkpoint(migration_id, table)
                    assert checkpoint is not None
                    rows = self.source.fetch_after(
                        table, checkpoint.last_source_key, chunk_rows
                    )
                    if not rows:
                        final_status = (
                            "FAILED" if checkpoint.error_count else "VERIFIED"
                        )
                        final_checkpoint = TableCheckpoint(
                            **{
                                **asdict(checkpoint),
                                "status": final_status,
                                "updated_at": self._now(),
                            }
                        )
                        self.journal.upsert_table_checkpoint(final_checkpoint)
                        if (
                            final_status == "VERIFIED"
                            and final_checkpoint.authority_state == "LEGACY_AUTHORITY"
                        ):
                            self.journal.transition_authority(
                                migration_id,
                                table,
                                to_state="SHARD_VERIFIED",
                                expected_revision=final_checkpoint.cutover_revision,
                                reason="COPY and digest verification completed",
                                now=self._now(),
                            )
                        break
                    started = self._monotonic()
                    started_at = self._now()
                    self.journal.upsert_table_checkpoint(
                        TableCheckpoint(
                            **{
                                **asdict(checkpoint),
                                "status": "COPYING",
                                "updated_at": started_at,
                            }
                        )
                    )
                    valid_events: list[dict[str, Any]] = []
                    invalid: list[dict[str, Any]] = []
                    canonical_source = SUPPORTED_SPECS[table].canonical_source
                    matched_rows = (
                        self.source.projection_matches(table, rows)
                        if canonical_source
                        else rows
                    )
                    for row, matched_row in zip(rows, matched_rows, strict=True):
                        try:
                            if matched_row is None:
                                raise ValueError(
                                    "projection row has no authoritative source match"
                                )
                            valid_events.append(
                                self.store.legacy_migration_event(
                                    canonical_source or table, matched_row
                                )
                            )
                        except (KeyError, TypeError, ValueError) as exc:
                            invalid.append(
                                {
                                    "source_table": table,
                                    "source_key": int(row.get("id") or 0),
                                    "reason": self._error_code(exc),
                                }
                            )
                    inserted = 0
                    verified = 0
                    inserted_by_month: dict[str, int] = {}
                    if valid_events and not canonical_source:
                        event_groups: dict[str, list[dict[str, Any]]] = {}
                        for event in valid_events:
                            event_groups.setdefault(
                                str(event["collected_at"])[:7], []
                            ).append(event)
                        for month, month_events in event_groups.items():
                            month_inserted, month_verified = (
                                self.store.copy_legacy_migration_events(month_events)
                            )
                            inserted_by_month[month] = month_inserted
                            inserted += month_inserted
                            verified += month_verified
                            target_commits += 1
                    if slow_storage_delay_seconds:
                        self._sleep(slow_storage_delay_seconds)
                    if after_target_commit:
                        after_target_commit(table, int(rows[-1]["id"]))
                    verifying = TableCheckpoint(
                        **{
                            **asdict(checkpoint),
                            "status": "VERIFYING",
                            "updated_at": self._now(),
                        }
                    )
                    self.journal.upsert_table_checkpoint(verifying)
                    target_rows = self.store.read_legacy_migration_events(valid_events)
                    self._verify_chunk(migration_id, table, valid_events, target_rows)
                    if canonical_source:
                        verified = len(valid_events)
                    elapsed_ms = int((self._monotonic() - started) * 1000)
                    budget_exceeded = bool(
                        max_elapsed_seconds
                        and self._monotonic() - invocation_started
                        >= max_elapsed_seconds
                    )
                    self._record_ranges(
                        migration_id,
                        table,
                        rows,
                        valid_events,
                        target_rows,
                        inserted_by_month=inserted_by_month,
                        invalid_count=len(invalid),
                        started_at=started_at,
                        elapsed_ms=elapsed_ms,
                        budget_exceeded=budget_exceeded,
                    )
                    if invalid:
                        self._append_invalid(invalid)
                    updated = TableCheckpoint(
                        migration_id=migration_id,
                        source_table=table,
                        source_range=f"{item['min_source_key']}..{item['max_source_key']}",
                        last_source_key=int(rows[-1]["id"]),
                        copied_count=checkpoint.copied_count + inserted,
                        verified_count=checkpoint.verified_count + verified,
                        duplicate_count=checkpoint.duplicate_count
                        + max(0, verified - inserted),
                        error_count=checkpoint.error_count + len(invalid),
                        status="FAILED" if invalid else "COPYING",
                        updated_at=self._now(),
                        last_error="INVALID_OR_UNSUPPORTED_ROW" if invalid else "",
                    )
                    self.journal.upsert_table_checkpoint(updated)
                    checkpoint_commits += 1
                    self._update_totals(
                        migration_id,
                        "COPYING",
                        target_commits=target_commits,
                        checkpoint_commits=checkpoint_commits,
                    )
                    if after_checkpoint:
                        after_checkpoint(table, updated.last_source_key)
                    if budget_exceeded:
                        return self._result(
                            migration_id, inventory, budget_exceeded=True
                        )
            tables = self.journal.list_table_checkpoints(migration_id)
            status = (
                "FAILED"
                if any(item.status == "FAILED" for item in tables)
                else "VERIFIED"
            )
            self._update_totals(
                migration_id,
                status,
                requested_state="PAUSED",
                target_commits=target_commits,
                checkpoint_commits=checkpoint_commits,
            )
            return self._result(migration_id, inventory, budget_exceeded=False)
        except Exception as exc:
            self._update_totals(
                migration_id,
                "FAILED",
                requested_state="PAUSED",
                last_error=exc.__class__.__name__,
                target_commits=target_commits,
                checkpoint_commits=checkpoint_commits,
            )
            raise

    def _ensure_table_checkpoints(self, record: MigrationRecord, inventory: dict[str, Any]) -> None:
        existing = {item.source_table for item in self.journal.list_table_checkpoints(record.migration_id)}
        for item in inventory["tables"]:
            table = str(item["table_name"])
            if item["classification"] != "SUPPORTED" or table in existing:
                continue
            self.journal.upsert_table_checkpoint(
                TableCheckpoint(
                    migration_id=record.migration_id,
                    source_table=table,
                    source_range=f"{item['min_source_key']}..{item['max_source_key']}",
                    last_source_key=0,
                    copied_count=0,
                    verified_count=0,
                    duplicate_count=0,
                    error_count=0,
                    status="PENDING",
                    updated_at=self._now(),
                )
            )

    def _record_ranges(
        self,
        migration_id: str,
        table: str,
        source_rows: list[dict[str, Any]],
        events: list[dict[str, Any]],
        target_rows: list[dict[str, Any]],
        *,
        inserted_by_month: dict[str, int],
        invalid_count: int,
        started_at: str,
        elapsed_ms: int,
        budget_exceeded: bool,
    ) -> None:
        target_by_id = {str(row["event_id"]): row for row in target_rows}
        groups: dict[str, list[dict[str, Any]]] = {}
        for event in events:
            groups.setdefault(str(event["collected_at"])[:7], []).append(event)
        if invalid_count:
            groups["INVALID"] = []
        for month, month_events in groups.items():
            month_target = [target_by_id[str(event["event_id"])] for event in month_events]
            month_inserted = inserted_by_month.get(month, 0)
            source_digest = self._digest_events(month_events)
            target_digest = self._digest_events(month_target)
            self.journal.record_range(
                {
                    "migration_id": migration_id,
                    "source_table": table,
                    "source_start_key": int(source_rows[0]["id"]),
                    "source_end_key": int(source_rows[-1]["id"]),
                    "target_month": month,
                    "source_count": invalid_count if month == "INVALID" else len(month_events),
                    "copied_count": month_inserted,
                    "verified_count": len(month_target),
                    "duplicate_count": max(0, len(month_target) - month_inserted),
                    "error_count": invalid_count if month == "INVALID" else 0,
                    "source_digest": source_digest,
                    "target_digest": target_digest,
                    "sample_count": min(5, len(month_events)),
                    "elapsed_ms": elapsed_ms,
                    "budget_exceeded": int(budget_exceeded),
                    "status": "FAILED" if month == "INVALID" else "VERIFIED",
                    "started_at": started_at,
                    "updated_at": self._now(),
                    "last_error": "INVALID_OR_UNSUPPORTED_ROW" if month == "INVALID" else "",
                }
            )

    def _verify_chunk(
        self,
        migration_id: str,
        table: str,
        source_events: list[dict[str, Any]],
        target_rows: list[dict[str, Any]],
    ) -> None:
        if len(target_rows) != len(source_events):
            raise RuntimeError("target event count does not match source chunk")
        if self._digest_events(source_events) != self._digest_events(target_rows):
            raise RuntimeError("target event digest does not match source chunk")
        if not source_events:
            return
        target_by_id = {str(row["event_id"]): row for row in target_rows}
        rng = random.Random(f"{migration_id}|{table}|{source_events[0]['event_id']}")
        samples = rng.sample(source_events, min(5, len(source_events)))
        for event in samples:
            target = target_by_id[str(event["event_id"])]
            if self._digest_events([event]) != self._digest_events([target]):
                raise RuntimeError("target sample does not match source event")

    def _assert_current_source(self, migration_id: str) -> MigrationRecord:
        record = self.journal.get(migration_id)
        if record is None:
            raise ValueError(f"unknown migration: {migration_id}")
        current = self.source_database_identity(
            self.inventory(exact_counts=True, write_report=False)
        )
        if current != record.source_database_identity:
            raise ValueError("migration source database identity changed")
        return record

    def _required_table(self, migration_id: str, source_table: str) -> TableCheckpoint:
        checkpoint = self.journal.table_checkpoint(migration_id, source_table)
        if checkpoint is None:
            raise ValueError(f"unknown migration source table: {source_table}")
        return checkpoint

    def _build_delete_plan_table(self, checkpoint: TableCheckpoint) -> dict[str, Any]:
        spec = SUPPORTED_SPECS.get(checkpoint.source_table)
        reasons: list[str] = []
        entries: list[dict[str, Any]] = []
        if spec is None:
            reasons.append("UNSUPPORTED_SOURCE")
        if checkpoint.status != "VERIFIED" or checkpoint.error_count:
            reasons.append("COPY_OR_DIGEST_VERIFICATION_INCOMPLETE")
        for record in self.journal.range_records(checkpoint.migration_id):
            if str(record["source_table"]) != checkpoint.source_table:
                continue
            if str(record["target_month"]) == "INVALID":
                reasons.append("UNSUPPORTED_OR_INVALID_ROWS_PRESENT")
                continue
            rows = self.source.fetch_range(
                checkpoint.source_table,
                int(record["source_start_key"]),
                int(record["source_end_key"]),
            )
            matched = (
                self.source.projection_matches(checkpoint.source_table, rows)
                if spec and spec.canonical_source
                else rows
            )
            selected_keys: list[int] = []
            events: list[dict[str, Any]] = []
            for source_row, matched_row in zip(rows, matched, strict=True):
                if matched_row is None:
                    reasons.append("INVALID_CANONICAL_MAPPING")
                    continue
                event = self.store.legacy_migration_event(
                    spec.canonical_source or checkpoint.source_table,
                    matched_row,
                )
                if str(event["collected_at"])[:7] != str(record["target_month"]):
                    continue
                selected_keys.append(int(source_row["id"]))
                events.append(event)
            target_rows = self.store.read_legacy_migration_events(events)
            source_digest = self._digest_events(events)
            target_digest = self._digest_events(target_rows)
            range_reasons: list[str] = []
            if len(selected_keys) != int(record["source_count"]):
                range_reasons.append("SOURCE_COUNT_CHANGED")
            if len(target_rows) != len(events):
                range_reasons.append("TARGET_EVENT_MISSING")
            if source_digest != str(record["source_digest"]):
                range_reasons.append("SOURCE_DIGEST_CHANGED")
            if target_digest != str(record["target_digest"]):
                range_reasons.append("TARGET_DIGEST_CHANGED")
            if int(record["verified_count"]) != int(record["source_count"]):
                range_reasons.append("RANGE_NOT_FULLY_VERIFIED")
            if int(record["copied_count"]) + int(record["duplicate_count"]) != int(
                record["verified_count"]
            ):
                range_reasons.append("COPY_DUPLICATE_ACCOUNTING_MISMATCH")
            if (
                spec
                and spec.canonical_source
                and int(record["duplicate_count"]) != int(record["source_count"])
            ):
                range_reasons.append("PROJECTION_MAPPING_NOT_VERIFIED")
            if range_reasons:
                reasons.extend(range_reasons)
            entries.append(
                {
                    "source_start_key": int(record["source_start_key"]),
                    "source_end_key": int(record["source_end_key"]),
                    "target_month": str(record["target_month"]),
                    "source_key_ranges": self._compress_keys(selected_keys),
                    "row_count": len(selected_keys),
                    "verified_count": int(record["verified_count"]),
                    "source_digest": source_digest,
                    "target_digest": target_digest,
                    "projection_duplicate": bool(spec and spec.canonical_source),
                    "eligibility": not range_reasons,
                    "reason": "ELIGIBLE"
                    if not range_reasons
                    else ",".join(sorted(set(range_reasons))),
                }
            )
        eligible = not reasons and all(bool(item["eligibility"]) for item in entries)
        return {
            "source_table": checkpoint.source_table,
            "source_range": checkpoint.source_range,
            "row_count": sum(int(item["row_count"]) for item in entries),
            "verified_count": checkpoint.verified_count,
            "duplicate_count": checkpoint.duplicate_count,
            "authority_state": checkpoint.authority_state,
            "cutover_revision": checkpoint.cutover_revision,
            "eligibility": eligible,
            "reason": "ELIGIBLE" if eligible else ",".join(sorted(set(reasons))),
            "ranges": entries,
        }

    @staticmethod
    def _compress_keys(values: list[int]) -> list[dict[str, int]]:
        keys = sorted(set(int(value) for value in values))
        if not keys:
            return []
        ranges: list[dict[str, int]] = []
        start = previous = keys[0]
        for value in keys[1:]:
            if value == previous + 1:
                previous = value
                continue
            ranges.append({"start": start, "end": previous})
            start = previous = value
        ranges.append({"start": start, "end": previous})
        return ranges

    @staticmethod
    def _stable_digest(value: Any) -> str:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _digest_events(events: list[dict[str, Any]]) -> str:
        stable: list[dict[str, Any]] = []
        for event in events:
            payload = json.loads(str(event.get("payload_json") or "{}"))
            kind = str(event.get("kind") or "")
            if kind == "fit_ap_lldp":
                important = {"neighbor_interface": payload.get("neighbor_interface")}
            elif kind == "fit_ap_optical":
                important = {
                    key: payload.get(key) for key in ("interface_name", "rx_power", "tx_power")
                }
            else:
                important = {
                    key: value
                    for key, value in payload.items()
                    if key not in {"legacy_source_table", "legacy_source_id"}
                }
            stable.append(
                {
                    "event_id": str(event.get("event_id") or ""),
                    "kind": kind,
                    "entity_key": str(event.get("entity_key") or ""),
                    "collected_at": str(event.get("collected_at") or ""),
                    "important_payload": important,
                }
            )
        encoded = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _update_totals(
        self,
        migration_id: str,
        status: str,
        *,
        requested_state: str | None = None,
        last_error: str = "",
        target_commits: int | None = None,
        checkpoint_commits: int | None = None,
    ) -> None:
        checkpoints = self.journal.list_table_checkpoints(migration_id)
        totals = {
            "copied_count": sum(item.copied_count for item in checkpoints),
            "verified_count": sum(item.verified_count for item in checkpoints),
            "duplicate_count": sum(item.duplicate_count for item in checkpoints),
            "error_count": sum(item.error_count for item in checkpoints),
        }
        self.journal.update_migration(
            migration_id,
            status=status,
            requested_state=requested_state,
            totals=totals,
            now=self._now(),
            last_error=last_error,
            target_commits=target_commits,
            checkpoint_commits=checkpoint_commits,
        )

    def _result(
        self,
        migration_id: str,
        inventory: dict[str, Any],
        *,
        budget_exceeded: bool,
    ) -> dict[str, Any]:
        status = self.status(migration_id)
        migration = status.get("migration", {})
        return {
            **status,
            "inventory": inventory,
            "budget_exceeded": budget_exceeded,
            "result": "COPY_ONLY_READY" if migration.get("status") == "VERIFIED" else "NOT_READY",
            "maintenance_exclusive_class": MAINTENANCE_EXCLUSIVE_CLASS,
            "source_preserved": True,
        }

    def _not_ready(self, reason: str, *, inventory: dict[str, Any]) -> dict[str, Any]:
        return {
            "result": "NOT_READY",
            "reason": reason,
            "inventory": inventory,
            "source_preserved": True,
            "destructive_operations": {"DELETE": "NO", "DROP": "NO", "VACUUM": "NO"},
        }

    def validate_query_parity(
        self, migration_id: str, source_table: str
    ) -> dict[str, Any]:
        """Validate count, ordering, pagination, filters, and event identity."""

        checkpoint = self._required_table(migration_id, source_table)
        spec = SUPPORTED_SPECS.get(source_table)
        if spec is None or checkpoint.authority_state not in {
            "SHARD_AUTHORITY",
            "SOURCE_DELETE_ELIGIBLE",
            "SOURCE_DELETED",
        }:
            raise ValueError("query parity requires shard authority")
        if spec.canonical_source:
            if checkpoint.authority_state == "SOURCE_DELETED":
                canonical_checkpoint = self._required_table(
                    migration_id, spec.canonical_source
                )
                if canonical_checkpoint.authority_state not in {
                    "SHARD_AUTHORITY",
                    "SOURCE_DELETE_ELIGIBLE",
                    "SOURCE_DELETED",
                }:
                    raise ValueError("projection canonical target is not authoritative")
                projection_ranges = [
                    record
                    for record in self.journal.range_records(migration_id)
                    if str(record["source_table"]) == source_table
                    and str(record["target_month"]) != "INVALID"
                ]
                if (
                    not projection_ranges
                    or checkpoint.duplicate_count != checkpoint.verified_count
                    or sum(int(record["verified_count"]) for record in projection_ranges)
                    != checkpoint.verified_count
                    or any(
                        str(record["status"]) != "VERIFIED"
                        or int(record["source_count"]) != int(record["verified_count"])
                        or int(record["duplicate_count"]) != int(record["source_count"])
                        or str(record["source_digest"]) != str(record["target_digest"])
                        for record in projection_ranges
                    )
                ):
                    raise RuntimeError("projection post-delete provenance is incomplete")
                evidence = self._validate_post_delete_target(
                    canonical_checkpoint,
                    kind=spec.entity_type,
                    expected_source_table=spec.canonical_source,
                )
                return {
                    "source_table": source_table,
                    "kind": spec.entity_type,
                    "projection_duplicate": True,
                    "canonical_source": spec.canonical_source,
                    "verified_rows": checkpoint.verified_count,
                    "canonical_mapping_rows": checkpoint.verified_count,
                    "canonical_target_rows": evidence["target_rows"],
                    "canonical_mapping_hash": evidence["mapping_hash"],
                    "projection_provenance_digest": self._stable_digest(
                        projection_ranges
                    ),
                    "post_delete": True,
                    "target_query": evidence,
                    "result": "PASS",
                }
            proof = self._build_delete_plan_table(checkpoint)
            if not proof["eligibility"]:
                raise ValueError("projection canonical parity failed")
            return {
                "source_table": source_table,
                "kind": spec.entity_type,
                "projection_duplicate": True,
                "canonical_source": spec.canonical_source,
                "verified_rows": checkpoint.verified_count,
                "canonical_mapping_rows": int(proof["row_count"]),
                "result": "PASS",
            }

        kind = spec.entity_type
        expected_count = int(checkpoint.verified_count)
        actual_count = self.store.count_events(kind=kind)
        if actual_count != expected_count:
            raise RuntimeError(
                f"history count parity failed: {actual_count} != {expected_count}"
            )
        page_size = min(25, max(1, expected_count))
        first = self.store.query_events(kind=kind, limit=page_size, offset=0)
        second = self.store.query_events(
            kind=kind, limit=page_size, offset=page_size
        )
        combined = first + second
        expected_order = sorted(
            combined,
            key=lambda item: (
                str(item.get("collected_at") or ""),
                str(item.get("event_id") or ""),
            ),
            reverse=True,
        )
        if combined != expected_order:
            raise RuntimeError("history ordering or pagination parity failed")
        identities = [str(item.get("event_id") or "") for item in combined]
        if len(identities) != len(set(identities)):
            raise RuntimeError("history pagination returned duplicate event identity")
        source_samples: dict[str, dict[str, Any]] = {}
        if checkpoint.authority_state != "SOURCE_DELETED":
            source_samples = self.source.find_rows_by_event_ids(
                source_table, set(identities)
            )
            if len(source_samples) != len(identities):
                raise RuntimeError("history query source identity is missing")
            for item in combined:
                expected_event = self.store.legacy_migration_event(
                    source_table, source_samples[str(item["event_id"])]
                )
                expected_output = json.loads(str(expected_event["payload_json"]))
                for envelope_field in (
                    "collected_at",
                    "legacy_source_table",
                    "legacy_source_id",
                ):
                    expected_output.pop(envelope_field, None)
                expected_output.update(
                    {
                        "event_id": expected_event["event_id"],
                        "event_type": expected_event["event_type"],
                        "collected_at": expected_event["collected_at"],
                    }
                )
                observed_output = dict(item)
                for envelope_field in (
                    "legacy_source_table",
                    "legacy_source_id",
                ):
                    observed_output.pop(envelope_field, None)
                if self._stable_digest(observed_output) != self._stable_digest(
                    expected_output
                ):
                    raise RuntimeError("history query event identity or payload mismatch")

        month_counts: dict[str, int] = {}
        for record in self.journal.range_records(migration_id):
            if str(record["source_table"]) != source_table:
                continue
            month = str(record["target_month"])
            if month == "INVALID":
                continue
            month_counts[month] = month_counts.get(month, 0) + int(
                record["source_count"]
            )
        for month, expected in month_counts.items():
            actual = self.store.count_events(
                kind=kind,
                collected_from=f"{month}-01T00:00:00",
                collected_to=f"{month}-31T23:59:59.999999",
            )
            if actual != expected:
                raise RuntimeError(
                    f"history month filter parity failed for {month}: {actual} != {expected}"
                )
        entity_count = 0
        if first and checkpoint.authority_state != "SOURCE_DELETED":
            source_row = source_samples[str(first[0]["event_id"])]
            event = self.store.legacy_migration_event(source_table, source_row)
            entity_count = self.store.count_events(
                kind=kind, entity_key=str(event["entity_key"])
            )
            if entity_count <= 0:
                raise RuntimeError("history entity filter parity failed")
        health = self.store.history_health()
        if health["status"] != "ready":
            raise RuntimeError(f"history query health degraded: {health['errors']}")
        post_delete_evidence: dict[str, Any] | None = None
        if checkpoint.authority_state == "SOURCE_DELETED":
            post_delete_evidence = self._validate_post_delete_target(
                checkpoint,
                kind=kind,
                expected_source_table=source_table,
            )
        return {
            "source_table": source_table,
            "kind": kind,
            "projection_duplicate": False,
            "expected_count": expected_count,
            "actual_count": actual_count,
            "page_one_rows": len(first),
            "page_two_rows": len(second),
            "month_counts": month_counts,
            "entity_filter_count": entity_count,
            "history_health": health,
            "post_delete": checkpoint.authority_state == "SOURCE_DELETED",
            "target_query": post_delete_evidence,
            "payload_identity_validation": (
                "PRE_DELETE_RANGE_DIGEST"
                if checkpoint.authority_state == "SOURCE_DELETED"
                else "LIVE_SOURCE_SAMPLE"
            ),
            "result": "PASS",
        }

    def _validate_post_delete_target(
        self,
        checkpoint: TableCheckpoint,
        *,
        kind: str,
        expected_source_table: str,
    ) -> dict[str, Any]:
        """Re-query the canonical target after source deletion.

        A deleted source cannot be used as a proof of parity.  The target must
        therefore prove row count, pagination, time filtering, health, and the
        deterministic source-id mapping that was copied before deletion.
        """

        expected_count = int(checkpoint.verified_count)
        actual_count = self.store.count_events(kind=kind)
        if actual_count != expected_count:
            raise RuntimeError(
                f"post-delete target count parity failed: {actual_count} != {expected_count}"
            )
        page_size = min(25, max(1, expected_count))
        first = self.store.query_events(kind=kind, limit=page_size, offset=0)
        second = self.store.query_events(kind=kind, limit=page_size, offset=page_size)
        combined = first + second
        if combined != sorted(
            combined,
            key=lambda item: (
                str(item.get("collected_at") or ""),
                str(item.get("event_id") or ""),
            ),
            reverse=True,
        ):
            raise RuntimeError("post-delete target ordering or pagination parity failed")
        identities = [str(item.get("event_id") or "") for item in combined]
        if len(identities) != len(set(identities)):
            raise RuntimeError("post-delete target pagination returned duplicate identity")

        mapping_rows: list[tuple[str, str, str]] = []
        month_expected_counts: dict[str, int] = {}
        for record in self.journal.range_records(checkpoint.migration_id):
            if str(record["source_table"]) != checkpoint.source_table:
                continue
            month = str(record["target_month"])
            if month == "INVALID":
                continue
            month_expected_counts[month] = month_expected_counts.get(month, 0) + int(
                record["verified_count"]
            )

        month_counts: dict[str, int] = {}
        for month, expected_month in month_expected_counts.items():
            actual_month = self.store.count_events(
                kind=kind,
                collected_from=f"{month}-01T00:00:00",
                collected_to=f"{month}-31T23:59:59.999999",
            )
            if actual_month != expected_month:
                raise RuntimeError(
                    f"post-delete target month filter parity failed for {month}: "
                    f"{actual_month} != {expected_month}"
                )
            month_counts[month] = actual_month
            offset = 0
            while True:
                page = self.store.query_events(
                    kind=kind,
                    limit=1000,
                    offset=offset,
                    collected_from=f"{month}-01T00:00:00",
                    collected_to=f"{month}-31T23:59:59.999999",
                )
                if not page:
                    break
                for event in page:
                    raw_payload = event.get("payload_json")
                    payload = (
                        json.loads(str(raw_payload or "{}"))
                        if raw_payload is not None
                        else event
                    )
                    source_table = str(payload.get("legacy_source_table") or "")
                    source_id = str(payload.get("legacy_source_id") or "")
                    if source_table != expected_source_table or not source_id:
                        raise RuntimeError("post-delete target source mapping is incomplete")
                    mapping_rows.append(
                        (
                            str(event.get("event_id") or ""),
                            source_table,
                            source_id,
                        )
                    )
                offset += len(page)
                if len(page) < 1000:
                    break

        if len(mapping_rows) != expected_count:
            raise RuntimeError(
                f"post-delete target mapping count failed: {len(mapping_rows)} != {expected_count}"
            )
        if len({row[2] for row in mapping_rows}) != expected_count:
            raise RuntimeError("post-delete target source mapping is not one-to-one")
        mapping_hash = hashlib.sha256(
            json.dumps(sorted(mapping_rows), ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()
        health = self.store.history_health()
        if health["status"] != "ready":
            raise RuntimeError(f"post-delete target query health degraded: {health['errors']}")
        return {
            "expected_rows": expected_count,
            "target_rows": actual_count,
            "page_one_rows": len(first),
            "page_two_rows": len(second),
            "month_counts": month_counts,
            "mapping_rows": len(mapping_rows),
            "mapping_hash": mapping_hash,
            "history_health": health,
            "query_mode": "POST_DELETE_CANONICAL_TARGET_REQUERY",
        }

    def _append_invalid(self, rows: list[dict[str, Any]]) -> None:
        self.diagnostics_dir.mkdir(parents=True, exist_ok=True)
        path = self.diagnostics_dir / "LEGACY_HISTORY_INVALID_ROWS.jsonl"
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    def _write_json(self, name: str, value: dict[str, Any]) -> None:
        self.diagnostics_dir.mkdir(parents=True, exist_ok=True)
        path = self.diagnostics_dir / name
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)

    def _now(self) -> str:
        value = (self._clock or (lambda: datetime.now(UTC).astimezone()))()
        return value.isoformat(timespec="seconds")

    @staticmethod
    def _error_code(exc: Exception) -> str:
        message = str(exc).casefold()
        if "collection time" in message:
            return "INVALID_TIMESTAMP"
        return "UNSUPPORTED_ROW"


__all__ = [
    "DELETE_PLAN_FILE_NAME",
    "HistoryLegacyMigrationService",
    "INVENTORY_FILE_NAME",
    "MAINTENANCE_EXCLUSIVE_CLASS",
    "SUPPORTED_SPECS",
    "UNSUPPORTED_TABLES",
]
