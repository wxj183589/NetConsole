from __future__ import annotations

from types import SimpleNamespace

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
    assert no_active.ap_transition_display == "无主链路 → 横溪站-AP03"
    assert lost_active.ap_transition_display == "横溪站-AP02 → 无主链路"
    assert lost_active.resolution_status == "NO_ACTIVE_LINK"


def _match(
    query_mac: str,
    *,
    entity_id: str,
    name: str,
    ap_mac: str = "0011-2233-4455",
    revision: int = 1,
) -> ApIdentityMatch:
    return ApIdentityMatch(
        status="matched",
        identity_revision=revision,
        query_mac=query_mac,
        matched_entity_id=entity_id,
        effective_ap_name=name,
        effective_ap_mac=ap_mac,
        station="横溪站",
        section="横溪站-站点B",
        matched_alias_type="ac_bssid",
        matched_source="ac_runtime",
        match_rule="actual_bssid_exact",
        match_confidence=100,
        radio_id=1,
    )
