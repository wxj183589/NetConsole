from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


DIAGNOSTICS_ENABLED_FLAG = "ap_identity_diagnostics_enabled"
DIAGNOSTICS_UI_ENABLED_FLAG = "ap_identity_diagnostics_ui_enabled"
DIAGNOSTICS_SAMPLES_ENABLED_FLAG = "ap_identity_diagnostics_samples_enabled"

_SUPPORTED_SCHEMA_VERSION = 1
_SOURCE_KEYS = (
    "identity_shadow",
    "detail_identity_shadow",
    "export_identity_diagnostics",
)
_SOURCE_TITLES = {
    "identity_shadow": "AP Identity 诊断摘要",
    "detail_identity_shadow": "AP Identity 详情诊断摘要",
    "export_identity_diagnostics": "AP Identity 导出诊断摘要",
}
_STATUS_TEXT = {
    "disabled": "诊断展示已关闭",
    "not_collected": "本任务未生成 AP Identity 诊断摘要",
    "unavailable": "本任务诊断不可用，不影响业务结果",
    "insufficient_fields": "字段不足，无法生成可靠诊断",
    "failed": "诊断生成失败，不影响业务结果",
    "redacted": "明细已按安全策略隐藏",
    "not_supported": "当前任务类型暂不支持诊断展示",
    "available": "可查看聚合诊断摘要",
}
_STATUS_ACTIONS = {
    "disabled": "如需查看，请由维护人员显式开启诊断展示。",
    "not_collected": "无需影响当前任务；如需诊断，请在受控环境重新执行。",
    "unavailable": "保留原业务结果，检查诊断输入是否完整。",
    "insufficient_fields": "继续使用旧生产路径，并复核诊断输入字段。",
    "failed": "关闭诊断展示并保留原任务状态。",
    "redacted": "不要展开明细；复核脱敏和字段允许列表。",
    "not_supported": "继续使用原任务结果，等待受控适配。",
}
_RISK_ACTIONS = {
    "critical": "保持旧生产路径，人工复核 identity_changed。",
    "high": "保持旧生产路径，人工复核歧义或重复字段。",
    "medium": "继续只读观测，并补充候选或作用域信息。",
    "low": "继续只读观测，不改变现有业务路径。",
}

_COUNT_FIELDS = (
    "matched",
    "unresolved",
    "ambiguous",
    "identity_changed",
    "identity_unchanged",
    "name_only_matches",
    "mac_like_names",
    "missing_ac_scope",
    "duplicate_mac_field_records",
    "peer_mac_equals_peer_radio_mac",
    "peer_mac_equals_ap_mac",
    "radio_or_bssid_only_records",
    "interface_only_records",
    "lldp_only_records",
    "optical_fallback_records",
    "missing_min_rssi_rows",
    "missing_backup_link_rows",
)
_EXPORT_FIELD_ALIASES = {
    "duplicate_mac_field_records": ("duplicate_mac_field_records", "duplicate_peer_radio_mac_rows"),
    "peer_mac_equals_peer_radio_mac": (
        "peer_mac_equals_peer_radio_mac",
        "peer_mac_equals_peer_radio_mac_rows",
    ),
    "peer_mac_equals_ap_mac": ("peer_mac_equals_ap_mac", "peer_mac_equals_ap_mac_rows"),
    "radio_or_bssid_only_records": ("radio_or_bssid_only_records", "radio_or_bssid_only_rows"),
    "mac_like_names": ("mac_like_names", "ap_name_mac_like_rows"),
}
_SENSITIVE_KEYS = frozenset(
    {
        "items",
        "samples",
        "evidence",
        "warnings",
        "warning",
        "error",
        "traceback",
        "raw_row",
        "raw_result",
        "ap_mac",
        "peer_mac",
        "peer_radio_mac",
        "radio_mac",
        "bssid",
        "bbssid",
        "ip",
        "ip_address",
        "device_name",
        "site_name",
        "station_name",
        "section_name",
        "line_name",
        "candidate_key",
        "new_candidate_key",
        "old_match_key",
        "old_identity_key",
        "old_ap_key",
        "old_peer_key",
        "record_ref",
        "row_ref",
        "extension_ref",
        "optical_ref",
        "raw_log_path",
        "database_path",
        "xlsx_path",
        "session_path",
    }
)


@dataclass(frozen=True, slots=True)
class DiagnosticsMetric:
    key: str
    count: int
    percentage: float | None


