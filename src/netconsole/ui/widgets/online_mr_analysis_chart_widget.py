from __future__ import annotations

import math
from datetime import datetime
from types import SimpleNamespace

import numpy as np
from matplotlib.dates import date2num, num2date
from PySide6.QtCore import QSignalBlocker, QTimer, Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLabel, QMenu, QPushButton, QScrollBar, QSizePolicy, QVBoxLayout, QWidget

from netconsole.core.i18n import I18n
from netconsole.services.online_mr_chart_builder import ChartData, ChartEvent
from netconsole.ui.mesh_chart_font import apply_cjk_font
from netconsole.ui.mesh_chart_interaction_controller import MeshChartInteractionController
from netconsole.ui.mesh_chart_payload import preserve_extrema_indices, render_indices
from netconsole.ui.mesh_chart_time_axis import configure_mesh_time_axis
from netconsole.ui.mesh_time_window_controller import MeshTimeWindowController
from netconsole.ui.widgets.scrollable_matplotlib_view import AnalysisChartHoverController, ScrollableMatplotlibView


ACTIVE_LINE_STYLE = {"linewidth": 1.2, "marker": "o", "markersize": 2.5}
SWITCH_MARKER_STYLE = {
    "s": 48,
    "marker": "^",
    "color": "#f97316",
    "edgecolors": "#111827",
    "linewidths": 0.7,
    "alpha": 0.95,
    "zorder": 6,
    "label": "链路切换点",
}
ANOMALY_MARKER_STYLE = {
    "s": 42,
    "marker": "D",
    "color": "#dc2626",
    "edgecolors": "#ffffff",
    "linewidths": 0.7,
    "alpha": 0.95,
    "zorder": 7,
    "label": "异常点",
}
LOCKED_LINE_STYLE = {"color": "#0f766e", "alpha": 0.78, "linewidth": 1.2, "linestyle": "--", "zorder": 8}
LOCKED_MARKER_STYLE = {"s": 60, "marker": "o", "color": "#0f766e", "edgecolors": "#ffffff", "linewidths": 0.9, "zorder": 9}
LOCK_MATCH_TOLERANCE_SECONDS = {
    "rssi": 1.5,
    "ping_loss": 1.5,
    "ping": 1.5,
    "interface": 3.0,
    "busy": 5.0,
    "traffic": 2.0,
    "switch_rssi": 10.0,
    "switch_log_rssi": 10.0,
}


