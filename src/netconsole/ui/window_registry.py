from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtWidgets import QApplication, QWidget

from netconsole.core import app_logger


@dataclass(frozen=True)
class RegisteredWindow:
    window: QWidget
    name: str


class WindowRegistry:
    def __init__(self) -> None:
        self._windows: dict[QWidget, str] = {}

    def register(self, window: QWidget, name: str | None = None) -> None:
        self._windows[window] = name or window.objectName() or window.__class__.__name__
        window.destroyed.connect(lambda _=None, w=window: self.unregister(w))

    def unregister(self, window: QWidget) -> None:
        self._windows.pop(window, None)

    def count(self) -> int:
        return len(self.list_windows())

    def list_windows(self) -> list[RegisteredWindow]:
        return [RegisteredWindow(window, name) for window, name in list(self._windows.items()) if window is not None]

    def close_all(
        self,
        reason: str = "app_exit",
        *,
        main_window: QWidget | None = None,
        exclude: set[QWidget] | None = None,
        include_unregistered: bool = False,
    ) -> int:
        closed = 0
        excluded = set(exclude or set())
        if main_window is not None:
            excluded.add(main_window)
        candidates: list[QWidget] = [item.window for item in self.list_windows()]
        app = QApplication.instance()
        if include_unregistered and app is not None:
            for window in app.topLevelWidgets():
                if window in excluded:
                    continue
                if window not in candidates:
                    candidates.append(window)
        for window in candidates:
            if window is None or window in excluded:
                continue
            self._prepare_window_close(window, reason)
            try:
                window.close()
                window.hide()
                window.deleteLater()
                closed += 1
            except RuntimeError:
                self.unregister(window)
        return closed

    def prepare_all(
        self,
        reason: str = "app_exit",
        *,
        root: QWidget | None = None,
        exclude: set[QWidget] | None = None,
        include_unregistered: bool = False,
    ) -> int:
        prepared = 0
        excluded = set(exclude or set())
        candidates: list[QWidget] = [item.window for item in self.list_windows()]
        app = QApplication.instance()
        if include_unregistered and app is not None:
            for window in app.topLevelWidgets():
                if window not in candidates:
                    candidates.append(window)
        if root is not None:
            candidates.append(root)
            candidates.extend(root.findChildren(QWidget))
        seen: set[int] = set()
        for window in candidates:
            if window is None or window in excluded:
                continue
            marker = id(window)
            if marker in seen:
                continue
            seen.add(marker)
            if self._prepare_window_close(window, reason):
                prepared += 1
        return prepared

    @staticmethod
    def _prepare_window_close(window: QWidget, reason: str) -> bool:
        prepared = False
        for attr, value in (("ignore_callbacks", True), ("_ignore_callbacks", True), ("_shutting_down", True)):
            try:
                setattr(window, attr, value)
            except Exception:
                pass
        prepare = getattr(window, "prepare_close", None)
        if callable(prepare):
            try:
                prepare(reason)
                prepared = True
            except TypeError:
                prepare()
                prepared = True
            except Exception as exc:
                app_logger.log_error("WINDOW_PREPARE_CLOSE_FAILED", f"{window.__class__.__name__}: {exc}")
        prepare_shutdown = getattr(window, "prepare_shutdown", None)
        if callable(prepare_shutdown) and prepare_shutdown is not prepare:
            try:
                prepare_shutdown(reason)
                prepared = True
            except TypeError:
                prepare_shutdown()
                prepared = True
            except Exception as exc:
                app_logger.log_error("WINDOW_PREPARE_SHUTDOWN_FAILED", f"{window.__class__.__name__}: {exc}")
        return prepared


window_registry = WindowRegistry()
