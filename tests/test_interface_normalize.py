import pytest

from netconsole.utils.interface_normalize import normalize_interface_name


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        ("GigabitEthernet 2/0/16", "GigabitEthernet2/0/16"),
        ("GigabitEthernet   2/0/16", "GigabitEthernet2/0/16"),
        ("GigabitEthernet2/0/16", "GigabitEthernet2/0/16"),
        ("Ten-GigabitEthernet 1/0/1", "Ten-GigabitEthernet1/0/1"),
        ("Bridge-Aggregation 10", "Bridge-Aggregation10"),
        ("Vlan-interface 100", "Vlan-interface100"),
        ("GE 2/0/16", "GigabitEthernet2/0/16"),
        ("XGE 1/0/1", "Ten-GigabitEthernet1/0/1"),
    ),
)
def test_normalize_interface_name_compacts_known_prefix_and_number(
    value, expected
):
    assert normalize_interface_name(value) == expected


def test_normalize_interface_name_preserves_identifier_separators():
    assert (
        normalize_interface_name("GigabitEthernet 2/0/16.100:1")
        == "GigabitEthernet2/0/16.100:1"
    )


@pytest.mark.parametrize(
    "value",
    (
        "GigabitEthernet 2/0/16 uplink to core",
        "uplink to core 1",
    ),
)
def test_normalize_interface_name_preserves_unrelated_whitespace(value):
    assert normalize_interface_name(value) == value
