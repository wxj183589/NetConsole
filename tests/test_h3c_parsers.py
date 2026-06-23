from pathlib import Path

from netconsole.parsers.h3c.boot_loader_parser import parse_boot_loader
from netconsole.parsers.h3c.device_parser import parse_device_model
from netconsole.parsers.h3c.interface_parser import parse_interfaces
from netconsole.parsers.h3c.lldp_parser import parse_lldp_neighbors
from netconsole.parsers.h3c.ac.fit_ap_optical_parser import parse_fit_ap_optical, parse_fit_ap_transceiver
from netconsole.parsers.h3c.sysname_parser import parse_sysname
from netconsole.parsers.h3c.transceiver_parser import (
    merge_transceiver_data,
    parse_transceiver_diagnosis,
    parse_transceiver_manuinfo,
    parse_transceivers,
)
from netconsole.parsers.h3c.version_parser import normalize_device_mac, parse_version


FIXTURES = Path(__file__).parent / "fixtures" / "h3c"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_version_parser_extracts_sysname_version_and_uptime():
    parsed = parse_version(
        fixture("display_version.txt"),
        fixture("display_device.txt"),
        fixture("display_device_manuinfo.txt"),
    )

    assert parsed["sysname"] == "SW01"
    assert parsed["software_version"] == "Version 7.1.070 Release 6607P20"
    assert parsed["uptime"] == "12 weeks, 3 days, 4 hours, 5 minutes"
    assert parsed["serial_number"] == "SN-SW01-0001"
    assert parsed["mac_address"] == "105e-ae3e-0700"
    assert parsed["vendor"] == "H3C"


def test_device_mac_normalizes_common_formats():
    assert normalize_device_mac("105E-AE3E-0700") == "105e-ae3e-0700"
    assert normalize_device_mac("105E:AE3E:0700") == "105e-ae3e-0700"
    assert normalize_device_mac("105eae3e0700") == "105e-ae3e-0700"
    assert normalize_device_mac("") is None


def test_version_parser_extracts_mac_with_fullwidth_colon():
    parsed = parse_version("", "", "MAC_ADDRESS：105E-AE3E-0700")

    assert parsed["mac_address"] == "105e-ae3e-0700"


def test_sysname_parser_extracts_sysname_line():
    assert parse_sysname(fixture("display_current_configuration_sysname.txt")) == "SW01"


def test_device_parser_extracts_ac_and_sw_models():
    assert parse_device_model(fixture("display_device_ac.txt")) == "WX5540H-HCL"
    assert parse_device_model(fixture("display_device_sw.txt")) == "S6850"


def test_chassis_manuinfo_overrides_slot_board_model_and_serial():
    parsed = parse_version(
        """
H3C Comware Software, Version 7.1.070, Release 7756P10
H3C S7503X-M-G uptime is
0 weeks, 5 days, 23 hours, 59 minutes
""",
        """
Slot Brd Type           Status
0    LSCM2CGT24TSSC0    Master
1    LSCM2CGT24TSSC0    Standby
2    LSCM2GP48SC0       Normal
""",
        """
Chassis self:
DEVICE_NAME          : S7503X-M-G
DEVICE_SERIAL_NUMBER : 210235A3XAX25A0C7059
VENDOR_NAME          : H3C

Slot 0:
DEVICE_NAME          : LSCM2CGT24TSSC0
DEVICE_SERIAL_NUMBER : SLOT0-SN
""",
    )

    assert parsed["model"] == "S7503X-M-G"
    assert parsed["serial_number"] == "210235A3XAX25A0C7059"
    assert parsed["vendor"] == "H3C"
    assert parsed["software_version"] == "Version 7.1.070 Release 7756P10"
    assert parsed["uptime"] == "0 weeks, 5 days, 23 hours, 59 minutes"


