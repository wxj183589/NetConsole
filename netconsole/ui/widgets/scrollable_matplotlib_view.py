from __future__ import annotations

from bisect import bisect_left
from datetime import datetime
from typing import Callable

from matplotlib.dates import date2num
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtWidgets import QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from netconsole.ui.mesh_chart_hover_popup import MeshChartHoverPopup


TOOLBAR_TRANSLATIONS = {
    "Home": "复位",
    "Back": "后退",
    "Forward": "前进",
    "Pan": "平移",
    "Zoom": "缩放",
    "Subplots": "布局调整",
    "Customize": "图形选项",
    "Save": "保存图片",
}

TOOLTIP_TRANSLATIONS = {
    "Reset original view": "复位到初始视图",
    "Back to previous view": "后退到上一视图",
    "Forward to next view": "前进到下一视图",
    "Left button pans, Right button zooms": "左键平移，右键缩放",
    "Zoom to rectangle": "框选缩放",
    "Configure subplots": "调整图形布局",
    "Edit axis, curve and image parameters": "调整图形参数",
    "Save the figure": "保存图片",
}


def _strip_action_text(text: str) -> str:
    return str(text or "").replace("&", "").strip()


class ChineseNavigationToolbar:
    @staticmethod
    def create(canvas, parent):
        from matplotlib.backends.backend_qtagg import NavigationToolbar2QT

        toolbar = NavigationToolbar2QT(canvas, parent)
        for action in toolbar.actions():
            text = _strip_action_text(action.text())
            tooltip = str(action.toolTip() or "").strip()
            if text in {"Subplots", "Customize"}:
                action.setVisible(False)
                continue
            translated = TOOLBAR_TRANSLATIONS.get(text)
            translated_tooltip = TOOLTIP_TRANSLATIONS.get(tooltip)
            if translated:
                action.setText(translated)
                action.setToolTip(translated_tooltip or translated)
                action.setStatusTip(translated_tooltip or translated)
            elif translated_tooltip:
                action.setToolTip(translated_tooltip)
                action.setStatusTip(translated_tooltip)
        return toolbar


class ScrollableMatplotlibView(QWidget):
    def __init__(self, parent: QWidget | None = None, *, min_plot_width: int = 1300, min_plot_height: int = 520) -> None:
        super().__init__(parent)
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        from matplotlib.figure import Figure

        self.figure = Figure(figsize=(min_plot_width / 100, min_plot_height / 100), tight_layout=True)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.canvas.setMinimumSize(min_plot_width, min_plot_height)

        self.chart_container = QWidget()
        container_layout = QVBoxLayout(self.chart_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.addWidget(self.canvas)
        self.chart_container.setMinimumSize(min_plot_width, min_plot_height)

        self.toolbar = ChineseNavigationToolbar.create(self.canvas, self)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(False)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setWidget(self.chart_container)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.scroll_area, 1)

    def set_preferred_plot_width(self, width: int, *, height: int = 520) -> None:
        width = max(900, int(width))
        height = max(420, int(height))
        self.figure.set_size_inches(width / 100, height / 100, forward=True)
        self.canvas.setMinimumSize(width, height)
        self.canvas.resize(width, height)
        self.chart_container.setMinimumSize(width, height)


