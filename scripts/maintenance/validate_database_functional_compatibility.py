"""Generate read-only before/after database functional compatibility evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import struct
import subprocess
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from contextlib import closing
from dataclasses import fields
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from netconsole.core.sqlite_utils import (
    DEFAULT_SQLITE_BUSY_TIMEOUT_MS,
    DEFAULT_SQLITE_TIMEOUT_SECONDS,
    configure_sqlite_connection,
)
from netconsole.models.task_snapshot import TaskSnapshot
from netconsole.models.task_state import TaskState
from netconsole.repositories.history_store import LEGACY_HISTORY_TABLES, TaskHistoryStore
from netconsole.repositories.task_repository import TaskRepository


DEFAULT_DEVELOPMENT_ROOT = Path("D:/study")
OUTPUT_FILENAMES = (
    "FUNCTIONAL_BASELINE.json",
    "FUNCTIONAL_AFTER.json",
    "FUNCTIONAL_COMPATIBILITY.json",
)
DEFAULT_EXCLUDED_TASK_IDS = frozenset({"database-footprint-ref-compatibility"})

DEVICE_MAINTENANCE_TABLES = frozenset(
    {
        "schema_metadata",
        "history_outbox",
        "history_state",
    }
)
TASK_MAINTENANCE_TABLES = frozenset(
    {
        "task_schema_meta",
        "task_result_storage_rollout",
        "task_result_storage_rollout_audit",
    }
)
TASK_REPOSITORY_AUTHORITY_TABLES = frozenset(
    {"task_snapshots", "task_events", "task_results"}
)

DEVICE_TABLE_TEST_IDS = (
    "tests/test_database_footprint_maintenance.py::test_readonly_online_backup_and_compact_replace_rollback",
    "tests/test_history_legacy_migration.py::test_per_table_cutover_query_authority_persists_and_rolls_back",
)
TASK_REPOSITORY_TEST_IDS = (
    "tests/test_task_repository_storage_governance.py::test_old_dual_write_and_ref_only_results_remain_readable",
    "tests/test_task_repository_storage_governance.py::test_batch_event_read_does_not_truncate_archived_history_at_10000",
    "tests/test_site_retention.py::test_typed_task_retention_exact_apply_preserves_active_mr_ground_and_artifact",
)
HISTORY_TEST_IDS = (
    "tests/test_history_legacy_migration.py::test_per_table_cutover_query_authority_persists_and_rolls_back",
    "tests/test_history_store.py::test_sealed_shard_replay_is_noop_and_new_event_uses_next_segment",
)


class FunctionalCompatibilityError(ValueError):
    """Raised when an input or output boundary is unsafe or incomplete."""


class _ReadonlyTaskRepository(TaskRepository):
    """TaskRepository read facade without initialize or writable connections."""

    def __init__(self, db_path: Path, *, history_root: Path) -> None:
        self.db_path = Path(db_path)
        self.task_history = TaskHistoryStore(
            self.db_path,
            history_root=history_root,
        )

    def _connect(self) -> sqlite3.Connection:
        return _connect_readonly(self.db_path)


def validate_database_functional_compatibility(
    *,
    before_devices: Path,
    after_devices: Path,
    before_tasks: Path,
    after_tasks: Path,
    before_history_evidence: Path,
    after_history_evidence: Path,
    before_consumer_observations: Path | None = None,
    after_consumer_observations: Path | None = None,
    output_dir: Path,
    development_root: Path = DEFAULT_DEVELOPMENT_ROOT,
    excluded_task_ids: Iterable[str] = DEFAULT_EXCLUDED_TASK_IDS,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Profile two isolated snapshots and atomically publish three JSON reports."""

    root = Path(development_root).resolve(strict=True)
    inputs = {
        "before_devices": _validated_input_file(before_devices, root),
        "after_devices": _validated_input_file(after_devices, root),
        "before_tasks": _validated_input_file(before_tasks, root),
        "after_tasks": _validated_input_file(after_tasks, root),
        "before_history_evidence": _validated_input_directory(
            before_history_evidence, root
        ),
        "after_history_evidence": _validated_input_directory(
            after_history_evidence, root
        ),
    }
    observation_inputs: dict[str, Path] | None = None
    if before_consumer_observations is None or after_consumer_observations is None:
        raise FunctionalCompatibilityError(
            "before/after consumer observation manifests are required"
        )
    observation_inputs = {
        "before": _validated_input_file(before_consumer_observations, root),
        "after": _validated_input_file(after_consumer_observations, root),
    }
    if inputs["before_devices"] == inputs["after_devices"]:
        raise FunctionalCompatibilityError("before/after devices databases must differ")
    if inputs["before_tasks"] == inputs["after_tasks"]:
        raise FunctionalCompatibilityError("before/after tasks databases must differ")

    destination = _validated_output_directory(
        output_dir,
        development_root=root,
        evidence_directories=(
            inputs["before_history_evidence"],
            inputs["after_history_evidence"],
        ),
    )
    output_paths = {name: destination / name for name in OUTPUT_FILENAMES}
    existing = sorted(path.name for path in output_paths.values() if path.exists())
    if existing and not overwrite:
        raise FileExistsError(
            "refusing to overwrite functional compatibility outputs: "
            + ", ".join(existing)
        )

    exclusions = {
        str(value).strip()
        for value in excluded_task_ids
        if str(value).strip()
    }
    before = _build_snapshot_artifact(
        artifact="FUNCTIONAL_BASELINE",
        devices=inputs["before_devices"],
        tasks=inputs["before_tasks"],
        evidence_dir=inputs["before_history_evidence"],
        excluded_task_ids=exclusions,
        consumer_observations=_load_consumer_observations(observation_inputs["before"], root),
    )
    after = _build_snapshot_artifact(
        artifact="FUNCTIONAL_AFTER",
        devices=inputs["after_devices"],
        tasks=inputs["after_tasks"],
        evidence_dir=inputs["after_history_evidence"],
        excluded_task_ids=exclusions,
        consumer_observations=_load_consumer_observations(observation_inputs["after"], root),
    )
    compatibility = _build_compatibility_artifact(before, after)
    generator = _evidence_binding(Path(__file__).resolve())
    for artifact in (before, after, compatibility):
        artifact["git_head"] = generator["git_head"]
        artifact["generator"] = dict(generator)
    for artifact in (before, after):
        for observation in artifact["consumer_observations"]["observations"].values():
            observation["generator"] = dict(generator)
        artifact["consumer_observations"]["snapshot_binding"]["git_head"] = generator[
            "git_head"
        ]
    payloads = {
        "FUNCTIONAL_BASELINE.json": before,
        "FUNCTIONAL_AFTER.json": after,
        "FUNCTIONAL_COMPATIBILITY.json": compatibility,
    }
    _atomic_publish_json(output_paths, payloads, overwrite=overwrite)
    return {
        "status": compatibility["status"],
        "outputs": {name: path for name, path in output_paths.items()},
    }


