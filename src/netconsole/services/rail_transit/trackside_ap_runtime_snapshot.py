"""协调轨旁 AP 运行态、交换机 LLDP 和光衰事实的只读快照。

该模块只根据调用方已经读取的事实计算一致性诊断，不创建任务、不写库，
也不改变任何原始采集记录。当前数据库尚无统一 generation 表，因此优先
使用各来源的 collect_run_uuid，并以最新成功事实的 collected_at 作为兼容
时序证据。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
from typing import Iterable, Literal, Mapping


SnapshotStatus = Literal["consistent", "lldp_stale", "optical_stale", "partial", "unavailable"]
LldpHistoryStatus = Literal[
    "current_consistent",
    "current_conflict",
    "historical_conflict",
    "port_migrated",
    "stale_snapshot",
    "no_current_evidence",
]


@dataclass(frozen=True)
class TracksideApRuntimeSnapshot:
    fit_ap_collected_at: str = ""
    fit_ap_generation: str = ""
    switch_lldp_collected_at: str = ""
    switch_lldp_generation: str = ""
    optical_collected_at: str = ""
    optical_generation: str = ""
    station_data_revision: str = ""
    ap_identity_revision: str = ""
    snapshot_status: SnapshotStatus = "unavailable"
    snapshot_age_seconds: int | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def lldp_is_stale(self) -> bool:
        return self.snapshot_status == "lldp_stale"

    @property
    def has_current_lldp(self) -> bool:
        return bool(self.switch_lldp_collected_at or self.switch_lldp_generation)

    def to_dict(self) -> dict[str, object]:
        return {
            "fit_ap_collected_at": self.fit_ap_collected_at,
            "fit_ap_generation": self.fit_ap_generation,
            "switch_lldp_collected_at": self.switch_lldp_collected_at,
            "switch_lldp_generation": self.switch_lldp_generation,
            "optical_collected_at": self.optical_collected_at,
            "optical_generation": self.optical_generation,
            "station_data_revision": self.station_data_revision,
            "ap_identity_revision": self.ap_identity_revision,
            "snapshot_status": self.snapshot_status,
            "snapshot_age_seconds": self.snapshot_age_seconds,
            "warnings": list(self.warnings),
        }


def build_trackside_ap_runtime_snapshot(
    *,
    fit_ap_rows: Iterable[Mapping[str, object | None]] = (),
    switch_lldp_rows: Iterable[Mapping[str, object | None]] = (),
    optical_rows: Iterable[Mapping[str, object | None]] = (),
    station_data_revision: object = "",
    ap_identity_revision: object = "",
    now: datetime | None = None,
) -> TracksideApRuntimeSnapshot:
    fit_rows = [dict(row) for row in fit_ap_rows]
    lldp_rows = [dict(row) for row in switch_lldp_rows]
    optical = [dict(row) for row in optical_rows]
    fit_time = _latest_time(fit_rows)
    lldp_time = _latest_time(lldp_rows, "observed_at")
    optical_time = _latest_time(optical)
    fit_generation = _generation(fit_rows)
    lldp_generation = _generation(lldp_rows)
    optical_generation = _generation(optical)
    warnings: list[str] = []
    status: SnapshotStatus
    if not fit_rows:
        status = "unavailable"
        warnings.append("FIT-AP 当前运行快照不可用")
    elif not lldp_rows:
        status = "partial"
        warnings.append("车站交换机当前 LLDP 快照不可用")
    elif _before(lldp_time, fit_time):
        status = "lldp_stale"
        warnings.append("车站交换机 LLDP 快照早于 FIT-AP 运行快照")
    elif optical_rows and _before(optical_time, fit_time):
        status = "optical_stale"
        warnings.append("光衰快照早于 FIT-AP 运行快照")
    else:
        status = "consistent"
    age = _age_seconds(now or datetime.now(timezone.utc), fit_time)
    return TracksideApRuntimeSnapshot(
        fit_ap_collected_at=fit_time,
        fit_ap_generation=fit_generation,
        switch_lldp_collected_at=lldp_time,
        switch_lldp_generation=lldp_generation,
        optical_collected_at=optical_time,
        optical_generation=optical_generation,
        station_data_revision=str(station_data_revision or ""),
        ap_identity_revision=str(ap_identity_revision or ""),
        snapshot_status=status,
        snapshot_age_seconds=age,
        warnings=tuple(warnings),
    )


def select_latest_lldp_snapshot_rows(
    rows: Iterable[Mapping[str, object | None]],
) -> list[dict[str, object | None]]:
    """按设备选择最近一批 LLDP；旧接口仍由历史查询单独保留。"""

    grouped: dict[str, list[dict[str, object | None]]] = {}
    for raw in rows:
        row = dict(raw)
        if not _is_successful_snapshot_row(row):
            continue
        grouped.setdefault(str(row.get("device_uuid") or row.get("switch_device_uuid") or ""), []).append(row)
    selected: list[dict[str, object | None]] = []
    for device_rows in grouped.values():
        if not device_rows:
            continue
        newest = max(device_rows, key=_row_time_key)
        generation = str(newest.get("collect_run_uuid") or "").strip()
        if generation:
            candidates = [row for row in device_rows if str(row.get("collect_run_uuid") or "").strip() == generation]
        else:
            timestamp = _row_time_key(newest)[0]
            candidates = [row for row in device_rows if _row_time_key(row)[0] == timestamp]
        selected.extend(candidates)
    return selected


def deduplicate_lldp_snapshot_rows(
    rows: Iterable[Mapping[str, object | None]],
) -> list[dict[str, object | None]]:
    """去重 merged/direct 对同一事实的重复表达。"""

    result: dict[tuple[str, str, str, str, str], dict[str, object | None]] = {}
    for raw in rows:
        row = dict(raw)
        generation = str(
            row.get("collect_run_uuid")
            or row.get("session_id")
            or row.get("generation")
            or ""
        ).strip().casefold()
        key = (
            str(row.get("device_uuid") or row.get("switch_device_uuid") or "").strip().casefold(),
            str(row.get("local_interface") or row.get("switch_interface") or "").strip().casefold(),
            _compact_mac(row.get("neighbor_mac") or row.get("observed_ap_mac") or row.get("ap_mac")),
            str(row.get("neighbor_interface") or row.get("interface") or "").strip().casefold(),
            generation or str(row.get("collected_at") or row.get("observed_at") or "").strip().casefold(),
        )
        if not any((key[0], key[1], key[3])):
            key = (*key[:4], str(row.get("station_id") or row.get("device_station") or "").strip().casefold(), key[4])
        if not any(key):
            continue
        existing = result.get(key)
        if existing is None or _source_score(row) > _source_score(existing):
            result[key] = row
        elif existing:
            for field, value in row.items():
                if existing.get(field) in (None, "") and value not in (None, ""):
                    existing[field] = value
    return list(result.values())


def classify_lldp_history_status(
    current_rows: Iterable[Mapping[str, object | None]],
    history_rows: Iterable[Mapping[str, object | None]] = (),
) -> LldpHistoryStatus:
    """返回 current view 使用的 LLDP 状态，而不是把历史冲突带入当前。"""

    current = deduplicate_lldp_snapshot_rows(current_rows)
    history = deduplicate_lldp_snapshot_rows(history_rows)
    if not current:
        return "no_current_evidence" if not history else "stale_snapshot"
    current_by_ap = _lldp_candidates_by_ap(current)
    if any(len(candidates) > 1 for candidates in current_by_ap.values()):
        return "current_conflict"
    history_by_ap = _lldp_candidates_by_ap(history)
    for ap_key, candidates in current_by_ap.items():
        historical_candidates = history_by_ap.get(ap_key, set())
        if len(historical_candidates) > 1:
            return "historical_conflict"
        if (
            historical_candidates
            and any(any(candidate[1:]) for candidate in historical_candidates)
            and any(any(candidate[1:]) for candidate in candidates)
            and not historical_candidates.intersection(candidates)
        ):
            return "port_migrated"
    return "current_consistent"


def _lldp_candidates_by_ap(
    rows: Iterable[Mapping[str, object | None]],
) -> dict[str, set[tuple[str, str, str]]]:
    grouped: dict[str, set[tuple[str, str, str]]] = {}
    for row in rows:
        ap_key = _compact_mac(row.get("neighbor_mac") or row.get("observed_ap_mac") or row.get("ap_mac"))
        if not ap_key:
            continue
        candidate = (
            str(row.get("device_uuid") or row.get("switch_device_uuid") or "").strip().casefold(),
            str(row.get("local_interface") or row.get("switch_interface") or "").strip().casefold(),
            str(row.get("neighbor_interface") or row.get("interface") or "").strip().casefold(),
        )
        grouped.setdefault(ap_key, set()).add(candidate)
    return grouped


def _is_successful_snapshot_row(row: Mapping[str, object | None]) -> bool:
    """Ignore explicit failed/partial records when selecting current topology."""

    for field_name in ("collection_status", "collect_status", "batch_status", "status"):
        value = str(row.get(field_name) or "").strip().casefold()
        if value in {"failed", "failure", "error", "partial", "incomplete", "timeout", "cancelled"}:
            return False
    return True


def _latest_time(rows: list[dict[str, object | None]], fallback_field: str = "") -> str:
    values = []
    for row in rows:
        value = row.get(fallback_field) if fallback_field else None
        value = value or row.get("collected_at") or row.get("updated_at")
        if str(value or "").strip():
            values.append(str(value).strip())
    return max(values) if values else ""


def _generation(rows: list[dict[str, object | None]]) -> str:
    values = sorted({str(row.get("collect_run_uuid") or "").strip() for row in rows if str(row.get("collect_run_uuid") or "").strip()})
    if not values:
        return ""
    if len(values) == 1:
        return values[0]
    digest = hashlib.sha256("|".join(values).encode("utf-8")).hexdigest()[:16]
    return f"batch:{digest}"


def _row_time_key(row: Mapping[str, object | None]) -> tuple[str, str, int]:
    try:
        row_id = int(str(row.get("id") or 0))
    except ValueError:
        row_id = 0
    return (
        str(row.get("collected_at") or row.get("observed_at") or row.get("updated_at") or ""),
        str(row.get("updated_at") or ""),
        row_id,
    )


def _before(left: str, right: str) -> bool:
    return bool(left and right and left < right)


def _age_seconds(now: datetime, value: str) -> int | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0, int((now - parsed).total_seconds()))
    except ValueError:
        return None


def _compact_mac(value: object) -> str:
    return "".join(character for character in str(value or "").casefold() if character in "0123456789abcdef")


def _source_score(row: Mapping[str, object | None]) -> tuple[int, int]:
    source = str(row.get("lldp_source") or row.get("source") or "").casefold()
    return (2 if source == "merged" else 1 if source == "ap_direct_lldp" else 0, int(bool(row.get("neighbor_mac") or row.get("ap_mac"))))


__all__ = [
    "TracksideApRuntimeSnapshot",
    "build_trackside_ap_runtime_snapshot",
    "select_latest_lldp_snapshot_rows",
    "deduplicate_lldp_snapshot_rows",
    "classify_lldp_history_status",
]
