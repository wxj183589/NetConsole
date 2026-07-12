from __future__ import annotations

from PySide6.QtWidgets import QApplication, QTableView, QWidget

from netconsole.ui.shell.fluent_bridge import apply_fluent_theme


THEME_TOKENS = {
    "light": {
        "background": "#f7f8fa",
        "surface": "#ffffff",
        "surface_alt": "#f8fafc",
        "panel": "#f3f4f6",
        "text_primary": "#111827",
        "text_secondary": "#1f2933",
        "text_muted": "#6b7280",
        "border": "#dde3ea",
        "border_strong": "#cbd5df",
        "hover": "#eef5ff",
        "selected": "#dbeafe",
        "selected_text": "#111827",
        "primary": "#2563eb",
        "primary_hover": "#1d4ed8",
        "primary_soft": "#e8f1ff",
        "danger": "#b91c1c",
        "danger_surface": "#fee2e2",
        "scrollbar_bg": "#f3f4f6",
        "scrollbar_handle": "#cbd5df",
        "scrollbar_handle_hover": "#94a3b8",
        "log_background": "#111827",
        "log_text": "#e5e7eb",
    },
    "dark": {
        "background": "#111827",
        "surface": "#1f2937",
        "surface_alt": "#273549",
        "panel": "#1f2937",
        "text_primary": "#ffffff",
        "text_secondary": "#e5e7eb",
        "text_muted": "#94a3b8",
        "border": "#374151",
        "border_strong": "#475569",
        "hover": "#334155",
        "selected": "rgba(37, 99, 235, 0.28)",
        "selected_text": "#ffffff",
        "primary": "#3b82f6",
        "primary_hover": "#60a5fa",
        "primary_soft": "#1e3a8a",
        "danger": "#fca5a5",
        "danger_surface": "#7f1d1d",
        "scrollbar_bg": "#111827",
        "scrollbar_handle": "#334155",
        "scrollbar_handle_hover": "#475569",
        "log_background": "#111827",
        "log_text": "#e5e7eb",
    },
}


