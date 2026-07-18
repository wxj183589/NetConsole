from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_SOURCE = Path("apps/web/src")
BASELINE_PATH = Path("config/architecture/table-layout-baseline.json")
EXCEPTIONS_PATH = Path("config/architecture/table-layout-exceptions.yaml")
INVENTORY_PATH = Path("docs/ui/TABLE_INVENTORY.md")

DIRECT_TABLE_RE = re.compile(r"<el-table(?!-)(?P<attrs>[^>]*)>", re.IGNORECASE | re.DOTALL)
DATA_TABLE_RE = re.compile(r"<NcDataTable\b(?P<attrs>[^>]*)>", re.IGNORECASE | re.DOTALL)
STATIC_ATTRIBUTE_TEMPLATE = r"(?:^|\s){name}\s*=\s*['\"]([^'\"]+)['\"]"


@dataclass(frozen=True)
class TableUse:
    path: str
    line: int
    ordinal: int
    component: str
    table_id: str
    route_key: str
    columns_bound: bool

    @property
    def baseline_key(self) -> str:
        return f"{self.path}#{self.ordinal}"


def _line_number(source: str, offset: int) -> int:
    return source.count("\n", 0, offset) + 1


def _static_attribute(attrs: str, name: str) -> str:
    match = re.search(STATIC_ATTRIBUTE_TEMPLATE.format(name=re.escape(name)), attrs)
    return match.group(1).strip() if match else ""


def _legacy_table_id(path: str, ordinal: int) -> str:
    stem = Path(path).with_suffix("").as_posix().replace("apps/web/src/", "")
    return f"legacy:{stem.replace('/', ':')}:{ordinal}"


def _legacy_route(path: str) -> str:
    parts = Path(path).parts
    try:
        index = parts.index("views")
    except ValueError:
        return f"embedded:{Path(path).stem}"
    return "/" + parts[index + 1].replace("-management", "")


def scan_tables(root: Path = PROJECT_ROOT) -> tuple[list[TableUse], list[TableUse]]:
    direct: list[TableUse] = []
    managed: list[TableUse] = []
    source_root = root / WEB_SOURCE
    for file_path in sorted(source_root.rglob("*.vue")):
        relative = file_path.relative_to(root).as_posix()
        if relative.startswith("apps/web/src/components/table/") or relative.endswith("/NcTable.vue"):
            continue
        source = file_path.read_text(encoding="utf-8")
        for ordinal, match in enumerate(DIRECT_TABLE_RE.finditer(source), start=1):
            direct.append(
                TableUse(
                    path=relative,
                    line=_line_number(source, match.start()),
                    ordinal=ordinal,
                    component="el-table",
                    table_id=_legacy_table_id(relative, ordinal),
                    route_key=_legacy_route(relative),
                    columns_bound=False,
                )
            )
        for ordinal, match in enumerate(DATA_TABLE_RE.finditer(source), start=1):
            attrs = match.group("attrs")
            managed.append(
                TableUse(
                    path=relative,
                    line=_line_number(source, match.start()),
                    ordinal=ordinal,
                    component="NcDataTable",
                    table_id=_static_attribute(attrs, "table-id"),
                    route_key=_static_attribute(attrs, "route-key"),
                    columns_bound=bool(re.search(r"(?:^|\s)(?::|v-bind:)columns\s*=", attrs)),
                )
            )
    return direct, managed


def load_baseline(root: Path = PROJECT_ROOT) -> dict[str, dict[str, object]]:
    path = root / BASELINE_PATH
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {str(item["key"]): item for item in payload.get("direct_el_tables", [])}


