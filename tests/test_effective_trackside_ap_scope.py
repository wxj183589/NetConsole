from __future__ import annotations

import json
import hashlib

from netconsole.services.rail_transit.effective_trackside_ap_scope import (
    TracksideApScopeContext,
    resolve_effective_trackside_ap_scope,
)


def _station(row_id: int, name: str, node_uid: str, sort_order: int) -> dict[str, object]:
    return {
        "id": row_id,
        "belong_type": "__base_station__",
        "station_id": f"station:{hashlib.sha1(node_uid.encode('utf-8')).hexdigest()[:12]}",
        "station_name": name,
        "raw_payload_json": json.dumps(
            {
                "node_uid": node_uid,
                "canonical_station_name": name.removeprefix(f"{sort_order:02d}-"),
                "sort_order": sort_order,
            },
            ensure_ascii=False,
        ),
    }


def _reference(
    row_id: int,
    name: str,
    station: str,
    mac: str,
    **metadata: object,
) -> dict[str, object]:
    return {
        "id": row_id,
        "site_id": "extension",
        "belong_type": "station",
        "station_name": station,
        "ap_name": name,
        "ap_mac_norm": mac,
        "line_name": "杭州地铁10号线延长线",
        "raw_payload_json": json.dumps(metadata, ensure_ascii=False),
    }


def _resource(
    extension_id: int | None,
    name: str,
    mac: str,
    *,
    ap_uuid: str,
    state: str = "R/M",
) -> dict[str, object]:
    return {
        "extension_id": extension_id,
        "ap_uuid": ap_uuid,
        "ap_name": name,
        "ap_mac": mac,
        "state": state,
        "updated_at": "2026-07-30T15:00:00+08:00",
    }


def _resolve(
    *,
    stations: list[dict[str, object]],
    plans: list[dict[str, object]],
    references: list[dict[str, object]],
    resources: list[dict[str, object]],
    runtime_station_rows: list[dict[str, object]] | None = None,
):
    station_ids_by_name: dict[str, list[str]] = {}
    station_ids_by_node_uid: dict[str, str] = {}
    for station in stations:
        metadata = json.loads(str(station.get("raw_payload_json") or "{}"))
        station_id = str(station.get("station_id") or "")
        station_ids_by_node_uid[str(metadata.get("node_uid") or "")] = station_id
        for name in (
            str(station.get("station_name") or ""),
            str(metadata.get("canonical_station_name") or ""),
        ):
            if station_id not in station_ids_by_name.setdefault(name, []):
                station_ids_by_name[name].append(station_id)
    for row in [*plans, *references]:
        if row.get("station_id"):
            continue
        metadata = json.loads(str(row.get("raw_payload_json") or "{}"))
        node_uid = str(metadata.get("station_node_uid") or "")
        candidates = station_ids_by_name.get(str(row.get("station_name") or ""), [])
        station_id = station_ids_by_node_uid.get(node_uid, "")
        if not station_id and len(candidates) == 1:
            station_id = candidates[0]
        if station_id:
            row["station_id"] = station_id
    return resolve_effective_trackside_ap_scope(
        context=TracksideApScopeContext(
            site_id="extension",
            project_id="extension",
            line_name="杭州地铁10号线延长线",
            project_phase="phase_2",
        ),
        station_rows=stations,
        plan_rows=plans,
        reference_rows=references,
        resource_rows=resources,
        runtime_station_rows=runtime_station_rows,
    )


def test_numbered_station_aliases_group_by_one_station_id_and_dedupe_ac_rows() -> None:
    stations = [_station(100, "16-双陈站", "node-shuangchen", 16)]
    references = [
        _reference(
            1,
            "AP-SC-01",
            "双陈站",
            "001122334455",
            operation_status="in_service",
            project_id="extension",
            construction_phase_id="phase_2",
        )
    ]
    scope = _resolve(
        stations=stations,
        plans=[
            {
                "station_id": "",
                "station_name": "双陈站",
                "ap_count": 1,
                "sequence_no": 16,
            }
        ],
        references=references,
        resources=[
            _resource(1, "AP-SC-01", "0011-2233-4455", ap_uuid="ac-a-ap-1"),
            _resource(1, "AP-SC-01", "0011-2233-4455", ap_uuid="ac-b-ap-9"),
        ],
    )

    rows = scope.station_statistics()
    assert len(rows) == 1
    assert rows[0]["station_name"] == "16-双陈站"
    assert rows[0]["planned_ap_count"] == 1
    assert rows[0]["actual_online_count"] == 1
    assert rows[0]["online_rate"] == 100.0
    assert scope.scope_station_count == 1
    assert scope.scope_device_count == 1