LIGHT_APP_STYLESHEET = """
QWidget {
    background-color: #f7f8fa;
    color: #1f2933;
    font-family: "Microsoft YaHei", "Segoe UI";
    font-size: 13px;
}
QDialog {
    background-color: #f7f8fa;
    color: #1f2933;
}
QLabel {
    background-color: transparent;
    color: #1f2933;
}
#appShell {
    background-color: #dfe6ee;
}
#appContent {
    background-color: #f6f8fb;
}
#appTitleBar {
    background-color: #ffffff;
    border-bottom: 1px solid #dde3ea;
}
#appTitleText {
    color: #111827;
    font-weight: 600;
    font-size: 14px;
}
#appTitleMeta {
    color: #334155;
    padding-left: 12px;
}
#appTitleStatus {
    color: #2563eb;
    background-color: #e8f1ff;
    border: 1px solid #bfdbfe;
    border-radius: 4px;
    padding: 3px 8px;
}
#leftSidebar {
    background-color: #ffffff;
    border-right: 1px solid #dde3ea;
}
#navigation, #systemPanel {
    background-color: #ffffff;
    border: 1px solid #dde3ea;
}
#systemPanel {
    border-radius: 6px;
    padding: 6px;
}
QListWidget {
    background-color: #ffffff;
    border: 1px solid #dde3ea;
    color: #1f2933;
}
QListWidget::item {
    height: 36px;
    padding-left: 10px;
    border-radius: 4px;
}
#navigation::item {
    padding-left: 0px;
    padding-right: 0px;
}
QListWidget::item:selected {
    background-color: #e8f1ff;
    color: #1459b3;
}
QPushButton {
    background-color: #ffffff;
    border: 1px solid #cbd5df;
    border-radius: 4px;
    min-height: 26px;
    padding: 6px 10px;
    color: #111827;
}
QPushButton:hover {
    background-color: #eef5ff;
    border-color: #8bb7ee;
}
QPushButton:pressed {
    background-color: #dbeafe;
    border-color: #2563eb;
}
QPushButton:checked {
    background-color: #dbeafe;
    border-color: #2563eb;
    color: #1e3a8a;
    font-weight: 600;
}
QPushButton:disabled {
    background-color: #f3f4f6;
    border-color: #d1d5db;
    color: #9ca3af;
}
QPushButton#tableActionButton {
    padding: 0 8px;
    border-radius: 5px;
    font-size: 12px;
}
QPushButton#dangerButton {
    color: #b91c1c;
    font-weight: 600;
}
QPushButton#titleBarToolButton, QPushButton#titleBarMinButton, QPushButton#titleBarMaxButton, QPushButton#titleBarCloseButton {
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    min-height: 28px;
    padding: 0;
}
QPushButton#titleBarToolButton:hover, QPushButton#titleBarMinButton:hover, QPushButton#titleBarMaxButton:hover {
    background-color: #eef5ff;
    border-color: #bfdbfe;
}
QPushButton#titleBarCloseButton:hover {
    background-color: #fee2e2;
    border-color: #fecaca;
    color: #b91c1c;
}
QLineEdit, QComboBox, QSpinBox {
    background-color: #ffffff;
    border: 1px solid #cbd5df;
    border-radius: 4px;
    min-height: 28px;
    padding: 5px;
    color: #111827;
    selection-background-color: #dbeafe;
    selection-color: #111827;
}
QTextEdit, QPlainTextEdit {
    background-color: #ffffff;
    border: 1px solid #cbd5df;
    border-radius: 4px;
    padding: 5px;
    color: #111827;
    selection-background-color: #dbeafe;
    selection-color: #111827;
}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QTextEdit:hover, QPlainTextEdit:hover {
    border-color: #93c5fd;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QTextEdit:focus, QPlainTextEdit:focus {
    border-color: #2563eb;
}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QTextEdit:disabled, QPlainTextEdit:disabled {
    background-color: #f3f4f6;
    color: #9ca3af;
    border-color: #d1d5db;
}
QCheckBox {
    background-color: transparent;
    color: #1f2933;
    border: none;
    spacing: 0px;
}
QCheckBox:focus {
    border: none;
    outline: none;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border: 1px solid #8a8f99;
    border-radius: 3px;
    background-color: #ffffff;
}
QCheckBox::indicator:unchecked:hover {
    border-color: #2563eb;
    background-color: #f8fbff;
}
QCheckBox::indicator:checked {
    background-color: #2563eb;
    border-color: #2563eb;
}
QCheckBox::indicator:checked:hover {
    background-color: #1d4ed8;
    border-color: #1d4ed8;
}
QCheckBox::indicator:disabled {
    background-color: #e5e7eb;
    border-color: #cbd5e1;
}
QComboBox QAbstractItemView {
    background-color: #ffffff;
    color: #111827;
    border: 1px solid #cbd5df;
    selection-background-color: #dbeafe;
}
QTabWidget::pane {
    background-color: #ffffff;
    border: 1px solid #dde3ea;
}
QTabBar::tab {
    background-color: #f3f4f6;
    color: #111827;
    border: 1px solid #dde3ea;
    border-bottom: 0;
    padding: 7px 14px;
}
QTabBar::tab:selected {
    background-color: #ffffff;
    color: #2563eb;
}
QTabBar::tab:hover {
    background-color: #eef5ff;
}
QTableWidget, QTableView {
    background-color: #ffffff;
    alternate-background-color: #f8fafc;
    color: #111827;
    border: 1px solid #dde3ea;
    gridline-color: #edf1f5;
    selection-background-color: #dbeafe;
    selection-color: #111827;
}
QTableWidget::item, QTableView::item {
    padding: 4px;
}
QTableWidget::item:hover, QTableView::item:hover {
    background-color: #eef5ff;
}
QTableWidget::item:selected, QTableView::item:selected {
    background-color: #dbeafe;
    color: #111827;
}
QHeaderView::section {
    background-color: #f3f4f6;
    color: #111827;
    font-weight: 600;
    padding: 6px;
    border: 0;
    border-right: 1px solid #dde3ea;
    border-bottom: 1px solid #dde3ea;
}
QScrollBar:vertical, QScrollBar:horizontal {
    background-color: #f3f4f6;
    border: 0;
    margin: 0;
}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background-color: #cbd5df;
    border-radius: 4px;
    min-height: 24px;
    min-width: 24px;
}
QScrollBar::handle:hover {
    background-color: #94a3b8;
}
QScrollBar::add-line, QScrollBar::sub-line {
    width: 0;
    height: 0;
}
"""

