from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.services.rail_transit.car_network_diagnostic import CarNetworkDiagnosticService, CarNetworkNode, CarNetworkTrain


class CarNetworkDiagnosticWorker(QThread):
    progress = Signal(str, object)
    progress_changed = Signal(int, str)
    stage_changed = Signal(str)
    task_started = Signal(dict)
    task_finished = Signal(dict)
    node_state_changed = Signal(dict)
    link_state_changed = Signal(dict)
    diagnosis_message = Signal(str)
    log_line = Signal(str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        nodes: list[CarNetworkNode],
        train: CarNetworkTrain | None,
        ac_devices: list[Device],
        core_devices: list[Device],
        paths: PathResolver | None = None,
        site_name: str = "",
        core_discovery: dict[str, object] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.nodes = nodes
        self.train = train
        self.ac_devices = ac_devices
        self.core_devices = core_devices
        self.paths = paths
        self.site_name = site_name
        self.core_discovery = core_discovery
        self.cancel_requested = False

    def cancel(self) -> None:
        self.cancel_requested = True
        self.requestInterruption()

    def run(self) -> None:
        try:
            service = CarNetworkDiagnosticService(
                self.nodes,
                train=self.train,
                ac_devices=self.ac_devices,
                core_devices=self.core_devices,
                paths=self.paths,
                site_name=self.site_name,
                core_discovery=self.core_discovery,
                cancel_checker=lambda: self.cancel_requested or self.isInterruptionRequested(),
            )
            result = service.run(self._handle_progress)
            self.completed.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))

    def _handle_progress(self, stage: str, payload: object) -> None:
        self.progress.emit(stage, payload)
        if stage == "progress_meta" and isinstance(payload, dict):
            self.progress_changed.emit(int(payload.get("percent") or 0), str(payload.get("message") or ""))
        elif stage == "stage":
            self.stage_changed.emit(str(payload))
            self.log_line.emit(str(payload))
        elif stage == "task_started" and isinstance(payload, dict):
            self.task_started.emit(payload)
            self.log_line.emit(str(payload.get("message") or ""))
        elif stage == "task_finished" and isinstance(payload, dict):
            self.task_finished.emit(payload)
            self.log_line.emit(str(payload.get("message") or ""))
        elif stage == "diagnosis":
            self.diagnosis_message.emit(str(payload))
            self.log_line.emit(str(payload))