def _build_snapshot_artifact(
    *,
    artifact: str,
    devices: Path,
    tasks: Path,
    evidence_dir: Path,
    excluded_task_ids: set[str],
    consumer_observations: dict[str, Any],
) -> dict[str, Any]:
    devices_profile = _profile_current_tables(devices, owner="devices")
    tasks_tables_profile = _profile_current_tables(tasks, owner="tasks")
    history_root = _resolve_history_root(tasks, evidence_dir)
    task_profile = _profile_task_repository(
        tasks,
        history_root=history_root,
        excluded_task_ids=excluded_task_ids,
    )
    history_profile = _profile_history_evidence(evidence_dir)
    checks = [
        _profile_check(
            "devices.current_business_tables",
            devices_profile,
            evidence_paths=[devices],
            test_ids=DEVICE_TABLE_TEST_IDS,
        ),
        _profile_check(
            "tasks.auxiliary_business_tables",
            tasks_tables_profile,
            evidence_paths=[tasks],
            test_ids=TASK_REPOSITORY_TEST_IDS,
        ),
        _profile_check(
            "tasks.repository_transparent_read",
            task_profile,
            evidence_paths=[tasks, history_root],
            test_ids=TASK_REPOSITORY_TEST_IDS,
        ),
        _profile_check(
            "history.parity_evidence",
            history_profile,
            evidence_paths=[evidence_dir],
            test_ids=HISTORY_TEST_IDS,
        ),
    ]
    status = "PASS" if all(item["status"] == "PASS" for item in checks) else "FAIL"
    return {
        "schema_version": 1,
        "artifact": artifact,
        "mode": "READ_ONLY_FUNCTIONAL_PROFILE",
        "generated_at_utc": _now(),
        "status": status,
        "source": {
            "devices_database": str(devices),
            "tasks_database": str(tasks),
            "history_evidence_directory": str(evidence_dir),
            "history_root": str(history_root),
        },
        "checks": checks,
        "profiles": {
            "devices_current_tables": devices_profile,
            "tasks_auxiliary_tables": tasks_tables_profile,
            "task_repository": task_profile,
            "history_evidence": history_profile,
        },
        "consumer_observations": consumer_observations,
        "summary": _checks_summary(checks),
    }


