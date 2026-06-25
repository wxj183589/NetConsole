from __future__ import annotations

from PySide6.QtCore import QThread, Signal

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
        store: VehicleMrOnlineStore,
        registered_trains: dict[str, VehicleMrTrainState],
        ap_lookup: dict[str, MatchedAp],
        mapping_lookup: dict[str, TrainIdentity] | None,
        connection_config: OnlineMrConnectionConfig,
        connection_factory: VehicleMrConnectionFactory | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.collector = VehicleMrOnlineCollector(
            ac=ac,
            site_name=site_name,
            interval_seconds=interval_seconds,
            store=store,
            registered_trains=registered_trains,
            ap_lookup=ap_lookup,
            mapping_lookup=mapping_lookup,
            connection_config=connection_config,
            connection_factory=connection_factory,
        )

    def cancel(self) -> None:
        self.collector.cancelled = True

    def run(self) -> None:
        try:
            self.collector.run_forever(lambda snapshot: self.snapshot.emit(snapshot))
            self.completed.emit(self.collector.session_id)
        except Exception as exc:
            self.failed.emit(str(exc))
