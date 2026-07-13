from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.online_mr_models import (
    FpingConfig,
    IperfTrafficConfig,
    OnlineMrConnectionConfig,
    OnlineMrIntervals,
    OnlineMrRadioConfig,
    OnlineMrSessionMeta,
    OnlineMrSnapshot,
    OnlineMrTaskToggles,
)
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.netmiko_connection import connection_targets


def collection_config_to_payload(config: OnlineMrConnectionConfig) -> dict[str, Any]:
    return {
        "site": config.site,
        "mr_id": config.mr_id,
        "mr_name": config.mr_name,
        "safe_mr_name": config.safe_mr_name,
        "device_id": config.device_id,
        "device_name": config.device_name,
        "host": config.host,
        "protocol": config.protocol,
        "port": config.port,
        "username": config.username,
        "password": config.password,
        "intervals": config.intervals.as_dict(),
        "tasks": {
            "mesh_link": config.tasks.mesh_link,
            "channel_busy": config.tasks.channel_busy,
            "ap_radio_statistics": config.tasks.ap_radio_statistics,
            "switch_history": config.tasks.switch_history,
            "interface_rate": config.tasks.interface_rate,
            "wireless_status": config.tasks.wireless_status,
        },
        "radio": config.radio.as_dict(),
        "fping": config.fping.as_dict(),
        "iperf": config.iperf.as_dict(),
        "auto_reconnect": config.auto_reconnect,
        "reconnect_interval": config.reconnect_interval,
        "max_reconnect": config.max_reconnect,
        "command_timeout": config.command_timeout,
        "duration_minutes": config.duration_minutes,
        "connection_method": config.connection_method,
        "collect_config_on_start": config.collect_config_on_start,
    }


def collection_config_from_payload(payload: dict[str, Any], paths: PathResolver) -> OnlineMrConnectionConfig:
    values = dict(payload or {})
    site = str(values.get("site") or "demo")
    device_id = _optional_int(values.get("device_id"))
    device = None
    if device_id is not None:
        db_path = Path(str(values.get("db_path") or paths.site_db_path(site)))
        if db_path.exists():
            device = DeviceRepository(Database(db_path)).get(device_id)

    intervals = dict(values.get("intervals") or {})
    tasks = dict(values.get("tasks") or {})
    radio = dict(values.get("radio") or {})
    fping = dict(values.get("fping") or {})
    iperf = dict(values.get("iperf") or {})
    protocol = str(values.get("protocol") or "SSH")
    port = int(values.get("port") or (23 if protocol.casefold() == "telnet" else 22))
    username = str(values.get("username") or "")
    password = str(values.get("password") or "")
    host = str(values.get("host") or "")
    targets: tuple[object, ...] = ()
    if device is not None:
        targets = tuple(connection_targets(device))
        host = str(device.primary_address or host)
        if device.ssh_enabled:
            protocol, port = "SSH", int(device.ssh_port or 22)
            username, password = str(device.ssh_username or "").strip(), str(device.ssh_password or "")
        elif device.telnet_enabled:
            protocol, port = "Telnet", int(device.telnet_port or 23)
            username, password = str(device.telnet_username or "").strip(), str(device.telnet_password or "")

    return OnlineMrConnectionConfig(
        site=site,
        mr_id=str(values.get("mr_id") or device_id or ""),
        mr_name=str(values.get("mr_name") or getattr(device, "name", "") or ""),
        safe_mr_name=str(values.get("safe_mr_name") or f"device__{device_id or 0}"),
        device_id=device_id,
        device_name=str(values.get("device_name") or getattr(device, "name", "") or ""),
        host=host,
        protocol=protocol,
        port=port,
        username=username,
        password=password,
        intervals=OnlineMrIntervals(
            mesh_link=int(intervals.get("mesh_link") or 1),
            channel_busy=int(intervals.get("channel_busy") or 9),
            ap_radio_statistics=int(intervals.get("ap_radio_statistics") or 10),
            switch_history=int(intervals.get("switch_history") or 300),
            interface_rate=int(intervals.get("interface_rate") or 2),
            fping_interval_ms=int(intervals.get("fping_interval_ms") or 10),
            wireless_status=int(intervals.get("wireless_status") or 3),
        ),
        tasks=OnlineMrTaskToggles(
            mesh_link=bool(tasks.get("mesh_link", True)),
            channel_busy=bool(tasks.get("channel_busy", True)),
            ap_radio_statistics=bool(tasks.get("ap_radio_statistics", True)),
            switch_history=bool(tasks.get("switch_history", True)),
            interface_rate=bool(tasks.get("interface_rate", True)),
            wireless_status=bool(tasks.get("wireless_status", False)),
        ),
        radio=OnlineMrRadioConfig(
            channel_busy_radio=int(radio.get("channel_busy_radio") or 1),
            ap_radio_statistics_radio=int(radio.get("ap_radio_statistics_radio") or 1),
            wireless_status_radio=int(radio.get("wireless_status_radio") or 1),
        ),
        fping=FpingConfig(**_known_values(FpingConfig, fping)),
        iperf=IperfTrafficConfig(**_known_values(IperfTrafficConfig, iperf)),
        auto_reconnect=bool(values.get("auto_reconnect", True)),
        reconnect_interval=int(values.get("reconnect_interval") or 5),
        max_reconnect=_optional_int(values.get("max_reconnect")),
        command_timeout=int(values.get("command_timeout") or 15),
        duration_minutes=_optional_int(values.get("duration_minutes")),
        connection_targets=targets,
        connection_method=str(values.get("connection_method") or ""),
        collect_config_on_start=bool(values.get("collect_config_on_start", False)),
    )