def test_scope_restores_numbered_station_display_from_source_metadata() -> None:
    station = _station(100, "小洋江站", "node-xiaoyangjiang", 1)
    station["raw_payload_json"] = json.dumps(
        {
            "node_uid": "node-xiaoyangjiang",
            "canonical_station_name": "小洋江站",
            "source_station_value": "01小洋江站",
            "source_kind": "device_station_field",
            "sort_order": 1,
        },
        ensure_ascii=False,
    )
    scope = _resolve(
        stations=[station],
        plans=[{"station_name": "小洋江站", "ap_count": 1, "sequence_no": 1}],
        references=[],
        resources=[],
    )

    assert scope.station_statistics()[0]["station_name"] == "01-小洋江站"


def test_plan_uses_stable_station_node_id_when_display_name_has_changed() -> None:
    stations = [_station(100, "16-双陈站", "node-shuangchen", 16)]
    scope = _resolve(
        stations=stations,
        plans=[
            {
                "station_id": "node-shuangchen",
                "station_name": "双陈站旧名称",
                "ap_count": 3,
                "sequence_no": 16,
            }
        ],
        references=[
            _reference(
                1,
                "AP-SC-01",
                "双陈站",
                "001122334455",
                station_node_uid="node-shuangchen",
                operation_status="in_service",
                project_id="extension",
                construction_phase_id="phase_2",
            )
        ],
        resources=[
            _resource(1, "AP-SC-01", "001122334455", ap_uuid="online-1")
        ],
    )

    row = scope.station_statistics()[0]
    assert row["station_name"] == "16-双陈站"
    assert row["planned_ap_count"] == 3
    assert row["actual_online_count"] == 1


def test_duplicate_reference_mac_is_deduplicated_even_when_uuids_differ() -> None:
    stations = [_station(100, "16-双陈站", "node-shuangchen", 16)]
    references = [
        _reference(
            row_id,
            f"AP-SC-0{row_id}",
            "双陈站",
            "001122334455",
            station_node_uid="node-shuangchen",
            operation_status="in_service",
            project_id="extension",
            construction_phase_id="phase_2",
            ap_uuid=f"reference-{row_id}",
        )
        for row_id in (1, 2)
    ]
    scope = _resolve(
        stations=stations,
        plans=[{"station_name": "双陈站", "ap_count": 1, "sequence_no": 16}],
        references=references,
        resources=[
            _resource(
                row_id,
                f"AP-SC-0{row_id}",
                "001122334455",
                ap_uuid=f"online-{row_id}",
            )
            for row_id in (1, 2)
        ],
    )

    row = scope.station_statistics()[0]
    assert scope.scope_device_count == 1
    assert row["actual_online_count"] == 1
    assert any(item.reason == "同一 AP 稳定身份重复，已去重。" for item in scope.excluded_items)


def test_missing_plan_with_online_ap_marks_total_anomalous() -> None:
    stations = [_station(100, "16-双陈站", "node-shuangchen", 16)]
    scope = _resolve(
        stations=stations,
        plans=[],
        references=[
            _reference(
                1,
                "AP-SC-01",
                "双陈站",
                "001122334455",
                station_node_uid="node-shuangchen",
                operation_status="in_service",
                project_id="extension",
                construction_phase_id="phase_2",
            )
        ],
        resources=[
            _resource(1, "AP-SC-01", "001122334455", ap_uuid="online-1")
        ],
    )

    overview = scope.overview_export_rows()
    assert scope.station_statistics() == []
    assert overview == [overview[-1]]
    assert overview[-1]["total"] == 0
    assert overview[-1]["online"] == 0


def test_station_statistics_retains_unassigned_optical_problem_count() -> None:
    station = _station(100, "01-站点A", "node-a", 1)
    scope = _resolve(
        stations=[station],
        plans=[{"station_name": "站点A", "ap_count": 1, "sequence_no": 1}],
        references=[],
        resources=[],
    )

    rows = scope.station_statistics({"01-站点A": 1, "未归属": 2})
    by_name = {str(row["station_name"]): row for row in rows}

    assert by_name["01-站点A"]["optical_problem_count"] == 1
    assert by_name["01-站点A"]["warning"] == "存在 1 个光衰问题 AP。"
    assert by_name["未归属"]["planned_ap_count"] == 0
    assert by_name["未归属"]["optical_problem_count"] == 2
    assert by_name["未归属"]["warning"] == "存在未归属的光衰问题 AP。"