def test_boot_loader_parser_extracts_grouped_version_and_plain_formats():
    assert parse_boot_loader(fixture("display_boot_loader_ac.txt")) == (
        "当前:\n"
        "  flash:/wx5540hhcl-cmw710-boot-a6429.bin Alpha 7165\n"
        "  flash:/wx5540hhcl-cmw710-system-a6429.bin Alpha 7165\n\n"
        "主用:\n"
        "  flash:/wx5540hhcl-cmw710-boot-a6429.bin Alpha 7165\n"
        "  flash:/wx5540hhcl-cmw710-system-a6429.bin Alpha 7165\n\n"
        "备用:\n"
        "  flash:/wx5540hhcl-cmw710-boot-a6429.bin Alpha 7165\n"
        "  flash:/wx5540hhcl-cmw710-system-a6429.bin Alpha 7165"
    )
    assert parse_boot_loader(fixture("display_boot_loader_sw.txt")) == (
        "当前:\n"
        "  flash:/s6850-cmw710-boot-t7064p15.bin\n"
        "  flash:/s6850-cmw710-system-t7064p15.bin\n\n"
        "主用:\n"
        "  flash:/s6850-cmw710-boot-t7064p15.bin\n"
        "  flash:/s6850-cmw710-system-t7064p15.bin\n\n"
        "备用:\n"
        "  flash:/s6850-cmw710-boot-t7064p15.bin\n"
        "  flash:/s6850-cmw710-system-t7064p15.bin"
    )


def test_boot_loader_parser_can_format_english_labels():
    parsed = parse_boot_loader(fixture("display_boot_loader_sw.txt"), language="en_US")

    assert parsed
    assert "Current:" in parsed
    assert "Main:" in parsed
    assert "Backup:" in parsed


def test_boot_loader_parser_preserves_chassis_slots():
    parsed = parse_boot_loader(
        """
Software images on slot 0:
Current software images:
  flash:/s7503x-cmw710-boot-r7756p10.bin
Main startup software images:
  flash:/s7503x-cmw710-boot-r7756p10.bin
Backup startup software images:
  flash:/s7503x-cmw710-boot-backup.bin

Software images on slot 1:
Current software images:
  flash:/s7503x-cmw710-boot-r7756p10.bin
Main startup software images:
  flash:/s7503x-cmw710-boot-r7756p10.bin
Backup startup software images:
  flash:/s7503x-cmw710-boot-backup.bin
"""
    )

    assert "slot0" in parsed
    assert "slot1" in parsed
    assert "当前:" in parsed
    assert "主用:" in parsed
    assert "备用:" in parsed


def test_interface_parser_extracts_name_link_protocol_and_description():
    parsed = parse_interfaces(fixture("display_interface.txt"))

    assert len(parsed) == 2
    assert parsed[0]["interface_name"] == "GigabitEthernet1/0/1"
    assert parsed[0]["link_status"] == "UP"
    assert parsed[0]["protocol_status"] == "UP"
    assert parsed[0]["description"] == "Uplink to AC"
    assert parsed[0]["ip_address"] == "10.0.0.52/24"


def test_interface_parser_supports_two_line_h3c_headers():
    parsed = parse_interfaces(
        """
FortyGigE1/0/53
Current state: DOWN
Line protocol state: DOWN
IP packet frame type: Ethernet II, hardware address: 4c6f-b6a1-0200
Description: FortyGigE1/0/53 Interface
40Gbps-speed mode, unknown-duplex mode
PVID: 1
Port link-type: Access
"""
    )

    assert parsed[0]["interface_name"] == "FortyGigE1/0/53"
    assert parsed[0]["link_status"] == "DOWN"
    assert parsed[0]["protocol_status"] == "DOWN"
    assert parsed[0]["mac_address"] == "4c6f-b6a1-0200"
    assert parsed[0]["speed"] == "40Gbps"


def test_interface_parser_extracts_vlan_interface_ip_and_l3_type():
    parsed = parse_interfaces(
        """
Vlan-interface1
Current state: UP
Line protocol state: UP
Description: Vlan-interface1 Interface
Internet address: 10.0.0.52/24 (Primary)
IP packet frame type: Ethernet II, hardware address: 4c6f-b6a1-0202
"""
    )

    assert parsed[0]["interface_name"] == "Vlan-interface1"
    assert parsed[0]["ip_address"] == "10.0.0.52/24"
    assert parsed[0]["interface_type"] == "三层"
    assert parsed[0]["port_status"] == "route"


def test_interface_parser_keeps_chinese_description_readable():
    parsed = parse_interfaces(
        """
GigabitEthernet2/0/13
Current state: UP
Line protocol state: UP
Description: To_信号系统
"""
    )

    assert parsed[0]["description"] == "To_信号系统"


def test_interface_parser_keeps_gb2312_chinese_description_readable():
    parsed = parse_interfaces(
        """
GigabitEthernet2/0/13
Current state: UP
Line protocol state: UP
Description: To_广播系统
"""
    )

    assert parsed[0]["description"] == "To_广播系统"


