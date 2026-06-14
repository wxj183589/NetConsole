from netconsole.utils.interface_sort import interface_sort_key


def test_interface_sort_key_orders_numeric_segments_logically():
    names = ["GigabitEthernet1/0/10", "GigabitEthernet1/0/2", "GigabitEthernet1/0/1"]

    assert sorted(names, key=interface_sort_key) == [
        "GigabitEthernet1/0/1",
        "GigabitEthernet1/0/2",
        "GigabitEthernet1/0/10",
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
