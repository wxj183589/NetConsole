import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QHeaderView, QSizePolicy, QTableWidget, QTableWidgetItem

from netconsole.ui.render.table_render_engine import (
    ACTION_COLUMN_WIDTH,
    AP_MAC_COLUMN_WIDTH,
    AP_NAME_MIN_WIDTH,
    DARK_WIDGET_STYLESHEET,
    HIGH_PRIORITY_MIN_WIDTH,
    MEDIUM_PRIORITY_MAX_WIDTH,
    ROW_HEIGHT,
    STATUS_COLOR_MAP,
    apply_action_column,
    apply_auto_layout,
    apply_dark_theme,
    apply_table_style,
    set_table_column_fields,
)
from netconsole.ui.table.table_autosize_engine import (
    calculate_column_widths,
    calculate_excel_column_widths,
    weighted_text_length,
)
from netconsole.ui.theme.contrast_engine import apply_status_item_contrast, get_contrast_text_color
from netconsole.ui.theme.qt_theme_engine import apply_theme
from netconsole.ui.table_utils import (
    READONLY_TABLE_STYLESHEET,
    auto_resize_table_columns_to_contents,
    auto_resize_table_columns,
    configure_readonly_table,
    create_table_context_menu,
    format_row_for_copy,
    setup_readable_table,
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
    assert "background-color: #dbeafe" in READONLY_TABLE_STYLESHEET
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


def test_setup_readable_table_and_alias_apply_project_table_rules():
    app()
    table = QTableWidget(1, 2)
    table.setHorizontalHeaderLabels(["Path", "Status"])
    table.setItem(0, 0, QTableWidgetItem("flash:/very/long/path/meshlog.log"))
    table.setItem(0, 1, QTableWidgetItem("Ready"))

    setup_readable_table(table)
    auto_resize_table_columns_to_contents(table, column_min_widths={0: 240})

    assert table.horizontalHeader().sectionResizeMode(0) == QHeaderView.Interactive
    assert table.horizontalHeader().stretchLastSection() is False
    assert table.wordWrap() is False
    assert table.columnWidth(0) >= 240
    assert table.item(0, 0).toolTip() == "flash:/very/long/path/meshlog.log"


def test_apply_table_style_prioritizes_ap_name_over_ap_mac():
    app()
    table = QTableWidget(1, 3)
    set_table_column_fields(table, ["ap_name", "ap_mac", "vlan"])
    table.setHorizontalHeaderLabels(["AP Name", "AP_MAC", "VLAN"])
    table.setItem(0, 0, QTableWidgetItem("Station-Long-AP-Name-001"))
    table.setItem(0, 1, QTableWidgetItem("bc:9c:c5:01:66:84"))
    table.setItem(0, 2, QTableWidgetItem("10"))

    apply_table_style(table)

    assert table.columnWidth(0) >= AP_NAME_MIN_WIDTH
    assert table.horizontalHeader().sectionResizeMode(0) == QHeaderView.Interactive
    assert AP_MAC_COLUMN_WIDTH <= table.columnWidth(1) <= MEDIUM_PRIORITY_MAX_WIDTH
    assert table.horizontalHeader().sectionResizeMode(1) == QHeaderView.Interactive
    assert table.sizePolicy().horizontalPolicy() == QSizePolicy.Expanding
    assert table.sizePolicy().verticalPolicy() == QSizePolicy.Expanding
    assert table.horizontalHeader().stretchLastSection() is False


def test_apply_table_style_caps_vlan_width():
    app()
    table = QTableWidget(1, 2)
    set_table_column_fields(table, ["vlan", "description"])
    table.setHorizontalHeaderLabels(["VLAN", "Description"])
    table.setItem(0, 0, QTableWidgetItem("1, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100"))
    table.setItem(0, 1, QTableWidgetItem("Uplink"))

    apply_table_style(table)

    assert table.columnWidth(0) <= MEDIUM_PRIORITY_MAX_WIDTH
    assert table.horizontalHeader().sectionResizeMode(0) == QHeaderView.Interactive


def test_configure_readonly_table_applies_unified_behavior():
    app()
    table = QTableWidget(1, 1)

    configure_readonly_table(table)

    assert table.wordWrap() is False
    assert table.alternatingRowColors() is True
    assert ROW_HEIGHT == 36
    assert table.verticalHeader().defaultSectionSize() == ROW_HEIGHT
    assert table.rowHeight(0) == ROW_HEIGHT
    assert table.horizontalHeader().sectionResizeMode(0) == QHeaderView.Interactive
    assert table.horizontalHeader().stretchLastSection() is False
    assert table.wordWrap() is False


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


def test_auto_layout_uses_content_width_without_stretching_to_viewport():
    app()
    table = QTableWidget(1, 6)
    set_table_column_fields(table, ["select", "ap_name", "ap_mac", "ap_ip", "updated_at", "actions"])
    table.setHorizontalHeaderLabels(["", "AP Name", "AP_MAC", "IP", "Updated", "Actions"])
    for column, value in enumerate(["", "Station-Very-Long-AP-Name-001", "bc5a-3457-cbe0", "10.1.1.1", "2026-06-18", ""]):
        table.setItem(0, column, QTableWidgetItem(value))

    apply_auto_layout(table, 1920)

    ap_name_column = 1
    ap_mac_column = 2
    widths = table.property("netconsole_auto_layout_widths")
    used_width = sum(widths.values())
    assert table.horizontalHeader().sectionResizeMode(ap_name_column) == QHeaderView.Interactive
    assert widths[ap_name_column] >= 180
    assert 112 <= widths[ap_mac_column] <= MEDIUM_PRIORITY_MAX_WIDTH
    assert used_width < int(1920 * 0.95)
    assert table.horizontalHeader().stretchLastSection() is False


def test_auto_layout_keeps_content_widths_when_viewport_changes():
    app()
    table = QTableWidget(1, 4)
    set_table_column_fields(table, ["ap_name", "ap_mac", "ap_ip", "updated_at"])
    table.setHorizontalHeaderLabels(["AP Name", "AP_MAC", "IP", "Updated"])

    apply_auto_layout(table, 900)
    initial_width = table.property("netconsole_auto_layout_widths")[0]
    apply_auto_layout(table, 1600)

    assert table.property("netconsole_auto_layout_widths")[0] == initial_width


def test_excel_autosize_weights_chinese_as_double_width():
    assert weighted_text_length("AP名称") == 6
    assert weighted_text_length("APName") == 6
    assert weighted_text_length("车站A") == 5


def test_calculate_column_widths_uses_header_and_content_without_viewport_fill():
    app()
    table = QTableWidget(2, 3)
    set_table_column_fields(table, ["ap_name", "ap_mac", "updated_at"])
    table.setHorizontalHeaderLabels(["AP名称", "AP_MAC", "更新时间"])
    table.setItem(0, 0, QTableWidgetItem("01小洋江站-AP-001"))
    table.setItem(0, 1, QTableWidgetItem("bc5a-3457-cbe0"))
    table.setItem(0, 2, QTableWidgetItem("2026-06-18T16:02:45"))
    table.setItem(1, 0, QTableWidgetItem("02云龙火车站-AP-002"))

    widths = calculate_column_widths(table, 1200)

    assert widths[0] > widths[1]
    assert widths[0] >= AP_NAME_MIN_WIDTH
    assert AP_MAC_COLUMN_WIDTH <= widths[1] <= MEDIUM_PRIORITY_MAX_WIDTH
    assert sum(widths.values()) < int(1200 * 0.9)


def test_excel_width_calculation_matches_chinese_weighting():
    widths = calculate_excel_column_widths(
        ["AP名称", "AP_MAC"],
        [{"ap_name": "01小洋江站-AP-001", "ap_mac": "bc5a-3457-cbe0"}],
        ["ap_name", "ap_mac"],
    )

    assert widths[0] > widths[1]
    assert widths[0] > len("01小洋江站-AP-001")


def test_dark_theme_stylesheet_covers_core_controls_and_states():
    assert "QWidget" in DARK_WIDGET_STYLESHEET
    assert "QDialog" in DARK_WIDGET_STYLESHEET
    assert "QTabWidget::pane" in DARK_WIDGET_STYLESHEET
    assert "QScrollBar:vertical" in DARK_WIDGET_STYLESHEET
    assert "QTableWidget" in DARK_WIDGET_STYLESHEET
    assert "QTableWidget::item:hover" in DARK_WIDGET_STYLESHEET
    assert "QTableWidget::item:selected" in DARK_WIDGET_STYLESHEET
    assert "QHeaderView::section" in DARK_WIDGET_STYLESHEET
    assert "background-color: #111827" in DARK_WIDGET_STYLESHEET
    assert "QPushButton:hover" in DARK_WIDGET_STYLESHEET
    assert "QPushButton {\n    background-color: #1f2937" in DARK_WIDGET_STYLESHEET
    assert "color: #ffffff" in DARK_WIDGET_STYLESHEET
    assert "QLineEdit:disabled" in DARK_WIDGET_STYLESHEET
    assert "QComboBox:disabled" in DARK_WIDGET_STYLESHEET
    assert "QToolTip" in DARK_WIDGET_STYLESHEET
    assert "selection-background-color" in DARK_WIDGET_STYLESHEET


def test_contrast_engine_picks_readable_text_for_backgrounds():
    assert get_contrast_text_color("#111827") == "#ffffff"
    assert get_contrast_text_color("#fbbf24") == "#111827"
    assert get_contrast_text_color("#f87171") == "#ffffff"


def test_render_engine_exposes_single_status_color_map():
    assert STATUS_COLOR_MAP["normal"] == "#22c55e"
    assert STATUS_COLOR_MAP["warning"] == "#fbbf24"
    assert STATUS_COLOR_MAP["alarm"] == "#f87171"
    assert STATUS_COLOR_MAP["link_down"] == "#fb7185"
    assert STATUS_COLOR_MAP["no_light"] == "#6b7280"


def test_status_item_contrast_sets_background_and_foreground():
    item = QTableWidgetItem("No Light")

    apply_status_item_contrast(item, "no_light")

    assert item.background().color().name() == "#6b7280"
    assert item.foreground().color().name() == "#ffffff"


def test_apply_dark_theme_sets_global_stylesheet():
    qt_app = app()

    apply_dark_theme()

    assert "QTableWidget" in qt_app.styleSheet()
    assert "QDialog" in qt_app.styleSheet()


def test_apply_theme_switches_without_local_table_stylesheet():
    qt_app = app()
    table = QTableWidget()

    configure_readonly_table(table)
    apply_theme("dark")

    assert table.styleSheet() == ""
    assert "background-color: #111827" in qt_app.styleSheet()
    assert "background-color: #0b0f14" not in qt_app.styleSheet()
    assert "background-color: #0f172a" not in qt_app.styleSheet()
    assert "QTableWidget::item:selected" in qt_app.styleSheet()


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
