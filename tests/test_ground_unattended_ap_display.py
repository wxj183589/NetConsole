from __future__ import annotations

from types import SimpleNamespace

import pytest

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.ap_identity_index import ApIdentityMatch
from netconsole.repositories.ac_repository import AcRepository
from netconsole.repositories.ground_unattended_repository import (
    GroundUnattendedRepository,
)
from netconsole.services.ap_identity import ApIdentityQueryService, normalize_mac_key
from netconsole.services.ground_unattended.ap_resolver import (
    GroundApDisplayResolver,
)
from netconsole.services.ground_unattended.application_service import (
    GroundUnattendedApplicationService,
)


class FakeIdentityQuery:
    def __init__(
        self,
        matches: dict[str, ApIdentityMatch] | None = None,
        *,
        revision: int = 1,
    ) -> None:
        self.matches = matches or {}
        self.revision = revision
        self.batch_calls: list[tuple[tuple[str, ...], str | None]] = []
        self.state_calls = 0

    def resolve_peer_macs(self, macs, *, ap_role=None):
        keys = tuple(key for mac in macs if (key := normalize_mac_key(mac)) is not None)
        self.batch_calls.append((keys, ap_role))
        return {
            key: self.matches.get(key)
            or ApIdentityMatch(
                status="unresolved",
                identity_revision=self.revision,
                query_mac=key,
                unresolved_reason="exact_alias_not_found",
            )
            for key in keys
        }

    def resolve_current_ap_macs(self, macs, *, ap_role=None):
        return self.resolve_peer_macs(macs, ap_role=ap_role)

    def index_state(self) -> dict[str, object]:
        self.state_calls += 1
        return {"revision": self.revision}


def test_ap_display_resolver_resolves_registered_current_ap_aliases_and_identity_fields() -> None:
    radio_key = "101122334455"
    query = FakeIdentityQuery(
        {
            radio_key: _match(
                radio_key,
                entity_id="entity-1",
                name="站点A-AP01",
                ap_mac="0011-2233-4455",
                revision=7,
            )
        },
        revision=7,
    )
    resolver = GroundApDisplayResolver(query)

    physical = resolver.resolve(mac="0011-2233-4455")
    radio = resolver.resolve(mac="1011-2233-4455")

    assert physical["resolution_status"] == "UNRESOLVED"
    assert physical["peer_ap_id"] == ""
    assert radio["resolution_status"] == "RADIO_BSSID"
    assert radio["peer_ap_id"] == "entity-1"
    assert radio["peer_ap_name"] == "站点A-AP01"
    assert radio["peer_ap_mac"] == "00:11:22:33:44:55"
    assert radio["identity_entity_id"] == "entity-1"
    assert radio["identity_revision"] == 7
    assert radio["identity_status"] == "matched"
    assert radio["identity_source"] == "ac_runtime"


def test_ap_display_resolver_uses_real_base_identity_for_yard_radio_alias(
    tmp_path,
) -> None:
    database = Database(tmp_path / "devices.db")
    database.initialize()
    repository = AcRepository(database)
    repository.upsert_ap_extension_point(
        {
            "ap_name": "车辆段-AP01",
            "ap_point_code": "YARD-AP01",
            "ap_vendor": "H3C",
            "ap_mac_display": "74ad-cb9d-3320",
            "station_name": "车辆段",
            "belong_type": "yard",
        }
    )
    query = ApIdentityQueryService(database)
    query.rebuild_index("ground_yard_base_data")
    resolver = GroundApDisplayResolver(query)

    radio = resolver.resolve(mac="74ad-cb9d-332f")
    physical = resolver.resolve(mac="74ad-cb9d-3320")

    assert radio["resolution_status"] == "RADIO_BSSID"
    assert radio["peer_ap_name"] == "车辆段-AP01"
    assert radio["peer_ap_mac"] == "74:ad:cb:9d:33:20"
    assert radio["station"] == "车辆段"
    assert radio["identity_source"] == "base_data"
    assert physical["resolution_status"] == "PHYSICAL_AP"
    assert physical["peer_ap_name"] == "车辆段-AP01"
    assert physical["peer_ap_mac"] == "74:ad:cb:9d:33:20"


