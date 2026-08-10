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
                    "path": "apps/web/src/**",
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
    assert "10/10 passed" in result.stdout
