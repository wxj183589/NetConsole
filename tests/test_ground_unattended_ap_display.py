from __future__ import annotations

from types import SimpleNamespace

from netconsole.core.paths import PathResolver
from netconsole.repositories.ground_unattended_repository import (
    GroundUnattendedRepository,
)
from netconsole.services.ground_unattended.ap_resolver import (
    GroundApDisplayResolver,
)
from netconsole.services.ground_unattended.application_service import (
    GroundUnattendedApplicationService,
)


def test_ap_display_resolver_keeps_peer_radio_and_alias_semantics_distinct() -> None:
    ap = _ap(
        "ap-1",
        "站点A-AP01",
        "0011-2233-4455",
        bssid="1011-2233-4455",
        aliases=["旧名-AP01"],
    )
    resolver = GroundApDisplayResolver([ap])

    peer = resolver.resolve(mac="0011-2233-4455")
    radio = resolver.resolve(mac="1011-2233-4455")
    alias = resolver.resolve(name="旧名-AP01")
    enriched = resolver.enrich_parsed(
        {
            "peer_mac": "1011-2233-4455",
            "details": {"peer_radio_mac": "1011-2233-4455"},
        }
    )

    assert peer["resolution_status"] == "PEER_MAC_EXACT"
    assert peer["peer_ap_id"] == "ap-1"
    assert radio["resolution_status"] == "RADIO_BSSID"
    assert alias["resolution_status"] == "UNRESOLVED"
    assert enriched["peer_mac"] == "10:11:22:33:44:55"
    assert enriched["details"]["peer_ap_mac"] == "00:11:22:33:44:55"
    assert enriched["details"]["peer_radio_mac"] == "10:11:22:33:44:55"


def test_ap_display_resolver_rejects_ambiguous_candidates() -> None:
    resolver = GroundApDisplayResolver(
        [
            _ap("ap-1", "重复 AP", "0011-2233-4455"),
            _ap("ap-2", "重复 AP", "0011-2233-4455"),
        ]
    )

    result = resolver.resolve(name="重复 AP", mac="0011-2233-4455")

    assert result["resolution_status"] == "AMBIGUOUS"
    assert result["peer_ap_id"] == ""
    assert result["peer_ap_mac"] == ""


def test_ap_display_resolver_uses_ac_detail_h3c_radio_evidence() -> None:
    resolver = GroundApDisplayResolver(
        resources=[
            _ac_detail(
                "ap-1",
                "0011-2233-4450",
                trackside_name="Z01-01",
            )
        ]
    )

    result = resolver.resolve(mac="0011-2233-445f")

    assert result["peer_ap_id"] == ""
    assert result["peer_ap_name"] == "00:11:22:33:44:5f"
    assert result["peer_ap_mac"] == ""
    assert result["resolution_status"] == "UNRESOLVED"
    assert result["resolution_rule"] == ""
    assert result["resolution_confidence"] == ""


def test_ap_display_resolver_marks_mac_configured_name_source() -> None:
    resolver = GroundApDisplayResolver(
        resources=[_ac_detail("ap-1", "0011-2233-4450")]
    )

    result = resolver.resolve(mac="0011-2233-445f")

    assert result["peer_ap_name"] == "00:11:22:33:44:5f"
    assert result["display_name_source"] == "RAW_OBSERVATION"
    assert result["resolution_status"] == "UNRESOLVED"


def test_ap_display_resolver_rejects_ambiguous_h3c_radio_candidates() -> None:
    resolver = GroundApDisplayResolver(
        resources=[
            _ac_detail("ap-1", "0011-2233-4450"),
            _ac_detail("ap-2", "0011-2233-4451"),
        ]
    )

    result = resolver.resolve(mac="0011-2233-445f")

    assert result["resolution_status"] == "UNRESOLVED"
    assert result["peer_ap_id"] == ""


def test_ambiguous_base_radio_does_not_fall_through_to_h3c_derivation() -> None:
    resolver = GroundApDisplayResolver(
        [
            _ap(
                "base-ap-1",
                "重复 Radio 1",
                "1011-2233-4451",
                bssid="0011-2233-445f",
            ),
            _ap(
                "base-ap-2",
                "重复 Radio 2",
                "2011-2233-4451",
                bssid="0011-2233-445f",
            ),
        ],
        resources=[
            _ac_detail(
                "resource-ap",
                "0011-2233-4450",
                trackside_name="派生结果",
            )
        ],
    )

    result = resolver.resolve(mac="0011-2233-445f")

    assert result["resolution_status"] == "AMBIGUOUS"
    assert result["peer_ap_id"] == ""
    assert result["peer_ap_name"] == "00:11:22:33:44:5f"


