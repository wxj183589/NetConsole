from __future__ import annotations

import json

from netconsole.parsers.h3c.ac.state_mapper import classify_fit_ap_state, map_fit_ap_state
from netconsole.services.ap_online_overview import is_fit_ap_online
from netconsole.services.rail_transit.effective_trackside_ap_scope import (
    TracksideApScopeContext,
    resolve_effective_trackside_ap_scope,
)
from netconsole.services.rail_transit.trackside_ap_runtime_snapshot import (
    build_trackside_ap_runtime_snapshot,
    classify_lldp_history_status,
    deduplicate_lldp_snapshot_rows,
    select_latest_lldp_snapshot_rows,
)
from netconsole.services.trackside_ap_business import (
    build_new_online_ap_overview_rows,
    current_optical_abnormal_reason,
)


def _station(name: str = "01-站点A") -> dict[str, object]:
    return {
        "id": 1,
        "belong_type": "__base_station__",
        "station_id": "station-a",
        "station_name": name,
        "raw_payload_json": json.dumps({"node_uid": "node-a", "sort_order": 1}),
    }


def _resource(mac: str = "001122334455", state: str = "R/M") -> dict[str, object]:
    return {
        "ap_uuid": f"ap-{mac}",
        "ap_name": f"AP-{mac}",
        "ap_mac": mac,
        "state": state,
        "collected_at": "2026-08-05T14:09:25+08:00",
        "updated_at": "2026-08-05T14:09:25+08:00",
        "collect_run_uuid": "fit-run",
    }


def _scope(resource_rows, runtime_rows):
    return resolve_effective_trackside_ap_scope(
        context=TracksideApScopeContext(site_id="demo", project_id="demo"),
        station_rows=[_station()],
        plan_rows=[{"station_id": "station-a", "station_name": "站点A", "ap_count": 1}],
        reference_rows=[],
        resource_rows=resource_rows,
        runtime_station_rows=runtime_rows,
    )


def test_fit_ap_state_tokens_are_online_without_optical_or_lldp_context():
    for value in ("R/M", "R/B", "R", "M", "Run", "Up", "Online", "运行(主)"):
        assert classify_fit_ap_state(value) == "online"
        assert is_fit_ap_online({"state": value}) is True


def test_fit_ap_state_unknown_is_not_inferred_from_empty_evidence():
    assert classify_fit_ap_state() == "unknown"
    assert classify_fit_ap_state("Idle") == "offline"
    assert map_fit_ap_state("M") == "Run"


def test_snapshot_marks_lldp_stale_when_fit_ap_is_newer():
    snapshot = build_trackside_ap_runtime_snapshot(
        fit_ap_rows=[_resource()],
        switch_lldp_rows=[{"device_uuid": "sw-1", "neighbor_mac": "0011-2233-4455", "collected_at": "2026-08-04T17:40:05+08:00", "collect_run_uuid": "lldp-old"}],
    )
    assert snapshot.snapshot_status == "lldp_stale"
    assert snapshot.fit_ap_generation == "fit-run"
    assert snapshot.switch_lldp_generation == "lldp-old"


def test_snapshot_is_consistent_when_current_batches_are_newer_or_equal():
    snapshot = build_trackside_ap_runtime_snapshot(
        fit_ap_rows=[_resource()],
        switch_lldp_rows=[{"device_uuid": "sw-1", "neighbor_mac": "0011-2233-4455", "collected_at": "2026-08-05T14:27:41+08:00", "collect_run_uuid": "lldp-new"}],
    )
    assert snapshot.snapshot_status == "consistent"


def test_latest_lldp_snapshot_drops_old_interface_rows():
    rows = select_latest_lldp_snapshot_rows([
        {"device_uuid": "sw-1", "local_interface": "GE1/0/8", "collected_at": "2026-08-04T17:40:05", "collect_run_uuid": "old"},
        {"device_uuid": "sw-1", "local_interface": "GE1/0/12", "collected_at": "2026-08-05T14:27:41", "collect_run_uuid": "new"},
    ])
    assert [row["local_interface"] for row in rows] == ["GE1/0/12"]


