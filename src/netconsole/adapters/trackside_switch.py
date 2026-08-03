from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

from netconsole.models.device import Device
from netconsole.models.trackside_switch import (
    CommandCapabilityState,
    ParserVerificationStatus,
    TracksideAdapterDescription,
    TracksideCapabilityDescriptor,
    TracksideCommandPlan,
    TracksideCommandPlanItem,
    TracksideCommandProfile,
)
from netconsole.parsers.h3c.interface_parser import parse_interfaces as parse_h3c_interfaces
from netconsole.parsers.h3c.lldp_parser import parse_lldp_neighbors
from netconsole.parsers.h3c.transceiver_parser import parse_transceiver_diagnosis
from netconsole.parsers.zte.zxr10 import (
    merge_optical_modules,
    ZteParseResult,
    parse_device_identity,
    parse_interface_detail,
    parse_interfaces,
    parse_lldp,
    parse_lldp_brief,
    parse_lldp_entries,
    merge_lldp_neighbors,
    parse_optical_detail,
    parse_optical_summary,
)
from netconsole.services import command_guard
from netconsole.services.netmiko_connection import (
    CommandCancelled,
    CommandOutputLimitExceeded,
    PagedCommandResult,
    encoding_for_vendor,
    safe_send_command_with_paging,
)


TRACKSIDE_COMMAND_CONTEXT = "trackside_switch_collect"
SWITCH_VENDOR_SAMPLE_CONTEXT = "switch_vendor_sample_collect"
ZTE_PROFILE_ID = "zte_zxr10_5960x_es_v2"
H3C_PROFILE_ID = "h3c_comware_trackside_v1"
_SAFE_INTERFACE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9./:_-]{0,79}$")
_PROMPT_RE = re.compile(
    r"(?m)^\s*(?P<prompt>[A-Za-z0-9_.:/-]{1,128}"
    r"(?:\(config[^)]*\))?[>#])\s*$",
    re.IGNORECASE,
)
_SAMPLE_OUTPUT_FILES = {
    "device_version": "version.txt",
    "interface_brief": "interface-brief.txt",
    "interface_detail": "interface-detail.txt",
    "optical_brief": "optical-brief.txt",
    "optical_detail": "optical-detail.txt",
    "lldp_global": "lldp-global.txt",
    "lldp_interface": "lldp-interface.txt",
}

ZTE_TRACKSIDE_COMMAND_PROFILE = TracksideCommandProfile(
    profile_id=ZTE_PROFILE_ID,
    vendor="ZTE",
    platform="ZXR10",
    product_family="5960X-ES",
    reference_version="V2.00.20.03",
    privilege_required=False,
    enable_command="enable 15",
    enable_level=15,
    enable_secret_configured=False,
    device_version=("show version",),
    interface_brief=("show interface brief",),
    interface_detail=("show interface <interface_name>",),
    optical_brief=("show opticalinfo brief",),
    optical_detail=("show opticalinfo <interface_name>",),
    lldp_global_candidates=(
        "show lldp neighbor brief",
        "show lldp entry",
    ),
)

H3C_TRACKSIDE_COMMAND_PROFILE = TracksideCommandProfile(
    profile_id=H3C_PROFILE_ID,
    vendor="H3C",
    platform="Comware",
    product_family="*",
    reference_version="",
    device_version=("display version",),
    interface_brief=("display interface brief",),
    interface_detail=("display interface <interface>",),
    optical_brief=("display transceiver diagnosis interface",),
    lldp_global_candidates=("display lldp neighbor-information list",),
)


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
    interface_snapshot_status: str = ""
    optical_snapshot_status: str = ""


def _append_snapshot_warning(
    result: TracksideSwitchCollection,
    label: str,
    status: object,
    retained_message: str,
) -> None:
    normalized = str(status or "").strip().upper()
    if normalized == "OK":
        return
    result.warnings.append(
        f"ZTE {label}状态为 {normalized or 'UNKNOWN'}，{retained_message}"
    )


