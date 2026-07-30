from __future__ import annotations

from types import SimpleNamespace

from netconsole.services.rail_transit.mesh_ap_location_service import (
    MeshApLocation,
    MeshApLocationService,
    MeshApLocationSnapshot,
)


def test_location_snapshot_prefers_mac_before_duplicate_name() -> None:
    snapshot = MeshApLocationSnapshot(
        (
            MeshApLocation(name="AP-01", mac="0000-0000-0010", station="车站A"),
            MeshApLocation(name="AP-01", mac="0000-0000-0020", station="车站B"),
        )
    )

    location = snapshot.resolve({"peer_ap_mac": "000000000010", "peer_ap_name": "AP-01"})

    assert location.station == "车站A"


def test_location_snapshot_does_not_guess_when_name_is_duplicated() -> None:
    snapshot = MeshApLocationSnapshot(
        (
            MeshApLocation(name="AP-01", mac="0000-0000-0010", station="车站A"),
            MeshApLocation(name="AP-01", mac="0000-0000-0020", station="车站B"),
        )
    )

    assert snapshot.resolve({"peer_ap_name": "AP-01"}) == MeshApLocation(name="AP-01")


def test_location_snapshot_uses_active_peer_mac_without_overriding_ap_mac_priority() -> None:
    snapshot = MeshApLocationSnapshot(
        (
            MeshApLocation(name="AP-01", mac="0000-0000-0010", station="车站A"),
            MeshApLocation(name="AP-02", mac="0000-0000-0020", station="车站B"),
        )
    )

    active_only = snapshot.resolve({"active_peer_mac": "000000000010"})
    explicit_ap = snapshot.resolve(
        {"peer_ap_mac": "000000000020", "active_peer_mac": "000000000010"}
    )

    assert active_only.station == "车站A"
    assert explicit_ap.station == "车站B"


def test_location_snapshot_falls_back_to_name_and_preserves_section_only() -> None:
    snapshot = MeshApLocationSnapshot((MeshApLocation(name="AP-02", section="区间A-B"),))

    named = snapshot.resolve({"peer_ap_name": "ap-02"})
    unresolved = MeshApLocationSnapshot().resolve(
        {"peer_ap_name": "AP-03", "peer_section": "区间B-C"}
    )

    assert named.section == "区间A-B"
    assert unresolved.station == ""
    assert unresolved.section == "区间B-C"
    assert MeshApLocationSnapshot().resolve({}) == MeshApLocation()


def test_location_snapshot_serialization_round_trip_is_worker_safe() -> None:
    source = MeshApLocationSnapshot.from_base_data_items(
        (
            SimpleNamespace(
                name="AP-04",
                mac="0000-0000-0040",
                station="车站D",
                section="",
                mileage=SimpleNamespace(raw="K12+300"),
                line_side="上行",
            ),
        )
    )

    serialized = source.to_serializable()
    restored = MeshApLocationSnapshot.from_serializable(serialized)

    assert serialized == [
        {
            "name": "AP-04",
            "point_code": "",
            "mac": "0000-0000-0040",
            "station": "车站D",
            "section": "",
            "section_start_station": "",
            "section_end_station": "",
            "mileage": "K12+300",
            "line_side": "上行",
            "direction": "",
        }
    ]
    assert restored.resolve({"peer_ap_mac": "000000000040"}) == MeshApLocation(
        name="AP-04",
        mac="0000-0000-0040",
        station="车站D",
        mileage="K12+300",
        line_side="上行",
    )


def test_location_snapshot_uses_point_code_when_base_ap_name_is_empty() -> None:
    snapshot = MeshApLocationSnapshot.from_base_data_items(
        (
            SimpleNamespace(
                name="",
                point_code="AP0127",
                mac="1c94-6876-8ee0",
                station="高桥西",
                section="高桥西-高桥",
                section_start_station="高桥西",
                section_end_station="高桥",
                mileage=SimpleNamespace(raw="ZDK12+300"),
                line_side="左线",
                direction="下行",
            ),
        )
    )

    location = snapshot.resolve({"peer_ap_mac": "1c9468768ee0"})
    assert location.name == "AP0127"
    assert location.point_code == "AP0127"
    assert location.station == "高桥西"
    assert location.section == "高桥西-高桥"
    assert location.section_start_station == "高桥西"
    assert location.section_end_station == "高桥"
    assert location.mileage == "ZDK12+300"
    assert location.direction == "下行"


def test_location_service_prefers_the_unpaged_location_source() -> None:
    item = SimpleNamespace(
        name="AP-05",
        mac="0000-0000-0050",
        station="车站E",
        section="",
        mileage=SimpleNamespace(raw=""),
        line_side="下行",
    )

    class Query:
        list_ap_location_items = staticmethod(lambda _site_id: [item])
        list_aps = staticmethod(lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError))

    snapshot = MeshApLocationService(Query()).snapshot("demo")  # type: ignore[arg-type]

    assert snapshot.resolve({"peer_ap_mac": "000000000050"}).station == "车站E"
