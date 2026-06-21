from __future__ import annotations

import math


MESH_SERIES_METADATA: dict[str, dict[str, object]] = {
    "peer.local_rssi": {"label_key": "mesh_analysis.mr_rssi", "unit": "raw", "decimals": 0, "description_key": "mesh_analysis.mr_rssi_description"},
    "peer.peer_rssi": {"label_key": "mesh_analysis.peer_rssi_raw", "unit": "raw", "decimals": 0, "description_key": "mesh_analysis.peer_rssi_description"},
    "peer.local_noise": {"label_key": "mesh_analysis.local_noise", "unit": "raw_dbm_negative", "decimals": 0, "description_key": "mesh_analysis.noise_description"},
    "peer.peer_noise": {"label_key": "mesh_analysis.peer_noise", "unit": "raw_dbm_negative", "decimals": 0, "description_key": "mesh_analysis.noise_description"},
    "peer.local_tx_busy": {"label_key": "mesh_analysis.local_tx_busy", "unit": "percent", "decimals": 0, "description_key": "mesh_analysis.tx_busy_description"},
    "peer.peer_tx_busy": {"label_key": "mesh_analysis.peer_tx_busy", "unit": "percent", "decimals": 0, "description_key": "mesh_analysis.tx_busy_description"},
    "peer.local_rx_busy": {"label_key": "mesh_analysis.local_rx_busy", "unit": "percent", "decimals": 0, "description_key": "mesh_analysis.rx_busy_description"},
    "peer.peer_rx_busy": {"label_key": "mesh_analysis.peer_rx_busy", "unit": "percent", "decimals": 0, "description_key": "mesh_analysis.rx_busy_description"},
    "peer.state": {"label_key": "mesh_analysis.state", "unit": "state", "decimals": 0, "description_key": "mesh_analysis.state_description"},
    "active.active_local_rssi": {"label_key": "mesh_analysis.current_active_mr_rssi", "unit": "raw", "decimals": 0, "description_key": "mesh_analysis.mr_rssi_description"},
    "active.active_local_tx_busy": {"label_key": "mesh_analysis.mr_tx_busy", "unit": "percent", "decimals": 0, "description_key": "mesh_analysis.tx_busy_description"},
    "active.active_local_rx_busy": {"label_key": "mesh_analysis.mr_rx_busy", "unit": "percent", "decimals": 0, "description_key": "mesh_analysis.rx_busy_description"},
}


def format_mesh_value(value: object, metadata: dict[str, object]) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "-"
    if not math.isfinite(numeric):
        return "-"
    unit = str(metadata.get("unit") or "")
    decimals = int(metadata.get("decimals") or 0)
    if unit == "state":
        return "ACTIVE" if int(numeric) == 1 else "STANDBY" if int(numeric) == 0 else "-"
    if decimals <= 0:
        text = str(int(round(numeric)))
    else:
        text = f"{numeric:.{decimals}f}".rstrip("0").rstrip(".")
    if unit == "percent":
        return f"{text}%"
    if unit == "seconds":
        return f"{text}s"
    if unit == "raw_dbm_negative":
        return f"{text} (meaning -{text} dBm)"
    return text
