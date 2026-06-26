from __future__ import annotations

import sqlite3
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from netconsole.core.database import Database
from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.repositories.device_group_repository import DeviceGroupRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.vehicle_mr_online import (
    H3CComwareV9VehicleMrMeshLinkParser,
    MatchedAp,
    ONLINE_POLICY_DUAL_ACTIVE,
    ONLINE_POLICY_SINGLE_TAIL,
    ONLINE_POLICY_SINGLE_TC1,
    ONLINE_POLICY_SINGLE_TC2,
    VehicleMrMeshLink,
    VehicleMrMeshParseResult,
    VehicleMrEndState,
    VehicleMrOnlineStore,
    VehicleMrTrainMapping,
    VehicleMrTrainState,
    backfill_fit_ap_resource_station_from_optical,
    build_mapping_lookup,
    build_registered_trains,
    build_canonical_train_key,
    build_train_states,
    choose_best_links,
    is_same_or_h3c_radio_mac,
    load_trackside_ap_lookup,
    load_vehicle_mr_mapping_trains,
    match_ap,
    normalize_mac,
    normalize_train_no,
    parse_ac_clock_line,
    parse_train_identity,
    resolve_ap_station,
)
from netconsole.ui.pages.rail_transit_page import RailTransitPage
from netconsole.ui.pages.vehicle_mr_online_page import export_vehicle_mr_history_rows, export_vehicle_mr_mapping_template


SAMPLE = """<NBDT12HX-WX3540X-AC1>display clock
22:01:45 Beijing Thu 06/25/2026
Time Zone : Beijing add 08:00:00
<NBDT12HX-WX3540X-AC1>display  wlan  mesh-link ap
AP name: 30f5-277a-8440
 Peer Name              Peer Mac       Local Mac      Status     RSSI Packets(Rx/Tx)
 NBL12-LC06-MR-CW       74ad-cb9d-317f 30f5-277a-844f Forwarding 41   7995/5412

AP name: bc5a-3457-cde0
 Peer Name              Peer Mac       Local Mac      Status     RSSI Packets(Rx/Tx)
 NBL12-LC06-MR-CT       74ad-cb9d-3321 bc5a-3457-cdef Forwarding 58   3202/5050
<NBDT12HX-WX3540X-AC1>
"""


def test_h3c_v9_vehicle_mr_mesh_link_parser_parses_sample() -> None:
    result = H3CComwareV9VehicleMrMeshLinkParser().parse(SAMPLE)

    assert result.parse_status == "OK"
    assert result.ac_time == "2026-06-25 22:01:45"
    assert len(result.links) == 2
    assert {link.local_ap_name for link in result.links} == {"30f5-277a-8440", "bc5a-3457-cde0"}
    by_peer = {link.peer_name: link for link in result.links}
    assert by_peer["NBL12-LC06-MR-CT"].rssi == 58
    assert by_peer["NBL12-LC06-MR-CW"].rx_packets == 7995
    assert by_peer["NBL12-LC06-MR-CW"].tx_packets == 5412


def test_parse_ac_clock_line_full_datetime_and_fallback() -> None:
    fallback = __import__("datetime").datetime(2026, 6, 26, 1, 2, 3)

    assert parse_ac_clock_line("22:01:45 Beijing Thu 06/25/2026", fallback) == "2026-06-25 22:01:45"
    assert parse_ac_clock_line("22:01:45", fallback) == "2026-06-26 22:01:45"
    assert parse_ac_clock_line("bad clock", fallback) == "2026-06-26 01:02:03"


def test_train_no_canonical_names_merge() -> None:
    values = ["06车", "6车", "列车06", "列车6", "LC06", "NBL12-LC06", "列车06-MR-CT", "NBL12-LC06-MR-CT"]

    assert {normalize_train_no(value) for value in values} == {"06"}
    assert {build_canonical_train_key(value) for value in values} == {"train:06"}


def test_parse_train_identity_merges_ct_and_cw_to_same_train() -> None:
    ct = parse_train_identity("NBL12-LC06-MR-CT")
    cw = parse_train_identity("NBL12-LC06-MR-CW")

    assert ct is not None
    assert cw is not None
    assert ct.train_id == "NBL12-LC06"
    assert cw.train_id == "NBL12-LC06"
    assert ct.train_no == "06"
    assert ct.car_end_label == "TC1"
    assert cw.car_end_label == "TC2"