DARK_APP_STYLESHEET = """
QWidget {
    background-color: #111827;
    color: #e5e7eb;
    font-family: "Microsoft YaHei", "Segoe UI";
    font-size: 13px;
}
QDialog {
    background-color: #111827;
    color: #e5e7eb;
}
QLabel {
    background-color: transparent;
    color: #e5e7eb;
}
#appShell {
    background-color: #111827;
}
#appContent {
    background-color: #111827;
}
#appTitleBar {
    background-color: #1f2937;
    border-bottom: 1px solid #374151;
}
#appTitleText {
    color: #ffffff;
    font-weight: 600;
    font-size: 14px;
}
#appTitleMeta {
    color: #cbd5e1;
    padding-left: 12px;
}
#appTitleStatus {
    color: #dbeafe;
    background-color: #1e3a8a;
    border: 1px solid #2563eb;
    border-radius: 4px;
    padding: 3px 8px;
}
#leftSidebar {
    background-color: #1f2937;
    border-right: 1px solid #374151;
}
#navigation, #systemPanel {
    background-color: #1f2937;
    border: 1px solid #374151;
}
#systemPanel {
    border-radius: 6px;
    padding: 6px;
}
QListWidget {
    background-color: #1f2937;
    border: 1px solid #374151;
    color: #e5e7eb;
}
QListWidget::item {
    height: 36px;
    padding-left: 10px;
    border-radius: 4px;
    color: #e5e7eb;
}
#navigation::item {
    padding-left: 0px;
    padding-right: 0px;
}
QListWidget::item:selected {
    background-color: rgba(37, 99, 235, 0.28);
    color: #ffffff;
}
QPushButton {
    background-color: #1f2937;
    border: 1px solid #374151;
    border-radius: 4px;
    min-height: 26px;
    padding: 6px 10px;
    color: #ffffff;
}
QPushButton:hover {
    background-color: #273549;
    border-color: #64748b;
}
QPushButton:pressed {
    background-color: #334155;
    border-color: #94a3b8;
}
QPushButton:checked {
    background-color: #334155;
    border-color: #94a3b8;
    color: #ffffff;
    font-weight: 600;
}
QPushButton:disabled {
    background-color: #1f2937;
    border-color: #1f2937;
    color: #6b7280;
}
QPushButton#tableActionButton {
    padding: 0 8px;
    border-radius: 5px;
    font-size: 12px;
}
QPushButton#dangerButton {
    color: #fca5a5;
    font-weight: 600;
}
QPushButton#titleBarToolButton, QPushButton#titleBarMinButton, QPushButton#titleBarMaxButton, QPushButton#titleBarCloseButton {
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    min-height: 28px;
    padding: 0;
}
QPushButton#titleBarToolButton:hover, QPushButton#titleBarMinButton:hover, QPushButton#titleBarMaxButton:hover {
    background-color: #273549;
    border-color: #475569;
}
QPushButton#titleBarCloseButton:hover {
    background-color: #7f1d1d;
    border-color: #991b1b;
    color: #ffffff;
}
QLineEdit, QComboBox, QSpinBox {
    background-color: #1f2937;
    border: 1px solid #374151;
    border-radius: 4px;
    min-height: 28px;
    padding: 5px;
    color: #e5e7eb;
    selection-background-color: rgba(37, 99, 235, 0.28);
    selection-color: #ffffff;
}
QTextEdit, QPlainTextEdit {
    background-color: #1f2937;
    border: 1px solid #374151;
    border-radius: 4px;
    padding: 5px;
    color: #e5e7eb;
    selection-background-color: rgba(37, 99, 235, 0.28);
    selection-color: #ffffff;
}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QTextEdit:hover, QPlainTextEdit:hover {
    border-color: #64748b;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QTextEdit:focus, QPlainTextEdit:focus {
    border-color: #94a3b8;
}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QTextEdit:disabled, QPlainTextEdit:disabled {
    background-color: #111827;
    color: #64748b;
    border-color: #1f2937;
}
QCheckBox {
    background-color: transparent;
    color: #e5e7eb;
    border: none;
    spacing: 0px;
}
QCheckBox:focus {
    border: none;
    outline: none;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border: 1px solid #475569;
    border-radius: 3px;
    background-color: #1f2937;
}
QCheckBox::indicator:unchecked:hover {
    border-color: #64748b;
    background-color: #1f2937;
}
QCheckBox::indicator:checked {
    background-color: #2563eb;
    border-color: #94a3b8;
}
QCheckBox::indicator:checked:hover {
    background-color: #1e40af;
    border-color: #94a3b8;
}
QCheckBox::indicator:disabled {
    background-color: #111827;
    border-color: #1f2937;
}
QComboBox QAbstractItemView {
    background-color: #1f2937;
    color: #e5e7eb;
    border: 1px solid #374151;
    selection-background-color: rgba(37, 99, 235, 0.28);
    selection-color: #ffffff;
}
QTabWidget::pane {
    background-color: #111827;
    border: 1px solid #374151;
}
QTabBar::tab {
    background-color: #1f2937;
    color: #cbd5e1;
    border: 1px solid #374151;
    border-bottom: 0;
    padding: 7px 14px;
}
QTabBar::tab:selected {
    background-color: #273549;
    color: #ffffff;
}
QTabBar::tab:hover {
    background-color: #334155;
    color: #ffffff;
}
QTableWidget, QTableView {
    background-color: #1f2937;
    alternate-background-color: #273549;
    color: #e5e7eb;
    border: 1px solid #374151;
    gridline-color: #374151;
    selection-background-color: rgba(37, 99, 235, 0.28);
    selection-color: #ffffff;
}
QTableWidget::item, QTableView::item {
    padding: 4px;
}
QTableWidget::item:hover, QTableView::item:hover {
    background-color: #334155;
}
QTableWidget::item:selected, QTableView::item:selected {
    background-color: rgba(37, 99, 235, 0.28);
    color: #ffffff;
}
QHeaderView::section {
    background-color: #1f2937;
    color: #ffffff;
    font-weight: 600;
    padding: 6px;
    border: 0;
    border-right: 1px solid #374151;
    border-bottom: 1px solid #374151;
}
QScrollBar:vertical, QScrollBar:horizontal {
    background-color: #111827;
    border: 0;
    margin: 0;
}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background-color: #334155;
    border-radius: 4px;
    min-height: 24px;
    min-width: 24px;
}
QScrollBar::handle:hover {
    background-color: #475569;
}
QScrollBar::add-line, QScrollBar::sub-line {
    width: 0;
    height: 0;
}
QToolTip {
    background-color: #1f2937;
    color: #ffffff;
    border: 1px solid #374151;
    padding: 6px;
}
"""


