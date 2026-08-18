"""Explicit, resumable COPY-only migration for legacy device history tables."""

from __future__ import annotations

import hashlib
import json
import random
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
from netconsole.services.database_upgrade.coordinator import database_maintenance_lock
from netconsole.services.history_store import HistoryStore


MAINTENANCE_EXCLUSIVE_CLASS = "site-database-maintenance"
INVENTORY_FILE_NAME = "LEGACY_HISTORY_INVENTORY.json"
MIGRATION_REPORT_FILE_NAME = "LEGACY_HISTORY_MIGRATION_REPORT.json"


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
    "ap_lldp_history": LegacyTableSpec(
        "fit_ap_lldp", ("ap_uuid",), canonical_source="ac_fit_ap_lldp_history"
    ),
    "ap_optical_history": LegacyTableSpec(
        "fit_ap_optical", ("ap_uuid",), canonical_source="ac_fit_ap_optical_history"
    ),
}
UNSUPPORTED_TABLES = {
    "ac_fit_ap_unauthenticated_history": "no target history entity contract",
    "ac_station_online_summary_history": "aggregate summary has no target event contract",
}
SOURCE_ORDER = tuple(
    name for name in SUPPORTED_SPECS if not SUPPORTED_SPECS[name].canonical_source
) + tuple(name for name in SUPPORTED_SPECS if SUPPORTED_SPECS[name].canonical_source)


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
        clock: Callable[[], datetime] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.paths = paths
        self.site_id = str(site_id)
        self.source_database = Path(source_database).resolve()
        self.history_root = Path(history_root).resolve()
        self.diagnostics_dir = Path(diagnostics_dir).resolve()
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
        safe_chunk_rows = max(1, min(int(chunk_rows), 500))
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
        lock_key = f"{MAINTENANCE_EXCLUSIVE_CLASS}:{self.site_id}"
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

    def resume(self, migration_id: str, **kwargs: Any) -> dict[str, Any]:
        record = self.journal.get(migration_id)
        if record is None:
            raise ValueError(f"unknown migration: {migration_id}")
        return self.start(migration_id=migration_id, chunk_rows=record.chunk_rows, **kwargs)

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
        """Switch a verified source table to shard query authority without deleting it."""

        lock_key = f"{MAINTENANCE_EXCLUSIVE_CLASS}:{self.site_id}"
        with database_maintenance_lock(self.paths, lock_key):
            self._assert_current_source(migration_id)
            checkpoint = self._required_table(migration_id, source_table)
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
        """Return one table to legacy query authority while the source is preserved."""

        lock_key = f"{MAINTENANCE_EXCLUSIVE_CLASS}:{self.site_id}"
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
        target_commits = (self.journal.get(migration_id) or MigrationRecord("", "", "", "", "", "", 0)).target_commits
        checkpoint_commits = (self.journal.get(migration_id) or MigrationRecord("", "", "", "", "", "", 0)).checkpoint_commits
        invocation_started = self._monotonic()
        budget_exceeded = False
        inventory_by_name = {str(item["table_name"]): item for item in inventory["tables"]}
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
                        self.journal.set_requested_state(migration_id, "PAUSED", now=self._now())
                        return self._result(migration_id, inventory, budget_exceeded=False)
                    checkpoint = self.journal.table_checkpoint(migration_id, table)
                    assert checkpoint is not None
                    rows = self.source.fetch_after(table, checkpoint.last_source_key, chunk_rows)
                    if not rows:
                        final_status = "FAILED" if checkpoint.error_count else "VERIFIED"
                        self.journal.upsert_table_checkpoint(
                            TableCheckpoint(**{**asdict(checkpoint), "status": final_status, "updated_at": self._now()})
                        )
                        break
                    started = self._monotonic()
                    started_at = self._now()
                    self.journal.upsert_table_checkpoint(
                        TableCheckpoint(**{**asdict(checkpoint), "status": "COPYING", "updated_at": started_at})
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
                                raise ValueError("projection row has no authoritative source match")
                            valid_events.append(
                                self.store.legacy_migration_event(
                                    canonical_source or table, matched_row
                                )
                            )
                        except (KeyError, TypeError, ValueError) as exc:
                            invalid.append(
                                {"source_table": table, "source_key": int(row.get("id") or 0), "reason": self._error_code(exc)}
                            )
                    inserted = 0
                    verified = 0
                    inserted_by_month: dict[str, int] = {}
                    if valid_events and not canonical_source:
                        event_groups: dict[str, list[dict[str, Any]]] = {}
                        for event in valid_events:
                            event_groups.setdefault(str(event["collected_at"])[:7], []).append(event)
                        for month, month_events in event_groups.items():
                            month_inserted, month_verified = self.store.copy_legacy_migration_events(month_events)
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
                        and self._monotonic() - invocation_started >= max_elapsed_seconds
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
                        duplicate_count=checkpoint.duplicate_count + max(0, verified - inserted),
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
                        return self._result(migration_id, inventory, budget_exceeded=True)
            tables = self.journal.list_table_checkpoints(migration_id)
            for checkpoint in tables:
                if (
                    checkpoint.status == "VERIFIED"
                    and checkpoint.error_count == 0
                    and checkpoint.authority_state == "LEGACY_AUTHORITY"
                ):
                    self.journal.transition_authority(
                        migration_id,
                        checkpoint.source_table,
                        to_state="SHARD_VERIFIED",
                        expected_revision=checkpoint.cutover_revision,
                        reason="copy verification completed",
                        now=self._now(),
                    )
            tables = self.journal.list_table_checkpoints(migration_id)
            status = "FAILED" if any(item.status == "FAILED" for item in tables) else "VERIFIED"
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
    "HistoryLegacyMigrationService",
    "INVENTORY_FILE_NAME",
    "MAINTENANCE_EXCLUSIVE_CLASS",
    "SUPPORTED_SPECS",
    "UNSUPPORTED_TABLES",
]