def test_train_status_online_partial_offline_and_unregistered() -> None:
    registered = {"NBL12-LC06": VehicleMrTrainState("NBL12-LC06", "06", True)}
    ap_lookup = {"ap-a": MatchedAp("AP-A", "鼓楼站")}

    both = build_train_states(
        registered,
        VehicleMrMeshParseResult(
            "22:01:45",
            [
                VehicleMrMeshLink("AP-A", "NBL12-LC06-MR-CT", rssi=50),
                VehicleMrMeshLink("AP-A", "NBL12-LC06-MR-CW", rssi=40),
            ],
        ),
        ap_lookup,
    )
    assert both[0].status == "在线"

    only_tc1 = build_train_states(registered, VehicleMrMeshParseResult("22:01:46", [VehicleMrMeshLink("AP-A", "NBL12-LC06-MR-CT", rssi=50)]), ap_lookup)
    assert only_tc1[0].status == "在线"

    only_tc2 = build_train_states(registered, VehicleMrMeshParseResult("22:01:47", [VehicleMrMeshLink("AP-A", "NBL12-LC06-MR-CW", rssi=50)]), ap_lookup)
    assert only_tc2[0].status == "在线"

    offline = build_train_states(registered, VehicleMrMeshParseResult("22:01:48", []), ap_lookup)
    assert offline[0].status == "离线"

    unregistered = build_train_states(registered, VehicleMrMeshParseResult("22:01:49", [VehicleMrMeshLink("AP-A", "NBL12-LC19-MR-CT", rssi=60)]), ap_lookup)
    by_id = {train.train_id: train for train in unregistered}
    assert by_id["NBL12-LC19"].is_registered is False
    assert by_id["NBL12-LC19"].status == "在线"


def test_registered_train_no_merges_ac_peer_with_different_prefix() -> None:
    registered = {"列车06": VehicleMrTrainState("列车06", "06", True)}
    result = VehicleMrMeshParseResult(
        "00:22:05",
        [
            VehicleMrMeshLink("AP-A", "NBL12-LC06-MR-CT", rssi=45),
            VehicleMrMeshLink("AP-B", "NBL12-LC06-MR-CW", rssi=52),
        ],
    )

    trains = build_train_states(registered, result, {})

    assert len(trains) == 1
    assert trains[0].train_id == "列车06"
    assert trains[0].display_name == "06车"
    assert trains[0].is_registered is True
    assert trains[0].status == "在线"


def test_best_ap_chooses_highest_rssi_and_ignores_missing_rssi() -> None:
    links = [
        VehicleMrMeshLink("AP-A", "NBL12-LC06-MR-CT", rssi=37),
        VehicleMrMeshLink("AP-B", "NBL12-LC06-MR-CT", rssi=None),
        VehicleMrMeshLink("AP-C", "NBL12-LC06-MR-CT", rssi=58),
    ]

    best = choose_best_links(links)

    assert best["NBL12-LC06-MR-CT"].local_ap_name == "AP-C"
    states = build_train_states({}, VehicleMrMeshParseResult("22:01:45", links), {})
    assert states[0].tc1.station == "未知车站"
    assert states[0].tc1.ap_name == "AP-C"


def test_registered_vehicle_mr_devices_prebuild_train_rows(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path)
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    repository = DeviceRepository(database)
    group = DeviceGroupRepository(database, "demo").create("车载")
    for index in range(1, 19):
        for suffix in ("CT", "CW"):
            repository.create(Device(name=f"NBL12-LC{index:02d}-MR-{suffix}", group_id=group.id, device_type="FAT-AP", primary_address=f"192.0.2.{index}"))

    trains = build_registered_trains(repository.list(), {group.id: group.name})

    assert len(trains) == 18
    assert "NBL12-LC01" in trains
    assert "NBL12-LC18" in trains