def test_application_service_caches_ap_display_sources(tmp_path) -> None:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    repository = GroundUnattendedRepository(
        paths.ground_unattended_db_path("site-a"), site_id="site-a"
    )
    calls = {"base": 0, "ac": 0}

    def list_base(_site_id: str) -> list[SimpleNamespace]:
        calls["base"] += 1
        return []

    def list_ac(_site_id: str) -> list[SimpleNamespace]:
        calls["ac"] += 1
        return [_ac_detail("ap-1", "0011-2233-4450")]

    service = GroundUnattendedApplicationService(
        paths,
        site_id="site-a",
        repository=repository,
        supervisor=SimpleNamespace(
            fleet_ping=SimpleNamespace(target_summaries=lambda: [])
        ),
        base_query=SimpleNamespace(
            list_ap_location_items=list_base,
            ac_query=SimpleNamespace(list_all_ap_details=list_ac),
        ),
    )

    first = service._ap_display_resolver()
    thread = service._ap_display_refresh_thread
    assert thread is not None
    thread.join(timeout=2)
    second = service._ap_display_resolver()

    assert first is not second
    assert calls == {"base": 1, "ac": 1}
    service._ap_display_cache_loaded_at -= 31
    service._ap_display_resolver()
    thread = service._ap_display_refresh_thread
    assert thread is not None
    thread.join(timeout=2)
    assert calls == {"base": 2, "ac": 2}


def test_application_service_keeps_old_ap_cache_when_background_refresh_fails(
    tmp_path,
) -> None:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    repository = GroundUnattendedRepository(
        paths.ground_unattended_db_path("site-a"), site_id="site-a"
    )
    fail = False

    def list_ac(_site_id: str) -> list[SimpleNamespace]:
        if fail:
            raise RuntimeError("AC detail unavailable")
        return [_ac_detail("ap-1", "0011-2233-4450")]

    service = GroundUnattendedApplicationService(
        paths,
        site_id="site-a",
        repository=repository,
        supervisor=SimpleNamespace(),
        base_query=SimpleNamespace(
            list_ap_location_items=lambda _site_id: [],
            ac_query=SimpleNamespace(list_all_ap_details=list_ac),
        ),
    )
    service._ap_display_resolver()
    thread = service._ap_display_refresh_thread
    assert thread is not None
    thread.join(timeout=2)
    cached = service._ap_display_resolver()
    assert cached.resolve(mac="0011-2233-4450")["peer_ap_id"] == "ap-1"

    fail = True
    service._ap_display_cache_loaded_at -= 31
    stale = service._ap_display_resolver()
    thread = service._ap_display_refresh_thread
    assert thread is not None
    thread.join(timeout=2)

    assert stale.resolve(mac="0011-2233-4450")["peer_ap_id"] == "ap-1"
    assert service._ap_display_resolver().resolve(
        mac="0011-2233-4450"
    )["peer_ap_id"] == "ap-1"


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
    ap1 = _ap(
        "ap-1",
        "横溪站-AP02",
        "0011-2233-4455",
        bssid="1011-2233-4455",
    )
    ap2 = _ap("ap-2", "横溪站-AP03", "0022-3344-5566", bssid="1022-3344-5566")
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
            {
                    "old_peer_mac": "1011-2233-4455",
                "new_peer_mac": "",
            },
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
    service = GroundUnattendedApplicationService(
        paths,
        site_id="site-a",
        repository=repository,
        supervisor=SimpleNamespace(
            fleet_ping=SimpleNamespace(target_summaries=lambda: [])
        ),
        base_query=SimpleNamespace(
            list_ap_location_items=lambda _site_id: [ap1, ap2]
        ),
    )

    rows = {item.event_id: item for item in service.timeline("site-a").items}
    linkup = rows[1]
    linkdown = rows[2]
    switch = rows[3]
    no_active = rows[4]
    lost_active = rows[5]

    assert linkup.resolved_ap_name == "横溪站-AP02"
    assert "RSSI -51 dBm" in linkup.message
    assert linkdown.resolved_ap_name == "横溪站-AP02"
    assert "弱信号（本端）" in linkdown.message
    assert switch.ap_transition_display == "横溪站-AP02 → 横溪站-AP03"
    assert no_active.ap_transition_display == "无主链路 → 横溪站-AP03"
    assert lost_active.ap_transition_display == "横溪站-AP02 → 无主链路"
    assert lost_active.resolution_status == "NO_ACTIVE_LINK"


def _ap(
    ap_id: str,
    name: str,
    mac: str,
    *,
    bssid: str = "",
    aliases: list[str] | None = None,
) -> SimpleNamespace:
    radios = [SimpleNamespace(bssid=bssid)] if bssid else []
    return SimpleNamespace(
        id=ap_id,
        name=name,
        point_code="",
        mac=mac,
        station="横溪站",
        section="横溪站-站点B",
        radios=radios,
        base_metadata={"aliases": aliases or []},
    )


def _ac_detail(
    ap_id: str,
    mac: str,
    *,
    trackside_name: str = "",
) -> SimpleNamespace:
    return SimpleNamespace(
        ap=SimpleNamespace(
            id=ap_id,
            name=mac,
            mac=mac,
            trackside_ap_name=trackside_name,
            point_code="",
            station="横溪站",
            section="横溪站-站点B",
        ),
        radios=[
            SimpleNamespace(
                radio_id=1,
                bssid=mac,
            )
        ],
    )
