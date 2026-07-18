from __future__ import annotations

from netconsole.models.mesh_series import (
    MESH_METRICS,
    MeshLinkStateValue,
    MeshUnitSemantics,
    MeshValueKind,
)


def test_mesh_metric_semantics_are_independent_from_presentation() -> None:
    state = MESH_METRICS["peer.state"]
    assert state.value_kind is MeshValueKind.STATE_CODE
    assert state.minimum == MeshLinkStateValue.STANDBY
    assert state.maximum == MeshLinkStateValue.ACTIVE

    busy = MESH_METRICS["peer.local_tx_busy"]
    assert busy.unit is MeshUnitSemantics.PERCENT
    assert busy.minimum == 0
    assert busy.maximum == 100


def test_mesh_metric_semantics_do_not_contain_ui_keys_or_display_text() -> None:
    serialized = repr(MESH_METRICS)
    assert "label_key" not in serialized
    assert "description_key" not in serialized
    assert "meaning" not in serialized
