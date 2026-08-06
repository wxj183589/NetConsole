from __future__ import annotations

from netconsole.services.neighbor_matcher import (
    NeighborDeviceIdentityIndex,
    normalize_neighbor_identity_name,
)


def _switch(
    device_uuid: str,
    *,
    name: str,
    system_name: str = "",
    primary_address: str = "",
    mac_address: str = "",
    fact_sysname: str = "",
    fact_mac_address: str = "",
    station_id: str = "station-a",
    station: str = "Station A",
) -> dict[str, object]:
    return {
        "device_uuid": device_uuid,
        "name": name,
        "system_name": system_name,
        "primary_address": primary_address,
        "mac_address": mac_address,
        "fact_sysname": fact_sysname,
        "fact_mac_address": fact_mac_address,
        "station_id": station_id,
        "station": station,
        "device_type": "SW",
        "work_scope_status": "included",
    }


def test_neighbor_identity_name_normalizes_case_spacing_fqdn_and_vendor_prefix() -> None:
    assert normalize_neighbor_identity_name("  HZDT_SC.Example.COM. ") == "hzdt-sc"
    assert normalize_neighbor_identity_name("ZTE ZXR10 HZDT-SC") == "hzdt-sc"
    assert normalize_neighbor_identity_name("ＨＺＤＴ＿ＳＣ") == "hzdt-sc"


def test_neighbor_identity_uses_stable_device_id_before_other_evidence() -> None:
    index = NeighborDeviceIdentityIndex(
        [
            _switch("sw-a", name="SW-A", mac_address="0011-2233-4455"),
            _switch("sw-b", name="SW-B", mac_address="0011-2233-4466"),
        ]
    )

    match = index.resolve(
        {
            "switch_device_uuid": "sw-a",
            "lldp_neighbor_mac": "00:11:22:33:44:66",
            "lldp_neighbor_name": "SW-B",
        }
    )

    assert match.match_status == "matched"
    assert match.device_uuid == "sw-a"
    assert match.matched_by == "device_id"


def test_neighbor_identity_does_not_treat_source_device_as_neighbor_id() -> None:
    index = NeighborDeviceIdentityIndex(
        [_switch("sw-a", name="SW-A", system_name="HZDT-SC")]
    )

    match = index.resolve(
        {
            "device_uuid": "ac-source-device",
            "lldp_neighbor_name": "HZDT-SC",
        }
    )

    assert match.device_uuid == "sw-a"
    assert match.matched_by == "system_name"


def test_neighbor_identity_matches_unique_chassis_ip_and_normalized_name() -> None:
    index = NeighborDeviceIdentityIndex(
        [
            _switch(
                "sw-a",
                name="16-Station A",
                system_name="HZDT-SC",
                primary_address="192.0.2.10",
                mac_address="0011-2233-4455",
            )
        ]
    )

    by_chassis = index.resolve({"lldp_neighbor_mac": "00:11:22:33:44:55"})
    by_ip = index.resolve({"lldp_management_ip": "192.0.2.10"})
    by_name = index.resolve({"lldp_neighbor_name": " zte-zxr10-hzdt_sc.example.com "})

    assert (by_chassis.device_uuid, by_chassis.matched_by) == ("sw-a", "chassis_id")
    assert (by_ip.device_uuid, by_ip.matched_by) == ("sw-a", "management_ip")
    assert (by_name.device_uuid, by_name.matched_by) == ("sw-a", "system_name")


def test_neighbor_identity_is_scoped_to_the_index_site() -> None:
    site_a = NeighborDeviceIdentityIndex(
        [_switch("site-a-sw", name="Shared-SW", primary_address="192.0.2.20")]
    )
    site_b = NeighborDeviceIdentityIndex(
        [_switch("site-b-sw", name="Shared-SW", primary_address="192.0.2.20")]
    )

    assert site_a.resolve({"lldp_neighbor_name": "shared_sw"}).device_uuid == "site-a-sw"
    assert site_b.resolve({"lldp_neighbor_name": "shared_sw"}).device_uuid == "site-b-sw"


def test_neighbor_identity_never_selects_first_ambiguous_candidate() -> None:
    index = NeighborDeviceIdentityIndex(
        [
            _switch("sw-a", name="SW-A", system_name="HZDT-SC"),
            _switch("sw-b", name="SW-B", system_name="hzdt_sc.example.com"),
        ]
    )

    match = index.resolve({"lldp_neighbor_name": "HZDT-SC"})

    assert match.match_status == "ambiguous"
    assert match.device_uuid is None
    assert match.candidate_count == 2
    assert match.matched_by == "system_name"


def test_neighbor_identity_does_not_use_generic_vendor_name() -> None:
    index = NeighborDeviceIdentityIndex([_switch("sw-a", name="Station Switch")])

    match = index.resolve({"lldp_neighbor_name": "H3C"})

    assert match.match_status == "unresolved"
    assert match.device_uuid is None


def test_neighbor_identity_keeps_h3c_and_other_vendor_regression() -> None:
    index = NeighborDeviceIdentityIndex(
        [
            _switch("sw-h3c", name="H3C Switch", system_name="H3C-SW-A"),
            _switch("sw-other", name="Other Switch", system_name="EDGE-SW-B"),
        ]
    )

    h3c = index.resolve(
        {"lldp_neighbor_name": "comware_h3c_sw_a.example.com"}
    )
    other = index.resolve({"lldp_neighbor_name": "edge_sw_b.example.com"})

    assert (h3c.device_uuid, h3c.matched_by) == ("sw-h3c", "system_name")
    assert (other.device_uuid, other.matched_by) == ("sw-other", "system_name")
