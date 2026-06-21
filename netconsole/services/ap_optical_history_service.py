from __future__ import annotations

from pathlib import Path

from netconsole.repositories.ac_repository import AcRepository


class ApOpticalHistoryService:
    def __init__(self, repository: AcRepository) -> None:
        self.repository = repository

    def query_ap_optical_history(self, ap_uuid: str, page: int = 1, page_size: int = 200) -> tuple[list[dict[str, object | None]], int]:
        rows = self.query_ap_optical_history_all(ap_uuid)
        start = max(page - 1, 0) * page_size
        return rows[start : start + page_size], len(rows)

    def query_ap_optical_history_all(self, ap_uuid: str) -> list[dict[str, object | None]]:
        return self.repository.list_fit_ap_optical_history_by_ap(ap_uuid, limit=100000)

    def get_latest_optical_summary(self, ac_device_uuid: str, ap_uuid: str) -> dict[str, object | None]:
        return self.repository.get_fit_ap_optical_by_uuid(ac_device_uuid, ap_uuid) or {}

    @staticmethod
    def raw_log_dir(record: dict[str, object | None]) -> Path | None:
        raw_path = str(record.get("raw_log_path") or "").strip()
        if not raw_path:
            return None
        path = Path(raw_path)
        return path.parent if path.suffix else path
