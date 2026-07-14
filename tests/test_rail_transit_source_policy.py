from __future__ import annotations

from netconsole.services.rail_transit.source_policy import (
    field_action,
    is_runtime_field,
    match_trackside_ap,
    match_vehicle_mr,
)


def test_ap_source_policy_prefers_formal_identity_and_ignores_dhcp_ip() -> None:
    existing = [
        {"id": 1, "ap_name": "AP-001", "ap_mac_norm": "001122334455", "ap_ip": "10.0.0.10"},
    ]

    assert match_trackside_ap({"ap_mac_display": "0011-2233-4455"}, existing).entity_id == "ap:1"
    assert match_trackside_ap({"ap_name": "AP-001"}, existing).method == "name_exact"
    assert match_trackside_ap({"ap_ip": "10.0.0.10"}, existing).status == "create"
    assert match_trackside_ap({"ap_name": "AP-00"}, existing).status == "create"
    assert field_action("正式名称", "AC 运行时名称", source_type="ac_fit_ap") == "manual_review"
    assert is_runtime_field("management_ip") is True


def test_mr_source_policy_matches_static_ip_and_rejects_cross_key_conflict() -> None:
    existing = [
        {"device_uuid": "mr-ct", "device_id": 1, "primary_address": "10.0.0.1", "mac_address": "0011-2233-4401", "name": "MR-CT"},
        {"device_uuid": "mr-tc", "device_id": 2, "primary_address": "10.0.0.2", "mac_address": "0011-2233-4402", "name": "MR-TC"},
    ]

    matched = match_vehicle_mr({"primary_address": "10.0.0.1"}, existing)
    conflict = match_vehicle_mr(
        {"primary_address": "10.0.0.1", "mac_address": "0011-2233-4402"},
        existing,
    )

    assert matched.status == "matched"
    assert matched.entity_id == "mr-ct"
    assert matched.method == "static_ip"
    assert conflict.status == "conflict"
    assert conflict.method == "cross_key"
