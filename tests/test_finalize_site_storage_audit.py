from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.maintenance.finalize_site_storage_audit import (
    OUTPUT_FILENAMES,
    _STORAGE_REPORT_SECTIONS,
    _parser,
    StorageAuditError,
    finalize_site_storage_audit,
)


def _store(
    store_id: str,
    relative_path: str,
    *,
    data_type: str = "OPERATIONAL_CURRENT",
    source_locations: list[str] | None = None,
) -> dict[str, object]:
    return {
        "id": store_id,
        "relative_path": relative_path,
        "owner": f"{store_id}.owner",
        "code_owners": ["test"],
        "data_type": data_type,
        "authority": f"{store_id}.authority",
        "producer": [f"{store_id}.producer"],
        "consumers": [f"{store_id}.consumer"],
        "retention_owner": (
            "UNKNOWN_PROTECT" if data_type == "UNKNOWN" else f"{store_id}.lifecycle"
        ),
        "rebuildable": False,
        "site_package_policy": "include",
        "backup_policy": "bounded",
        "migration_policy": "recover and cleanup",
        "schema_version": 1,
        "allowed_data_classes": [data_type],
        "forbidden_data_classes": [],
        "source_locations": source_locations or ["owner.py"],
        **({"active_producer": True} if data_type == "UNKNOWN" else {}),
    }


def _registry(stores: list[dict[str, object]]) -> dict[str, object]:
    return {
        "version": 1,
        "unknown_policy": "PROTECT",
        "data_classes": [
            "OPERATIONAL_CURRENT",
            "HISTORICAL_RAW_FACT",
            "HISTORICAL_TREND",
            "ARTIFACT_OR_RAW_FILE",
            "CACHE_REBUILDABLE",
            "STAGING_TEMPORARY",
            "BACKUP_ROLLBACK",
            "DISPOSABLE_DERIVED",
            "UNKNOWN",
        ],
        "infrastructure_locations": [],
        "stores": stores,
    }


def _table(name: str = "events") -> dict[str, object]:
    return {
        "name": name,
        "sql": f"CREATE TABLE {name} (id TEXT, payload TEXT)",
        "columns": [],
        "indexes": [{"name": f"idx_{name}", "columns": ["id"]}],
        "dbstat": None,
        "classification": "UNKNOWN",
        "classification_reason": "raw audit requires owner map",
        "rows": 2,
        "logical_payload": {
            "text_bytes": 20,
            "blob_bytes": 4,
            "max_text_or_blob_bytes": 12,
        },
        "content_columns": {
            "payload": {
                "bytes": 20,
                "duplicate_values": 1,
                "distinct_hashes": 1,
            }
        },
        "time_ranges": {"created_at": {"min": "2026-01-01", "max": "2026-01-02"}},
        "identity_columns": {"source_id": {"distinct": 1}},
        "duplicate_content": {
            "row_content_sha256": "a" * 64,
            "duplicate_rows": 1,
            "duplicate_rows_method": "EXACT_ROW_SHA256",
        },
    }


def _raw(files: list[dict[str, object]]) -> dict[str, object]:
    databases = []
    for item in files:
        if item.get("sqlite_header"):
            databases.append(
                {
                    "path": item["path"],
                    "bytes": item["bytes"],
                    "sha256": item["sha256"],
                    "open_contract": "mode=ro&immutable=1",
                    "database_pragmas": {
                        "page_size": 4096,
                        "page_count": 1,
                        "freelist_count": 0,
                    },
                    "dbstat_available": False,
                    "dbstat_error": "no such table: dbstat",
                    "schema_objects": [],
                    "tables": [_table()],
                    "summary": {"rows": 2},
                    "elapsed_seconds": 0.01,
                }
            )
    duplicate_paths = [str(item["path"]) for item in files[:2]]
    duplicate_bytes = int(files[0]["bytes"]) if len(files) > 1 else 0
    return {
        "schema_version": 1,
        "generated_at_utc": "2026-08-16T00:00:00+00:00",
        "site_root": "D:/NetConsoleData/sites/production-site",
        "safety_contract": {"production_access": "READ_ONLY"},
        "totals": {
            "files": len(files),
            "bytes": sum(int(item["bytes"]) for item in files),
            "sqlite_files_by_header": len(databases),
            "sqlite_bytes": sum(
                int(item["bytes"]) for item in files if item.get("sqlite_header")
            ),
            "exact_duplicate_groups": 1 if len(files) > 1 else 0,
            "exact_duplicate_bytes": duplicate_bytes,
        },
        "by_top_level": [],
        "by_extension": [],
        "by_classification": [],
        "duplicate_groups": (
            [
                {
                    "bytes_each": int(files[0]["bytes"]),
                    "sha256": "d" * 64,
                    "count": 2,
                    "duplicate_bytes": duplicate_bytes,
                    "paths": duplicate_paths,
                }
            ]
            if len(files) > 1
            else []
        ),
        "zip_archives": [],
        "sqlite_databases": databases,
        "files": files,
        "production_metadata_verification": {
            "before_files": len(files),
            "after_files": len(files),
            "added": [],
            "removed": [],
            "changed": [],
            "unchanged": True,
        },
    }


