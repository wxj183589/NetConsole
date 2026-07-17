from __future__ import annotations

import math

from netconsole.services.mesh_series_metadata import MESH_SERIES_METADATA, format_mesh_value


def test_mesh_series_metadata_formats_supported_units() -> None:
    assert format_mesh_value(1, MESH_SERIES_METADATA["peer.state"]) == "ACTIVE"
    assert format_mesh_value(0, MESH_SERIES_METADATA["peer.state"]) == "STANDBY"
    assert format_mesh_value(12.4, MESH_SERIES_METADATA["peer.local_tx_busy"]) == "12%"
    assert format_mesh_value(88, MESH_SERIES_METADATA["peer.local_noise"]) == "88 (meaning -88 dBm)"


def test_mesh_series_metadata_rejects_missing_or_non_finite_values() -> None:
    metadata = MESH_SERIES_METADATA["peer.local_rssi"]
    assert format_mesh_value(None, metadata) == "-"
    assert format_mesh_value(math.nan, metadata) == "-"
    assert format_mesh_value(math.inf, metadata) == "-"
