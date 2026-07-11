from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable, Mapping, Sequence

from netconsole.services.ap_identity import normalize_mac


DEFAULT_SAMPLE_LIMIT = 20
DEFAULT_WARNING_LIMIT = 50

_PEER_MAC_FIELDS = ("peer_mac", "peer_mac_raw", "peer_mac_normalized", "PeerMac", "Peer MAC")
_AP_MAC_FIELDS = ("peer_ap_mac", "ap_mac", "AP MAC", "对端AP MAC")
_PEER_RADIO_MAC_FIELDS = ("peer_radio_mac", "Peer Radio MAC")
_AP_NAME_FIELDS = ("peer_ap_name", "ap_name", "当前PEER AP名称", "对端AP名称", "AP名称")
_RADIO_FIELDS = ("peer_radio", "peer_radio_label", "radio_mac", "Radio MAC", "Radio", "射频ID")
_BSSID_FIELDS = ("bssid", "bbssid", "BSSID", "BBSSID")
_MIN_RSSI_FIELDS = ("min_mr_rssi", "min_rssi", "最低RSSI", "MR侧最低RSSI")
_BACKUP_FIELDS = (
    "backup_peer_mac",
    "standby_peer_mac",
    "backup_link",
    "standby_link",
    "backup_count",
    "standby_count",
    "备用链路",
    "备份链路",
    "备链",
)
_MAPPING_SOURCE_FIELDS = (
    "peer_resolve_source",
    "mapping_source",
    "belonging_source",
    "identity_source",
    "归属来源",
)
_REFERENCE_FIELDS = ("record_seq", "source_line_number", "sample_time", "采样时间", "collector_time")


@dataclass(frozen=True)
class ExportIdentityDiagnosticsReport:
    available: bool
    export_type: str
    total_rows: int = 0
    duplicate_peer_radio_mac_rows: int = 0
    peer_mac_equals_ap_mac_rows: int = 0
    peer_mac_equals_peer_radio_mac_rows: int = 0
    ap_name_mac_like_rows: int = 0
    radio_or_bssid_only_rows: int = 0
    missing_ap_mac_rows: int = 0
    missing_peer_mac_rows: int = 0
    missing_min_rssi_rows: int = 0
    missing_backup_link_rows: int = 0
    has_mapping_source_field: bool = False
    has_peer_radio_mac_field: bool = False
    samples: tuple[dict[str, object], ...] = ()
    warnings: tuple[str, ...] = ()
    error: str = ""

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["samples"] = [dict(sample) for sample in self.samples]
        payload["warnings"] = list(self.warnings)
        return payload


