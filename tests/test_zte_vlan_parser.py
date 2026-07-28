from __future__ import annotations

from pathlib import Path

from netconsole.parsers.zte.vlan import (
    MAX_EXPANDED_INTERFACES,
    expand_interface_list,
    merge_interface_vlan_facts,
    parse_switchvlan_running_config,
    parse_vlan_table,
)


FIXTURES = Path(__file__).parent / "fixtures" / "zte"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _interfaces(*names: str) -> list[dict[str, object | None]]:
    return [
        {
            "interface_name": name,
            "link_status": "UP",
            "media_type": "optical",
            "collected_at": "2026-07-28T12:00:00+00:00",
        }
        for name in names
    ]


def test_parse_switchvlan_hybrid_native_tagged_and_unknown_line() -> None:
    parsed = parse_switchvlan_running_config(
        _fixture("hzdt10_show_running_config_switchvlan.txt")
    )

    assert parsed.status == "OK"
    assert len(parsed.value) == 4
    first = parsed.value[0]
    assert first["interface_name"] == "gei-0/3/0/1"
    assert first["port_mode"] == "hybrid"
    assert first["port_status"] == "hybrid"
    assert first["pvid"] == "71"
    assert first["native_vlan"] == "71"
    assert first["tagged_vlans"] == ["201"]
    assert first["untagged_vlans"] == []
    assert first["pvid_source"] == "show_running_config_switchvlan"
    assert any("未识别 switchport" in warning for warning in parsed.warnings)
    access = parsed.value[2]
    assert access["port_mode"] == "access"
    assert access["pvid"] == "30"
    assert access["untagged_vlans"] == ["30"]
    trunk = parsed.value[3]
    assert trunk["port_mode"] == "trunk"
    assert len(trunk["tagged_vlans"]) == 4093
    assert trunk["tagged_vlans"][0] == "2"
    assert trunk["tagged_vlans"][-1] == "4094"
    assert trunk["native_vlan"] == "71"
    assert trunk["pvid"] is None


def test_switchvlan_dollar_ends_each_interface_block() -> None:
    parsed = parse_switchvlan_running_config(
        """
switchvlan-configuration
 interface gei-0/3/0/1
  switchport mode hybrid
 $
 switchport hybrid native vlan 99
 interface xgei-0/4/0/1
  switchport mode trunk
 $
"""
    )

    assert [item["interface_name"] for item in parsed.value] == [
        "gei-0/3/0/1",
        "xgei-0/4/0/1",
    ]
    assert parsed.value[0]["pvid"] is None
    assert parsed.value[1]["port_mode"] == "trunk"


def test_switchvlan_supports_multiple_vlan_lines_and_safe_ranges() -> None:
    parsed = parse_switchvlan_running_config(
        """
switchvlan-configuration
 interface cgei-0/1/0/1
  switchport mode hybrid
  switchport hybrid vlan 10,12-14 tag
  switchport hybrid vlan 20 to 21 tag
 $
"""
    )

    assert parsed.value[0]["tagged_vlans"] == [
        "10",
        "12",
        "13",
        "14",
        "20",
        "21",
    ]


def test_parse_vlan_table_uses_columns_and_continuations() -> None:
    parsed = parse_vlan_table(_fixture("hzdt10_show_vlan.txt"))

    assert parsed.status == "OK"
    vlan30 = next(item for item in parsed.value if item["vlan_id"] == 30)
    vlan71 = next(item for item in parsed.value if item["vlan_id"] == 71)
    vlan201 = next(item for item in parsed.value if item["vlan_id"] == 201)
    assert len(vlan30["pvid_ports"]) == 24
    assert vlan30["pvid_ports"][0] == "gei-0/4/0/25"
    assert vlan30["pvid_ports"][-1] == "gei-0/4/0/48"
    assert len(vlan71["pvid_ports"]) == 64
    assert "gei-0/4/0/9" in vlan71["pvid_ports"]
    assert "gei-0/4/0/24" in vlan71["pvid_ports"]
    assert "xgei-0/4/0/1" in vlan71["tagged_ports"]
    assert set(vlan71["pvid_ports"]).isdisjoint(vlan71["tagged_ports"])
    assert "gei-0/3/0/1" in vlan201["tagged_ports"]
    assert not vlan201["pvid_ports"]


def test_parse_vlan_id_output_uses_same_columns_without_hardcoding_vlan() -> None:
    parsed = parse_vlan_table(_fixture("hzdt10_show_vlan_id_71.txt"))

    assert parsed.status == "OK"
    assert len(parsed.value) == 1
    vlan = parsed.value[0]
    assert vlan["vlan_id"] == 71
    assert len(vlan["pvid_ports"]) == 64
    assert vlan["pvid_ports"][0] == "gei-0/3/0/1"
    assert vlan["pvid_ports"][-1] == "gei-0/4/0/24"
    assert len(vlan["tagged_ports"]) == 8


