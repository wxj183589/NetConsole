from __future__ import annotations

from pathlib import Path
from threading import Event

from PySide6.QtCore import QThread, Signal

from netconsole.repositories.cloud_sync_repository import CloudSyncRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.cloud_sync.wps_ksheet_sync_service import PROFILE_NAME, TracksideApWpsKSheetSyncService


class WpsKSheetSyncThread(QThread):
    progress_changed = Signal(str)
    sync_finished = Signal(object)
    sync_failed = Signal(str)

    def __init__(
        self,
        repository: DeviceRepository,
        site_id: str,
        *,
        local_export_path: Path | None = None,
        header_getter=None,
        force: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.repository = repository
        self.site_id = site_id
        self.local_export_path = Path(local_export_path) if local_export_path else None
        self.header_getter = header_getter
        self.force = force
        self._cancel_event = Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        try:
            service = TracksideApWpsKSheetSyncService(
                self.repository,
                CloudSyncRepository(self.repository.database),
                header_getter=self.header_getter,
            )
            result = service.sync_trackside_ap_business(
                self.site_id,
                PROFILE_NAME,
                local_export_path=self.local_export_path,
                progress_callback=lambda key, _value=None: self.progress_changed.emit(key),
                cancel_event=self._cancel_event,
                force=self.force,
            )
        except Exception as exc:
            self.sync_failed.emit(str(exc))
            return
        self.sync_finished.emit(result)

