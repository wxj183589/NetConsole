from __future__ import annotations

from PySide6.QtWidgets import QApplication, QWidget


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
        "log_background": "#ffffff",
        "log_text": "#111827",
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
QLineEdit, QComboBox, QSpinBox, QTextEdit, QPlainTextEdit {
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
QTableWidget {
    background-color: #ffffff;
    alternate-background-color: #f8fafc;
    color: #111827;
    border: 1px solid #dde3ea;
    gridline-color: #edf1f5;
    selection-background-color: #dbeafe;
    selection-color: #111827;
}
QTableWidget::item {
    padding: 4px;
}
QTableWidget::item:hover {
    background-color: #eef5ff;
}
QTableWidget::item:selected {
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
QLineEdit, QComboBox, QSpinBox, QTextEdit, QPlainTextEdit {
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
QTableWidget {
    background-color: #1f2937;
    alternate-background-color: #273549;
    color: #e5e7eb;
    border: 1px solid #374151;
    gridline-color: #374151;
    selection-background-color: rgba(37, 99, 235, 0.28);
    selection-color: #ffffff;
}
QTableWidget::item {
    padding: 4px;
}
QTableWidget::item:hover {
    background-color: #334155;
}
QTableWidget::item:selected {
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
    return DARK_APP_STYLESHEET if mode == "dark" else LIGHT_APP_STYLESHEET


def apply_theme(mode: str) -> None:
    app = QApplication.instance()
    if app is None:
        return
    theme_mode = "dark" if mode == "dark" else "light"
    stylesheet = stylesheet_for_theme(theme_mode)
    if app.property("netconsoleTheme") == theme_mode and app.styleSheet() == stylesheet:
        return
    app.setProperty("netconsoleTheme", theme_mode)
    app.setStyleSheet(stylesheet)
    for widget in app.topLevelWidgets():
        _refresh_widget_tree(widget)


def apply_dark_theme(widget: QWidget | None = None) -> None:
    _ = widget
    apply_theme("dark")


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