def _file(path: str, size: int, *, sqlite: bool = False) -> dict[str, object]:
    return {
        "path": path,
        "bytes": size,
        "mtime_ns": 1,
        "mtime_utc": "2026-08-16T00:00:00+00:00",
        "classification": "UNKNOWN",
        "classification_basis": "raw evidence",
        "extension": ".db" if sqlite else ".log",
        "sqlite_header": sqlite,
        "sha256": "a" * 64,
        "sha256_source": "COMPUTED",
    }


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _impact(
    raw_path: Path,
    *,
    operational_before: int,
    artifact_before: int,
    global_raw_path: Path | None = None,
) -> dict[str, object]:
    sections = {
        name: {
            "before_bytes": 0,
            "after_operational_bytes": 0,
            "history_moved_bytes": 0,
            "duplicates_removed_bytes": 0,
            "protected_bytes": 0,
            "evidence": ["isolated rehearsal"],
        }
        for name in _STORAGE_REPORT_SECTIONS
    }
    sections["Operational DBs"].update(
        {
            "before_bytes": operational_before,
            "after_operational_bytes": max(0, operational_before - 20),
            "history_moved_bytes": min(20, operational_before),
        }
    )
    sections["Artifacts/raw"].update(
        {
            "before_bytes": artifact_before,
            "after_operational_bytes": artifact_before,
        }
    )
    site_digest = hashlib.sha256(raw_path.read_bytes()).hexdigest()
    if global_raw_path is None:
        inventory_digest = site_digest
        measurement_scope = "entire recursive site inventory"
    else:
        global_digest = hashlib.sha256(global_raw_path.read_bytes()).hexdigest()
        binding = json.dumps(
            {
                "global_inventory_sha256": global_digest,
                "site_inventory_sha256": site_digest,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        inventory_digest = hashlib.sha256(binding).hexdigest()
        measurement_scope = "entire recursive site plus data-root global inventory"
    return {
        "format": "netconsole-site-storage-impact-v1",
        "schema_version": 1,
        "source_inventory_sha256": inventory_digest,
        "measurement_scope": measurement_scope,
        "measurement_status": "ISOLATED_REHEARSAL_OVERLAY",
        "before_site_bytes": operational_before + artifact_before,
        "after_site_bytes": max(0, operational_before - 20) + artifact_before,
        "after_operational_bytes": max(0, operational_before - 20)
        + artifact_before,
        "history_moved_bytes": min(20, operational_before),
        "duplicates_removed_bytes": 0,
        "protected_bytes": 0,
        "sections": sections,
    }


def _run(
    tmp_path: Path,
    *,
    files: list[dict[str, object]],
    stores: list[dict[str, object]],
    output_name: str = "output",
    overwrite: bool = False,
) -> tuple[Path, dict[str, Path]]:
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    (repo / "owner.py").write_text("OWNER = True\n", encoding="utf-8")
    raw_path = tmp_path / "raw.json"
    registry_path = tmp_path / "registry.json"
    _write_json(raw_path, _raw(files))
    _write_json(registry_path, _registry(stores))
    output = tmp_path / output_name
    paths = finalize_site_storage_audit(
        raw_inventory_path=raw_path,
        registry_path=registry_path,
        output_dir=output,
        repo_root=repo,
        development_root=tmp_path,
        overwrite=overwrite,
    )
    return output, paths


def test_finalizer_generates_all_outputs_and_retains_table_profiles(
    tmp_path: Path,
) -> None:
    files = [
        _file("db/devices.db", 100, sqlite=True),
        _file("files/raw/session.log", 100),
    ]
    stores = [
        _store("site.devices", "sites/{site_id}/db/devices.db"),
        _store(
            "site.raw",
            "sites/{site_id}/files/raw/**",
            data_type="ARTIFACT_OR_RAW_FILE",
        ),
    ]

    output, paths = _run(tmp_path, files=files, stores=stores)

    assert set(paths) == set(OUTPUT_FILENAMES)
    assert all(path.is_file() for path in paths.values())
    inventory = json.loads(
        (output / "SITE_STORAGE_INVENTORY.json").read_text(encoding="utf-8")
    )
    database = inventory["sqlite_databases"][0]
    table = database["tables"][0]
    assert database["storage_resolution"]["store_id"] == "site.devices"
    assert table["rows"] == 2
    assert table["logical_payload"]["text_bytes"] == 20
    assert table["indexes"][0]["name"] == "idx_events"
    assert table["time_ranges"]["created_at"]["min"] == "2026-01-01"
    assert table["identity_columns"]["source_id"]["distinct"] == 1
    assert table["lifecycle_classification"]["data_class"] == "OPERATIONAL_CURRENT"


def test_template_match_and_source_evidence(tmp_path: Path) -> None:
    files = [_file("history/devices-2026-08-0002.db", 12, sqlite=True)]
    stores = [
        _store(
            "site.history",
            "sites/{site_id}/history/devices-YYYY-MM[-NNNN].db",
            data_type="HISTORICAL_RAW_FACT",
            source_locations=["owner.py", "missing.py"],
        )
    ]

    output, _ = _run(tmp_path, files=files, stores=stores)

    owner_map = json.loads(
        (output / "DATABASE_OWNER_MAP.json").read_text(encoding="utf-8")
    )
    database = owner_map["databases"][0]
    evidence = owner_map["registered_store_usage"][0]["source_evidence"]
    assert database["store_resolution"]["store_id"] == "site.history"
    assert database["lifecycle_profile"]["current_history_ratio"]["history_rows"] == 2
    assert database["lifecycle_profile"]["rebuildable_ratio"]["rows"] == 0.0
    assert evidence == [
        {"exists": False, "kind": "missing", "path": "missing.py"},
        {"exists": True, "kind": "file", "path": "owner.py"},
    ]


def test_ambiguous_and_unmatched_paths_are_unknown_and_protected(
    tmp_path: Path,
) -> None:
    files = [
        _file("db/shared.db", 20, sqlite=True),
        _file("unowned/value.bin", 30),
    ]
    stores = [
        _store("site.first", "sites/{site_id}/db/shared.db"),
        _store("site.second", "sites/{site_id}/db/shared.db"),
    ]

    output, _ = _run(tmp_path, files=files, stores=stores)

    classification = json.loads(
        (output / "DATA_LIFECYCLE_CLASSIFICATION.json").read_text(encoding="utf-8")
    )
    items = {item["path"]: item for item in classification["files"]}
    assert items["db/shared.db"]["resolution_status"] == "AMBIGUOUS"
    assert items["db/shared.db"]["classification"] == "UNKNOWN"
    assert items["db/shared.db"]["protection"] == "PROTECT"
    assert items["unowned/value.bin"]["resolution_status"] == "UNREGISTERED"
    assert items["unowned/value.bin"]["classification"] == "UNKNOWN"
    assert classification["file_totals"]["UNKNOWN"] == {
        "bytes": 50,
        "files": 2,
    }


def test_registered_unknown_is_protected_but_not_an_unresolved_owner(
    tmp_path: Path,
) -> None:
    files = [_file("legacy/protected.bin", 30)]
    stores = [
        _store(
            "site.legacy.protected",
            "sites/{site_id}/legacy/**",
            data_type="UNKNOWN",
        )
    ]
    stores[0]["authority"] = "UNKNOWN_PROTECT"
    stores[0]["retention_owner"] = "UNKNOWN_PROTECT"

    output, _ = _run(tmp_path, files=files, stores=stores)

    lifecycle = json.loads(
        (output / "STORAGE_LIFECYCLE_PLAN.json").read_text(encoding="utf-8")
    )
    assert lifecycle["unresolved"] == {
        "files": 0,
        "bytes": 0,
        "required_action": "ASSIGN_OWNER_AND_PROVE_CONSUMERS_BEFORE_RECLASSIFICATION",
        "items": [],
    }
    assert lifecycle["registered_unknown_protected"] == {
        "files": 1,
        "bytes": 30,
        "active_or_unproven_files": 1,
        "active_or_unproven_bytes": 30,
        "policy": "PROTECT",
        "items": [
            {
                "path": "legacy/protected.bin",
                "bytes": 30,
                "store_id": "site.legacy.protected",
                "producer": ["site.legacy.protected.producer"],
                "producer_status": "ACTIVE_PRODUCER",
            }
        ],
    }


def test_mixed_store_does_not_guess_table_classification(tmp_path: Path) -> None:
    store = _store("site.mixed", "sites/{site_id}/db/mixed.db")
    store["allowed_data_classes"] = [
        "OPERATIONAL_CURRENT",
        "HISTORICAL_RAW_FACT",
    ]

    output, _ = _run(
        tmp_path,
        files=[_file("db/mixed.db", 40, sqlite=True)],
        stores=[store],
    )

    inventory = json.loads(
        (output / "SITE_STORAGE_INVENTORY.json").read_text(encoding="utf-8")
    )
    classification = inventory["sqlite_databases"][0]["tables"][0][
        "lifecycle_classification"
    ]
    assert classification["data_class"] == "UNKNOWN"
    assert classification["protection"] == "PROTECT"
    assert "no explicit table rule" in classification["basis"]


def test_mixed_store_uses_exact_table_rule_with_owner_chain(tmp_path: Path) -> None:
    store = _store("site.mixed", "sites/{site_id}/db/mixed.db")
    store["allowed_data_classes"] = [
        "OPERATIONAL_CURRENT",
        "HISTORICAL_RAW_FACT",
    ]
    store["table_rules"] = [
        {
            "tables": ["events"],
            "data_class": "HISTORICAL_RAW_FACT",
            "authority": "immutable event fact authority",
            "producer": ["EventRepository"],
            "consumers": ["EventQueryService"],
            "lifecycle_owner": "HistoryStore",
            "rebuildable": False,
            "source_locations": ["owner.py"],
        }
    ]

    output, _ = _run(
        tmp_path,
        files=[_file("db/mixed.db", 40, sqlite=True)],
        stores=[store],
    )

    inventory = json.loads(
        (output / "SITE_STORAGE_INVENTORY.json").read_text(encoding="utf-8")
    )
    classification = inventory["sqlite_databases"][0]["tables"][0][
        "lifecycle_classification"
    ]
    assert classification == {
        "authority": "immutable event fact authority",
        "basis": "explicit table rule from store site.mixed",
        "consumers": ["EventQueryService"],
        "data_class": "HISTORICAL_RAW_FACT",
        "lifecycle_owner": "HistoryStore",
        "producer": ["EventRepository"],
        "protection": "OWNER_MANAGED",
        "rebuildable": False,
        "source_evidence": [
            {"exists": True, "kind": "file", "path": "owner.py"}
        ],
    }


def test_duplicate_exact_table_rules_are_rejected(tmp_path: Path) -> None:
    store = _store("site.mixed", "sites/{site_id}/db/mixed.db")
    store["allowed_data_classes"] = [
        "OPERATIONAL_CURRENT",
        "HISTORICAL_RAW_FACT",
    ]
    rule = {
        "tables": ["events"],
        "data_class": "HISTORICAL_RAW_FACT",
        "authority": "event authority",
        "producer": ["EventRepository"],
        "consumers": ["EventQueryService"],
        "lifecycle_owner": "HistoryStore",
        "rebuildable": False,
        "source_locations": ["owner.py"],
    }
    store["table_rules"] = [rule, dict(rule)]

    with pytest.raises(StorageAuditError, match="duplicate table rules"):
        _run(
            tmp_path,
            files=[_file("db/mixed.db", 40, sqlite=True)],
            stores=[store],
        )


def test_outputs_are_deterministic_and_default_to_no_overwrite(
    tmp_path: Path,
) -> None:
    files = [_file("db/devices.db", 100, sqlite=True)]
    stores = [_store("site.devices", "sites/{site_id}/db/devices.db")]
    first, _ = _run(tmp_path, files=files, stores=stores, output_name="first")
    second, _ = _run(tmp_path, files=files, stores=stores, output_name="second")

    for name in OUTPUT_FILENAMES:
        assert (first / name).read_bytes() == (second / name).read_bytes()

    with pytest.raises(StorageAuditError, match="refusing to overwrite"):
        _run(tmp_path, files=files, stores=stores, output_name="first")


def test_final_mode_requires_complete_evidence_and_cli_is_explicit(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "owner.py").write_text("OWNER = True\n", encoding="utf-8")
    raw_path = tmp_path / "raw.json"
    registry_path = tmp_path / "registry.json"
    _write_json(raw_path, _raw([_file("db/devices.db", 100, sqlite=True)]))
    _write_json(
        registry_path,
        _registry([_store("site.devices", "sites/{site_id}/db/devices.db")]),
    )

    with pytest.raises(StorageAuditError, match="final mode requires complete"):
        finalize_site_storage_audit(
            raw_inventory_path=raw_path,
            registry_path=registry_path,
            output_dir=tmp_path / "output",
            repo_root=repo,
            development_root=tmp_path,
            final_mode=True,
        )
    assert not (tmp_path / "output").exists()

    args = _parser().parse_args(
        [
            "--raw-inventory",
            str(raw_path),
            "--storage-registry",
            str(registry_path),
            "--output-dir",
            str(tmp_path / "cli-output"),
            "--final",
        ]
    )
    assert args.final_mode is True


def test_final_mode_binds_outputs_to_head_registry_and_script(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "owner.py").write_text("OWNER = True\n", encoding="utf-8")
    raw_path = tmp_path / "site-raw.json"
    global_raw_path = tmp_path / "global-raw.json"
    registry_path = tmp_path / "registry.json"
    impact_path = tmp_path / "impact.json"
    _write_json(raw_path, _raw([_file("db/devices.db", 100, sqlite=True)]))
    global_raw = _raw([])
    global_raw["site_root"] = "D:/NetConsoleData"
    global_raw["inventory_scope"] = "DATA_ROOT_GLOBAL_EXCLUDING_SITES"
    _write_json(global_raw_path, global_raw)
    _write_json(
        registry_path,
        _registry([_store("site.devices", "sites/{site_id}/db/devices.db")]),
    )
    _write_json(
        impact_path,
        _impact(
            raw_path,
            global_raw_path=global_raw_path,
            operational_before=100,
            artifact_before=0,
        ),
    )
    expected_head = "f" * 40
    monkeypatch.setattr(
        "scripts.maintenance.finalize_site_storage_audit._resolve_git_head",
        lambda _repo_root: expected_head,
    )

    output = tmp_path / "output"
    finalize_site_storage_audit(
        raw_inventory_path=raw_path,
        global_inventory_path=global_raw_path,
        registry_path=registry_path,
        optimization_impact_path=impact_path,
        output_dir=output,
        repo_root=repo,
        development_root=tmp_path,
        final_mode=True,
    )

    registry_sha256 = hashlib.sha256(registry_path.read_bytes()).hexdigest()
    impact_sha256 = hashlib.sha256(impact_path.read_bytes()).hexdigest()
    for name in OUTPUT_FILENAMES:
        report = json.loads((output / name).read_text(encoding="utf-8"))
        evidence = report["final_evidence"]
        assert report["audit_mode"] == "FINAL_EVIDENCE"
        assert evidence["mode"] == "FINAL"
        assert evidence["status"] == "BOUND_TO_SOURCE"
        assert evidence["git_head"] == expected_head
        assert evidence["registry_sha256"] == registry_sha256
        assert evidence["optimization_impact_sha256"] == impact_sha256
        assert len(evidence["finalizer_script_sha256"]) == 64
        assert len(evidence["binding_sha256"]) == 64
    footprint = json.loads(
        (output / "SITE_STORAGE_FOOTPRINT.json").read_text(encoding="utf-8")
    )
    assert footprint["optimization_impact"]["after_operational_bytes"] == 80
    assert footprint["optimization_impact"]["history_moved_bytes"] == 20


def test_final_mode_rejects_null_after_or_history_measurements(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "owner.py").write_text("OWNER = True\n", encoding="utf-8")
    raw_path = tmp_path / "site-raw.json"
    global_raw_path = tmp_path / "global-raw.json"
    registry_path = tmp_path / "registry.json"
    impact_path = tmp_path / "impact.json"
    _write_json(raw_path, _raw([_file("db/devices.db", 100, sqlite=True)]))
    global_raw = _raw([])
    global_raw["site_root"] = "D:/NetConsoleData"
    global_raw["inventory_scope"] = "DATA_ROOT_GLOBAL_EXCLUDING_SITES"
    _write_json(global_raw_path, global_raw)
    _write_json(
        registry_path,
        _registry([_store("site.devices", "sites/{site_id}/db/devices.db")]),
    )
    impact = _impact(
        raw_path,
        global_raw_path=global_raw_path,
        operational_before=100,
        artifact_before=0,
    )
    impact["sections"]["Operational DBs"]["after_operational_bytes"] = None
    _write_json(impact_path, impact)

    with pytest.raises(
        StorageAuditError,
        match=r"Operational DBs\.after_operational_bytes must be a non-negative integer",
    ):
        finalize_site_storage_audit(
            raw_inventory_path=raw_path,
            global_inventory_path=global_raw_path,
            registry_path=registry_path,
            optimization_impact_path=impact_path,
            output_dir=tmp_path / "output",
            repo_root=repo,
            development_root=tmp_path,
            final_mode=True,
        )


def test_final_mode_rejects_ambiguous_or_unregistered_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "owner.py").write_text("OWNER = True\n", encoding="utf-8")
    raw_path = tmp_path / "raw.json"
    global_raw_path = tmp_path / "global-raw.json"
    registry_path = tmp_path / "registry.json"
    impact_path = tmp_path / "impact.json"
    _write_json(raw_path, _raw([_file("unowned/value.bin", 100)]))
    global_raw = _raw([])
    global_raw["inventory_scope"] = "DATA_ROOT_GLOBAL_EXCLUDING_SITES"
    _write_json(global_raw_path, global_raw)
    _write_json(
        registry_path,
        _registry([_store("site.devices", "sites/{site_id}/db/devices.db")]),
    )
    impact = _impact(
        raw_path,
        global_raw_path=global_raw_path,
        operational_before=0,
        artifact_before=100,
    )
    impact["sections"]["Artifacts/raw"].update(
        {"before_bytes": 0, "after_operational_bytes": 0}
    )
    impact["sections"]["Unknown/protected"].update(
        {
            "before_bytes": 100,
            "after_operational_bytes": 100,
            "protected_bytes": 100,
        }
    )
    impact["protected_bytes"] = 100
    _write_json(impact_path, impact)
    monkeypatch.setattr(
        "scripts.maintenance.finalize_site_storage_audit._resolve_git_head",
        lambda _repo: "a" * 40,
    )

    with pytest.raises(
        StorageAuditError,
        match="final mode rejects ambiguous or unregistered storage owners",
    ):
        finalize_site_storage_audit(
            raw_inventory_path=raw_path,
            global_inventory_path=global_raw_path,
            registry_path=registry_path,
            optimization_impact_path=impact_path,
            output_dir=tmp_path / "output",
            repo_root=repo,
            development_root=tmp_path,
            final_mode=True,
        )


def test_final_mode_rejects_registered_unknown_with_unproven_producer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "owner.py").write_text("OWNER = True\n", encoding="utf-8")
    raw_path = tmp_path / "raw.json"
    global_raw_path = tmp_path / "global-raw.json"
    registry_path = tmp_path / "registry.json"
    impact_path = tmp_path / "impact.json"
    _write_json(raw_path, _raw([_file("legacy/value.bin", 100)]))
    global_raw = _raw([])
    global_raw["inventory_scope"] = "DATA_ROOT_GLOBAL_EXCLUDING_SITES"
    _write_json(global_raw_path, global_raw)
    store = _store(
        "unknown.active",
        "sites/{site_id}/legacy/**",
        data_type="UNKNOWN",
    )
    store["authority"] = "UNKNOWN_PROTECT"
    store["retention_owner"] = "UNKNOWN_PROTECT"
    _write_json(registry_path, _registry([store]))
    impact = _impact(
        raw_path,
        global_raw_path=global_raw_path,
        operational_before=0,
        artifact_before=100,
    )
    impact["sections"]["Artifacts/raw"].update(
        {"before_bytes": 0, "after_operational_bytes": 0}
    )
    impact["sections"]["Unknown/protected"].update(
        {
            "before_bytes": 100,
            "after_operational_bytes": 100,
            "protected_bytes": 100,
        }
    )
    impact["protected_bytes"] = 100
    _write_json(impact_path, impact)
    monkeypatch.setattr(
        "scripts.maintenance.finalize_site_storage_audit._resolve_git_head",
        lambda _repo: "a" * 40,
    )

    with pytest.raises(
        StorageAuditError,
        match="registered UNKNOWN storage with active or unproven producers",
    ):
        finalize_site_storage_audit(
            raw_inventory_path=raw_path,
            global_inventory_path=global_raw_path,
            registry_path=registry_path,
            optimization_impact_path=impact_path,
            output_dir=tmp_path / "output",
            repo_root=repo,
            development_root=tmp_path,
            final_mode=True,
        )


