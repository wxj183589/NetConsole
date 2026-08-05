from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ac_management_web_fixture import build_ac_management_fixture
from netconsole.core.database import Database
from netconsole.models.api.ac_management import AcApDTO, AcLldpDTO, AcOpticalDTO
from netconsole.repositories.ac_repository import AcRepository
from netconsole.services.ap_identity import ApIdentityQueryService
from netconsole.services.ac.query_service import AcManagementQueryService
from netconsole.services.config_lifecycle_service import extract_h3c_configuration_body


def _fingerprint(path: Path) -> tuple[str, int]:
    return hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns


def test_ac_query_service_reads_summary_filters_and_details_without_writes(tmp_path: Path) -> None:
    paths, db_path, _files = build_ac_management_fixture(tmp_path)
    service = AcManagementQueryService(paths)
    before = _fingerprint(db_path)

    summary = service.get_summary("demo")
    online = service.list_aps("demo", status="online")
    offline = service.list_aps("demo", status="offline")
    unauthenticated = service.list_aps("demo", status="unauthenticated")
    section = service.list_aps("demo", section="A-B")
    detail = service.get_ap_detail("demo", "ap-offline")
    page_details = service.list_ap_details_for_macs(
        "demo",
        ["0000-0000-0001"],
    )

    assert summary.ap_total == 3
    assert summary.online_aps == 2
    assert summary.offline_aps == 1
    assert summary.unauthenticated_aps == 1
    assert summary.acs[0].web_url == "https://10.0.0.1:443"
    assert online.total == 1
    assert offline.total == 1
    assert unauthenticated.total == 1
    assert online.filter_options.stations == ["车站A", "车站B"]
    assert online.filter_options.sections == ["A-B 区间", "B-C 区间"]
    assert online.filter_options.models == ["WA-Test"]
    assert online.filter_options.switches == ["接入交换机"]
    assert unauthenticated.items[0].station == "车站A"
    assert unauthenticated.items[0].station_source == "resource"
    assert section.items[0].id == "ap-online"
    assert detail is not None
    assert [item.ap.id for item in page_details] == ["ap-online"]
    assert page_details[0].radios == []
    assert [radio.radio_id for radio in detail.radios] == [1, 2]
    assert all(radio.radio_id != 3 for radio in detail.radios)
    assert [radio.clients for radio in detail.radios] == [3, 1]
    assert detail.ap.station == "车站B"
    assert detail.ap.station_source == "metadata"
    assert "serial" not in str(detail.model_dump()).casefold()
    assert "SECRET-SN" not in str(detail.model_dump())
    assert _fingerprint(db_path) == before


def test_ac_query_service_coalesces_unmatched_unauthenticated_duplicate_by_serial(
    tmp_path: Path,
) -> None:
    paths, db_path, _files = build_ac_management_fixture(tmp_path)
    with Database(db_path).connect() as conn:
        conn.execute(
            """
            INSERT INTO ac_fit_ap_unauthenticated (
                ac_device_uuid, ap_name, apid, state, state_display, model,
                serial_number, collected_at, updated_at
            ) VALUES (
                'ac-1', 'AP-Online', '1', 'R/M', '运行(主)', 'WA-Test',
                'SECRET-SN-1', '2026-07-29T00:42:15+08:00',
                '2026-07-29T00:42:15+08:00'
            )
            """
        )
        conn.commit()

    page = AcManagementQueryService(paths).list_aps(
        "demo",
        ac_id="ac-1",
        query="AP-Online",
        page_size=20,
    )

    assert page.total == 1
    assert page.items[0].id == "ap-online"
    assert page.items[0].mac == "0000-0000-0001"


