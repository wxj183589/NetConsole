from __future__ import annotations

import secrets
import threading


class SessionCredentialVault:
    """进程内凭据容器；不落盘、不进入日志或 API 响应。"""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}
        self._lock = threading.Lock()

    def store(self, value: str, reference: str = "") -> str:
        selected = reference or f"session:{secrets.token_urlsafe(18)}"
        with self._lock:
            self._values[selected] = value
        return selected

    def get(self, reference: str) -> str | None:
        with self._lock:
            return self._values.get(reference)

    def remove(self, reference: str) -> None:
        with self._lock:
            self._values.pop(reference, None)

    def contains(self, reference: str) -> bool:
        with self._lock:
            return bool(reference and reference in self._values)