def test_duplicate_and_footprint_totals_reconcile(tmp_path: Path) -> None:
    files = [
        _file("files/raw/a.log", 25),
        _file("files/raw/b.log", 25),
    ]
    stores = [
        _store(
            "site.raw",
            "sites/{site_id}/files/raw/**",
            data_type="ARTIFACT_OR_RAW_FILE",
        )
    ]

    output, _ = _run(tmp_path, files=files, stores=stores)

    duplication = json.loads(
        (output / "STORAGE_DUPLICATION_AUDIT.json").read_text(encoding="utf-8")
    )
    footprint = json.loads(
        (output / "SITE_STORAGE_FOOTPRINT.json").read_text(encoding="utf-8")
    )
    assert duplication["summary"]["exact_duplicate_bytes_lower_bound"] == 25
    assert duplication["summary"]["reconciles_with_raw_inventory"] is True
    assert duplication["policy"]["deletion_authorized_bytes"] == 0
    assert footprint["summary"]["site_total_bytes"] == 50
    assert footprint["summary"]["classification_total_bytes"] == 50
    assert footprint["summary"]["reconciliation_delta_bytes"] == 0
    assert footprint["optimization_impact"]["after_site_bytes"] is None
    storage = footprint["all_databases_storage"]
    assert storage["title"] == "ALL DATABASES / STORAGE"
    assert storage["sections_overlap"] is False
    assert storage["sections"]["Artifacts/raw"]["before_bytes"] == 50
    assert storage["sections"]["Artifacts/raw"]["authority"] == [
        {
            "authority": "site.raw.authority",
            "before_bytes": 50,
            "store_id": "site.raw",
        }
    ]


