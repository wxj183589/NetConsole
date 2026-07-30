from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from netconsole.services.ap_identity import (
    ApIdentityCandidate,
    ApIdentityResolver,
    ApMatchStatus,
    ApObservation,
    CanonicalApIdentity,
    CanonicalApLocation,
    CanonicalApRadioIdentity,
    candidate_from_ap_entity_row,
    candidate_from_extension_row,
    candidate_from_fit_ap_resource_row,
    is_mac_like,
    normalize_ap_name,
    normalize_mac,
    normalize_mileage,
    observation_from_mesh_peer,
    observation_from_online_mr_sample,
    observation_from_wireless_bssid,
    parse_line_direction,
    same_mac,
)


def candidate(
    *,
    ap_uuid: str | None = None,
    ap_id: str | None = None,
    ap_mac: str | None = None,
    ap_name: str | None = None,
    ac_uuid: str | None = None,
    radios: tuple[CanonicalApRadioIdentity, ...] = (),
    location: CanonicalApLocation | None = None,
    raw: dict[str, object] | None = None,
) -> ApIdentityCandidate:
    return ApIdentityCandidate(
        identity=CanonicalApIdentity(
            ap_uuid=ap_uuid,
            ap_id=ap_id,
            ap_mac=ap_mac,
            ap_name=ap_name,
            ac_uuid=ac_uuid,
            source="test",
        ),
        radios=radios,
        location=location or CanonicalApLocation(),
        raw=raw or {},
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("aa:bb:cc:dd:ee:ff", "aa:bb:cc:dd:ee:ff"),
        ("AA-BB-CC-DD-EE-FF", "aa:bb:cc:dd:ee:ff"),
        ("aabb.ccdd.eeff", "aa:bb:cc:dd:ee:ff"),
        ("bc5a-3457-8cc0", "bc:5a:34:57:8c:c0"),
        ("BC5A-3457-8CC0", "bc:5a:34:57:8c:c0"),
        ("bc5a.3457.8cc0", "bc:5a:34:57:8c:c0"),
        ("bc:5a:34:57:8c:c0", "bc:5a:34:57:8c:c0"),
        ("bc-5a-34-57-8c-c0", "bc:5a:34:57:8c:c0"),
        ("bc5a34578cc0", "bc:5a:34:57:8c:c0"),
        ("aabbccddeeff", "aa:bb:cc:dd:ee:ff"),
        ("AABBCCDDEEFF", "aa:bb:cc:dd:ee:ff"),
    ],
)
def test_normalize_mac_accepts_supported_formats(raw, expected):
    assert normalize_mac(raw) == expected
    assert is_mac_like(raw)


@pytest.mark.parametrize("raw", [None, "", "N/A", "--", "unknown", "None", "bad-mac", "aa:bb:cc:dd:ee", "0011-2233-445", "0011-2233-G455", "0011/2233/4455", "0011-2233-445566"])
def test_normalize_mac_rejects_empty_sentinels_and_invalid_values(raw):
    assert normalize_mac(raw) is None
    assert not is_mac_like(raw)


def test_same_mac_compares_normalized_values_only():
    assert same_mac("AA-BB-CC-DD-EE-FF", "aabb.ccdd.eeff")
    assert not same_mac("bad", "bad")


def test_ap_name_preserves_original_mac_like_name_without_retyping_it():
    raw_name = "AA-BB-CC-DD-EE-FF"

    assert normalize_ap_name(f"  {raw_name}  ") == raw_name
    assert is_mac_like(raw_name)
    observation = ApObservation(ap_name=raw_name)
    assert observation.ap_name == raw_name
    assert observation.ap_mac is None


@pytest.mark.parametrize(
    ("raw", "mileage", "line", "direction"),
    [
        ("!Z!D!K01+020", "ZDK1+020", "左线", "下行"),
        ("!Y!D!K01+020", "YDK1+020", "右线", "上行"),
        ("!C!D!K01+020", "CDK1+020", "出段线", "出段"),
        ("!R!D!K01+020", "RDK1+020", "入段线", "入段"),
    ],
)
def test_mileage_and_line_direction_normalization_preserves_prefix_semantics(raw, mileage, line, direction):
    assert normalize_mileage(raw) == mileage
    assert parse_line_direction(raw) == (line, direction)