def test_ap_display_resolver_batches_distinct_current_and_previous_peers() -> None:
    first = "101122334455"
    second = "102233445566"
    query = FakeIdentityQuery(
        {
            first: _match(first, entity_id="entity-1", name="AP-01"),
            second: _match(second, entity_id="entity-2", name="AP-02"),
        }
    )
    resolver = GroundApDisplayResolver(query)
    parsed_rows = [
        {
            "peer_mac": "1011-2233-4455",
            "previous_peer_mac": "1022-3344-5566",
            "details": {},
        },
        {"peer_mac": "1011-2233-4455", "details": {}},
    ]

    resolver.preload_parsed(parsed_rows)
    enriched = resolver.enrich_parsed(parsed_rows[0])

    assert query.batch_calls == [(("101122334455", "102233445566"), "trackside")]
    assert enriched["peer_name"] == "AP-01"
    assert enriched["previous_peer_name"] == "AP-02"
    assert enriched["details"]["identity_entity_id"] == "entity-1"
    assert enriched["details"]["previous_identity_entity_id"] == "entity-2"


def test_ap_display_resolver_keeps_ambiguous_result_unbound() -> None:
    key = "101122334455"
    query = FakeIdentityQuery(
        {
            key: ApIdentityMatch(
                status="ambiguous",
                identity_revision=3,
                query_mac=key,
                candidates=({"entity_id": "a"}, {"entity_id": "b"}),
                unresolved_reason="duplicate_exact_alias",
            )
        },
        revision=3,
    )

    result = GroundApDisplayResolver(query).resolve(
        name="原始 Peer",
        mac="1011-2233-4455",
    )

    assert result["resolution_status"] == "AMBIGUOUS"
    assert result["peer_ap_id"] == ""
    assert result["peer_ap_name"] == "原始 Peer"
    assert result["identity_status"] == "ambiguous"
    assert result["identity_reason"] == "duplicate_exact_alias"


def test_ap_display_resolver_invalidates_cache_only_when_revision_changes() -> None:
    now = [0.0]
    key = "101122334455"
    query = FakeIdentityQuery({key: _match(key, entity_id="entity-1", name="AP-OLD")})
    resolver = GroundApDisplayResolver(
        query,
        revision_check_interval_seconds=30,
        monotonic_provider=lambda: now[0],
    )

    assert resolver.resolve(mac=key)["peer_ap_name"] == "AP-OLD"
    assert resolver.resolve(mac=key)["peer_ap_name"] == "AP-OLD"
    resolver.refresh_revision(force=True)
    assert resolver.resolve(mac=key)["peer_ap_name"] == "AP-OLD"
    assert len(query.batch_calls) == 1

    query.revision = 2
    query.matches[key] = _match(
        key,
        entity_id="entity-1",
        name="AP-NEW",
        revision=2,
    )
    now[0] = 31.0

    assert resolver.resolve(mac=key)["peer_ap_name"] == "AP-NEW"
    assert len(query.batch_calls) == 2


def test_application_service_uses_injected_identity_query_without_base_alias_cache(
    tmp_path,
) -> None:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    repository = GroundUnattendedRepository(
        paths.ground_unattended_db_path("site-a"),
        site_id="site-a",
    )
    query = FakeIdentityQuery()
    service = GroundUnattendedApplicationService(
        paths,
        site_id="site-a",
        repository=repository,
        supervisor=SimpleNamespace(),
        base_query=SimpleNamespace(
            list_ap_location_items=lambda _site_id: (_ for _ in ()).throw(
                AssertionError("Ground display must not reload base AP rows")
            )
        ),
        ap_identity_query_service=query,
    )

    assert service._ap_display_resolver() is service._ap_display_resolver()
    assert service._ap_display_resolver().query_service is query


