from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import QObject, QEvent, QSize, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QWidget,
)

from netconsole.ui.components.button_icons import apply_button_icon
from netconsole.ui.windowing import available_screen_geometry
from netconsole.ui.window_registry import window_registry


PRIMARY_WORDS = ("确定", "保存", "应用", "开始", "导出", "导入", "测试", "刷新", "查询", "连接")
SECONDARY_WORDS = ("取消", "关闭", "返回")
DANGER_WORDS = ("删除", "清理", "移除", "重建", "清空", "强制", "退出")
ICON_WORDS = {
    "确定": "ACCEPT",
    "应用": "ACCEPT",
    "保存": "SAVE",
    "取消": "CLOSE",
    "关闭": "CLOSE",
    "删除": "DELETE",
    "移除": "DELETE",
    "清理": "DELETE",
    "清空": "DELETE",
    "重建": "DELETE",
    "刷新": "SYNC",
    "更新": "SYNC",
    "导入": "DOWNLOAD",
    "导出": "SAVE",
    "下载": "DOWNLOAD",
    "浏览": "FOLDER",
    "选择": "FOLDER",
    "测试": "CONNECT",
    "连接": "LINK",
    "复制": "COPY",
    "搜索": "SEARCH",
    "查询": "SEARCH",
    "设置": "SETTING",
    "退出": "CLOSE",
}


def dialog_stylesheet_for_theme(mode: str) -> str:
    from netconsole.ui.theme.qt_theme_engine import theme_tokens_for

    tokens = theme_tokens_for(mode)
    return f"""
QDialog#ncDialog {{
    background-color: {tokens["background"]};
    color: {tokens["text_primary"]};
}}
QWidget#ncPopupWindow {{
    background-color: {tokens["background"]};
    color: {tokens["text_primary"]};
}}
QFrame#ncDialogRoot {{
    background-color: {tokens["surface"]};
    border: 1px solid {tokens["border"]};
    border-radius: 8px;
}}
QFrame#ncDialogHeader {{
    background-color: {tokens["surface"]};
    border-bottom: 1px solid {tokens["border"]};
}}
QLabel#ncDialogTitle {{
    color: {tokens["text_primary"]};
    font-size: 15px;
    font-weight: 700;
}}
QLabel#ncDialogSubtitle {{
    color: {tokens["text_muted"]};
    font-size: 12px;
}}
QFrame#ncDialogContent, QWidget#ncDialogContent {{
    background-color: {tokens["surface"]};
    color: {tokens["text_primary"]};
}}
QFrame#ncDialogCard {{
    background-color: {tokens["surface_alt"]};
    border: 1px solid {tokens["border"]};
    border-radius: 8px;
}}
QFrame#ncDialogFooter {{
    background-color: {tokens["surface"]};
    border-top: 1px solid {tokens["border"]};
}}
QScrollArea#ncDialogScrollArea {{
    background-color: {tokens["surface"]};
    border: 0;
}}
QScrollArea#ncDialogScrollArea > QWidget > QWidget {{
    background-color: {tokens["surface"]};
}}
QPushButton#ncPrimaryButton {{
    background-color: {tokens["primary"]};
    border: 1px solid {tokens["primary"]};
    border-radius: 5px;
    color: #ffffff;
    min-height: 32px;
    min-width: 82px;
    padding: 6px 14px;
    font-weight: 600;
}}
QPushButton#ncPrimaryButton:hover {{
    background-color: {tokens["primary_hover"]};
    border-color: {tokens["primary_hover"]};
}}
QPushButton#ncSecondaryButton, QDialogButtonBox QPushButton {{
    background-color: {tokens["surface"]};
    border: 1px solid {tokens["border_strong"]};
    border-radius: 5px;
    color: {tokens["text_primary"]};
    min-height: 32px;
    min-width: 82px;
    padding: 6px 14px;
}}
QPushButton#ncSecondaryButton:hover, QDialogButtonBox QPushButton:hover {{
    background-color: {tokens["hover"]};
    border-color: {tokens["primary"]};
}}
QPushButton#ncDangerButton {{
    background-color: {tokens["danger_surface"]};
    border: 1px solid {tokens["danger"]};
    border-radius: 5px;
    color: {tokens["danger"]};
    min-height: 32px;
    min-width: 82px;
    padding: 6px 14px;
    font-weight: 600;
}}
QPushButton#ncDangerButton:hover {{
    background-color: {tokens["danger"]};
    color: #ffffff;
}}
QPushButton#ncGhostButton {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 5px;
    color: {tokens["text_primary"]};
    min-height: 32px;
    min-width: 82px;
    padding: 6px 12px;
}}
QPushButton#ncGhostButton:hover {{
    background-color: {tokens["hover"]};
    border-color: {tokens["border"]};
}}
"""