def test_scope_excludes_non_service_cross_project_and_ambiguous_station_rows() -> None:
    stations = [
        _station(100, "16-双陈站", "node-shuangchen", 16),
        _station(101, "双陈站", "node-shuangchen-duplicate", 17),
        _station(102, "18-仁和南站", "node-renhenan", 18),
    ]
    references = [
        _reference(
            1,
            "AP-RHN-01",
            "18-仁和南站",
            "001122334401",
            operation_status="in_service",
            project_id="extension",
            construction_phase_id="phase_2",
        ),
        _reference(
            2,
            "AP-RHN-02",
            "18-仁和南站",
            "001122334402",
            operation_status="suspended",
            project_id="extension",
            construction_phase_id="phase_2",
        ),
        _reference(
            3,
            "AP-RHN-03",
            "18-仁和南站",
            "001122334403",
            operation_status="in_service",
            project_id="phase_1_project",
            construction_phase_id="phase_1",
        ),
        _reference(
            4,
            "AP-SC-AMBIGUOUS",
            "双陈站",
            "001122334404",
            operation_status="in_service",
            project_id="extension",
            construction_phase_id="phase_2",
        ),
        _reference(
            5,
            "AP-RHN-NO-PHASE",
            "18-仁和南站",
            "001122334405",
            operation_status="in_service",
            project_id="extension",
        ),
    ]
    scope = _resolve(
        stations=stations,
        plans=[{"station_name": "仁和南站", "ap_count": 0, "sequence_no": 18}],
        references=references,
        resources=[
            _resource(1, "AP-RHN-01", "001122334401", ap_uuid="online-1"),
            _resource(2, "AP-RHN-02", "001122334402", ap_uuid="online-2"),
            _resource(None, "UNKNOWN", "00112233ffff", ap_uuid="unknown"),
        ],
    )

    rows = scope.station_statistics()
    assert len(rows) == 1
    by_name = {row["station_name"]: row for row in rows}
    assert by_name["18-仁和南站"]["planned_ap_count"] == 0
    assert by_name["18-仁和南站"]["actual_online_count"] == 0
    assert by_name["18-仁和南站"]["online_rate"] is None
    assert by_name["18-仁和南站"]["status"] == "unplanned_online"
    reasons = {item.reason for item in scope.excluded_items}
    assert "当前工作状态不是参与当前调试。" in reasons
    assert "不属于当前项目。" in reasons
    assert "缺少当前项目要求的建设阶段。" in reasons
    assert "缺少有效 station_id，且精确站名对应多个正式站点。" in reasons
    assert "在线 AP 尚未匹配轨旁 AP 基础资料；基础资料仅作补充，不影响业务生成。" in {
        item.reason for item in scope.unmatched_online_items
    }


def test_legacy_base_ap_uses_only_unique_exact_station_projection_at_field_scale() -> None:
    station = _station(100, "16-双陈站", "node-shuangchen", 16)
    station_id = str(station["station_id"])
    references = [
        _reference(
            index,
            f"AP-SC-{index:04d}",
            "双陈站",
            f"{index:012x}",
            operation_status="in_service",
            project_id="extension",
            construction_phase_id="phase_2",
        )
        for index in range(1, 684)
    ]
    resources = [
        _resource(
            None,
            f"AP-SC-{index:04d}",
            f"{index:012x}",
            ap_uuid=f"fit-ap-{index}",
        )
        for index in range(1, 686)
    ]

    scope = resolve_effective_trackside_ap_scope(
        context=TracksideApScopeContext(
            site_id="extension",
            project_id="extension",
            line_name="杭州地铁10号线延长线",
            project_phase="phase_2",
        ),
        station_rows=[station],
        plan_rows=[
            {
                "station_id": station_id,
                "station_name": "双陈站",
                "ap_count": 683,
                "sequence_no": 16,
            }
        ],
        reference_rows=references,
        resource_rows=resources,
    )

    assert scope.scope_ap_reference_count == 683
    assert scope.fit_ap_resource_total_count == 685
    assert scope.fit_ap_matched_count == 683
    assert scope.fit_ap_unmatched_online_count == 2
    assert scope.station_statistics()[0]["actual_online_count"] == 683