def test_interface_parser_supports_loopback_management_and_null_ports():
    parsed = parse_interfaces(
        """
InLoopBack0
Current state: UP
Line protocol state: UP
M-GigabitEthernet0/0/0
Current state: UP
Line protocol state: UP
LoopBack0
Current state: UP
Line protocol state: UP
NULL0
Current state: UP
Line protocol state: UP
"""
    )

    assert [item["interface_name"] for item in parsed] == [
        "InLoopBack0",
        "M-GigabitEthernet0/0/0",
        "LoopBack0",
        "NULL0",
    ]


def test_interface_parser_identifies_access_l2_pvid_and_status():
    parsed = parse_interfaces(
        """
GigabitEthernet1/0/1
Current state: UP
Line protocol state: UP
PVID: 1
Port link-type: Access
"""
    )

    assert parsed[0]["interface_type"] == "二层"
    assert parsed[0]["port_status"] == "access"
    assert parsed[0]["pvid"] == "1"


def test_interface_parser_identifies_hybrid_l2_and_vlan_details():
    parsed = parse_interfaces(
        """
GigabitEthernet1/0/2
Current state: UP
Line protocol state: UP
PVID: 10
Port link-type: Hybrid
 Tagged VLANs:   20
 Untagged VLANs: 10
"""
    )

    assert parsed[0]["interface_type"] == "二层"
    assert parsed[0]["port_status"] == "hybrid"
    assert parsed[0]["pvid"] == "10"
    assert "Tagged: 20" in parsed[0]["vlan"]
    assert "Untagged: 10" in parsed[0]["vlan"]


def test_interface_parser_identifies_trunk_l2_and_vlan_details():
    parsed = parse_interfaces(
        """
GigabitEthernet1/0/3
Current state: UP
Line protocol state: UP
PVID: 20
Port link-type: Trunk
VLAN Passing  : 1(default vlan), 10, 20
VLAN permitted: 1(default vlan), 10, 20
"""
    )

    assert parsed[0]["interface_type"] == "二层"
    assert parsed[0]["port_status"] == "trunk"
    assert parsed[0]["pvid"] == "20"
    assert parsed[0]["vlan"] == "1(default vlan), 10, 20"


def test_interface_parser_access_vlan_uses_untagged_value_only():
    parsed = parse_interfaces(
        """
GigabitEthernet2/0/1
Current state: UP
Line protocol state: UP
PVID: 921
Port link-type: Access
Untagged VLANs: 1
"""
    )

    assert parsed[0]["pvid"] == "921"
    assert parsed[0]["vlan"] == "1"


def test_interface_parser_trunk_vlan_uses_passing_value_only():
    parsed = parse_interfaces(
        """
GigabitEthernet2/0/2
Current state: UP
Line protocol state: UP
PVID: 921
Port link-type: Trunk
VLAN Passing: 921, 989-990
VLAN permitted: 921, 989-990
"""
    )

    assert parsed[0]["pvid"] == "921"
    assert parsed[0]["vlan"] == "921, 989-990"


def test_transceiver_parser_extracts_model_serial_and_power():
    base = parse_transceivers(fixture("display_transceiver_interface.txt"))
    diagnosis = parse_transceiver_diagnosis(fixture("display_transceiver_diagnosis_interface.txt"))
    merged = merge_transceiver_data(base, diagnosis)

    assert merged[0]["interface_name"] == "GigabitEthernet1/0/1"
    assert merged[0]["module_model"] == "SFP-GE-LX-SM1310"
    assert merged[0]["module_serial_number"] == "OPT-SW01-0001"
    assert merged[0]["rx_power"] == "-3.21 dBm"
    assert merged[0]["tx_power"] == "-2.85 dBm"


def test_transceiver_diagnosis_parser_extracts_h3c_table_values_and_thresholds():
    parsed = parse_transceiver_diagnosis(
        """
GigabitEthernet2/0/1 transceiver diagnostic information:
  Current diagnostic parameters:
    Temp.(C)   Voltage(V)  Bias(mA)  RX power(dBm)  TX power(dBm)
    38         3.28        17.50     -7.34          -6.09
  Alarm thresholds:
    High  85   3.60  60.00  -3.00  -1.00
    Low   -5   3.00  0.00   -19.00 -11.00
  Warning thresholds:
    High  80   3.50  50.00  -5.00  -3.00
    Low   0    3.10  0.00   -16.99 -9.00
"""
    )

    item = parsed[0]
    assert item["interface_name"] == "GigabitEthernet2/0/1"
    assert item["temperature"] == "38"
    assert item["voltage"] == "3.28"
    assert item["bias_current"] == "17.50"
    assert item["rx_power"] == "-7.34"
    assert item["tx_power"] == "-6.09"
    assert item["rx_low_alarm"] == "-19.00"
    assert item["rx_high_alarm"] == "-3.00"
    assert item["tx_low_alarm"] == "-11.00"
    assert item["tx_high_alarm"] == "-1.00"
    assert item["rx_low_warning"] == "-16.99"
    assert item["rx_high_warning"] == "-5.00"
    assert item["tx_low_warning"] == "-9.00"
    assert item["tx_high_warning"] == "-3.00"


