"""Full-resolution, source-scoped AP and NO_BACKUP statistics shared by API/export.

Only one sample group is materialized. RSSI histograms retain exact quantiles
without retaining a second copy of the raw links. No schema or raw data writes.
"""

from __future__ import annotations

import math
import json
import sqlite3
from contextlib import closing
from dataclasses import replace
from collections import Counter
from datetime import datetime
from itertools import groupby
import unicodedata
from typing import Callable, Iterable

from netconsole.models.mesh_log_models import normalize_link_state
from netconsole.services.ap_identity.normalizers import format_mac, normalize_mac_key
from netconsole.services.mesh_quality_analysis import (
    MeshQualityRules,
    build_sample_quality,
)
from netconsole.services.rail_transit.mesh_ap_location_service import (
    MeshApLocationSnapshot,
    enrich_mesh_ap_location_row,
)


class MeshBusinessParamsError(ValueError):
    """Invalid effective Mesh business thresholds."""


def effective_business_rules(params, rules: MeshQualityRules) -> MeshQualityRules:
    changes = {
        key: getattr(params, key)
        for key in (
            "rssi_good_threshold",
            "rssi_warning_threshold",
            "backup_available_threshold",
        )
        if getattr(params, key) is not None
    }
    result = replace(rules, **changes)
    if result.rssi_warning_threshold > result.rssi_good_threshold:
        raise MeshBusinessParamsError("RSSI 关注阈值不能高于良好阈值")
    return result


def iter_business_links(conn: sqlite3.Connection, source_file_id: int | None = None):
    """Select only facts required here; tolerate old optional identity columns."""
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(mesh_links)")}
    names = (
        "id",
        "sample_id",
        "source_file_id",
        "sample_time",
        "radio",
        "timestamp_tag",
        "link_state",
        "peer_mac_raw",
        "peer_mac_normalized",
        "peer_radio_mac",
        "peer_ap_mac",
        "peer_ap_name",
        "peer_site",
        "peer_section",
        "peer_identity_status",
        "peer_identity_reason",
        "source_line_number",
        "local_rssi_db",
        "peer_rssi_db",
        "archived_filename",
        "peer_identity_source",
        "peer_match_rule",
        "station",
        "belong_section",
    )
    expressions = []
    for name in names:
        if name in columns:
            expressions.append(name)
        elif name in {"local_rssi_db", "peer_rssi_db"} and "metrics_json" in columns:
            expressions.append(f"json_extract(metrics_json, '$.{name}') AS {name}")
        else:
            expressions.append(f"NULL AS {name}")
    where, values = (
        ("WHERE source_file_id = ?", (source_file_id,))
        if source_file_id is not None
        else ("", ())
    )
    cursor = conn.execute(
        f"SELECT {', '.join(names)} FROM (SELECT {', '.join(expressions)} FROM mesh_links {where}) "
        "ORDER BY source_file_id, substr(sample_time, 1, 19), radio, "
        "COALESCE(NULLIF(sample_id, 0), NULLIF(timestamp_tag, ''), substr(sample_time, 1, 19)), id",
        values,
    )
    fields = [column[0] for column in cursor.description]
    for row in cursor:
        yield dict(zip(fields, row))


