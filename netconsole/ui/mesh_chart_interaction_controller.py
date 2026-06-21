from __future__ import annotations

from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import Qt

from netconsole.core import app_logger


class MeshChartInteractionController(QObject):
    def __init__(self, canvas, axis, owner, chart_key: str, parent=None) -> None:
        super().__init__(parent)
        self.canvas = canvas
        self.axis = axis
        self.owner = owner
        self.chart_key = chart_key
        self.enabled = False
        self.dragging = False
        self.drag_started = False
        self.drag_start_mouse_x = 0.0
        self.drag_start_window_index = 0
        self.axis_pixel_width = 1.0
        self.visible_sample_count = 0
        self.pending_drag_start: int | None = None
        self.drag_timer = QTimer(self)
        self.drag_timer.setSingleShot(True)
        self.drag_timer.setInterval(16)
        self.drag_timer.timeout.connect(self._apply_pending_drag)
        self.scroll_cid = canvas.mpl_connect("scroll_event", self.on_scroll)
        self.press_cid = canvas.mpl_connect("button_press_event", self.on_press)
        self.motion_cid = canvas.mpl_connect("motion_notify_event", self.on_motion)
        self.release_cid = canvas.mpl_connect("button_release_event", self.on_release)

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        if not enabled:
            self.cancel()

    def disconnect(self) -> None:
        self.cancel()
        for cid in (self.scroll_cid, self.press_cid, self.motion_cid, self.release_cid):
            self.canvas.mpl_disconnect(cid)

    def on_scroll(self, event) -> None:
        if not self.enabled or self.owner.interaction_state == "PANNING" or event.inaxes is not self.axis or event.xdata is None:
            return
        self.owner.begin_zoom_interaction()
        self.owner.zoom_time_window_at(self.chart_key, float(event.xdata), float(getattr(event, "step", 0) or 0))
        self.owner.finish_zoom_interaction_later()

    def on_press(self, event) -> None:
        if not self.enabled or event.inaxes is not self.axis or getattr(event, "button", None) != 1:
            return
        if self.owner.is_all_samples_visible():
            return
        toolbar = getattr(self.canvas, "toolbar", None)
        if toolbar is not None and getattr(toolbar, "mode", ""):
            return
        self.dragging = True
        self.drag_started = False
        self.drag_start_mouse_x = float(event.x or 0)
        self.drag_start_window_index = self.owner.window_start_index
        bbox = self.axis.get_window_extent()
        self.axis_pixel_width = max(float(bbox.width), 1.0)
        self.visible_sample_count = self.owner.effective_visible_sample_count()

    def on_motion(self, event) -> None:
        if not self.dragging or event.x is None:
            return
        pixel_distance = abs(float(event.x) - self.drag_start_mouse_x)
        if pixel_distance < 4:
            return
        if not self.drag_started:
            self.drag_started = True
            self.owner.begin_pan_interaction()
            self.canvas.setCursor(Qt.ClosedHandCursor)
            app_logger.log_info("MESH_CHART_DRAG_STARTED", f"tab={self.chart_key}, start={self.drag_start_window_index}, visible={self.visible_sample_count}")
        pixel_delta = self.drag_start_mouse_x - float(event.x)
        sample_delta = round(pixel_delta / self.axis_pixel_width * max(self.visible_sample_count, 1))
        self.pending_drag_start = self.drag_start_window_index + sample_delta
        self.drag_timer.start()

    def on_release(self, event) -> None:
        if not self.dragging:
            return
        if self.drag_started:
            self._apply_pending_drag()
            app_logger.log_info("MESH_CHART_DRAG_FINISHED", f"tab={self.chart_key}, start={self.owner.window_start_index}, visible={self.owner.visible_sample_count}")
            self.owner.finish_pan_interaction_later()
        self.canvas.setCursor(Qt.ArrowCursor)
        self.dragging = False
        self.drag_started = False
        self.pending_drag_start = None

    def cancel(self) -> None:
        self.drag_timer.stop()
        self.pending_drag_start = None
        self.dragging = False
        self.drag_started = False
        self.canvas.setCursor(Qt.ArrowCursor)

    def _apply_pending_drag(self) -> None:
        if self.pending_drag_start is None:
            return
        start = self.pending_drag_start
        self.pending_drag_start = None
        self.owner.pan_time_window_to(start, "drag")
        app_logger.log_info("MESH_CHART_DRAG_UPDATED", f"tab={self.chart_key}, start={self.owner.window_start_index}, visible={self.owner.visible_sample_count}")