def apply_dialog_style(
    dialog: QDialog,
    *,
    title: str | None = None,
    subtitle: str | None = None,
    minimum_size: QSize | tuple[int, int] | None = None,
    default_size: QSize | tuple[int, int] | None = None,
    scrollable: bool = False,
    center: bool = True,
    delete_on_close: bool = False,
) -> QDialog:
    _ = subtitle
    if title:
        dialog.setWindowTitle(title)
    if delete_on_close:
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    if not dialog.objectName():
        dialog.setObjectName("ncDialog")
    dialog.setProperty("netconsoleDialog", True)
    if minimum_size is not None:
        width, height = _size_pair(minimum_size)
        dialog.setMinimumSize(width, height)
    if default_size is not None and not dialog.property("_ncDefaultSizeApplied"):
        width, height = _size_pair(default_size)
        dialog.resize(width, height)
        dialog.setProperty("_ncDefaultSizeApplied", True)
    polish_dialog_buttons(dialog)
    _tag_dialog_scroll_areas(dialog)
    _refresh_styles(dialog)
    if center:
        QTimer.singleShot(0, lambda d=dialog: center_dialog(d))
    if scrollable:
        _ensure_dialog_can_resize(dialog)
    return dialog


def apply_popup_window_style(window: QWidget, *, center: bool = True) -> QWidget:
    if not window.objectName():
        window.setObjectName("ncPopupWindow")
    window.setProperty("netconsoleDialog", True)
    polish_dialog_buttons(window)
    _tag_dialog_scroll_areas(window)
    _refresh_styles(window)
    if center and not window.property("_ncCenteredOnce"):
        QTimer.singleShot(0, lambda w=window: center_dialog(w))
    return window


def polish_dialog_buttons(root_widget: QWidget) -> None:
    for button_box in root_widget.findChildren(QDialogButtonBox):
        for button in button_box.buttons():
            _polish_button(button)
    for button in root_widget.findChildren(QPushButton):
        _polish_button(button)


def center_dialog(dialog: QWidget, parent: QWidget | None = None, max_screen_ratio: float = 0.88) -> None:
    if dialog.property("_ncCenteredOnce"):
        return
    dialog.setProperty("_ncCenteredOnce", True)
    parent = parent or dialog.parentWidget()
    available = _available_geometry_for(dialog, parent)
    max_width = max(320, int(available.width() * max_screen_ratio))
    max_height = max(240, int(available.height() * max_screen_ratio))

    hint = dialog.sizeHint()
    width = dialog.width() if dialog.width() > 0 else hint.width()
    height = dialog.height() if dialog.height() > 0 else hint.height()
    if width <= 0:
        width = 640
    if height <= 0:
        height = 420
    width = min(width, max_width)
    height = min(height, max_height)
    dialog.resize(width, height)

    frame = dialog.frameGeometry()
    frame.setWidth(width)
    frame.setHeight(height)
    if parent is not None and parent.isVisible():
        target = parent.frameGeometry().center()
    else:
        target = available.center()
    frame.moveCenter(target)
    if frame.left() < available.left():
        frame.moveLeft(available.left())
    if frame.top() < available.top():
        frame.moveTop(available.top())
    if frame.right() > available.right():
        frame.moveRight(available.right())
    if frame.bottom() > available.bottom():
        frame.moveBottom(available.bottom())
    dialog.move(frame.topLeft())


