from __future__ import annotations

from netconsole.ui.dialogs.message_service import MessageBox
import ipaddress
import subprocess

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QMenu,
    QSizePolicy,
    QSplitter,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from netconsole.core.admin import is_admin, open_network_manager_as_admin
from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.services.network_profile_store import AdapterMatch, AdapterProfile, NetworkProfileStore, SecondaryIp
from netconsole.services.route_profile_store import RouteProfile, RouteProfileEntry, RouteProfileStore
from netconsole.services.windows_network_manager import (
    AdapterIpConfig,
    NetworkAdapterInfo,
    RouteConfig,
    RouteInfo,
    SecondaryIpConfig,
    VlanProperty,
    WindowsNetworkManager,
    build_destination_prefix,
    build_open_network_connections_command,
    parse_prefix_or_netmask,
)
from netconsole.ui.components.button_icons import apply_button_icon


ADAPTER_HEADERS = ["名称", "描述", "MAC", "状态", "速率", "IPv4", "网关", "标签"]
ADAPTER_WIDTHS = [160, 280, 150, 90, 100, 180, 160, 180]
ROUTE_HEADERS = ["序号", "目标网络", "下一跳", "接口", "跃点数", "策略存储", "持久", "来源"]
ROUTE_WIDTHS = [60, 180, 160, 180, 80, 140, 70, 100]
PROFILE_HEADERS = ["方案名称", "路由数量", "是否启用", "备注"]
EDIT_ROUTE_HEADERS = ["目标网络", "下一跳", "出接口", "跃点数", "持久", "备注"]


class NetworkRefreshWorker(QObject):
    progress = Signal(str)
    finished = Signal(object, object, str)

    def __init__(self, manager: WindowsNetworkManager) -> None:
        super().__init__()
        self.manager = manager

    def run(self) -> None:
        try:
            self.progress.emit("正在读取本地网卡...")
            adapters = self.manager.list_adapters()
            self.progress.emit("正在读取路由表...")
            routes = self.manager.list_routes()
            self.finished.emit(adapters, routes, "")
        except Exception as exc:
            self.finished.emit([], [], str(exc))


EDIT_ROUTE_HEADERS = ["目标网络", "掩码", "下一跳", "出接口", "跃点数", "持久", "备注"]