def test_legacy_station_projection_keeps_ambiguous_name_out_of_scope() -> None:
    stations = [
        _station(100, "16-双陈站", "node-shuangchen-a", 16),
        _station(101, "双陈站", "node-shuangchen-b", 17),
    ]
    reference = _reference(
        1,
        "AP-SC-01",
        "双陈站",
        "001122334455",
        operation_status="in_service",
        project_id="extension",
        construction_phase_id="phase_2",
    )

    scope = resolve_effective_trackside_ap_scope(
        context=TracksideApScopeContext(
            site_id="extension",
            project_id="extension",
            line_name="杭州地铁10号线延长线",
            project_phase="phase_2",
        ),
        station_rows=stations,
        plan_rows=[],
        reference_rows=[reference],
        resource_rows=[
            _resource(1, "AP-SC-01", "001122334455", ap_uuid="fit-ap-1")
        ],
    )

    assert scope.scope_ap_reference_count == 0
    assert scope.fit_ap_matched_count == 0
    assert any("对应多个正式站点" in item.reason for item in scope.excluded_items)


def test_legacy_station_projection_keeps_unknown_name_out_of_scope() -> None:
    reference = _reference(
        1,
        "AP-UNKNOWN-01",
        "不存在站",
        "001122334455",
        operation_status="in_service",
        project_id="extension",
        construction_phase_id="phase_2",
    )

    scope = resolve_effective_trackside_ap_scope(
        context=TracksideApScopeContext(
            site_id="extension",
            project_id="extension",
            line_name="杭州地铁10号线延长线",
            project_phase="phase_2",
        ),
        station_rows=[_station(100, "16-双陈站", "node-shuangchen", 16)],
        plan_rows=[],
        reference_rows=[reference],
        resource_rows=[
            _resource(None, "AP-UNKNOWN-01", "001122334455", ap_uuid="fit-ap-1")
        ],
    )

    assert scope.scope_ap_reference_count == 0
    assert scope.fit_ap_matched_count == 0
    assert any("未命中当前正式站点" in item.reason for item in scope.excluded_items)


def test_over_planned_rate_is_not_exported_as_a_large_percentage() -> None:
    stations = [_station(100, "18-仁和南站", "node-renhenan", 18)]
    references = [
        _reference(
            row_id,
            f"AP-RHN-{row_id:02d}",
            "仁和南站",
            f"0011223344{row_id:02d}",
            operation_status="in_service",
            project_id="extension",
            construction_phase_id="phase_2",
        )
        for row_id in (1, 2)
    ]
    scope = _resolve(
        stations=stations,
        plans=[{"station_name": "18-仁和南站", "ap_count": 1, "sequence_no": 18}],
        references=references,
        resources=[
            _resource(
                row_id,
                f"AP-RHN-{row_id:02d}",
                f"0011223344{row_id:02d}",
                ap_uuid=f"online-{row_id}",
            )
            for row_id in (1, 2)
        ],
    )

    row = scope.station_statistics()[0]
    assert row["actual_online_count"] == 1
    assert row["online_rate"] is None
    assert row["status"] == "over_planned"
    overview = scope.overview_export_rows()
    assert overview[0]["online_rate"] == "—"
    assert overview[-1]["online_rate"] == "—"


def test_business_rows_are_filtered_and_station_name_is_canonicalized() -> None:
    stations = [_station(100, "16-双陈站", "node-shuangchen", 16)]
    scope = _resolve(
        stations=stations,
        plans=[{"station_name": "双陈站", "ap_count": 1, "sequence_no": 16}],
        references=[
            _reference(
                1,
                "AP-SC-01",
                "双陈站",
                "001122334455",
                operation_status="in_service",
                project_id="extension",
                construction_phase_id="phase_2",
            )
        ],
        resources=[
            _resource(1, "AP-SC-01", "001122334455", ap_uuid="resource-uuid")
        ],
    )

    rows = scope.filter_business_rows(
        [
                {
                    "site": "双陈站",
                    "station_id": stations[0]["station_id"],
                "device_uuid": "sw-1",
                "interface_name": "XGE1/0/1",
                "ap_uuid": "resource-uuid",
                "ap_name": "AP-SC-01",
                "ap_mac": "0011-2233-4455",
            },
                {
                "site": "一期既有站",
                "device_uuid": "sw-old",
                "interface_name": "XGE1/0/2",
                "ap_uuid": "old-ap",
                "ap_name": "OLD-AP",
                "ap_mac": "0011-2233-ffff",
            },
        ]
    )
    assert len(rows) == 1
    assert rows[0]["site"] == "16-双陈站"
    assert rows[0]["station_id"]


