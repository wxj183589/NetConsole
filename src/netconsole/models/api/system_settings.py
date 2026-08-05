from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from netconsole.models.api.common import ApiModel


Theme = Literal["light", "dark", "auto"]
Language = Literal["zh_CN", "en_US"]
ThemeColor = Literal["#0078D4", "#2563EB", "#0891B2", "#16A34A"]
TerminalType = Literal["putty", "securecrt", "xshell"]
NetworkComponentName = Literal["iperf3", "fping"]
NetworkComponentMode = Literal["builtin", "custom"]
NetworkComponentSource = Literal["builtin", "custom"]
FeatureConfigurationTarget = Literal["runtime", "full", "customer"]


class TerminalPathsDTO(ApiModel):
    putty: str = Field(max_length=32_767)
    securecrt: str = Field(max_length=32_767)
    xshell: str = Field(max_length=32_767)

    @field_validator("putty", "securecrt", "xshell")
    @classmethod
    def validate_paths(cls, value: str) -> str:
        return _path_text(value)


class SystemSettingsValuesDTO(ApiModel):
    theme: Theme
    language: Language
    theme_color: ThemeColor
    iperf_path: str = Field(max_length=32_767)
    fping_path: str = Field(max_length=32_767)
    ipop_path: str = Field(max_length=32_767)
    terminal_type: TerminalType
    terminal_paths: TerminalPathsDTO
    securecrt_sessions_root: str = Field(max_length=32_767)
    ssh_port: int = Field(ge=1, le=65_535)
    telnet_port: int = Field(ge=1, le=65_535)
    crt_encoding: Literal["UTF-8", "GBK"]

    @field_validator("iperf_path", "fping_path", "ipop_path", "securecrt_sessions_root")
    @classmethod
    def validate_paths(cls, value: str) -> str:
        return _path_text(value)


class SystemSettingsSaveDTO(SystemSettingsValuesDTO):
    expected_version: str = Field(min_length=7, max_length=64)


class SystemSettingsSnapshotDTO(ApiModel):
    version: str
    values: SystemSettingsValuesDTO
    defaults: SystemSettingsValuesDTO
    current_site_name: str
    current_site_path: str
    language_status: Literal["BLOCKED_ON_GLOBAL_I18N"] = "BLOCKED_ON_GLOBAL_I18N"


class NetworkComponentStatusDTO(ApiModel):
    component_name: NetworkComponentName
    mode: NetworkComponentMode
    source: NetworkComponentSource
    configured_path: str
    effective_path: str
    available: bool
    file_exists: bool
    fallback_used: bool
    fallback_reason: str
    validation_message: str


class NetworkComponentsSnapshotDTO(ApiModel):
    version: str
    components: list[NetworkComponentStatusDTO]


class NetworkComponentUpdateDTO(ApiModel):
    mode: NetworkComponentMode
    custom_path: str = Field(default="", max_length=32_767)
    expected_version: str = Field(min_length=7, max_length=64)

    @field_validator("custom_path")
    @classmethod
    def validate_custom_path(cls, value: str) -> str:
        return _path_text(value)


class FeatureStateDTO(ApiModel):
    feature_id: str
    title: str
    group_id: str
    group_title: str
    scope: Literal["global"] = "global"
    visible: bool
    enabled: bool
    inherited_visible: bool
    inherited_enabled: bool
    client_package: bool
    package_included: bool
    package_editable: bool
    internal_only: bool
    package_range: Literal["customer_internal", "internal", "internal_only", "not_included"]
    status: Literal["ENABLED", "DISABLED", "DEVELOPMENT", "HIDDEN"]
    dependencies: list[str] = Field(default_factory=list)
    locked: bool = False
    lock_reason: str = ""
    overridden: bool = False


class FeatureSettingsSnapshotDTO(ApiModel):
    items: list[FeatureStateDTO]
    target: FeatureConfigurationTarget
    preview_active: bool
    configuration_name: str
    scope_label: str = "全局"
    inherited_profile: str
    applies_immediately: bool
    save_effect: str


class FeatureStateUpdateDTO(ApiModel):
    feature_id: str
    visible: bool
    enabled: bool
    package_included: bool | None = None


class FeatureSettingsUpdateDTO(ApiModel):
    target: FeatureConfigurationTarget = "runtime"
    items: list[FeatureStateUpdateDTO]
    confirmed: bool


class FeatureSettingsRestoreDTO(ApiModel):
    target: FeatureConfigurationTarget = "runtime"
    confirmed: bool


class RuntimeSelfCheckItemDTO(ApiModel):
    check_id: str
    title: str
    status: Literal["normal", "warning", "error"]
    message: str
    suggestion: str = ""


class RuntimeSelfCheckSnapshotDTO(ApiModel):
    status: Literal["normal", "warning", "error"]
    checked_at: str
    packaged: bool
    unicode_sample: str
    items: list[RuntimeSelfCheckItemDTO] = Field(default_factory=list)


def _path_text(value: str) -> str:
    value = value.strip()
    if any(ord(character) < 32 for character in value):
        raise ValueError("路径不能包含控制字符")
    return value


__all__ = [
    "FeatureConfigurationTarget", "FeatureSettingsRestoreDTO", "FeatureSettingsSnapshotDTO",
    "FeatureSettingsUpdateDTO", "FeatureStateDTO", "FeatureStateUpdateDTO",
    "NetworkComponentStatusDTO", "NetworkComponentsSnapshotDTO", "NetworkComponentUpdateDTO",
    "RuntimeSelfCheckItemDTO", "RuntimeSelfCheckSnapshotDTO",
    "SystemSettingsSaveDTO", "SystemSettingsSnapshotDTO", "SystemSettingsValuesDTO",
]