def _load_consumer_observations(path: Path, development_root: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FunctionalCompatibilityError(
            f"invalid consumer observation manifest {path}: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise FunctionalCompatibilityError("consumer observation manifest must be an object")
    binding = value.get("snapshot_binding")
    observations = value.get("observations")
    if not isinstance(binding, dict) or not isinstance(observations, dict):
        raise FunctionalCompatibilityError("consumer observation manifest is incomplete")
    if str(binding.get("site_id") or "") != "ningbo-line-12":
        raise FunctionalCompatibilityError("consumer observation snapshot is not Ningbo Line 12")
    if binding.get("isolated_copy") is not True:
        raise FunctionalCompatibilityError("consumer observation snapshot is not an isolated copy")
    root_text = str(binding.get("root") or "")
    snapshot_root = Path(root_text).resolve()
    if not snapshot_root.is_relative_to(development_root) or not snapshot_root.is_dir():
        raise FunctionalCompatibilityError("consumer observation snapshot root is not below D:/study")
    for name, item in observations.items():
        if not isinstance(item, dict):
            raise FunctionalCompatibilityError(f"consumer observation is invalid: {name}")
        if str(item.get("status") or "") != "PASS":
            raise FunctionalCompatibilityError(f"consumer observation is not PASS: {name}")
        digest = str(item.get("query_digest") or "").casefold()
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise FunctionalCompatibilityError(f"consumer observation digest is invalid: {name}")
        paths = item.get("source_paths")
        if not isinstance(paths, list) or not paths:
            raise FunctionalCompatibilityError(f"consumer observation has no source paths: {name}")
        for raw_path in paths:
            source = Path(str(raw_path)).resolve()
            if not source.is_relative_to(development_root) or not source.is_file():
                raise FunctionalCompatibilityError(f"consumer observation source is invalid: {name}")
        for field in ("producer", "repository", "consumer", "lifecycle_owner"):
            if not str(item.get(field) or "").strip():
                raise FunctionalCompatibilityError(f"consumer observation {field} is missing: {name}")
        authority = item.get("authority_evidence")
        if not isinstance(authority, Mapping) or str(authority.get("status") or "") != "PASS":
            raise FunctionalCompatibilityError(
                f"consumer observation authority evidence is missing: {name}"
            )
        if not str(authority.get("authority") or "").strip():
            raise FunctionalCompatibilityError(
                f"consumer observation authority is missing: {name}"
            )
        test_ids = authority.get("test_ids")
        if not isinstance(test_ids, list) or not test_ids or not all(
            str(value).strip() for value in test_ids
        ):
            raise FunctionalCompatibilityError(
                f"consumer observation authority tests are missing: {name}"
            )
    return {
        "schema_version": int(value.get("schema_version") or 1),
        "snapshot_binding": dict(binding),
        "observations": {str(name): dict(item) for name, item in observations.items()},
        "manifest_sha256": _sha256_file(path),
        "manifest_path": str(path),
    }


def _profile_check(
    check_id: str,
    profile: Mapping[str, Any],
    *,
    evidence_paths: Sequence[Path],
    test_ids: Sequence[str],
) -> dict[str, Any]:
    errors = [str(value) for value in profile.get("validation_errors", [])]
    authority = profile.get("storage_authority", {})
    if isinstance(authority, Mapping):
        errors.extend(
            f"storage_authority.{value}"
            for value in authority.get("validation_errors", [])
        )
    return {
        "id": check_id,
        "status": str(profile.get("status") or "FAIL"),
        "summary": _public_profile_summary(profile),
        "differences": [
            {"item": value, "before": None, "after": None} for value in errors
        ],
        "evidence_paths": [str(path) for path in evidence_paths],
        "test_ids": list(test_ids),
    }


def _build_compatibility_artifact(
    before: Mapping[str, Any], after: Mapping[str, Any]
) -> dict[str, Any]:
    before_profiles = before["profiles"]
    after_profiles = after["profiles"]
    checks = [
        _compare_table_profiles(
            "devices.current_business_tables",
            before_profiles["devices_current_tables"],
            after_profiles["devices_current_tables"],
            before_path=Path(before["source"]["devices_database"]),
            after_path=Path(after["source"]["devices_database"]),
            test_ids=DEVICE_TABLE_TEST_IDS,
        ),
        _compare_table_profiles(
            "tasks.auxiliary_business_tables",
            before_profiles["tasks_auxiliary_tables"],
            after_profiles["tasks_auxiliary_tables"],
            before_path=Path(before["source"]["tasks_database"]),
            after_path=Path(after["source"]["tasks_database"]),
            test_ids=TASK_REPOSITORY_TEST_IDS,
        ),
        _compare_task_profiles(
            before_profiles["task_repository"],
            after_profiles["task_repository"],
            evidence_paths=(
                Path(before["source"]["tasks_database"]),
                Path(after["source"]["tasks_database"]),
                Path(before["source"]["history_root"]),
                Path(after["source"]["history_root"]),
            ),
        ),
        _compare_history_evidence(
            before_profiles["history_evidence"],
            after_profiles["history_evidence"],
            before_path=Path(before["source"]["history_evidence_directory"]),
            after_path=Path(after["source"]["history_evidence_directory"]),
        ),
    ]
    status = "PASS" if all(item["status"] == "PASS" for item in checks) else "FAIL"
    return {
        "schema_version": 1,
        "artifact": "FUNCTIONAL_COMPATIBILITY",
        "mode": "READ_ONLY_BEFORE_AFTER_COMPARISON",
        "generated_at_utc": _now(),
        "status": status,
        "checks": checks,
        "summary": _checks_summary(checks),
        "source_artifacts": {
            "before": "FUNCTIONAL_BASELINE.json",
            "after": "FUNCTIONAL_AFTER.json",
        },
    }


def _compare_table_profiles(
    check_id: str,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    *,
    before_path: Path,
    after_path: Path,
    test_ids: Sequence[str],
) -> dict[str, Any]:
    differences: list[dict[str, Any]] = []
    before_tables = before.get("tables", {})
    after_tables = after.get("tables", {})
    for table in sorted(set(before_tables) | set(after_tables)):
        left = before_tables.get(table)
        right = after_tables.get(table)
        if left == right:
            continue
        differences.append(
            {
                "item": f"table:{table}",
                "before": _difference_summary(left),
                "after": _difference_summary(right),
            }
        )
    if before.get("quick_check") != "ok" or after.get("quick_check") != "ok":
        differences.append(
            {
                "item": "sqlite_quick_check",
                "before": {"hash": _hash_json(before.get("quick_check"))},
                "after": {"hash": _hash_json(after.get("quick_check"))},
            }
        )
    return {
        "id": check_id,
        "status": "PASS" if not differences else "FAIL",
        "summary": {
            "before": _public_profile_summary(before),
            "after": _public_profile_summary(after),
        },
        "differences": differences,
        "evidence_paths": [str(before_path), str(after_path)],
        "test_ids": list(test_ids),
    }


def _compare_task_profiles(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    *,
    evidence_paths: Sequence[Path],
) -> dict[str, Any]:
    differences: list[dict[str, Any]] = []
    for area in ("snapshots", "events"):
        left = before.get(area, {})
        right = after.get(area, {})
        for component in sorted(set(left) | set(right)):
            if left.get(component) == right.get(component):
                continue
            differences.append(
                {
                    "item": f"{area}.{component}",
                    "before": _difference_summary(left.get(component)),
                    "after": _difference_summary(right.get(component)),
                }
            )
    for side, profile in (("before", before), ("after", after)):
        authority = profile.get("storage_authority", {})
        if not isinstance(authority, Mapping) or authority.get("status") != "PASS":
            differences.append(
                {
                    "item": f"{side}.storage_authority.integrity",
                    "before": _difference_summary(authority)
                    if side == "before"
                    else None,
                    "after": _difference_summary(authority)
                    if side == "after"
                    else None,
                }
            )
        for error in profile.get("validation_errors", []):
            differences.append(
                {"item": f"{side}.{error}", "before": None, "after": None}
            )
    return {
        "id": "tasks.repository_transparent_read",
        "status": "PASS" if not differences else "FAIL",
        "summary": {
            "before": _public_profile_summary(before),
            "after": _public_profile_summary(after),
        },
        "differences": differences,
        "evidence_paths": [str(path) for path in evidence_paths],
        "test_ids": list(TASK_REPOSITORY_TEST_IDS),
    }


def _compare_history_evidence(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    *,
    before_path: Path,
    after_path: Path,
) -> dict[str, Any]:
    differences: list[dict[str, Any]] = []
    if before.get("status") != "PASS":
        differences.append({"item": "before.history_evidence", "before": "FAIL", "after": None})
    if after.get("status") != "PASS":
        differences.append({"item": "after.history_evidence", "before": None, "after": "FAIL"})
    if int(before.get("migration_parity_count") or 0) <= 0:
        differences.append({"item": "before.migration_parity_missing", "before": None, "after": None})
    if int(after.get("post_replace_parity_count") or 0) <= 0:
        differences.append({"item": "after.post_replace_parity_missing", "before": None, "after": None})
    failed = int(before.get("failed_count") or 0) + int(after.get("failed_count") or 0)
    if failed:
        differences.append(
            {
                "item": "history.non_pass_evidence",
                "before": {"count": int(before.get("failed_count") or 0)},
                "after": {"count": int(after.get("failed_count") or 0)},
            }
        )
    return {
        "id": "history.migration_and_post_replace_parity",
        "status": "PASS" if not differences else "FAIL",
        "summary": {
            "before": _public_profile_summary(before),
            "after": _public_profile_summary(after),
        },
        "differences": differences,
        "evidence_paths": [str(before_path), str(after_path)],
        "test_ids": list(HISTORY_TEST_IDS),
    }


def _profile_current_tables(database: Path, *, owner: str) -> dict[str, Any]:
    excluded: dict[str, str] = {}
    table_profiles: dict[str, dict[str, Any]] = {}
    with closing(_connect_readonly(database)) as connection:
        quick_check = str(connection.execute("PRAGMA quick_check").fetchone()[0])
        tables = [
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_schema WHERE type='table' ORDER BY name"
            ).fetchall()
            if not str(row[0]).startswith("sqlite_")
        ]
        for table in tables:
            reason = _table_exclusion_reason(owner, table)
            if reason:
                excluded[table] = reason
                continue
            table_profiles[table] = _profile_table(connection, table)
    aggregate = _hash_json(
        [
            {"table": table, **profile}
            for table, profile in sorted(table_profiles.items())
        ]
    )
    total_rows = sum(int(item["row_count"]) for item in table_profiles.values())
    errors = [] if quick_check == "ok" else ["sqlite_quick_check_failed"]
    return {
        "status": "PASS" if not errors else "FAIL",
        "quick_check": quick_check,
        "database_size_bytes": database.stat().st_size,
        "database_sha256": _sha256_file(database),
        "business_table_count": len(table_profiles),
        "business_row_count": total_rows,
        "aggregate_hash": aggregate,
        "tables": table_profiles,
        "excluded_tables": excluded,
        "validation_errors": errors,
    }


def _table_exclusion_reason(owner: str, table: str) -> str:
    if owner == "devices":
        if table in LEGACY_HISTORY_TABLES:
            return "SUPPORTED_LEGACY_HISTORY_MIGRATION_AUTHORITY"
        if table in DEVICE_MAINTENANCE_TABLES:
            return "MAINTENANCE_METADATA"
        return ""
    if table in TASK_REPOSITORY_AUTHORITY_TABLES:
        return "TASK_REPOSITORY_SEMANTIC_AUTHORITY"
    if table in TASK_MAINTENANCE_TABLES:
        return "MAINTENANCE_METADATA"
    return ""


def _profile_table(connection: sqlite3.Connection, table: str) -> dict[str, Any]:
    quoted = _quote_identifier(table)
    columns = [dict(row) for row in connection.execute(f"PRAGMA table_info({quoted})")]
    schema_hash = _hash_json(
        [
            {
                "cid": int(row["cid"]),
                "name": str(row["name"]),
                "type": str(row["type"]),
                "notnull": int(row["notnull"]),
                "default_hash": _hash_json(row["dflt_value"]),
                "pk": int(row["pk"]),
            }
            for row in columns
        ]
    )
    names = [str(row["name"]) for row in columns]
    query = "SELECT " + ", ".join(_quote_identifier(name) for name in names) + f" FROM {quoted}"
    count = 0
    xor_value = 0
    sum_value = 0
    modulus = 1 << 256
    for row in connection.execute(query):
        digest = _row_digest(row)
        number = int.from_bytes(digest, "big")
        xor_value ^= number
        sum_value = (sum_value + number) % modulus
        count += 1
    content_hash = hashlib.sha256(
        f"{count}:{xor_value:064x}:{sum_value:064x}".encode("ascii")
    ).hexdigest()
    return {
        "column_count": len(columns),
        "schema_hash": schema_hash,
        "row_count": count,
        "content_hash": content_hash,
    }


def _row_digest(row: sqlite3.Row) -> bytes:
    digest = hashlib.sha256()
    for value in row:
        encoded = _scalar_bytes(value)
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.digest()


def _scalar_bytes(value: Any) -> bytes:
    if value is None:
        return b"n"
    if isinstance(value, bytes):
        return b"b" + value
    if isinstance(value, int):
        return b"i" + str(value).encode("ascii")
    if isinstance(value, float):
        return b"f" + struct.pack("!d", value)
    return b"t" + str(value).encode("utf-8")


def _profile_task_repository(
    database: Path,
    *,
    history_root: Path,
    excluded_task_ids: set[str],
) -> dict[str, Any]:
    repository = _ReadonlyTaskRepository(database, history_root=history_root)
    authority_profile = _profile_task_storage_authority(
        database,
        repository=repository,
        excluded_task_ids=excluded_task_ids,
    )
    try:
        snapshots, snapshot_errors = _read_all_snapshots(
            repository, excluded_task_ids=excluded_task_ids
        )
    except sqlite3.DatabaseError:
        snapshots = []
        snapshot_errors = ["snapshot_result_authority_invalid"]
        _append_storage_authority_error(
            authority_profile, "snapshot_repository_readthrough_invalid"
        )
    task_ids = {snapshot.task_id for snapshot in snapshots}
    with closing(_connect_readonly(database)) as connection:
        if _table_exists(connection, "task_events"):
            task_ids.update(
                str(row[0])
                for row in connection.execute(
                    "SELECT DISTINCT task_id FROM task_events"
                ).fetchall()
            )
    task_ids.difference_update(excluded_task_ids)
    try:
        grouped = repository.list_events_for_tasks(sorted(task_ids)) if task_ids else {}
    except sqlite3.DatabaseError:
        grouped = {}
        snapshot_errors.append("event_result_authority_invalid")
        _append_storage_authority_error(
            authority_profile, "event_repository_readthrough_invalid"
        )
    events, event_errors = _normalized_events(grouped)
    filter_errors = _validate_task_filters(
        repository,
        snapshots,
        events,
        excluded_task_ids=excluded_task_ids,
    )
    errors = sorted(set(snapshot_errors + event_errors + filter_errors))
    snapshot_profile = _snapshot_components(snapshots)
    event_profile = _event_components(events)
    return {
        "status": (
            "PASS"
            if not errors and authority_profile["status"] == "PASS"
            else "FAIL"
        ),
        "excluded_task_count": len(excluded_task_ids),
        "snapshots": snapshot_profile,
        "events": event_profile,
        "storage_authority": authority_profile,
        "aggregate_hash": _hash_json(
            {"snapshots": snapshot_profile, "events": event_profile}
        ),
        "validation_errors": errors,
    }


def _profile_task_storage_authority(
    database: Path,
    *,
    repository: TaskRepository,
    excluded_task_ids: set[str],
) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    errors: Counter[str] = Counter()
    bindings: list[dict[str, Any]] = []
    with closing(_connect_readonly(database)) as connection:
        if _table_exists(connection, "task_results"):
            rows = connection.execute(
                "SELECT * FROM task_results ORDER BY result_id"
            ).fetchall()
            for raw_row in rows:
                row = dict(raw_row)
                if str(row.get("task_id") or "") in excluded_task_ids:
                    continue
                counts["result_rows"] += 1
                try:
                    verified = repository._verified_result_row(row)
                except (KeyError, TypeError, ValueError, sqlite3.DatabaseError):
                    errors["task_result_row_invalid"] += 1
                    continue
                bindings.append(
                    {
                        "kind": "result",
                        "task_id": str(verified["task_id"]),
                        "terminal_event_type": str(
                            verified["terminal_event_type"]
                        ),
                        "sha256": str(verified["sha256"]),
                    }
                )

        snapshot_rows = connection.execute(
            "SELECT task_id, status, result_id, result_hash, "
            "result_summary_json FROM task_snapshots WHERE result_id<>'' "
            "ORDER BY task_id"
        ).fetchall()
        for raw_row in snapshot_rows:
            row = dict(raw_row)
            task_id = str(row["task_id"])
            if task_id in excluded_task_ids:
                continue
            counts["snapshot_refs"] += 1
            verified = _verified_bound_result(
                connection,
                repository=repository,
                result_id=str(row["result_id"]),
                task_id=task_id,
                terminal_event_type=None,
                result_hash=str(row.get("result_hash") or ""),
                errors=errors,
            )
            if verified is None:
                continue
            summary = TaskRepository._json_object(row.get("result_summary_json"))
            if summary and summary != repository._result_summary(
                dict(verified["result"]), byte_size=int(verified["byte_size"])
            ):
                errors["snapshot_result_summary_mismatch"] += 1
                continue
            counts["resolved_snapshot_refs"] += 1
            bindings.append(
                {
                    "kind": "snapshot_ref",
                    "task_id": task_id,
                    "terminal_event_type": str(verified["terminal_event_type"]),
                    "sha256": str(verified["sha256"]),
                }
            )

        event_rows = connection.execute(
            "SELECT sequence, task_id, event_type, payload_json FROM task_events "
            "WHERE payload_json LIKE '%\"result_id\"%' ORDER BY sequence"
        ).fetchall()
        for raw_row in event_rows:
            row = dict(raw_row)
            task_id = str(row["task_id"])
            if task_id in excluded_task_ids:
                continue
            payload = TaskRepository._json_object(row.get("payload_json"))
            result_id = str(payload.get("result_id") or "")
            if not result_id:
                continue
            counts["event_refs"] += 1
            event_type = str(row["event_type"])
            verified = _verified_bound_result(
                connection,
                repository=repository,
                result_id=result_id,
                task_id=task_id,
                terminal_event_type=event_type,
                result_hash=str(payload.get("result_hash") or ""),
                errors=errors,
            )
            if verified is None:
                continue
            full_result = payload.get("result")
            if isinstance(full_result, dict) and repository._canonical_result_json(
                full_result
            ) != str(verified["canonical_json"]):
                errors["event_result_canonical_mismatch"] += 1
                continue
            summary = payload.get("result_summary")
            if isinstance(summary, Mapping) and dict(summary) != (
                repository._result_summary(
                    dict(verified["result"]), byte_size=int(verified["byte_size"])
                )
            ):
                errors["event_result_summary_mismatch"] += 1
                continue
            counts["resolved_event_refs"] += 1
            bindings.append(
                {
                    "kind": "event_ref",
                    "task_id": task_id,
                    "terminal_event_type": event_type,
                    "sha256": str(verified["sha256"]),
                }
            )

    error_names = sorted(errors)
    return {
        "status": "PASS" if not error_names else "FAIL",
        "result_rows": int(counts["result_rows"]),
        "snapshot_refs": int(counts["snapshot_refs"]),
        "event_refs": int(counts["event_refs"]),
        "resolved_snapshot_refs": int(counts["resolved_snapshot_refs"]),
        "resolved_event_refs": int(counts["resolved_event_refs"]),
        "binding_hash": _hash_json(bindings),
        "validation_errors": error_names,
        "validation_error_counts": {
            name: int(errors[name]) for name in error_names
        },
    }


def _verified_bound_result(
    connection: sqlite3.Connection,
    *,
    repository: TaskRepository,
    result_id: str,
    task_id: str,
    terminal_event_type: str | None,
    result_hash: str,
    errors: Counter[str],
) -> dict[str, Any] | None:
    if terminal_event_type is not None and not terminal_event_type:
        errors["result_ref_terminal_event_type_missing"] += 1
        return None
    if not result_hash:
        errors["result_ref_hash_missing"] += 1
        return None
    row = repository._result_row(connection, result_id)
    if row is None:
        errors["result_ref_missing"] += 1
        return None
    try:
        verified = repository._verified_result_row(dict(row))
    except (KeyError, TypeError, ValueError, sqlite3.DatabaseError):
        errors["result_ref_authority_invalid"] += 1
        return None
    if str(verified["task_id"]) != task_id:
        errors["result_ref_task_mismatch"] += 1
        return None
    if terminal_event_type is not None and (
        str(verified["terminal_event_type"]) != terminal_event_type
    ):
        errors["result_ref_terminal_event_type_mismatch"] += 1
        return None
    if str(verified["sha256"]) != result_hash:
        errors["result_ref_hash_mismatch"] += 1
        return None
    return verified


def _append_storage_authority_error(
    profile: dict[str, Any], error: str
) -> None:
    name = str(error)
    errors = {str(value) for value in profile.get("validation_errors", [])}
    errors.add(name)
    counts = {
        str(key): int(value)
        for key, value in dict(
            profile.get("validation_error_counts", {})
        ).items()
    }
    counts[name] = counts.get(name, 0) + 1
    profile["status"] = "FAIL"
    profile["validation_errors"] = sorted(errors)
    profile["validation_error_counts"] = {
        key: counts[key] for key in sorted(counts)
    }


def _read_all_snapshots(
    repository: TaskRepository,
    *,
    excluded_task_ids: set[str],
) -> tuple[list[TaskSnapshot], list[str]]:
    page_size = 1000
    offset = 0
    snapshots: list[TaskSnapshot] = []
    raw_seen = 0
    while True:
        page = repository.list_filtered(
            include_dismissed=True,
            limit=page_size,
            offset=offset,
        )
        raw_seen += len(page)
        snapshots.extend(
            item for item in page if item.task_id not in excluded_task_ids
        )
        if len(page) < page_size:
            break
        offset += len(page)
    expected = repository.count_filtered(include_dismissed=True)
    errors = [] if raw_seen == expected else ["snapshot_pagination_incomplete"]
    if len({item.task_id for item in snapshots}) != len(snapshots):
        errors.append("snapshot_identity_duplicate")
    return snapshots, errors


def _snapshot_components(snapshots: list[TaskSnapshot]) -> dict[str, Any]:
    records = [_snapshot_record(item) for item in snapshots]
    ordered_ids = [str(item["task_id"]) for item in records]
    by_identity = sorted(records, key=lambda item: str(item["task_id"]))
    return {
        "count": len(records),
        "semantic": _component(by_identity),
        "status": _component(
            [{"task_id": item["task_id"], "status": item["status"]} for item in by_identity]
        ),
        "type": _component(
            [{"task_id": item["task_id"], "task_type": item["task_type"]} for item in by_identity]
        ),
        "timestamps": _component(
            [
                {
                    "task_id": item["task_id"],
                    "created_time": item["created_time"],
                    "updated_time": item["updated_time"],
                    "started_time": item["started_time"],
                    "finished_time": item["finished_time"],
                }
                for item in by_identity
            ]
        ),
        "result": _component(
            [
                {
                    "task_id": item["task_id"],
                    "result": item["result"],
                }
                for item in by_identity
            ]
        ),
        "failure": _component(
            [
                {
                    "task_id": item["task_id"],
                    "status": item["status"],
                    "error_message": item["error_message"],
                }
                for item in by_identity
                if item["status"] == TaskState.FAILED.value or item["error_message"]
            ]
        ),
        "artifact_refs": _component(
            [
                {"task_id": item["task_id"], "refs": _artifact_refs(item)}
                for item in by_identity
                if _artifact_refs(item)
            ]
        ),
        "order": {"count": len(ordered_ids), "hash": _hash_json(ordered_ids)},
    }


def _snapshot_record(snapshot: TaskSnapshot) -> dict[str, Any]:
    result = {field.name: getattr(snapshot, field.name) for field in fields(snapshot)}
    result["status"] = snapshot.status.value
    result.pop("result_id", None)
    result.pop("result_hash", None)
    result.pop("result_summary", None)
    return _json_value(result)


def _normalized_events(
    grouped: Mapping[str, list[dict[str, Any]]]
) -> tuple[list[dict[str, Any]], list[str]]:
    events: list[dict[str, Any]] = []
    errors: list[str] = []
    identities: set[str] = set()
    for task_id in sorted(grouped):
        rows = list(grouped[task_id])
        expected = sorted(
            rows,
            key=lambda item: (int(item.get("sequence") or 0), str(item.get("id") or "")),
        )
        if rows != expected:
            errors.append("event_order_invalid")
        for row in rows:
            event_id = str(row.get("id") or "")
            if event_id in identities:
                errors.append("event_identity_duplicate")
            identities.add(event_id)
            events.append(_json_value(dict(row)))
    return events, errors


def _event_components(events: list[dict[str, Any]]) -> dict[str, Any]:
    business_events = [_event_business_record(item) for item in events]
    return {
        "count": len(events),
        "semantic": _component(business_events),
        "type": _component(
            [
                {"id": item.get("id"), "task_id": item.get("task_id"), "type": item.get("type")}
                for item in events
            ]
        ),
        "timestamps": _component(
            [
                {"id": item.get("id"), "task_id": item.get("task_id"), "time": item.get("time")}
                for item in events
            ]
        ),
        "result": _component(
            [
                {
                    "id": item.get("id"),
                    "result_fields": _selected_fields(
                        item.get("payload"),
                        {"result"},
                    ),
                }
                for item in business_events
            ]
        ),
        "failure": _component(
            [
                {"id": item.get("id"), "payload": item.get("payload")}
                for item in business_events
                if str(item.get("type") or "").casefold() in {"error", "failed"}
                or _selected_fields(item.get("payload"), {"error", "error_message"})
            ]
        ),
        "artifact_refs": _component(
            [
                {"id": item.get("id"), "refs": _artifact_refs(item.get("payload"))}
                for item in business_events
                if _artifact_refs(item.get("payload"))
            ]
        ),
        "order": {
            "count": len(events),
            "hash": _hash_json(
                [
                    {
                        "task_id": item.get("task_id"),
                        "sequence": item.get("sequence"),
                        "id": item.get("id"),
                    }
                    for item in events
                ]
            ),
        },
    }


def _event_business_record(event: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(event)
    payload = result.get("payload")
    if isinstance(payload, Mapping):
        business_payload = dict(payload)
        business_payload.pop("result_id", None)
        business_payload.pop("result_hash", None)
        business_payload.pop("result_summary", None)
        result["payload"] = business_payload
    return result


def _validate_task_filters(
    repository: TaskRepository,
    snapshots: list[TaskSnapshot],
    events: list[dict[str, Any]],
    *,
    excluded_task_ids: set[str],
) -> list[str]:
    errors: list[str] = []
    if snapshots:
        selected_statuses = set(sorted({item.status for item in snapshots}, key=lambda value: value.value)[::2])
        if selected_statuses:
            actual, _ = _read_filtered_snapshots(
                repository,
                excluded_task_ids=excluded_task_ids,
                statuses=selected_statuses,
            )
            expected = [item.task_id for item in snapshots if item.status in selected_statuses]
            if actual != expected:
                errors.append("snapshot_status_filter_mismatch")
        selected_types = sorted({item.task_type for item in snapshots})[::2]
        if selected_types:
            actual, _ = _read_filtered_snapshots(
                repository,
                excluded_task_ids=excluded_task_ids,
                task_types=selected_types,
            )
            expected = [item.task_id for item in snapshots if item.task_type in selected_types]
            if actual != expected:
                errors.append("snapshot_type_filter_mismatch")
    event_types = sorted({str(item.get("type") or "") for item in events})[::2]
    task_ids = sorted({str(item.get("task_id") or "") for item in events})
    if event_types and task_ids:
        grouped = repository.list_events_for_tasks(task_ids, event_types=event_types)
        actual, order_errors = _normalized_events(grouped)
        if order_errors:
            errors.append("event_filter_order_invalid")
        expected = [item for item in events if str(item.get("type") or "") in event_types]
        if _component(actual) != _component(expected):
            errors.append("event_type_filter_mismatch")
    return errors


def _read_filtered_snapshots(
    repository: TaskRepository,
    *,
    excluded_task_ids: set[str],
    **filters: Any,
) -> tuple[list[str], int]:
    offset = 0
    task_ids: list[str] = []
    while True:
        page = repository.list_filtered(
            include_dismissed=True,
            limit=1000,
            offset=offset,
            **filters,
        )
        task_ids.extend(
            item.task_id for item in page if item.task_id not in excluded_task_ids
        )
        if len(page) < 1000:
            break
        offset += len(page)
    return task_ids, len(task_ids)


def _profile_history_evidence(directory: Path) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in sorted(directory.rglob("*.json")):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            errors.append("invalid_json_evidence")
            continue
        for pointer, item in _walk_json_objects(value):
            kind = _parity_kind(path, item, pointer=pointer)
            if not kind:
                continue
            status = str(item.get("result") or item.get("status") or "").upper()
            records.append(
                {
                    "kind": kind,
                    "status": status,
                    "path": str(path),
                    "json_pointer": pointer,
                    "record_hash": _hash_json(item),
                }
            )
    records.sort(key=lambda item: (item["path"], item["json_pointer"], item["kind"]))
    failed = [item for item in records if item["status"] != "PASS"]
    if not records:
        errors.append("parity_evidence_missing")
    if failed:
        errors.append("parity_evidence_not_pass")
    return {
        "status": "PASS" if not errors else "FAIL",
        "record_count": len(records),
        "passed_count": len(records) - len(failed),
        "failed_count": len(failed),
        "migration_parity_count": sum(item["kind"] == "MIGRATION_PARITY" for item in records),
        "post_replace_parity_count": sum(item["kind"] == "POST_REPLACE_PARITY" for item in records),
        "aggregate_hash": _hash_json(records),
        "records": records,
        "validation_errors": sorted(set(errors)),
    }


def _walk_json_objects(value: Any, pointer: str = "$") -> Iterable[tuple[str, Mapping[str, Any]]]:
    if isinstance(value, Mapping):
        yield pointer, value
        for key, item in value.items():
            yield from _walk_json_objects(item, f"{pointer}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk_json_objects(item, f"{pointer}[{index}]")


def _parity_kind(
    path: Path, value: Mapping[str, Any], *, pointer: str
) -> str:
    marker = " ".join(
        [
            path.stem,
            *(str(value.get(key) or "") for key in ("phase", "stage", "check_id", "test_id", "name", "kind", "format")),
        ]
    ).upper().replace("-", "_")
    has_status = "result" in value or "status" in value
    node_marker = " ".join(
        str(value.get(key) or "")
        for key in ("phase", "stage", "check_id", "test_id", "name", "kind", "format")
    ).upper().replace("-", "_")
    if has_status and "POST_REPLACE" in marker and "PARITY" in marker and (
        pointer == "$" or "POST_REPLACE" in node_marker
    ):
        return "POST_REPLACE_PARITY"
    source_table = str(value.get("source_table") or "")
    if has_status and (
        source_table in LEGACY_HISTORY_TABLES
        or (
            pointer == "$"
            and "MIGRATION" in marker
            and "PARITY" in marker
            and any(
                key in value
                for key in (
                    "expected_count",
                    "actual_count",
                    "month_counts",
                    "projection_duplicate",
                )
            )
        )
    ):
        return "MIGRATION_PARITY"
    return ""


def _resolve_history_root(tasks_database: Path, evidence_dir: Path) -> Path:
    candidates = [tasks_database.parent / "history", evidence_dir, evidence_dir / "history"]
    for candidate in candidates:
        if (candidate / "catalog.db").is_file():
            return candidate.resolve()
    discovered = sorted(path.parent.resolve() for path in evidence_dir.rglob("catalog.db"))
    unique = list(dict.fromkeys(discovered))
    if len(unique) > 1:
        raise FunctionalCompatibilityError(
            "history evidence contains multiple catalog roots"
        )
    return unique[0] if unique else (tasks_database.parent / "history").resolve()


def _component(values: Iterable[Any]) -> dict[str, Any]:
    hashes = sorted(_hash_json(value) for value in values)
    return {"count": len(hashes), "hash": _hash_json(hashes)}


def _selected_fields(value: Any, names: set[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in value.items() if str(key) in names}


def _artifact_refs(value: Any, prefix: str = "$") -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if isinstance(value, Mapping):
        for key in sorted(value, key=str):
            item = value[key]
            name = str(key)
            path = f"{prefix}.{name}"
            if "artifact" in name.casefold() or name.casefold() == "result_path":
                result.append({"field": path, "value": _json_value(item)})
            result.extend(_artifact_refs(item, path))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            result.extend(_artifact_refs(item, f"{prefix}[{index}]"))
    return result


def _public_profile_summary(profile: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "quick_check",
        "database_size_bytes",
        "database_sha256",
        "business_table_count",
        "business_row_count",
        "aggregate_hash",
        "record_count",
        "passed_count",
        "failed_count",
        "migration_parity_count",
        "post_replace_parity_count",
        "excluded_task_count",
    )
    summary = {key: profile[key] for key in keys if key in profile}
    for area in ("snapshots", "events"):
        if area in profile:
            summary[area] = {
                "count": int(profile[area].get("count") or 0),
                "semantic_hash": str(profile[area].get("semantic", {}).get("hash") or ""),
                "order_hash": str(profile[area].get("order", {}).get("hash") or ""),
            }
    authority = profile.get("storage_authority")
    if isinstance(authority, Mapping):
        summary["storage_authority"] = {
            "status": str(authority.get("status") or "FAIL"),
            "result_rows": int(authority.get("result_rows") or 0),
            "snapshot_refs": int(authority.get("snapshot_refs") or 0),
            "event_refs": int(authority.get("event_refs") or 0),
            "resolved_snapshot_refs": int(
                authority.get("resolved_snapshot_refs") or 0
            ),
            "resolved_event_refs": int(authority.get("resolved_event_refs") or 0),
            "binding_hash": str(authority.get("binding_hash") or ""),
            "validation_error_count": len(
                authority.get("validation_errors", [])
            ),
        }
    summary["validation_error_count"] = len(profile.get("validation_errors", []))
    return summary


def _difference_summary(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Mapping):
        result = {key: value[key] for key in ("column_count", "row_count", "schema_hash", "content_hash", "count", "hash") if key in value}
        return result or {"hash": _hash_json(value)}
    if isinstance(value, (list, tuple, set)):
        return {"count": len(value), "hash": _hash_json(value)}
    return {"hash": _hash_json(value)}


def _checks_summary(checks: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    passed = sum(item.get("status") == "PASS" for item in checks)
    failed = len(checks) - passed
    return {
        "check_count": len(checks),
        "passed_count": passed,
        "failed_count": failed,
        "aggregate_hash": _hash_json(
            [{"id": item.get("id"), "status": item.get("status")} for item in checks]
        ),
    }


def _validated_input_file(path: Path, root: Path) -> Path:
    candidate = _validated_development_path(path, root, strict=True)
    if Path(path).is_symlink() or not candidate.is_file() or candidate.stat().st_size <= 0:
        raise FunctionalCompatibilityError(f"input database is missing or unsafe: {candidate}")
    return candidate


def _validated_input_directory(path: Path, root: Path) -> Path:
    candidate = _validated_development_path(path, root, strict=True)
    if Path(path).is_symlink() or not candidate.is_dir():
        raise FunctionalCompatibilityError(f"evidence directory is missing or unsafe: {candidate}")
    return candidate


def _validated_output_directory(
    path: Path,
    *,
    development_root: Path,
    evidence_directories: Sequence[Path],
) -> Path:
    candidate = _validated_development_path(path, development_root, strict=False)
    original = Path(path)
    if original.exists() and (original.is_symlink() or not original.is_dir()):
        raise FunctionalCompatibilityError(f"output directory is unsafe: {candidate}")
    for evidence in evidence_directories:
        if _overlaps(candidate, evidence):
            raise FunctionalCompatibilityError(
                "output directory must not overlap history evidence"
            )
    return candidate


def _validated_development_path(path: Path, root: Path, *, strict: bool) -> Path:
    candidate = Path(path).resolve(strict=strict)
    if candidate == root:
        raise FunctionalCompatibilityError("development root itself is not a valid path")
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise FunctionalCompatibilityError(
            f"path must remain below development root {root}: {candidate}"
        ) from exc
    return candidate


def _overlaps(left: Path, right: Path) -> bool:
    try:
        left.relative_to(right)
        return True
    except ValueError:
        pass
    try:
        right.relative_to(left)
        return True
    except ValueError:
        return False


def _connect_readonly(path: Path) -> sqlite3.Connection:
    wal_path = path.with_name(f"{path.name}-wal")
    if wal_path.is_file() and wal_path.stat().st_size > 0:
        raise FunctionalCompatibilityError(
            f"functional compatibility input has a non-empty WAL: {path}"
        )
    connection = sqlite3.connect(
        f"{path.resolve().as_uri()}?mode=ro&immutable=1",
        uri=True,
        timeout=DEFAULT_SQLITE_TIMEOUT_SECONDS,
    )
    connection.row_factory = sqlite3.Row
    configure_sqlite_connection(
        connection,
        busy_timeout_ms=DEFAULT_SQLITE_BUSY_TIMEOUT_MS,
        foreign_keys=True,
    )
    connection.execute("PRAGMA query_only = ON")
    return connection


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_schema WHERE type='table' AND name=?", (table,)
        ).fetchone()
        is not None
    )


def _quote_identifier(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(key): _json_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, bytes):
        return {"byte_count": len(value), "sha256": hashlib.sha256(value).hexdigest()}
    if isinstance(value, Path):
        return str(value)
    return value


def _hash_json(value: Any) -> str:
    encoded = json.dumps(
        _json_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _evidence_binding(script: Path) -> dict[str, str]:
    repository = script.parents[2]
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return {
        "git_head": completed.stdout.strip().casefold(),
        "script_path": script.relative_to(repository).as_posix(),
        "script_sha256": _sha256_file(script),
    }


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _atomic_publish_json(
    paths: Mapping[str, Path],
    payloads: Mapping[str, Mapping[str, Any]],
    *,
    overwrite: bool,
) -> None:
    destination = next(iter(paths.values())).parent
    destination.mkdir(parents=True, exist_ok=True)
    temporary_paths: dict[str, Path] = {}
    try:
        for name, target in paths.items():
            temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
            with temporary.open("xb") as stream:
                stream.write(_json_bytes(payloads[name]))
                stream.flush()
                os.fsync(stream.fileno())
            temporary_paths[name] = temporary
        for name, target in paths.items():
            temporary = temporary_paths[name]
            if overwrite:
                os.replace(temporary, target)
            else:
                os.link(temporary, target)
                temporary.unlink()
    finally:
        for temporary in temporary_paths.values():
            temporary.unlink(missing_ok=True)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before-devices", type=Path, required=True)
    parser.add_argument("--after-devices", type=Path, required=True)
    parser.add_argument("--before-tasks", type=Path, required=True)
    parser.add_argument("--after-tasks", type=Path, required=True)
    parser.add_argument("--before-history-evidence", type=Path, required=True)
    parser.add_argument("--after-history-evidence", type=Path, required=True)
    parser.add_argument("--before-consumer-observations", type=Path, required=True)
    parser.add_argument("--after-consumer-observations", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--development-root", type=Path, default=DEFAULT_DEVELOPMENT_ROOT
    )
    parser.add_argument("--exclude-task-id", action="append", default=[])
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    excluded = set(DEFAULT_EXCLUDED_TASK_IDS)
    excluded.update(str(value) for value in args.exclude_task_id)
    result = validate_database_functional_compatibility(
        before_devices=args.before_devices,
        after_devices=args.after_devices,
        before_tasks=args.before_tasks,
        after_tasks=args.after_tasks,
        before_history_evidence=args.before_history_evidence,
        after_history_evidence=args.after_history_evidence,
        before_consumer_observations=args.before_consumer_observations,
        after_consumer_observations=args.after_consumer_observations,
        output_dir=args.output_dir,
        development_root=args.development_root,
        excluded_task_ids=excluded,
        overwrite=args.overwrite,
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "outputs": {
                    key: str(value) for key, value in result["outputs"].items()
                },
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