def test_identity_models_are_frozen_and_raw_mappings_are_read_only():
    item = candidate(ap_uuid="ap-1", raw={"id": 7})

    with pytest.raises(FrozenInstanceError):
        item.identity.ap_uuid = "changed"
    with pytest.raises(TypeError):
        item.raw["id"] = 8


def test_resolver_matches_ap_uuid_before_conflicting_lower_priority_fields():
    uuid_match = candidate(ap_uuid="ap-1", ap_mac="00:11:22:33:44:55", ap_name="AP-A")
    mac_match = candidate(ap_uuid="ap-2", ap_mac="aa:bb:cc:dd:ee:ff", ap_name="AP-B")

    result = ApIdentityResolver().resolve(
        ApObservation(ap_uuid="AP-1", ap_mac="aa-bb-cc-dd-ee-ff", ap_name="AP-B"),
        [uuid_match, mac_match],
    )

    assert result.status is ApMatchStatus.MATCHED
    assert result.candidate is uuid_match
    assert result.evidence[0].field == "ap_uuid"


def test_sqlite_row_id_is_trace_only_and_never_a_global_identity():
    first = candidate(ap_name="AP-A", raw={"id": 1})
    second = candidate(ap_name="AP-B", raw={"id": 2})

    result = ApIdentityResolver().resolve(ApObservation(source_ref="1"), [first, second])

    assert result.status is ApMatchStatus.UNRESOLVED


def test_apid_without_ac_scope_cannot_match_globally():
    candidates = [
        candidate(ap_id="7", ac_uuid="ac-a"),
        candidate(ap_id="7", ac_uuid="ac-b"),
    ]

    assert ApIdentityResolver().resolve(ApObservation(ap_id="7"), candidates).status is ApMatchStatus.UNRESOLVED


def test_scoped_apid_matches_only_one_ac_and_duplicate_in_scope_is_ambiguous():
    first = candidate(ap_uuid="ap-1", ap_id="7", ac_uuid="ac-a")
    other_ac = candidate(ap_uuid="ap-2", ap_id="7", ac_uuid="ac-b")
    resolver = ApIdentityResolver()

    matched = resolver.resolve(ApObservation(ap_id="7", ac_uuid="AC-A"), [first, other_ac])
    ambiguous = resolver.resolve(
        ApObservation(ap_id="7", ac_uuid="ac-a"),
        [first, candidate(ap_uuid="ap-3", ap_id="7", ac_uuid="ac-a")],
    )

    assert matched.status is ApMatchStatus.MATCHED
    assert matched.candidate is first
    assert ambiguous.status is ApMatchStatus.AMBIGUOUS


def test_ap_mac_unique_match_and_cross_ac_duplicate_behavior():
    first = candidate(ap_uuid="ap-1", ap_mac="aa:bb:cc:dd:ee:ff", ac_uuid="ac-a")
    second = candidate(ap_uuid="ap-2", ap_mac="aa-bb-cc-dd-ee-ff", ac_uuid="ac-b")
    resolver = ApIdentityResolver()

    ambiguous = resolver.resolve(ApObservation(ap_mac="aabb.ccdd.eeff"), [first, second])
    scoped = resolver.resolve(ApObservation(ap_mac="aabb.ccdd.eeff", ac_uuid="ac-b"), [first, second])

    assert ambiguous.status is ApMatchStatus.AMBIGUOUS
    assert scoped.status is ApMatchStatus.MATCHED
    assert scoped.candidate is second


def test_missing_ap_mac_is_unresolved():
    result = ApIdentityResolver().resolve(ApObservation(), [candidate(ap_mac="aa:bb:cc:dd:ee:ff")])

    assert result.status is ApMatchStatus.UNRESOLVED


