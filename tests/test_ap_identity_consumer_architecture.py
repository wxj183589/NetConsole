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
    "vehicle_mr_online.py",
}

LEGACY_RESOLVER_ALLOWLIST = {
    "ap_radio_mapping_service.py",
    "rail_transit/online_mr_diagnosis_parser.py",
    "vehicle_mr_online.py",
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

    assert found - LEGACY_RESOLVER_ALLOWLIST == set()
