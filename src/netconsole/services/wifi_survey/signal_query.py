from __future__ import annotations

import math
from dataclasses import dataclass

from netconsole.services.wifi_survey.heatmap import clean_rssi


@dataclass(frozen=True)
class SignalAtPoint:
    ssid: str
    bssid: str
    band: str
    channel: int | None
    rssi_dbm: float
    data_type: str
    point_index: int | None = None


def query_signal_at_position(
    x_px: float,
    y_px: float,
    points: list[dict[str, object]],
    observations: list[dict[str, object]],
    selected_ssids: set[str] | None = None,
    selected_bssids: set[str] | None = None,
    measured_radius_px: float = 15.0,
) -> list[SignalAtPoint]:
    selected_ssids = selected_ssids or set()
    selected_bssids = {value.casefold() for value in (selected_bssids or set())}
    point_by_id = {int(point["id"]): point for point in points}
    filtered = [
        observation
        for observation in observations
        if observation.get("point_id") is not None
        and int(observation["point_id"]) in point_by_id
        and _matches_filter(observation, selected_ssids, selected_bssids)
        and clean_rssi(observation.get("rssi_dbm"), observation.get("signal_quality")) is not None
    ]
    nearest_point_id = _nearest_point_id(x_px, y_px, points, measured_radius_px)
    if nearest_point_id is not None:
        measured = [
            _signal_from_observation(observation, "实测", point_by_id[nearest_point_id])
            for observation in filtered
            if int(observation["point_id"]) == nearest_point_id
        ]
        return sorted(measured, key=lambda signal: signal.rssi_dbm, reverse=True)[:20]
    estimated = _estimated_signals(x_px, y_px, filtered, point_by_id)
    return sorted(estimated, key=lambda signal: signal.rssi_dbm, reverse=True)[:20]


def nearest_point_for_position(
    x_px: float,
    y_px: float,
    points: list[dict[str, object]],
    measured_radius_px: float = 15.0,
) -> dict[str, object] | None:
    point_id = _nearest_point_id(x_px, y_px, points, measured_radius_px)
    if point_id is None:
        return None
    for point in points:
        if int(point["id"]) == point_id:
            return point
    return None


def _estimated_signals(
    x_px: float,
    y_px: float,
    observations: list[dict[str, object]],
    point_by_id: dict[int, dict[str, object]],
) -> list[SignalAtPoint]:
    by_bssid: dict[str, list[dict[str, object]]] = {}
    for observation in observations:
        bssid = str(observation.get("bssid") or "").casefold()
        if bssid:
            by_bssid.setdefault(bssid, []).append(observation)
    signals: list[SignalAtPoint] = []
    for rows in by_bssid.values():
        samples = _best_samples_by_point(rows, point_by_id)
        if len(samples) < 2:
            continue
        rssi = _idw_value(x_px, y_px, samples)
        metadata = max(rows, key=lambda row: clean_rssi(row.get("rssi_dbm"), row.get("signal_quality")) or -999)
        signals.append(
            SignalAtPoint(
                ssid=str(metadata.get("ssid") or "<hidden>"),
                bssid=str(metadata.get("bssid") or ""),
                band=str(metadata.get("band") or ""),
                channel=_optional_int(metadata.get("channel")),
                rssi_dbm=round(rssi, 1),
                data_type="估算",
            )
        )
    return signals


def _best_samples_by_point(
    observations: list[dict[str, object]],
    point_by_id: dict[int, dict[str, object]],
) -> list[tuple[float, float, float]]:
    best: dict[int, float] = {}
    for observation in observations:
        point_id = int(observation["point_id"])
        rssi = clean_rssi(observation.get("rssi_dbm"), observation.get("signal_quality"))
        if rssi is None:
            continue
        current = best.get(point_id)
        if current is None or rssi > current:
            best[point_id] = rssi
    samples = []
    for point_id, rssi in best.items():
        point = point_by_id[point_id]
        samples.append((float(point["x_px"]), float(point["y_px"]), rssi))
    return samples


def _nearest_point_id(x_px: float, y_px: float, points: list[dict[str, object]], radius: float) -> int | None:
    nearest_id = None
    nearest_distance = float("inf")
    for point in points:
        distance = math.hypot(x_px - float(point["x_px"]), y_px - float(point["y_px"]))
        if distance <= radius and distance < nearest_distance:
            nearest_distance = distance
            nearest_id = int(point["id"])
    return nearest_id


def _signal_from_observation(observation: dict[str, object], data_type: str, point: dict[str, object]) -> SignalAtPoint:
    rssi = clean_rssi(observation.get("rssi_dbm"), observation.get("signal_quality"))
    return SignalAtPoint(
        ssid=str(observation.get("ssid") or "<hidden>"),
        bssid=str(observation.get("bssid") or ""),
        band=str(observation.get("band") or ""),
        channel=_optional_int(observation.get("channel")),
        rssi_dbm=float(rssi if rssi is not None else -100.0),
        data_type=data_type,
        point_index=_optional_int(point.get("point_index")),
    )


def _matches_filter(observation: dict[str, object], selected_ssids: set[str], selected_bssids: set[str]) -> bool:
    if not selected_ssids and not selected_bssids:
        return True
    ssid = str(observation.get("ssid") or "<hidden>")
    bssid = str(observation.get("bssid") or "").casefold()
    return ssid in selected_ssids or bssid in selected_bssids


def _idw_value(x_px: float, y_px: float, samples: list[tuple[float, float, float]]) -> float:
    weighted_sum = 0.0
    weight_total = 0.0
    for x, y, rssi in samples:
        distance = math.hypot(x_px - x, y_px - y)
        if distance < 1:
            return rssi
        weight = 1.0 / (distance * distance)
        weighted_sum += rssi * weight
        weight_total += weight
    return weighted_sum / weight_total if weight_total else -100.0


def _optional_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    return int(value)
