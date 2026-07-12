from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from netconsole.core.paths import PathResolver
from netconsole.models.wireless_scan_models import WirelessAdapter
from netconsole.services.network_tools.wireless_scan_service import WirelessScanService


class WirelessAdapterLoadWorker(QThread):
    completed = Signal(list)
    failed = Signal(str)

    def __init__(self, site_name: str, paths: PathResolver, parent=None) -> None:
        super().__init__(parent)
        self.site_name = site_name
        self.paths = paths

    def run(self) -> None:
        try:
            adapters = WirelessScanService(self.site_name, self.paths).list_adapters()
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.completed.emit(adapters)


class WirelessScanWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, site_name: str, paths: PathResolver, adapter: WirelessAdapter | None, scan_source: str = "auto", parent=None) -> None:
        super().__init__(parent)
        self.site_name = site_name
        self.paths = paths
        self.adapter = adapter
        self.scan_source = scan_source

    def run(self) -> None:
        try:
            result = WirelessScanService(self.site_name, self.paths, scan_source=self.scan_source).scan(self.adapter)
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.completed.emit(result)
