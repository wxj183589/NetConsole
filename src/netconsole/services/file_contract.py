from __future__ import annotations

import csv
import io
import json
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

from netconsole.core.version import APP_VERSION
from netconsole.utils.excel_workbook import load_workbook_without_unsupported_image_warning
from netconsole.utils.text_encoding import (
    TEXT_ENCODINGS,
    decode_bytes_with_fallback,
)


META_SHEET = "_netconsole_meta"
ZIP_MANIFEST = "_netconsole_manifest.json"
CSV_META_MARKER = "#NETCONSOLE_META"
CONTRACT_SCHEMA_VERSION = 1
SUPPORTED_SCHEMA_VERSIONS = {1, 2, 3, 4}
_ARTIFACT_MEDIA_TYPES = {
    ".cfg": "text/plain",
    ".conf": "text/plain",
    ".csv": "text/csv",
    ".diff": "text/plain",
    ".gz": "application/gzip",
    ".html": "text/html",
    ".json": "application/json",
    ".jsonl": "application/x-ndjson",
    ".log": "text/plain",
    ".md": "text/markdown",
    ".nam": "text/plain",
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".tar.gz": "application/gzip",
    ".tgz": "application/gzip",
    ".txt": "text/plain",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
    ".zip": "application/zip",
    ".zip.gz": "application/gzip",
}


def artifact_media_type(filename: object) -> str:
    name = Path(str(filename or "")).name.casefold()
    suffix = next(
        (value for value in (".tar.gz", ".zip.gz") if name.endswith(value)),
        Path(name).suffix,
    )
    return _ARTIFACT_MEDIA_TYPES.get(suffix, "application/octet-stream")


class ImportValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ImportValidationResult:
    path: Path
    file_type: str
    module: str
    metadata: dict[str, Any]
    legacy: bool = False
    headers: tuple[str, ...] = ()
    sheet_names: tuple[str, ...] = ()
    row_count: int = 0
    encoding: str = ""


def build_metadata(
    *,
    file_type: str,
    module: str,
    export_type: str,
    required_sheets: Iterable[str] = (),
    required_columns: Mapping[str, Iterable[str]] | None = None,
) -> dict[str, Any]:
    return {
        "format": "netconsole",
        "file_type": str(file_type),
        "type": str(export_type),
        "module": str(module),
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "required_sheets": [str(value) for value in required_sheets],
        "required_columns": {
            str(sheet): [str(value) for value in columns]
            for sheet, columns in dict(required_columns or {}).items()
        },
        "exported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "app_version": APP_VERSION,
    }


def attach_export_metadata(
    path: str | Path,
    *,
    effective_suffix: str,
    export_type: str,
    payload: Mapping[str, Any] | None = None,
) -> None:
    target = Path(path)
    if not target.is_file():
        return
    suffix = str(effective_suffix or target.suffix).casefold()
    payload = dict(payload or {})
    module = str(payload.get("source_module") or _infer_module(export_type, payload))
    if suffix == ".xlsx":
        _attach_xlsx_metadata(target, module, export_type, payload)
    elif suffix == ".csv":
        _attach_csv_metadata(target, module, export_type)
    elif suffix == ".json":
        _attach_json_metadata(target, module, export_type)
    elif suffix == ".zip":
        _attach_zip_metadata(target, module, export_type)


