from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
import tokenize
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from scripts.architecture.guard_core import CONFIG_ROOT, ROOT, Finding, load_json_yaml, relative_path, run_git


PYTHON_ROOT = ROOT / "src" / "netconsole"
ROUTER_ROOT = PYTHON_ROOT / "backend" / "api"
TS_AST_SCRIPT = ROOT / "scripts" / "architecture" / "typescript_ast.mjs"
SQL_CONNECT_NAMES = {
    "sqlite3.connect",
    "aiosqlite.connect",
    "netconsole.core.sqlite_utils.connect_sqlite",
}
SQL_CLASSIFICATIONS = {
    "REPOSITORY_REQUIRED",
    "READ_ONLY_DATA_GATEWAY",
    "ANALYSIS_DB_OWNER",
    "MIGRATION_TOOL",
    "TEST_ONLY",
    "VIOLATION",
}
UI_CLASSIFICATIONS = {"DISPLAY_ONLY", "BUSINESS_LOGIC", "FALSE_POSITIVE"}
UI_NAME_PATTERN = re.compile(
    r"(?:parse|calculat|aggregate|merge|match|resolve|dedup|normaliz|bucket|summari[sz]|derive|classif|reconcile)",
    re.IGNORECASE,
)
COLOR_LITERAL = re.compile(
    r"(?:#[0-9a-f]{3,8}\b|rgba?\s*\(|hsla?\s*\()", re.IGNORECASE
)
NAMED_THEME_COLOR_LITERAL = re.compile(r"\b(?:white|black)\b", re.IGNORECASE)
THEME_BASE_PROPERTIES = {
    "background",
    "background-color",
    "border",
    "border-bottom",
    "border-bottom-color",
    "border-color",
    "border-left",
    "border-left-color",
    "border-right",
    "border-right-color",
    "border-top",
    "border-top-color",
    "box-shadow",
    "color",
    "outline-color",
    "text-shadow",
}
THEME_LITERAL_CATEGORIES = {"BRAND", "STATUS", "CHART_SERIES"}
THEME_LITERAL_CONFIG_FIELDS = {
    "path", "selector", "property", "value", "category", "reason", "owner", "test"
}
STATUS_SELECTOR = re.compile(
    r"(?:success|warning|danger|critical|online|offline|status|normal)",
    re.IGNORECASE,
)
ALLOWED_STATUS_TOKENS = {
    "--nc-primary",
    "--nc-success",
    "--nc-warning",
    "--nc-danger",
    "--nc-info",
    "--nc-status-success-bg",
    "--nc-status-warning-bg",
    "--nc-status-danger-bg",
    "--nc-text-code-success",
    "--nc-text-code-danger",
    "--nc-text-code-warning",
    "--el-color-primary",
    "--el-color-success",
    "--el-color-success-light-7",
    "--el-color-warning",
    "--el-color-danger",
    "--el-color-danger-light-7",
    "--el-color-info",
}
STATUS_TOKEN_NAME = re.compile(
    r"^--(?:nc-(?:status-)?(?:primary|success|warning|danger|info)|"
    r"el-color-(?:primary|success|warning|danger|info))(?:-|$)",
    re.IGNORECASE,
)
BASE_ELEMENT_PREFIXES = (
    "--el-bg-",
    "--el-border-",
    "--el-box-shadow",
    "--el-color-",
    "--el-disabled-",
    "--el-fill-",
    "--el-font-",
    "--el-mask-",
    "--el-text-",
)

FORBIDDEN_ROUTER_IMPORTS = {
    "asyncssh", "bz2", "gzip", "lzma", "netmiko", "paramiko", "shutil", "tarfile", "zipfile", "zlib"
}
CONSTRUCTOR_SUFFIXES = ("Database", "Parser", "PathResolver", "Repository", "Service")
SQLITE_DEPENDENCY = "sqlite3 exception mapping dependency"


def _python_files() -> Iterable[Path]:
    yield from sorted(PYTHON_ROOT.rglob("*.py"))


def _parse_python(path: Path) -> ast.Module:
    with tokenize.open(path) as stream:
        return ast.parse(stream.read(), filename=str(path))


@dataclass(frozen=True)
class CssDeclaration:
    selector: str
    property: str
    value: str
    line: int


