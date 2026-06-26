from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
from matplotlib.collections import LineCollection
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from PySide6.QtCore import QByteArray, QPoint, QSignalBlocker, QTimer, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QDialog, QGridLayout, QHBoxLayout, QLabel, QMenu, QPushButton, QScrollBar, QSizePolicy, QTabWidget, QVBoxLayout, QWidget

from netconsole.core import app_logger
from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.core.settings import SettingsStore
from netconsole.models.mesh_log_models import MeshMrProfile, format_mac_h3c
from netconsole.ui.mesh_chart_hover import MeshChartHoverController
from netconsole.ui.mesh_chart_interaction_controller import MeshChartInteractionController
from netconsole.ui.mesh_chart_font import apply_cjk_font, resolve_matplotlib_cjk_font
from netconsole.ui.mesh_chart_payload import build_chart_payload, preserve_extrema_indices, render_indices
from netconsole.ui.mesh_chart_time_axis import configure_mesh_time_axis
from netconsole.ui.mesh_peer_series_worker import MeshPeerSeriesWorker
from netconsole.ui.mesh_time_window_controller import MeshTimeWindowController


DEFAULT_VISIBLE_SAMPLES = 120


@dataclass(frozen=True)
class MeshSelectedPoint:
    index: int
    session_id: str
    sample_time: str
    peer_mac: str
    peer_ap_name: str
    peer_site: str
    radio: str
    peer_radio: str
    state: str
    locked: bool = False