def test_ac_query_service_searches_actual_radio_mac_via_identity_index(
    tmp_path: Path,
) -> None:
    paths, db_path, _files = build_ac_management_fixture(tmp_path)
    database = Database(db_path)
    ApIdentityQueryService(database).rebuild_index("test_fixture_ready")

    page = AcManagementQueryService(paths).list_aps(
        "demo",
        query="00:00:00:01:00:01",
    )

    assert page.total == 1
    assert page.items[0].id == "ap-online"
    assert page.items[0].name == "AP-Online"


def test_ac_query_service_suggests_station_from_unique_lldp_switch_without_writes(tmp_path: Path) -> None:
    paths, db_path, _files = build_ac_management_fixture(tmp_path)
    database = Database(db_path)
    with database.connect() as conn:
        conn.execute("UPDATE devices SET station = '车辆段A' WHERE device_uuid = 'switch-1'")
        conn.execute(
            "UPDATE ac_fit_ap_resources SET site = NULL, lldp_neighbor_name = 'SW-TEST' WHERE ap_uuid = 'ap-unauth'"
        )
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    before = _fingerprint(db_path)

    detail = AcManagementQueryService(paths).get_ap_detail("demo", "ap-unauth")

    assert detail is not None
    assert detail.ap.station == "车辆段A"
    assert detail.ap.station_source == "lldp_switch_suggestion"
    assert detail.lldp.switch_device_uuid == "switch-1"
    assert _fingerprint(db_path) == before


def test_ac_query_service_does_not_suggest_station_when_switch_station_is_empty(tmp_path: Path) -> None:
    paths, db_path, _files = build_ac_management_fixture(tmp_path)
    with Database(db_path).connect() as conn:
        conn.execute("UPDATE ac_fit_ap_resources SET site = NULL WHERE ap_uuid = 'ap-unauth'")
        conn.commit()

    detail = AcManagementQueryService(paths).get_ap_detail("demo", "ap-unauth")

    assert detail is not None
    assert detail.ap.station == ""
    assert detail.ap.station_source == "empty"


def test_ac_query_service_does_not_guess_station_for_ambiguous_switch_name(tmp_path: Path) -> None:
    paths, db_path, _files = build_ac_management_fixture(tmp_path)
    with Database(db_path).connect() as conn:
        conn.execute("UPDATE devices SET station = '车辆段A' WHERE device_uuid = 'switch-1'")
        conn.execute("UPDATE ac_fit_ap_resources SET site = NULL WHERE ap_uuid = 'ap-unauth'")
        conn.execute(
            """
            INSERT INTO devices (
                device_uuid, name, system_name, station, device_vendor, device_type,
                primary_address, created_at, updated_at
            ) VALUES (
                'switch-2', '接入交换机', 'SW-OTHER', '车辆段B', 'H3C', 'SW',
                '10.0.0.3', '2026-07-14T12:00:00', '2026-07-14T12:00:00'
            )
            """
        )
        conn.commit()

    detail = AcManagementQueryService(paths).get_ap_detail("demo", "ap-unauth")

    assert detail is not None
    assert detail.ap.station == ""
    assert detail.ap.station_source == "empty"
    assert detail.lldp.switch_device_uuid == ""


def test_ac_query_service_returns_allowlisted_radio_history_without_raw_paths(tmp_path: Path) -> None:
    paths, _db_path, _files = build_ac_management_fixture(tmp_path)
    repository = AcRepository(Database(paths.site_db_path("demo")))
    ap = repository.get_fit_ap_resource_by_uuid("ac-1", "ap-online")
    assert ap is not None
    repository.upsert_fit_ap_resource("ac-1", ap)
    service = AcManagementQueryService(paths)

    history = service.get_ap_history("demo", "ap-online", "radio")

    assert history is not None
    assert history.total == 2
    assert {int(row["rid"]): int(row["clients"] or 0) for row in history.items} == {1: 3, 2: 1}
    assert all("ap_name" in row and "status" in row and "usage" in row for row in history.items)
    assert all("raw_log_path" not in row for row in history.items)
    with pytest.raises(ValueError, match="不支持"):
        service.get_ap_history("demo", "ap-online", "unknown")