@dataclass(frozen=True, slots=True)
class DiagnosticsSummaryViewModel:
    is_enabled: bool
    status: str
    title: str
    metrics: tuple[DiagnosticsMetric, ...] = ()
    total: int | None = None
    risk_level: str = "none"
    blocks_takeover: bool = False
    recommended_action: str = ""
    source: str | None = None

    @property
    def status_text(self) -> str:
        return _STATUS_TEXT[self.status]

    @property
    def metrics_by_key(self) -> dict[str, DiagnosticsMetric]:
        return {metric.key: metric for metric in self.metrics}

    @classmethod
    def from_job_result(
        cls,
        result: Mapping[str, object] | object,
        settings: Mapping[str, object] | None = None,
    ) -> DiagnosticsSummaryViewModel:
        if not _display_enabled(settings):
            return cls._for_status("disabled", is_enabled=False)
        try:
            if not isinstance(result, Mapping):
                return cls._for_status("failed")
            source, payload, present = _find_payload(result)
            if not present or payload is None:
                return cls._for_status("not_collected")
            if not isinstance(payload, Mapping):
                status = "redacted" if isinstance(payload, (list, tuple, set)) else "failed"
                return cls._for_status(status, source=source)
            if not _schema_supported(payload):
                return cls._for_status("not_supported", source=source)

            available = _coerce_bool(payload.get("available"))
            metrics, total = _extract_metrics(payload, source)
            if available is False:
                return cls._for_status(
                    "unavailable",
                    source=source,
                    metrics=metrics,
                    total=total,
                )
            if available is None:
                return cls._for_status(
                    "insufficient_fields",
                    source=source,
                    metrics=metrics,
                    total=total,
                )
            if total is None:
                status = "redacted" if _contains_sensitive_keys(payload) and not metrics else "insufficient_fields"
                return cls._for_status(status, source=source, metrics=metrics)

            risk_level = _risk_level(metrics)
            return cls(
                is_enabled=True,
                status="available",
                title=_title_for(source),
                metrics=metrics,
                total=total,
                risk_level=risk_level,
                blocks_takeover=risk_level in {"critical", "high", "medium"},
                recommended_action=_RISK_ACTIONS[risk_level],
                source=source,
            )
        except Exception:
            return cls._for_status("failed")

    @classmethod
    def _for_status(
        cls,
        status: str,
        *,
        is_enabled: bool = True,
        source: str | None = None,
        metrics: tuple[DiagnosticsMetric, ...] = (),
        total: int | None = None,
    ) -> DiagnosticsSummaryViewModel:
        return cls(
            is_enabled=is_enabled,
            status=status,
            title=_title_for(source),
            metrics=metrics,
            total=total,
            risk_level="none",
            blocks_takeover=False,
            recommended_action=_STATUS_ACTIONS.get(status, ""),
            source=source,
        )


def _display_enabled(settings: Mapping[str, object] | None) -> bool:
    if not isinstance(settings, Mapping):
        return False
    return _flag(settings.get(DIAGNOSTICS_ENABLED_FLAG)) and _flag(settings.get(DIAGNOSTICS_UI_ENABLED_FLAG))


def _flag(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value == 1
    return str(value or "").strip().casefold() in {"1", "true", "yes", "on", "enabled", "启用"}


def _find_payload(result: Mapping[str, object]) -> tuple[str | None, object, bool]:
    for source in _SOURCE_KEYS:
        if source in result:
            return source, result.get(source), True
    return None, None, False


def _schema_supported(payload: Mapping[str, object]) -> bool:
    if "schema_version" not in payload:
        return True
    value = _coerce_count(payload.get("schema_version"))
    return value == _SUPPORTED_SCHEMA_VERSION


def _extract_metrics(
    payload: Mapping[str, object],
    source: str | None,
) -> tuple[tuple[DiagnosticsMetric, ...], int | None]:
    total_aliases = ("total", "total_rows") if source == "export_identity_diagnostics" else ("total",)
    total = _first_count(payload, total_aliases)
    metrics: list[DiagnosticsMetric] = []
    if total is not None:
        metrics.append(DiagnosticsMetric("total", total, None))
    for key in _COUNT_FIELDS:
        aliases = _EXPORT_FIELD_ALIASES.get(key, (key,)) if source == "export_identity_diagnostics" else (key,)
        count = _first_count(payload, aliases)
        if count is None:
            continue
        percentage = round(count * 100.0 / total, 2) if total else None
        metrics.append(DiagnosticsMetric(key, count, percentage))
    return tuple(metrics), total


def _first_count(payload: Mapping[str, object], aliases: tuple[str, ...]) -> int | None:
    for key in aliases:
        if key not in payload:
            continue
        value = _coerce_count(payload.get(key))
        if value is not None:
            return value
    return None


def _coerce_count(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        return int(value) if value >= 0 and value.is_integer() else None
    text = str(value).strip()
    return int(text) if text.isdigit() else None


def _coerce_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().casefold()
    if text in {"1", "true", "yes", "on", "available"}:
        return True
    if text in {"0", "false", "no", "off", "unavailable"}:
        return False
    return None


def _contains_sensitive_keys(payload: Mapping[str, object]) -> bool:
    return any(str(key).strip().casefold() in _SENSITIVE_KEYS for key in payload)


def _risk_level(metrics: tuple[DiagnosticsMetric, ...]) -> str:
    counts = {metric.key: metric.count for metric in metrics}
    if counts.get("identity_changed", 0) > 0:
        return "critical"
    if counts.get("ambiguous", 0) > 0 or counts.get("duplicate_mac_field_records", 0) > 0:
        return "high"
    if any(counts.get(key, 0) > 0 for key in ("unresolved", "missing_ac_scope", "name_only_matches")):
        return "medium"
    return "low"


def _title_for(source: str | None) -> str:
    return _SOURCE_TITLES.get(source, "AP Identity 诊断摘要")