def test_ap_name_is_display_only_and_mac_remains_the_only_identity():
    by_name = candidate(ap_uuid="ap-name", ap_name="AP-01", ap_mac="00:11:22:33:44:55", ac_uuid="ac-a")
    by_mac = candidate(ap_uuid="ap-mac", ap_name="AP-OLD", ap_mac="aa:bb:cc:dd:ee:ff", ac_uuid="ac-a")
    duplicate_name = candidate(ap_uuid="ap-other", ap_name="ap-01", ac_uuid="ac-b")
    resolver = ApIdentityResolver()

    scoped = resolver.resolve(ApObservation(ap_name="ap-01", ac_uuid="ac-a"), [by_name, duplicate_name])
    ambiguous = resolver.resolve(ApObservation(ap_name="AP-01"), [by_name, duplicate_name])
    mac_wins = resolver.resolve(ApObservation(ap_name="AP-01", ap_mac="aa-bb-cc-dd-ee-ff"), [by_name, by_mac])

    assert scoped.status is ApMatchStatus.UNRESOLVED
    assert ambiguous.status is ApMatchStatus.UNRESOLVED
    assert mac_wins.candidate is by_mac
    assert mac_wins.evidence[0].field == "ap_mac"


def test_radio_mac_and_bssid_require_explicit_candidate_radio_mapping():
    radio_candidate = candidate(
        ap_uuid="ap-1",
        ap_mac="00:11:22:33:44:55",
        radios=(
            CanonicalApRadioIdentity(
                radio_id=1,
                radio_mac="aa:bb:cc:dd:ee:01",
                bssid="aa:bb:cc:dd:ee:02",
                bbssid="aa:bb:cc:dd:ee:03",
            ),
        ),
    )
    no_radio_mapping = candidate(ap_uuid="ap-2", ap_mac="aa:bb:cc:dd:ee:04")
    resolver = ApIdentityResolver()

    assert resolver.resolve(ApObservation(radio_mac="aa-bb-cc-dd-ee-01"), [radio_candidate]).candidate is radio_candidate
    assert resolver.resolve(ApObservation(bssid="aabb.ccdd.ee02"), [radio_candidate]).candidate is radio_candidate
    assert resolver.resolve(ApObservation(bssid="aa:bb:cc:dd:ee:03"), [radio_candidate]).candidate is radio_candidate
    assert resolver.resolve(ApObservation(radio_mac="aa:bb:cc:dd:ee:04"), [no_radio_mapping]).status is ApMatchStatus.UNRESOLVED
    assert resolver.resolve(ApObservation(bssid="aa:bb:cc:dd:ee:04"), [no_radio_mapping]).status is ApMatchStatus.UNRESOLVED


def test_peer_observation_prefers_explicit_radio_mapping_over_ap_mac_fallback():
    ap_mac_candidate = candidate(ap_uuid="ap-1", ap_mac="aa:bb:cc:dd:ee:ff")
    radio_candidate = candidate(
        ap_uuid="ap-2",
        ap_mac="00:11:22:33:44:55",
        radios=(CanonicalApRadioIdentity(radio_id=2, radio_mac="aa:bb:cc:dd:ee:ff"),),
    )

    result = ApIdentityResolver().resolve(ApObservation(peer_mac="aa-bb-cc-dd-ee-ff"), [ap_mac_candidate, radio_candidate])

    assert result.status is ApMatchStatus.MATCHED
    assert result.candidate is radio_candidate
    assert result.evidence[0].field == "peer_mac"


def test_peer_mac_matching_ap_mac_alone_stays_unresolved_without_evidence():
    ap = candidate(ap_uuid="ap-1", ap_mac="aa:bb:cc:dd:ee:ff")

    result = ApIdentityResolver().resolve(ApObservation(peer_mac="aa-bb-cc-dd-ee-ff"), [ap])

    assert result.status is ApMatchStatus.UNRESOLVED
    assert result.candidates == ()
    assert result.evidence == ()
    assert result.warnings == ()


def test_duplicate_peer_and_peer_radio_mac_records_warning_without_dropping_observation():
    observation = ApObservation(peer_mac="AA-BB-CC-DD-EE-FF", peer_radio_mac="aabb.ccdd.eeff")

    result = ApIdentityResolver().resolve(observation, [])

    assert result.status is ApMatchStatus.UNRESOLVED
    assert result.warnings == ("peer_mac 与 peer_radio_mac 规范化后重复",)
    assert result.evidence[0].field == "peer_mac+peer_radio_mac"
    assert observation.peer_mac == "AA-BB-CC-DD-EE-FF"


