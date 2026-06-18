from __future__ import annotations

from PySide6.QtWidgets import QApplication

from netconsole.ui.theme.table_style_engine import DARK_WIDGET_STYLESHEET, LIGHT_WIDGET_STYLESHEET


BASE_LIGHT_THEME = """
QMainWindow, QWidget { background: #f7f8fa; color: #1f2933; font-family: "Microsoft YaHei", "Segoe UI"; font-size: 13px; }
#navigation { background: #ffffff; border: 1px solid #dde3ea; padding: 8px; }
#systemPanel { background: #ffffff; border: 1px solid #dde3ea; border-radius: 6px; padding: 6px; }
QListWidget::item { height: 36px; padding-left: 10px; border-radius: 4px; }
QListWidget::item:selected { background: #e8f1ff; color: #1459b3; }
"""

BASE_DARK_THEME = """
QMainWindow, QWidget { background: #111827; color: #e5e7eb; font-family: "Microsoft YaHei", "Segoe UI"; font-size: 13px; }
#navigation { background: #1f2937; border: 1px solid #374151; padding: 8px; }
#systemPanel { background: #1f2937; border: 1px solid #374151; border-radius: 6px; padding: 6px; }
QListWidget::item { height: 36px; padding-left: 10px; border-radius: 4px; color: #e5e7eb; }
QListWidget::item:selected { background: #2563eb; color: #ffffff; }
"""

LIGHT_THEME = BASE_LIGHT_THEME + LIGHT_WIDGET_STYLESHEET
DARK_THEME = BASE_DARK_THEME + DARK_WIDGET_STYLESHEET


def stylesheet_for_theme(theme: str) -> str:
    return DARK_THEME if theme == "dark" else LIGHT_THEME


def apply_global_theme(theme: str) -> None:
    app = QApplication.instance()
    if app is not None:
        app.setStyleSheet(stylesheet_for_theme(theme))
