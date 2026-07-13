from __future__ import annotations

import ast
from importlib.util import resolve_name
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "src" / "netconsole"

FRAMEWORK_IMPORTS = ("PySide6", "PyQt6", "qfluentwidgets", "fastapi", "sqlalchemy")
IMPLEMENTATION_IMPORTS = (
    "sqlite3",
    "openpyxl",
    "pandas",
    "xlsxwriter",
    "netmiko",
    "paramiko",
    "pysnmp",
    "sqlalchemy",
    "netconsole.infrastructure",
    "netconsole.repositories",
    "netconsole.storage",
    "netconsole.parsers",
    "netconsole.adapters",
)
TARGET_ADAPTER_IMPORTS = IMPLEMENTATION_IMPORTS + (
    "netconsole.backend",
    "netconsole.services",
    "netconsole.ui",
)

# 迁移前已存在的直接依赖；只允许减少，不允许新增。
LEGACY_QT_PAGE_IMPORTS = {
    ("ac_management_page.py", "openpyxl.styles"),
    ("ac_management_page.py", "netconsole.adapters.h3c.h3c_command_profile"),
    ("ac_management_page.py", "netconsole.repositories.ac_repository"),
    ("ac_management_page.py", "netconsole.repositories.device_fact_repository"),
    ("ac_management_page.py", "netconsole.repositories.device_repository"),
    ("car_network_diagnostic_page.py", "netconsole.repositories.device_repository"),
    ("config_collection_center_page.py", "netconsole.repositories.config_snapshot_repository"),
    ("config_collection_center_page.py", "netconsole.repositories.device_group_repository"),
    ("config_collection_center_page.py", "netconsole.repositories.device_repository"),
    ("device_management_page.py", "netconsole.repositories.device_fact_repository"),
    ("device_management_page.py", "netconsole.repositories.device_group_repository"),
    ("device_management_page.py", "netconsole.repositories.device_repository"),
    ("file_management_page.py", "netconsole.repositories.device_repository"),
    ("mesh_log_analysis_page.py", "netconsole.repositories.device_repository"),
    ("mesh_log_analysis_page.py", "netconsole.repositories.mesh_catalog_repository"),
    ("mesh_log_analysis_page.py", "netconsole.repositories.mesh_mr_repository"),
    ("online_mr_collection_analysis_page.py", "netconsole.repositories.device_repository"),
    ("online_mr_collection_page.py", "netconsole.repositories.ac_repository"),
    ("online_mr_collection_page.py", "netconsole.repositories.device_repository"),
    ("online_mr_collection_page.py", "sqlite3"),
    ("rail_transit_page.py", "netconsole.repositories.device_repository"),
    ("snmp_center_page.py", "netconsole.repositories.device_repository"),
    ("snmp_center_page.py", "netconsole.repositories.global_mib_repository"),
    ("snmp_center_page.py", "netconsole.repositories.site_snmp_repository"),
    ("snmp_center_page.py", "sqlite3"),
    ("trackside_ap_plan_page.py", "netconsole.repositories.ac_repository"),
    ("trackside_ap_service_page.py", "netconsole.repositories.ac_repository"),
    ("trackside_ap_service_page.py", "netconsole.repositories.device_fact_repository"),
    ("trackside_ap_service_page.py", "netconsole.repositories.device_repository"),
    ("vehicle_mr_online_page.py", "netconsole.repositories.device_repository"),
}


def _matches(module: str, prefixes: tuple[str, ...]) -> bool:
    return any(module == prefix or module.startswith(f"{prefix}.") for prefix in prefixes)


def _imports(path: Path) -> set[str]:
    package = ".".join(path.relative_to(ROOT / "src").with_suffix("").parts[:-1])
    modules: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            name = "." * node.level + (node.module or "")
            if node.level:
                name = resolve_name(name, package)
            if name:
                modules.add(name)
    return modules


def _violations(directory: Path, forbidden: tuple[str, ...]) -> list[str]:
    return [
        f"{path.relative_to(ROOT)} -> {module}"
        for path in sorted(directory.rglob("*.py"))
        for module in sorted(_imports(path))
        if _matches(module, forbidden)
    ]


def test_domain_and_application_keep_inward_dependencies() -> None:
    domain_forbidden = FRAMEWORK_IMPORTS + (
        "netconsole.application",
        "netconsole.infrastructure",
        "netconsole.api",
        "netconsole.presentation",
        "netconsole.backend",
        "netconsole.ui",
        "netconsole.services",
        "netconsole.models",
        "netconsole.core",
        "netconsole.utils",
        "netconsole.repositories",
        "netconsole.storage",
        "netconsole.parsers",
        "netconsole.adapters",
    )
    application_forbidden = FRAMEWORK_IMPORTS + (
        "netconsole.infrastructure",
        "netconsole.api",
        "netconsole.presentation",
        "netconsole.backend",
        "netconsole.ui",
        "netconsole.services",
        "netconsole.models",
        "netconsole.core",
        "netconsole.utils",
        "netconsole.repositories",
        "netconsole.storage",
        "netconsole.parsers",
        "netconsole.adapters",
    )
    violations = _violations(PACKAGE_ROOT / "domain", domain_forbidden)
    violations += _violations(PACKAGE_ROOT / "application", application_forbidden)
    assert not violations, "domain/application 依赖越界：\n" + "\n".join(violations)


def test_new_qt_and_api_adapters_do_not_import_implementations() -> None:
    violations = _violations(PACKAGE_ROOT / "presentation" / "qt", TARGET_ADAPTER_IMPORTS)
    violations += _violations(PACKAGE_ROOT / "api", TARGET_ADAPTER_IMPORTS)
    assert not violations, "Qt/API 应只调用 application，不得直接导入具体实现：\n" + "\n".join(violations)


def test_legacy_qt_pages_do_not_add_direct_implementation_imports() -> None:
    pages = PACKAGE_ROOT / "ui" / "pages"
    actual = {
        (path.name, module)
        for path in sorted(pages.rglob("*.py"))
        for module in _imports(path)
        if _matches(module, IMPLEMENTATION_IMPORTS)
    }
    added = sorted(actual - LEGACY_QT_PAGE_IMPORTS)
    assert not added, "旧 Qt 页面新增了具体实现依赖，请先迁入 application/infrastructure：\n" + "\n".join(
        f"{filename} -> {module}" for filename, module in added
    )
