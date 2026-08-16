from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from scripts.architecture.checks import (
    SQL_CLASSIFICATIONS,
    STATUS_TOKEN_NAME,
    _css_declarations,
    _load_theme_literal_allowlist,
    _load_sql_inventory,
    dynamic_chart_stability_findings,
    orphan_module_findings,
    storage_registry_findings,
    typescript_records,
)
from scripts.architecture.cli import CHECKS
from scripts.architecture.guard_core import (
    ROOT,
    Finding,
    apply_exceptions,
    load_exceptions,
)


def test_all_architecture_checks_have_no_unwaived_findings() -> None:
    exceptions = load_exceptions()
    active = {
        name: unwaived
        for name, check in CHECKS.items()
        if (unwaived := apply_exceptions(check(), exceptions)[0])
    }
    assert active == {}


def test_storage_registry_guard_rejects_a_new_unregistered_sqlite(tmp_path: Path) -> None:
    rogue = tmp_path / "rogue_owner.py"
    rogue.write_text(
        "import sqlite3\n\n"
        "def create():\n"
        "    return sqlite3.connect('rogue.db')\n",
        encoding="utf-8",
    )

    findings = storage_registry_findings(source_roots=[tmp_path])

    assert any(item.rule_id == "UNREGISTERED_STORAGE" for item in findings)
    assert any("rogue.db" in item.message for item in findings)


def test_storage_registry_guard_requires_exact_direct_sql_source_registration(
    tmp_path: Path,
) -> None:
    inventory = tmp_path / "direct_sql.json"
    inventory.write_text(
        json.dumps(
            [
                {
                    "path": "src/netconsole/repositories/unregistered_store.py",
                    "classification": "REPOSITORY_REQUIRED",
                    "owner": "job-center",
                    "reason": "same code owner is not an exact store binding",
                }
            ]
        ),
        encoding="utf-8",
    )

    findings = storage_registry_findings(
        source_roots=[tmp_path / "absent"], direct_sql_path=inventory
    )

    assert any(
        item.rule_id == "UNREGISTERED_STORAGE"
        and item.path == "src/netconsole/repositories/unregistered_store.py"
        and "exact storage registry declaration" in item.message
        for item in findings
    )


def test_storage_registry_closes_observed_legacy_paths_without_guessing_owners() -> None:
    registry = json.loads((ROOT / "config" / "storage_registry.yaml").read_text(encoding="utf-8"))
    stores = {str(item["id"]): item for item in registry["stores"]}
    expected_owned = {
        "site.legacy.snmp": "sites/{site_id}/db/snmp.db",
        "site.legacy.config_raw": "sites/{site_id}/raw/config/**",
        "site.legacy.device_downloads": "sites/{site_id}/downloads/files/**",
    }
    expected_unknown = {
        "site.legacy.snmp_sidecars": "sites/{site_id}/db/snmp.db-*",
        "unknown.fit_ap_association_backups": (
            "sites/{site_id}/files/backups/fit-ap-association-*/**"
        ),
        "unknown.ground_unattended_backups": (
            "sites/{site_id}/files/backups/ground_unattended/**"
        ),
    }

    for store_id, relative_path in expected_owned.items():
        store = stores[store_id]
        assert store["relative_path"] == relative_path
        assert store["data_type"] != "UNKNOWN"
        assert store["authority"] != "UNKNOWN_PROTECT"
        assert store["retention_owner"] != "UNKNOWN_PROTECT"
        assert store["producer"] != ["NO_ACTIVE_PRODUCER_PROVEN"]

    for store_id, relative_path in expected_unknown.items():
        store = stores[store_id]
        assert store["relative_path"] == relative_path
        assert store["data_type"] == "UNKNOWN"
        assert store["authority"] == "UNKNOWN_PROTECT"
        assert store["retention_owner"] == "UNKNOWN_PROTECT"
        assert store["rebuildable"] is False
        assert store["allowed_data_classes"] == ["UNKNOWN"]
        assert isinstance(store["active_producer"], bool)

    assert all(
        isinstance(store.get("active_producer"), bool)
        for store in stores.values()
        if store["data_type"] == "UNKNOWN"
    )


