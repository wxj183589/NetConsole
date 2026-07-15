from __future__ import annotations

import ast
from pathlib import Path


ROUTER_ROOT = Path(__file__).resolve().parents[1] / "src" / "netconsole" / "backend" / "api"
FORBIDDEN_IMPORTS = {
    "asyncssh",
    "bz2",
    "gzip",
    "lzma",
    "netmiko",
    "paramiko",
    "shutil",
    "tarfile",
    "zipfile",
    "zlib",
}
CONSTRUCTOR_SUFFIXES = ("Database", "Parser", "PathResolver", "Repository", "Service")
SQLITE_DEPENDENCY = "sqlite3 exception mapping dependency"

# Phase 0.5 当前分支证据：A/B/C 业务债务和既有 SQLite 映射；E 集成后删除已消失项。
TEMPORARY_WAVE_DEBT = {
    "ac_management_router.py": {SQLITE_DEPENDENCY},
    "ac_mesh_link_router.py": {SQLITE_DEPENDENCY},
    "config_collection_router.py": {SQLITE_DEPENDENCY},
    "device_management_router.py": {SQLITE_DEPENDENCY},
    "file_management_router.py": {SQLITE_DEPENDENCY},
    "job_center_router.py": {SQLITE_DEPENDENCY},
    "mesh_analysis_router.py": {SQLITE_DEPENDENCY},
    "online_mr_router.py": {"stateful SiteManager.get_current_site"},
    "online_mr_control_router.py": {"stateful SiteManager.get_current_site"},
    "online_mr_agent_control_router.py": {"private router site helper"},
    "traffic_router.py": {
        "agent execution-target orchestration",
        "run filtering and pagination",
        "traffic controller-task cancellation and retry",
    },
    "rail_transit_base_data_router.py": {
        "import policy assembly",
        "import service guard access",
        SQLITE_DEPENDENCY,
    },
    "train_communication_router.py": {SQLITE_DEPENDENCY},
    "wireless_dashboard_router.py": {SQLITE_DEPENDENCY},
}


def _qualified_name(node: ast.AST, aliases: dict[str, str]) -> str:
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        prefix = _qualified_name(node.value, aliases)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _aliases(tree: ast.AST) -> dict[str, str]:
    result: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for item in node.names:
                result[item.asname or item.name] = f"{node.module or ''}.{item.name}".strip(".")
        elif isinstance(node, ast.Import):
            for item in node.names:
                result[item.asname or item.name.split(".")[0]] = item.name
    return result


def _forbidden_import(module: str) -> bool:
    parts = set(module.casefold().split("."))
    return bool(
        parts & FORBIDDEN_IMPORTS
        or "repositories" in parts
        or "parser" in parts
        or "parsers" in parts
        or module in {"netconsole.core.database", "netconsole.core.paths"}
    )