def test_merged_and_direct_same_lldp_fact_are_deduplicated():
    rows = deduplicate_lldp_snapshot_rows([
        {"device_uuid": "sw-1", "local_interface": "GE1/0/1", "neighbor_mac": "0011-2233-4455", "neighbor_interface": "GE1/0/8", "collected_at": "2026-08-05", "source": "ap_direct_lldp"},
        {"device_uuid": "sw-1", "local_interface": "GE1/0/1", "neighbor_mac": "0011-2233-4455", "neighbor_interface": "GE1/0/8", "collected_at": "2026-08-05", "source": "merged"},
    ])
    assert len(rows) == 1
    assert rows[0]["source"] == "merged"


def test_current_conflict_is_not_created_by_historical_conflict():
    assert classify_lldp_history_status([], [{"neighbor_mac": "0011-2233-4455"}]) == "stale_snapshot"
    assert classify_lldp_history_status([
        {"device_uuid": "sw-1", "local_interface": "GE1/0/1", "neighbor_mac": "0011-2233-4455", "collected_at": "2026-08-05"},
    ], [
        {"neighbor_mac": "0011-2233-4455"},
        {"neighbor_mac": "0011-2233-4466"},
    ]) == "current_consistent"


def test_stale_lldp_online_ap_is_waiting_sync_not_base_data_missing():
    scope = _scope([_resource()], [{"ap_mac": "0011-2233-ffff", "station_id": "station-a", "observed_at": "2026-08-04T17:40:05+08:00", "collect_run_uuid": "lldp-old"}])
    assert scope.fit_ap_unmatched_online_count == 1
    item = scope.unmatched_online_items[0]
    assert item.association_status == "lldp_snapshot_stale"
    assert item.reason_code == "LLDP_SNAPSHOT_STALE"
    overview = scope.overview_export_rows()
    assert [row["site"] for row in overview] == ["01-站点A", "合计"]
    assert "未计入业务统计" in str(overview[-1]["remark"])


def test_current_exact_lldp_resolves_same_ap_after_refresh():
    resource = _resource()
    scope = _scope([resource], [{"ap_mac": resource["ap_mac"], "station_id": "station-a", "observed_at": "2026-08-05T14:27:41+08:00", "collect_run_uuid": "lldp-new"}])
    assert scope.fit_ap_unmatched_online_count == 0
    assert scope.resources[0]["_scope_binding_source"] == "switch_lldp_exact"


def test_lldp_pending_status_is_distinct_from_planning_missing():
    scope = _scope([_resource()], [{"ap_mac": "00aabbccddeeff", "station_id": "station-a", "observed_at": "2026-08-05T14:27:41+08:00", "collect_run_uuid": "lldp-new"}])
    assert scope.unmatched_online_items[0].association_status == "lldp_exact_match_pending"


def test_optical_alarm_does_not_override_online_runtime_state():
    row = {"ap_mac": "0011-2233-4455", "ap_state": "R/M", "ap_rx_power": "-17.80", "ap_optical_status": "no_light", "is_ap_offline": False}
    result = current_optical_abnormal_reason(row)
    assert result["ap_online_status"] == "在线"
    assert result["judgement"] == "异常"


def test_optical_unknown_without_runtime_state_remains_unknown():
    assert current_optical_abnormal_reason({"ap_mac": "0011-2233-4455", "ap_optical_status": "warning"})["ap_online_status"] == "未知"


def test_new_online_uses_identity_entity_before_name_or_station_projection():
    rows = build_new_online_ap_overview_rows(
        current_resource_rows=[{"identity_entity_id": "entity-1", "ap_name": "AP-NEW", "ap_mac": "0011-2233-4455", "state": "R/M", "collected_at": "2026-08-05"}],
        resource_history_rows=[{"identity_entity_id": "entity-1", "ap_name": "AP-OLD", "ap_mac": "0011-2233-4455", "state": "Idle", "collected_at": "2026-08-04"}],
        trackside_rows=[],
    )
    assert len(rows) == 1
    assert rows[0]["ap_name"] == "AP-NEW"
    assert rows[0]["site"] == "等待 LLDP 同步"
    assert rows[0]["baseline_collected_at"] == "2026-08-04"


def test_new_online_ignores_name_change_when_stable_identity_was_already_online():
    rows = build_new_online_ap_overview_rows(
        current_resource_rows=[{"identity_entity_id": "entity-1", "ap_name": "AP-NEW", "ap_mac": "0011-2233-4455", "state": "R/M", "collected_at": "2026-08-05"}],
        resource_history_rows=[{"identity_entity_id": "entity-1", "ap_name": "AP-OLD", "ap_mac": "0011-2233-4455", "state_raw": "R/M", "collected_at": "2026-08-04"}],
        trackside_rows=[],
    )
    assert rows == []


