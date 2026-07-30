from __future__ import annotations

from datetime import datetime

import pytest

from netconsole.models.api.ac_mesh_link import AcMeshMrStatusDTO
from netconsole.models.api.rail_transit_base_data import (
    MileageDTO,
    MeshRadioDTO,
    RailTransitSummaryDTO,
    SectionDTO,
    StationDTO,
    TracksideApDTO,
    VehicleMrDTO,
)
from netconsole.services.ground_unattended.eligibility import (
    GroundUnattendedEligibilityClassifier,
    StationaryTracker,
)


NOW = datetime.fromisoformat("2026-07-25T12:00:00+08:00")


@pytest.mark.parametrize(
    ("station", "section", "metadata", "expected"),
    [
        (StationDTO(id="s1", name="正线站"), None, {}, "MAINLINE"),
        (
            StationDTO(
                id="s1",
                name="车辆段",
                node_type="depot",
                path_code="YARD",
                participates_in_direction=False,
            ),
            None,
            {},
            "DEPOT",
        ),
        (
            StationDTO(
                id="s1",
                name="停车场",
                node_type="parking_lot",
                path_code="PARK",
                participates_in_direction=False,
            ),
            None,
            {},
            "PARKING_LOT",
        ),
        (
            StationDTO(id="s1", name="存车站", track_facilities=["storage_track"]),
            None,
            {},
            "STORAGE_TRACK",
        ),
        (
            StationDTO(id="s1", name="支线站", path_code="BRANCH"),
            None,
            {},
            "NON_MAIN_PATH",
        ),
        (
            None,
            SectionDTO(id="x1", name="出入段线", section_kind="depot_connection"),
            {},
            "DEPOT_CONNECTION",
        ),
        (None, None, {"belong_type": "storage_track"}, "STORAGE_TRACK"),
        (
            None,
            None,
            {"track_facilities": ["turnback_line", "storage_track"]},
            "STORAGE_TRACK",
        ),
    ],
)
def test_structured_mainline_exclusions(station, section, metadata, expected) -> None:
    ap = _ap(station.name if station else "", section.name if section else "", metadata)
    result = _classify(
        ap=ap,
        stations=[station] if station else [],
        sections=[section] if section else [],
    )
    assert result.train.eligibility_status == expected
    assert result.train.ping_eligible is (expected == "MAINLINE")


def test_unmatched_and_stale_ac_do_not_become_depot() -> None:
    unmatched = _classify(ap=None)
    stale = _classify(
        ap=_ap("正线站", "", {}), data_status="stale", online_status="stale"
    )
    assert unmatched.train.eligibility_status == "AP_UNMATCHED"
    assert stale.train.eligibility_status == "AC_STALE"
    assert "DEPOT" not in {
        unmatched.train.eligibility_status,
        stale.train.eligibility_status,
    }


def test_unmatched_ap_mac_stays_unknown_even_when_station_is_special() -> None:
    depot = _classify(
        ap=None,
        stations=[
            StationDTO(
                id="depot",
                name="云龙车辆段",
                node_type="depot",
                path_code="UNASSIGNED",
                participates_in_direction=False,
            )
        ],
        row_station="11云龙车辆段",
        peer_ap_name="bc5a-3457-bc00",
    )
    parking = _classify(
        ap=None,
        stations=[
            StationDTO(
                id="parking",
                name="停车场",
                node_type="parking_lot",
                path_code="UNASSIGNED",
                participates_in_direction=False,
            )
        ],
        row_station="停车场",
    )

    assert depot.train.eligibility_status == "AP_UNMATCHED"
    assert depot.train.location_class == "UNKNOWN"
    assert depot.train.location_match_level == "STATION_EXACT"
    assert depot.train.exclusion_reason == "当前 AP MAC 未匹配任何轨旁 AP 基础资料"
    assert depot.train.raw_peer_ap_name == "bc5a-3457-bc00"
    assert depot.train.resolved_ap_id == ""
    assert parking.train.eligibility_status == "AP_UNMATCHED"
    assert parking.train.location_match_level == "STATION_EXACT"


