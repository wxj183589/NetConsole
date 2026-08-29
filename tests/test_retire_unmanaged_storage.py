from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.maintenance.retire_unmanaged_storage import (
    StorageRetirementError,
    apply_retirement_plan,
    build_retirement_plan,
    write_retirement_plan,
)


def _spec(path: Path, *, classification: str = "UNMANAGED_EXTERNAL") -> Path:
    registry = path.parent / "storage-registry.yaml"
    authority = path.parent / "devices.db"
    rollback_owner = path.parent / "rollback-owner.json"
    registry.write_text("registry\n", encoding="utf-8")
    authority.write_text("authority\n", encoding="utf-8")
    rollback_owner.write_text('{"operation_id":"op-1"}\n', encoding="utf-8")
    value = {
        "protection": {
            "storage_registry": {"path": str(registry)},
            "active_authority_manifest": {
                "scope": "test",
                "files": [{"role": "devices.db", "path": str(authority)}],
            },
            "current_rollback_owner": {
                "operation_id": "op-1",
                "database": "devices.db",
                "status": "VERIFIED",
                "retire_state": "PROTECT",
                "owner_path": str(rollback_owner),
            },
        },
        "candidates": [
            {
                "path": path.name,
                "classification": classification,
                "reason": "test evidence",
                "code_writer": "none proven",
                "code_reader": "none proven",
                "active_references": [],
            }
        ]
    }
    output = path.parent / "spec.json"
    output.write_text(json.dumps(value), encoding="utf-8")
    return output


def test_retirement_plan_apply_verifies_hash_and_manifest(tmp_path: Path) -> None:
    root = tmp_path / "NetConsoleData"
    root.mkdir()
    (root / "runtime_mode.json").write_text('{"mode":"production"}\n', encoding="utf-8")
    spec = _spec(root / "runtime_mode.json")
    destination = tmp_path / "NetConsoleData-retired-20260829-010203"
    plan = build_retirement_plan(root, spec, destination, generated_at="2026-08-29T01:02:03Z")
    plan_path = write_retirement_plan(plan, tmp_path / "plan.json")

    result = apply_retirement_plan(
        plan_path,
        expected_plan_digest=plan["plan_digest"],
        retired_at="2026-08-29T01:03:00Z",
    )

    assert result["hash_verify"] == "PASS"
    assert not (root / "runtime_mode.json").exists()
    manifest = json.loads(
        (destination / "retirement-manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["files"][0]["original_path"].endswith("runtime_mode.json")
    assert (destination / "runtime_mode.json").read_text(encoding="utf-8") == (
        '{"mode":"production"}\n'
    )


def test_retirement_rejects_path_traversal_and_unknown(tmp_path: Path) -> None:
    root = tmp_path / "NetConsoleData"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("protected", encoding="utf-8")
    for relative in ("../outside.txt", "runtime/../outside.txt"):
        spec = root / "spec.json"
        spec.write_text(
            json.dumps(
                {
                    "candidates": [
                        {
                            "path": relative,
                            "classification": "UNMANAGED_EXTERNAL",
                            "reason": "bad",
                            "active_references": [],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(StorageRetirementError):
            build_retirement_plan(
                root,
                spec,
                tmp_path / "NetConsoleData-retired-20260829-010203",
            )
    spec = _spec(root / "missing.txt", classification="UNKNOWN")
    with pytest.raises(StorageRetirementError):
        build_retirement_plan(
            root,
            spec,
            tmp_path / "NetConsoleData-retired-20260829-010204",
        )


def test_retirement_rejects_active_reference(tmp_path: Path) -> None:
    root = tmp_path / "NetConsoleData"
    root.mkdir()
    target = root / "input.zip"
    target.write_bytes(b"input")
    spec = root / "spec.json"
    spec.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "path": "input.zip",
                        "classification": "LEGACY_MANAGED",
                        "reason": "legacy",
                        "active_references": ["import-1"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(StorageRetirementError):
        build_retirement_plan(
            root,
            spec,
            tmp_path / "NetConsoleData-retired-20260829-010205",
        )
