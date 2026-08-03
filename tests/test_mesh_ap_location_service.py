from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.repositories.ac_repository import AcRepository
from netconsole.services.ap_identity import ApIdentityQueryService
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

    assert snapshot.resolve({"peer_ap_name": "AP-01"}) == MeshApLocation(
        name="AP-01",
        identity_status="unresolved",
        identity_reason="缺少规范 AP MAC",
    )


def test_location_snapshot_does_not_treat_active_peer_mac_as_physical_ap_mac() -> None:
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

    assert active_only == MeshApLocation(
        identity_status="unresolved",
        identity_reason="缺少规范 AP MAC",
    )
    assert explicit_ap.station == "车站B"


def test_location_snapshot_rejects_name_only_and_preserves_observed_section() -> None:
    snapshot = MeshApLocationSnapshot((MeshApLocation(name="AP-02", section="区间A-B"),))

    named = snapshot.resolve({"peer_ap_name": "ap-02"})
    unresolved = MeshApLocationSnapshot().resolve(
        {"peer_ap_name": "AP-03", "peer_section": "区间B-C"}
    )

    assert named == MeshApLocation(
        name="ap-02",
        identity_status="unresolved",
        identity_reason="缺少规范 AP MAC",
    )
    assert unresolved.station == ""
    assert unresolved.section == "区间B-C"
    assert MeshApLocationSnapshot().resolve({}) == MeshApLocation(
        identity_status="unresolved",
        identity_reason="缺少规范 AP MAC",
    )


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
            "identity_status": "matched",
            "identity_source": "BASE_DATA_AP_MAC",
            "identity_reason": "",
        }
    ]
    assert restored.resolve({"peer_ap_mac": "000000000040"}) == MeshApLocation(
        name="AP-04",
        mac="0000-0000-0040",
        station="车站D",
        mileage="K12+300",
        line_side="上行",
        identity_status="matched",
        identity_source="BASE_DATA_AP_MAC",
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


def test_location_service_keeps_complete_base_location_and_supplements_identity_only_aps(
    tmp_path: Path,
) -> None:
    paths = PathResolver(tmp_path)
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    repository = AcRepository(database)
    repository.upsert_ap_extension_point(
        {
            "ap_name": "AP0208",
            "ap_point_code": "AP0208",
            "ap_mac_display": "4873-97cc-e0e0",
            "station_name": "基础资料站",
        }
    )
    repository.replace_fit_ap_resources(
        "ac-1",
        [
            {
                "ap_uuid": "ap-0208",
                "ap_name": "AP0208",
                "ap_mac": "4873-97cc-e080",
                "site": "AC运行站",
            }
        ],
    )
    ApIdentityQueryService(database).rebuild_index("test_sources_saved")

    class Query:
        def __init__(self, resolver: PathResolver) -> None:
            self.paths = resolver

        @staticmethod
        def list_ap_location_items(_site_id: str):
            return [
                SimpleNamespace(
                    name="AP0208",
                    point_code="AP0208",
                    mac="4873-97cc-e0e0",
                    station="基础资料站",
                    section="基础资料区间",
                    section_start_station="起点站",
                    section_end_station="终点站",
                    mileage=SimpleNamespace(raw="K12+300"),
                    line_side="",
                    direction="上行",
                )
            ]

    snapshot = MeshApLocationService(Query(paths)).snapshot("demo")  # type: ignore[arg-type]
    location = snapshot.resolve({"peer_ap_mac": "4873-97cc-e080"})

    assert location.name == "AP0208"
    assert location.mac == "4873-97cc-e080"
    assert location.station == "AC运行站"
    assert location.identity_source == "ac_runtime"
    assert location.identity_reason == ""
    base_location = snapshot.resolve({"peer_ap_mac": "4873-97cc-e0e0"})
    assert base_location.station == "基础资料站"
    assert base_location.section == "基础资料区间"
    assert base_location.section_start_station == "起点站"
    assert base_location.section_end_station == "终点站"
    assert base_location.mileage == "K12+300"
    assert base_location.line_side == "上行"
    assert base_location.direction == "上行"
    assert base_location.identity_source == "BASE_DATA_AP_MAC"
