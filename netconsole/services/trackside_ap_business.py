from __future__ import annotations

from pathlib import Path

from netconsole.core.optical_severity_engine import display_optical_status, worse_optical_severity
from netconsole.core.sources.ap_source import compute_ap_status
from netconsole.core.sources.switch_source import (
    build_switch_data_lookup,
    compute_switch_status,
)
from netconsole.models.device import Device
from netconsole.utils.interface_normalize import normalize_interface_name
from netconsole.utils.interface_sort import interface_sort_key


TRACKSIDE_AP_BUSINESS_COLUMNS = (
    ("ac.station", "site"),
    ("ac.indoor_switch", "device_name"),
    ("details.interface_name", "interface_name"),
    ("details.link", "link_status"),
    ("details.port_description", "description"),
    ("details.port_status", "port_status"),
    ("details.pvid", "pvid"),
    ("details.vlan", "vlan"),
    ("ac.indoor_switch_rx_power", "switch_rx_power"),
    ("trackside.switch_optical_status", "switch_optical_status"),
    ("ac.ap_mac", "ap_mac"),
    ("ac.ap_name", "ap_name"),
    ("ac.ap_side_rx_power", "ap_rx_power"),
    ("trackside.ap_optical_status", "ap_optical_status"),
    ("field.updated_at", "updated_at"),
)

TRACKSIDE_AP_DEVICE_COLUMNS = (
    ("details.interface_name", "interface_name"),
    ("details.link", "link_status"),
    ("details.protocol", "protocol_status"),
    ("details.port_description", "description"),
    ("details.port_status", "port_status"),
    ("details.pvid", "pvid"),
    ("details.vlan", "vlan"),
    ("ac.indoor_switch_rx_power", "switch_rx_power"),
    ("trackside.switch_optical_status", "switch_optical_status"),
    ("ac.ap_mac", "ap_mac"),
    ("ac.ap_name", "ap_name"),
    ("ac.ap_side_rx_power", "ap_rx_power"),
    ("trackside.ap_optical_status", "ap_optical_status"),
    ("field.updated_at", "updated_at"),
)

TRACKSIDE_OPTICAL_COLOR_RGB = {
    "normal": "DCFCE7",
    "warning": "FEF9C3",
    "alarm": "FEE2E2",
    "link_abnormal": "FFE4E6",
    "no_light": "E5E7EB",
    "skipped": "F3F4F6",
}


def description_contains_ap(description: object) -> bool:
    return "ap" in str(description or "").casefold()


def build_device_optical_status_lookup(
    devices: list[Device],
    optical_by_device: dict[str, list[dict[str, object | None]]],
) -> dict:
    """Backward-compatible alias — delegates to ``switch_source.build_switch_data_lookup``."""
    return build_switch_data_lookup(devices, optical_by_device)


def build_trackside_ap_business_rows(
    devices: list[Device],
    interfaces_by_device: dict[str, list[dict[str, object | None]]],
    optical_by_device: dict[str, list[dict[str, object | None]]],
    fit_ap_optical_rows: list[dict[str, object | None]],
    lldp_by_device: dict[str, list[dict[str, object | None]]] | None = None,
    fit_ap_resource_rows: list[dict[str, object | None]] | None = None,
    device_optical_status_lookup: dict[tuple[str, str], str] | None = None,
) -> list[dict[str, object | None]]:
    optical_indexes = {
        device_uuid: {normalize_interface_name(row.get("interface_name")).casefold(): row for row in rows}
        for device_uuid, rows in optical_by_device.items()
    }
    lldp_indexes = {
        device_uuid: {normalize_interface_name(row.get("local_interface")).casefold(): row for row in rows}
        for device_uuid, rows in (lldp_by_device or {}).items()
    }
    fit_ap_index: dict[tuple[str, str], dict[str, object | None]] = {}
    fit_ap_optical_by_mac: dict[str, dict[str, object | None]] = {}
    fit_ap_optical_by_name_mac: dict[str, dict[str, object | None]] = {}
    fit_ap_resource_by_mac: dict[str, dict[str, object | None]] = {}
    for row in fit_ap_optical_rows:
        key = (_normalize_name(row.get("neighbor_device_name")), normalize_interface_name(row.get("neighbor_interface")).casefold())
        if key[0] and key[1]:
            fit_ap_index[key] = row
        mac = normalize_mac(row.get("ap_mac"))
        if mac:
            fit_ap_optical_by_mac[mac] = row
        name_as_mac = normalize_mac(row.get("ap_name"))
        if name_as_mac:
            fit_ap_optical_by_name_mac[name_as_mac] = row
    for row in fit_ap_resource_rows or []:
        mac = normalize_mac(row.get("ap_mac"))
        if mac:
            fit_ap_resource_by_mac[mac] = row

    result: list[dict[str, object | None]] = []
    for device in devices:
        device_uuid = str(device.device_uuid or "")
        device_names = {_normalize_name(device.name), _normalize_name(device.sysname)}
        device_names.discard("")
        optical_index = optical_indexes.get(device_uuid, {})
        lldp_index = lldp_indexes.get(device_uuid, {})
        for interface in interfaces_by_device.get(device_uuid, []):
            if not description_contains_ap(interface.get("description")):
                continue
            interface_name = str(interface.get("interface_name") or "")
            normalized_interface = normalize_interface_name(interface_name).casefold()
            optical = optical_index.get(normalized_interface, {})
            lldp = lldp_index.get(normalized_interface, {})
            neighbor_mac = normalize_mac(lldp.get("neighbor_mac"))
            fit_ap = (
                fit_ap_optical_by_mac.get(neighbor_mac)
                or _merge_resource_with_optical(fit_ap_resource_by_mac.get(neighbor_mac), fit_ap_optical_by_mac)
                or fit_ap_optical_by_name_mac.get(neighbor_mac)
                or _find_fit_ap_row(fit_ap_index, device_names, interface_name)
            )
            switch_status = compute_switch_status(
                device_name=device.name,
                interface_name=interface_name,
                switch_rx_power=optical.get("rx_power"),
                switch_port_status=optical.get("port_status"),
                alarm_low=optical.get("rx_low_alarm"),
                alarm_high=optical.get("rx_high_alarm"),
                warning_low=optical.get("rx_low_warning"),
                lookup=device_optical_status_lookup,
            )
            ap_status = compute_ap_status(fit_ap)
            result.append(
                {
                    "site": device.station or fit_ap.get("site") or "",
                    "ac_device_uuid": fit_ap.get("ac_device_uuid"),
                    "ap_uuid": fit_ap.get("ap_uuid"),
                    "device_uuid": device_uuid,
                    "device_name": device.name,
                    "interface_name": interface_name,
                    "link_status": interface.get("link_status") or interface.get("link"),
                    "protocol_status": interface.get("protocol_status") or interface.get("protocol"),
                    "description": interface.get("description"),
                    "port_status": interface.get("port_status"),
                    "pvid": interface.get("pvid"),
                    "vlan": interface.get("vlan"),
                    "switch_rx_power": optical.get("rx_power"),
                    "switch_optical_status": switch_status,
                    "ap_mac": normalize_mac(fit_ap.get("ap_mac")) or neighbor_mac,
                    "ap_name": fit_ap.get("ap_name"),
                    "ap_rx_power": fit_ap.get("rx_power"),
                    "ap_optical_status": ap_status,
                    "updated_at": fit_ap.get("updated_at") or optical.get("updated_at") or interface.get("updated_at") or interface.get("collected_at"),
                }
            )
    return sorted(result, key=lambda row: (str(row.get("site") or ""), str(row.get("device_name") or ""), interface_sort_key(row.get("interface_name"))))