def test_interface_range_preserves_full_prefix_and_rejects_unsafe_ranges() -> None:
    expanded, warnings = expand_interface_list("gei-0/3/0/1-48")
    assert len(expanded) == 48
    assert expanded[0] == "gei-0/3/0/1"
    assert expanded[-1] == "gei-0/3/0/48"
    assert not warnings

    descending, descending_warnings = expand_interface_list("xgei-0/4/0/8-1")
    assert descending == []
    assert any("倒序" in warning for warning in descending_warnings)

    too_large, limit_warnings = expand_interface_list(
        f"gei-0/3/0/1-{MAX_EXPANDED_INTERFACES + 1}"
    )
    assert too_large == []
    assert any("安全上限" in warning for warning in limit_warnings)


def test_merge_prefers_switchvlan_and_verifies_matching_vlan_table() -> None:
    switch = parse_switchvlan_running_config(
        _fixture("hzdt10_show_running_config_switchvlan.txt")
    )
    table = parse_vlan_table(_fixture("hzdt10_show_vlan.txt"))
    merged = merge_interface_vlan_facts(
        _interfaces("gei-0/3/0/1", "xgei-0/4/0/1"),
        switch,
        table,
    )

    first = merged.interfaces[0]
    assert first["port_status"] == "hybrid"
    assert first["media_type"] == "optical"
    assert first["pvid"] == "71"
    assert first["native_vlan"] == "71"
    assert first["tagged_vlans"] == ["201"]
    assert first["pvid_source"] == "show_running_config_switchvlan"
    assert first["pvid_verified"] is True
    assert first["vlan"] == "Native/PVID 71；Tagged 201"
    xgei = merged.interfaces[1]
    assert xgei["pvid"] is None
    assert len(xgei["tagged_vlans"]) == 4093
    assert xgei["vlan"] == "Native 71；Tagged 2-4094"


def test_merge_conflict_keeps_switchvlan_and_records_structured_warning() -> None:
    switch = parse_switchvlan_running_config(
        """
switchvlan-configuration
 interface gei-0/3/0/1
  switchport mode hybrid
  switchport hybrid native vlan 71
 $
"""
    )
    table = parse_vlan_table(
        """
VLAN     Name     PvidPorts           UntagPorts          TagPorts
30       vlan0030 gei-0/3/0/1
"""
    )
    merged = merge_interface_vlan_facts(
        _interfaces("gei-0/3/0/1"),
        switch,
        table,
    )

    assert merged.interfaces[0]["pvid"] == "71"
    assert merged.interfaces[0]["pvid_verified"] is False
    assert merged.stats["conflict_count"] == 1
    warning = next(
        item for item in merged.warnings if item["code"] == "ZTE_PVID_SOURCE_CONFLICT"
    )
    assert warning == {
        "code": "ZTE_PVID_SOURCE_CONFLICT",
        "interface_name": "gei-0/3/0/1",
        "switchvlan_pvid": "71",
        "vlan_table_pvid": "30",
        "selected_pvid": "71",
        "selected_source": "show_running_config_switchvlan",
    }


def test_merge_uses_vlan_table_fallback_and_never_uses_tag_ports_as_pvid() -> None:
    table = parse_vlan_table(_fixture("hzdt10_show_vlan.txt"))
    merged = merge_interface_vlan_facts(
        _interfaces("gei-0/4/0/25", "xgei-0/4/0/1"),
        None,
        table,
    )

    assert merged.interfaces[0]["pvid"] == "30"
    assert merged.interfaces[0]["pvid_source"] == "show_vlan_pvid_ports"
    assert merged.interfaces[1]["pvid"] is None
    assert merged.interfaces[1]["tagged_vlans"] == ["30", "71"]


def test_merge_preserves_previous_stable_fields_when_both_vlan_commands_fail() -> None:
    previous = [
        {
            "interface_name": "gei-0/3/0/1",
            "port_mode": "hybrid",
            "port_status": "hybrid",
            "pvid": "71",
            "native_vlan": "71",
            "tagged_vlans": '["201"]',
            "untagged_vlans": "[]",
            "vlan_config_collected_at": "2026-07-27T12:00:00+00:00",
        }
    ]
    failed = parse_vlan_table("Invalid command")
    merged = merge_interface_vlan_facts(
        _interfaces("gei-0/3/0/1"),
        None,
        failed,
        previous,
    )
    item = merged.interfaces[0]

    assert item["link_status"] == "UP"
    assert item["port_status"] == "hybrid"
    assert item["pvid"] == "71"
    assert item["tagged_vlans"] == ["201"]
    assert item["pvid_source"] == "previous_snapshot"
    assert item["vlan_config_status"] == "inherited"
    assert item["vlan_config_collected_at"] == "2026-07-27T12:00:00+00:00"


def test_vlan_success_does_not_create_interfaces_without_interface_brief() -> None:
    table = parse_vlan_table(_fixture("hzdt10_show_vlan.txt"))
    merged = merge_interface_vlan_facts([], None, table)
    assert merged.interfaces == []
