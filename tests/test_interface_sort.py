from netconsole.utils.interface_sort import interface_sort_key


def test_interface_sort_key_orders_numeric_segments_logically():
    names = [
        "GigabitEthernet1/0/43",
        "GigabitEthernet1/0/11",
        "GigabitEthernet1/0/10",
        "GigabitEthernet1/0/9",
        "GigabitEthernet1/0/2",
        "GigabitEthernet1/0/1",
    ]

    assert sorted(names, key=interface_sort_key) == [
        "GigabitEthernet1/0/1",
        "GigabitEthernet1/0/2",
        "GigabitEthernet1/0/9",
        "GigabitEthernet1/0/10",
        "GigabitEthernet1/0/11",
        "GigabitEthernet1/0/43",
    ]


def test_interface_sort_key_accepts_common_h3c_prefixes_and_empty_values():
    names = [None, "Bridge-Aggregation1", "Vlan-interface10", "XGE1/0/1", "GE1/0/1", "Route-Aggregation1"]

    assert sorted(names, key=interface_sort_key) == [
        "Vlan-interface10",
        "Bridge-Aggregation1",
        "Route-Aggregation1",
        "GE1/0/1",
        "XGE1/0/1",
        None,
    ]


def test_interface_sort_key_normalizes_vendor_aliases_and_subinterfaces():
    names = [
        "GEI-0/3/0/10",
        "GigabitEthernet0/3/0/2.10",
        "gei-0/3/0/2",
        "GigabitEthernet0/3/0/2.2",
        "gei-0/3/0/1",
    ]

    assert sorted(names, key=interface_sort_key) == [
        "gei-0/3/0/1",
        "gei-0/3/0/2",
        "GigabitEthernet0/3/0/2.2",
        "GigabitEthernet0/3/0/2.10",
        "GEI-0/3/0/10",
    ]


def test_interface_sort_key_supports_common_interface_types():
    names = [
        "Ten-GigabitEthernet1/0/10",
        "XGigabitEthernet1/0/1",
        "Ethernet1/1",
        "Eth-Trunk1",
        "Bridge-Aggregation10",
        "LoopBack0",
        "Vlan-interface100",
    ]

    ordered = sorted(names, key=interface_sort_key)

    assert ordered == [
        "Vlan-interface100",
        "Eth-Trunk1",
        "Bridge-Aggregation10",
        "LoopBack0",
        "Ethernet1/1",
        "XGigabitEthernet1/0/1",
        "Ten-GigabitEthernet1/0/10",
    ]


def test_interface_sort_key_puts_invalid_and_empty_names_last_naturally():
    names = [None, "???10", "", "GE1/0/2", "???2", " "]

    assert sorted(names, key=interface_sort_key) == [
        "GE1/0/2",
        "???2",
        "???10",
        None,
        "",
        " ",
    ]


def test_interface_sort_key_keeps_equal_names_stable_and_case_insensitive():
    rows = [
        ("GigabitEthernet1/0/1", "first"),
        ("GE1/0/1", "second"),
        ("gei-1/0/1", "third"),
        ("GIGABITETHERNET1/0/1", "fourth"),
    ]

    assert [
        marker for _name, marker in sorted(rows, key=lambda row: interface_sort_key(row[0]))
    ] == ["first", "second", "third", "fourth"]