def test_ac_optical_anomaly_is_independent_from_ap_online_state(tmp_path: Path) -> None:
    paths, _db_path, _files = build_ac_management_fixture(tmp_path)
    service = AcManagementQueryService(paths)

    online = service.get_ap_optical("demo", "ap-online")
    offline = service.get_ap_optical("demo", "ap-offline")
    anomalies = service.list_optical_anomalies("demo")

    assert online is not None
    assert online.raw_status == "no_light"
    assert online.optical_status == "critical"
    assert online.ap_rx_status == "normal"
    assert online.switch_rx_status == "no_light"
    assert online.tx_power_status == "unknown"
    assert online.ap_offline_related is False
    assert online.ap_online_status == "online"
    assert online.is_current_anomaly is True
    assert "当前 AP 在线" in online.anomaly_reason
    assert offline is not None
    assert offline.optical_status == "critical"
    assert offline.ap_rx_status == "abnormal"
    assert offline.switch_rx_status == "alarm"
    assert offline.ap_offline_related is True
    assert offline.ap_online_status == "offline"
    assert offline.is_current_anomaly is True
    assert [item.id for item in anomalies.items] == ["ap-online", "ap-offline"]


def test_ac_optical_reports_switch_side_alarm_without_coloring_ap_rx(tmp_path: Path) -> None:
    paths, db_path, _files = build_ac_management_fixture(tmp_path)
    with Database(db_path).connect() as conn:
        conn.execute(
            """
            UPDATE ac_fit_ap_optical
            SET rx_power = '-8.63', tx_power = '-6.13', rx_low_alarm = '-19 dBm', rx_low_warning = '-17 dBm'
            WHERE ap_uuid = 'ap-online'
            """
        )
        conn.execute(
            """
            UPDATE device_optical_modules
            SET rx_power = '-19.75', rx_low_alarm = '-19 dBm', rx_low_warning = '-17 dBm'
            WHERE interface_name = 'GigabitEthernet1/0/1'
            """
        )
        conn.commit()

    optical = AcManagementQueryService(paths).get_ap_optical("demo", "ap-online")

    assert optical is not None
    assert optical.ap_rx_status == "normal"
    assert optical.switch_rx_status == "alarm"
    assert optical.tx_power_status == "unknown"
    assert optical.raw_status == "alarm"
    assert optical.threshold_status == "一般告警"
    assert optical.is_current_anomaly is True
    assert "交换机侧收光一般告警：-19.75 dBm" in optical.anomaly_reason
    assert "AP 侧收光正常：-8.63 dBm" in optical.anomaly_reason


def test_ac_optical_reports_ap_side_alarm_without_switch_alarm(tmp_path: Path) -> None:
    paths, db_path, _files = build_ac_management_fixture(tmp_path)
    with Database(db_path).connect() as conn:
        conn.execute(
            """
            UPDATE ac_fit_ap_optical
            SET rx_power = '-19.75', rx_low_alarm = '-19 dBm', rx_low_warning = '-17 dBm'
            WHERE ap_uuid = 'ap-online'
            """
        )
        conn.execute(
            """
            UPDATE device_optical_modules
            SET rx_power = '-8.63', rx_low_alarm = '-19 dBm', rx_low_warning = '-17 dBm'
            WHERE interface_name = 'GigabitEthernet1/0/1'
            """
        )
        conn.commit()

    optical = AcManagementQueryService(paths).get_ap_optical("demo", "ap-online")

    assert optical is not None
    assert optical.ap_rx_status == "abnormal"
    assert optical.switch_rx_status == "normal"
    assert optical.raw_status == "abnormal"
    assert "AP 侧收光光衰大：-19.75 dBm" in optical.anomaly_reason
    assert "交换机侧收光正常：-8.63 dBm" in optical.anomaly_reason


