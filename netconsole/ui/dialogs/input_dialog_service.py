from __future__ import annotations

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
        accepted = _exec_input_dialog(parent, title, label, edit)
        return edit.text(), accepted

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
        combo.addItems([str(item) for item in items])
        if items:
            combo.setCurrentIndex(max(0, min(current, len(items) - 1)))
        combo.setMinimumWidth(260)
        accepted = _exec_input_dialog(parent, title, label, combo)
        return combo.currentText(), accepted

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
        accepted = _exec_input_dialog(parent, title, label, spin)
        return spin.value(), accepted


def _exec_input_dialog(parent: QWidget | None, title: str, label: str, input_widget: QWidget) -> bool:
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(18, 18, 18, 14)
    layout.setSpacing(14)
    form = QFormLayout()
    form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
    form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    form.setHorizontalSpacing(12)
    form.setVerticalSpacing(10)
    form.addRow(label, input_widget)
    layout.addLayout(form)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
    buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    apply_dialog_style(dialog, minimum_size=(420, 170), center=True)
    input_widget.setFocus()
    return dialog.exec() == QDialog.DialogCode.Accepted
