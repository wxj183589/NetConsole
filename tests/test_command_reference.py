import json
from pathlib import Path


from netconsole.core.paths import PathResolver
from netconsole.services.command_reference_service import export_command_references_markdown, load_command_references




def test_command_reference_json_covers_switch_baseline():
    items = load_command_references(PathResolver(Path(__file__).resolve().parents[1]))
    by_command = {item.command_template: item for item in items}
    baseline = {
        "screen-length disable",
        "screen-length d",
        "display current-configuration | include sysname",
        "display version",
        "display device",
        "display device manuinfo",
        "display boot-loader",
        "display interface",
        "display interface brief",
        "display transceiver interface",
        "display transceiver manuinfo interface",
        "display transceiver diagnosis interface",
        "display lldp neighbor-information list",
        "display lldp neighbor-information verbose",
        "display current-configuration",
        "display info-center",
        "display current-configuration | include info-center",
        "display saved-configuration",
        "save force",
        "display diagnostic-information",
        "n",
        "dir flash:/",
        "dir flash:/diagfile/",
        "ping <ip>",
        "ping -c <count> <ip>",
        "show running-config switchvlan",
        "show vlan",
    }

    assert baseline <= set(by_command)
    assert by_command["save force"].risk_level == "config_write"
    assert by_command["n"].interactive_input is True
    assert by_command["n"].risk_level == "interactive"
    assert by_command["display transceiver diagnosis interface"].zte_adaptation_status == "document_sample_only"
    assert (
        by_command["show opticalinfo brief"].zte_adaptation_status
        == "field_verified_partial"
    )
    assert "C89E-4 V1.9.0 已实机验证" in by_command[
        "show opticalinfo brief"
    ].parser_status
    assert "C89E-4 V1.9.0 已完成 Entry 实机解析" in by_command[
        "display lldp neighbor-information verbose"
    ].parser_status
    assert "show lldp statistic" not in by_command
    assert (
        by_command["show running-config switchvlan"].zte_adaptation_status
        == "field_verified"
    )
    assert by_command["show vlan"].zte_adaptation_status == "field_verified"
    assert by_command[
        "display lldp neighbor-information list"
    ].zte_adaptation_status == "field_verified"


def test_command_reference_json_is_unique_and_has_non_cli_section():
    data = json.loads((Path(__file__).resolve().parents[1] / "resources" / "command_reference.json").read_text(encoding="utf-8"))
    items = data["items"]
    ids = [item["id"] for item in items]

    assert len(items) == 87
    assert len(ids) == len(set(ids))
    assert {
        "ac_display_wlan_ap_all_connection_record",
        "ac_display_wlan_ap_all_radio_type",
        "ac_display_wlan_ap_all_verbose",
        "ac_display_wlan_ap_name_verbose",
    } <= set(ids)
    assert sum(1 for item in items if not item["is_cli"]) >= 1
    assert not any(item["module"] == "SNMP 中心" for item in items)
    assert any(item["protocol"] == "RESTful/HTTPS" for item in items)


def test_command_reference_markdown_export_contains_commands():
    items = load_command_references(PathResolver(Path(__file__).resolve().parents[1]))
    markdown = export_command_references_markdown(items[:3])

    assert "# 软件使用命令清单导出" in markdown
    assert "| 类别 | 命令/接口 | 当前用途 |" in markdown
