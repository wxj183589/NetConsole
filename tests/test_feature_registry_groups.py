from __future__ import annotations

import pytest

from netconsole.core.feature_registry import group_id_of


@pytest.mark.parametrize(
    ("feature_id", "expected_group"),
    [
        ("module.devices", "devices"),
        ("module.ac", "ac"),
        ("module.config_collection", "configuration"),
        ("module.rail_base_data", "rail_base"),
        ("module.trackside_ap", "trackside_ap"),
        ("capability.trackside_ap.plan", "trackside_ap"),
        ("module.train_online", "train_online"),
        ("module.ground_unattended", "train_online"),
        ("module.online_mr", "online_mr"),
        ("module.online_mr_analysis", "online_mr"),
        ("module.mesh_analysis", "mesh"),
        ("capability.network_tools.toolbox", "network_tools"),
        ("module.system_settings", "system"),
        ("internal.feature_switch", "internal"),
    ],
)
def test_feature_registry_uses_business_domain_groups(
    feature_id: str,
    expected_group: str,
) -> None:
    assert group_id_of(feature_id) == expected_group


def test_ground_v2_tabs_and_actions_share_authority_and_localized_titles() -> None:
    from netconsole.core.feature_registry import FEATURE_BY_ID
    from netconsole.core.i18n import TRANSLATIONS

    children = [item for item in FEATURE_BY_ID.values() if item.parent_id == "module.ground_unattended"]
    assert len([item for item in children if item.item_type == "tab"]) == 10
    assert {item.feature_id for item in children if item.item_type == "action"} == {
        "capability.ground_unattended.quick_ping", "capability.ground_unattended.history_export",
    }
    for item in children:
        for language in ("zh_CN", "en_US"):
            assert item.title_key in TRANSLATIONS[language]
