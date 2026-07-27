from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from netconsole.models.device import Device
from netconsole.parsers.h3c.interface_parser import parse_interfaces as parse_h3c_interfaces
from netconsole.parsers.h3c.lldp_parser import parse_lldp_neighbors
from netconsole.parsers.h3c.transceiver_parser import parse_transceiver_diagnosis
from netconsole.parsers.zte.zxr10 import (
    TRACKSIDE_PHYSICAL_PREFIXES,
    ZteParseResult,
    parse_device_identity,
    parse_interface_detail,
    parse_interfaces,
    parse_lldp,
    parse_optical_detail,
    parse_optical_summary,
)
from netconsole.services import command_guard
from netconsole.services.device_command_profile_service import (
    device_cli_output_is_unsupported,
)
from netconsole.services.netmiko_connection import (
    CommandCancelled,
    CommandOutputLimitExceeded,
    PagedCommandResult,
    encoding_for_vendor,
    safe_send_command_with_paging,
)


TRACKSIDE_COMMAND_CONTEXT = "trackside_switch_collect"
ZTE_PROFILE_ID = "zte_zxr10_5960x_es_v2"
H3C_PROFILE_ID = "h3c_comware_trackside_v1"
_SAFE_INTERFACE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9./:_-]{0,79}$")


@dataclass(frozen=True)
class TracksideSwitchCapabilities:
    ssh_readonly: bool = True
    device_identity: bool = True
    interface_inventory: bool = True
    interface_status: bool = True
    interface_detail: bool = True
    lldp_neighbors: bool = True
    lldp_interface_neighbor: bool = True
    optical_dom_summary: bool = True
    optical_dom_detail: bool = True
    bidirectional_attenuation: bool = False
    configuration_write: bool = False

    def to_dict(self) -> dict[str, bool]:
        return {
            field_name: bool(getattr(self, field_name))
            for field_name in self.__dataclass_fields__
        }


@dataclass(frozen=True)
class TracksidePortError:
    interface_name: str
    capability: str
    error_code: str
    message: str


@dataclass
class TracksideSwitchCollection:
    vendor: str
    profile_id: str
    capabilities: TracksideSwitchCapabilities
    identity: dict[str, object | None] = field(default_factory=dict)
    interfaces: list[dict[str, object | None]] = field(default_factory=list)
    optical_modules: list[dict[str, object | None]] = field(default_factory=list)
    lldp_neighbors: list[dict[str, object | None]] = field(default_factory=list)
    raw_outputs: dict[str, str] = field(default_factory=dict)
    command_pages: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    port_errors: list[TracksidePortError] = field(default_factory=list)
    lldp_status: str = ""


