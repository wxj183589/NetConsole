"""Finalize a read-only site storage inventory against the storage registry.

The raw inventory is immutable evidence.  This module adds ownership and
lifecycle decisions only when a registry path has exactly one match.  Missing
or ambiguous matches fail closed to UNKNOWN/PROTECT.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


OUTPUT_FILENAMES = (
    "SITE_STORAGE_INVENTORY.json",
    "DATABASE_OWNER_MAP.json",
    "STORAGE_DUPLICATION_AUDIT.json",
    "STORAGE_LIFECYCLE_PLAN.json",
    "DATA_LIFECYCLE_CLASSIFICATION.json",
    "SITE_STORAGE_FOOTPRINT.json",
)
UNKNOWN_CLASS = "UNKNOWN"
UNKNOWN_POLICY = "PROTECT"
SITE_INVENTORY_SCOPE = "SITE_ROOT"
GLOBAL_INVENTORY_SCOPE = "DATA_ROOT_GLOBAL_EXCLUDING_SITES"
DEFAULT_DEVELOPMENT_ROOT = Path("D:/study")
_STORAGE_REPORT_SECTIONS = (
    "Operational DBs",
    "History DBs/shards",
    "Ground/Unattended",
    "Online MR",
    "MR Raw/MESH",
    "Syslog/Ping",
    "Analysis",
    "Site Package staging",
    "Cache/temp",
    "Backups",
    "Artifacts/raw",
    "Unknown/protected",
)

_REQUIRED_REGISTRY_FIELDS = {
    "id",
    "relative_path",
    "owner",
    "data_type",
    "authority",
    "producer",
    "consumers",
    "retention_owner",
    "rebuildable",
    "site_package_policy",
    "backup_policy",
    "migration_policy",
    "schema_version",
    "allowed_data_classes",
    "forbidden_data_classes",
    "source_locations",
}
_REQUIRED_TABLE_RULE_FIELDS = {
    "tables",
    "data_class",
    "authority",
    "producer",
    "consumers",
    "lifecycle_owner",
    "rebuildable",
    "source_locations",
}


class StorageAuditError(ValueError):
    """Raised when evidence, registry, or an output boundary is invalid."""


def finalize_site_storage_audit(
    *,
    raw_inventory_path: Path,
    registry_path: Path,
    output_dir: Path,
    repo_root: Path | None = None,
    development_root: Path = DEFAULT_DEVELOPMENT_ROOT,
    global_inventory_path: Path | None = None,
    optimization_impact_path: Path | None = None,
    final_mode: bool = False,
    overwrite: bool = False,
) -> dict[str, Path]:
    """Build the six deterministic storage-audit artifacts.

    No SQLite database is opened by this function.  The only writes are the
    six JSON files below ``output_dir`` after all output boundaries and
    overwrite conditions have passed preflight validation.
    """

    if final_mode:
        missing = [
            name
            for name, value in (
                ("global_inventory_path", global_inventory_path),
                ("optimization_impact_path", optimization_impact_path),
            )
            if value is None
        ]
        if missing:
            raise StorageAuditError(
                "final mode requires complete global inventory and optimization impact "
                "evidence; missing: " + ", ".join(missing)
            )

    raw_path = raw_inventory_path.resolve(strict=True)
    registry_file = registry_path.resolve(strict=True)
    root = (repo_root or Path(__file__).resolve().parents[2]).resolve(strict=True)
    raw = _load_json_object(raw_path, label="raw inventory")
    registry = _load_json_object(registry_file, label="storage registry")
    _validate_raw_inventory(raw)
    global_raw_path = (
        global_inventory_path.resolve(strict=True)
        if global_inventory_path is not None
        else None
    )
    global_raw = (
        _load_json_object(global_raw_path, label="global raw inventory")
        if global_raw_path is not None
        else None
    )
    if global_raw is not None:
        _validate_raw_inventory(global_raw)
        _validate_global_inventory(global_raw)
    combined_raw = _merge_raw_inventories(raw, global_raw)
    stores = _validate_registry(registry)
    destination = _validate_output_directory(
        output_dir,
        site_root=Path(str(raw["site_root"])),
        development_root=development_root,
    )
    output_paths = {name: destination / name for name in OUTPUT_FILENAMES}
    existing = sorted(path.name for path in output_paths.values() if path.exists())
    if existing and not overwrite:
        raise StorageAuditError(
            "refusing to overwrite existing audit outputs: " + ", ".join(existing)
        )

    registry_sha256 = _sha256_file(registry_file)
    raw_sha256 = _sha256_file(raw_path)
    optimization_impact = (
        _load_optimization_impact(
            optimization_impact_path.resolve(strict=True),
            raw_sha256=_inventory_evidence_digest(
                raw_sha256,
                _sha256_file(global_raw_path) if global_raw_path is not None else None,
            ),
            raw_total_bytes=int(combined_raw["totals"]["bytes"]),
            measurement_scope=(
                "entire recursive site plus data-root global inventory"
                if global_raw is not None
                else "entire recursive site inventory"
            ),
        )
        if optimization_impact_path is not None
        else None
    )
    final_evidence = (
        _build_final_evidence(
            repo_root=root,
            registry_sha256=registry_sha256,
            site_inventory_sha256=raw_sha256,
            global_inventory_sha256=(
                _sha256_file(global_raw_path) if global_raw_path is not None else None
            ),
            optimization_impact_sha256=(
                _sha256_file(optimization_impact_path.resolve(strict=True))
                if optimization_impact_path is not None
                else None
            ),
        )
        if final_mode
        else {
            "mode": "ANALYSIS",
            "status": "NOT_FINAL",
        }
    )
    store_records, matchers = _prepare_stores(stores, root)
    infrastructure_evidence = [
        _source_location_evidence(root, str(location))
        for location in sorted(
            registry.get("infrastructure_locations", []), key=str.casefold
        )
    ]
    file_records, resolutions = _classify_files(
        combined_raw.get("files", []),
        store_records=store_records,
        matchers=matchers,
        data_classes=set(str(value) for value in registry["data_classes"]),
    )
    database_records = _classify_databases(
        combined_raw.get("sqlite_databases", []),
        resolutions=resolutions,
        store_records=store_records,
    )
    context = {
        "schema_version": 1,
        "audit_mode": "FINAL_EVIDENCE" if final_mode else "READ_ONLY_CLASSIFICATION",
        "final_evidence": final_evidence,
        "generated_at_utc": raw.get("generated_at_utc"),
        "source_inventory": {
            "path": str(raw_path),
            "sha256": raw_sha256,
            "schema_version": raw.get("schema_version"),
        },
        "source_inventories": [
            {
                "scope": "SITE_ROOT",
                "path": str(raw_path),
                "sha256": raw_sha256,
                "root": str(raw["site_root"]),
            },
            *(
                [
                    {
                        "scope": "DATA_ROOT_GLOBAL_EXCLUDING_SITES",
                        "path": str(global_raw_path),
                        "sha256": _sha256_file(global_raw_path),
                        "root": str(global_raw["site_root"]),
                    }
                ]
                if global_raw is not None and global_raw_path is not None
                else []
            ),
        ],
        "measurement_scope": (
            "entire recursive site plus data-root global inventory"
            if global_raw is not None
            else "entire recursive site inventory"
        ),
        "optimization_evidence": (
            {
                "path": str(optimization_impact_path.resolve(strict=True)),
                "sha256": _sha256_file(optimization_impact_path.resolve(strict=True)),
                "format": optimization_impact.get("format"),
            }
            if optimization_impact is not None and optimization_impact_path is not None
            else None
        ),
        "storage_registry": {
            "path": str(registry_file),
            "sha256": registry_sha256,
            "version": registry.get("version"),
            "unknown_policy": registry.get("unknown_policy"),
        },
        "storage_infrastructure_evidence": infrastructure_evidence,
        "site_root": str(raw["site_root"]),
        "safety_contract": copy.deepcopy(raw.get("safety_contract", {})),
        "production_metadata_verification": copy.deepcopy(
            raw.get("production_metadata_verification", {})
        ),
    }

    artifacts = {
        "SITE_STORAGE_INVENTORY.json": _build_inventory(
            context=context,
            raw=combined_raw,
            files=file_records,
            databases=database_records,
            stores=store_records,
        ),
        "DATABASE_OWNER_MAP.json": _build_owner_map(
            context=context,
            databases=database_records,
            stores=store_records,
        ),
        "STORAGE_DUPLICATION_AUDIT.json": _build_duplication_audit(
            context=context,
            raw=combined_raw,
            files=file_records,
            databases=database_records,
            resolutions=resolutions,
            stores=store_records,
        ),
        "STORAGE_LIFECYCLE_PLAN.json": _build_lifecycle_plan(
            context=context,
            files=file_records,
            stores=store_records,
        ),
        "DATA_LIFECYCLE_CLASSIFICATION.json": _build_classification(
            context=context,
            files=file_records,
            databases=database_records,
            data_classes=[str(value) for value in registry["data_classes"]],
        ),
        "SITE_STORAGE_FOOTPRINT.json": _build_footprint(
            context=context,
            raw=combined_raw,
            files=file_records,
            databases=database_records,
            stores=store_records,
            optimization_impact=optimization_impact,
        ),
    }
    if final_mode:
        _validate_final_artifacts(artifacts)
    payloads = {name: _json_bytes(payload) for name, payload in artifacts.items()}

    destination.mkdir(parents=True, exist_ok=True)
    for name in OUTPUT_FILENAMES:
        _atomic_write(output_paths[name], payloads[name])
    return output_paths


def _build_final_evidence(
    *,
    repo_root: Path,
    registry_sha256: str,
    site_inventory_sha256: str,
    global_inventory_sha256: str | None,
    optimization_impact_sha256: str | None,
) -> dict[str, Any]:
    script_path = Path(__file__).resolve(strict=True)
    binding = {
        "git_head": _resolve_git_head(repo_root),
        "registry_sha256": registry_sha256,
        "finalizer_script_sha256": _sha256_file(script_path),
        "site_inventory_sha256": site_inventory_sha256,
        "global_inventory_sha256": global_inventory_sha256,
        "optimization_impact_sha256": optimization_impact_sha256,
    }
    binding_sha256 = hashlib.sha256(
        json.dumps(
            binding,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
    ).hexdigest()
    return {
        "mode": "FINAL",
        "status": "BOUND_TO_SOURCE",
        **binding,
        "binding_sha256": binding_sha256,
    }


def _resolve_git_head(repo_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--verify", "HEAD"],
            check=False,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            text=True,
        )
    except OSError as exc:
        raise StorageAuditError(f"cannot resolve final evidence Git HEAD: {exc}") from exc
    head = result.stdout.strip().casefold()
    if result.returncode != 0 or re.fullmatch(r"[0-9a-f]{40,64}", head) is None:
        detail = result.stderr.strip() or "git rev-parse returned an invalid commit"
        raise StorageAuditError(f"cannot resolve final evidence Git HEAD: {detail}")
    return head


def _validate_final_artifacts(artifacts: Mapping[str, Mapping[str, Any]]) -> None:
    footprint = artifacts["SITE_STORAGE_FOOTPRINT.json"]
    impact = footprint.get("optimization_impact")
    if not isinstance(impact, Mapping):
        raise StorageAuditError("final mode requires optimization impact output")
    for field in ("after_operational_bytes", "history_moved_bytes"):
        if impact.get(field) is None:
            raise StorageAuditError(f"final mode rejects null optimization_impact.{field}")
    storage_report = footprint.get("all_databases_storage")
    sections = storage_report.get("sections") if isinstance(storage_report, Mapping) else None
    if not isinstance(sections, Mapping):
        raise StorageAuditError("final mode requires all storage report sections")
    for name in _STORAGE_REPORT_SECTIONS:
        section = sections.get(name)
        if not isinstance(section, Mapping):
            raise StorageAuditError(f"final mode requires storage report section {name}")
        for field in ("after_operational_bytes", "history_moved_bytes"):
            if section.get(field) is None:
                raise StorageAuditError(
                    f"final mode rejects null storage section {name}.{field}"
                )
    lifecycle = artifacts["STORAGE_LIFECYCLE_PLAN.json"]
    unresolved = lifecycle.get("unresolved")
    if not isinstance(unresolved, Mapping):
        raise StorageAuditError("final mode requires unresolved owner audit output")
    if int(unresolved.get("files") or 0) or int(unresolved.get("bytes") or 0):
        raise StorageAuditError(
            "final mode rejects ambiguous or unregistered storage owners"
        )
    registered_unknown = lifecycle.get("registered_unknown_protected")
    if not isinstance(registered_unknown, Mapping):
        raise StorageAuditError("final mode requires registered UNKNOWN producer audit")
    if int(registered_unknown.get("active_or_unproven_files") or 0) or int(
        registered_unknown.get("active_or_unproven_bytes") or 0
    ):
        raise StorageAuditError(
            "final mode rejects registered UNKNOWN storage with active or unproven producers"
        )


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StorageAuditError(f"invalid {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise StorageAuditError(f"{label} must be a JSON object: {path}")
    return value


def _load_optimization_impact(
    path: Path,
    *,
    raw_sha256: str,
    raw_total_bytes: int,
    measurement_scope: str,
) -> dict[str, Any]:
    impact = _load_json_object(path, label="optimization impact evidence")
    if impact.get("format") != "netconsole-site-storage-impact-v1":
        raise StorageAuditError("invalid optimization impact evidence format")
    if int(impact.get("schema_version") or 0) != 1:
        raise StorageAuditError("unsupported optimization impact evidence version")
    if str(impact.get("source_inventory_sha256") or "").casefold() != raw_sha256.casefold():
        raise StorageAuditError("optimization impact source inventory digest mismatch")
    if str(impact.get("measurement_scope") or "") != measurement_scope:
        raise StorageAuditError(
            "optimization impact does not cover the complete inventory scope"
        )
    if str(impact.get("measurement_status") or "") != "ISOLATED_REHEARSAL_OVERLAY":
        raise StorageAuditError(
            "optimization impact measurement status must be ISOLATED_REHEARSAL_OVERLAY"
        )
    sections = impact.get("sections")
    if not isinstance(sections, dict) or set(sections) != set(_STORAGE_REPORT_SECTIONS):
        raise StorageAuditError("optimization impact must provide every storage report section")
    numeric_fields = (
        "before_bytes",
        "after_operational_bytes",
        "history_moved_bytes",
        "duplicates_removed_bytes",
        "protected_bytes",
    )
    normalized_sections: dict[str, dict[str, Any]] = {}
    for name in _STORAGE_REPORT_SECTIONS:
        raw_section = sections[name]
        if not isinstance(raw_section, dict):
            raise StorageAuditError(f"optimization impact section {name} must be an object")
        section: dict[str, Any] = {}
        for field in numeric_fields:
            value = raw_section.get(field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise StorageAuditError(
                    f"optimization impact section {name}.{field} must be a non-negative integer"
                )
            section[field] = value
        evidence = raw_section.get("evidence", [])
        if not isinstance(evidence, list) or any(
            not isinstance(value, str) or not value.strip() for value in evidence
        ):
            raise StorageAuditError(
                f"optimization impact section {name}.evidence must be a string list"
            )
        section["evidence"] = list(evidence)
        normalized_sections[name] = section
    before_total = sum(value["before_bytes"] for value in normalized_sections.values())
    after_total = sum(
        value["after_operational_bytes"] for value in normalized_sections.values()
    )
    if before_total != raw_total_bytes:
        raise StorageAuditError("optimization impact before bytes do not reconcile")
    if int(impact.get("before_site_bytes") or -1) != raw_total_bytes:
        raise StorageAuditError("optimization impact baseline total does not match raw inventory")
    if int(impact.get("after_site_bytes") or -1) != after_total:
        raise StorageAuditError("optimization impact after bytes do not reconcile")
    for field in (
        "after_operational_bytes",
        "history_moved_bytes",
        "duplicates_removed_bytes",
        "protected_bytes",
    ):
        value = impact.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise StorageAuditError(
                f"optimization impact {field} must be a non-negative integer"
            )
        section_total = sum(
            int(section[field]) for section in normalized_sections.values()
        )
        if value != section_total:
            raise StorageAuditError(
                f"optimization impact {field} does not reconcile with sections"
            )
    return {**copy.deepcopy(impact), "sections": normalized_sections}


def _validate_global_inventory(raw: Mapping[str, Any]) -> None:
    if raw.get("inventory_scope") != GLOBAL_INVENTORY_SCOPE:
        raise StorageAuditError(
            f"global raw inventory must declare {GLOBAL_INVENTORY_SCOPE}"
        )
    for item in raw.get("files", []):
        normalized = _normalize_relative_path(str(item.get("path") or ""))
        if normalized.casefold() == "sites" or normalized.casefold().startswith(
            "sites/"
        ):
            raise StorageAuditError("global raw inventory must exclude sites/**")


def _merge_raw_inventories(
    site_raw: Mapping[str, Any],
    global_raw: Mapping[str, Any] | None,
) -> dict[str, Any]:
    merged = copy.deepcopy(dict(site_raw))
    site_files = [
        _scoped_inventory_record(item, scope=SITE_INVENTORY_SCOPE)
        for item in site_raw.get("files", [])
    ]
    global_files = [
        _scoped_inventory_record(item, scope=GLOBAL_INVENTORY_SCOPE)
        for item in (global_raw or {}).get("files", [])
    ]
    identities = [
        _resolution_key(
            str(item["inventory_scope"]),
            _normalize_relative_path(str(item.get("path") or "")),
        )
        for item in [*site_files, *global_files]
    ]
    if len(identities) != len(set(identities)):
        raise StorageAuditError("site/global inventory paths overlap")
    files = [*site_files, *global_files]
    databases = [
        *[
            _scoped_inventory_record(item, scope=SITE_INVENTORY_SCOPE)
            for item in site_raw.get("sqlite_databases", [])
        ],
        *[
            _scoped_inventory_record(item, scope=GLOBAL_INVENTORY_SCOPE)
            for item in (global_raw or {}).get("sqlite_databases", [])
        ],
    ]
    merged["files"] = files
    merged["sqlite_databases"] = databases
    merged["zip_archives"] = [
        *[
            _scoped_inventory_record(item, scope=SITE_INVENTORY_SCOPE)
            for item in site_raw.get("zip_archives", [])
        ],
        *[
            _scoped_inventory_record(item, scope=GLOBAL_INVENTORY_SCOPE)
            for item in (global_raw or {}).get("zip_archives", [])
        ],
    ]
    if global_raw is None:
        return merged
    duplicate_groups: list[dict[str, Any]] = []
    by_digest: dict[tuple[str, int], list[dict[str, str]]] = defaultdict(list)
    for item in files:
        digest = str(item.get("sha256") or "").casefold()
        if re.fullmatch(r"[0-9a-f]{64}", digest):
            by_digest[(digest, _nonnegative_int(item, "bytes"))].append(
                {
                    "inventory_scope": str(item["inventory_scope"]),
                    "path": _normalize_relative_path(str(item.get("path") or "")),
                }
            )
    for (digest, size), members in sorted(by_digest.items()):
        if len(members) < 2:
            continue
        sorted_members = sorted(
            members,
            key=lambda item: (
                str(item["inventory_scope"]).casefold(),
                str(item["path"]).casefold(),
            ),
        )
        duplicate_groups.append(
            {
                "bytes_each": size,
                "sha256": digest,
                "count": len(members),
                "duplicate_bytes": size * (len(members) - 1),
                "paths": [item["path"] for item in sorted_members],
                "members": sorted_members,
            }
        )
    merged["duplicate_groups"] = duplicate_groups
    merged["totals"] = {
        **copy.deepcopy(dict(site_raw["totals"])),
        "files": len(files),
        "bytes": sum(_nonnegative_int(item, "bytes") for item in files),
        "sqlite_files_by_header": len(databases),
        "sqlite_bytes": sum(int(item.get("bytes") or 0) for item in databases),
        "exact_duplicate_groups": len(duplicate_groups),
        "exact_duplicate_bytes": sum(
            int(item["duplicate_bytes"]) for item in duplicate_groups
        ),
    }
    return merged


def _scoped_inventory_record(
    value: Mapping[str, Any], *, scope: str
) -> dict[str, Any]:
    record = copy.deepcopy(dict(value))
    record["inventory_scope"] = scope
    return record


def _resolution_key(scope: str, path: str) -> str:
    return f"{scope.casefold()}\0{path.casefold()}"


def _inventory_evidence_digest(site_sha256: str, global_sha256: str | None) -> str:
    if global_sha256 is None:
        return site_sha256
    payload = json.dumps(
        {
            "global_inventory_sha256": global_sha256,
            "site_inventory_sha256": site_sha256,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _validate_raw_inventory(raw: Mapping[str, Any]) -> None:
    required = {
        "schema_version",
        "generated_at_utc",
        "site_root",
        "totals",
        "sqlite_databases",
        "files",
    }
    missing = sorted(required - set(raw))
    if missing:
        raise StorageAuditError(
            "raw inventory is missing fields: " + ", ".join(missing)
        )
    if not isinstance(raw["files"], list) or not isinstance(
        raw["sqlite_databases"], list
    ):
        raise StorageAuditError("raw inventory files/sqlite_databases must be lists")
    totals = raw["totals"]
    if not isinstance(totals, dict):
        raise StorageAuditError("raw inventory totals must be an object")
    observed_files = len(raw["files"])
    observed_bytes = sum(_nonnegative_int(item, "bytes") for item in raw["files"])
    if totals.get("files") != observed_files or totals.get("bytes") != observed_bytes:
        raise StorageAuditError(
            "raw inventory totals do not reconcile with the file inventory"
        )
    verification = raw.get("production_metadata_verification")
    if isinstance(verification, dict) and verification.get("unchanged") is not True:
        raise StorageAuditError("production metadata verification is not unchanged")


def _validate_registry(registry: Mapping[str, Any]) -> list[dict[str, Any]]:
    classes = registry.get("data_classes")
    stores = registry.get("stores")
    if registry.get("unknown_policy") != UNKNOWN_POLICY:
        raise StorageAuditError("storage registry UNKNOWN policy must be PROTECT")
    if not isinstance(classes, list) or UNKNOWN_CLASS not in classes:
        raise StorageAuditError("storage registry must declare UNKNOWN data class")
    if len(classes) != len(set(classes)) or not all(
        isinstance(value, str) and value for value in classes
    ):
        raise StorageAuditError("storage registry data classes must be unique strings")
    if not isinstance(stores, list) or not stores:
        raise StorageAuditError("storage registry stores must be a non-empty list")
    result: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    class_set = set(classes)
    for index, value in enumerate(stores):
        if not isinstance(value, dict):
            raise StorageAuditError(f"storage registry store {index} must be an object")
        missing = sorted(_REQUIRED_REGISTRY_FIELDS - set(value))
        if missing:
            raise StorageAuditError(
                f"storage registry store {index} is missing: {', '.join(missing)}"
            )
        store = copy.deepcopy(value)
        store_id = str(store["id"])
        if not store_id or store_id in seen_ids:
            raise StorageAuditError(f"duplicate or empty storage id: {store_id!r}")
        seen_ids.add(store_id)
        data_type = str(store["data_type"])
        allowed = {str(item) for item in store["allowed_data_classes"]}
        forbidden = {str(item) for item in store["forbidden_data_classes"]}
        if data_type not in class_set or not allowed <= class_set:
            raise StorageAuditError(f"{store_id} uses an unknown data class")
        if forbidden - class_set or allowed & forbidden:
            raise StorageAuditError(f"{store_id} has invalid class constraints")
        if not isinstance(store["rebuildable"], bool):
            raise StorageAuditError(f"{store_id}.rebuildable must be boolean")
        if data_type == UNKNOWN_CLASS and (
            str(store["authority"]) != "UNKNOWN_PROTECT"
            or str(store["retention_owner"]) != "UNKNOWN_PROTECT"
            or store["rebuildable"] is not False
        ):
            raise StorageAuditError(
                f"{store_id} UNKNOWN declaration is not fail-closed"
            )
        if data_type == UNKNOWN_CLASS and type(store.get("active_producer")) is not bool:
            raise StorageAuditError(
                f"{store_id} UNKNOWN declaration must specify active_producer"
            )
        _validate_table_rules(store, class_set=class_set, allowed=allowed)
        result.append(store)
    return sorted(result, key=lambda item: str(item["id"]))


def _validate_table_rules(
    store: Mapping[str, Any], *, class_set: set[str], allowed: set[str]
) -> None:
    store_id = str(store["id"])
    rules = store.get("table_rules", [])
    if not isinstance(rules, list):
        raise StorageAuditError(f"{store_id}.table_rules must be a list")
    seen_tables: set[str] = set()
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict):
            raise StorageAuditError(
                f"{store_id}.table_rules[{index}] must be an object"
            )
        missing = sorted(_REQUIRED_TABLE_RULE_FIELDS - set(rule))
        if missing:
            raise StorageAuditError(
                f"{store_id}.table_rules[{index}] is missing: {', '.join(missing)}"
            )
        tables = rule["tables"]
        if not isinstance(tables, list) or not tables or not all(
            isinstance(value, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value)
            for value in tables
        ):
            raise StorageAuditError(
                f"{store_id}.table_rules[{index}].tables must contain exact table names"
            )
        normalized = {str(value).casefold() for value in tables}
        duplicates = sorted(seen_tables & normalized)
        if duplicates:
            raise StorageAuditError(
                f"{store_id} has duplicate table rules: {', '.join(duplicates)}"
            )
        seen_tables.update(normalized)
        data_class = str(rule["data_class"])
        if data_class not in class_set or data_class not in allowed:
            raise StorageAuditError(
                f"{store_id}.table_rules[{index}] uses a class not allowed by the store"
            )
        if not isinstance(rule["rebuildable"], bool):
            raise StorageAuditError(
                f"{store_id}.table_rules[{index}].rebuildable must be boolean"
            )
        for field in ("producer", "consumers", "source_locations"):
            values = rule[field]
            if not isinstance(values, list) or not values or not all(
                isinstance(value, str) and value for value in values
            ):
                raise StorageAuditError(
                    f"{store_id}.table_rules[{index}].{field} must be a non-empty string list"
                )


def _prepare_stores(
    stores: Sequence[dict[str, Any]], repo_root: Path
) -> tuple[
    list[dict[str, Any]], list[tuple[str, str, re.Pattern[str]]]
]:
    records: list[dict[str, Any]] = []
    matchers: list[tuple[str, str, re.Pattern[str]]] = []
    for store in stores:
        record = copy.deepcopy(store)
        relative_path = str(store["relative_path"])
        normalized_path = _normalize_relative_path(relative_path)
        scope = (
            SITE_INVENTORY_SCOPE
            if normalized_path.casefold().startswith("sites/{site_id}/")
            else GLOBAL_INVENTORY_SCOPE
        )
        variants = _expand_registry_path(relative_path)
        record["normalized_path_variants"] = variants
        record["inventory_scope"] = scope
        record["source_evidence"] = [
            _source_location_evidence(repo_root, str(location))
            for location in sorted(store["source_locations"], key=str.casefold)
        ]
        for rule in record.get("table_rules", []):
            rule["source_evidence"] = [
                _source_location_evidence(repo_root, str(location))
                for location in sorted(rule["source_locations"], key=str.casefold)
            ]
        records.append(record)
        for variant in variants:
            matchers.append(
                (str(store["id"]), scope, _compile_path_template(variant))
            )
    return records, matchers


def _source_location_evidence(repo_root: Path, location: str) -> dict[str, Any]:
    normalized = _normalize_relative_path(location)
    resolved = (repo_root / Path(normalized)).resolve(strict=False)
    try:
        resolved.relative_to(repo_root)
        inside_repo = True
    except ValueError:
        inside_repo = False
    exists = inside_repo and resolved.exists()
    return {
        "path": normalized,
        "exists": exists,
        "kind": (
            "directory"
            if exists and resolved.is_dir()
            else "file"
            if exists and resolved.is_file()
            else "missing"
        ),
    }


def _expand_registry_path(value: str) -> list[str]:
    normalized = _normalize_relative_path(value)
    site_prefix = "sites/{site_id}/"
    if normalized.casefold().startswith(site_prefix):
        normalized = normalized[len(site_prefix) :]
    if "|" not in normalized:
        return [_directory_template(normalized)]

    # The registry uses compact segment alternatives such as
    # ``cache|temp|jobs/**`` and ``agent-data/tasks|packages/**``.
    tokens = normalized.split("|")
    final = tokens[-1]
    suffix = "/**" if final.endswith("/**") else ""
    if suffix:
        tokens[-1] = final[: -len(suffix)]
    first_parent = tokens[0].rsplit("/", 1)[0] if "/" in tokens[0] else ""
    variants: list[str] = []
    for index, token in enumerate(tokens):
        candidate = token
        if index and first_parent and "/" not in candidate:
            candidate = f"{first_parent}/{candidate}"
        if suffix and not candidate.endswith(suffix):
            candidate += suffix
        variants.append(_directory_template(candidate))
    return sorted(set(variants), key=str.casefold)


def _directory_template(value: str) -> str:
    return f"{value}**" if value.endswith("/") else value


def _compile_path_template(template: str) -> re.Pattern[str]:
    tokens = (
        ("YYYY-MM[-NNNN]", r"\d{4}-\d{2}(?:-\d{4})?"),
        ("YYYY-MM-DD", r"\d{4}-\d{2}-\d{2}"),
        ("YYYY-MM", r"\d{4}-\d{2}"),
        ("**", r".*"),
        ("*", r"[^/]*"),
    )
    pattern: list[str] = ["^"]
    index = 0
    while index < len(template):
        if template[index] == "{":
            end = template.find("}", index + 1)
            if end < 0:
                raise StorageAuditError(f"invalid registry path template: {template}")
            name = template[index + 1 : end]
            if not name or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                raise StorageAuditError(f"invalid registry placeholder: {template}")
            pattern.append(r"[^/]+")
            index = end + 1
            continue
        matched = False
        for literal, replacement in tokens:
            if template.startswith(literal, index):
                pattern.append(replacement)
                index += len(literal)
                matched = True
                break
        if matched:
            continue
        pattern.append(re.escape(template[index]))
        index += 1
    pattern.append("$")
    return re.compile("".join(pattern), re.IGNORECASE)


def _classify_files(
    files: Iterable[Mapping[str, Any]],
    *,
    store_records: Sequence[dict[str, Any]],
    matchers: Sequence[tuple[str, str, re.Pattern[str]]],
    data_classes: set[str],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    stores_by_id = {str(store["id"]): store for store in store_records}
    records: list[dict[str, Any]] = []
    resolutions: dict[str, dict[str, Any]] = {}
    for raw_file in sorted(
        files,
        key=lambda item: (
            str(item.get("inventory_scope") or SITE_INVENTORY_SCOPE).casefold(),
            _path_sort_key(item.get("path")),
        ),
    ):
        record = copy.deepcopy(dict(raw_file))
        normalized = _normalize_relative_path(str(record.get("path", "")))
        scope = str(record.get("inventory_scope") or SITE_INVENTORY_SCOPE)
        matched_ids = sorted(
            {
                store_id
                for store_id, matcher_scope, matcher in matchers
                if matcher_scope == scope and matcher.fullmatch(normalized) is not None
            },
            key=str.casefold,
        )
        if len(matched_ids) == 1:
            store = stores_by_id[matched_ids[0]]
            data_class = str(store["data_type"])
            if data_class not in data_classes:
                raise StorageAuditError(
                    f"registry store {matched_ids[0]} resolved to an unknown class"
                )
            resolution = _registered_resolution(store, matched_ids)
        else:
            resolution = _unknown_resolution(matched_ids)
        record["path"] = normalized
        record["inventory_scope"] = scope
        record["observed_classification"] = record.pop("classification", None)
        record["storage_resolution"] = resolution
        records.append(record)
        resolutions[_resolution_key(scope, normalized)] = resolution
    return records, resolutions


def _registered_resolution(
    store: Mapping[str, Any], matched_ids: Sequence[str]
) -> dict[str, Any]:
    data_class = str(store["data_type"])
    return {
        "status": "REGISTERED",
        "matched_store_ids": list(matched_ids),
        "store_id": str(store["id"]),
        "data_class": data_class,
        "protection": UNKNOWN_POLICY
        if data_class == UNKNOWN_CLASS
        else "OWNER_MANAGED",
        "owner": str(store["owner"]),
        "producer": copy.deepcopy(store["producer"]),
        "consumers": copy.deepcopy(store["consumers"]),
        "lifecycle_owner": str(store["retention_owner"]),
        "authority": str(store["authority"]),
        "rebuildable": bool(store["rebuildable"]),
        "active_producer": store.get("active_producer"),
    }


def _unknown_resolution(matched_ids: Sequence[str]) -> dict[str, Any]:
    return {
        "status": "AMBIGUOUS" if matched_ids else "UNREGISTERED",
        "matched_store_ids": list(matched_ids),
        "store_id": None,
        "data_class": UNKNOWN_CLASS,
        "protection": UNKNOWN_POLICY,
        "owner": "UNKNOWN",
        "producer": [],
        "consumers": [],
        "lifecycle_owner": "UNKNOWN_PROTECT",
        "authority": "UNKNOWN_PROTECT",
        "rebuildable": False,
    }


def _classify_databases(
    databases: Iterable[Mapping[str, Any]],
    *,
    resolutions: Mapping[str, dict[str, Any]],
    store_records: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    stores_by_id = {str(store["id"]): store for store in store_records}
    result: list[dict[str, Any]] = []
    for raw_database in sorted(
        databases,
        key=lambda item: (
            str(item.get("inventory_scope") or SITE_INVENTORY_SCOPE).casefold(),
            _path_sort_key(item.get("path")),
        ),
    ):
        database = copy.deepcopy(dict(raw_database))
        normalized = _normalize_relative_path(str(database.get("path", "")))
        scope = str(database.get("inventory_scope") or SITE_INVENTORY_SCOPE)
        resolution = copy.deepcopy(
            resolutions.get(
                _resolution_key(scope, normalized), _unknown_resolution([])
            )
        )
        database["path"] = normalized
        database["inventory_scope"] = scope
        database["storage_resolution"] = resolution
        store = stores_by_id.get(str(resolution.get("store_id")))
        tables: list[dict[str, Any]] = []
        for raw_table in sorted(
            database.get("tables", []), key=lambda item: str(item.get("name", ""))
        ):
            table = copy.deepcopy(dict(raw_table))
            table["observed_classification"] = table.pop("classification", None)
            table["observed_classification_reason"] = table.pop(
                "classification_reason", None
            )
            table["lifecycle_classification"] = _table_classification(
                resolution, store, table_name=str(table.get("name", ""))
            )
            tables.append(table)
        database["tables"] = tables
        result.append(database)
    return result


def _table_classification(
    resolution: Mapping[str, Any],
    store: Mapping[str, Any] | None,
    *,
    table_name: str,
) -> dict[str, Any]:
    if resolution.get("status") != "REGISTERED" or store is None:
        return {
            "data_class": UNKNOWN_CLASS,
            "protection": UNKNOWN_POLICY,
            "basis": "database owner is not uniquely resolved",
            "authority": "UNKNOWN_PROTECT",
            "producer": [],
            "consumers": [],
            "lifecycle_owner": "UNKNOWN_PROTECT",
            "rebuildable": False,
            "source_evidence": [],
        }
    matching_rules = [
        rule
        for rule in store.get("table_rules", [])
        if table_name.casefold()
        in {str(value).casefold() for value in rule.get("tables", [])}
    ]
    if len(matching_rules) == 1:
        rule = matching_rules[0]
        data_class = str(rule["data_class"])
        return {
            "data_class": data_class,
            "protection": (
                UNKNOWN_POLICY if data_class == UNKNOWN_CLASS else "OWNER_MANAGED"
            ),
            "basis": f"explicit table rule from store {store['id']}",
            "authority": str(rule["authority"]),
            "producer": copy.deepcopy(rule["producer"]),
            "consumers": copy.deepcopy(rule["consumers"]),
            "lifecycle_owner": str(rule["lifecycle_owner"]),
            "rebuildable": bool(rule["rebuildable"]),
            "source_evidence": copy.deepcopy(rule.get("source_evidence", [])),
        }
    allowed = sorted({str(value) for value in store["allowed_data_classes"]})
    if len(allowed) != 1:
        return {
            "data_class": UNKNOWN_CLASS,
            "protection": UNKNOWN_POLICY,
            "basis": (
                "registry permits multiple table classes; no explicit table rule exists"
            ),
            "allowed_store_classes": allowed,
            "authority": "UNKNOWN_PROTECT",
            "producer": [],
            "consumers": [],
            "lifecycle_owner": "UNKNOWN_PROTECT",
            "rebuildable": False,
            "source_evidence": [],
        }
    return {
        "data_class": allowed[0],
        "protection": (
            UNKNOWN_POLICY if allowed[0] == UNKNOWN_CLASS else "OWNER_MANAGED"
        ),
        "basis": f"single allowed class from store {store['id']}",
        "authority": str(store["authority"]),
        "producer": copy.deepcopy(store["producer"]),
        "consumers": copy.deepcopy(store["consumers"]),
        "lifecycle_owner": str(store["retention_owner"]),
        "rebuildable": bool(store["rebuildable"]),
        "source_evidence": copy.deepcopy(store.get("source_evidence", [])),
    }


def _build_inventory(
    *,
    context: Mapping[str, Any],
    raw: Mapping[str, Any],
    files: Sequence[dict[str, Any]],
    databases: Sequence[dict[str, Any]],
    stores: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    summary = _resolution_summary(files)
    summary.update(
        {
            "files": len(files),
            "bytes": sum(int(item["bytes"]) for item in files),
            "sqlite_databases": len(databases),
            "sqlite_tables": sum(len(item.get("tables", [])) for item in databases),
        }
    )
    return {
        **copy.deepcopy(dict(context)),
        "summary": summary,
        "raw_totals": copy.deepcopy(raw.get("totals", {})),
        "raw_aggregates": {
            "by_top_level": copy.deepcopy(raw.get("by_top_level", [])),
            "by_extension": copy.deepcopy(raw.get("by_extension", [])),
            "by_classification": copy.deepcopy(raw.get("by_classification", [])),
        },
        "registered_stores": copy.deepcopy(list(stores)),
        "files": copy.deepcopy(list(files)),
        "sqlite_databases": copy.deepcopy(list(databases)),
    }


def _build_owner_map(
    *,
    context: Mapping[str, Any],
    databases: Sequence[dict[str, Any]],
    stores: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    store_usage = _store_usage(databases, stores)
    database_map: list[dict[str, Any]] = []
    for database in databases:
        resolution = database["storage_resolution"]
        database_map.append(
            {
                "database": database["path"],
                "bytes": database["bytes"],
                "sha256": database.get("sha256"),
                "store_resolution": copy.deepcopy(resolution),
                "database_pragmas": copy.deepcopy(database.get("database_pragmas", {})),
                "schema_objects": copy.deepcopy(database.get("schema_objects", [])),
                "summary": copy.deepcopy(database.get("summary", {})),
                "lifecycle_profile": _database_lifecycle_profile(database),
                "tables": [
                    {
                        "name": table.get("name"),
                        "lifecycle_classification": copy.deepcopy(
                            table["lifecycle_classification"]
                        ),
                        "rows": table.get("rows"),
                        "logical_payload": copy.deepcopy(
                            table.get("logical_payload", {})
                        ),
                        "content_columns": copy.deepcopy(
                            table.get("content_columns", {})
                        ),
                        "indexes": copy.deepcopy(table.get("indexes", [])),
                        "dbstat": copy.deepcopy(table.get("dbstat")),
                        "time_ranges": copy.deepcopy(table.get("time_ranges", {})),
                        "identity_columns": copy.deepcopy(
                            table.get("identity_columns", {})
                        ),
                        "duplicate_content": copy.deepcopy(
                            table.get("duplicate_content", {})
                        ),
                    }
                    for table in database.get("tables", [])
                ],
            }
        )
    return {
        **copy.deepcopy(dict(context)),
        "contract": (
            "database/table -> producer -> repository/service -> consumer -> "
            "lifecycle owner"
        ),
        "registered_store_usage": store_usage,
        "databases": database_map,
        "unresolved_databases": [
            item["database"]
            for item in database_map
            if item["store_resolution"]["status"] != "REGISTERED"
        ],
    }


def _database_lifecycle_profile(database: Mapping[str, Any]) -> dict[str, Any]:
    by_class: dict[str, dict[str, int]] = defaultdict(
        lambda: {"tables": 0, "rows": 0, "logical_payload_bytes": 0}
    )
    total_rows = 0
    total_payload = 0
    rebuildable_rows = 0
    rebuildable_payload = 0
    rebuildable_classes = {"CACHE_REBUILDABLE", "DISPOSABLE_DERIVED"}
    for table in database.get("tables", []):
        data_class = str(table["lifecycle_classification"]["data_class"])
        rows = int(table.get("rows", 0) or 0)
        logical = table.get("logical_payload", {})
        payload = int(logical.get("text_bytes", 0) or 0) + int(
            logical.get("blob_bytes", 0) or 0
        )
        by_class[data_class]["tables"] += 1
        by_class[data_class]["rows"] += rows
        by_class[data_class]["logical_payload_bytes"] += payload
        total_rows += rows
        total_payload += payload
        classification = table["lifecycle_classification"]
        if (
            classification.get("rebuildable") is True
            and data_class in rebuildable_classes
        ):
            rebuildable_rows += rows
            rebuildable_payload += payload
    current_rows = by_class["OPERATIONAL_CURRENT"]["rows"]
    current_payload = by_class["OPERATIONAL_CURRENT"]["logical_payload_bytes"]
    history_rows = (
        by_class["HISTORICAL_RAW_FACT"]["rows"] + by_class["HISTORICAL_TREND"]["rows"]
    )
    history_payload = (
        by_class["HISTORICAL_RAW_FACT"]["logical_payload_bytes"]
        + by_class["HISTORICAL_TREND"]["logical_payload_bytes"]
    )
    pragmas = database.get("database_pragmas", {})
    page_size = int(pragmas.get("page_size", 0) or 0)
    freelist_count = int(pragmas.get("freelist_count", 0) or 0)
    return {
        "physical_bytes": int(database.get("bytes", 0) or 0),
        "freelist_bytes_estimate": page_size * freelist_count,
        "by_data_class": {
            name: by_class[name] for name in sorted(by_class, key=str.casefold)
        },
        "current_history_ratio": {
            "current_rows": current_rows,
            "history_rows": history_rows,
            "current_to_history_rows": (
                current_rows / history_rows if history_rows else None
            ),
            "current_logical_payload_bytes": current_payload,
            "history_logical_payload_bytes": history_payload,
            "current_to_history_logical_payload": (
                current_payload / history_payload if history_payload else None
            ),
        },
        "rebuildable_ratio": {
            "rows": rebuildable_rows / total_rows if total_rows else 0.0,
            "logical_payload": (
                rebuildable_payload / total_payload if total_payload else 0.0
            ),
            "basis": (
                "explicit table lifecycle classification with rebuildable=true and "
                "a rebuildable data class"
            ),
        },
        "unknown_protected_ratio": {
            "rows": (
                by_class[UNKNOWN_CLASS]["rows"] / total_rows if total_rows else 0.0
            ),
            "logical_payload": (
                by_class[UNKNOWN_CLASS]["logical_payload_bytes"] / total_payload
                if total_payload
                else 0.0
            ),
        },
    }


def _build_duplication_audit(
    *,
    context: Mapping[str, Any],
    raw: Mapping[str, Any],
    files: Sequence[dict[str, Any]],
    databases: Sequence[dict[str, Any]],
    resolutions: Mapping[str, dict[str, Any]],
    stores: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    exact_groups: list[dict[str, Any]] = []
    for group in sorted(
        raw.get("duplicate_groups", []), key=lambda item: str(item.get("sha256", ""))
    ):
        enriched = copy.deepcopy(dict(group))
        members = group.get("members")
        if not isinstance(members, list):
            members = [
                {"inventory_scope": SITE_INVENTORY_SCOPE, "path": path}
                for path in group.get("paths", [])
            ]
        enriched["path_resolutions"] = [
            {
                "inventory_scope": str(
                    member.get("inventory_scope") or SITE_INVENTORY_SCOPE
                ),
                "path": _normalize_relative_path(str(member.get("path") or "")),
                "storage_resolution": copy.deepcopy(
                    resolutions.get(
                        _resolution_key(
                            str(
                                member.get("inventory_scope")
                                or SITE_INVENTORY_SCOPE
                            ),
                            _normalize_relative_path(
                                str(member.get("path") or "")
                            ),
                        ),
                        _unknown_resolution([]),
                    )
                ),
            }
            for member in sorted(
                members,
                key=lambda item: (
                    str(
                        item.get("inventory_scope") or SITE_INVENTORY_SCOPE
                    ).casefold(),
                    _path_sort_key(item.get("path")),
                ),
            )
        ]
        enriched["disposition"] = "PROTECT_REVIEW"
        enriched["deletion_authorized"] = False
        exact_groups.append(enriched)

    table_candidates: list[dict[str, Any]] = []
    for database in databases:
        for table in database.get("tables", []):
            duplicate = table.get("duplicate_content", {})
            content_columns = table.get("content_columns", {})
            duplicate_rows = int(duplicate.get("duplicate_rows", 0) or 0)
            duplicate_values = sum(
                int(profile.get("duplicate_values", 0) or 0)
                for profile in content_columns.values()
                if isinstance(profile, dict)
            )
            if duplicate_rows or duplicate_values:
                table_candidates.append(
                    {
                        "database": database["path"],
                        "table": table.get("name"),
                        "rows": table.get("rows"),
                        "duplicate_rows": duplicate_rows,
                        "duplicate_content_values": duplicate_values,
                        "content_columns": copy.deepcopy(content_columns),
                        "storage_resolution": copy.deepcopy(
                            database["storage_resolution"]
                        ),
                        "disposition": "PROTECT_UNTIL_QUERY_PARITY_AND_OWNER_REVIEW",
                    }
                )

    expected_duplicate_bytes = int(
        raw.get("totals", {}).get("exact_duplicate_bytes", 0) or 0
    )
    observed_duplicate_bytes = sum(
        int(group.get("duplicate_bytes", 0) or 0) for group in exact_groups
    )
    return {
        **copy.deepcopy(dict(context)),
        "policy": {
            "exact_duplicate_is_not_disposable_by_itself": True,
            "unknown_is_protected": True,
            "raw_authority_requires_owner_and_consumer_verification": True,
            "deletion_authorized_bytes": 0,
        },
        "summary": {
            "exact_duplicate_groups": len(exact_groups),
            "exact_duplicate_bytes_lower_bound": observed_duplicate_bytes,
            "table_duplicate_candidates": len(table_candidates),
            "reconciles_with_raw_inventory": (
                expected_duplicate_bytes == observed_duplicate_bytes
            ),
            "duplicates_removed_bytes": 0,
        },
        "exact_file_duplicate_groups": exact_groups,
        "sqlite_table_duplicate_candidates": table_candidates,
        "zip_archives": copy.deepcopy(raw.get("zip_archives", [])),
        "raw_authority_audit": _build_raw_authority_audit(
            files=files,
            databases=databases,
            stores=stores,
            exact_groups=exact_groups,
        ),
    }


def _build_raw_authority_audit(
    *,
    files: Iterable[Mapping[str, Any]],
    databases: Sequence[Mapping[str, Any]],
    stores: Sequence[Mapping[str, Any]],
    exact_groups: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Report raw representations without inferring authority from filenames."""

    definitions = (
        {
            "id": "ground_unattended_raw",
            "raw_authority_store_ids": ("site.ground.active_raw", "site.ground.archive"),
            "store_prefixes": ("site.ground.active_raw", "site.ground.archive"),
            "authority_transition": "active raw -> immutable Ground archive",
            "representations": (
                "raw_file",
                "parsed_fact_rows",
                "task_event_payload",
                "artifact_or_export",
            ),
        },
        {
            "id": "online_mr_raw",
            "raw_authority_store_ids": ("site.online_mr.session_raw",),
            "store_prefixes": ("site.online_mr.session_raw", "site.online_mr.session_package"),
            "authority_transition": "session raw remains authority; ZIP is an artifact representation",
            "representations": (
                "raw_log",
                "zip_package",
                "parsed_sqlite",
                "task_result_or_event",
                "artifact_or_export",
            ),
        },
        {
            "id": "mesh_raw",
            "raw_authority_store_ids": ("site.mesh.raw",),
            "store_prefixes": ("site.mesh.raw", "site.mesh.source_detail", "site.mesh.outputs"),
            "authority_transition": "content-addressed MESH raw remains authority; parsed/report stores are derived",
            "representations": (
                "raw_log_or_zip",
                "parsed_sqlite",
                "derived_rows",
                "task_result_or_event",
                "artifact_or_export",
            ),
        },
    )
    records = list(files)
    store_ids = {str(store.get("id") or "") for store in stores}
    result: list[dict[str, Any]] = []
    for definition in definitions:
        prefixes = tuple(str(value) for value in definition["store_prefixes"])
        representation_store_ids = sorted(
            store_id
            for store_id in store_ids
            if any(store_id == prefix or store_id.startswith(prefix + ".") for prefix in prefixes)
        )
        raw_authority_store_ids = sorted(
            store_id
            for store_id in definition["raw_authority_store_ids"]
            if store_id in store_ids
        )
        matched_paths: list[dict[str, Any]] = []
        for item in records:
            resolution = item.get("storage_resolution", {})
            store_id = str(resolution.get("store_id") or "")
            if store_id in representation_store_ids:
                matched_paths.append(
                    {
                        "path": item.get("path"),
                        "bytes": int(item.get("bytes") or 0),
                        "store_id": store_id,
                    }
                )
        identity_columns: dict[str, set[str]] = {}
        for database in databases:
            resolution = database.get("storage_resolution", {})
            if str(resolution.get("store_id") or "") not in representation_store_ids:
                continue
            for table in database.get("tables", []):
                for name in dict(table.get("identity_columns", {})):
                    identity_columns.setdefault(str(table.get("name") or ""), set()).add(name)
        duplicate_paths = sorted(
            {
                str(path)
                for group in exact_groups
                for path in group.get("paths", [])
                if any(
                    str(member.get("path") or "") == str(path)
                    and str(member.get("storage_resolution", {}).get("store_id") or "")
                    in representation_store_ids
                    for member in group.get("path_resolutions", [])
                )
            },
            key=str.casefold,
        )
        result.append(
            {
                "id": definition["id"],
                "raw_authority_store_ids": raw_authority_store_ids,
                "representation_store_ids": representation_store_ids,
                "authority_status": (
                    "UNIQUE_REGISTERED_RAW_OWNER"
                    if len(raw_authority_store_ids) == 1
                    else "UNIQUE_BY_LIFECYCLE_STAGE"
                    if len(raw_authority_store_ids) > 1
                    else "UNKNOWN_PROTECT"
                ),
                "authority_transition": definition["authority_transition"],
                "representations_checked": list(definition["representations"]),
                "matched_paths": sorted(matched_paths, key=lambda item: str(item["path"]).casefold()),
                "database_identity_columns": {
                    table: sorted(columns, key=str.casefold)
                    for table, columns in sorted(identity_columns.items(), key=lambda item: item[0].casefold())
                },
                "exact_duplicate_paths": duplicate_paths,
                "source_identity_requirement": "source_id + timestamp + parsed facts + artifact_ref + hash",
                "decision": "PROTECT_UNTIL_SOURCE_IDENTITY_AND_REBUILD_PARITY",
                "deletion_authorized": False,
            }
        )
    return {
        "policy": "raw evidence is retained; DB/task/artifact copies are derived until identity and rebuild consumers are proven",
        "groups": result,
    }