def _css_declarations(text: str, *, line_offset: int = 0) -> list[CssDeclaration]:
    """Parse CSS blocks and declarations with balanced braces/parentheses."""
    source = re.sub(r"/\*[\s\S]*?\*/", lambda match: "\n" * match.group(0).count("\n"), text)
    declarations: list[CssDeclaration] = []

    def matching_brace(start: int, end: int) -> int:
        depth = 0
        quote = ""
        escaped = False
        for index in range(start, end):
            char = source[index]
            if quote:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = ""
            elif char in {'"', "'"}:
                quote = char
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return index
        return -1

    def parse_range(start: int, end: int) -> None:
        cursor = start
        while cursor < end:
            open_brace = source.find("{", cursor, end)
            if open_brace < 0:
                return
            close_brace = matching_brace(open_brace, end)
            if close_brace < 0:
                return
            selector = source[cursor:open_brace].strip()
            body_start = open_brace + 1
            if selector.startswith("@"):
                parse_range(body_start, close_brace)
            else:
                segment_start = body_start
                parentheses = 0
                quote = ""
                escaped = False
                for index in range(body_start, close_brace + 1):
                    char = source[index] if index < close_brace else ";"
                    if quote:
                        if escaped:
                            escaped = False
                        elif char == "\\":
                            escaped = True
                        elif char == quote:
                            quote = ""
                    elif char in {'"', "'"}:
                        quote = char
                    elif char == "(":
                        parentheses += 1
                    elif char == ")":
                        parentheses = max(0, parentheses - 1)
                    elif char == ";" and parentheses == 0:
                        raw = source[segment_start:index].strip()
                        segment_start = index + 1
                        if ":" not in raw or "{" in raw:
                            continue
                        property_name, value = raw.split(":", 1)
                        property_name = property_name.strip().casefold()
                        if not re.fullmatch(r"(?:--)?[a-z_][a-z0-9_-]*", property_name):
                            continue
                        line = line_offset + source.count("\n", 0, index - len(raw)) + 1
                        declarations.append(
                            CssDeclaration(selector, property_name, value.strip(), line)
                        )
            cursor = close_brace + 1

    parse_range(0, len(source))
    return declarations


def _file_css_declarations(path: Path) -> list[CssDeclaration]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".css":
        return _css_declarations(text)
    declarations: list[CssDeclaration] = []
    for match in re.finditer(r"<style\b[^>]*>([\s\S]*?)</style>", text, re.IGNORECASE):
        offset = text.count("\n", 0, match.start(1))
        declarations.extend(_css_declarations(match.group(1), line_offset=offset))
    return declarations


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


def _forbidden_router_import(module: str) -> bool:
    parts = set(module.casefold().split("."))
    return bool(
        parts & FORBIDDEN_ROUTER_IMPORTS
        or "repositories" in parts
        or "parser" in parts
        or "parsers" in parts
        or module in {"netconsole.core.database", "netconsole.core.paths"}
    )


def router_boundary_messages(path: Path) -> set[str]:
    tree = _parse_python(path)
    aliases = _aliases(tree)
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    findings: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".", 1)[0] == "sqlite3":
                findings.add(SQLITE_DEPENDENCY)
            elif _forbidden_router_import(node.module or ""):
                findings.add(f"forbidden import {node.module}")
        elif isinstance(node, ast.Import):
            if any(item.name.split(".", 1)[0] == "sqlite3" for item in node.names):
                findings.add(SQLITE_DEPENDENCY)
            findings.update(
                f"forbidden import {item.name}"
                for item in node.names
                if _forbidden_router_import(item.name)
            )
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
    if path.name == "online_mr_agent_control_router.py" and any(
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
        ) and any(
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == "runs"
            for node in ast.walk(tree)
        ):
            findings.add("run filtering and pagination")
        traffic_controls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"cancel", "retry"}
            and any(
                isinstance(argument, ast.Attribute)
                and argument.attr == "controller_task_id"
                for argument in node.args
            )
        }
        if traffic_controls == {"cancel", "retry"}:
            findings.add("traffic controller-task cancellation and retry")
    elif path.name == "rail_transit_base_data_router.py":
        if any(
            isinstance(node, ast.Attribute) and node.attr == "guard"
            for node in ast.walk(tree)
        ):
            findings.add("import service guard access")
        if any(
            isinstance(node, ast.Call)
            and _qualified_name(node.func, aliases).endswith(
                ("ImportPolicyResponseDTO", "import_policy_rows")
            )
            for node in ast.walk(tree)
        ):
            findings.add("import policy assembly")
    return findings


