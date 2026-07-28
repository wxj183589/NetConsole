from __future__ import annotations

import fnmatch
import json
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from netconsole.core.paths import PathResolver
from netconsole.core.resources import package_resource_path
from netconsole.services.device_command_profile_service import (
    DeviceCommandProfileError,
    load_device_command_profiles,
)


PROFILE_FILENAME = "device_compatibility_profiles.json"
PROFILE_SCHEMA_VERSION = "2026.07.device-compatibility-profiles.v1"
UNKNOWN = "未识别"
_RELEASE_RE = re.compile(r"\bR[0-9A-Z]{4,}\b", re.IGNORECASE)
_PLATFORM_RE = re.compile(r"\b(?:Comware\s*)?V([1-9][0-9]*)\b", re.IGNORECASE)
_SERIAL_LIKE_RE = re.compile(r"^[A-Z0-9]{12,}$", re.IGNORECASE)
_ROLE_DISPLAY = {
    "wireless_controller": "无线控制器",
    "switch": "交换机",
    "mobile_router": "车载 MR",
    "mobile_router_cloud_ap": "车载 MR（Cloud AP）",
    "cloud_ap": "Cloud AP",
    "fit_ap": "FIT AP",
    "server": "服务器",
    "other": "其他",
    "unknown": "未识别",
}
_ALLOWED_CAPABILITY_STATES = {
    "supported",
    "partially_supported",
    "unsupported",
    "not_applicable",
    "unverified",
    "document_sample_only",
    "sample_required",
    "not_verified",
}
_ALLOWED_VALIDATION_LEVELS = {
    "validated",
    "locally_observed",
    "registered_pending_field_validation",
    "experimental",
    "document_sample_only",
}
_CATALOG_KEYS = {"schema_version", "profiles"}
_PROFILE_KEYS = {
    "profile_id",
    "vendor",
    "device_role",
    "display_role",
    "model_matchers",
    "platform_family",
    "platform_major_version",
    "software_version_matchers",
    "command_profile_id",
    "parser_profile_id",
    "capabilities",
    "validation_level",
    "notes",
}


class DeviceCompatibilityError(ValueError):
    pass


@dataclass(frozen=True)
class DeviceFingerprint:
    vendor: str
    role: str
    model: str = UNKNOWN
    platform_family: str = "unknown"
    platform_major_version: int | None = None
    software_version: str = UNKNOWN
    patch_version: str = ""
    version_source: str = UNKNOWN

    @property
    def key(self) -> tuple[str, str, str, str, int | None, str]:
        return (
            self.vendor.casefold(),
            self.role.casefold(),
            self.model.casefold(),
            self.platform_family.casefold(),
            self.platform_major_version,
            self.software_version.casefold(),
        )


@dataclass(frozen=True)
class DeviceCompatibilityProfile:
    profile_id: str
    vendor: str
    device_role: str
    display_role: str
    model_matchers: tuple[str, ...]
    platform_family: str
    platform_major_version: int
    software_version_matchers: tuple[str, ...]
    command_profile_id: str
    parser_profile_id: str
    capabilities: dict[str, str]
    validation_level: str
    notes: str = ""

    @property
    def is_exact_registration(self) -> bool:
        return "*" not in self.model_matchers and "*" not in self.software_version_matchers


@dataclass(frozen=True)
class CompatibilityCandidate:
    vendor: str
    role: str
    model: str
    platform_family: str
    platform_major_version: int | None
    software_version: str
    version_source: str
    local_count: int
    registered: bool
    suggested_profile_id: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "vendor": self.vendor,
            "role": _ROLE_DISPLAY.get(self.role, self.role),
            "model": self.model,
            "platform_family": self.platform_family,
            "platform_major_version": self.platform_major_version,
            "software_version": self.software_version,
            "version_source": self.version_source,
            "local_count": self.local_count,
            "registered": self.registered,
            "suggested_profile_id": self.suggested_profile_id,
        }


@dataclass(frozen=True)
class CompatibilityResolution:
    fingerprint: DeviceFingerprint
    profile: DeviceCompatibilityProfile | None
    reason: str

    @property
    def matched(self) -> bool:
        return self.profile is not None