def test_planned_station_scope_survives_without_references_or_resources() -> None:
    stations = [
        _station(index, f"{index:02d}站点{index}", f"node-{index}", index)
        for index in range(1, 16)
    ]
    plans = [
        {
            "station_id": stations[index - 1]["station_id"],
            "station_name": f"站点{index}",
            "sequence_no": index,
            "ap_count": index + 1,
        }
        for index in range(1, 16)
    ]

    scope = _resolve(
        stations=stations,
        plans=plans,
        references=[],
        resources=[],
    )

    assert scope.scope_station_count == 15
    rows = scope.station_statistics()
    assert len(rows) == 15
    assert all(row["actual_online_count"] == 0 for row in rows)
    assert all(row["offline_count"] == row["planned_ap_count"] for row in rows)
    assert all(row["status"] == "normal" for row in rows)
    assert all(row["online_rate"] == 0.0 for row in rows)


def test_switch_scope_keeps_candidate_ports_without_ap_references() -> None:
    scope = _resolve(
        stations=[_station(1, "01-站点A", "node-a", 1)],
        plans=[{"station_name": "站点A", "ap_count": 8, "sequence_no": 1}],
        references=[],
        resources=[],
    )

    rows = scope.filter_switch_scope_rows(
        [
                {
                    "device_uuid": "switch-a",
                    "station_id": scope.station_scope_ids.pop(),
                "device_name": "SW-A",
                "site": "站点A",
                "interface_name": "XGE1/0/1",
                "link_status": "UP",
                "switch_rx_power": -10.0,
                "ap_name": "",
                "ap_mac": "",
            }
        ],
        switch_device_ids={"switch-a"},
    )

    assert len(rows) == 1
    assert rows[0]["station_id"]
    assert rows[0]["site"] == "01-站点A"
    assert rows[0]["interface_name"] == "XGE1/0/1"
    assert rows[0]["ap_name"] == ""


def test_switch_scope_keeps_device_station_row_without_base_station_id() -> None:
    scope = _resolve(
        stations=[_station(1, "01-站点A", "node-a", 1)],
        plans=[],
        references=[],
        resources=[],
    )

    rows = scope.filter_switch_scope_rows(
        [
            {
                "device_uuid": "switch-a",
                "station_id": "",
                "device_name": "SW-A",
                "site": "设备管理站点A",
                "interface_name": "XGE1/0/1",
                "ap_name": "",
                "ap_mac": "",
            }
        ],
        switch_device_ids={"switch-a"},
    )

    assert len(rows) == 1
    assert rows[0]["site"] == "设备管理站点A"
    assert rows[0]["station_id"] == ""
    assert rows[0]["station_consistency_reason"] == "STATION_ID_MISSING"


def test_ambiguous_stable_identity_is_excluded_from_switch_scope() -> None:
    scope = _resolve(
        stations=[
            _station(1, "01-站点A", "node-a", 1),
            _station(2, "02-站点B", "node-b", 2),
        ],
        plans=[
            {"station_name": "站点A", "ap_count": 1, "sequence_no": 1},
            {"station_name": "站点B", "ap_count": 1, "sequence_no": 2},
        ],
        references=[
            _reference(
                1,
                "AP-AMBIGUOUS-A",
                "站点A",
                "001122334455",
                station_node_uid="node-a",
                operation_status="in_service",
                project_id="extension",
                construction_phase_id="phase_2",
            ),
            _reference(
                2,
                "AP-AMBIGUOUS-B",
                "站点B",
                "001122334455",
                station_node_uid="node-b",
                operation_status="in_service",
                project_id="extension",
                construction_phase_id="phase_2",
            ),
        ],
        resources=[],
    )

    rows = scope.filter_switch_scope_rows(
        [
            {
                "device_uuid": "switch-a",
                "site": "站点A",
                "interface_name": "XGE1/0/1",
                "ap_mac": "0011-2233-4455",
            }
        ],
        switch_device_ids={"switch-a"},
    )

    assert rows == []
    assert len(scope.excluded_items) == 2


def test_unmatched_online_resources_are_diagnostics_not_exclusions() -> None:
    stations = [_station(1, "01站点", "node-1", 1)]
    scope = _resolve(
        stations=stations,
        plans=[{"station_id": stations[0]["station_id"], "station_name": "站点", "ap_count": 2, "sequence_no": 1}],
        references=[],
        resources=[
            _resource(
                None,
                f"在线 AP {index}",
                f"0011223344{index:02x}",
                ap_uuid=f"online-{index}",
            )
            for index in range(1, 4)
        ],
    )

    assert scope.fit_ap_resource_total_count == 3
    assert scope.fit_ap_matched_count == 0
    assert scope.fit_ap_unmatched_online_count == 3
    assert scope.excluded_device_count == 0
    assert len(scope.excluded_items) == 0
    overview = scope.overview_export_rows()
    assert [row["site"] for row in overview] == ["01-站点", "合计"]
    assert overview[-1]["online"] == 0
    assert overview[-1]["offline"] == 2
    assert "AC AP 资源 3 个" in str(overview[-1]["remark"])
    assert "已关联上线 0 个" in str(overview[-1]["remark"])
    assert "3 个 AC 在线 AP" in str(overview[-1]["remark"])