def test_ping_switch_projection_resolves_radio_aliases_in_one_identity_batch(
    tmp_path,
) -> None:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    repository = GroundUnattendedRepository(
        paths.ground_unattended_db_path("site-a"), site_id="site-a"
    )
    query = FakeIdentityQuery(
        {
            "101122334455": _match(
                "101122334455",
                entity_id="old-ap",
                name="站点A-AP01",
                ap_mac="0011-2233-4455",
                station="站点A",
                section="站点A-站点B",
                revision=9,
            ),
            "102233445566": _match(
                "102233445566",
                entity_id="new-ap",
                name="站点B-AP01",
                ap_mac="0022-3344-5566",
                station="站点B",
                section="站点B-站点C",
                revision=9,
            ),
        },
        revision=9,
    )
    service = GroundUnattendedApplicationService(
        paths,
        site_id="site-a",
        repository=repository,
        supervisor=SimpleNamespace(),
        ap_identity_query_service=query,
    )

    projected = service._project_ping_transitions(
        [
            {
                "ts": "2026-08-07T20:29:21.840+08:00",
                "event_time": "2026-08-07T20:29:21.840+08:00",
                "old_ap_raw": "1011-2233-4455",
                "new_ap_raw": "1022-3344-5566",
                "old_ap_mac": "",
                "new_ap_mac": "",
            }
        ]
    )

    assert query.batch_calls == [
        (("102233445566", "101122334455"), "trackside")
    ]
    assert projected[0]["old_ap_id"] == "old-ap"
    assert projected[0]["new_ap_id"] == "new-ap"
    assert projected[0]["old_ap_mac"] == "00:11:22:33:44:55"
    assert projected[0]["new_ap_mac"] == "00:22:33:44:55:66"
    assert projected[0]["old_station"] == "站点A"
    assert projected[0]["new_station"] == "站点B"
    assert projected[0]["old_ap_identity_status"] == "MATCHED"
    assert projected[0]["new_ap_identity_status"] == "MATCHED"
    assert projected[0]["identity_status"] == "BOTH_MATCHED"
    assert projected[0]["old_match_source"] == "ac_runtime"
    assert projected[0]["new_match_source"] == "ac_runtime"
    assert projected[0]["old_match_rule"] == "actual_bssid_exact"
    assert projected[0]["new_match_rule"] == "actual_bssid_exact"
    assert projected[0]["identity_revision"] == 9


@pytest.mark.parametrize(
    ("old_match", "new_match", "old_raw", "new_raw", "expected"),
    [
        ("matched", "unresolved", "1011-2233-4455", "1022-3344-5566", "OLD_ONLY_MATCHED"),
        ("unresolved", "matched", "1011-2233-4455", "1022-3344-5566", "NEW_ONLY_MATCHED"),
        ("unresolved", "unresolved", "1011-2233-4455", "1022-3344-5566", "BOTH_NOT_FOUND"),
        ("ambiguous", "matched", "1011-2233-4455", "1022-3344-5566", "OLD_CONFLICT"),
        ("matched", "ambiguous", "1011-2233-4455", "1022-3344-5566", "NEW_CONFLICT"),
        ("ambiguous", "ambiguous", "1011-2233-4455", "1022-3344-5566", "BOTH_CONFLICT"),
        ("matched", "matched", "bad-old-mac", "1022-3344-5566", "INVALID_MAC"),
        ("matched", "matched", "", "1022-3344-5566", "NO_AP_ENDPOINT"),
        ("matched", "matched", "1011-2233-4455", "", "NO_AP_ENDPOINT"),
    ],
)
def test_switch_projector_reports_explicit_dual_endpoint_statuses(
    old_match: str,
    new_match: str,
    old_raw: str,
    new_raw: str,
    expected: str,
) -> None:
    matches: dict[str, ApIdentityMatch] = {}
    for key, status, entity_id, name in (
        ("101122334455", old_match, "old-ap", "AP-A"),
        ("102233445566", new_match, "new-ap", "AP-B"),
    ):
        if status == "matched":
            matches[key] = _match(
                key,
                entity_id=entity_id,
                name=name,
                revision=11,
            )
        elif status == "ambiguous":
            matches[key] = ApIdentityMatch(
                status="ambiguous",
                identity_revision=11,
                query_mac=key,
                candidates=({"entity_id": "a"}, {"entity_id": "b"}),
                unresolved_reason="duplicate_exact_alias",
            )
    query = FakeIdentityQuery(matches, revision=11)
    resolver = GroundApDisplayResolver(query)
    parsed = {
        "event_type": "MESH_ACTIVELINK_SWITCH",
        "previous_peer_mac": old_raw,
        "peer_mac": new_raw,
        "details": {
            "old_peer_mac": old_raw,
            "new_peer_mac": new_raw,
        },
    }

    resolver.preload_parsed([parsed])
    projected = resolver.project_switch(parsed)

    assert projected["identity_status"] == expected
    assert projected["identity_revision"] == 11
    assert projected["old_ap_raw"] == old_raw
    assert projected["new_ap_raw"] == new_raw
    assert len(query.batch_calls) <= 1
    if expected == "OLD_ONLY_MATCHED":
        assert projected["old_ap_identity_status"] == "MATCHED"
        assert projected["new_ap_identity_status"] == "NOT_FOUND"
        assert projected["old_ap_name"] == "AP-A"
        assert projected["new_ap_name"] == ""
    elif expected == "NEW_ONLY_MATCHED":
        assert projected["old_ap_identity_status"] == "NOT_FOUND"
        assert projected["new_ap_identity_status"] == "MATCHED"
        assert projected["old_ap_name"] == ""
        assert projected["new_ap_name"] == "AP-B"
    elif expected == "OLD_CONFLICT":
        assert projected["old_ap_identity_status"] == "CONFLICT"
        assert projected["old_ap_name"] == ""
    elif expected == "NEW_CONFLICT":
        assert projected["new_ap_identity_status"] == "CONFLICT"
        assert projected["new_ap_name"] == ""
    elif expected == "INVALID_MAC":
        assert projected["old_ap_identity_status"] == "INVALID_MAC"
    elif expected == "NO_AP_ENDPOINT":
        assert "NO_AP_ENDPOINT" in {
            projected["old_ap_identity_status"],
            projected["new_ap_identity_status"],
        }


