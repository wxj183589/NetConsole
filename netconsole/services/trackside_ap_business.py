from __future__ import annotations

from pathlib import Path
import re

from netconsole.core.optical_severity_engine import compute_optical_severity, display_optical_status, worse_optical_severity
from netconsole.core.sources.switch_source import build_switch_data_lookup
from netconsole.models.device import Device
from netconsole.services.ap_online_overview import AP_ONLINE_OVERVIEW_COLUMNS, write_ap_online_overview_sheet
from netconsole.utils.interface_normalize import normalize_interface_name
from netconsole.utils.interface_sort import interface_sort_key


TRACKSIDE_AP_BUSINESS_INTERNAL_FIELDS = {
    "host",
    "host_address",
    "management_ip",
    "ap_ip",
    "source_device",
    "collection_status",
}

TRACKSIDE_AP_BUSINESS_VISIBLE_COLUMNS = (
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
    ("trackside_ap.tx_power", "ap_tx_power"),
    ("trackside_ap.last_collected_at", "updated_at"),
)

TRACKSIDE_AP_BUSINESS_COLUMNS = TRACKSIDE_AP_BUSINESS_VISIBLE_COLUMNS

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
    "notice": "FEF9C3",
    "warning": "FEF9C3",
    "alarm": "FEE2E2",
    "link_abnormal": "FFE4E6",
    "link_down": "FFE4E6",
    "no_light": "E5E7EB",
    "no_module": "F3F4F6",
    "skipped": "F3F4F6",
}

AP_SIDE_DISPLAY_FIELDS = {"ap_mac", "ap_name", "ap_rx_power", "ap_tx_power"}
AP_SIDE_MISSING_DISPLAY = "-"


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
            switch_result = compute_optical_severity(
                {
                    "module_present": bool(_has_optical_module_data(optical)),
                    "switch_rx_power": optical.get("rx_power"),
                    "switch_port_status": optical.get("port_status"),
                    "alarm_low": optical.get("rx_low_alarm"),
                    "alarm_high": optical.get("rx_high_alarm"),
                    "warning_low": optical.get("rx_low_warning"),
                    "device_type": "switch",
                }
            )
            switch_status = switch_result.severity
            ap_candidate = {
                "ap_mac": normalize_mac(fit_ap.get("ap_mac")) or neighbor_mac,
                "ap_name": fit_ap.get("ap_name"),
                "ap_rx_power": fit_ap.get("rx_power"),
                "ap_tx_power": fit_ap.get("tx_power"),
            }
            ap_side_has_data = _has_ap_side_optical_data(fit_ap, ap_candidate)
            ap_status = ""
            if ap_side_has_data:
                ap_result = compute_optical_severity(
                    {
                        "module_present": bool(_has_optical_module_data(fit_ap)) or _explicit_no_module(fit_ap),
                        "no_module": _explicit_no_module(fit_ap),
                        "ap_rx_power": fit_ap.get("rx_power"),
                        "ap_port_status": fit_ap.get("ap_port_status"),
                        "alarm_low": fit_ap.get("rx_low_alarm"),
                        "alarm_high": fit_ap.get("rx_high_alarm"),
                        "warning_low": fit_ap.get("rx_low_warning"),
                        "device_type": "ap",
                    }
                )
                ap_status = ap_result.severity
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
                    "ap_mac": ap_candidate["ap_mac"] if ap_side_has_data else None,
                    "ap_name": ap_candidate["ap_name"] if ap_side_has_data else None,
                    "ap_ip": fit_ap.get("ap_ip"),
                    "ap_state": fit_ap.get("state"),
                    "ap_state_display": fit_ap.get("state_display") or fit_ap.get("state_raw"),
                    "ap_rx_power": ap_candidate["ap_rx_power"] if ap_side_has_data else None,
                    "ap_tx_power": ap_candidate["ap_tx_power"] if ap_side_has_data else None,
                    "ap_optical_status": ap_status,
                    "ap_side_has_data": ap_side_has_data,
                    "updated_at": fit_ap.get("updated_at") or optical.get("updated_at") or interface.get("updated_at") or interface.get("collected_at"),
                    "source_device": fit_ap.get("device_name") or fit_ap.get("neighbor_device_name") or device.name,
                    "collection_status": fit_ap.get("status") or ("success" if optical else "not_collected"),
                }
            )
    return sorted(result, key=lambda row: (str(row.get("site") or ""), str(row.get("device_name") or ""), interface_sort_key(row.get("interface_name"))))