class NetworkAdapterRoutePage(QWidget):
    def __init__(
        self,
        i18n: I18n,
        paths: PathResolver,
        manager: WindowsNetworkManager | None = None,
        profile_store: NetworkProfileStore | None = None,
        route_store: RouteProfileStore | None = None,
    ) -> None:
        super().__init__()
        self.i18n = i18n
        self.paths = paths
        self.manager = manager or WindowsNetworkManager()
        self.profile_store = profile_store or NetworkProfileStore(paths.network_profiles_path)
        self.route_store = route_store or RouteProfileStore(paths.route_profiles_path)
        self.adapters: list[NetworkAdapterInfo] = []
        self.routes: list[RouteInfo] = []
        self.admin_launch_pending = False
        self.refresh_thread: QThread | None = None
        self.refresh_worker: NetworkRefreshWorker | None = None

        self.permission_label = QLabel()
        self.status_label = QLabel()
        self.refresh_button = QPushButton()
        self.open_connections_button = QPushButton()
        self.admin_button = QPushButton()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.hide()
        self.tabs = QTabWidget()
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)

        self.adapter_combo = QComboBox()
        self.adapter_table = QTableWidget(0, len(ADAPTER_HEADERS))
        self.adapter_table.setHorizontalHeaderLabels(ADAPTER_HEADERS)
        self.adapter_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["DHCP", "静态IP"])
        self.ip_edit = QLineEdit()
        self.prefix_edit = QLineEdit("24")
        self.prefix_edit.setPlaceholderText("例如：24 或 255.255.255.0")
        self.gateway_edit = QLineEdit()
        self.secondary_edit = QTextEdit()
        self.secondary_edit.setPlaceholderText("192.168.1.200/24\n172.16.1.200/255.255.255.0")
        self.vlan_spin = QSpinBox()
        self.vlan_spin.setRange(0, 4094)
        self.profile_name_edit = QLineEdit()
        self.profile_combo = QComboBox()
        self.save_profile_button = QPushButton()
        self.apply_profile_button = QPushButton()
        self.refresh_vlan_button = QPushButton()
        self.reset_button = QPushButton()
        self.apply_ip_button = QPushButton()

        self.route_table = QTableWidget(0, len(ROUTE_HEADERS))
        self.route_table.setHorizontalHeaderLabels(ROUTE_HEADERS)
        self.route_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.route_table.setSortingEnabled(False)
        self.manual_static_only_check = QCheckBox("只显示手动配置的静态路由")
        self.persistent_only_check = QCheckBox("只显示持久静态路由")
        self.route_profile_table = QTableWidget(0, len(PROFILE_HEADERS))
        self.route_profile_table.setHorizontalHeaderLabels(PROFILE_HEADERS)
        self.route_profile_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.route_profile_name_edit = QLineEdit()
        self.route_profile_combo = QComboBox()
        self.route_edit_table = QTableWidget(0, len(EDIT_ROUTE_HEADERS))
        self.route_edit_table.setHorizontalHeaderLabels(EDIT_ROUTE_HEADERS)
        self.add_route_button = QPushButton()
        self.delete_route_button = QPushButton()
        self.save_route_profile_button = QPushButton()
        self.apply_route_button = QPushButton()
        self.remove_route_button = QPushButton()

        self._build_ui()
        self._connect_signals()
        self._apply_table_widths()
        self.retranslate()
        self.load_profiles()
        self._sync_ip_mode_fields()

    def refresh_all(self) -> None:
        if self.refresh_thread is not None:
            return
        self.refresh_button.setEnabled(False)
        self.refresh_button.setText("刷新中...")
        self.progress_bar.show()
        self._append_log("正在读取本地网卡...")
        self.refresh_thread = QThread(self)
        self.refresh_worker = NetworkRefreshWorker(self.manager)
        self.refresh_worker.moveToThread(self.refresh_thread)
        self.refresh_thread.started.connect(self.refresh_worker.run)
        self.refresh_worker.progress.connect(self._append_log)
        self.refresh_worker.finished.connect(self._refresh_finished)
        self.refresh_worker.finished.connect(self.refresh_thread.quit)
        self.refresh_worker.finished.connect(self.refresh_worker.deleteLater)
        self.refresh_thread.finished.connect(self._refresh_thread_finished)
        self.refresh_thread.finished.connect(self.refresh_thread.deleteLater)
        self.refresh_thread.start()

    def refresh_adapters(self) -> None:
        self.refresh_all()

    def refresh_routes(self) -> None:
        self.refresh_all()

    def selected_adapter(self) -> NetworkAdapterInfo | None:
        data = self.adapter_combo.currentData()
        return data if isinstance(data, NetworkAdapterInfo) else None

    def apply_ip_config(self) -> None:
        adapter = self.selected_adapter()
        if adapter is None:
            MessageBox.warning(self, self.i18n.t("network_manager.title"), "请先选择网卡。")
            return
        try:
            config = self._ip_config_from_form(adapter)
        except ValueError as exc:
            MessageBox.warning(self, self.i18n.t("network_manager.title"), str(exc))
            return
        if not self._confirm_write(self._ip_preview(adapter, config)):
            return
        try:
            self.manager.apply_ip_config(config)
            vlan_property = self._current_vlan_property(adapter)
            if vlan_property is not None:
                self.manager.set_vlan_id(adapter.name, vlan_property, self.vlan_spin.value())
            self._append_log("操作完成：IP/VLAN 配置已应用。")
            self.refresh_all()
        except PermissionError:
            self._prompt_admin()
        except Exception as exc:
            MessageBox.warning(self, self.i18n.t("network_manager.title"), str(exc))
            self._append_log(f"操作失败：{exc}")

    def reset_adapter_defaults(self) -> None:
        adapter = self.selected_adapter()
        if adapter is None:
            return
        text = (
            f"即将恢复默认网卡配置：{adapter.name}\n\n"
            "该操作会恢复 DHCP，清理静态 IP、备用 IP、网关和 VLAN。\n"
            "本地保存的配置方案不会被删除。"
        )
        if MessageBox.question(self, self.i18n.t("network_manager.reset_defaults"), text) != MessageBox.Yes:
            return
        try:
            self.manager.reset_adapter_defaults(adapter.interface_index, adapter_name=adapter.name, vlan_property=self._current_vlan_property(adapter))
            self._append_log("操作完成：网卡已恢复默认配置。")
            self.refresh_all()
        except PermissionError:
            self._prompt_admin()
        except Exception as exc:
            MessageBox.warning(self, self.i18n.t("network_manager.title"), str(exc))
            self._append_log(f"恢复默认失败：{exc}")

    def save_adapter_profile(self) -> None:
        adapter = self.selected_adapter()
        name = self.profile_name_edit.text().strip()
        if adapter is None or not name:
            return
        try:
            config = self._ip_config_from_form(adapter)
        except ValueError as exc:
            MessageBox.warning(self, self.i18n.t("network_manager.title"), str(exc))
            return
        profile = AdapterProfile(
            profile_name=name,
            adapter_match=AdapterMatch(name=adapter.name, mac=adapter.mac_address, description_keyword=adapter.description),
            mode=config.mode,
            ip_address=config.ip_address,
            prefix_length=config.prefix_length if config.mode != "dhcp" else 0,
            gateway=config.gateway,
            dns=[],
            secondary_ips=[SecondaryIp(item.ip_address, item.prefix_length) for item in config.secondary_ips],
            vlan_id=self.vlan_spin.value(),
        )
        self.profile_store.upsert(profile)
        self.load_profiles()
        self._append_log(f"已保存网卡配置方案：{name}")

    def apply_adapter_profile(self) -> None:
        profile = self.profile_combo.currentData()
        if not isinstance(profile, AdapterProfile):
            return
        self.mode_combo.setCurrentText("DHCP" if profile.mode == "dhcp" else "静态IP")
        if profile.mode != "dhcp":
            self.ip_edit.setText(profile.ip_address)
            self.prefix_edit.setText(str(profile.prefix_length))
            self.gateway_edit.setText(profile.gateway)
            self.secondary_edit.setPlainText("\n".join(f"{item.ip_address}/{item.prefix_length}" for item in profile.secondary_ips))
        self.vlan_spin.setValue(profile.vlan_id)
        self.apply_ip_config()

    def load_profiles(self) -> None:
        self.profile_combo.clear()
        for profile in self.profile_store.load():
            self.profile_combo.addItem(profile.profile_name, profile)
        self.route_profile_combo.clear()
        self.route_profile_table.setRowCount(0)
        for profile in self.route_store.load():
            self.route_profile_combo.addItem(profile.profile_name, profile)
            row = self.route_profile_table.rowCount()
            self.route_profile_table.insertRow(row)
            values = [profile.profile_name, str(len(profile.routes)), "否", ""]
            for column, value in enumerate(values):
                self._set_table_item(self.route_profile_table, row, column, value)

    def add_route_row(self) -> None:
        row = self.route_edit_table.rowCount()
        self.route_edit_table.insertRow(row)
        defaults = ["192.168.105.0/24", "192.168.105.1", self._selected_adapter_name(), "10", "是", ""]
        for column, value in enumerate(defaults):
            self._set_table_item(self.route_edit_table, row, column, value)

    def delete_route_row(self) -> None:
        rows = sorted({item.row() for item in self.route_edit_table.selectedItems()}, reverse=True)
        for row in rows:
            self.route_edit_table.removeRow(row)

    def save_route_profile(self) -> None:
        name = self.route_profile_name_edit.text().strip() or self.route_profile_combo.currentText().strip()
        if not name:
            return
        try:
            entries = self._route_entries_from_table()
        except ValueError as exc:
            MessageBox.warning(self, self.i18n.t("network_manager.title"), str(exc))
            return
        self.route_store.upsert(RouteProfile(profile_name=name, routes=entries))
        self.load_profiles()
        self._append_log(f"已保存路由方案：{name}")

    def apply_route_profile(self) -> None:
        routes = self._selected_or_edited_routes()
        if not routes:
            return
        preview = "\n".join(f"{row.destination_prefix} -> {row.next_hop} ({row.interface_alias})" for row in routes)
        if not self._confirm_write(f"即将写入静态路由：\n{preview}"):
            return
        try:
            for route in routes:
                self.manager.apply_route(route)
            self._append_log("操作完成：静态路由已写入。")
            self.refresh_all()
        except PermissionError:
            self._prompt_admin()
        except Exception as exc:
            MessageBox.warning(self, self.i18n.t("network_manager.title"), str(exc))
            self._append_log(f"路由写入失败：{exc}")

    def remove_route_profile(self) -> None:
        routes = self._selected_or_edited_routes()
        if not routes:
            return
        preview = "\n".join(f"{row.destination_prefix} -> {row.next_hop} ({row.interface_alias})" for row in routes)
        if not self._confirm_write(f"即将删除该方案管理的静态路由：\n{preview}"):
            return
        try:
            for route in routes:
                self.manager.remove_route(route)
            self._append_log("操作完成：静态路由已删除。")
            self.refresh_all()
        except PermissionError:
            self._prompt_admin()
        except Exception as exc:
            MessageBox.warning(self, self.i18n.t("network_manager.title"), str(exc))
            self._append_log(f"路由删除失败：{exc}")

    def open_network_connections(self) -> None:
        subprocess.Popen(build_open_network_connections_command())

    def request_admin_network_manager(self) -> None:
        if is_admin():
            self._append_log("当前已经是管理员权限。")
            self._sync_permission_state()
            return
        if self.admin_launch_pending:
            self._append_log("管理员权限启动请求已发送，请在 UAC 窗口中确认。")
            return
        self.admin_launch_pending = True
        self.admin_button.setEnabled(False)
        self._append_log("正在请求管理员权限...")
        result = open_network_manager_as_admin(app_root=self.paths.app_root)
        if result.success:
            self._append_log("已请求管理员权限，普通窗口即将关闭。")
            QTimer.singleShot(800, self._quit_normal_app)
            return
        self.admin_launch_pending = False
        self._sync_permission_state()
        message = f"管理员权限启动失败：{result.message}"
        self._append_log(message)
        MessageBox.warning(self, self.i18n.t("network_manager.title"), message)

    def retranslate(self) -> None:
        self.refresh_button.setText("刷新")
        self.open_connections_button.setText(self.i18n.t("network_manager.open_connections"))
        self.save_profile_button.setText(self.i18n.t("network_manager.save_profile"))
        self.apply_profile_button.setText(self.i18n.t("network_manager.apply_profile"))
        self.refresh_vlan_button.setText(self.i18n.t("network_manager.detect_vlan"))
        self.reset_button.setText(self.i18n.t("network_manager.reset_defaults"))
        self.apply_ip_button.setText(self.i18n.t("network_manager.apply"))
        self.add_route_button.setText("新增路由")
        self.delete_route_button.setText("删除路由")
        self.save_route_profile_button.setText(self.i18n.t("network_manager.save_route_profile"))
        self.apply_route_button.setText(self.i18n.t("network_manager.apply_route"))
        self.remove_route_button.setText(self.i18n.t("network_manager.remove_route"))
        self.tabs.setTabText(0, self.i18n.t("network_manager.adapter_config"))
        if self.tabs.count() > 1:
            self.tabs.setTabText(1, self.i18n.t("network_manager.route_config"))
        self._apply_button_icons()
        self._sync_permission_state()

    def _apply_button_icons(self) -> None:
        for button, icon_name in (
            (self.refresh_button, "SYNC"),
            (self.open_connections_button, "FOLDER"),
            (self.admin_button, "SETTING"),
            (self.save_profile_button, "SAVE"),
            (self.apply_profile_button, "ACCEPT"),
            (self.refresh_vlan_button, "SYNC"),
            (self.reset_button, "RETURN"),
            (self.apply_ip_button, "EDIT"),
            (self.add_route_button, "ADD"),
            (self.delete_route_button, "DELETE"),
            (self.save_route_profile_button, "SAVE"),
            (self.apply_route_button, "ACCEPT"),
            (self.remove_route_button, "DELETE"),
        ):
            apply_button_icon(button, icon_name)

    def _build_ui(self) -> None:
        top = QHBoxLayout()
        top.addWidget(self.permission_label)
        top.addWidget(self.status_label, 1)
        top.addWidget(self.progress_bar)
        top.addWidget(self.refresh_button)
        top.addWidget(self.open_connections_button)
        top.addWidget(self.admin_button)

        adapter_page = QWidget()
        adapter_layout = QVBoxLayout(adapter_page)
        adapter_splitter = QSplitter(Qt.Vertical)
        adapter_splitter.addWidget(self.adapter_table)
        adapter_layout.addWidget(adapter_splitter)
        config_panel = QWidget()
        config_layout = QVBoxLayout(config_panel)
        form_group = QGroupBox("IP / VLAN 配置")
        form = QFormLayout(form_group)
        form.addRow("网卡选择", self.adapter_combo)
        form.addRow("IP模式", self.mode_combo)
        form.addRow("IP地址", self.ip_edit)
        form.addRow("前缀长度/子网掩码", self.prefix_edit)
        form.addRow("默认网关", self.gateway_edit)
        form.addRow("备用IP", self.secondary_edit)
        form.addRow("VLAN ID", self.vlan_spin)
        config_layout.addWidget(form_group)
        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel("方案名称"))
        profile_row.addWidget(self.profile_name_edit)
        profile_row.addWidget(self.save_profile_button)
        profile_row.addWidget(self.profile_combo)
        profile_row.addWidget(self.apply_profile_button)
        profile_row.addWidget(self.refresh_vlan_button)
        profile_row.addWidget(self.reset_button)
        profile_row.addWidget(self.apply_ip_button)
        config_layout.addLayout(profile_row)
        config_layout.addStretch(1)
        adapter_splitter.addWidget(config_panel)
        adapter_splitter.setStretchFactor(0, 4)
        adapter_splitter.setStretchFactor(1, 5)
        adapter_splitter.setSizes([320, 420])

        route_page = QWidget(self)
        route_layout = QVBoxLayout(route_page)
        route_layout.addWidget(QLabel("当前路由表"))
        route_filter_row = QHBoxLayout()
        route_filter_row.addWidget(self.manual_static_only_check)
        route_filter_row.addWidget(self.persistent_only_check)
        route_filter_row.addStretch(1)
        route_layout.addLayout(route_filter_row)
        route_layout.addWidget(self.route_table)
        route_layout.addWidget(QLabel("静态路由方案"))
        route_layout.addWidget(self.route_profile_table)
        edit_group = QGroupBox("路由编辑区")
        edit_layout = QVBoxLayout(edit_group)
        edit_top = QHBoxLayout()
        edit_top.addWidget(QLabel("方案名称"))
        edit_top.addWidget(self.route_profile_name_edit)
        edit_top.addWidget(self.route_profile_combo)
        edit_top.addWidget(self.add_route_button)
        edit_top.addWidget(self.delete_route_button)
        edit_top.addWidget(self.save_route_profile_button)
        edit_top.addWidget(self.apply_route_button)
        edit_top.addWidget(self.remove_route_button)
        edit_layout.addLayout(edit_top)
        edit_layout.addWidget(self.route_edit_table)
        route_layout.addWidget(edit_group)

        self.tabs.addTab(adapter_page, "")
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        main_splitter = QSplitter(Qt.Vertical)
        main_splitter.addWidget(self.tabs)
        log_panel = QWidget()
        log_layout = QVBoxLayout(log_panel)
        log_layout.addWidget(QLabel("操作日志"))
        log_layout.addWidget(self.log_text)
        main_splitter.addWidget(log_panel)
        main_splitter.setStretchFactor(0, 4)
        main_splitter.setStretchFactor(1, 1)
        main_splitter.setSizes([720, 180])
        layout.addWidget(main_splitter, 1)

    def _connect_signals(self) -> None:
        self.refresh_button.clicked.connect(self.refresh_all)
        self.open_connections_button.clicked.connect(self.open_network_connections)
        self.admin_button.clicked.connect(self.request_admin_network_manager)
        self.adapter_combo.currentIndexChanged.connect(self._adapter_changed)
        self.mode_combo.currentTextChanged.connect(self._sync_ip_mode_fields)
        self.refresh_vlan_button.clicked.connect(self._adapter_changed)
        self.apply_ip_button.clicked.connect(self.apply_ip_config)
        self.reset_button.clicked.connect(self.reset_adapter_defaults)
        self.save_profile_button.clicked.connect(self.save_adapter_profile)
        self.apply_profile_button.clicked.connect(self.apply_adapter_profile)
        self.manual_static_only_check.toggled.connect(self._fill_route_table)
        self.persistent_only_check.toggled.connect(self._fill_route_table)
        self.add_route_button.clicked.connect(self.add_route_row)
        self.delete_route_button.clicked.connect(self.delete_route_row)
        self.save_route_profile_button.clicked.connect(self.save_route_profile)
        self.apply_route_button.clicked.connect(self.apply_route_profile)
        self.remove_route_button.clicked.connect(self.remove_route_profile)

    def _apply_table_widths(self) -> None:
        for table, widths in ((self.adapter_table, ADAPTER_WIDTHS), (self.route_table, ROUTE_WIDTHS)):
            table.setWordWrap(False)
            table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            for index, width in enumerate(widths):
                table.setColumnWidth(index, width)
            header = table.horizontalHeader()
            header.setSectionResizeMode(QHeaderView.Interactive)
            header.setStretchLastSection(False)
            header.setSectionsMovable(False)
        self.route_profile_table.setColumnWidth(0, 220)
        self.route_edit_table.setColumnWidth(0, 180)
        self.route_edit_table.setColumnWidth(1, 160)
        self.route_edit_table.setColumnWidth(2, 180)

    def _refresh_finished(self, adapters: object, routes: object, error: str) -> None:
        if error:
            self._append_log(f"刷新失败：{error}")
        else:
            self.adapters = list(adapters)
            self.routes = list(routes)
            self._fill_adapter_table()
            self._fill_route_table()
            self._append_log("刷新完成。")
        self._sync_permission_state()

    def _refresh_thread_finished(self) -> None:
        self.refresh_thread = None
        self.refresh_worker = None
        self.progress_bar.hide()
        self.refresh_button.setEnabled(True)
        self.refresh_button.setText("刷新")

    def _fill_adapter_table(self) -> None:
        self.adapter_combo.clear()
        self.adapter_table.setRowCount(0)
        for adapter in self.adapters:
            if not adapter.excluded:
                label = " | ".join(
                    [
                        adapter.name,
                        ", ".join(adapter.ipv4_addresses) or "-",
                        adapter.description or "-",
                        "/".join(self._display_tags(adapter)) or "-",
                    ]
                )
                self.adapter_combo.addItem(label, adapter)
            row = self.adapter_table.rowCount()
            self.adapter_table.insertRow(row)
            values = [
                adapter.name,
                adapter.description,
                adapter.mac_address,
                self._display_status(adapter.status),
                adapter.link_speed,
                ", ".join(adapter.ipv4_addresses),
                ", ".join(adapter.gateways),
                "/".join(self._display_tags(adapter)) if not adapter.excluded else adapter.exclude_reason,
            ]
            for column, value in enumerate(values):
                self._set_table_item(self.adapter_table, row, column, value or "-")

    def _fill_route_table(self) -> None:
        self.route_table.setRowCount(0)
        routes = sorted(self.routes, key=self._route_sort_key)
        if self.manual_static_only_check.isChecked():
            routes = [route for route in routes if self._is_manual_static_route(route)]
        if self.persistent_only_check.isChecked():
            routes = [route for route in routes if self._is_persistent_route(route)]
        for route in routes:
            row = self.route_table.rowCount()
            self.route_table.insertRow(row)
            values = [
                str(route.order_index + 1),
                route.destination_prefix,
                route.next_hop,
                route.interface_alias,
                str(route.route_metric),
                route.policy_store,
                "是" if route.persistent else "否",
                route.source,
            ]
            for column, value in enumerate(values):
                self._set_table_item(self.route_table, row, column, value or "-")

    def _adapter_changed(self) -> None:
        adapter = self.selected_adapter()
        if adapter is None:
            return
        if self.mode_combo.currentText().upper() == "DHCP":
            self._sync_ip_mode_fields()
            return
        self.ip_edit.setText(adapter.ipv4_addresses[0].split("/", 1)[0] if adapter.ipv4_addresses else "")
        if adapter.ipv4_addresses and "/" in adapter.ipv4_addresses[0]:
            self.prefix_edit.setText(adapter.ipv4_addresses[0].split("/", 1)[1])
        self.gateway_edit.setText(adapter.gateways[0] if adapter.gateways else "")
        try:
            vlan_property = self.manager.get_vlan_property(adapter.name)
            self.vlan_spin.setEnabled(vlan_property is not None)
            self._append_log("已检测到 VLAN 配置项。" if vlan_property else "该网卡驱动未检测到 VLAN ID 配置项。")
        except Exception as exc:
            self.vlan_spin.setEnabled(False)
            self._append_log(f"VLAN 检测失败：{exc}")

    def _ip_config_from_form(self, adapter: NetworkAdapterInfo) -> AdapterIpConfig:
        mode = "dhcp" if self.mode_combo.currentText().upper() == "DHCP" else "static"
        if mode == "dhcp":
            return AdapterIpConfig(interface_index=adapter.interface_index, mode="dhcp", dns_servers=[])
        prefix = parse_prefix_or_netmask(self.prefix_edit.text())
        secondary = []
        for raw in self.secondary_edit.toPlainText().splitlines():
            text = raw.strip()
            if not text:
                continue
            ip, _, prefix_text = text.partition("/")
            secondary.append(SecondaryIpConfig(ip.strip(), parse_prefix_or_netmask(prefix_text or str(prefix))))
        return AdapterIpConfig(
            interface_index=adapter.interface_index,
            mode=mode,
            ip_address=self.ip_edit.text().strip(),
            prefix_length=prefix,
            gateway=self.gateway_edit.text().strip(),
            dns_servers=[],
            secondary_ips=secondary,
        )

    def _route_entries_from_table(self) -> list[RouteProfileEntry]:
        entries: list[RouteProfileEntry] = []
        for row in range(self.route_edit_table.rowCount()):
            destination = self._table_text(self.route_edit_table, row, 0)
            next_hop = self._table_text(self.route_edit_table, row, 1)
            interface = self._table_text(self.route_edit_table, row, 2) or self._selected_adapter_name()
            metric = int(self._table_text(self.route_edit_table, row, 3) or "10")
            persistent = self._table_text(self.route_edit_table, row, 4) != "否"
            remark = self._table_text(self.route_edit_table, row, 5)
            if destination:
                entries.append(RouteProfileEntry(destination, next_hop, interface, metric, persistent, remark))
        if not entries:
            raise ValueError("请至少新增一条路由。")
        return entries

    def _selected_or_edited_routes(self) -> list[RouteConfig]:
        profile = self.route_profile_combo.currentData()
        if isinstance(profile, RouteProfile):
            return [RouteConfig(row.destination_prefix, row.next_hop, row.interface_alias, row.metric, row.persistent) for row in profile.routes]
        return [RouteConfig(row.destination_prefix, row.next_hop, row.interface_alias, row.metric, row.persistent) for row in self._route_entries_from_table()]

    def _current_vlan_property(self, adapter: NetworkAdapterInfo) -> VlanProperty | None:
        if not self.vlan_spin.isEnabled():
            return None
        try:
            return self.manager.get_vlan_property(adapter.name)
        except Exception:
            return None

    def _ip_preview(self, adapter: NetworkAdapterInfo, config: AdapterIpConfig) -> str:
        return (
            f"即将修改网卡：{adapter.name}\n"
            f"模式：{config.mode}\n"
            f"IP地址：{config.ip_address or '-'}\n"
            f"网关：{config.gateway or '-'}\n"
            f"备用IP：{', '.join(item.ip_address for item in config.secondary_ips) or '-'}\n"
            f"VLAN ID：{self.vlan_spin.value() if self.vlan_spin.isEnabled() else '-'}"
        )

    def _confirm_write(self, preview: str) -> bool:
        if not is_admin():
            self._prompt_admin()
            return False
        return MessageBox.question(self, self.i18n.t("network_manager.confirm"), preview) == MessageBox.Yes

    def _prompt_admin(self) -> None:
        MessageBox.information(self, self.i18n.t("network_manager.title"), "该操作需要管理员权限，请点击“以管理员权限打开网络管理”。")

    def _sync_permission_state(self) -> None:
        admin = is_admin()
        self.permission_label.setText("当前权限：管理员" if admin else "当前权限：普通")
        self.admin_button.setText("当前已经是管理员" if admin else self.i18n.t("network_manager.open_as_admin"))
        self.admin_button.setEnabled((not admin) and (not self.admin_launch_pending))
        for button in (self.apply_ip_button, self.apply_profile_button, self.reset_button, self.apply_route_button, self.remove_route_button):
            button.setEnabled(admin)

    def _quit_normal_app(self) -> None:
        app = QApplication.instance()
        if app is not None:
            for widget in app.topLevelWidgets():
                if hasattr(widget, "app_is_exiting"):
                    setattr(widget, "app_is_exiting", True)
            app.quit()

    def _sync_ip_mode_fields(self) -> None:
        dhcp = self.mode_combo.currentText().upper() == "DHCP"
        if dhcp:
            self.ip_edit.clear()
            self.prefix_edit.clear()
            self.gateway_edit.clear()
            self.secondary_edit.clear()
        for widget in (self.ip_edit, self.prefix_edit, self.gateway_edit, self.secondary_edit):
            widget.setEnabled(not dhcp)
        self.vlan_spin.setEnabled(True)

    def _is_persistent_route(self, route: RouteInfo) -> bool:
        return route.persistent or route.policy_store.lower() == "persistentstore"

    def _route_sort_key(self, route: RouteInfo) -> tuple[int, int]:
        return (0 if route.destination_prefix == "0.0.0.0/0" else 1, route.order_index)

    def _is_manual_static_route(self, route: RouteInfo) -> bool:
        source = route.source.lower()
        policy = route.policy_store.lower()
        next_hop = route.next_hop.strip().lower()
        destination = route.destination_prefix.strip().lower()
        if self._is_persistent_route(route):
            return True
        if any(token in source for token in ("manual", "profile", "persistent", "route add")):
            return True
        if policy == "persistentstore":
            return True
        if next_hop in {"", "0.0.0.0", "::", "on-link", "onlink"}:
            return False
        if destination.startswith(("127.", "224.", "255.")) or destination in {"0.0.0.0/0"}:
            return False
        return True

    def _append_log(self, text: str) -> None:
        self.status_label.setText(text)
        self.log_text.append(text)

    def _set_table_item(self, table: QTableWidget, row: int, column: int, value: str) -> None:
        item = QTableWidgetItem(value)
        item.setToolTip(value)
        table.setItem(row, column, item)

    def _table_text(self, table: QTableWidget, row: int, column: int) -> str:
        item = table.item(row, column)
        return item.text().strip() if item is not None else ""

    def _selected_adapter_name(self) -> str:
        adapter = self.selected_adapter()
        return adapter.name if adapter is not None else ""

    def _display_status(self, value: str) -> str:
        mapping = {"up": "已连接", "connected": "已连接", "disabled": "已禁用", "disconnected": "未连接"}
        return mapping.get(value.lower(), value)

    def _display_tags(self, adapter: NetworkAdapterInfo) -> list[str]:
        mapping = {"PCI": "板载", "USB": "USB", "Ethernet": "以太网", "Connected": "已连接", "IPv4": "IPv4", "Hardware": "物理"}
        tags = [mapping.get(tag, tag) for tag in adapter.tags]
        if adapter.score >= 100:
            tags.insert(0, "推荐")
        return tags