def test_fit_ap_transceiver_selects_ten2_when_ten1_is_absent():
    parsed = parse_fit_ap_transceiver(
        """
Ten-GigabitEthernet1/0/1 transceiver diagnostic information:
The transceiver is absent.

Ten-GigabitEthernet1/0/2 transceiver diagnostic information:
Current diagnostic parameters:
Temp.(C) Voltage(V) Bias(mA) RX power(dBm) TX power(dBm)
37 3.28 14.90 -9.24 -5.81
"""
    )

    assert parsed["interface_name"] == "Ten-GigabitEthernet1/0/2"
    assert parsed["rx_power"] == "-9.24"
    assert parsed["tx_power"] == "-5.81"


def test_fit_ap_optical_matches_lldp_xge_to_ten_gigabit_interface():
    parsed = parse_fit_ap_optical(
        """
System Name Local Interface Chassis ID Port ID
CJL-PIS-1 XGE1/0/2 6c87-207f-f4fe GigabitEthernet1/0/13
""",
        """
Ten-GigabitEthernet1/0/1 transceiver diagnostic information:
The transceiver is absent.

Ten-GigabitEthernet1/0/2 transceiver diagnostic information:
Current diagnostic parameters:
Temp.(C) Voltage(V) Bias(mA) RX power(dBm) TX power(dBm)
37 3.28 14.90 -9.24 -5.81
""",
    )

    assert parsed["lldp_neighbor"] == "CJL-PIS-1"
    assert parsed["interface_name"] == "Ten-GigabitEthernet1/0/2"
    assert parsed["neighbor_interface"] == "GigabitEthernet1/0/13"
    assert parsed["rx_power"] == "-9.24"
    assert parsed["tx_power"] == "-5.81"


def test_transceiver_parser_extracts_base_information_fields():
    parsed = parse_transceivers(
        """
GigabitEthernet2/0/1 transceiver information:
  Transceiver Type       : 1000_BASE_LX_SFP
  Ordering Name          : SFP-GE-LX-SM1310-D
  Serial Number          : OPT-SN-001
  Vendor Name            : H3C
  Wavelength(nm)         : 1310
  Transfer Distance(km)  : 10(SMF)
  Connector Type         : LC
  Status                 : Normal
"""
    )

    assert parsed[0]["module_model"] == "SFP-GE-LX-SM1310-D"
    assert parsed[0]["module_serial_number"] == "OPT-SN-001"
    assert parsed[0]["module_vendor"] == "H3C"
    assert parsed[0]["wavelength"] == "1310 nm"
    assert parsed[0]["transmission_distance"] == "10(SMF) km"
    assert parsed[0]["connector_type"] == "LC"
    assert parsed[0]["status"] == "Normal"


def test_transceiver_manuinfo_parser_extracts_serial_and_vendor():
    parsed = parse_transceiver_manuinfo(
        """
GigabitEthernet2/0/30 transceiver manufacture information:
  Manu. Serial Number : 210231A962N253002CVW
  Manufacturing Date  : 2025-03-23
  Vendor Name         : H3C
"""
    )

    assert parsed[0]["interface_name"] == "GigabitEthernet2/0/30"
    assert parsed[0]["module_serial_number"] == "210231A962N253002CVW"
    assert parsed[0]["module_vendor"] == "H3C"


