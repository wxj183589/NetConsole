from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from netconsole.models.device import Device
from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.repositories.config_snapshot_repository import ConfigSnapshotRepository
from netconsole.services.config_lifecycle_service import ConfigLifecycleService, ConfigOperationResult, run_batch_config_download


class ConfigLifecycleWorker(QThread):
    result_ready = Signal(object)

    def __init__(
        self,
        action: str,
        db_path: str | Path,
        site_name: str,
        device_uuid: str | None = None,
        device_uuids: list[str] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.action = action
        self.db_path = Path(db_path)
        self.site_name = site_name
        self.device_uuid = str(device_uuid or "")
        self.device_uuids = [str(uuid) for uuid in device_uuids or [] if uuid]

    def run(self) -> None:
        database = Database(self.db_path)
        repository = ConfigSnapshotRepository(database)
        service = ConfigLifecycleService(self.site_name, database, PathResolver(), repository)
        if self.action == "batch_fetch":
            devices = [_device_by_uuid(database, uuid) for uuid in self.device_uuids]
            result = run_batch_config_download(devices, lambda: service)
        elif not self.device_uuid:
            result = ConfigOperationResult(False, "", "", [], error_message="No device selected.")
        else:
            device = _device_by_uuid(database, self.device_uuid)
            if self.action == "save":
                result = service.save_force(device)
            elif self.action == "fetch":
                result = service.fetch_configs(device)
            else:
                result = ConfigOperationResult(False, str(device.device_uuid or ""), "", [], error_message=f"Unknown action: {self.action}")
        self.result_ready.emit(result)


def _device_by_uuid(database: Database, device_uuid: str) -> Device:
    with database.connect() as conn:
        row = conn.execute("SELECT * FROM devices WHERE device_uuid = ?", (device_uuid,)).fetchone()
    if row is None:
        raise KeyError(f"Device not found: {device_uuid}")
    return Device.from_mapping(dict(row))
