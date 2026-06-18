from __future__ import annotations

from PySide6.QtWidgets import QApplication, QWidget


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
    app.setStyleSheet(stylesheet_for_theme(mode))
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