def _network_page_new_interface_combo(self, selected_alias: str = "", selected_index: int = 0) -> QComboBox:
    combo = QComboBox()
    for adapter in self.adapters:
        if adapter.excluded:
            continue
        ip_text = ", ".join(adapter.ipv4_addresses) or "-"
        label = f"{'/'.join(self._display_tags(adapter)) or '-'} | {ip_text} | {adapter.description or adapter.name}"
        combo.addItem(label, (adapter.name, adapter.interface_index))
    if combo.count() == 0:
        combo.addItem(selected_alias or self._selected_adapter_name() or "-", (selected_alias or self._selected_adapter_name(), selected_index))
    for index in range(combo.count()):
        alias, interface_index = combo.itemData(index)
        if (selected_index and interface_index == selected_index) or (selected_alias and alias == selected_alias):
            combo.setCurrentIndex(index)
            break
    return combo


def _network_page_new_persistent_checkbox(self, checked: bool = True) -> QCheckBox:
    checkbox = QCheckBox()
    checkbox.setChecked(checked)
    checkbox.setStyleSheet("QCheckBox { margin-left: 18px; }")
    return checkbox


def _network_page_add_route_row(self) -> None:
    row = self.route_edit_table.rowCount()
    self.route_edit_table.insertRow(row)
    self.route_edit_table.setRowHeight(row, 38)
    defaults = ["192.168.105.0", "255.255.255.0", "192.168.105.1", "", "10", "", ""]
    for column, value in enumerate(defaults):
        self._set_table_item(self.route_edit_table, row, column, value)
    self.route_edit_table.setCellWidget(row, 3, self._new_interface_combo())
    self.route_edit_table.setCellWidget(row, 5, self._new_persistent_checkbox(True))


