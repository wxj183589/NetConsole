from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from netconsole.core.paths import PathResolver
from netconsole.core.resources import package_resource_path
from netconsole.models.device import Device
from netconsole.services import command_guard


PROFILE_SCHEMA_VERSION = "2026.07.device-command-profiles.v1"
PROFILE_FILENAME = "device_command_profiles.json"
DEVICE_INVENTORY_OPERATION_ID = "device.inventory.collect"
_IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_STEP_SELECTOR_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
_CONTROL_CHARACTER_PATTERN = re.compile(r"[\x00-\x1f\x7f]")
_PROFILE_SELECTOR_KEYS = frozenset({"vendor", "role", "platform", "software_version"})
_CATALOG_KEYS = frozenset({"schema_version", "profiles"})
_PROFILE_KEYS = frozenset(
    {
        "operation_id",
        "profile_id",
        "profile_version",
        "selector",
        "compatibility",
        "risk",
        "parser_contract",
        "dto_contract",
        "verification",
        "steps",
    }
)
_STEP_KEYS = frozenset(
    {
        "order",
        "step_id",
        "command",
        "selector",
        "parser_contract",
        "dto_contract",
        "risk",
        "verification",
    }
)
_COMPATIBILITY_LEVELS = frozenset({"fixture_verified", "generic_read_only"})
_VERIFICATION_STATUSES = frozenset({"fixture_verified", "behavior_preservation_only"})
_DEVICE_INVENTORY_STEP_CONTRACT = (
    ("terminal.pagination.disable", "session.pagination"),
    ("device.sysname.collect", "inventory.sysname"),
    ("device.version.collect", "inventory.version"),
    ("device.slot.collect", "inventory.device"),
    ("device.manufacturing.collect", "inventory.manuinfo"),
    ("device.boot-loader.collect", "inventory.boot_loader"),
    ("device.interfaces.collect", "inventory.interfaces"),
    ("device.transceivers.collect", "inventory.transceivers"),
    ("device.transceiver-manufacturing.collect", "inventory.transceiver_manuinfo"),
    ("device.transceiver-diagnostics.collect", "inventory.transceiver_diagnosis"),
    ("device.lldp-summary.collect", "inventory.lldp_list"),
    ("device.lldp-detail.collect", "inventory.lldp_verbose"),
)


class DeviceCommandProfileError(ValueError):
    pass


class DeviceCommandProfileNotFound(DeviceCommandProfileError):
    pass


@dataclass(frozen=True)
class DeviceCommandSelector:
    vendor: str
    role: str
    platform: str
    software_version: str


@dataclass(frozen=True)
class DeviceCommandStep:
    order: int
    step_id: str
    command: str
    selector: str
    parser_contract: str
    dto_contract: str
    risk: str
    guard_context: str
    verification_status: str
    verification_evidence: str


@dataclass(frozen=True)
class DeviceCommandProfile:
    operation_id: str
    profile_id: str
    profile_version: int
    selector: DeviceCommandSelector
    compatibility: str
    risk: str
    parser_contract: str
    dto_contract: str
    fixture_versions: tuple[str, ...]
    real_device_status: str
    steps: tuple[DeviceCommandStep, ...]

    @property
    def commands(self) -> tuple[str, ...]:
        return tuple(step.command for step in self.steps)


def device_command_profile_path(paths: PathResolver | None = None) -> Path:
    resolver = paths or PathResolver()
    source_path = resolver.app_root / "resources" / PROFILE_FILENAME
    if source_path.is_file():
        return source_path
    packaged_path = package_resource_path("assets", PROFILE_FILENAME)
    return packaged_path if packaged_path.is_file() else source_path


def load_device_command_profiles(paths: PathResolver | None = None) -> tuple[DeviceCommandProfile, ...]:
    path = device_command_profile_path(paths)
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object_pairs,
        )
    except OSError as exc:
        raise DeviceCommandProfileError(f"命令 Profile 文件不可读: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise DeviceCommandProfileError(
            f"命令 Profile JSON 无效: line={exc.lineno}, column={exc.colno}"
        ) from exc
    if not isinstance(payload, dict) or set(payload) != _CATALOG_KEYS:
        raise DeviceCommandProfileError("命令 Profile 根字段非法")
    if payload.get("schema_version") != PROFILE_SCHEMA_VERSION:
        raise DeviceCommandProfileError("命令 Profile schema_version 不受支持")
    rows = payload.get("profiles")
    if not isinstance(rows, list) or not rows:
        raise DeviceCommandProfileError("命令 Profile 必须包含非空 profiles")
    profiles = tuple(_parse_profile(row) for row in rows)
    _validate_catalog(profiles)
    return profiles


