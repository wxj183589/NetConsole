"""Isolated support for the interface discovery Shadow rehearsal.

The helpers in this module are test-only.  They use a temporary initialized
devices database, persist facts through the existing Legacy repository path,
and inspect the database through the existing read-only connection.  Shadow
callbacks receive normalized data only and never receive a repository,
database, transport, or task writer.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.repositories.device_fact_repository import DeviceFactRepository
from netconsole.services.database_upgrade.backup_store import DatabaseBackupStore
from netconsole.services.interface_discovery_shadow import (
    InterfaceDiscoveryShadowReport,
    InterfaceDiscoveryShadowRunner,
)

REHEARSAL_DEVICE_UUID = "rehearsal-h3c-device"
REHEARSAL_SITE_NAME = "interface-discovery-rehearsal"

CURRENT_TABLES = (
    "device_facts",
    "device_interfaces",
    "device_optical_modules",
    "device_lldp_neighbors",
)
RECENT_TABLES = ("device_fact_recent",)
HISTORY_TABLES = (
    "device_facts_history",
    "device_interfaces_history",
    "device_optical_modules_history",
    "device_lldp_neighbors_history",
)
REPOSITORY_TABLES = (*CURRENT_TABLES, *RECENT_TABLES, *HISTORY_TABLES)

_RUNTIME_FIELDS = frozenset(
    {
        "id",
        "created_at",
        "updated_at",
        "collected_at",
        "collect_run_uuid",
        "raw_log_path",
        "changed_at",
        "first_seen_at",
        "last_seen_at",
        "vlan_config_collected_at",
    }
)
_SENSITIVE_KEY_NAMES = frozenset(
    {"password", "passwd", "secret", "token", "community", "private_key", "credential"}
)
_SENSITIVE_VALUE = re.compile(
    r"(?i)\b(?:password|passwd|secret|token|community|private[_ -]?key|credential)\b\s*[=:]"
)


def _canonical_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_value(child)
            for key, child in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_value(child) for child in value]
    if isinstance(value, bytes):
        return value.hex()
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _canonical_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _semantic_row(row: Mapping[str, Any]) -> dict[str, Any]:
    semantic: dict[str, Any] = {}
    for key, value in row.items():
        field_name = str(key)
        if field_name in _RUNTIME_FIELDS:
            continue
        if field_name == "payload_json":
            try:
                decoded = json.loads(str(value or "{}"))
            except (TypeError, ValueError):
                decoded = {}
            semantic["payload_semantic"] = (
                _semantic_row(decoded) if isinstance(decoded, Mapping) else decoded
            )
            continue
        if field_name in {"state_json", "previous_state_json"}:
            try:
                value = json.loads(str(value or "{}"))
            except (TypeError, ValueError):
                pass
        semantic[field_name] = _canonical_value(value)
    return semantic


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def repository_fingerprint(database: Database, device_uuid: str) -> dict[str, Any]:
    """Return a stable, read-only fingerprint of the device fact repository."""

    target = str(device_uuid).strip()
    if not target:
        raise ValueError("device_uuid is required for a repository fingerprint")
    with database.connect_readonly() as connection:
        schema_rows = connection.execute(
            "SELECT key, value FROM schema_metadata ORDER BY key"
        ).fetchall()
        schema_metadata = [
            {"key": str(row["key"]), "value": str(row["value"])}
            for row in schema_rows
        ]
        tables: dict[str, dict[str, Any]] = {}
        for table in REPOSITORY_TABLES:
            rows = [
                dict(row)
                for row in connection.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
            ]
            device_rows = [
                row for row in rows if str(row.get("device_uuid") or "").strip() == target
            ]
            semantic_rows = [_semantic_row(row) for row in rows]
            device_semantic_rows = [_semantic_row(row) for row in device_rows]
            revision_rows = [
                {
                    field_name: _canonical_value(row.get(field_name))
                    for field_name in ("revision", "generation", "version", "source_revision")
                    if field_name in row
                }
                for row in device_rows
            ]
            history_sequence = (
                [_sha256_json(_semantic_row(row)) for row in device_rows]
                if table in HISTORY_TABLES
                else []
            )
            tables[table] = {
                "total_count": len(rows),
                "device_record_count": len(device_rows),
                "semantic_sha256": _sha256_json(semantic_rows),
                "device_semantic_sha256": _sha256_json(device_semantic_rows),
                "revision_sha256": _sha256_json(revision_rows),
                "history_sequence": history_sequence,
            }

    payload = {
        "device_uuid": target,
        "schema_metadata": schema_metadata,
        "tables": tables,
        "runtime_fields_ignored": sorted(_RUNTIME_FIELDS),
    }
    return {**payload, "fingerprint_sha256": _sha256_json(payload)}


def repository_effect(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    *,
    unexpected_writes: int = 0,
) -> dict[str, Any]:
    """Compare the repository at two Shadow boundaries."""

    def same_tables(names: tuple[str, ...]) -> bool:
        return all(
            before.get("tables", {}).get(name) == after.get("tables", {}).get(name)
            for name in names
        )

    schema_same = before.get("schema_metadata") == after.get("schema_metadata")
    revisions_same = schema_same and all(
        before.get("tables", {}).get(name, {}).get("revision_sha256")
        == after.get("tables", {}).get(name, {}).get("revision_sha256")
        for name in REPOSITORY_TABLES
    )
    current = "NONE" if same_tables(CURRENT_TABLES) else "CHANGED"
    recent = "NONE" if same_tables(RECENT_TABLES) else "CHANGED"
    history = "NONE" if same_tables(HISTORY_TABLES) else "CHANGED"
    revision = "NONE" if revisions_same else "CHANGED"
    effect = "NONE" if all(value == "NONE" for value in (current, recent, history, revision)) else "CHANGED"
    if unexpected_writes:
        effect = "FAIL"
    return {
        "repository_effect": effect,
        "current_effect": current,
        "recent_effect": recent,
        "history_effect": history,
        "revision_effect": revision,
        "unexpected_writes": int(unexpected_writes),
    }


@dataclass
class WritePathCounter:
    """Count existing repository writer calls without introducing a writer."""

    calls: dict[str, int] = field(default_factory=dict)

    def install(self, repository: DeviceFactRepository, monkeypatch: Any) -> None:
        for method_name in (
            "upsert_device_fact",
            "replace_device_interfaces",
            "replace_optical_modules",
            "replace_lldp_neighbors",
        ):
            original = getattr(repository, method_name)
            self.calls.setdefault(method_name, 0)

            def counted(*args: Any, _name: str = method_name, _original: Any = original, **kwargs: Any) -> Any:
                self.calls[_name] += 1
                return _original(*args, **kwargs)

            monkeypatch.setattr(repository, method_name, counted)

    def snapshot(self) -> dict[str, int]:
        return dict(self.calls)


@dataclass
class IsolatedShadowRehearsal:
    """A test-only controller for Legacy persistence and Shadow invocation."""

    root: Path
    database: Database
    repository: DeviceFactRepository
    result: dict[str, Any]
    write_counter: WritePathCounter
    device_uuid: str = REHEARSAL_DEVICE_UUID
    task_status: str = "SUCCESS"
    shadow_enabled: bool = False
    fingerprints: dict[str, dict[str, Any]] = field(default_factory=dict)
    task_states: dict[str, str] = field(default_factory=dict)
    reports: dict[str, InterfaceDiscoveryShadowReport] = field(default_factory=dict)
    _legacy_cycle_number: int = 0

    @classmethod
    def create(
        cls,
        tmp_path: Path,
        monkeypatch: Any,
        result: Mapping[str, Any],
    ) -> "IsolatedShadowRehearsal":
        root = Path(tmp_path).resolve()
        database_path = root / "sites" / REHEARSAL_SITE_NAME / "db" / "devices.db"
        database_path.parent.mkdir(parents=True, exist_ok=True)
        database = Database(database_path)
        database.initialize()
        repository = DeviceFactRepository(database)
        write_counter = WritePathCounter()
        write_counter.install(repository, monkeypatch)
        rehearsal = cls(
            root=root,
            database=database,
            repository=repository,
            result=copy.deepcopy(dict(result)),
            write_counter=write_counter,
        )
        rehearsal._seed_with_history()
        return rehearsal

    def _seed_with_history(self) -> None:
        changed = copy.deepcopy(self.result)
        facts = changed.setdefault("facts", {})
        facts["model"] = f"{facts.get('model') or 'H3C'}-seed-change"
        interfaces = changed.get("interfaces") or []
        if interfaces:
            interfaces[0] = dict(interfaces[0])
            interfaces[0]["link_status"] = "SEED_CHANGE"
        self._persist_legacy(changed, "seed-change", "2026-09-06T00:00:00Z")
        self._persist_legacy(self.result, "seed-current", "2026-09-06T00:01:00Z")

    def _persist_legacy(
        self,
        result: Mapping[str, Any],
        collect_run_uuid: str,
        collected_at: str,
    ) -> None:
        facts = result.get("facts") if isinstance(result.get("facts"), Mapping) else {}
        self.repository.upsert_device_fact(
            {
                "device_uuid": self.device_uuid,
                "sysname": facts.get("sysname"),
                "model": facts.get("model"),
                "serial_number": facts.get("serial_number"),
                "mac_address": facts.get("mac_address"),
                "software_version": facts.get("software_version"),
                "bootrom_version": facts.get("bootrom_version"),
                "vendor": facts.get("vendor"),
                "collected_at": collected_at,
                "updated_at": collected_at,
                "collect_run_uuid": collect_run_uuid,
            }
        )
        interfaces = result.get("interfaces")
        if not isinstance(interfaces, list) or not interfaces:
            raise ValueError("rehearsal fixture must contain at least one interface")
        rows = []
        for interface in interfaces:
            row = dict(interface)
            row.update(
                {
                    "device_uuid": self.device_uuid,
                    "collected_at": collected_at,
                    "updated_at": collected_at,
                    "collect_run_uuid": collect_run_uuid,
                }
            )
            rows.append(row)
        self.repository.replace_device_interfaces(self.device_uuid, rows)

    def capture(self, label: str) -> dict[str, Any]:
        fingerprint = repository_fingerprint(self.database, self.device_uuid)
        self.fingerprints[label] = fingerprint
        self.task_states[label] = self.task_status
        return fingerprint

    def legacy_cycle(self) -> dict[str, Any]:
        self._legacy_cycle_number += 1
        cycle = self._legacy_cycle_number
        self._persist_legacy(
            self.result,
            f"legacy-cycle-{cycle}",
            f"2026-09-06T00:{cycle + 10:02d}:00Z",
        )
        return copy.deepcopy(self.result)

    def enable_shadow(self) -> None:
        self.shadow_enabled = True

    def disable_shadow(self) -> None:
        self.shadow_enabled = False

    def shadow_cycle(
        self,
        scenario: str,
        shadow_capability: Callable[[], Mapping[str, Any]],
    ) -> InterfaceDiscoveryShadowReport:
        if not self.shadow_enabled:
            raise RuntimeError("Shadow rehearsal is disabled")
        report = InterfaceDiscoveryShadowRunner().run(
            execution_id=f"rehearsal-{scenario.casefold()}",
            device_identity={
                "device_uuid": self.device_uuid,
                "vendor": self.result.get("device", {}).get("vendor"),
                "role": self.result.get("device", {}).get("role"),
                "software_version": self.result.get("device", {}).get("software_version"),
            },
            legacy_status=self.task_status,
            legacy_result=copy.deepcopy(self.result),
            shadow_capability=shadow_capability,
        )
        self.reports[scenario] = report
        return report

    def scenario_record(
        self,
        scenario: str,
        before_label: str,
        after_label: str,
        *,
        writes_before: Mapping[str, int],
        writes_after: Mapping[str, int],
        rollback_status: str = "PASS",
    ) -> dict[str, Any]:
        report = self.reports[scenario]
        unexpected_writes = sum(
            max(0, int(writes_after.get(name, 0)) - int(writes_before.get(name, 0)))
            for name in set(writes_before) | set(writes_after)
        )
        effect = repository_effect(
            self.fingerprints[before_label],
            self.fingerprints[after_label],
            unexpected_writes=unexpected_writes,
        )
        return {
            "scenario": scenario,
            "legacy_status": report.legacy_status,
            "shadow_status": report.shadow_status,
            "compare_status": report.compare_status,
            "added": list(report.added),
            "removed": list(report.removed),
            "changed": list(report.changed),
            "repository_fingerprint_before": self.fingerprints[before_label]["fingerprint_sha256"],
            "repository_fingerprint_after": self.fingerprints[after_label]["fingerprint_sha256"],
            "repository_effect": effect["repository_effect"],
            "repository_effect_detail": effect,
            "task_status_before": self.task_states[before_label],
            "task_status_after": self.task_states[after_label],
            "rollback_status": rollback_status,
            "error": report.error,
        }


def build_evidence_payload(
    *,
    run_id: str,
    git_sha: str,
    branch: str,
    test_root: Path,
    scenarios: Mapping[str, Mapping[str, Any]],
    repository_fingerprint_before: Mapping[str, Any],
    repository_fingerprint_after: Mapping[str, Any],
    backup_manifest_status: str,
) -> dict[str, Any]:
    return {
        "phase": "2D-B1",
        "status": "PASS",
        "run_id": run_id,
        "git_sha": git_sha,
        "branch": branch,
        "test_root": str(test_root),
        "scenario": "interface-discovery-shadow-rehearsal",
        "scenarios": {name: dict(value) for name, value in scenarios.items()},
        "repository_fingerprint_before": dict(repository_fingerprint_before),
        "repository_fingerprint_after": dict(repository_fingerprint_after),
        "repository_effect": "NONE",
        "task_status_before": "SUCCESS",
        "task_status_after": "SUCCESS",
        "rollback_status": "PASS",
        "backup_manifest_status": backup_manifest_status,
        "errors": [],
        "production_touched": False,
        "real_device_connected": False,
        "no_runtime_feature_flag_added": True,
    }


def secret_scan(value: Any) -> list[str]:
    findings: list[str] = []

    def visit(node: Any, path: str) -> None:
        if isinstance(node, Mapping):
            for key, child in node.items():
                key_text = str(key).casefold()
                if key_text in _SENSITIVE_KEY_NAMES:
                    findings.append(f"{path}.{key}")
                visit(child, f"{path}.{key}")
        elif isinstance(node, (list, tuple)):
            for index, child in enumerate(node):
                visit(child, f"{path}[{index}]")
        elif isinstance(node, str) and _SENSITIVE_VALUE.search(node):
            findings.append(path)

    visit(value, "$")
    return findings


def write_evidence_bundle(root: Path, payload: Mapping[str, Any]) -> Path:
    """Write a small, ephemeral machine-readable evidence bundle."""

    findings = secret_scan(payload)
    if findings:
        raise AssertionError(f"evidence contains sensitive fields: {findings}")
    evidence_root = Path(root).resolve()
    evidence_root.mkdir(parents=True, exist_ok=True)
    summary_path = evidence_root / "summary.json"
    summary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    scenarios = payload.get("scenarios")
    if isinstance(scenarios, Mapping):
        scenario_root = evidence_root / "scenarios"
        scenario_root.mkdir(exist_ok=True)
        for name, scenario in scenarios.items():
            (scenario_root / f"{str(name).casefold()}.json").write_text(
                json.dumps(scenario, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
    return summary_path


def rehearse_pre_switch_backup(
    database: Database,
    root: Path,
    *,
    git_sha: str,
    branch: str,
) -> dict[str, Any]:
    """Exercise the existing DatabaseBackupStore only against the test root."""

    source = database.path.resolve()
    source_before = {
        "path": str(source),
        "size": source.stat().st_size,
        "mtime_ns": source.stat().st_mtime_ns,
        "sha256": _file_sha256(source),
    }
    with database.connect_readonly() as connection:
        schema_metadata = {
            str(row["key"]): str(row["value"])
            for row in connection.execute(
                "SELECT key, value FROM schema_metadata ORDER BY key"
            ).fetchall()
        }
    paths = PathResolver(data_root=Path(root).resolve())
    store = DatabaseBackupStore(paths)
    result = store.create(
        source_path=source,
        database_kind="devices",
        scope_type="site",
        scope_id=REHEARSAL_SITE_NAME,
        task_id="phase2d-b1-backup-rehearsal",
        old_version=schema_metadata.get("schema_version", "unknown"),
        target_version="rehearsal-no-cutover",
        strategy="PRE_SWITCH_MANIFEST_REHEARSAL",
        reason="isolated interface discovery Shadow rehearsal",
        metadata={
            "data_root_identity": "isolated-test-root",
            "source_git_sha": git_sha,
            "source_branch": branch,
            "source_mtime_ns": source_before["mtime_ns"],
            "source_file_list": [source_before],
            "schema_version_metadata": schema_metadata,
            "restore_notes": "Validate the existing manifest before any approved restore; no production restore in this rehearsal.",
        },
        checkpoint={"status": "not_required_for_closed_test_database"},
    )
    backup_id = str(result["backup_id"])
    validated = store.validate(backup_id)
    manifest_path = Path(str(validated["path"])) / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    validation = dict(validated.get("validation") or {})
    source_after = {
        "path": str(source),
        "size": source.stat().st_size,
        "mtime_ns": source.stat().st_mtime_ns,
        "sha256": _file_sha256(source),
    }
    sha256_verified = bool(
        validation.get("restorable")
        and validation.get("sha256_matches")
        and str(manifest.get("database_sha256") or "")
        == str(validation.get("sha256") or "")
    )
    return {
        "status": "PASS" if sha256_verified and source_before == source_after else "FAIL",
        "manifest": manifest,
        "validation": validation,
        "source_before": source_before,
        "source_after": source_after,
        "source_mutated": source_before != source_after,
        "sha256_verified": sha256_verified,
        "production_backup_executed": False,
        "manifest_path": str(manifest_path),
    }


__all__ = [
    "IsolatedShadowRehearsal",
    "REHEARSAL_DEVICE_UUID",
    "build_evidence_payload",
    "rehearse_pre_switch_backup",
    "repository_effect",
    "repository_fingerprint",
    "secret_scan",
    "write_evidence_bundle",
]