def stylesheet_for_theme(mode: str) -> str:
    from netconsole.ui.dialogs.dialog_style import dialog_stylesheet_for_theme

    theme_mode = "dark" if mode == "dark" else "light"
    base = DARK_APP_STYLESHEET if theme_mode == "dark" else LIGHT_APP_STYLESHEET
    return f"{base}\n{_fluent_shell_stylesheet(theme_mode)}\n{dialog_stylesheet_for_theme(theme_mode)}"


def apply_theme(mode: str) -> None:
    from netconsole.ui.dialogs.dialog_style import install_dialog_style_event_filter

    app = QApplication.instance()
    if app is None:
        return
    install_dialog_style_event_filter(app)
    theme_mode = "dark" if mode == "dark" else "light"
    apply_fluent_theme(theme_mode)
    stylesheet = stylesheet_for_theme(theme_mode)
    if app.property("netconsoleTheme") == theme_mode and app.styleSheet() == stylesheet:
        return
    app.setProperty("netconsoleTheme", theme_mode)
    app.setStyleSheet(stylesheet)


def apply_dark_theme(widget: QWidget | None = None) -> None:
    _ = widget
    apply_theme("dark")


def apply_table_theme(table: QTableView, theme: str | None = None) -> None:
    mode = theme or current_theme_mode()
    tokens = theme_tokens_for(mode)
    table.setAlternatingRowColors(True)
    table.setProperty("netconsoleTheme", "dark" if mode == "dark" else "light")
    table.setStyleSheet(
        f"""
        QTableWidget, QTableView {{
            background-color: {tokens["surface"]};
            alternate-background-color: {tokens["surface_alt"]};
            color: {tokens["text_primary"]};
            border: 1px solid {tokens["border"]};
            gridline-color: {tokens["border"]};
            selection-background-color: {tokens["selected"]};
            selection-color: {tokens["selected_text"]};
        }}
        QTableWidget::item, QTableView::item {{
            padding: 4px;
        }}
        QTableWidget::item:hover, QTableView::item:hover {{
            background-color: {tokens["hover"]};
        }}
        QTableWidget::item:selected, QTableView::item:selected {{
            background-color: {tokens["selected"]};
            color: {tokens["selected_text"]};
        }}
        QHeaderView::section {{
            background-color: {tokens["panel"]};
            color: {tokens["text_primary"]};
            font-weight: 600;
            padding: 6px;
            border: 0;
            border-right: 1px solid {tokens["border"]};
            border-bottom: 1px solid {tokens["border"]};
        }}
        """
    )