def validate_csv_import(
    path: str | Path,
    *,
    expected_module: str,
    required_headers: Iterable[str],
    allow_legacy: bool = True,
    allow_header_only: bool = False,
) -> ImportValidationResult:
    target = _require_file(path, {".csv"})
    text, encoding = _read_text(target)
    rows = list(csv.reader(io.StringIO(text)))
    metadata, rows = _extract_csv_metadata(rows)
    if not rows or not any(any(str(value).strip() for value in row) for row in rows):
        raise ImportValidationError("文件为空")
    headers = tuple(str(value).strip() for value in rows[0])
    required = tuple(str(value).strip() for value in required_headers)
    missing = [header for header in required if header not in headers]
    if missing:
        raise ImportValidationError(f"缺少必要字段：{', '.join(missing)}")
    data_rows = [row for row in rows[1:] if any(str(value).strip() for value in row)]
    if not data_rows and not allow_header_only:
        raise ImportValidationError("文件为空：没有可导入的数据")
    for line_number, row in enumerate(data_rows, start=2):
        if len(row) != len(headers):
            raise ImportValidationError(f"第 {line_number} 行列数量与表头不一致")
    legacy = not bool(metadata)
    if legacy and not allow_legacy:
        raise ImportValidationError("不是 NetConsole 导出的文件")
    _validate_metadata(metadata, expected_module, "csv", allow_missing=allow_legacy)
    return ImportValidationResult(target, "csv", expected_module, metadata, legacy, headers, row_count=len(data_rows), encoding=encoding)


def read_validated_csv_rows(path: str | Path) -> tuple[list[list[str]], dict[str, Any], str]:
    target = _require_file(path, {".csv"})
    text, encoding = _read_text(target)
    metadata, rows = _extract_csv_metadata(list(csv.reader(io.StringIO(text))))
    return rows, metadata, encoding


def validate_excel_import(
    path: str | Path,
    *,
    expected_module: str,
    required_sheets: Iterable[str] = (),
    required_headers: Mapping[str, Iterable[str]] | None = None,
    allow_legacy: bool = True,
) -> ImportValidationResult:
    target = _require_file(path, {".xlsx"})
    try:
        workbook = load_workbook_without_unsupported_image_warning(target, data_only=True, read_only=False)
    except Exception as exc:
        raise ImportValidationError(f"文件已损坏或无法读取：{exc}") from exc
    try:
        metadata = _xlsx_metadata(workbook)
        sheets = tuple(name for name in workbook.sheetnames if name != META_SHEET)
        required_sheet_names = tuple(str(value) for value in required_sheets)
        missing_sheets = [name for name in required_sheet_names if name not in sheets]
        if missing_sheets:
            raise ImportValidationError(f"缺少必要 sheet：{', '.join(missing_sheets)}")
        total_rows = 0
        discovered_headers: tuple[str, ...] = ()
        for sheet_name, headers in dict(required_headers or {}).items():
            selected_name = sheet_name if sheet_name in workbook.sheetnames else (sheets[0] if len(sheets) == 1 else "")
            if not selected_name:
                raise ImportValidationError(f"缺少必要 sheet：{sheet_name}")
            sheet = workbook[selected_name]
            header_values, header_row = _find_excel_header(sheet, tuple(str(value) for value in headers))
            missing = [value for value in headers if str(value) not in header_values]
            if missing:
                raise ImportValidationError(f"缺少必要字段：{', '.join(str(value) for value in missing)}")
            discovered_headers = tuple(header_values)
            rows = [row for row in sheet.iter_rows(min_row=header_row + 1, values_only=True) if any(value not in (None, "") for value in row)]
            total_rows += len(rows)
        if not required_headers:
            total_rows = sum(
                1
                for name in sheets
                for row in workbook[name].iter_rows(values_only=True)
                if any(value not in (None, "") for value in row)
            )
        if total_rows <= 0:
            raise ImportValidationError("文件为空")
        legacy = not bool(metadata)
        if legacy and not allow_legacy:
            raise ImportValidationError("不是 NetConsole 导出的文件")
        _validate_metadata(metadata, expected_module, "xlsx", allow_missing=allow_legacy)
        return ImportValidationResult(target, "xlsx", expected_module, metadata, legacy, discovered_headers, sheets, total_rows)
    finally:
        workbook.close()