def test_storage_registry_uses_exclusive_upgrade_lifecycle_classes() -> None:
    registry = json.loads((ROOT / "config" / "storage_registry.yaml").read_text(encoding="utf-8"))
    stores = {str(item["id"]): item for item in registry["stores"]}

    assert stores["site.backups.database_upgrade"]["relative_path"] == (
        "backups/database_upgrade/{scope_type}/{scope_id}/{database_kind}/{backup_id}/**"
    )
    invalid_legacy = stores["site.backups.database_upgrade_invalid_legacy"]
    assert invalid_legacy["relative_path"] == (
        "backups/database_upgrade/_invalid/{archive_id}/**"
    )
    assert invalid_legacy["data_type"] == "UNKNOWN"
    assert invalid_legacy["authority"] == "UNKNOWN_PROTECT"
    assert invalid_legacy["rebuildable"] is False
    assert stores["site.backups.database_migration"]["allowed_data_classes"] == [
        "BACKUP_ROLLBACK"
    ]
    assert stores["site.online_mr.session_parsed_candidate"][
        "allowed_data_classes"
    ] == ["STAGING_TEMPORARY"]
    assert stores["site.online_mr.session_parsed_rollback"][
        "allowed_data_classes"
    ] == ["BACKUP_ROLLBACK"]


def test_storage_registry_covers_global_persistent_lifecycle_roots() -> None:
    registry = json.loads(
        (ROOT / "config" / "storage_registry.yaml").read_text(encoding="utf-8")
    )
    stores = {str(item["id"]): item for item in registry["stores"]}
    expected = {
        "global.migrations.conflicts": "BACKUP_ROLLBACK",
        "global.migrations.source_archives": "BACKUP_ROLLBACK",
        "global.migrations.unclassified": "UNKNOWN",
        "global.legacy.mib_archive": "ARTIFACT_OR_RAW_FILE",
        "global.runtime.logs": "HISTORICAL_RAW_FACT",
        "global.runtime.background_jobs": "OPERATIONAL_CURRENT",
        "global.runtime.export_jobs": "OPERATIONAL_CURRENT",
        "global.runtime.base_data_import_previews": "STAGING_TEMPORARY",
        "global.runtime.database_upgrade": "OPERATIONAL_CURRENT",
        "global.runtime.electron_user_data": "OPERATIONAL_CURRENT",
        "global.legacy_agent.data": "ARTIFACT_OR_RAW_FILE",
        "global.data_root.staging": "STAGING_TEMPORARY",
    }

    for store_id, data_type in expected.items():
        store = stores[store_id]
        assert store["data_type"] == data_type
        assert store["producer"]
        assert store["consumers"]
        assert store["retention_owner"]


def test_storage_registry_classifies_legacy_online_mr_live_tables() -> None:
    registry = json.loads((ROOT / "config" / "storage_registry.yaml").read_text(encoding="utf-8"))
    stores = {str(item["id"]): item for item in registry["stores"]}
    rules = stores["site.online_mr.session_parsed"]["table_rules"]
    table_classes = {
        str(table): str(rule["data_class"])
        for rule in rules
        for table in rule["tables"]
    }

    assert {
        table_classes[table]
        for table in (
            "collector_logs",
            "live_samples",
            "live_mesh_links",
            "live_channel_busy",
            "live_interface_rates",
            "live_radio_statistics_raw_index",
            "live_terminal_events",
            "live_events",
            "ping_samples",
        )
    } == {"HISTORICAL_RAW_FACT"}
    assert table_classes["ping_summary"] == "HISTORICAL_TREND"
    assert table_classes["live_switch_history_latest"] == "OPERATIONAL_CURRENT"

    legacy_mesh = stores["site.mesh.legacy_analysis"]
    assert legacy_mesh["relative_path"] == (
        "sites/{site_id}/analysis/mesh/{analysis_id}/analysis.sqlite"
    )
    assert legacy_mesh["data_type"] == "UNKNOWN"
    assert legacy_mesh["authority"] == "UNKNOWN_PROTECT"
    assert legacy_mesh["retention_owner"] == "UNKNOWN_PROTECT"
    assert legacy_mesh["active_producer"] is True
    assert legacy_mesh["source_locations"] == [
        "src/netconsole/services/mesh_log_analysis_service.py"
    ]

    ground_rules = stores["site.ground.index"]["table_rules"]
    ground_unknown = next(
        rule
        for rule in ground_rules
        if "ground_unattended_ping_loss_intervals" in rule["tables"]
    )
    assert ground_unknown["data_class"] == "UNKNOWN"
    assert ground_unknown["authority"] == "UNKNOWN_PROTECT"

    device_rule_tables = {
        str(table)
        for rule in stores["site.devices.current"]["table_rules"]
        for table in rule["tables"]
    }
    assert not {
        "wifi_floor_plans",
        "wifi_observations",
        "wifi_survey_points",
        "wifi_survey_sessions",
    } & device_rule_tables


