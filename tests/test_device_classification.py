from __future__ import annotations

import pytest

from netconsole.models.device_classification import (
    CATALOG_VERSION,
    SMART_HUB_CATALOG,
    UNCLASSIFIED,
    classify_device,
    validate_classification_selection,
)


def test_smarthub_catalog_preserves_static_source_cardinality() -> None:
    assert CATALOG_VERSION == "smarthub-device-v1.0.9-r6"
    assert len(SMART_HUB_CATALOG) == 20
    assert len({category for categories in SMART_HUB_CATALOG.values() for category in categories}) == 8
    assert len({subcategory for categories in SMART_HUB_CATALOG.values() for values in categories.values() for subcategory in values}) == 26


@pytest.mark.parametrize(
    ("role", "subcategory"),
    (("AC", "WIRELESS"), ("Cloud-AP", "WIRELESS"), ("FAT-AP", "WIRELESS"), ("MR", "WIRELESS"), ("SW", "SWITCH")),
)
def test_h3c_network_roles_keep_business_identity(role: str, subcategory: str) -> None:
    classification = classify_device("H3C", role)

    assert classification.category_code == "NETWORK"
    assert classification.subcategory_code == subcategory
    assert classification.device_role == role


@pytest.mark.parametrize(("vendor", "role"), (("现场自研", "SW"), ("H3C", "Legacy-Unknown")))
def test_unknown_business_roles_remain_unclassified(vendor: str, role: str) -> None:
    classification = classify_device(vendor, role)

    assert classification.category_code == UNCLASSIFIED
    assert classification.subcategory_code == UNCLASSIFIED
    assert classification.device_role == role
    validate_classification_selection(vendor, UNCLASSIFIED, UNCLASSIFIED, role)


def test_non_round_trippable_smarthub_selection_is_rejected() -> None:
    with pytest.raises(ValueError, match="无法无损写入"):
        validate_classification_selection("H3C", "SERVER", "H3C_SERVER", "Other")


def test_mapped_role_cannot_be_downgraded_to_unclassified() -> None:
    with pytest.raises(ValueError, match="不能标记为未分类"):
        validate_classification_selection("H3C", UNCLASSIFIED, UNCLASSIFIED, "SW")