def test_ac_optical_reports_both_sides_normal_and_no_data_status(tmp_path: Path) -> None:
    paths, db_path, _files = build_ac_management_fixture(tmp_path)
    with Database(db_path).connect() as conn:
        conn.execute(
            "UPDATE ac_fit_ap_optical SET rx_power = '-8.63', rx_low_alarm = '-19 dBm', rx_low_warning = '-17 dBm' WHERE ap_uuid = 'ap-online'"
        )
        conn.execute(
            "UPDATE device_optical_modules SET rx_power = '-8.64', rx_low_alarm = '-19 dBm', rx_low_warning = '-17 dBm' WHERE interface_name = 'GigabitEthernet1/0/1'"
        )
        conn.commit()

    service = AcManagementQueryService(paths)
    normal = service.get_ap_optical("demo", "ap-online")
    no_data = service.get_ap_optical("demo", "ap-unauth")

    assert normal is not None
    assert normal.ap_rx_status == "normal"
    assert normal.switch_rx_status == "normal"
    assert normal.raw_status == "normal"
    assert normal.is_current_anomaly is False
    assert no_data is not None
    assert no_data.optical_status == "no_data"
    assert no_data.ap_rx_status == "unknown"
    assert no_data.switch_rx_status == "unknown"


def test_ac_optical_fixed_threshold_overrides_backend_normal_status(tmp_path: Path) -> None:
    paths, db_path, _files = build_ac_management_fixture(tmp_path)
    with Database(db_path).connect() as conn:
        conn.execute(
            "UPDATE ac_fit_ap_optical SET rx_power = '-17.80', optical_alarm_status = 'normal' WHERE ap_uuid = 'ap-online'"
        )
        conn.execute(
            "UPDATE device_optical_modules SET rx_power = '-8.63', rx_low_alarm = '-19', rx_low_warning = '-17' WHERE interface_name = 'GigabitEthernet1/0/1'"
        )
        conn.commit()

    service = AcManagementQueryService(paths)
    optical = service.get_ap_optical("demo", "ap-online")

    assert optical is not None
    assert optical.ap_rx_status == "abnormal"
    assert optical.raw_status == "abnormal"
    assert optical.optical_status == "critical"
    assert optical.threshold_status == "光衰大"
    assert optical.is_current_anomaly is True
    assert service.list_optical_anomalies("demo").items[0].id == "ap-online"


def test_ac_optical_wa6522_is_not_applicable_or_anomalous(tmp_path: Path) -> None:
    paths, db_path, _files = build_ac_management_fixture(tmp_path)
    with Database(db_path).connect() as conn:
        conn.execute(
            "UPDATE ac_fit_ap_resources SET model = ' wa6522 ' WHERE ap_uuid = 'ap-online'"
        )
        conn.execute(
            "UPDATE ac_fit_ap_optical SET rx_power = '-30', optical_alarm_status = 'no_light' WHERE ap_uuid = 'ap-online'"
        )
        conn.commit()

    service = AcManagementQueryService(paths)
    optical = service.get_ap_optical("demo", "ap-online")
    item = next(ap for ap in service.list_aps("demo", page_size=10).items if ap.id == "ap-online")
    anomaly_ids = {ap.id for ap in service.list_optical_anomalies("demo", page_size=10).items}

    assert optical is not None
    assert optical.optical_applicable is False
    assert optical.optical_status == "not_applicable"
    assert optical.is_current_anomaly is False
    assert optical.anomaly_reason == "该型号使用网口接入，不适用 AP 光模块光衰检测。"
    assert item.optical_applicable is False
    assert item.optical_status == "not_applicable"
    assert item.optical_rx_power == ""
    assert "ap-online" not in anomaly_ids


