from __future__ import annotations

from pathlib import Path

from netconsole.core.database import Database
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.rail_transit.base_data_query_service import (
    RailTransitBaseDataQueryService,
)
from netconsole.services.rail_transit.vehicle_mr_online_query_service import (
    VehicleMrOnlineQueryService,
)
from netconsole.services.rail_transit.vehicle_mr_reconciliation import (
    VEHICLE_MR_DUPLICATE_POSITION,
)
from tests.support.rail_transit_base_data_fixture import (
    build_rail_transit_base_data_fixture,
)


def _rename_fixture_mrs(db_path: Path, *, station: str = "32车") -> None:
    with Database(db_path).connect() as connection:
        connection.execute(
            "UPDATE devices SET name = 'LC32-MR-CT', station = ?, primary_address = '10.82.24.232' WHERE device_uuid = 'mr-01-ct'",
            (station,),
        )
        connection.execute(
            "UPDATE devices SET name = 'LC32-MR-CW', station = ?, primary_address = '10.82.25.232' WHERE device_uuid = 'mr-01-cw'",
            (station,),
        )
        connection.commit()


def test_device_mr_projection_merges_ct_cw_and_is_idempotent(tmp_path: Path) -> None:
    paths, db_path = build_rail_transit_base_data_fixture(tmp_path)
    _rename_fixture_mrs(db_path)
    service = RailTransitBaseDataQueryService(paths)

    snapshots = [
        (service.list_trains("demo", page_size=200), service.list_mrs("demo", page_size=200))
        for _ in range(3)
    ]

    assert all(trains.total == 1 and trains.items[0].mr_count == 2 for trains, _mrs in snapshots)
    assert all(mrs.total == 2 for _trains, mrs in snapshots)
    assert {item.role for item in snapshots[0][1].items} == {"CT", "CW"}
    assert {item.id for item in snapshots[0][1].items} == {"mr-01-ct", "mr-01-cw"}
    assert snapshots[0][0].items[0].id == "train:32"
    assert snapshots[0][0].items[0].name == "32车"


def test_device_mr_projection_uses_name_fallback_and_keeps_partial_train(tmp_path: Path) -> None:
    paths, db_path = build_rail_transit_base_data_fixture(tmp_path)
    _rename_fixture_mrs(db_path, station="")
    with Database(db_path).connect() as connection:
        connection.execute("UPDATE devices SET name = 'LC33-MR-CT' WHERE device_uuid = 'mr-01-ct'")
        connection.execute("UPDATE devices SET name = 'LC33-MR-CW' WHERE device_uuid = 'mr-01-cw'")
        connection.commit()

    service = RailTransitBaseDataQueryService(paths)
    trains = service.list_trains("demo", page_size=200)
    mrs = service.list_mrs("demo", page_size=200)

    assert trains.total == 1
    assert trains.items[0].train_no == "33"
    assert mrs.total == 2

    with Database(db_path).connect() as connection:
        connection.execute("UPDATE devices SET name = 'LC33-MR-CT-A' WHERE device_uuid = 'mr-01-ct'")
        connection.execute("UPDATE devices SET name = 'LC33-MR-CT-B' WHERE device_uuid = 'mr-01-cw'")
        connection.commit()
    duplicate_issues = service.list_issues("demo", page_size=500)

    assert any(item.code == VEHICLE_MR_DUPLICATE_POSITION for item in duplicate_issues.items)


def test_device_mr_group_move_and_device_updates_rebuild_same_relation(tmp_path: Path) -> None:
    paths, db_path = build_rail_transit_base_data_fixture(tmp_path)
    _rename_fixture_mrs(db_path)
    service = RailTransitBaseDataQueryService(paths)
    repository = DeviceRepository(Database(db_path))
    with Database(db_path).connect_readonly() as connection:
        group_id = int(connection.execute("SELECT group_id FROM devices WHERE device_uuid = 'mr-01-ct'").fetchone()[0])

    before = {item.id: item for item in service.list_mrs("demo", page_size=200).items}
    with Database(db_path).connect() as connection:
        connection.execute("UPDATE devices SET primary_address = '10.82.24.250', name = 'LC32-MR-CT-RENAMED' WHERE device_uuid = 'mr-01-ct'")
        connection.commit()
    after = {item.id: item for item in service.list_mrs("demo", page_size=200).items}
    assert set(after) == set(before)
    assert after["mr-01-ct"].management_ip == "10.82.24.250"

    with Database(db_path).connect() as connection:
        connection.execute("UPDATE devices SET group_id = NULL WHERE device_uuid = 'mr-01-ct'")
        connection.commit()
    assert service.list_mrs("demo", page_size=200).total == 1
    with Database(db_path).connect() as connection:
        connection.execute("UPDATE devices SET group_id = ? WHERE device_uuid = 'mr-01-ct'", (group_id,))
        connection.commit()
    assert service.list_mrs("demo", page_size=200).total == 2
    assert repository.get_by_uuid("mr-01-ct").name == "LC32-MR-CT-RENAMED"

    with Database(db_path).connect() as connection:
        connection.execute("UPDATE devices SET station = '42车' WHERE device_uuid = 'mr-01-ct'")
        connection.commit()
    moved_trains = service.list_trains("demo", page_size=200)
    assert {item.id for item in moved_trains.items} == {"train:32", "train:42"}
    assert any(item.code == "VEHICLE_MR_TRAIN_AMBIGUOUS" for item in service.list_issues("demo", page_size=500).items)


def test_unknown_group_does_not_create_vehicle_mr_projection(tmp_path: Path) -> None:
    paths, db_path = build_rail_transit_base_data_fixture(tmp_path)
    with Database(db_path).connect() as connection:
        cursor = connection.execute(
            "INSERT INTO device_groups (site_id, name, sort_order, created_at, updated_at) VALUES ('demo', '轨旁-MR', 99, 'now', 'now')"
        )
        group_id = int(cursor.lastrowid)
        connection.execute(
            "UPDATE devices SET name = 'ABC-MR', group_id = ?, device_type = 'MR' WHERE device_uuid = 'mr-temp'",
            (group_id,),
        )
        connection.commit()

    service = RailTransitBaseDataQueryService(paths)
    assert service.list_mrs("demo", page_size=200).total == 2
    assert not any(
        item.entity_name == "ABC-MR" and item.entity_type == "mr"
        for item in service.list_issues("demo", page_size=500).items
    )


def test_vehicle_mr_online_is_seeded_from_base_data_without_runtime_session(tmp_path: Path) -> None:
    paths, db_path = build_rail_transit_base_data_fixture(tmp_path)
    _rename_fixture_mrs(db_path)

    page = VehicleMrOnlineQueryService(paths).list_trains("demo", page_size=200)

    assert page.total == 1
    assert page.items[0].is_registered is True
    assert page.items[0].train_no == "32"
    assert page.items[0].ct.mr_id == "mr-01-ct"
    assert page.items[0].tc.mr_id == "mr-01-cw"
    assert page.items[0].overall_status == "UNKNOWN"
