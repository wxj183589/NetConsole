from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AcResourceRefreshRequest:
    device_uuid: str
    site_name: str
    source: str = "auto"
    snmp_oids: list[str] = field(default_factory=list)
    snmp_operation: str = "WALK"
    snmp_concurrency: int = 10
    snmp_timeout_ms: int = 2000
    snmp_retries: int = 1
    snmp_max_repetitions: int = 10
    snmp_max_rows: int = 500


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
                "error_message": self.error_message,
            },
        }