def architecture_boundary_findings() -> list[Finding]:
    findings: list[Finding] = []
    forbidden_layers = {
        "core": {"application", "backend", "infrastructure", "repositories", "services"},
        "repositories": {"application", "backend", "infrastructure", "services"},
        "services": {"application", "backend", "infrastructure"},
        "application": {"backend"},
    }
    for path in _python_files():
        tree = _parse_python(path)
        relative = path.relative_to(PYTHON_ROOT)
        layer = relative.parts[0]
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.ImportFrom):
                modules.append(node.module or "")
            elif isinstance(node, ast.Import):
                modules.extend(item.name for item in node.names)
            for module in modules:
                parts = module.split(".")
                target = parts[1] if len(parts) > 1 and parts[0] == "netconsole" else ""
                if target in forbidden_layers.get(layer, set()):
                    findings.append(Finding(f"PY_LAYER_{layer.upper()}_REVERSE", relative_path(path), node.lineno, f"{layer} imports {module}"))
    for path in sorted(ROUTER_ROOT.glob("*_router.py")):
        for message in sorted(router_boundary_messages(path)):
            findings.append(Finding("FASTAPI_ROUTER_BOUNDARY", relative_path(path), 0, message))
    records, failure = typescript_records()
    if failure:
        findings.append(failure)
        return findings
    for record in records:
        item_path = str(record["path"])
        for diagnostic in record["diagnostics"]:
            findings.append(Finding("TS_AST_PARSE", item_path, int(diagnostic["line"]), str(diagnostic["message"])))
        for item in record["imports"]:
            specifier = str(item["specifier"]).replace("\\", "/")
            line = int(item["line"])
            if item_path.startswith("apps/desktop_renderer/src/") and (
                "/main/" in specifier or "/preload/" in specifier
            ):
                findings.append(Finding("TS_WEB_ELECTRON_IMPORT", item_path, line, f"web imports {specifier}"))
            elif item_path.startswith("apps/desktop_electron/src/main/") and ("apps/desktop_renderer" in specifier or "/stores/" in specifier):
                findings.append(Finding("TS_MAIN_WEB_IMPORT", item_path, line, f"main imports {specifier}"))
            elif item_path.startswith("apps/desktop_electron/src/preload/") and not (
                specifier == "electron" or specifier.startswith("../shared/") or specifier.startswith("./")
            ):
                findings.append(Finding("TS_PRELOAD_BUSINESS_IMPORT", item_path, line, f"preload imports {specifier}"))
        for item in record["legacy"]:
            if item_path not in {
                "apps/desktop_renderer/src/navigation/registry.ts",
                "apps/desktop_renderer/src/navigation/registry.test.ts",
            }:
                findings.append(Finding("LEGACY_NAV_FIELD_SCOPE", item_path, int(item["line"]), f"legacy field {item['name']} escaped migration metadata"))
    return findings


def forbidden_import_findings() -> list[Finding]:
    findings: list[Finding] = []
    forbidden_roots = {"PySide2", "PySide6", "PyQt5", "PyQt6", "qfluentwidgets", "QFluentWidgets", "qtpy"}
    for path in _python_files():
        tree = _parse_python(path)
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.ImportFrom):
                modules.append(node.module or "")
            elif isinstance(node, ast.Import):
                modules.extend(item.name for item in node.names)
            for module in modules:
                if module.split(".", 1)[0] in forbidden_roots:
                    findings.append(Finding("QT_RUNTIME_IMPORT", relative_path(path), node.lineno, f"imports {module}"))
    for relative in ("requirements-runtime.txt", "pyproject.toml", "apps/desktop_electron/package.json", "apps/desktop_renderer/package.json"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        for marker in sorted(forbidden_roots):
            if re.search(rf"(?i)(?:^|[^a-z]){re.escape(marker)}(?:$|[^a-z])", text):
                findings.append(Finding("QT_RUNTIME_DEPENDENCY", relative, 0, f"declares {marker}"))
    return findings


def _load_sql_inventory() -> dict[str, dict[str, str]]:
    raw = load_json_yaml(CONFIG_ROOT / "direct_sql_access.yaml")
    if not isinstance(raw, list):
        raise ValueError("direct_sql_access.yaml must contain a list")
    result: dict[str, dict[str, str]] = {}
    required = {"path", "classification", "owner", "reason"}
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict) or set(item) != required:
            raise ValueError(f"direct_sql_access.yaml item {index} must contain exactly {sorted(required)}")
        values = {key: str(value).strip() for key, value in item.items()}
        item_path = values["path"].replace("\\", "/")
        if any(char in item_path for char in "*?[") or item_path in result:
            raise ValueError(f"direct_sql_access.yaml item {index} path must be unique and exact")
        if values["classification"] not in SQL_CLASSIFICATIONS:
            raise ValueError(f"direct_sql_access.yaml item {index} has invalid classification")
        result[item_path] = values
    return result


