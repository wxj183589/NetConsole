from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtWidgets import QComboBox, QStyledItemDelegate, QStyleOptionViewItem, QWidget


ComboOption = tuple[str, Any]
ComboOptions = Iterable[ComboOption] | Callable[[QModelIndex], Iterable[ComboOption]]


class ComboBoxItemDelegate(QStyledItemDelegate):
    """Edit table option values with a transient combo box instead of cell widgets."""

    def __init__(self, options: ComboOptions, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._options = options

    def _resolved_options(self, index: QModelIndex) -> list[ComboOption]:
        source = self._options(index) if callable(self._options) else self._options
        return list(source)

    def createEditor(self, parent: QWidget, _option: QStyleOptionViewItem, index: QModelIndex) -> QWidget:
        editor = QComboBox(parent)
        options = self._resolved_options(index)
        current_data = index.data(Qt.ItemDataRole.UserRole)
        for label, value in options:
            editor.addItem(str(label), value)
        if current_data is not None and all(value != current_data for _label, value in options):
            editor.addItem(str(index.data(Qt.ItemDataRole.DisplayRole) or current_data), current_data)
        return editor

    def setEditorData(self, editor: QWidget, index: QModelIndex) -> None:
        if not isinstance(editor, QComboBox):
            return
        current_data = index.data(Qt.ItemDataRole.UserRole)
        for option_index in range(editor.count()):
            if editor.itemData(option_index) == current_data:
                editor.setCurrentIndex(option_index)
                return

    def setModelData(self, editor: QWidget, model, index: QModelIndex) -> None:
        if not isinstance(editor, QComboBox):
            return
        model.setData(index, editor.currentText(), Qt.ItemDataRole.EditRole)
        model.setData(index, editor.currentData(), Qt.ItemDataRole.UserRole)


def combo_item_value(item, default: Any = "") -> Any:
    if item is None:
        return default
    value = item.data(Qt.ItemDataRole.UserRole)
    return default if value is None else value
