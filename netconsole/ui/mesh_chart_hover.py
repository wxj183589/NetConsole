from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QObject, QPoint, QTimer

from netconsole.core import app_logger
from netconsole.core.i18n import I18n
from netconsole.ui.mesh_hover_content_cache import HoverContent, HoverContentCache
from netconsole.models.mesh_log_models import format_mac_h3c
from netconsole.ui.mesh_chart_hover_popup import MeshChartHoverPopup
from netconsole.ui.mesh_chart_time_axis import full_sample_time_label
from netconsole.ui.mesh_series_metadata import MESH_SERIES_METADATA, format_mesh_value


class MeshChartHoverController(QObject):
    def __init__(self, canvas, axis, i18n: I18n, parent=None) -> None:
        super().__init__(parent)
        self.canvas = canvas
        self.axis = axis
        self.i18n = i18n
        self.payload: dict[str, object] = {}
        self.chart_key = ""
        self.series_fields: list[str] = []
        self.latest_event = None
        self.enabled = True
        self.paused = False
        self.current_sample_index = -1
        self.current_cache_key: tuple[str, int, str, str] | None = None
        self.current_html = ""
        self.session_filter = ""
        self.content_cache = HoverContentCache()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self._process_latest_event)
        self.vline = axis.axvline(0, color="#0f766e", linewidth=1.0, alpha=0.65, visible=False)
        self.popup = MeshChartHoverPopup()
        self.markers = []
        for _index in range(8):
            (marker,) = axis.plot([], [], "o", markersize=4, color="#0f766e", visible=False, zorder=6)
            self.markers.append(marker)
        self.motion_cid = canvas.mpl_connect("motion_notify_event", self.on_mouse_move)
        self.leave_cid = canvas.mpl_connect("axes_leave_event", self.hide_hover)

    def set_context(self, payload: dict[str, object], chart_key: str, series_fields: list[str], session_filter: str = "") -> None:
        if payload is not self.payload or chart_key != self.chart_key or session_filter != self.session_filter:
            self.content_cache.clear()
            self.current_cache_key = None
        self.payload = payload
        self.chart_key = chart_key
        self.series_fields = series_fields
        self.session_filter = session_filter
        self.hide_hover()

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        if not enabled:
            self.hide_hover()

    def set_paused(self, paused: bool) -> None:
        self.paused = paused
        if paused:
            self.hide_hover()

    def clear_cache(self) -> None:
        self.content_cache.clear()
        self.current_cache_key = None
        self.current_html = ""
        self.current_sample_index = -1
        self.popup.clear_cached_text()

    def disconnect(self) -> None:
        self.canvas.mpl_disconnect(self.motion_cid)
        self.canvas.mpl_disconnect(self.leave_cid)
        self.timer.stop()
        self.content_cache.clear()
        self.popup.hide()
        self.popup.deleteLater()

    def on_mouse_move(self, event) -> None:
        if not self.enabled or self.paused:
            return
        if event.inaxes is not self.axis:
            self.hide_hover()
            return
        self.latest_event = event
        self.timer.start()

    def hide_hover(self, *_args) -> None:
        self.timer.stop()
        self.latest_event = None
        self.current_sample_index = -1
        self.vline.set_visible(False)
        self.popup.hide()
        for marker in self.markers:
            marker.set_visible(False)
        self.canvas.draw_idle()

    def nearest_index(self, xdata: float, pixel_x: float | None = None) -> int:
        timestamps = self.payload.get("timestamp_numeric")
        if not isinstance(timestamps, np.ndarray) or len(timestamps) == 0 or not math.isfinite(float(xdata)):
            return -1
        left, right = self.axis.get_xlim()
        lower = min(left, right)
        upper = max(left, right)
        visible_left = int(np.searchsorted(timestamps, lower, side="left"))
        visible_right = int(np.searchsorted(timestamps, upper, side="right"))
        if visible_left >= visible_right:
            return -1
        index = int(np.searchsorted(timestamps, xdata))
        left_index = index - 1 if index > 0 else -1
        right_index = index if index < len(timestamps) else -1
        if left_index < 0 and right_index < 0:
            return -1
        if left_index < 0:
            nearest = right_index
        elif right_index < 0:
            nearest = left_index
        else:
            nearest = left_index if abs(float(timestamps[left_index]) - float(xdata)) <= abs(float(timestamps[right_index]) - float(xdata)) else right_index
        if not (lower <= timestamps[nearest] <= upper):
            return -1
        if pixel_x is not None:
            sample_pixel = self.axis.transData.transform((timestamps[nearest], 0))[0]
            if abs(sample_pixel - pixel_x) > 16:
                return -1
        return nearest

    def tooltip_text(self, index: int) -> str:
        labels = self.payload.get("timestamp_labels") or []
        sample_time = labels[index] if 0 <= index < len(labels) else ""
        lines = [
            f"{self.i18n.t('mesh_analysis.hover_sample_time')}:",
            full_sample_time_label(sample_time),
            "",
        ]
        lines.extend(self._main_link_lines(index))
        metric_lines: list[str] = []
        for field in self._metric_fields_for_tooltip():
            metric_lines.extend(self._metric_lines(field, index))
        if metric_lines:
            lines.append("")
            lines.extend(metric_lines)
        lines.append("")
        lines.extend(self._standby_link_lines(index))
        event_lines = self._event_lines(index)
        if event_lines:
            lines.append("")
            lines.extend(event_lines)
        return "\n".join(lines)
        peer = self._peer_for_index(index)
        peer_ap_name = self._payload_value_for_index("active_peer_ap_names" if self.chart_key.startswith("active_") else "peer_ap_names", index)
        peer_site = self._payload_value_for_index("active_peer_sites" if self.chart_key.startswith("active_") else "peer_sites", index)
        peer_radio = self._payload_value_for_index("active_peer_radios" if self.chart_key.startswith("active_") else "peer_radios", index)
        state = self._state_for_index(index)
        lines = [
            f"{self.i18n.t('mesh_analysis.sample_time')}:",
            full_sample_time_label(sample_time),
            "当前PEER AP名称:",
            peer_ap_name or "-",
            "归属站点:",
            peer_site or "-",
            f"PeerMac: {format_mac_h3c(peer) if peer else '-'}",
            f"Radio: {peer_radio or '-'}",
            f"{self.i18n.t('mesh_analysis.state')}: {self._state_text(state)}",
            "",
        ]
        if self.chart_key == "active_next_rssi":
            lines.extend(self._current_active_rssi_lines(index))
        elif self.chart_key == "active_channel_load":
            lines.extend(self._active_load_lines(index))
        else:
            for field in self.series_fields:
                lines.extend(self._metric_lines(field, index))
        lines.append("")
        lines.extend(self._standby_link_lines(index))
        event_lines = self._event_lines(index)
        if event_lines:
            lines.append("")
            lines.extend(event_lines)
        return "\n".join(lines)

    def _process_latest_event(self) -> None:
        if not self.enabled or self.paused:
            return
        event = self.latest_event
        if event is None or event.xdata is None:
            self.hide_hover()
            return
        index = self.nearest_index(float(event.xdata), event.x)
        if index < 0:
            self.hide_hover()
            return
        timestamps = self.payload.get("timestamp_numeric")
        if not isinstance(timestamps, np.ndarray):
            return
        x = float(timestamps[index])
        global_pos = self.canvas.mapToGlobal(QPoint(int(event.x), int(event.y)))
        if index == self.current_sample_index and self.popup.isVisible():
            self.popup.show_at(global_pos, resize=False)
            return
        app_logger.log_info("MESH_HOVER_INDEX_CHANGED", f"tab={self.chart_key}, index={index}")
        self.vline.set_xdata([x, x])
        self.vline.set_visible(True)
        text = self._cached_tooltip_text(index)
        resized = self.popup.set_tooltip_text(text)
        self.popup.show_at(global_pos, resize=False if not resized else True)
        self._update_markers(index, x)
        self.current_sample_index = index
        self.canvas.draw_idle()

    def _cached_tooltip_text(self, index: int) -> str:
        locale = getattr(self.i18n, "locale", "")
        key = (self.chart_key, index, str(locale), self.session_filter)
        cached = self.content_cache.get(key)
        if cached is not None:
            app_logger.log_info("MESH_HOVER_CONTENT_CACHE_HIT", f"tab={self.chart_key}, index={index}")
            return cached.text
        text = self.tooltip_text(index)
        self.content_cache.put(key, HoverContent(text))
        app_logger.log_info("MESH_HOVER_CONTENT_CACHE_MISS", f"tab={self.chart_key}, index={index}")
        return text

    def _update_markers(self, index: int, x: float) -> None:
        used = 0
        for field in self.series_fields:
            values = self._series_values(field)
            if values is None or not (0 <= index < len(values)):
                continue
            value = values[index]
            if not np.isfinite(value):
                continue
            if used >= len(self.markers):
                break
            self.markers[used].set_data([x], [float(value)])
            self.markers[used].set_visible(True)
            used += 1
        for marker in self.markers[used:]:
            marker.set_visible(False)

    def _metric_lines(self, field: str, index: int) -> list[str]:
        metadata = MESH_SERIES_METADATA.get(field, {})
        values = self._series_values(field)
        value = values[index] if values is not None and 0 <= index < len(values) else np.nan
        label = self.i18n.t(str(metadata.get("label_key") or field))
        if np.isfinite(value):
            formatted = format_mesh_value(value, metadata)
        else:
            formatted = self.i18n.t("mesh_analysis.unavailable_counter_delta") if field.startswith("peer.delta_") else "-"
        return [f"{label}: {formatted}"]

    def _metric_fields_for_tooltip(self) -> list[str]:
        hidden = {"peer.local_rssi", "peer.peer_rssi", "active.active_local_rssi"}
        return [field for field in self.series_fields if field not in hidden]

    def _main_link_lines(self, index: int) -> list[str]:
        peer = self._peer_for_index(index)
        mr_rssi, ap_rssi = self._main_rssi_pair(index)
        return [
            f"{self.i18n.t('mesh_analysis.hover_active_link')}:",
            f"{self._main_peer_name(index, peer)} / {self._main_peer_site(index)}",
            f"PeerMac: {format_mac_h3c(peer) if peer else '-'}",
            f"{self.i18n.t('mesh_analysis.hover_mr_ap_rssi')}: {mr_rssi}/{ap_rssi}",
            f"{self.i18n.t('mesh_analysis.state')}: {self._state_text(self._state_for_index(index))}",
        ]

    def _main_peer_name(self, index: int, peer: str) -> str:
        key = "active_peer_ap_names" if self.chart_key.startswith("active_") else "peer_ap_names"
        value = self._payload_value_for_index(key, index)
        return value or (format_mac_h3c(peer) if peer else "-")

    def _main_peer_site(self, index: int) -> str:
        key = "active_peer_sites" if self.chart_key.startswith("active_") else "peer_sites"
        return self._payload_value_for_index(key, index) or "-"

    def _main_rssi_pair(self, index: int) -> tuple[str, str]:
        if self.chart_key.startswith("active_"):
            return self._format_raw_value(self._series_value("active.active_local_rssi", index)), self._active_peer_rssi(index)
        return self._format_raw_value(self._series_value("peer.local_rssi", index)), self._format_raw_value(self._series_value("peer.peer_rssi", index))

    def _series_value(self, field: str, index: int) -> object:
        values = self._series_values(field)
        if values is not None and 0 <= index < len(values):
            return values[index]
        return np.nan

    def _current_active_rssi_lines(self, index: int) -> list[str]:
        active_peers = self.payload.get("active_peer_macs") or []
        if not (0 <= index < len(active_peers)) or not active_peers[index]:
            return [self.i18n.t("mesh_analysis.no_unique_active")]
        peer_name = self._payload_value_for_index("active_peer_ap_names", index)
        peer_site = self._payload_value_for_index("active_peer_sites", index)
        peer_rssi = self._active_peer_rssi(index)
        lines = ["当前PEER AP名称" + f": {peer_name or '-'}", f"归属站点: {peer_site or '-'}"]
        for field in ("active.active_local_rssi",):
            lines.extend(self._metric_lines(field, index)[:1])
        lines.append(f"AP侧RSSI: {peer_rssi}")
        return lines

    def _active_load_lines(self, index: int) -> list[str]:
        active_peers = self.payload.get("active_peer_macs") or []
        if not (0 <= index < len(active_peers)) or not active_peers[index]:
            return [self.i18n.t("mesh_analysis.no_unique_active")]
        peer_name = self._payload_value_for_index("active_peer_ap_names", index)
        lines = ["当前PEER AP名称" + f": {peer_name or '-'}"]
        for field in ("active.active_local_tx_busy", "active.active_local_rx_busy"):
            lines.extend(self._metric_lines(field, index)[:1])
        return lines

    def _standby_link_lines(self, index: int) -> list[str]:
        rows_by_index = self.payload.get("standby_links_by_index")
        rows = rows_by_index[index] if isinstance(rows_by_index, list) and 0 <= index < len(rows_by_index) else []
        title = self.i18n.t("mesh_analysis.hover_standby_links")
        if not rows:
            return [self.i18n.t("mesh_analysis.hover_no_standby_links")]
        lines = [f"{title}:"]
        for number, row in enumerate(rows[:3], start=1):
            if not isinstance(row, dict):
                continue
            peer_mac = str(row.get("peer_mac") or "")
            ap_name = str(row.get("ap_name") or "").strip() or (format_mac_h3c(peer_mac) if peer_mac else "-")
            site = str(row.get("site") or "").strip() or "-"
            mr_rssi = self._format_raw_value(row.get("mr_rssi"))
            ap_rssi = self._format_raw_value(row.get("ap_rssi"))
            lines.append(f"{number}. {ap_name} / {site} / {self.i18n.t('mesh_analysis.hover_mr_ap_rssi')} {mr_rssi}/{ap_rssi}")
        return lines
        title = self.i18n.t("mesh_analysis.standby_links")
        if not rows:
            return [f"{title}: {self.i18n.t('mesh_analysis.no_standby_links')}"]
        lines = [f"{title}:"]
        for number, row in enumerate(rows[:3], start=1):
            if not isinstance(row, dict):
                continue
            ap_name = str(row.get("ap_name") or "-")
            site = str(row.get("site") or "-")
            mr_rssi = self._format_raw_value(row.get("mr_rssi"))
            ap_rssi = self._format_raw_value(row.get("ap_rssi"))
            peer_radio = str(row.get("peer_radio") or "-")
            lines.append(f"{number}. {ap_name} / {site} / MR侧RSSI {mr_rssi} / AP侧RSSI {ap_rssi} / Peer Radio {peer_radio}")
        return lines

    def _active_peer_rssi(self, index: int) -> str:
        values = self.payload.get("active_peer_rssi")
        if isinstance(values, np.ndarray) and 0 <= index < len(values):
            return self._format_raw_value(values[index])
        return "-"

    def _format_raw_value(self, value: object) -> str:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return "-"
        return f"{number:.0f}" if np.isfinite(number) else "-"

    def _event_lines(self, index: int) -> list[str]:
        events_by_index = self.payload.get("events_by_index")
        if not isinstance(events_by_index, dict):
            return []
        lines: list[str] = []
        for event in events_by_index.get(index, []):
            event_type = event.get("event_type")
            if event_type == "ACTIVE_SWITCH":
                lines.extend(
                    [
                        "事件:",
                        self.i18n.t("mesh_analysis.active_switch"),
                        "切换时间:",
                        str(event.get("event_time") or event.get("current_sample_time") or "-"),
                        f"{event.get('from_peer_mac') or '-'} -> {event.get('to_peer_mac') or '-'}",
                        f"{self.i18n.t('mesh_analysis.observed_window')}: {event.get('observed_window_ms') or '-'} ms",
                    ]
                )
            elif event_type == "NO_ACTIVE":
                lines.append(self.i18n.t("mesh_analysis.no_unique_active"))
            elif event_type == "MULTI_ACTIVE":
                lines.append(self.i18n.t("mesh_analysis.multiple_active_at_sample"))
        return lines

    def _series_values(self, field: str) -> np.ndarray | None:
        group, name = field.split(".", 1)
        series = self.payload.get("peer_series" if group == "peer" else "active_series")
        if isinstance(series, dict) and isinstance(series.get(name), np.ndarray):
            return series[name]
        return None

    def _peer_for_index(self, index: int) -> str:
        if self.chart_key.startswith("active_"):
            peers = self.payload.get("active_peer_macs") or []
        else:
            peers = self.payload.get("peer_macs") or []
        return str(peers[index]) if 0 <= index < len(peers) else ""

    def _payload_value_for_index(self, key: str, index: int) -> str:
        values = self.payload.get(key) or []
        return str(values[index]) if 0 <= index < len(values) and values[index] else ""

    def _state_for_index(self, index: int) -> str:
        states = self.payload.get("peer_link_states") or []
        if 0 <= index < len(states) and states[index]:
            return str(states[index])
        active_peers = self.payload.get("active_peer_macs") or []
        return "ACTIVE" if 0 <= index < len(active_peers) and active_peers[index] else ""

    def _state_text(self, state: str) -> str:
        if state == "ACTIVE":
            return self.i18n.t("mesh_analysis.hover_status_active")
        if state == "STANDBY":
            return self.i18n.t("mesh_analysis.hover_status_standby")
        return self.i18n.t("mesh_analysis.no_unique_active") if not state else state
