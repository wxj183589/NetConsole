from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from netconsole.models.api.common import ApiModel


Theme = Literal["light", "dark", "auto"]
Language = Literal["zh_CN", "en_US"]
ThemeColor = Literal["#0078D4", "#2563EB", "#0891B2", "#16A34A"]
TerminalType = Literal["putty", "securecrt", "xshell"]


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


class FeatureStateDTO(ApiModel):
    feature_id: str
    title: str
    visible: bool
    enabled: bool
    client_package: bool
    internal_only: bool


class FeatureSettingsSnapshotDTO(ApiModel):
    items: list[FeatureStateDTO]
    preview_active: bool


class FeatureSettingsUpdateDTO(ApiModel):
    items: list[FeatureStateDTO]
    confirmed: bool


def _path_text(value: str) -> str:
    value = value.strip()
    if any(ord(character) < 32 for character in value):
        raise ValueError("路径不能包含控制字符")
    return value


__all__ = [
    "FeatureSettingsSnapshotDTO", "FeatureSettingsUpdateDTO", "FeatureStateDTO",
    "SystemSettingsSaveDTO", "SystemSettingsSnapshotDTO", "SystemSettingsValuesDTO",
]
