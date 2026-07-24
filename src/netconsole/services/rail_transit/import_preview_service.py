from __future__ import annotations

import hashlib
import json
import mimetypes
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from netconsole.models.api.rail_transit_base_data import (
    DataQualityIssueDTO,
    ImportPreviewResultDTO,
    ImportPreviewRowDTO,
)
from netconsole.services.ap_extension_import import AP_SWITCH_PORT_POINT_TABLE, ApExtensionImportService, normalize_ap_mac
from netconsole.services.rail_transit.base_data_import_service import RailTransitBaseDataImportService
from netconsole.services.rail_transit.base_data_query_service import RailTransitBaseDataQueryService
from netconsole.services.rail_transit.source_policy import is_blocking_issue
from netconsole.utils.mileage import parse_track_mileage


MAX_IMPORT_PREVIEW_BYTES = 10 * 1024 * 1024
MAX_IMPORT_PREVIEW_ROWS = 5_000
_ALLOWED_SUFFIXES = {".xlsx", ".csv", ".json"}
_ALLOWED_MIME_TYPES = {
    "application/octet-stream",
    "application/json",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/csv",
    "text/plain",
}
_SAFE_FIELDS = (
    "line_name",
    "system_type",
    "network_domain",
    "belong_type",
    "station_name",
    "section_name",
    "section_start_station",
    "section_end_station",
    "line_side",
    "direction",
    "ap_point_code",
    "ap_name",
    "ap_mac_norm",
    "ap_mac_display",
    "mileage_text",
    "mileage_m",
    "uplink_switch",
    "uplink_port",
    "remark",
    "source_sheet",
    "source_row",
)
_SECRET_MARKERS = ("password", "passwd", "secret", "token", "community", "credential", "username", "账号", "密码", "口令")


