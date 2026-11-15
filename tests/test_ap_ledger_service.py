from __future__ import annotations

from pathlib import Path

from netconsole.services.ap_extension_import import ApExtensionImportService
from netconsole.services.rail_transit.ap_ledger_service import (
    AC_ONLY_AP,
    CONFIRMED_AP,
    CONFIRMED_NON_AP,
    PENDING_DEVICE_TYPE,
    ApLedgerSource,
    build_ap_ledger,
    build_ap_ledger_from_sources,
)


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


def test_multi_source_ledger_retains_unresolved_neighbors_and_preserves_lldp_provenance() -> None:
    report = build_ap_ledger_from_sources(
        ac_ap_all_output="AP-A 1 R WA6320 SN-A\nAP-B 2 R WA6320 SN-B",
        ac_ap_address_output=(
            "AP Name IP Address MAC Address\n"
            "AP-A 10.0.0.1 0011-2233-4401\n"
            "AP-B 10.0.0.2 0011-2233-4402\n"
        ),
        sources=(
            ApLedgerSource(
                station_name="甲站",
                switch_name="SW-A",
                source_file="甲站.txt",
                source_sheet="甲站",
                build_phase="一期",
                source_timestamp="2026-11-15T10:00:00+08:00",
                lldp_output=(
                    "System Name Local Interface Chassis ID Port ID\n"
                    "AP-A GE1/0/2 0011-2233-4401 GE1/0/48\n"
                    "UPLINK GE1/0/48 aaaa-bbbb-cccc xge1/0/1\n"
                ),
            ),
            ApLedgerSource(
                station_name="乙站",
                switch_name="SW-B",
                source_file="乙站.txt",
                source_sheet="乙站",
                build_phase="一期",
                lldp_output=(
                    "System Name Local Interface Chassis ID Port ID\n"
                    "AP-B GE1/0/10 0011-2233-4402 GE1/0/48\n"
                ),
            ),
        ),
    )

    assert report.stats["lldp_ap_rows"] == 2
    assert report.stats["pending_device_type_rows"] == 1
    assert report.stats["non_ap_lldp_rows"] == 0
    assert report.pending_device_type[0].status == PENDING_DEVICE_TYPE
    assert len(report.observations) == 3
    assert {row.station_name for row in report.rows} == {"甲站", "乙站"}
    assert {row.uplink_port for row in report.rows} == {"GigabitEthernet1/0/2", "GigabitEthernet1/0/10"}
    values = report.rows[0].import_values()
    assert values["uplink_port"] != "GigabitEthernet1/0/48"
    assert '"source_type": "LLDP"' in str(values["raw_payload_json"])
    assert '"lldp_neighbor_interface": "GigabitEthernet1/0/48"' in str(values["raw_payload_json"])


def test_multi_source_ledger_marks_same_mac_or_port_conflicts_without_overwriting() -> None:
    report = build_ap_ledger_from_sources(
        ac_ap_all_output="AP-A 1 R WA6320 SN-A\nAP-B 2 R WA6320 SN-B",
        ac_ap_address_output=(
            "AP Name IP Address MAC Address\n"
            "AP-A 10.0.0.1 0011-2233-4401\n"
            "AP-B 10.0.0.2 0011-2233-4402\n"
        ),
        sources=(
            ApLedgerSource(
                station_name="甲站", switch_name="SW-A",
                lldp_output=(
                    "System Name Local Interface Chassis ID Port ID\n"
                    "AP-A GE1/0/2 0011-2233-4401 GE1/0/48\n"
                    "AP-B GE1/0/2 0011-2233-4402 GE1/0/48\n"
                ),
            ),
            ApLedgerSource(
                station_name="乙站", switch_name="SW-B",
                lldp_output=(
                    "System Name Local Interface Chassis ID Port ID\n"
                    "AP-A GE1/0/9 0011-2233-4401 GE1/0/48\n"
                ),
            ),
        ),
    )

    assert not report.rows
    assert report.stats["conflict_rows"] >= 3
    assert all(row.status == "CONFLICT" for row in report.conflicts)


def test_multi_source_ledger_collapses_identical_observations_and_keeps_name_difference() -> None:
    report = build_ap_ledger_from_sources(
        ac_ap_all_output="AP-AC 1 R WA6320 SN-AC\n",
        ac_ap_address_output="AP Name IP Address MAC Address\nAP-AC 10.0.0.1 0011-2233-4401\n",
        sources=(
            ApLedgerSource(
                station_name="甲站", switch_name="SW-A", source_file="a.txt",
                lldp_output="System Name Local Interface Chassis ID Port ID\nAP-LLDP GE1/0/2 0011-2233-4401 GE1/0/48\n",
            ),
            ApLedgerSource(
                station_name="甲站", switch_name="SW-A", source_file="b.txt",
                lldp_output="System Name Local Interface Chassis ID Port ID\nAP-LLDP GE1/0/2 0011-2233-4401 GE1/0/48\n",
            ),
        ),
    )
    assert len(report.rows) == 1
    assert report.rows[0].reason.startswith("MAC 精确匹配但名称字段不同")
    assert not report.conflicts


def test_lldp_classification_requires_explicit_non_ap_evidence_and_supports_ap_only_evidence() -> None:
    report = build_ap_ledger_from_sources(
        ac_ap_all_output="",
        ac_ap_address_output="",
        sources=(ApLedgerSource(
            station_name="甲站",
            switch_name="SW-A",
            device_type_by_name={"WIRELESS-NEW": "AP", "UPLINK": "switch"},
            lldp_output=(
                "System Name Local Interface Chassis ID Port ID\n"
                "WIRELESS-NEW GE1/0/1 0011-2233-4401 GE1/0/48\n"
                "UPLINK GE1/0/2 aaaa-bbbb-cccc xge1/0/1\n"
            ),
        ),),
    )

    assert len(report.rows) == 1
    assert report.rows[0].status == CONFIRMED_AP
    assert report.rows[0].match_method == "lldp_device_type"
    assert len(report.confirmed_non_ap) == 1
    assert report.confirmed_non_ap[0].status == CONFIRMED_NON_AP
    assert not report.pending_device_type


def test_ac_only_identity_is_audit_evidence_and_does_not_create_fake_uplink() -> None:
    report = build_ap_ledger_from_sources(
        ac_ap_all_output="AP-OLD 1 R WA6320 SN-OLD\n",
        ac_ap_address_output="AP Name IP Address MAC Address\nAP-OLD 10.0.0.1 0011-2233-4401\n",
        sources=(ApLedgerSource(
            station_name="甲站",
            switch_name="SW-A",
            lldp_output="System Name Local Interface Chassis ID Port ID\nOTHER GE1/0/2 aaaa-bbbb-cccc xge1/0/1\n",
        ),),
    )

    assert not report.rows
    assert len(report.ac_only) == 1
    assert report.ac_only[0].status == AC_ONLY_AP
    assert report.ac_only[0].uplink_switch == ""
    assert report.ac_only[0].uplink_port == ""
