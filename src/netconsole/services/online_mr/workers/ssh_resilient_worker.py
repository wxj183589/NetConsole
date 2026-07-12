from __future__ import annotations

import time
from collections.abc import Callable


class SshResilientWorker:
    def __init__(
        self,
        read_stream: Callable[[], None],
        reconnect: Callable[[], None],
        *,
        should_run: Callable[[], bool] | None = None,
        reconnect_interval_seconds: float = 2.0,
        max_reconnects: int | None = None,
    ) -> None:
        self.read_stream = read_stream
        self.reconnect = reconnect
        self.should_run = should_run or (lambda: True)
        self.reconnect_interval_seconds = float(reconnect_interval_seconds)
        self.max_reconnects = max_reconnects
        self.reconnect_count = 0

    def run(self) -> None:
        while self.should_run():
            try:
                self.read_stream()
                return
            except Exception as exc:
                if not _is_reset_10054(exc):
                    raise
                if self.max_reconnects is not None and self.reconnect_count >= self.max_reconnects:
                    raise
                self.reconnect_count += 1
                self.reconnect()
                time.sleep(self.reconnect_interval_seconds)


def _is_reset_10054(exc: Exception) -> bool:
    text = str(exc)
    return "10054" in text or "connection reset" in text.lower() or "forcibly closed" in text.lower()