def test_duplication_audit_declares_raw_authority_without_authorizing_delete(
    tmp_path: Path,
) -> None:
    output, _ = _run(
        tmp_path,
        files=[_file("files/rail_transit/mr_raw_mesh/profile/raw/source.log", 25)],
        stores=[
            _store(
                "site.mesh.raw",
                "sites/{site_id}/files/rail_transit/mr_raw_mesh/{profile_id}/raw/**",
                data_type="ARTIFACT_OR_RAW_FILE",
            )
        ],
    )

    duplication = json.loads(
        (output / "STORAGE_DUPLICATION_AUDIT.json").read_text(encoding="utf-8")
    )
    mesh = next(
        item
        for item in duplication["raw_authority_audit"]["groups"]
        if item["id"] == "mesh_raw"
    )
    assert mesh["raw_authority_store_ids"] == ["site.mesh.raw"]
    assert mesh["representation_store_ids"] == ["site.mesh.raw"]
    assert mesh["authority_status"] == "UNIQUE_REGISTERED_RAW_OWNER"
    assert mesh["deletion_authorized"] is False
    assert mesh["matched_paths"] == [
        {
            "bytes": 25,
            "path": "files/rail_transit/mr_raw_mesh/profile/raw/source.log",
            "store_id": "site.mesh.raw",
        }
    ]


