from __future__ import annotations

from netconsole.parsers.h3c.transceiver_parser import merge_transceiver_data, parse_transceiver_diagnosis, parse_transceiver_manuinfo, parse_transceivers


def parse_optical(raw: str) -> list[dict[str, object | None]]:
    merged = parse_optical_repository(raw)
    result: list[dict[str, object | None]] = []
    for item in merged:
        result.append(
            {
                **item,
                "serial": item.get("module_serial_number"),
                "rx_power": _to_float(item.get("rx_power")),
                "tx_power": _to_float(item.get("tx_power")),
                "temperature": _to_float(item.get("temperature")),
                "voltage": _to_float(item.get("voltage")),
                "bias": _to_float(item.get("bias_current")),
                "alarm_status": _alarm_status(item),
            }
        )
    return result


def parse_optical_repository(raw: str) -> list[dict[str, object | None]]:
    return merge_transceiver_data(
        parse_transceivers(raw),
        parse_transceiver_manuinfo(raw),
        parse_transceiver_diagnosis(raw),
    )


def _alarm_status(item: dict[str, object | None]) -> str:
    status = str(item.get("status") or "").strip().lower()
    if status in {"normal", "warning", "alarm", "no_light", "no_module"}:
        return status
    if not _has_optical_module_data(item):
        return "no_module"
    rx_power = str(item.get("rx_power") or "")
    return "no_light" if rx_power.startswith("-40") else "normal"


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).split()[0])
    except (ValueError, IndexError):
        return None


def _has_optical_module_data(item: dict[str, object | None]) -> bool:
    return any(
        item.get(field) not in (None, "")
        for field in (
            "rx_power",
            "tx_power",
            "module_model",
            "module_serial_number",
            "module_vendor",
            "wavelength",
            "transmission_distance",
            "connector_type",
        )
    )