def _network_page_route_interface_data(self, row: int) -> tuple[str, int]:
    widget = self.route_edit_table.cellWidget(row, 3)
    if isinstance(widget, QComboBox):
        data = widget.currentData()
        if isinstance(data, tuple):
            return str(data[0] or ""), int(data[1] or 0)
        return widget.currentText().strip(), 0
    return self._table_text(self.route_edit_table, row, 3) or self._selected_adapter_name(), 0


def _network_page_route_persistent_checked(self, row: int) -> bool:
    widget = self.route_edit_table.cellWidget(row, 5)
    if isinstance(widget, QCheckBox):
        return widget.isChecked()
    return self._table_text(self.route_edit_table, row, 5) not in {"否", "No", "False", "0"}


def _network_page_route_entries_from_table(self) -> list[RouteProfileEntry]:
    entries: list[RouteProfileEntry] = []
    for row in range(self.route_edit_table.rowCount()):
        destination = self._table_text(self.route_edit_table, row, 0)
        netmask = self._table_text(self.route_edit_table, row, 1)
        next_hop = self._table_text(self.route_edit_table, row, 2)
        interface, interface_index = self._route_interface_data(row)
        metric = int(self._table_text(self.route_edit_table, row, 4) or "10")
        persistent = self._route_persistent_checked(row)
        remark = self._table_text(self.route_edit_table, row, 6)
        if destination:
            prefix = build_destination_prefix(destination, netmask)
            entries.append(RouteProfileEntry(prefix, next_hop, interface, metric, persistent, remark, netmask, interface_index))
    if not entries:
        raise ValueError("请至少新增一条路由。")
    return entries


