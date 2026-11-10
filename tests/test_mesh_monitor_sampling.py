from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta

import pytest

from netconsole.services.mesh_monitor_sampling import select_monitor_rows


def row(index, seconds, *, role="ACTIVE", peer="a", value=40, count=1, radio=1):
    return {"id": index, "sample_time": (datetime(2026, 7, 14, 10) + timedelta(seconds=seconds)).isoformat(sep=" ", timespec="milliseconds"),
            "source_file_id": 1, "radio": radio, "link_state": role, "peer_mac_normalized": peer,
            "establish_time": "2026-07-14 09:00:00.000", "link_count": count,
            "local_rssi_db": value, "peer_rssi_db": value, "local_tx": value}


def select(rows, group="rssi", budget=100):
    return select_monitor_rows(rows, group, "2026-07-14 10:00:00.000", "2026-07-14 11:00:00.000", budget)


def test_interleaved_roles_keep_each_peak_without_false_switches_or_input_mutation():
    rows = [row(2 * i + offset, i, role=role, peer=peer, value=(99 if i == peak else 40))
            for i in range(500)
            for offset, role, peer, peak in [(1, "ACTIVE", "a", 231), (2, "STANDBY", "b", 319)]]
    before = deepcopy(rows)
    selected, total, zero = select(rows)
    assert total == 1000 and zero == 0 and len(selected) <= 100
    assert {463, 640} <= {item["id"] for item in selected}
    assert rows == before


def test_role_switch_keeps_both_historical_sides():
    rows = [row(i + 1, i, role="ACTIVE" if i < 14 else "STANDBY") for i in range(30)]
    selected, *_ = select(rows)
    by_id = {item["id"]: item for item in selected}
    assert by_id[14]["link_state"] == "ACTIVE"
    assert by_id[15]["link_state"] == "STANDBY"


def test_counters_are_differenced_before_sampling_and_preserve_reset_gap_zero():
    rows = [row(1, 0, value=10), row(2, 1, value=12), row(3, 2, value=100),
            row(4, 3, value=2), row(5, 4, value=5), row(6, 100, value=9),
            row(7, 101, count=0, role="UNCONNECTED", value=0), row(8, 102, value=15)]
    selected, total, zero = select(rows, "counters")
    by_id = {item["id"]: item for item in selected}
    assert total == 8 and zero == 1
    assert by_id[3]["local_tx_delta"] == 88
    assert by_id[4]["local_tx_delta"] is None
    assert by_id[6]["monitor_gap_before"] and by_id[6]["local_tx_delta"] is None
    assert by_id[8]["local_tx_delta"] is None


def test_dense_real_switches_fail_explicitly():
    with pytest.raises(ValueError, match="切换事件过密"):
        select([row(i + 1, i, peer=str(i)) for i in range(80)])


def test_counter_samples_use_actual_fractional_interval_and_keep_endpoints_separate():
    rows = [dict(row(1, 0, value=100), peer_tx=200),
            dict(row(2, 2.5, value=135), peer_tx=250)]
    selected, *_ = select(rows, "counters")
    point = selected[-1]
    assert point["local_tx_delta"] == 35
    assert point["counter_samples"]["local_tx"] == {
        "current": 135, "previous": 100, "delta": 35,
        "interval_seconds": 2.5, "per_second": 14, "status": "valid",
    }
    assert point["counter_samples"]["peer_tx"]["per_second"] == 20
    assert point["counter_samples"]["local_rx"]["status"] == "missing"


@pytest.mark.parametrize("field,new_value", [
    ("source_file_id", 2), ("radio", 2), ("peer_mac_normalized", "b"),
    ("establish_time", "2026-07-14 09:59:00.000"),
    ("peer_radio_mac", "radio-b"), ("peer_radio_label", "radio2"),
    ("peer_ap_mac", "ap-b"), ("local_ap_mac", "local-b"),
])
def test_counter_identity_never_crosses_endpoint_radio_build_or_source(field, new_value):
    rows = [row(1, 0, value=100), dict(row(2, 1, value=200), **{field: new_value}),
            dict(row(3, 2, value=210), **{field: new_value})]
    selected, *_ = select(rows, "counters")
    by_id = {point["id"]: point for point in selected}
    assert by_id[2]["local_tx_delta"] is None
    assert by_id[3]["local_tx_delta"] == 10


def test_duplicate_and_out_of_order_counters_do_not_poison_next_baseline():
    rows = [row(1, 0, value=10), row(2, 2, value=20), row(3, 2, value=900),
            row(4, 1, value=800), row(5, 3, value=25)]
    selected, *_ = select(rows, "counters")
    by_id = {point["id"]: point for point in selected}
    for index in (3, 4):
        assert by_id[index]["counter_samples"]["local_tx"]["status"] == "invalid_interval"
        assert by_id[index]["local_tx_delta"] is None
    assert by_id[5]["counter_samples"]["local_tx"]["previous"] == 20
    assert by_id[5]["local_tx_delta"] == 5


def test_role_switch_and_ap_return_reestablish_counter_baselines():
    rows = [row(1, 0, value=10), row(2, 1, role="STANDBY", value=20),
            row(3, 2, value=30), row(4, 3, peer="b", value=100),
            row(5, 4, value=40), row(6, 5, value=45)]
    selected, *_ = select(rows, "counters")
    by_id = {point["id"]: point for point in selected}
    for index in (2, 3, 4, 5):
        assert by_id[index]["local_tx_delta"] is None
        assert by_id[index]["counter_samples"]["local_tx"]["status"] == "link_changed"
    assert by_id[6]["local_tx_delta"] == 5


def test_missing_reset_and_zero_values_are_distinct_and_baselines_recover():
    values = [100, None, 110, 0, 0, 10]
    selected, *_ = select([row(i + 1, i, value=value) for i, value in enumerate(values)], "counters")
    by_id = {point["id"]: point for point in selected}
    for index in (2, 3):
        assert by_id[index]["counter_samples"]["local_tx"]["status"] == "missing"
    assert by_id[4]["counter_samples"]["local_tx"]["status"] == "reset"
    assert by_id[5]["local_tx_delta"] == 0
    assert by_id[6]["local_tx_delta"] == 10


def test_counter_cadence_is_isolated_from_other_radios():
    rows = [row(1, 0, value=10), row(2, 10, value=20), row(3, 20, value=30)]
    rows.extend(row(10 + i, 20 + i / 100, radio=2, value=i) for i in range(101))
    rows.append(row(200, 25, value=40))
    selected, *_ = select(rows, "counters", budget=2000)
    target = next(point for point in selected if point["id"] == 200)
    assert target["monitor_gap_before"] is False
    assert target["counter_samples"]["local_tx"]["per_second"] == 2
