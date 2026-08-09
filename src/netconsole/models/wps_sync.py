from __future__ import annotations

from hashlib import sha256
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


WPS_SYNC_PROTOCOL_VERSION = 2
TRACKSIDE_AP_WPS_BUSINESS_KEY = "rail_transit.trackside_ap_business"
WPS_BINDING_ID_PREFIX = "wpsbind_v1_"


def build_wps_binding_id(site_id: str, business_key: str, target_code: str) -> str:
    canonical = "\n".join(
        (
            "wpsbind:v1",
            str(site_id or "").strip().casefold(),
            str(business_key or "").strip().casefold(),
            str(target_code or "").strip().casefold(),
        )
    )
    return f"{WPS_BINDING_ID_PREFIX}{sha256(canonical.encode('utf-8')).hexdigest()}"


class WpsTargetType(StrEnum):
    STANDARD_SPREADSHEET = "WPS_STANDARD_SPREADSHEET"


class WpsSyncMode(StrEnum):
    FULL_REPLACE = "FULL_REPLACE"
    PREPEND_SNAPSHOT = "PREPEND_SNAPSHOT"
    DISABLED = "DISABLED"


class WpsFreezeMode(StrEnum):
    NONE = "NONE"
    FIRST_ROW_ONLY = "FIRST_ROW_ONLY"


@dataclass(frozen=True)
class WpsSyncTarget:
    target_id: str
    site_id: str
    business_key: str
    target_code: str
    target_type: WpsTargetType
    credential_id: str
    target_name: str
    document_open_url: str
    webhook_url: str
    expected_document_id: str
    binding_id: str = ""
    enabled: bool = True
    protocol_version: int = WPS_SYNC_PROTOCOL_VERSION
    timeout_seconds: int = 30
    token_configured: bool = False
    token_suffix: str = ""
    last_test_at: str = ""
    last_test_status: str = ""
    last_test_message: str = ""
    last_sync_at: str = ""
    last_sync_status: str = ""
    last_sync_revision: str = ""
    runtime_capability: str = "DEPLOYMENT_PENDING"
    last_runtime_probe_at: str = ""
    runtime_probe_document_id: str = ""
    runtime_probe_script_id: str = ""
    runtime_probe_script_version: str = ""
    runtime_probe_deployment_id: str = ""
    binding_status: str = "UNKNOWN"
    remote_binding_id: str = ""
    remote_site_id: str = ""
    remote_site_name: str = ""
    remote_business_key: str = ""
    connection_diagnostic: dict[str, Any] = field(default_factory=dict)
    runtime_probe_diagnostic: dict[str, Any] = field(default_factory=dict)
    sync_test_diagnostic: dict[str, Any] = field(default_factory=dict)
    sheet_tab_color_probe_diagnostic: dict[str, Any] = field(default_factory=dict)
    column_width_probe_diagnostic: dict[str, Any] = field(default_factory=dict)
    remote_script_version: str = ""
    remote_deployment_id: str = ""
    remote_script_id: str = ""
    remote_identity_verified_at: str = ""

    def __post_init__(self) -> None:
        if not self.binding_id:
            object.__setattr__(
                self,
                "binding_id",
                build_wps_binding_id(self.site_id, self.business_key, self.target_code),
            )

    def public_dict(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "site_id": self.site_id,
            "business_key": self.business_key,
            "target_code": self.target_code,
            "target_type": self.target_type.value,
            "target_name": self.target_name,
            "document_open_url": self.document_open_url,
            "webhook_url": self.webhook_url,
            "expected_document_id": self.expected_document_id,
            "enabled": self.enabled,
            "protocol_version": self.protocol_version,
            "timeout_seconds": self.timeout_seconds,
            "token_configured": self.token_configured,
            "token_suffix": self.token_suffix,
            "last_test_at": self.last_test_at,
            "last_test_status": self.last_test_status,
            "last_test_message": self.last_test_message,
            "last_sync_at": self.last_sync_at,
            "last_sync_status": self.last_sync_status,
            "last_sync_revision": self.last_sync_revision,
            "runtime_capability": self.runtime_capability,
            "last_runtime_probe_at": self.last_runtime_probe_at,
            "runtime_probe_document_id": self.runtime_probe_document_id,
            "runtime_probe_script_id": self.runtime_probe_script_id,
            "runtime_probe_script_version": self.runtime_probe_script_version,
            "runtime_probe_deployment_id": self.runtime_probe_deployment_id,
            "binding_status": self.binding_status,
            "binding_id": self.binding_id,
            "remote_binding_id": self.remote_binding_id,
            "remote_site_id": self.remote_site_id,
            "remote_site_name": self.remote_site_name,
            "remote_business_key": self.remote_business_key,
            "connection_diagnostic": self.connection_diagnostic,
            "runtime_probe_diagnostic": self.runtime_probe_diagnostic,
            "sync_test_diagnostic": self.sync_test_diagnostic,
            "sheet_tab_color_probe_diagnostic": self.sheet_tab_color_probe_diagnostic,
            "column_width_probe_diagnostic": self.column_width_probe_diagnostic,
            "remote_script_version": self.remote_script_version,
            "remote_deployment_id": self.remote_deployment_id,
            "remote_script_id": self.remote_script_id,
            "remote_identity_verified_at": self.remote_identity_verified_at,
        }


