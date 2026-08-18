from __future__ import annotations

from collections import Counter
from pathlib import Path

from scripts.architecture.guard_core import load_exceptions


ROOT = Path(__file__).resolve().parents[1]


def test_exception_inventory_matches_audit_document() -> None:
    entries = load_exceptions()
    assert len(entries) == 39
    counts = Counter(item.rule_id for item in entries)
    assert counts == Counter(
        {
            "ORPHAN_SERVICE_MODULE": 22,
            "PY_LAYER_CORE_REVERSE": 7,
            "PY_LAYER_REPOSITORIES_REVERSE": 5,
            "PY_LAYER_SERVICES_REVERSE": 4,
            "WEB_STATUS_COLOR_TOKEN": 1,
        }
    )
    audit = (ROOT / "docs/architecture/EXCEPTIONS_AUDIT.md").read_text(encoding="utf-8")
    assert "总数为 39" in audit
    assert "maintenance CLI-only" in audit


def test_maintenance_cli_only_entries_have_explicit_runtime_importers() -> None:
    entries = {
        item.path: item
        for item in load_exceptions()
        if item.rule_id == "ORPHAN_SERVICE_MODULE"
    }
    for path, script in (
        (
            "src/netconsole/services/history_legacy_migration.py",
            "scripts/maintenance/migrate_device_history.py",
        ),
        (
            "src/netconsole/services/production_database_maintenance.py",
            "scripts/maintenance/production_database_maintenance.py",
        ),
    ):
        assert path in entries
        assert (ROOT / script).is_file()
        module = path.removeprefix("src/").removesuffix(".py").replace("/", ".")
        assert module in (
            (ROOT / script).read_text(encoding="utf-8").replace("/", ".")
        )
        assert "maintenance CLI" in entries[path].reason