def test_compute_optical_severity_returns_normal_warning_alarm_and_no_light():
    """compute_optical_severity is the unified threshold calculator."""
    from netconsole.core.optical_severity_engine import compute_optical_severity

    base = {"switch_rx_power": "-10.00", "alarm_low": "-19.00", "warning_low": "-16.99"}

    assert compute_optical_severity(base).severity == "normal"
    assert compute_optical_severity({**base, "switch_rx_power": "-20.00"}).severity == "alarm"
    assert compute_optical_severity({**base, "switch_rx_power": "-14.35"}).severity == "notice"
    assert compute_optical_severity({**base, "switch_rx_power": "-13.99"}).severity == "normal"
    assert compute_optical_severity({**base, "switch_rx_power": "-13.98"}).severity == "normal"
    assert compute_optical_severity({**base, "switch_rx_power": "-17.00"}).severity == "warning"
    assert compute_optical_severity({**base, "switch_rx_power": "-20.32", "alarm_low": "-20.00"}).severity == "alarm"
    assert compute_optical_severity({**base, "switch_rx_power": "-36.96"}).severity == "no_light"
    assert compute_optical_severity({**base, "switch_rx_power": "-40.00"}).severity == "no_light"
    assert compute_optical_severity({**base, "switch_rx_power": "-9.71", "switch_port_status": "DOWN"}).severity == "link_abnormal"


def test_compute_optical_severity_uses_warning_low_threshold():
    """compute_optical_severity uses warning_low + 3 as upper boundary."""
    from netconsole.core.optical_severity_engine import compute_optical_severity

    base = {"switch_rx_power": "-10.00", "alarm_low": "-25.00", "warning_low": "-18.00"}

    assert compute_optical_severity({**base, "switch_rx_power": "-15.50"}).severity == "notice"
    assert compute_optical_severity({**base, "switch_rx_power": "-12.50", "warning_low": "-14.00"}).severity == "notice"
    assert compute_optical_severity({**base, "switch_rx_power": "-14.99"}).severity == "normal"


def test_compute_optical_severity_derives_ap_warning_threshold_from_alarm():
    from netconsole.core.optical_severity_engine import compute_optical_severity

    result = compute_optical_severity({"ap_rx_power": "-15.58", "alarm_low": "-19.00", "device_type": "ap"})

    assert result.severity == "notice"
    assert result.alarm_low == -19.0
    assert result.warning_low == -16.99
    assert result.maintenance_normal_line == -13.99
    assert result.warning_source == "derived"
    assert result.source_label == "AP derived"


def test_compute_optical_severity_does_not_mark_missing_thresholds_normal():
    from netconsole.core.optical_severity_engine import compute_optical_severity

    result = compute_optical_severity({"ap_rx_power": "-10.00", "device_type": "ap"})

    assert result.severity == "unknown"
    assert result.source_label == "threshold missing"


def test_lldp_parser_extracts_local_neighbor_and_remote_interface():
    parsed = parse_lldp_neighbors(
        fixture("display_lldp_neighbor_information_list.txt"),
        fixture("display_lldp_neighbor_information_verbose.txt"),
    )

    assert parsed[0]["local_interface"] == "GigabitEthernet1/0/1"
    assert parsed[0]["neighbor_sysname"] == "AC-DEMO"
    assert parsed[0]["neighbor_interface"] == "GigabitEthernet1/0/1"
    assert parsed[0]["neighbor_ip"] == "10.0.0.51"


def test_lldp_parser_normalizes_numbered_verbose_port_header():
    parsed = parse_lldp_neighbors(
        "",
        """
LLDP neighbor-information of port 49[GigabitEthernet1/0/48]:
 Port ID             : GigabitEthernet1/0/1
 System name         : AC
 Management address  : 10.0.0.51
""",
    )

    assert parsed[0]["local_interface"] == "GigabitEthernet1/0/48"


def test_lldp_list_parser_handles_port_id_variants_and_spaced_system_name():
    parsed = parse_lldp_neighbors(
        """
Local Interface Chassis ID      Port ID                         System Name
GE0/0/1         bc9c-c501-6684  1                               Intelligent Power Distribution Unit
GE0/0/17        3cc7-86b0-1022  GigabitEthernet0/0/19           FutureMatrix
XGE0/0/28       2c4c-7d30-4e00  Ten-GigabitEthernet1/2/0/48     COCC-12-CORE
""",
        "",
    )

    assert parsed[0]["local_interface"] == "GigabitEthernet0/0/1"
    assert parsed[0]["neighbor_mac"] == "bc9c-c501-6684"
    assert parsed[0]["neighbor_interface"] == "1"
    assert parsed[0]["neighbor_sysname"] == "Intelligent Power Distribution Unit"
    assert parsed[1]["neighbor_interface"] == "GigabitEthernet0/0/19"
    assert parsed[1]["neighbor_sysname"] == "FutureMatrix"
    assert parsed[2]["local_interface"] == "Ten-GigabitEthernet0/0/28"
    assert parsed[2]["neighbor_interface"] == "Ten-GigabitEthernet1/2/0/48"
    assert parsed[2]["neighbor_sysname"] == "COCC-12-CORE"
