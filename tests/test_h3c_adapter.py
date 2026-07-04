from __future__ import annotations

from netconsole.adapters.h3c.h3c_adapter import H3CAdapter
from netconsole.adapters.h3c.h3c_command_profile import H3CCommandProfile, H3cAcCommandProfile
from netconsole.adapters.h3c.h3c_connection import H3CConnection, execute_h3c_command
from netconsole.adapters.h3c.h3c_interface_parser import classify_interface, normalize_interface
from netconsole.adapters.h3c.h3c_parser import H3CParser
from netconsole.models.device import Device
from netconsole.utils.text_encoding import safe_decode


def test_h3c_connection_params_lock_gb2312_encoding():
    params = H3CConnection(Device(ip_address="10.0.0.1", ssh_username="u", ssh_password="p")).params()

    assert params["device_type"] == "hp_comware"
    assert params["encoding"] == "gb2312"
    assert params["session_log"] is None
    assert params["global_delay_factor"] == 1


def test_execute_h3c_command_falls_back_to_utf8():
    calls = []

    class FakeConn:
        def send_command(self, cmd, encoding=None):
            calls.append(encoding)
            if encoding == "gb2312":
                raise UnicodeDecodeError("gb2312", b"", 0, 1, "boom")
            return "ok"

    assert execute_h3c_command(FakeConn(), "display interface") == "ok"
    assert calls == ["gb2312", "utf-8"]


def test_safe_decode_reads_gb2312_chinese_description():
    assert safe_decode("Description: To_广播系统".encode("gb2312")) == "Description: To_广播系统"


def test_normalize_interface_supports_h3c_logical_management_and_aliases():
    assert normalize_interface("M-GigabitEthernet0/0/0") == "M-GigabitEthernet0/0/0"
    assert normalize_interface("InLoopBack0") == "InLoopBack0"
    assert normalize_interface("GE2/0/48") == "GigabitEthernet2/0/48"
    assert classify_interface("InLoopBack0") == "loopback"
    assert classify_interface("M-GigabitEthernet0/0/0") == "physical"


def test_command_profile_switches_v5_v7_v9_commands():
    assert H3CCommandProfile(Device(remark="Comware V5")).get_command("interface") == "display interface"
    assert H3CCommandProfile(Device(remark="Comware V7")).get_command("interface") == "display interface brief"
    assert H3CCommandProfile(Device(remark="Comware V9")).get_command("optical") == "display optical-module"


def test_ac_persist_auto_ap_commands_include_save_force_only_in_action_profile():
    profile = H3cAcCommandProfile(Device(device_type="AC", device_vendor="H3C"))

    assert profile.persist_auto_ap_commands == (
        "system-view",
        "wlan auto-ap persistent all",
        "save force",
        "return",
        "quit",
    )
    assert "save force" not in profile.fit_ap_resource_commands
    assert "save force" not in profile.enable_ap_remote_login_commands


def test_parser_interfaces_keep_management_ports_and_chinese_descriptions():
    rows = H3CParser().parse_interfaces(
        """
InLoopBack0
Current state: UP
Line protocol state: UP
Description: To_广播系统
M-GigabitEthernet0/0/0
Current state: UP
Line protocol state: UP
"""
    )

    assert [row["interface_name"] for row in rows] == ["InLoopBack0", "M-GigabitEthernet0/0/0"]
    assert rows[0]["description"] == "To_广播系统"


def test_parser_optical_returns_unified_structure():
    rows = H3CParser().parse_optical(
        """
GigabitEthernet1/0/1 transceiver information:
  Serial Number          : OPT-SN-001
  Wavelength(nm)         : 1310
  Status                 : Normal
GigabitEthernet1/0/1 transceiver diagnostic information:
  Current diagnostic parameters:
    Temp.(C)   Voltage(V)  Bias(mA)  RX power(dBm)  TX power(dBm)
    38         3.28        17.50     -7.34          -6.09
"""
    )

    row = rows[0]
    assert row["interface_name"] == "GigabitEthernet1/0/1"
    assert row["serial"] == "OPT-SN-001"
    assert row["rx_power"] == -7.34
    assert row["tx_power"] == -6.09
    assert row["temperature"] == 38.0
    assert row["voltage"] == 3.28
    assert row["bias"] == 17.5
    assert row["alarm_status"] == "normal"


def test_parser_lldp_normalizes_mac_and_interfaces():
    rows = H3CParser().parse_lldp(
        """
Local Interface Chassis ID      Port ID                         System Name
GE0/0/1         bc9c-c501-6684  XGE1/0/49                       CORE
""",
        "",
    )

    assert rows[0]["local_interface"] == "GigabitEthernet0/0/1"
    assert rows[0]["neighbor_interface"] == "Ten-GigabitEthernet1/0/49"
    assert rows[0]["neighbor_mac"] == "bc:9c:c5:01:66:84"


def test_h3c_adapter_collect_all_uses_unified_entry(monkeypatch):
    device = Device(remark="Comware V7", ip_address="10.0.0.1")
    adapter = H3CAdapter(device)
    outputs = {
        "display version": "H3C Comware Software, Version 7.1.070\nH3C S6850 uptime is 1 week",
        "display device": "",
        "display device manuinfo": "",
        "display interface brief": "InLoopBack0\nCurrent state: UP\nLine protocol state: UP\n",
        "display transceiver diagnosis interface": "",
        "display lldp neighbor-information verbose": "",
    }

    monkeypatch.setattr(adapter.conn, "send", lambda cmd: outputs.get(cmd, ""))

    collected = adapter.collect_all()

    assert set(collected) == {"system", "interfaces", "optical", "lldp"}
    assert collected["interfaces"][0]["interface_name"] == "InLoopBack0"