def _network_page_selected_or_edited_routes(self) -> list[RouteConfig]:
    profile = self.route_profile_combo.currentData()
    if isinstance(profile, RouteProfile):
        return [RouteConfig(row.destination_prefix, row.next_hop, row.interface_alias, row.metric, row.persistent, row.interface_index) for row in profile.routes]
    return [RouteConfig(row.destination_prefix, row.next_hop, row.interface_alias, row.metric, row.persistent, row.interface_index) for row in self._route_entries_from_table()]


def _network_page_route_sort_key(self, route: RouteInfo) -> tuple[int, int, int, int]:
    try:
        network = ipaddress.IPv4Network(route.destination_prefix, strict=False)
        ip_value = int(network.network_address)
        prefix = int(network.prefixlen)
    except Exception:
        ip_value = 2**32 - 1
        prefix = 32
    return (0 if route.destination_prefix == "0.0.0.0/0" else 1, ip_value, prefix, route.order_index)


def _network_page_fill_route_table(self) -> None:
    self.route_table.setSortingEnabled(False)
    self.route_table.setRowCount(0)
    routes = sorted(self.routes, key=self._route_sort_key)
    if self.manual_static_only_check.isChecked():
        routes = [route for route in routes if self._is_manual_static_route(route)]
    if self.persistent_only_check.isChecked():
        routes = [route for route in routes if self._is_persistent_route(route)]
    for display_index, route in enumerate(routes, start=1):
        row = self.route_table.rowCount()
        self.route_table.insertRow(row)
        values = [
            str(display_index),
            route.destination_prefix,
            route.next_hop,
            route.interface_alias,
            str(route.route_metric),
            route.policy_store,
            "是" if route.persistent else "否",
            route.source,
        ]
        for column, value in enumerate(values):
            self._set_table_item(self.route_table, row, column, value or "-")


def _network_page_current_vlan_property(self, adapter: NetworkAdapterInfo) -> VlanProperty | None:
    if not self.vlan_spin.isEnabled():
        return None
    try:
        return self.manager.get_vlan_property(adapter.name)
    except Exception:
        return None


def _network_page_adapter_changed(self) -> None:
    adapter = self.selected_adapter()
    if adapter is None:
        return
    if self.mode_combo.currentText().upper() == "DHCP":
        self._sync_ip_mode_fields()
    else:
        self.ip_edit.setText(adapter.ipv4_addresses[0].split("/", 1)[0] if adapter.ipv4_addresses else "")
        if adapter.ipv4_addresses and "/" in adapter.ipv4_addresses[0]:
            self.prefix_edit.setText(adapter.ipv4_addresses[0].split("/", 1)[1])
        self.gateway_edit.setText(adapter.gateways[0] if adapter.gateways else "")
    try:
        capability = self.manager.get_vlan_capability(adapter.name)
        self.vlan_spin.setEnabled(capability.mode == "vlan_id_numeric")
        self._append_log(capability.message)
    except Exception as exc:
        self.vlan_spin.setEnabled(False)
        self._append_log(f"VLAN 检测失败：{exc}")


def _network_page_apply_table_widths(self) -> None:
    for table, widths in ((self.adapter_table, ADAPTER_WIDTHS), (self.route_table, ROUTE_WIDTHS)):
        table.setWordWrap(False)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        for index, width in enumerate(widths):
            table.setColumnWidth(index, width)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(False)
        header.setSectionsMovable(False)
    self.route_profile_table.setColumnWidth(0, 220)
    route_widths = [170, 130, 150, 240, 80, 70, 160]
    for index, width in enumerate(route_widths):
        self.route_edit_table.setColumnWidth(index, width)
    self.route_edit_table.verticalHeader().setDefaultSectionSize(38)


NetworkAdapterRoutePage._new_interface_combo = _network_page_new_interface_combo
NetworkAdapterRoutePage._new_persistent_checkbox = _network_page_new_persistent_checkbox
NetworkAdapterRoutePage.add_route_row = _network_page_add_route_row
NetworkAdapterRoutePage._route_interface_data = _network_page_route_interface_data
NetworkAdapterRoutePage._route_persistent_checked = _network_page_route_persistent_checked
NetworkAdapterRoutePage._route_entries_from_table = _network_page_route_entries_from_table
NetworkAdapterRoutePage._selected_or_edited_routes = _network_page_selected_or_edited_routes
NetworkAdapterRoutePage._route_sort_key = _network_page_route_sort_key
NetworkAdapterRoutePage._fill_route_table = _network_page_fill_route_table
NetworkAdapterRoutePage._current_vlan_property = _network_page_current_vlan_property
NetworkAdapterRoutePage._adapter_changed = _network_page_adapter_changed
NetworkAdapterRoutePage._apply_table_widths = _network_page_apply_table_widths


