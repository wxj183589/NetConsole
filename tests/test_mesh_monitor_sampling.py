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