class MeshPeerDetailDialog(QDialog):
    def __init__(
        self,
        i18n: I18n,
        profile: MeshMrProfile,
        db_path: Path,
        peer_mac: str,
        radio: int | None = None,
        session_id: str | None = None,
        parent=None,
        auto_load: bool = True,
        anchor_link_id: int | None = None,
        initial_tab: str | None = None,
        source_file_id: int | str | None = None,
    ) -> None:
        super().__init__(parent)
        flags = self.windowFlags()
        flags |= Qt.Window | Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint | Qt.WindowCloseButtonHint
        self.setWindowFlags(flags)
        self.setSizeGripEnabled(True)
        resolve_matplotlib_cjk_font()
        self.i18n = i18n
        self.profile = profile
        self.db_path = db_path
        self.peer_mac = peer_mac
        self.radio = radio
        self.initial_session_id = session_id or ""
        self.anchor_link_id = anchor_link_id
        self.source_file_id = source_file_id
        self.initial_tab = initial_tab
        self.worker: MeshPeerSeriesWorker | None = None
        self.segment: dict[str, object] = {}
        self.chart_payload: dict[str, object] | None = None
        self.window_start_index = 0
        self.visible_sample_count = DEFAULT_VISIBLE_SAMPLES
        self.user_moved_window = False
        self.rendered_tabs: set[str] = set()
        self.dirty_tabs: set[str] = set()
        self.chart_artists: dict[str, dict[str, object]] = {}
        self.hover_controllers: dict[str, MeshChartHoverController] = {}
        self.interaction_controllers: dict[str, MeshChartInteractionController] = {}
        self.tab_keys: list[str] = []
        self.settings = SettingsStore(PathResolver())
        self.current_session_id = ""
        self.interaction_state = "IDLE"
        self.fast_pan_mode = False
        self.locked_selected_point: MeshSelectedPoint | None = None
        self.focus_peer_mac = ""
        self.focus_peer_ap_name = ""

        self.summary_labels: dict[str, QLabel] = {}
        self.status_label = QLabel(self.i18n.t("mesh_analysis.loading_chart"))
        self.lock_status_label = QLabel("")
        self.focus_status_label = QLabel("")
        self.session_filter = QComboBox()
        self.session_filter_container = QWidget()
        self.session_filter_label = QLabel(self.i18n.t("mesh_analysis.session_filter"))
        self.visible_samples_combo = QComboBox()
        self.show_switch_points_checkbox = QCheckBox("显示链路切换点")
        self.show_switch_points_checkbox.setChecked(True)
        self.unlock_point_button = QPushButton("解除锁定")
        self.unlock_point_button.setEnabled(False)
        self.clear_focus_button = QPushButton("取消聚焦")
        self.clear_focus_button.setEnabled(False)
        self.center_button = QPushButton(self.i18n.t("mesh_analysis.center_selected_sample"))
        self.reset_button = QPushButton(self.i18n.t("mesh_analysis.reset_view"))
        self.time_scrollbar = QScrollBar(Qt.Horizontal)
        self.tabs = QTabWidget()
        self.tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.figures: dict[str, Figure] = {}
        self.canvases: dict[str, FigureCanvasQTAgg] = {}
        self.window_update_timer = QTimer(self)
        self.window_update_timer.setSingleShot(True)
        self.window_update_timer.setInterval(40)
        self.interaction_resume_timer = QTimer(self)
        self.interaction_resume_timer.setSingleShot(True)
        self.interaction_resume_timer.setInterval(100)
        self.interaction_resume_timer.timeout.connect(self._resume_hover_after_interaction)
        self.time_window_controller = MeshTimeWindowController(self)
        self.time_window_controller.windowChanged.connect(self._time_window_changed)

        self._build_layout()
        title_radio = f"Radio {radio}" if radio is not None else "Radio"
        self.setWindowTitle(f"{profile.display_name} / {title_radio} / {format_mac_h3c(peer_mac)}")
        self.resize(1180, 860)
        self._restore_window_geometry()
        self.setFocusPolicy(Qt.StrongFocus)
        self.session_filter.currentIndexChanged.connect(self._mark_all_dirty_and_render_current)
        self.visible_samples_combo.currentIndexChanged.connect(self._visible_samples_changed)
        self.show_switch_points_checkbox.toggled.connect(self._mark_all_dirty_and_render_current)
        self.unlock_point_button.clicked.connect(self.clear_locked_point)
        self.clear_focus_button.clicked.connect(self.clear_focus_peer)
        self.center_button.clicked.connect(self.center_selected_sample)
        self.reset_button.clicked.connect(self.center_selected_sample)
        self.time_scrollbar.valueChanged.connect(self._scroll_changed)
        self.tabs.currentChanged.connect(self._render_current_tab)
        self.window_update_timer.timeout.connect(self._render_current_tab)
        if auto_load:
            self._load()

    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        summary = QGridLayout()
        keys = ("peer", "radio", "segment", "interval", "first", "last", "samples", "active", "standby")
        labels = {
            "peer": "PeerMac",
            "radio": "Radio",
            "segment": self.i18n.t("mesh_analysis.current_continuous_segment"),
            "interval": self.i18n.t("mesh_analysis.estimated_sample_interval"),
            "first": self.i18n.t("mesh_analysis.earliest_time"),
            "last": self.i18n.t("mesh_analysis.latest_time"),
            "samples": self.i18n.t("mesh_analysis.samples"),
            "active": "ACTIVE",
            "standby": "STANDBY",
        }
        for index, key in enumerate(keys):
            summary.addWidget(QLabel(labels[key]), index // 3, (index % 3) * 2)
            value = QLabel("-")
            self.summary_labels[key] = value
            summary.addWidget(value, index // 3, (index % 3) * 2 + 1)
        layout.addLayout(summary)
        session_layout = QHBoxLayout(self.session_filter_container)
        session_layout.setContentsMargins(0, 0, 0, 0)
        session_layout.addWidget(self.session_filter_label)
        session_layout.addWidget(self.session_filter, 1)
        layout.addWidget(self.session_filter_container)
        layout.addWidget(QLabel(self.i18n.t("mesh_analysis.visible_samples")))
        for value in (30, 60, 120, 300, 0):
            self.visible_samples_combo.addItem(self.i18n.t("mesh_analysis.all_samples") if value == 0 else str(value), value)
        self.visible_samples_combo.setCurrentIndex(2)
        layout.addWidget(self.visible_samples_combo)
        layout.addWidget(self.show_switch_points_checkbox)
        lock_layout = QHBoxLayout()
        lock_layout.addWidget(self.lock_status_label, 1)
        lock_layout.addWidget(self.unlock_point_button)
        layout.addLayout(lock_layout)
        focus_layout = QHBoxLayout()
        focus_layout.addWidget(self.focus_status_label, 1)
        focus_layout.addWidget(self.clear_focus_button)
        layout.addLayout(focus_layout)
        layout.addWidget(self.center_button)
        layout.addWidget(self.reset_button)
        for key, title in self._chart_titles():
            page = QWidget()
            page_layout = QVBoxLayout(page)
            figure = Figure(figsize=(8, 4), tight_layout=True)
            canvas = FigureCanvasQTAgg(figure)
            canvas.setFocusPolicy(Qt.StrongFocus)
            canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            page.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            page_layout.addWidget(canvas)
            self.figures[key] = figure
            self.canvases[key] = canvas
            self.tabs.addTab(page, title)
            self.tab_keys.append(key)
        layout.addWidget(self.status_label)
        layout.addWidget(self.tabs, 1)
        layout.addWidget(self.time_scrollbar)

    def _load(self) -> None:
        self.status_label.setText("正在加载首屏图表...")
        self.worker = MeshPeerSeriesWorker(self.db_path, self.peer_mac, self.radio, self.initial_session_id, self, self.anchor_link_id, self.source_file_id)
        if self.anchor_link_id is None:
            self.worker.loaded.connect(self._on_loaded)
        else:
            self.worker.loaded_initial.connect(self._on_loaded)
            self.worker.loaded_full.connect(self._on_loaded)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def _on_loaded(self, payload: object) -> None:
        kind = str(payload.get("kind") or "") if isinstance(payload, dict) else ""
        was_partial = bool((self.chart_payload or {}).get("metadata", {}).get("partial")) if isinstance(self.chart_payload, dict) else False
        preserve_center = kind == "full" and self.user_moved_window
        center_label = self._visible_center_sample_time() if preserve_center else ""
        if isinstance(payload, dict) and "chart_payload" in payload:
            self.chart_payload = payload["chart_payload"]
            self.segment = dict(payload.get("peer_segment") or {})
        elif isinstance(payload, dict) and "peer_segment" in payload and "run_segment" in payload:
            self.chart_payload = build_chart_payload(dict(payload.get("peer_segment") or {}), dict(payload.get("run_segment") or {}))
            self.segment = dict(payload.get("peer_segment") or {})
        else:
            rows = list(payload or []) if isinstance(payload, list) else []
            segment = {"anchor": rows[0] if rows else None, "rows": rows, "segment_start": rows[0].get("sample_time") if rows else None, "segment_end": rows[-1].get("sample_time") if rows else None}
            self.chart_payload = build_chart_payload(segment, {**segment, "events": []})
            self.segment = segment
        metadata = self.chart_payload.get("metadata", {}) if isinstance(self.chart_payload, dict) else {}
        is_partial = bool(metadata.get("partial"))
        if is_partial:
            self.status_label.setText("正在后台加载完整链路数据...")
        elif was_partial or kind == "full":
            self.status_label.setText("完整数据已加载")
        else:
            self.status_label.setText("")
        self._populate_sessions()
        self._update_summary()
        if preserve_center:
            self._configure_scrollbar(center_anchor=False)
            self._restore_visible_center(center_label)
        else:
            self._configure_scrollbar(center_anchor=True)
        self._mark_all_dirty_and_render_current()
        if self.initial_tab:
            index = self.tab_keys.index(self.initial_tab) if self.initial_tab in self.tab_keys else -1
            if index >= 0:
                self.tabs.setCurrentIndex(index)
        if self.worker is not None and not is_partial:
            self.worker.deleteLater()
            self.worker = None

    def _on_failed(self, error: str) -> None:
        self.status_label.setText(error)
        if self.worker is not None:
            self.worker.deleteLater()
            self.worker = None

    def _populate_sessions(self) -> None:
        self.session_filter.blockSignals(True)
        self.session_filter.clear()
        payload = self.chart_payload or {}
        sessions = [item for item in payload.get("session_options", []) if isinstance(item, dict) and item.get("session_id")]
        if len(sessions) <= 1:
            self.current_session_id = str(sessions[0]["session_id"]) if len(sessions) == 1 else ""
            self.session_filter_container.setVisible(False)
            self.session_filter.blockSignals(False)
            return
        self.session_filter_container.setVisible(True)
        self.session_filter.addItem(self.i18n.t("mesh_analysis.all_sessions"), "")
        for index, item in enumerate(sessions, start=1):
            start = _short_time(str(item.get("first_sample_time") or ""))
            end = _short_time(str(item.get("last_sample_time") or ""))
            self.session_filter.addItem(self.i18n.t("mesh_analysis.session_time_range", index=index, start=start, end=end), str(item["session_id"]))
        selected = self.session_filter.findData(self.initial_session_id)
        self.session_filter.setCurrentIndex(selected if selected >= 0 else 0)
        self.current_session_id = str(self.session_filter.currentData() or "")
        self.session_filter.blockSignals(False)

    def _update_summary(self) -> None:
        payload = self.chart_payload or {}
        metadata = payload.get("metadata", {}) if isinstance(payload.get("metadata"), dict) else {}
        labels = payload.get("timestamp_labels") or []
        peer_series = payload.get("peer_series", {}) if isinstance(payload.get("peer_series"), dict) else {}
        state_values = peer_series.get("state")
        active_count = int(np.sum(state_values == 1)) if isinstance(state_values, np.ndarray) else 0
        standby_count = int(np.sum(state_values == 0)) if isinstance(state_values, np.ndarray) else 0
        self.summary_labels["peer"].setText(format_mac_h3c(self.peer_mac))
        self.summary_labels["radio"].setText(str(self.radio) if self.radio is not None else "-")
        self.summary_labels["first"].setText(str(labels[0]) if labels else "-")
        self.summary_labels["last"].setText(str(labels[-1]) if labels else "-")
        self.summary_labels["segment"].setText(f"{metadata.get('segment_start') or '-'} - {metadata.get('segment_end') or '-'}")
        interval = metadata.get("estimated_interval_seconds")
        self.summary_labels["interval"].setText(f"{float(interval):.3f}s" if isinstance(interval, int | float) else "-")
        self.summary_labels["samples"].setText(str(metadata.get("sample_count") or 0))
        self.summary_labels["active"].setText(str(active_count))
        self.summary_labels["standby"].setText(str(standby_count))
        self.setToolTip("")

    def _chart_titles(self) -> list[tuple[str, str]]:
        return [
            ("signal", self.i18n.t("mesh_analysis.signal_chart")),
            ("rssi_noise", self.i18n.t("mesh_analysis.rssi_noise_chart")),
            ("load", self.i18n.t("mesh_analysis.channel_load_chart")),
            ("active_next_rssi", self.i18n.t("mesh_analysis.current_active_rssi")),
            ("active_channel_load", self.i18n.t("mesh_analysis.active_channel_load")),
        ]

    def _mark_all_dirty_and_render_current(self, *_args) -> None:
        self.current_session_id = str(self.session_filter.currentData() or "") if self.session_filter_container.isVisible() else self.current_session_id
        for controller in self.hover_controllers.values():
            controller.clear_cache()
        self.dirty_tabs.update(self.tab_keys)
        self._render_current_tab()

    def _render_current_tab(self, *_args) -> None:
        if self.chart_payload is None or not self.tab_keys:
            return
        key = self.tab_keys[self.tabs.currentIndex()]
        self._sync_active_controllers(key)
        started = time.perf_counter()
        self._render_tab(key)
        elapsed = (time.perf_counter() - started) * 1000
        event = "MESH_CHART_INITIAL_RENDER" if key not in self.rendered_tabs else "MESH_CHART_WINDOW_UPDATED"
        app_logger.log_info(event, f"anchor_link_id={self.anchor_link_id}, tab={key}, rendered_points={self._last_render_count(key)}, elapsed_ms={elapsed:.1f}, backend=matplotlib-cpu")
        self.rendered_tabs.add(key)
        self.dirty_tabs.discard(key)

    def _render_tab(self, key: str) -> None:
        artists = self.chart_artists.get(key)
        if artists is None:
            artists = self._create_chart_artists(key)
            self.chart_artists[key] = artists
        self._update_chart_data(key, artists)

    def _create_chart_artists(self, key: str) -> dict[str, object]:
        figure = self.figures[key]
        figure.clear()
        axis = figure.add_subplot(111)
        axis._mesh_chart_key = key
        axis.grid(True)
        lines = {}
        for field, label, style in self._series_specs(key):
            (line,) = axis.plot([], [], style, linewidth=1.2, marker=None, label=label)
            lines[field] = line
        anchor_line = axis.axvline(0, color="#2563eb", linewidth=1.2, linestyle="-.", label=self.i18n.t("mesh_analysis.selected_sample"))
        axis.legend()
        if key in {"signal", "active_next_rssi"}:
            axis.set_ylabel(self.i18n.t("mesh_analysis.raw_rssi"))
        if key in {"load", "active_channel_load"}:
            axis.set_ylabel(self.i18n.t("mesh_analysis.channel_load_percent"))
        configure_mesh_time_axis(axis, None, None, self.i18n)
        hover = MeshChartHoverController(self.canvases[key], axis, self.i18n, self)
        hover.set_enabled(key == self._current_tab_key())
        self.hover_controllers[key] = hover
        interaction = MeshChartInteractionController(self.canvases[key], axis, self, key, self)
        interaction.set_enabled(key == self._current_tab_key())
        self.interaction_controllers[key] = interaction
        apply_cjk_font(axis)
        return {"axis": axis, "lines": lines, "anchor_line": anchor_line, "collections": [], "spans": [], "texts": [], "last_count": 0}

    def _update_chart_data(self, key: str, artists: dict[str, object]) -> None:
        payload = self.chart_payload or {}
        timestamp_numeric = payload.get("timestamp_numeric")
        if not isinstance(timestamp_numeric, np.ndarray) or len(timestamp_numeric) == 0:
            return
        axis = artists["axis"]
        lines: dict[str, object] = artists["lines"]
        important = payload.get("important_indices") if isinstance(payload.get("important_indices"), np.ndarray) else np.asarray([], dtype=np.int32)
        base_indices = self._base_render_indices()
        max_points = self._max_render_points(key)
        all_y_values: list[np.ndarray] = []
        rendered_count = 0
        for field, _label, _style in self._series_specs(key):
            values = self._series_values(field)
            if values is None:
                continue
            render_values = self._render_series_values(field, values)
            indices = base_indices
            if self.visible_sample_count == 0:
                indices = np.union1d(preserve_extrema_indices(np.arange(len(timestamp_numeric), dtype=np.int32), render_values, max_points), important)
            x = timestamp_numeric[indices]
            y = render_values[indices]
            lines[field].set_data(x, y)
            finite = y[np.isfinite(y)]
            if len(finite):
                all_y_values.append(finite)
            rendered_count = max(rendered_count, len(indices))
        self._apply_axes_window(axis, timestamp_numeric, all_y_values)
        self._clear_overlay_artists(artists)
        for field, _label, _style in self._series_specs(key):
            values = self._series_values(field)
            line = lines.get(field)
            if values is not None and line is not None:
                self._draw_short_gap_bridges(artists, field, values, base_indices, line.get_color())
        self._draw_overlays(key, artists, base_indices)
        self.hover_controllers[key].set_context(payload, key, [field for field, _label, _style in self._series_specs(key)], self.current_session_id)
        artists["last_count"] = rendered_count
        if self.visible_sample_count == 0 and rendered_count:
            app_logger.log_info("MESH_CHART_DOWNSAMPLED", f"anchor_link_id={self.anchor_link_id}, tab={key}, raw_samples={len(timestamp_numeric)}, rendered_samples={rendered_count}")
        self.canvases[key].draw_idle()

    def _current_tab_key(self) -> str:
        return self.tab_keys[self.tabs.currentIndex()] if self.tab_keys else ""

    def hit_test_chart_point(self, chart_key: str, event) -> MeshSelectedPoint | None:
        payload = self.chart_payload or {}
        timestamps = payload.get("timestamp_numeric")
        if not isinstance(timestamps, np.ndarray) or len(timestamps) == 0 or event.xdata is None:
            return None
        axis = self.chart_artists.get(chart_key, {}).get("axis")
        if axis is None:
            return None
        switch_indices = payload.get("switch_indices") if isinstance(payload.get("switch_indices"), np.ndarray) else np.asarray([], dtype=np.int32)
        switch = self._nearest_switch_index(axis, timestamps, switch_indices, event)
        if switch >= 0:
            return self._selected_point_from_index(switch, chart_key)
        index = int(np.searchsorted(timestamps, float(event.xdata)))
        candidates = [candidate for candidate in (index - 1, index, index + 1) if 0 <= candidate < len(timestamps)]
        best_index = -1
        best_distance = 9999.0
        for candidate in candidates:
            pixel_x = axis.transData.transform((timestamps[candidate], 0))[0]
            x_distance = abs(float(pixel_x) - float(event.x or 0))
            if x_distance > 12:
                continue
            y_distance = self._nearest_series_pixel_distance(axis, chart_key, candidate, float(event.y or 0))
            distance = max(x_distance, y_distance)
            if distance < best_distance:
                best_distance = distance
                best_index = candidate
        return self._selected_point_from_index(best_index, chart_key) if best_index >= 0 else None

    def toggle_locked_point_from_event(self, chart_key: str, event) -> None:
        point = self.hit_test_chart_point(chart_key, event)
        if point is None:
            return
        if self.locked_selected_point and self.locked_selected_point.index == point.index:
            self.clear_locked_point()
            return
        self.locked_selected_point = MeshSelectedPoint(**{**point.__dict__, "locked": True})
        self._update_lock_status()
        self.center_on_index(point.index)
        self._mark_all_dirty_and_render_current()

    def show_chart_context_menu(self, chart_key: str, event) -> None:
        point = self.hit_test_chart_point(chart_key, event)
        if point is None:
            return
        menu = QMenu(self)
        lock_action = menu.addAction("解除锁定" if self.locked_selected_point else "锁定当前采样点")
        focus_action = menu.addAction("打开当前AP链路显示")
        jump_action = menu.addAction("跳转到链路明细")
        menu.addSeparator()
        copy_peer_action = menu.addAction("复制 PeerMac")
        copy_ap_action = menu.addAction("复制 AP名称")
        focus_action.setEnabled(bool(point.peer_mac))
        copy_peer_action.setEnabled(bool(point.peer_mac))
        copy_ap_action.setEnabled(bool(point.peer_ap_name))
        jump_action.setEnabled(bool(point.sample_time))
        selected = menu.exec(self.canvases[chart_key].mapToGlobal(QPoint(int(event.x or 0), int(event.y or 0))))
        if selected is lock_action:
            if self.locked_selected_point:
                self.clear_locked_point()
            else:
                self.locked_selected_point = MeshSelectedPoint(**{**point.__dict__, "locked": True})
                self._update_lock_status()
                self.center_on_index(point.index)
                self._mark_all_dirty_and_render_current()
        elif selected is focus_action:
            self.focus_peer(point)
        elif selected is jump_action:
            self.jump_to_detail_row(point)
        elif selected is copy_peer_action:
            QApplication.clipboard().setText(format_mac_h3c(point.peer_mac))
        elif selected is copy_ap_action:
            QApplication.clipboard().setText(point.peer_ap_name)

    def clear_locked_point(self) -> None:
        self.locked_selected_point = None
        self._update_lock_status()
        self._mark_all_dirty_and_render_current()

    def focus_peer(self, point: MeshSelectedPoint) -> None:
        self.focus_peer_mac = point.peer_mac
        self.focus_peer_ap_name = point.peer_ap_name
        self._update_focus_status()
        target = self.tab_keys.index("active_next_rssi") if "active_next_rssi" in self.tab_keys else self.tabs.currentIndex()
        self.tabs.setCurrentIndex(target)
        self.center_on_index(point.index)
        self._mark_all_dirty_and_render_current()

    def clear_focus_peer(self) -> None:
        self.focus_peer_mac = ""
        self.focus_peer_ap_name = ""
        self._update_focus_status()
        self._mark_all_dirty_and_render_current()

    def jump_to_detail_row(self, point: MeshSelectedPoint) -> None:
        parent = self.parent()
        handler = getattr(parent, "jump_to_mesh_link_detail", None)
        if callable(handler):
            handler(
                {
                    "session_id": point.session_id,
                    "sample_time": point.sample_time,
                    "peer_mac": point.peer_mac,
                    "radio": point.radio,
                    "state": point.state,
                }
            )

    def center_on_index(self, index: int) -> None:
        self.user_moved_window = False
        self.time_window_controller.center_on(index, self.visible_sample_count, "locked_point")

    def _selected_point_from_index(self, index: int, chart_key: str) -> MeshSelectedPoint:
        payload = self.chart_payload or {}
        labels = payload.get("timestamp_labels") or []
        session_ids = payload.get("peer_session_ids") or []
        active = chart_key.startswith("active_")
        peer_macs = payload.get("active_peer_macs" if active else "peer_macs") or []
        ap_names = payload.get("active_peer_ap_names" if active else "peer_ap_names") or []
        sites = payload.get("active_peer_sites" if active else "peer_sites") or []
        radios = payload.get("active_peer_radios" if active else "peer_radios") or []
        states = payload.get("peer_link_states") or []
        mesh_radio = str(self.radio) if self.radio is not None else ""
        return MeshSelectedPoint(
            index=index,
            session_id=str(session_ids[index]) if 0 <= index < len(session_ids) else self.current_session_id,
            sample_time=str(labels[index]) if 0 <= index < len(labels) else "",
            peer_mac=str(peer_macs[index]) if 0 <= index < len(peer_macs) else "",
            peer_ap_name=str(ap_names[index]) if 0 <= index < len(ap_names) else "",
            peer_site=str(sites[index]) if 0 <= index < len(sites) else "",
            radio=mesh_radio,
            peer_radio=str(radios[index]) if 0 <= index < len(radios) else "",
            state=str(states[index]) if 0 <= index < len(states) and states[index] else ("ACTIVE" if active else ""),
        )

    def _nearest_switch_index(self, axis, timestamps: np.ndarray, switch_indices: np.ndarray, event) -> int:
        if not self.show_switch_points_checkbox.isChecked() or len(switch_indices) == 0:
            return -1
        switch_times = timestamps[switch_indices]
        pos = int(np.searchsorted(switch_times, float(event.xdata)))
        candidates = [int(switch_indices[item]) for item in (pos - 1, pos, pos + 1) if 0 <= item < len(switch_indices)]
        if not candidates:
            return -1
        y_values = dict(zip(candidates, self._switch_marker_y_values(candidates), strict=False))
        best = -1
        best_distance = 9999.0
        for index in candidates:
            px, py = axis.transData.transform((timestamps[index], y_values[index]))
            distance = max(abs(float(px) - float(event.x or 0)), abs(float(py) - float(event.y or 0)))
            if distance <= 12 and distance < best_distance:
                best = index
                best_distance = distance
        return best

    def _nearest_series_pixel_distance(self, axis, chart_key: str, index: int, pixel_y: float) -> float:
        distances = []
        for field, _label, _style in self._series_specs(chart_key):
            values = self._series_values(field)
            if values is None or not (0 <= index < len(values)) or not np.isfinite(values[index]):
                continue
            py = axis.transData.transform((0, float(values[index])))[1]
            distances.append(abs(float(py) - pixel_y))
        return min(distances) if distances else 0.0

    def _update_lock_status(self) -> None:
        if self.locked_selected_point is None:
            self.lock_status_label.setText("")
            self.unlock_point_button.setEnabled(False)
            return
        point = self.locked_selected_point
        peer = format_mac_h3c(point.peer_mac) if point.peer_mac else "-"
        self.lock_status_label.setText(f"已锁定采样点: {point.sample_time} / {peer}")
        self.unlock_point_button.setEnabled(True)

    def _update_focus_status(self) -> None:
        if not self.focus_peer_mac:
            self.focus_status_label.setText("")
            self.clear_focus_button.setEnabled(False)
            return
        label = self.focus_peer_ap_name or format_mac_h3c(self.focus_peer_mac)
        self.focus_status_label.setText(f"当前聚焦AP: {label}")
        self.clear_focus_button.setEnabled(True)

    def _sync_active_controllers(self, active_key: str | None = None) -> None:
        key = active_key or self._current_tab_key()
        for tab_key, controller in self.hover_controllers.items():
            controller.set_enabled(tab_key == key and self.interaction_state == "IDLE")
        for tab_key, controller in self.interaction_controllers.items():
            controller.set_enabled(tab_key == key)

    def _series_specs(self, key: str) -> list[tuple[str, str, str]]:
        return {
            "signal": [("peer.local_rssi", self.i18n.t("mesh_analysis.mr_rssi"), "-"), ("peer.peer_rssi", self.i18n.t("mesh_analysis.peer_rssi_raw"), "-")],
            "rssi_noise": [("peer.local_rssi", self.i18n.t("mesh_analysis.local_rssi"), "-"), ("peer.peer_rssi", self.i18n.t("mesh_analysis.peer_rssi"), "-"), ("peer.local_noise", self.i18n.t("mesh_analysis.local_noise"), "--"), ("peer.peer_noise", self.i18n.t("mesh_analysis.peer_noise"), "--")],
            "load": [("peer.local_tx_busy", "L_TxBusy", "-"), ("peer.peer_tx_busy", "P_TxBusy", "-"), ("peer.local_rx_busy", "L_RxBusy", "--"), ("peer.peer_rx_busy", "P_RxBusy", "--")],
            "active_next_rssi": [("active.active_local_rssi", self.i18n.t("mesh_analysis.current_active_mr_rssi"), "-")],
            "active_channel_load": [
                ("active.active_local_tx_busy", self.i18n.t("mesh_analysis.mr_tx_busy"), "-"),
                ("active.active_local_rx_busy", self.i18n.t("mesh_analysis.mr_rx_busy"), "-."),
            ],
        }.get(key, [])

    def _series_values(self, field: str) -> np.ndarray | None:
        payload = self.chart_payload or {}
        group, name = field.split(".", 1)
        series = payload.get("peer_series" if group == "peer" else "active_series")
        if isinstance(series, dict) and isinstance(series.get(name), np.ndarray):
            values = series[name].astype(np.float32, copy=False)
            if group == "peer" and self.current_session_id:
                session_ids = self.chart_payload.get("peer_session_ids") if self.chart_payload else None
                if isinstance(session_ids, list) and len(session_ids) == len(values):
                    mask = np.asarray([session_id == self.current_session_id for session_id in session_ids], dtype=bool)
                    filtered = values.copy()
                    filtered[~mask] = np.nan
                    return filtered
            return values
        return None

    def _render_series_values(self, field: str, values: np.ndarray) -> np.ndarray:
        if not field.startswith("active."):
            return values
        payload = self.chart_payload or {}
        rendered = values.astype(np.float32, copy=True)
        if self.focus_peer_mac:
            payload = self.chart_payload or {}
            peers = payload.get("active_peer_macs" if field.startswith("active.") else "peer_macs")
            if isinstance(peers, list) and len(peers) == len(rendered):
                focus = "".join(character for character in self.focus_peer_mac.lower() if character in "0123456789abcdef")
                mask = np.asarray(["".join(character for character in str(peer).lower() if character in "0123456789abcdef") == focus for peer in peers], dtype=bool)
                rendered[~mask] = np.nan
        threshold = self._continuity_gap_seconds()
        labels = payload.get("timestamp_labels")
        if not isinstance(labels, list) or len(labels) != len(rendered):
            return rendered
        for index in range(1, len(rendered)):
            if np.isfinite(rendered[index - 1]) and np.isfinite(rendered[index]) and _seconds_between_labels(str(labels[index - 1]), str(labels[index])) > threshold:
                rendered[index] = np.nan
        return rendered

    def _continuity_gap_seconds(self) -> float:
        metadata = (self.chart_payload or {}).get("metadata")
        if not isinstance(metadata, dict):
            return 5.0
        value = metadata.get("continuity_gap_seconds")
        if value is None:
            value = max(float(metadata.get("estimated_interval_seconds") or 1.0) * 5, 5.0)
        try:
            return float(value)
        except (TypeError, ValueError):
            return 5.0

    def _bridge_gap_seconds(self) -> float:
        metadata = (self.chart_payload or {}).get("metadata")
        interval = 1.0
        if isinstance(metadata, dict):
            try:
                interval = float(metadata.get("estimated_interval_seconds") or 1.0)
            except (TypeError, ValueError):
                interval = 1.0
        return max(interval * 3, 3.0)

    def _draw_short_gap_bridges(self, artists: dict[str, object], field: str, values: np.ndarray, indices: np.ndarray, color: str) -> None:
        if not field.startswith("active.") or len(values) < 3:
            return
        payload = self.chart_payload or {}
        timestamp_numeric = payload.get("timestamp_numeric")
        labels = payload.get("timestamp_labels")
        if not isinstance(timestamp_numeric, np.ndarray) or not isinstance(labels, list) or len(labels) != len(values):
            return
        active_peers = payload.get("active_peer_macs")
        visible = {int(index) for index in indices}
        max_gap_seconds = self._bridge_gap_seconds()
        segments = []
        index = 1
        while index < len(values) - 1:
            if np.isfinite(values[index]):
                index += 1
                continue
            gap_start = index
            while index < len(values) - 1 and not np.isfinite(values[index]):
                index += 1
            gap_end = index - 1
            gap_size = gap_end - gap_start + 1
            previous_index = gap_start - 1
            next_index = gap_end + 1
            if gap_size > 2 or gap_start not in visible:
                continue
            if not (np.isfinite(values[previous_index]) and np.isfinite(values[next_index])):
                continue
            if isinstance(active_peers, list) and len(active_peers) == len(values):
                if not str(active_peers[previous_index] or "") or not str(active_peers[next_index] or ""):
                    continue
            if _seconds_between_labels(str(labels[previous_index]), str(labels[next_index])) > max_gap_seconds:
                continue
            segments.append([(timestamp_numeric[previous_index], float(values[previous_index])), (timestamp_numeric[next_index], float(values[next_index]))])
        if not segments:
            return
        collection = LineCollection(segments, colors=[color], linewidths=1.0, linestyles="--", alpha=0.65)
        artists["axis"].add_collection(collection)
        artists["collections"].append(collection)

    def _base_render_indices(self) -> np.ndarray:
        payload = self.chart_payload or {}
        total = len(payload.get("timestamp_numeric")) if isinstance(payload.get("timestamp_numeric"), np.ndarray) else 0
        important = payload.get("important_indices") if isinstance(payload.get("important_indices"), np.ndarray) else np.asarray([], dtype=np.int32)
        return render_indices(total, self.window_start_index, self.visible_sample_count, important, self._max_render_points(self.tab_keys[self.tabs.currentIndex()] if self.tab_keys else ""))

    def _apply_axes_window(self, axis, timestamp_numeric: np.ndarray, y_values: list[np.ndarray]) -> None:
        start = 0
        end = len(timestamp_numeric) - 1
        if self.visible_sample_count > 0:
            start = min(self.window_start_index, max(len(timestamp_numeric) - self.visible_sample_count, 0))
            end = min(start + self.visible_sample_count - 1, len(timestamp_numeric) - 1)
            self._set_axis_xlim(axis, float(timestamp_numeric[start]), float(timestamp_numeric[end]))
        else:
            self._set_axis_xlim(axis, float(timestamp_numeric[0]), float(timestamp_numeric[-1]))
        configure_mesh_time_axis(axis, self._timestamp_at(start), self._timestamp_at(end), self.i18n)
        if getattr(axis, "_mesh_chart_key", "") in {"load", "active_channel_load"}:
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

    def _set_axis_xlim(self, axis, left: float, right: float) -> None:
        if left == right:
            pad = 0.5 / 86400
            axis.set_xlim(left - pad, right + pad)
            return
        axis.set_xlim(left, right)

    def _clear_overlay_artists(self, artists: dict[str, object]) -> None:
        for item in artists.get("collections", []):
            item.remove()
        for item in artists.get("spans", []):
            item.remove()
        for item in artists.get("texts", []):
            item.remove()
        artists["collections"] = []
        artists["spans"] = []
        artists["texts"] = []

    def _draw_overlays(self, key: str, artists: dict[str, object], indices: np.ndarray) -> None:
        payload = self.chart_payload or {}
        timestamp_numeric = payload.get("timestamp_numeric")
        if not isinstance(timestamp_numeric, np.ndarray) or len(timestamp_numeric) == 0:
            return
        axis = artists["axis"]
        anchor_index = int(payload.get("metadata", {}).get("anchor_index", -1))
        if 0 <= anchor_index < len(timestamp_numeric):
            artists["anchor_line"].set_xdata([timestamp_numeric[anchor_index], timestamp_numeric[anchor_index]])
        ymin, ymax = axis.get_ylim()
        switch_indices = payload.get("switch_indices") if isinstance(payload.get("switch_indices"), np.ndarray) else np.asarray([], dtype=np.int32)
        if self.fast_pan_mode:
            return
        visible_switches: list[int] = []
        if len(indices) and len(switch_indices):
            visible_start = int(indices[0])
            visible_end = int(indices[-1])
            left = int(np.searchsorted(switch_indices, visible_start, side="left"))
            right = int(np.searchsorted(switch_indices, visible_end, side="right"))
            visible_index_set = set(int(value) for value in indices)
            visible_switches = [int(index) for index in switch_indices[left:right] if int(index) in visible_index_set]
        if visible_switches and self.show_switch_points_checkbox.isChecked():
            y_values = self._switch_marker_y_values(visible_switches)
            collection = axis.scatter(timestamp_numeric[visible_switches], y_values, s=34, marker="o", color="#dc2626", edgecolors="#ffffff", linewidths=0.7, alpha=0.92, zorder=5, label="链路切换")
            artists["collections"].append(collection)
        if self.locked_selected_point and 0 <= self.locked_selected_point.index < len(timestamp_numeric):
            locked_index = self.locked_selected_point.index
            artists["collections"].append(axis.vlines(timestamp_numeric[locked_index], ymin, ymax, color="#f59e0b", alpha=0.75, linewidth=1.4))
            locked_y = self._switch_marker_y_values([locked_index])[0]
            artists["collections"].append(axis.scatter([timestamp_numeric[locked_index]], [locked_y], s=48, marker="o", color="#f59e0b", edgecolors="#111827", linewidths=0.8, zorder=6))
        self._draw_station_labels(axis, artists, key, indices)
        if key == "signal":
            state = self._series_values("peer.state")
            if state is not None:
                for start, end in _active_intervals(indices, state):
                    artists["spans"].append(axis.axvspan(timestamp_numeric[start], timestamp_numeric[end], color="#16a34a", alpha=0.10))

    def _switch_marker_y_values(self, switch_indices: list[int]) -> list[float]:
        values = self._series_values("active.active_local_rssi")
        if values is None or len(values) == 0:
            return [0.0 for _index in switch_indices]
        finite_indices = np.flatnonzero(np.isfinite(values))
        if len(finite_indices) == 0:
            return [0.0 for _index in switch_indices]
        result: list[float] = []
        for index in switch_indices:
            if 0 <= index < len(values) and np.isfinite(values[index]):
                result.append(float(values[index]))
                continue
            position = int(np.searchsorted(finite_indices, index))
            candidates = []
            if position < len(finite_indices):
                candidates.append(int(finite_indices[position]))
            if position > 0:
                candidates.append(int(finite_indices[position - 1]))
            nearest = min(candidates, key=lambda item: abs(item - index)) if candidates else int(finite_indices[0])
            result.append(float(values[nearest]))
        return result

    def _draw_station_labels(self, axis, artists: dict[str, object], key: str, indices: np.ndarray) -> None:
        payload = self.chart_payload or {}
        timestamp_numeric = payload.get("timestamp_numeric")
        if not isinstance(timestamp_numeric, np.ndarray) or len(indices) == 0:
            return
        sites = payload.get("active_peer_sites" if key.startswith("active_") else "peer_sites")
        if not isinstance(sites, list) or len(sites) != len(timestamp_numeric):
            return
        candidates: list[tuple[int, str, bool]] = []
        previous_site = ""
        for raw_index in indices:
            index = int(raw_index)
            site = str(sites[index] or "").strip()
            if not site:
                continue
            important = self.locked_selected_point is not None and index == self.locked_selected_point.index
            if site != previous_site or important:
                candidates.append((index, site, important))
            previous_site = site
        if not candidates:
            return
        accepted: list[tuple[int, str, bool]] = []
        accepted_pixels: list[float] = []
        locked = [item for item in candidates if item[2]]
        ordered = locked + [item for item in candidates if not item[2]]
        for index, site, important in ordered:
            pixel_x = axis.transData.transform((timestamp_numeric[index], 0))[0]
            if not important and any(abs(pixel_x - used) < 120 for used in accepted_pixels):
                continue
            accepted.append((index, site, important))
            accepted_pixels.append(pixel_x)
        accepted.sort(key=lambda item: item[0])
        for index, site, important in accepted:
            label = _short_site_label(site)
            text = axis.text(
                timestamp_numeric[index],
                0.02 if not important else 0.08,
                label,
                transform=axis.get_xaxis_transform(),
                fontsize=9,
                color="#f59e0b" if important else "#64748b",
                ha="center",
                va="bottom",
                alpha=0.95 if important else 0.80,
                clip_on=True,
            )
            text.set_gid(site)
            artists["texts"].append(text)

    def _configure_scrollbar(self, center_anchor: bool = False) -> None:
        total = self._sample_count()
        if center_anchor:
            self.time_window_controller.set_total_count(total, self.visible_sample_count, source="payload")
            self.time_window_controller.center_on(self._anchor_index(), self.visible_sample_count, "center_anchor")
        else:
            self.time_window_controller.set_total_count(total, self.visible_sample_count, self.window_start_index, "payload")
        self._sync_time_controls()

    def _visible_center_sample_time(self) -> str:
        payload = self.chart_payload or {}
        labels = payload.get("timestamp_labels") or []
        if not labels:
            return ""
        center = self.window_start_index + max(self.effective_visible_sample_count(), 1) // 2
        center = max(0, min(int(center), len(labels) - 1))
        return str(labels[center])

    def _restore_visible_center(self, sample_time: str) -> None:
        if not sample_time:
            return
        payload = self.chart_payload or {}
        labels = [str(value) for value in payload.get("timestamp_labels") or []]
        if not labels:
            return
        index = _nearest_label_index(labels, sample_time)
        visible = self.visible_sample_count
        effective_visible = self.effective_visible_sample_count()
        start = self._center_start_index(index, effective_visible, len(labels))
        self.time_window_controller.set_time_window(start, visible, "payload")

    def _time_window_changed(self, start_index: int, visible_count: int, source: str) -> None:
        self.window_start_index = start_index
        self.visible_sample_count = visible_count
        if source not in {"payload", "center_anchor"}:
            self.user_moved_window = source != "preset"
        self._sync_time_controls()
        self.dirty_tabs.update(self.tab_keys)
        if source in {"scrollbar", "drag", "wheel"}:
            self.window_update_timer.start()
        else:
            self._render_current_tab()

    def _sync_time_controls(self) -> None:
        total = self._sample_count()
        visible = self.effective_visible_sample_count()
        maximum = max(total - visible, 0)
        with QSignalBlocker(self.time_scrollbar):
            self.time_scrollbar.setRange(0, maximum)
            self.time_scrollbar.setPageStep(max(visible, 1))
            self.time_scrollbar.setValue(self.window_start_index)
            self.time_scrollbar.setEnabled(maximum > 0)
        self._sync_visible_samples_combo()

    def _sync_visible_samples_combo(self) -> None:
        count = self.visible_sample_count
        preset_index = self.visible_samples_combo.findData(count)
        if count == 0:
            preset_index = self.visible_samples_combo.findData(0)
        with QSignalBlocker(self.visible_samples_combo):
            custom_role = Qt.ItemDataRole.UserRole.value + 1
            custom_indices = [index for index in range(self.visible_samples_combo.count()) if self.visible_samples_combo.itemData(index, custom_role) == "custom"]
            for index in reversed(custom_indices):
                self.visible_samples_combo.removeItem(index)
            if preset_index >= 0:
                self.visible_samples_combo.setCurrentIndex(preset_index)
                return
            self.visible_samples_combo.addItem(self.i18n.t("mesh_analysis.custom_visible_samples", count=count), count)
            custom_index = self.visible_samples_combo.count() - 1
            self.visible_samples_combo.setItemData(custom_index, "custom", custom_role)
            self.visible_samples_combo.setCurrentIndex(custom_index)

    def set_time_window(self, start_index: int, visible_count: int, source: str) -> None:
        self.time_window_controller.set_time_window(start_index, visible_count, source)

    def zoom_time_window_at(self, chart_key: str, xdata: float, step: float) -> None:
        payload = self.chart_payload or {}
        timestamps = payload.get("timestamp_numeric")
        if not isinstance(timestamps, np.ndarray):
            return
        index = self.time_window_controller.cursor_index_from_xdata(timestamps, xdata)
        if index < 0:
            return
        before = (self.window_start_index, self.visible_sample_count)
        self.time_window_controller.zoom_at_index(index, step, "wheel")
        app_logger.log_info("MESH_CHART_WHEEL_ZOOM", f"tab={chart_key}, step={step}, cursor_index={index}, before={before}, after={(self.window_start_index, self.visible_sample_count)}")

    def pan_time_window_to(self, start_index: int, source: str = "drag") -> None:
        self.time_window_controller.pan_to(start_index, source)

    def effective_visible_sample_count(self) -> int:
        return self.time_window_controller.effective_visible_count()

    def is_all_samples_visible(self) -> bool:
        return self.time_window_controller.is_all_visible()

    def begin_pan_interaction(self) -> None:
        self.interaction_state = "PANNING"
        self.fast_pan_mode = True
        self._pause_hover_controllers()

    def finish_pan_interaction_later(self) -> None:
        self.interaction_resume_timer.start()

    def begin_zoom_interaction(self) -> None:
        self.interaction_state = "ZOOMING"
        self.fast_pan_mode = False
        self._pause_hover_controllers()

    def finish_zoom_interaction_later(self) -> None:
        self.interaction_resume_timer.start()

    def _pause_hover_controllers(self) -> None:
        for controller in self.hover_controllers.values():
            controller.set_paused(True)

    def _resume_hover_after_interaction(self) -> None:
        self.interaction_state = "IDLE"
        self.fast_pan_mode = False
        for controller in self.hover_controllers.values():
            controller.set_paused(False)
        self._sync_active_controllers()
        self._render_current_tab()

    def _visible_samples_changed(self) -> None:
        old_center = self._anchor_index() if not self.user_moved_window else self.window_start_index + max(self.visible_sample_count, 1) // 2
        value = int(self.visible_samples_combo.currentData() or 0)
        total = self._sample_count()
        visible = value if value > 0 else 0
        effective_visible = visible or total
        start = self._center_start_index(old_center, effective_visible, total)
        self.time_window_controller.set_time_window(start, visible, "preset")

    def center_selected_sample(self) -> None:
        self.user_moved_window = False
        self.time_window_controller.center_on(self._anchor_index(), self.visible_sample_count, "center_anchor")

    def _scroll_changed(self, value: int) -> None:
        self.time_window_controller.set_time_window(value, self.visible_sample_count, "scrollbar")

    def keyPressEvent(self, event: QKeyEvent) -> None:
        step = 10 if event.modifiers() & Qt.ShiftModifier else 1
        key = event.key()
        if key == Qt.Key_Left:
            self.time_scrollbar.setValue(max(self.time_scrollbar.value() - step, self.time_scrollbar.minimum()))
        elif key == Qt.Key_Right:
            self.time_scrollbar.setValue(min(self.time_scrollbar.value() + step, self.time_scrollbar.maximum()))
        elif key == Qt.Key_PageUp:
            self.time_scrollbar.setValue(max(self.time_scrollbar.value() - self.time_scrollbar.pageStep(), self.time_scrollbar.minimum()))
        elif key == Qt.Key_PageDown:
            self.time_scrollbar.setValue(min(self.time_scrollbar.value() + self.time_scrollbar.pageStep(), self.time_scrollbar.maximum()))
        elif key == Qt.Key_Home:
            self.time_scrollbar.setValue(self.time_scrollbar.minimum())
        elif key == Qt.Key_End:
            self.time_scrollbar.setValue(self.time_scrollbar.maximum())
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        self._save_window_geometry()
        if self.worker is not None and self.worker.isRunning():
            self.worker.quit()
            self.worker.wait(1000)
        self.window_update_timer.stop()
        self.interaction_resume_timer.stop()
        for controller in self.interaction_controllers.values():
            controller.disconnect()
        for controller in self.hover_controllers.values():
            controller.disconnect()
        self.interaction_controllers.clear()
        self.hover_controllers.clear()
        for figure in self.figures.values():
            figure.clear()
        self.canvases.clear()
        super().closeEvent(event)

    def changeEvent(self, event) -> None:
        if event.type() == event.Type.WindowStateChange and self.isMinimized():
            for controller in self.hover_controllers.values():
                controller.hide_hover()
        super().changeEvent(event)

    def _sample_count(self) -> int:
        payload = self.chart_payload or {}
        values = payload.get("timestamp_numeric")
        return len(values) if isinstance(values, np.ndarray) else 0

    def _anchor_index(self) -> int:
        payload = self.chart_payload or {}
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        return int(metadata.get("anchor_index", 0) or 0)

    def _center_start_index(self, index: int, visible: int, total: int) -> int:
        return max(min(index - visible // 2, max(total - visible, 0)), 0)

    def _max_render_points(self, key: str) -> int:
        canvas = self.canvases.get(key)
        width = canvas.width() if canvas is not None else 1000
        return max(width * 2, 1000)

    def _last_render_count(self, key: str) -> int:
        artists = self.chart_artists.get(key) or {}
        return int(artists.get("last_count") or 0)

    def _timestamp_at(self, index: int) -> datetime | None:
        payload = self.chart_payload or {}
        timestamps = payload.get("timestamps")
        if isinstance(timestamps, list) and 0 <= index < len(timestamps) and isinstance(timestamps[index], datetime):
            return timestamps[index]
        labels = payload.get("timestamp_labels") or []
        if 0 <= index < len(labels):
            try:
                return datetime.fromisoformat(str(labels[index]))
            except ValueError:
                return None
        return None

    def _save_window_geometry(self) -> None:
        self.settings.set_value("mesh_peer_detail/geometry", bytes(self.saveGeometry().toBase64()).decode("ascii"))
        self.settings.set_value("mesh_peer_detail/maximized", self.isMaximized())

    def _restore_window_geometry(self) -> None:
        geometry = self.settings.get_value("mesh_peer_detail/geometry", "")
        if isinstance(geometry, str) and geometry:
            self.restoreGeometry(QByteArray.fromBase64(geometry.encode("ascii")))
            if not _is_on_available_screen(self.frameGeometry()):
                self.move((self.parent().geometry().center() if self.parent() else QGuiApplication.primaryScreen().availableGeometry().center()) - self.rect().center())
        if bool(self.settings.get_value("mesh_peer_detail/maximized", False)):
            self.showMaximized()


def _active_intervals(indices: np.ndarray, state: np.ndarray) -> list[tuple[int, int]]:
    intervals: list[tuple[int, int]] = []
    current_start: int | None = None
    previous_index: int | None = None
    for index in [int(value) for value in indices if 0 <= int(value) < len(state)]:
        if state[index] == 1 and current_start is None:
            current_start = index
        if state[index] != 1 and current_start is not None and previous_index is not None:
            intervals.append((current_start, previous_index))
            current_start = None
        previous_index = index
    if current_start is not None and previous_index is not None:
        intervals.append((current_start, previous_index))
    return intervals


def _short_time(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%H:%M:%S")
    except ValueError:
        return value


def _short_site_label(value: str, max_chars: int = 10) -> str:
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max(max_chars - 1, 1)] + "…"


def _nearest_label_index(labels: list[str], sample_time: str) -> int:
    if not labels:
        return 0
    try:
        target = datetime.fromisoformat(sample_time)
    except (TypeError, ValueError):
        return min(range(len(labels)), key=lambda index: abs(index - len(labels) // 2))
    best_index = 0
    best_delta = float("inf")
    for index, label in enumerate(labels):
        try:
            delta = abs((datetime.fromisoformat(label) - target).total_seconds())
        except (TypeError, ValueError):
            continue
        if delta < best_delta:
            best_delta = delta
            best_index = index
    return best_index


def _seconds_between_labels(previous: str, current: str) -> float:
    try:
        return (datetime.fromisoformat(current) - datetime.fromisoformat(previous)).total_seconds()
    except (TypeError, ValueError):
        return 0.0


def _is_on_available_screen(rect) -> bool:
    return any(screen.availableGeometry().intersects(rect) for screen in QGuiApplication.screens())
