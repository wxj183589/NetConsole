from __future__ import annotations

from PySide6.QtWidgets import QApplication


LIGHT_THEME = """
QMainWindow, QWidget { background: #f7f8fa; color: #1f2933; font-family: "Microsoft YaHei", "Segoe UI"; font-size: 13px; }
#navigation { background: #ffffff; border: 1px solid #dde3ea; padding: 8px; }
#systemPanel { background: #ffffff; border: 1px solid #dde3ea; border-radius: 6px; padding: 6px; }
QListWidget::item { height: 36px; padding-left: 10px; border-radius: 4px; }
QListWidget::item:selected { background: #e8f1ff; color: #1459b3; }
QPushButton { background: #ffffff; border: 1px solid #cbd5df; border-radius: 4px; padding: 6px 10px; }
QPushButton:hover { background: #eef5ff; border-color: #8bb7ee; }
QPushButton:checked { background: #dbeafe; border-color: #2563eb; color: #1e3a8a; font-weight: 600; }
QLineEdit, QComboBox, QSpinBox, QTextEdit { background: #ffffff; border: 1px solid #cbd5df; border-radius: 4px; padding: 5px; }
QTableWidget { background: #ffffff; border: 1px solid #dde3ea; gridline-color: #edf1f5; selection-background-color: #dcecff; }
QHeaderView::section { background: #f0f3f7; border: 0; border-right: 1px solid #dde3ea; border-bottom: 1px solid #dde3ea; padding: 6px; font-weight: 600; }
"""

DARK_THEME = """
QMainWindow, QWidget { background: #111827; color: #e5e7eb; font-family: "Microsoft YaHei", "Segoe UI"; font-size: 13px; }
#navigation { background: #1f2937; border: 1px solid #374151; padding: 8px; }
#systemPanel { background: #1f2937; border: 1px solid #374151; border-radius: 6px; padding: 6px; }
QListWidget::item { height: 36px; padding-left: 10px; border-radius: 4px; color: #e5e7eb; }
QListWidget::item:selected { background: #2563eb; color: #ffffff; }
QPushButton { background: #1f2937; border: 1px solid #4b5563; border-radius: 4px; padding: 6px 10px; color: #f9fafb; }
QPushButton:hover { background: #374151; border-color: #60a5fa; }
QPushButton:checked { background: #1d4ed8; border-color: #93c5fd; color: #ffffff; font-weight: 600; }
QLineEdit, QComboBox, QSpinBox, QTextEdit { background: #111827; color: #f9fafb; border: 1px solid #4b5563; border-radius: 4px; padding: 5px; }
QTableWidget { background: #111827; color: #f9fafb; border: 1px solid #374151; gridline-color: #374151; selection-background-color: #1d4ed8; }
QHeaderView::section { background: #1f2937; color: #f9fafb; border: 0; border-right: 1px solid #374151; border-bottom: 1px solid #374151; padding: 6px; font-weight: 600; }
"""


def stylesheet_for_theme(theme: str) -> str:
    return DARK_THEME if theme == "dark" else LIGHT_THEME


def apply_global_theme(theme: str) -> None:
    app = QApplication.instance()
    if app is not None:
        app.setStyleSheet(stylesheet_for_theme(theme))