def statistics_page(
    rows: list[dict],
    *,
    page: int,
    page_size: int,
    query: str = "",
    station: str = "",
    grade: str = "",
    sort_by: str = "peer_ap_name",
    descending: bool = False,
) -> tuple[list[dict], int]:
    """Filter/sort/page aggregated results in SQLite, never slice raw links."""
    allowed = {
        "peer_ap_name",
        "avg_rssi",
        "min_rssi",
        "p10_rssi",
        "max_rssi",
        "start_time",
        "duration_seconds",
    }
    sort_by = sort_by if sort_by in allowed else "peer_ap_name"
    with closing(sqlite3.connect(":memory:")) as conn:
        conn.create_function("casefold", 1, lambda value: str(value or "").casefold())
        clauses, values = [], []
        if query:
            clauses.append(
                "instr(casefold(COALESCE(json_extract(value, '$.peer_ap_name'), '') || ' ' || "
                "COALESCE(json_extract(value, '$.peer_ap_mac'), '') || ' ' || "
                "COALESCE(json_extract(value, '$.peer_mac_raw'), '')), ?) > 0"
            )
            values.append(query.casefold())
        if station:
            clauses.append("json_extract(value, '$.station') = ?")
            values.append(station)
        if grade == "RECOGNIZED":
            clauses.append("json_extract(value, '$.peer_ap_mac') IS NOT NULL")
        elif grade:
            clauses.append("json_extract(value, '$.signal_grade') = ?")
            values.append(grade)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        data = json.dumps(rows, ensure_ascii=False, allow_nan=False)
        total = conn.execute(
            f"SELECT COUNT(*) FROM json_each(?) {where}", [data, *values]
        ).fetchone()[0]
        result = conn.execute(
            f"SELECT value FROM json_each(?) {where} ORDER BY json_extract(value, '$.{sort_by}') "
            f"{'DESC' if descending else 'ASC'} NULLS LAST, key LIMIT ? OFFSET ?",
            [data, *values, page_size, (page - 1) * page_size],
        )
        return [json.loads(row[0]) for row in result], total


def _finite_number(value: object) -> float | None:
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    return number if math.isfinite(number) else None


def business_sample_key(row: dict) -> tuple:
    bucket = str(row.get("sample_time") or "")[:19].replace("T", " ")
    return (
        row.get("source_file_id"),
        bucket,
        row.get("radio"),
        row.get("sample_id") or row.get("timestamp_tag") or bucket,
    )


def business_sort_key(row: dict) -> tuple[str, ...]:
    return tuple(str(value) for value in business_sample_key(row))


def classify_station_type(value: object) -> str:
    """Classify a formal node/location type first; only then use station names."""
    text = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    normalized = "".join(character for character in text if character.isalnum() or "\u4e00" <= character <= "\u9fff")
    if normalized in {"depot", "车辆段", "车辆基地", "段场"} or normalized.endswith(
        ("车辆段", "车辆基地", "段场")
    ):
        return "DEPOT"
    if normalized in {"parkinglot", "parkingyard", "停车场", "停车库", "停车基地"} or normalized.endswith(
        ("停车场", "停车库", "停车基地")
    ):
        return "PARKING"
    if normalized in {"station", "mainline", "mainline_ap", "正线", "车站"}:
        return "STATION"
    return "UNKNOWN"


def _location_scope(location: dict) -> str:
    formal_type = classify_station_type(location.get("station_type"))
    if formal_type != "UNKNOWN":
        return formal_type
    return classify_station_type(location.get("station"))


def _seconds(start: object, end: object) -> float:
    try:
        return max(
            0.0,
            (
                datetime.fromisoformat(str(end)) - datetime.fromisoformat(str(start))
            ).total_seconds(),
        )
    except ValueError:
        return 0.0


def _p10(histogram: Counter) -> float | None:
    count = histogram.total()
    if not count:
        return None
    position = (count - 1) * 0.1
    lower, upper = math.floor(position), math.ceil(position)
    seen = 0
    low = high = None
    for value, frequency in sorted(histogram.items()):
        if low is None and seen + frequency > lower:
            low = value
        if seen + frequency > upper:
            high = value
            break
        seen += frequency
    return round(low + (high - low) * (position - lower), 3)