def trackside_row_status(row: dict[str, object | None]) -> str:
    switch_status = str(row.get("switch_optical_status") or "")
    ap_status = str(row.get("ap_optical_status") or "") if has_ap_side_optical_data(row) else ""
    return worse_optical_severity(switch_status, ap_status)


def has_ap_side_optical_data(row: dict[str, object | None]) -> bool:
    if not row:
        return False
    if "ap_side_has_data" in row:
        return bool(row.get("ap_side_has_data"))
    if _explicit_no_module(row):
        return True
    if _is_missing_display(row.get("ap_mac")) or _is_missing_display(row.get("ap_name")) or _is_missing_display(row.get("ap_rx_power")):
        return False
    return _has_optical_module_data({"rx_power": row.get("ap_rx_power"), "tx_power": row.get("ap_tx_power")})


def format_ap_side_alarm(row: dict[str, object | None], language: str = "zh") -> str:
    if not has_ap_side_optical_data(row):
        return AP_SIDE_MISSING_DISPLAY
    status = str(row.get("ap_optical_status") or "")
    return display_optical_status(status, language) if status else AP_SIDE_MISSING_DISPLAY


def format_trackside_display_value(field: str, row: dict[str, object | None], language: str = "zh") -> str:
    if field == "ap_optical_status":
        return format_ap_side_alarm(row, language)
    if field in AP_SIDE_DISPLAY_FIELDS and not has_ap_side_optical_data(row):
        return AP_SIDE_MISSING_DISPLAY
    value = row.get(field)
    if field == "switch_optical_status" and value:
        return display_optical_status(str(value), language)
    if field == "ap_optical_status" and value:
        return display_optical_status(str(value), language)
    return str(value) if value not in (None, "") else AP_SIDE_MISSING_DISPLAY


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


def export_trackside_ap_business_xlsx(
    path: Path,
    rows: list[dict[str, object | None]],
    columns: tuple[tuple[str, str], ...],
    headers: list[str],
    ap_online_overview_rows: list[dict[str, object | None]] | None = None,
    ap_online_overview_columns: tuple[tuple[str, str], ...] | None = None,
    ap_online_overview_headers: list[str] | None = None,
) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    from netconsole.ui.table.table_autosize_engine import apply_worksheet_autofit

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "\u8f68\u65c1AP\u4e1a\u52a1"
    sheet.append(headers)
    for row in rows:
        sheet.append([_export_value(field, row) for _key, field in columns])
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
    header_font = Font(bold=True)
    _format_export_sheet(sheet, alignment, border, header_font)
    _append_ap_overview_sheet(
        workbook,
        rows,
        alignment,
        border,
        header_font,
        ap_online_overview_rows,
        ap_online_overview_columns,
        ap_online_overview_headers,
    )
    _append_switch_optical_summary_sheet(workbook, rows, alignment, border, header_font)
    for worksheet in workbook.worksheets:
        apply_worksheet_autofit(worksheet, maximum=60)
    _set_switch_optical_summary_widths(workbook)
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


def summarize_trackside_ap_online_counts(rows: list[dict[str, object | None]]) -> tuple[int, int]:
    online = 0
    offline = 0
    seen: set[str] = set()
    for row in rows:
        key = str(row.get("ap_uuid") or row.get("ap_mac") or row.get("ap_name") or "").strip()
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        state = _ap_state(row)
        if state == "online":
            online += 1
        elif state == "offline":
            offline += 1
    return online, offline


def _normalize_name(value: object) -> str:
    return str(value or "").strip().casefold()


def normalize_mac(value: object) -> str:
    import re

    hex_text = re.sub(r"[^0-9a-fA-F]", "", str(value or ""))
    if len(hex_text) != 12:
        return str(value or "").strip().casefold()
    hex_text = hex_text.casefold()
    return f"{hex_text[0:4]}-{hex_text[4:8]}-{hex_text[8:12]}"


def _export_value(field: str, row: dict[str, object | None]) -> str:
    return format_trackside_display_value(field, row)


def _has_optical_module_data(row: dict[str, object | None]) -> bool:
    if not row:
        return False
    module_fields = (
        "rx_power",
        "tx_power",
        "module_model",
        "module_serial_number",
        "module_vendor",
        "wavelength",
        "transmission_distance",
        "connector_type",
        "rx_low_alarm",
        "rx_low_warning",
    )
    return any(row.get(field) not in (None, "") for field in module_fields)