def test_output_must_remain_below_explicit_development_root(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "owner.py").write_text("OWNER = True\n", encoding="utf-8")
    raw_path = tmp_path / "raw.json"
    registry_path = tmp_path / "registry.json"
    _write_json(raw_path, _raw([_file("db/devices.db", 1, sqlite=True)]))
    _write_json(
        registry_path,
        _registry([_store("site.devices", "sites/{site_id}/db/devices.db")]),
    )
    development_root = tmp_path / "allowed"
    development_root.mkdir()

    with pytest.raises(StorageAuditError, match="below development root"):
        finalize_site_storage_audit(
            raw_inventory_path=raw_path,
            registry_path=registry_path,
            output_dir=tmp_path / "outside",
            repo_root=repo,
            development_root=development_root,
        )


def test_global_inventory_is_classified_without_overlapping_site_scope(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "owner.py").write_text("OWNER = True\n", encoding="utf-8")
    site_raw_path = tmp_path / "site-raw.json"
    global_raw_path = tmp_path / "global-raw.json"
    registry_path = tmp_path / "registry.json"
    _write_json(site_raw_path, _raw([_file("db/devices.db", 100, sqlite=True)]))
    global_raw = _raw([_file("runtime/cache/runtime.db", 25, sqlite=True)])
    global_raw["site_root"] = "D:/NetConsoleData"
    global_raw["inventory_scope"] = "DATA_ROOT_GLOBAL_EXCLUDING_SITES"
    _write_json(global_raw_path, global_raw)
    _write_json(
        registry_path,
        _registry(
            [
                _store("site.devices", "sites/{site_id}/db/devices.db"),
                _store(
                    "runtime.cache",
                    "runtime/cache/**",
                    data_type="CACHE_REBUILDABLE",
                ),
            ]
        ),
    )

    output = tmp_path / "output"
    finalize_site_storage_audit(
        raw_inventory_path=site_raw_path,
        global_inventory_path=global_raw_path,
        registry_path=registry_path,
        output_dir=output,
        repo_root=repo,
        development_root=tmp_path,
    )

    inventory = json.loads(
        (output / "SITE_STORAGE_INVENTORY.json").read_text(encoding="utf-8")
    )
    assert inventory["measurement_scope"] == (
        "entire recursive site plus data-root global inventory"
    )
    assert len(inventory["source_inventories"]) == 2
    assert inventory["summary"]["bytes"] == 125
    assert {
        item["storage_resolution"]["store_id"]
        for item in inventory["files"]
    } == {"site.devices", "runtime.cache"}