def test_new_online_with_no_history_survives_missing_station_projection():
    rows = build_new_online_ap_overview_rows(
        current_resource_rows=[{"ap_name": "AP-NEW", "ap_mac": "0011-2233-4455", "state": "Online", "collected_at": "2026-08-05"}],
        resource_history_rows=[],
        trackside_rows=[],
    )
    assert len(rows) == 1
    assert rows[0]["site"] == "等待 LLDP 同步"


def test_snapshot_diagnostics_do_not_mutate_raw_rows():
    raw = _resource()
    before = dict(raw)
    build_trackside_ap_runtime_snapshot(fit_ap_rows=[raw], switch_lldp_rows=[])
    assert raw == before


def test_snapshot_is_unavailable_without_fit_ap_runtime_rows():
    snapshot = build_trackside_ap_runtime_snapshot(
        switch_lldp_rows=[{"device_uuid": "sw-1", "collected_at": "2026-08-05T14:27:41+08:00"}],
    )
    assert snapshot.snapshot_status == "unavailable"
    assert snapshot.warnings == ("FIT-AP 当前运行快照不可用",)


def test_snapshot_is_partial_without_switch_lldp_rows():
    snapshot = build_trackside_ap_runtime_snapshot(fit_ap_rows=[_resource()])
    assert snapshot.snapshot_status == "partial"
    assert snapshot.has_current_lldp is False


def test_snapshot_marks_optical_stale_without_changing_fit_ap_state():
    snapshot = build_trackside_ap_runtime_snapshot(
        fit_ap_rows=[_resource()],
        switch_lldp_rows=[{"device_uuid": "sw-1", "collected_at": "2026-08-05T14:27:41+08:00"}],
        optical_rows=[{"ap_mac": "0011-2233-4455", "collected_at": "2026-08-05T13:00:00+08:00"}],
    )
    assert snapshot.snapshot_status == "optical_stale"
    assert is_fit_ap_online(_resource()) is True


def test_latest_lldp_snapshot_ignores_explicit_failed_batch():
    rows = select_latest_lldp_snapshot_rows([
        {"device_uuid": "sw-1", "local_interface": "GE1/0/8", "collected_at": "2026-08-05T14:00:00", "collect_run_uuid": "ok", "status": "success"},
        {"device_uuid": "sw-1", "local_interface": "GE1/0/12", "collected_at": "2026-08-05T15:00:00", "collect_run_uuid": "failed", "status": "failed"},
    ])
    assert [row["collect_run_uuid"] for row in rows] == ["ok"]


def test_latest_lldp_snapshot_keeps_complete_newest_generation():
    rows = select_latest_lldp_snapshot_rows([
        {"device_uuid": "sw-1", "local_interface": "GE1/0/1", "collected_at": "2026-08-05T14:00:00", "collect_run_uuid": "old"},
        {"device_uuid": "sw-1", "local_interface": "GE1/0/2", "collected_at": "2026-08-05T15:00:00", "collect_run_uuid": "new"},
        {"device_uuid": "sw-1", "local_interface": "GE1/0/3", "collected_at": "2026-08-05T15:00:00", "collect_run_uuid": "new"},
    ])
    assert {row["local_interface"] for row in rows} == {"GE1/0/2", "GE1/0/3"}


def test_lldp_dedup_uses_generation_instead_of_row_timestamp():
    rows = deduplicate_lldp_snapshot_rows([
        {"device_uuid": "sw-1", "local_interface": "GE1/0/1", "neighbor_mac": "0011-2233-4455", "neighbor_interface": "GE1/0/8", "collect_run_uuid": "run-1", "collected_at": "2026-08-05T15:00:00", "source": "ap_direct_lldp"},
        {"device_uuid": "sw-1", "local_interface": "GE1/0/1", "neighbor_mac": "0011-2233-4455", "neighbor_interface": "GE1/0/8", "collect_run_uuid": "run-1", "collected_at": "2026-08-05T15:00:01", "source": "merged"},
    ])
    assert len(rows) == 1
    assert rows[0]["source"] == "merged"


def test_lldp_dedup_preserves_distinct_station_candidates_without_interfaces():
    rows = deduplicate_lldp_snapshot_rows([
        {"ap_mac": "0011-2233-4455", "station_id": "station-a"},
        {"ap_mac": "0011-2233-4455", "station_id": "station-b"},
    ])
    assert len(rows) == 2