def trackside_row_status(row: dict[str, object | None]) -> str:
    switch_status = str(row.get("switch_optical_status") or "")
    ap_status = str(row.get("ap_optical_status") or "")
    return worse_optical_severity(switch_status, ap_status)


def filter_trackside_ap_business_rows(rows: list[dict[str, object | None]], site: object = "", search: object = "") -> list[dict[str, object | None]]:
    site_text = str(site or "").strip()
    search_text = str(search or "").strip().casefold()
    result = rows
    if site_text:
        result = [row for row in result if str(row.get("site") or "") == site_text]
    if search_text:
        fields = ("ap_name", "ap_mac", "device_name", "interface_name", "site")
        result = [row for row in result if any(search_text in str(row.get(field) or "").casefold() for field in fields)]
    return result


def build_trackside_site_filter_items(rows: list[dict[str, object | None]], all_label: str) -> list[tuple[str, str]]:
    sites = sorted({str(row.get("site") or "").strip() for row in rows if str(row.get("site") or "").strip()})
    return [(all_label, ""), *[(site, site) for site in sites]]


def export_trackside_ap_business_xlsx(path: Path, rows: list[dict[str, object | None]], columns: tuple[tuple[str, str], ...], headers: list[str]) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    from netconsole.ui.table.table_autosize_engine import apply_worksheet_autofit

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "轨旁AP业务"
    sheet.append(headers)
    for row in rows:
        sheet.append([_export_value(field, row.get(field)) for _key, field in columns])
        color = TRACKSIDE_OPTICAL_COLOR_RGB.get(trackside_row_status(row))
        fill = PatternFill(fill_type="solid", fgColor=color) if color else None
        for cell in sheet[sheet.max_row]:
            if fill:
                cell.fill = fill
    alignment = Alignment(horizontal="center", vertical="center")
    border = Border(
        left=Side(style="thin", color="D1D5DB"),
        right=Side(style="thin", color="D1D5DB"),
        top=Side(style="thin", color="D1D5DB"),
        bottom=Side(style="thin", color="D1D5DB"),
    )
    sheet.freeze_panes = "A2"
    for row in sheet.iter_rows():
        sheet.row_dimensions[row[0].row].height = 24 if row[0].row == 1 else 22
        for cell in row:
            cell.alignment = alignment
            cell.border = border
            if cell.row == 1:
                cell.font = Font(bold=True)
    apply_worksheet_autofit(sheet, maximum=60)
    workbook.save(path)


# Legacy aliases removed — status is now computed real-time from raw data.


def _find_fit_ap_row(fit_ap_index: dict[tuple[str, str], dict[str, object | None]], device_names: set[str], interface_name: object) -> dict[str, object | None]:
    interface_key = normalize_interface_name(interface_name).casefold()
    for device_name in device_names:
        row = fit_ap_index.get((device_name, interface_key))
        if row:
            return row
    return {}


def _merge_resource_with_optical(resource: dict[str, object | None] | None, optical_by_mac: dict[str, dict[str, object | None]]) -> dict[str, object | None]:
    if not resource:
        return {}
    optical = optical_by_mac.get(normalize_mac(resource.get("ap_mac")), {})
    return {**resource, **optical}


def _normalize_name(value: object) -> str:
    return str(value or "").strip().casefold()


def normalize_mac(value: object) -> str:
    import re

    hex_text = re.sub(r"[^0-9a-fA-F]", "", str(value or ""))
    if len(hex_text) != 12:
        return str(value or "").strip().casefold()
    hex_text = hex_text.casefold()
    return f"{hex_text[0:4]}-{hex_text[4:8]}-{hex_text[8:12]}"


def _export_value(field: str, value: object) -> str:
    if field in {"switch_optical_status", "ap_optical_status"} and value:
        return display_optical_status(str(value))
    return str(value) if value not in (None, "") else "-"