def test_station_level_match_does_not_replace_trackside_ap_identity() -> None:
    exact = _classify(
        ap=None,
        stations=[StationDTO(id="main", name="小洋江站")],
        row_station="01小洋江站",
    )
    alias = _classify(
        ap=None,
        stations=[
            StationDTO(
                id="alias",
                name="小洋江站",
                source_station_value="01设备别名站",
            )
        ],
        row_station="设备别名站",
    )
    unknown = _classify(
        ap=None,
        stations=[StationDTO(id="main", name="小洋江站")],
        row_station="未知位置",
    )

    assert exact.train.eligibility_status == "AP_UNMATCHED"
    assert exact.train.location_match_level == "STATION_EXACT"
    assert not exact.train.ping_eligible
    assert not exact.train.deep_collection_eligible
    assert alias.train.eligibility_status == "AP_UNMATCHED"
    assert alias.train.location_match_level == "STATION_ALIAS"
    assert not alias.train.ping_eligible
    assert not alias.train.deep_collection_eligible
    assert unknown.train.eligibility_status == "AP_UNMATCHED"
    assert unknown.train.location_match_level == "UNMATCHED"
    assert not unknown.train.ping_eligible


def test_ap_registry_matches_mac_but_ap_name_alias_is_not_identity() -> None:
    registry_ap = _ap("正线站", "", {}).model_copy(
        update={
            "mac": "",
            "radios": [
                MeshRadioDTO(
                    radio_id=1,
                    bssid="00:AA:BB:CC:DD:EE",
                )
            ],
        }
    )
    registry = _classify(
        ap=registry_ap,
        peer_ap_id="missing",
        peer_ap_name="unregistered-name",
        peer_ap_mac="00-AA-BB-CC-DD-EE",
    )
    alias_ap = _ap("正线站", "", {"ap_aliases": ["confirmed-alias"]})
    alias = _classify(
        ap=alias_ap,
        peer_ap_id="missing",
        peer_ap_name="confirmed-alias",
        peer_ap_mac="00:00:00:00:00:99",
    )

    assert registry.train.location_match_level == "AP_REGISTRY"
    assert registry.train.resolved_ap_id == "ap-1"
    assert alias.train.location_match_level == "UNMATCHED"
    assert alias.train.eligibility_status == "AP_UNMATCHED"
    assert alias.train.resolved_ap_name == ""


@pytest.mark.parametrize(
    ("location_class", "expected_status"),
    [
        ("DEPOT", "DEPOT"),
        ("PARKING_YARD", "PARKING_LOT"),
        ("STABLING", "STORAGE_TRACK"),
    ],
)
def test_depot_ping_switch_only_enables_ping_for_supported_special_locations(
    location_class: str,
    expected_status: str,
) -> None:
    ap = _ap("", "", {}).model_copy(
        update={
            "location_class": location_class,
            "participates_in_mainline": False,
            "location_class_source": "MANUAL_EXPLICIT",
        }
    )

    disabled = _classify(ap=ap, ping_depot_trains_enabled=False)
    enabled = _classify(ap=ap, ping_depot_trains_enabled=True)

    assert disabled.train.eligibility_status == expected_status
    assert not disabled.train.mainline_eligible
    assert not disabled.train.ping_eligible
    assert not disabled.train.deep_collection_eligible
    assert enabled.train.eligibility_status == expected_status
    assert not enabled.train.mainline_eligible
    assert enabled.train.ping_eligible
    assert enabled.train.ping_inclusion_reason == "已启用车辆段长 Ping"
    assert not enabled.train.deep_collection_eligible


def test_matched_trackside_ap_without_special_marker_defaults_to_mainline() -> None:
    result = _classify(ap=_ap("正线站", "", {}))

    assert result.train.location_class == "MAINLINE"
    assert result.train.mainline_eligible
    assert result.train.ping_eligible
    assert result.train.deep_collection_eligible