def test_vehicle_group_chinese_names_and_station_fallback_generate_ordered_trains(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path)
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    repository = DeviceRepository(database)
    group = DeviceGroupRepository(database, "demo").create("车载")
    for index in range(1, 19):
        if index in {1, 18}:
            repository.create(Device(name=f"列车{index:02d}-MR-CT", group_id=group.id, device_type="FAT-AP", primary_address=f"192.0.2.{index}", station=f"{index:02d}车车头"))
            repository.create(Device(name=f"列车{index:02d}-MR-CW", group_id=group.id, device_type="FAT-AP", primary_address=f"192.0.3.{index}", station=f"{index:02d}车车尾"))
        else:
            repository.create(Device(name=f"MR-{index:02d}-A", group_id=group.id, device_type="FAT-AP", primary_address=f"192.0.2.{index}", station=f"{index:02d}车车头"))
            repository.create(Device(name=f"MR-{index:02d}-B", group_id=group.id, device_type="FAT-AP", primary_address=f"192.0.3.{index}", station=f"{index:02d}车车尾"))

    trains = build_registered_trains(repository.list(), {group.id: group.name})
    ordered = sorted(trains.values(), key=lambda train: int(train.train_no))

    assert len(ordered) == 18
    assert [train.display_name for train in ordered[:2]] == ["01车", "02车"]
    assert ordered[-1].display_name == "18车"


def test_optional_vehicle_mr_mapping_table_prebuilds_trains(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path)
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    repository = DeviceRepository(database)
    with database.connect() as conn:
        conn.execute("CREATE TABLE vehicle_mr_mapping (peer_name TEXT, train_id TEXT, train_no TEXT, car_end TEXT)")
        conn.execute("INSERT INTO vehicle_mr_mapping VALUES ('custom', 'MAP-LC06', '06', 'TC1')")
        conn.commit()

    trains = load_vehicle_mr_mapping_trains(repository)

    assert trains["MAP-LC06"].display_name == "06车"


def test_mapping_import_and_peer_lookup_priority(tmp_path: Path) -> None:
    store = VehicleMrOnlineStore(PathResolver(tmp_path), "demo")
    count = store.import_mapping_rows(
        [
            {"车次": "1车", "TC1": "0101", "TC2": "0106", "备注": ""},
            {"车次": "2车", "TC1": "0201", "TC2": "0206", "备注": ""},
        ]
    )
    lookup = build_mapping_lookup(store.list_mappings())
    result = VehicleMrMeshParseResult("2026-06-26 01:15:38", [VehicleMrMeshLink("AP-A", "0101", rssi=45), VehicleMrMeshLink("AP-B", "0106", rssi=46)])

    trains = build_train_states({}, result, {}, {}, lookup)

    assert count == 2
    assert lookup["0101"].train_no == "01"
    assert trains[0].display_name == "01车"
    assert trains[0].status == "在线"


def test_mapping_edit_replaces_old_peer(tmp_path: Path) -> None:
    store = VehicleMrOnlineStore(PathResolver(tmp_path), "demo")
    store.import_mapping_rows([{"车次": "1车", "TC1": "0101", "TC2": "0106", "备注": ""}])
    mapping = store.list_mappings()[0]
    mapping.tc1_peer_name = "01A"
    store.save_mappings([mapping])
    lookup = build_mapping_lookup(store.list_mappings())

    assert "01A" in lookup
    assert "0101" not in lookup


def test_mapping_template_export_contains_required_headers(tmp_path: Path) -> None:
    path = tmp_path / "template.xlsx"

    export_vehicle_mr_mapping_template(path)

    from openpyxl import load_workbook

    sheet = load_workbook(path).active
    assert [sheet.cell(1, index).value for index in range(1, 6)] == ["车次", "TC1", "TC2", "在线策略", "备注"]


def test_online_policy_dual_active_marks_missing_end_abnormal() -> None:
    registered = {
        "列车06": VehicleMrTrainState("列车06", "06", True, online_policy=ONLINE_POLICY_DUAL_ACTIVE),
    }

    trains = build_train_states(registered, VehicleMrMeshParseResult("00:01:00", [VehicleMrMeshLink("AP-A", "列车06-MR-CT", rssi=45)]), {})

    assert trains[0].status == "异常单端"
    assert trains[0].status_reason == "tc2_missing"


def test_online_policy_single_tc1_and_tc2_expected_end_rules() -> None:
    tc1_registered = {"列车06": VehicleMrTrainState("列车06", "06", True, online_policy=ONLINE_POLICY_SINGLE_TC1)}
    tc1_expected = build_train_states(tc1_registered, VehicleMrMeshParseResult("00:01:00", [VehicleMrMeshLink("AP-A", "列车06-MR-CT", rssi=45)]), {})
    tc1_unexpected = build_train_states(tc1_registered, VehicleMrMeshParseResult("00:02:00", [VehicleMrMeshLink("AP-B", "列车06-MR-CW", rssi=45)]), {})

    assert tc1_expected[0].status == "在线"
    assert tc1_expected[0].expected_end == "TC1"
    assert tc1_unexpected[0].status == "非预期端在线"

    tc2_registered = {"列车07": VehicleMrTrainState("列车07", "07", True, online_policy=ONLINE_POLICY_SINGLE_TC2)}
    tc2_expected = build_train_states(tc2_registered, VehicleMrMeshParseResult("00:03:00", [VehicleMrMeshLink("AP-C", "列车07-MR-CW", rssi=45)]), {})

    assert tc2_expected[0].status == "在线"
    assert tc2_expected[0].expected_end == "TC2"


