from __future__ import annotations

from pathlib import Path

from netconsole.core.database import Database
from netconsole.models.device import Device
from netconsole.repositories.device_fact_repository import DeviceFactRepository
from netconsole.repositories.device_group_repository import DeviceGroupRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.rail_transit import trackside_optical_collection
from netconsole.services.rail_transit.trackside_optical_collection import (
    SUSPENDED_OPERATION_STATUS_REASON,
    _collect_one_target,
    build_station_switch_targets,
)
from netconsole.services.trackside_ap_export_service import (
    export_trackside_ap_business_from_database,
    load_trackside_ap_business_snapshot,
)


def _repository(tmp_path: Path) -> DeviceRepository:
    database = Database(tmp_path / "data" / "sites" / "demo" / "db" / "devices.db")
    database.initialize()
    return DeviceRepository(database)


def _create_switch(
    repository: DeviceRepository,
    *,
    group_id: int,
    name: str,
    address: str,
    operation_status: str = "in_service",
    project_phase: str = "phase_1",
) -> Device:
    device = repository.create(
        Device(
            name=name,
            station=f"{name}-站",
            group_id=group_id,
            device_type="SW",
            device_vendor="ZTE",
            project_phase=project_phase,
            operation_status=operation_status,
            primary_address=address,
            ssh_enabled=1,
            ssh_username="readonly",
            ssh_password="test-only",
        )
    )
    facts = DeviceFactRepository(repository.database)
    facts.replace_device_interfaces(
        str(device.device_uuid),
        [
            {
                "interface_name": "gei-0/3/0/1",
                "description": "Trackside AP",
                "link_status": "UP",
                "port_status": "hybrid",
                "pvid": "71",
            }
        ],
    )
    facts.replace_optical_modules(
        str(device.device_uuid),
        [
            {
                "interface_name": "gei-0/3/0/1",
                "device_vendor": "ZTE",
                "device_reported_status": "Normal",
                "threshold_source": "zte_brief",
                "rx_power": -7.0,
                "tx_power": -5.0,
                "rx_low_alarm": -28.2,
                "rx_high_alarm": 0.0,
                "tx_low_alarm": -10.0,
                "tx_high_alarm": -0.5,
                "status": "normal",
            }
        ],
    )
    return device


def test_trackside_snapshot_export_and_targets_exclude_only_suspended(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    station = DeviceGroupRepository(repository.database, "demo").create("车站")
    phase_one = _create_switch(
        repository,
        group_id=int(station.id or 0),
        name="一期",
        address="192.0.2.11",
        project_phase="phase_1",
    )
    suspended = _create_switch(
        repository,
        group_id=int(station.id or 0),
        name="暂停",
        address="192.0.2.12",
        operation_status="suspended",
        project_phase="phase_2",
    )

    snapshot = load_trackside_ap_business_snapshot(repository, "demo", generation=1)
    targets, skipped = build_station_switch_targets(repository, "demo")
    export_result = export_trackside_ap_business_from_database(
        database_path=repository.database.path,
        site_name="demo",
        output_path=tmp_path / "trackside.xlsx",
        tmp_path=tmp_path / "trackside.tmp.xlsx",
    )

    assert snapshot.device_count == 1
    assert snapshot.row_count == 1
    assert {row["device_name"] for row in snapshot.rows} == {phase_one.name}
    assert export_result["row_count"] == snapshot.row_count
    assert [target.device_uuid for target in targets] == [phase_one.device_uuid]
    assert any(
        item.host == suspended.primary_address
        and item.reason == SUSPENDED_OPERATION_STATUS_REASON
        for item in skipped
    )

    repository.update_lifecycle_many(
        [str(suspended.device_uuid)],
        operation_status="in_service",
    )
    restored = load_trackside_ap_business_snapshot(repository, "demo", generation=2)
    restored_targets, _ = build_station_switch_targets(repository, "demo")
    assert restored.device_count == 2
    assert restored.row_count == 2
    assert {target.device_uuid for target in restored_targets} == {
        phase_one.device_uuid,
        suspended.device_uuid,
    }


def test_trackside_execute_time_recheck_skips_suspended_before_ssh(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repository = _repository(tmp_path)
    station = DeviceGroupRepository(repository.database, "demo").create("车站")
    device = _create_switch(
        repository,
        group_id=int(station.id or 0),
        name="竞态",
        address="192.0.2.21",
    )
    targets, _ = build_station_switch_targets(repository, "demo")
    repository.update_lifecycle_many(
        [str(device.device_uuid)],
        operation_status="suspended",
    )
    connected = False

    def fail_if_connected(**_kwargs):
        nonlocal connected
        connected = True
        raise AssertionError("suspended target must not open SSH")

    monkeypatch.setattr(
        trackside_optical_collection.netmiko_connection,
        "ConnectHandler",
        fail_if_connected,
    )

    result = _collect_one_target(
        targets[0],
        cancel_event=None,
        repository=repository,
    )

    assert connected is False
    assert result.success is True
    assert result.skipped_reason == SUSPENDED_OPERATION_STATUS_REASON


def test_old_zte_database_rows_are_normalized_on_read(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    device_uuid = Device.new_uuid()
    with repository.database.connect() as connection:
        connection.execute(
            """
            INSERT INTO device_optical_modules (
                device_uuid, interface_name, rx_power, tx_power, module_model,
                module_serial_number, device_vendor, device_reported_status,
                threshold_source, status, collected_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                device_uuid,
                "gei-0/3/0/1",
                -7.0,
                -5.0,
                "STALE",
                "STALE-SN",
                "ZTE",
                "offline",
                "zte_brief",
                "offline",
                "2026-07-28T10:00:00+08:00",
                "2026-07-28T10:00:00+08:00",
            ),
        )
        connection.commit()

    row = DeviceFactRepository(repository.database).list_optical_modules(device_uuid)[0]

    assert row["status"] == "no_module"
    assert row["module_present"] is False
    assert row["module_online"] is False
    assert row["rx_power"] is None
    assert row["module_model"] is None
    assert row["module_serial_number"] is None