class CompatibilityResolver:
    def __init__(self, profiles: Iterable[DeviceCompatibilityProfile]) -> None:
        self._profiles = tuple(profiles)

    def resolve(self, fingerprint: DeviceFingerprint) -> CompatibilityResolution:
        candidates: list[tuple[tuple[int, int, int, str], DeviceCompatibilityProfile]] = []
        for profile in self._profiles:
            score = _match_score(profile, fingerprint)
            if score is not None:
                candidates.append(((*score, profile.profile_id), profile))
        if not candidates:
            return CompatibilityResolution(fingerprint, None, "未登记兼容配置，进入安全降级")
        candidates.sort(key=lambda item: (-item[0][0], -item[0][1], -item[0][2], item[0][3]))
        return CompatibilityResolution(fingerprint, candidates[0][1], "已匹配兼容配置")


class DeviceCompatibilityService:
    def __init__(self, paths: PathResolver | None = None) -> None:
        self.paths = paths or PathResolver()

    def profiles(self) -> tuple[DeviceCompatibilityProfile, ...]:
        profiles = load_device_compatibility_profiles(self.paths)
        audit_command_profile_references(profiles, self.paths)
        return profiles

    def summary(self) -> dict[str, object]:
        profiles = self.profiles()
        platforms = sorted({_profile_platform_label(profile) for profile in profiles})
        roles = sorted({_ROLE_DISPLAY.get(profile.device_role, profile.display_role) for profile in profiles})
        levels = sorted({profile.validation_level for profile in profiles})
        return {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "profile_count": len(profiles),
            "platforms": platforms,
            "roles": roles,
            "validation_levels": levels,
            "statement": "当前代码内置兼容基线面向 H3C Comware V7/V9，并登记 ZTE ZXR10 C89E-4 V1.9.0 只读现场验证与 5960X-ES V2 文档样例框架。",
            "disclaimer": "本地扫描候选不会显示到普通用户首页；已登记基线也不等于所有型号和 Release 均已完成现场验证。",
            "profiles": [
                {
                    "profile_id": profile.profile_id,
                    "vendor": profile.vendor,
                    "device_role": profile.display_role,
                    "platform": _profile_platform_label(profile),
                    "validation_level": profile.validation_level,
                    "capabilities": profile.capabilities,
                }
                for profile in profiles
            ],
        }

    def scan_local_candidates(self, *, full: bool = False) -> list[CompatibilityCandidate]:
        rows = list(_read_local_fingerprint_rows(self.paths))
        return scan_candidate_rows(rows, self.profiles(), full=full)


def device_compatibility_profile_path(paths: PathResolver | None = None) -> Path:
    resolver = paths or PathResolver()
    source_path = resolver.app_root / "resources" / PROFILE_FILENAME
    if source_path.is_file():
        return source_path
    packaged_path = package_resource_path("assets", PROFILE_FILENAME)
    return packaged_path if packaged_path.is_file() else source_path