def test_site_owner_never_claims_same_relative_path_from_global_scope(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "owner.py").write_text("OWNER = True\n", encoding="utf-8")
    site_raw_path = tmp_path / "site-raw.json"
    global_raw_path = tmp_path / "global-raw.json"
    registry_path = tmp_path / "registry.json"
    _write_json(site_raw_path, _raw([_file("db/devices.db", 100, sqlite=True)]))
    global_raw = _raw([_file("db/devices.db", 25, sqlite=True)])
    global_raw["site_root"] = "D:/NetConsoleData"
    global_raw["inventory_scope"] = "DATA_ROOT_GLOBAL_EXCLUDING_SITES"
    _write_json(global_raw_path, global_raw)
    _write_json(
        registry_path,
        _registry([_store("site.devices", "sites/{site_id}/db/devices.db")]),
    )

    output = tmp_path / "output"
    finalize_site_storage_audit(
        raw_inventory_path=site_raw_path,
        global_inventory_path=global_raw_path,
        registry_path=registry_path,
        output_dir=output,
        repo_root=repo,
        development_root=tmp_path,
    )

    inventory = json.loads(
        (output / "SITE_STORAGE_INVENTORY.json").read_text(encoding="utf-8")
    )
    files = {
        (item["inventory_scope"], item["path"]): item["storage_resolution"]
        for item in inventory["files"]
    }
    assert files[("SITE_ROOT", "db/devices.db")]["store_id"] == "site.devices"
    assert files[("DATA_ROOT_GLOBAL_EXCLUDING_SITES", "db/devices.db")][
        "status"
    ] == "UNREGISTERED"