def test_online_policy_single_tail_unknown_direction_treats_any_end_online() -> None:
    registered = {"列车06": VehicleMrTrainState("列车06", "06", True, online_policy=ONLINE_POLICY_SINGLE_TAIL)}

    trains = build_train_states(registered, VehicleMrMeshParseResult("00:01:00", [VehicleMrMeshLink("AP-A", "列车06-MR-CT", rssi=45)]), {})

    assert trains[0].status == "在线"
    assert trains[0].direction == "未知"
    assert trains[0].status_reason == "direction_unknown_any_end_online"


def test_mapping_import_old_template_defaults_online_policy_auto(tmp_path: Path) -> None:
    store = VehicleMrOnlineStore(PathResolver(tmp_path), "demo")

    store.import_mapping_rows([{"车次": "1车", "TC1": "0101", "TC2": "0106", "备注": "old"}])

    mapping = store.list_mappings()[0]
    assert mapping.online_policy == "auto"
    assert build_mapping_lookup([mapping])["0101"].online_policy == "auto"


def test_mapping_import_and_save_preserve_online_policy(tmp_path: Path) -> None:
    store = VehicleMrOnlineStore(PathResolver(tmp_path), "demo")

    store.import_mapping_rows([{"车次": "1车", "TC1": "0101", "TC2": "0106", "在线策略": "双端在线", "备注": ""}])
    mapping = store.list_mappings()[0]

    assert mapping.online_policy == ONLINE_POLICY_DUAL_ACTIVE
    trains = build_train_states({}, VehicleMrMeshParseResult("00:01:00", [VehicleMrMeshLink("AP-A", "0101", rssi=45)]), {}, {}, build_mapping_lookup([mapping]))
    assert trains[0].status == "异常单端"


def test_pass_events_store_policy_reason_fields(tmp_path: Path) -> None:
    store = VehicleMrOnlineStore(PathResolver(tmp_path), "demo")
    train = VehicleMrTrainState(
        "列车06",
        "06",
        True,
        status="异常单端",
        current_station="鼓楼站",
        last_ac_time="2026-06-26 09:00:00",
        tc1=VehicleMrEndState(True, "鼓楼站", "AP-A", 46, "2026-06-26 09:00:00"),
        online_policy=ONLINE_POLICY_DUAL_ACTIVE,
        status_reason="tc2_missing",
    )

    store.persist_snapshot("s1", 1, VehicleMrMeshParseResult(train.last_ac_time, []), [train], {}, 10)

    event = store.list_events("列车06", 1)[0]
    assert event["online_policy"] == ONLINE_POLICY_DUAL_ACTIVE
    assert event["status_reason"] == "tc2_missing"
    assert event["status"] == "异常单端"


