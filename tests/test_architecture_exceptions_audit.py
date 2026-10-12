from __future__ import annotations

from collections import Counter
from datetime import date
from pathlib import Path

from scripts.architecture.guard_core import load_exceptions


ROOT = Path(__file__).resolve().parents[1]


def test_exception_inventory_matches_audit_document() -> None:
    entries = load_exceptions(today=date(2026, 9, 30))
    assert len(entries) == 0
    counts = Counter(item.rule_id for item in entries)
    assert counts == Counter()
    audit = (ROOT / "docs/architecture/ARCHITECTURE_EXCEPTIONS.md").read_text(encoding="utf-8")
    assert "总数为 0" in audit
    assert "Production maintenance boundary" in audit


def test_production_maintenance_capability_keeps_an_explicit_cli_boundary() -> None:
    entries = {
        item.path: item
        for item in load_exceptions(today=date(2026, 9, 30))
        if item.rule_id == "ORPHAN_SERVICE_MODULE"
    }
    assert "src/netconsole/services/production_database_maintenance.py" not in entries
    assert (ROOT / "scripts/maintenance/production_database_maintenance.py").is_file()
    cli_text = (ROOT / "scripts/maintenance/production_database_maintenance.py").read_text(
        encoding="utf-8"
    ).replace("/", ".")
    assert "netconsole.services.production_database_maintenance" in cli_text
