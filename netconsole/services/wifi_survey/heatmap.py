from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap


@dataclass(frozen=True)
class HeatmapSample:
    point_id: int
    x_px: float
    y_px: float
    rssi_dbm: float


def rssi_to_color(rssi_dbm: float | None, alpha: int = 130) -> QColor:
    if rssi_dbm is None:
        return QColor(140, 145, 152, alpha)
    if rssi_dbm >= -55:
        return QColor(10, 120, 60, alpha)
    if rssi_dbm >= -67:
        return QColor(58, 180, 90, alpha)
    if rssi_dbm >= -72:
        return QColor(180, 210, 70, alpha)
    if rssi_dbm >= -78:
        return QColor(235, 165, 45, alpha)
    if rssi_dbm >= -80:
        return QColor(220, 90, 55, alpha)
    return QColor(120, 45, 45, alpha)


def generate_idw_heatmap(width: int, height: int, samples: list[tuple[float, float, float]], step: int = 10) -> QPixmap | None:
    if width <= 0 or height <= 0 or len(samples) < 3:
        return None
    step = max(6, min(20, int(step)))
    low_width = max(1, math.ceil(width / step))
    low_height = max(1, math.ceil(height / step))
    image = QImage(low_width, low_height, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    for y in range(low_height):
        for x in range(low_width):
            px = x * step
            py = y * step
            rssi = _idw_value(px, py, samples)
            image.setPixelColor(x, y, rssi_to_color(rssi, 120))
    scaled = image.scaled(width, height, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    return QPixmap.fromImage(scaled)


def render_heatmap_png(base: QPixmap, overlay: QPixmap | None) -> QPixmap:
    result = QPixmap(base.size())
    result.fill(Qt.transparent)
    painter = QPainter(result)
    painter.drawPixmap(0, 0, base)
    if overlay is not None:
        painter.drawPixmap(0, 0, overlay)
    painter.end()
    return result


def build_heatmap_samples(
    points: list[dict[str, object]],
    observations: list[dict[str, object]],
    mode: str,
    selected_ssids: set[str] | None = None,
    selected_bssids: set[str] | None = None,
) -> list[HeatmapSample]:
    selected_ssids = selected_ssids or set()
    selected_bssids = {value.casefold() for value in (selected_bssids or set())}
    point_by_id = {int(point["id"]): point for point in points}
    best_by_point: dict[int, float] = {}
    for observation in observations:
        point_id_value = observation.get("point_id")
        if point_id_value is None:
            continue
        point_id = int(point_id_value)
        if point_id not in point_by_id or not _observation_matches_mode(observation, mode, selected_ssids, selected_bssids):
            continue
        rssi = clean_rssi(observation.get("rssi_dbm"), observation.get("signal_quality"))
        if rssi is None:
            continue
        current = best_by_point.get(point_id)
        if current is None or rssi > current:
            best_by_point[point_id] = rssi
    samples: list[HeatmapSample] = []
    for point_id, rssi in best_by_point.items():
        point = point_by_id[point_id]
        samples.append(HeatmapSample(point_id, float(point["x_px"]), float(point["y_px"]), rssi))
    return sorted(samples, key=lambda sample: sample.point_id)


def clean_rssi(value: object, signal_quality: object = None) -> float | None:
    rssi = _to_float(value)
    if rssi is None:
        quality = _to_float(signal_quality)
        if quality is not None:
            rssi = quality / 2 - 100
    if rssi is None or math.isnan(rssi) or not -120 <= rssi <= 0:
        return None
    return rssi


def _observation_matches_mode(
    observation: dict[str, object],
    mode: str,
    selected_ssids: set[str],
    selected_bssids: set[str],
) -> bool:
    if mode == "strongest":
        return True
    if mode == "ssid":
        return str(observation.get("ssid") or "<hidden>") in selected_ssids
    if mode == "bssid":
        return str(observation.get("bssid") or "").casefold() in selected_bssids
    if mode == "multi":
        ssid = str(observation.get("ssid") or "<hidden>")
        bssid = str(observation.get("bssid") or "").casefold()
        return ssid in selected_ssids or bssid in selected_bssids
    return False


def _to_float(value: object) -> float | None:
    if value in (None, "", "-"):
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _idw_value(x: float, y: float, samples: list[tuple[float, float, float]]) -> float:
    weighted_sum = 0.0
    weight_total = 0.0
    for sx, sy, rssi in samples:
        distance = math.hypot(x - sx, y - sy)
        if distance < 1:
            return rssi
        weight = 1.0 / (distance * distance)
        weighted_sum += rssi * weight
        weight_total += weight
    return weighted_sum / weight_total if weight_total else -90.0
