from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtWidgets import QHBoxLayout, QMenu, QPushButton, QWidget

from netconsole.ui.shell.fluent_bridge import PrimaryPushButton, PushButton


@dataclass(frozen=True)
class NCCommandAction:
    text: str
    callback: Callable[[], None] | None = None
    icon: object | None = None
    primary: bool = False
    danger: bool = False
    enabled: bool = True
    tooltip: str | None = None
    overflow: bool = False


class NCCommandBar(QWidget):
    """Text-first command bar used by the Fluent shell."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("fluentCommandBar")
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)
        self._overflow_menu = QMenu(self)
        self._overflow_button: QPushButton | None = None

    def add_action_button(self, action: NCCommandAction) -> QPushButton:
        if not action.text.strip():
            raise ValueError("command button text must not be empty")
        if action.overflow:
            return self._add_overflow_action(action)
        button = self._make_button(action)
        self._layout.addWidget(button)
        return button

    def add_stretch(self) -> None:
        self._layout.addStretch(1)

    def _make_button(self, action: NCCommandAction) -> QPushButton:
        button_cls = PrimaryPushButton if action.primary and PrimaryPushButton is not None else PushButton
        button = button_cls(action.text) if button_cls is not None else QPushButton(action.text)
        icon = _to_qicon(action.icon)
        if icon is not None and hasattr(button, "setIcon"):
            try:
                button.setIcon(icon)
            except TypeError:
                pass
        button.setText(action.text)
        button.setToolTip(action.tooltip or action.text)
        button.setEnabled(action.enabled)
        button.setMinimumWidth(max(86, min(180, 18 + len(action.text) * 14)))
        if action.danger:
            button.setObjectName("dangerButton")
        if action.callback is not None:
            button.clicked.connect(action.callback)
        return button

    def _add_overflow_action(self, action: NCCommandAction) -> QPushButton:
        if self._overflow_button is None:
            self._overflow_button = PushButton("更多") if PushButton is not None else QPushButton("更多")
            self._overflow_button.setToolTip("更多操作")
            self._overflow_button.setMenu(self._overflow_menu)
            self._layout.addWidget(self._overflow_button)
        menu_action = self._overflow_menu.addAction(action.text)
        icon = _to_qicon(action.icon)
        if icon is not None:
            try:
                menu_action.setIcon(icon)
            except TypeError:
                pass
        menu_action.setEnabled(action.enabled)
        if action.tooltip:
            menu_action.setToolTip(action.tooltip)
        if action.callback is not None:
            menu_action.triggered.connect(action.callback)
        return self._overflow_button


def _to_qicon(icon: object | None) -> object | None:
    if icon is None:
        return None
    icon_factory = getattr(icon, "icon", None)
    if callable(icon_factory):
        return icon_factory()
    return icon