def _findings(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    aliases = _aliases(tree)
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    findings: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".", 1)[0] == "sqlite3":
                findings.add(SQLITE_DEPENDENCY)
            elif _forbidden_import(node.module or ""):
                findings.add(f"forbidden import {node.module}")
        elif isinstance(node, ast.Import):
            if any(item.name.split(".", 1)[0] == "sqlite3" for item in node.names):
                findings.add(SQLITE_DEPENDENCY)
            findings.update(f"forbidden import {item.name}" for item in node.names if _forbidden_import(item.name))
        elif isinstance(node, ast.Attribute) and _qualified_name(node, aliases).startswith("sqlite3."):
            if node.attr not in {"Error", "OperationalError"}:
                findings.add(f"sqlite3 runtime access {node.attr}")
        elif isinstance(node, ast.Call):
            name = _qualified_name(node.func, aliases)
            short_name = name.rsplit(".", 1)[-1]
            if name.startswith("sqlite3."):
                findings.add(f"sqlite3 runtime call {short_name}")
            elif short_name.endswith(CONSTRUCTOR_SUFFIXES):
                findings.add(f"infrastructure construction {short_name}")
            elif short_name == "SiteManager":
                parent = parents.get(node)
                method = parent.attr if isinstance(parent, ast.Attribute) and parent.value is node else ""
                if method == "get_current_site":
                    findings.add("stateful SiteManager.get_current_site")
                elif method != "validate_site_name":
                    findings.add(f"SiteManager infrastructure access {method or 'constructor'}")
            elif name in {"__import__", "importlib.import_module"} or (
                isinstance(node.func, ast.Call) and _qualified_name(node.func.func, aliases) == "getattr"
            ):
                findings.add("dynamic import or constructor lookup")

    if path.name == "online_mr_agent_control_router.py":
        if any(
            isinstance(node, ast.ImportFrom)
            and (node.module or "").endswith("online_mr_control_router")
            and any(item.name == "_site_id" for item in node.names)
            for node in ast.walk(tree)
        ):
            findings.add("private router site helper")
    elif path.name == "traffic_router.py":
        if any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "list_agents"
            and isinstance(node.func.value, ast.Call)
            and _qualified_name(node.func.value.func, aliases).endswith("agent_service")
            for node in ast.walk(tree)
        ):
            findings.add("agent execution-target orchestration")
        if any(
            isinstance(node, ast.Compare)
            and isinstance(node.left, ast.Attribute)
            and node.left.attr == "created_at"
            for node in ast.walk(tree)
        ) and any(isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == "runs" for node in ast.walk(tree)):
            findings.add("run filtering and pagination")
        traffic_controls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"cancel", "retry"}
            and any(isinstance(arg, ast.Attribute) and arg.attr == "controller_task_id" for arg in node.args)
        }
        if traffic_controls == {"cancel", "retry"}:
            findings.add("traffic controller-task cancellation and retry")
    elif path.name == "rail_transit_base_data_router.py":
        if any(isinstance(node, ast.Attribute) and node.attr == "guard" for node in ast.walk(tree)):
            findings.add("import service guard access")
        if any(
            isinstance(node, ast.Call)
            and _qualified_name(node.func, aliases).endswith(("ImportPolicyResponseDTO", "import_policy_rows"))
            for node in ast.walk(tree)
        ):
            findings.add("import policy assembly")
    return findings


def test_routers_keep_static_application_boundary() -> None:
    actual = {
        path.name: findings
        for path in sorted(ROUTER_ROOT.glob("*_router.py"))
        if (findings := _findings(path))
    }
    assert actual == TEMPORARY_WAVE_DEBT


def test_router_boundary_allows_controlled_transport_responses(tmp_path: Path) -> None:
    router = tmp_path / "transport_router.py"
    router.write_text(
        "from fastapi import WebSocket\n"
        "from fastapi.responses import FileResponse, StreamingResponse\n"
        "def download(path): return FileResponse(path)\n"
        "def stream(rows): return StreamingResponse(rows)\n"
        "async def socket(websocket: WebSocket): await websocket.accept()\n",
        encoding="utf-8",
    )
    assert _findings(router) == set()


def test_router_boundary_rejects_runtime_dependencies_and_construction(tmp_path: Path) -> None:
    router = tmp_path / "invalid_router.py"
    router.write_text(
        "import sqlite3, zipfile, paramiko\n"
        "from netconsole.core.database import Database\n"
        "from netconsole.core.paths import PathResolver\n"
        "from netconsole.core.sites import SiteManager\n"
        "from netconsole.repositories.device_repository import DeviceRepository\n"
        "from netconsole.parsers.cli import CommandParser\n"
        "from netconsole.services.demo import DemoApplicationService\n"
        "def route():\n"
        " sqlite3.connect('runtime.db')\n"
        " Database(); PathResolver(); DeviceRepository(); CommandParser(); DemoApplicationService()\n"
        " SiteManager().get_current_site(); zipfile.ZipFile('runtime.zip'); __import__('module')\n",
        encoding="utf-8",
    )

    findings = _findings(router)
    assert SQLITE_DEPENDENCY in findings
    assert "sqlite3 runtime call connect" in findings
    assert "stateful SiteManager.get_current_site" in findings
    assert "infrastructure construction DemoApplicationService" in findings
    assert "dynamic import or constructor lookup" in findings
    assert {"forbidden import zipfile", "forbidden import paramiko"} <= findings
    assert any(item.startswith("forbidden import netconsole.repositories") for item in findings)


def test_router_boundary_rejects_sqlite_direct_symbol_import(tmp_path: Path) -> None:
    router = tmp_path / "sqlite_symbol_router.py"
    router.write_text("from sqlite3 import OperationalError\n", encoding="utf-8")
    assert _findings(router) == {SQLITE_DEPENDENCY}
