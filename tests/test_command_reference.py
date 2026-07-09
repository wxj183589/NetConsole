import json
from pathlib import Path

from PySide6.QtWidgets import QApplication

from netconsole.core.paths import PathResolver
from netconsole.services.command_reference_service import export_command_references_markdown, load_command_references


def app():
    return QApplication.instance() or QApplication([])


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
        "display saved-configuration",
        "save force",
        "display diagnostic-information",
        "n",
        "dir flash:/",
        "dir flash:/diagfile/",
        "ping <ip>",
        "ping -c <count> <ip>",
    }

    assert baseline <= set(by_command)
    assert by_command["save force"].risk_level == "config_write"
    assert by_command["n"].interactive_input is True
    assert by_command["n"].risk_level == "interactive"
    assert by_command["display transceiver diagnosis interface"].zte_adaptation_status == "phase_1_reference"


def test_command_reference_json_is_unique_and_has_non_cli_section():
    data = json.loads((Path(__file__).resolve().parents[1] / "resources" / "command_reference.json").read_text(encoding="utf-8"))
    items = data["items"]
    ids = [item["id"] for item in items]

    assert len(items) == 77
    assert len(ids) == len(set(ids))
    assert sum(1 for item in items if not item["is_cli"]) >= 7
    assert any(item["protocol"] == "SNMP" for item in items)
    assert any(item["protocol"] == "RESTful/HTTPS" for item in items)


def test_command_reference_markdown_export_contains_commands():
    items = load_command_references(PathResolver(Path(__file__).resolve().parents[1]))
    markdown = export_command_references_markdown(items[:3])

    assert "# 软件使用命令清单导出" in markdown
    assert "| 类别 | 命令/接口 | 当前用途 |" in markdown


def test_command_reference_page_loads_and_filters():
    from netconsole.ui.pages.command_reference_page import CommandReferencePage

    app()
    page = CommandReferencePage(PathResolver(Path(__file__).resolve().parents[1]))

    assert len(page.references) == 77
    assert page.table.rowCount() == 77
    page.search_edit.setText("save force")
    QApplication.processEvents()
    assert page.table.rowCount() == 1
    assert page.filtered_references[0].command_template == "save force"
