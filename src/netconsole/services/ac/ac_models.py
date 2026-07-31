from __future__ import annotations

from dataclasses import dataclass, field

from netconsole.services.ac.fit_ap_optical_concurrency import DEFAULT_FIT_AP_OPTICAL_CONCURRENCY


@dataclass(frozen=True)
class AcResourceRefreshRequest:
    device_uuid: str
    site_name: str
    source: str = "auto"


@dataclass(frozen=True)
class AcFitApDetailRefreshRequest:
    device_uuid: str
    ap_uuid: str
    site_name: str


@dataclass(frozen=True)
class AcResourceSnapshot:
    ac_device_uuid: str
    summary: dict[str, object | None] = field(default_factory=dict)
    resources: list[dict[str, object | None]] = field(default_factory=list)

    def to_payload(self) -> dict[str, object]:
        return {
            "ac_uuid": self.ac_device_uuid,
            "summary": dict(self.summary),
            "resources": [dict(row) for row in self.resources],
        }


@dataclass(frozen=True)
class AcResourceRefreshResult:
    success: bool
    source: str
    snapshot: AcResourceSnapshot
    collect_run_uuid: str = ""
    raw_log_path: str = ""
    fit_ap_resources_updated: int = 0
    unauthenticated_rows_updated: int = 0
    bbssid_rows_parsed: int = 0
    lldp_rows_parsed: int = 0
    failed_commands: list[str] = field(default_factory=list)
    summary_updated: bool = False
    https_port: int | None = None
    https_port_persisted: bool = False
    target_ap_uuid: str = ""
    error_message: str = ""

    def to_payload(self) -> dict[str, object]:
        return {
            **self.snapshot.to_payload(),
            "collection": {
                "success": self.success,
                "source": self.source,
                "collect_run_uuid": self.collect_run_uuid,
                "raw_log_path": self.raw_log_path,
                "fit_ap_resources_updated": self.fit_ap_resources_updated,
                "unauthenticated_rows_updated": self.unauthenticated_rows_updated,
                "bbssid_rows_parsed": self.bbssid_rows_parsed,
                "lldp_rows_parsed": self.lldp_rows_parsed,
                "failed_commands": list(self.failed_commands),
                "summary_updated": self.summary_updated,
                "https_port": self.https_port,
                "https_port_persisted": self.https_port_persisted,
                "target_ap_uuid": self.target_ap_uuid,
                "error_message": self.error_message,
            },
        }

    def to_terminal_payload(self) -> dict[str, object]:
        """Worker 终态只回执持久化摘要，资源列表通过分页查询读取。"""

        snapshot_revision = (
            self.snapshot.summary.get("snapshot_revision")
            or self.snapshot.summary.get("revision")
            or ""
        )
        return {
            "ac_uuid": self.snapshot.ac_device_uuid,
            "collect_run_uuid": self.collect_run_uuid,
            "success": bool(self.success),
            "fit_ap_resources_updated": int(self.fit_ap_resources_updated),
            "unauthenticated_rows_updated": int(self.unauthenticated_rows_updated),
            "bbssid_rows_parsed": int(self.bbssid_rows_parsed),
            "lldp_rows_parsed": int(self.lldp_rows_parsed),
            "failed_commands": [str(item) for item in self.failed_commands],
            "summary_updated": bool(self.summary_updated),
            "snapshot_revision": str(snapshot_revision),
            "data_persisted": bool(self.success),
            "reload_required": bool(self.success),
        }


@dataclass(frozen=True)
class AcOpticalRefreshRequest:
    device_uuid: str
    site_name: str
    refresh_scope: str = "all"
    source: str = "auto"
    max_workers: int = DEFAULT_FIT_AP_OPTICAL_CONCURRENCY
    timeout: int = 15
    retry: int = 2
    target_ap_uuids: list[str] = field(default_factory=list)
    target_ap_macs: list[str] = field(default_factory=list)
    target_ap_names: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AcOpticalSnapshot:
    ac_device_uuid: str
    summary: dict[str, object | None] = field(default_factory=dict)
    resources: list[dict[str, object | None]] = field(default_factory=list)
    optical_rows: list[dict[str, object | None]] = field(default_factory=list)

    def to_payload(self) -> dict[str, object]:
        return {
            "ac_uuid": self.ac_device_uuid,
            "summary": dict(self.summary),
            "resources": [dict(row) for row in self.resources],
            "optical_rows": [dict(row) for row in self.optical_rows],
        }


@dataclass(frozen=True)
class AcOpticalRefreshResult:
    success: bool
    partial_success: bool
    source: str
    refresh_scope: str
    snapshot: AcOpticalSnapshot
    collect_run_uuid: str = ""
    optical_rows_updated: int = 0
    failed_aps: int = 0
    error_message: str = ""
    requested_concurrency: int = 0
    effective_concurrency: int = 0
    platform_concurrency_limit: int = 0
    round_summaries: list[dict[str, object]] = field(default_factory=list)

    def to_payload(self) -> dict[str, object]:
        return {
            **self.snapshot.to_payload(),
            "collection": {
                "success": self.success,
                "partial_success": self.partial_success,
                "source": self.source,
                "refresh_scope": self.refresh_scope,
                "collect_run_uuid": self.collect_run_uuid,
                "optical_rows_updated": self.optical_rows_updated,
                "failed_aps": self.failed_aps,
                "error_message": self.error_message,
                "requested_concurrency": self.requested_concurrency,
                "effective_concurrency": self.effective_concurrency,
                "platform_concurrency_limit": self.platform_concurrency_limit,
                "round_summaries": [dict(row) for row in self.round_summaries],
            },
        }


@dataclass(frozen=True)
class AcCommandRequest:
    device_uuid: str
    site_name: str
    action: str
    command_sequence: list[str] = field(default_factory=list)
    confirm_required: bool = True
    timeout: int = 10
    retry: int = 0
    source: str = "auto"


@dataclass(frozen=True)
class AcCommandExecutionResult:
    success: bool
    device_uuid: str
    action: str
    commands: list[str] = field(default_factory=list)
    command_results: list[dict[str, object | None]] = field(default_factory=list)
    collect_run_uuid: str = ""
    raw_log_path: str = ""
    error_code: str = ""
    error_message: str = ""
    confirm_required: bool = True

    def to_payload(self) -> dict[str, object]:
        return {
            "device_uuid": self.device_uuid,
            "action": self.action,
            "commands": list(self.commands),
            "command_results": [dict(row) for row in self.command_results],
            "collect_run_uuid": self.collect_run_uuid,
            "raw_log_path": self.raw_log_path,
            "success": self.success,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "confirm_required": self.confirm_required,
        }
