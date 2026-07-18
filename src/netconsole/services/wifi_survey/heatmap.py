from __future__ import annotations

import math
from dataclasses import dataclass

from PIL import Image


RgbaColor = tuple[int, int, int, int]


@dataclass(frozen=True)
class HeatmapSample:
    point_id: int
    x_px: float
    y_px: float
    rssi_dbm: float


def rssi_to_color(rssi_dbm: float | None, alpha: int = 130) -> RgbaColor:
    if rssi_dbm is None:
        return 140, 145, 152, alpha
    if rssi_dbm >= -55:
        return 10, 120, 60, alpha
    if rssi_dbm >= -67:
        return 58, 180, 90, alpha
    if rssi_dbm >= -72:
        return 180, 210, 70, alpha
    if rssi_dbm >= -78:
        return 235, 165, 45, alpha
    if rssi_dbm >= -80:
        return 220, 90, 55, alpha
    return 120, 45, 45, alpha


def generate_idw_heatmap_image(
    width: int,
    height: int,
    samples: list[tuple[float, float, float]],
    step: int = 10,
) -> Image.Image | None:
    if width <= 0 or height <= 0 or len(samples) < 3:
        return None
    step = max(6, min(20, int(step)))
    low_width = max(1, math.ceil(width / step))
    low_height = max(1, math.ceil(height / step))
    image = Image.new("RGBA", (low_width, low_height), (0, 0, 0, 0))
    pixels = image.load()
    for y in range(low_height):
        for x in range(low_width):
            px = x * step
            py = y * step
            rssi = _idw_value(px, py, samples)
            pixels[x, y] = rssi_to_color(rssi, 120)
    return image.resize((width, height), Image.Resampling.BICUBIC)


def generate_idw_heatmap(
    width: int,
    height: int,
    samples: list[tuple[float, float, float]],
    step: int = 10,
) -> Image.Image | None:
    return generate_idw_heatmap_image(width, height, samples, step)


def render_heatmap_png(base: Image.Image, overlay: Image.Image | None) -> Image.Image:
    result = base.convert("RGBA")
    if overlay is None:
        return result
    if overlay.size != result.size:
        overlay = overlay.resize(result.size, Image.Resampling.BICUBIC)
    return Image.alpha_composite(result, overlay.convert("RGBA"))


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