def load_device_compatibility_profiles(paths: PathResolver | None = None) -> tuple[DeviceCompatibilityProfile, ...]:
    path = device_compatibility_profile_path(paths)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object_pairs)
    except OSError as exc:
        raise DeviceCompatibilityError(f"兼容性 Profile 文件不可读: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise DeviceCompatibilityError(f"兼容性 Profile JSON 无效: line={exc.lineno}, column={exc.colno}") from exc
    if not isinstance(payload, dict) or set(payload) != _CATALOG_KEYS:
        raise DeviceCompatibilityError("兼容性 Profile 根字段非法")
    if payload.get("schema_version") != PROFILE_SCHEMA_VERSION:
        raise DeviceCompatibilityError("兼容性 Profile schema_version 不受支持")
    rows = payload.get("profiles")
    if not isinstance(rows, list) or not rows:
        raise DeviceCompatibilityError("兼容性 Profile 必须包含非空 profiles")
    profiles = tuple(sorted((_parse_profile(item) for item in rows), key=lambda item: item.profile_id))
    _validate_profiles(profiles)
    return profiles


def audit_command_profile_references(
    profiles: Iterable[DeviceCompatibilityProfile],
    paths: PathResolver | None = None,
) -> None:
    try:
        command_profiles = {profile.profile_id for profile in load_device_command_profiles(paths)}
    except DeviceCommandProfileError as exc:
        raise DeviceCompatibilityError(f"命令 Profile 审计失败: {exc}") from exc
    missing = sorted(
        profile.command_profile_id
        for profile in profiles
        if profile.command_profile_id not in command_profiles
        and not profile.command_profile_id.startswith("legacy.")
    )
    if missing:
        raise DeviceCompatibilityError(f"兼容性 Profile 引用未知命令 Profile: {', '.join(missing)}")


def scan_candidate_rows(
    rows: Iterable[dict[str, object]],
    profiles: Iterable[DeviceCompatibilityProfile],
    *,
    full: bool = False,
) -> list[CompatibilityCandidate]:
    profile_list = tuple(profiles)
    exact_keys = {_exact_key(profile) for profile in profile_list if profile.is_exact_registration}
    resolver = CompatibilityResolver(profile_list)
    counts: Counter[DeviceFingerprint] = Counter()
    for row in rows:
        fingerprint = fingerprint_from_record(row)
        counts[fingerprint] += 1
    candidates: list[CompatibilityCandidate] = []
    for fingerprint, count in counts.items():
        registered = fingerprint.key in exact_keys
        if registered and not full:
            continue
        resolution = resolver.resolve(fingerprint)
        candidates.append(
            CompatibilityCandidate(
                vendor=fingerprint.vendor,
                role=fingerprint.role,
                model=fingerprint.model,
                platform_family=fingerprint.platform_family,
                platform_major_version=fingerprint.platform_major_version,
                software_version=fingerprint.software_version,
                version_source=fingerprint.version_source,
                local_count=count,
                registered=registered,
                suggested_profile_id=resolution.profile.profile_id if resolution.profile else "",
            )
        )
    return sorted(
        candidates,
        key=lambda item: (
            item.registered,
            item.vendor.casefold(),
            item.role.casefold(),
            item.model.casefold(),
            item.platform_major_version or 0,
            item.software_version.casefold(),
        ),
    )


def fingerprint_from_record(row: dict[str, object]) -> DeviceFingerprint:
    vendor = _normalize_vendor(row.get("vendor") or row.get("device_vendor"))
    role = normalize_role(row.get("role") or row.get("device_role") or row.get("device_type"))
    model = normalize_model(row.get("model"), serial_number=row.get("serial_number"))
    platform_family = _normalize_platform_family(row.get("platform_family"))
    platform_major = _platform_major(row.get("platform_major_version") or row.get("platform_version"))
    software_version, source = _software_version(row)
    return DeviceFingerprint(
        vendor=vendor,
        role=role,
        model=model,
        platform_family=platform_family,
        platform_major_version=platform_major,
        software_version=software_version,
        patch_version=str(row.get("patch_version") or "").strip(),
        version_source=source,
    )


def normalize_role(value: object) -> str:
    text = str(value or "").strip().casefold().replace("_", "-")
    if text in {"sw", "switch", "交换机"}:
        return "switch"
    if text in {"ac", "wireless-controller", "wireless_controller", "无线控制器"}:
        return "wireless_controller"
    if text in {"mr", "mobile-router", "mobile_router", "vehicle-mr", "vehicle_mr", "车载 mr"}:
        return "mobile_router"
    if text in {"cloud-ap", "cloud ap", "cloud_ap", "mobile-router-cloud-ap", "mobile_router_cloud_ap"}:
        return "mobile_router_cloud_ap"
    if text in {"fit-ap", "fit ap", "fit_ap"}:
        return "fit_ap"
    if text in {"server", "服务器"}:
        return "server"
    return "unknown" if not text else "other"


def normalize_model(value: object, *, serial_number: object = "") -> str:
    text = " ".join(str(value or "").strip().split())
    if not text:
        return UNKNOWN
    if text.casefold().endswith(".bin") or "/" in text or "\\" in text:
        return UNKNOWN
    serial = str(serial_number or "").strip()
    if serial and text.casefold() == serial.casefold():
        return UNKNOWN
    if _SERIAL_LIKE_RE.fullmatch(text) and not re.search(r"[-_]", text):
        return UNKNOWN
    return text.upper()


def extract_release_from_image(value: object) -> str:
    text = str(value or "")
    match = _RELEASE_RE.search(Path(text).name)
    return match.group(0).upper() if match else ""


def _parse_profile(row: object) -> DeviceCompatibilityProfile:
    if not isinstance(row, dict) or set(row) != _PROFILE_KEYS:
        raise DeviceCompatibilityError("兼容性 Profile 条目字段非法")
    capabilities = row.get("capabilities")
    if not isinstance(capabilities, dict) or not capabilities:
        raise DeviceCompatibilityError("capabilities 必须是非空对象")
    normalized_capabilities = {str(key): str(value) for key, value in capabilities.items()}
    invalid_states = sorted(set(normalized_capabilities.values()) - _ALLOWED_CAPABILITY_STATES)
    if invalid_states:
        raise DeviceCompatibilityError(f"capabilities 状态非法: {', '.join(invalid_states)}")
    validation_level = str(row.get("validation_level") or "").strip()
    if validation_level not in _ALLOWED_VALIDATION_LEVELS:
        raise DeviceCompatibilityError("validation_level 非法")
    major = row.get("platform_major_version")
    if not isinstance(major, int) or isinstance(major, bool) or major < 1:
        raise DeviceCompatibilityError("platform_major_version 必须是正整数")
    profile = DeviceCompatibilityProfile(
        profile_id=_required_text(row.get("profile_id"), "profile_id"),
        vendor=_normalize_vendor(row.get("vendor")),
        device_role=normalize_role(row.get("device_role")),
        display_role=_required_text(row.get("display_role"), "display_role"),
        model_matchers=tuple(_string_list(row.get("model_matchers"), "model_matchers")),
        platform_family=_normalize_platform_family(row.get("platform_family")),
        platform_major_version=major,
        software_version_matchers=tuple(_string_list(row.get("software_version_matchers"), "software_version_matchers")),
        command_profile_id=_required_text(row.get("command_profile_id"), "command_profile_id"),
        parser_profile_id=_required_text(row.get("parser_profile_id"), "parser_profile_id"),
        capabilities=normalized_capabilities,
        validation_level=validation_level,
        notes=str(row.get("notes") or "").strip(),
    )
    if profile.device_role == "unknown" or profile.platform_family == "unknown":
        raise DeviceCompatibilityError(f"{profile.profile_id}: role/platform 不明确")
    return profile


def _profile_platform_label(profile: DeviceCompatibilityProfile) -> str:
    family = str(profile.platform_family or "").strip()
    label = "Comware" if family.casefold() == "comware" else family.upper()
    return f"{label} V{profile.platform_major_version}"


def _validate_profiles(profiles: tuple[DeviceCompatibilityProfile, ...]) -> None:
    ids = [profile.profile_id for profile in profiles]
    if len(ids) != len(set(ids)):
        raise DeviceCompatibilityError("兼容性 Profile profile_id 重复")


def _read_local_fingerprint_rows(paths: PathResolver) -> Iterable[dict[str, object]]:
    if not paths.sites_dir.exists():
        return []
    rows: list[dict[str, object]] = []
    for site_dir in sorted(path for path in paths.sites_dir.iterdir() if path.is_dir() and not path.is_symlink()):
        db_path = site_dir / "db" / "devices.db"
        if not db_path.is_file():
            continue
        uri = db_path.resolve().as_uri() + "?mode=ro"
        try:
            conn = sqlite3.connect(uri, uri=True)
            conn.row_factory = sqlite3.Row
            try:
                rows.extend(
                    dict(row)
                    for row in conn.execute(
                        """
                        SELECT
                            d.device_vendor AS vendor,
                            d.device_type AS role,
                            f.model AS model,
                            f.software_version AS software_version,
                            f.bootrom_version AS bootrom_version
                        FROM devices d
                        LEFT JOIN device_facts f ON f.device_uuid = d.device_uuid
                        """
                    ).fetchall()
                )
            finally:
                conn.close()
        except sqlite3.Error:
            continue
    return rows


def _match_score(
    profile: DeviceCompatibilityProfile,
    fingerprint: DeviceFingerprint,
) -> tuple[int, int, int] | None:
    if profile.vendor.casefold() != fingerprint.vendor.casefold():
        return None
    if profile.device_role != fingerprint.role:
        return None
    if profile.platform_family != fingerprint.platform_family:
        return None
    if profile.platform_major_version != fingerprint.platform_major_version:
        return None
    model_score = _pattern_score(profile.model_matchers, fingerprint.model)
    version_score = _pattern_score(profile.software_version_matchers, fingerprint.software_version)
    if model_score is None or version_score is None:
        return None
    return (model_score + version_score, model_score, version_score)


def _pattern_score(patterns: Iterable[str], value: str) -> int | None:
    best: int | None = None
    normalized_value = str(value or UNKNOWN).casefold()
    for pattern in patterns:
        normalized_pattern = pattern.casefold()
        if normalized_pattern == "*":
            score = 1
        elif "*" in normalized_pattern:
            score = 2 if fnmatch.fnmatchcase(normalized_value, normalized_pattern) else None
        else:
            score = 3 if normalized_value == normalized_pattern else None
        if score is not None:
            best = score if best is None else max(best, score)
    return best


def _exact_key(profile: DeviceCompatibilityProfile) -> tuple[str, str, str, str, int | None, str]:
    return (
        profile.vendor.casefold(),
        profile.device_role.casefold(),
        profile.model_matchers[0].casefold(),
        profile.platform_family.casefold(),
        profile.platform_major_version,
        profile.software_version_matchers[0].casefold(),
    )


def _software_version(row: dict[str, object]) -> tuple[str, str]:
    for key, source in (
        ("software_version", "结构化设备信息"),
        ("version", "结构化设备信息"),
        ("system_image", "启动镜像解析"),
        ("boot_image", "启动镜像解析"),
    ):
        value = str(row.get(key) or "").strip()
        if not value:
            continue
        if key in {"system_image", "boot_image"}:
            release = extract_release_from_image(value)
            if release:
                return release, source
            continue
        release = _RELEASE_RE.search(value)
        return (release.group(0).upper() if release else value, source)
    return UNKNOWN, UNKNOWN


def _platform_major(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    text = str(value or "").strip()
    match = _PLATFORM_RE.search(text)
    return int(match.group(1)) if match else None


def _normalize_vendor(value: object) -> str:
    text = str(value or "").strip()
    return "H3C" if text.casefold() == "h3c" else (text or UNKNOWN)


def _normalize_platform_family(value: object) -> str:
    text = str(value or "").strip().casefold()
    return "comware" if text == "comware" else ("unknown" if not text else text)


def _required_text(value: object, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise DeviceCompatibilityError(f"{field_name} 不能为空")
    return text


def _string_list(value: object, field_name: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise DeviceCompatibilityError(f"{field_name} 必须是非空数组")
    values = [_required_text(item, field_name) for item in value]
    if len(values) != len(set(values)):
        raise DeviceCompatibilityError(f"{field_name} 不得重复")
    return values


def _unique_object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise DeviceCompatibilityError(f"兼容性 Profile JSON 含重复键: {key}")
        result[key] = value
    return result


__all__ = [
    "CompatibilityCandidate",
    "CompatibilityResolver",
    "DeviceCompatibilityError",
    "DeviceCompatibilityProfile",
    "DeviceCompatibilityService",
    "DeviceFingerprint",
    "audit_command_profile_references",
    "extract_release_from_image",
    "fingerprint_from_record",
    "load_device_compatibility_profiles",
    "normalize_model",
    "normalize_role",
    "scan_candidate_rows",
]
