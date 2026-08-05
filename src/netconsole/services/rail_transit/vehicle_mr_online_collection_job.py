from __future__ import annotations

from netconsole.core.database import Database
from netconsole.models.online_mr_models import OnlineMrConnectionConfig
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.job_center.job_context import JobContext
from netconsole.services.netmiko_connection import connection_targets
from netconsole.services.vehicle_mr_online import (
    VehicleMrOnlineCollector,
    VehicleMrOnlineSnapshot,
    VehicleMrOnlineStore,
    build_mapping_lookup,
    build_mapping_trains,
    build_registered_trains,
    is_ac_device,
    load_group_names,
    load_trackside_ap_lookup,
)


def run_vehicle_mr_online_collection(context: JobContext) -> dict[str, object]:
    """Run the Qt-proven AC mesh-link collector as a cancellable Job Center task."""

    context.check_cancelled()
    site_id = str(context.params.get("site_name") or "").strip()
    if not site_id:
        raise ValueError("列车在线连续采集缺少局点")
    try:
        device_id = int(context.params.get("ac_device_id") or 0)
    except (TypeError, ValueError):
        device_id = 0
    if device_id <= 0:
        raise ValueError("请选择无线控制器 AC")
    interval_seconds = max(3, min(300, int(context.params.get("interval_seconds") or 10)))
    repository = DeviceRepository(Database(context.paths.site_db_path(site_id)))
    try:
        ac = repository.get(device_id)
    except KeyError as exc:
        raise ValueError("所选无线控制器 AC 不存在") from exc
    if not is_ac_device(ac):
        raise ValueError("所选设备不是无线控制器 AC")
    protocol, port, username, password = _connection_fields(ac)
    if not protocol or not ac.primary_address or not username or not password:
        raise ValueError("AC 连接信息不完整")

    store = VehicleMrOnlineStore(context.paths, site_id)
    devices = repository.list()
    mappings = store.list_mappings()
    registered = {
        **build_registered_trains(devices, load_group_names(repository, site_id)),
        **build_mapping_trains(mappings),
    }
    collector = VehicleMrOnlineCollector(
        ac=ac,
        site_name=site_id,
        interval_seconds=interval_seconds,
        store=store,
        registered_trains=registered,
        identity_query_service=load_trackside_ap_lookup(repository),
        mapping_lookup=build_mapping_lookup(mappings),
        connection_config=OnlineMrConnectionConfig(
            site=site_id,
            mr_id=f"ac-{ac.id or ac.name}",
            mr_name=ac.name,
            safe_mr_name="vehicle_mr_online",
            device_id=ac.id,
            device_name=ac.name,
            host=ac.primary_address,
            protocol=protocol,
            port=port,
            username=username,
            password=password,
            command_timeout=15,
            connection_targets=tuple(connection_targets(ac)),
        ),
    )
    last_error = ""

    def report(snapshot: VehicleMrOnlineSnapshot) -> None:
        nonlocal last_error
        last_error = snapshot.error_message
        message = f"{snapshot.status}；已采集 {collector.sample_index} 次"
        if snapshot.ac_time:
            message += f"；AC 时间 {snapshot.ac_time}"
        context.progress("vehicle_mr_online_collection", 0, 0, message)

    context.progress("vehicle_mr_online_collection", 0, 0, "正在连接无线控制器 AC")
    collector.run_forever(report, should_cancel=context.should_cancel)
    context.check_cancelled()
    if last_error:
        raise RuntimeError(last_error)
    return {
        "session_id": collector.session_id,
        "sample_count": collector.sample_index,
        "status": "已停止",
        "ac_device_id": device_id,
        "interval_seconds": interval_seconds,
    }


def _connection_fields(device) -> tuple[str, int, str, str]:
    if device.ssh_enabled:
        return "SSH", int(device.ssh_port or 22), str(device.ssh_username or "").strip(), str(device.ssh_password or "")
    if device.telnet_enabled:
        return "Telnet", int(device.telnet_port or 23), str(device.telnet_username or "").strip(), str(device.telnet_password or "")
    return "", 0, "", ""


__all__ = ["run_vehicle_mr_online_collection"]
