from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from netconsole.adapters.trackside_switch import (
    SWITCH_VENDOR_SAMPLE_CONTEXT,
    resolve_trackside_switch_adapter,
)
from netconsole.models.device import Device
from netconsole.parsers.zte.zxr10 import ZTE_PARSER_VERSION
from netconsole.services.device_command_profile_service import (
    device_cli_output_is_unsupported,
)
from netconsole.services.netmiko_connection import (
    CommandCancelled,
    CommandOutputLimitExceeded,
    sanitize_sensitive_text,
)


SAMPLE_TASK_TYPE = "switch_vendor_sample_collect"
SAMPLE_ARCHIVE_FILES = (
    "manifest.json",
    "command-status.json",
    "version.txt",
    "interface-brief.txt",
    "interface-detail.txt",
    "optical-brief.txt",
    "optical-detail.txt",
    "lldp-global.txt",
    "lldp-interface.txt",
    "session-metadata.json",
)
_OUTPUT_FILES = SAMPLE_ARCHIVE_FILES[2:-1]


@dataclass(frozen=True)
class SwitchVendorSampleResult:
    status: str
    success_count: int
    failed_count: int
    unsupported_count: int
    timeout_count: int
    output_size: int
    command_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "success_count": self.success_count,
            "failed_count": self.failed_count,
            "unsupported_count": self.unsupported_count,
            "timeout_count": self.timeout_count,
            "output_size": self.output_size,
            "command_count": self.command_count,
        }