@pytest.mark.parametrize("rx_power", [None, "", "--", "invalid"])
def test_ac_optical_missing_or_invalid_ap_rx_is_not_collected(
    tmp_path: Path,
    rx_power: object,
) -> None:
    paths, db_path, _files = build_ac_management_fixture(tmp_path)
    with Database(db_path).connect() as conn:
        conn.execute(
            "UPDATE ac_fit_ap_optical SET rx_power = ?, optical_alarm_status = 'normal', neighbor_rx_power = NULL WHERE ap_uuid = 'ap-online'",
            (rx_power,),
        )
        conn.execute(
            "UPDATE device_optical_modules SET rx_power = NULL, status = 'success' WHERE interface_name = 'GigabitEthernet1/0/1'"
        )
        conn.commit()

    optical = AcManagementQueryService(paths).get_ap_optical("demo", "ap-online")

    assert optical is not None
    assert optical.ap_rx_status == "unknown"
    assert optical.optical_status == "no_data"
    assert optical.is_current_anomaly is False


def test_ac_optical_online_general_alarm_is_current_anomaly_and_stale_data_is_not(tmp_path: Path) -> None:
    paths, db_path, _files = build_ac_management_fixture(tmp_path)
    with Database(db_path).connect() as conn:
        conn.execute(
            """
            UPDATE ac_fit_ap_optical
            SET rx_power = '-23.57 dBm', rx_low_alarm = '-23 dBm', rx_low_warning = '-20 dBm'
            WHERE ap_uuid = 'ap-online'
            """
        )
        conn.execute(
            """
            UPDATE device_optical_modules
            SET rx_power = '-21.61 dBm', rx_low_alarm = '-23 dBm', rx_low_warning = '-20 dBm'
            WHERE interface_name = 'GigabitEthernet1/0/1'
            """
        )
        conn.commit()

    service = AcManagementQueryService(paths)
    optical = service.get_ap_optical("demo", "ap-online")

    assert optical is not None
    assert optical.ap_online_status == "online"
    assert optical.raw_status == "abnormal"
    assert optical.ap_rx_status == "abnormal"
    assert optical.switch_rx_status == "warning"
    assert optical.threshold_status == "光衰大"
    assert optical.optical_status == "critical"
    assert optical.is_current_anomaly is True
    assert "已计入严重光衰异常；当前 AP 在线" in optical.anomaly_reason

    with Database(db_path).connect() as conn:
        conn.execute("UPDATE ac_fit_ap_optical SET collected_at = '2020-01-01T00:00:00+00:00', updated_at = '2020-01-01T00:00:00+00:00' WHERE ap_uuid = 'ap-online'")
        conn.commit()

    stale = service.get_ap_optical("demo", "ap-online")
    assert stale is not None
    assert stale.data_freshness == "stale"
    assert stale.is_current_anomaly is False
    assert stale.ap_rx_status == "abnormal"
    assert stale.switch_rx_status == "warning"
    assert stale.optical_status == "critical"
    assert "不作为当前实时状态统计" in stale.anomaly_reason
    assert "ap-online" not in {item.id for item in service.list_optical_anomalies("demo").items}


def test_ac_optical_offline_with_normal_power_and_explicit_no_module_are_not_anomalies(tmp_path: Path) -> None:
    paths, db_path, _files = build_ac_management_fixture(tmp_path)
    with Database(db_path).connect() as conn:
        conn.execute(
            "UPDATE ac_fit_ap_optical SET rx_power = '-10 dBm', rx_low_alarm = '-19 dBm', rx_low_warning = '-17 dBm' WHERE ap_uuid = 'ap-offline'"
        )
        conn.execute(
            "UPDATE device_optical_modules SET rx_power = '-10 dBm', rx_low_alarm = '-19 dBm', rx_low_warning = '-17 dBm' WHERE interface_name = 'GigabitEthernet1/0/2'"
        )
        conn.execute("UPDATE ac_fit_ap_optical SET optical_alarm_status = 'no_module', rx_power = NULL WHERE ap_uuid = 'ap-online'")
        conn.execute("UPDATE device_optical_modules SET status = 'no_module', rx_power = NULL WHERE interface_name = 'GigabitEthernet1/0/1'")
        conn.commit()

    service = AcManagementQueryService(paths)
    offline = service.get_ap_optical("demo", "ap-offline")
    no_module = service.get_ap_optical("demo", "ap-online")

    assert offline is not None
    assert offline.ap_online_status == "offline"
    assert offline.optical_status == "normal"
    assert offline.ap_offline_related is False
    assert offline.is_current_anomaly is False
    assert no_module is not None
    assert no_module.optical_status == "no_data"
    assert no_module.is_current_anomaly is False


