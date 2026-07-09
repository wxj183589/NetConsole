from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QWidget

from netconsole.ui.dialogs.dialog_style import apply_dialog_style, polish_dialog_buttons


class MessageBox(QMessageBox):
    StandardButton = QMessageBox.StandardButton
    Icon = QMessageBox.Icon
    ButtonRole = QMessageBox.ButtonRole

    Ok = QMessageBox.StandardButton.Ok
    Yes = QMessageBox.StandardButton.Yes
    No = QMessageBox.StandardButton.No
    Cancel = QMessageBox.StandardButton.Cancel
    Save = QMessageBox.StandardButton.Save
    Discard = QMessageBox.StandardButton.Discard

    Information = QMessageBox.Icon.Information
    Warning = QMessageBox.Icon.Warning
    Critical = QMessageBox.Icon.Critical
    Question = QMessageBox.Icon.Question
    NoIcon = QMessageBox.Icon.NoIcon

    ActionRole = QMessageBox.ButtonRole.ActionRole
    DestructiveRole = QMessageBox.ButtonRole.DestructiveRole
    RejectRole = QMessageBox.ButtonRole.RejectRole
    AcceptRole = QMessageBox.ButtonRole.AcceptRole

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        apply_dialog_style(self, minimum_size=(420, 180))

    @staticmethod
    def information(parent: QWidget | None, title: str, text: str, *args, **kwargs) -> QMessageBox.StandardButton:
        return _show_standard(parent, title, text, QMessageBox.Icon.Information, *args, **kwargs)

    @staticmethod
    def warning(parent: QWidget | None, title: str, text: str, *args, **kwargs) -> QMessageBox.StandardButton:
        return _show_standard(parent, title, text, QMessageBox.Icon.Warning, *args, **kwargs)

    @staticmethod
    def critical(parent: QWidget | None, title: str, text: str, *args, **kwargs) -> QMessageBox.StandardButton:
        return _show_standard(parent, title, text, QMessageBox.Icon.Critical, *args, **kwargs)

    @staticmethod
    def question(parent: QWidget | None, title: str, text: str, *args, **kwargs) -> QMessageBox.StandardButton:
        buttons = args[0] if args else kwargs.pop("buttons", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        default = args[1] if len(args) > 1 else kwargs.pop("defaultButton", QMessageBox.StandardButton.No)
        return _show_standard(parent, title, text, QMessageBox.Icon.Question, buttons, default)


def show_info(parent: QWidget | None, title: str, message: str) -> QMessageBox.StandardButton:
    return MessageBox.information(parent, title, message)


def show_success(parent: QWidget | None, title: str, message: str) -> QMessageBox.StandardButton:
    if _show_infobar("success", parent, title, message):
        return QMessageBox.StandardButton.Ok
    return MessageBox.information(parent, title, message)


def show_warning(parent: QWidget | None, title: str, message: str) -> QMessageBox.StandardButton:
    return MessageBox.warning(parent, title, message)


def show_error(parent: QWidget | None, title: str, message: str) -> QMessageBox.StandardButton:
    return MessageBox.critical(parent, title, message)


def confirm(
    parent: QWidget | None,
    title: str,
    message: str,
    *,
    yes_text: str = "确定",
    no_text: str = "取消",
    danger: bool = False,
) -> bool:
    box = MessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning if danger else QMessageBox.Icon.Question)
    box.setWindowTitle(title)
    box.setText(message)
    box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    box.setDefaultButton(QMessageBox.StandardButton.No)
    yes_button = box.button(QMessageBox.StandardButton.Yes)
    no_button = box.button(QMessageBox.StandardButton.No)
    if yes_button is not None:
        yes_button.setText(yes_text)
        yes_button.setObjectName("ncDangerButton" if danger else "ncPrimaryButton")
    if no_button is not None:
        no_button.setText(no_text)
        no_button.setObjectName("ncSecondaryButton")
    polish_dialog_buttons(box)
    apply_dialog_style(box, minimum_size=(460, 190))
    return box.exec() == QMessageBox.StandardButton.Yes


def _show_standard(
    parent: QWidget | None,
    title: str,
    text: str,
    icon: QMessageBox.Icon,
    buttons: QMessageBox.StandardButtons | QMessageBox.StandardButton = QMessageBox.StandardButton.Ok,
    default_button: QMessageBox.StandardButton = QMessageBox.StandardButton.NoButton,
    *args,
    **kwargs,
) -> QMessageBox.StandardButton:
    _ = args, kwargs
    box = MessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setIcon(icon)
    box.setStandardButtons(buttons)
    if default_button != QMessageBox.StandardButton.NoButton:
        box.setDefaultButton(default_button)
    _localize_standard_buttons(box)
    apply_dialog_style(box, minimum_size=(420, 180))
    return QMessageBox.StandardButton(box.exec())


def _localize_standard_buttons(box: QMessageBox) -> None:
    labels = {
        QMessageBox.StandardButton.Ok: "确定",
        QMessageBox.StandardButton.Yes: "确定",
        QMessageBox.StandardButton.No: "取消",
        QMessageBox.StandardButton.Cancel: "取消",
        QMessageBox.StandardButton.Save: "保存",
        QMessageBox.StandardButton.Discard: "不保存",
    }
    for button, text in labels.items():
        widget = box.button(button)
        if widget is not None:
            widget.setText(text)
    polish_dialog_buttons(box)


def _show_infobar(kind: str, parent: QWidget | None, title: str, message: str) -> bool:
    if parent is None:
        return False
    try:
        from qfluentwidgets import InfoBar, InfoBarPosition
    except Exception:
        return False
    method = getattr(InfoBar, kind, None)
    if not callable(method):
        return False
    try:
        method(
            title=title,
            content=message,
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP_RIGHT,
            duration=2800,
            parent=parent,
        )
        return True
    except Exception:
        return False
