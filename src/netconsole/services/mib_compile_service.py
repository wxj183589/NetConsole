from __future__ import annotations

import re
from pathlib import Path

from netconsole.models.mib_models import MibCompileResult, MibObjectRecord


MODULE_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9-]*)\s+DEFINITIONS\s*::=\s*BEGIN\b", re.MULTILINE)
IMPORTS_RE = re.compile(r"\bIMPORTS\b(?P<body>.*?)\s*;", re.IGNORECASE | re.DOTALL)
FROM_RE = re.compile(r"\bFROM\s+([A-Za-z][A-Za-z0-9-]*)", re.IGNORECASE)
OBJECT_TYPE_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9-]*)\s+OBJECT-TYPE\b(?P<body>.*?::=\s*\{\s*(?:[A-Za-z][A-Za-z0-9-]*|[0-9.]+)\s+\d+\s*\})", re.MULTILINE | re.DOTALL)
OID_ASSIGN_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9-]*)\s+(?:OBJECT IDENTIFIER\s+)?::=\s*\{\s*([A-Za-z][A-Za-z0-9-]*|[0-9.]+)\s+(\d+)\s*\}", re.MULTILINE)
SYNTAX_RE = re.compile(r"\bSYNTAX\s+([^\n]+)")
MAX_ACCESS_RE = re.compile(r"\b(?:MAX-ACCESS|ACCESS)\s+([^\n]+)")
STATUS_RE = re.compile(r"\bSTATUS\s+([^\n]+)")
DESC_RE = re.compile(r'\bDESCRIPTION\s+"(.*?)"', re.DOTALL)
INDEX_RE = re.compile(r"\bINDEX\s+\{(.*?)\}", re.DOTALL)
NOTIFICATION_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9-]*)\s+NOTIFICATION-TYPE\b(?P<body>.*?::=\s*\{\s*(?:[A-Za-z][A-Za-z0-9-]*|[0-9.]+)\s+\d+\s*\})", re.MULTILINE | re.DOTALL)
TRAP_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9-]*)\s+TRAP-TYPE\b(?P<body>.*?::=\s*\{\s*(?:[A-Za-z][A-Za-z0-9-]*|[0-9.]+)\s+\d+\s*\})", re.MULTILINE | re.DOTALL)


BASE_OIDS = {
    "iso": "1",
    "org": "1.3",
    "dod": "1.3.6",
    "internet": "1.3.6.1",
    "directory": "1.3.6.1.1",
    "mgmt": "1.3.6.1.2",
    "mib-2": "1.3.6.1.2.1",
    "transmission": "1.3.6.1.2.1.10",
    "experimental": "1.3.6.1.3",
    "private": "1.3.6.1.4",
    "enterprises": "1.3.6.1.4.1",
    "hh3c": "1.3.6.1.4.1.25506",
    "hh3cDot11": "1.3.6.1.4.1.25506.2.75",
    "hh3cDot11sMesh": "1.3.6.1.4.1.25506.2.75.11",
    "snmpModules": "1.3.6.1.6.3",
}