def test_ac_query_service_defaults_to_natural_topology_order_for_resources_and_optical(
    tmp_path: Path,
) -> None:
    paths, _db_path, _files = build_ac_management_fixture(tmp_path)
    service = AcManagementQueryService(paths)
    items = [
        AcApDTO(
            id="ap-missing-switch",
            ac_id="ac-1",
            name="AP-00",
            switch_interface="GE2/0/1",
            optical_status="warning",
            optical_is_current_anomaly=True,
        ),
        AcApDTO(
            id="ap-port-10",
            ac_id="ac-1",
            name="AP-10",
            switch_name="交换机2",
            switch_interface="GE2/0/10",
            optical_status="critical",
            optical_is_current_anomaly=True,
        ),
        AcApDTO(
            id="ap-switch-10",
            ac_id="ac-1",
            name="AP-01",
            switch_name="交换机10",
            switch_interface="GE1/0/1",
            optical_status="warning",
            optical_is_current_anomaly=True,
        ),
        AcApDTO(
            id="ap-missing-port",
            ac_id="ac-1",
            name="AP-20",
            switch_name="交换机2",
            optical_status="critical",
            optical_is_current_anomaly=True,
        ),
        AcApDTO(
            id="ap-port-9",
            ac_id="ac-1",
            name="AP-50",
            switch_name="交换机2",
            switch_interface="GigabitEthernet2/0/9",
            optical_status="warning",
            optical_is_current_anomaly=True,
        ),
    ]
    service._ap_records = lambda _site_id, **_kwargs: [
        (item, {}, AcOpticalDTO(), AcLldpDTO()) for item in items
    ]

    resources = service.list_aps("demo", page_size=20)
    optical = service.list_optical_anomalies("demo", page_size=20)

    expected = ["ap-port-9", "ap-port-10", "ap-missing-port", "ap-switch-10", "ap-missing-switch"]
    assert [item.id for item in resources.items] == expected
    assert [item.id for item in optical.items] == expected
    assert [item.id for item in service.list_aps("demo", page_size=20, sort_by="name").items] == [
        "ap-missing-switch",
        "ap-switch-10",
        "ap-port-10",
        "ap-missing-port",
        "ap-port-9",
    ]


def test_ac_config_snapshot_content_diff_and_path_isolation(tmp_path: Path) -> None:
    paths, db_path, files = build_ac_management_fixture(tmp_path)
    service = AcManagementQueryService(paths)
    running_before = _fingerprint(files["running"])
    db_before = _fingerprint(db_path)
    page = service.list_config_snapshots("demo")
    running = next(item for item in page.items if item.type == "running")

    content = service.get_config_snapshot("demo", running.id)
    diff = service.get_config_diff("demo", running.id)

    assert content is not None
    assert content.content == extract_h3c_configuration_body(files["running"].read_text(encoding="utf-8"))
    assert "header" not in content.content
    assert "<AC-TEST>" not in content.content
    assert diff is not None
    assert "10.0.0.1" in diff.raw_diff
    assert "10.0.0.9" in diff.raw_diff
    assert _fingerprint(files["running"]) == running_before
    assert _fingerprint(db_path) == db_before

    with pytest.raises(ValueError, match="路径越界"):
        service._snapshot_path("demo", {"file_path": "../outside.txt"})