def resolve_device_command_profile(
    *,
    operation_id: str,
    vendor: str,
    role: str,
    platform: str,
    software_version: str | None = None,
    paths: PathResolver | None = None,
) -> DeviceCommandProfile:
    normalized_operation = _normalize_identifier(operation_id, "operation_id")
    normalized_vendor = _normalize_selector_value(vendor)
    normalized_role = _normalize_selector_value(role)
    normalized_platform = _normalize_selector_value(platform)
    if not normalized_vendor or not normalized_role or not normalized_platform:
        raise DeviceCommandProfileNotFound("vendor、role 和 platform 均必须明确")
    candidates = [
        profile
        for profile in load_device_command_profiles(paths)
        if profile.operation_id == normalized_operation
        and _normalize_selector_value(profile.selector.vendor) == normalized_vendor
        and _normalize_selector_value(profile.selector.role) == normalized_role
        and _normalize_selector_value(profile.selector.platform) == normalized_platform
    ]
    version = _version_major(software_version)
    if version:
        exact = [
            profile
            for profile in candidates
            if profile.selector.software_version != "*"
            and profile.selector.software_version.casefold() == version.casefold()
        ]
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            raise DeviceCommandProfileError("命令 Profile selector 不唯一")
    generic = [profile for profile in candidates if profile.selector.software_version == "*"]
    if len(generic) == 1 and generic[0].compatibility == "generic_read_only":
        return generic[0]
    if len(generic) > 1:
        raise DeviceCommandProfileError("命令 Profile generic selector 不唯一")
    raise DeviceCommandProfileNotFound(
        "不支持的设备命令 Profile: "
        f"operation={normalized_operation}, vendor={vendor}, role={role}, platform={platform}"
    )


def resolve_device_inventory_profile(
    device: Device,
    *,
    software_version: str | None = None,
    paths: PathResolver | None = None,
) -> DeviceCommandProfile:
    vendor = str(device.device_vendor or "").strip()
    role = _device_role(device.device_type)
    if vendor.casefold() != "h3c":
        raise DeviceCommandProfileNotFound(
            f"设备详情采集仅支持 H3C: vendor={vendor or 'unknown'}"
        )
    if role != "switch":
        raise DeviceCommandProfileNotFound(
            f"设备详情采集仅支持交换机: role={role or 'unknown'}"
        )
    return resolve_device_command_profile(
        operation_id=DEVICE_INVENTORY_OPERATION_ID,
        vendor="H3C",
        role=role,
        platform="comware",
        software_version=software_version,
        paths=paths,
    )


def default_device_inventory_profile(paths: PathResolver | None = None) -> DeviceCommandProfile:
    return resolve_device_command_profile(
        operation_id=DEVICE_INVENTORY_OPERATION_ID,
        vendor="H3C",
        role="switch",
        platform="comware",
        paths=paths,
    )