def validate_json_import(
    path: str | Path,
    *,
    expected_module: str,
    data_key: str = "data",
    required_keys: Iterable[str] = (),
    allow_legacy: bool = False,
) -> ImportValidationResult:
    target = _require_file(path, {".json"})
    if target.stat().st_size == 0:
        raise ImportValidationError("文件为空")
    try:
        payload = json.loads(target.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise ImportValidationError(f"文件已损坏或无法读取：{exc}") from exc
    metadata = dict(payload.get("_netconsole_meta") or {}) if isinstance(payload, dict) else {}
    legacy = not bool(metadata)
    if legacy and not allow_legacy:
        raise ImportValidationError("不是 NetConsole 导出的文件")
    _validate_metadata(metadata, expected_module, "json", allow_missing=allow_legacy)
    data = payload.get(data_key) if isinstance(payload, dict) else payload if allow_legacy else None
    if not isinstance(data, (list, dict)) or not data:
        raise ImportValidationError("文件为空或业务数据结构无效")
    if isinstance(data, dict):
        missing = [key for key in required_keys if key not in data]
        if missing:
            raise ImportValidationError(f"缺少必要字段：{', '.join(missing)}")
    elif required_keys:
        for index, item in enumerate(data, start=1):
            if not isinstance(item, dict):
                raise ImportValidationError(f"第 {index} 项业务数据结构无效")
            missing = [key for key in required_keys if key not in item]
            if missing:
                raise ImportValidationError(f"第 {index} 项缺少必要字段：{', '.join(missing)}")
    return ImportValidationResult(target, "json", expected_module, metadata, legacy, row_count=len(data))


def validate_optional_contract_metadata(path: str | Path, *, expected_module: str) -> None:
    target = Path(path)
    suffix = target.suffix.casefold()
    if suffix == ".xlsx":
        try:
            workbook = load_workbook_without_unsupported_image_warning(target, data_only=True, read_only=False)
        except Exception as exc:
            raise ImportValidationError(f"文件已损坏或无法读取：{exc}") from exc
        try:
            metadata = _xlsx_metadata(workbook)
        finally:
            workbook.close()
        if metadata:
            _validate_metadata(metadata, expected_module, "xlsx", allow_missing=False)
        return
    if suffix == ".csv":
        text, _encoding = _read_text(_require_file(target, {".csv"}))
        metadata, _rows = _extract_csv_metadata(list(csv.reader(io.StringIO(text))))
        if metadata:
            _validate_metadata(metadata, expected_module, "csv", allow_missing=False)
        return
    raise ImportValidationError("文件类型不匹配")


def validate_zip_import(
    path: str | Path,
    *,
    expected_module: str,
    required_files: Iterable[str] = (),
    allow_external: bool = False,
    allowed_external_suffixes: Iterable[str] = (),
) -> ImportValidationResult:
    target = _require_file(path, {".zip"})
    try:
        with zipfile.ZipFile(target) as archive:
            names = archive.namelist()
            _validate_zip_names(names)
            metadata: dict[str, Any] = {}
            if ZIP_MANIFEST in names:
                metadata = json.loads(archive.read(ZIP_MANIFEST).decode("utf-8-sig"))
            if not metadata and not allow_external:
                raise ImportValidationError("不是 NetConsole 支持的导入文件：缺少 manifest")
            if metadata:
                _validate_metadata(metadata, expected_module, "zip", allow_missing=False)
            elif allowed_external_suffixes:
                suffixes = {str(value).casefold() for value in allowed_external_suffixes}
                if not any(Path(name).suffix.casefold() in suffixes for name in names if not name.endswith("/")):
                    raise ImportValidationError("不是 NetConsole 支持的导入文件")
            missing = [name for name in required_files if name not in names]
            if missing:
                raise ImportValidationError(f"缺少必要文件：{', '.join(missing)}")
            return ImportValidationResult(target, "zip", expected_module, metadata, not bool(metadata), row_count=len(names))
    except ImportValidationError:
        raise
    except Exception as exc:
        raise ImportValidationError(f"文件已损坏或无法读取：{exc}") from exc


def safe_extract_zip(archive: zipfile.ZipFile, destination: str | Path) -> None:
    _validate_zip_names(archive.namelist())
    root = Path(destination).resolve()
    for member in archive.infolist():
        target = (root / member.filename).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise ImportValidationError("ZIP 包含不安全路径") from exc
    archive.extractall(root)


def _attach_xlsx_metadata(
    path: Path,
    module: str,
    export_type: str,
    payload: Mapping[str, Any],
) -> None:
    with path.open("rb") as handle:
        workbook = load_workbook_without_unsupported_image_warning(handle, read_only=False)
    try:
        if META_SHEET in workbook.sheetnames:
            del workbook[META_SHEET]
        required_sheets = [name for name in workbook.sheetnames if name != META_SHEET]
        required_columns = {
            name: _first_nonempty_excel_row(workbook[name])
            for name in required_sheets
        }
        metadata = build_metadata(
            file_type="xlsx",
            module=module,
            export_type=export_type,
            required_sheets=required_sheets,
            required_columns=required_columns,
        )
        contract_metadata = payload.get("contract_metadata")
        if isinstance(contract_metadata, Mapping):
            for key in (
                "template_type",
                "schema_version",
                "generated_at",
                "exported_at",
                "project_id",
                "line_id",
                "site_id",
                "site_display_name",
            ):
                if key in contract_metadata:
                    metadata[key] = contract_metadata[key]
        sheet = workbook.create_sheet(META_SHEET)
        sheet.sheet_state = "hidden"
        sheet.append(["metadata_json", json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))])
        workbook.save(path)
    finally:
        workbook.close()


