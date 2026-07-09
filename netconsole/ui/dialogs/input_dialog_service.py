from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from netconsole.ui.dialogs.dialog_style import apply_dialog_style
from netconsole.ui.window_popup_service import show_non_focus_window


class InputDialog:
    @staticmethod
    def getText(
        parent: QWidget | None,
        title: str,
        label: str,
        mode: QLineEdit.EchoMode = QLineEdit.EchoMode.Normal,
        text: str = "",
        *args,
        **kwargs,
    ) -> tuple[str, bool]:
        _ = args, kwargs
        edit = QLineEdit()
        edit.setEchoMode(mode)
        edit.setText(text)
        return _exec_input_dialog(parent, title, label, edit, lambda: edit.text(), text)

    @staticmethod
    def getItem(
        parent: QWidget | None,
        title: str,
        label: str,
        items: list[str] | tuple[str, ...],
        current: int = 0,
        editable: bool = True,
        *args,
        **kwargs,
    ) -> tuple[str, bool]:
        _ = args, kwargs
        combo = QComboBox()
        combo.setEditable(editable)
        item_texts = [str(item) for item in items]
        combo.addItems(item_texts)
        if item_texts:
            try:
                current_index = int(current)
            except (TypeError, ValueError):
                current_index = 0
            combo.setCurrentIndex(max(0, min(current_index, len(item_texts) - 1)))
        combo.setMinimumWidth(260)
        initial_value = combo.currentText() if item_texts or editable else ""
        return _exec_input_dialog(parent, title, label, combo, lambda: combo.currentText(), initial_value)

    @staticmethod
    def getItemAsync(
        parent: QWidget | None,
        title: str,
        label: str,
        items: list[str] | tuple[str, ...],
        current: int = 0,
        editable: bool = True,
        *,
        on_accepted: Callable[[str], None],
        on_rejected: Callable[[], None] | None = None,
    ) -> QDialog:
        combo = QComboBox()
        combo.setEditable(editable)
        item_texts = [str(item) for item in items]
        combo.addItems(item_texts)
        if item_texts:
            try:
                current_index = int(current)
            except (TypeError, ValueError):
                current_index = 0
            combo.setCurrentIndex(max(0, min(current_index, len(item_texts) - 1)))
        combo.setMinimumWidth(260)
        return _show_input_dialog_async(parent, title, label, combo, lambda: combo.currentText(), on_accepted, on_rejected)

    get_item_async = getItemAsync

    @staticmethod
    def getDouble(
        parent: QWidget | None,
        title: str,
        label: str,
        value: float = 0.0,
        minimum: float = -2147483647.0,
        maximum: float = 2147483647.0,
        decimals: int = 1,
        *args,
        **kwargs,
    ) -> tuple[float, bool]:
        _ = args, kwargs
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(decimals)
        spin.setValue(value)
        spin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        spin.setMinimumWidth(220)
        return _exec_input_dialog(parent, title, label, spin, lambda: spin.value(), spin.value())


def _exec_input_dialog(parent: QWidget | None, title: str, label: str, input_widget: QWidget, value_reader, initial_value):
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setModal(True)
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(18, 18, 18, 14)
    layout.setSpacing(14)
    form = QFormLayout()
    form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
    form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    form.setHorizontalSpacing(12)
    form.setVerticalSpacing(10)
    input_widget.setParent(dialog)
    form.addRow(label, input_widget)
    layout.addLayout(form)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
    buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
    ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
    if isinstance(input_widget, QComboBox) and input_widget.count() == 0 and not input_widget.isEditable():
        if ok_button is not None:
            ok_button.setEnabled(False)
    result = {"value": initial_value, "accepted": False}

    def on_accept() -> None:
        result["value"] = value_reader()
        result["accepted"] = True
        dialog.accept()

    def on_reject() -> None:
        result["accepted"] = False
        dialog.reject()

    buttons.accepted.connect(on_accept)
    buttons.rejected.connect(on_reject)
    layout.addWidget(buttons)
    apply_dialog_style(dialog, minimum_size=(420, 170), center=True, delete_on_close=False)
    input_widget.setFocus()
    dialog.exec()
    return result["value"], result["accepted"]


def _show_input_dialog_async(
    parent: QWidget | None,
    title: str,
    label: str,
    input_widget: QWidget,
    value_reader,
    on_accepted: Callable,
    on_rejected: Callable[[], None] | None,
) -> QDialog:
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setModal(False)
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(18, 18, 18, 14)
    layout.setSpacing(14)
    form = QFormLayout()
    form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
    form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    form.setHorizontalSpacing(12)
    form.setVerticalSpacing(10)
    input_widget.setParent(dialog)
    form.addRow(label, input_widget)
    layout.addLayout(form)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
    buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
    ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
    if isinstance(input_widget, QComboBox) and input_widget.count() == 0 and not input_widget.isEditable():
        if ok_button is not None:
            ok_button.setEnabled(False)

    def cleanup() -> None:
        dialog.deleteLater()

    def accept() -> None:
        value = value_reader()
        dialog.accept()
        on_accepted(value)

    def reject() -> None:
        dialog.reject()
        if on_rejected is not None:
            on_rejected()

    buttons.accepted.connect(accept)
    buttons.rejected.connect(reject)
    dialog.finished.connect(lambda _=0: cleanup())
    layout.addWidget(buttons)
    apply_dialog_style(dialog, minimum_size=(420, 170), center=False, delete_on_close=False)
    show_non_focus_window(parent, dialog, key=f"input_dialog:{title}", activate=False, raise_window=False)
    return dialog