class ExportIdentityDiagnostics:
    """只读统计导出行中的 identity 字段风险，不参与字段生成或改写。"""

    def __init__(
        self,
        export_type: str,
        *,
        sample_limit: int = DEFAULT_SAMPLE_LIMIT,
        warning_limit: int = DEFAULT_WARNING_LIMIT,
    ) -> None:
        self.export_type = str(export_type or "unknown")
        self.sample_limit = max(0, min(int(sample_limit), DEFAULT_SAMPLE_LIMIT))
        self.warning_limit = max(0, min(int(warning_limit), DEFAULT_WARNING_LIMIT))
        self.available = True
        self.error = ""
        self.total_rows = 0
        self.duplicate_peer_radio_mac_rows = 0
        self.peer_mac_equals_ap_mac_rows = 0
        self.peer_mac_equals_peer_radio_mac_rows = 0
        self.ap_name_mac_like_rows = 0
        self.radio_or_bssid_only_rows = 0
        self.missing_ap_mac_rows = 0
        self.missing_peer_mac_rows = 0
        self.missing_min_rssi_rows = 0
        self.missing_backup_link_rows = 0
        self.has_mapping_source_field = False
        self.has_peer_radio_mac_field = False
        self._recognized_identity_field = False
        self._samples: list[dict[str, object]] = []
        self._warnings: list[str] = []

    def inspect_mesh_link_detail_rows(
        self,
        rows: Iterable[Mapping[str, object]],
    ) -> ExportIdentityDiagnosticsReport:
        for row_index, row in enumerate(rows, start=1):
            self.inspect_mesh_link_detail_row(row, row_index=row_index)
        return self.summarize()

    def inspect_mesh_link_detail_row(
        self,
        row: Mapping[str, object],
        *,
        row_index: int | None = None,
    ) -> None:
        self._inspect_mapping(row, row_index=row_index)

    def inspect_online_mr_detail_rows(
        self,
        rows: Iterable[Mapping[str, object] | Sequence[object]],
        *,
        headers: Sequence[object] | None = None,
    ) -> ExportIdentityDiagnosticsReport:
        header_names = tuple(str(header) for header in headers) if headers is not None else None
        for row_index, row in enumerate(rows, start=1):
            if isinstance(row, Mapping):
                mapping = row
            elif header_names is not None:
                mapping = dict(zip(header_names, row))
            else:
                raise ValueError("位置数组 diagnostics 缺少表头")
            self._inspect_mapping(mapping, row_index=row_index)
        return self.summarize()

    def mark_unavailable(self, error: BaseException | str) -> None:
        self.available = False
        text = str(error).strip()
        error_type = error.__class__.__name__ if isinstance(error, BaseException) else "DiagnosticsError"
        self.error = f"{error_type}: {text}"[:300]
        self._warn_once("identity diagnostics 执行失败，原导出结果未受影响")

    def summarize(self) -> ExportIdentityDiagnosticsReport:
        available = self.available and (self.total_rows == 0 or self._recognized_identity_field)
        error = self.error
        if self.total_rows and not self._recognized_identity_field:
            error = error or "DiagnosticsUnavailable: 输入行没有可安全识别的 identity 字段"
            self._warn_once("输入行没有可安全识别的 identity 字段")
        return ExportIdentityDiagnosticsReport(
            available=available,
            export_type=self.export_type,
            total_rows=self.total_rows,
            duplicate_peer_radio_mac_rows=self.duplicate_peer_radio_mac_rows,
            peer_mac_equals_ap_mac_rows=self.peer_mac_equals_ap_mac_rows,
            peer_mac_equals_peer_radio_mac_rows=self.peer_mac_equals_peer_radio_mac_rows,
            ap_name_mac_like_rows=self.ap_name_mac_like_rows,
            radio_or_bssid_only_rows=self.radio_or_bssid_only_rows,
            missing_ap_mac_rows=self.missing_ap_mac_rows,
            missing_peer_mac_rows=self.missing_peer_mac_rows,
            missing_min_rssi_rows=self.missing_min_rssi_rows,
            missing_backup_link_rows=self.missing_backup_link_rows,
            has_mapping_source_field=self.has_mapping_source_field,
            has_peer_radio_mac_field=self.has_peer_radio_mac_field,
            samples=tuple(self._samples),
            warnings=tuple(self._warnings),
            error=error,
        )

    def _inspect_mapping(self, row: Mapping[str, object], *, row_index: int | None) -> None:
        self.total_rows += 1
        index = int(row_index or self.total_rows)
        peer_mac, peer_present = _first_value(row, _PEER_MAC_FIELDS)
        ap_mac, ap_present = _first_value(row, _AP_MAC_FIELDS)
        peer_radio_mac, peer_radio_present = _first_value(row, _PEER_RADIO_MAC_FIELDS)
        ap_name, ap_name_present = _first_value(row, _AP_NAME_FIELDS)
        radio, radio_present = _first_value(row, _RADIO_FIELDS)
        bssid, bssid_present = _first_value(row, _BSSID_FIELDS)
        min_rssi, min_rssi_present = _first_value(row, _MIN_RSSI_FIELDS)
        backup, backup_present = _first_value(row, _BACKUP_FIELDS)
        _mapping_source, mapping_source_present = _first_value(row, _MAPPING_SOURCE_FIELDS)

        self._recognized_identity_field = self._recognized_identity_field or any(
            (peer_present, ap_present, peer_radio_present, ap_name_present, radio_present, bssid_present)
        )
        self.has_mapping_source_field = self.has_mapping_source_field or mapping_source_present
        self.has_peer_radio_mac_field = self.has_peer_radio_mac_field or peer_radio_present

        normalized_peer = _normalize_export_mac(peer_mac)
        normalized_ap = _normalize_export_mac(ap_mac)
        normalized_peer_radio = _normalize_export_mac(peer_radio_mac)
        reasons: list[str] = []

        if normalized_peer and normalized_ap and normalized_peer == normalized_ap:
            self.peer_mac_equals_ap_mac_rows += 1
            reasons.append("peer_mac_equals_ap_mac")
            self._warn_once("存在 Peer MAC 与 AP MAC 相同的记录")
        if normalized_peer and normalized_peer_radio and normalized_peer == normalized_peer_radio:
            self.peer_mac_equals_peer_radio_mac_rows += 1
            reasons.append("peer_mac_equals_peer_radio_mac")
            self._warn_once("存在 Peer MAC 与 Peer Radio MAC 相同的记录")
        if normalized_peer_radio and normalized_peer_radio in {normalized_peer, normalized_ap}:
            self.duplicate_peer_radio_mac_rows += 1
            reasons.append("duplicate_peer_radio_mac")
        if _normalize_export_mac(ap_name):
            self.ap_name_mac_like_rows += 1
            reasons.append("ap_name_mac_like")
            self._warn_once("存在 MAC-like AP 名称")
        if _is_empty(peer_mac):
            self.missing_peer_mac_rows += 1
            reasons.append("missing_peer_mac")
        if _is_empty(ap_mac):
            self.missing_ap_mac_rows += 1
            reasons.append("missing_ap_mac")
        if not min_rssi_present or _is_empty(min_rssi):
            self.missing_min_rssi_rows += 1
            reasons.append("missing_min_rssi")
        if not backup_present or _is_empty(backup):
            self.missing_backup_link_rows += 1
            reasons.append("missing_backup_link")
        if _is_empty(peer_mac) and _is_empty(ap_mac) and any(
            not _is_empty(value) for value in (peer_radio_mac, radio, bssid)
        ):
            self.radio_or_bssid_only_rows += 1
            reasons.append("radio_or_bssid_only")

        if reasons and len(self._samples) < self.sample_limit:
            reference, _present = _first_value(row, _REFERENCE_FIELDS)
            sample: dict[str, object] = {"row_index": index, "reasons": reasons}
            if not _is_empty(reference):
                sample["record_ref"] = str(reference)[:80]
            self._samples.append(sample)

    def _warn_once(self, message: str) -> None:
        if message not in self._warnings and len(self._warnings) < self.warning_limit:
            self._warnings.append(message)


def unavailable_export_identity_diagnostics(
    export_type: str,
    error: BaseException | str,
) -> dict[str, object]:
    text = str(error).strip()
    error_type = error.__class__.__name__ if isinstance(error, BaseException) else "DiagnosticsError"
    return ExportIdentityDiagnosticsReport(
        available=False,
        export_type=str(export_type or "unknown"),
        warnings=("identity diagnostics 执行失败，原导出结果未受影响",),
        error=f"{error_type}: {text}"[:300],
    ).to_dict()


def _first_value(row: Mapping[str, object], names: Sequence[str]) -> tuple[object | None, bool]:
    present = False
    fallback: object | None = None
    for name in names:
        if name not in row:
            continue
        present = True
        value = row.get(name)
        if fallback is None:
            fallback = value
        if not _is_empty(value):
            return value, True
    return fallback, present


def _is_empty(value: object) -> bool:
    return value is None or str(value).strip().casefold() in {"", "-", "--", "n/a", "na", "none", "null"}


def _normalize_export_mac(value: object) -> str | None:
    normalized = normalize_mac(value)
    if normalized is not None or value is None:
        return normalized
    text = str(value).strip()
    return normalize_mac(text.replace("-", ""))