def install_dialog_style_event_filter(app: QApplication | None = None) -> None:
    app = app or QApplication.instance()
    if app is None or app.property("_ncDialogStyleFilterInstalled"):
        return
    event_filter = _DialogStyleEventFilter(app)
    app.installEventFilter(event_filter)
    app.setProperty("_ncDialogStyleFilterInstalled", True)
    app.setProperty("_ncDialogStyleFilter", event_filter)


def wrap_dialog_content_if_needed(dialog: QDialog, content: QWidget) -> QScrollArea:
    scroll_area = QScrollArea(dialog)
    scroll_area.setObjectName("ncDialogScrollArea")
    scroll_area.setWidgetResizable(True)
    scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    scroll_area.setFrameShape(QFrame.NoFrame)
    scroll_area.setWidget(content)
    return scroll_area


class _DialogStyleEventFilter(QObject):
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() != QEvent.Show or not isinstance(watched, QWidget):
            return False
        if isinstance(watched, QDialog):
            apply_dialog_style(watched)
        elif _looks_like_popup_window(watched):
            apply_popup_window_style(watched)
            window_registry.register(watched)
        return False


def _polish_button(button: QPushButton) -> None:
    text = button.text().strip()
    if not text:
        return
    if not button.objectName() or button.objectName() in {"qt_msgbox_buttonbox"}:
        button.setObjectName(_button_object_name(text))
    button.setMinimumHeight(max(button.minimumHeight(), 32))
    button.setMinimumWidth(max(button.minimumWidth(), 82))
    button.setSizePolicy(QSizePolicy.Policy.Minimum, button.sizePolicy().verticalPolicy())
    icon_name = _icon_for_text(text)
    if icon_name:
        apply_button_icon(button, icon_name)
    if not button.toolTip():
        button.setToolTip(text)


def _button_object_name(text: str) -> str:
    if _contains_any(text, DANGER_WORDS):
        return "ncDangerButton"
    if _contains_any(text, SECONDARY_WORDS):
        return "ncSecondaryButton"
    if _contains_any(text, PRIMARY_WORDS):
        return "ncPrimaryButton"
    return "ncSecondaryButton"


def _icon_for_text(text: str) -> str | None:
    for word, icon in ICON_WORDS.items():
        if word in text:
            return icon
    return None


def _contains_any(text: str, words: Iterable[str]) -> bool:
    return any(word in text for word in words)


def _size_pair(size: QSize | tuple[int, int]) -> tuple[int, int]:
    if isinstance(size, QSize):
        return size.width(), size.height()
    return size


def _tag_dialog_scroll_areas(root_widget: QWidget) -> None:
    for scroll_area in root_widget.findChildren(QScrollArea):
        if not scroll_area.objectName():
            scroll_area.setObjectName("ncDialogScrollArea")


def _ensure_dialog_can_resize(dialog: QDialog) -> None:
    flags = dialog.windowFlags()
    flags |= Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint
    dialog.setWindowFlags(flags)


def _refresh_styles(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def _looks_like_popup_window(widget: QWidget) -> bool:
    if not widget.isWindow():
        return False
    class_name = widget.__class__.__name__
    if class_name in {"MainWindow", "AppFluentWindow"}:
        return False
    return class_name.endswith("Dialog")


def _available_geometry_for(dialog: QWidget, parent: QWidget | None) -> object:
    if parent is not None:
        handle = parent.windowHandle()
        if handle is not None and handle.screen() is not None:
            return handle.screen().availableGeometry()
    handle = dialog.windowHandle()
    if handle is not None and handle.screen() is not None:
        return handle.screen().availableGeometry()
    screen = QGuiApplication.screenAt(dialog.pos())
    if screen is not None:
        return screen.availableGeometry()
    return available_screen_geometry()
