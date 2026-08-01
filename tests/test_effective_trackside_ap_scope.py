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
    state: str = "R",
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
            station_ids_by_name.setdefault(name, []).append(station_id)
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

    row = scope.station_statistics()[0]
    assert row["planning_missing"] is True
    assert row["count_anomaly"] is True
    assert row["online_rate"] is None
    overview = scope.overview_export_rows()
    assert overview[0]["total"] is None
    assert overview[-1]["online_rate"] == "—"


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
    assert len(rows) == 3
    by_name = {row["station_name"]: row for row in rows}
    assert by_name["18-仁和南站"]["planned_ap_count"] == 0
    assert by_name["18-仁和南站"]["actual_online_count"] == 1
    assert by_name["18-仁和南站"]["online_rate"] is None
    assert by_name["18-仁和南站"]["status"] == "unplanned_online"
    reasons = {item.reason for item in scope.excluded_items}
    assert "当前工作状态不是参与当前调试。" in reasons
    assert "不属于当前项目。" in reasons
    assert "缺少当前项目要求的建设阶段。" in reasons
    assert "缺少有效 station_id；历史站名仅供诊断，不能建立正式关联。" in reasons
    assert "在线 AP 未匹配到当前有效轨旁 AP 资料。" in {
        item.reason for item in scope.unmatched_online_items
    }


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
    assert row["actual_online_count"] == 2
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
        plans=[{"station_name": "站点", "ap_count": 2, "sequence_no": 1}],
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
        plans=[{"station_name": "站点", "ap_count": 2, "sequence_no": 1}],
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
        {"station_name": f"站点{index}", "sequence_no": index, "ap_count": 50}
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
