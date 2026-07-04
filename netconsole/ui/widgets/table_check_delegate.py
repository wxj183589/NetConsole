from __future__ import annotations

from PySide6.QtCore import QEvent, QRect, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QStyle, QStyledItemDelegate, QStyleOptionButton, QStyleOptionViewItem, QTableWidget, QTableWidgetItem


def is_checked_value(value: object) -> bool:
    if value == Qt.CheckState.Checked:
        return True
    expected = getattr(Qt.CheckState.Checked, "value", Qt.CheckState.Checked)
    current = getattr(value, "value", value)
    try:
        return int(current) == int(expected)
    except (TypeError, ValueError):
        return False


class CheckBoxOnlyDelegate(QStyledItemDelegate):
    """Paint only a centered checkbox for table batch-selection columns.

    Project convention: all QTableWidget batch-selection columns should use
    QTableWidgetItem + CheckStateRole with this delegate. Do not put QCheckBox
    cell widgets in table cells, and do not copy page-local checkbox delegates.
    """

    def paint(self, painter, option, index) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        style = opt.widget.style() if opt.widget else QApplication.style()

        opt.state &= ~QStyle.StateFlag.State_HasFocus
        opt.text = ""
        opt.icon = QIcon()
        opt.features &= ~QStyleOptionViewItem.ViewItemFeature.HasDisplay
        opt.features &= ~QStyleOptionViewItem.ViewItemFeature.HasDecoration
        opt.features &= ~QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
        style.drawPrimitive(QStyle.PrimitiveElement.PE_PanelItemViewItem, opt, painter, opt.widget)
        if not (index.flags() & Qt.ItemFlag.ItemIsUserCheckable):
            return

        check_option = QStyleOptionButton()
        if index.flags() & Qt.ItemFlag.ItemIsEnabled:
            check_option.state |= QStyle.StateFlag.State_Enabled
        if option.state & QStyle.StateFlag.State_Active:
            check_option.state |= QStyle.StateFlag.State_Active
        check_option.state |= QStyle.StateFlag.State_On if is_checked_value(index.data(Qt.ItemDataRole.CheckStateRole)) else QStyle.StateFlag.State_Off

        indicator_rect = style.subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, check_option, opt.widget)
        check_option.rect = QRect(
            opt.rect.x() + (opt.rect.width() - indicator_rect.width()) // 2,
            opt.rect.y() + (opt.rect.height() - indicator_rect.height()) // 2,
            indicator_rect.width(),
            indicator_rect.height(),
        )
        style.drawPrimitive(QStyle.PrimitiveElement.PE_IndicatorCheckBox, check_option, painter, opt.widget)

    def editorEvent(self, event, model, option, index) -> bool:
        if not index.isValid() or not (index.flags() & Qt.ItemFlag.ItemIsUserCheckable):
            return False
        if event.type() not in (QEvent.Type.MouseButtonRelease, QEvent.Type.KeyPress):
            return False
        if event.type() == QEvent.Type.MouseButtonRelease and getattr(event, "button", lambda: Qt.MouseButton.LeftButton)() != Qt.MouseButton.LeftButton:
            return False
        if event.type() == QEvent.Type.KeyPress and event.key() not in (Qt.Key.Key_Space, Qt.Key.Key_Select):
            return False
        next_state = Qt.CheckState.Unchecked if is_checked_value(index.data(Qt.ItemDataRole.CheckStateRole)) else Qt.CheckState.Checked
        return model.setData(index, next_state, Qt.ItemDataRole.CheckStateRole)


def create_checkable_table_item(
    checked: bool = False,
    *,
    user_data: object | None = None,
    enabled: bool = True,
    selectable: bool = True,
) -> QTableWidgetItem:
    item = QTableWidgetItem()
    flags = Qt.ItemFlag.ItemIsUserCheckable
    if enabled:
        flags |= Qt.ItemFlag.ItemIsEnabled
    if selectable:
        flags |= Qt.ItemFlag.ItemIsSelectable
    item.setFlags(flags)
    item.setText("")
    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
    if user_data is not None:
        item.setData(Qt.ItemDataRole.UserRole, user_data)
    return item


def install_checkbox_only_delegate(table: QTableWidget, column: int = 0) -> None:
    table.setItemDelegateForColumn(column, CheckBoxOnlyDelegate(table))


def set_table_row_checked(table: QTableWidget, row: int, checked: bool, column: int = 0) -> None:
    item = table.item(row, column)
    if item is None or not (item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
        return
    item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
    table.viewport().update()


def set_all_table_rows_checked(table: QTableWidget, checked: bool, column: int = 0) -> None:
    for row in range(table.rowCount()):
        set_table_row_checked(table, row, checked, column)
    table.viewport().update()


def invert_table_rows_checked(table: QTableWidget, column: int = 0) -> None:
    for row in range(table.rowCount()):
        item = table.item(row, column)
        if item is None or not (item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
            continue
        item.setCheckState(Qt.CheckState.Unchecked if is_checked_value(item.checkState()) else Qt.CheckState.Checked)
    table.viewport().update()


def is_table_row_checked(table: QTableWidget, row: int, column: int = 0) -> bool:
    item = table.item(row, column)
    return item is not None and is_checked_value(item.checkState())