def session_meta_from_payload(payload: dict[str, Any]) -> OnlineMrSessionMeta:
    started_at = datetime.fromisoformat(str(payload.get("started_at") or datetime.now().isoformat()))
    ended_text = str(payload.get("ended_at") or "")
    return OnlineMrSessionMeta(
        session_id=str(payload.get("session_id") or ""),
        site=str(payload.get("site") or ""),
        mr_id=str(payload.get("mr_id") or ""),
        mr_name=str(payload.get("mr_name") or ""),
        device_id=_optional_int(payload.get("device_id")),
        device_name=str(payload.get("device_name") or ""),
        host=str(payload.get("host") or ""),
        protocol=str(payload.get("protocol") or "SSH"),
        port=int(payload.get("port") or 22),
        started_at=started_at,
        connection_method=str(payload.get("connection_method") or ""),
        ended_at=datetime.fromisoformat(ended_text) if ended_text else None,
        status=str(payload.get("status") or "CREATED"),
        intervals=dict(payload.get("intervals") or {}),
        radio=dict(payload.get("radio") or {}),
        fping=dict(payload.get("fping") or {}),
        iperf=dict(payload.get("iperf") or {}),
        stats=dict(payload.get("stats") or {}),
        session_dir=Path(str(payload.get("session_dir"))) if payload.get("session_dir") else None,
        session_type=str(payload.get("session_type") or "realtime"),
        config_collect_enabled=bool(payload.get("config_collect_enabled", False)),
        config_collect_status=str(payload.get("config_collect_status") or "skipped"),
        config_file_path=str(payload.get("config_file_path") or ""),
        config_error=str(payload.get("config_error")) if payload.get("config_error") is not None else None,
        raw_log_path=str(payload.get("raw_log_path") or ""),
        init=dict(payload.get("init") or {}),
        configured_duration_minutes=_optional_int(payload.get("configured_duration_minutes")),
        duration_minutes=float(payload["duration_minutes"]) if payload.get("duration_minutes") is not None else None,
        stop_reason=str(payload.get("stop_reason") or ""),
        force_stopped=bool(payload.get("force_stopped", False)),
        traffic_summary=dict(payload.get("traffic_summary") or {}),
        finalization_warnings=[str(item) for item in list(payload.get("finalization_warnings") or [])],
        finalization_complete=bool(payload.get("finalization_complete", False)),
        package_available=bool(payload.get("package_available", False)),
        data_integrity=str(payload.get("data_integrity") or "unknown"),
    )


def snapshot_to_payload(snapshot: OnlineMrSnapshot) -> dict[str, Any]:
    return dict(snapshot.__dict__)


def snapshot_from_payload(payload: dict[str, Any]) -> OnlineMrSnapshot:
    return OnlineMrSnapshot(**_known_values(OnlineMrSnapshot, payload))


def _known_values(model_type: type, values: dict[str, Any]) -> dict[str, Any]:
    return {name: values[name] for name in model_type.__dataclass_fields__ if name in values}


def _optional_int(value: object) -> int | None:
    if value in {None, ""}:
        return None
    return int(value)
