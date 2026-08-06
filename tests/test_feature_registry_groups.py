from __future__ import annotations

import pytest

from netconsole.core.feature_registry import group_id_of


@pytest.mark.parametrize(
    ("feature_id", "expected_group"),
    [
        ("web.device_management", "devices"),
        ("web.ac_management", "ac"),
        ("web.config_collection", "configuration"),
        ("web.rail_transit_base_data", "rail_base"),
        ("web.rail_trackside_ap_business", "trackside_ap"),
        ("web.rail_trackside_ap_plan", "trackside_ap"),
        ("web.rail_train_online", "train_online"),
        ("web.ground_unattended", "train_online"),
        ("web.online_mr_realtime", "online_mr"),
        ("web.online_mr_analysis", "online_mr"),
        ("web.mesh_analysis", "mesh"),
        ("web.network_tools_toolbox", "network_tools"),
        ("web.system_settings", "system"),
        ("web.feature_switch", "internal"),
    ],
)
def test_feature_registry_uses_business_domain_groups(
    feature_id: str,
    expected_group: str,
) -> None:
    assert group_id_of(feature_id) == expected_group
