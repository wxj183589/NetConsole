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