def test_vehicle_mr_store_persists_unregistered_current_state(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path)
    store = VehicleMrOnlineStore(paths, "demo")
    train = VehicleMrTrainState("NBL12-LC19", "19", False, status="单端在线", current_station="未知车站", last_ac_time="22:01:45")
    result = VehicleMrMeshParseResult("22:01:45", [VehicleMrMeshLink("AP-X", "NBL12-LC19-MR-CT", rssi=61)])
    store.persist_snapshot("s1", 1, result, [train], {}, 12)

    reloaded = store.list_current_states()

    assert reloaded[0].train_id == "NBL12-LC19"
    assert reloaded[0].is_registered is False
    with sqlite3.connect(store.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM vehicle_mr_online_links").fetchone()[0] == 1


def test_cleanup_history_keeps_recent_mapping_current_state_and_external_tables(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path)
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    repository = DeviceRepository(database)
    repository.create(Device(name="AC1", device_type="AC", primary_address="192.0.2.1"))
    store = VehicleMrOnlineStore(paths, "demo")
    now = __import__("datetime").datetime(2026, 6, 26, 0, 0, 0)
    old = "2026-05-26 00:00:00"
    recent = "2026-05-28 00:00:00"
    store.import_mapping_rows([{"车次": "1车", "TC1": "0101", "TC2": "0106", "备注": ""}])
    with store.connect() as conn:
        conn.execute("INSERT INTO vehicle_mr_online_sessions (session_id, created_at) VALUES ('old', ?)", (old,))
        conn.execute("INSERT INTO vehicle_mr_online_sessions (session_id, created_at) VALUES ('recent', ?)", (recent,))
        conn.execute("INSERT INTO vehicle_mr_online_snapshots (session_id, created_at) VALUES ('old', ?)", (old,))
        conn.execute("INSERT INTO vehicle_mr_online_links (session_id, created_at) VALUES ('old', ?)", (old,))
        conn.execute("INSERT INTO vehicle_mr_train_pass_events (train_id, created_at) VALUES ('old', ?)", (old,))
        conn.execute("INSERT INTO vehicle_mr_train_current_state (train_id, train_no, updated_at) VALUES ('列车01', '01', ?)", (old,))

    deleted = store.cleanup_history(30, now=now)

    with store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM vehicle_mr_online_sessions WHERE session_id='old'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM vehicle_mr_online_sessions WHERE session_id='recent'").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM vehicle_mr_train_mapping").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM vehicle_mr_train_current_state").fetchone()[0] == 1
    assert repository.list()
    assert deleted >= 4


def test_fit_ap_resource_station_match_by_ap_name_and_persist_method(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path)
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    repository = DeviceRepository(database)
    with database.connect() as conn:
        conn.execute(
            """
            INSERT INTO ac_fit_ap_resources (
                ac_device_uuid, ap_uuid, ap_name, ap_mac, site, collected_at, updated_at
            ) VALUES ('ac1', 'ap1', 'bc5a-3457-a740', 'bc5a-3457-a740', '鼓楼站', 'now', 'now')
            """
        )
        conn.commit()
    lookup = load_trackside_ap_lookup(repository)
    result = VehicleMrMeshParseResult("00:22:05", [VehicleMrMeshLink("bc5a-3457-a740", "列车06-MR-CT", local_mac="bc5a-3457-a740", rssi=46)])
    trains = build_train_states({"列车06": VehicleMrTrainState("列车06", "06", True)}, result, lookup)

    assert trains[0].current_station == "鼓楼站"
    assert trains[0].tc1.display() == "鼓楼站 / bc5a-3457-a740 / 46"
    store = VehicleMrOnlineStore(paths, "demo")
    store.persist_snapshot("s1", 1, result, trains, lookup, 10)
    with sqlite3.connect(store.db_path) as conn:
        row = conn.execute("SELECT matched_station, matched_ap_name, match_method, match_score FROM vehicle_mr_online_links").fetchone()
    assert row == ("鼓楼站", "bc5a-3457-a740", "ap_name_exact", 100)


def test_resolve_ap_station_prefers_optical_site() -> None:
    station, source = resolve_ap_station(
        {
            "resource.ap_name": "30f5-2787-a560",
            "resource.site": "-",
            "metadata.site_name": "-",
            "optical.site": "11云龙车辆段",
        }
    )

    assert station == "11云龙车辆段"
    assert source == "optical.site"


def test_optical_site_backfills_empty_fit_ap_resource_site(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path)
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    repository = DeviceRepository(database)
    with database.connect() as conn:
        conn.execute(
            """
            INSERT INTO ac_fit_ap_resources (
                ac_device_uuid, ap_uuid, ap_name, ap_mac, site, collected_at, updated_at
            ) VALUES ('ac1', 'ap1', '30f5-2787-a560', '30f5-2787-a560', '-', 'now', 'now')
            """
        )
        conn.execute(
            """
            INSERT INTO ac_fit_ap_optical (
                ac_device_uuid, ap_uuid, ap_name, ap_mac, site
            ) VALUES ('ac1', 'ap1', '30f5-2787-a560', '30f5-2787-a560', '11云龙车辆段')
            """
        )
        conn.commit()

    changed = backfill_fit_ap_resource_station_from_optical(repository)

    assert changed == 1
    with database.connect() as conn:
        assert conn.execute("SELECT site FROM ac_fit_ap_resources WHERE ap_name='30f5-2787-a560'").fetchone()[0] == "11云龙车辆段"


