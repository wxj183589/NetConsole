from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from openpyxl import Workbook

from netconsole.repositories.global_mib_repository import GlobalMibRepository


COMPARE_HEADERS = ["类型", "差异", "模块", "MIB文件", "对象/告警", "OID", "字段", "左侧值", "右侧值", "说明"]


@dataclass(frozen=True)
class ProductReferenceCompareResult:
    left_reference_id: int
    right_reference_id: int
    left_reference_name: str = ""
    right_reference_name: str = ""
    summary: dict[str, int] = field(default_factory=dict)
    rows: list[dict[str, object]] = field(default_factory=list)


class MibProductReferenceCompareService:
    def __init__(self, repository: GlobalMibRepository) -> None:
        self.repository = repository

    def compare(self, left_reference_id: int, right_reference_id: int, *, persist: bool = True) -> ProductReferenceCompareResult:
        left = self.repository.get_product_reference(left_reference_id) or {}
        right = self.repository.get_product_reference(right_reference_id) or {}
        if not left or not right:
            raise ValueError("请选择有效的产品 MIB 参考表。")

        left_objects = self._object_map(self.repository.list_product_object_overrides(left_reference_id))
        right_objects = self._object_map(self.repository.list_product_object_overrides(right_reference_id))
        left_traps = self._trap_map(self.repository.list_product_trap_overrides(left_reference_id))
        right_traps = self._trap_map(self.repository.list_product_trap_overrides(right_reference_id))

        rows: list[dict[str, object]] = []
        rows.extend(self._compare_modules(left_objects.values(), right_objects.values()))
        rows.extend(self._compare_records("object", left_objects, right_objects, OBJECT_COMPARE_FIELDS))
        rows.extend(self._compare_records("trap", left_traps, right_traps, TRAP_COMPARE_FIELDS))

        summary = {
            "left_objects": len(left_objects),
            "right_objects": len(right_objects),
            "left_traps": len(left_traps),
            "right_traps": len(right_traps),
            "modules_changed": sum(1 for row in rows if row.get("item_type") == "module"),
            "objects_added": sum(1 for row in rows if row.get("item_type") == "object" and row.get("diff_type") == "added"),
            "objects_removed": sum(1 for row in rows if row.get("item_type") == "object" and row.get("diff_type") == "removed"),
            "objects_changed": len({row.get("stable_key") for row in rows if row.get("item_type") == "object" and row.get("diff_type") in {"changed", "category_changed"}}),
            "traps_added": sum(1 for row in rows if row.get("item_type") == "trap" and row.get("diff_type") == "added"),
            "traps_removed": sum(1 for row in rows if row.get("item_type") == "trap" and row.get("diff_type") == "removed"),
            "traps_changed": len({row.get("stable_key") for row in rows if row.get("item_type") == "trap" and row.get("diff_type") in {"changed", "category_changed"}}),
            "diff_rows": len(rows),
        }

        if persist:
            self.repository.replace_product_reference_overlays(left_reference_id, left_objects.values())
            self.repository.replace_product_reference_overlays(right_reference_id, right_objects.values())
            self.repository.replace_product_reference_compare_results(left_reference_id, right_reference_id, rows)

        return ProductReferenceCompareResult(
            left_reference_id=int(left_reference_id),
            right_reference_id=int(right_reference_id),
            left_reference_name=str(left.get("reference_name") or ""),
            right_reference_name=str(right.get("reference_name") or ""),
            summary=summary,
            rows=rows,
        )

    def list_results(
        self,
        left_reference_id: int,
        right_reference_id: int,
        *,
        diff_type: str = "",
        keyword: str = "",
        limit: int = 500,
        offset: int = 0,
    ) -> list[dict[str, object]]:
        return self.repository.list_product_reference_compare_results(
            left_reference_id,
            right_reference_id,
            diff_type=diff_type,
            keyword=keyword,
            limit=limit,
            offset=offset,
        )

    def export_results(self, left_reference_id: int, right_reference_id: int, target_path: str | Path) -> Path:
        path = Path(target_path)
        rows = self.list_results(left_reference_id, right_reference_id, limit=200000)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix.lower() == ".xlsx":
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "产品参考对比"
            sheet.append(COMPARE_HEADERS)
            for row in rows:
                sheet.append(_row_values(row))
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
            for column in sheet.columns:
                letter = column[0].column_letter
                sheet.column_dimensions[letter].width = min(60, max(12, max(len(str(cell.value or "")) for cell in column) + 2))
            workbook.save(path)
            return path
        with path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(COMPARE_HEADERS)
            for row in rows:
                writer.writerow(_row_values(row))
        return path

    def _object_map(self, rows: Iterable[dict[str, object]]) -> dict[str, dict[str, object]]:
        result: dict[str, dict[str, object]] = {}
        for row in rows:
            stable_key, key_type = _object_key(row)
            if not stable_key or stable_key in result:
                continue
            category_number, category_title = split_category(str(row.get("category_name") or ""))
            item = dict(row)
            item.update(
                {
                    "stable_key": stable_key,
                    "key_type": key_type,
                    "category_number": category_number,
                    "category_title": category_title,
                }
            )
            result[stable_key] = item
        return result

    def _trap_map(self, rows: Iterable[dict[str, object]]) -> dict[str, dict[str, object]]:
        result: dict[str, dict[str, object]] = {}
        for row in rows:
            stable_key, key_type = _trap_key(row)
            if not stable_key or stable_key in result:
                continue
            category_number, category_title = split_category(str(row.get("category_name") or ""))
            item = dict(row)
            item.update(
                {
                    "stable_key": stable_key,
                    "key_type": key_type,
                    "category_number": category_number,
                    "category_title": category_title,
                    "object_name": str(row.get("trap_name") or ""),
                    "numeric_oid": str(row.get("trap_oid") or ""),
                }
            )
            result[stable_key] = item
        return result

    def _compare_modules(self, left_rows: Iterable[dict[str, object]], right_rows: Iterable[dict[str, object]]) -> list[dict[str, object]]:
        left_modules = _module_categories(left_rows)
        right_modules = _module_categories(right_rows)
        rows: list[dict[str, object]] = []
        for module in sorted(set(left_modules) - set(right_modules)):
            rows.append(_diff_row("module", "removed", module, {"module_name": module}, {}, "module_name", module, "", "左侧存在，右侧缺失模块。"))
        for module in sorted(set(right_modules) - set(left_modules)):
            rows.append(_diff_row("module", "added", module, {}, {"module_name": module}, "module_name", "", module, "右侧新增模块。"))
        for module in sorted(set(left_modules) & set(right_modules)):
            left_categories = left_modules[module]
            right_categories = right_modules[module]
            for title in sorted(set(left_categories) & set(right_categories)):
                left_numbers = left_categories[title]
                right_numbers = right_categories[title]
                if left_numbers != right_numbers:
                    rows.append(
                        _diff_row(
                            "module",
                            "category_changed",
                            module,
                            {"module_name": module},
                            {"module_name": module},
                            "category_name",
                            _format_category_numbers(left_numbers, title),
                            _format_category_numbers(right_numbers, title),
                            "分册名称相同但编号变化，按同一业务分类处理。",
                        )
                    )
        return rows

    def _compare_records(
        self,
        item_type: str,
        left_map: dict[str, dict[str, object]],
        right_map: dict[str, dict[str, object]],
        fields: tuple[tuple[str, str], ...],
    ) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for key in sorted(set(left_map) - set(right_map)):
            left = left_map[key]
            rows.append(_diff_row(item_type, "removed", key, left, {}, "", _record_title(left), "", "左侧存在，右侧缺失。"))
        for key in sorted(set(right_map) - set(left_map)):
            right = right_map[key]
            rows.append(_diff_row(item_type, "added", key, {}, right, "", "", _record_title(right), "右侧新增。"))
        for key in sorted(set(left_map) & set(right_map)):
            left = left_map[key]
            right = right_map[key]
            if _same_text(left.get("category_title"), right.get("category_title")) and not _same_text(left.get("category_number"), right.get("category_number")):
                rows.append(
                    _diff_row(
                        item_type,
                        "category_changed",
                        key,
                        left,
                        right,
                        "category_name",
                        str(left.get("category_name") or ""),
                        str(right.get("category_name") or ""),
                        "分册名称相同但编号变化，按同一业务分类处理。",
                    )
                )
            for field, label in fields:
                left_value = _text(left.get(field))
                right_value = _text(right.get(field))
                if _same_text(left_value, right_value):
                    continue
                rows.append(_diff_row(item_type, "changed", key, left, right, label, left_value, right_value, f"{label} 发生变化。"))
        return rows