def direct_sql_findings() -> list[Finding]:
    findings: list[Finding] = []
    try:
        inventory = _load_sql_inventory()
    except ValueError as exc:
        return [Finding("DIRECT_SQL_CONFIG", "config/architecture/direct_sql_access.yaml", 0, str(exc))]
    actual_paths: set[str] = set()
    scan_roots = (PYTHON_ROOT, ROOT / "scripts", ROOT / "tests")
    for scan_root in scan_roots:
        for path in sorted(scan_root.rglob("*.py")):
            if "scripts/architecture" in path.as_posix():
                continue
            tree = _parse_python(path)
            aliases = _aliases(tree)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = _qualified_name(node.func, aliases)
                if name not in SQL_CONNECT_NAMES:
                    continue
                item_path = relative_path(path)
                actual_paths.add(item_path)
                config = inventory.get(item_path)
                if config is None:
                    findings.append(Finding("DIRECT_SQL_UNCLASSIFIED", item_path, node.lineno, f"unclassified {name}"))
                elif config["classification"] == "VIOLATION":
                    findings.append(
                        Finding(
                            "DIRECT_SQL_VIOLATION",
                            item_path,
                            node.lineno,
                            f"{name}; owner={config['owner']}",
                        )
                    )
    for item_path in sorted(inventory.keys() - actual_paths):
        findings.append(Finding("DIRECT_SQL_STALE_CLASSIFICATION", item_path, 0, "classified file no longer opens SQLite directly"))
    return findings


def device_command_findings() -> list[Finding]:
    process = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "maintenance" / "audit_commands.py"), "--strict", "--json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if process.returncode == 0:
        return []
    message = (process.stdout or process.stderr).strip().replace("\n", " ")
    return [Finding("DEVICE_COMMAND_AUDIT", "scripts/maintenance/audit_commands.py", 0, message or f"exited {process.returncode}")]


def typescript_records() -> tuple[list[dict[str, Any]], Finding | None]:
    process = subprocess.run(
        ["node", str(TS_AST_SCRIPT)], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
    )
    if process.returncode != 0:
        return [], Finding("TS_AST_UNAVAILABLE", relative_path(TS_AST_SCRIPT), 0, (process.stderr or process.stdout).strip())
    try:
        payload = json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        return [], Finding("TS_AST_INVALID_OUTPUT", relative_path(TS_AST_SCRIPT), 0, str(exc))
    return payload, None


def ui_business_logic_findings() -> list[Finding]:
    records, failure = typescript_records()
    if failure:
        return [failure]
    raw = load_json_yaml(CONFIG_ROOT / "ui_business_logic.yaml")
    if not isinstance(raw, list):
        return [Finding("UI_CLASSIFICATION_CONFIG", "config/architecture/ui_business_logic.yaml", 0, "must contain a list")]
    classified: dict[tuple[str, str], dict[str, str]] = {}
    required = {"path", "symbol", "classification", "reason", "test"}
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict) or set(item) != required:
            return [Finding("UI_CLASSIFICATION_CONFIG", "config/architecture/ui_business_logic.yaml", index, f"item must contain exactly {sorted(required)}")]
        values = {key: str(value).strip() for key, value in item.items()}
        key = (values["path"].replace("\\", "/"), values["symbol"])
        if any(char in key[0] for char in "*?[") or key in classified or values["classification"] not in UI_CLASSIFICATIONS:
            return [Finding("UI_CLASSIFICATION_CONFIG", "config/architecture/ui_business_logic.yaml", index, "invalid exact classification")]
        if not (ROOT / values["test"]).is_file():
            return [Finding("UI_CLASSIFICATION_CONFIG", "config/architecture/ui_business_logic.yaml", index, f"test does not exist: {values['test']}")]
        classified[key] = values
    findings: list[Finding] = []
    candidates: set[tuple[str, str]] = set()
    for record in records:
        item_path = str(record["path"])
        if not item_path.startswith("apps/desktop_renderer/src/") or item_path.endswith(".test.ts"):
            continue
        for item in record["functions"]:
            symbol = str(item["name"])
            if not UI_NAME_PATTERN.search(symbol):
                continue
            key = (item_path, symbol)
            candidates.add(key)
            config = classified.get(key)
            if config is None:
                findings.append(Finding("UI_BUSINESS_LOGIC_UNCLASSIFIED", item_path, int(item["line"]), f"candidate symbol {symbol}"))
            elif config["classification"] == "BUSINESS_LOGIC":
                findings.append(Finding("UI_BUSINESS_LOGIC", item_path, int(item["line"]), f"classified business symbol {symbol}"))
    for item_path, symbol in sorted(classified.keys() - candidates):
        findings.append(Finding("UI_CLASSIFICATION_STALE", item_path, 0, f"symbol no longer detected: {symbol}"))
    findings.extend(web_theme_findings(records))
    return findings


