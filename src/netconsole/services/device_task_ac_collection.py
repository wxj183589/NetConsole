"""Report-only AC wireless and MESH collection using existing CLI contracts."""
from __future__ import annotations

from dataclasses import asdict
import re

from netconsole.models.device import Device
from netconsole.parsers.h3c.ac.wlan_ap_address_parser import parse_wlan_ap_addresses
from netconsole.parsers.h3c.ac.wlan_ap_parser import parse_wlan_ap_list, parse_wlan_ap_summary
from netconsole.parsers.h3c.ac.wlan_ap_radio_parser import parse_wlan_ap_radios
from netconsole.parsers.h3c.version_parser import parse_version
from netconsole.services.ac.mesh_link_refresh_service import (
    AcMeshLinkRefreshWorkerService,
    MESH_LINK_REFRESH_COMMANDS,
    MESH_LINK_V5_COMMAND,
)
from netconsole.services.device_command_profile_service import (
    DeviceCommandProfileNotFound,
    resolve_h3c_capability,
)
from netconsole.services.job_center.job_context import JobContext
from netconsole.services.h3c_ac_collect_service import CLI_FAILURE_MARKERS
from netconsole.services.job_center.web_export_event_safety import redact_web_task_text
from netconsole.services.netmiko_connection import (
    run_netmiko_with_retry,
    safe_send_command_with_paging,
    sanitize_sensitive_text,
)
from netconsole.services.vehicle_mr_online import (
    H3CComwareV5VehicleMrMeshLinkParser,
    H3CComwareV9VehicleMrMeshLinkParser,
)


def _unsupported(output: str) -> bool:
    return bool(re.search(r"\b(?:unrecognized command|incomplete command|wrong parameter|unsupported command|not supported)\b",
                          output, flags=re.IGNORECASE))


def collect_ac_task(context: JobContext, site: str, kind: str, device: Device) -> dict[str, object]:
    command_results = []

    def execute(connection, target):
        executed = []

        def read(command: str) -> str:
            context.check_cancelled()
            output = safe_send_command_with_paging(
                connection, command, encoding=target.encoding,
                command_timeout=max(5, min(120, int(context.params.get("command_timeout") or 40))),
                max_pages=32, max_output_bytes=128_000, cancel_check=context.should_cancel,
            ).output
            context.check_cancelled()
            executed.append(command)
            unsupported = _unsupported(output)
            lowered = output.casefold()
            failed = any(marker.casefold() in lowered for marker in CLI_FAILURE_MARKERS)
            command_status = "success"
            if unsupported:
                command_status = "unavailable"
            elif failed:
                command_status = "failed"
            command_results.append({"command": command, "status": command_status,
                                    "output": redact_web_task_text(sanitize_sensitive_text(output, device))[:4096]})
            if failed and not unsupported:
                raise ValueError(f"设备拒绝查询命令：{command}")
            return output

        if kind == "wireless":
            version_output = read("display version")
            version = parse_version(version_output).get("software_version") or version_output
            try:
                capabilities = [resolve_h3c_capability(device, capability, software_version=version)
                                for capability in ("wlan_ap_all", "wlan_ap_address", "wlan_ap_radio")]
            except DeviceCommandProfileNotFound:
                return {"status": "skipped", "message": "当前 AC 软件版本未解析到受支持的无线命令能力"}
            outputs = []
            for capability in capabilities:
                output = read(capability.commands[0])
                if _unsupported(output) and capability.fallback_commands:
                    output = read(capability.fallback_commands[0])
                if _unsupported(output):
                    return {"status": "skipped", "message": "AC 软件不支持所需无线信息命令", "commands": executed}
                if not output.strip():
                    return {"status": "failed", "message": "AC 未返回受支持的无线信息回显", "commands": executed}
                outputs.append(output)
            summary = parse_wlan_ap_summary(outputs[0])
            aps = parse_wlan_ap_list(outputs[0])
            addresses = list(parse_wlan_ap_addresses(outputs[1]).values())
            radios = list(parse_wlan_ap_radios(outputs[2]).values())
            records = [{"record_type": category, **row}
                       for category, rows in (("ap", aps), ("address", addresses), ("radio", radios))
                       for row in rows]
            if not aps and summary["total_aps"] != 0:
                return {"status": "failed", "message": "无线回显无法解析，且未明确返回零 AP", "commands": executed}
            incomplete = bool(aps) and (not addresses or not radios)
            return {"status": "partial" if incomplete else "success",
                    "message": "AP 地址或射频明细未解析到记录" if incomplete else "",
                    "records": records[:128], "record_count": len(records),
                    "records_truncated": len(records) > 128, "wireless_summary": summary, "commands": executed}

        clock = read(MESH_LINK_REFRESH_COMMANDS[1])
        output = read(MESH_LINK_REFRESH_COMMANDS[2])
        parser = H3CComwareV9VehicleMrMeshLinkParser()
        if AcMeshLinkRefreshWorkerService._needs_v5_fallback(output):
            output = read(MESH_LINK_V5_COMMAND)
            parser = H3CComwareV5VehicleMrMeshLinkParser()
        if _unsupported(output):
            return {"status": "skipped", "message": "AC 软件不支持 MESH 查询命令", "commands": executed}
        if re.search(r"\bWMESH is not configured\b", output, flags=re.IGNORECASE):
            return {"status": "skipped", "message": "AC 未配置 WMESH", "records": [],
                    "record_count": 0, "commands": executed}
        AcMeshLinkRefreshWorkerService._validate_mesh_output(output)
        parsed = parser.parse(f"{clock}\n{output}")
        if not parsed.links and not AcMeshLinkRefreshWorkerService._is_valid_empty(output):
            return {"status": "failed", "message": "MESH 回显无法解析，且未明确返回零链路", "commands": executed}
        if parsed.parse_status.casefold() not in {"ok", "success"}:
            return {"status": "failed", "message": "MESH 回显时间或格式无法解析", "commands": executed}
        return {"status": "success", "records": [asdict(link) for link in parsed.links[:128]],
                "record_count": len(parsed.links), "records_truncated": len(parsed.links) > 128,
                "ac_time": parsed.ac_time, "commands": executed}

    result = run_netmiko_with_retry(device, execute, paths=context.paths, site_id=site)
    return {**result, "command_results": command_results}