class TracksideSwitchAdapter(ABC):
    vendor: str
    platform_family: str
    model_family: str
    profile_id: str
    capabilities = TracksideSwitchCapabilities()

    def __init__(self, device: Device) -> None:
        self.device = device
        self.encoding = encoding_for_vendor(device.device_vendor)

    @abstractmethod
    def collect(
        self,
        connection: object,
        *,
        artifact_dir: Path | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> TracksideSwitchCollection:
        raise NotImplementedError

    @abstractmethod
    def parse_device_identity(self, raw: str) -> object:
        raise NotImplementedError

    @abstractmethod
    def parse_interfaces(self, raw: str) -> object:
        raise NotImplementedError

    @abstractmethod
    def parse_lldp(self, raw: str) -> object:
        raise NotImplementedError

    @abstractmethod
    def parse_optical_summary(self, raw: str) -> object:
        raise NotImplementedError

    @abstractmethod
    def parse_optical_detail(
        self, raw: str, interface_name: str | None = None
    ) -> object:
        raise NotImplementedError

    def identify_device(
        self, connection: object, cancel_check: Callable[[], bool] | None = None
    ) -> PagedCommandResult:
        return self._execute(connection, self.identity_command(), cancel_check)

    def prepare_session(
        self, connection: object, cancel_check: Callable[[], bool] | None = None
    ) -> None:
        for command in self.session_prepare_commands():
            self._execute(connection, command, cancel_check)

    def collect_interfaces(
        self, connection: object, cancel_check: Callable[[], bool] | None = None
    ) -> PagedCommandResult:
        return self._execute(connection, self.interface_summary_command(), cancel_check)

    def collect_interface_detail(
        self,
        connection: object,
        interface_name: str,
        cancel_check: Callable[[], bool] | None = None,
    ) -> PagedCommandResult:
        return self._execute(
            connection, self.interface_detail_command(interface_name), cancel_check
        )

    def collect_lldp_neighbors(
        self, connection: object, cancel_check: Callable[[], bool] | None = None
    ) -> PagedCommandResult:
        return self._execute(connection, self.lldp_summary_command(), cancel_check)

    def collect_lldp_neighbor(
        self,
        connection: object,
        interface_name: str,
        cancel_check: Callable[[], bool] | None = None,
    ) -> PagedCommandResult:
        return self._execute(
            connection, self.lldp_interface_command(interface_name), cancel_check
        )

    def collect_optical_summary(
        self, connection: object, cancel_check: Callable[[], bool] | None = None
    ) -> PagedCommandResult:
        return self._execute(connection, self.optical_summary_command(), cancel_check)

    def collect_optical_detail(
        self,
        connection: object,
        interface_name: str,
        cancel_check: Callable[[], bool] | None = None,
    ) -> PagedCommandResult:
        return self._execute(
            connection, self.optical_detail_command(interface_name), cancel_check
        )

    def normalize_interface_name(self, interface_name: str) -> str:
        value = str(interface_name or "").strip()
        if not _SAFE_INTERFACE_RE.fullmatch(value):
            raise ValueError("接口名称包含不安全字符")
        return value

    def capability_manifest(self) -> dict[str, object]:
        return {
            "vendor": self.vendor,
            "platform_family": self.platform_family,
            "model_family": self.model_family,
            "command_profile_version": self.profile_id,
            "capabilities": self.capabilities.to_dict(),
        }

    def session_prepare_commands(self) -> tuple[str, ...]:
        return ()

    def identity_command(self) -> str:
        raise NotImplementedError

    def interface_summary_command(self) -> str:
        raise NotImplementedError

    def interface_detail_command(self, interface_name: str) -> str:
        raise NotImplementedError

    def lldp_summary_command(self) -> str:
        raise NotImplementedError

    def lldp_interface_command(self, interface_name: str) -> str:
        raise NotImplementedError

    def optical_summary_command(self) -> str:
        raise NotImplementedError

    def optical_detail_command(self, interface_name: str) -> str:
        raise NotImplementedError

    def _execute(
        self,
        connection: object,
        command: str,
        cancel_check: Callable[[], bool] | None,
    ) -> PagedCommandResult:
        command_guard.validate_command_list((command,), TRACKSIDE_COMMAND_CONTEXT)
        return safe_send_command_with_paging(
            connection,
            command,
            max_pages=256,
            max_output_bytes=4 * 1024 * 1024,
            command_timeout=120,
            idle_timeout=10,
            encoding=self.encoding,
            cancel_check=cancel_check,
        )

    def _write_artifacts(
        self,
        artifact_dir: Path | None,
        result: TracksideSwitchCollection,
        commands: dict[str, str],
    ) -> None:
        if artifact_dir is None:
            return
        artifact_dir.mkdir(parents=True, exist_ok=True)
        files: list[dict[str, str]] = []
        for selector, raw in result.raw_outputs.items():
            file_name = _artifact_file_name(selector)
            (artifact_dir / file_name).write_text(raw, encoding="utf-8")
            files.append(
                {
                    "selector": selector,
                    "command": commands.get(selector, ""),
                    "file": file_name,
                }
            )
        manifest = {
            **self.capability_manifest(),
            "device_uuid": str(self.device.device_uuid or ""),
            "device_name": str(self.device.name or ""),
            "collected_at": datetime.now().isoformat(timespec="seconds"),
            "lldp_status": result.lldp_status,
            "warnings": result.warnings,
            "port_errors": [
                {
                    "interface_name": item.interface_name,
                    "capability": item.capability,
                    "error_code": item.error_code,
                    "message": item.message,
                }
                for item in result.port_errors
            ],
            "files": files,
        }
        (artifact_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


class H3CTracksideSwitchAdapter(TracksideSwitchAdapter):
    vendor = "H3C"
    platform_family = "Comware"
    model_family = "*"
    profile_id = H3C_PROFILE_ID
    capabilities = TracksideSwitchCapabilities(device_identity=False)

    def collect(
        self,
        connection: object,
        *,
        artifact_dir: Path | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> TracksideSwitchCollection:
        result = TracksideSwitchCollection(
            self.vendor, self.profile_id, self.capabilities
        )
        commands = {
            "session": "screen-length disable",
            "interfaces": "display interface brief",
            "optical": "display transceiver diagnosis interface",
            "lldp": "display lldp neighbor-information list",
        }
        for selector, command in commands.items():
            command_result = self._execute(connection, command, cancel_check)
            result.raw_outputs[selector] = command_result.raw_output
            result.command_pages[selector] = command_result.page_count
        result.interfaces = parse_h3c_interfaces(result.raw_outputs["interfaces"])
        result.optical_modules = parse_transceiver_diagnosis(
            result.raw_outputs["optical"]
        )
        result.lldp_neighbors = parse_lldp_neighbors(result.raw_outputs["lldp"])
        result.lldp_status = "OK" if result.lldp_neighbors else "NO_NEIGHBOR"
        self._write_artifacts(artifact_dir, result, commands)
        return result

    def parse_device_identity(self, raw: str) -> dict[str, object]:
        return {}

    def parse_interfaces(self, raw: str) -> list[dict[str, object | None]]:
        return parse_h3c_interfaces(raw)

    def parse_lldp(self, raw: str) -> list[dict[str, object | None]]:
        return parse_lldp_neighbors(raw)

    def parse_optical_summary(self, raw: str) -> list[dict[str, object | None]]:
        return parse_transceiver_diagnosis(raw)

    def parse_optical_detail(
        self, raw: str, interface_name: str | None = None
    ) -> list[dict[str, object | None]]:
        return parse_transceiver_diagnosis(raw)

    def session_prepare_commands(self) -> tuple[str, ...]:
        return ("screen-length disable",)

    def identity_command(self) -> str:
        return "display version"

    def interface_summary_command(self) -> str:
        return "display interface brief"

    def interface_detail_command(self, interface_name: str) -> str:
        return f"display interface {self.normalize_interface_name(interface_name)}"

    def lldp_summary_command(self) -> str:
        return "display lldp neighbor-information list"

    def lldp_interface_command(self, interface_name: str) -> str:
        raise NotImplementedError("H3C 轨旁采集使用全量 LLDP 命令")

    def optical_summary_command(self) -> str:
        return "display transceiver diagnosis interface"

    def optical_detail_command(self, interface_name: str) -> str:
        raise NotImplementedError("H3C 轨旁采集使用全量光模块命令")


class ZteZxr10TracksideSwitchAdapter(TracksideSwitchAdapter):
    vendor = "ZTE"
    platform_family = "ZXR10"
    model_family = "5960X-ES"
    profile_id = ZTE_PROFILE_ID

    def collect(
        self,
        connection: object,
        *,
        artifact_dir: Path | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> TracksideSwitchCollection:
        result = TracksideSwitchCollection(
            self.vendor, self.profile_id, self.capabilities
        )
        commands: dict[str, str] = {}

        version = self.identify_device(connection, cancel_check)
        commands["version"] = self.identity_command()
        result.raw_outputs["version"] = version.raw_output
        result.command_pages["version"] = version.page_count
        identity = self.parse_device_identity(version.output)
        result.identity = identity.value
        result.warnings.extend(identity.warnings)
        if identity.status == "NOT_RECOGNIZED":
            raise ValueError("ZTE_DEVICE_NOT_RECOGNIZED")

        interface_output = self.collect_interfaces(connection, cancel_check)
        commands["interface-brief"] = self.interface_summary_command()
        result.raw_outputs["interface-brief"] = interface_output.raw_output
        result.command_pages["interface-brief"] = interface_output.page_count
        interface_parse = self.parse_interfaces(interface_output.output)
        result.interfaces = interface_parse.value
        result.warnings.extend(interface_parse.warnings)

        optical_output = self.collect_optical_summary(connection, cancel_check)
        commands["optical-brief"] = self.optical_summary_command()
        result.raw_outputs["optical-brief"] = optical_output.raw_output
        result.command_pages["optical-brief"] = optical_output.page_count
        optical_parse = self.parse_optical_summary(optical_output.output)
        result.optical_modules = optical_parse.value
        result.warnings.extend(optical_parse.warnings)

        interface_index = {
            str(item.get("interface_name") or "").casefold(): item
            for item in result.interfaces
        }
        optical_index = {
            str(item.get("interface_name") or "").casefold(): item
            for item in result.optical_modules
        }
        detail_interfaces = sorted(
            {
                str(item.get("interface_name") or "")
                for item in result.optical_modules
                if item.get("module_online")
            }
            | {
                str(item.get("interface_name") or "")
                for item in result.interfaces
                if "ap" in str(item.get("description") or "").casefold()
            }
        )
        for interface_name in detail_interfaces:
            if not interface_name:
                continue
            try:
                interface_detail_output = self.collect_interface_detail(
                    connection, interface_name, cancel_check
                )
                selector = f"interface-detail/{interface_name}"
                commands[selector] = self.interface_detail_command(interface_name)
                result.raw_outputs[selector] = interface_detail_output.raw_output
                result.command_pages[selector] = interface_detail_output.page_count
                parsed_interface = parse_interface_detail(
                    interface_detail_output.output
                )
                if parsed_interface.value:
                    interface_index[interface_name.casefold()].update(
                        parsed_interface.value
                    )
                result.warnings.extend(parsed_interface.warnings)
            except (CommandOutputLimitExceeded, CommandCancelled):
                raise
            except Exception as exc:
                result.port_errors.append(
                    TracksidePortError(
                        interface_name,
                        "interface_detail",
                        "ZTE_INTERFACE_PARSE_FAILED",
                        _safe_port_error(exc),
                    )
                )
            try:
                optical_detail_output = self.collect_optical_detail(
                    connection, interface_name, cancel_check
                )
                selector = f"optical-detail/{interface_name}"
                commands[selector] = self.optical_detail_command(interface_name)
                result.raw_outputs[selector] = optical_detail_output.raw_output
                result.command_pages[selector] = optical_detail_output.page_count
                parsed_optical = self.parse_optical_detail(
                    optical_detail_output.output, interface_name
                )
                if parsed_optical.value:
                    summary = optical_index.get(interface_name.casefold(), {})
                    summary_status = summary.get("status")
                    summary.update(parsed_optical.value)
                    if summary_status in {
                        "abnormal",
                        "unverified",
                        "dom_unavailable",
                        "offline",
                    }:
                        summary["status"] = summary_status
                    optical_index[interface_name.casefold()] = summary
                result.warnings.extend(parsed_optical.warnings)
            except (CommandOutputLimitExceeded, CommandCancelled):
                raise
            except Exception as exc:
                result.port_errors.append(
                    TracksidePortError(
                        interface_name,
                        "optical_dom_detail",
                        "ZTE_OPTICAL_PARSE_FAILED",
                        _safe_port_error(exc),
                    )
                )

        lldp_outputs: list[str] = []
        try:
            lldp_config = self.collect_lldp_neighbors(connection, cancel_check)
            commands["lldp-config"] = self.lldp_summary_command()
            result.raw_outputs["lldp-config"] = lldp_config.raw_output
            result.command_pages["lldp-config"] = lldp_config.page_count
            lldp_outputs.append(lldp_config.output)
        except (CommandOutputLimitExceeded, CommandCancelled):
            raise
        except Exception as exc:
            result.warnings.append(f"ZTE LLDP 全局状态采集失败：{_safe_port_error(exc)}")

        candidate_interfaces = [
            str(item.get("interface_name") or "")
            for item in result.interfaces
            if str(item.get("interface_name") or "")
            .casefold()
            .startswith(TRACKSIDE_PHYSICAL_PREFIXES)
        ]
        for interface_name in candidate_interfaces:
            try:
                lldp_output = self.collect_lldp_neighbor(
                    connection, interface_name, cancel_check
                )
                selector = f"lldp-entry/{interface_name}"
                commands[selector] = self.lldp_interface_command(interface_name)
                result.raw_outputs[selector] = lldp_output.raw_output
                result.command_pages[selector] = lldp_output.page_count
                lldp_outputs.append(lldp_output.output)
                if device_cli_output_is_unsupported(self.device, lldp_output.output):
                    result.lldp_status = "COMMAND_UNSUPPORTED"
                    break
            except (CommandOutputLimitExceeded, CommandCancelled):
                raise
            except Exception as exc:
                result.port_errors.append(
                    TracksidePortError(
                        interface_name,
                        "lldp_interface_neighbor",
                        "ZTE_LLDP_PARSE_FAILED",
                        _safe_port_error(exc),
                    )
                )
        parsed_lldp = self.parse_lldp("\n".join(lldp_outputs))
        result.lldp_neighbors = parsed_lldp.value
        result.lldp_status = result.lldp_status or parsed_lldp.status
        result.warnings.extend(parsed_lldp.warnings)
        result.interfaces = list(interface_index.values())
        result.optical_modules = list(optical_index.values())
        self._write_artifacts(artifact_dir, result, commands)
        return result

    def parse_device_identity(
        self, raw: str
    ) -> ZteParseResult[dict[str, object | None]]:
        return parse_device_identity(raw)

    def parse_interfaces(
        self, raw: str
    ) -> ZteParseResult[list[dict[str, object | None]]]:
        return parse_interfaces(raw)

    def parse_lldp(
        self, raw: str
    ) -> ZteParseResult[list[dict[str, object | None]]]:
        return parse_lldp(raw)

    def parse_optical_summary(
        self, raw: str
    ) -> ZteParseResult[list[dict[str, object | None]]]:
        return parse_optical_summary(raw)

    def parse_optical_detail(
        self, raw: str, interface_name: str | None = None
    ) -> ZteParseResult[dict[str, object | None]]:
        return parse_optical_detail(raw, interface_name)

    def identity_command(self) -> str:
        return "show version"

    def interface_summary_command(self) -> str:
        return "show interface brief"

    def interface_detail_command(self, interface_name: str) -> str:
        return f"show interface {self.normalize_interface_name(interface_name)}"

    def lldp_summary_command(self) -> str:
        return "show lldp config"

    def lldp_interface_command(self, interface_name: str) -> str:
        return (
            "show lldp entry interface "
            f"{self.normalize_interface_name(interface_name)}"
        )

    def lldp_sampling_commands(self, interface_name: str) -> tuple[str, ...]:
        interface = self.normalize_interface_name(interface_name)
        return (
            "show lldp config",
            f"show lldp config interface {interface}",
            f"show lldp entry interface {interface}",
            f"show lldp statistic interface {interface}",
        )

    def optical_summary_command(self) -> str:
        return "show opticalinfo brief"

    def optical_detail_command(self, interface_name: str) -> str:
        return f"show opticalinfo {self.normalize_interface_name(interface_name)}"


_ADAPTER_REGISTRY: dict[str, type[TracksideSwitchAdapter]] = {
    "h3c": H3CTracksideSwitchAdapter,
    "zte": ZteZxr10TracksideSwitchAdapter,
}


def resolve_trackside_switch_adapter(device: Device) -> TracksideSwitchAdapter:
    vendor = str(device.device_vendor or "").strip().casefold()
    try:
        adapter_type = _ADAPTER_REGISTRY[vendor]
    except KeyError as exc:
        raise ValueError("vendor_not_supported") from exc
    return adapter_type(device)


def _artifact_file_name(selector: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", selector).strip(".-")
    return f"{value or 'output'}.txt"


def _safe_port_error(exc: Exception) -> str:
    if isinstance(exc, CommandOutputLimitExceeded):
        return "命令输出超过受控上限"
    if isinstance(exc, TimeoutError):
        return "命令执行超时"
    text = str(exc or "").strip()
    return text[:240] if text else exc.__class__.__name__


__all__ = [
    "H3CTracksideSwitchAdapter",
    "TracksidePortError",
    "TracksideSwitchAdapter",
    "TracksideSwitchCapabilities",
    "TracksideSwitchCollection",
    "ZteZxr10TracksideSwitchAdapter",
    "resolve_trackside_switch_adapter",
]