def dynamic_chart_stability_findings() -> list[Finding]:
    """Keep shared ECharts timelines on the proven no-dirty-rectangle lifecycle."""
    findings: list[Finding] = []
    chart_root = ROOT / "apps" / "desktop_renderer" / "src" / "components"
    required_patterns = {
        "useDirtyRect: false": re.compile(r"createTimeChartInitOptions\s*\([\s\S]{0,240}?useDirtyRect\s*:\s*false"),
        "ResizeObserver": re.compile(r"ResizeObserver"),
        "dispose": re.compile(r"\.dispose\s*\("),
        "connectNulls: false": re.compile(r"connectNulls\s*:\s*false"),
        "replaceMerge series": re.compile(r"replaceMerge\s*:\s*\[[^\]]*['\"]series['\"]"),
    }
    for path in sorted(chart_root.rglob("*.vue")):
        text = path.read_text(encoding="utf-8")
        if "createTimeChartInitOptions" not in text:
            continue
        item_path = relative_path(path)
        for label, pattern in required_patterns.items():
            if pattern.search(text):
                continue
            findings.append(
                Finding(
                    "DYNAMIC_CHART_STABILITY",
                    item_path,
                    1,
                    f"dynamic chart must provide {label}",
                )
            )
    return findings


def _load_theme_literal_allowlist(
    config_path: Path | None = None,
) -> dict[tuple[str, str, str, str], dict[str, str]]:
    config_path = config_path or CONFIG_ROOT / "theme_color_literals.yaml"
    raw = load_json_yaml(config_path)
    if not isinstance(raw, list):
        raise ValueError("theme_color_literals.yaml must contain a list")
    result: dict[tuple[str, str, str, str], dict[str, str]] = {}
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict) or set(item) != THEME_LITERAL_CONFIG_FIELDS:
            raise ValueError(
                f"theme_color_literals.yaml item {index} must contain exactly "
                f"{sorted(THEME_LITERAL_CONFIG_FIELDS)}"
            )
        values = {key: str(value).strip() for key, value in item.items()}
        if any(not value for value in values.values()):
            raise ValueError(f"theme_color_literals.yaml item {index} contains an empty field")
        item_path = values["path"].replace("\\", "/")
        test_path = values["test"].replace("\\", "/")
        if (
            not item_path.startswith("apps/desktop_renderer/src/")
            or Path(item_path).is_absolute()
            or any(char in item_path for char in "*?[")
            or not (ROOT / item_path).is_file()
        ):
            raise ValueError(
                f"theme_color_literals.yaml item {index} path must be an exact Web source file"
            )
        if any(char in values["selector"] for char in "*?["):
            raise ValueError(
                f"theme_color_literals.yaml item {index} selector must be exact without wildcards"
            )
        if values["property"].casefold() not in THEME_BASE_PROPERTIES:
            raise ValueError(f"theme_color_literals.yaml item {index} property is not controlled")
        if values["category"] not in THEME_LITERAL_CATEGORIES:
            raise ValueError(f"theme_color_literals.yaml item {index} category is invalid")
        if not (ROOT / test_path).is_file():
            raise ValueError(
                f"theme_color_literals.yaml item {index} test does not exist: {test_path}"
            )
        key = (
            item_path,
            values["selector"],
            values["property"].casefold(),
            values["value"],
        )
        if key in result:
            raise ValueError(f"theme_color_literals.yaml item {index} duplicates an exact entry")
        result[key] = values
    return result


