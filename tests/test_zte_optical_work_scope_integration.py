from __future__ import annotations

import json
from pathlib import Path

from netconsole.core.database import Database
from netconsole.models.device import Device
from netconsole.repositories.device_fact_repository import DeviceFactRepository
from netconsole.repositories.device_group_repository import DeviceGroupRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.repositories.ac_repository import AcRepository
from netconsole.services.rail_transit import trackside_optical_collection
from netconsole.services.rail_transit.trackside_optical_collection import (
    EXCLUDED_WORK_SCOPE_REASON,
    TracksideDeviceCollectionResult,
    _collect_one_target,
    _persist_result,
    _snapshot_can_replace,
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
    work_scope_status: str = "included",
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
            work_scope_status=work_scope_status,
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


def _seed_effective_trackside_aps(
    repository: DeviceRepository,
    devices: list[Device],
) -> None:
    extension_rows: list[dict[str, object]] = []
    fit_ap_rows: list[dict[str, object]] = []
    facts = DeviceFactRepository(repository.database)
    for index, device in enumerate(devices, start=1):
        node_uid = f"station-{device.device_uuid}"
        ap_name = f"{device.name}-AP"
        ap_uuid = f"ap-{index}"
        ap_mac = f"0011223344{index:02x}"
        extension_rows.extend(
            [
                {
                    "site_id": "demo",
                    "belong_type": "__base_station__",
                    "station_name": str(device.station or ""),
                    "raw_payload_json": json.dumps(
                        {
                            "node_uid": node_uid,
                            "canonical_station_name": str(device.station or ""),
                            "sort_order": index,
                        },
                        ensure_ascii=False,
                    ),
                },
                {
                    "site_id": "demo",
                    "belong_type": "station",
                    "station_name": str(device.station or ""),
                    "ap_name": ap_name,
                    "ap_mac_norm": ap_mac,
                    "raw_payload_json": json.dumps(
                        {
                            "station_node_uid": node_uid,
                            "work_scope_status": "included",
                            "project_id": "demo",
                            "ap_uuid": ap_uuid,
                        },
                        ensure_ascii=False,
                    ),
                },
            ]
        )
        fit_ap_rows.append(
            {
                "ap_uuid": ap_uuid,
                "ap_name": ap_name,
                "ap_mac": ap_mac,
                "state": "R/M",
            }
        )
        facts.replace_lldp_neighbors(
            str(device.device_uuid),
            [
                {
                    "local_interface": "gei-0/3/0/1",
                    "neighbor_sysname": ap_name,
                    "neighbor_mac": ap_mac,
                    "neighbor_interface": "GigabitEthernet1/0/1",
                }
            ],
        )
    ac_repository = AcRepository(repository.database)
    result = ac_repository.import_ap_extension_points(
        extension_rows,
        source_file="work-scope-fixture.xlsx",
        template_type="trackside_ap_scope_fixture",
    )
    assert result["error_rows"] == 0
    ac_repository.replace_fit_ap_resources("ac-fixture", fit_ap_rows)


def test_trackside_snapshot_export_and_targets_exclude_work_scope(
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
    excluded = _create_switch(
        repository,
        group_id=int(station.id or 0),
        name="暂不参与",
        address="192.0.2.12",
        work_scope_status="excluded",
        project_phase="phase_2",
    )
    _seed_effective_trackside_aps(repository, [phase_one, excluded])

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
        item.host == excluded.primary_address
        and item.reason == EXCLUDED_WORK_SCOPE_REASON
        for item in skipped
    )

    repository.update_classification_many(
        [str(excluded.device_uuid)],
        work_scope_status="included",
    )
    restored = load_trackside_ap_business_snapshot(repository, "demo", generation=2)
    restored_targets, _ = build_station_switch_targets(repository, "demo")
    assert restored.device_count == 2
    assert restored.row_count == 2
    assert {target.device_uuid for target in restored_targets} == {
        phase_one.device_uuid,
        excluded.device_uuid,
    }


def test_trackside_execute_time_recheck_skips_excluded_before_ssh(
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
    repository.update_classification_many(
        [str(device.device_uuid)],
        work_scope_status="excluded",
    )
    connected = False

    def fail_if_connected(**_kwargs):
        nonlocal connected
        connected = True
        raise AssertionError("excluded target must not open SSH")

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
    assert result.skipped_reason == EXCLUDED_WORK_SCOPE_REASON


def test_zte_trackside_update_replaces_stale_down_interface_snapshot(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repository = _repository(tmp_path)
    station = DeviceGroupRepository(repository.database, "demo").create("车站")
    device = _create_switch(
        repository,
        group_id=int(station.id or 0),
        name="状态刷新",
        address="192.0.2.31",
    )
    _seed_effective_trackside_aps(repository, [device])
    facts = DeviceFactRepository(repository.database)
    facts.replace_device_interfaces(
        str(device.device_uuid),
        [
            {
                "interface_name": "gei-0/3/0/1",
                "description": "Trackside AP",
                "link_status": "PHYSICAL_DOWN",
                "admin_status": "up",
                "physical_status": "down",
                "protocol_status": "down",
                "port_status": "hybrid",
                "port_mode": "hybrid",
                "pvid": "71",
                "native_vlan": "71",
                "tagged_vlans": ["201"],
            }
        ],
    )

    class FakeZteConnection:
        def send_command_timing(self, command: str, **_kwargs) -> str:
            outputs = {
                "show version": (
                    Path(__file__).parent
                    / "fixtures"
                    / "zte"
                    / "zte_5960x_show_version.txt"
                ).read_text(encoding="utf-8"),
                "show interface brief": "\n".join(
                    [
                        "Interface Attribute Mode BW Admin Phy Prot Description",
                        "gei-0/3/0/1 optical Duplex/full 1G up up up To-AP",
                    ]
                ),
                "show opticalinfo brief": "\n".join(
                    [
                        "Interface Type Wavelength RxPower(dBm) TxPower(dBm) Status",
                        "gei-0/3/0/1 1G-10km-SFP 1310nm "
                        "-11.7/[-28.2,0.0] -5.0/[-10.0,-0.5] Normal",
                    ]
                ),
            }
            return outputs[command]

        def disconnect(self) -> None:
            return None

    monkeypatch.setattr(
        trackside_optical_collection.netmiko_connection,
        "ConnectHandler",
        lambda **_kwargs: FakeZteConnection(),
    )
    targets, _ = build_station_switch_targets(repository, "demo")

    result = _collect_one_target(
        targets[0],
        artifact_dir=tmp_path / "raw" / "status-refresh",
        repository=repository,
    )
    _persist_result(
        repository,
        AcRepository(repository.database),
        result,
        tmp_path / "parsed" / "trackside_update_results.sqlite",
    )

    current = facts.list_device_interfaces(str(device.device_uuid))[0]
    assert result.success is True
    assert current["link_status"] == "UP"
    assert current["physical_status"] == "up"
    assert current["protocol_status"] == "up"
    assert current["port_status"] == "hybrid"
    assert current["pvid"] == "71"
    assert current["tagged_vlans"] == '["201"]'
    snapshot = load_trackside_ap_business_snapshot(repository, "demo", generation=1)
    assert snapshot.rows[0]["link_status"] == "UP"
    assert snapshot.rows[0]["switch_interface_data_status"] == "current"
    assert snapshot.rows[0]["switch_optical_data_status"] == "current"


def test_zte_invalid_interface_snapshot_is_not_presented_as_current(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repository = _repository(tmp_path)
    station = DeviceGroupRepository(repository.database, "demo").create("车站")
    device = _create_switch(
        repository,
        group_id=int(station.id or 0),
        name="接口摘要失败",
        address="192.0.2.32",
    )
    _seed_effective_trackside_aps(repository, [device])
    facts = DeviceFactRepository(repository.database)
    device_uuid = str(device.device_uuid)
    facts.mark_device_collection_attempt(device_uuid, "old-run")
    facts.replace_device_interfaces(
        device_uuid,
        [
            {
                "interface_name": "gei-0/3/0/1",
                "description": "Trackside AP",
                "link_status": "PHYSICAL_DOWN",
                "admin_status": "up",
                "physical_status": "down",
                "protocol_status": "down",
                "port_status": "hybrid",
                "collect_run_uuid": "old-run",
                "collected_at": "2026-08-02T10:00:00+08:00",
                "updated_at": "2026-08-02T10:00:00+08:00",
            }
        ],
    )
    facts.replace_optical_modules(
        device_uuid,
        [
            {
                "interface_name": "gei-0/3/0/1",
                "device_vendor": "ZTE",
                "rx_power": "-7.10",
                "tx_power": "-4.90",
                "status": "normal",
                "collect_run_uuid": "old-run",
                "collected_at": "2026-08-02T10:00:00+08:00",
                "updated_at": "2026-08-02T10:00:00+08:00",
            }
        ],
    )

    class FakeZteConnection:
        def send_command_timing(self, command: str, **_kwargs) -> str:
            outputs = {
                "show version": (
                    Path(__file__).parent
                    / "fixtures"
                    / "zte"
                    / "zte_5960x_show_version.txt"
                ).read_text(encoding="utf-8"),
                "show interface brief": "ZXR10#show interface brief\nZXR10#",
                "show opticalinfo brief": "\n".join(
                    [
                        "Interface Type Wavelength RxPower(dBm) TxPower(dBm) Status",
                        "gei-0/3/0/1 1G-10km-SFP 1310nm "
                        "-11.7/[-28.2,0.0] -5.0/[-10.0,-0.5] Normal",
                    ]
                ),
            }
            return outputs[command]

        def disconnect(self) -> None:
            return None

    monkeypatch.setattr(
        trackside_optical_collection.netmiko_connection,
        "ConnectHandler",
        lambda **_kwargs: FakeZteConnection(),
    )
    targets, _ = build_station_switch_targets(repository, "demo")

    result = _collect_one_target(
        targets[0],
        artifact_dir=tmp_path / "raw" / "invalid-interface",
        repository=repository,
    )
    _persist_result(
        repository,
        AcRepository(repository.database),
        result,
        tmp_path / "parsed" / "trackside_update_results.sqlite",
    )

    snapshot = load_trackside_ap_business_snapshot(repository, "demo", generation=1)
    assert snapshot.rows, {
        "empty_reason": snapshot.empty_reason,
        "interface_count": snapshot.interface_count,
        "candidate_count": snapshot.candidate_ap_interface_count,
        "fact": facts.get_device_fact(device_uuid),
        "interfaces": facts.list_device_interfaces(device_uuid),
        "optical": facts.list_optical_modules(device_uuid),
    }
    row = snapshot.rows[0]
    assert result.success is True
    assert result.interface_snapshot_status == "PARSE_FAILED"
    assert result.optical_snapshot_status == "OK"
    assert any("接口摘要状态" in warning for warning in result.warnings)
    assert row["switch_interface_data_status"] == "stale"
    assert row["link_status"] == "-"
    assert row["switch_optical_data_status"] == "current"
    assert row["switch_rx_power"] == "-11.7"
    assert row["switch_interface_updated_at"] == "2026-08-02T10:00:00+08:00"


def test_zte_connection_failure_does_not_present_old_realtime_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repository = _repository(tmp_path)
    station = DeviceGroupRepository(repository.database, "demo").create("车站")
    device = _create_switch(
        repository,
        group_id=int(station.id or 0),
        name="连接失败",
        address="192.0.2.33",
    )
    _seed_effective_trackside_aps(repository, [device])
    facts = DeviceFactRepository(repository.database)
    device_uuid = str(device.device_uuid)
    facts.mark_device_collection_attempt(
        device_uuid,
        "old-run",
        "files/rail_transit/trackside_ap/raw/old-run",
    )
    facts.replace_device_interfaces(
        device_uuid,
        [
            {
                "interface_name": "gei-0/3/0/1",
                "description": "Trackside AP",
                "link_status": "UP",
                "protocol_status": "up",
                "port_status": "hybrid",
                "collect_run_uuid": "old-run",
                "collected_at": "2026-08-02T10:00:00+08:00",
                "updated_at": "2026-08-02T10:00:00+08:00",
            }
        ],
    )
    facts.replace_optical_modules(
        device_uuid,
        [
            {
                "interface_name": "gei-0/3/0/1",
                "device_vendor": "ZTE",
                "rx_power": "-7.10",
                "tx_power": "-4.90",
                "status": "normal",
                "collect_run_uuid": "old-run",
                "collected_at": "2026-08-02T10:00:00+08:00",
                "updated_at": "2026-08-02T10:00:00+08:00",
            }
        ],
    )
    monkeypatch.setattr(
        trackside_optical_collection.netmiko_connection,
        "ConnectHandler",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("connection failed")),
    )
    targets, _ = build_station_switch_targets(repository, "demo")

    result = _collect_one_target(
        targets[0],
        artifact_dir=tmp_path / "raw" / "connection-failed",
        repository=repository,
    )
    _persist_result(
        repository,
        AcRepository(repository.database),
        result,
        tmp_path / "parsed" / "trackside_update_results.sqlite",
    )

    snapshot = load_trackside_ap_business_snapshot(repository, "demo", generation=1)
    row = snapshot.rows[0]
    assert result.success is False
    latest_fact = facts.get_device_fact(device_uuid)
    assert latest_fact["collect_run_uuid"] == result.collect_run_uuid
    assert latest_fact["raw_log_path"] == (
        "files/rail_transit/trackside_ap/raw/old-run"
    )
    assert row["switch_interface_data_status"] == "stale"
    assert row["link_status"] == "-"
    assert row["protocol_status"] is None
    assert row["switch_optical_data_status"] == "stale"
    assert row["switch_rx_power"] is None
    assert row["switch_tx_power"] is None
    assert row["switch_optical_status"] == "unknown"
    assert row["switch_interface_updated_at"] == "2026-08-02T10:00:00+08:00"
    assert row["switch_optical_updated_at"] == "2026-08-02T10:00:00+08:00"


def test_zte_snapshot_rejects_count_regression_without_changing_h3c_behavior(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    station = DeviceGroupRepository(repository.database, "demo").create("车站")
    _create_switch(
        repository,
        group_id=int(station.id or 0),
        name="条数保护",
        address="192.0.2.34",
    )
    target = build_station_switch_targets(repository, "demo")[0][0]
    current_rows = [{"interface_name": "gei-0/3/0/1"}]
    existing_rows = [
        {"interface_name": "gei-0/3/0/1"},
        {"interface_name": "gei-0/3/0/2"},
    ]
    zte_result = TracksideDeviceCollectionResult(
        target=target,
        success=True,
        vendor="ZTE",
        interface_snapshot_status="OK",
    )
    h3c_result = TracksideDeviceCollectionResult(
        target=target,
        success=True,
        vendor="H3C",
        interface_snapshot_status="OK",
    )

    assert _snapshot_can_replace(
        zte_result,
        "interface",
        current_rows,
        existing_rows,
    ) is False
    assert zte_result.interface_snapshot_status == "INCOMPLETE"
    assert any("少于上一份 2 条" in warning for warning in zte_result.warnings)
    assert _snapshot_can_replace(
        h3c_result,
        "interface",
        current_rows,
        existing_rows,
    ) is True
    assert h3c_result.interface_snapshot_status == "OK"


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