def test_multiple_aps_in_one_current_snapshot_are_not_a_conflict():
    assert classify_lldp_history_status([
        {"device_uuid": "sw-1", "local_interface": "GE1/0/1", "neighbor_mac": "0011-2233-4455"},
        {"device_uuid": "sw-1", "local_interface": "GE1/0/2", "neighbor_mac": "0011-2233-4466"},
    ]) == "current_consistent"


def test_same_ap_on_two_current_ports_is_current_conflict():
    assert classify_lldp_history_status([
        {"device_uuid": "sw-1", "local_interface": "GE1/0/1", "neighbor_mac": "0011-2233-4455"},
        {"device_uuid": "sw-1", "local_interface": "GE1/0/2", "neighbor_mac": "0011-2233-4455"},
    ]) == "current_conflict"


def test_new_current_port_with_old_historical_port_is_migrated():
    assert classify_lldp_history_status(
        [{"device_uuid": "sw-1", "local_interface": "GE1/0/12", "neighbor_mac": "0011-2233-4455"}],
        [{"device_uuid": "sw-1", "local_interface": "GE1/0/8", "neighbor_mac": "0011-2233-4455"}],
    ) == "port_migrated"


def test_historical_multi_port_conflict_does_not_mark_current_conflict():
    assert classify_lldp_history_status(
        [{"device_uuid": "sw-1", "local_interface": "GE1/0/12", "neighbor_mac": "0011-2233-4455"}],
        [
            {"device_uuid": "sw-1", "local_interface": "GE1/0/8", "neighbor_mac": "0011-2233-4455"},
            {"device_uuid": "sw-1", "local_interface": "GE1/0/9", "neighbor_mac": "0011-2233-4455"},
        ],
    ) == "historical_conflict"


def test_current_lldp_with_missing_station_master_is_not_planning_missing():
    scope = resolve_effective_trackside_ap_scope(
        context=TracksideApScopeContext(site_id="demo", project_id="demo"),
        station_rows=[_station()],
        plan_rows=[{"station_id": "station-a", "station_name": "站点A", "ap_count": 1}],
        reference_rows=[],
        resource_rows=[_resource()],
        runtime_station_rows=[{
            "ap_mac": "0011-2233-4455",
            "station_id": "missing-station",
            "device_station": "不存在站点",
            "observed_at": "2026-08-05T14:27:41+08:00",
        }],
    )
    item = scope.unmatched_online_items[0]
    assert item.association_status == "station_master_missing"
    assert scope.fit_ap_planning_missing_count == 0
    assert scope.fit_ap_station_master_missing_count == 1


def test_overview_reports_actual_online_independently_of_association():
    scope = _scope([_resource()], [])
    total = scope.overview_export_rows()[-1]
    assert len(scope.runtime_resources) == 1
    assert total["online"] == 0
    assert "已关联上线 0 个" in str(total["remark"])


def test_runtime_totals_keep_all_305_fit_aps_independent_of_station_association():
    resources = [
        _resource(f"{index:012x}", "R/M" if index < 300 else "Idle")
        for index in range(305)
    ]
    scope = _scope(resources, [])
    assert len(scope.runtime_resources) == 305
    assert scope.fit_ap_resource_total_count == 305
    assert scope.fit_ap_online_total_count == 300
    assert scope.fit_ap_offline_total_count == 5
    assert scope.fit_ap_unknown_total_count == 0
    assert scope.overview_export_rows()[-1]["online"] == 0


def test_matched_resource_count_is_distinct_from_matched_online_count():
    online = _resource("001122334455", "R/M")
    offline = _resource("001122334466", "Idle")
    scope = _scope(
        [online, offline],
        [
            {"ap_mac": online["ap_mac"], "station_id": "station-a", "observed_at": "2026-08-05T14:27:41+08:00"},
            {"ap_mac": offline["ap_mac"], "station_id": "station-a", "observed_at": "2026-08-05T14:27:41+08:00"},
        ],
    )
    assert scope.fit_ap_matched_count == 2
    assert len(scope.runtime_resources) == 2
    assert scope.fit_ap_matched_online_count == 1
    assert scope.fit_ap_online_total_count == 1
    assert scope.fit_ap_offline_total_count == 1