def web_theme_findings(
    records: list[dict[str, Any]] | None = None,
) -> list[Finding]:
    findings: list[Finding] = []
    try:
        literal_allowlist = _load_theme_literal_allowlist()
    except ValueError as exc:
        return [
            Finding(
                "WEB_THEME_LITERAL_CONFIG",
                "config/architecture/theme_color_literals.yaml",
                0,
                str(exc),
            )
        ]
    matched_literal_allowlist: set[tuple[str, str, str, str]] = set()
    tokens_path = ROOT / "apps" / "desktop_renderer" / "src" / "theme" / "tokens.css"
    token_declarations = {
        declaration.property: declaration.value
        for declaration in _file_css_declarations(tokens_path)
        if declaration.property.startswith("--nc-")
    }
    chart_series_tokens = {
        "--nc-primary",
        "--nc-success",
        "--nc-warning",
        "--nc-danger",
        "--nc-info",
    }
    required_tokens = chart_series_tokens | {"--nc-content-max-width"}
    for token in sorted(required_tokens - token_declarations.keys()):
        findings.append(
            Finding("WEB_THEME_TOKEN_MISSING", relative_path(tokens_path), 0, f"missing {token}")
        )

    required_theme_tokens = {
        "--nc-bg-app",
        "--nc-bg-code",
        "--nc-bg-code-added",
        "--nc-bg-code-modified",
        "--nc-bg-code-removed",
        "--nc-bg-panel",
        "--nc-text-code",
        "--nc-text-code-danger",
        "--nc-text-code-success",
        "--nc-text-code-warning",
        "--nc-text-primary",
    }
    for theme_name in ("light.css", "dark.css"):
        theme_path = tokens_path.with_name(theme_name)
        declared = {
            item.property
            for item in _file_css_declarations(theme_path)
            if item.property.startswith("--nc-")
        }
        for token in sorted(required_theme_tokens - declared):
            findings.append(
                Finding("WEB_THEME_TOKEN_MISSING", relative_path(theme_path), 0, f"missing {token}")
            )

    style_paths = sorted((ROOT / "apps" / "desktop_renderer" / "src").rglob("*.css"))
    style_paths.extend(sorted((ROOT / "apps" / "desktop_renderer" / "src").rglob("*.vue")))
    sidebar_background_found = False
    for path in style_paths:
        item_path = relative_path(path)
        for declaration in _file_css_declarations(path):
            has_literal = bool(
                COLOR_LITERAL.search(declaration.value)
                or NAMED_THEME_COLOR_LITERAL.search(declaration.value)
            )
            if declaration.property in THEME_BASE_PROPERTIES and has_literal:
                key = (
                    item_path,
                    declaration.selector,
                    declaration.property,
                    declaration.value,
                )
                if key in literal_allowlist:
                    matched_literal_allowlist.add(key)
                else:
                    findings.append(
                        Finding(
                            "WEB_THEME_BASE_LITERAL",
                            item_path,
                            declaration.line,
                            f"{declaration.selector} {declaration.property}={declaration.value}",
                        )
                    )
            if (
                declaration.property.startswith(BASE_ELEMENT_PREFIXES)
                and item_path != "apps/desktop_renderer/src/theme/element-plus.css"
            ):
                findings.append(
                    Finding(
                        "WEB_THEME_EL_BASE_OVERRIDE",
                        item_path,
                        declaration.line,
                        f"{declaration.property} must be owned by theme/element-plus.css",
                    )
                )
            if ".app-sidebar" in declaration.selector and declaration.property in {
                "background",
                "background-color",
            }:
                if declaration.selector.strip() == ".app-sidebar":
                    sidebar_background_found = (
                        declaration.value == "var(--nc-bg-sidebar)"
                    )
                if COLOR_LITERAL.search(declaration.value):
                    findings.append(
                        Finding(
                            "WEB_THEME_SIDEBAR_LITERAL",
                            item_path,
                            declaration.line,
                            f"{declaration.selector} uses {declaration.value}",
                        )
                    )
            if (
                STATUS_SELECTOR.search(declaration.selector)
                and declaration.property
                in {"color", "background", "background-color", "border-color", "border-top-color", "border-left-color"}
            ):
                token_match = re.fullmatch(r"var\((--[a-z0-9-]+)\)", declaration.value, re.IGNORECASE)
                semantic_token = bool(
                    token_match and STATUS_TOKEN_NAME.search(token_match.group(1))
                )
                if COLOR_LITERAL.search(declaration.value) or (
                    semantic_token
                    and token_match
                    and token_match.group(1) not in ALLOWED_STATUS_TOKENS
                ):
                    findings.append(
                        Finding(
                            "WEB_STATUS_COLOR_TOKEN",
                            item_path,
                            declaration.line,
                            f"{declaration.selector} {declaration.property}={declaration.value}",
                        )
                    )
            if (
                "/components/" in item_path
                and item_path.endswith("Chart.vue")
                and declaration.property
                in {"color", "background", "background-color", "border-color"}
                and COLOR_LITERAL.search(declaration.value)
            ):
                findings.append(
                    Finding(
                        "WEB_CHART_LITERAL_COLOR",
                        item_path,
                        declaration.line,
                        f"chart style literal color {declaration.value}",
                    )
                )
    if not sidebar_background_found:
        findings.append(
            Finding(
                "WEB_THEME_SIDEBAR_SURFACE",
                "apps/desktop_renderer/src/styles/main.css",
                0,
                ".app-sidebar background must be var(--nc-bg-sidebar)",
            )
        )
    for item_path, selector, property_name, value in sorted(
        literal_allowlist.keys() - matched_literal_allowlist
    ):
        findings.append(
            Finding(
                "WEB_THEME_LITERAL_CONFIG",
                "config/architecture/theme_color_literals.yaml",
                0,
                f"stale exact entry {item_path} {selector} {property_name}={value}",
            )
        )

    main_styles = ROOT / "apps" / "desktop_renderer" / "src" / "styles" / "main.css"
    layout_declarations = {
        (item.selector, item.property): item.value
        for item in _file_css_declarations(main_styles)
    }
    required_layout = {
        (".app-workspace", "flex"): "1 1 auto",
        (".app-workspace", "min-width"): "0",
        (".app-main", "width"): "100%",
        (".app-shell .app-workspace .app-main > *", "width"): "100%",
        (".app-shell .app-workspace .app-main > *", "max-width"): "var(--nc-content-max-width)",
        (".app-main .el-table", "width"): "100%",
    }
    for key, expected in required_layout.items():
        if layout_declarations.get(key) != expected:
            findings.append(
                Finding(
                    "WEB_LAYOUT_FLUID_CONTAINER",
                    relative_path(main_styles),
                    0,
                    f"{key[0]} {key[1]} must be {expected}",
                )
            )
    app_layout = ROOT / "apps" / "desktop_renderer" / "src" / "layouts" / "AppLayout.vue"
    app_layout_text = app_layout.read_text(encoding="utf-8")
    if re.search(
        r"style\s*=\s*(['\"])[^'\"]*background(?:-color)?\s*:\s*(?:#[0-9a-f]{3,8}|rgba?\s*\(|hsla?\s*\()[^'\"]*\1",
        app_layout_text,
        re.IGNORECASE,
    ):
        findings.append(
            Finding(
                "WEB_THEME_SIDEBAR_LITERAL",
                relative_path(app_layout),
                0,
                "AppLayout inline style contains a literal background",
            )
        )

    ast_records = records
    if ast_records is None:
        ast_records, failure = typescript_records()
        if failure:
            return findings + [failure]
    for record in ast_records:
        item_path = str(record["path"])
        is_chart = "/components/" in item_path and (
            item_path.endswith("Chart.vue") or item_path.endswith("Chart.ts")
        )
        if not is_chart:
            continue
        imports = {str(item["specifier"]) for item in record["imports"]}
        if not any(specifier.endswith("theme/echarts") for specifier in imports):
            findings.append(
                Finding(
                    "WEB_CHART_TOKEN_IMPORT",
                    item_path,
                    0,
                    "chart must consume the shared ECharts token adapter",
                )
            )
        for color in record.get("colors", []):
            findings.append(
                Finding(
                    "WEB_CHART_LITERAL_COLOR",
                    item_path,
                    int(color["line"]),
                    f"chart literal color {color['value']}",
                )
            )
    echarts_path = ROOT / "apps" / "desktop_renderer" / "src" / "theme" / "echarts.ts"
    echarts_text = echarts_path.read_text(encoding="utf-8")
    for token in sorted(chart_series_tokens):
        if f"read('{token}'" not in echarts_text:
            findings.append(
                Finding(
                    "WEB_CHART_SERIES_TOKEN",
                    relative_path(echarts_path),
                    0,
                    f"shared chart series does not read {token}",
                )
            )
    return findings