def test_online_vehicle_mr_uses_optical_site_for_station_display(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path)
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    repository = DeviceRepository(database)
    with database.connect() as conn:
        conn.execute("INSERT INTO ac_fit_ap_optical (ac_device_uuid, ap_uuid, ap_name, ap_mac, site) VALUES ('ac1', 'ap1', '30f5-2787-a560', '30f5-2787-a560', '11云龙车辆段')")
        conn.commit()
    lookup = load_trackside_ap_lookup(repository)
    result = VehicleMrMeshParseResult("00:22:05", [VehicleMrMeshLink("30f5-2787-a560", "NBL12-LC06-MR-CT", local_mac="30f5-2787-a560", rssi=45)])

    trains = build_train_states({"列车06": VehicleMrTrainState("列车06", "06", True)}, result, lookup)

    assert trains[0].current_station == "11云龙车辆段"
    assert trains[0].tc1.display() == "11云龙车辆段 / 30f5-2787-a560 / 45"


def test_h3c_radio_mac_tolerant_match_returns_station() -> None:
    lookup = {
        "__resources__": [MatchedAp("Y01-02", "鼓楼站", "resource", 0, "bc5a3457a740")],
    }

    matched = match_ap("unknown-ap", lookup, "bc5a-3457-a750")

    assert normalize_mac("BC5A-3457-A740") == "bc5a3457a740"
    assert is_same_or_h3c_radio_mac("bc5a-3457-a740", "bc5a-3457-a750")
    assert matched is not None
    assert matched.station == "鼓楼站"
    assert matched.match_method == "h3c_radio_mac"
    assert matched.match_score == 80


def test_pass_events_are_persisted_for_online_ap_station_and_offline_changes(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path)
    store = VehicleMrOnlineStore(paths, "demo")
    train_id = "列车06"
    states = [
        VehicleMrTrainState(train_id, "06", True, status="单端在线", current_station="鼓楼站", last_ac_time="00:01:00", tc1=VehicleMrEndState(True, "鼓楼站", "AP-A", 46, "00:01:00")),
        VehicleMrTrainState(train_id, "06", True, status="单端在线", current_station="鼓楼站", last_ac_time="00:02:00", tc1=VehicleMrEndState(True, "鼓楼站", "AP-B", 48, "00:02:00")),
        VehicleMrTrainState(train_id, "06", True, status="单端在线", current_station="西门口站", last_ac_time="00:03:00", tc1=VehicleMrEndState(True, "西门口站", "AP-C", 50, "00:03:00")),
        VehicleMrTrainState(train_id, "06", True, status="离线", current_station="-", last_ac_time="00:04:00", tc1=VehicleMrEndState(False, last_seen_at="00:03:00")),
    ]
    for index, state in enumerate(states, start=1):
        store.persist_snapshot("s1", index, VehicleMrMeshParseResult(state.last_ac_time, []), [state], {}, 5)

    reloaded = VehicleMrOnlineStore(paths, "demo").list_events(train_id, 200)
    event_types = [row["event_type"] for row in reversed(reloaded)]

    assert event_types == ["online", "ap_changed", "station_changed", "offline"]


def test_rail_transit_first_tab_is_vehicle_mr_online(tmp_path: Path) -> None:
    QApplication.instance() or QApplication([])
    paths = PathResolver(tmp_path)
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    page = RailTransitPage(DeviceRepository(database), I18n("zh_CN"), "demo", paths)

    assert page.tabs.tabText(0) == "在线车载MR"
    assert page.vehicle_mr_online_page.interval_spin.value() == 10
    assert page.vehicle_mr_online_page.interval_spin.minimum() == 3
    assert page.vehicle_mr_online_page.interval_spin.maximum() == 300
    assert page.vehicle_mr_online_page.interval_unit_label.text() == "秒"


def test_vehicle_mr_page_status_items_have_readable_roles_and_interval_validation(tmp_path: Path) -> None:
    QApplication.instance() or QApplication([])
    paths = PathResolver(tmp_path)
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    rail_page = RailTransitPage(DeviceRepository(database), I18n("zh_CN"), "demo", paths)
    page = rail_page.vehicle_mr_online_page
    page.current_trains = {
        "列车06": VehicleMrTrainState("列车06", "06", True, status="离线"),
        "列车19": VehicleMrTrainState("列车19", "19", False, status="单端在线"),
    }

    page._fill_train_table(list(page.current_trains.values()))

    offline_item = page.train_table.item(0, 1)
    partial_item = page.train_table.item(1, 1)
    assert offline_item.text() == "离线"
    assert offline_item.data(Qt.UserRole) == "status-offline"
    assert offline_item.data(Qt.UserRole + 1)
    assert offline_item.data(Qt.UserRole + 2)
    assert partial_item.data(Qt.UserRole) == "status-partial"

    page.interval_spin.setValue(3)
    assert page._interval_seconds() == 3
    page.interval_spin.setValue(300)
    assert page._interval_seconds() == 300


