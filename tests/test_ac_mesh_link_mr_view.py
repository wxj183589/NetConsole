from __future__ import annotations

from contextlib import closing
from datetime import datetime
from pathlib import Path

import pytest

from netconsole.services.ac.mesh_link_query_service import AcMeshLinkQueryService
from tests.support.ac_mesh_link_web_fixture import build_ac_mesh_link_fixture


def _add_links(db: Path, count: int, *, unregistered: bool = False) -> None:
    import sqlite3

    with closing(sqlite3.connect(db)) as conn:
        original = conn.execute("SELECT * FROM vehicle_mr_online_links ORDER BY id LIMIT 1").fetchone()
        names = [item[1] for item in conn.execute("PRAGMA table_info(vehicle_mr_online_links)")]
        values = dict(zip(names, original, strict=True))
        for index in range(count):
            row = {key: value for key, value in values.items() if key != "id"}
            row.update(local_mac=f"00aa-0000-{index:04x}", local_ap_name=f"Peer-{index}", rssi=-50-index)
            if unregistered:
                row.update(peer_name="列车88-MR-CW", peer_mac="1000-0000-0088", train_no="88", car_end="CW")
            conn.execute(f"INSERT INTO vehicle_mr_online_links ({','.join(row)}) VALUES ({','.join('?' for _ in row)})", list(row.values()))
        conn.commit()


@pytest.mark.parametrize("count", [1, 3, 10])
def test_mr_keeps_all_peers_and_searches_beyond_first_two(tmp_path: Path, count: int) -> None:
    paths, _, db = build_ac_mesh_link_fixture(tmp_path)
    _add_links(db, count)
    service = AcMeshLinkQueryService(paths, now_provider=lambda: datetime(2026, 7, 14, 12, 0, 10))
    page = service.list_mrs("demo", query=f"Peer-{count-1}", page_size=1)
    assert page.total == 1
    mr = page.items[0]
    assert mr.mr_id == "mr-01-ct"
    assert len(mr.peer_aps) == count + 1
    assert service.list_mrs("demo", multiple_peers=True).total == 1
    detail = service.get_mr_link_detail("demo", mr.mr_id)
    assert detail is not None and len(detail.current_links) == count + 1
    assert all(peer.relation_status == "historical" for peer in detail.history_links)
    assert all(peer.received_at and peer.device_time for peer in mr.peer_aps)


def test_unregistered_mr_is_not_repeated_per_peer_and_missing_endpoint_is_not_invented(tmp_path: Path) -> None:
    paths, _, db = build_ac_mesh_link_fixture(tmp_path)
    _add_links(db, 10, unregistered=True)
    service = AcMeshLinkQueryService(paths, now_provider=lambda: datetime(2026, 7, 14, 12, 0, 10))
    page = service.list_mrs("demo", car_end="CW")
    assert page.total == 1
    assert len(page.items[0].peer_aps) == 10
    assert {item.car_end for item in service.list_mrs("demo", train_no="01").items} == {"CT"}
    empty = next(item for item in service.list_mrs("demo").items if item.mr_id == "mr-03-ct")
    assert empty.peer_aps == []
    assert empty.resolved_ap == empty.resolved_ap_station == empty.resolved_ap_section == ""


def test_reverse_ap_aggregation_preserves_multiple_mrs_and_unknown_observations(tmp_path: Path) -> None:
    import sqlite3

    paths, _, db = build_ac_mesh_link_fixture(tmp_path)
    with closing(sqlite3.connect(db)) as conn:
        conn.execute("UPDATE vehicle_mr_online_links SET local_mac = '0000-0001-0001' WHERE id = 2")
        conn.commit()
    service = AcMeshLinkQueryService(paths, now_provider=lambda: datetime(2026, 7, 14, 12, 0, 10))
    page = service.list_peer_aps("demo", query="AP-Online", page_size=1)
    assert page.total == 1
    assert {row.mr_id for row in page.items[0].relations} == {"mr-01-ct", "mr-02-ct"}
    summary = service.get_summary("demo")
    assert summary.registered_mrs == 3
    assert summary.link_total == 3
    assert summary.unique_peer_aps == 1


def test_data_filters_and_history_time_pagination_are_server_side(tmp_path: Path) -> None:
    paths, _, db = build_ac_mesh_link_fixture(tmp_path)
    _add_links(db, 10)
    service = AcMeshLinkQueryService(paths, now_provider=lambda: datetime(2026, 7, 14, 12, 10))
    assert service.list_mrs("demo", data_status="fresh").total == 0
    page = service.list_mrs("demo", data_status="stale", page=2, page_size=1)
    assert page.total == 4 and len(page.items) == 1
    assert all(peer.relation_status == "stale" for peer in page.items[0].peer_aps)
    detail = service.get_mr_link_detail("demo", "mr-01-ct", page=2, page_size=3)
    assert detail is not None and len(detail.history_links) == 3 and detail.history_total == 11
    empty = service.get_mr_link_detail("demo", "mr-01-ct", start_time="2026-07-15 00:00:00")
    assert empty is not None and empty.history_total == 0 and not empty.history_links


def test_backup_address_does_not_duplicate_mr_or_override_peer_location(tmp_path: Path) -> None:
    import sqlite3

    paths, devices, _ = build_ac_mesh_link_fixture(tmp_path)
    with closing(sqlite3.connect(devices)) as conn:
        conn.execute("UPDATE devices SET backup_address = '192.0.2.12' WHERE device_uuid = 'mr-01-ct'")
        conn.commit()
    service = AcMeshLinkQueryService(paths, now_provider=lambda: datetime(2026, 7, 14, 12, 0, 10))
    page = service.list_mrs("demo", query="192.0.2.12")
    assert page.total == 1
    assert page.items[0].management_ips == ["10.12.1.11", "192.0.2.12"]
    assert page.items[0].peer_aps[0].station == "车站A"
    assert page.items[0].resolved_ap_station == ""


def test_history_uses_system_name_alias_and_rejects_reversed_range(tmp_path: Path) -> None:
    import sqlite3

    paths, devices, links_db = build_ac_mesh_link_fixture(tmp_path)
    with closing(sqlite3.connect(devices)) as conn:
        conn.execute("UPDATE devices SET system_name = 'MR-01-ALIAS' WHERE device_uuid = 'mr-01-ct'")
        conn.commit()
    with closing(sqlite3.connect(links_db)) as conn:
        conn.execute("UPDATE vehicle_mr_online_links SET peer_name = 'MR-01-ALIAS' WHERE peer_name = '列车01-MR-CT'")
        conn.commit()
    service = AcMeshLinkQueryService(paths, now_provider=lambda: datetime(2026, 7, 14, 12, 0, 10))
    detail = service.get_mr_link_detail("demo", "mr-01-ct")
    assert detail is not None
    assert detail.history_total == 1
    assert [link.mr_id for link in detail.history_links] == ["mr-01-ct"]
    with pytest.raises(ValueError, match="开始时间"):
        service.get_mr_link_detail("demo", "mr-01-ct", start_time="2026-07-15 00:00:00", end_time="2026-07-14 00:00:00")