def test_typescript_guard_uses_compiler_ast() -> None:
    records, failure = typescript_records()
    assert failure is None
    assert records
    assert any(item["path"].endswith(".vue") for item in records)


def test_dynamic_chart_guard_covers_shared_timeline_components() -> None:
    assert dynamic_chart_stability_findings() == []


def test_css_guard_parses_minified_and_nested_declarations() -> None:
    declarations = _css_declarations(
        "@media(max-width:900px){.app-sidebar{background:#081426}}"
        ".page{--el-color-primary:#00f;color:var(--nc-text-primary)}"
    )
    assert {(item.selector, item.property, item.value) for item in declarations} == {
        (".app-sidebar", "background", "#081426"),
        (".page", "--el-color-primary", "#00f"),
        (".page", "color", "var(--nc-text-primary)"),
    }


def test_status_token_name_does_not_treat_plain_text_tokens_as_status_colors() -> None:
    assert STATUS_TOKEN_NAME.search("--nc-primary")
    assert STATUS_TOKEN_NAME.search("--nc-status-success-bg")
    assert STATUS_TOKEN_NAME.search("--el-color-danger-light-7")
    assert not STATUS_TOKEN_NAME.search("--nc-text-primary")
    assert not STATUS_TOKEN_NAME.search("--nc-text-secondary")


def test_theme_literal_allowlist_is_exact_and_currently_empty() -> None:
    assert _load_theme_literal_allowlist() == {}


def test_theme_literal_allowlist_rejects_directory_wildcards(tmp_path: Path) -> None:
    path = tmp_path / "theme_color_literals.yaml"
    path.write_text(
        json.dumps(
            [
                {
                    "path": "apps/desktop_renderer/src/**",
                    "selector": ".example",
                    "property": "background",
                    "value": "#ffffff",
                    "category": "BRAND",
                    "owner": "architecture",
                    "reason": "验证目录通配符失败关闭。",
                    "test": "tests/architecture/test_architecture_guards.py",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="exact Web source file"):
        _load_theme_literal_allowlist(path)


def test_direct_sql_inventory_uses_all_non_debt_classifications() -> None:
    inventory = _load_sql_inventory()
    assert "VIOLATION" in SQL_CLASSIFICATIONS
    assert {item["classification"] for item in inventory.values()} == SQL_CLASSIFICATIONS - {"VIOLATION"}


def test_orphan_guard_excludes_registered_transport_and_contract_modules() -> None:
    findings = orphan_module_findings()
    assert all("/backend/api/" not in item.path for item in findings)
    assert all("/handlers/" not in item.path for item in findings)
    assert all("/models/" not in item.path for item in findings)


def test_exception_schema_fails_closed_on_missing_fields(tmp_path: Path) -> None:
    path = tmp_path / "exceptions.yaml"
    path.write_text(json.dumps([{"rule_id": "DEMO"}]), encoding="utf-8")
    with pytest.raises(ValueError, match="exactly"):
        load_exceptions(path)


def test_exception_schema_rejects_expired_and_wildcard_entries(
    tmp_path: Path,
) -> None:
    base = {
        "rule_id": "DEMO",
        "path": "src/netconsole/demo.py",
        "reason": "验证失败关闭。",
        "owner": "architecture",
        "created_at": "2026-01-01",
        "expires_at": "2026-01-02",
        "test": "tests/architecture/test_architecture_guards.py",
    }
    path = tmp_path / "exceptions.yaml"
    path.write_text(json.dumps([base], ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="expired"):
        load_exceptions(path, today=date(2026, 1, 3))

    base["expires_at"] = "2026-02-01"
    base["path"] = "src/netconsole/services/**"
    path.write_text(json.dumps([base], ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="exact"):
        load_exceptions(path, today=date(2026, 1, 3))


def test_exception_matching_is_exact_by_rule_and_path() -> None:
    exception = load_exceptions()[0]
    findings = [
        Finding(exception.rule_id, exception.path, 1, "matched"),
        Finding(exception.rule_id, f"{exception.path}.other", 1, "different path"),
        Finding(f"{exception.rule_id}_OTHER", exception.path, 1, "different rule"),
    ]
    active, waived = apply_exceptions(findings, [exception])
    assert [item.message for item in waived] == ["matched"]
    assert {item.message for item in active} == {"different path", "different rule"}


def test_run_all_works_from_repository_root() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/architecture/run_all.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "11/11 passed" in result.stdout