def _network_page_connect_signals(self) -> None:
    self.refresh_button.clicked.connect(self.refresh_all)
    self.open_connections_button.clicked.connect(self.open_network_connections)
    self.admin_button.clicked.connect(self.request_admin_network_manager)
    self.adapter_combo.currentIndexChanged.connect(self._adapter_changed)
    self.mode_combo.currentTextChanged.connect(self._sync_ip_mode_fields)
    self.refresh_vlan_button.clicked.connect(self._adapter_changed)
    self.apply_ip_button.clicked.connect(self.apply_ip_config)
    self.reset_button.clicked.connect(self.reset_adapter_defaults)
    self.save_profile_button.clicked.connect(self.save_adapter_profile)
    self.apply_profile_button.clicked.connect(self.apply_adapter_profile)
    self.profile_combo.currentIndexChanged.connect(self._adapter_profile_combo_changed)
    self.manual_static_only_check.toggled.connect(self._fill_route_table)
    self.persistent_only_check.toggled.connect(self._fill_route_table)
    self.add_route_button.clicked.connect(self.add_route_row)
    self.delete_route_button.clicked.connect(self.delete_route_row)
    self.save_route_profile_button.clicked.connect(self.save_route_profile)
    self.apply_route_button.clicked.connect(self.apply_route_profile)
    self.remove_route_button.clicked.connect(self.remove_route_profile)
    self.route_profile_table.itemSelectionChanged.connect(self._route_profile_table_selection_changed)
    self.route_profile_table.itemDoubleClicked.connect(lambda *_args: self._route_profile_table_selection_changed())
    self.route_profile_combo.currentIndexChanged.connect(self._route_profile_combo_changed)
    self.route_edit_table.setContextMenuPolicy(Qt.CustomContextMenu)
    self.route_edit_table.customContextMenuRequested.connect(self._show_route_edit_context_menu)
    original_key_press = self.route_edit_table.keyPressEvent

    def key_press(event):
        if event.key() == Qt.Key_Delete:
            self.delete_route_row()
            return
        original_key_press(event)

    self.route_edit_table.keyPressEvent = key_press


def _network_page_load_profiles(self) -> None:
    current_adapter_profile = self.profile_combo.currentText().strip()
    current_route_profile = self.route_profile_combo.currentText().strip()
    self.profile_combo.blockSignals(True)
    self.profile_combo.clear()
    for profile in self.profile_store.load():
        self.profile_combo.addItem(profile.profile_name, profile)
    if current_adapter_profile:
        index = self.profile_combo.findText(current_adapter_profile)
        if index >= 0:
            self.profile_combo.setCurrentIndex(index)
    self.profile_combo.blockSignals(False)

    self.route_profile_combo.blockSignals(True)
    self.route_profile_combo.clear()
    self.route_profile_table.setRowCount(0)
    for profile in self.route_store.load():
        self.route_profile_combo.addItem(profile.profile_name, profile)
        row = self.route_profile_table.rowCount()
        self.route_profile_table.insertRow(row)
        values = [profile.profile_name, str(len(profile.routes)), "是", ""]
        for column, value in enumerate(values):
            self._set_table_item(self.route_profile_table, row, column, value)
    if current_route_profile:
        index = self.route_profile_combo.findText(current_route_profile)
        if index >= 0:
            self.route_profile_combo.setCurrentIndex(index)
            self.route_profile_table.selectRow(index)
    self.route_profile_combo.blockSignals(False)


def _network_page_adapter_profile_combo_changed(self) -> None:
    profile = self.profile_combo.currentData()
    if isinstance(profile, AdapterProfile):
        self.load_adapter_profile_into_form(profile)


def _network_page_find_adapter_for_profile(self, profile: AdapterProfile) -> NetworkAdapterInfo | None:
    match = profile.adapter_match
    if match.mac:
        for adapter in self.adapters:
            if not adapter.excluded and adapter.mac_address.lower() == match.mac.lower():
                return adapter
    if match.name:
        for adapter in self.adapters:
            if not adapter.excluded and adapter.name == match.name:
                return adapter
    if match.description_keyword:
        keyword = match.description_keyword.lower()
        for adapter in self.adapters:
            if not adapter.excluded and keyword in adapter.description.lower():
                return adapter
    return self.selected_adapter()


def _network_page_load_adapter_profile_into_form(self, profile: AdapterProfile) -> None:
    adapter = self._find_adapter_for_profile(profile)
    if adapter is not None:
        for index in range(self.adapter_combo.count()):
            data = self.adapter_combo.itemData(index)
            if isinstance(data, NetworkAdapterInfo) and data.name == adapter.name:
                self.adapter_combo.setCurrentIndex(index)
                break
    else:
        self._append_log("未找到该方案原来使用的网卡，请手动选择网卡。")
    self.mode_combo.setCurrentText("DHCP" if profile.mode == "dhcp" else "静态IP")
    if profile.mode == "dhcp":
        self.ip_edit.clear()
        self.prefix_edit.clear()
        self.gateway_edit.clear()
        self.secondary_edit.clear()
    else:
        self.ip_edit.setText(profile.ip_address)
        self.prefix_edit.setText(str(profile.prefix_length))
        self.gateway_edit.setText(profile.gateway)
        self.secondary_edit.setPlainText("\n".join(f"{item.ip_address}/{item.prefix_length}" for item in profile.secondary_ips))
    self.vlan_spin.setValue(profile.vlan_id)
    self._sync_ip_mode_fields()


def _network_page_apply_adapter_profile(self) -> None:
    profile = self.profile_combo.currentData()
    if isinstance(profile, AdapterProfile):
        self.load_adapter_profile_into_form(profile)
    self.apply_ip_config()


def _network_page_route_profile_combo_changed(self) -> None:
    if getattr(self, "_loading_route_profile", False):
        return
    profile = self.route_profile_combo.currentData()
    if isinstance(profile, RouteProfile):
        self.load_route_profile_into_editor(profile)


def _network_page_route_profile_table_selection_changed(self) -> None:
    if getattr(self, "_loading_route_profile", False):
        return
    row = self.route_profile_table.currentRow()
    if row < 0:
        return
    profile_name = self._table_text(self.route_profile_table, row, 0)
    for index in range(self.route_profile_combo.count()):
        profile = self.route_profile_combo.itemData(index)
        if isinstance(profile, RouteProfile) and profile.profile_name == profile_name:
            self.route_profile_combo.setCurrentIndex(index)
            self.load_route_profile_into_editor(profile)
            break


def _network_page_load_route_profile_into_editor(self, profile: RouteProfile) -> None:
    self._loading_route_profile = True
    try:
        self.route_profile_name_edit.setText(profile.profile_name)
        combo_index = self.route_profile_combo.findText(profile.profile_name)
        if combo_index >= 0:
            self.route_profile_combo.setCurrentIndex(combo_index)
        self.route_edit_table.setRowCount(0)
        for entry in profile.routes:
            self._append_route_entry_to_editor(entry)
    finally:
        self._loading_route_profile = False


def _network_page_append_route_entry_to_editor(self, entry: RouteProfileEntry) -> None:
    row = self.route_edit_table.rowCount()
    self.route_edit_table.insertRow(row)
    self.route_edit_table.setRowHeight(row, 38)
    destination, netmask = self._split_destination_prefix(entry.destination_prefix, entry.netmask)
    values = [destination, netmask, entry.next_hop, "", str(entry.metric), "", entry.remark]
    for column, value in enumerate(values):
        self._set_table_item(self.route_edit_table, row, column, value)
    self.route_edit_table.setCellWidget(row, 3, self._new_interface_combo(entry.interface_alias, entry.interface_index))
    self.route_edit_table.setCellWidget(row, 5, self._new_persistent_checkbox(entry.persistent))