def test_endpoint_targets_are_independent_and_require_online_valid_management_ip() -> None:
    endpoints = GroundUnattendedEligibilityClassifier._endpoints(
        [
            VehicleMrDTO(
                id="mr-ct",
                name="01-CT",
                train_id="train-01",
                train_no="01",
                mr_position_code="CT",
                management_ip="192.0.2.10",
            ),
            VehicleMrDTO(
                id="mr-cw",
                name="01-CW",
                train_id="train-01",
                train_no="01",
                mr_position_code="CW",
                management_ip="bad-address",
            ),
        ],
        [
            AcMeshMrStatusDTO(
                mr_id="mr-ct",
                train_no="01",
                car_end="CT",
                mr_name="01-CT",
                management_ip="192.0.2.10",
                online_status="online",
            ),
            AcMeshMrStatusDTO(
                mr_id="mr-cw",
                train_no="01",
                car_end="CW",
                mr_name="01-CW",
                management_ip="bad-address",
                online_status="online",
            ),
        ],
    )

    assert endpoints[0].ping_target_eligible is True
    assert endpoints[1].ping_target_eligible is False
    assert endpoints[1].ping_exclusion_reason == "CW 管理 IP 无效"


def test_invalid_management_ip_returns_explicit_ping_exclusion_reason() -> None:
    result = _classify(
        ap=_ap("正线站", "", {}),
        management_ip="bad-address",
    )

    assert result.train.mainline_eligible is True
    assert result.train.ping_eligible is False
    assert result.train.ping_exclusion_reason == "CT 管理 IP 无效"
    assert result.train.deep_collection_eligible is False


def test_same_ap_stationary_keeps_ping_and_ap_change_restores_deep_collection() -> None:
    ap = _ap("正线站", "", {})
    tracker = StationaryTracker("id:ap-1", "2026-07-25T11:49:59+08:00")
    stationary = _classify(ap=ap, tracker=tracker)
    assert stationary.train.eligibility_status == "MAINLINE_STATIONARY"
    assert (
        stationary.train.ping_eligible and not stationary.train.deep_collection_eligible
    )
    changed = _classify(
        ap=ap.model_copy(update={"id": "ap-2", "name": "AP-2"}), tracker=tracker
    )
    assert changed.train.eligibility_status == "MAINLINE"
    assert changed.train.deep_collection_eligible
    assert changed.train.same_ap_duration_seconds == 0


def _classify(
    *,
    ap,
    stations=None,
    sections=None,
    tracker=StationaryTracker(),
    data_status="fresh",
    online_status="online",
    row_station="",
    row_section="",
    peer_ap_name="",
    peer_ap_mac="",
    peer_ap_id=None,
    ping_depot_trains_enabled=False,
    management_ip="192.0.2.10",
):
    classifier = GroundUnattendedEligibilityClassifier()
    row = AcMeshMrStatusDTO(
        mr_id="mr-ct",
        mr_device_id="mr-ct",
        train_no="01",
        car_end="CT",
        mr_name="01-CT",
        management_ip=management_ip,
        online_status=online_status,
        peer_ap_id=(
            peer_ap_id
            if peer_ap_id is not None
            else ap.id
            if ap
            else "missing"
        ),
        peer_ap_name=peer_ap_name or (ap.name if ap else "UNKNOWN-AP"),
        peer_ap_mac=peer_ap_mac or (ap.mac if ap else ""),
        station=row_station,
        section=row_section,
        data_status=data_status,
        last_seen_at=NOW.isoformat(),
    )
    result = classifier.classify_all(
        summary=RailTransitSummaryDTO(
            site_id="site-a", site_name="A", main_path_code="MAIN"
        ),
        stations=stations or [StationDTO(id="s1", name="正线站")],
        sections=sections or [],
        aps=[ap] if ap else [],
        mrs=[
            VehicleMrDTO(
                id="mr-ct",
                device_id=1,
                name="01-CT",
                train_id="train-01",
                train_no="01",
                mr_position_code="CT",
                management_ip=management_ip,
            )
        ],
        ac_rows=[row],
        trackers={"train-01": tracker},
        stationary_exclusion_minutes=10,
        now=NOW,
        ping_depot_trains_enabled=ping_depot_trains_enabled,
    )
    return result[0]


def _ap(station: str, section: str, metadata: dict) -> TracksideApDTO:
    return TracksideApDTO(
        id="ap-1",
        site_id="site-a",
        name="AP-1",
        mac="00:11:22:33:44:55",
        station=station,
        section=section,
        mileage=MileageDTO(),
        base_metadata=metadata,
    )
