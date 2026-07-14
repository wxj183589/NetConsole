from __future__ import annotations

from collections.abc import Iterator
import os
import tempfile

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication


# conftest 会在测试模块收集前加载。这里先隔离数据根，避免模块级 app =
# create_app() 在 fixture 生效前读取开发态 .local/data。
_TEST_DATA_ROOT = tempfile.TemporaryDirectory(prefix="netconsole-pytest-")
os.environ["NETCONSOLE_DATA_ROOT"] = _TEST_DATA_ROOT.name


_QT_APPLICATION: QApplication | None = None


@pytest.fixture(scope="session")
def qt_application() -> Iterator[QApplication]:
    """整个 pytest 进程只保留一个 QApplication，避免包装对象提前回收。"""

    global _QT_APPLICATION
    application = QApplication.instance()
    if application is None:
        application = QApplication([])
    if not isinstance(application, QApplication):
        raise RuntimeError("Qt 测试需要 QApplication，当前进程已存在不兼容的 QCoreApplication")
    application.setQuitOnLastWindowClosed(False)
    _QT_APPLICATION = application
    yield application


@pytest.fixture
def qt_page_lifecycle(qt_application: QApplication) -> Iterator[None]:
    """逐条清理顶层窗口和 deleteLater 队列，隔离 Qt 页面测试生命周期。"""

    for widget in list(qt_application.topLevelWidgets()):
        try:
            widget.hide()
            widget.deleteLater()
        except RuntimeError:
            continue
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    yield
    application = qt_application
    widgets = list(application.topLevelWidgets())
    for widget in widgets:
        try:
            widget.close()
        except RuntimeError:
            continue
    for widget in widgets:
        try:
            widget.deleteLater()
        except RuntimeError:
            continue
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
