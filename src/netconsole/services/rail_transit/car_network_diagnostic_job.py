from __future__ import annotations

from netconsole.core.database import Database
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.job_center.job_context import JobContext
from netconsole.services.rail_transit.car_network_diagnostic import (
    NODE_ORDER,
    CarNetworkDiagnosticService,
    CarNetworkPointTableStore,
    build_car_network_trains,
    discover_ac_devices,
    discover_core_switch_candidates,
)


def run_car_network_diagnostic(context: JobContext) -> dict[str, object]:
    """执行 Qt 车内通信页同一套真实诊断服务。"""

    site_id = str(context.params.get("site_name") or "").strip()
    train_id = str(context.params.get("train_id") or "").strip()
    if not site_id or not train_id:
        raise ValueError("车内通信检测缺少局点或列车标识")

    repository = DeviceRepository(Database(context.params["db_path"]))
    trains = build_car_network_trains(repository, site_id)
    train = next(
        (
            item
            for item in trains
            if train_id in {item.train_id, item.train_no, item.display_name}
        ),
        None,
    )
    if train is None:
        raise ValueError("所选列车不存在或未绑定正式车载 MR 设备")

    stored_nodes = CarNetworkPointTableStore(context.paths, site_id).load()
    by_name = {
        node.node_name: node
        for node in stored_nodes
        if node.train_id == train.train_id or node.train_no == train.train_no
    }
    nodes = [by_name[name] for name in NODE_ORDER if name in by_name]
    if not nodes:
        raise ValueError("所选列车没有可用的车内通信点表")

    core_candidates = discover_core_switch_candidates(repository, site_id)
    core_devices = [device for device, candidate in core_candidates if candidate.selected]
    core_discovery = {
        "candidates": [
            {
                "device_name": candidate.device_name,
                "system_name": candidate.system_name,
                "group": candidate.group,
                "host": candidate.host,
                "selected": candidate.selected,
                "reason": candidate.reason,
            }
            for _device, candidate in core_candidates
        ],
        "selected_count": len(core_devices),
    }

    def cancelled() -> bool:
        context.check_cancelled()
        return False

    def progress(stage: str, payload: object) -> None:
        if stage == "progress_meta" and isinstance(payload, dict):
            current = int(payload.get("completed") or payload.get("percent") or 0)
            total = int(payload.get("total") or 100)
            context.progress(stage, current, total, str(payload.get("message") or ""))
        elif stage in {"stage", "diagnosis"}:
            context.progress(stage, 0, 0, str(payload or ""))
        elif stage in {"task_started", "task_finished"} and isinstance(payload, dict):
            context.progress(stage, 0, 0, str(payload.get("message") or ""))

    result = CarNetworkDiagnosticService(
        nodes,
        train=train,
        ac_devices=discover_ac_devices(repository),
        core_devices=core_devices,
        paths=context.paths,
        site_name=site_id,
        core_discovery=core_discovery,
        cancel_checker=cancelled,
    ).run(progress)
    return result.to_json_dict()


__all__ = ["run_car_network_diagnostic"]