def _attach_csv_metadata(path: Path, module: str, export_type: str) -> None:
    text, _encoding = _read_text(path)
    rows = list(csv.reader(io.StringIO(text)))
    _old, rows = _extract_csv_metadata(rows)
    metadata = build_metadata(
        file_type="csv",
        module=module,
        export_type=export_type,
        required_columns={"data": rows[0] if rows else []},
    )
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow([CSV_META_MARKER, json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))])
    writer.writerows(rows)
    path.write_text(output.getvalue(), encoding="utf-8-sig")


def _attach_json_metadata(path: Path, module: str, export_type: str) -> None:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    data = payload.get("data") if isinstance(payload, dict) and "data" in payload else payload
    if isinstance(data, list) and data and isinstance(data[0], dict):
        fields = list(data[0])
    elif isinstance(data, dict):
        fields = list(data)
    else:
        fields = []
    metadata = build_metadata(
        file_type="json",
        module=module,
        export_type=export_type,
        required_columns={"data": fields},
    )
    if isinstance(payload, dict):
        payload["_netconsole_meta"] = metadata
    else:
        payload = {"_netconsole_meta": metadata, "data": payload}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _attach_zip_metadata(path: Path, module: str, export_type: str) -> None:
    with zipfile.ZipFile(path, "a", zipfile.ZIP_DEFLATED) as archive:
        files = [name for name in archive.namelist() if name != ZIP_MANIFEST]
        metadata = build_metadata(file_type="zip", module=module, export_type=export_type)
        metadata["files"] = files
        archive.writestr(ZIP_MANIFEST, json.dumps(metadata, ensure_ascii=False, indent=2))


def _xlsx_metadata(workbook: Any) -> dict[str, Any]:
    if META_SHEET not in workbook.sheetnames:
        return {}
    value = workbook[META_SHEET].cell(1, 2).value
    try:
        data = json.loads(str(value or ""))
    except json.JSONDecodeError as exc:
        raise ImportValidationError("NetConsole metadata 已损坏") from exc
    return data if isinstance(data, dict) else {}


def _extract_csv_metadata(rows: list[list[str]]) -> tuple[dict[str, Any], list[list[str]]]:
    if not rows or not rows[0] or str(rows[0][0]).strip() != CSV_META_MARKER:
        return {}, rows
    if len(rows[0]) < 2:
        raise ImportValidationError("NetConsole metadata 已损坏")
    try:
        metadata = json.loads(rows[0][1])
    except json.JSONDecodeError as exc:
        raise ImportValidationError("NetConsole metadata 已损坏") from exc
    return (metadata if isinstance(metadata, dict) else {}), rows[1:]


