from __future__ import annotations

from time import perf_counter

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QLabel, QListWidgetItem, QStackedWidget, QVBoxLayout, QWidget

from netconsole.core import app_logger
from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.core.settings import SettingsStore
from netconsole.core.sites import Site
from netconsole.core import version as version_info
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.ui.pages.device_management_page import DeviceManagementPage
from netconsole.ui.shell.fluent_bridge import (
    Action,
    CommandBar,
    FIF,
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    PushButton,
    SettingCard,
    SettingCardGroup,
    SplitFluentWindow,
    TransparentToolButton,
    apply_fluent_theme,
)
from netconsole.ui.windowing import fit_default_window_size


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
        self.current_theme = self.settings.theme
        self.pages: dict[str, QWidget] = {}
        self._nav_items: list[QListWidgetItem] = []
        self._current_row = 0
        self.preloaded_pages: set[str] = set()
        self.preload_failures: dict[str, str] = {}
        self._info_bar_shown = False

        apply_fluent_theme(self.current_theme)
        self.setMicaEffectEnabled(False)
        self.setWindowTitle(f"{version_info.APP_NAME} {version_info.APP_VERSION_DISPLAY}")
        self.resize_for_screen()

        self.device_page = DeviceManagementPage(repository, i18n, site.name)
        self._add_page("devices", self._command_page("设备管理", self.device_page, self._device_actions()), FIF.APPLICATION, "设备管理")
        self._add_page("task_center", self._task_center_page(), FIF.SYNC, "任务中心")
        self._add_page("system_settings", self._settings_page(), FIF.SETTING, "系统设置")

        self.stack = self.stackedWidget
        self.navigation = _FluentNavigationProxy(self)
        app_logger.log_info("WINDOW_CLASS", self.__class__.__name__)
        app_logger.log_info("FLUENT_UI_ENABLED", f"class={self.__class__.__name__} site={site.name}")

    def resize_for_screen(self) -> None:
        screen = self.screen()
        if screen is None:
            self.resize(1440, 900)
            return
        available = screen.availableGeometry()
        size = fit_default_window_size(available.width(), available.height(), 1440, 900)
        self.resize(size.width, size.height)
        frame = self.frameGeometry()
        frame.moveCenter(available.center())
        self.move(frame.topLeft())
        self.setMinimumSize(1280, 760)

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

    def _command_page(self, title: str, content: QWidget, actions: list[Action]) -> QWidget:
        page = QWidget()
        page.setObjectName("fluentPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 16, 20, 20)
        layout.setSpacing(12)
        command_bar = CommandBar()
        command_bar.setObjectName("fluentCommandBar")
        for action in actions:
            command_bar.addAction(action)
        layout.addWidget(self._page_title(title))
        layout.addWidget(command_bar)
        layout.addWidget(content, 1)
        return page

    def _page_title(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("fluentPageTitle")
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        return label

    def _device_actions(self) -> list[Action]:
        return [
            Action(FIF.ADD, "新增"),
            Action(FIF.DOWNLOAD, "导入"),
            Action(FIF.SHARE, "导出"),
            Action(FIF.CONNECT, "测试连接"),
            Action(FIF.SYNC, "刷新"),
            Action(FIF.MORE, "更多"),
        ]

    def _task_center_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 16, 20, 20)
        layout.setSpacing(12)
        command_bar = CommandBar()
        for action in (
            Action(FIF.PLAY, "启动"),
            Action(FIF.CANCEL, "取消"),
            Action(FIF.DELETE, "删除"),
            Action(FIF.FOLDER, "打开日志"),
            Action(FIF.SYNC, "刷新"),
        ):
            command_bar.addAction(action)
        layout.addWidget(self._page_title("任务中心"))
        layout.addWidget(command_bar)
        card = QWidget()
        card.setObjectName("fluentCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 18, 18, 18)
        card_layout.setSpacing(10)
        card_layout.addWidget(QLabel("任务中心 Fluent 壳已启用，后续逐步接入采集任务列表和状态标签。"))
        card_layout.addWidget(PrimaryPushButton("创建采集任务"))
        card_layout.addWidget(PushButton("查看运行日志"))
        card_layout.addWidget(TransparentToolButton(FIF.MORE))
        layout.addWidget(card)
        layout.addStretch(1)
        return page

    def _settings_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 16, 20, 20)
        layout.setSpacing(12)
        command_bar = CommandBar()
        command_bar.addAction(Action(FIF.SAVE, "保存"))
        command_bar.addAction(Action(FIF.SYNC, "重载"))
        layout.addWidget(self._page_title("系统设置"))
        layout.addWidget(command_bar)
        appearance = SettingCardGroup("外观")
        appearance.addSettingCard(SettingCard(FIF.BRUSH, "主题", "浅色 / 深色 / 跟随系统"))
        appearance.addSettingCard(SettingCard(FIF.TRANSPARENT, "Mica 效果", "默认关闭，不支持时自动降级"))
        collection = SettingCardGroup("采集")
        collection.addSettingCard(SettingCard(FIF.SPEED_HIGH, "默认并发数", "后续接入现有采集参数"))
        collection.addSettingCard(SettingCard(FIF.HISTORY, "日志保留", "后续接入日志策略"))
        layout.addWidget(appearance)
        layout.addWidget(collection)
        layout.addStretch(1)
        return page

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._info_bar_shown or InfoBar is None:
            return
        self._info_bar_shown = True
        QTimer.singleShot(300, self._show_enabled_info)

    def _show_enabled_info(self) -> None:
        InfoBar.success(
            title="Fluent UI 已启用",
            content="当前主窗口类：AppFluentWindow",
            duration=3500,
            position=InfoBarPosition.TOP_RIGHT,
            parent=self,
        )

    def preload_page(self, page_id: str) -> None:
        self.preloaded_pages.add(page_id)
        if page_id not in self.pages:
            self._add_page(page_id, self._command_page(page_id, QLabel("此模块将在后续 Fluent 化步骤中接入。"), [Action(FIF.SYNC, "刷新")]), FIF.APPLICATION, page_id)

    def mark_preload_failures(self, failures: dict[str, str]) -> None:
        self.preload_failures = dict(failures)

    def get_or_create_page(self, page_id: str) -> QWidget:
        if page_id not in self.pages:
            self.preload_page(page_id)
        return self.pages[page_id]

    def activate_page(self, page_id: str, **kwargs) -> None:
        _ = kwargs
        self.stackedWidget.setCurrentWidget(self.get_or_create_page(page_id))

    def open_current_page(self, row: int) -> None:
        if not 0 <= row < len(self._nav_items):
            return
        self._current_row = row
        page_id = str(self._nav_items[row].data(256))
        self.navigationInterface.setCurrentItem(page_id)
        self.activate_page(page_id, force_if_empty=(page_id == "rail_transit"))


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