OBJECT_COMPARE_FIELDS = (
    ("module_name", "模块名"),
    ("mib_file_name", "MIB文件名"),
    ("object_name", "对象名"),
    ("numeric_oid", "OID"),
    ("access_from_reference", "访问权限"),
    ("data_type_from_reference", "数据类型"),
    ("value_range", "取值范围"),
    ("chinese_description", "中文含义"),
    ("function_description", "功能描述"),
    ("implementation_spec", "实现规格"),
    ("operation_support", "操作支持情况"),
)


TRAP_COMPARE_FIELDS = (
    ("module_name", "模块名"),
    ("mib_file_name", "MIB文件名"),
    ("trap_name", "告警名"),
    ("trap_oid", "告警OID"),
    ("trap_title", "告警标题"),
    ("trap_type", "告警类型"),
    ("trap_level", "告警级别"),
    ("clear_trap_oid", "清除告警OID"),
    ("clear_trap_name", "清除告警名称"),
    ("default_status", "缺省状态"),
    ("trigger_reason", "触发原因"),
    ("system_impact", "系统影响"),
    ("status_control", "状态控制"),
    ("varbind_oids", "绑定变量OID"),
    ("varbind_names", "绑定变量名称"),
    ("varbind_descriptions", "绑定变量说明"),
    ("suggestion", "处理建议"),
)