def _network_page_split_destination_prefix(self, destination_prefix: str, netmask: str = "") -> tuple[str, str]:
    try:
        network = ipaddress.IPv4Network(destination_prefix, strict=False)
        return str(network.network_address), netmask or str(network.netmask)
    except Exception:
        return destination_prefix, netmask


def _network_page_add_route_row_inheriting_previous(self) -> None:
    row = self.route_edit_table.rowCount()
    previous = row - 1
    next_hop = self._table_text(self.route_edit_table, previous, 2) if previous >= 0 else ""
    metric = self._table_text(self.route_edit_table, previous, 4) if previous >= 0 else "10"
    persistent = self._route_persistent_checked(previous) if previous >= 0 else True
    selected_alias, selected_index = self._route_interface_data(previous) if previous >= 0 else ("", 0)
    self.route_edit_table.insertRow(row)
    self.route_edit_table.setRowHeight(row, 38)
    values = ["", "255.255.255.0", next_hop, "", metric or "10", "", ""]
    for column, value in enumerate(values):
        self._set_table_item(self.route_edit_table, row, column, value)
    self.route_edit_table.setCellWidget(row, 3, self._new_interface_combo(selected_alias, selected_index))
    self.route_edit_table.setCellWidget(row, 5, self._new_persistent_checkbox(persistent))


def _network_page_selected_or_edited_routes_from_editor(self) -> list[RouteConfig]:
    return [RouteConfig(row.destination_prefix, row.next_hop, row.interface_alias, row.metric, row.persistent, row.interface_index) for row in self._route_entries_from_table()]


def _network_page_save_route_profile(self) -> None:
    name = self.route_profile_name_edit.text().strip() or self.route_profile_combo.currentText().strip()
    if not name:
        return
    try:
        entries = self._route_entries_from_table()
    except ValueError as exc:
        MessageBox.warning(self, self.i18n.t("network_manager.title"), str(exc))
        return
    self.route_store.upsert(RouteProfile(profile_name=name, routes=entries))
    self._append_log(f"已保存路由方案：{name}")
    self.load_profiles()
    index = self.route_profile_combo.findText(name)
    if index >= 0:
        self.route_profile_combo.setCurrentIndex(index)
        self.route_profile_table.selectRow(index)


def _network_page_show_route_edit_context_menu(self, pos) -> None:
    row = self.route_edit_table.rowAt(pos.y())
    if row >= 0 and not self.route_edit_table.selectionModel().isRowSelected(row):
        self.route_edit_table.selectRow(row)
    menu = QMenu(self.route_edit_table)
    delete_action = menu.addAction("删除选中路由")
    clear_action = menu.addAction("清空路由编辑区")
    action = menu.exec(self.route_edit_table.viewport().mapToGlobal(pos))
    if action == delete_action:
        self.delete_route_row()
    elif action == clear_action:
        if MessageBox.question(self, self.i18n.t("network_manager.confirm"), "确认清空路由编辑区？") == MessageBox.Yes:
            self.route_edit_table.setRowCount(0)


NetworkAdapterRoutePage._connect_signals = _network_page_connect_signals
NetworkAdapterRoutePage.load_profiles = _network_page_load_profiles
NetworkAdapterRoutePage._adapter_profile_combo_changed = _network_page_adapter_profile_combo_changed
NetworkAdapterRoutePage._find_adapter_for_profile = _network_page_find_adapter_for_profile
NetworkAdapterRoutePage.load_adapter_profile_into_form = _network_page_load_adapter_profile_into_form
NetworkAdapterRoutePage.apply_adapter_profile = _network_page_apply_adapter_profile
NetworkAdapterRoutePage._route_profile_combo_changed = _network_page_route_profile_combo_changed
NetworkAdapterRoutePage._route_profile_table_selection_changed = _network_page_route_profile_table_selection_changed
NetworkAdapterRoutePage.load_route_profile_into_editor = _network_page_load_route_profile_into_editor
NetworkAdapterRoutePage._append_route_entry_to_editor = _network_page_append_route_entry_to_editor
NetworkAdapterRoutePage._split_destination_prefix = _network_page_split_destination_prefix
NetworkAdapterRoutePage.add_route_row = _network_page_add_route_row_inheriting_previous
NetworkAdapterRoutePage._selected_or_edited_routes = _network_page_selected_or_edited_routes_from_editor
NetworkAdapterRoutePage.save_route_profile = _network_page_save_route_profile
NetworkAdapterRoutePage._show_route_edit_context_menu = _network_page_show_route_edit_context_menu


def _network_page_apply_ip_config(self) -> None:
    adapter = self.selected_adapter()
    if adapter is None:
        MessageBox.warning(self, self.i18n.t("network_manager.title"), "请先选择网卡。")
        return
    try:
        config = self._ip_config_from_form(adapter)
    except ValueError as exc:
        MessageBox.warning(self, self.i18n.t("network_manager.title"), str(exc))
        return
    if not self._confirm_write(self._ip_preview(adapter, config)):
        return
    ip_success = False
    vlan_message = ""
    try:
        self.manager.apply_ip_config(config)
        ip_success = True
        self._append_log("IP配置成功。")
    except PermissionError:
        self._prompt_admin()
        return
    except Exception as exc:
        MessageBox.warning(self, self.i18n.t("network_manager.title"), str(exc))
        self._append_log(f"IP配置失败：{exc}")
        return

    vlan_property = self._current_vlan_property(adapter)
    if vlan_property is not None:
        try:
            self.manager.set_vlan_id(adapter.name, vlan_property, self.vlan_spin.value())
            vlan_message = "VLAN配置成功。"
            self._append_log(vlan_message)
        except Exception as exc:
            vlan_message = f"VLAN配置失败：{exc}"
            self._append_log(f"IP配置成功，但 {vlan_message}")
            MessageBox.warning(self, self.i18n.t("network_manager.title"), f"IP配置成功，但 {vlan_message}")
    if ip_success and not vlan_message:
        self._append_log("网卡配置已应用。")
    self.refresh_all()


def _network_page_reset_adapter_defaults(self) -> None:
    adapter = self.selected_adapter()
    if adapter is None:
        return
    if MessageBox.question(self, self.i18n.t("network_manager.reset_defaults"), f"确认恢复默认网卡配置：{adapter.name}？") != MessageBox.Yes:
        return
    try:
        self.manager.reset_adapter_defaults(adapter.interface_index, adapter_name=adapter.name, vlan_property=None)
        self._append_log("IP配置已恢复默认。")
    except PermissionError:
        self._prompt_admin()
        return
    except Exception as exc:
        MessageBox.warning(self, self.i18n.t("network_manager.title"), str(exc))
        self._append_log(f"恢复默认失败：{exc}")
        return
    vlan_property = self._current_vlan_property(adapter)
    if vlan_property is not None:
        try:
            self.manager.set_vlan_id(adapter.name, vlan_property, 0)
            self._append_log("VLAN配置已恢复默认。")
        except Exception as exc:
            self._append_log(f"IP配置已恢复，但 VLAN无法自动恢复：{exc}")
    self.refresh_all()


NetworkAdapterRoutePage.apply_ip_config = _network_page_apply_ip_config
NetworkAdapterRoutePage.reset_adapter_defaults = _network_page_reset_adapter_defaults


