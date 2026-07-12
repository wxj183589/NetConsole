from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from netconsole.core.feature_flags import FeatureGate, default_feature_gate
from netconsole.core.i18n import I18n
from netconsole.ui.shell.fluent_bridge import NavigationInterface, fluent_available, fluent_icon


class Navigation(QWidget):
    currentRowChanged = Signal(int)

    EXPANDED_WIDTH = 220
    COLLAPSED_WIDTH = 64
    ITEMS = (
        ("module.devices", "nav.devices", "devices", "Dev", "SERVER"),
        ("module.ac", "nav.ac", "ac", "AC", "WIFI"),
        ("module.rail_transit", "nav.rail_transit", "rail_transit", "Rail", "TRAIN"),
        ("module.wifi_survey", "nav.wifi_survey", "wifi_survey", "WiFi", "WIFI"),
        ("module.config_collection", "nav.config_collection", "config_collection", "Cfg", "SYNC"),
        ("module.file_management", "nav.file_management", "file_management", "File", "FOLDER"),
        ("module.snmp_center", "nav.snmp_center", "snmp_center", "SNMP", "SEARCH"),
        ("module.network_tools", "nav.network_tools", "network_tools", "Net", "COMMAND_PROMPT"),
        ("module.command_reference", "nav.command_reference", "command_reference", "Cmd", "DOCUMENT"),
        ("module.logs", "nav.logs", "logs", "Log", "DOCUMENT"),
        ("module.system_settings", "nav.system_settings", "system_settings", "Sys", "SETTING"),
        ("module.feature_switch", "system.feature_flags", "feature_flags", "Flag", "SETTING"),
    )

    def __init__(self, i18n: I18n, feature_gate: FeatureGate | None = None) -> None:
        super().__init__()
        self.i18n = i18n
        self.feature_gate = feature_gate or default_feature_gate()
        self.collapsed = False
        self._current_row = -1
        self._items: list[QListWidgetItem] = []
        self._blocked = False
        self.setObjectName("navigation")
        self.setFixedWidth(self.EXPANDED_WIDTH)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        if fluent_available() and NavigationInterface is not None:
            self._fluent = NavigationInterface(showMenuButton=False, showReturnButton=False)
            self._fluent.setObjectName("fluentNavigation")
            self._fluent.setCollapsible(False)
            self._fluent.setExpandWidth(self.EXPANDED_WIDTH)
            layout.addWidget(self._fluent)
            self._legacy_list = None
        else:
            self._fluent = None
            self._legacy_list = QListWidget()
            self._legacy_list.setObjectName("navigationList")
            self._legacy_list.currentRowChanged.connect(self.setCurrentRow)
            layout.addWidget(self._legacy_list)
        self.retranslate()

    def retranslate(self) -> None:
        self._populate_items()

    def set_collapsed(self, collapsed: bool) -> None:
        self.collapsed = bool(collapsed)
        width = self.COLLAPSED_WIDTH if collapsed else self.EXPANDED_WIDTH
        self.setFixedWidth(width)
        if self._fluent is not None:
            self._fluent.setExpandWidth(width)
        self._populate_items()

    def count(self) -> int:
        return len(self._items)

    def item(self, index: int) -> QListWidgetItem:
        return self._items[index]

    def currentRow(self) -> int:
        return self._current_row

    def currentItem(self) -> QListWidgetItem | None:
        if 0 <= self._current_row < len(self._items):
            return self._items[self._current_row]
        return None

    def setCurrentRow(self, row: int) -> None:
        if not 0 <= row < len(self._items):
            row = -1
        if row == self._current_row:
            return
        self._current_row = row
        self._sync_visual_current()
        if not self.signalsBlocked() and not self._blocked:
            self.currentRowChanged.emit(row)

    def blockSignals(self, block: bool) -> bool:
        previous = super().blockSignals(block)
        self._blocked = bool(block)
        if self._legacy_list is not None:
            self._legacy_list.blockSignals(block)
        return previous

    def current_page(self) -> str:
        item = self.currentItem()
        return str(item.data(256)) if item is not None else "devices"

    def find_page(self, page_id: str) -> int:
        for index, item in enumerate(self._items):
            if item.data(256) == page_id:
                return index
        return -1

    def _populate_items(self) -> None:
        current_page = self.current_page()
        self._items.clear()
        if self._legacy_list is not None:
            self._legacy_list.clear()
        if self._fluent is not None:
            self._clear_fluent_navigation()

        for feature_id, key, page_id, collapsed_text, icon_name in self.ITEMS:
            if not self.feature_gate.is_visible(feature_id) or not self.feature_gate.is_enabled(feature_id):
                continue
            label = self.i18n.t(key)
            item = QListWidgetItem(collapsed_text if self.collapsed else label)
            item.setData(256, page_id)
            item.setData(257, label)
            item.setData(258, feature_id)
            item.setToolTip(label)
            item.setTextAlignment(Qt.AlignCenter)
            self._items.append(item)
            if self._legacy_list is not None:
                self._legacy_list.addItem(item.clone())
            if self._fluent is not None:
                self._add_fluent_item(page_id, label, icon_name)

        index = self.find_page(current_page)
        self._current_row = index if index >= 0 else (0 if self._items else -1)
        self._sync_visual_current()

    def _add_fluent_item(self, page_id: str, label: str, icon_name: str) -> None:
        assert self._fluent is not None
        icon = fluent_icon(icon_name)
        self._fluent.addItem(
            routeKey=page_id,
            icon=icon,
            text=label,
            tooltip=label,
            onClick=lambda checked=False, route_key=page_id: self._select_route(route_key),
        )

    def _select_route(self, route_key: str) -> None:
        index = self.find_page(route_key)
        if index >= 0:
            self.setCurrentRow(index)

    def _sync_visual_current(self) -> None:
        item = self.currentItem()
        route_key = str(item.data(256)) if item is not None else ""
        if self._legacy_list is not None and self._legacy_list.currentRow() != self._current_row:
            blocked = self._legacy_list.blockSignals(True)
            self._legacy_list.setCurrentRow(self._current_row)
            self._legacy_list.blockSignals(blocked)
        if self._fluent is not None and route_key:
            self._fluent.setCurrentItem(route_key)

    def _clear_fluent_navigation(self) -> None:
        assert self._fluent is not None
        for child in list(self._fluent.findChildren(QWidget)):
            if child.objectName():
                continue
        try:
            panel = getattr(self._fluent, "panel", None)
            if panel is not None and hasattr(panel, "items"):
                for route_key in list(panel.items.keys()):
                    self._fluent.removeWidget(route_key)
        except Exception:
            self._fluent = NavigationInterface(showMenuButton=False, showReturnButton=False)
            self._fluent.setObjectName("fluentNavigation")
            self._fluent.setCollapsible(False)
            self._fluent.setExpandWidth(self.COLLAPSED_WIDTH if self.collapsed else self.EXPANDED_WIDTH)
            layout = self.layout()
            if layout is not None:
                while layout.count():
                    child = layout.takeAt(0)
                    widget = child.widget()
                    if widget is not None:
                        widget.deleteLater()
                layout.addWidget(self._fluent)