class AnalysisChartHoverController:
    def __init__(self, canvas, axis, points: list[object], tooltip_builder: Callable[[object], str]) -> None:
        self.canvas = canvas
        self.axis = axis
        self.points = points
        self.tooltip_builder = tooltip_builder
        self.timestamps = [_point_timestamp_number(point) for point in points]
        self.popup = MeshChartHoverPopup()
        self.fixed_index: int | None = None
        self.current_index = -1
        self.latest_event = None
        self.timer = QTimer()
        self.timer.setSingleShot(True)
        self.timer.setInterval(35)
        self.timer.timeout.connect(self._process_latest_event)
        original_xlim = axis.get_xlim()
        original_ylim = axis.get_ylim()
        vline_x = self.timestamps[0] if self.timestamps else original_xlim[0]
        self.vline = axis.axvline(vline_x, color="#0f766e", linewidth=1.0, alpha=0.65, visible=False)
        (self.marker,) = axis.plot([], [], "o", markersize=6, color="#0f766e", visible=False, zorder=7)
        axis.set_xlim(original_xlim)
        axis.set_ylim(original_ylim)
        self.motion_cid = canvas.mpl_connect("motion_notify_event", self.on_mouse_move)
        self.click_cid = canvas.mpl_connect("button_press_event", self.on_click)
        self.leave_cid = canvas.mpl_connect("axes_leave_event", self.on_axes_leave)

    def disconnect(self) -> None:
        for cid in (self.motion_cid, self.click_cid, self.leave_cid):
            self.canvas.mpl_disconnect(cid)
        self.timer.stop()
        self.popup.hide()
        self.popup.deleteLater()

    def nearest_index(self, xdata: float, pixel_x: float | None = None, *, max_pixel_distance: int = 24) -> int:
        if not self.timestamps:
            return -1
        index = bisect_left(self.timestamps, float(xdata))
        candidates = []
        if index > 0:
            candidates.append(index - 1)
        if index < len(self.timestamps):
            candidates.append(index)
        if not candidates:
            return -1
        nearest = min(candidates, key=lambda item: abs(self.timestamps[item] - float(xdata)))
        if pixel_x is not None:
            sample_pixel = self.axis.transData.transform((self.timestamps[nearest], 0))[0]
            if abs(sample_pixel - pixel_x) > max_pixel_distance:
                return -1
        left, right = self.axis.get_xlim()
        lower, upper = min(left, right), max(left, right)
        return nearest if lower <= self.timestamps[nearest] <= upper else -1

    def tooltip_text(self, index: int) -> str:
        if not (0 <= index < len(self.points)):
            return ""
        return self.tooltip_builder(self.points[index])

    def on_mouse_move(self, event) -> None:
        if event.inaxes is not self.axis or event.xdata is None:
            if self.fixed_index is None:
                self.hide()
            return
        self.latest_event = event
        self.timer.start()

    def on_click(self, event) -> None:
        if event.inaxes is not self.axis or event.xdata is None or getattr(event, "button", None) != 1:
            return
        toolbar = getattr(self.canvas, "toolbar", None)
        if toolbar is not None and getattr(toolbar, "mode", ""):
            return
        index = self.nearest_index(float(event.xdata), float(event.x or 0), max_pixel_distance=32)
        if index < 0:
            return
        self.fixed_index = index
        self._show_index(index, event)

    def on_axes_leave(self, _event) -> None:
        if self.fixed_index is None:
            self.hide()

    def hide(self) -> None:
        self.timer.stop()
        self.latest_event = None
        self.current_index = -1
        self.vline.set_visible(False)
        self.marker.set_visible(False)
        self.popup.hide()
        self.canvas.draw_idle()

    def _process_latest_event(self) -> None:
        event = self.latest_event
        if event is None or event.xdata is None:
            if self.fixed_index is None:
                self.hide()
            return
        index = self.nearest_index(float(event.xdata), float(event.x or 0))
        if index < 0:
            if self.fixed_index is None:
                self.hide()
            return
        if self.fixed_index is None:
            self._show_index(index, event)

    def _show_index(self, index: int, event) -> None:
        point = self.points[index]
        x_value = self.timestamps[index]
        y_value = _point_value(point)
        self.vline.set_xdata([x_value, x_value])
        self.vline.set_visible(True)
        if y_value is not None:
            self.marker.set_data([x_value], [float(y_value)])
            self.marker.set_visible(True)
        text = self.tooltip_text(index)
        resized = self.popup.set_tooltip_text(text)
        self.popup.show_at(self.canvas.mapToGlobal(QPoint(int(event.x or 0), int(event.y or 0))), resize=resized)
        self.current_index = index
        self.canvas.draw_idle()


def _point_timestamp_number(point: object) -> float:
    value = getattr(point, "timestamp", None)
    if isinstance(value, datetime):
        return float(date2num(value))
    try:
        return float(date2num(datetime.fromisoformat(str(value).replace(" ", "T"))))
    except (TypeError, ValueError):
        return 0.0


def _point_value(point: object) -> float | None:
    for attr in ("metric_value", "rssi", "traffic_rate_mbps"):
        try:
            value = getattr(point, attr)
            if value is not None:
                return float(value)
        except (TypeError, ValueError):
            continue
    return None