class TracksideSwitchAdapter(ABC):
    vendor: str
    platform_family: str
    model_family: str
    profile_id: str
    command_profile: TracksideCommandProfile
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
        optical_fast_only: bool = False,
    ) -> TracksideSwitchCollection:
        raise NotImplementedError

    @abstractmethod
    def parse_device_identity(self, raw: str) -> object:
        raise NotImplementedError

    @abstractmethod
    def parse_interfaces(self, raw: str) -> object:
        raise NotImplementedError

    def parse_interface_brief(self, raw: str) -> object:
        return self.parse_interfaces(raw)

    def parse_interface_detail(self, raw: str) -> object:
        return self.parse_interfaces(raw)

    @abstractmethod
    def parse_lldp(self, raw: str) -> object:
        raise NotImplementedError

    @abstractmethod
    def parse_optical_summary(self, raw: str) -> object:
        raise NotImplementedError

    def parse_optical_brief(self, raw: str) -> object:
        return self.parse_optical_summary(raw)

    @abstractmethod
    def parse_optical_detail(
        self, raw: str, interface_name: str | None = None
    ) -> object:
        raise NotImplementedError

    def identify_device(
        self, connection: object, cancel_check: Callable[[], bool] | None = None
    ) -> PagedCommandResult:
        return self.collect_raw_output(
            connection, self.identity_command(), cancel_check=cancel_check
        )

    def prepare_session(
        self, connection: object, cancel_check: Callable[[], bool] | None = None
    ) -> None:
        for command in self.session_prepare_commands():
            self.collect_raw_output(connection, command, cancel_check=cancel_check)
        if self.command_profile.privilege_required:
            if not self.command_profile.enable_secret_configured:
                raise ValueError("ENABLE_SECRET_REQUIRED")
            raise NotImplementedError("ZTE 特权密码通道需在真实节点阶段验证")

    def build_command_plan(
        self,
        *,
        selected_interface: str = "",
        requested_commands: Iterable[str] = (),
    ) -> TracksideCommandPlan:
        selected = str(selected_interface or "").strip()
        interface = self.normalize_interface_name(selected) if selected else ""
        requested = tuple(
            dict.fromkeys(
                str(value or "").strip()
                for value in requested_commands
                if str(value or "").strip()
            )
        )
        allowed = tuple(_SAMPLE_OUTPUT_FILES)
        unknown = sorted(set(requested) - set(allowed))
        if unknown:
            raise ValueError(f"不支持的采样命令 selector：{', '.join(unknown)}")
        selectors = requested or allowed
        commands = self._sampling_commands_by_selector(interface)
        items: list[TracksideCommandPlanItem] = []
        for selector in selectors:
            for command in commands.get(selector, ()):
                items.append(
                    TracksideCommandPlanItem(
                        selector=selector,
                        command=command,
                        output_file=_SAMPLE_OUTPUT_FILES[selector],
                        status=CommandCapabilityState.IMPLEMENTED,
                        candidate=False,
                    )
                )
        return TracksideCommandPlan(self.profile_id, interface, tuple(items))

    def normalize_prompt(self, value: object) -> str:
        matches = list(_PROMPT_RE.finditer(str(value or "")))
        return matches[-1].group("prompt") if matches else ""

    def collect_raw_output(
        self,
        connection: object,
        command: str,
        *,
        cancel_check: Callable[[], bool] | None = None,
        command_context: str = TRACKSIDE_COMMAND_CONTEXT,
    ) -> PagedCommandResult:
        return self._execute(
            connection,
            command,
            cancel_check,
            command_context=command_context,
        )

    @abstractmethod
    def describe_capabilities(self) -> TracksideAdapterDescription:
        raise NotImplementedError

    def collect_interfaces(
        self, connection: object, cancel_check: Callable[[], bool] | None = None
    ) -> PagedCommandResult:
        return self.collect_raw_output(
            connection, self.interface_summary_command(), cancel_check=cancel_check
        )

    def collect_interface_detail(
        self,
        connection: object,
        interface_name: str,
        cancel_check: Callable[[], bool] | None = None,
    ) -> PagedCommandResult:
        return self.collect_raw_output(
            connection,
            self.interface_detail_command(interface_name),
            cancel_check=cancel_check,
        )

    def collect_lldp_neighbors(
        self, connection: object, cancel_check: Callable[[], bool] | None = None
    ) -> PagedCommandResult:
        return self.collect_raw_output(
            connection, self.lldp_summary_command(), cancel_check=cancel_check
        )

    def collect_lldp_neighbor(
        self,
        connection: object,
        interface_name: str,
        cancel_check: Callable[[], bool] | None = None,
    ) -> PagedCommandResult:
        return self.collect_raw_output(
            connection,
            self.lldp_interface_command(interface_name),
            cancel_check=cancel_check,
        )

    def collect_optical_summary(
        self, connection: object, cancel_check: Callable[[], bool] | None = None
    ) -> PagedCommandResult:
        return self.collect_raw_output(
            connection, self.optical_summary_command(), cancel_check=cancel_check
        )

    def collect_optical_detail(
        self,
        connection: object,
        interface_name: str,
        cancel_check: Callable[[], bool] | None = None,
    ) -> PagedCommandResult:
        return self.collect_raw_output(
            connection,
            self.optical_detail_command(interface_name),
            cancel_check=cancel_check,
        )

    def normalize_interface_name(self, interface_name: str) -> str:
        value = str(interface_name or "").strip()
        if not _SAFE_INTERFACE_RE.fullmatch(value):
            raise ValueError("接口名称包含不安全字符")
        return value

    def capability_manifest(self) -> dict[str, object]:
        description = self.describe_capabilities()
        return {
            "vendor": self.vendor,
            "platform_family": self.platform_family,
            "model_family": self.model_family,
            "command_profile_version": self.profile_id,
            "capabilities": self.capabilities.to_dict(),
            "capability_statuses": [
                item.to_dict() for item in description.capabilities
            ],
            "adaptation_status": description.adaptation_status,
            "verification_status": description.verification_status.value,
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
        *,
        command_context: str = TRACKSIDE_COMMAND_CONTEXT,
    ) -> PagedCommandResult:
        command_guard.validate_command_list((command,), command_context)
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

    def _sampling_commands_by_selector(
        self, interface_name: str
    ) -> dict[str, tuple[str, ...]]:
        profile = self.command_profile
        return {
            "device_version": profile.device_version,
            "interface_brief": profile.interface_brief,
            "interface_detail": _format_profile_commands(
                profile.interface_detail, interface_name
            ),
            "optical_brief": profile.optical_brief,
            "optical_detail": _format_profile_commands(
                profile.optical_detail, interface_name
            ),
            "lldp_global": tuple(
                command
                for command in (
                    *profile.lldp_global_candidates,
                    *profile.lldp_config_candidates,
                )
                if "<interface_name>" not in command
            ),
            "lldp_interface": _format_profile_commands(
                (
                    *profile.lldp_interface_candidates,
                    *(
                        command
                        for command in profile.lldp_config_candidates
                        if "<interface_name>" in command
                    ),
                ),
                interface_name,
            ),
        }

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
    command_profile = H3C_TRACKSIDE_COMMAND_PROFILE
    capabilities = TracksideSwitchCapabilities(
        device_identity=False,
        bidirectional_attenuation=True,
    )

    def collect(
        self,
        connection: object,
        *,
        artifact_dir: Path | None = None,
        cancel_check: Callable[[], bool] | None = None,
        optical_fast_only: bool = False,
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

    def describe_capabilities(self) -> TracksideAdapterDescription:
        return TracksideAdapterDescription(
            vendor=self.vendor,
            vendor_label="新华三 H3C",
            platform=self.platform_family,
            product_family=self.model_family,
            adaptation_status="已接入",
            verification_status=ParserVerificationStatus.REAL_DEVICE_PENDING,
            profile=self.command_profile,
            capabilities=(
                TracksideCapabilityDescriptor(
                    "ssh",
                    "SSH",
                    CommandCapabilityState.IMPLEMENTED,
                    "复用现有 H3C 只读采集链",
                ),
                TracksideCapabilityDescriptor(
                    "interface_status",
                    "接口状态",
                    CommandCapabilityState.IMPLEMENTED,
                    "复用现有 H3C Parser",
                ),
                TracksideCapabilityDescriptor(
                    "optical_dom",
                    "光模块 DOM",
                    CommandCapabilityState.IMPLEMENTED,
                    "复用现有 H3C Parser",
                ),
                TracksideCapabilityDescriptor(
                    "lldp",
                    "LLDP",
                    CommandCapabilityState.IMPLEMENTED,
                    "复用现有 H3C Parser",
                ),
                TracksideCapabilityDescriptor(
                    "bidirectional_attenuation",
                    "双向光衰",
                    CommandCapabilityState.IMPLEMENTED,
                    "复用现有 H3C 两端 DOM 计算规则",
                ),
            ),
        )

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
    command_profile = ZTE_TRACKSIDE_COMMAND_PROFILE
    capabilities = TracksideSwitchCapabilities(
        lldp_neighbors=True,
        lldp_interface_neighbor=False,
    )

    def collect(
        self,
        connection: object,
        *,
        artifact_dir: Path | None = None,
        cancel_check: Callable[[], bool] | None = None,
        optical_fast_only: bool = False,
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
        _annotate_raw_output_ref(result.identity, "version.txt")
        result.warnings.extend(identity.warnings)
        if identity.status == "NOT_RECOGNIZED":
            raise ValueError("ZTE_DEVICE_NOT_RECOGNIZED")

        if optical_fast_only:
            interface_output = self.collect_interfaces(connection, cancel_check)
            commands["interface-brief"] = self.interface_summary_command()
            result.raw_outputs["interface-brief"] = interface_output.raw_output
            result.command_pages["interface-brief"] = interface_output.page_count
            interface_parse = self.parse_interfaces(interface_output.output)
            result.interfaces = interface_parse.value
            result.interface_snapshot_status = interface_parse.status
            _annotate_raw_output_refs(result.interfaces, "interface-brief.txt")
            result.warnings.extend(interface_parse.warnings)
            _append_snapshot_warning(
                result,
                "接口摘要",
                interface_parse.status,
                "上一份接口状态快照已保留",
            )

            optical_output = self.collect_optical_summary(connection, cancel_check)
            commands["optical-brief"] = self.optical_summary_command()
            result.raw_outputs["optical-brief"] = optical_output.raw_output
            result.command_pages["optical-brief"] = optical_output.page_count
            optical_parse = self.parse_optical_summary(optical_output.output)
            result.optical_modules = optical_parse.value
            result.optical_snapshot_status = optical_parse.status
            _annotate_raw_output_refs(result.optical_modules, "optical-brief.txt")
            result.warnings.extend(optical_parse.warnings)
            _append_snapshot_warning(
                result,
                "光模块摘要",
                optical_parse.status,
                "上一份光模块快照已保留",
            )
            self._write_artifacts(artifact_dir, result, commands)
            return result

        interface_output = self.collect_interfaces(connection, cancel_check)
        commands["interface-brief"] = self.interface_summary_command()
        result.raw_outputs["interface-brief"] = interface_output.raw_output
        result.command_pages["interface-brief"] = interface_output.page_count
        interface_parse = self.parse_interfaces(interface_output.output)
        result.interfaces = interface_parse.value
        result.interface_snapshot_status = interface_parse.status
        _annotate_raw_output_refs(result.interfaces, "interface-brief.txt")
        result.warnings.extend(interface_parse.warnings)
        _append_snapshot_warning(
            result,
            "接口摘要",
            interface_parse.status,
            "上一份接口状态快照已保留",
        )

        optical_output = self.collect_optical_summary(connection, cancel_check)
        commands["optical-brief"] = self.optical_summary_command()
        result.raw_outputs["optical-brief"] = optical_output.raw_output
        result.command_pages["optical-brief"] = optical_output.page_count
        optical_parse = self.parse_optical_summary(optical_output.output)
        result.optical_modules = optical_parse.value
        result.optical_snapshot_status = optical_parse.status
        _annotate_raw_output_refs(result.optical_modules, "optical-brief.txt")
        result.warnings.extend(optical_parse.warnings)
        _append_snapshot_warning(
            result,
            "光模块摘要",
            optical_parse.status,
            "上一份光模块快照已保留",
        )

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
                parsed_interface = self.parse_interface_detail(
                    interface_detail_output.output
                )
                if parsed_interface.value:
                    interface_index[interface_name.casefold()].update(
                        parsed_interface.value
                    )
                    _annotate_raw_output_ref(
                        interface_index[interface_name.casefold()],
                        _artifact_file_name(selector),
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
                    merged = merge_optical_modules(
                        [summary] if summary else [],
                        [parsed_optical.value],
                    )
                    summary = merged[0] if merged else dict(parsed_optical.value)
                    _annotate_raw_output_ref(
                        summary,
                        _artifact_file_name(selector),
                    )
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

        brief_parse: ZteParseResult[list[dict[str, object | None]]] | None = None
        entry_parse: ZteParseResult[list[dict[str, object | None]]] | None = None
        for selector, command, parser in (
            (
                "lldp-brief",
                "show lldp neighbor brief",
                parse_lldp_brief,
            ),
            ("lldp-entry", "show lldp entry", parse_lldp_entries),
        ):
            try:
                output = self.collect_raw_output(
                    connection,
                    command,
                    cancel_check=cancel_check,
                )
                commands[selector] = command
                result.raw_outputs[selector] = output.raw_output
                result.command_pages[selector] = output.page_count
                parsed = parser(output.output)
                result.warnings.extend(parsed.warnings)
                if selector == "lldp-brief":
                    brief_parse = parsed
                else:
                    entry_parse = parsed
            except (CommandOutputLimitExceeded, CommandCancelled):
                raise
            except Exception:
                result.warnings.append(f"{selector} 只读采集失败")

        lldp_snapshot: list[dict[str, object | None]] | None = None
        if brief_parse is not None and brief_parse.status == "OK":
            lldp_snapshot = merge_lldp_neighbors(
                brief_parse.value,
                (
                    entry_parse.value
                    if entry_parse is not None and entry_parse.status == "OK"
                    else []
                ),
            )
        elif entry_parse is not None and entry_parse.status == "OK":
            lldp_snapshot = entry_parse.value
        elif any(
            parsed is not None and parsed.status == "NO_NEIGHBOR"
            for parsed in (brief_parse, entry_parse)
        ):
            lldp_snapshot = []
        result.lldp_neighbors = lldp_snapshot or []
        _annotate_raw_output_refs(result.lldp_neighbors, "lldp-entry.txt")
        result.lldp_status = (
            CommandCapabilityState.VERIFIED.value
            if lldp_snapshot is not None
            else CommandCapabilityState.SAMPLE_REQUIRED.value
        )
        result.interfaces = list(interface_index.values())
        result.optical_modules = list(optical_index.values())
        self._write_artifacts(artifact_dir, result, commands)
        return result

    def describe_capabilities(self) -> TracksideAdapterDescription:
        return TracksideAdapterDescription(
            vendor=self.vendor,
            vendor_label="中兴 ZTE",
            platform=self.platform_family,
            product_family=self.model_family,
            adaptation_status="C89E-4 Release 已验证；其他 ZXR10/5960X 型号需逐型号复核",
            verification_status=ParserVerificationStatus.REAL_DEVICE_PENDING,
            profile=self.command_profile,
            capabilities=(
                TracksideCapabilityDescriptor(
                    "ssh",
                    "SSH",
                    CommandCapabilityState.VERIFIED,
                    "C89E-4 Release 只读会话已实机验证",
                ),
                TracksideCapabilityDescriptor(
                    "device_version",
                    "设备版本",
                    CommandCapabilityState.VERIFIED,
                    "C89E-4 Release 已实机验证",
                ),
                TracksideCapabilityDescriptor(
                    "interface_status",
                    "接口状态",
                    CommandCapabilityState.VERIFIED,
                    "C89E-4 Release 已实机验证",
                ),
                TracksideCapabilityDescriptor(
                    "optical_dom",
                    "光模块 DOM",
                    CommandCapabilityState.VERIFIED,
                    "C89E-4 Release brief 状态与原生门限已实机验证",
                ),
                TracksideCapabilityDescriptor(
                    "lldp",
                    "LLDP",
                    CommandCapabilityState.VERIFIED,
                    "C89E-4 Release 已实机验证；其他型号需逐型号复核",
                ),
                TracksideCapabilityDescriptor(
                    "ap_auto_match",
                    "AP 自动匹配",
                    CommandCapabilityState.IMPLEMENTED,
                    "复用当前 LLDP 与 AP Identity 匹配链",
                ),
                TracksideCapabilityDescriptor(
                    "bidirectional_attenuation",
                    "双向光衰",
                    CommandCapabilityState.SAMPLE_REQUIRED,
                    "仅有单端光功率时不计算双向光衰",
                ),
                TracksideCapabilityDescriptor(
                    "configuration_write",
                    "配置下发",
                    CommandCapabilityState.UNSUPPORTED,
                    "本适配器只允许只读命令",
                ),
            ),
            pending_items=(
                "非 C89E-4 Release 型号的命令与字段兼容性复核",
                "双端 ZTE 光衰计算验证",
                "其他 ZXR10 型号与版本兼容验证",
            ),
        )

    def parse_device_identity(
        self, raw: str
    ) -> ZteParseResult[dict[str, object | None]]:
        return parse_device_identity(raw)

    def parse_interfaces(
        self, raw: str
    ) -> ZteParseResult[list[dict[str, object | None]]]:
        return parse_interfaces(raw)

    def parse_interface_detail(
        self, raw: str
    ) -> ZteParseResult[dict[str, object | None]]:
        return parse_interface_detail(raw)

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
        return self.command_profile.lldp_global_candidates[0]

    def lldp_interface_command(self, interface_name: str) -> str:
        raise NotImplementedError("ZTE 轨旁采集仅使用已确认的全量 LLDP 命令")

    def lldp_sampling_commands(self, interface_name: str) -> tuple[str, ...]:
        self.normalize_interface_name(interface_name)
        return self.command_profile.lldp_global_candidates

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


def trackside_switch_command_profile(
    profile_id: str,
) -> TracksideCommandProfile:
    profiles = {
        H3C_PROFILE_ID: H3C_TRACKSIDE_COMMAND_PROFILE,
        ZTE_PROFILE_ID: ZTE_TRACKSIDE_COMMAND_PROFILE,
    }
    try:
        return profiles[str(profile_id or "").strip()]
    except KeyError as exc:
        raise ValueError("command_profile_not_supported") from exc


def _format_profile_commands(
    commands: Iterable[str], interface_name: str
) -> tuple[str, ...]:
    result: list[str] = []
    for command in commands:
        if "<interface_name>" in command:
            if not interface_name:
                continue
            result.append(command.replace("<interface_name>", interface_name))
        else:
            result.append(command)
    return tuple(result)


def _annotate_raw_output_ref(
    item: dict[str, object | None], raw_output_ref: str
) -> None:
    if item:
        item["raw_output_ref"] = raw_output_ref


def _annotate_raw_output_refs(
    items: Iterable[dict[str, object | None]], raw_output_ref: str
) -> None:
    for item in items:
        _annotate_raw_output_ref(item, raw_output_ref)


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
    "H3C_PROFILE_ID",
    "H3C_TRACKSIDE_COMMAND_PROFILE",
    "H3CTracksideSwitchAdapter",
    "SWITCH_VENDOR_SAMPLE_CONTEXT",
    "TRACKSIDE_COMMAND_CONTEXT",
    "TracksidePortError",
    "TracksideSwitchAdapter",
    "TracksideSwitchCapabilities",
    "TracksideSwitchCollection",
    "ZTE_PROFILE_ID",
    "ZTE_TRACKSIDE_COMMAND_PROFILE",
    "ZteZxr10TracksideSwitchAdapter",
    "resolve_trackside_switch_adapter",
    "trackside_switch_command_profile",
]
