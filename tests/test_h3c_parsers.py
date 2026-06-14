from pathlib import Path

from netconsole.parsers.h3c.boot_loader_parser import parse_boot_loader
from netconsole.parsers.h3c.device_parser import parse_device_model
from netconsole.parsers.h3c.interface_parser import parse_interfaces
from netconsole.parsers.h3c.lldp_parser import parse_lldp_neighbors
from netconsole.parsers.h3c.sysname_parser import parse_sysname
from netconsole.parsers.h3c.transceiver_parser import merge_transceiver_data, parse_transceiver_diagnosis, parse_transceivers
from netconsole.parsers.h3c.version_parser import parse_version


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
    assert parsed["software_version"] == "H3C Comware Software, Version 7.1.070, Release 6607P20"
    assert parsed["uptime"] == "12 weeks, 3 days, 4 hours, 5 minutes"
    assert parsed["serial_number"] == "SN-SW01-0001"
    assert parsed["vendor"] == "H3C"


def test_sysname_parser_extracts_sysname_line():
    assert parse_sysname(fixture("display_current_configuration_sysname.txt")) == "SW01"


def test_device_parser_extracts_ac_and_sw_models():
    assert parse_device_model(fixture("display_device_ac.txt")) == "WX5540H-HCL"
    assert parse_device_model(fixture("display_device_sw.txt")) == "S6850"


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
    assert "Tagged VLANs:   20" in parsed[0]["vlan"]
    assert "Untagged VLANs: 10" in parsed[0]["vlan"]


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
    assert "VLAN Passing" in parsed[0]["vlan"]
    assert "VLAN permitted" in parsed[0]["vlan"]


def test_transceiver_parser_extracts_model_serial_and_power():
    base = parse_transceivers(fixture("display_transceiver_interface.txt"))
    diagnosis = parse_transceiver_diagnosis(fixture("display_transceiver_diagnosis_interface.txt"))
    merged = merge_transceiver_data(base, diagnosis)

    assert merged[0]["interface_name"] == "GigabitEthernet1/0/1"
    assert merged[0]["module_model"] == "SFP-GE-LX-SM1310"
    assert merged[0]["module_serial_number"] == "OPT-SW01-0001"
    assert merged[0]["rx_power"] == "-3.21 dBm"
    assert merged[0]["tx_power"] == "-2.85 dBm"


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