def collect_switch_vendor_sample(
    device: Device,
    connection: object,
    *,
    output_path: Path,
    vendor: str,
    command_profile: str,
    selected_interface: str = "",
    requested_commands: Iterable[str] = (),
    cancel_check: Callable[[], bool] | None = None,
    progress_callback: Callable[[str, int, int, str], None] | None = None,
) -> SwitchVendorSampleResult:
    adapter = resolve_trackside_switch_adapter(device)
    if adapter.vendor.casefold() != "zte":
        raise ValueError("第一阶段仅支持 ZTE 交换机厂商适配采样")
    if str(vendor or "").strip().casefold() != adapter.vendor.casefold():
        raise ValueError("采样厂商与设备 Adapter 不一致")
    if str(command_profile or "").strip() != adapter.profile_id:
        raise ValueError("采样命令 Profile 与设备 Adapter 不一致")
    plan = adapter.build_command_plan(
        selected_interface=selected_interface,
        requested_commands=requested_commands,
    )
    target = Path(output_path).resolve()
    if target.suffix.casefold() != ".zip":
        raise ValueError("厂商采样 Artifact 必须为 ZIP")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    started_at = _now()
    outputs = {name: [] for name in _OUTPUT_FILES}
    command_status: list[dict[str, object]] = []
    clean_outputs: dict[str, list[str]] = {}
    prompt = ""

    try:
        adapter.prepare_session(connection, cancel_check)
        if hasattr(connection, "find_prompt"):
            try:
                prompt = adapter.normalize_prompt(connection.find_prompt())
            except Exception:
                prompt = ""
        total = len(plan.items)
        for index, item in enumerate(plan.items, start=1):
            _check_cancelled(cancel_check)
            command_started = _now()
            success = False
            unsupported = False
            timeout = False
            output_size = 0
            page_count = 0
            error_message = ""
            raw_output = ""
            clean_output = ""
            try:
                result = adapter.collect_raw_output(
                    connection,
                    item.command,
                    cancel_check=cancel_check,
                    command_context=SWITCH_VENDOR_SAMPLE_CONTEXT,
                )
                raw_output = sanitize_sensitive_text(result.raw_output, device)
                clean_output = sanitize_sensitive_text(result.output, device)
                output_size = len(raw_output.encode("utf-8"))
                page_count = result.page_count
                unsupported = device_cli_output_is_unsupported(
                    device, clean_output
                )
                success = not unsupported
                if unsupported:
                    error_message = "设备返回不支持或无效命令"
            except CommandCancelled:
                raise
            except TimeoutError:
                timeout = True
                error_message = "命令执行超时"
            except CommandOutputLimitExceeded:
                error_message = "命令输出超过受控上限"
            except Exception as exc:
                error_message = sanitize_sensitive_text(str(exc), device)[
                    :240
                ] or exc.__class__.__name__
            command_ended = _now()
            if raw_output:
                outputs[item.output_file].append(
                    f"===== COMMAND: {item.command} =====\n{raw_output.rstrip()}\n"
                )
            clean_outputs.setdefault(item.selector, []).append(clean_output)
            command_status.append(
                {
                    "selector": item.selector,
                    "command": item.command,
                    "started_at": command_started,
                    "ended_at": command_ended,
                    "success": success,
                    "unsupported": unsupported,
                    "timeout": timeout,
                    "output_size": output_size,
                    "page_count": page_count,
                    "candidate": item.candidate,
                    "capability_status": item.status.value,
                    "error_message": error_message,
                }
            )
            if progress_callback is not None:
                progress_callback(
                    "switch_vendor_sample.command",
                    index,
                    max(total, 1),
                    f"正在采样 {item.selector}",
                )

        ended_at = _now()
        identity = _identity_payload(
            adapter,
            "\n".join(clean_outputs.get("device_version", ())),
        )
        output_size = sum(
            int(item.get("output_size") or 0) for item in command_status
        )
        success_count = sum(bool(item.get("success")) for item in command_status)
        unsupported_count = sum(
            bool(item.get("unsupported")) for item in command_status
        )
        timeout_count = sum(bool(item.get("timeout")) for item in command_status)
        failed_count = len(command_status) - success_count
        status = (
            "SUCCESS"
            if failed_count == 0
            else "PARTIAL_SUCCESS"
            if success_count > 0
            else "FAILED"
        )
        manifest = {
            "schema_version": "netconsole.switch-vendor-sample.v1",
            "vendor": adapter.vendor,
            "device_model": str(
                identity.get("model") or adapter.model_family
            ),
            "software_version": str(identity.get("software_version") or ""),
            "command": [item["command"] for item in command_status],
            "started_at": started_at,
            "ended_at": ended_at,
            "success": failed_count == 0,
            "unsupported": unsupported_count,
            "timeout": timeout_count,
            "output_size": output_size,
            "parser_version": ZTE_PARSER_VERSION,
            "verification_status": "DOCUMENT_SAMPLE_ONLY",
            "command_profile": adapter.profile_id,
            "commands": command_status,
        }
        session_metadata = {
            "device_uuid": str(device.device_uuid or ""),
            "device_name": str(device.name or ""),
            "vendor": adapter.vendor,
            "platform": adapter.platform_family,
            "product_family": adapter.model_family,
            "command_profile": adapter.profile_id,
            "selected_interface": plan.selected_interface,
            "requested_commands": list(
                dict.fromkeys(
                    str(value or "").strip()
                    for value in requested_commands
                    if str(value or "").strip()
                )
            ),
            "prompt": prompt,
            "privilege_required": adapter.command_profile.privilege_required,
            "enable_command": adapter.command_profile.enable_command,
            "enable_level": adapter.command_profile.enable_level,
            "enable_secret_configured": adapter.command_profile.enable_secret_configured,
            "started_at": started_at,
            "ended_at": ended_at,
        }
        archive_payload = {
            "manifest.json": _json_text(manifest),
            "command-status.json": _json_text(command_status),
            "session-metadata.json": _json_text(session_metadata),
            **{
                name: "\n".join(outputs[name]).rstrip() + (
                    "\n" if outputs[name] else ""
                )
                for name in _OUTPUT_FILES
            },
        }
        _write_archive(temporary, target, archive_payload)
        return SwitchVendorSampleResult(
            status=status,
            success_count=success_count,
            failed_count=failed_count,
            unsupported_count=unsupported_count,
            timeout_count=timeout_count,
            output_size=output_size,
            command_count=len(command_status),
        )
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _identity_payload(adapter: object, output: str) -> dict[str, object]:
    if not output.strip():
        return {}
    parsed = adapter.parse_device_identity(output)
    value = getattr(parsed, "value", parsed)
    return dict(value) if isinstance(value, dict) else {}


def _write_archive(
    temporary: Path,
    target: Path,
    payload: dict[str, str],
) -> None:
    if set(payload) != set(SAMPLE_ARCHIVE_FILES):
        raise ValueError("厂商采样 Artifact 文件清单不完整")
    with ZipFile(temporary, "w", compression=ZIP_DEFLATED) as archive:
        for name in SAMPLE_ARCHIVE_FILES:
            archive.writestr(name, payload[name].encode("utf-8"))
    os.replace(temporary, target)


def _check_cancelled(cancel_check: Callable[[], bool] | None) -> None:
    if cancel_check is not None and cancel_check():
        raise CommandCancelled("设备命令已取消")


def _json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


__all__ = [
    "SAMPLE_ARCHIVE_FILES",
    "SAMPLE_TASK_TYPE",
    "SwitchVendorSampleResult",
    "collect_switch_vendor_sample",
]