def test_business_totals_use_only_planned_station_scope_and_keep_ac_resource_totals() -> None:
    station = _station(1, "01-站点", "node-1", 1)
    station_id = str(station["station_id"])
    matched_references = [
        _reference(
            index,
            f"AP-{index:04d}",
            "站点",
            f"{index:012x}",
            station_node_uid="node-1",
            operation_status="in_service",
            project_id="extension",
            construction_phase_id="phase_2",
        )
        for index in range(1, 932)
    ]
    matched_resources = [
        _resource(
            index,
            f"AP-{index:04d}",
            f"{index:012x}",
            ap_uuid=f"online-{index}",
        )
        for index in range(1, 932)
    ]
    unmatched_online = [
        _resource(
            None,
            f"UNMATCHED-{index:02d}",
            f"{10_000 + index:012x}",
            ap_uuid=f"unmatched-{index}",
        )
        for index in range(46)
    ]
    offline = [
        _resource(
            None,
            f"OFFLINE-{index:02d}",
            f"{20_000 + index:012x}",
            ap_uuid=f"offline-{index}",
            state="Idle",
        )
        for index in range(15)
    ]
    duplicate = _resource(
        1,
        "AP-0001-DUPLICATE",
        "00:00:00:00:00:01",
        ap_uuid="duplicate-record",
    )

    scope = _resolve(
        stations=[station],
        plans=[
            {
                "station_id": station_id,
                "station_name": "站点",
                "ap_count": 945,
                "sequence_no": 1,
            }
        ],
        references=matched_references,
        resources=[*matched_resources, *unmatched_online, *offline, duplicate],
    )

    station_row = scope.station_statistics()[0]
    total = scope.overview_export_rows()[-1]
    assert station_row["planned_ap_count"] == 945
    assert station_row["actual_online_count"] == 931
    assert station_row["offline_count"] == 14
    assert station_row["online_rate"] == 98.5
    assert total["total"] == 945
    assert total["online"] == 931
    assert total["offline"] == 14
    assert total["online_rate"] == "98.5%"
    assert [row["site"] for row in scope.overview_export_rows()] == ["01-站点", "合计"]
    assert scope.fit_ap_resource_total_count == 992
    assert scope.fit_ap_online_total_count == 977
    assert scope.fit_ap_unmatched_online_count == 46
    assert "46 个 AC 在线 AP" in str(total["remark"])
    assert "未计入业务统计" in str(total["remark"])


def test_conflicting_ac_lldp_reports_evidence_gap_without_name_or_ip_fallback() -> None:
    resource = _resource(
        None,
        "AP-CONFLICT",
        "001122334455",
        ap_uuid="ap-conflict",
    )
    resource["lldp_match_status"] = "conflict"
    station = _station(1, "01站点", "node-1", 1)
    scope = _resolve(
        stations=[station],
        plans=[{"station_id": station["station_id"], "station_name": "站点", "ap_count": 1, "sequence_no": 1}],
        references=[],
        resources=[resource],
    )

    assert scope.fit_ap_matched_count == 0
    assert scope.fit_ap_unmatched_online_count == 1
    item = scope.unmatched_online_items[0]
    assert "AC 侧 LLDP 结果冲突" in item.reason
    assert "精确 AP MAC" in item.reason
    assert "名称" not in item.suggested_action
    assert "补充轨旁 AP 基础资料 MAC" in item.suggested_action


def test_unique_lldp_station_evidence_projects_runtime_ap_into_station() -> None:
    station = _station(1, "01站点", "node-1", 1)
    station_id = str(station["station_id"])
    scope = _resolve(
        stations=[station],
        plans=[{"station_id": station_id, "station_name": "站点", "ap_count": 1, "sequence_no": 1}],
        references=[],
        resources=[
            _resource(
                None,
                "AP-LLDP-01",
                "0011-2233-4455",
                ap_uuid="ap-lldp-01",
            )
        ],
        runtime_station_rows=[
            {
                "ap_mac": "00:11:22:33:44:55",
                "station_id": station_id,
                "project_phase": "phase_2",
            }
        ],
    )

    assert scope.scope_ap_reference_count == 0
    assert scope.fit_ap_matched_count == 1
    assert scope.fit_ap_unmatched_online_count == 0
    assert scope.resources[0]["station_id"] == station_id
    assert scope.resources[0]["site"] == "01-站点"
    assert scope.resources[0]["_scope_binding_source"] == "switch_lldp_exact"
    assert scope.station_statistics()[0]["actual_online_count"] == 1


