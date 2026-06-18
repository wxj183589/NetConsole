import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QHeaderView, QSizePolicy, QTableWidget, QTableWidgetItem

from netconsole.ui.theme.table_style_engine import (
    ACTION_COLUMN_WIDTH,
    DARK_WIDGET_STYLESHEET,
    HIGH_PRIORITY_MIN_WIDTH,
    MEDIUM_PRIORITY_MAX_WIDTH,
    ROW_HEIGHT,
    apply_action_column,
    apply_dark_theme,
    apply_table_style,
    set_table_column_fields,
)
from netconsole.ui.table_utils import (
    READONLY_TABLE_STYLESHEET,
    auto_resize_table_columns,
    configure_readonly_table,
    create_table_context_menu,
    format_row_for_copy,
)


def app():
    return QApplication.instance() or QApplication([])


def test_auto_resize_table_columns_keeps_header_text_visible():
    app()
    table = QTableWidget(1, 1)
    configure_readonly_table(table)
    table.setHorizontalHeaderLabels(["Very Long Header Text"])
    table.setItem(0, 0, QTableWidgetItem("x"))

    auto_resize_table_columns(table, min_width=90)

    header_width = table.horizontalHeader().fontMetrics().horizontalAdvance("Very Long Header Text") + 28
    assert table.columnWidth(0) >= header_width


def test_readonly_table_stylesheet_keeps_selected_text_high_contrast():
    assert "QTableWidget::item:selected" in READONLY_TABLE_STYLESHEET
    assert "background: #dbeafe" in READONLY_TABLE_STYLESHEET
    assert "color: #111827" in READONLY_TABLE_STYLESHEET


def test_auto_resize_table_columns_supports_column_min_widths():
    app()
    table = QTableWidget(1, 2)
    configure_readonly_table(table)
    table.setHorizontalHeaderLabels(["Interface", "Status"])
    table.setItem(0, 0, QTableWidgetItem("Ten-GigabitEthernet1/0/49"))
    table.setItem(0, 1, QTableWidgetItem("UP"))

    auto_resize_table_columns(table, column_min_widths={0: 180})

    assert table.columnWidth(0) >= 180


def test_apply_table_style_protects_ap_mac_width_and_expands_table():
    app()
    table = QTableWidget(1, 2)
    set_table_column_fields(table, ["ap_mac", "vlan"])
    table.setHorizontalHeaderLabels(["AP_MAC", "VLAN"])
    table.setItem(0, 0, QTableWidgetItem("bc:9c:c5:01:66:84"))
    table.setItem(0, 1, QTableWidgetItem("10"))

    apply_table_style(table)

    assert table.columnWidth(0) >= HIGH_PRIORITY_MIN_WIDTH
    assert table.sizePolicy().horizontalPolicy() == QSizePolicy.Expanding
    assert table.sizePolicy().verticalPolicy() == QSizePolicy.Expanding
    assert table.horizontalHeader().stretchLastSection() is True


def test_apply_table_style_caps_vlan_width():
    app()
    table = QTableWidget(1, 2)
    set_table_column_fields(table, ["vlan", "description"])
    table.setHorizontalHeaderLabels(["VLAN", "Description"])
    table.setItem(0, 0, QTableWidgetItem("1, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100"))
    table.setItem(0, 1, QTableWidgetItem("Uplink"))

    apply_table_style(table)

    assert table.columnWidth(0) <= MEDIUM_PRIORITY_MAX_WIDTH


def test_configure_readonly_table_applies_unified_behavior():
    app()
    table = QTableWidget(1, 1)

    configure_readonly_table(table)

    assert table.wordWrap() is False
    assert table.alternatingRowColors() is True
    assert table.verticalHeader().defaultSectionSize() == ROW_HEIGHT
    assert table.horizontalHeader().sectionResizeMode(0) == QHeaderView.Stretch


def test_action_column_is_fixed_and_not_stretched():
    app()
    table = QTableWidget(1, 3)
    set_table_column_fields(table, ["name", "ip_address", "actions"])
    table.setHorizontalHeaderLabels(["Name", "IP", "Actions"])

    apply_table_style(table)
    apply_action_column(table)

    assert table.columnWidth(2) == ACTION_COLUMN_WIDTH
    assert table.horizontalHeader().sectionResizeMode(2) == QHeaderView.Fixed
    assert table.horizontalHeader().stretchLastSection() is False


def test_dark_theme_stylesheet_covers_core_controls_and_states():
    assert "QTableWidget" in DARK_WIDGET_STYLESHEET
    assert "QHeaderView::section" in DARK_WIDGET_STYLESHEET
    assert "QPushButton:hover" in DARK_WIDGET_STYLESHEET
    assert "QLineEdit:disabled" in DARK_WIDGET_STYLESHEET
    assert "QComboBox:disabled" in DARK_WIDGET_STYLESHEET
    assert "selection-background-color" in DARK_WIDGET_STYLESHEET


def test_apply_dark_theme_sets_widget_stylesheet():
    app()
    table = QTableWidget()

    apply_dark_theme(table)

    assert "QTableWidget" in table.styleSheet()


def test_table_context_menu_actions_exist_in_english():
    app()
    table = QTableWidget(1, 1)
    table.setHorizontalHeaderLabels(["Name"])
    table.setItem(0, 0, QTableWidgetItem("GE1/0/1"))

    menu = create_table_context_menu(table, 0, 0, "en_US")

    assert [action.text() for action in menu.actions() if not action.isSeparator()] == [
        "Copy Cell",
        "Copy Row",
        "View History",
    ]


def test_table_context_menu_history_action_calls_callback():
    app()
    table = QTableWidget(1, 1)
    table.setHorizontalHeaderLabels(["Name"])
    table.setItem(0, 0, QTableWidgetItem("GE1/0/1"))
    rows = []
    menu = create_table_context_menu(table, 0, 0, "en_US", history_callback=lambda row: rows.append(row))

    menu.actions()[-1].trigger()

    assert rows == [0]


def test_format_row_for_copy_uses_header_order():
    assert format_row_for_copy(["A", "B"], ["1", "2"]) == "A: 1 | B: 2"
