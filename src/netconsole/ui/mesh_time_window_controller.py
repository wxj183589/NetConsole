from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QObject, Signal


class MeshTimeWindowController(QObject):
    windowChanged = Signal(int, int, str)

    def __init__(self, parent=None, minimum_visible_samples: int = 10, zoom_factor: float = 1.25) -> None:
        super().__init__(parent)
        self.minimum_visible_samples = minimum_visible_samples
        self.zoom_factor = zoom_factor
        self.total_count = 0
        self.window_start_index = 0
        self.visible_sample_count = 120

    def set_total_count(self, total_count: int, visible_count: int | None = None, start_index: int | None = None, source: str = "payload") -> None:
        self.total_count = max(int(total_count), 0)
        visible = self.visible_sample_count if visible_count is None else int(visible_count)
        start = self.window_start_index if start_index is None else int(start_index)
        self.set_time_window(start, visible, source)

    def set_time_window(self, start_index: int, visible_count: int, source: str) -> None:
        visible = self._normalize_visible_count(visible_count)
        maximum = self.maximum_start_for_visible(visible)
        start = max(0, min(int(start_index), maximum))
        changed = start != self.window_start_index or visible != self.visible_sample_count
        self.window_start_index = start
        self.visible_sample_count = visible
        if changed or source == "payload":
            self.windowChanged.emit(self.window_start_index, self.visible_sample_count, source)

    def center_on(self, sample_index: int, visible_count: int | None = None, source: str = "center_anchor") -> None:
        visible = self.visible_sample_count if visible_count is None else self._normalize_visible_count(visible_count)
        effective_visible = self.effective_visible_count(visible)
        start = max(min(int(sample_index) - effective_visible // 2, self.maximum_start_for_visible(visible)), 0)
        self.set_time_window(start, visible, source)

    def pan_to(self, start_index: int, source: str = "drag") -> None:
        self.set_time_window(start_index, self.visible_sample_count, source)

    def zoom_at_index(self, cursor_index: int, step: float, source: str = "wheel") -> None:
        if self.total_count <= 0 or not math.isfinite(float(step)) or step == 0:
            return
        old_visible = self.effective_visible_count()
        if old_visible <= 0:
            return
        power = abs(float(step))
        factor = self.zoom_factor**power
        if step > 0:
            new_visible = round(old_visible / factor)
        else:
            new_visible = round(old_visible * factor)
        new_visible = max(self.minimum_visible_samples, min(new_visible, self.total_count))
        visible_for_storage = 0 if new_visible >= self.total_count else new_visible
        old_start = self.window_start_index
        anchor_ratio = (int(cursor_index) - old_start) / max(old_visible - 1, 1)
        anchor_ratio = max(0.0, min(anchor_ratio, 1.0))
        new_start = int(cursor_index) - round(anchor_ratio * max(new_visible - 1, 1))
        self.set_time_window(new_start, visible_for_storage, source)

    def cursor_index_from_xdata(self, timestamps: np.ndarray, xdata: float) -> int:
        if len(timestamps) == 0 or not math.isfinite(float(xdata)):
            return -1
        index = int(np.searchsorted(timestamps, xdata))
        candidates = []
        if index < len(timestamps):
            candidates.append(index)
        if index > 0:
            candidates.append(index - 1)
        if not candidates:
            return -1
        return min(candidates, key=lambda item: abs(float(timestamps[item]) - float(xdata)))

    def effective_visible_count(self, visible_count: int | None = None) -> int:
        visible = self.visible_sample_count if visible_count is None else int(visible_count)
        if self.total_count <= 0:
            return 0
        if visible <= 0 or visible >= self.total_count:
            return self.total_count
        return visible

    def maximum_start_for_visible(self, visible_count: int | None = None) -> int:
        return max(self.total_count - self.effective_visible_count(visible_count), 0)

    def is_all_visible(self) -> bool:
        return self.total_count <= 0 or self.effective_visible_count() >= self.total_count

    def _normalize_visible_count(self, visible_count: int) -> int:
        if self.total_count <= 0:
            return 0
        visible = int(visible_count)
        if visible <= 0 or visible >= self.total_count:
            return 0
        return max(self.minimum_visible_samples, min(visible, self.total_count))
