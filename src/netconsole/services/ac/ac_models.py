from __future__ import annotations

from dataclasses import dataclass, field

from netconsole.services.ac.fit_ap_optical_concurrency import DEFAULT_FIT_AP_OPTICAL_CONCURRENCY


AC_DEVICE_TYPES = frozenset({"ac", "wireless_controller"})
FIT_AP_SNAPSHOT_STATUS_NOT_COLLECTED = "NOT_COLLECTED"
FIT_AP_SNAPSHOT_STATUS_SUCCESS_WITH_ROWS = "SUCCESS_WITH_ROWS"
FIT_AP_SNAPSHOT_STATUS_SUCCESS_EMPTY = "SUCCESS_EMPTY"
FIT_AP_SNAPSHOT_STATUS_FAILED = "FAILED"
FIT_AP_SNAPSHOT_STATUSES = frozenset(
    {
        FIT_AP_SNAPSHOT_STATUS_NOT_COLLECTED,
        FIT_AP_SNAPSHOT_STATUS_SUCCESS_WITH_ROWS,
        FIT_AP_SNAPSHOT_STATUS_SUCCESS_EMPTY,
        FIT_AP_SNAPSHOT_STATUS_FAILED,
    }
)


def is_ac_device_type(value: object) -> bool:
    normalized = str(value or "").strip().casefold().replace("-", "_")
    return normalized in AC_DEVICE_TYPES


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
    bbssid_collect_status: str = "not_collected"
    bbssid_error: str = ""
    failed_commands: list[str] = field(default_factory=list)
    summary_updated: bool = False
    https_port: int | None = None
    https_port_persisted: bool = False
    target_ap_uuid: str = ""
    error_message: str = ""
    detail_rows_updated: int = 0
    detail_failed_count: int = 0
    detail_mode: str = ""
    batch_serial_duplicates: int = 0
    batch_serial_merged: int = 0
    serial_identity_conflicts: int = 0
    duplicate_ap_entity_created: int = 0
    fit_ap_snapshot_status: str = FIT_AP_SNAPSHOT_STATUS_NOT_COLLECTED
    persisted_components: list[str] = field(default_factory=list)
    failed_components: list[str] = field(default_factory=list)
    skipped_components: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """兼容旧 collector 返回值，同时给 Task Center 一个稳定的组件账本。"""

        persisted = list(self.persisted_components)
        failed = list(self.failed_components)
        if not persisted:
            if self.target_ap_uuid:
                if self.detail_rows_updated > 0 or self.fit_ap_resources_updated > 0:
                    persisted.append("AP_DETAIL")
            elif self.summary_updated or self.https_port_persisted:
                persisted.append("AC_BASIC")
            elif (
                self.fit_ap_resources_updated > 0
                or self.bbssid_rows_parsed > 0
                or self.lldp_rows_parsed > 0
                or self.fit_ap_snapshot_status != FIT_AP_SNAPSHOT_STATUS_NOT_COLLECTED
            ):
                persisted.append("FIT_AP")
        if not failed and not self.success:
            if self.target_ap_uuid:
                failed.append("AP_DETAIL")
            elif self.summary_updated or self.https_port is not None or self.https_port_persisted:
                failed.append("AC_BASIC")
            elif persisted or self.fit_ap_snapshot_status != FIT_AP_SNAPSHOT_STATUS_NOT_COLLECTED:
                failed.append("FIT_AP")
        object.__setattr__(self, "persisted_components", persisted)
        object.__setattr__(self, "failed_components", failed)
        object.__setattr__(self, "skipped_components", list(self.skipped_components))

    @property
    def partial_success(self) -> bool:
        return bool(self.persisted_components and self.failed_components)

    @property
    def business_outcome(self) -> str:
        if self.partial_success:
            return "PARTIAL_SUCCESS"
        return "SUCCESS" if self.success else "FAILED"

    def to_payload(self) -> dict[str, object]:
        return {
            **self.snapshot.to_payload(),
            "fit_ap_snapshot_status": str(self.fit_ap_snapshot_status),
            "collection": {
                "success": self.success,
                "source": self.source,
                "collect_run_uuid": self.collect_run_uuid,
                "raw_log_path": self.raw_log_path,
                "fit_ap_resources_updated": self.fit_ap_resources_updated,
                "unauthenticated_rows_updated": self.unauthenticated_rows_updated,
                "bbssid_rows_parsed": self.bbssid_rows_parsed,
                "lldp_rows_parsed": self.lldp_rows_parsed,
                "bbssid_collect_status": self.bbssid_collect_status,
                "bbssid_error": self.bbssid_error,
                "failed_commands": list(self.failed_commands),
                "summary_updated": self.summary_updated,
                "https_port": self.https_port,
                "https_port_persisted": self.https_port_persisted,
                "target_ap_uuid": self.target_ap_uuid,
                "detail_rows_updated": self.detail_rows_updated,
                "detail_failed_count": self.detail_failed_count,
                "detail_mode": self.detail_mode,
                "batch_serial_duplicates": self.batch_serial_duplicates,
                "batch_serial_merged": self.batch_serial_merged,
                "serial_identity_conflicts": self.serial_identity_conflicts,
                "duplicate_ap_entity_created": self.duplicate_ap_entity_created,
                "fit_ap_snapshot_status": self.fit_ap_snapshot_status,
                "persisted_components": list(self.persisted_components),
                "failed_components": list(self.failed_components),
                "skipped_components": list(self.skipped_components),
                "partial_success": self.partial_success,
                "business_outcome": self.business_outcome,
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
        failed_commands = [str(item) for item in self.failed_commands]
        collection = {
            "success": bool(self.success),
            "source": str(self.source),
            "collect_run_uuid": self.collect_run_uuid,
            "fit_ap_resources_updated": int(self.fit_ap_resources_updated),
            "unauthenticated_rows_updated": int(self.unauthenticated_rows_updated),
            "bbssid_rows_parsed": int(self.bbssid_rows_parsed),
            "lldp_rows_parsed": int(self.lldp_rows_parsed),
            "bbssid_collect_status": str(self.bbssid_collect_status),
            "bbssid_error": str(self.bbssid_error),
            "failed_commands": failed_commands,
            "summary_updated": bool(self.summary_updated),
            "https_port": self.https_port,
            "https_port_persisted": bool(self.https_port_persisted),
            "target_ap_uuid": str(self.target_ap_uuid),
            "detail_rows_updated": int(self.detail_rows_updated),
            "detail_failed_count": int(self.detail_failed_count),
            "detail_mode": str(self.detail_mode),
            "batch_serial_duplicates": int(self.batch_serial_duplicates),
            "batch_serial_merged": int(self.batch_serial_merged),
            "serial_identity_conflicts": int(self.serial_identity_conflicts),
            "duplicate_ap_entity_created": int(self.duplicate_ap_entity_created),
            "fit_ap_snapshot_status": str(self.fit_ap_snapshot_status),
            "persisted_components": list(self.persisted_components),
            "failed_components": list(self.failed_components),
            "skipped_components": list(self.skipped_components),
            "partial_success": self.partial_success,
            "business_outcome": self.business_outcome,
            "error_message": str(self.error_message),
        }
        return {
            "ac_uuid": self.snapshot.ac_device_uuid,
            "collect_run_uuid": self.collect_run_uuid,
            "success": bool(self.success),
            "fit_ap_resources_updated": int(self.fit_ap_resources_updated),
            "unauthenticated_rows_updated": int(self.unauthenticated_rows_updated),
            "bbssid_rows_parsed": int(self.bbssid_rows_parsed),
            "lldp_rows_parsed": int(self.lldp_rows_parsed),
            "bbssid_collect_status": str(self.bbssid_collect_status),
            "bbssid_error": str(self.bbssid_error),
            "detail_rows_updated": int(self.detail_rows_updated),
            "detail_failed_count": int(self.detail_failed_count),
            "detail_mode": str(self.detail_mode),
            "failed_commands": failed_commands,
            "summary_updated": bool(self.summary_updated),
            "snapshot_revision": str(snapshot_revision),
            "fit_ap_snapshot_status": str(self.fit_ap_snapshot_status),
            "persisted_components": list(self.persisted_components),
            "failed_components": list(self.failed_components),
            "skipped_components": list(self.skipped_components),
            "partial_success": self.partial_success,
            "business_outcome": self.business_outcome,
            "data_persisted": bool(self.persisted_components),
            "reload_required": bool(self.persisted_components),
            "collection": collection,
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

    def to_terminal_payload(self) -> dict[str, object]:
        """Worker 终态只回执持久化摘要，光衰明细通过查询接口读取。"""

        updated = max(0, int(self.optical_rows_updated))
        failed = max(0, int(self.failed_aps))
        succeeded = max(0, updated - failed)
        data_persisted = succeeded > 0
        round_summaries = [dict(row) for row in self.round_summaries]
        collection = {
            "success": bool(self.success),
            "partial_success": bool(self.partial_success),
            "source": str(self.source),
            "refresh_scope": str(self.refresh_scope),
            "collect_run_uuid": str(self.collect_run_uuid),
            "optical_rows_updated": updated,
            "success_count": succeeded,
            "failed_aps": failed,
            "failed_count": failed,
            "error_message": str(self.error_message),
            "requested_concurrency": int(self.requested_concurrency),
            "effective_concurrency": int(self.effective_concurrency),
            "platform_concurrency_limit": int(self.platform_concurrency_limit),
            "round_summaries": round_summaries,
        }
        return {
            "ac_uuid": str(self.snapshot.ac_device_uuid),
            "collect_run_uuid": str(self.collect_run_uuid),
            "success": bool(self.success),
            "partial_success": bool(self.partial_success),
            "refresh_scope": str(self.refresh_scope),
            "optical_rows_updated": updated,
            "success_count": succeeded,
            "failed_aps": failed,
            "failed_count": failed,
            "error_message": str(self.error_message),
            "data_persisted": data_persisted,
            "reload_required": data_persisted,
            "collection": collection,
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
