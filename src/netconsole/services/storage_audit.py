"""Read-only access to previously generated storage audit reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REPORT_DIRECTORY_NAME = "storage-audit-report"
REPORT_FILES = (
    "SITE_STORAGE_INVENTORY.json",
    "SITE_STORAGE_ANALYSIS.json",
    "LARGE_FILES_REPORT.json",
    "SITES_SUMMARY.json",
    "ALL_SQLITE_DATABASES.json",
)


class StorageAuditService:
    """Expose an existing report without scanning or mutating the data root."""

    def __init__(self, data_root: Path, report_directory: Path | None = None) -> None:
        self.data_root = Path(data_root).expanduser().resolve()
        self.report_directory = (
            Path(report_directory).expanduser().resolve()
            if report_directory is not None
            else self._discover_report_directory()
        )

    def _discover_report_directory(self) -> Path:
        candidates = (
            self.data_root / REPORT_DIRECTORY_NAME / "all-sites",
            self.data_root / REPORT_DIRECTORY_NAME,
            self.data_root / "sites" / REPORT_DIRECTORY_NAME / "all-sites",
            self.data_root / "sites" / REPORT_DIRECTORY_NAME,
        )
        for candidate in candidates:
            if (candidate / "SITE_STORAGE_INVENTORY.json").is_file():
                return candidate
        return candidates[0]

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    def snapshot(self) -> dict[str, Any]:
        present = [name for name in REPORT_FILES if (self.report_directory / name).is_file()]
        missing = [name for name in REPORT_FILES if name not in present]
        reports = {name: self._read_json(self.report_directory / name) for name in REPORT_FILES}
        inventory = reports["SITE_STORAGE_INVENTORY.json"]
        analysis = reports["SITE_STORAGE_ANALYSIS.json"]
        sites = reports["SITES_SUMMARY.json"]
        databases = reports["ALL_SQLITE_DATABASES.json"]
        errors = self._errors(reports)
        invalid = [name for name in present if not reports[name]]
        if not self.data_root.exists():
            status = "DATA_ROOT_UNAVAILABLE"
            message = "当前数据根目录不存在或不可访问。"
        elif not present:
            status = "REPORT_NOT_GENERATED"
            message = "尚未生成存储审计报告；页面不会用 0 伪装为真实扫描结果。"
        elif missing or invalid:
            status = "REPORT_INCOMPLETE"
            message = "存储审计报告不完整或格式无效，请重新生成报告。"
        elif errors:
            status = "READY_WITH_ERRORS"
            message = "报告可读，但扫描时记录了异常。"
        else:
            status = "READY"
            message = "已加载现有只读存储审计报告。"
        return {
            "status": status,
            "message": message,
            "required_report_files": list(REPORT_FILES),
            "missing_report_files": missing,
            "invalid_report_files": invalid,
            "report_directory": str(self.report_directory),
            "root_path": inventory.get("root_path", str(self.data_root)),
            "generated_at": inventory.get("generated_at", ""),
            "total_size_bytes": int(inventory.get("total_size_bytes", 0) or 0),
            "total_files": int(inventory.get("total_files", 0) or 0),
            "sites": self._sorted(sites.get("sites", []), "total_size_bytes"),
            "directories": self._sorted(
                analysis.get("top_directories", analysis.get("directories", [])),
                "size_bytes",
            ),
            "largest_files": self._sorted(inventory.get("largest_files", []), "size_bytes"),
            "databases": self._sorted(databases.get("databases", []), "size_bytes"),
            "errors": errors,
            "read_only": True,
        }

    @staticmethod
    def _sorted(items: Any, size_key: str) -> list[dict[str, Any]]:
        if not isinstance(items, list):
            return []
        values = [item for item in items if isinstance(item, dict)]
        return sorted(values, key=lambda item: (-int(item.get(size_key, 0) or 0), str(item.get("path", item.get("site_name", "")))))

    @staticmethod
    def _errors(reports: dict[str, dict[str, Any]]) -> list[str]:
        errors: list[str] = []
        for name, report in reports.items():
            report_errors = report.get("errors", [])
            if isinstance(report_errors, list):
                errors.extend(f"{name}: {error}" for error in report_errors if error)
        return sorted(set(errors))
