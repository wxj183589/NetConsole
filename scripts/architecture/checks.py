from __future__ import annotations

import ast
import fnmatch
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
STORAGE_REGISTRY_PATH = ROOT / "config" / "storage_registry.yaml"
HISTORY_MIGRATION_SOURCE = ROOT / "src" / "netconsole" / "services" / "history_legacy_migration.py"
STORAGE_REQUIRED_FIELDS = {
    "id",
    "relative_path",
    "owner",
    "data_type",
    "authority",
    "producer",
    "consumers",
    "retention_owner",
    "rebuildable",
    "site_package_policy",
    "backup_policy",
    "migration_policy",
    "schema_version",
    "allowed_data_classes",
    "forbidden_data_classes",
    "source_locations",
}
STORAGE_TABLE_RULE_REQUIRED_FIELDS = {
    "tables",
    "data_class",
    "authority",
    "producer",
    "consumers",
    "lifecycle_owner",
    "rebuildable",
    "source_locations",
}
SQLITE_LITERAL_PATTERN = re.compile(r"(?:^|[/\\])[^/\\]*(?:\.db|\.sqlite|\.sqlite3)(?:$|[-.])", re.IGNORECASE)
SQLITE_LITERAL_TOKEN_PATTERN = re.compile(
    r"(?P<database>[A-Za-z0-9_{}.*-]+\.(?:db|sqlite|sqlite3)(?:-[A-Za-z0-9_{}.*-]+)?)",
    re.IGNORECASE,
)
NON_PYTHON_STORAGE_SUFFIXES = frozenset({".ts", ".tsx", ".js", ".mjs", ".cjs", ".go"})
NON_PYTHON_STORAGE_MARKERS = re.compile(
    r"(?:"
    r"better-sqlite3|node:sqlite|modernc\.org/sqlite|github\.com/mattn/go-sqlite3|"
    r"database/sql|\bsqlite3\b|\bCREATE\s+(?:TABLE|INDEX|VIEW|TRIGGER)\b|"
    r"[A-Za-z0-9_{}.*-]+\.(?:db|sqlite|sqlite3)(?:[-.][A-Za-z0-9_{}.*-]+)?"
    r")",
    re.IGNORECASE,
)
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


