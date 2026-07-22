from __future__ import annotations

from netconsole.core.database import Database
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.job_center.job_context import JobContext
from netconsole.services.rail_transit.car_network_diagnostic import (
    NODE_ORDER,
    CarNetworkDiagnosticService,
    CarNetworkPointTableStore,
    CarNetworkTrain,
    build_car_network_trains,
    discover_ac_devices,
    discover_core_switch_candidates,
)
from netconsole.services.rail_transit.train_identity import train_identity_matches


def run_car_network_diagnostic(context: JobContext) -> dict[str, object]:
    """执行 Qt 车内通信页同一套真实诊断服务。"""

    site_id = str(context.params.get("site_name") or "").strip()
    train_id = str(context.params.get("train_id") or "").strip()
    if not site_id or not train_id:
        raise ValueError("车内通信检测缺少局点或列车标识")

    repository = DeviceRepository(Database(context.params["db_path"]))
    stored_nodes = CarNetworkPointTableStore(context.paths, site_id).load()
    by_name = {
        node.node_name: node
        for node in stored_nodes
        if train_identity_matches(
            (train_id,),
            (node.train_id, node.train_no, node.display_name),
        )
    }
    nodes = [by_name[name] for name in NODE_ORDER if name in by_name]
    if not nodes:
        raise ValueError("所选列车没有可用的车内通信点表")

    trains = build_car_network_trains(repository, site_id)
    train = next(
        (
            item
            for item in trains
            if train_identity_matches((train_id,), (item.train_id, item.train_no, item.display_name))
        ),
        None,
    )
    needs_bound_device = any(
        node.is_mr
        and node.device_id
        and (
            train is None
            or (node.normalized_name == "TC1-MR" and train.tc1_device is None)
            or (node.normalized_name == "TC2-MR" and train.tc2_device is None)
        )
        for node in nodes
    )
    devices_by_id = {
        str(device.id): device
        for device in repository.list()
        if getattr(device, "id", None) is not None
    } if needs_bound_device else {}
    point_devices = {
        node.normalized_name: devices_by_id.get(str(node.device_id))
        for node in nodes
        if node.is_mr and node.device_id
    }
    first_node = nodes[0]
    train = CarNetworkTrain(
        train_id=train.train_id if train is not None else str(context.params.get("canonical_train_id") or first_node.train_id or train_id),
        train_no=train.train_no if train is not None else str(context.params.get("train_no") or first_node.train_no or ""),
        display_name=train.display_name if train is not None else str(context.params.get("display_name") or first_node.display_name or train_id),
        tc1_device=(train.tc1_device if train is not None else None) or point_devices.get("TC1-MR"),
        tc2_device=(train.tc2_device if train is not None else None) or point_devices.get("TC2-MR"),
    )

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
    payload = result.to_json_dict()
    for key in (
        "canonical_train_id",
        "point_table_revision",
        "online_snapshot_time",
        "online_status",
        "ct_mr_id",
        "ct_mr_name",
        "tc_mr_id",
        "tc_mr_name",
    ):
        value = context.params.get(key)
        if value not in (None, ""):
            payload[key] = value
    return payload


__all__ = ["run_car_network_diagnostic"]
