from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QIcon, QMouseEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget

from netconsole.core import version as version_info
from netconsole.core.resources import icon_path
from netconsole.ui.shell.theme import TITLE_BAR_HEIGHT, next_theme


class AppTitleBar(QWidget):
    minimize_requested = Signal()
    maximize_restore_requested = Signal()
    close_requested = Signal()
    theme_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("appTitleBar")
        self.setFixedHeight(TITLE_BAR_HEIGHT)
        self._theme = "dark"

        self.icon_label = QLabel()
        self.icon_label.setObjectName("appTitleIcon")
        self.icon_label.setFixedSize(22, 22)
        self.icon_label.setPixmap(QIcon(str(icon_path("love.png"))).pixmap(18, 18))

        self.title_label = QLabel(version_info.APP_NAME)
        self.title_label.setObjectName("appTitleText")
        self.title_label.setMinimumWidth(220)

        self.site_label = QLabel()
        self.site_label.setObjectName("appTitleMeta")
        self.status_label = QLabel()
        self.status_label.setObjectName("appTitleStatus")

        self.theme_button = QPushButton()
        self.theme_button.setObjectName("titleBarToolButton")
        self.theme_button.setFixedSize(34, 30)
        self.theme_button.setToolTip("切换主题")
        self.theme_button.clicked.connect(self._request_next_theme)

        self.minimize_button = self._window_button("titleBarMinButton", "_", "最小化")
        self.maximize_button = self._window_button("titleBarMaxButton", "□", "最大化")
        self.close_button = self._window_button("titleBarCloseButton", "×", "关闭")

        self.minimize_button.clicked.connect(self.minimize_requested)
        self.maximize_button.clicked.connect(self.maximize_restore_requested)
        self.close_button.clicked.connect(self.close_requested)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 8, 0)
        layout.setSpacing(8)
        layout.addWidget(self.icon_label)
        layout.addWidget(self.title_label)
        layout.addWidget(self.site_label)
        layout.addWidget(self.status_label)
        layout.addStretch(1)
        layout.addWidget(self.theme_button)
        layout.addWidget(self.minimize_button)
        layout.addWidget(self.maximize_button)
        layout.addWidget(self.close_button)

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.set_theme(self._theme)
        self.set_context("", "就绪")

    def _window_button(self, object_name: str, text: str, tooltip: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName(object_name)
        button.setFixedSize(42, 32)
        button.setToolTip(tooltip)
        button.setProperty("titleBarControl", True)
        return button

    def _request_next_theme(self) -> None:
        self.theme_requested.emit(next_theme(self._theme))

    def set_theme(self, theme: str) -> None:
        self._theme = "dark" if theme == "dark" else "light"
        self.theme_button.setText("亮" if self._theme == "dark" else "暗")
        self.theme_button.setToolTip("切换为亮色主题" if self._theme == "dark" else "切换为深色主题")

    def set_context(self, site_name: str, status: str) -> None:
        self.site_label.setText(f"当前局点：{site_name}" if site_name else "")
        self.status_label.setText(f"运行状态：{status or '就绪'}")

    def set_maximized(self, maximized: bool) -> None:
        self.maximize_button.setText("❐" if maximized else "□")
        self.maximize_button.setToolTip("还原" if maximized else "最大化")

    def is_drag_area(self, global_pos: QPoint) -> bool:
        local_pos = self.mapFromGlobal(global_pos)
        if not self.rect().contains(local_pos):
            return False
        child = self.childAt(local_pos)
        while child is not None:
            if child.property("titleBarControl"):
                return False
            child = child.parentWidget()
        return True

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.is_drag_area(event.globalPosition().toPoint()):
            self.maximize_restore_requested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)