def _validate_metadata(metadata: Mapping[str, Any], expected_module: str, file_type: str, *, allow_missing: bool) -> None:
    if not metadata:
        if allow_missing:
            return
        raise ImportValidationError("不是 NetConsole 导出的文件")
    if metadata.get("format") != "netconsole":
        raise ImportValidationError("不是 NetConsole 支持的导入文件")
    if str(metadata.get("file_type") or "").casefold() != file_type.casefold():
        raise ImportValidationError("文件类型不匹配")
    if str(metadata.get("module") or "") != expected_module:
        raise ImportValidationError("当前模块不能导入该文件")
    if not str(metadata.get("type") or "").strip():
        raise ImportValidationError("不是 NetConsole 支持的导入文件：缺少类型标识")
    try:
        schema = int(metadata.get("schema_version"))
    except (TypeError, ValueError) as exc:
        raise ImportValidationError("文件版本不兼容") from exc
    if schema not in SUPPORTED_SCHEMA_VERSIONS:
        raise ImportValidationError("文件版本不兼容")


def _require_file(path: str | Path, suffixes: set[str]) -> Path:
    target = Path(path)
    if target.suffix.casefold() not in suffixes:
        raise ImportValidationError("文件类型不匹配")
    if not target.is_file():
        raise ImportValidationError("文件不存在或无法读取")
    if target.stat().st_size <= 0:
        raise ImportValidationError("文件为空")
    return target


def _read_text(path: Path) -> tuple[str, str]:
    data = path.read_bytes()
    try:
        decoded = decode_bytes_with_fallback(
            data,
            encodings=TEXT_ENCODINGS,
            replace_on_failure=False,
            source="csv_import",
        )
    except ValueError as exc:
        attempted = "、".join(TEXT_ENCODINGS)
        raise ImportValidationError(
            f"文件编码无法识别；已尝试：{attempted}"
        ) from exc
    return decoded.text, decoded.encoding


def _find_excel_header(sheet: Any, required: tuple[str, ...]) -> tuple[list[str], int]:
    for row_number, row in enumerate(sheet.iter_rows(min_row=1, max_row=10, values_only=True), start=1):
        headers = [str(value or "").strip() for value in row]
        if all(value in headers for value in required):
            return headers, row_number
    return [], 0


def _first_nonempty_excel_row(sheet: Any) -> list[str]:
    best: list[str] = []
    for row in sheet.iter_rows(min_row=1, max_row=10, values_only=True):
        values = [str(value or "").strip() for value in row]
        if sum(bool(value) for value in values) > sum(bool(value) for value in best):
            best = values
    return best


def _validate_zip_names(names: Iterable[str]) -> None:
    for name in names:
        normalized = str(name).replace("\\", "/")
        pure = PurePosixPath(normalized)
        if pure.is_absolute() or ".." in pure.parts or (pure.parts and ":" in pure.parts[0]):
            raise ImportValidationError("ZIP 包含不安全路径")


def _infer_module(export_type: str, payload: Mapping[str, Any]) -> str:
    mapping = {
        "device_csv": "devices",
        "device_template_csv": "devices",
        "fit_ap_csv": "ac.fit_ap",
        "fit_ap_extension_xlsx": "ac.ap_extension",
        "fit_ap_extension_template_xlsx": "ac.ap_extension",
        "car_network_point_table": "rail.car_network_point_table",
        "online_mr_report_xlsx": "rail.online_mr",
        "vehicle_mr_history_xlsx": "rail.vehicle_mr_history",
        "config_snapshots_zip": "config_collection",
        "app_logs_csv": "logs",
    }
    if export_type in mapping:
        return mapping[export_type]
    hint = " ".join(
        str(payload.get(key) or "")
        for key in ("title", "sheet_name")
    )
    if "轨旁AP规划" in hint:
        return "ac.trackside_ap_plan"
    if "轨旁AP业务" in hint:
        return "rail.trackside_ap_business"
    if "车载MR映射" in hint or "映射模板" in hint:
        return "rail.vehicle_mr_mapping"
    return f"export.{export_type}"