def storage_registry_findings(
    registry_path: Path = STORAGE_REGISTRY_PATH,
    *,
    source_roots: Iterable[Path] | None = None,
    direct_sql_path: Path | None = None,
) -> list[Finding]:
    findings: list[Finding] = []
    try:
        registry = load_json_yaml(registry_path)
    except ValueError as exc:
        return [Finding("STORAGE_REGISTRY_INVALID", relative_path(registry_path), 0, str(exc))]
    registry_display = _storage_display_path(registry_path)
    if not isinstance(registry, dict):
        return [Finding("STORAGE_REGISTRY_INVALID", registry_display, 0, "registry must be an object")]
    classes = registry.get("data_classes")
    stores = registry.get("stores")
    if not isinstance(classes, list) or not classes or len(set(classes)) != len(classes):
        findings.append(
            Finding("STORAGE_REGISTRY_INVALID", registry_display, 0, "data_classes must be a unique non-empty list")
        )
        classes = []
    class_set = {str(value) for value in classes}
    if registry.get("unknown_policy") != "PROTECT" or "UNKNOWN" not in class_set:
        findings.append(
            Finding("STORAGE_UNKNOWN_POLICY", registry_display, 0, "UNKNOWN must be registered and default to PROTECT")
        )
    if not isinstance(stores, list) or not stores:
        findings.append(Finding("STORAGE_REGISTRY_INVALID", registry_display, 0, "stores must be a non-empty list"))
        return findings

    ids: set[str] = set()
    registered_locations: set[str] = set()
    registered_database_patterns: set[str] = set()
    registered_database_patterns_by_location: dict[str, set[str]] = {}
    for index, item in enumerate(stores, start=1):
        if not isinstance(item, dict):
            findings.append(Finding("STORAGE_REGISTRY_INVALID", registry_display, index, "store must be an object"))
            continue
        missing = sorted(STORAGE_REQUIRED_FIELDS - set(item))
        if missing:
            findings.append(
                Finding("STORAGE_REGISTRY_INVALID", registry_display, index, f"store is missing fields: {', '.join(missing)}")
            )
            continue
        store_id = str(item.get("id") or "").strip()
        if not store_id or store_id in ids:
            findings.append(Finding("STORAGE_REGISTRY_INVALID", registry_display, index, f"duplicate or empty id: {store_id}"))
        ids.add(store_id)
        for field in (
            "relative_path",
            "owner",
            "data_type",
            "authority",
            "retention_owner",
            "site_package_policy",
            "backup_policy",
            "migration_policy",
        ):
            if not str(item.get(field) or "").strip():
                findings.append(Finding("STORAGE_REGISTRY_INVALID", registry_display, index, f"{store_id}.{field} is empty"))
        if not isinstance(item.get("rebuildable"), bool):
            findings.append(Finding("STORAGE_REGISTRY_INVALID", registry_display, index, f"{store_id}.rebuildable must be boolean"))
        database_name_patterns = item.get("database_name_patterns")
        if database_name_patterns is not None and (
            not isinstance(database_name_patterns, list)
            or not database_name_patterns
            or not all(
                isinstance(pattern, str)
                and bool(pattern.strip())
                and "/" not in pattern.replace("\\", "/")
                for pattern in database_name_patterns
            )
        ):
            findings.append(
                Finding(
                    "STORAGE_REGISTRY_INVALID",
                    registry_display,
                    index,
                    f"{store_id}.database_name_patterns must contain filename-only patterns",
                )
            )
        for field in (
            "producer",
            "consumers",
            "allowed_data_classes",
            "forbidden_data_classes",
            "source_locations",
        ):
            value = item.get(field)
            if not isinstance(value, list) or (
                field in {"producer", "consumers", "allowed_data_classes", "source_locations"}
                and not value
            ):
                findings.append(Finding("STORAGE_REGISTRY_INVALID", registry_display, index, f"{store_id}.{field} must be a list"))
        allowed = {str(value) for value in item.get("allowed_data_classes", [])}
        forbidden = {str(value) for value in item.get("forbidden_data_classes", [])}
        if not allowed <= class_set or not forbidden <= class_set or allowed & forbidden:
            findings.append(Finding("STORAGE_CLASSIFICATION_INVALID", registry_display, index, f"{store_id} has invalid allowed/forbidden classes"))
        if str(item.get("data_type")) not in class_set:
            findings.append(Finding("STORAGE_CLASSIFICATION_INVALID", registry_display, index, f"{store_id} data_type is not registered"))
        if str(item.get("data_type")) == "UNKNOWN":
            active_producer = item.get("active_producer")
            if not isinstance(active_producer, bool):
                findings.append(
                    Finding(
                        "STORAGE_UNKNOWN_ACTIVE_PRODUCER",
                        registry_display,
                        index,
                        f"{store_id} UNKNOWN must declare boolean active_producer",
                    )
                )
            if (
                str(item.get("authority")) != "UNKNOWN_PROTECT"
                or item.get("rebuildable") is not False
                or str(item.get("retention_owner")) != "UNKNOWN_PROTECT"
            ):
                findings.append(Finding("STORAGE_UNKNOWN_POLICY", registry_display, index, f"{store_id} UNKNOWN must fail closed"))
        if str(item.get("data_type")) == "BACKUP_ROLLBACK" and "UNKNOWN" == str(item.get("retention_owner")):
            findings.append(Finding("STORAGE_BACKUP_OWNER", registry_display, index, f"{store_id} backup has no retention owner"))
        if str(item.get("data_type")) == "STAGING_TEMPORARY" and "cleanup" not in str(item.get("migration_policy")).casefold() and "recover" not in str(item.get("migration_policy")).casefold():
            findings.append(Finding("STORAGE_STAGING_LIFECYCLE", registry_display, index, f"{store_id} staging has no cleanup/recovery policy"))
        table_rules = item.get("table_rules", [])
        if not isinstance(table_rules, list):
            findings.append(
                Finding(
                    "STORAGE_REGISTRY_INVALID",
                    registry_display,
                    index,
                    f"{store_id}.table_rules must be a list",
                )
            )
            table_rules = []
        relative_path_value = str(item.get("relative_path") or "").casefold()
        store_database_patterns = _registry_database_patterns(
            str(item.get("relative_path") or ""),
            item.get("database_name_patterns"),
        )
        registered_database_patterns.update(store_database_patterns)
        requires_table_rules = (
            len(allowed) > 1
            and str(item.get("data_type"))
            not in {"STAGING_TEMPORARY", "BACKUP_ROLLBACK", "UNKNOWN"}
            and bool(re.search(r"\.(?:db|sqlite)(?:$|[.*-])", relative_path_value))
        )
        if requires_table_rules and not table_rules:
            findings.append(
                Finding(
                    "STORAGE_TABLE_OWNER_MISSING",
                    registry_display,
                    index,
                    f"{store_id} multi-class SQLite store requires exact table ownership rules",
                )
            )
        seen_rule_tables: set[str] = set()
        for rule_index, rule in enumerate(table_rules, start=1):
            if not isinstance(rule, dict):
                findings.append(
                    Finding(
                        "STORAGE_REGISTRY_INVALID",
                        registry_display,
                        index,
                        f"{store_id}.table_rules[{rule_index}] must be an object",
                    )
                )
                continue
            missing_rule = sorted(STORAGE_TABLE_RULE_REQUIRED_FIELDS - set(rule))
            if missing_rule:
                findings.append(
                    Finding(
                        "STORAGE_TABLE_OWNER_MISSING",
                        registry_display,
                        index,
                        f"{store_id}.table_rules[{rule_index}] is missing: {', '.join(missing_rule)}",
                    )
                )
                continue
            tables = rule.get("tables")
            if not isinstance(tables, list) or not tables or not all(
                isinstance(table, str)
                and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table)
                for table in tables
            ):
                findings.append(
                    Finding(
                        "STORAGE_TABLE_OWNER_MISSING",
                        registry_display,
                        index,
                        f"{store_id}.table_rules[{rule_index}] has no exact table names",
                    )
                )
                continue
            normalized_tables = {str(table).casefold() for table in tables}
            if seen_rule_tables & normalized_tables:
                findings.append(
                    Finding(
                        "STORAGE_TABLE_OWNER_AMBIGUOUS",
                        registry_display,
                        index,
                        f"{store_id} declares one table in multiple lifecycle rules",
                    )
                )
            seen_rule_tables.update(normalized_tables)
            if str(rule.get("data_class")) not in allowed:
                findings.append(
                    Finding(
                        "STORAGE_CLASSIFICATION_INVALID",
                        registry_display,
                        index,
                        f"{store_id}.table_rules[{rule_index}] class is not allowed",
                    )
                )
            for field in ("producer", "consumers", "source_locations"):
                values = rule.get(field)
                if not isinstance(values, list) or not values or not all(
                    isinstance(value, str) and value for value in values
                ):
                    findings.append(
                        Finding(
                            "STORAGE_TABLE_OWNER_MISSING",
                            registry_display,
                            index,
                            f"{store_id}.table_rules[{rule_index}].{field} must be a non-empty list",
                        )
                    )
            if not str(rule.get("authority") or "").strip() or not str(
                rule.get("lifecycle_owner") or ""
            ).strip():
                findings.append(
                    Finding(
                        "STORAGE_TABLE_OWNER_MISSING",
                        registry_display,
                        index,
                        f"{store_id}.table_rules[{rule_index}] lacks authority or lifecycle owner",
                    )
                )
            if not isinstance(rule.get("rebuildable"), bool):
                findings.append(
                    Finding(
                        "STORAGE_REGISTRY_INVALID",
                        registry_display,
                        index,
                        f"{store_id}.table_rules[{rule_index}].rebuildable must be boolean",
                    )
                )
        for location in item.get("source_locations", []):
            normalized = str(location).replace("\\", "/").strip("/")
            registered_locations.add(normalized)
            registered_database_patterns_by_location.setdefault(normalized, set()).update(
                store_database_patterns
            )
            if not (ROOT / normalized).exists():
                findings.append(Finding("STORAGE_SOURCE_MISSING", registry_display, index, f"{store_id} source location does not exist: {normalized}"))
        for rule in item.get("table_rules", []):
            if not isinstance(rule, dict):
                continue
            for location in rule.get("source_locations", []):
                normalized = str(location).replace("\\", "/").strip("/")
                registered_locations.add(normalized)
                registered_database_patterns_by_location.setdefault(normalized, set()).update(
                    store_database_patterns
                )
                if not (ROOT / normalized).exists():
                    findings.append(
                        Finding(
                            "STORAGE_SOURCE_MISSING",
                            registry_display,
                            index,
                            f"{store_id} table source location does not exist: {normalized}",
                        )
                    )

    for location in registry.get("infrastructure_locations", []):
        normalized = str(location).replace("\\", "/").strip("/")
        registered_locations.add(normalized)
        registered_database_patterns_by_location.setdefault(normalized, set()).update(
            registered_database_patterns
        )
        if not (ROOT / normalized).exists():
            findings.append(Finding("STORAGE_SOURCE_MISSING", registry_display, 0, f"infrastructure location does not exist: {normalized}"))

    inventory_path = direct_sql_path or CONFIG_ROOT / "direct_sql_access.yaml"
    try:
        direct_inventory = load_json_yaml(inventory_path)
    except ValueError as exc:
        findings.append(Finding("STORAGE_REGISTRY_INVALID", relative_path(inventory_path), 0, str(exc)))
        direct_inventory = []
    direct_paths: set[str] = set()
    direct_classifications: dict[str, str] = {}
    if isinstance(direct_inventory, list):
        for item in direct_inventory:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or "").replace("\\", "/")
            direct_paths.add(path)
            direct_classifications[path] = str(item.get("classification") or "")
            if str(item.get("classification")) == "TEST_ONLY":
                continue
            owner = str(item.get("owner") or "")
            registered = any(
                path == location or path.startswith(f"{location}/")
                for location in registered_locations
            )
            if not registered:
                findings.append(
                    Finding(
                        "UNREGISTERED_STORAGE",
                        path,
                        0,
                        f"database source has no exact storage registry declaration for owner '{owner}'",
                    )
                )

    roots = tuple(
        source_roots
        or (
            ROOT / "src" / "netconsole",
            ROOT / "scripts" / "maintenance",
            ROOT / "scripts" / "build",
            ROOT / "apps" / "agent",
            ROOT / "apps" / "desktop_electron" / "src",
            ROOT / "apps" / "desktop_renderer" / "src",
        )
    )
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            try:
                tree = _parse_python(path)
            except (OSError, SyntaxError) as exc:
                display = _storage_display_path(path)
                findings.append(Finding("STORAGE_SCAN_ERROR", display, 0, str(exc)))
                continue
            aliases = _aliases(tree)
            candidate_lines: list[tuple[int, str]] = []
            database_literals: list[tuple[int, str]] = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and _qualified_name(node.func, aliases) in SQL_CONNECT_NAMES:
                    candidate_lines.append((int(getattr(node, "lineno", 0)), _qualified_name(node.func, aliases)))
                elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                    value = node.value.strip()
                    if SQLITE_LITERAL_PATTERN.search(value) or "CREATE TABLE" in value.upper():
                        candidate_lines.append((int(getattr(node, "lineno", 0)), value[:120]))
                    database_literals.extend(
                        (int(getattr(node, "lineno", 0)), match.group("database"))
                        for match in SQLITE_LITERAL_TOKEN_PATTERN.finditer(value)
                    )
            if not candidate_lines:
                continue
            display = _storage_display_path(path)
            source_database_patterns = _registered_database_patterns_for_source(
                display,
                registered_database_patterns_by_location,
            )
            registered = display in direct_paths or any(
                display == location or display.startswith(f"{location}/")
                for location in registered_locations
            )
            if not registered:
                line, database = min(candidate_lines)
                findings.append(
                    Finding(
                        "UNREGISTERED_STORAGE",
                        display,
                        line,
                        f"UNREGISTERED STORAGE database={database!r}; source location has no storage registry declaration",
                    )
                )
                continue
            if direct_classifications.get(display) != "TEST_ONLY":
                findings.extend(
                    _unregistered_database_literal_findings(
                        display,
                        database_literals,
                        registered_database_patterns=source_database_patterns,
                    )
                )
        for path in sorted(
            candidate
            for candidate in root.rglob("*")
            if candidate.is_file()
            and candidate.suffix.casefold() in NON_PYTHON_STORAGE_SUFFIXES
            and not _is_non_python_test_source(candidate)
        ):
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeError) as exc:
                findings.append(
                    Finding("STORAGE_SCAN_ERROR", _storage_display_path(path), 0, str(exc))
                )
                continue
            candidate_lines = [
                (line_number, line.strip()[:120])
                for line_number, line in enumerate(lines, start=1)
                if NON_PYTHON_STORAGE_MARKERS.search(line)
            ]
            if not candidate_lines:
                continue
            database_literals = [
                (line_number, match.group("database"))
                for line_number, line in enumerate(lines, start=1)
                for match in SQLITE_LITERAL_TOKEN_PATTERN.finditer(line)
            ]
            display = _storage_display_path(path)
            source_database_patterns = _registered_database_patterns_for_source(
                display,
                registered_database_patterns_by_location,
            )
            registered = display in direct_paths or any(
                display == location or display.startswith(f"{location}/")
                for location in registered_locations
            )
            if not registered:
                line, database = min(candidate_lines)
                findings.append(
                    Finding(
                        "UNREGISTERED_STORAGE",
                        display,
                        line,
                        f"UNREGISTERED STORAGE database={database!r}; non-Python source location has no storage registry declaration",
                    )
                )
                continue
            if direct_classifications.get(display) != "TEST_ONLY":
                findings.extend(
                    _unregistered_database_literal_findings(
                        display,
                        database_literals,
                        registered_database_patterns=source_database_patterns,
                    )
                )
    return findings