def test_unique_device_station_text_projects_runtime_ap_without_station_id() -> None:
    station = _station(1, "16-双陈站", "node-1", 16)
    station_id = str(station["station_id"])
    scope = _resolve(
        stations=[station],
        plans=[{"station_name": "双陈站", "ap_count": 1, "sequence_no": 16}],
        references=[],
        resources=[
            _resource(
                None,
                "AP-LLDP-01",
                "0011-2233-4455",
                ap_uuid="ap-lldp-01",
            )
        ],
        runtime_station_rows=[
            {
                "ap_mac": "00:11:22:33:44:55",
                "station_id": "",
                "device_station": "双陈站",
                "project_phase": "phase_2",
            }
        ],
    )

    assert scope.fit_ap_matched_count == 1
    assert scope.fit_ap_unmatched_online_count == 0
    assert scope.resources[0]["station_id"] == station_id
    assert scope.resources[0]["site"] == "16-双陈站"
    assert scope.station_statistics()[0]["actual_online_count"] == 1


def test_ambiguous_device_station_text_does_not_project_runtime_ap() -> None:
    stations = [
        _station(1, "16-双陈站", "node-a", 16),
        _station(2, "双陈站", "node-b", 17),
    ]
    scope = _resolve(
        stations=stations,
        plans=[],
        references=[],
        resources=[
            _resource(
                None,
                "AP-AMBIGUOUS",
                "0011-2233-4455",
                ap_uuid="ap-ambiguous",
            )
        ],
        runtime_station_rows=[
            {
                "ap_mac": "0011-2233-4455",
                "station_id": "",
                "device_station": "双陈站",
                "project_phase": "phase_2",
            }
        ],
    )

    assert scope.fit_ap_matched_count == 0
    assert scope.fit_ap_unmatched_online_count == 1


def test_lldp_station_evidence_does_not_choose_between_multiple_stations() -> None:
    stations = [
        _station(1, "01站点A", "node-a", 1),
        _station(2, "02站点B", "node-b", 2),
    ]
    scope = _resolve(
        stations=stations,
        plans=[
            {"station_name": "站点A", "ap_count": 1, "sequence_no": 1},
            {"station_name": "站点B", "ap_count": 1, "sequence_no": 2},
        ],
        references=[],
        resources=[
            _resource(None, "AP-AMBIGUOUS", "001122334455", ap_uuid="ap-ambiguous")
        ],
        runtime_station_rows=[
            {
                "ap_mac": "0011-2233-4455",
                "station_id": station["station_id"],
                "project_phase": "phase_2",
            }
            for station in stations
        ],
    )

    assert scope.fit_ap_matched_count == 0
    assert scope.fit_ap_unmatched_online_count == 1
    assert scope.ambiguous_online_total_count == 1
    assert "多个站点" in scope.unmatched_online_items[0].reason


def test_excluded_base_reference_blocks_lldp_station_fallback() -> None:
    station = _station(1, "01站点", "node-1", 1)
    scope = _resolve(
        stations=[station],
        plans=[{"station_name": "站点", "ap_count": 1, "sequence_no": 1}],
        references=[
            _reference(
                1,
                "暂停 AP",
                "站点",
                "001122334455",
                station_node_uid="node-1",
                operation_status="suspended",
                project_id="extension",
                construction_phase_id="phase_2",
            )
        ],
        resources=[
            _resource(None, "暂停 AP", "001122334455", ap_uuid="ap-suspended")
        ],
        runtime_station_rows=[
            {
                "ap_mac": "0011-2233-4455",
                "station_id": station["station_id"],
                "project_phase": "phase_2",
            }
        ],
    )

    assert scope.fit_ap_matched_count == 0
    assert scope.fit_ap_unmatched_online_count == 0
    assert scope.excluded_device_count == 1
    assert any(item.source == "fit_ap_online_excluded" for item in scope.excluded_items)