def test_global_inventory_rejects_sites_scope_overlap(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "owner.py").write_text("OWNER = True\n", encoding="utf-8")
    site_raw_path = tmp_path / "site-raw.json"
    global_raw_path = tmp_path / "global-raw.json"
    registry_path = tmp_path / "registry.json"
    _write_json(site_raw_path, _raw([]))
    global_raw = _raw([_file("sites/site-one/db/devices.db", 1, sqlite=True)])
    global_raw["inventory_scope"] = "DATA_ROOT_GLOBAL_EXCLUDING_SITES"
    _write_json(global_raw_path, global_raw)
    _write_json(registry_path, _registry([]))

    with pytest.raises(StorageAuditError, match="must exclude sites"):
        finalize_site_storage_audit(
            raw_inventory_path=site_raw_path,
            global_inventory_path=global_raw_path,
            registry_path=registry_path,
            output_dir=tmp_path / "output",
            repo_root=repo,
            development_root=tmp_path,
        )


def test_optimization_impact_overlay_reconciles_all_totals(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "owner.py").write_text("OWNER = True\n", encoding="utf-8")
    raw_path = tmp_path / "raw.json"
    registry_path = tmp_path / "registry.json"
    impact_path = tmp_path / "impact.json"
    _write_json(
        raw_path,
        _raw(
            [
                _file("db/devices.db", 100, sqlite=True),
                _file("files/raw/source.log", 100),
            ]
        ),
    )
    _write_json(
        registry_path,
        _registry(
            [
                _store("site.devices", "sites/{site_id}/db/devices.db"),
                _store(
                    "site.raw",
                    "sites/{site_id}/files/raw/**",
                    data_type="ARTIFACT_OR_RAW_FILE",
                ),
            ]
        ),
    )
    _write_json(
        impact_path,
        _impact(raw_path, operational_before=100, artifact_before=100),
    )

    output = tmp_path / "output"
    finalize_site_storage_audit(
        raw_inventory_path=raw_path,
        registry_path=registry_path,
        optimization_impact_path=impact_path,
        output_dir=output,
        repo_root=repo,
        development_root=tmp_path,
    )

    footprint = json.loads(
        (output / "SITE_STORAGE_FOOTPRINT.json").read_text(encoding="utf-8")
    )
    assert footprint["optimization_impact"] == {
        "after_operational_bytes": 180,
        "after_site_bytes": 180,
        "before_bytes": 200,
        "duplicates_removed_bytes": 0,
        "history_moved_bytes": 20,
        "note": (
            "Exact isolated-copy measurements are overlaid on the immutable "
            "read-only site baseline; no production mutation is implied."
        ),
        "protected_bytes": 0,
        "status": "ISOLATED_REHEARSAL_MEASURED",
    }
    assert footprint["all_databases_storage"]["sections"]["Operational DBs"][
        "after_operational_bytes"
    ] == 80


