from __future__ import annotations

from netconsole.services.online_mr_parser import parse_channel_busy_text


def parse_channelbusy(raw_text: str) -> dict[str, object]:
    rows = parse_channel_busy_text(raw_text)
    first = rows[0] if rows else {}
    return {
        "channelbusy": {
            "tx": first.get("tx_busy"),
            "rx": first.get("rx_busy"),
        },
        "rows": rows,
    }
