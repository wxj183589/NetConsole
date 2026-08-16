from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.maintenance.build_site_storage_optimization_impact import (
    StorageImpactError,
    build_site_storage_optimization_impact,
)
from scripts.maintenance.finalize_site_storage_audit import _STORAGE_REPORT_SECTIONS


def test_builds_reconciled_isolated_storage_overlay(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    output = tmp_path / "output" / "STORAGE_OPTIMIZATION_IMPACT.json"

    report = build_site_storage_optimization_impact(
        **inputs,
        output_path=output,
        development_root=tmp_path,
    )

    assert report["before_site_bytes"] == 310
    assert report["after_site_bytes"] == 131
    assert report["history_moved_bytes"] == 61
    assert report["duplicates_removed_bytes"] == 30
    assert report["protected_bytes"] == 10
    assert report["sections"]["Operational DBs"]["after_operational_bytes"] == 60
    assert report["sections"]["History DBs/shards"]["after_operational_bytes"] == 71
    assert json.loads(output.read_text(encoding="utf-8")) == report


def test_rejects_source_database_that_does_not_match_registered_baseline(
    tmp_path: Path,
) -> None:
    inputs = _inputs(tmp_path)
    Path(inputs["before_devices_path"]).write_bytes(b"x" * 101)

    with pytest.raises(StorageImpactError, match="site.devices.current"):
        build_site_storage_optimization_impact(
            **inputs,
            output_path=tmp_path / "impact.json",
            development_root=tmp_path,
        )


def test_refuses_to_overwrite_existing_impact(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    output = tmp_path / "impact.json"
    output.write_text("{}\n", encoding="utf-8")

    with pytest.raises(StorageImpactError, match="refusing to overwrite"):
        build_site_storage_optimization_impact(
            **inputs,
            output_path=output,
            development_root=tmp_path,
        )


def _inputs(tmp_path: Path) -> dict[str, Path]:
    before_devices = tmp_path / "before-devices.db"
    after_devices = tmp_path / "after-devices.db"
    before_tasks = tmp_path / "before-tasks.db"
    after_tasks = tmp_path / "after-tasks.db"
    before_devices.write_bytes(b"d" * 100)
    after_devices.write_bytes(b"d" * 20)
    before_tasks.write_bytes(b"t" * 200)
    after_tasks.write_bytes(b"t" * 40)
    history = tmp_path / "history"
    history.mkdir()
    (history / "catalog.db").write_bytes(b"c")
    (history / "devices-2026-07.db").write_bytes(b"h" * 60)

    sections = {
        name: {
            "before_bytes": 0,
            "protected_bytes": 0,
            "authority": [],
        }
        for name in _STORAGE_REPORT_SECTIONS
    }
    sections["Operational DBs"].update(
        {
            "before_bytes": 300,
            "authority": [
                {"store_id": "site.devices.current", "before_bytes": 100},
                {"store_id": "site.tasks.current", "before_bytes": 200},
            ],
        }
    )
    sections["History DBs/shards"]["before_bytes"] = 10
    sections["History DBs/shards"]["protected_bytes"] = 10
    baseline = tmp_path / "baseline.json"
    _write_json(
        baseline,
        {
            "measurement_scope": "entire recursive site plus data-root global inventory",
            "summary": {"site_total_bytes": 310},
            "all_databases_storage": {"sections": sections},
        },
    )
    site_inventory = tmp_path / "site-inventory.json"
    global_inventory = tmp_path / "global-inventory.json"
    _write_json(site_inventory, {"totals": {"bytes": 300}})
    _write_json(global_inventory, {"totals": {"bytes": 10}})
    task_report = tmp_path / "task-authority.json"
    _write_json(
        task_report,
        {
            "logical_result_bytes_removed": 30,
            "event_full_results_removed": 2,
        },
    )
    provenance = tmp_path / "provenance.json"
    _write_json(provenance, {"status": "PASS"})

    expected_digest = hashlib.sha256(
        json.dumps(
            {
                "global_inventory_sha256": _sha256(global_inventory),
                "site_inventory_sha256": _sha256(site_inventory),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
    ).hexdigest()
    assert len(expected_digest) == 64
    return {
        "baseline_footprint_path": baseline,
        "site_inventory_path": site_inventory,
        "global_inventory_path": global_inventory,
        "before_devices_path": before_devices,
        "after_devices_path": after_devices,
        "before_tasks_path": before_tasks,
        "after_tasks_path": after_tasks,
        "after_history_root": history,
        "task_authority_report_path": task_report,
        "provenance_report_path": provenance,
    }


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