class MibCompileService:
    def compile_file(self, path: Path, known_modules: set[str] | None = None, oid_map: dict[str, str] | None = None) -> MibCompileResult:
        known_modules = set(known_modules or ())
        try:
            text = _read_text(path)
        except Exception as exc:
            return MibCompileResult(module_name=path.stem, status="failed", error_message=f"读取 MIB 文件失败：{exc}")
        module_name = self.identify_module(text) or path.stem
        imports = self.parse_imports(text)
        missing = sorted(dep for dep in imports if dep not in known_modules and dep != module_name)
        if missing:
            error = f"缺少依赖模块：{', '.join(missing)}"
            return MibCompileResult(module_name=module_name, status="missing_dependencies", imports=imports, missing_dependencies=missing, error_message=error)
        try:
            objects = self.parse_objects(text, module_name, oid_map=oid_map)
        except Exception as exc:
            return MibCompileResult(module_name=module_name, status="failed", imports=imports, missing_dependencies=missing, error_message=f"MIB 索引失败：{exc}")
        status = "compiled"
        error = ""
        return MibCompileResult(module_name=module_name, status=status, objects=objects, imports=imports, missing_dependencies=missing, error_message=error)

    def identify_module(self, text: str) -> str:
        text = _strip_comments(text)
        match = MODULE_RE.search(text)
        return match.group(1) if match else ""

    def parse_imports(self, text: str) -> list[str]:
        text = _strip_comments(text)
        match = IMPORTS_RE.search(text)
        if not match:
            return []
        return sorted(set(FROM_RE.findall(match.group("body"))))

    def build_oid_map(self, paths: list[Path]) -> dict[str, str]:
        assignments: list[tuple[str, str, str]] = []
        for path in paths:
            try:
                text = _read_text(path)
            except Exception:
                continue
            assignments.extend(OID_ASSIGN_RE.findall(text))
        oid_map = dict(BASE_OIDS)
        changed = True
        while changed:
            changed = False
            for name, parent, number in assignments:
                parent_oid = oid_map.get(parent, parent if parent and parent[0].isdigit() else "")
                if parent_oid and name not in oid_map:
                    oid_map[name] = f"{parent_oid}.{number}"
                    changed = True
        return oid_map

    def parse_objects(self, text: str, module_name: str, oid_map: dict[str, str] | None = None) -> list[MibObjectRecord]:
        text = _strip_comments(text)
        oid_map = {**BASE_OIDS, **(oid_map or {})}
        objects: list[MibObjectRecord] = []
        for name, parent, number in OID_ASSIGN_RE.findall(text):
            parent_oid = oid_map.get(parent, parent if parent and parent[0].isdigit() else "")
            if not parent_oid:
                continue
            oid = f"{parent_oid}.{number}"
            oid_map[name] = oid
            objects.append(
                MibObjectRecord(
                    name=name,
                    oid=oid,
                    parent_oid=parent_oid,
                    syntax="OBJECT IDENTIFIER",
                    access="not-accessible",
                    status="current",
                    description="",
                )
            )
        for match in OBJECT_TYPE_RE.finditer(text):
            name = match.group(1)
            body = match.group("body")
            oid = oid_map.get(name) or _oid_from_body(body, oid_map)
            if not oid:
                continue
            oid_map[name] = oid
            syntax = _first(SYNTAX_RE, body)
            access = _first(MAX_ACCESS_RE, body)
            status = _first(STATUS_RE, body)
            description = _description(body)
            index_def = _first(INDEX_RE, body)
            lower_name = name.lower()
            is_table = lower_name.endswith("table") or "SEQUENCE OF" in syntax
            is_entry = lower_name.endswith("entry")
            is_scalar = access.lower() in {"read-only", "read-write", "read-create"} and not is_table and not is_entry and not index_def
            objects.append(
                MibObjectRecord(
                    name=name,
                    oid=oid,
                    parent_oid=".".join(oid.split(".")[:-1]),
                    syntax=syntax,
                    access=access,
                    status=status,
                    description=description,
                    is_scalar=1 if is_scalar else 0,
                    is_table=1 if is_table else 0,
                    is_table_entry=1 if is_entry else 0,
                    is_column=1 if (not is_scalar and not is_table and not is_entry) else 0,
                    table_name=name if is_table else "",
                    entry_name=name if is_entry else "",
                    index_def=index_def,
                    enum_map_json=_enum_map_from_syntax(syntax),
                )
            )
        for regex, is_trap, is_notification in ((NOTIFICATION_RE, 0, 1), (TRAP_RE, 1, 0)):
            for match in regex.finditer(text):
                name = match.group(1)
                body = match.group("body")
                oid = oid_map.get(name) or _oid_from_body(body, oid_map)
                if not oid:
                    continue
                objects.append(
                    MibObjectRecord(
                        name=name,
                        oid=oid,
                        parent_oid=".".join(oid.split(".")[:-1]),
                        syntax="NOTIFICATION-TYPE" if is_notification else "TRAP-TYPE",
                        access="not-accessible",
                        status=_first(STATUS_RE, body),
                        description=_description(body),
                        is_trap=is_trap,
                        is_notification=is_notification,
                    )
                )
        return _dedupe_objects(objects)


def _read_text(path: Path) -> str:
    return read_text_with_fallback(Path(path))


def _strip_comments(text: str) -> str:
    return "\n".join(re.sub(r"--.*$", "", line) for line in text.splitlines())


def _first(regex: re.Pattern[str], text: str) -> str:
    match = regex.search(text)
    if not match:
        return ""
    return " ".join(match.group(1).replace("\n", " ").split())


def _description(text: str) -> str:
    match = DESC_RE.search(text)
    if not match:
        return ""
    return " ".join(match.group(1).replace("\n", " ").split())


def _oid_from_body(body: str, oid_map: dict[str, str]) -> str:
    match = re.search(r"::=\s*\{\s*([A-Za-z][A-Za-z0-9-]*|[0-9.]+)\s+(\d+)\s*\}", body)
    if not match:
        return ""
    parent, number = match.groups()
    parent_oid = oid_map.get(parent, parent if parent[0].isdigit() else "")
    return f"{parent_oid}.{number}" if parent_oid else ""


def _enum_map_from_syntax(syntax: str) -> str:
    matches = re.findall(r"([A-Za-z][A-Za-z0-9-]*)\s*\((\d+)\)", syntax)
    if not matches:
        return "{}"
    import json

    return json.dumps({number: name for name, number in matches}, ensure_ascii=False)


def _dedupe_objects(objects: list[MibObjectRecord]) -> list[MibObjectRecord]:
    seen: set[tuple[str, str]] = set()
    result: list[MibObjectRecord] = []
    for item in objects:
        key = (item.name, item.oid)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result
from netconsole.utils.text_encoding import read_text_with_fallback
