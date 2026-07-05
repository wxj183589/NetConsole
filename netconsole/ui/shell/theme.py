from __future__ import annotations


TITLE_BAR_HEIGHT = 44
FRAME_RESIZE_BORDER = 8
WINDOW_MIN_WIDTH = 1280
WINDOW_MIN_HEIGHT = 760


def next_theme(current_theme: str) -> str:
    return "light" if current_theme == "dark" else "dark"