def _parse_profile(row: object) -> DeviceCommandProfile:
    if not isinstance(row, dict):
        raise DeviceCommandProfileError("命令 Profile 条目必须是对象")
    if set(row) != _PROFILE_KEYS:
        raise DeviceCommandProfileError("命令 Profile 条目字段非法")
    operation_id = _normalize_identifier(row.get("operation_id"), "operation_id")
    profile_id = _normalize_identifier(row.get("profile_id"), "profile_id")
    profile_version = row.get("profile_version")
    if not isinstance(profile_version, int) or isinstance(profile_version, bool) or profile_version < 1:
        raise DeviceCommandProfileError(f"{profile_id}: profile_version 必须是正整数")
    if not profile_id.endswith(f".v{profile_version}"):
        raise DeviceCommandProfileError(
            f"{profile_id}: profile_id 与 profile_version 不一致"
        )
    selector_row = row.get("selector")
    if not isinstance(selector_row, dict) or set(selector_row) != _PROFILE_SELECTOR_KEYS:
        raise DeviceCommandProfileError(f"{profile_id}: selector 字段非法")
    selector = DeviceCommandSelector(
        vendor=_selector_value(selector_row.get("vendor"), "selector.vendor"),
        role=_selector_value(selector_row.get("role"), "selector.role"),
        platform=_selector_value(selector_row.get("platform"), "selector.platform"),
        software_version=_software_version_selector(selector_row.get("software_version")),
    )
    compatibility = _normalize_identifier(row.get("compatibility"), "compatibility")
    if compatibility not in _COMPATIBILITY_LEVELS:
        raise DeviceCommandProfileError(f"{profile_id}: compatibility 非法")
    if selector.software_version == "*" and compatibility != "generic_read_only":
        raise DeviceCommandProfileError(
            f"{profile_id}: generic Profile 必须声明 generic_read_only"
        )
    if selector.software_version != "*" and compatibility == "generic_read_only":
        raise DeviceCommandProfileError(
            f"{profile_id}: generic_read_only Profile 必须使用通配版本"
        )
    risk = _normalize_identifier(row.get("risk"), "risk")
    if risk != "read_only":
        raise DeviceCommandProfileError(f"{profile_id}: 当前目录仅允许 read_only Profile")
    parser_contract = _normalize_identifier(row.get("parser_contract"), "parser_contract")
    dto_contract = _normalize_identifier(row.get("dto_contract"), "dto_contract")
    verification = row.get("verification")
    if not isinstance(verification, dict) or set(verification) != {
        "fixture_versions",
        "real_device_status",
    }:
        raise DeviceCommandProfileError(f"{profile_id}: verification 字段非法")
    fixture_versions = verification.get("fixture_versions")
    if not isinstance(fixture_versions, list) or not fixture_versions:
        raise DeviceCommandProfileError(f"{profile_id}: fixture_versions 必须是非空数组")
    normalized_fixture_versions = tuple(
        _required_text(value, "fixture_versions") for value in fixture_versions
    )
    if len(normalized_fixture_versions) != len(set(normalized_fixture_versions)):
        raise DeviceCommandProfileError(f"{profile_id}: fixture_versions 不得重复")
    if selector.software_version != "*":
        expected_major = selector.software_version.removeprefix("V")
        fixture_majors = {_fixture_major(value) for value in normalized_fixture_versions}
        if expected_major not in fixture_majors:
            raise DeviceCommandProfileError(
                f"{profile_id}: fixture_versions 与软件主版本 {selector.software_version} 不一致"
            )
    real_device_status = _normalize_identifier(
        verification.get("real_device_status"), "real_device_status"
    )
    if real_device_status != "real_device_pending":
        raise DeviceCommandProfileError(f"{profile_id}: 首切片必须保持 REAL_DEVICE_PENDING")
    step_rows = row.get("steps")
    if not isinstance(step_rows, list) or not step_rows:
        raise DeviceCommandProfileError(f"{profile_id}: steps 必须是非空数组")
    steps = tuple(_parse_step(operation_id, profile_id, item) for item in step_rows)
    return DeviceCommandProfile(
        operation_id=operation_id,
        profile_id=profile_id,
        profile_version=profile_version,
        selector=selector,
        compatibility=compatibility,
        risk=risk,
        parser_contract=parser_contract,
        dto_contract=dto_contract,
        fixture_versions=normalized_fixture_versions,
        real_device_status=real_device_status,
        steps=steps,
    )


def _parse_step(
    operation_id: str,
    profile_id: str,
    row: object,
) -> DeviceCommandStep:
    if not isinstance(row, dict):
        raise DeviceCommandProfileError(f"{profile_id}: step 必须是对象")
    if set(row) != _STEP_KEYS:
        raise DeviceCommandProfileError(f"{profile_id}: step 字段非法")
    order = row.get("order")
    if not isinstance(order, int) or isinstance(order, bool) or order < 1:
        raise DeviceCommandProfileError(f"{profile_id}: step.order 必须是正整数")
    step_id = _normalize_identifier(row.get("step_id"), "step_id")
    command = _required_text(row.get("command"), "command")
    selector = _required_text(row.get("selector"), "step.selector").casefold()
    if not _STEP_SELECTOR_PATTERN.fullmatch(selector):
        raise DeviceCommandProfileError(f"{profile_id}/{step_id}: selector 格式无效")
    if _CONTROL_CHARACTER_PATTERN.search(command) or ";" in command:
        raise DeviceCommandProfileError(
            f"{profile_id}/{step_id}: command 含非法控制字符或分号"
        )
    parser_contract = _normalize_identifier(
        row.get("parser_contract"), "step.parser_contract"
    )
    dto_contract = _normalize_identifier(row.get("dto_contract"), "step.dto_contract")
    risk = row.get("risk")
    if not isinstance(risk, dict) or set(risk) != {"level", "guard_context"}:
        raise DeviceCommandProfileError(f"{profile_id}/{step_id}: risk 字段非法")
    risk_level = _normalize_identifier(risk.get("level"), "step.risk.level")
    guard_context = _normalize_identifier(
        risk.get("guard_context"), "step.risk.guard_context"
    )
    if risk_level != "read_only" or guard_context != operation_id:
        raise DeviceCommandProfileError(f"{profile_id}/{step_id}: risk 契约非法")
    reason = command_guard.command_reject_reason(command, guard_context)
    if reason:
        raise DeviceCommandProfileError(
            f"{profile_id}/{step_id}: command 未通过 Guard: {reason}"
        )
    verification = row.get("verification")
    if not isinstance(verification, dict) or set(verification) != {"status", "evidence"}:
        raise DeviceCommandProfileError(
            f"{profile_id}/{step_id}: verification 字段非法"
        )
    verification_status = _normalize_identifier(
        verification.get("status"), "step.verification.status"
    )
    verification_evidence = _required_text(
        verification.get("evidence"), "step.verification.evidence"
    )
    if verification_status not in _VERIFICATION_STATUSES:
        raise DeviceCommandProfileError(
            f"{profile_id}/{step_id}: verification.status 非法"
        )
    return DeviceCommandStep(
        order=order,
        step_id=step_id,
        command=command,
        selector=selector,
        parser_contract=parser_contract,
        dto_contract=dto_contract,
        risk=risk_level,
        guard_context=guard_context,
        verification_status=verification_status,
        verification_evidence=verification_evidence,
    )


