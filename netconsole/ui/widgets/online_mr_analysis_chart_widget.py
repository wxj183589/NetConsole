from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Callable

from matplotlib.dates import AutoDateLocator, ConciseDateFormatter, date2num
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from netconsole.services.online_mr_chart_builder import ChartData, ChartEvent
from netconsole.ui.widgets.scrollable_matplotlib_view import AnalysisChartHoverController, ScrollableMatplotlibView


class OnlineMrAnalysisChartWidget(QWidget):
    hoverChanged = Signal(object)

    def __init__(self, chart_key: str, chart_title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.chart_key = chart_key
        self.chart_title = chart_title
        self.current_chart: ChartData | None = None
        self.current_hover_points: list[object] = []
        self.tooltip_builder: Callable[[object], str] = _default_tooltip_text
        self.hover_controller: AnalysisChartHoverController | None = None
        self.axis = None
        self.summary_labels: dict[str, QLabel] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)
        layout.addLayout(self._build_summary())
        layout.addWidget(self._build_controls())
        self.view = ScrollableMatplotlibView(self, min_plot_width=1500, min_plot_height=620)
        self.view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.view, 1)
        self.status_label = QLabel("解析采集数据后显示图表")
        self.status_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(self.status_label)

    @property
    def canvas(self):
        return self.view.canvas

    def set_summary(self, summary: dict[str, object]) -> None:
        values = {
            "device": summary.get("device_name") or "-",
            "time_range": f"{_display(summary.get('session_start'))} - {_display(summary.get('session_end'))}",
            "main_link": summary.get("main_link", 0),
            "switch": summary.get("switch", 0),
            "fping": summary.get("fping", 0),
            "iperf": summary.get("iperf", 0),
            "busy": summary.get("channel_busy", 0),
            "interface": summary.get("interface_rate", 0),
        }
        for key, value in values.items():
            label = self.summary_labels.get(key)
            if label is not None:
                label.setText(str(value))

    def render_chart(
        self,
        chart: ChartData,
        *,
        hover_points: list[object] | None = None,
        tooltip_builder: Callable[[object], str] | None = None,
    ) -> None:
        self.hide_hover()
        self._disconnect_hover()
        self.current_chart = chart
        self.current_hover_points = hover_points or _generic_hover_points(self.chart_key, chart)
        self.tooltip_builder = tooltip_builder or _default_tooltip_text
        self._update_layer_visibility()

        figure = self.canvas.figure
        figure.clear()
        axis = figure.add_subplot(111)
        self.axis = axis
        plotted_points: list[tuple[datetime, float]] = []
        plotted = False
        total_points = 0
        for series in chart.series:
            points = [_chart_point(point) for point in series.points]
            points = [point for point in points if point is not None]
            if not points:
                continue
            total_points += len(points)
            plotted_points.extend(points)
            first = True
            for segment in _split_segments(points, max_gap_seconds=60 if self.chart_key == "switch_rssi" else 180):
                x_values = [point[0] for point in segment]
                y_values = [point[1] for point in segment]
                kwargs = {"linewidth": 1.15, "label": series.name if first else None}
                if self.chart_key in {"rssi", "switch_rssi"}:
                    kwargs.update({"marker": "o", "markersize": 2.6 if self.chart_key == "rssi" else 4.0})
                axis.plot(x_values, y_values, **kwargs)
                first = False
            plotted = True

        self._resize_plot(total_points)
        if plotted:
            self._draw_overlays(axis, plotted_points, chart.events)
            axis.grid(True, alpha=0.28)
            axis.legend(loc="upper right")
            axis.set_xlabel(_x_label_for_chart(self.chart_key))
            axis.set_ylabel(_y_label_for_chart(self.chart_key, chart.y_label))
            _configure_time_axis(axis)
        else:
            axis.text(0.5, 0.5, chart.empty_message, ha="center", va="center", transform=axis.transAxes)
            axis.set_xticks([])
            axis.set_yticks([])
        axis.set_title(chart.title)
        _apply_right_y_ticks(axis)
        try:
            from netconsole.ui.mesh_chart_font import apply_cjk_font

            apply_cjk_font(axis)
        except Exception:
            pass
        if plotted and self.current_hover_points:
            self.hover_controller = AnalysisChartHoverController(self.canvas, axis, self.current_hover_points, self.tooltip_builder)
            self.hoverChanged.emit(self.hover_controller)
        self.canvas.draw_idle()
        self.status_label.setText(f"已加载 {chart.title}，采样点 {total_points} 个" if plotted else chart.empty_message)

    def hide_hover(self) -> None:
        if self.hover_controller is not None:
            self.hover_controller.hide()

    def clear(self, empty_message: str = "未解析到图表数据") -> None:
        self.hide_hover()
        self._disconnect_hover()
        figure = self.canvas.figure
        figure.clear()
        axis = figure.add_subplot(111)
        self.axis = axis
        axis.text(0.5, 0.5, empty_message, ha="center", va="center", transform=axis.transAxes)
        axis.set_xticks([])
        axis.set_yticks([])
        axis.set_title(self.chart_title)
        self.canvas.draw_idle()
        self.status_label.setText(empty_message)

    def _build_summary(self) -> QGridLayout:
        layout = QGridLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(2)
        labels = (
            ("device", "设备名称"),
            ("time_range", "会话时间"),
            ("main_link", "主链路点"),
            ("switch", "切换次数"),
            ("fping", "fping点"),
            ("iperf", "打流点"),
            ("busy", "信道繁忙点"),
            ("interface", "接口速率点"),
        )
        for index, (key, title) in enumerate(labels):
            row = index // 4
            column = (index % 4) * 2
            layout.addWidget(QLabel(title), row, column)
            value = QLabel("-")
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.summary_labels[key] = value
            layout.addWidget(value, row, column + 1)
        return layout

    def _build_controls(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(QLabel("可见采样点"))
        self.visible_samples_combo = QComboBox()
        for text, value in (("自适应", 0), ("120", 120), ("300", 300), ("全部", -1)):
            self.visible_samples_combo.addItem(text, value)
        self.visible_samples_combo.setMaximumWidth(110)
        layout.addWidget(self.visible_samples_combo)
        self.show_switch_points_checkbox = QCheckBox("显示链路切换点")
        self.show_switch_points_checkbox.setChecked(True)
        self.show_station_checkbox = QCheckBox("显示归属站点")
        self.show_station_checkbox.setChecked(True)
        self.show_section_checkbox = QCheckBox("显示归属区间")
        self.show_section_checkbox.setChecked(False)
        self.show_anomaly_checkbox = QCheckBox("显示异常点")
        self.show_anomaly_checkbox.setChecked(True)
        self.show_traffic_interval_checkbox = QCheckBox("显示打流区间")
        self.show_traffic_interval_checkbox.setChecked(False)
        self.active_only_checkbox = QCheckBox("仅显示 ACTIVE")
        self.active_only_checkbox.setChecked(True)
        self.show_standby_checkbox = QCheckBox("显示 STANDBY")
        self.show_standby_checkbox.setChecked(False)
        for checkbox in (
            self.show_switch_points_checkbox,
            self.show_station_checkbox,
            self.show_section_checkbox,
            self.show_anomaly_checkbox,
            self.show_traffic_interval_checkbox,
            self.active_only_checkbox,
            self.show_standby_checkbox,
        ):
            checkbox.toggled.connect(self._rerender_current)
            layout.addWidget(checkbox)
        self.reset_button = QPushButton("重置视图")
        self.reset_button.clicked.connect(lambda: self.render_chart(self.current_chart, hover_points=self.current_hover_points, tooltip_builder=self.tooltip_builder) if self.current_chart is not None else None)
        layout.addWidget(self.reset_button)
        layout.addStretch(1)
        return widget

    def _rerender_current(self) -> None:
        if self.current_chart is not None:
            self.render_chart(self.current_chart, hover_points=self.current_hover_points, tooltip_builder=self.tooltip_builder)

    def _disconnect_hover(self) -> None:
        if self.hover_controller is not None:
            self.hover_controller.disconnect()
            self.hover_controller = None
            self.hoverChanged.emit(None)

    def _update_layer_visibility(self) -> None:
        is_rssi = self.chart_key == "rssi"
        is_switch = self.chart_key == "switch_rssi"
        self.show_switch_points_checkbox.setVisible(self.chart_key in {"rssi", "ping_loss", "ping", "traffic", "switch_rssi"})
        self.show_station_checkbox.setVisible(is_rssi)
        self.show_section_checkbox.setVisible(is_rssi or is_switch)
        self.show_traffic_interval_checkbox.setVisible(self.chart_key in {"ping_loss", "ping", "traffic"})
        self.active_only_checkbox.setVisible(is_rssi)
        self.show_standby_checkbox.setVisible(is_rssi)

    def _resize_plot(self, point_count: int) -> None:
        width = 1500
        if point_count > 180:
            width += min(8000, (point_count - 180) * 6)
        if self.chart_key in {"interface", "traffic", "busy"}:
            width += 240
        self.view.set_preferred_plot_width(width, height=620)

    def _draw_overlays(self, axis, points: list[tuple[datetime, float]], events: list[ChartEvent]) -> None:
        if self.show_switch_points_checkbox.isChecked() and events:
            x_values = []
            y_values = []
            colors = []
            for event in events:
                y_value = _nearest_y(points, event.time)
                if y_value is None:
                    continue
                x_values.append(event.time)
                y_values.append(y_value)
                colors.append("#f59e0b" if event.severity == "warning" else "#dc2626")
            if x_values:
                axis.scatter(x_values, y_values, s=32, marker="o", color=colors, edgecolors="#ffffff", linewidths=0.7, alpha=0.92, zorder=5, label="链路切换")
        if self.show_anomaly_checkbox.isChecked():
            anomalies = [(time_value, y_value) for time_value, y_value in points if _is_anomaly(self.chart_key, y_value)]
            if anomalies:
                axis.scatter([item[0] for item in anomalies], [item[1] for item in anomalies], s=24, color="#ef4444", marker="o", alpha=0.9, zorder=4, label="异常点")
        if self.chart_key == "rssi":
            if self.show_station_checkbox.isChecked():
                self._draw_location_labels(axis, "station", points)
            if self.show_section_checkbox.isChecked():
                self._draw_location_labels(axis, "section", points)

    def _draw_location_labels(self, axis, key: str, points: list[tuple[datetime, float]]) -> None:
        if not self.current_hover_points:
            return
        accepted: list[tuple[datetime, str]] = []
        accepted_pixels: list[float] = []
        previous = ""
        for point in self.current_hover_points:
            detail = getattr(point, "detail", {}) or {}
            label = str(getattr(point, key, "") or detail.get(key, "")).strip()
            timestamp = getattr(point, "timestamp", None)
            if not isinstance(timestamp, datetime) or not label or label == previous:
                previous = label
                continue
            pixel_x = axis.transData.transform((date2num(timestamp), 0))[0]
            if any(abs(pixel_x - used) < 130 for used in accepted_pixels):
                previous = label
                continue
            accepted.append((timestamp, label))
            accepted_pixels.append(pixel_x)
            previous = label
        for timestamp, label in accepted[:80]:
            axis.text(timestamp, 0.02, _short_label(label), transform=axis.get_xaxis_transform(), fontsize=9, color="#64748b", ha="center", va="bottom", alpha=0.82, clip_on=True)


def _chart_point(value: object) -> tuple[datetime, float] | None:
    if not isinstance(value, (tuple, list)) or len(value) < 2:
        return None
    timestamp = _parse_time(value[0])
    if timestamp is None:
        return None
    try:
        metric = float(value[1])
    except (TypeError, ValueError):
        return None
    return timestamp, metric


def _parse_time(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip().replace("Z", "")
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _split_segments(points: list[tuple[datetime, float]], *, max_gap_seconds: int) -> list[list[tuple[datetime, float]]]:
    if not points:
        return []
    ordered = sorted(points, key=lambda point: point[0])
    segments: list[list[tuple[datetime, float]]] = [[ordered[0]]]
    for point in ordered[1:]:
        if (point[0] - segments[-1][-1][0]).total_seconds() > max_gap_seconds:
            segments.append([point])
        else:
            segments[-1].append(point)
    return segments


def _generic_hover_points(chart_key: str, chart: ChartData) -> list[object]:
    rows_by_time: dict[str, dict[str, object]] = {}
    for row in chart.tooltip_rows:
        time_value = str(row.get("time") or row.get("collected_at") or "").strip()
        if time_value:
            rows_by_time.setdefault(time_value, row)
    points: list[object] = []
    for series in chart.series:
        for value in series.points:
            parsed = _chart_point(value)
            if parsed is None:
                continue
            timestamp, metric_value = parsed
            timestamp_label = str(value[0]) if isinstance(value, (tuple, list)) and value else timestamp.isoformat(sep=" ", timespec="milliseconds")
            detail = rows_by_time.get(timestamp_label, {})
            points.append(
                SimpleNamespace(
                    timestamp=timestamp,
                    timestamp_label=timestamp_label,
                    chart_key=chart_key,
                    series_name=series.name,
                    metric_label=_metric_label(chart_key, chart.title),
                    metric_value=metric_value,
                    detail=detail,
                    traffic_direction=detail.get("direction", "") if chart_key == "traffic" else "",
                    traffic_rate_mbps=detail.get("rate_mbps", metric_value) if chart_key == "traffic" else None,
                    traffic_protocol=detail.get("protocol", "") if chart_key == "traffic" else "",
                    traffic_role=detail.get("role", "") if chart_key == "traffic" else "",
                    traffic_jitter_ms=detail.get("jitter_ms") if chart_key == "traffic" else None,
                    traffic_loss_percent=detail.get("loss_percent") if chart_key == "traffic" else None,
                    traffic_retransmits=detail.get("retransmits") if chart_key == "traffic" else None,
                    traffic_transfer_bytes=detail.get("transfer_bytes") if chart_key == "traffic" else None,
                    raw=detail.get("raw", ""),
                )
            )
    return sorted(points, key=lambda item: item.timestamp)


def _default_tooltip_text(point: object) -> str:
    detail = getattr(point, "detail", {}) or {}
    lines = [
        "采样时间:",
        _display(getattr(point, "timestamp_label", "")),
        f"曲线: {_display(getattr(point, 'series_name', None))}",
        f"{_display(getattr(point, 'metric_label', None))}: {_display(getattr(point, 'metric_value', None))}",
    ]
    if detail.get("target"):
        lines.append(f"目标: {_display(detail.get('target'))}")
    if detail.get("interface"):
        lines.append(f"接口: {_display(detail.get('interface'))}")
    if detail.get("direction"):
        lines.append(f"方向: {_display(detail.get('direction'))}")
    return "\n".join(lines[:8])


def _metric_label(chart_key: str, title: str) -> str:
    return {
        "ping_loss": "丢包率",
        "ping": "延迟",
        "interface": "接口 PPS",
        "traffic": "打流速率",
        "busy": "信道繁忙度",
        "switch_rssi": "RSSI",
    }.get(chart_key, title)


def _configure_time_axis(axis) -> None:
    locator = AutoDateLocator(minticks=4, maxticks=10)
    axis.xaxis.set_major_locator(locator)
    axis.xaxis.set_major_formatter(ConciseDateFormatter(locator))
    axis.figure.autofmt_xdate()


def _apply_right_y_ticks(axis) -> None:
    axis.yaxis.set_ticks_position("both")
    axis.tick_params(axis="y", which="both", labelleft=True, labelright=True)
    axis.spines["right"].set_visible(True)


def _x_label_for_chart(chart_key: str) -> str:
    return "设备时间" if chart_key in {"busy", "switch_rssi"} else "采样时间"


def _y_label_for_chart(chart_key: str, ylabel: str) -> str:
    if chart_key in {"rssi", "switch_rssi"}:
        return "RSSI（设备原始值）"
    return ylabel


def _nearest_y(points: list[tuple[datetime, float]], timestamp: datetime) -> float | None:
    if not points:
        return None
    nearest = min(points, key=lambda point: abs((point[0] - timestamp).total_seconds()))
    return nearest[1]


def _is_anomaly(chart_key: str, value: float) -> bool:
    if chart_key == "ping_loss":
        return value > 0
    if chart_key == "ping":
        return value >= 100
    if chart_key == "busy":
        return value >= 80
    if chart_key in {"rssi", "switch_rssi"}:
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
    return text or "-"
