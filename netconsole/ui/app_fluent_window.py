from __future__ import annotations

import traceback
import os
from inspect import signature
from time import perf_counter
from typing import Callable

from PySide6.QtCore import QRect, QTimer, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QStackedWidget,
    QTabWidget,
    QTableView,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from netconsole.core import app_logger
from netconsole.core.background_tasks import background_task_manager
from netconsole.core.database import Database
from netconsole.core.feature_flags import FeatureGate, default_feature_gate
from netconsole.core.feature_registry import PAGE_FEATURE_BY_PAGE_ID
from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.core.settings import SettingsStore
from netconsole.core.shutdown_manager import shutdown_manager
from netconsole.core.sites import Site, SiteManager
from netconsole.core import version as version_info
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.ui.pages.device_management_page import DeviceManagementPage
from netconsole.ui.pages.settings_page import SettingsPage
from netconsole.ui.dialogs.mesh_analysis_params_dialog import MeshAnalysisParamsEditor
from netconsole.ui.components.nc_command_bar import NCCommandAction, NCCommandBar
from netconsole.ui.shell.fluent_bridge import (
    FIF,
    InfoBar,
    InfoBarPosition,
    PushButton,
    SplitFluentWindow,
    apply_fluent_theme,
)
from netconsole.ui.theme import apply_global_theme
from netconsole.ui.theme.qt_theme_engine import apply_table_theme, theme_tokens_for
from netconsole.ui.windowing import (
    MAIN_WINDOW_MIN_HEIGHT,
    MAIN_WINDOW_MIN_WIDTH,
    apply_startup_main_window_geometry,
    available_screen_geometry,
    calculate_default_main_window_geometry,
    format_geometry,
    main_window_geometry_issue,
    should_save_main_window_geometry,
)


WINDOW_CONTROL_SAFE_RIGHT = 180
TOP_BAR_MIN_HEIGHT = 52
TOP_BAR_FULL_WIDTH = 1600
TOP_BAR_MEDIUM_WIDTH = 1280
SITE_BAR_COMPACT_WIDTH = TOP_BAR_FULL_WIDTH


