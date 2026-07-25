from __future__ import annotations

from datetime import datetime

import pytest

from netconsole.models.api.ac_mesh_link import AcMeshMrStatusDTO
from netconsole.models.api.rail_transit_base_data import (
    MileageDTO,
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
):
    classifier = GroundUnattendedEligibilityClassifier()
    row = AcMeshMrStatusDTO(
        mr_id="mr-ct",
        mr_device_id="mr-ct",
        train_no="01",
        car_end="CT",
        mr_name="01-CT",
        management_ip="192.0.2.10",
        online_status=online_status,
        peer_ap_id=ap.id if ap else "missing",
        peer_ap_name=ap.name if ap else "UNKNOWN-AP",
        peer_ap_mac=ap.mac if ap else "",
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
                management_ip="192.0.2.10",
            )
        ],
        ac_rows=[row],
        trackers={"train-01": tracker},
        stationary_exclusion_minutes=10,
        now=NOW,
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