def removed_feature_findings() -> list[Finding]:
    findings: list[Finding] = []
    for relative in ("src/netconsole/ui", "apps/desktop", "src/netconsole/services/wifi_survey"):
        tracked = run_git("ls-files", "--", relative)
        if tracked.returncode != 0 or tracked.stdout.strip():
            findings.append(Finding("REMOVED_FEATURE_PATH", relative, 0, "removed architecture path exists"))
    allowed = {"src/netconsole/core/feature_registry.py"}
    markers = {"module.snmp_center", "module.wifi_survey"}
    for path in _python_files():
        tree = _parse_python(path)
        item_path = relative_path(path)
        if item_path in allowed:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in markers:
                findings.append(Finding("REMOVED_FEATURE_ENTRY", item_path, node.lineno, f"active removed feature id {node.value}"))
    return findings


def runtime_path_findings() -> list[Finding]:
    findings: list[Finding] = []
    tracked = run_git("ls-files", "--", ".local", "data", "dist")
    if tracked.returncode != 0:
        findings.append(Finding("RUNTIME_PATH_GIT", ".", 0, tracked.stderr.strip()))
    else:
        for item_path in sorted(filter(None, tracked.stdout.splitlines())):
            findings.append(Finding("RUNTIME_PATH_TRACKED", item_path.replace("\\", "/"), 0, "runtime artifact is tracked"))
    for path in _python_files():
        tree = _parse_python(path)
        aliases = _aliases(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _qualified_name(node.func, aliases) in {"pathlib.Path.cwd", "Path.cwd", "os.getcwd"}:
                findings.append(Finding("RUNTIME_PATH_CWD", relative_path(path), node.lineno, "production path depends on current working directory"))
    required = load_json_yaml(CONFIG_ROOT / "required_readmes.yaml")
    if not isinstance(required, list) or any(not isinstance(item, str) for item in required):
        findings.append(Finding("DIRECTORY_README_CONFIG", "config/architecture/required_readmes.yaml", 0, "must contain an exact path list"))
    else:
        for item in required:
            item_path = item.replace("\\", "/")
            if any(char in item_path for char in "*?["):
                findings.append(Finding("DIRECTORY_README_CONFIG", "config/architecture/required_readmes.yaml", 0, f"wildcard path: {item_path}"))
            elif not (ROOT / item_path).is_file():
                findings.append(Finding("DIRECTORY_README_MISSING", item_path, 0, "required directory README is missing"))
    return findings


def _module_name(path: Path) -> str:
    relative = path.relative_to(ROOT / "src").with_suffix("")
    return ".".join(relative.parts[:-1] if relative.name == "__init__" else relative.parts)


def orphan_module_findings() -> list[Finding]:
    paths = list(_python_files())
    modules = {_module_name(path): path for path in paths}
    referenced: set[str] = set()
    excluded: set[str] = set()
    for module, path in modules.items():
        tree = _parse_python(path)
        relative = path.relative_to(PYTHON_ROOT)
        if (
            path.name == "__init__.py"
            or relative.parts[0] in {"models", "parsers", "backend"}
            or "handlers" in relative.parts
            or path.stem.endswith(("_router", "_worker"))
            or any(isinstance(node, ast.Name) and node.id == "HANDLERS" for node in ast.walk(tree))
            or any(isinstance(node, ast.If) and isinstance(node.test, ast.Compare) and "__name__" in ast.unparse(node.test) for node in ast.walk(tree))
        ):
            excluded.add(module)
        package = module if path.name == "__init__.py" else module.rsplit(".", 1)[0]
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names.extend(item.name for item in node.names)
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    parent_parts = package.split(".")
                    base_parts = parent_parts[: len(parent_parts) - node.level + 1]
                    if base:
                        base_parts.extend(base.split("."))
                    base = ".".join(base_parts)
                names.append(base)
                names.extend(f"{base}.{item.name}" for item in node.names if item.name != "*")
            for name in names:
                if name in modules:
                    referenced.add(name)
    findings: list[Finding] = []
    for module, path in sorted(modules.items()):
        relative = path.relative_to(PYTHON_ROOT)
        if relative.parts[0] != "services" or module in referenced or module in excluded:
            continue
        findings.append(Finding("ORPHAN_SERVICE_MODULE", relative_path(path), 0, f"no static production importer for {module}"))
    return findings


def migration_map_findings() -> list[Finding]:
    path = ROOT / "docs" / "architecture" / "MIGRATION_MATRIX.md"
    if not path.is_file():
        return [Finding("MIGRATION_MAP_MISSING", relative_path(path), 0, "migration matrix is missing")]
    text = path.read_text(encoding="utf-8")
    findings: list[Finding] = []
    for value in ("PURE_UI", "BUSINESS_MOVED", "ADAPTER_REPLACED", "DEAD_CODE", "FEATURE_REMOVED"):
        if f"`{value}`" not in text:
            findings.append(Finding("MIGRATION_MAP_CLASSIFICATION", relative_path(path), 0, f"missing {value}"))
    for value in ("MIGRATED", "REMOVED", "HIDDEN_PENDING_MIGRATION", "BLOCKED"):
        if f"`{value}`" not in text:
            findings.append(Finding("MIGRATION_MAP_STATUS", relative_path(path), 0, f"missing {value}"))
    history = run_git("ls-tree", "-r", "--name-only", "2d0bdbd5^", "--", "src/netconsole/ui")
    if history.returncode != 0:
        findings.append(Finding("MIGRATION_MAP_HISTORY", relative_path(path), 0, "cannot read Qt deletion baseline 2d0bdbd5^"))
    else:
        qt_files = history.stdout.splitlines()
        declared = re.search(r"153\s*个受跟踪 Qt 文件", text) is not None
        if len(qt_files) != 153 or not declared:
            findings.append(Finding("MIGRATION_MAP_HISTORY", relative_path(path), 0, f"Qt baseline expected=153 actual={len(qt_files)} declared={declared}"))
    return findings
