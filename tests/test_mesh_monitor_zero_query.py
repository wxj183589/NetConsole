from __future__ import annotations

import hashlib
import pytest

from netconsole.services.rail_transit.mesh_analysis_query_service import (
    MeshAnalysisQueryError, MeshAnalysisQueryService, _zero_window,
)
from tests.support.mesh_analysis_test_support import EmptyBaseQuery, create_mesh_analysis_fixture

ZERO = "[1] Active 0000-0000-001f 2026/07/14 09:00:00 0d 00h 00m 03s 0 0/0 2%/4% 45%/47% 3/1 15/27 60/72060 88/105 0/5000 2/297 314/0 0/93 0/0 0/0 0/0"


def fingerprint(path):
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def data(tmp_path):
    paths, session, detail, raw, report = create_mesh_analysis_fixture(tmp_path)
    raw.write_text("[1] 2026/07/14 10:00:00.500\n" + ZERO + "\n[2] 2026/07/14 10:00:01.500\n" + ZERO.replace("[1]", "[2]") + "\n", encoding="utf-8")
    return MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery(), schedule_catalog_index=False), session, (detail, raw, report)


def test_exact_millisecond_endpoints_keep_whole_second_rows(data):
    service, session, _ = data
    result = service.list_link_details("demo", session, metric_group="rssi",
                                       time_from="2026-07-14T10:00:02", time_to="2026-07-14T10:00:02")
    assert {item.record_id for item in result.items} == {3, 4}


def test_zero_toggle_filters_cache_and_readonly_fingerprints(data):
    service, session, protected = data
    before = [fingerprint(path) for path in protected]
    base = service.list_link_details("demo", session)
    enabled = service.list_link_details("demo", session, include_zero=True)
    assert base.total == 4 and enabled.total == 6 and enabled.zero_link_count == 2
    assert sum(item.link_status == "UNCONNECTED" for item in enabled.items) == 2
    radio = service.list_link_details("demo", session, include_zero=True, radio=2)
    assert radio.total == 1 and radio.items[0].link_count == 0
    filtered = service.list_link_details("demo", session, include_zero=True, peer_ap_mac="000000000020", exact_ap=True)
    assert filtered.zero_link_count == 0 and filtered.total == 1
    assert service.list_link_details("demo", session).model_dump() | {"query_duration_ms": 0} == base.model_dump() | {"query_duration_ms": 0}
    assert [fingerprint(path) for path in protected] == before
    assert _zero_window.cache_info().maxsize == 4


def test_build_zero_observations_are_not_fabricated_builds_and_paginate(data):
    service, session, protected = data
    before = [fingerprint(path) for path in protected]
    base = service.list_active_build_order("demo", session, sort_order="asc")
    enabled = service.list_active_build_order("demo", session, include_zero=True, sort_order="asc")
    assert enabled.total == base.total + 2
    zeros = [item for item in enabled.items if item.link_count == 0]
    assert len(zeros) == 2
    assert all(item.build_result == "UNCONNECTED" and item.observation_time and not item.build_start_time and not item.build_end_time and item.main_link_duration_seconds is None for item in zeros)
    only_zero = service.list_active_build_order("demo", session, include_zero=True, build_result="UNCONNECTED", page_size=1, page=2, sort_order="asc")
    assert only_zero.total == 2 and only_zero.items[0].local_radio == 2
    assert service.list_active_build_order("demo", session, link_role="STANDBY").total == 0
    assert service.list_active_build_order("demo", session).total == base.total
    assert [fingerprint(path) for path in protected] == before


def test_zero_cache_invalidates_changed_raw_and_is_bounded(data):
    service, session, (_, raw, _) = data
    for second in range(6):
        service.list_link_details("demo", session, include_zero=True, time_to=f"2026-07-14 10:00:0{second}.999")
    assert _zero_window.cache_info().currsize <= 4
    raw.write_text("[1] 2026/07/14 10:00:00.500\n" + ZERO + "\n", encoding="utf-8")
    assert service.list_link_details("demo", session, include_zero=True).zero_link_count == 1


@pytest.mark.parametrize("peer", ["00:00:00:00:00:1f", "0000-0000-001f", "00000000001f"])
def test_build_zero_peer_filter_normalizes_full_mac(data, peer):
    service, session, _ = data
    result = service.list_active_build_order("demo", session, include_zero=True, build_result="UNCONNECTED", peer=peer)
    assert result.total == 2
    assert all(item.link_count == 0 for item in result.items)


def test_zero_requires_available_raw(data):
    service, session, (_, raw, _) = data
    raw.unlink()
    with pytest.raises(MeshAnalysisQueryError, match="原始日志不可用"):
        service.list_link_details("demo", session, include_zero=True)


@pytest.mark.parametrize("stored", ["00:00:00:00:00:20", "0000-0000-0020", "000000000020"])
def test_exact_ap_accepts_display_mac_formats(data, stored):
    import sqlite3
    service, session, (detail, _, _) = data
    with sqlite3.connect(detail) as connection:
        connection.execute("UPDATE mesh_links SET peer_ap_mac = ? WHERE peer_ap_mac = ?", (stored, "000000000020"))
    result = service.list_link_details("demo", session, exact_ap=True, peer_ap_mac="00:00:00:00:00:20")
    assert result.total == 1