def test_valid_base_reference_takes_precedence_over_lldp_station_evidence() -> None:
    stations = [
        _station(1, "01站点A", "node-a", 1),
        _station(2, "02站点B", "node-b", 2),
    ]
    scope = _resolve(
        stations=stations,
        plans=[
            {"station_name": "站点A", "ap_count": 1, "sequence_no": 1},
            {"station_name": "站点B", "ap_count": 1, "sequence_no": 2},
        ],
        references=[
            _reference(
                1,
                "AP-BASE",
                "站点A",
                "001122334455",
                station_node_uid="node-a",
                operation_status="in_service",
                project_id="extension",
                construction_phase_id="phase_2",
            )
        ],
        resources=[_resource(None, "AP-BASE", "001122334455", ap_uuid="ap-base")],
        runtime_station_rows=[
            {
                "ap_mac": "0011-2233-4455",
                "station_id": stations[1]["station_id"],
                "project_phase": "phase_2",
            }
        ],
    )

    assert scope.fit_ap_matched_count == 1
    assert scope.resources[0]["station_id"] == stations[0]["station_id"]
    assert scope.resources[0]["_scope_binding_source"] == "base_data"


def test_excluded_reference_without_mac_serializes_as_empty_string() -> None:
    stations = [_station(1, "01站点", "node-1", 1)]
    scope = _resolve(
        stations=stations,
        plans=[{"station_name": "站点", "ap_count": 1, "sequence_no": 1}],
        references=[
            {
                "id": 1,
                "belong_type": "station",
                "station_name": "",
                "ap_name": "",
                "ap_mac_norm": None,
                "ap_mac_display": None,
                "raw_payload_json": "{}",
            }
        ],
        resources=[],
    )

    assert scope.excluded_items[0].mac == ""
    assert scope.excluded_items[0].to_dict()["mac"] == ""


def test_runtime_resources_with_same_name_but_different_macs_are_not_deduped() -> None:
    station = _station(1, "01站点", "node-1", 1)
    scope = _resolve(
        stations=[station],
        plans=[{"station_id": station["station_id"], "station_name": "站点", "ap_count": 2, "sequence_no": 1}],
        references=[
            _reference(
                1,
                "同名 AP",
                "站点",
                "001122334401",
                station_node_uid="node-1",
                operation_status="in_service",
                project_id="extension",
                construction_phase_id="phase_2",
            ),
            _reference(
                2,
                "同名 AP",
                "站点",
                "001122334402",
                station_node_uid="node-1",
                operation_status="in_service",
                project_id="extension",
                construction_phase_id="phase_2",
            ),
        ],
        resources=[
            _resource(1, "同名 AP", "001122334401", ap_uuid="online-1"),
            _resource(2, "同名 AP", "001122334402", ap_uuid="online-2"),
        ],
    )

    assert scope.fit_ap_matched_count == 2
    assert scope.station_statistics()[0]["actual_online_count"] == 2


def test_site_equivalent_fixture_keeps_switch_ports_and_unmatched_online_resources() -> None:
    stations = [
        _station(index, f"{index:02d}站点{index}", f"node-{index}", index)
        for index in range(1, 16)
    ]
    plans = [
        {
            "station_id": stations[index - 1]["station_id"],
            "station_name": f"站点{index}",
            "sequence_no": index,
            "ap_count": 50,
        }
        for index in range(1, 16)
    ]
    scope = _resolve(
        stations=stations,
        plans=plans,
        references=[],
        resources=[
            _resource(
                None,
                f"在线 AP {index}",
                f"001122{index:06x}",
                ap_uuid=f"online-{index}",
            )
            for index in range(1, 189)
        ],
    )
    candidate_rows = [
            {
                "device_uuid": f"switch-{station_index}",
                "station_id": stations[station_index - 1]["station_id"],
            "site": f"站点{station_index}",
            "interface_name": f"XGE1/0/{port_index}",
            "ap_name": "",
            "ap_mac": "",
        }
        for station_index in range(1, 16)
        for port_index in range(1, 51)
    ]
    candidate_rows.extend(
            {
                "device_uuid": "switch-1",
                "station_id": stations[0]["station_id"],
            "site": "站点1",
            "interface_name": f"XGE1/0/{port_index}",
            "ap_name": "",
            "ap_mac": "",
        }
        for port_index in range(51, 57)
    )

    filtered = scope.filter_switch_scope_rows(
        candidate_rows,
        switch_device_ids={f"switch-{index}" for index in range(1, 16)},
    )

    assert scope.scope_station_count == 15
    assert len(filtered) == 756
    assert scope.fit_ap_unmatched_online_count == 188
    assert scope.excluded_device_count == 0
    assert len(scope.station_statistics()) == 15
