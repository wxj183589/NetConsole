from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget

from netconsole.ui.window_manager import WindowManager


def test_detached_page_window_is_not_owned_by_main_window():
    source = Path("netconsole/ui/main_window.py").read_text(encoding="utf-8")
    detach_body = source.split("def detach_current_page", 1)[1].split("def activate_detached_page", 1)[0]

    assert "QMainWindow(self)" not in detach_body
    assert "QMainWindow()" in detach_body


def test_window_manager_register_and_restore_do_not_show_child():
    app = QApplication.instance() or QApplication([])
    _ = app
    manager = WindowManager()
    child = QWidget()
    show_calls = []
    child.show = lambda: show_calls.append("show")  # type: ignore[method-assign]

    manager.register_child_window(child)
    manager.restore_child_window_flags()

    assert show_calls == []
    assert not bool(child.windowFlags() & Qt.WindowStaysOnTopHint)
    child.deleteLater()