def write_baseline(root: Path = PROJECT_ROOT) -> None:
    direct, _ = scan_tables(root)
    payload = {
        "version": 1,
        "description": "阶段 1 建立时已有的直接 el-table 基线；逐域迁移后必须删除对应项。",
        "direct_el_tables": [
            {
                "key": table.baseline_key,
                "path": table.path,
                "ordinal": table.ordinal,
                "table_id": table.table_id,
                "status": "BLOCKED",
            }
            for table in direct
        ],
    }
    path = root / BASELINE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _parse_exception_entries(source: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for raw_line in source.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line == "exceptions:":
            continue
        if line.startswith("- "):
            if current:
                entries.append(current)
            current = {}
            line = line[2:].strip()
        if current is None or ":" not in line:
            continue
        key, value = line.split(":", 1)
        current[key.strip()] = value.strip().strip("'\"")
    if current:
        entries.append(current)
    return entries


def validate_exceptions(root: Path = PROJECT_ROOT) -> list[str]:
    path = root / EXCEPTIONS_PATH
    if not path.exists():
        return [f"缺少表格布局例外文件: {EXCEPTIONS_PATH.as_posix()}"]
    required = {"table_id", "column_key", "reason", "fixed_width", "test", "expires_at"}
    errors: list[str] = []
    for index, entry in enumerate(_parse_exception_entries(path.read_text(encoding="utf-8")), start=1):
        missing = required - entry.keys()
        if missing:
            errors.append(f"例外 #{index} 缺少字段: {', '.join(sorted(missing))}")
            continue
        if "*" in entry["table_id"] or "*" in entry["column_key"]:
            errors.append(f"例外 #{index} 禁止通配 table_id 或 column_key")
        try:
            expires_at = date.fromisoformat(entry["expires_at"])
        except ValueError:
            errors.append(f"例外 #{index} expires_at 不是 ISO 日期")
        else:
            if expires_at < date.today():
                errors.append(f"例外 #{index} 已过期: {entry['expires_at']}")
    return errors


def check_table_contracts(root: Path = PROJECT_ROOT) -> list[str]:
    direct, managed = scan_tables(root)
    baseline = load_baseline(root)
    current_keys = {table.baseline_key for table in direct}
    baseline_keys = set(baseline)
    errors = [
        f"新增直接 el-table，必须改用 NcDataTable: {table.path}:{table.line}"
        for table in direct
        if table.baseline_key not in baseline
    ]
    for stale_key in sorted(baseline_keys - current_keys):
        errors.append(f"旧表基线已失效，请在迁移提交中删除该项: {stale_key}")
    for table in managed:
        if not table.table_id:
            errors.append(f"NcDataTable 缺少静态 table-id: {table.path}:{table.line}")
        if not table.route_key:
            errors.append(f"NcDataTable 缺少静态 route-key: {table.path}:{table.line}")
        if not table.columns_bound:
            errors.append(f"NcDataTable 必须绑定统一 columns 列定义: {table.path}:{table.line}")
    errors.extend(validate_exceptions(root))
    return errors


def migrated_source_files(root: Path = PROJECT_ROOT) -> set[Path]:
    _, managed = scan_tables(root)
    return {root / table.path for table in managed}


def check_column_definitions(root: Path = PROJECT_ROOT) -> list[str]:
    errors: list[str] = []
    for path in sorted(migrated_source_files(root)):
        source = path.read_text(encoding="utf-8")
        relative = path.relative_to(root).as_posix()
        for pattern, message in (
            (r"<el-table-column\b", "迁移文件仍直接声明 el-table-column"),
            (r"\bheader-align\s*=", "迁移文件仍散写 header-align"),
            (r"\bmeasureText\s*\(", "迁移文件仍自行实现 measureText"),
        ):
            if re.search(pattern, source):
                errors.append(f"{message}: {relative}")
    return errors


def check_table_alignment(root: Path = PROJECT_ROOT) -> list[str]:
    errors: list[str] = []
    for path in sorted(migrated_source_files(root)):
        source = path.read_text(encoding="utf-8")
        relative = path.relative_to(root).as_posix()
        if re.search(r"\.el-table[^{}]*\{[^}]*\btext-align\s*:", source, re.DOTALL):
            errors.append(f"迁移文件不得用 CSS 覆盖表格对齐: {relative}")
    return errors


def check_hardcoded_column_widths(root: Path = PROJECT_ROOT) -> list[str]:
    errors: list[str] = []
    for path in sorted(migrated_source_files(root)):
        source = path.read_text(encoding="utf-8")
        relative = path.relative_to(root).as_posix()
        if re.search(r"<el-table-column\b[^>]*\b(?:min-)?width\s*=", source, re.DOTALL):
            errors.append(f"迁移文件不得散写 Element Plus 列宽: {relative}")
    return errors


def inventory_markdown(root: Path = PROJECT_ROOT) -> str:
    direct, managed = scan_tables(root)
    rows = [
        "# 表格与字段展示清单",
        "",
        "本清单由 `scripts/ui/export_table_inventory.py` 生成。`BLOCKED` 表示已登记但尚未迁移的旧表，不表示功能故障。",
        "",
        "| 路由 | 页面 | 表格 ID | 当前组件 | 表头/内容居中 | 自动列宽 | 表头最小宽度 | 整改状态 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for table in [*managed, *direct]:
        compliant = table.component == "NcDataTable"
        rows.append(
            f"| `{table.route_key or '—'}` | `{table.path}:{table.line}` | `{table.table_id or '—'}` "
            f"| `{table.component}` | {'是' if compliant else '否'} | {'是' if compliant else '否'} "
            f"| {'是' if compliant else '否'} | {'MIGRATED' if compliant else 'BLOCKED'} |"
        )
    rows.extend(("", f"总计：{len(managed)} 张已迁移，{len(direct)} 张待迁移。", ""))
    return "\n".join(rows)


def write_inventory(root: Path = PROJECT_ROOT) -> None:
    path = root / INVENTORY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(inventory_markdown(root), encoding="utf-8")