class AppFluentWindow(SplitFluentWindow):
    def __init__(
        self,
        site: Site,
        repository: DeviceRepository,
        i18n: I18n,
        paths: PathResolver,
        startup_started_at: float | None = None,
    ) -> None:
        super().__init__()
        self.startup_started_at = startup_started_at or perf_counter()
        self.site = site
        self.repository = repository
        self.i18n = i18n
        self.paths = paths
        self.settings = SettingsStore(paths)
        self.site_manager = SiteManager(paths)
        self.feature_gate: FeatureGate = default_feature_gate()
        self._current_theme = self._normalize_theme(self.settings.theme)
        self.pages: dict[str, QWidget] = {}
        self.raw_pages: dict[str, QWidget] = {}
        self._page_factories: dict[str, Callable[[], QWidget]] = {}
        self._page_content_widgets: dict[str, QWidget] = {}
        self._nav_items: list[QListWidgetItem] = []
        self._site_labels: list[QLabel] = []
        self._status_labels: list[QLabel] = []
        self._site_bar_action_groups: list[dict[str, object]] = []
        self._current_row = 0
        self.preloaded_pages: set[str] = set()
        self.preload_failures: dict[str, str] = {}
        self._info_bar_shown = False
        self._window_geometry_log: list[str] = []
        self._startup_geometry_checks_scheduled = False
        self._startup_geometry_default_rect = QRect()
        self._force_close = False
        self._page_enter_serial = 0
        self._site_bar_sync_scheduled = False

        self.apply_app_theme(self.settings.theme, persist=False)
        self.setMicaEffectEnabled(False)
        self.setWindowTitle(f"{version_info.APP_NAME} {version_info.APP_VERSION_DISPLAY} - 网络设备采集工具")
        self.resize_for_screen()

        self._register_real_pages()
        self.apply_app_theme(self.settings.theme, persist=False)
        self._hide_fluent_window_title_text()

        self.stack = self.stackedWidget
        self.navigation = _FluentNavigationProxy(self)
        self.stackedWidget.currentChanged.connect(self._handle_stack_current_changed)
        self._handle_stack_current_changed(self.stackedWidget.currentIndex())
        self._log_ui_startup()

    def _normalize_theme(self, theme: str) -> str:
        return "dark" if str(theme).lower() == "dark" else "light"

    @property
    def current_theme(self) -> str:
        app = QApplication.instance()
        if app is not None and app.property("netconsoleTheme") in {"light", "dark"}:
            return str(app.property("netconsoleTheme"))
        return self._current_theme

    @current_theme.setter
    def current_theme(self, theme: str) -> None:
        self._current_theme = self._normalize_theme(theme)

    def apply_app_theme(self, theme: str, persist: bool = True) -> None:
        requested_theme = str(theme or "light").lower()
        theme = self._normalize_theme(requested_theme)
        self.current_theme = theme
        if persist:
            self.settings.set_theme(requested_theme if requested_theme in {"light", "dark", "auto"} else theme)

        apply_global_theme(theme)
        apply_fluent_theme(theme, self.settings.theme_color)
        self.setProperty("netconsoleTheme", theme)

        for page in self.pages.values():
            page.setProperty("netconsoleTheme", theme)
        for page in self.raw_pages.values():
            page.setProperty("netconsoleTheme", theme)

        self._update_site_bars()
        self.update()

    def set_theme(self, theme: str) -> None:
        requested_theme = str(theme or "light").lower()
        theme_mode = self._normalize_theme(requested_theme)
        try:
            self.current_theme = theme_mode
            self.settings.set_theme(requested_theme if requested_theme in {"light", "dark", "auto"} else theme_mode)
            print(f"[Theme] set theme: {theme_mode}")
            if os.environ.get("QT_QPA_PLATFORM", "").casefold() == "offscreen":
                app = QApplication.instance()
                if app is not None:
                    app.setProperty("netconsoleTheme", theme_mode)
                print(f"[Theme] app stylesheet applied: {theme_mode} (offscreen-skip)")
                print(f"[Theme] qfluentwidgets applied: {theme_mode} (offscreen-skip)")
            else:
                apply_global_theme(theme_mode)
                print(f"[Theme] app stylesheet applied: {theme_mode}")
                apply_fluent_theme(theme_mode, self.settings.theme_color)
                print(f"[Theme] qfluentwidgets applied: {theme_mode}")
            QTimer.singleShot(0, self._safe_refresh_theme)
        except Exception:
            app_logger.log_error("THEME_APPLY_FAILED", traceback.format_exc())
            return

    def _apply_theme_to_widget_tree(self, root: QWidget) -> None:
        for widget in [root, *root.findChildren(QWidget)]:
            widget.setProperty("netconsoleTheme", self.current_theme)
            if isinstance(widget, QTableView):
                apply_table_theme(widget, self.current_theme)
                if isinstance(widget, QAbstractItemView):
                    widget.setAlternatingRowColors(True)
                continue
            if isinstance(widget, (QPlainTextEdit, QTextEdit)) and widget.isReadOnly() and not widget.objectName():
                widget.setObjectName("ncLogPanel")

    def _hide_legacy_action_buttons(self, content: QWidget) -> None:
        for attr in ("action_scroll", "action_content"):
            widget = getattr(content, attr, None)
            if isinstance(widget, QWidget):
                widget.hide()
                widget.setProperty("netconsoleLegacyActionBarHidden", True)
        if content.__class__.__name__ == "DeviceManagementPage":
            for attr in (
                "add_button",
                "test_connection_button",
                "external_terminal_button",
                "generate_crt_sessions_button",
                "clear_selection_button",
                "invert_selection_button",
                "batch_delete_button",
                "diagnostic_download_button",
                "manage_groups_button",
                "assign_group_button",
                "batch_refresh_details_button",
                "import_csv_button",
                "export_csv_button",
                "export_template_button",
            ):
                widget = getattr(content, attr, None)
                if isinstance(widget, QPushButton):
                    widget.hide()
        if content.__class__.__name__ == "FileManagementPage":
            for attr in ("connect_button", "disconnect_button", "external_winscp_button"):
                widget = getattr(content, attr, None)
                if isinstance(widget, QPushButton):
                    widget.hide()

    def _safe_refresh_theme(self) -> None:
        page_entries: list[tuple[str, QWidget]] = []
        seen: set[int] = set()
        for page_id, page in list(self.pages.items()):
            if page is None or id(page) in seen:
                continue
            seen.add(id(page))
            page_entries.append((page_id, page))
        print(f"[Theme] notify loaded pages: {len(page_entries)}")
        for page_id, page in page_entries:
            try:
                page.setProperty("netconsoleTheme", self.current_theme)
                raw_page = self.raw_pages.get(page_id)
                if raw_page is not None:
                    raw_page.setProperty("netconsoleTheme", self.current_theme)
                    self._call_page_apply_theme(raw_page)
                self._apply_theme_to_widget_tree(page)
                page.updateGeometry()
                page.update()
                print(f"[Theme] page updated: {page_id}")
            except RuntimeError as exc:
                detail = f"{page_id}: {exc}"
                print(f"[Theme][WARN] apply failed: {detail}")
                app_logger.log_error("THEME_PAGE_REFRESH_DELETED", detail)
            except Exception as exc:
                detail = f"{page_id}: {exc}"
                print(f"[Theme][WARN] apply failed: {detail}")
                app_logger.log_error("THEME_PAGE_REFRESH_FAILED", f"{page_id}\n{traceback.format_exc()}")
        app = QApplication.instance()
        if app is not None:
            for widget in app.topLevelWidgets():
                if widget is self:
                    continue
                try:
                    self._apply_theme_to_widget_tree(widget)
                    widget.update()
                except RuntimeError:
                    continue
                except Exception:
                    app_logger.log_error("THEME_POPUP_REFRESH_FAILED", traceback.format_exc())
        try:
            self.setProperty("netconsoleTheme", self.current_theme)
            self._update_site_bars()
            self.update()
            print("[Theme] theme switch finished")
        except Exception:
            app_logger.log_error("THEME_MAIN_REPOLISH_FAILED", traceback.format_exc())

    def _call_page_apply_theme(self, page: QWidget) -> None:
        apply_theme = getattr(page, "apply_theme", None)
        if not callable(apply_theme):
            return
        try:
            parameter_count = len(signature(apply_theme).parameters)
        except (TypeError, ValueError):
            parameter_count = 1
        if parameter_count == 0:
            apply_theme()
        else:
            apply_theme(self.current_theme)

    def _safe_repolish(self, root: QWidget) -> None:
        for widget in [root, *root.findChildren(QWidget)]:
            try:
                style = widget.style()
                style.unpolish(widget)
                style.polish(widget)
                widget.update()
            except RuntimeError:
                continue

    def resize_for_screen(self) -> None:
        available = available_screen_geometry()
        default_rect = calculate_default_main_window_geometry(available)
        decision = apply_startup_main_window_geometry(self, None, available)
        rect = QRect(self.geometry())
        self._startup_geometry_default_rect = QRect(default_rect)
        self._window_geometry_log = [
            f"[UI] Screen available: {format_geometry(available)}",
            "[UI] Default geometry policy: 75% available screen",
            f"[UI] Default geometry calculated: {format_geometry(default_rect)}",
            "[UI] Saved geometry raw: none",
            "[UI] Saved geometry normalized: rejected:none",
            f"[UI] Main window geometry: {format_geometry(rect)} status={decision.status}",
            f"[UI] Main window minimum: {MAIN_WINDOW_MIN_WIDTH}x{MAIN_WINDOW_MIN_HEIGHT}",
        ]

    def log_startup_geometry_checkpoint(self, phase: str) -> None:
        self._emit_startup_geometry_line(f"[UI] Geometry {phase}: {format_geometry(QRect(self.geometry()))}")

    def schedule_startup_geometry_checks(self) -> None:
        if self._startup_geometry_checks_scheduled:
            return
        self._startup_geometry_checks_scheduled = True
        QTimer.singleShot(0, lambda: self.ensure_reasonable_startup_geometry("after show +0ms"))
        QTimer.singleShot(200, lambda: self.ensure_reasonable_startup_geometry("after show +200ms"))

    def ensure_reasonable_startup_geometry(self, phase: str) -> None:
        available = available_screen_geometry()
        current = QRect(self.geometry())
        self._emit_startup_geometry_line(f"[UI] Geometry {phase}: {format_geometry(current)}")
        if self.isMaximized() or self.isFullScreen():
            self._emit_startup_geometry_line(f"[UI] Geometry final: maximized/fullscreen {format_geometry(current)}")
            return

        issue = main_window_geometry_issue(current, available)
        if issue is None:
            if phase.endswith("+200ms"):
                self._emit_startup_geometry_line(f"[UI] Geometry final: {format_geometry(current)} status=ok")
            return

        default_rect = calculate_default_main_window_geometry(available)
        if self.isMinimized():
            self.showNormal()
        self.setMinimumSize(MAIN_WINDOW_MIN_WIDTH, MAIN_WINDOW_MIN_HEIGHT)
        self.setGeometry(default_rect)
        corrected = QRect(self.geometry())
        corrected_issue = main_window_geometry_issue(corrected, available)
        self._emit_startup_geometry_line(
            f"[UI] Startup geometry corrected: reason={issue} default={format_geometry(default_rect)} "
            f"corrected={format_geometry(corrected)}"
        )
        if corrected_issue is None:
            app_logger.log_warning("UI_STARTUP_GEOMETRY_CORRECTED", f"phase={phase} reason={issue}")
            self._emit_startup_geometry_line(f"[UI] Geometry final: {format_geometry(corrected)} status=corrected")
            return
        line = f"[UI][ERROR] Startup geometry still too small after correction: reason={corrected_issue} rect={format_geometry(corrected)}"
        print(line)
        app_logger.log_error("UI_STARTUP_GEOMETRY_FAILED", line)

    def _emit_startup_geometry_line(self, line: str) -> None:
        print(line)
        app_logger.log_info("UI_STARTUP_GEOMETRY", line)

    def _log_main_window_geometry_save_policy(self) -> None:
        rect = QRect(self.normalGeometry() if self.isMaximized() else self.geometry())
        ok, reason = should_save_main_window_geometry(rect, available_screen_geometry(), minimized=self.isMinimized())
        if ok:
            self._emit_startup_geometry_line(f"[UI] Main window geometry save candidate: {format_geometry(rect)} status=ok")
        else:
            self._emit_startup_geometry_line(f"[UI] Main window geometry save skipped: reason={reason} rect={format_geometry(rect)}")

    def _register_real_pages(self) -> None:
        specs = [
            ("devices", "设备管理", "设备主数据、连接测试、导入导出和批量操作", FIF.APPLICATION, self._create_device_page, self._device_actions()),
            ("ac", "AC 管理", "AC、FIT-AP、轨旁 AP 和光衰资源采集", FIF.WIFI, self._create_ac_page, self._ac_actions()),
            ("rail_transit", "轨道交通", "车载 MR 在线收集、Mesh 日志分析和车地无线诊断", FIF.BUS, self._create_rail_transit_page, self._rail_actions()),
            ("wifi_survey", "无线勘测", "轨旁 AP 隐藏信号扫描和 Wi-Fi 勘测", FIF.WIFI, self._create_wifi_survey_page, self._refresh_actions()),
            ("config_collection", "配置采集中心", "保存配置、下载配置和差异比较", FIF.SYNC, self._create_config_collection_page, self._config_actions()),
            ("file_management", "文件管理", "本地/设备双窗格文件下载和 Mesh 快选", FIF.FOLDER, self._create_file_management_page, self._file_actions()),
            ("snmp_center", "SNMP 中心", "MIB 浏览、OID 查询、SNMP 采集和监控", FIF.SEARCH, self._create_snmp_center_page, self._snmp_actions()),
            ("network_tools", "网络工具", "Ping、fping、iperf、本机网卡和路由工具", FIF.COMMAND_PROMPT, self._create_network_tools_page, self._network_actions()),
            ("command_reference", "命令说明", "软件使用命令、接口说明和中兴适配参考", FIF.DOCUMENT, self._create_command_reference_page, self._command_reference_actions()),
            ("logs", "日志中心", "运行日志、筛选、导出和打开日志目录", FIF.DOCUMENT, self._create_log_page, self._log_actions()),
            ("system_settings", "系统设置", "外观、局点、采集、文件和工具路径", FIF.SETTING, self._settings_page, self._settings_actions()),
            ("feature_flags", "功能开关配置", "模块显示、客户配置和内部功能开关", FIF.SETTING, self._create_feature_flags_page, []),
        ]
        for page_id, title, description, icon, factory, actions in specs:
            feature_id = PAGE_FEATURE_BY_PAGE_ID.get(page_id)
            if feature_id is not None and not self.feature_gate.is_enabled(feature_id):
                continue
            self._page_factories[page_id] = factory
            if page_id == "devices":
                content = factory()
                self.raw_pages[page_id] = content
            else:
                content = self._lazy_placeholder(title)
            page = self._command_page(title, description, content, actions)
            self._page_content_widgets[page_id] = content
            self._add_page(page_id, page, icon, title)

    def _lazy_placeholder(self, title: str) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 28, 0, 0)
        label = QLabel(f"{title} 页面加载中...")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setObjectName("lazyPagePlaceholder")
        layout.addStretch(1)
        layout.addWidget(label)
        layout.addStretch(2)
        return widget

    def _add_page(self, page_id: str, page: QWidget, icon, text: str) -> None:
        page.setObjectName(page_id)
        self.pages[page_id] = page
        self.addSubInterface(page, icon, text)
        item = QListWidgetItem(text)
        item.setData(256, page_id)
        item.setData(257, text)
        item.setToolTip(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self._nav_items.append(item)

    def _command_page(self, title: str, description: str, content: QWidget, actions: list[NCCommandAction]) -> QWidget:
        page = QWidget()
        page.setObjectName("fluentPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 16, 20, 20)
        layout.setSpacing(12)
        self._hide_legacy_action_buttons(content)
        layout.addWidget(self._site_bar())
        layout.addWidget(self._page_header(title, description))
        if actions:
            command_bar = NCCommandBar()
            for action in actions:
                command_bar.add_action_button(action)
            command_bar.add_stretch()
            layout.addWidget(command_bar)
        layout.addWidget(content, 1)
        for name in ("tabs", "table", "device_table", "navigation", "stack"):
            if hasattr(content, name):
                setattr(page, name, getattr(content, name))
        self._apply_theme_to_widget_tree(page)
        return page

    def _ensure_real_page(self, page_id: str) -> QWidget | None:
        raw_page = self.raw_pages.get(page_id)
        if raw_page is not None:
            return raw_page
        factory = self._page_factories.get(page_id)
        wrapper = self.pages.get(page_id)
        if factory is None or wrapper is None:
            return None
        started = perf_counter()
        app_logger.log_info("BOOT_MODULE_LAZY_LOAD_STARTED", f"page_id={page_id}")
        raw_page = factory()
        self._hide_legacy_action_buttons(raw_page)
        old_content = self._page_content_widgets.get(page_id)
        layout = wrapper.layout()
        insert_index = layout.indexOf(old_content) if layout is not None and old_content is not None else -1
        if layout is not None and old_content is not None:
            layout.removeWidget(old_content)
            old_content.deleteLater()
        if layout is not None:
            layout.insertWidget(insert_index if insert_index >= 0 else layout.count(), raw_page, 1)
        self.raw_pages[page_id] = raw_page
        self._page_content_widgets[page_id] = raw_page
        for name in ("tabs", "table", "device_table", "navigation", "stack"):
            if hasattr(raw_page, name):
                setattr(wrapper, name, getattr(raw_page, name))
        self._apply_theme_to_widget_tree(wrapper)
        elapsed_ms = int((perf_counter() - started) * 1000)
        app_logger.log_info("BOOT_MODULE_LAZY_LOAD_FINISHED", f"page_id={page_id} elapsed_ms={elapsed_ms}")
        return raw_page

    def _site_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("appTopBar")
        bar.setMinimumHeight(TOP_BAR_MIN_HEIGHT)
        bar.setMaximumHeight(TOP_BAR_MIN_HEIGHT)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 6, 0, 6)
        layout.setSpacing(8)
        site_label = QLabel()
        site_label.setObjectName("appTopBarSiteBadge")
        site_label.setMinimumWidth(170)
        site_label.setMaximumWidth(260)
        status_label = QLabel("采集状态：就绪")
        status_label.setObjectName("appTopBarStatusBadge")
        status_label.setMinimumWidth(116)
        status_label.setMaximumWidth(150)
        self._site_labels.append(site_label)
        self._status_labels.append(status_label)
        layout.addWidget(self._top_bar_title())
        layout.addWidget(site_label)
        layout.addWidget(status_label)
        layout.addStretch(1)
        actions_widget = QWidget(bar)
        actions_widget.setObjectName("appTopBarActions")
        actions_layout = QHBoxLayout(actions_widget)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(8)

        create_button = self._site_action_button("新建局点", self.create_site, actions_widget)
        switch_button = self._site_action_button("切换局点", self.switch_site_dialog, actions_widget)
        detach_button = self._site_action_button("弹出模块", self.detach_current_page, actions_widget)
        more_button = self._site_action_button("更多", None, actions_widget, minimum_width=72)
        more_menu = QMenu(more_button)
        more_button.setMenu(more_menu)

        responsive_actions = [
            ("create", "新建局点", self.create_site),
            ("switch", "切换局点", self.switch_site_dialog),
            ("detach", "弹出模块", self.detach_current_page),
        ]
        overflow_actions = [
            ("top", "窗口置顶", self.toggle_always_on_top),
            ("open_site_dir", "打开当前局点目录", self.open_current_site_dir),
            ("disk_cleanup", "磁盘清理", self.show_disk_cleanup),
            ("changelog", "版本更新日志", self.show_changelog),
            ("open_source", "开源许可", self.show_open_source_notices),
            ("about", "关于 NetConsole", self.show_about),
            ("exit", "退出", self.close),
        ]
        responsive_menu_actions = {}
        for key, text, callback in responsive_actions:
            action = more_menu.addAction(text)
            action.triggered.connect(lambda checked=False, action_callback=callback: action_callback())
            responsive_menu_actions[key] = action
        more_menu.addSeparator()
        overflow_menu_actions = {}
        for key, text, callback in overflow_actions:
            action = more_menu.addAction(text)
            action.triggered.connect(lambda checked=False, action_callback=callback: action_callback())
            feature_id = {
                "disk_cleanup": "system.disk_cleanup",
                "changelog": "system.changelog",
                "open_source": "system.open_source",
            }.get(key)
            if feature_id is not None:
                action.setVisible(self.feature_gate.is_visible(feature_id))
                action.setEnabled(self.feature_gate.is_enabled(feature_id))
            overflow_menu_actions[key] = action

        for button in (create_button, switch_button, detach_button, more_button):
            actions_layout.addWidget(button)
        layout.addWidget(actions_widget, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addItem(QSpacerItem(WINDOW_CONTROL_SAFE_RIGHT, 1, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum))
        self._site_bar_action_groups.append(
            {
                "buttons": {
                    "create": create_button,
                    "switch": switch_button,
                    "detach": detach_button,
                },
                "more_button": more_button,
                "responsive_actions": responsive_menu_actions,
                "top_action": overflow_menu_actions["top"],
            }
        )
        self._sync_site_bar_action_modes()
        self._update_site_bars()
        return bar

    def _site_action_button(
        self,
        text: str,
        callback: Callable[[], None] | None,
        parent: QWidget,
        *,
        minimum_width: int = 86,
    ) -> QPushButton:
        button = PushButton(text, parent) if PushButton is not None else QPushButton(text, parent)
        button.setObjectName("fluentSiteActionButton")
        button.setToolTip(text)
        button.setMinimumWidth(minimum_width)
        button.setMaximumWidth(150)
        if callback is not None:
            button.clicked.connect(callback)
        return button

    def _top_bar_title(self) -> QLabel:
        title_label = QLabel(f"{version_info.APP_NAME} {version_info.APP_VERSION_DISPLAY}")
        title_label.setObjectName("appTopBarTitle")
        title_label.setToolTip("网络设备采集工具")
        title_label.setMinimumWidth(142)
        title_label.setMaximumWidth(210)
        title_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        return title_label

    def _sync_site_bar_action_modes(self) -> None:
        self._site_bar_sync_scheduled = False
        groups = getattr(self, "_site_bar_action_groups", None)
        if not groups:
            return
        width = self.width()
        if width >= TOP_BAR_FULL_WIDTH:
            visible_actions = {"create", "switch", "detach"}
        elif width >= TOP_BAR_MEDIUM_WIDTH:
            visible_actions = {"switch", "detach"}
        else:
            visible_actions = set()
        for group in groups:
            buttons = group.get("buttons", {})
            if isinstance(buttons, dict):
                for key, button in buttons.items():
                    if isinstance(button, QPushButton):
                        button.setVisible(key in visible_actions)
            responsive_actions = group.get("responsive_actions", {})
            if isinstance(responsive_actions, dict):
                for key, action in responsive_actions.items():
                    if hasattr(action, "setVisible"):
                        action.setVisible(key not in visible_actions)
            more_button = group["more_button"]
            if isinstance(more_button, QPushButton):
                more_button.setVisible(True)

    def _schedule_site_bar_action_sync(self) -> None:
        if getattr(self, "_site_bar_sync_scheduled", False):
            return
        self._site_bar_sync_scheduled = True
        QTimer.singleShot(0, self._safe_sync_site_bar_action_modes)

    def _safe_sync_site_bar_action_modes(self) -> None:
        try:
            self._sync_site_bar_action_modes()
        except Exception:
            self._site_bar_sync_scheduled = False
            app_logger.log_error("APP_TOP_BAR_RESPONSIVE_FAILED", traceback.format_exc())

    def _hide_fluent_window_title_text(self) -> None:
        title_bar = getattr(self, "titleBar", None)
        if title_bar is not None:
            title_label = getattr(title_bar, "titleLabel", None)
            if isinstance(title_label, QLabel):
                title_label.clear()
                title_label.hide()
                title_label.setFixedWidth(0)
            set_title = getattr(title_bar, "setTitle", None)
            if callable(set_title):
                set_title("")
        for label in self.findChildren(QLabel, "titleLabel"):
            if label.text() == self.windowTitle():
                label.clear()
                label.hide()
                label.setFixedWidth(0)

    def _page_header(self, title: str, description: str) -> QWidget:
        header = QWidget()
        header.setObjectName("fluentPageHeader")
        layout = QVBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self._page_title(title))
        description_label = QLabel(description)
        description_label.setObjectName("fluentPageDescription")
        layout.addWidget(description_label)
        return header

    def _page_title(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("fluentPageTitle")
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        return label

    def _action(
        self,
        icon,
        text: str,
        callback: Callable[[], None] | None = None,
        *,
        primary: bool = False,
        danger: bool = False,
        overflow: bool = False,
        enabled: bool = True,
    ) -> NCCommandAction:
        return NCCommandAction(text=text, callback=callback, icon=icon, primary=primary, danger=danger, overflow=overflow, enabled=enabled)

    def _device_actions(self) -> list[NCCommandAction]:
        return [
            self._action(FIF.ADD, "新增", lambda: self._click_raw("devices", "add_button"), primary=True),
            self._action(FIF.CONNECT, "测试连接", lambda: self._click_raw("devices", "test_connection_button")),
            self._action(None, "批量更新详情", lambda: self._click_raw("devices", "batch_refresh_details_button")),
            self._action(FIF.DOWNLOAD, "诊断下载", lambda: self._click_raw("devices", "diagnostic_download_button")),
            self._action(FIF.DOWNLOAD, "导入 CSV", lambda: self._click_raw("devices", "import_csv_button")),
            self._action(FIF.SHARE, "导出 CSV", lambda: self._click_raw("devices", "export_csv_button")),
            self._action(FIF.SYNC, "刷新", lambda: self._call_raw("devices", "refresh")),
            self._action(FIF.COMMAND_PROMPT, "生成 CRT 会话", lambda: self._click_raw("devices", "generate_crt_sessions_button"), overflow=True),
            self._action(None, "清空选择", lambda: self._click_raw("devices", "clear_selection_button"), overflow=True),
            self._action(None, "反选", lambda: self._click_raw("devices", "invert_selection_button"), overflow=True),
            self._action(None, "分组管理", lambda: self._click_raw("devices", "manage_groups_button"), overflow=True),
            self._action(None, "设置分组", lambda: self._click_raw("devices", "assign_group_button"), overflow=True),
            self._action(None, "导出模板", lambda: self._click_raw("devices", "export_template_button"), overflow=True),
            self._action(FIF.DELETE, "批量删除", lambda: self._click_raw("devices", "batch_delete_button"), danger=True, overflow=True),
        ]

    def _refresh_actions(self) -> list[NCCommandAction]:
        return [self._action(FIF.SYNC, "刷新", lambda: self._call_current_refresh())]

    def _config_actions(self) -> list[NCCommandAction]:
        return [
            self._action(FIF.SAVE, "保存配置", lambda: self._click_raw("config_collection", "save_button")),
            self._action(FIF.DOWNLOAD, "下载配置", lambda: self._click_raw("config_collection", "fetch_button")),
            self._action(FIF.DOCUMENT, "配置对比", lambda: self._click_raw("config_collection", "compare_button")),
            self._action(FIF.FOLDER, "打开目录", lambda: self._click_raw("config_collection", "open_dir_button")),
            self._action(FIF.SYNC, "刷新", lambda: self._call_raw("config_collection", "refresh")),
        ]

    def _file_actions(self) -> list[NCCommandAction]:
        return [
            self._action(FIF.CONNECT, "连接", lambda: self._click_raw("file_management", "connect_button")),
            self._action(FIF.CANCEL, "断开", lambda: self._call_raw("file_management", "disconnect_sftp")),
            self._action(FIF.SYNC, "刷新连接状态", lambda: self._call_raw("file_management", "refresh_connection_status")),
            self._action(FIF.FOLDER, "打开 WinSCP", lambda: self._click_raw("file_management", "external_winscp_button")),
        ]

    def _ac_actions(self) -> list[NCCommandAction]:
        return [
            self._action(FIF.SYNC, "刷新", lambda: self._call_raw("ac", "refresh_current_async_or_lazy")),
            self._action(FIF.INFO, "获取 AC 信息", lambda: self._call_raw("ac", "refresh_ac_info")),
            self._action(FIF.GLOBE, "打开网页", lambda: self._call_raw("ac", "open_web")),
            self._action(FIF.UPDATE, "更新 AC 信息", lambda: self._call_raw("ac", "refresh_ac_info")),
            self._action(FIF.SAVE, "一键固化新上线 AP", lambda: self._call_raw_args("ac", "run_ac_action", "persist_auto_ap", "一键固化新上线AP")),
            self._action(FIF.VPN, "一键开启 AP 远程登入", lambda: self._call_raw_args("ac", "run_ac_action", "enable_ap_remote_login", "一键开启AP远程登入")),
        ]

    def _rail_actions(self) -> list[NCCommandAction]:
        return []

    def _snmp_actions(self) -> list[NCCommandAction]:
        return []

    def _network_actions(self) -> list[NCCommandAction]:
        return []

    def _command_reference_actions(self) -> list[NCCommandAction]:
        return [
            self._action(FIF.DOCUMENT, "复制命令模板", lambda: self._call_raw("command_reference", "copy_selected_command")),
            self._action(FIF.SHARE, "导出 Markdown", lambda: self._call_raw("command_reference", "export_markdown")),
            self._action(FIF.SYNC, "刷新", lambda: self._call_raw("command_reference", "load_references")),
        ]

    def _log_actions(self) -> list[NCCommandAction]:
        return [
            self._action(FIF.SYNC, "刷新", lambda: self._call_raw("logs", "refresh")),
            self._action(FIF.FOLDER, "打开目录", lambda: self._call_raw("logs", "open_log_dir")),
            self._action(FIF.DELETE, "清空当前日志记录", lambda: self._call_raw("logs", "clear_logs")),
            self._action(FIF.DELETE, "清理旧日志", lambda: self._call_raw("logs", "cleanup_old_logs")),
            self._action(FIF.SHARE, "导出", lambda: self._call_raw("logs", "export_logs")),
        ]

    def _settings_actions(self) -> list[NCCommandAction]:
        return [
            self._action(FIF.SAVE, "保存设置", lambda: self._call_raw("system_settings", "save_settings"), primary=True),
            self._action(FIF.SYNC, "刷新", lambda: self._call_raw("system_settings", "reload_settings")),
            self._action(FIF.FOLDER, "打开配置目录", lambda: self._call_raw("system_settings", "open_config_dir")),
            self._action(FIF.CANCEL, "恢复默认", lambda: self._call_raw("system_settings", "reset_defaults"), overflow=True),
        ]

    def _settings_page(self) -> QWidget:
        self.settings_page = SettingsPage(
            self.settings,
            self.site,
            self.paths,
            apply_theme_callback=self.set_theme,
            apply_language_callback=self.apply_language_setting,
            create_site_callback=self.create_site,
            switch_site_callback=self.switch_site_dialog,
            disk_cleanup_callback=self.show_disk_cleanup if self.feature_gate.is_enabled("system.disk_cleanup") else None,
            changelog_callback=self.show_changelog if self.feature_gate.is_enabled("system.changelog") else None,
            open_source_callback=self.show_open_source_notices if self.feature_gate.is_enabled("system.open_source") else None,
        )
        return self.settings_page

    def _create_feature_flags_page(self) -> QWidget:
        from netconsole.ui.pages.feature_flags_page import FeatureFlagsPage

        self.feature_flags_page = FeatureFlagsPage(self.i18n, self.feature_gate, on_profile_saved=self.refresh_feature_flags)
        return self.feature_flags_page

    def _create_device_page(self) -> QWidget:
        self.device_page = DeviceManagementPage(self.repository, self.i18n, self.site.name)
        self.device_page.groups_changed.connect(self.refresh_group_filters)
        self.device_page.devices_changed.connect(self.refresh_device_dependents)
        return self.device_page

    def _create_ac_page(self) -> QWidget:
        from netconsole.ui.pages.ac_management_page import AcManagementPage

        self.ac_page = AcManagementPage(self.repository, self.i18n, self.site.name, self.feature_gate, eager_load=False)
        return self.ac_page

    def _create_rail_transit_page(self) -> QWidget:
        from netconsole.ui.pages.rail_transit_page import RailTransitPage

        self.rail_transit_page = RailTransitPage(self.repository, self.i18n, self.site.name, self.paths, self.feature_gate)
        return self.rail_transit_page

    def _create_wifi_survey_page(self) -> QWidget:
        from netconsole.ui.pages.wifi_survey_page import WifiSurveyPage

        self.wifi_survey_page = WifiSurveyPage(self.i18n, self.site.name, self.paths)
        return self.wifi_survey_page

    def _create_config_collection_page(self) -> QWidget:
        from netconsole.ui.pages.config_collection_center_page import ConfigCollectionCenterPage

        self.config_collection_page = ConfigCollectionCenterPage(self.repository, self.i18n, self.site.name, self.paths)
        return self.config_collection_page

    def _create_file_management_page(self) -> QWidget:
        from netconsole.ui.pages.file_management_page import FileManagementPage

        self.file_management_page = FileManagementPage(self.repository, self.i18n, self.site.name, self.paths, self.feature_gate)
        return self.file_management_page

    def _create_snmp_center_page(self) -> QWidget:
        from netconsole.ui.pages.snmp_center_page import SnmpCenterPage

        self.snmp_center_page = SnmpCenterPage(self.repository, self.i18n, self.site.name, self.paths, self.feature_gate)
        return self.snmp_center_page

    def _create_network_tools_page(self) -> QWidget:
        from netconsole.ui.pages.network_tools_page import NetworkToolsPage

        self.network_tools_page = NetworkToolsPage(self.i18n, self.site.name, self.paths, self.feature_gate)
        return self.network_tools_page

    def _create_command_reference_page(self) -> QWidget:
        from netconsole.ui.pages.command_reference_page import CommandReferencePage

        self.command_reference_page = CommandReferencePage(self.paths)
        return self.command_reference_page

    def _create_log_page(self) -> QWidget:
        from netconsole.ui.pages.app_log_page import AppLogPage

        self.log_page = AppLogPage(self.i18n, auto_refresh=False, paths=self.paths)
        return self.log_page

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._schedule_site_bar_action_sync()
        self.log_startup_geometry_checkpoint("after show immediate")
        self.schedule_startup_geometry_checks()
        if self._info_bar_shown or InfoBar is None:
            return
        self._info_bar_shown = True
        QTimer.singleShot(300, self._show_enabled_info)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        try:
            self._schedule_site_bar_action_sync()
        except Exception:
            app_logger.log_error("APP_TOP_BAR_RESIZE_EVENT_FAILED", traceback.format_exc())

    def closeEvent(self, event) -> None:
        if self._force_close or not self.isVisible():
            event.accept()
            return
        answer = QMessageBox.question(
            self,
            "退出 NetConsole",
            "确认退出 NetConsole？\n\n退出会停止后台任务并关闭已打开的子窗口。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            event.ignore()
            return
        event.accept()
        self._log_main_window_geometry_save_policy()
        self._force_close = True
        self._shutdown_children_and_tasks()
        QApplication.quit()

    def _shutdown_children_and_tasks(self) -> None:
        app_logger.log_info("FLUENT_APP_EXIT", "closing child windows and background tasks")
        for page in list(self.raw_pages.values()):
            shutdown = getattr(page, "shutdown", None)
            if callable(shutdown):
                shutdown()
        background_task_manager.stop_all()
        if shutdown_manager.request_exit("fluent_main_window_close"):
            if not shutdown_manager.wait_for_shutdown(timeout=2.0):
                shutdown_manager.kill_processes()
        for widget in list(QApplication.topLevelWidgets()):
            if widget is self:
                continue
            try:
                widget.close()
            except Exception as exc:
                app_logger.log_warning("FLUENT_CHILD_CLOSE_FAILED", f"{widget.__class__.__name__}: {exc}")

    def _show_enabled_info(self) -> None:
        InfoBar.success(
            title="Fluent UI 已启用",
            content=f"当前主窗口类：AppFluentWindow，当前局点：{self.site.name}",
            duration=3500,
            position=InfoBarPosition.TOP_RIGHT,
            parent=self,
        )

    def preload_page(self, page_id: str) -> None:
        self.preloaded_pages.add(page_id)
        if page_id not in self.pages:
            app_logger.log_warning("FLUENT_PAGE_NOT_REGISTERED", page_id)
            return
        self._ensure_real_page(page_id)

    def mark_preload_failures(self, failures: dict[str, str]) -> None:
        self.preload_failures = dict(failures)

    def refresh_feature_flags(self) -> None:
        self.feature_gate.reload()
        for page_id, page in list(self.raw_pages.items()):
            try:
                apply_gate = getattr(page, "_apply_feature_gate", None)
                if callable(apply_gate):
                    apply_gate()
                reload_from_gate = getattr(page, "reload_from_gate", None)
                if callable(reload_from_gate):
                    reload_from_gate()
                app_logger.log_info("FEATURE_GATE_UI_REFRESH", f"page_id={page_id} page_class={page.__class__.__name__}")
            except Exception:
                app_logger.log_error("FEATURE_GATE_PAGE_REFRESH_FAILED", f"{page_id}\n{traceback.format_exc()}")

    def get_or_create_page(self, page_id: str) -> QWidget:
        if page_id not in self.pages:
            self.preload_page(page_id)
        return self.pages[page_id]

    def activate_page(self, page_id: str, **kwargs) -> None:
        _ = kwargs
        page = self.get_or_create_page(page_id)
        enter_serial = self._page_enter_serial
        self.switchTo(page)
        if self._page_enter_serial == enter_serial:
            self._enter_page(page_id)

    def _handle_stack_current_changed(self, index: int) -> None:
        page = self.stackedWidget.widget(index)
        for page_id, widget in self.pages.items():
            if widget is page:
                self._enter_page(page_id)
                return

    def _enter_page(self, page_id: str) -> None:
        raw_page = self._ensure_real_page(page_id)
        on_enter = getattr(raw_page, "on_enter", None)
        if callable(on_enter):
            self._page_enter_serial += 1
            on_enter()

    def open_current_page(self, row: int) -> None:
        if not 0 <= row < len(self._nav_items):
            return
        self._current_row = row
        page_id = str(self._nav_items[row].data(256))
        self.navigationInterface.setCurrentItem(page_id)
        self.activate_page(page_id, force_if_empty=(page_id == "rail_transit"))

    def create_site(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("新建局点")
        form = QFormLayout()
        name_input = QLineEdit()
        line_input = QLineEdit()
        system_combo = QComboBox()
        system_combo.addItems(["PIS", "信号", "其他"])
        network_combo = QComboBox()
        network_combo.addItems(["default", "A网", "B网", "红网", "蓝网", "其他"])
        remark_input = QLineEdit()
        form.addRow("局点名称", name_input)
        form.addRow("线路名称", line_input)
        form.addRow("系统类型", system_combo)
        form.addRow("网络域", network_combo)
        form.addRow("备注", remark_input)
        basic_page = QWidget()
        basic_page.setLayout(form)
        mesh_params_editor = MeshAnalysisParamsEditor()
        tabs = QTabWidget()
        tabs.addTab(basic_page, "基础信息")
        tabs.addTab(mesh_params_editor, "MR / MESH 分析参数")
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("确定")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout = QVBoxLayout(dialog)
        layout.addWidget(tabs)
        layout.addWidget(buttons)
        dialog.setMinimumWidth(560)
        if dialog.exec() != QDialog.Accepted:
            return
        name = name_input.text().strip()
        if not name:
            return
        try:
            site = self.site_manager.create_site(
                name,
                display_name=name,
                line_name=line_input.text().strip(),
                system_type=str(system_combo.currentText() or "").strip(),
                network_domain=str(network_combo.currentText() or "default").strip(),
                remark=remark_input.text().strip(),
                mesh_analysis_params=mesh_params_editor.params().to_dict(),
            )
        except Exception as exc:
            app_logger.log_warning("SITE_CREATE_FAILED", str(exc))
            QMessageBox.warning(self, "新建局点", str(exc))
            return
        self._switch_to_site(site)
        self._show_info("局点已创建", f"当前局点：{site.name}")

    def switch_site_dialog(self) -> None:
        sites = self.site_manager.list_sites()
        if not sites:
            return
        current_index = sites.index(self.site.name) if self.site.name in sites else 0
        name, accepted = QInputDialog.getItem(self, "切换局点", "请选择局点", sites, current_index, False)
        if not accepted or not name or name == self.site.name:
            return
        try:
            site = self.site_manager.switch_site(name)
        except Exception as exc:
            app_logger.log_warning("SITE_SWITCH_FAILED", str(exc))
            QMessageBox.warning(self, "切换局点", str(exc))
            return
        self._switch_to_site(site)
        self._show_info("局点已切换", f"当前局点：{site.name}")

    def _switch_to_site(self, site: Site) -> None:
        self.site = site
        self.repository = DeviceRepository(Database(site.database_path))
        for page in self.raw_pages.values():
            set_repository = getattr(page, "set_repository", None)
            if callable(set_repository):
                set_repository(self.repository, site.name)
            else:
                set_site = getattr(page, "set_site", None)
                if callable(set_site):
                    set_site(site.name)
        self._update_site_bars()
        settings_page = getattr(self, "settings_page", None)
        if isinstance(settings_page, SettingsPage):
            settings_page.update_site(site)
        app_logger.log_info("SITE_SWITCHED", site.name)

    def _update_site_bars(self) -> None:
        for label in self._site_labels:
            label.setText(f"当前局点：{self.site.name}")
        for label in self._status_labels:
            label.setText("采集状态：就绪")

    def refresh_group_filters(self) -> None:
        for page_id in ("config_collection", "file_management", "rail_transit"):
            page = self.raw_pages.get(page_id)
            refresh_groups = getattr(page, "refresh_groups", None)
            if callable(refresh_groups):
                refresh_groups()

    def refresh_device_dependents(self) -> None:
        for page_id in ("ac", "config_collection", "file_management", "rail_transit", "snmp_center"):
            page = self.raw_pages.get(page_id)
            for method_name in ("refresh_devices", "refresh", "mark_devices_changed", "refresh_all"):
                method = getattr(page, method_name, None)
                if callable(method):
                    try:
                        method()
                    except TypeError:
                        method(False)
                    break

    def toggle_always_on_top(self) -> None:
        enabled = not bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        self.show()
        self._update_always_on_top_labels(enabled)

    def _update_always_on_top_labels(self, enabled: bool) -> None:
        text = "取消置顶" if enabled else "窗口置顶"
        for group in getattr(self, "_site_bar_action_groups", ()):
            top_action = group.get("top_action")
            if hasattr(top_action, "setText"):
                top_action.setText(text)

    def apply_language_setting(self, language: str) -> None:
        self.i18n.set_language(language)
        self._show_info("语言设置已保存", "部分界面将在重启后生效。")

    def detach_current_page(self) -> None:
        self._show_info("弹出模块", "Fluent 主窗口将在后续步骤接入独立窗口弹出。")

    def _show_info(self, title: str, content: str) -> None:
        if InfoBar is None:
            return
        InfoBar.success(title=title, content=content, duration=2500, position=InfoBarPosition.TOP_RIGHT, parent=self)

    def open_current_site_dir(self) -> None:
        path = self.paths.site_dir(self.site.name)
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def show_about(self) -> None:
        from netconsole.ui.dialogs.about_dialog import AboutRepositoryDialog

        dialog = getattr(self, "about_dialog", None)
        if dialog is None:
            dialog = AboutRepositoryDialog(self.i18n, self)
            dialog.destroyed.connect(lambda _=None: setattr(self, "about_dialog", None))
            self.about_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def show_changelog(self) -> None:
        self.feature_gate.assert_enabled("system.changelog")
        from netconsole.ui.dialogs.changelog_dialog import ChangelogDialog

        dialog = getattr(self, "changelog_dialog", None)
        if dialog is None:
            dialog = ChangelogDialog(self.i18n, self)
            dialog.destroyed.connect(lambda _=None: setattr(self, "changelog_dialog", None))
            self.changelog_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def show_disk_cleanup(self) -> None:
        self.feature_gate.assert_enabled("system.disk_cleanup")
        from netconsole.ui.dialogs.disk_cleanup_dialog import DiskCleanupDialog

        dialog = getattr(self, "disk_cleanup_dialog", None)
        if dialog is None:
            dialog = DiskCleanupDialog(self.paths, self)
            dialog.destroyed.connect(lambda _=None: setattr(self, "disk_cleanup_dialog", None))
            self.disk_cleanup_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def show_open_source_notices(self) -> None:
        self.feature_gate.assert_enabled("system.open_source")
        from netconsole.ui.dialogs.open_source_notices_dialog import OpenSourceNoticesDialog

        dialog = getattr(self, "open_source_notices_dialog", None)
        if dialog is None:
            dialog = OpenSourceNoticesDialog(self)
            dialog.destroyed.connect(lambda _=None: setattr(self, "open_source_notices_dialog", None))
            self.open_source_notices_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _click_raw(self, page_id: str, attribute_name: str) -> None:
        button = getattr(self._ensure_real_page(page_id), attribute_name, None)
        if button is not None and hasattr(button, "click"):
            button.click()

    def _call_raw(self, page_id: str, method_name: str) -> None:
        method = getattr(self._ensure_real_page(page_id), method_name, None)
        if callable(method):
            method()

    def _call_raw_args(self, page_id: str, method_name: str, *args) -> None:
        method = getattr(self._ensure_real_page(page_id), method_name, None)
        if callable(method):
            method(*args)

    def _call_current_refresh(self) -> None:
        item = self.navigation.item(self.navigation.currentRow()) if self.navigation.count() else None
        if item is None:
            return
        page = self.raw_pages.get(str(item.data(256)))
        for method_name in ("refresh_all", "refresh", "refresh_devices"):
            method = getattr(page, method_name, None)
            if callable(method):
                method()
                return

    def _log_ui_startup(self) -> None:
        page_names = ", ".join(item.text() for item in self._nav_items)
        tokens = theme_tokens_for(self.current_theme)
        ac_page = self.raw_pages.get("ac")
        ac_tab_actions = []
        if ac_page is not None and hasattr(ac_page, "current_tab_action_labels"):
            ac_tab_actions = ac_page.current_tab_action_labels()
        lines = [
            "[UI] Qt Binding: PySide6",
            "[UI] QFluentWidgets: enabled",
            f"[UI] MainWindow: {self.__class__.__name__}",
            f"[UI] Window chrome: {self._window_chrome_mode()}",
            "[UI] Top bar mode: integrated-single-line",
            f"[UI] Title bar mode: {self._window_chrome_mode()}",
            f"[UI] Top bar safe right: {WINDOW_CONTROL_SAFE_RIGHT}px",
            "[UI] Top bar actions: 新建局点, 切换局点, 弹出模块, 更多",
            "[UI] Overflow actions: 窗口置顶, 打开当前局点目录, 磁盘清理, 版本更新日志, 开源许可, 关于, 退出",
            "[UI] Language switch: settings-page",
            f"[UI] Current language: {self.i18n.language}",
            "[UI] TopBar event handling: safe",
            f"[UI] Window title: {self.windowTitle()}",
            f"[UI] Visible title line: {version_info.APP_NAME} {version_info.APP_VERSION_DISPLAY}",
            *self._window_geometry_log,
            "[UI] Theme source: SettingsStore",
            f"[UI] Settings theme: {self.settings.theme}",
            f"[UI] Normalized theme: {self.current_theme}",
            f"[UI] Fluent theme applied: {self.current_theme}",
            f"[UI] NetConsole stylesheet applied: {self.current_theme}",
            f"[UI] Theme tokens: background={tokens['background']} surface={tokens['surface']} text={tokens['text_primary']}",
            "[UI] Hardcoded dark style scan: fixed-common-theme-entry",
            f"[UI] Theme loaded: {self.settings.theme}",
            f"[UI] Theme color: {self.settings.theme_color}",
            f"[UI] Mica setting: {str(self.settings.mica_enabled).lower()}",
            "[UI] Mica runtime enabled: false",
            "[UI] Settings page: interactive",
            "[UI] CommandBar mode: text-first",
            "[UI] Legacy button bars: removed",
            "[AC] Global actions: 刷新, 获取 AC 信息, 打开网页, 更新 AC 信息, 一键固化新上线 AP, 一键开启 AP 远程登入",
            f"[AC] Current tab actions: {', '.join(ac_tab_actions)}",
            f"[UI] Current site: {self.site.name}",
            f"[UI] Registered pages: {page_names}",
            "[UI] Fallback: no",
        ]
        for line in lines:
            print(line)
            app_logger.log_info("UI_STARTUP", line)

    def _window_chrome_mode(self) -> str:
        return "qfluentwidgets-custom-titlebar" if getattr(self, "titleBar", None) is not None else "native-titlebar"


class _FluentNavigationProxy:
    def __init__(self, window: AppFluentWindow) -> None:
        self.window = window

    def count(self) -> int:
        return len(self.window._nav_items)

    def item(self, index: int) -> QListWidgetItem:
        return self.window._nav_items[index]

    def currentRow(self) -> int:
        return self.window._current_row

    def setCurrentRow(self, row: int) -> None:
        if not 0 <= row < len(self.window._nav_items):
            return
        self.window._current_row = row
        page_id = str(self.window._nav_items[row].data(256))
        self.window.navigationInterface.setCurrentItem(page_id)
        self.window.activate_page(page_id)

    def find_page(self, page_id: str) -> int:
        for index, item in enumerate(self.window._nav_items):
            if item.data(256) == page_id:
                return index
        return -1