def test_switch_projector_normalizes_supported_mac_formats_in_one_batch() -> None:
    key = "bc5a34575d00"
    query = FakeIdentityQuery(
        {key: _match(key, entity_id="ap-a", name="AP-A", revision=13)},
        revision=13,
    )
    rows = [
        {
            "event_type": "MESH_ACTIVELINK_SWITCH",
            "previous_peer_mac": value,
            "peer_mac": "BC5A34575D00",
            "details": {},
        }
        for value in (
            "bc:5a:34:57:5d:00",
            "bc5a-3457-5d00",
            "bc5a.3457.5d00",
            "bc5a34575d00",
        )
    ]
    resolver = GroundApDisplayResolver(query)

    resolver.preload_parsed(rows)
    projected = [resolver.project_switch(row) for row in rows]

    assert query.batch_calls == [((key,), "trackside")]
    assert {item["identity_status"] for item in projected} == {"BOTH_MATCHED"}
    assert {item["old_ap_id"] for item in projected} == {"ap-a"}
    assert {item["new_ap_id"] for item in projected} == {"ap-a"}


def test_timeline_enriches_link_events_and_no_active_link_switch(tmp_path) -> None:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    repository = GroundUnattendedRepository(
        paths.ground_unattended_db_path("site-a"), site_id="site-a"
    )
    repository.create_or_get_run(
        run_id="run-timeline",
        run_date="2026-07-28",
        scheduled_start_at="2026-07-28T07:00:00+08:00",
        scheduled_end_at="2026-07-28T23:00:00+08:00",
    )
    repository.update_run("run-timeline", state="RUNNING")
    events = [
        (
            "mesh_linkup",
            "WMESH 链路建立",
            {"peer_mac": "1011-2233-4455", "rssi": -51},
        ),
        (
            "mesh_linkdown",
            "WMESH 链路断开",
            {
                "peer_mac": "1011-2233-4455",
                "rssi": -72,
                "reason_code": "WEAK_RSSI_LOCAL",
                "reason_label": "弱信号（本端）",
            },
        ),
        (
            "mesh_activelink_switch",
            "WMESH 主链路切换",
            {
                "old_peer_mac": "1011-2233-4455",
                "new_peer_mac": "1022-3344-5566",
            },
        ),
        (
            "mesh_activelink_switch",
            "WMESH 主链路切换",
            {
                "old_active_link_missing": True,
                "new_peer_mac": "1022-3344-5566",
            },
        ),
        (
            "mesh_activelink_switch",
            "WMESH 主链路切换",
            {"old_peer_mac": "1011-2233-4455", "new_peer_mac": ""},
        ),
    ]
    for index, (event_type, title, details) in enumerate(events):
        repository.add_event(
            run_id="run-timeline",
            event_type=event_type,
            title=title,
            details=details,
            ts=f"2026-07-28T08:00:0{index}+08:00",
        )
    query = FakeIdentityQuery(
        {
            "101122334455": _match(
                "101122334455",
                entity_id="entity-1",
                name="横溪站-AP02",
            ),
            "102233445566": _match(
                "102233445566",
                entity_id="entity-2",
                name="横溪站-AP03",
            ),
        }
    )
    service = GroundUnattendedApplicationService(
        paths,
        site_id="site-a",
        repository=repository,
        supervisor=SimpleNamespace(
            fleet_ping=SimpleNamespace(target_summaries=lambda: [])
        ),
        ap_identity_query_service=query,
    )

    rows = {item.event_id: item for item in service.timeline("site-a").items}
    linkup = rows[1]
    linkdown = rows[2]
    switch = rows[3]
    no_active = rows[4]
    lost_active = rows[5]

    assert query.batch_calls == [(("101122334455", "102233445566"), "trackside")]
    assert linkup.resolved_ap_name == "横溪站-AP02"
    assert "RSSI -51 dBm" in linkup.message
    assert linkdown.resolved_ap_name == "横溪站-AP02"
    assert "弱信号（本端）" in linkdown.message
    assert switch.ap_transition_display == "横溪站-AP02 → 横溪站-AP03"
    assert "1011-2233-4455 → 1022-3344-5566" in switch.message
    assert "横溪站-AP02 → 横溪站-AP03" in switch.message
    assert switch.resolution_status == "BOTH_MATCHED"
    assert switch.identity_status == "BOTH_MATCHED"
    assert switch.old_ap_identity_status == "MATCHED"
    assert switch.new_ap_identity_status == "MATCHED"
    assert switch.old_ap_raw == "1011-2233-4455"
    assert switch.new_ap_raw == "1022-3344-5566"
    assert no_active.ap_transition_display == "无主链路 → 横溪站-AP03"
    assert lost_active.ap_transition_display == "横溪站-AP02 → 无主链路"
    assert no_active.resolution_status == "NO_AP_ENDPOINT"
    assert lost_active.resolution_status == "NO_AP_ENDPOINT"

    ping_switch = service._project_ping_transitions(
        [
            {
                "ts": switch.ts,
                "event_time": switch.ts,
                "old_ap_raw": switch.old_ap_raw,
                "new_ap_raw": switch.new_ap_raw,
            }
        ]
    )[0]
    assert query.batch_calls == [
        (("101122334455", "102233445566"), "trackside"),
        (("102233445566", "101122334455"), "trackside"),
    ]
    assert ping_switch["identity_status"] == switch.identity_status
    assert ping_switch["old_ap_id"] == switch.previous_peer_ap_id
    assert ping_switch["new_ap_id"] == switch.peer_ap_id
    assert ping_switch["old_station"] == switch.previous_station
    assert ping_switch["new_station"] == switch.station
    assert ping_switch["identity_revision"] == switch.identity_revision


def _match(
    query_mac: str,
    *,
    entity_id: str,
    name: str,
    ap_mac: str = "0011-2233-4455",
    station: str = "横溪站",
    section: str = "横溪站-站点B",
    revision: int = 1,
) -> ApIdentityMatch:
    return ApIdentityMatch(
        status="matched",
        identity_revision=revision,
        query_mac=query_mac,
        matched_entity_id=entity_id,
        effective_ap_name=name,
        effective_ap_mac=ap_mac,
        station=station,
        section=section,
        matched_alias_type="ac_bssid",
        matched_source="ac_runtime",
        match_rule="actual_bssid_exact",
        match_confidence=100,
        radio_id=1,
    )
