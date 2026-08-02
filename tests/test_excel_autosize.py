from __future__ import annotations

from openpyxl import Workbook

from netconsole.services.excel_autosize import (
    apply_worksheet_column_widths,
    excel_column_width_bounds,
)


def test_specific_radio_fields_use_time_and_mac_bounds() -> None:
    assert excel_column_width_bounds("radio_updated_at", "Radio更新时间") == (18.0, 26.0)
    assert excel_column_width_bounds("radio_mac", "Radio MAC") == (18.0, 22.0)
    assert excel_column_width_bounds("serial_number", "AP序列号") == (14.0, 32.0)
    assert excel_column_width_bounds("radio_count", "Radio数量") == (8.0, 12.0)
    assert excel_column_width_bounds("software_version", "AC软件版本")[1] >= 40.0


def test_apply_worksheet_column_widths_uses_headers_data_and_text_limits() -> None:
    workbook = Workbook()
    sheet = workbook.active
    headers = ["Radio更新时间", "Radio MAC", "AP序列号", "连接端口", "AC软件版本", "备注"]
    rows = [
        {
            "radio_updated_at": "2026-08-03 12:34:56",
            "radio_mac": "00:11:22:33:44:55",
            "serial_number": "001234567890",
            "switch_interface": "GigabitEthernet2/0/20",
            "ac_version": "Version 7.1.064, Release 5632P20",
            "remark": "长备注" * 40,
        }
    ]
    sheet.append(headers)
    for row in rows:
        sheet.append(list(row.values()))
    apply_worksheet_column_widths(
        sheet,
        headers,
        rows,
        ["radio_updated_at", "radio_mac", "serial_number", "switch_interface", "ac_version", "remark"],
        maximum=48,
    )
    widths = [sheet.column_dimensions[chr(ord("A") + index)].width for index in range(len(headers))]
    assert 18.0 <= widths[0] <= 26.0
    assert 18.0 <= widths[1] <= 22.0
    assert 14.0 <= widths[2] <= 32.0
    assert widths[3] >= 18.0
    assert widths[4] >= 18.0
    assert 18.0 <= widths[5] <= 40.0
