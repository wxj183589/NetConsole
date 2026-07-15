from __future__ import annotations

import json
import sys


def run_qt_probe(component: str) -> int:
    try:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication(["NetConsole Qt Probe"])
        if component == "widgets":
            detail = f"platform={app.platformName()}"
        elif component == "webengine":
            from PySide6.QtWebEngineWidgets import QWebEngineView

            view = QWebEngineView()
            view.deleteLater()
            detail = "QWebEngineView initialized"
        else:
            raise ValueError(f"unknown component: {component}")
        payload = {"component": component, "available": True, "detail": detail}
        result = 0
    except BaseException as exc:
        payload = {"component": component, "available": False, "detail": f"{exc.__class__.__name__}: {exc}"}
        result = 1
    if sys.stdout is not None:
        print(json.dumps(payload, ensure_ascii=False), flush=True)
    return result


__all__ = ["run_qt_probe"]