class RailTransitImportPreviewService:
    """受控文件解析与校验；仅持久化安全合并计划，不写正式数据。"""

    def __init__(
        self,
        query_service: RailTransitBaseDataQueryService,
        *,
        temp_root: Path | None = None,
        import_service: RailTransitBaseDataImportService | None = None,
    ) -> None:
        self.query_service = query_service
        self.temp_root = temp_root
        self.ap_importer = ApExtensionImportService()
        self.import_service = import_service or RailTransitBaseDataImportService(query_service.paths)

    def preview(
        self,
        *,
        site_id: str,
        file_name: str,
        content: bytes,
        content_type: str = "",
    ) -> ImportPreviewResultDTO:
        safe_name = Path(str(file_name or "")).name
        suffix = Path(safe_name).suffix.casefold()
        if not safe_name or suffix not in _ALLOWED_SUFFIXES:
            raise ValueError("仅支持 xlsx、csv、json 导入预览")
        if not content or len(content) > MAX_IMPORT_PREVIEW_BYTES:
            raise ValueError("导入预览文件必须非空且不超过 10 MiB")
        mime = str(content_type or mimetypes.guess_type(safe_name)[0] or "application/octet-stream").split(";", 1)[0].strip().casefold()
        if mime not in _ALLOWED_MIME_TYPES:
            raise ValueError("文件 MIME 类型不在导入预览白名单中")
        if suffix == ".json":
            rows = self._json_rows(content)
            template_type = "json_base_data"
            confidence = 100
            parser_issues: list[dict[str, Any]] = []
        else:
            if self.temp_root is not None:
                self.temp_root.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="netconsole-rail-preview-", dir=self.temp_root) as directory:
                path = Path(directory) / f"preview{suffix}"
                path.write_bytes(content)
                preview = self.ap_importer.preview_file(path)
                rows = preview.standard_rows
                template_type = preview.template_type
                confidence = preview.confidence_score
                parser_issues = [issue for sheet in preview.sheets for issue in sheet.issues]
        if len(rows) > MAX_IMPORT_PREVIEW_ROWS:
            raise ValueError(f"导入预览最多支持 {MAX_IMPORT_PREVIEW_ROWS} 行")
        known_stations, known_sections = self.query_service.known_locations(site_id)
        issues_by_row: dict[int, list[DataQualityIssueDTO]] = defaultdict(list)
        for issue in parser_issues:
            row_number = self._row_number(issue)
            issues_by_row[row_number].append(self._parser_issue(issue, row_number))
        mac_counts = Counter(
            normalize_ap_mac(row.get("ap_mac_norm") or row.get("ap_mac_display")).normalized
            for row in rows
            if normalize_ap_mac(row.get("ap_mac_norm") or row.get("ap_mac_display")).normalized
        )
        output: list[ImportPreviewRowDTO] = []
        for index, raw in enumerate(rows, 1):
            values = self._safe_values(raw, index)
            if template_type == AP_SWITCH_PORT_POINT_TABLE and self._same_mac_text(values.get("ap_name"), values.get("ap_mac_display")):
                values["ap_name"] = ""
            row_number = int(values.get("source_row") or index)
            row_issues = issues_by_row[row_number]
            row_issues.extend(self._validate_row(values, row_number, mac_counts, known_stations, known_sections, template_type=template_type))
            row_issues = self._deduplicate_issues(row_issues)
            output.append(ImportPreviewRowDTO(row_number=row_number, values=values, issues=row_issues))
        error_count = sum(issue.severity == "error" for row in output for issue in row.issues)
        warning_count = sum(issue.severity == "warning" for row in output for issue in row.issues)
        valid_rows = sum(
            not any(issue.severity == "error" for issue in row.issues)
            and not any(issue.code == "ap_mac_placeholder" for issue in row.issues)
            for row in output
        )
        statistics = self._statistics(output)
        merge_plan = self.import_service.build_merge_plan(
            site_id=site_id,
            rows=output,
            source_file_name=safe_name,
            source_file_sha256=hashlib.sha256(content).hexdigest(),
            source_type="official_point_table" if suffix in {".xlsx", ".csv"} else "import_file",
        )
        preview_id = self.import_service.save_preview(merge_plan)
        return ImportPreviewResultDTO(
            preview_id=preview_id,
            file_name=safe_name,
            file_size=len(content),
            template_type=template_type,
            confidence_score=confidence,
            total_rows=len(output),
            valid_rows=valid_rows,
            error_count=error_count,
            warning_count=warning_count,
            sheet_names=sorted({str(row.values.get("source_sheet") or "") for row in output if row.values.get("source_sheet")}),
            statistics=statistics,
            rows=output,
            merge_plan=merge_plan,
            database_hash=merge_plan.database_hash,
            preview_expires_at=merge_plan.preview_expires_at,
            write_enabled=merge_plan.write_enabled,
        )

    @staticmethod
    def _statistics(rows: list[ImportPreviewRowDTO]) -> dict[str, int]:
        return {
            "valid_ap_rows": sum(bool(normalize_ap_mac(row.values.get("ap_mac_norm") or row.values.get("ap_mac_display")).valid) for row in rows),
            "placeholder_rows": sum(any(issue.code == "ap_mac_placeholder" for issue in row.issues) for row in rows),
            "section_rows": sum(bool(str(row.values.get("section_name") or "").strip()) for row in rows),
            "without_section_rows": sum(not str(row.values.get("section_name") or "").strip() for row in rows),
            "missing_mileage_rows": sum(
                normalize_ap_mac(row.values.get("ap_mac_norm") or row.values.get("ap_mac_display")).valid
                and not str(row.values.get("mileage_text") or "").strip()
                and row.values.get("mileage_m") is None
                for row in rows
            ),
            "up_direction_rows": sum(str(row.values.get("direction") or "").strip() == "上行" for row in rows),
            "down_direction_rows": sum(str(row.values.get("direction") or "").strip() == "下行" for row in rows),
        }

    @staticmethod
    def _json_rows(content: bytes) -> list[dict[str, Any]]:
        try:
            payload = json.loads(content.decode("utf-8-sig"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("JSON 文件无法解析") from exc
        rows = payload.get("rows") if isinstance(payload, dict) else payload
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError("JSON 顶层必须是对象数组或包含 rows 数组")
        return [dict(row) for row in rows]

    @classmethod
    def _safe_values(cls, row: dict[str, Any], fallback_row: int) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for field in _SAFE_FIELDS:
            if any(marker in field.casefold() for marker in _SECRET_MARKERS):
                continue
            value = row.get(field)
            if isinstance(value, str):
                value = value[:2_000]
            values[field] = value
        values["source_row"] = cls._row_number(row) or fallback_row
        mac = normalize_ap_mac(values.get("ap_mac_norm") or values.get("ap_mac_display"))
        values["ap_mac_norm"] = mac.normalized
        values["ap_mac_display"] = mac.display or mac.raw
        mileage = parse_track_mileage(values.get("mileage_text") or values.get("mileage_m"))
        values["mileage_m"] = mileage.meters
        source_station_name = cls._source_station_name(row)
        if source_station_name:
            values["raw_payload_json"] = json.dumps(
                {"import_source": {"station_name": source_station_name}},
                ensure_ascii=False,
            )
        return values

    @staticmethod
    def _source_station_name(row: dict[str, Any]) -> str:
        try:
            payload = json.loads(str(row.get("raw_payload_json") or "{}"))
            raw_values = payload.get("values")
            mapping = payload.get("mapping")
            index = mapping.get("station_name") if isinstance(mapping, dict) else None
            if not isinstance(raw_values, list) or not isinstance(index, int) or not 0 <= index < len(raw_values):
                return ""
            return str(raw_values[index] or "").strip()[:2_000]
        except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
            return ""

    @classmethod
    def _validate_row(
        cls,
        values: dict[str, Any],
        row_number: int,
        mac_counts: Counter[str],
        known_stations: set[str],
        known_sections: set[str],
        *,
        template_type: str = "",
    ) -> list[DataQualityIssueDTO]:
        issues: list[DataQualityIssueDTO] = []
        name = str(values.get("ap_name") or "").strip()
        mac = normalize_ap_mac(values.get("ap_mac_norm") or values.get("ap_mac_display"))
        if not name and template_type != AP_SWITCH_PORT_POINT_TABLE:
            issues.append(cls._issue("warning", "ap_name_missing", row_number, "ap_name", "", "AP 名称为空", "补充正式 AP 名称"))
        if not mac.raw:
            issues.append(cls._issue("warning", "ap_mac_missing", row_number, "ap_mac_display", "", "AP MAC 为空", "补充有效 AP MAC"))
        elif template_type == AP_SWITCH_PORT_POINT_TABLE and str(mac.raw or "").strip().casefold() in {"-", "--", "无", "n/a", "na", "none"}:
            issues.append(cls._issue("warning", "ap_mac_placeholder", row_number, "ap_mac_display", mac.raw, "无效占位行，将跳过导入", "确认是否为无效空端口行"))
        elif not mac.valid:
            issues.append(cls._issue("error", "ap_mac_invalid", row_number, "ap_mac_display", mac.raw, "AP MAC 格式无效", "使用项目支持的常见 MAC 格式"))
        elif mac_counts[mac.normalized] > 1:
            issues.append(cls._issue("error", "ap_mac_duplicate", row_number, "ap_mac_display", mac.raw, "预览文件内 AP MAC 重复", "核对重复行"))
        station = str(values.get("station_name") or "").strip()
        section = str(values.get("section_name") or "").strip()
        if station and known_stations and station not in known_stations:
            issues.append(cls._issue("warning", "station_unknown", row_number, "station_name", station, "站点不在当前基础资料中", "确认站点名称或后续正式建模"))
        if section and known_sections and section not in known_sections:
            issues.append(cls._issue("warning", "section_unknown", row_number, "section_name", section, "区间不在当前基础资料中", "确认区间名称或后续正式建模"))
        raw_mileage = str(values.get("mileage_text") or "").strip()
        parsed = parse_track_mileage(raw_mileage or values.get("mileage_m"))
        if raw_mileage and (parsed.meters is None or parsed.error):
            issues.append(cls._issue("error", "mileage_invalid", row_number, "mileage_text", raw_mileage, parsed.error or "里程格式无效", "按 ZDK/YDK/CDK/RDK 格式修正"))
        expected = cls._expected_prefix(str(values.get("line_side") or ""), str(values.get("direction") or ""))
        if parsed.meters is not None and parsed.prefix and expected and parsed.prefix != expected:
            issues.append(cls._issue("warning", "mileage_direction_mismatch", row_number, "mileage_text", raw_mileage, "里程前缀与线路方向不一致", "核对线别和里程前缀"))
        return issues

    @staticmethod
    def _expected_prefix(line_side: str, direction: str) -> str:
        text = f"{line_side} {direction}"
        if "左" in text or "下行" in text:
            return "ZDK"
        if "右" in text or "上行" in text:
            return "YDK"
        if "出" in text:
            return "CDK"
        if "入" in text:
            return "RDK"
        return ""

    @staticmethod
    def _same_mac_text(left: object, right: object) -> bool:
        left_mac = normalize_ap_mac(left).normalized
        right_mac = normalize_ap_mac(right).normalized
        return bool(left_mac and right_mac and left_mac == right_mac)

    @staticmethod
    def _parser_issue(issue: dict[str, Any], row_number: int) -> DataQualityIssueDTO:
        severity = str(issue.get("severity") or "warning")
        if severity not in {"error", "warning", "info"}:
            severity = "warning"
        return RailTransitImportPreviewService._issue(
            severity,
            str(issue.get("type") or "parser_warning"),
            row_number,
            str(issue.get("field_name") or ""),
            str(issue.get("original_value") or ""),
            str(issue.get("message") or "文件内容需要人工核对"),
            "核对原始行",
        )

    @staticmethod
    def _issue(severity: str, code: str, row: int, field: str, original: str, message: str, action: str) -> DataQualityIssueDTO:
        return DataQualityIssueDTO(
            severity=severity,  # type: ignore[arg-type]
            code=code,
            entity_type="import_row",
            entity_id=f"row:{row}",
            entity_name=f"第 {row} 行",
            row_number=row,
            field_name=field,
            original_value=original,
            message=message,
            suggested_action=action,
            blocking=is_blocking_issue(code, severity),
        )

    @staticmethod
    def _row_number(row: dict[str, Any]) -> int:
        try:
            return int(row.get("source_row") or row.get("row_number") or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _deduplicate_issues(issues: list[DataQualityIssueDTO]) -> list[DataQualityIssueDTO]:
        seen: set[tuple[str, str, int | None]] = set()
        result = []
        for issue in issues:
            key = (issue.code, issue.message, issue.row_number)
            if key not in seen:
                seen.add(key)
                result.append(issue)
        return result


__all__ = ["MAX_IMPORT_PREVIEW_BYTES", "MAX_IMPORT_PREVIEW_ROWS", "RailTransitImportPreviewService"]
