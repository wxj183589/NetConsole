from __future__ import annotations

from PySide6.QtWidgets import QPushButton

from netconsole.ui.shell.fluent_bridge import FIF


def safe_fluent_icon(name: str | None) -> object | None:
    if not name or FIF is None:
        return None
    return getattr(FIF, name, None)


def apply_button_icon(button: QPushButton, icon_name: str | None) -> None:
    icon = safe_fluent_icon(icon_name)
    if icon is not None:
        icon_factory = getattr(icon, "icon", None)
        resolved_icon = icon_factory() if callable(icon_factory) else icon
        try:
            button.setIcon(resolved_icon)
        except TypeError:
            pass
    if button.text().strip():
        button.setToolTip(button.text())