class OnlineMrAnalysisChartWidget(QWidget):
    """Mesh 全量 ACTIVE 图表交互风格的车载 MR 动态图表容器。"""

    hoverChanged = Signal(object)
    lockTimeRequested = Signal(object)
    lockTimeCleared = Signal()

    def __init__(self, i18n: I18n, chart_key: str, chart_title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.i18n = i18n
        self.chart_key = chart_key
        self.chart_title = chart_title
        self.current_chart: ChartData | None = None
        self.summary_labels: dict[str, QLabel] = {}
        self.series_values: dict[str, np.ndarray] = {}
        self.series_order: list[str] = []
        self.timestamps: list[datetime] = []
        self.timestamp_labels: list[str] = []
        self.timestamp_numeric = np.asarray([], dtype=np.float64)
        self.hover_points: list[object] = []
        self.event_indices: list[int] = []
        self.locked_index = -1
        self.locked_time: datetime | None = None
        self.locked_delta_seconds: float | None = None
        self.window_start_index = 0
        self.visible_sample_count = 120
        self.interaction_state = "IDLE"
        self.fast_pan_mode = False
        self.axis = None
        self.hover_controller: AnalysisChartHoverController | None = None
        self.interaction_controller: MeshChartInteractionController | None = None
        self.time_window_controller = MeshTimeWindowController(self)
        self.time_window_controller.windowChanged.connect(self._time_window_changed)
        self.interaction_resume_timer = QTimer(self)
        self.interaction_resume_timer.setSingleShot(True)
        self.interaction_resume_timer.setInterval(80)
        self.interaction_resume_timer.timeout.connect(self._resume_after_interaction)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addLayout(self._build_summary(), 0)
        layout.addWidget(self._build_controls(), 0)
        self.view = ScrollableMatplotlibView(self, fill_parent=True)
        self.view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.view, 1)
        self.status_label = QLabel("解析采集数据后显示图表")
        self.status_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(self.status_label, 0)
        self.time_scrollbar = QScrollBar(Qt.Horizontal)
        self.time_scrollbar.valueChanged.connect(self._scroll_changed)
        layout.addWidget(self.time_scrollbar, 0)

    @property
    def canvas(self):
        return self.view.canvas

    def set_summary(self, summary: dict[str, object]) -> None:
        values = {
            "peer": summary.get("active_peer") or "-",
            "radio": summary.get("radio") or "-",
            "segment": f"{_display(summary.get('session_start'))} - {_display(summary.get('session_end'))}",
            "interval": "-",
            "first": summary.get("session_start") or "-",
            "last": summary.get("session_end") or "-",
            "samples": summary.get("main_link", 0),
            "active": summary.get("active_link", 0),
            "standby": max(int(summary.get("main_link", 0) or 0) - int(summary.get("active_link", 0) or 0), 0),
            "main_link": summary.get("main_link", 0),
            "switch": summary.get("switch", 0),
            "fping": summary.get("fping", 0),
            "iperf": summary.get("iperf", 0),
            "time_sync": summary.get("time_sync") or "时间同步：未建立，fping 使用本地时间",
        }
        for key, value in values.items():
            label = self.summary_labels.get(key)
            if label is not None:
                label.setText(str(value))

    def render_chart(self, chart: ChartData) -> None:
        self.current_chart = chart
        self.locked_index = -1
        self._disconnect_controllers()
        self._prepare_chart_data(chart)
        self._apply_locked_time()
        self._update_layer_visibility()
        visible = int(self.visible_samples_combo.currentData() or 0)
        self.visible_sample_count = 0 if visible <= 0 else visible
        self.time_window_controller.set_total_count(len(self.timestamp_numeric), self.visible_sample_count, 0, "payload")
        self._redraw_chart()

    def clear(self, empty_message: str = "未解析到图表数据") -> None:
        self._disconnect_controllers()
        self.series_values.clear()
        self.series_order.clear()
        self.timestamps = []
        self.timestamp_labels = []
        self.timestamp_numeric = np.asarray([], dtype=np.float64)
        self.locked_index = -1
        self.locked_delta_seconds = None
        figure = self.canvas.figure
        figure.clear()
        axis = figure.add_subplot(111)
        self.axis = axis
        axis.text(0.5, 0.5, empty_message, ha="center", va="center", transform=axis.transAxes)
        axis.set_xticks([])
        axis.set_yticks([])
        axis.set_title(self.chart_title)
        _apply_right_y_ticks(axis)
        self.view.refresh_figure_layout()
        self.status_label.setText(empty_message)
        self._sync_time_controls()

    def hide_hover(self) -> None:
        if self.hover_controller is not None:
            self.hover_controller.hide()

    def disconnect_controllers(self) -> None:
        self._disconnect_controllers()

    def set_locked_time(self, timestamp: datetime | None, *, redraw: bool = True) -> None:
        self.locked_time = timestamp.replace(tzinfo=None) if isinstance(timestamp, datetime) else None
        self._apply_locked_time()
        if redraw and self.current_chart is not None:
            self._redraw_chart()

    def clear_locked_time(self, *, redraw: bool = True) -> None:
        self.locked_time = None
        self.locked_index = -1
        self.locked_delta_seconds = None
        if redraw and self.current_chart is not None:
            self._redraw_chart()

    def begin_pan_interaction(self) -> None:
        self.interaction_state = "PANNING"
        self.fast_pan_mode = True
        self.hide_hover()

    def finish_pan_interaction_later(self) -> None:
        self.interaction_resume_timer.start()

    def begin_zoom_interaction(self) -> None:
        self.interaction_state = "ZOOMING"
        self.fast_pan_mode = False
        self.hide_hover()

    def finish_zoom_interaction_later(self) -> None:
        self.interaction_resume_timer.start()

    def zoom_time_window_at(self, _chart_key: str, xdata: float, step: float) -> None:
        index = self.time_window_controller.cursor_index_from_xdata(self.timestamp_numeric, xdata)
        if index >= 0:
            self.time_window_controller.zoom_at_index(index, step, "wheel")

    def pan_time_window_to(self, start_index: int, source: str = "drag") -> None:
        self.time_window_controller.set_time_window(start_index, self.visible_sample_count, source)

    def effective_visible_sample_count(self) -> int:
        return self.time_window_controller.effective_visible_count()

    def is_all_samples_visible(self) -> bool:
        return self.time_window_controller.is_all_visible()

    def toggle_locked_point_from_event(self, _chart_key: str, event) -> None:
        timestamp, _index = self._time_from_event(event)
        if timestamp is None:
            return
        self.lockTimeRequested.emit(timestamp)

    def show_chart_context_menu(self, _chart_key: str, event) -> None:
        timestamp, index = self._time_from_event(event)
        menu = QMenu(self)
        lock_action = menu.addAction("锁定当前时间点")
        clear_action = menu.addAction("取消锁定时间点")
        clear_action.setVisible(self.locked_time is not None)
        copy_action = menu.addAction("复制当前点信息")
        copy_action.setEnabled(index >= 0)
        menu.addSeparator()
        reset_action = menu.addAction("重置视图")
        action = menu.exec(self.canvas.mapToGlobal(event.guiEvent.pos()) if getattr(event, "guiEvent", None) is not None else QCursor.pos())
        if action is lock_action and timestamp is not None:
            self.lockTimeRequested.emit(timestamp)
        elif action is clear_action:
            self.lockTimeCleared.emit()
        elif action is copy_action and index >= 0:
            point = self._point_for_index(index)
            if point is not None:
                QApplication.clipboard().setText(self._tooltip_text(point))
        elif action is reset_action:
            self.reset_view()

    def reset_view(self) -> None:
        visible = int(self.visible_samples_combo.currentData() or 0)
        self.visible_sample_count = 0 if visible <= 0 else visible
        self.time_window_controller.set_time_window(0, self.visible_sample_count, "reset")

    def center_selected_sample(self) -> None:
        target = self.locked_index if self.locked_index >= 0 else max(0, len(self.timestamp_numeric) - 1)
        self.time_window_controller.center_on(target, self.visible_sample_count, "center")

    def _build_summary(self) -> QGridLayout:
        layout = QGridLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(2)
        labels = (
            ("peer", "PeerMac"),
            ("radio", "Radio"),
            ("segment", "当前连续运行时段"),
            ("interval", "估算采样间隔"),
            ("first", "最早采样时间"),
            ("last", "最新采样时间"),
            ("samples", "采样点数"),
            ("active", "ACTIVE"),
            ("standby", "STANDBY"),
            ("switch", "切换次数"),
            ("fping", "fping点"),
            ("iperf", "打流点"),
            ("time_sync", "时间同步"),
        )
        for index, (key, title) in enumerate(labels):
            row = index // 4
            column = (index % 4) * 2
            layout.addWidget(QLabel(title), row, column)
            value = QLabel("-")
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.summary_labels[key] = value
            layout.addWidget(value, row, column + 1)
        self.summary_labels["main_link"] = self.summary_labels["samples"]
        return layout

    def _build_controls(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(QLabel("可见采样点"))
        self.visible_samples_combo = QComboBox()
        for value in (30, 60, 120, 300, 0):
            self.visible_samples_combo.addItem("全部" if value == 0 else str(value), value)
        self.visible_samples_combo.setCurrentIndex(2)
        self.visible_samples_combo.setMaximumWidth(110)
        self.visible_samples_combo.currentIndexChanged.connect(self._visible_samples_changed)
        layout.addWidget(self.visible_samples_combo)
        self.show_switch_points_checkbox = QCheckBox("显示链路切换点")
        self.show_switch_points_checkbox.setChecked(True)
        self.show_station_checkbox = QCheckBox("显示归属站点/区间")
        self.show_station_checkbox.setChecked(True)
        self.show_anomaly_checkbox = QCheckBox("显示异常点")
        self.show_anomaly_checkbox.setChecked(True)
        for checkbox in (self.show_switch_points_checkbox, self.show_station_checkbox, self.show_anomaly_checkbox):
            checkbox.toggled.connect(self._redraw_chart)
            layout.addWidget(checkbox)
        self.center_button = QPushButton("定位当前点")
        self.center_button.clicked.connect(self.center_selected_sample)
        self.reset_button = QPushButton("重置视图")
        self.reset_button.clicked.connect(self.reset_view)
        layout.addWidget(self.center_button)
        layout.addWidget(self.reset_button)
        layout.addStretch(1)
        return widget

    def _prepare_chart_data(self, chart: ChartData) -> None:
        series_points: dict[str, list[tuple[datetime, float, str]]] = {}
        all_times: dict[datetime, str] = {}
        for series in chart.series:
            values: list[tuple[datetime, float, str]] = []
            for raw_time, raw_value in series.points:
                timestamp = _parse_time(raw_time)
                if timestamp is None or timestamp.year < 2000 or timestamp.year > 2100:
                    continue
                try:
                    metric = float(raw_value)
                except (TypeError, ValueError):
                    continue
                if not math.isfinite(metric):
                    continue
                label = _format_timestamp(timestamp, raw_time)
                values.append((timestamp, metric, label))
                all_times.setdefault(timestamp, label)
            if values:
                series_points[series.name] = sorted(values, key=lambda item: item[0])
        self.timestamps = sorted(all_times)
        self.timestamp_labels = [all_times[timestamp] for timestamp in self.timestamps]
        self.timestamp_numeric = np.asarray([date2num(timestamp) for timestamp in self.timestamps], dtype=np.float64)
        self.series_order = list(series_points)
        self.series_values = {}
        time_index = {timestamp: index for index, timestamp in enumerate(self.timestamps)}
        for name, points in series_points.items():
            values = np.full(len(self.timestamps), np.nan, dtype=np.float32)
            for timestamp, metric, _label in points:
                index = time_index.get(timestamp)
                if index is not None:
                    values[index] = metric
            self.series_values[name] = values
        self.hover_points = _build_hover_points(self.chart_key, chart, self.series_order, self.series_values, self.timestamps, self.timestamp_labels)
        self.event_indices = _event_indices(chart.events, self.timestamps)
        interval_label = self.summary_labels.get("interval")
        if interval_label is not None:
            interval_label.setText(_estimated_interval_text(self.timestamps))

    def _redraw_chart(self, *_args) -> None:
        self._disconnect_controllers()
        chart = self.current_chart
        if chart is None:
            self.clear()
            return
        if len(self.timestamp_numeric) == 0 or not self.series_values:
            self.clear(chart.empty_message)
            return
        figure = self.canvas.figure
        figure.clear()
        axis = figure.add_subplot(111)
        self.axis = axis
        axis._mesh_chart_key = self.chart_key
        indices = self._render_indices()
        y_values_for_window: list[np.ndarray] = []
        rendered_count = 0
        for name in self.series_order:
            values = self.series_values[name]
            render_indices_for_series = indices
            if self.visible_sample_count == 0:
                render_indices_for_series = np.union1d(indices, preserve_extrema_indices(np.arange(len(values), dtype=np.int32), values, self._max_render_points()))
            finite_values = values[render_indices_for_series]
            finite = finite_values[np.isfinite(finite_values)]
            if len(finite):
                y_values_for_window.append(finite)
            rendered_count = max(rendered_count, len(render_indices_for_series))
            self._draw_series(axis, name, values, render_indices_for_series)
        self._apply_axes(axis, indices, y_values_for_window)
        self._draw_overlays(axis, indices)
        axis.set_title(chart.title)
        axis.set_ylabel(_y_label_for_chart(self.chart_key, chart.y_label))
        axis.grid(True, alpha=0.28)
        axis.legend(loc="upper right")
        _apply_right_y_ticks(axis)
        apply_cjk_font(axis)
        self.view.refresh_figure_layout()
        self.status_label.setText(self._status_text(chart.title, rendered_count))
        self._sync_time_controls()
        self.hover_controller = AnalysisChartHoverController(self.canvas, axis, self.hover_points, self._tooltip_text)
        self.hoverChanged.emit(self.hover_controller)
        self.interaction_controller = MeshChartInteractionController(self.canvas, axis, self, self.chart_key, self)
        self.interaction_controller.set_enabled(True)

    def _draw_series(self, axis, name: str, values: np.ndarray, indices: np.ndarray) -> None:
        first = True
        for segment in _split_visible_segments(self.timestamp_numeric, values, indices, self._continuity_gap_seconds()):
            x_values = [item[0] for item in segment]
            y_values = [item[1] for item in segment]
            kwargs = {"linewidth": 1.15, "label": name if first else None}
            if self.chart_key in {"rssi", "switch_rssi", "switch_log_rssi"}:
                kwargs.update(ACTIVE_LINE_STYLE if self.chart_key == "rssi" else {"marker": "o", "markersize": 4.0})
            axis.plot(x_values, y_values, **kwargs)
            first = False

    def _apply_axes(self, axis, indices: np.ndarray, y_values: list[np.ndarray]) -> None:
        start = int(indices[0]) if len(indices) else 0
        end = int(indices[-1]) if len(indices) else len(self.timestamp_numeric) - 1
        left = float(self.timestamp_numeric[start])
        right = float(self.timestamp_numeric[end])
        if left == right:
            pad = 0.5 / 86400
            axis.set_xlim(left - pad, right + pad)
        else:
            axis.set_xlim(left, right)
        configure_mesh_time_axis(axis, self.timestamps[start], self.timestamps[end], self.i18n)
        if self.chart_key == "busy":
            axis.set_ylim(0, 100)
        elif y_values:
            values = np.concatenate(y_values)
            ymin = float(np.nanmin(values))
            ymax = float(np.nanmax(values))
            if ymin == ymax:
                ymin -= 1
                ymax += 1
            pad = max((ymax - ymin) * 0.08, 1.0)
            axis.set_ylim(ymin - pad, ymax + pad)

    def _draw_overlays(self, axis, indices: np.ndarray) -> None:
        if len(indices) == 0:
            return
        visible = set(int(index) for index in indices)
        if self.show_switch_points_checkbox.isChecked() and self.event_indices:
            switch_indices = [index for index in self.event_indices if index in visible]
            if switch_indices:
                y_values = [self._nearest_y(index) for index in switch_indices]
                axis.scatter(self.timestamp_numeric[switch_indices], y_values, **SWITCH_MARKER_STYLE)
        if self.show_anomaly_checkbox.isChecked():
            anomaly_indices = [index for index in indices if self._is_anomaly_index(int(index))]
            if anomaly_indices:
                axis.scatter(self.timestamp_numeric[anomaly_indices], [self._nearest_y(index) for index in anomaly_indices], **ANOMALY_MARKER_STYLE)
        if self.locked_time is not None:
            locked_x = float(date2num(self.locked_time))
            left, right = axis.get_xlim()
            if min(left, right) <= locked_x <= max(left, right):
                ymin, ymax = axis.get_ylim()
                axis.vlines(locked_x, ymin, ymax, **LOCKED_LINE_STYLE)
                axis.text(locked_x, 0.98, _format_time_label(self.locked_time), transform=axis.get_xaxis_transform(), fontsize=8, color="#0f766e", ha="center", va="top", clip_on=True)
        if self.locked_index in visible and self.locked_delta_seconds is not None:
            y_value = self._nearest_y(self.locked_index)
            axis.scatter([self.timestamp_numeric[self.locked_index]], [y_value], **LOCKED_MARKER_STYLE)
        if self.show_station_checkbox.isChecked() and self.chart_key == "rssi":
            self._draw_location_labels(axis, indices)

    def _draw_location_labels(self, axis, indices: np.ndarray) -> None:
        labels_by_time = _location_labels_by_time(self.current_chart.tooltip_rows if self.current_chart else [])
        if not labels_by_time:
            return
        previous = ""
        candidates: list[tuple[int, str]] = []
        for raw_index in indices:
            index = int(raw_index)
            label = labels_by_time.get(self.timestamp_labels[index], "")
            if not label or label == previous:
                previous = label
                continue
            candidates.append((index, label))
            previous = label
        accepted: list[tuple[int, str]] = []
        accepted_pixels: list[float] = []
        for index, label in candidates:
            pixel_x = axis.transData.transform((self.timestamp_numeric[index], 0))[0]
            if any(abs(pixel_x - used) < 120 for used in accepted_pixels):
                continue
            accepted.append((index, label))
            accepted_pixels.append(pixel_x)
            if len(accepted) >= 100:
                break
        for index, label in accepted:
            axis.text(self.timestamp_numeric[index], 0.02, _short_label(label), transform=axis.get_xaxis_transform(), fontsize=9, color="#64748b", ha="center", va="bottom", alpha=0.82, clip_on=True)

    def _render_indices(self) -> np.ndarray:
        total = len(self.timestamp_numeric)
        important = np.asarray(sorted(set(self.event_indices + ([self.locked_index] if self.locked_index >= 0 else []))), dtype=np.int32)
        return render_indices(total, self.window_start_index, self.visible_sample_count, important, self._max_render_points())

    def _max_render_points(self) -> int:
        return 12000 if self.chart_key in {"rssi", "switch_rssi", "switch_log_rssi"} else 8000

    def _continuity_gap_seconds(self) -> float:
        if len(self.timestamps) < 2:
            return 180.0
        gaps = [(self.timestamps[index] - self.timestamps[index - 1]).total_seconds() for index in range(1, min(len(self.timestamps), 200))]
        gaps = [gap for gap in gaps if gap > 0]
        return max((float(np.median(gaps)) if gaps else 1.0) * 5, 5.0)

    def _nearest_y(self, index: int) -> float:
        candidates = []
        for values in self.series_values.values():
            if 0 <= index < len(values) and np.isfinite(values[index]):
                candidates.append(float(values[index]))
        if candidates:
            return candidates[0]
        for offset in range(1, min(len(self.timestamp_numeric), 200)):
            for candidate_index in (index - offset, index + offset):
                if not (0 <= candidate_index < len(self.timestamp_numeric)):
                    continue
                for values in self.series_values.values():
                    if np.isfinite(values[candidate_index]):
                        return float(values[candidate_index])
        return 0.0

    def _is_anomaly_index(self, index: int) -> bool:
        return any(_is_anomaly(self.chart_key, float(values[index])) for values in self.series_values.values() if 0 <= index < len(values) and np.isfinite(values[index]))

    def _apply_locked_time(self) -> None:
        if self.locked_time is None:
            self.locked_index = -1
            self.locked_delta_seconds = None
            return
        index, delta = self._nearest_index_for_time(self.locked_time, _lock_tolerance_seconds(self.chart_key))
        self.locked_index = index
        self.locked_delta_seconds = delta if index >= 0 else None

    def _nearest_index_for_time(self, timestamp: datetime, max_seconds: float | None = None) -> tuple[int, float | None]:
        if not self.timestamps:
            return -1, None
        nearest = min(range(len(self.timestamps)), key=lambda index: abs((self.timestamps[index] - timestamp).total_seconds()))
        delta = abs((self.timestamps[nearest] - timestamp).total_seconds())
        if max_seconds is not None and delta > max_seconds:
            return -1, delta
        return nearest, delta

    def _index_from_event(self, event, *, max_pixel_distance: int = 24) -> int:
        if event.xdata is None or len(self.timestamp_numeric) == 0:
            return -1
        index = self.time_window_controller.cursor_index_from_xdata(self.timestamp_numeric, float(event.xdata))
        if index < 0 or self.axis is None:
            return -1
        event_x = getattr(event, "x", None)
        if event_x is not None:
            sample_pixel = self.axis.transData.transform((self.timestamp_numeric[index], 0))[0]
            if abs(float(sample_pixel) - float(event_x)) > max_pixel_distance:
                return -1
        return index

    def _time_from_event(self, event) -> tuple[datetime | None, int]:
        if event.xdata is None:
            return None, -1
        index = self._index_from_event(event)
        if index >= 0:
            return self.timestamps[index], index
        try:
            timestamp = num2date(float(event.xdata)).replace(tzinfo=None)
        except (TypeError, ValueError, OverflowError):
            return None, -1
        return timestamp, -1

    def _point_for_index(self, index: int):
        if not (0 <= index < len(self.timestamps)):
            return None
        timestamp = self.timestamps[index]
        for point in self.hover_points:
            if getattr(point, "timestamp", None) == timestamp:
                return point
        return None

    def _status_text(self, title: str, rendered_count: int) -> str:
        base = f"已加载 {title}，采样点 {len(self.timestamp_numeric)} 个，可见 {rendered_count} 个"
        if self.locked_time is None:
            return base
        locked = f"已锁定时间点：{_format_full_time(self.locked_time)}"
        if self.locked_index < 0:
            return f"{base}；{locked}；当前图表在锁定时间附近无数据"
        nearest_time = self.timestamps[self.locked_index]
        delta = self.locked_delta_seconds if self.locked_delta_seconds is not None else abs((nearest_time - self.locked_time).total_seconds())
        return f"{base}；{locked}；当前图表最近点：{_format_full_time(nearest_time)}，偏差 {delta:.1f}s"

    def _visible_samples_changed(self) -> None:
        value = int(self.visible_samples_combo.currentData() or 0)
        self.visible_sample_count = 0 if value <= 0 else value
        self.time_window_controller.set_time_window(self.window_start_index, self.visible_sample_count, "preset")

    def _scroll_changed(self, value: int) -> None:
        self.time_window_controller.set_time_window(value, self.visible_sample_count, "scrollbar")

    def _time_window_changed(self, start: int, visible: int, _source: str) -> None:
        self.window_start_index = start
        self.visible_sample_count = visible
        self._sync_time_controls()
        self._redraw_chart()

    def _sync_time_controls(self) -> None:
        total = len(self.timestamp_numeric)
        effective = self.time_window_controller.effective_visible_count()
        maximum = max(total - effective, 0)
        with QSignalBlocker(self.time_scrollbar):
            self.time_scrollbar.setRange(0, maximum)
            self.time_scrollbar.setPageStep(max(effective, 1))
            self.time_scrollbar.setSingleStep(max(effective // 10, 1))
            self.time_scrollbar.setValue(min(self.window_start_index, maximum))

    def _resume_after_interaction(self) -> None:
        self.interaction_state = "IDLE"
        self.fast_pan_mode = False
        self._redraw_chart()

    def _disconnect_controllers(self) -> None:
        self.interaction_resume_timer.stop()
        if self.hover_controller is not None:
            self.hover_controller.disconnect()
            self.hover_controller = None
            self.hoverChanged.emit(None)
        if self.interaction_controller is not None:
            self.interaction_controller.disconnect()
            self.interaction_controller = None

    def _update_layer_visibility(self) -> None:
        self.show_switch_points_checkbox.setVisible(self.chart_key in {"rssi", "ping_loss", "ping", "traffic", "switch_rssi", "switch_log_rssi"})
        self.show_station_checkbox.setVisible(self.chart_key == "rssi")
        self.show_anomaly_checkbox.setVisible(True)

    def _tooltip_text(self, point: object) -> str:
        return _tooltip_text(point)


def _parse_time(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    text = str(value or "").strip().replace("Z", "")
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _format_timestamp(timestamp: datetime, original: object) -> str:
    text = str(original or "").strip()
    if text:
        return text
    return timestamp.isoformat(sep=" ", timespec="milliseconds")


def _format_full_time(timestamp: datetime) -> str:
    return timestamp.isoformat(sep=" ", timespec="milliseconds")


def _format_time_label(timestamp: datetime) -> str:
    return timestamp.strftime("%H:%M:%S")


def _lock_tolerance_seconds(chart_key: str) -> float:
    return LOCK_MATCH_TOLERANCE_SECONDS.get(chart_key, 3.0)


def _split_visible_segments(timestamp_numeric: np.ndarray, values: np.ndarray, indices: np.ndarray, max_gap_seconds: float) -> list[list[tuple[float, float]]]:
    segments: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    previous_index: int | None = None
    max_gap_days = max_gap_seconds / 86400
    for raw_index in indices:
        index = int(raw_index)
        if not (0 <= index < len(values)) or not np.isfinite(values[index]):
            if current:
                segments.append(current)
                current = []
            previous_index = None
            continue
        if previous_index is not None and float(timestamp_numeric[index] - timestamp_numeric[previous_index]) > max_gap_days:
            if current:
                segments.append(current)
                current = []
        current.append((float(timestamp_numeric[index]), float(values[index])))
        previous_index = index
    if current:
        segments.append(current)
    return segments


def _build_hover_points(chart_key: str, chart: ChartData, series_order: list[str], series_values: dict[str, np.ndarray], timestamps: list[datetime], labels: list[str]) -> list[object]:
    rows_by_time: dict[str, dict[str, object]] = {}
    for row in chart.tooltip_rows:
        time_value = str(row.get("time") or row.get("collected_at") or "").strip()
        if time_value:
            rows_by_time.setdefault(time_value, row)
    points: list[object] = []
    for index, timestamp in enumerate(timestamps):
        for series_name in series_order:
            values = series_values[series_name]
            if index >= len(values) or not np.isfinite(values[index]):
                continue
            detail = rows_by_time.get(labels[index], {})
            points.append(
                SimpleNamespace(
                    timestamp=timestamp,
                    timestamp_label=labels[index],
                    chart_key=chart_key,
                    series_name=series_name,
                    metric_label=_metric_label(chart_key, chart.title),
                    metric_value=float(values[index]),
                    detail=detail,
                    rssi=float(values[index]) if chart_key == "rssi" else None,
                    peer_name=str(detail.get("peer_name") or ""),
                    peer_mac=str(detail.get("peer_mac") or ""),
                    station=str(detail.get("station") or ""),
                    section=str(detail.get("section") or ""),
                    link_state=str(detail.get("status") or ""),
                    traffic_direction=detail.get("direction", "") if chart_key == "traffic" else "",
                    traffic_rate_mbps=detail.get("rate_mbps", float(values[index])) if chart_key == "traffic" else None,
                    traffic_protocol=detail.get("protocol", "") if chart_key == "traffic" else "",
                    traffic_loss_percent=detail.get("loss_percent") if chart_key == "traffic" else None,
                    traffic_retransmits=detail.get("retransmits") if chart_key == "traffic" else None,
                )
            )
    return sorted(points, key=lambda item: item.timestamp)


def _event_indices(events: list[ChartEvent], timestamps: list[datetime]) -> list[int]:
    if not events or not timestamps:
        return []
    result: set[int] = set()
    threshold = _event_snap_threshold_seconds(timestamps)
    for event in events:
        timestamp = event.time
        if timestamp is None or timestamp.year < 2000 or timestamp.year > 2100:
            continue
        nearest = min(range(len(timestamps)), key=lambda index: abs((timestamps[index] - timestamp).total_seconds()))
        if abs((timestamps[nearest] - timestamp).total_seconds()) <= threshold:
            result.add(nearest)
    return sorted(result)


def _event_snap_threshold_seconds(timestamps: list[datetime]) -> float:
    if len(timestamps) < 2:
        return 60.0
    gaps = [(timestamps[index] - timestamps[index - 1]).total_seconds() for index in range(1, min(len(timestamps), 500))]
    gaps = [gap for gap in gaps if gap > 0]
    if not gaps:
        return 60.0
    return max(60.0, min(float(np.median(gaps)) * 5, 600.0))


def _estimated_interval_text(timestamps: list[datetime]) -> str:
    if len(timestamps) < 2:
        return "-"
    gaps = [(timestamps[index] - timestamps[index - 1]).total_seconds() for index in range(1, min(len(timestamps), 500))]
    gaps = [gap for gap in gaps if gap > 0]
    if not gaps:
        return "-"
    seconds = float(np.median(gaps))
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 60:
        return f"{seconds:.1f}s" if seconds % 1 else f"{int(seconds)}s"
    minutes = seconds / 60
    return f"{minutes:.1f}min" if minutes % 1 else f"{int(minutes)}min"


def _location_labels_by_time(rows: list[dict[str, object]]) -> dict[str, str]:
    labels: dict[str, str] = {}
    for row in rows:
        time_value = str(row.get("time") or row.get("collected_at") or "").strip()
        if not time_value:
            continue
        label = str(row.get("section") or row.get("station") or "").strip()
        if label:
            labels[time_value] = label
    return labels


def _metric_label(chart_key: str, title: str) -> str:
    return {
        "ping_loss": "丢包率",
        "ping": "延迟",
        "interface": "接口 PPS",
        "traffic": "打流速率",
        "busy": "信道繁忙度",
        "switch_rssi": "RSSI",
        "switch_log_rssi": "RSSI",
    }.get(chart_key, title)


def _tooltip_text(point: object) -> str:
    detail = getattr(point, "detail", {}) or {}
    chart_key = str(getattr(point, "chart_key", "") or "")
    timestamp = _display(getattr(point, "timestamp_label", ""))
    series_name = _display(getattr(point, "series_name", None))
    metric_value = getattr(point, "metric_value", None)
    if chart_key == "rssi":
        lines = [
            "采样时间:",
            timestamp,
            f"RSSI: {_display(getattr(point, 'rssi', metric_value))}",
            f"对端名称: {_display(getattr(point, 'peer_name', None))}",
            f"对端MAC: {_display(getattr(point, 'peer_mac', None))}",
            f"归属站点: {_display(getattr(point, 'station', None))}",
            f"归属区间: {_display(getattr(point, 'section', None))}",
            "",
            f"MR侧发送信道繁忙度: {_format_percent(detail.get('tx_busy'))}",
            f"MR侧接收信道繁忙度: {_format_percent(detail.get('rx_busy'))}",
            "",
            "备份链路:",
        ]
        standby_links = detail.get("standby_links") if isinstance(detail, dict) else []
        if isinstance(standby_links, list) and standby_links:
            for index, link in enumerate(standby_links[:5], start=1):
                if not isinstance(link, dict):
                    continue
                lines.append(
                    f"{index}. {_display(link.get('peer_name'))} / {_display(link.get('belong_station'))} / {_display(link.get('belong_section'))} / RSSI {_display(link.get('rssi'))}"
                )
        else:
            lines.append("-")
        return "\n".join(lines)
    if chart_key == "ping_loss":
        return "\n".join(
            [
                "设备时间:",
                _display(detail.get("device_time") or timestamp),
                f"本地时间: {_display(detail.get('local_time'))}",
                f"时间偏移: {_format_offset_ms(detail.get('clock_offset_ms'))}",
                f"目标: {_display(detail.get('target'))}",
                f"丢包率: {_format_percent(metric_value)}",
                f"平均延迟: {_format_ms(detail.get('avg_latency_ms'))}",
            ]
        )
    if chart_key == "ping":
        return "\n".join(
            [
                "设备时间:",
                _display(detail.get("device_time") or timestamp),
                f"本地时间: {_display(detail.get('local_time'))}",
                f"时间偏移: {_format_offset_ms(detail.get('clock_offset_ms'))}",
                f"目标: {_display(detail.get('target'))}",
                f"延迟: {_format_ms(metric_value)}",
            ]
        )
    if chart_key == "interface":
        return "\n".join(["采样时间:", timestamp, f"接口: {_display(detail.get('interface') or series_name)}", f"方向: {_display_direction(detail.get('direction'))}", f"PPS: {_display(metric_value)}"])
    if chart_key == "traffic":
        return "\n".join(
            [
                "采样时间:",
                timestamp,
                f"速率: {_format_bitrate_mbps(getattr(point, 'traffic_rate_mbps', metric_value))}",
                f"协议: {_display(getattr(point, 'traffic_protocol', None))}",
                f"方向: {_display(getattr(point, 'traffic_direction', None))}",
                f"丢包率: {_format_percent(getattr(point, 'traffic_loss_percent', None))}",
                f"TCP重传: {_display(getattr(point, 'traffic_retransmits', None))}",
            ]
        )
    if chart_key == "busy":
        return "\n".join(["设备时间:", timestamp, f"射频ID: {_display(detail.get('radio'))}", f"控制信道繁忙度: {_format_percent(detail.get('ctl_busy'))}", f"发送繁忙度: {_format_percent(detail.get('tx_busy'))}", f"接收繁忙度: {_format_percent(detail.get('rx_busy'))}"])
    if chart_key in {"switch_rssi", "switch_log_rssi"}:
        return "\n".join(
            [
                "切换时间:",
                timestamp,
                f"切换原因: {_display(detail.get('reason_text'))}",
                f"原AP: {_display(detail.get('from_peer_name'))}",
                f"原AP MAC: {_display(detail.get('from_peer_mac'))}",
                f"原RSSI: {_display(detail.get('from_rssi'))}",
                f"原归属站点: {_display(detail.get('from_station'))}",
                f"原归属区间: {_display(detail.get('from_section'))}",
                "",
                f"新AP: {_display(detail.get('to_peer_name'))}",
                f"新AP MAC: {_display(detail.get('to_peer_mac'))}",
                f"新RSSI: {_display(detail.get('to_rssi'))}",
                f"新归属站点: {_display(detail.get('to_station'))}",
                f"新归属区间: {_display(detail.get('to_section'))}",
                "",
                f"Peer数量: {_display(detail.get('peer_quantity'))}",
                f"Link数量: {_display(detail.get('link_quantity'))}",
            ]
        )
    return "\n".join(["采样时间:", timestamp, f"曲线: {series_name}", f"{_display(getattr(point, 'metric_label', None))}: {_display(metric_value)}"])


def _apply_right_y_ticks(axis) -> None:
    axis.yaxis.set_ticks_position("both")
    axis.tick_params(axis="y", which="both", labelleft=True, labelright=True)
    axis.spines["right"].set_visible(True)


def _y_label_for_chart(chart_key: str, ylabel: str) -> str:
    return "RSSI（设备原始值）" if chart_key in {"rssi", "switch_rssi", "switch_log_rssi"} else ylabel


def _is_anomaly(chart_key: str, value: float) -> bool:
    if chart_key == "ping_loss":
        return value > 0
    if chart_key == "ping":
        return value >= 100
    if chart_key == "busy":
        return value >= 80
    if chart_key in {"rssi", "switch_rssi", "switch_log_rssi"}:
        return value <= 20
    if chart_key == "traffic":
        return value <= 0
    return False


def _short_label(value: str, *, limit: int = 12) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else f"{text[:limit]}..."


def _display(value: object) -> str:
    if value is None:
        return "-"
    text = str(value).strip()
    if not text:
        return "-"
    return text[:-2] if text.endswith(".0") else text


def _format_percent(value: object) -> str:
    text = _display(value)
    return text if text == "-" or text.endswith("%") else f"{text}%"


def _format_ms(value: object) -> str:
    text = _display(value)
    return text if text == "-" or text.endswith("ms") else f"{text} ms"


def _format_offset_ms(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    sign = "+" if number >= 0 else ""
    return f"{sign}{number:.0f}ms"


def _display_direction(value: object) -> str:
    text = str(value or "").strip().casefold()
    return {"inbound": "入方向", "outbound": "出方向", "download": "下行", "upload": "上行"}.get(text, _display(value))


def _format_bitrate_mbps(value: object) -> str:
    try:
        mbps = float(value)
    except (TypeError, ValueError):
        return "-"
    bps = mbps * 1_000_000
    if bps >= 1_000_000_000:
        return f"{bps / 1_000_000_000:.2f} Gbps"
    if bps >= 1_000_000:
        return f"{bps / 1_000_000:.2f} Mbps"
    if bps >= 1_000:
        return f"{bps / 1_000:.2f} Kbps"
    return f"{bps:.0f} bps"