def test_vehicle_mr_event_table_keeps_user_widths_and_centers_cells(tmp_path: Path) -> None:
    QApplication.instance() or QApplication([])
    paths = PathResolver(tmp_path)
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    rail_page = RailTransitPage(DeviceRepository(database), I18n("zh_CN"), "demo", paths)
    page = rail_page.vehicle_mr_online_page
    store = page.store
    train_id = "列车06"
    state = VehicleMrTrainState(
        train_id,
        "06",
        True,
        status="单端在线",
        current_station="鼓楼站",
        last_ac_time="2026-06-26 09:00:00",
        tc1=VehicleMrEndState(True, "鼓楼站", "AP-A", 46, "2026-06-26 09:00:00"),
    )
    store.persist_snapshot("s1", 1, VehicleMrMeshParseResult(state.last_ac_time, []), [state], {}, 10)
    page.event_table.setColumnWidth(0, 222)

    page._fill_events(train_id)

    assert page.event_table.columnWidth(0) == 222
    assert page.event_table.item(0, 0).textAlignment() == Qt.AlignCenter
    assert page.event_table.item(0, 2).textAlignment() == Qt.AlignCenter


def test_vehicle_mr_store_query_events_filters_by_time_end_status_station_and_ap(tmp_path: Path) -> None:
    store = VehicleMrOnlineStore(PathResolver(tmp_path), "demo")
    rows = [
        ("列车06", "06车", "06", "TC1", "2026-06-26 01:00:00", "在线", "鼓楼站", "AP-A", 46, "online"),
        ("列车06", "06车", "06", "TC2", "2026-06-26 01:20:00", "在线", "西门口站", "AP-B", 48, "station_changed"),
        ("列车06", "06车", "06", "TC1", "2026-06-26 02:00:00", "离线", "-", "AP-C", None, "offline"),
    ]
    with store.connect() as conn:
        conn.executemany(
            """
            INSERT INTO vehicle_mr_train_pass_events (
                train_id, train_display_name, train_no, car_end_label, event_time,
                status, station, ap_name, rssi, event_type, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [(*row, row[4]) for row in rows],
        )

    assert len(store.query_events("列车06", "2026-06-26 00:00:00", "2026-06-26 01:30:00")) == 2
    assert len(store.query_events("06车", "2026-06-26 00:00:00", "2026-06-26 01:30:00")) == 2
    assert len(store.query_events("NBL12-LC06", "2026-06-26 00:00:00", "2026-06-26 01:30:00")) == 2
    assert [row["car_end_label"] for row in store.query_events("06车", "2026-06-26 00:00:00", "2026-06-26 01:30:00", car_end_label="TC1")] == ["TC1"]
    assert [row["station"] for row in store.query_events("06车", "2026-06-26 00:00:00", "2026-06-26 01:30:00", station="西门")] == ["西门口站"]
    assert [row["ap_name"] for row in store.query_events("06车", "2026-06-26 00:00:00", "2026-06-26 01:30:00", ap_name="AP-B")] == ["AP-B"]
    assert [row["event_type"] for row in store.query_events("06车", "2026-06-26 00:00:00", "2026-06-26 03:00:00", status="离线")] == ["offline"]


def test_vehicle_mr_history_export_writes_rows(tmp_path: Path) -> None:
    path = tmp_path / "history.xlsx"

    export_vehicle_mr_history_rows(
        path,
        [
            {
                "event_time": "2026-06-26 01:00:00",
                "car_end_label": "TC1",
                "status": "在线",
                "station": "鼓楼站",
                "ap_name": "AP-A",
                "rssi": 46,
                "event_type": "online",
            }
        ],
    )

    from openpyxl import load_workbook

    sheet = load_workbook(path).active
    assert sheet.cell(1, 1).value == "时间"
    assert sheet.cell(2, 4).value == "鼓楼站"
