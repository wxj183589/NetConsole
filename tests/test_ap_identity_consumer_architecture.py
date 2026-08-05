from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVICES = ROOT / "src" / "netconsole" / "services"

DIRECT_IDENTITY_TABLE_ALLOWLIST = {
    "ac/mesh_link_query_service.py",
    "rail_transit/base_data_query_service.py",
    "rail_transit/mesh_analysis_query_service.py",
    "site_lifecycle.py",
}

PHASE2_CONSUMERS = {
    "vehicle_mr_online.py",
    "rail_transit/online_mr_diagnosis_parser.py",
    "rail_transit/online_mr_identity_remap_service.py",
    "network_tools/trackside_bssid_resolver.py",
}


def test_ground_ap_display_has_no_private_alias_index_or_h3c_derivation() -> None:
    source = (
        SERVICES / "ground_unattended" / "ap_resolver.py"
    ).read_text(encoding="utf-8")

    assert "resolve_peer_macs" in source
    for forbidden in (
        "_by_ap_mac",
        "_by_radio_mac",
        "_by_alias_mac",
        "_resource_by_ap_mac",
        "_resource_by_radio_mac",
        "h3c_radio_mac_match_method",
        "derive_h3c",
    ):
        assert forbidden not in source


def test_new_consumers_cannot_query_identity_tables_directly() -> None:
    pattern = re.compile(
        r"ap_identity_(?:entities|mac_aliases|h3c_prefixes|conflicts|index_state)"
    )
    found = {
        path.relative_to(SERVICES).as_posix()
        for path in SERVICES.rglob("*.py")
        if pattern.search(path.read_text(encoding="utf-8"))
    }

    assert found - DIRECT_IDENTITY_TABLE_ALLOWLIST == set()


def test_new_consumers_cannot_use_legacy_ap_radio_resolver() -> None:
    pattern = re.compile(r"ApRadioMappingService|h3c_radio_mac_match_method")
    found = {
        path.relative_to(SERVICES).as_posix()
        for path in SERVICES.rglob("*.py")
        if pattern.search(path.read_text(encoding="utf-8"))
    }

    assert found == set()


def test_phase2_consumers_use_only_batch_identity_projection_contract() -> None:
    sources = {
        relative: (SERVICES / relative).read_text(encoding="utf-8")
        for relative in PHASE2_CONSUMERS
    }
    for relative, source in sources.items():
        if relative != "rail_transit/online_mr_diagnosis_parser.py":
            assert "resolve_peer_macs" in source, relative
        for forbidden in (
            "resolve_peer_mac(",
            "resolve_ap_mac(",
            "ApRadioMappingService",
            "MeshPeerMappingService",
            "h3c_radio_mac_match_method",
            "radio_mac_map",
            "by_bssid",
            "by_radio_mac",
            "by_alias_mac",
            "__ap_identity_entities__",
            "_AP_IDENTITY_ENTITIES_KEY",
        ):
            assert forbidden not in source, f"{relative}: {forbidden}"