def _has_ap_side_optical_data(fit_ap: dict[str, object | None], candidate: dict[str, object | None]) -> bool:
    if not fit_ap:
        return False
    if _explicit_no_module(fit_ap):
        return True
    if _is_missing_display(candidate.get("ap_mac")) or _is_missing_display(candidate.get("ap_name")) or _is_missing_display(candidate.get("ap_rx_power")):
        return False
    return _has_optical_module_data(fit_ap)


def _explicit_no_module(row: dict[str, object | None]) -> bool:
    text = " ".join(
        str(row.get(field) or "")
        for field in (
            "optical_alarm_status",
            "status",
            "raw_status",
            "ap_raw_status",
            "error_message",
            "message",
        )
    ).strip().casefold()
    if not text:
        return False
    return any(token in text for token in ("no_module", "no module", "no transceiver", "no-transceiver", "\u65e0\u5149\u6a21\u5757"))


def _is_missing_display(value: object) -> bool:
    return str(value or "").strip() in {"", "-"}


def _format_export_sheet(sheet, alignment, border, header_font) -> None:
    sheet.freeze_panes = "A2"
    for row in sheet.iter_rows():
        sheet.row_dimensions[row[0].row].height = 24 if row[0].row == 1 else 22
        for cell in row:
            cell.alignment = alignment
            cell.border = border
            if cell.row == 1:
                cell.font = header_font


def _append_ap_overview_sheet(
    workbook,
    rows: list[dict[str, object | None]],
    alignment,
    border,
    header_font,
    overview_rows: list[dict[str, object | None]] | None = None,
    overview_columns: tuple[tuple[str, str], ...] | None = None,
    overview_headers: list[str] | None = None,
) -> None:
    sheet = workbook.create_sheet("AP上线情况概览")
    sheet.title = "AP\u4e0a\u7ebf\u60c5\u51b5\u6982\u89c8"
    if overview_rows is not None and overview_columns is not None and overview_headers is not None:
        write_ap_online_overview_sheet(sheet, overview_rows, overview_headers)
        return
    write_ap_online_overview_sheet(sheet, [], [key for key, _field in AP_ONLINE_OVERVIEW_COLUMNS])
    return


def _append_switch_optical_summary_sheet(workbook, rows: list[dict[str, object | None]], alignment, border, header_font) -> None:
    sheet = workbook.create_sheet("交换机光模块统计")
    sheet.append(["交换机", "光模块数量", "未插光模块端口数量", "未插光模块端口"])
    grouped: dict[str, dict[str, object]] = {}
    for row in rows:
        switch_name = str(row.get("device_name") or "-")
        item = grouped.setdefault(switch_name, {"module_count": 0, "missing_ports": []})
        missing_ports = item["missing_ports"]
        if isinstance(missing_ports, list):
            missing_ports.extend(_normalize_missing_module_ports(row.get("missing_module_ports")))
        if row.get("switch_optical_status") == "no_module" and isinstance(missing_ports, list):
            missing_ports.extend(_normalize_missing_module_ports(row.get("interface_name") or "-"))
        else:
            item["module_count"] = int(item["module_count"]) + 1
    for switch_name in sorted(grouped):
        item = grouped[switch_name]
        missing_ports = _normalize_missing_module_ports(item["missing_ports"])
        sheet.append(
            [
                switch_name,
                item["module_count"],
                len(missing_ports),
                ", ".join(_short_interface_name(port) for port in missing_ports) if missing_ports else "-",
            ]
        )
    _format_export_sheet(sheet, alignment, border, header_font)
    sheet.auto_filter.ref = sheet.dimensions


def _normalize_missing_module_ports(value: object) -> list[str]:
    if value in (None, "", "-"):
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item or "").strip() and str(item or "").strip() != "-"]
    return [part.strip() for part in re.split(r"[,，;；]", str(value)) if part.strip() and part.strip() != "-"]


def _set_switch_optical_summary_widths(workbook) -> None:
    if "交换机光模块统计" not in workbook.sheetnames:
        return
    sheet = workbook["交换机光模块统计"]
    for column, width in {"A": 22, "B": 14, "C": 20, "D": 80}.items():
        sheet.column_dimensions[column].width = width


def _ap_state(row: dict[str, object | None]) -> str:
    text = " ".join(str(row.get(field) or "") for field in ("ap_state", "ap_state_display", "state", "state_display")).strip().casefold()
    if not text:
        return ""
    if any(token in text for token in ("online", "run", "up", "normal", "在线")):
        return "online"
    if any(token in text for token in ("offline", "down", "fault", "离线")):
        return "offline"
    return ""


def _short_interface_name(value: object) -> str:
    return str(value or "-").replace("GigabitEthernet", "GE")