def test_optimization_impact_rejects_digest_and_section_mismatches(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "owner.py").write_text("OWNER = True\n", encoding="utf-8")
    raw_path = tmp_path / "raw.json"
    registry_path = tmp_path / "registry.json"
    impact_path = tmp_path / "impact.json"
    _write_json(raw_path, _raw([_file("db/devices.db", 100, sqlite=True)]))
    _write_json(
        registry_path,
        _registry([_store("site.devices", "sites/{site_id}/db/devices.db")]),
    )
    impact = _impact(raw_path, operational_before=100, artifact_before=0)
    impact["source_inventory_sha256"] = "0" * 64
    _write_json(impact_path, impact)
    with pytest.raises(StorageAuditError, match="digest mismatch"):
        finalize_site_storage_audit(
            raw_inventory_path=raw_path,
            registry_path=registry_path,
            optimization_impact_path=impact_path,
            output_dir=tmp_path / "digest-output",
            repo_root=repo,
            development_root=tmp_path,
        )

    impact = _impact(raw_path, operational_before=100, artifact_before=0)
    sections = impact["sections"]
    sections["Operational DBs"]["before_bytes"] = 90
    sections["Artifacts/raw"]["before_bytes"] = 10
    _write_json(impact_path, impact)
    with pytest.raises(StorageAuditError, match="section Operational DBs"):
        finalize_site_storage_audit(
            raw_inventory_path=raw_path,
            registry_path=registry_path,
            optimization_impact_path=impact_path,
            output_dir=tmp_path / "section-output",
            repo_root=repo,
            development_root=tmp_path,
        )


def test_mixed_table_rebuildable_ratio_uses_table_rule(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "owner.py").write_text("OWNER = True\n", encoding="utf-8")
    raw_path = tmp_path / "raw.json"
    registry_path = tmp_path / "registry.json"
    raw = _raw([_file("db/mixed.db", 40, sqlite=True)])
    raw["sqlite_databases"][0]["tables"] = [_table("current"), _table("cache")]
    _write_json(raw_path, raw)
    store = _store("site.mixed", "sites/{site_id}/db/mixed.db")
    store["allowed_data_classes"] = ["OPERATIONAL_CURRENT", "CACHE_REBUILDABLE"]
    store["table_rules"] = [
        {
            "tables": ["current"],
            "data_class": "OPERATIONAL_CURRENT",
            "authority": "current authority",
            "producer": ["CurrentRepository"],
            "consumers": ["CurrentService"],
            "lifecycle_owner": "CurrentRepository",
            "rebuildable": False,
            "source_locations": ["owner.py"],
        },
        {
            "tables": ["cache"],
            "data_class": "CACHE_REBUILDABLE",
            "authority": "derived cache",
            "producer": ["CacheBuilder"],
            "consumers": ["CacheQuery"],
            "lifecycle_owner": "CacheBuilder",
            "rebuildable": True,
            "source_locations": ["owner.py"],
        },
    ]
    _write_json(registry_path, _registry([store]))

    output = tmp_path / "output"
    finalize_site_storage_audit(
        raw_inventory_path=raw_path,
        registry_path=registry_path,
        output_dir=output,
        repo_root=repo,
        development_root=tmp_path,
    )
    owner_map = json.loads(
        (output / "DATABASE_OWNER_MAP.json").read_text(encoding="utf-8")
    )
    assert owner_map["databases"][0]["lifecycle_profile"]["rebuildable_ratio"] == {
        "basis": (
            "explicit table lifecycle classification with rebuildable=true and "
            "a rebuildable data class"
        ),
        "logical_payload": 0.5,
        "rows": 0.5,
    }
