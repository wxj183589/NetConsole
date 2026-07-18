from __future__ import annotations

import math

from netconsole.core.view_models.mesh_series_view_model import (
    MESH_SERIES_PRESENTATION,
    format_mesh_value,
)


def test_mesh_series_view_model_formats_supported_units() -> None:
    assert format_mesh_value(1, "peer.state") == "ACTIVE"
    assert format_mesh_value(0, "peer.state") == "STANDBY"
    assert format_mesh_value(12.4, "peer.local_tx_busy") == "12%"
    assert format_mesh_value(88, "peer.local_noise") == "88 (meaning -88 dBm)"


def test_mesh_series_view_model_rejects_missing_or_non_finite_values() -> None:
    assert format_mesh_value(None, "peer.local_rssi") == "-"
    assert format_mesh_value(math.nan, "peer.local_rssi") == "-"
    assert format_mesh_value(math.inf, "peer.local_rssi") == "-"


def test_mesh_series_presentation_owns_i18n_and_display_precision() -> None:
    metadata = MESH_SERIES_PRESENTATION["peer.local_rssi"]
    assert metadata.label_key == "mesh_analysis.mr_rssi"
    assert metadata.description_key == "mesh_analysis.mr_rssi_description"
    assert metadata.decimals == 0
