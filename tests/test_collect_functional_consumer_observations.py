from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.maintenance.benchmark_database_functional_queries import REQUIRED_CASES
from scripts.maintenance.collect_functional_consumer_observations import (
    OBSERVATION_SPECS,
    ConsumerObservationError,
    collect_functional_consumer_observations,
)
from scripts.maintenance.finalize_functional_compatibility import (
    MATRIX_DEFINITIONS,
    NO_REINFLATION_SCENARIOS,
)


def _write(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _fixture(tmp_path: Path) -> dict[str, Path]:
    site_name = "宁波地铁12号线"
    source_root = tmp_path / "source-data-root"
    imported_root = tmp_path / "imported-data-root"
    (source_root / "sites" / site_name).mkdir(parents=True)
    (imported_root / "sites" / site_name).mkdir(parents=True)
    snapshot = tmp_path / "isolated-snapshot"
    snapshot.mkdir()
    store_ids = sorted(
        {store_id for spec in OBSERVATION_SPECS.values() for store_id in spec["stores"]}
    )

    def stores() -> dict[str, object]:
        return {
            store_id: {
                "semantic_digest": hashlib.sha256(store_id.encode()).hexdigest(),
                "files": {},
                "owner": f"{store_id} owner",
                "authority": f"{store_id} authority",
                "source_locations": ["src/netconsole/repositories/example.py"],
            }
            for store_id in store_ids
        }

    package = _write(
        tmp_path / "SITE_PACKAGE.json",
        {
            "format": "netconsole-integrated-site-package-validation-v1",
            "status": "PASS",
            "scope": {"physical_directory": site_name},
            "source": {
                "data_root": str(source_root),
                "registered_storage": {"stores": stores()},
            },
            "imported": {
                "data_root": str(imported_root),
                "registered_storage": {"stores": stores()},
            },
            "parity": {"operational": {"devices": True}},
            "staging_cleanup": {"export_success": True, "import_success": True},
            "source_hashes": {"before": {"devices": "a"}, "after": {"devices": "a"}},
        },
    )
    performance = _write(
        tmp_path / "DATABASE_PERFORMANCE.json",
        {
            "format": "netconsole-database-performance-comparison-v1",
            "status": "PASS",
            "cases": [
                {
                    "id": case_id,
                    "status": "PASS",
                    "before": {
                        "result_sha256": hashlib.sha256(case_id.encode()).hexdigest()
                    },
                    "after": {
                        "result_sha256": hashlib.sha256(case_id.encode()).hexdigest()
                    },
                }
                for case_id in REQUIRED_CASES
            ],
        },
    )
    no_reinflation = _write(
        tmp_path / "STORAGE_NO_REINFLATION.json",
        {
            "status": "PASS",
            "scenarios": [
                {"scenario_id": scenario, "status": "PASS", "authority": scenario}
                for scenario in sorted(NO_REINFLATION_SCENARIOS)
            ],
        },
    )
    return {
        "site_package_report": package,
        "performance_report": performance,
        "no_reinflation_report": no_reinflation,
        "snapshot_root": snapshot,
        "output_dir": tmp_path / "output",
        "development_root": tmp_path,
    }


def test_consumer_specs_cover_final_matrix() -> None:
    assert set(OBSERVATION_SPECS) == {
        name for name, _core_ids, _test_ids in MATRIX_DEFINITIONS
    }


def test_collector_emits_equal_canonical_before_after_digests(tmp_path: Path) -> None:
    outputs = collect_functional_consumer_observations(**_fixture(tmp_path))

    before = json.loads(
        outputs["CONSUMER_OBSERVATIONS_BEFORE.json"].read_text(encoding="utf-8")
    )
    after = json.loads(
        outputs["CONSUMER_OBSERVATIONS_AFTER.json"].read_text(encoding="utf-8")
    )
    assert set(before["observations"]) == set(OBSERVATION_SPECS)
    assert {
        name: item["query_digest"] for name, item in before["observations"].items()
    } == {name: item["query_digest"] for name, item in after["observations"].items()}
    assert all(item["source_paths"] for item in before["observations"].values())


def test_collector_rejects_site_package_semantic_drift(tmp_path: Path) -> None:
    arguments = _fixture(tmp_path)
    package_path = arguments["site_package_report"]
    package = json.loads(package_path.read_text(encoding="utf-8"))
    package["imported"]["registered_storage"]["stores"]["site.devices.current"][
        "semantic_digest"
    ] = "0" * 64
    _write(package_path, package)

    with pytest.raises(ConsumerObservationError, match="semantic parity failed"):
        collect_functional_consumer_observations(**arguments)