def split_category(value: str) -> tuple[str, str]:
    text = _text(value)
    match = re.match(r"^\s*(\d+)\s*[-_－—]?\s*(.+?)\s*$", text)
    if match:
        return match.group(1), match.group(2).strip()
    return "", text


def _object_key(row: dict[str, object]) -> tuple[str, str]:
    oid = _text(row.get("numeric_oid"))
    if oid:
        return f"oid:{oid}", "numeric_oid"
    module = _text(row.get("module_name"))
    name = _text(row.get("object_name"))
    if module and name:
        return f"module_object:{module}:{name}", "module_name+object_name"
    mib_file = _text(row.get("mib_file_name"))
    if mib_file and name:
        return f"mib_file_object:{mib_file}:{name}", "mib_file_name+object_name"
    return (f"object:{name}", "object_name") if name else ("", "")


def _trap_key(row: dict[str, object]) -> tuple[str, str]:
    oid = _text(row.get("trap_oid"))
    if oid:
        return f"trap_oid:{oid}", "trap_oid"
    module = _text(row.get("module_name"))
    name = _text(row.get("trap_name"))
    if module and name:
        return f"module_trap:{module}:{name}", "module_name+trap_name"
    varbinds = _text(row.get("varbind_oids")) or _text(row.get("varbind_names"))
    if name and varbinds:
        return f"trap_varbind:{name}:{varbinds}", "trap_name+varbinds"
    return (f"trap:{name}", "trap_name") if name else ("", "")


def _module_categories(rows: Iterable[dict[str, object]]) -> dict[str, dict[str, set[str]]]:
    result: dict[str, dict[str, set[str]]] = {}
    for row in rows:
        module = _text(row.get("module_name"))
        if not module:
            continue
        number, title = split_category(_text(row.get("category_name")))
        if not title:
            title = _text(row.get("category_name"))
        result.setdefault(module, {}).setdefault(_normalize_category_title(title), set()).add(number)
    return result


def _diff_row(item_type: str, diff_type: str, stable_key: str, left: dict[str, object], right: dict[str, object], field_name: str, left_value: object, right_value: object, summary: str) -> dict[str, object]:
    source = right or left
    return {
        "item_type": item_type,
        "diff_type": diff_type,
        "stable_key": stable_key,
        "module_name": source.get("module_name") or "",
        "mib_file_name": source.get("mib_file_name") or "",
        "object_name": source.get("object_name") or source.get("trap_name") or "",
        "numeric_oid": source.get("numeric_oid") or source.get("trap_oid") or "",
        "field_name": field_name,
        "left_value": left_value,
        "right_value": right_value,
        "summary": summary,
    }


def _row_values(row: dict[str, object]) -> list[object]:
    return [
        row.get("item_type") or "",
        row.get("diff_type") or "",
        row.get("module_name") or "",
        row.get("mib_file_name") or "",
        row.get("object_name") or "",
        row.get("numeric_oid") or "",
        row.get("field_name") or "",
        row.get("left_value") or "",
        row.get("right_value") or "",
        row.get("summary") or "",
    ]


def _record_title(row: dict[str, object]) -> str:
    return _text(row.get("numeric_oid")) or _text(row.get("trap_oid")) or _text(row.get("object_name")) or _text(row.get("trap_name"))


def _format_category_numbers(numbers: set[str], normalized_title: str) -> str:
    title = normalized_title or ""
    return ",".join(f"{number}-{title}" if number else title for number in sorted(numbers))


def _same_text(left: object, right: object) -> bool:
    return _normalize_value(left) == _normalize_value(right)


def _normalize_category_title(value: object) -> str:
    return re.sub(r"\s+", "", _text(value)).lower()


def _normalize_value(value: object) -> str:
    return re.sub(r"\s+", " ", _text(value)).strip()


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()
