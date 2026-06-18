from __future__ import annotations

from netconsole.ui.theme.qt_theme_engine import DARK_APP_STYLESHEET, LIGHT_APP_STYLESHEET, apply_theme, stylesheet_for_theme


DARK_THEME = DARK_APP_STYLESHEET
LIGHT_THEME = LIGHT_APP_STYLESHEET


def apply_global_theme(theme: str) -> None:
    apply_theme(theme)
