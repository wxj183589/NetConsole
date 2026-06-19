import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from netconsole.core.i18n import I18n
from netconsole.ui.navigation import Navigation
from netconsole.ui.pages.file_management_page import format_speed, local_file_type


def app():
    return QApplication.instance() or QApplication([])


def test_navigation_includes_file_management_page():
    app()
    navigation = Navigation(I18n("en_US"))

    page_ids = [navigation.item(index).data(256) for index in range(navigation.count())]
    labels = [navigation.item(index).text() for index in range(navigation.count())]

    assert "file_management" in page_ids
    assert "File Management" in labels


def test_file_management_helpers_format_speed_and_types(tmp_path):
    archive = tmp_path / "diag.tar.gz"
    plain = tmp_path / "startup.cfg"

    assert local_file_type(archive) == "tar.gz"
    assert local_file_type(plain) == "cfg"
    assert format_speed(2048) == "2.0 KB/s"