def history_migration_contract_findings(
    registry_path: Path = STORAGE_REGISTRY_PATH,
    *,
    migration_source: Path = HISTORY_MIGRATION_SOURCE,
) -> list[Finding]:
    """Require an explicit migration contract for every registry-owned source."""

    try:
        registry = load_json_yaml(registry_path)
        tree = ast.parse(migration_source.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError) as exc:
        return [
            Finding(
                "HISTORY_MIGRATION_CONTRACT_INVALID",
                relative_path(registry_path),
                0,
                str(exc),
            )
        ]
    supported: set[str] = set()
    unsupported: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        names = {
            target.id
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        if isinstance(node.value, ast.Dict):
            values = {
                str(key.value)
                for key in node.value.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            }
            if "SUPPORTED_SPECS" in names:
                supported = values
            if "UNSUPPORTED_TABLES" in names:
                unsupported = values
        elif isinstance(node.value, (ast.Set, ast.Tuple, ast.List)):
            values = {
                str(item.value)
                for item in node.value.elts
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            }
            if "UNSUPPORTED_TABLES" in names:
                unsupported = values
    if not supported:
        return [
            Finding(
                "HISTORY_MIGRATION_CONTRACT_INVALID",
                relative_path(migration_source),
                0,
                "SUPPORTED_SPECS is missing or not an explicit mapping",
            )
        ]
    findings: list[Finding] = []
    stores = registry.get("stores", []) if isinstance(registry, dict) else []
    for store_index, store in enumerate(stores, start=1):
        if not isinstance(store, dict):
            continue
        for rule in store.get("table_rules", []):
            if not isinstance(rule, dict):
                continue
            if (
                rule.get("data_class") != "HISTORICAL_RAW_FACT"
                or rule.get("lifecycle_owner") != "HistoryLegacyMigrationService"
            ):
                continue
            for table in rule.get("tables", []):
                name = str(table)
                if name not in supported and name not in unsupported:
                    findings.append(
                        Finding(
                            "HISTORY_MIGRATION_CONTRACT_MISSING",
                            relative_path(registry_path),
                            store_index,
                            f"{name} is owned by HistoryLegacyMigrationService but has no SUPPORTED_SPECS contract",
                        )
                    )
    return findings


def production_database_boundary_findings(
    source: Path = ROOT / "src" / "netconsole" / "services" / "production_database_maintenance.py",
    cli_source: Path = ROOT / "scripts" / "maintenance" / "production_database_maintenance.py",
) -> list[Finding]:
    """Keep production destructive components separate from development guards."""

    findings: list[Finding] = []
    try:
        tree = ast.parse(source.read_text(encoding="utf-8"))
        cli_text = cli_source.read_text(encoding="utf-8")
    except (OSError, SyntaxError) as exc:
        return [Finding("PRODUCTION_BOUNDARY_INVALID", relative_path(source), 0, str(exc))]
    if "--force-executable" in cli_text or "--ignore-blocker" in cli_text:
        findings.append(
            Finding(
                "PRODUCTION_MANIFEST_BYPASS",
                relative_path(cli_source),
                0,
                "production maintenance CLI must not expose force/ignore manifest bypasses",
            )
        )
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or not node.name.startswith("Production"):
            continue
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            function_name = child.func.id if isinstance(child.func, ast.Name) else ""
            if function_name == "assert_development_path":
                findings.append(
                    Finding(
                        "PRODUCTION_DEVELOPMENT_GUARD_BYPASS",
                        relative_path(source),
                        int(getattr(child, "lineno", 0)),
                        f"{node.name} directly calls assert_development_path",
                    )
                )
    return findings


def _registry_database_patterns(
    relative_path_value: str,
    explicit_patterns: object = None,
) -> set[str]:
    patterns: set[str] = set()
    for alternative in relative_path_value.replace("\\", "/").split("|"):
        filename = alternative.rstrip("/").rsplit("/", 1)[-1].casefold()
        if not re.search(r"\.(?:db|sqlite|sqlite3)(?:$|[-.*])", filename):
            continue
        normalized = re.sub(r"\{[^{}]+\}", "*", filename)
        normalized = normalized.replace("yyyy-mm[-nnnn]", "*")
        patterns.add(normalized)
    if isinstance(explicit_patterns, list):
        patterns.update(
            str(pattern).replace("\\", "/").rsplit("/", 1)[-1].casefold()
            for pattern in explicit_patterns
            if str(pattern).strip()
        )
    return patterns


def _registered_database_patterns_for_source(
    display: str,
    patterns_by_location: dict[str, set[str]],
) -> set[str]:
    patterns: set[str] = set()
    for location, registered_patterns in patterns_by_location.items():
        if display == location or display.startswith(f"{location}/"):
            patterns.update(registered_patterns)
    return patterns


def _unregistered_database_literal_findings(
    display: str,
    literals: Iterable[tuple[int, str]],
    *,
    registered_database_patterns: set[str],
) -> list[Finding]:
    findings: list[Finding] = []
    seen: set[tuple[int, str]] = set()
    for line, literal in literals:
        database = literal.replace("\\", "/").rsplit("/", 1)[-1].casefold()
        if database.startswith("*."):
            continue
        key = (line, database)
        if key in seen:
            continue
        seen.add(key)
        if any(fnmatch.fnmatchcase(database, pattern) for pattern in registered_database_patterns):
            continue
        findings.append(
            Finding(
                "UNREGISTERED_STORAGE",
                display,
                line,
                f"UNREGISTERED STORAGE database={literal!r}; registered source has no matching physical database declaration",
            )
        )
    return findings


def _is_non_python_test_source(path: Path) -> bool:
    name = path.name.casefold()
    return (
        name.endswith("_test.go")
        or ".test." in name
        or ".spec." in name
        or any(part.casefold() in {"node_modules", "dist", "coverage"} for part in path.parts)
    )


def _storage_display_path(path: Path) -> str:
    try:
        return relative_path(path)
    except ValueError:
        return path.as_posix()


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


def product_architecture_findings() -> list[Finding]:
    path = CONFIG_ROOT / "product_architecture.json"
    if not path.is_file():
        return [Finding("PRODUCT_ARCHITECTURE_MISSING", relative_path(path), 0, "product architecture contract is missing")]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [Finding("PRODUCT_ARCHITECTURE_CONFIG", relative_path(path), 0, str(exc))]
    findings: list[Finding] = []
    if not isinstance(payload, dict):
        return [Finding("PRODUCT_ARCHITECTURE_CONFIG", relative_path(path), 0, "product architecture contract must be an object")]
    expected_sources = {
        "version": "src/netconsole/core/version.py",
        "features": "src/netconsole/core/feature_registry.py",
        "data_root": "src/netconsole/core/paths.py",
    }
    if payload.get("product_model") != "ELECTRON_DESKTOP_ONLY":
        findings.append(Finding("PRODUCT_ARCHITECTURE_MODEL", relative_path(path), 0, "product model must remain Electron Desktop Only"))
    if payload.get("maintenance_state") != "LONG_TERM_MAINTENANCE":
        findings.append(Finding("PRODUCT_ARCHITECTURE_STATE", relative_path(path), 0, "repository must use the long-term maintenance baseline"))
    if payload.get("authoritative_sources") != expected_sources:
        findings.append(Finding("PRODUCT_ARCHITECTURE_SOURCES", relative_path(path), 0, "version, feature, or DataRoot source is not authoritative"))
    components = payload.get("components")
    expected_components = {"electron-host", "desktop-renderer", "python-backend", "windows-agent"}
    if not isinstance(components, list) or {item.get("id") for item in components if isinstance(item, dict)} != expected_components:
        findings.append(Finding("PRODUCT_ARCHITECTURE_COMPONENTS", relative_path(path), 0, "runtime component set is incomplete"))
    else:
        for item in components:
            required_paths = item.get("required_paths")
            if not isinstance(required_paths, list) or not required_paths:
                findings.append(Finding("PRODUCT_ARCHITECTURE_COMPONENTS", relative_path(path), 0, f"{item['id']} has no required paths"))
                continue
            for required_path in required_paths:
                if not isinstance(required_path, str) or not (ROOT / required_path).is_file():
                    findings.append(Finding("PRODUCT_ARCHITECTURE_PATH", str(required_path), 0, f"missing required path for {item['id']}"))
    history = payload.get("historical_migration")
    archive = "docs/archive/migrations/qt-to-electron/MIGRATION_MATRIX.md"
    if history != {"status": "CLOSED", "archive": archive} or not (ROOT / archive).is_file():
        findings.append(Finding("PRODUCT_ARCHITECTURE_HISTORY", relative_path(path), 0, "closed migration history must resolve to the archive"))
    return findings
