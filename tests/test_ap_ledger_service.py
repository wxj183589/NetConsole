from __future__ import annotations

from pathlib import Path

from netconsole.services.ap_extension_import import ApExtensionImportService
from netconsole.services.rail_transit.ap_ledger_service import build_ap_ledger


def test_ap_ledger_uses_exact_mac_and_switch_local_port_then_round_trips_to_import_preview(tmp_path: Path) -> None:
    report = build_ap_ledger(
        station_name="翁梅",
        switch_name="SW-WM-01",
        ac_ap_all_output="AP-WM-01 1 R WA6320 SN-01\nAP-WM-02 2 R WA6320 SN-02",
        ac_ap_address_output=(
            "AP Name              IP Address       MAC Address\n"
            "AP-WM-01             10.0.0.11        0011-2233-4455\n"
            "AP-WM-02             10.0.0.12        0011-2233-4466\n"
        ),
        switch_lldp_outputs=(
            "System Name       Local Interface     Chassis ID          Port ID\n"
            "AP-WM-01          GE1/0/1             0011-2233-4455     GE1/0/48\n"
            "AP-WM-02          GE1/0/2             0011-2233-4466     GE1/0/48\n"
        ,),
        source_file="24翁梅(1).txt",
        source_sheet="翁梅",
    )
    assert report.stats == {
        "ac_ap_rows": 2, "matched_rows": 2, "unmatched_rows": 0,
        "conflict_rows": 0, "lldp_rows": 2,
    }
    assert [row.uplink_port for row in report.rows] == ["GigabitEthernet1/0/1", "GigabitEthernet1/0/2"]
    assert all(row.match_method == "exact_mac" for row in report.rows)

    path = report.write_xlsx(tmp_path / "ledger.xlsx")
    parsed = ApExtensionImportService().preview_file(path)
    assert parsed.template_type == "netconsole_standard_template"
    assert {row["station_name"] for row in parsed.standard_rows} == {"翁梅"}
    assert {row["uplink_port"] for row in parsed.standard_rows} == {"GigabitEthernet1/0/1", "GigabitEthernet1/0/2"}


def test_ap_ledger_does_not_use_station_prefix_or_fuzzy_matching() -> None:
    report = build_ap_ledger(
        station_name="翁梅",
        ac_ap_all_output="AP-WM-01 1 R WA6320 SN-01\nAP-WM-02 2 R WA6320 SN-02",
        ac_ap_address_output="AP-WM-01 10.0.0.11 0011-2233-4455\nAP-WM-02 10.0.0.12 0011-2233-4466",
        switch_lldp_outputs=("System Name       Local Interface     Chassis ID          Port ID\nWM-01-other       GE1/0/1             00aa-bbcc-ddee     GE1/0/48\n",),
    )
    assert not report.rows
    assert len(report.unmatched) == 2
