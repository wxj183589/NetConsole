"""NetConsole global table display helpers.

Tables should initialize readable content widths, allow horizontal scrolling
and manual column resizing, and reuse these helpers. See docs/ui_table_guidelines.md.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QApplication, QAbstractItemView, QHeaderView, QLabel, QMenu, QMessageBox, QTableWidget, QTableWidgetItem

from netconsole.ui.render.table_render_engine import apply_table_style
from netconsole.ui.theme.qt_theme_engine import LIGHT_APP_STYLESHEET


READONLY_TABLE_STYLESHEET = LIGHT_APP_STYLESHEET
DEFAULT_TABLE_MIN_WIDTH = 80
DEFAULT_TABLE_MAX_WIDTH = 320
LONG_TEXT_MAX_WIDTH = 520
LONG_TEXT_HEADER_TOKENS = {
    "错误信息",
    "异常信息",
    "备注",
    "路径",
    "文件路径",
    "命令输出",
    "配置摘要",
    "描述",
    "原因",
    "详情",
    "日志",
    "error",
    "exception",
    "remark",
    "note",
    "path",
    "output",
    "description",
    "detail",
    "message",
    "summary",
}
LONG_TEXT_FIELD_NAMES = {
    "error_message",
    "exception_message",
    "remark",
    "note",
    "path",
    "file_path",
    "raw_log_path",
    "command_output",
    "config_summary",
    "description",
    "details",
    "message",
}


def configure_readonly_table(table: QTableWidget) -> None:
    table.setEditTriggers(QTableWidget.NoEditTriggers)
    table.setSelectionBehavior(QTableWidget.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    apply_table_style(table)
    configure_readable_table_columns(table)


def make_table_item(value: object, align: Qt.AlignmentFlag | Qt.Alignment = Qt.AlignCenter, tooltip: bool = True) -> QTableWidgetItem:
    item = QTableWidgetItem("" if value is None else str(value))
    item.setTextAlignment(align)
    if tooltip:
        item.setToolTip(item.text())
    return item


def set_table_item_centered(item: QTableWidgetItem) -> QTableWidgetItem:
    item.setTextAlignment(Qt.AlignCenter)
    if not item.toolTip():
        item.setToolTip(item.text())
    return item


def apply_analysis_table_style(
    table: QTableWidget,
    *,
    raw_columns: set[int] | None = None,
    width_overrides: dict[int, int] | None = None,
) -> None:
    _ = (raw_columns, width_overrides)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
    table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
    table.setWordWrap(False)
    table.setTextElideMode(Qt.TextElideMode.ElideRight)
    table.setAlternatingRowColors(True)
    table.verticalHeader().setDefaultSectionSize(34)
    header = table.horizontalHeader()
    header.setDefaultAlignment(Qt.AlignCenter)
    header.setSectionResizeMode(QHeaderView.Interactive)
    header.setStretchLastSection(False)
    header.setSectionsMovable(False)
    for column in range(table.columnCount()):
        header_item = table.horizontalHeaderItem(column)
        if header_item is not None:
            header_item.setTextAlignment(Qt.AlignCenter)
            header_item.setToolTip(header_item.text())


def make_text_selectable(label: QLabel) -> QLabel:
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return label


def configure_readable_table_columns(table: QTableWidget) -> None:
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
    table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
    table.setWordWrap(False)
    table.setTextElideMode(Qt.TextElideMode.ElideRight)
    header = table.horizontalHeader()
    header.setDefaultAlignment(Qt.AlignCenter)
    header.setSectionResizeMode(QHeaderView.Interactive)
    header.setStretchLastSection(False)
    header.setSectionsMovable(False)
    for column in range(table.columnCount()):
        header.setSectionResizeMode(column, QHeaderView.Interactive)
        header_item = table.horizontalHeaderItem(column)
        if header_item is not None:
            header_item.setTextAlignment(Qt.AlignCenter)
            if not header_item.toolTip():
                header_item.setToolTip(header_item.text())


def setup_readable_table(
    table: QTableWidget,
    *,
    horizontal_scroll: bool = True,
    interactive: bool = True,
    stretch_last_section: bool = False,
) -> None:
    configure_readable_table_columns(table)
    if not horizontal_scroll:
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.Interactive if interactive else QHeaderView.Fixed)
    header.setStretchLastSection(stretch_last_section)


def auto_fit_table_columns(
    table: QTableWidget,
    *,
    max_rows: int = 500,
    min_widths: dict[int, int] | None = None,
    max_widths: dict[int, int] | None = None,
    column_min_widths: dict[str, int] | None = None,
    column_max_widths: dict[str, int] | None = None,
    default_min_width: int = DEFAULT_TABLE_MIN_WIDTH,
    default_max_width: int = DEFAULT_TABLE_MAX_WIDTH,
    long_text_max_width: int = LONG_TEXT_MAX_WIDTH,
    padding: int = 32,
) -> None:
    if table.columnCount() <= 0:
        return
    min_widths = dict(min_widths or {})
    max_widths = dict(max_widths or {})
    column_min_widths = dict(column_min_widths or {})
    column_max_widths = dict(column_max_widths or {})
    header = table.horizontalHeader()
    configure_readable_table_columns(table)
    header.setSectionResizeMode(QHeaderView.Interactive)
    header.setStretchLastSection(False)
    row_indexes = _sample_table_rows(table.rowCount(), max_rows)
    header_metrics = QFontMetrics(header.font())
    cell_metrics = QFontMetrics(table.font())
    old_blocked = table.blockSignals(True)
    try:
        for column in range(table.columnCount()):
            header_item = table.horizontalHeaderItem(column)
            header_text = header_item.text() if header_item is not None else ""
            width = header_metrics.horizontalAdvance(header_text)
            for row in row_indexes:
                item = table.item(row, column)
                if item is None:
                    continue
                text = item.text()
                width = max(width, cell_metrics.horizontalAdvance(text))
                _ensure_item_tooltip(item)
            field = _field_text(table, column)
            minimum = _column_bound(column, header_text, field, min_widths, column_min_widths, default_min_width, _default_min_width(header_text))
            maximum = _column_bound(column, header_text, field, max_widths, column_max_widths, default_max_width, _default_max_width(header_text))
            if _is_long_text_column(header_text, field):
                if column in max_widths:
                    maximum = int(max_widths[column])
                else:
                    maximum = int(column_max_widths.get(field, column_max_widths.get(header_text, long_text_max_width)))
            maximum = max(int(maximum), int(minimum))
            table.setColumnWidth(column, max(minimum, min(width + padding, maximum)))
    finally:
        table.blockSignals(old_blocked)
    viewport_width = max(0, table.viewport().width() - table.verticalScrollBar().sizeHint().width())
    total_width = sum(table.columnWidth(column) for column in range(table.columnCount()))
    if 0 < total_width < viewport_width:
        last = table.columnCount() - 1
        header_text = table.horizontalHeaderItem(last).text() if table.horizontalHeaderItem(last) else ""
        field = _field_text(table, last)
        maximum = _column_bound(last, header_text, field, max_widths, column_max_widths, default_max_width, _default_max_width(header_text))
        if _is_long_text_column(header_text, field):
            if last in max_widths:
                maximum = int(max_widths[last])
            else:
                maximum = int(column_max_widths.get(field, column_max_widths.get(header_text, long_text_max_width)))
        table.setColumnWidth(last, min(maximum, table.columnWidth(last) + viewport_width - total_width))


def _sample_table_rows(row_count: int, max_rows: int) -> list[int]:
    if row_count <= 0:
        return []
    max_rows = max(1, int(max_rows))
    if row_count <= max_rows:
        return list(range(row_count))
    tail_count = min(50, max_rows // 5)
    head_count = max_rows - tail_count
    return list(range(head_count)) + list(range(row_count - tail_count, row_count))


def _default_min_width(header_text: str) -> int:
    text = str(header_text or "")
    if text in {"", "全选", "选择", "勾选"}:
        return 48
    if text in {"序号"}:
        return 60
    if "操作" in text or "动作" in text or "Action" in text:
        return 220
    if "路径" in text or "目录" in text:
        return 320
    if "错误" in text or "异常" in text:
        return 260
    if "时间" in text:
        return 170
    if "任务" in text and "名称" in text:
        return 180
    if "MAC" in text:
        return 140
    if "IP" in text:
        return 120
    if "AP" in text or "设备" in text or "对端" in text or "名称" in text:
        return 150
    if "站点" in text:
        return 130
    if "原因" in text:
        return 240
    if "RSSI" in text or "数量" in text or "PPS" in text or "ID" in text or "利用率" in text:
        return 80
    return 90


def _default_max_width(header_text: str) -> int:
    text = str(header_text or "")
    if _is_long_text_column(text, ""):
        return LONG_TEXT_MAX_WIDTH
    if "原始" in text or "日志" in text or "内容" in text or "目录" in text or "详情" in text:
        return LONG_TEXT_MAX_WIDTH
    if "原因" in text:
        return 360
    if "站点" in text:
        return 240
    if "时间" in text:
        return 260
    return 420


def auto_resize_table_columns(
    table: QTableWidget,
    min_width: int = 90,
    max_width: int = 420,
    stretch_columns: set[int] | None = None,
    column_min_widths: dict[int, int] | None = None,
    column_max_widths: dict[int, int] | None = None,
    long_text_max_width: int = LONG_TEXT_MAX_WIDTH,
) -> None:
    _ = stretch_columns
    if table.columnCount() <= 0:
        configure_readable_table_columns(table)
        return
    min_widths = {column: max(int(min_width), _default_min_width(_header_text(table, column))) for column in range(table.columnCount())}
    for column, width in (column_min_widths or {}).items():
        min_widths[int(column)] = max(min_widths.get(int(column), int(min_width)), int(width))
    max_widths = {column: max(int(max_width), min_widths[column]) for column in range(table.columnCount())}
    for column, width in (column_max_widths or {}).items():
        max_widths[int(column)] = max(int(width), min_widths.get(int(column), int(min_width)))
    auto_fit_table_columns(table, min_widths=min_widths, max_widths=max_widths, long_text_max_width=long_text_max_width)


def auto_resize_table_columns_to_contents(
    table: QTableWidget,
    min_width: int = 90,
    max_width: int = 420,
    column_min_widths: dict[int, int] | None = None,
    column_max_widths: dict[int, int] | None = None,
    long_text_max_width: int = LONG_TEXT_MAX_WIDTH,
) -> None:
    auto_resize_table_columns(
        table,
        min_width=min_width,
        max_width=max_width,
        column_min_widths=column_min_widths,
        column_max_widths=column_max_widths,
        long_text_max_width=long_text_max_width,
    )


def _header_text(table: QTableWidget, column: int) -> str:
    item = table.horizontalHeaderItem(column)
    return item.text() if item else ""


def _field_text(table: QTableWidget, column: int) -> str:
    fields = table.property("netconsole_column_fields")
    if isinstance(fields, (list, tuple)) and column < len(fields):
        return str(fields[column] or "")
    return ""


def _column_bound(
    column: int,
    header_text: str,
    field: str,
    by_index: dict[int, int],
    by_name: dict[str, int],
    default: int,
    inferred: int,
) -> int:
    if column in by_index:
        return int(by_index[column])
    if field and field in by_name:
        return int(by_name[field])
    if header_text and header_text in by_name:
        return int(by_name[header_text])
    return max(int(default), int(inferred))


def _is_long_text_column(header_text: str, field: str) -> bool:
    normalized_header = str(header_text or "").strip().casefold()
    normalized_field = str(field or "").strip().casefold()
    if normalized_field in LONG_TEXT_FIELD_NAMES:
        return True
    return any(token.casefold() in normalized_header for token in LONG_TEXT_HEADER_TOKENS)


def _ensure_item_tooltip(item: QTableWidgetItem) -> None:
    text = item.text()
    if text and not item.toolTip():
        item.setToolTip(text)


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
