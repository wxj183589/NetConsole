"""Collect canonical Before/After consumer observations from isolated evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from scripts.maintenance.benchmark_database_functional_queries import REQUIRED_CASES
from scripts.maintenance.finalize_functional_compatibility import (
    MATRIX_DEFINITIONS,
    NO_REINFLATION_SCENARIOS,
)


DEFAULT_DEVELOPMENT_ROOT = Path("D:/study")
OUTPUT_NAMES = (
    "CONSUMER_OBSERVATIONS_BEFORE.json",
    "CONSUMER_OBSERVATIONS_AFTER.json",
)

# These are explicit authority edges, not filename inference.  The package
# registry supplies the producer/repository/lifecycle evidence for each store.
OBSERVATION_SPECS: dict[str, dict[str, tuple[str, ...]]] = {
    "Device Management": {
        "stores": ("site.devices.current",),
        "cases": ("current_device_query",),
    },
    "Interfaces": {
        "stores": ("site.devices.current",),
        "cases": ("current_device_query",),
    },
    "LLDP": {"stores": ("site.devices.current",), "cases": ("lldp_query",)},
    "Optical": {"stores": ("site.devices.current",), "cases": ("fit_ap_query",)},
    "FIT-AP": {"stores": ("site.devices.current",), "cases": ("fit_ap_query",)},
    "FIT-AP Radio": {"stores": ("site.devices.current",), "cases": ("fit_ap_query",)},
    "Trackside AP": {
        "stores": ("site.devices.current",),
        "cases": ("current_device_query",),
    },
    "AP Identity": {
        "stores": ("site.devices.current",),
        "cases": ("current_device_query",),
    },
    "Rail Base Data": {
        "stores": ("site.devices.current",),
        "cases": ("current_device_query",),
    },
    "History": {
        "stores": ("site.history.shard",),
        "cases": ("history_range_query", "cross_shard_history_query"),
    },
    "Task Center": {
        "stores": ("site.tasks.current",),
        "cases": ("task_center_list", "task_detail"),
    },
    "REST": {
        "stores": ("site.tasks.current",),
        "cases": ("task_center_list", "task_detail"),
    },
    "WebSocket": {"stores": ("site.tasks.current",), "cases": ("task_center_list",)},
    "Agent": {"stores": ("site.agents",), "cases": ("task_center_list",)},
    "Online MR": {
        "stores": ("site.online_mr.session_metadata", "site.online_mr.session_raw"),
        "cases": ("task_detail",),
    },
    "Ground": {
        "stores": ("site.ground.index", "site.ground.active_raw"),
        "cases": ("ground_history",),
    },
    "MR Collection": {
        "stores": ("site.online_mr.session_metadata",),
        "cases": ("task_center_list",),
    },
    "MR Raw Import": {
        "stores": ("site.mesh.raw", "site.online_mr.import_downloads"),
        "cases": (),
    },
    "MESH Analysis": {
        "stores": ("site.mesh.catalog", "site.mesh.aggregate", "site.mesh.raw"),
        "cases": ("mr_mesh_history",),
    },
    "RSSI / Link / Switch": {
        "stores": ("site.mesh.aggregate", "site.mesh.raw"),
        "cases": ("mr_mesh_history",),
    },
    "Ping": {"stores": ("site.ground.active_raw",), "cases": ("ground_history",)},
    "Syslog": {"stores": ("site.ground.active_raw",), "cases": ("ground_history",)},
    "Artifact": {"stores": ("site.artifacts.managed",), "cases": ()},
    "Import": {"stores": (), "cases": ()},
    "Export": {"stores": (), "cases": ()},
    "Site Package": {"stores": (), "cases": ()},
    "Restart Recovery": {
        "stores": ("site.history.catalog", "site.tasks.current"),
        "cases": (),
    },
    "Performance Regression": {"stores": (), "cases": tuple(REQUIRED_CASES)},
    "No-Reinflation": {"stores": (), "cases": ()},
}


class ConsumerObservationError(ValueError):
    """Raised when evidence cannot prove a canonical consumer result."""


def collect_functional_consumer_observations(
    *,
    site_package_report: Path,
    performance_report: Path,
    no_reinflation_report: Path,
    snapshot_root: Path,
    output_dir: Path,
    development_root: Path = DEFAULT_DEVELOPMENT_ROOT,
    snapshot_id: str = "ningbo-line-12-final-isolated",
) -> dict[str, Path]:
    development = development_root.resolve(strict=True)
    package_path = _input_file(site_package_report, development)
    performance_path = _input_file(performance_report, development)
    no_reinflation_path = _input_file(no_reinflation_report, development)
    snapshot = _input_directory(snapshot_root, development)
    output = _output_directory(output_dir, development)
    package = _load(package_path)
    performance = _load(performance_path)
    no_reinflation = _load(no_reinflation_path)
    _validate_package(package)
    performance_cases = _validate_performance(performance)
    reinflation_cases = _validate_no_reinflation(no_reinflation)
    source_site, imported_site = _package_sites(package, development)
    source_stores = _stores(package, "source")
    imported_stores = _stores(package, "imported")
    if set(source_stores) != set(imported_stores):
        raise ConsumerObservationError("Site Package source/imported store IDs differ")
    store_values: dict[str, str] = {}
    store_paths: dict[str, tuple[list[str], list[str]]] = {}
    for store_id in sorted(source_stores):
        left = source_stores[store_id]
        right = imported_stores[store_id]
        policy_class = str(left.get("policy_class") or "").upper()
        if policy_class == "EXCLUDED":
            if right.get("files"):
                raise ConsumerObservationError(
                    f"excluded Site Package store was imported: {store_id}"
                )
            # Excluded runtime markers (for example the History append lock)
            # intentionally have no imported authority. Compare their policy,
            # not a source-only file digest.
            store_values[store_id] = "EXCLUDED:" + str(
                left.get("site_package_policy") or ""
            )
            store_paths[store_id] = (
                _store_paths(source_site, left, package_path),
                _store_paths(imported_site, right, package_path),
            )
            continue
        left_digest = str(left.get("semantic_digest") or "")
        right_digest = str(right.get("semantic_digest") or "")
        if not left_digest or left_digest != right_digest:
            raise ConsumerObservationError(
                f"Site Package semantic parity failed: {store_id}"
            )
        store_values[store_id] = left_digest
        store_paths[store_id] = (
            _store_paths(source_site, left, package_path),
            _store_paths(imported_site, right, package_path),
        )

    package_projection = _package_projection(package)
    reinflation_projection = {
        key: {
            "status": str(value.get("status") or ""),
            "authority": str(value.get("authority") or value.get("owner") or ""),
        }
        for key, value in reinflation_cases.items()
    }
    report_paths = [str(package_path), str(performance_path), str(no_reinflation_path)]
    before = _build_manifest(
        side="before",
        snapshot=snapshot,
        snapshot_id=snapshot_id,
        package=package,
        performance_cases=performance_cases,
        store_values=store_values,
        store_paths=store_paths,
        report_paths=report_paths,
        package_projection=package_projection,
        reinflation_projection=reinflation_projection,
        source_side=0,
    )
    after = _build_manifest(
        side="after",
        snapshot=snapshot,
        snapshot_id=snapshot_id,
        package=package,
        performance_cases=performance_cases,
        store_values=store_values,
        store_paths=store_paths,
        report_paths=report_paths,
        package_projection=package_projection,
        reinflation_projection=reinflation_projection,
        source_side=1,
    )
    paths = {
        OUTPUT_NAMES[0]: output / OUTPUT_NAMES[0],
        OUTPUT_NAMES[1]: output / OUTPUT_NAMES[1],
    }
    _atomic_json(paths[OUTPUT_NAMES[0]], before)
    _atomic_json(paths[OUTPUT_NAMES[1]], after)
    return paths


def _build_manifest(
    *,
    side: str,
    snapshot: Path,
    snapshot_id: str,
    package: Mapping[str, Any],
    performance_cases: Mapping[str, Mapping[str, Any]],
    store_values: Mapping[str, str],
    store_paths: Mapping[str, tuple[list[str], list[str]]],
    report_paths: Sequence[str],
    package_projection: Mapping[str, Any],
    reinflation_projection: Mapping[str, Any],
    source_side: int,
) -> dict[str, Any]:
    observations: dict[str, Any] = {}
    for name, _core_ids, test_ids in MATRIX_DEFINITIONS:
        spec = OBSERVATION_SPECS.get(name)
        if spec is None:
            raise ConsumerObservationError(f"consumer spec is missing: {name}")
        payload: dict[str, Any] = {
            "consumer": name,
            "stores": {key: store_values[key] for key in spec["stores"]},
            "performance": {
                key: performance_cases[key]["before"]["result_sha256"]
                for key in spec["cases"]
            },
        }
        if (
            name == "Import"
            or name == "Export"
            or name == "Site Package"
            or name == "Restart Recovery"
        ):
            payload["package"] = dict(package_projection)
        if name == "No-Reinflation":
            payload["no_reinflation"] = dict(reinflation_projection)
        if name == "Performance Regression":
            payload["performance"] = {
                key: performance_cases[key]["before"]["result_sha256"]
                for key in REQUIRED_CASES
            }
        canonical = _sha256_json(payload)
        paths: list[str] = []
        for store_id in spec["stores"]:
            paths.extend(store_paths[store_id][source_side])
        paths.extend(report_paths)
        paths = sorted(dict.fromkeys(paths))
        authority = _authority_for(name, spec["stores"], package)
        observations[name] = {
            "status": "PASS",
            "query": f"canonical isolated {name} evidence ({side})",
            "query_digest": canonical,
            "source_paths": paths,
            "producer": authority["producer"],
            "repository": authority["repository"],
            "consumer": name,
            "lifecycle_owner": authority["lifecycle_owner"],
            "authority_evidence": {
                "status": "PASS",
                "authority": authority["authority"],
                "test_ids": list(test_ids)
                or ["scripts/maintenance/validate_integrated_site_package.py"],
            },
        }
    return {
        "schema_version": 1,
        "snapshot_binding": {
            "site_id": "ningbo-line-12",
            "snapshot_id": snapshot_id,
            "root": str(snapshot),
            "isolated_copy": True,
        },
        "observations": observations,
    }


def _authority_for(
    name: str, store_ids: Sequence[str], package: Mapping[str, Any]
) -> dict[str, str]:
    stores = _stores(package, "source")
    selected = [stores[key] for key in store_ids if key in stores]
    owners = sorted(
        {
            str(item.get("owner") or "")
            for item in selected
            if str(item.get("owner") or "")
        }
    )
    locations = sorted(
        {
            location
            for item in selected
            for location in item.get("source_locations", [])
            if str(location).strip()
        }
    )
    authority = sorted(
        {
            str(item.get("authority") or "")
            for item in selected
            if str(item.get("authority") or "")
        }
    )
    return {
        "producer": "; ".join(locations) or "validated package authority producer",
        "repository": "; ".join(locations) or "validated package authority repository",
        "lifecycle_owner": "; ".join(owners) or "validated package lifecycle owner",
        "authority": "; ".join(authority) or f"validated {name} canonical evidence",
    }


def _package_projection(package: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": package.get("status"),
        "parity": package.get("parity"),
        "staging_cleanup": package.get("staging_cleanup"),
        "source_hashes": package.get("source_hashes"),
    }


def _validate_package(package: Mapping[str, Any]) -> None:
    if (
        package.get("format") != "netconsole-integrated-site-package-validation-v1"
        or package.get("status") != "PASS"
    ):
        raise ConsumerObservationError("integrated Site Package report is not PASS")


def _validate_performance(report: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    if (
        report.get("format") != "netconsole-database-performance-comparison-v1"
        or report.get("status") != "PASS"
    ):
        raise ConsumerObservationError("database performance report is not PASS")
    cases = {
        str(item.get("id")): item
        for item in report.get("cases", [])
        if isinstance(item, Mapping)
    }
    if set(cases) != set(REQUIRED_CASES):
        raise ConsumerObservationError("database performance cases are incomplete")
    for key, item in cases.items():
        if item.get("status") != "PASS" or item.get("before", {}).get(
            "result_sha256"
        ) != item.get("after", {}).get("result_sha256"):
            raise ConsumerObservationError(
                f"database performance semantic parity failed: {key}"
            )
    return cases


def _validate_no_reinflation(report: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    if report.get("status") != "PASS":
        raise ConsumerObservationError("No-Reinflation report is not PASS")
    cases = {
        str(item.get("scenario_id")): item
        for item in report.get("scenarios", [])
        if isinstance(item, Mapping)
    }
    if set(cases) != set(NO_REINFLATION_SCENARIOS) or any(
        item.get("status") != "PASS" for item in cases.values()
    ):
        raise ConsumerObservationError("No-Reinflation scenarios are incomplete")
    return cases


def _stores(package: Mapping[str, Any], side: str) -> dict[str, Mapping[str, Any]]:
    value = package.get(side, {}).get("registered_storage", {}).get("stores", {})
    if not isinstance(value, Mapping):
        raise ConsumerObservationError(f"{side} registered storage stores are missing")
    stores = {
        str(key): item for key, item in value.items() if isinstance(item, Mapping)
    }
    side_data = package.get(side, {})
    site_name = str(package.get("scope", {}).get("physical_directory") or "")
    data_root = Path(str(side_data.get("data_root") or ""))
    site_root = data_root / "sites" / site_name

    def add_profile_store(
        store_id: str,
        relative: str,
        profile: Mapping[str, Any],
        *,
        owner: str,
        authority: str,
        data_type: str,
    ) -> None:
        if store_id in stores or not profile:
            return
        semantic_profile = {
            key: profile.get(key)
            for key in ("quick_check", "schema_digest", "table_counts")
            if key in profile
        }
        stores[store_id] = {
            "policy_class": "REQUIRED",
            "owner": owner,
            "authority": authority,
            "data_type": data_type,
            "files": {relative: {"kind": "sqlite"}},
            "semantic_digest": _sha256_json(semantic_profile),
            "source_locations": [],
        }

    add_profile_store(
        "site.devices.current",
        "db/devices.db",
        side_data.get("devices", {}),
        owner="DeviceRepository",
        authority="current devices.db operational authority",
        data_type="OPERATIONAL_CURRENT",
    )
    task_profile = side_data.get("tasks", {}).get("profile", {})
    add_profile_store(
        "site.tasks.current",
        "db/tasks.db",
        task_profile,
        owner="TaskRepository",
        authority="current tasks.db operational and recovery authority",
        data_type="OPERATIONAL_CURRENT",
    )

    history = side_data.get("history", {})
    history_files = history.get("files", {})
    if isinstance(history_files, Mapping):
        catalog = history_files.get("catalog.db")
        if isinstance(catalog, Mapping) and "site.history.catalog" not in stores:
            stores["site.history.catalog"] = {
                "policy_class": "REQUIRED",
                "owner": "HistoryStore",
                "authority": "published history catalog authority",
                "data_type": "HISTORICAL_RAW_FACT",
                "files": {"db/history/catalog.db": {"kind": "sqlite"}},
                "semantic_digest": _sha256_json(
                    {
                        key: catalog.get(key)
                        for key in ("quick_check", "table_counts", "event_identity_digest")
                    }
                ),
                "source_locations": [],
            }
        shard_files = {
            str(relative): profile
            for relative, profile in history_files.items()
            if str(relative).startswith("devices-") and isinstance(profile, Mapping)
        }
        if shard_files and "site.history.shard" not in stores:
            stores["site.history.shard"] = {
                "policy_class": "REQUIRED",
                "owner": "HistoryStore",
                "authority": "immutable verified history shard authority",
                "data_type": "HISTORICAL_RAW_FACT",
                "files": {
                    f"db/history/{relative}": {"kind": "sqlite"}
                    for relative in sorted(shard_files)
                },
                "semantic_digest": _sha256_json(
                    {
                        relative: {
                            key: profile.get(key)
                            for key in (
                                "quick_check",
                                "table_counts",
                                "event_identity_digest",
                                "kinds",
                            )
                        }
                        for relative, profile in sorted(shard_files.items())
                    }
                ),
                "source_locations": [],
            }

    if "site.artifacts.managed" not in stores:
        artifact_root = site_root / "files" / "web_artifacts"
        artifact_files = (
            sorted(path for path in artifact_root.rglob("*") if path.is_file())
            if artifact_root.is_dir()
            else []
        )
        if artifact_files:
            manifest = []
            relative_files: dict[str, Mapping[str, Any]] = {}
            for path in artifact_files:
                relative = path.relative_to(site_root).as_posix()
                digest = _sha256_file(path)
                manifest.append({"path": relative, "bytes": path.stat().st_size, "sha256": digest})
                relative_files[relative] = {"kind": "file", "bytes": path.stat().st_size, "sha256": digest}
            stores["site.artifacts.managed"] = {
                "policy_class": "REQUIRED",
                "owner": "ArtifactStore",
                "authority": "managed artifact content authority",
                "data_type": "ARTIFACT_OR_RAW_FILE",
                "files": relative_files,
                "semantic_digest": _sha256_json(manifest),
                "source_locations": [],
            }
    return stores


def _package_sites(package: Mapping[str, Any], development: Path) -> tuple[Path, Path]:
    site_name = str(package.get("scope", {}).get("physical_directory") or "")
    source_root = _input_directory(
        Path(str(package.get("source", {}).get("data_root") or "")), development
    )
    imported_root = _input_directory(
        Path(str(package.get("imported", {}).get("data_root") or "")), development
    )
    if not site_name or Path(site_name).name != site_name:
        raise ConsumerObservationError("Site Package physical directory is invalid")
    return _input_directory(
        source_root / "sites" / site_name, development
    ), _input_directory(imported_root / "sites" / site_name, development)


def _store_paths(
    site_root: Path, store: Mapping[str, Any], fallback: Path
) -> list[str]:
    files = store.get("files", {})
    paths: list[str] = []
    if isinstance(files, Mapping):
        for relative in files:
            candidate = (site_root / str(relative).replace("\\", "/")).resolve(
                strict=True
            )
            if not candidate.is_relative_to(site_root):
                raise ConsumerObservationError(
                    f"registered storage path escapes site root: {relative}"
                )
            paths.append(str(candidate))
    return paths or [str(fallback)]


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ConsumerObservationError(f"JSON evidence must be an object: {path}")
    return value


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _input_file(path: Path, development: Path) -> Path:
    candidate = path.resolve(strict=True)
    if not candidate.is_relative_to(development) or not candidate.is_file():
        raise ConsumerObservationError(
            f"input file must remain below D:/study: {candidate}"
        )
    return candidate


def _input_directory(path: Path, development: Path) -> Path:
    candidate = path.resolve(strict=True)
    if not candidate.is_relative_to(development) or not candidate.is_dir():
        raise ConsumerObservationError(
            f"input directory must remain below D:/study: {candidate}"
        )
    return candidate


def _output_directory(path: Path, development: Path) -> Path:
    candidate = path.resolve()
    if candidate == development or not candidate.is_relative_to(development):
        raise ConsumerObservationError("output must remain below D:/study")
    candidate.mkdir(parents=True, exist_ok=True)
    return candidate


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(
                (
                    json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
                    + "\n"
                ).encode("utf-8")
            )
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
        temporary.unlink()
    finally:
        temporary.unlink(missing_ok=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-package-report", type=Path, required=True)
    parser.add_argument("--performance-report", type=Path, required=True)
    parser.add_argument("--no-reinflation-report", type=Path, required=True)
    parser.add_argument("--snapshot-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--development-root", type=Path, default=DEFAULT_DEVELOPMENT_ROOT
    )
    parser.add_argument("--snapshot-id", default="ningbo-line-12-final-isolated")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    outputs = collect_functional_consumer_observations(
        site_package_report=args.site_package_report,
        performance_report=args.performance_report,
        no_reinflation_report=args.no_reinflation_report,
        snapshot_root=args.snapshot_root,
        output_dir=args.output_dir,
        development_root=args.development_root,
        snapshot_id=args.snapshot_id,
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "outputs": {key: str(value) for key, value in outputs.items()},
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
