from __future__ import annotations

import json
from pathlib import Path

from scripts.ui.table_guard import (
    check_column_definitions,
    check_table_alignment,
    check_table_contracts,
    inventory_markdown,
    scan_tables,
)


def _write(root: Path, relative: str, source: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def _empty_exceptions(root: Path) -> None:
    _write(root, "config/architecture/table-layout-exceptions.yaml", "exceptions: []\n")


def test_new_direct_element_table_is_rejected(tmp_path: Path) -> None:
    _write(tmp_path, "apps/web/src/views/demo/DemoView.vue", "<template><el-table :data=\"rows\" /></template>")
    _write(
        tmp_path,
        "config/architecture/table-layout-baseline.json",
        json.dumps({"version": 1, "direct_el_tables": []}),
    )
    _empty_exceptions(tmp_path)

    failures = check_table_contracts(tmp_path)

    assert any("新增直接 el-table" in failure for failure in failures)


def test_managed_table_requires_stable_route_and_table_ids(tmp_path: Path) -> None:
    _write(tmp_path, "apps/web/src/views/demo/DemoView.vue", "<template><NcDataTable /></template>")
    _write(
        tmp_path,
        "config/architecture/table-layout-baseline.json",
        json.dumps({"version": 1, "direct_el_tables": []}),
    )
    _empty_exceptions(tmp_path)

    failures = check_table_contracts(tmp_path)

    assert any("table-id" in failure for failure in failures)
    assert any("route-key" in failure for failure in failures)
    assert any("columns" in failure for failure in failures)


def test_migrated_file_cannot_mix_legacy_column_rules(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "apps/web/src/views/demo/DemoView.vue",
        "<template><NcDataTable table-id=\"demo\" route-key=\"/demo\" :columns=\"columns\" />"
        "<el-table-column width=\"80\" /></template>",
    )

    assert check_column_definitions(tmp_path) == [
        "迁移文件仍直接声明 el-table-column: apps/web/src/views/demo/DemoView.vue"
    ]


def test_migrated_file_cannot_calculate_or_limit_table_width(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "apps/web/src/views/demo/DemoView.vue",
        "<script setup>const width = containerWidth / columns.length; distributeColumnWidths()</script>"
        "<template><NcDataTable table-id=\"demo\" route-key=\"/demo\" :columns=\"columns\" /></template>"
        "<style>.nc-data-table { width: 60%; }</style>",
    )

    definition_failures = check_column_definitions(tmp_path)
    alignment_failures = check_table_alignment(tmp_path)

    assert any("不得自行调用公共列宽算法" in failure for failure in definition_failures)
    assert any("不得按容器宽度平均分配列宽" in failure for failure in definition_failures)
    assert alignment_failures == ["迁移文件不得限制表格百分比宽度: apps/web/src/views/demo/DemoView.vue"]


def test_inventory_uses_only_explicit_migration_states(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "apps/web/src/views/demo/DemoView.vue",
        "<template><NcDataTable table-id=\"managed\" route-key=\"/demo\" :columns=\"columns\" />"
        "<el-table :data=\"rows\" /></template>",
    )

    direct, managed = scan_tables(tmp_path)
    inventory = inventory_markdown(tmp_path)

    assert len(direct) == 1
    assert len(managed) == 1
    assert "COMPLIANT" in inventory
    assert "BLOCKED" in inventory
