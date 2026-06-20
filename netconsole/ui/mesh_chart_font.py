from __future__ import annotations

from functools import lru_cache

import matplotlib
from matplotlib import font_manager
from matplotlib.font_manager import FontProperties
from PySide6.QtWidgets import QApplication

from netconsole.core import app_logger


@lru_cache(maxsize=1)
def resolve_matplotlib_cjk_font() -> FontProperties | None:
    matplotlib.rcParams["axes.unicode_minus"] = False
    matplotlib.rcParams["path.simplify"] = True
    matplotlib.rcParams["path.simplify_threshold"] = 0.5
    matplotlib.rcParams["agg.path.chunksize"] = 10000
    families = []
    app = QApplication.instance()
    if app is not None:
        families.append(app.font().family())
    families.extend(
        [
            "Microsoft YaHei",
            "Microsoft JhengHei",
            "SimHei",
            "SimSun",
            "Noto Sans CJK SC",
            "Source Han Sans SC",
            "Arial Unicode MS",
        ]
    )
    for family in dict.fromkeys(families):
        try:
            font_manager.findfont(FontProperties(family=family), fallback_to_default=False)
        except (ValueError, RuntimeError):
            continue
        matplotlib.rcParams["font.family"] = [family]
        return FontProperties(family=family)
    app_logger.log_error("MESH_CHART_CJK_FONT_NOT_FOUND", "No CJK-capable matplotlib font found")
    return None


def apply_cjk_font(axis) -> FontProperties | None:
    font = resolve_matplotlib_cjk_font()
    if font is None:
        return None
    for text in [axis.title, axis.xaxis.label, axis.yaxis.label, *axis.get_xticklabels(), *axis.get_yticklabels()]:
        text.set_fontproperties(font)
    legend = axis.get_legend()
    if legend is not None:
        for text in legend.get_texts():
            text.set_fontproperties(font)
    return font