def test_location_fields_add_evidence_but_cannot_select_an_ap():
    location = CanonicalApLocation(site="Site-A", station=None, section="Section-A", mileage="ZDK1+020")
    ap = candidate(ap_uuid="ap-1", location=location)
    resolver = ApIdentityResolver()

    unresolved = resolver.resolve(ApObservation(site="Site-A", section="Section-A", mileage="!Z!D!K1+020"), [ap])
    matched = resolver.resolve(ApObservation(ap_uuid="ap-1", site="Site-A", section="Section-A", mileage="!Z!D!K1+020"), [ap])

    assert unresolved.status is ApMatchStatus.UNRESOLVED
    assert matched.status is ApMatchStatus.MATCHED
    assert {item.field for item in matched.evidence} >= {"ap_uuid", "site", "section", "mileage"}


def test_extension_adapter_keeps_section_when_station_is_empty_and_does_not_infer_pis_network_domain():
    pis = candidate_from_extension_row(
        {
            "id": 3,
            "ap_name": "AP-01",
            "ap_mac_display": "AA-BB-CC-DD-EE-FF",
            "system_type": "PIS",
            "station_name": "",
            "section_name": "A-B",
            "belong_type": "section",
            "mileage_text": "!Y!D!K1+020",
        }
    )
    signal = candidate_from_extension_row({"ap_name": "AP-02", "system_type": "信号", "network_domain": "红网"})

    assert pis.location.station is None
    assert pis.location.section == "A-B"
    assert pis.location.ownership_type == "section"
    assert pis.location.network_domain is None
    assert pis.location.mileage == "YDK1+020"
    assert signal.location.network_domain == "红网"


def test_row_adapters_are_read_only_and_preserve_identity_source_and_raw_values():
    row = {
        "id": 8,
        "ap_uuid": "ap-1",
        "ap_name": "AP-01",
        "ap_mac": "AA-BB-CC-DD-EE-FF",
        "ac_device_uuid": "ac-1",
        "apid": "7",
        "rid1_bbssid": "00-11-22-33-44-55",
    }
    original = dict(row)

    entity = candidate_from_ap_entity_row(row)
    resource = candidate_from_fit_ap_resource_row(row)

    assert row == original
    assert entity.identity.source == "ap_entity"
    assert resource.identity.source == "fit_ap_resource"
    assert resource.identity.ap_mac == "aa:bb:cc:dd:ee:ff"
    assert resource.identity.ap_id == "7"
    assert resource.radios[0].radio_id == 1
    assert resource.radios[0].bbssid == "00:11:22:33:44:55"
    assert resource.raw["ap_name"] == "AP-01"


def test_observation_adapters_keep_peer_bssid_and_topology_context_separate():
    mesh = observation_from_mesh_peer(
        {
            "peer_mac_raw": "AA-BB-CC-DD-EE-FF",
            "peer_radio_mac": "aabb.ccdd.eeff",
            "peer_ap_name": "AP-01",
            "source_file_id": 12,
        }
    )
    online = observation_from_online_mr_sample(
        {
            "peer_mac": "00-11-22-33-44-55",
            "bssid": "00-11-22-33-44-56",
            "ac_device_uuid": "ac-1",
            "device_uuid": "switch-1",
            "interface_name": "GigabitEthernet1/0/1",
        }
    )
    wireless = observation_from_wireless_bssid({"bssid": "00-11-22-33-44-57"})

    assert mesh.peer_mac == "aa:bb:cc:dd:ee:ff"
    assert mesh.peer_radio_mac == "aa:bb:cc:dd:ee:ff"
    assert mesh.ap_mac is None
    assert mesh.source_ref == "12"
    assert online.peer_mac == "00:11:22:33:44:55"
    assert online.bssid == "00:11:22:33:44:56"
    assert online.ac_uuid == "ac-1"
    assert online.device_uuid == "switch-1"
    assert online.interface_name == "GigabitEthernet1/0/1"
    assert wireless.bssid == "00:11:22:33:44:57"
    assert wireless.ap_mac is None


def test_identity_package_has_no_ui_repository_worker_or_network_dependencies():
    package = Path(__file__).parents[1] / "src" / "netconsole" / "services" / "ap_identity"
    forbidden = ("PySide6", "netconsole.ui", "netconsole.repositories", "job_center", "netmiko", "socket")

    for path in package.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not any(token in text for token in forbidden), path.name
