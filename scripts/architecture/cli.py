from __future__ import annotations

import argparse
from collections.abc import Callable

from scripts.architecture.checks import (
    architecture_boundary_findings,
    device_command_findings,
    direct_sql_findings,
    dynamic_chart_stability_findings,
    forbidden_import_findings,
    history_migration_contract_findings,
    production_database_boundary_findings,
    orphan_module_findings,
    product_architecture_findings,
    removed_feature_findings,
    runtime_path_findings,
    storage_registry_findings,
    ui_business_logic_findings,
)
from scripts.architecture.guard_core import Finding, finish


CHECKS: dict[str, Callable[[], list[Finding]]] = {
    "architecture-boundaries": architecture_boundary_findings,
    "forbidden-imports": forbidden_import_findings,
    "direct-sql-access": direct_sql_findings,
    "dynamic-chart-stability": dynamic_chart_stability_findings,
    "device-command-hardcoding": device_command_findings,
    "ui-business-logic": ui_business_logic_findings,
    "removed-features": removed_feature_findings,
    "runtime-paths": runtime_path_findings,
    "orphan-modules": orphan_module_findings,
    "product-architecture": product_architecture_findings,
    "storage-registry": storage_registry_findings,
    "history-migration-contracts": history_migration_contract_findings,
    "production-database-boundary": production_database_boundary_findings,
}


def run_named(name: str) -> int:
    return finish(name, CHECKS[name]())


def main(name: str) -> int:
    parser = argparse.ArgumentParser(description=f"Run the {name} architecture guard")
    parser.parse_args()
    return run_named(name)