@dataclass(frozen=True)
class WorkbookFormatRunDTO:
    range: str
    font: dict[str, Any] = field(default_factory=dict)
    fill: dict[str, Any] = field(default_factory=dict)
    number_format: str = ""
    alignment: dict[str, Any] = field(default_factory=dict)
    border: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "range": self.range,
            "font": self.font,
            "fill": self.fill,
            "number_format": self.number_format,
            "alignment": self.alignment,
            "border": self.border,
        }


@dataclass(frozen=True)
class WorkbookSheetDTO:
    logical_sheet_key: str
    sheet_name: str
    sync_mode: WpsSyncMode
    cells: list[list[Any]]
    row_count: int
    column_count: int
    sheet_order: int = 0
    sheet_visible: bool = True
    tab_color: str = ""
    merges: list[str] = field(default_factory=list)
    row_heights: dict[str, float] = field(default_factory=dict)
    column_widths: dict[str, float] = field(default_factory=dict)
    auto_fit_columns: tuple[str, ...] = ()
    column_layouts: dict[str, dict[str, Any]] = field(default_factory=dict)
    auto_fit_min_width: float = 8.0
    auto_fit_max_width: float = 60.0
    auto_fit_rows: bool = False
    format_runs: tuple[WorkbookFormatRunDTO, ...] = ()
    freeze_mode: WpsFreezeMode = WpsFreezeMode.NONE
    auto_filter: str = ""
    verification_samples: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "logical_sheet_key": self.logical_sheet_key,
            "sheet_name": self.sheet_name,
            "sync_mode": self.sync_mode.value,
            "cells": self.cells,
            "row_count": self.row_count,
            "column_count": self.column_count,
            "sheet_order": self.sheet_order,
            "sheet_visible": self.sheet_visible,
            "tab_color": self.tab_color,
            "merges": self.merges,
            "row_heights": self.row_heights,
            "column_widths": self.column_widths,
            "auto_fit_columns": list(self.auto_fit_columns),
            "column_layouts": self.column_layouts,
            "auto_fit_min_width": self.auto_fit_min_width,
            "auto_fit_max_width": self.auto_fit_max_width,
            "auto_fit_rows": self.auto_fit_rows,
            "format_runs": [run.to_dict() for run in self.format_runs],
            "freeze_mode": self.freeze_mode.value,
            "auto_filter": self.auto_filter,
            "verification_samples": list(self.verification_samples),
        }


@dataclass(frozen=True)
class WorkbookDTO:
    sheets: tuple[WorkbookSheetDTO, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"sheets": [sheet.to_dict() for sheet in self.sheets]}


__all__ = [
    "TRACKSIDE_AP_WPS_BUSINESS_KEY",
    "WPS_BINDING_ID_PREFIX",
    "WPS_SYNC_PROTOCOL_VERSION",
    "WorkbookFormatRunDTO",
    "WorkbookDTO",
    "WorkbookSheetDTO",
    "WpsFreezeMode",
    "WpsSyncMode",
    "WpsSyncTarget",
    "WpsTargetType",
    "build_wps_binding_id",
]