def _validate_catalog(profiles: tuple[DeviceCommandProfile, ...]) -> None:
    profile_ids: set[str] = set()
    selectors: set[tuple[str, str, str, str, str]] = set()
    for profile in profiles:
        if profile.profile_id in profile_ids:
            raise DeviceCommandProfileError(f"重复 profile_id: {profile.profile_id}")
        profile_ids.add(profile.profile_id)
        selector_key = (
            profile.operation_id,
            profile.selector.vendor,
            profile.selector.role,
            profile.selector.platform,
            profile.selector.software_version.casefold(),
        )
        if selector_key in selectors:
            raise DeviceCommandProfileError(f"重复 selector: {profile.profile_id}")
        selectors.add(selector_key)
        step_ids = [step.step_id for step in profile.steps]
        step_selectors = [step.selector for step in profile.steps]
        commands = [command_guard.normalize_command(step.command) for step in profile.steps]
        orders = [step.order for step in profile.steps]
        if len(step_ids) != len(set(step_ids)):
            raise DeviceCommandProfileError(f"{profile.profile_id}: step_id 重复")
        if len(step_selectors) != len(set(step_selectors)):
            raise DeviceCommandProfileError(f"{profile.profile_id}: step.selector 重复")
        if len(commands) != len(set(commands)):
            raise DeviceCommandProfileError(f"{profile.profile_id}: command 重复")
        if orders != sorted(orders) or len(orders) != len(set(orders)):
            raise DeviceCommandProfileError(
                f"{profile.profile_id}: step.order 必须唯一且严格升序"
            )
        if profile.operation_id == DEVICE_INVENTORY_OPERATION_ID:
            actual_contract = tuple(
                (step.step_id, step.selector) for step in profile.steps
            )
            if actual_contract != _DEVICE_INVENTORY_STEP_CONTRACT:
                raise DeviceCommandProfileError(
                    f"{profile.profile_id}: device.inventory.collect step 契约不完整或顺序错误"
                )


def _device_role(device_type: str | None) -> str:
    normalized = _normalize_selector_value(device_type)
    return "switch" if normalized in {"sw", "switch"} else normalized


def _normalize_identifier(value: object, field_name: str) -> str:
    normalized = _required_text(value, field_name).casefold()
    if not _IDENTIFIER_PATTERN.fullmatch(normalized):
        raise DeviceCommandProfileError(f"{field_name} 格式无效")
    return normalized


def _selector_value(value: object, field_name: str) -> str:
    normalized = _normalize_selector_value(value)
    if not normalized or not re.fullmatch(r"[a-z][a-z0-9_-]*", normalized):
        raise DeviceCommandProfileError(f"{field_name} 格式无效")
    return normalized


def _software_version_selector(value: object) -> str:
    text = _required_text(value, "selector.software_version")
    if text != "*" and not re.fullmatch(r"V[1-9][0-9]*", text, re.IGNORECASE):
        raise DeviceCommandProfileError("selector.software_version 格式无效")
    return text.upper() if text != "*" else text


def _version_major(value: object) -> str:
    text = str(value or "")
    match = re.search(r"\bV([1-9][0-9]*)\b", text, re.IGNORECASE)
    if not match:
        match = re.search(r"\bVERSION\s+([1-9][0-9]*)", text, re.IGNORECASE)
    return f"V{match.group(1)}" if match else ""


def _fixture_major(value: object) -> str:
    text = str(value or "").strip()
    match = re.search(r"(?:\bV|\bVERSION\s+)?([1-9][0-9]*)(?:\.|\b)", text, re.IGNORECASE)
    return match.group(1) if match else ""


def _required_text(value: object, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise DeviceCommandProfileError(f"{field_name} 不能为空")
    return text


def _normalize_selector_value(value: object) -> str:
    return str(value or "").strip().casefold()


def _unique_object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise DeviceCommandProfileError(f"命令 Profile JSON 含重复键: {key}")
        result[key] = value
    return result