def _refresh_widget_tree(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()
    for child in widget.findChildren(QWidget):
        child.style().unpolish(child)
        child.style().polish(child)
        child.update()


def current_theme_mode() -> str:
    app = QApplication.instance()
    if app is None:
        return "light"
    value = app.property("netconsoleTheme")
    return "dark" if value == "dark" else "light"


def theme_tokens_for(mode: str) -> dict[str, str]:
    return dict(THEME_TOKENS["dark" if mode == "dark" else "light"])


def current_theme_tokens() -> dict[str, str]:
    return theme_tokens_for(current_theme_mode())


def _fluent_shell_stylesheet(mode: str) -> str:
    tokens = theme_tokens_for(mode)
    status_bg = "#dcfce7" if mode != "dark" else "#14532d"
    status_border = "#bbf7d0" if mode != "dark" else "#166534"
    status_text = "#166534" if mode != "dark" else "#dcfce7"
    return f"""
#fluentPage {{
    background-color: {tokens["background"]};
    color: {tokens["text_primary"]};
}}
#fluentSiteBar {{
    background-color: {tokens["surface"]};
    border: 1px solid {tokens["border"]};
    border-radius: 8px;
}}
#appTopBar {{
    background-color: {tokens["surface"]};
    border: 1px solid {tokens["border"]};
    border-radius: 8px;
}}
#fluentSiteBar QLabel {{
    color: {tokens["text_primary"]};
}}
#appTopBar QLabel {{
    color: {tokens["text_primary"]};
}}
#appTopBarTitle {{
    color: {tokens["text_primary"]};
    font-size: 13px;
    font-weight: 700;
}}
#fluentTitleCard {{
    background-color: transparent;
}}
#fluentTitleMain {{
    color: {tokens["text_primary"]};
    font-size: 13px;
    font-weight: 700;
}}
#fluentTitleSub {{
    color: {tokens["text_secondary"]};
    font-size: 12px;
}}
#fluentSiteLabel {{
    color: {tokens["primary"]};
    background-color: {tokens["primary_soft"]};
    border: 1px solid {tokens["selected"]};
    border-radius: 6px;
    padding: 4px 8px;
    font-weight: 600;
}}
#appTopBarSiteBadge {{
    color: {tokens["primary"]};
    background-color: {tokens["primary_soft"]};
    border: 1px solid {tokens["selected"]};
    border-radius: 6px;
    padding: 5px 10px;
    font-weight: 600;
}}
#fluentStatusLabel {{
    color: {status_text};
    background-color: {status_bg};
    border: 1px solid {status_border};
    border-radius: 6px;
    padding: 4px 8px;
    font-weight: 600;
}}
#appTopBarStatusBadge {{
    color: {status_text};
    background-color: {status_bg};
    border: 1px solid {status_border};
    border-radius: 6px;
    padding: 5px 10px;
    font-weight: 600;
}}
#fluentPageHeader {{
    background-color: transparent;
}}
#fluentPageTitle {{
    color: {tokens["text_primary"]};
    font-size: 20px;
    font-weight: 700;
}}
#fluentPageDescription {{
    color: {tokens["text_secondary"]};
    font-size: 13px;
}}
#fluentCommandBar {{
    background-color: transparent;
    color: {tokens["text_primary"]};
}}
#ncCard, #fluentCard, #fluentFilterBar {{
    background-color: {tokens["surface"]};
    border: 1px solid {tokens["border"]};
    border-radius: 10px;
    color: {tokens["text_primary"]};
}}
#networkPingCardTitle {{
    color: {tokens["text_primary"]};
    font-weight: 600;
}}
#settingsPage {{
    background-color: {tokens["background"]};
    color: {tokens["text_primary"]};
}}
#settingRow {{
    background-color: {tokens["surface_alt"]};
    border: 1px solid {tokens["border"]};
    border-radius: 8px;
}}
#settingRowTitle {{
    color: {tokens["text_primary"]};
    font-size: 13px;
    font-weight: 700;
}}
#settingRowDescription {{
    color: {tokens["text_secondary"]};
    font-size: 12px;
}}
#ncLogPanel, #ncDarkLogPanel, #ncTerminalPanel {{
    background-color: {tokens["log_background"]};
    color: {tokens["log_text"]};
    border: 1px solid {tokens["border_strong"]};
    border-radius: 8px;
}}
#ncLogPanel QLabel, #ncDarkLogPanel QLabel, #ncTerminalPanel QLabel {{
    color: {tokens["log_text"]};
}}
QGroupBox {{
    background-color: {tokens["surface"]};
    color: {tokens["text_primary"]};
    border: 1px solid {tokens["border"]};
    border-radius: 8px;
    margin-top: 14px;
    padding: 12px 8px 8px 8px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: {tokens["text_primary"]};
}}
"""
