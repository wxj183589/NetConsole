from __future__ import annotations

from datetime import datetime

from netconsole.services.online_mr_parser import parse_mesh_link_text, summarize_active


def parse(raw_text: str, collected_at: datetime | None = None) -> dict[str, object]:
    collected_at = collected_at or datetime.now()
    records, status, error = parse_mesh_link_text(raw_text, collected_at)
    active = summarize_active(records)
    return {
        "timestamp": collected_at.timestamp(),
        "status": status,
        "error": error,
        "records": records,
        "mesh": {
            "mr_rssi": active.metrics.get("local_rssi_db") if active else None,
            "peer_rssi": active.metrics.get("peer_rssi_db") if active else None,
            "peer_mac": active.peer_mac_normalized if active else "",
        },
    }