def build_mesh_business_statistics(
    rows: Iterable[dict[str, object]],
    rules: MeshQualityRules,
    snapshot: MeshApLocationSnapshot,
    *,
    minimum_samples: int = 10,
    weak_signal_threshold: int | None = None,
    link_role: str = "ACTIVE",
    radio: int | None = None,
    exclude_depot: bool = True,
    exclude_parking: bool = True,
    should_cancel: Callable[[], bool] | None = None,
) -> dict[str, object]:
    """Rows must be ordered by source, sample_time, Radio, sample identity.

    Grades use the same MR RSSI units and thresholds as sample quality, applied
    to exact interpolated P10. Ten samples is a confidence floor, not an RSSI
    threshold. Unresolved groups are Peer observations, never physical APs.
    All continuous risk intervals are retained; ``qualifies_no_backup_event``
    exposes the existing minimum event duration without changing old events.
    """
    weak_threshold = rules.rssi_warning_threshold if weak_signal_threshold is None else int(weak_signal_threshold)
    if weak_threshold < 1 or weak_threshold > rules.rssi_good_threshold:
        raise MeshBusinessParamsError("弱信号阈值必须为正数且不高于信号良好阈值")
    selected_role = str(link_role or "ACTIVE").upper()
    if selected_role not in {"ACTIVE", "STANDBY", "ALL"}:
        raise MeshBusinessParamsError("AP 信号统计链路角色无效")
    aps: dict[tuple[str, str, int | None], dict] = {}
    histograms: dict[tuple[str, str, int | None], Counter] = {}
    risks: list[dict] = []
    current: dict[tuple[object, object], dict] = {}
    identity_cache: dict[tuple[str, ...], dict] = {}

    def identity(row: dict) -> dict:
        fields = (
            "peer_ap_mac",
            "peer_mac_normalized",
            "peer_radio_mac",
            "peer_identity_status",
            "peer_ap_name",
            "peer_site",
            "peer_section",
            "peer_identity_reason",
            "station",
            "belong_section",
            "peer_mac_raw",
            "peer_identity_source",
            "peer_match_rule",
        )
        key = tuple(str(row.get(field) or "") for field in fields)
        if key not in identity_cache:
            projected = enrich_mesh_ap_location_row(row, snapshot)
            location = snapshot.resolve(row)
            peer_location = snapshot.resolve(
                {
                    key: row.get(key)
                    for key in (
                        "peer_mac_normalized",
                        "peer_radio_mac",
                        "peer_mac_raw",
                        "peer_mac",
                    )
                }
            )
            status = str(projected.get("peer_identity_status") or "").lower()
            # Historical explicit physical MAC projections remain readable.
            # Ambiguous persisted or current identity evidence fails closed.
            mac = normalize_mac_key(projected.get("peer_ap_mac"))
            matched = bool(mac) and status not in {"ambiguous", "unresolved", "invalid"}
            if (
                location.identity_status == "ambiguous"
                or peer_location.identity_status == "ambiguous"
            ):
                matched = False
            if (
                peer_location.identity_status == "matched"
                and mac
                and normalize_mac_key(peer_location.mac) != mac
            ):
                matched = False
            identity_cache[key] = {
                "peer_ap_mac": format_mac(mac) if matched else None,
                "peer_ap_name": projected.get("peer_ap_name") if matched else None,
                "station": projected.get("station") or projected.get("peer_site") or "",
                "section": projected.get("section")
                or projected.get("peer_section")
                or "",
                "match_status": "matched" if matched else "unresolved",
                "peer_mac_raw": row.get("peer_mac_raw")
                or row.get("peer_mac_normalized")
                or row.get("peer_mac"),
                "identity_source": projected.get("peer_identity_source"),
                "identity_rule": projected.get("peer_match_rule"),
                "identity_reason": projected.get("peer_identity_reason"),
                "station_type": location.station_type,
                "station_scope": _location_scope(
                    {
                        "station_type": location.station_type,
                        "station": projected.get("station")
                        or projected.get("peer_site")
                        or "",
                    }
                ),
            }
        return identity_cache[key]

    def finish(scope: tuple[object, object]) -> None:
        block = current.pop(scope, None)
        if block is not None:
            block.pop("station_type", None)
            block.pop("station_scope", None)
            block["duration_seconds"] = _seconds(block["start_time"], block["end_time"])
            block["qualifies_no_backup_event"] = (
                block["duration_seconds"] >= rules.no_backup_min_seconds
            )
            block.pop("group_key", None)
            risks.append(block)

    previous_source = object()
    for index, (_key, group) in enumerate(groupby(rows, business_sample_key)):
        if previous_source != _key[0]:
            for scope in list(current):
                finish(scope)
            previous_source = _key[0]
        if index % 1000 == 0 and should_cancel and should_cancel():
            from netconsole.services.mesh_link_detail_export import (
                MeshLinkDetailExportCancelled,
            )

            raise MeshLinkDetailExportCancelled("导出已取消")
        sample_rows = []
        excluded_active = False
        for raw in group:
            row = dict(raw)
            row["link_state"] = normalize_link_state(
                row.get("link_state") or row.get("state")
            )
            row["peer_mac"] = normalize_mac_key(
                row.get("peer_mac_normalized")
                or row.get("peer_mac")
                or row.get("peer_mac_raw")
            )
            row["mr_rssi"] = _finite_number(
                row.get("local_rssi_db", row.get("mr_rssi"))
            )
            row["peer_rssi"] = _finite_number(
                row.get("peer_rssi_db", row.get("peer_rssi"))
            )
            info = identity(row)
            row["station_scope"] = info["station_scope"]
            excluded = (
                exclude_depot and info["station_scope"] == "DEPOT"
            ) or (
                exclude_parking and info["station_scope"] == "PARKING"
            )
            if excluded:
                excluded_active = excluded_active or row["link_state"] == "ACTIVE"
                continue
            sample_rows.append(row)
        scope = (_key[0], _key[2])
        if excluded_active:
            finish(scope)
        if not sample_rows:
            finish(scope)
            continue
        # Reuse the actual backup predicate/RSSI fallback, never LinkCnt.
        sample = build_sample_quality(sample_rows, rules)[0]
        scope = (sample["source_file_id"], sample["radio"])
        active = [
            row
            for row in sample_rows
            if str(row.get("link_state") or "").upper() == "ACTIVE"
        ]
        if selected_role == "ACTIVE" and len(active) != 1:
            finish(scope)
            continue
        sample_stat_keys: set[tuple[str, str, int | None]] = set()
        for candidate in sample_rows:
            role = str(candidate.get("link_state") or "").upper()
            sample_radio = int(candidate["radio"]) if candidate.get("radio") is not None else None
            if role not in {"ACTIVE", "STANDBY"} or (selected_role != "ALL" and role != selected_role):
                continue
            if radio is not None and sample_radio != radio:
                continue
            info = identity(candidate)
            mac = info["peer_ap_mac"]
            physical_key = normalize_mac_key(mac) if mac else f"unresolved:{candidate.get('peer_mac') or candidate.get('id') or index}"
            stat_key = (physical_key, role, sample_radio)
            if stat_key in sample_stat_keys:
                continue
            sample_stat_keys.add(stat_key)
            timestamp = str(candidate.get("sample_time") or "")
            ap = aps.setdefault(
                stat_key,
                {
                    **info,
                    "link_role": role,
                    "radio": sample_radio,
                    "valid_sample_count": 0,
                    "weak_sample_count": 0,
                    "first_seen": timestamp,
                    "last_seen": "",
                    "last_rssi": None,
                    "_last_rssi_time": "",
                },
            )
            ap["first_seen"] = min(ap["first_seen"], timestamp)
            if timestamp >= ap["last_seen"]:
                ap["last_seen"] = timestamp
            rssi = candidate["mr_rssi"]
            if rssi is not None and rssi > 0 and timestamp >= ap["_last_rssi_time"]:
                ap["_last_rssi_time"] = timestamp
                ap["last_rssi"] = rssi
            histogram = histograms.setdefault(stat_key, Counter())
            if rssi is not None and rssi > 0:
                histogram[rssi] += 1
                ap["valid_sample_count"] += 1
                ap["weak_sample_count"] += int(rssi < weak_threshold)
        if len(active) != 1:
            finish(scope)
            continue
        row = active[0]
        info = identity(row)
        mac = info["peer_ap_mac"]
        ap_key = normalize_mac_key(mac) if mac else f"unresolved:{row.get('peer_mac') or row.get('id') or index}"
        if int(sample["available_backup_count"]) > 0:
            finish(scope)
            continue
        kind = (
            "NO_STANDBY"
            if not sample["standby_peer_count"]
            else (
                "WEAK_STANDBY"
                if sample["best_backup_rssi"] != ""
                else "MISSING_STANDBY_RSSI"
            )
        )
        block_key = (ap_key, kind)
        block = current.get(scope)
        if block and (
            block["group_key"] != block_key
            or _seconds(block["end_time"], row["sample_time"]) > 2
        ):
            finish(scope)
            block = None
        if block is None:
            block = {
                **info,
                "source_file_id": scope[0],
                "radio": scope[1],
                "group_key": block_key,
                "start_time": row["sample_time"],
                "end_time": row["sample_time"],
                "standby_peer_count": 0,
                "available_backup_count": 0,
                "best_backup_rssi": None,
                "risk_type": kind,
                "diagnosis": sample["backup_judgment_reason"],
                "sample_count": 0,
                "source_line_number_start": row.get("source_line_number"),
                "source_line_number_end": row.get("source_line_number"),
                "source_file": row.get("archived_filename")
                or row.get("source_file")
                or "",
                "active_peer_mac": row.get("peer_mac_raw") or row.get("peer_mac"),
            }
            current[scope] = block
        block["end_time"] = row["sample_time"]
        block["sample_count"] += 1
        block["source_line_number_end"] = row.get("source_line_number")
        block["standby_peer_count"] = max(
            block["standby_peer_count"], sample["standby_peer_count"]
        )
        backup = sample["best_backup_rssi"]
        if backup != "":
            block["best_backup_rssi"] = max(block["best_backup_rssi"] or backup, backup)
    for scope in list(current):
        finish(scope)
    counts = dict.fromkeys(
        ("GOOD", "WARNING", "BAD", "INSUFFICIENT", "UNRECOGNIZED"), 0
    )
    for key, ap in aps.items():
        histogram = histograms[key]
        count = ap["valid_sample_count"]
        p10 = _p10(histogram)
        ap.update(
            avg_rssi=round(sum(value * n for value, n in histogram.items()) / count, 3)
            if count
            else None,
            min_rssi=min(histogram, default=None),
            max_rssi=max(histogram, default=None),
            p10_rssi=p10,
            weak_ratio=round(ap["weak_sample_count"] / count, 6) if count else None,
        )
        grade = (
            "UNRECOGNIZED"
            if not ap["peer_ap_mac"]
            else "INSUFFICIENT"
            if count < minimum_samples
            else (
                "GOOD"
                if p10 >= rules.rssi_good_threshold
                else "WARNING"
                if p10 >= weak_threshold
                else "BAD"
            )
        )
        ap["signal_grade"] = grade
        ap.pop("_last_rssi_time", None)
        ap.pop("station_type", None)
        ap.pop("station_scope", None)
        counts[grade] += 1
    risk_order = {"NO_STANDBY": 0, "WEAK_STANDBY": 1, "MISSING_STANDBY_RSSI": 2}
    risks.sort(
        key=lambda row: (
            -float(row["duration_seconds"]),
            risk_order.get(str(row["risk_type"]), 3),
            str(row["start_time"]),
            str(row["radio"]),
        )
    )
    return {
        "aps": list(aps.values()),
        "single_links": risks,
        "summary": {
            "ap_total": len({ap["peer_ap_mac"] for ap in aps.values() if ap["peer_ap_mac"]}),
            "grades": counts,
            "single_link_count": len(risks),
            "single_link_seconds": sum(row["duration_seconds"] for row in risks),
            "single_link_ap_count": len(
                {row["peer_ap_mac"] for row in risks if row["peer_ap_mac"]}
            ),
            "single_link_radios": sorted({row["radio"] for row in risks}, key=str),
            "no_backup_event_min_seconds": rules.no_backup_min_seconds,
            "good_threshold": rules.rssi_good_threshold,
            "warning_threshold": weak_threshold,
            "backup_available_threshold": rules.backup_available_threshold,
            "minimum_samples": minimum_samples,
            "grade_metric": "ACTIVE_MR_RSSI_P10",
            "rule_version": "mesh_business_v1",
            "exclude_depot": exclude_depot,
            "exclude_parking": exclude_parking,
            "scope_label": "CURRENT_FILTERED_SCOPE"
            if exclude_depot or exclude_parking
            else "FULL_SCOPE",
        },
    }
