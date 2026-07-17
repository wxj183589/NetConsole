from __future__ import annotations

from PySide6.QtWidgets import QWidget

from netconsole.core.feature_flags import FeatureGate


def apply_feature_to_widget(
    feature_gate: FeatureGate,
    feature_id: str,
    widget: QWidget,
    *,
    hide_when_invisible: bool = True,
) -> None:
    visible = feature_gate.is_visible(feature_id)
    enabled = feature_gate.is_enabled(feature_id)
    if hide_when_invisible:
        widget.setVisible(visible)
    widget.setEnabled(enabled)
    if visible and not enabled:
        widget.setToolTip("当前版本未开放此功能")
