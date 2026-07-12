from __future__ import annotations

from pathlib import Path

from netconsole.repositories.device_fact_repository import DeviceFactRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.utils.interface_normalize import normalize_interface_name


class TracksideOpticalHistoryService:
    def __init__(self, repository: DeviceRepository) -> None:
        self.repository = repository
        self.fact_repository = DeviceFactRepository(repository.database)

    def query_interface_history(self, device_uuid: str, interface_name: str, page: int = 1, page_size: int = 200) -> tuple[list[dict[str, object | None]], int]:
        all_rows = self.query_interface_history_all(device_uuid, interface_name)
        start = max(page - 1, 0) * page_size
        return all_rows[start : start + page_size], len(all_rows)

    def query_interface_history_all(self, device_uuid: str, interface_name: str) -> list[dict[str, object | None]]:
        wanted = normalize_interface_name(interface_name).casefold()
        devices = {str(device.device_uuid or ""): device for device in self.repository.list()}
        device = devices.get(device_uuid)
        rows = self.fact_repository.list_optical_history(device_uuid, interface_name)
        if not rows and wanted != interface_name.casefold():
            rows = self.fact_repository.list_optical_history(device_uuid, normalize_interface_name(interface_name))
        normalized_rows = []
        for row in rows:
            if normalize_interface_name(row.get("interface_name")).casefold() != wanted:
                continue
            normalized_rows.append(
                {
                    **row,
                    "source_device_name": device.name if device is not None else row.get("device_uuid"),
                    "source_device_id": device_uuid,
                    "host": device.ip_address if device is not None else "",
                    "optical_status": row.get("status"),
                    "session_id": row.get("collect_run_uuid"),
                }
            )
        return sorted(normalized_rows, key=lambda item: (str(item.get("collected_at") or ""), str(item.get("id") or "")), reverse=True)

    @staticmethod
    def raw_log_dir(record: dict[str, object | None]) -> Path | None:
        raw_path = str(record.get("raw_log_path") or "").strip()
        if not raw_path:
            return None
        path = Path(raw_path)
        return path.parent if path.suffix else path
