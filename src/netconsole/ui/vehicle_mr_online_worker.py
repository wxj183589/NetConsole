from __future__ import annotations

import threading

from PySide6.QtCore import QThread, Signal

from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.models.online_mr_models import OnlineMrConnectionConfig
from netconsole.services.vehicle_mr_online import (
    MatchedAp,
    TrainIdentity,
    VehicleMrConnectionFactory,
    VehicleMrOnlineCollector,
    VehicleMrOnlineStore,
    VehicleMrTrainState,
)


class VehicleMrOnlineWorker(QThread):
    snapshot = Signal(object)
    completed = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        ac: Device,
        site_name: str,
        interval_seconds: int,
        paths: PathResolver,
        registered_trains: dict[str, VehicleMrTrainState],
        ap_lookup: dict[str, MatchedAp],
        mapping_lookup: dict[str, TrainIdentity] | None,
        connection_config: OnlineMrConnectionConfig,
        connection_factory: VehicleMrConnectionFactory | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.ac = ac
        self.site_name = site_name
        self.interval_seconds = interval_seconds
        self.paths = paths
        self.registered_trains = registered_trains
        self.ap_lookup = ap_lookup
        self.mapping_lookup = mapping_lookup
        self.connection_config = connection_config
        self.connection_factory = connection_factory
        self.collector: VehicleMrOnlineCollector | None = None
        self._cancel_requested = threading.Event()

    def cancel(self) -> None:
        self._cancel_requested.set()
        collector = self.collector
        if collector is not None:
            collector.cancelled = True

    def run(self) -> None:
        try:
            store = VehicleMrOnlineStore(self.paths, self.site_name)
            self.collector = VehicleMrOnlineCollector(
                ac=self.ac,
                site_name=self.site_name,
                interval_seconds=self.interval_seconds,
                store=store,
                registered_trains=self.registered_trains,
                ap_lookup=self.ap_lookup,
                mapping_lookup=self.mapping_lookup,
                connection_config=self.connection_config,
                connection_factory=self.connection_factory,
            )
            if self._cancel_requested.is_set():
                self.collector.cancelled = True
            self.collector.run_forever(lambda snapshot: self.snapshot.emit(snapshot))
            self.completed.emit(self.collector.session_id)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.collector = None