def _network_page_build_ui_split(self) -> None:
    top = QHBoxLayout()
    top.addWidget(self.permission_label)
    top.addWidget(self.status_label, 1)
    top.addWidget(self.progress_bar)
    top.addWidget(self.refresh_button)
    top.addWidget(self.open_connections_button)
    top.addWidget(self.admin_button)

    adapter_page = QWidget()
    adapter_layout = QVBoxLayout(adapter_page)
    adapter_splitter = QSplitter(Qt.Vertical)
    adapter_splitter.addWidget(self.adapter_table)

    detail_splitter = QSplitter(Qt.Horizontal)
    status_group = QGroupBox("当前网卡实时状态")
    status_form = QFormLayout(status_group)
    self.adapter_status_fields = {}
    for key, label in (
        ("name", "名称"),
        ("mac", "MAC"),
        ("status", "状态"),
        ("ipv4", "IPv4"),
        ("gateway", "网关"),
        ("vlan", "VLAN状态"),
        ("speed", "速率"),
    ):
        value_label = QLabel("-")
        value_label.setWordWrap(True)
        self.adapter_status_fields[key] = value_label
        status_form.addRow(label, value_label)

    edit_group = QGroupBox("IP / VLAN 配置编辑区")
    edit_layout = QVBoxLayout(edit_group)
    form = QFormLayout()
    self.vlan_hint_label = QLabel("")
    self.vlan_hint_label.setWordWrap(True)
    form.addRow("网卡选择", self.adapter_combo)
    form.addRow("IP模式", self.mode_combo)
    form.addRow("IP地址", self.ip_edit)
    form.addRow("前缀/掩码", self.prefix_edit)
    form.addRow("默认网关", self.gateway_edit)
    form.addRow("VLAN ID", self.vlan_spin)
    form.addRow("VLAN提示", self.vlan_hint_label)
    form.addRow("备用IP", self.secondary_edit)
    edit_layout.addLayout(form)
    profile_row = QHBoxLayout()
    profile_row.addWidget(QLabel("方案名称"))
    profile_row.addWidget(self.profile_name_edit)
    profile_row.addWidget(self.save_profile_button)
    profile_row.addWidget(self.profile_combo)
    profile_row.addWidget(self.apply_profile_button)
    profile_row.addWidget(self.refresh_vlan_button)
    profile_row.addWidget(self.reset_button)
    profile_row.addWidget(self.apply_ip_button)
    edit_layout.addLayout(profile_row)
    edit_layout.addStretch(1)

    detail_splitter.addWidget(status_group)
    detail_splitter.addWidget(edit_group)
    detail_splitter.setStretchFactor(0, 2)
    detail_splitter.setStretchFactor(1, 3)
    detail_splitter.setSizes([400, 600])
    adapter_splitter.addWidget(detail_splitter)
    adapter_splitter.setStretchFactor(0, 3)
    adapter_splitter.setStretchFactor(1, 4)
    adapter_layout.addWidget(adapter_splitter)

    route_page = QWidget(self)
    route_layout = QVBoxLayout(route_page)
    route_layout.addWidget(QLabel("当前路由表"))
    route_filter_row = QHBoxLayout()
    route_filter_row.addWidget(self.manual_static_only_check)
    route_filter_row.addWidget(self.persistent_only_check)
    route_filter_row.addStretch(1)
    route_layout.addLayout(route_filter_row)
    route_layout.addWidget(self.route_table)
    route_layout.addWidget(QLabel("静态路由方案"))
    route_layout.addWidget(self.route_profile_table)
    edit_route_group = QGroupBox("路由编辑区")
    edit_route_layout = QVBoxLayout(edit_route_group)
    edit_top = QHBoxLayout()
    edit_top.addWidget(QLabel("方案名称"))
    edit_top.addWidget(self.route_profile_name_edit)
    edit_top.addWidget(self.route_profile_combo)
    edit_top.addWidget(self.add_route_button)
    edit_top.addWidget(self.delete_route_button)
    edit_top.addWidget(self.save_route_profile_button)
    edit_top.addWidget(self.apply_route_button)
    edit_top.addWidget(self.remove_route_button)
    edit_route_layout.addLayout(edit_top)
    edit_route_layout.addWidget(self.route_edit_table)
    route_layout.addWidget(edit_route_group)

    self.tabs.addTab(adapter_page, "")
    layout = QVBoxLayout(self)
    layout.addLayout(top)
    main_splitter = QSplitter(Qt.Vertical)
    main_splitter.addWidget(self.tabs)
    log_panel = QWidget()
    log_layout = QVBoxLayout(log_panel)
    log_layout.addWidget(QLabel("操作日志"))
    log_layout.addWidget(self.log_text)
    main_splitter.addWidget(log_panel)
    main_splitter.setStretchFactor(0, 4)
    main_splitter.setStretchFactor(1, 1)
    layout.addWidget(main_splitter, 1)


def _network_page_update_adapter_status_panel(self, adapter: NetworkAdapterInfo | None, vlan_message: str = "") -> None:
    fields = getattr(self, "adapter_status_fields", {})
    if not fields:
        return
    values = {
        "name": adapter.name if adapter else "-",
        "mac": adapter.mac_address if adapter else "-",
        "status": self._display_status(adapter.status) if adapter else "-",
        "ipv4": ", ".join(adapter.ipv4_addresses) if adapter and adapter.ipv4_addresses else "-",
        "gateway": ", ".join(adapter.gateways) if adapter and adapter.gateways else "-",
        "vlan": vlan_message or "-",
        "speed": adapter.link_speed if adapter else "-",
    }
    for key, value in values.items():
        fields[key].setText(value)


def _network_page_adapter_changed_split(self) -> None:
    adapter = self.selected_adapter()
    if adapter is None:
        self._update_adapter_status_panel(None)
        return
    if self.mode_combo.currentText().upper() == "DHCP":
        self._sync_ip_mode_fields()
    else:
        self.ip_edit.setText(adapter.ipv4_addresses[0].split("/", 1)[0] if adapter.ipv4_addresses else "")
        if adapter.ipv4_addresses and "/" in adapter.ipv4_addresses[0]:
            self.prefix_edit.setText(adapter.ipv4_addresses[0].split("/", 1)[1])
        self.gateway_edit.setText(adapter.gateways[0] if adapter.gateways else "")
    vlan_message = "未检测"
    try:
        capability = self.manager.get_vlan_capability(adapter.name)
        if capability.can_set_vlan_id:
            self._vlan_can_set_id = True
            self.vlan_spin.setEnabled(True)
            vlan_message = capability.message
        elif capability.vlan_switch_property:
            self._vlan_can_set_id = False
            self.vlan_spin.setValue(0)
            self.vlan_spin.setEnabled(False)
            vlan_message = "当前网卡仅支持 VLAN 开关，不支持 VLAN ID 设置"
        else:
            self._vlan_can_set_id = False
            self.vlan_spin.setValue(0)
            self.vlan_spin.setEnabled(False)
            vlan_message = "当前网卡不支持 VLAN 配置"
        if hasattr(self, "vlan_hint_label"):
            self.vlan_hint_label.setText(vlan_message)
        self._append_log(vlan_message)
    except Exception as exc:
        self._vlan_can_set_id = False
        self.vlan_spin.setValue(0)
        self.vlan_spin.setEnabled(False)
        vlan_message = f"VLAN 检测失败：{exc}"
        if hasattr(self, "vlan_hint_label"):
            self.vlan_hint_label.setText(vlan_message)
        self._append_log(vlan_message)
    self._update_adapter_status_panel(adapter, vlan_message)


NetworkAdapterRoutePage._build_ui = _network_page_build_ui_split
NetworkAdapterRoutePage._update_adapter_status_panel = _network_page_update_adapter_status_panel
NetworkAdapterRoutePage._adapter_changed = _network_page_adapter_changed_split


def _network_page_sync_ip_mode_fields(self) -> None:
    dhcp = self.mode_combo.currentText().upper() == "DHCP"
    if dhcp:
        self.ip_edit.clear()
        self.prefix_edit.clear()
        self.gateway_edit.clear()
        self.secondary_edit.clear()
    for widget in (self.ip_edit, self.prefix_edit, self.gateway_edit, self.secondary_edit):
        widget.setEnabled(not dhcp)
    if getattr(self, "_vlan_can_set_id", True):
        self.vlan_spin.setEnabled(True)
    else:
        self.vlan_spin.setValue(0)
        self.vlan_spin.setEnabled(False)


NetworkAdapterRoutePage._sync_ip_mode_fields = _network_page_sync_ip_mode_fields
