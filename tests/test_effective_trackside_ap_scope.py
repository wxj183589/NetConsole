from __future__ import annotations

import json

from netconsole.services.rail_transit.effective_trackside_ap_scope import (
    TracksideApScopeContext,
    resolve_effective_trackside_ap_scope,
)


def _station(row_id: int, name: str, node_uid: str, sort_order: int) -> dict[str, object]:
    return {
        "id": row_id,
        "belong_type": "__base_station__",
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
    assert len(rows) == 1
    assert rows[0]["station_name"] == "18-仁和南站"
    assert rows[0]["planned_ap_count"] == 0
    assert rows[0]["actual_online_count"] == 1
    assert rows[0]["online_rate"] is None
    assert rows[0]["status"] == "unplanned_online"
    reasons = {item.reason for item in scope.excluded_items}
    assert "投运状态不是在用。" in reasons
    assert "不属于当前项目。" in reasons
    assert "缺少当前项目要求的建设阶段。" in reasons
    assert "历史站名匹配到多个 station_id，需人工处理。" in reasons
    assert "在线 AP 未匹配到当前有效轨旁 AP 资料。" in reasons


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
