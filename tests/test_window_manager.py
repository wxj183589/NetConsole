import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget

from netconsole.ui.window_manager import WindowManager


def app():
    return QApplication.instance() or QApplication([])


def test_main_window_on_top_clears_child_on_top_and_restores_it():
    app()
    manager = WindowManager()
    main = QWidget()
    child = QWidget()
    manager.set_main_window(main)
    manager.register_child_window(child, always_on_top=True)

    manager.apply_main_window_on_top(True)

    assert main.windowFlags() & Qt.WindowStaysOnTopHint
    assert not (child.windowFlags() & Qt.WindowStaysOnTopHint)

    manager.apply_main_window_on_top(False)

    assert child.windowFlags() & Qt.WindowStaysOnTopHint
