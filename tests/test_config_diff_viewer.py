import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from netconsole.core.i18n import I18n
from netconsole.ui.widgets.config_diff_viewer import (
    DIFF_TABLE_STYLESHEET,
    LINE_NUMBER_BACKGROUND,
    LINE_NUMBER_FOREGROUND,
    ConfigDiffViewer,
)


def app():
    return QApplication.instance() or QApplication([])


def test_config_diff_viewer_uses_high_contrast_dark_diff_colors():
    app()
    viewer = ConfigDiffViewer(I18n("zh_CN"))

    viewer.set_diff(
        "running",
        "saved",
        "same\nleft-only\ncommon\nchange-old\nend",
        "same\ncommon\nchange-new\nright-only\nend",
    )

    rows_by_status = {viewer.table.item(row, 2).text(): row for row in range(viewer.table.rowCount())}
    assert viewer.table.item(rows_by_status["~"], 1).background().color().name() == "#4a3a1f"
    assert viewer.table.item(rows_by_status["~"], 1).foreground().color().name() == "#fff0c2"
    assert viewer.table.item(rows_by_status["-"], 1).background().color().name() == "#4a2428"
    assert viewer.table.item(rows_by_status["-"], 1).foreground().color().name() == "#ffd8dc"
    assert viewer.table.item(rows_by_status["+"], 4).background().color().name() == "#1f3d2b"
    assert viewer.table.item(rows_by_status["+"], 4).foreground().color().name() == "#d8ffe3"
    assert viewer.table.item(0, 0).background().color().name() == LINE_NUMBER_BACKGROUND
    assert viewer.table.item(0, 0).foreground().color().name() == LINE_NUMBER_FOREGROUND
    assert "font-family: Consolas" in viewer.table.styleSheet()
    assert DIFF_TABLE_STYLESHEET.strip() in viewer.table.styleSheet()
