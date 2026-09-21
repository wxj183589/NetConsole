from __future__ import annotations

from collections import Counter
from pathlib import Path

from scripts.architecture.guard_core import load_exceptions


ROOT = Path(__file__).resolve().parents[1]


def test_exception_inventory_matches_audit_document() -> None:
    entries = load_exceptions()
    assert len(entries) == 37
    counts = Counter(item.rule_id for item in entries)
    assert counts == Counter(
        {
            "ORPHAN_SERVICE_MODULE": 20,
            "PY_LAYER_CORE_REVERSE": 7,
            "PY_LAYER_REPOSITORIES_REVERSE": 5,
            "PY_LAYER_SERVICES_REVERSE": 4,
            "WEB_STATUS_COLOR_TOKEN": 1,
        }
    )
    audit = (ROOT / "docs/architecture/ARCHITECTURE_EXCEPTIONS.md").read_text(encoding="utf-8")
    assert "总数为 37" in audit
    assert "Production maintenance boundary" in audit


def test_production_maintenance_capability_keeps_an_explicit_cli_boundary() -> None:
    entries = {
        item.path: item
        for item in load_exceptions()
        if item.rule_id == "ORPHAN_SERVICE_MODULE"
    }
    assert "src/netconsole/services/production_database_maintenance.py" not in entries
    assert (ROOT / "scripts/maintenance/production_database_maintenance.py").is_file()
    cli_text = (ROOT / "scripts/maintenance/production_database_maintenance.py").read_text(
        encoding="utf-8"
    ).replace("/", ".")
    assert "netconsole.services.production_database_maintenance" in cli_text