def _build_lifecycle_plan(
    *,
    context: Mapping[str, Any],
    files: Sequence[dict[str, Any]],
    stores: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    usage = _store_usage(files, stores)
    unresolved = [
        {"path": item["path"], "bytes": item["bytes"]}
        for item in files
        if item["storage_resolution"]["status"] != "REGISTERED"
    ]
    protected_unknown: list[dict[str, Any]] = []
    for item in files:
        resolution = item["storage_resolution"]
        if resolution["status"] != "REGISTERED" or resolution["data_class"] != UNKNOWN_CLASS:
            continue
        producers = [str(value) for value in resolution.get("producer", [])]
        producer_status = (
            "ACTIVE_PRODUCER"
            if resolution.get("active_producer") is True
            else "NO_ACTIVE_PRODUCER_PROVEN"
        )
        protected_unknown.append(
            {
                "path": item["path"],
                "bytes": item["bytes"],
                "store_id": resolution.get("store_id"),
                "producer": producers,
                "producer_status": producer_status,
            }
        )
    active_unknown = [
        item
        for item in protected_unknown
        if item["producer_status"] == "ACTIVE_PRODUCER"
    ]
    return {
        **copy.deepcopy(dict(context)),
        "execution_policy": {
            "mode": "PLAN_ONLY",
            "dml_ddl_vacuum_delete_move": False,
            "unknown_policy": UNKNOWN_POLICY,
            "automatic_cleanup_authorized": False,
        },
        "stores": usage,
        "unresolved": {
            "files": len(unresolved),
            "bytes": sum(int(item["bytes"]) for item in unresolved),
            "required_action": "ASSIGN_OWNER_AND_PROVE_CONSUMERS_BEFORE_RECLASSIFICATION",
            "items": unresolved,
        },
        "registered_unknown_protected": {
            "files": len(protected_unknown),
            "bytes": sum(int(item["bytes"]) for item in protected_unknown),
            "active_or_unproven_files": len(active_unknown),
            "active_or_unproven_bytes": sum(int(item["bytes"]) for item in active_unknown),
            "policy": UNKNOWN_POLICY,
            "items": protected_unknown,
        },
        "global_actions": [
            {
                "action": "NO_REINFLATION_REPLAY",
                "status": "REQUIRED",
                "scope": "every registered persistent producer",
            },
            {
                "action": "SITE_PACKAGE_AUTHORITY_PARITY",
                "status": "REQUIRED",
                "scope": "operational, history, results, artifacts and staging",
            },
            {
                "action": "UNKNOWN_OWNER_AUDIT",
                "status": "REQUIRED" if unresolved else "PASS",
                "scope": "all unresolved paths and database tables",
            },
        ],
    }


def _build_classification(
    *,
    context: Mapping[str, Any],
    files: Sequence[dict[str, Any]],
    databases: Sequence[dict[str, Any]],
    data_classes: Sequence[str],
) -> dict[str, Any]:
    totals = _classification_totals(files, data_classes)
    table_totals: dict[str, dict[str, int]] = defaultdict(
        lambda: {"tables": 0, "rows": 0, "logical_payload_bytes": 0}
    )
    table_map: list[dict[str, Any]] = []
    for database in databases:
        for table in database.get("tables", []):
            classification = table["lifecycle_classification"]
            data_class = str(classification["data_class"])
            logical = table.get("logical_payload", {})
            logical_bytes = int(logical.get("text_bytes", 0) or 0) + int(
                logical.get("blob_bytes", 0) or 0
            )
            rows = int(table.get("rows", 0) or 0)
            table_totals[data_class]["tables"] += 1
            table_totals[data_class]["rows"] += rows
            table_totals[data_class]["logical_payload_bytes"] += logical_bytes
            table_map.append(
                {
                    "database": database["path"],
                    "table": table.get("name"),
                    "classification": copy.deepcopy(classification),
                    "rows": rows,
                    "logical_payload_bytes": logical_bytes,
                }
            )
    return {
        **copy.deepcopy(dict(context)),
        "policy": {
            "required_classes": list(data_classes),
            "unknown_is_protected": True,
            "classification_source": "unique storage registry path match only",
        },
        "file_totals": totals,
        "table_totals": {
            name: table_totals[name] for name in sorted(table_totals, key=str.casefold)
        },
        "files": [
            {
                "path": item["path"],
                "bytes": item["bytes"],
                "classification": item["storage_resolution"]["data_class"],
                "protection": item["storage_resolution"]["protection"],
                "store_id": item["storage_resolution"]["store_id"],
                "resolution_status": item["storage_resolution"]["status"],
            }
            for item in files
        ],
        "database_tables": table_map,
    }


def _build_footprint(
    *,
    context: Mapping[str, Any],
    raw: Mapping[str, Any],
    files: Sequence[dict[str, Any]],
    databases: Sequence[dict[str, Any]],
    stores: Sequence[dict[str, Any]],
    optimization_impact: Mapping[str, Any] | None,
) -> dict[str, Any]:
    classes = sorted(
        {str(item["storage_resolution"]["data_class"]) for item in files},
        key=str.casefold,
    )
    by_class = _classification_totals(files, classes)
    by_store = _store_usage(files, stores)
    total = sum(int(item["bytes"]) for item in files)
    class_total = sum(int(item["bytes"]) for item in by_class.values())
    largest_databases = sorted(
        (
            {
                "path": item["path"],
                "bytes": item["bytes"],
                "store_id": item["storage_resolution"]["store_id"],
                "classification": item["storage_resolution"]["data_class"],
            }
            for item in databases
        ),
        key=lambda item: (-int(item["bytes"]), str(item["path"]).casefold()),
    )[:25]
    largest_tables = sorted(
        (
            {
                "database": database["path"],
                "table": table.get("name"),
                "rows": table.get("rows"),
                "logical_payload_bytes": int(
                    table.get("logical_payload", {}).get("text_bytes", 0) or 0
                )
                + int(table.get("logical_payload", {}).get("blob_bytes", 0) or 0),
                "classification": table["lifecycle_classification"]["data_class"],
            }
            for database in databases
            for table in database.get("tables", [])
        ),
        key=lambda item: (
            -int(item["logical_payload_bytes"]),
            str(item["database"]).casefold(),
            str(item["table"]).casefold(),
        ),
    )[:50]
    storage_report = _build_storage_report_sections(
        by_store=by_store,
        unknown_bytes=int(by_class.get(UNKNOWN_CLASS, {}).get("bytes", 0) or 0),
    )
    if optimization_impact is not None:
        storage_report = _apply_optimization_impact(
            storage_report, optimization_impact
        )
        impact_summary = {
            "before_bytes": total,
            "after_site_bytes": int(optimization_impact["after_site_bytes"]),
            "after_operational_bytes": int(
                optimization_impact["after_operational_bytes"]
            ),
            "history_moved_bytes": int(optimization_impact["history_moved_bytes"]),
            "duplicates_removed_bytes": int(
                optimization_impact["duplicates_removed_bytes"]
            ),
            "protected_bytes": int(optimization_impact["protected_bytes"]),
            "status": "ISOLATED_REHEARSAL_MEASURED",
            "note": (
                "Exact isolated-copy measurements are overlaid on the immutable "
                "read-only site baseline; no production mutation is implied."
            ),
        }
        measurement_status = "ISOLATED_REHEARSAL_OVERLAY"
    else:
        impact_summary = {
            "before_bytes": total,
            "after_site_bytes": None,
            "after_operational_bytes": None,
            "history_moved_bytes": None,
            "duplicates_removed_bytes": 0,
            "protected_bytes": by_class.get(UNKNOWN_CLASS, {}).get("bytes", 0),
            "status": "POST_REHEARSAL_MEASUREMENT_REQUIRED",
            "note": (
                "The raw inventory is a production read-only baseline. Post-rehearsal "
                "bytes must be supplied by isolated-copy evidence, never inferred."
            ),
        }
        measurement_status = "READ_ONLY_BASELINE"
    return {
        **copy.deepcopy(dict(context)),
        "measurement_scope": context["measurement_scope"],
        "measurement_status": measurement_status,
        "summary": {
            "site_total_bytes": total,
            "raw_inventory_total_bytes": raw.get("totals", {}).get("bytes"),
            "classification_total_bytes": class_total,
            "reconciliation_delta_bytes": total - class_total,
            "files": len(files),
            "sqlite_databases": len(databases),
            "unknown_bytes": by_class.get(UNKNOWN_CLASS, {}).get("bytes", 0),
        },
        "by_data_class": by_class,
        "by_registered_store": by_store,
        "all_databases_storage": storage_report,
        "largest_databases": largest_databases,
        "largest_tables_by_logical_payload": largest_tables,
        "optimization_impact": impact_summary,
        "future_growth_behavior": {
            "registered_stores": "OWNER_POLICY_PLUS_NO_REINFLATION_TEST_REQUIRED",
            "unknown_storage": "PROTECT_AND_ASSIGN_OWNER",
            "deletion_authorized_bytes": 0,
        },
    }


def _apply_optimization_impact(
    storage_report: Mapping[str, Any], impact: Mapping[str, Any]
) -> dict[str, Any]:
    result = copy.deepcopy(dict(storage_report))
    sections = result["sections"]
    impact_sections = impact["sections"]
    for name in _STORAGE_REPORT_SECTIONS:
        baseline = sections[name]
        measured = impact_sections[name]
        if int(baseline["before_bytes"]) != int(measured["before_bytes"]):
            raise StorageAuditError(
                f"optimization impact section {name} does not match classified baseline"
            )
        for field in (
            "after_operational_bytes",
            "history_moved_bytes",
            "duplicates_removed_bytes",
            "protected_bytes",
        ):
            baseline[field] = int(measured[field])
        baseline["measurement_status"] = "ISOLATED_REHEARSAL_OVERLAY"
        baseline["evidence"] = list(measured["evidence"])
    result["measurement_status"] = "ISOLATED_REHEARSAL_OVERLAY"
    return result


def _build_storage_report_sections(
    *,
    by_store: Sequence[Mapping[str, Any]],
    unknown_bytes: int,
) -> dict[str, Any]:
    sections: dict[str, dict[str, Any]] = {
        name: {
            "before_bytes": 0,
            "after_operational_bytes": None,
            "history_moved_bytes": None,
            "duplicates_removed_bytes": 0,
            "protected_bytes": 0,
            "authority": [],
            "future_growth_behavior": [],
            "stores": [],
            "measurement_status": "READ_ONLY_BASELINE",
        }
        for name in _STORAGE_REPORT_SECTIONS
    }
    for store in by_store:
        section = _storage_report_section(store)
        target = sections[section]
        before_bytes = int(store.get("before_bytes", 0) or 0)
        target["before_bytes"] += before_bytes
        target["duplicates_removed_bytes"] += int(
            store.get("duplicates_removed_bytes", 0) or 0
        )
        target["protected_bytes"] += int(store.get("protected_bytes", 0) or 0)
        store_id = str(store.get("store_id") or "")
        target["stores"].append(store_id)
        target["authority"].append(
            {
                "store_id": store_id,
                "authority": str(store.get("authority") or ""),
                "before_bytes": before_bytes,
            }
        )
        target["future_growth_behavior"].append(
            {
                "store_id": store_id,
                "behavior": str(store.get("future_growth_behavior") or ""),
            }
        )
    unknown = sections["Unknown/protected"]
    registered_unknown = int(unknown["before_bytes"])
    unresolved_bytes = max(0, unknown_bytes - registered_unknown)
    if unresolved_bytes:
        unknown["before_bytes"] += unresolved_bytes
        unknown["protected_bytes"] += unresolved_bytes
        unknown["authority"].append(
            {
                "store_id": None,
                "authority": "UNKNOWN_PROTECT",
                "before_bytes": unresolved_bytes,
            }
        )
        unknown["future_growth_behavior"].append(
            {
                "store_id": None,
                "behavior": "PROTECT_AND_ASSIGN_OWNER",
            }
        )
    return {
        "title": "ALL DATABASES / STORAGE",
        "grouping_basis": (
            "registered logical storage owner and declared data class; not database filename"
        ),
        "sections_overlap": False,
        "sections": sections,
    }


def _storage_report_section(store: Mapping[str, Any]) -> str:
    store_id = str(store.get("store_id") or "")
    data_type = str(store.get("data_type") or UNKNOWN_CLASS)
    if data_type == UNKNOWN_CLASS or store_id.startswith("unknown."):
        return "Unknown/protected"
    if store_id == "site.ground.active_raw":
        return "Syslog/Ping"
    if store_id.startswith("site.ground."):
        return "Ground/Unattended"
    if store_id.startswith("site.online_mr.") or store_id == "site.vehicle_mr.online":
        return "Online MR"
    if store_id.startswith("site.mesh."):
        return "MR Raw/MESH"
    if store_id.startswith("site.history."):
        return "History DBs/shards"
    if store_id.startswith("site.backups."):
        return "Backups"
    if (
        store_id.startswith("runtime.site_package.")
        or store_id.startswith("runtime.site_sync.")
        or store_id.startswith("site.sync.")
    ):
        return "Site Package staging"
    if store_id.startswith("runtime.") or store_id.endswith(".sqlite_sidecars"):
        return "Cache/temp"
    if data_type == "ARTIFACT_OR_RAW_FILE":
        return "Artifacts/raw"
    if store_id.startswith(
        (
            "site.traffic.",
            "site.wireless_scan.",
            "site.trackside.",
            "site.ac_mesh_link.",
            "site.car_network.",
            "site.wps.",
            "site.network_toolbox.",
        )
    ):
        return "Analysis"
    if data_type in {"HISTORICAL_RAW_FACT", "HISTORICAL_TREND"}:
        return "History DBs/shards"
    if data_type in {"CACHE_REBUILDABLE", "STAGING_TEMPORARY", "DISPOSABLE_DERIVED"}:
        return "Cache/temp"
    if data_type == "BACKUP_ROLLBACK":
        return "Backups"
    return "Operational DBs"


def _store_usage(
    records: Sequence[Mapping[str, Any]], stores: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    usage: dict[str, dict[str, Any]] = {}
    for store in stores:
        store_id = str(store["id"])
        usage[store_id] = {
            "store_id": store_id,
            "relative_path": store["relative_path"],
            "owner": store["owner"],
            "data_type": store["data_type"],
            "authority": store["authority"],
            "producer": copy.deepcopy(store["producer"]),
            "consumers": copy.deepcopy(store["consumers"]),
            "lifecycle_owner": store["retention_owner"],
            "rebuildable": store["rebuildable"],
            "site_package_policy": store["site_package_policy"],
            "backup_policy": store["backup_policy"],
            "migration_policy": store["migration_policy"],
            "source_evidence": copy.deepcopy(store.get("source_evidence", [])),
            "matched_files": 0,
            "before_bytes": 0,
            "after_operational_bytes": None,
            "history_moved_bytes": None,
            "duplicates_removed_bytes": 0,
            "protected_bytes": 0,
            "future_growth_behavior": (
                "UNKNOWN_PROTECT_AUDIT_REQUIRED"
                if store["data_type"] == UNKNOWN_CLASS
                else "REGISTERED_POLICY_REQUIRES_NO_REINFLATION_TEST"
            ),
        }
    for record in records:
        resolution = record.get("storage_resolution", {})
        store_id = resolution.get("store_id")
        if store_id not in usage:
            continue
        usage[store_id]["matched_files"] += 1
        usage[store_id]["before_bytes"] += int(record.get("bytes", 0) or 0)
        if resolution.get("protection") == UNKNOWN_POLICY:
            usage[store_id]["protected_bytes"] += int(record.get("bytes", 0) or 0)
    return [usage[key] for key in sorted(usage, key=str.casefold)]


def _classification_totals(
    files: Sequence[Mapping[str, Any]], data_classes: Sequence[str]
) -> dict[str, dict[str, int]]:
    result = {name: {"files": 0, "bytes": 0} for name in data_classes}
    for item in files:
        name = str(item["storage_resolution"]["data_class"])
        result.setdefault(name, {"files": 0, "bytes": 0})
        result[name]["files"] += 1
        result[name]["bytes"] += int(item["bytes"])
    return {name: result[name] for name in sorted(result, key=str.casefold)}


def _resolution_summary(files: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    result = {
        "registered_files": 0,
        "registered_bytes": 0,
        "unregistered_files": 0,
        "unregistered_bytes": 0,
        "ambiguous_files": 0,
        "ambiguous_bytes": 0,
        "protected_unknown_files": 0,
        "protected_unknown_bytes": 0,
    }
    for item in files:
        status = item["storage_resolution"]["status"]
        prefix = {
            "REGISTERED": "registered",
            "UNREGISTERED": "unregistered",
            "AMBIGUOUS": "ambiguous",
        }[status]
        result[f"{prefix}_files"] += 1
        result[f"{prefix}_bytes"] += int(item["bytes"])
        if item["storage_resolution"]["data_class"] == UNKNOWN_CLASS:
            result["protected_unknown_files"] += 1
            result["protected_unknown_bytes"] += int(item["bytes"])
    return result


def _validate_output_directory(
    output_dir: Path, *, site_root: Path, development_root: Path
) -> Path:
    destination = output_dir.resolve(strict=False)
    dev_root = development_root.resolve(strict=True)
    production_root = site_root.resolve(strict=False)
    if not _is_relative_to(destination, dev_root):
        raise StorageAuditError(
            f"output directory must be below development root {dev_root}: {destination}"
        )
    if _is_relative_to(destination, production_root) or _is_relative_to(
        production_root, destination
    ):
        raise StorageAuditError(
            f"output directory overlaps production site root {production_root}"
        )
    return destination


def _is_relative_to(path: Path, root: Path) -> bool:
    path_value = os.path.normcase(os.path.abspath(path))
    root_value = os.path.normcase(os.path.abspath(root))
    try:
        return os.path.commonpath((path_value, root_value)) == root_value
    except ValueError:
        return False


def _normalize_relative_path(value: str) -> str:
    normalized = value.replace("\\", "/").strip().strip("/")
    if not normalized or re.match(r"^[A-Za-z]:", normalized):
        raise StorageAuditError(f"expected a non-empty relative path: {value!r}")
    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise StorageAuditError(f"unsafe relative path: {value!r}")
    return "/".join(parts)


def _path_sort_key(value: Any) -> str:
    return str(value or "").replace("\\", "/").casefold()


def _nonnegative_int(value: Mapping[str, Any], key: str) -> int:
    item = value.get(key)
    if type(item) is not int or item < 0:
        raise StorageAuditError(f"{key} must be a non-negative integer")
    return item


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _atomic_write(path: Path, payload: bytes) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-inventory", required=True, type=Path)
    parser.add_argument("--storage-registry", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--global-inventory", type=Path)
    parser.add_argument("--optimization-impact", type=Path)
    parser.add_argument(
        "--final",
        action="store_true",
        dest="final_mode",
        help=(
            "emit final evidence; requires global inventory and optimization impact "
            "and binds every output to Git HEAD, registry, and finalizer digests"
        ),
    )
    parser.add_argument(
        "--development-root", type=Path, default=DEFAULT_DEVELOPMENT_ROOT
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    outputs = finalize_site_storage_audit(
        raw_inventory_path=args.raw_inventory,
        registry_path=args.storage_registry,
        output_dir=args.output_dir,
        repo_root=args.repo_root,
        development_root=args.development_root,
        global_inventory_path=args.global_inventory,
        optimization_impact_path=args.optimization_impact,
        final_mode=args.final_mode,
        overwrite=args.overwrite,
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "outputs": {key: str(value) for key, value in outputs.items()},
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
