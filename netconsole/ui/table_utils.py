from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication, QAbstractItemView, QLabel, QMenu, QMessageBox, QTableWidget

from netconsole.ui.table.table_style_engine import apply_table_style


READONLY_TABLE_STYLESHEET = """
QTableWidget {
    background: #ffffff;
    alternate-background-color: #f8fafc;
    border: 1px solid #dde3ea;
    gridline-color: #edf1f5;
    selection-background-color: #dbeafe;
    selection-color: #111827;
}
QTableWidget::item {
    padding: 4px;
    color: #111827;
}
QTableWidget::item:selected {
    background: #dbeafe;
    color: #111827;
}
QHeaderView::section {
    background: #f3f4f6;
    color: #111827;
    font-weight: 600;
    padding: 6px;
    border: 1px solid #d1d5db;
}
"""


def configure_readonly_table(table: QTableWidget) -> None:
    table.setEditTriggers(QTableWidget.NoEditTriggers)
    table.setSelectionBehavior(QTableWidget.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.setStyleSheet(READONLY_TABLE_STYLESHEET)
    apply_table_style(table)


def make_text_selectable(label: QLabel) -> QLabel:
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return label


def auto_resize_table_columns(
    table: QTableWidget,
    min_width: int = 90,
    max_width: int = 420,
    stretch_columns: set[int] | None = None,
    column_min_widths: dict[int, int] | None = None,
) -> None:
    _ = (min_width, max_width, stretch_columns, column_min_widths)
    apply_table_style(table)


def attach_table_context_menu(table: QTableWidget, language: str = "zh_CN", history_callback=None, include_history: bool = True) -> None:
    table.setContextMenuPolicy(Qt.CustomContextMenu)
    table.customContextMenuRequested.connect(lambda position: _show_table_context_menu(table, position, language, history_callback, include_history))


def format_row_for_copy(headers: list[str], values: list[str]) -> str:
    return " | ".join(f"{header}: {value}" for header, value in zip(headers, values))


def create_table_context_menu(table: QTableWidget, row: int, column: int, language: str = "zh_CN", history_callback=None, include_history: bool = True) -> QMenu:
    labels = _menu_labels(language)
    menu = QMenu(table)
    copy_cell = menu.addAction(labels["copy_cell"])
    copy_cell.setEnabled(row >= 0 and column >= 0 and table.item(row, column) is not None)
    copy_cell.triggered.connect(lambda: _copy_cell(table, row, column))
    copy_row = menu.addAction(labels["copy_row"])
    copy_row.setEnabled(row >= 0)
    copy_row.triggered.connect(lambda: _copy_row(table, row))
    if include_history:
        menu.addSeparator()
        history = menu.addAction(labels["view_history"])
        history.setEnabled(row >= 0)
        if history_callback is None:
            history.triggered.connect(lambda: QMessageBox.information(table, labels["view_history"], labels["history_later"]))
        else:
            history.triggered.connect(lambda: history_callback(row))
    return menu


def _show_table_context_menu(table: QTableWidget, position: QPoint, language: str, history_callback, include_history: bool) -> None:
    index = table.indexAt(position)
    menu = create_table_context_menu(table, index.row(), index.column(), language, history_callback, include_history)
    menu.exec(table.viewport().mapToGlobal(position))


def _copy_cell(table: QTableWidget, row: int, column: int) -> None:
    item = table.item(row, column)
    QApplication.clipboard().setText(item.text() if item else "")


def _copy_row(table: QTableWidget, row: int) -> None:
    headers = [table.horizontalHeaderItem(column).text() if table.horizontalHeaderItem(column) else "" for column in range(table.columnCount())]
    values = [table.item(row, column).text() if table.item(row, column) else "" for column in range(table.columnCount())]
    QApplication.clipboard().setText(format_row_for_copy(headers, values))


def _menu_labels(language: str) -> dict[str, str]:
    if language == "en_US":
        return {
            "copy_cell": "Copy Cell",
            "copy_row": "Copy Row",
            "view_history": "View History",
            "history_later": "History data will be supported later",
        }
    return {
        "copy_cell": "复制单元格",
        "copy_row": "复制整行",
        "view_history": "查看历史数据",
        "history_later": "历史数据功能后续支持",
    }
