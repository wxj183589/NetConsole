from __future__ import annotations

from pathlib import Path

from netconsole.core.database import Database
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services import netmiko_connection
from netconsole.services.job_center.job_context import (
    BackgroundTaskCancelled,
    JobContext,
)
from netconsole.services.netmiko_connection import (
    CommandCancelled,
    build_netmiko_params,
    choose_connection_target,
    prepared_connection_target,
    sanitize_sensitive_text,
)
from netconsole.services.rail_transit.switch_vendor_sample import (
    collect_switch_vendor_sample,
)


def run_switch_vendor_sample_collect(
    context: JobContext,
) -> dict[str, object]:
    site_id = str(context.params.get("site_name") or "").strip()
    device_uuid = str(context.params.get("device_uuid") or "").strip()
    if not site_id or not device_uuid:
        raise ValueError("厂商适配采样缺少局点或设备标识")
    repository = DeviceRepository(Database(context.paths.site_db_path(site_id)))
    device = repository.get_by_uuid(device_uuid)
    if device is None:
        raise ValueError("厂商适配采样设备不存在")
    output_path = Path(str(context.params.get("artifact_output_path") or ""))
    _validate_output_path(context, site_id, output_path)
    target = choose_connection_target(device)
    if target is None:
        raise ValueError("设备未启用可用的 SSH/Telnet 连接")

    connection = None
    context.check_cancelled()
    context.progress("switch_vendor_sample.connect", 0, 1, "正在连接采样设备")
    try:
        with prepared_connection_target(target) as prepared:
            with netmiko_connection.ssh_connection_context(
                "switch_sample",
                "collect",
                device_uuid=str(device.device_uuid or device.id or ""),
            ):
                connection = netmiko_connection.ConnectHandler(
                    **build_netmiko_params(prepared)
                )
            context.progress(
                "switch_vendor_sample.connect", 1, 1, "采样设备连接成功"
            )
            result = collect_switch_vendor_sample(
                device,
                connection,
                output_path=output_path,
                vendor=str(context.params.get("vendor") or ""),
                command_profile=str(
                    context.params.get("command_profile") or ""
                ),
                selected_interface=str(
                    context.params.get("selected_interface") or ""
                ),
                requested_commands=tuple(
                    str(value)
                    for value in (
                        context.params.get("requested_commands") or ()
                    )
                ),
                cancel_check=context.should_cancel,
                progress_callback=context.progress,
            )
    except CommandCancelled as exc:
        if context.should_cancel is not None and context.should_cancel():
            context.check_cancelled()
        raise BackgroundTaskCancelled("厂商适配采样已取消") from exc
    except BackgroundTaskCancelled:
        raise
    except Exception as exc:
        raise RuntimeError(
            sanitize_sensitive_text(str(exc), device)
            or "厂商适配采样失败"
        ) from exc
    finally:
        if connection is not None:
            try:
                connection.disconnect()
            except Exception:
                pass

    context.progress(
        "switch_vendor_sample.package", 1, 1, "厂商采样 Artifact 已生成"
    )
    return {
        **result.to_dict(),
        "artifact_count": 1,
        "parser_version": "zte-zxr10-5960x-es-v2.document-sample.v1",
        "verification_status": "DOCUMENT_SAMPLE_ONLY",
    }


def _validate_output_path(
    context: JobContext,
    site_id: str,
    output_path: Path,
) -> None:
    root = (
        context.paths.trackside_ap_outputs_dir(site_id) / "vendor_samples"
    ).resolve()
    resolved = output_path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("厂商采样 Artifact 路径不在受控目录") from exc
    if resolved == root or resolved.suffix.casefold() != ".zip":
        raise ValueError("厂商采样 Artifact 路径无效")


__all__ = ["run_switch_vendor_sample_collect"]
