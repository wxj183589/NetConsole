from __future__ import annotations

from copy import deepcopy

import pytest

from netconsole.core.database import Database
from netconsole.repositories.ap_management_vlan_repository import (
    ApManagementVlanRepository,
)
from netconsole.services.rail_transit.ap_management_vlan_planning import (
    LINE_SINGLE,
    STATION_GROUPED,
    STATION_INDEPENDENT,
    allocate_addresses,
    auto_group_draft,
    build_point_table_rows,
    effective_network,
    enrich_plan,
    validate_plan,
)
from netconsole.services.trackside_ap_business import effective_pvid_plan


def _stations(count: int) -> list[dict[str, object]]:
    return [
        {
            "id": f"s{index + 1}",
            "name": f"{index + 1:02d}站",
            "sort_order": index,
            "ap_count": 1,
            "enabled": True,
        }
        for index in range(count)
    ]


def _aps(count: int) -> list[dict[str, object]]:
    return [
        {
            "id": f"ap:{index + 1}",
            "name": f"AP-{index + 1:02d}",
            "point_code": f"P{index + 1:02d}",
            "station": f"{index + 1:02d}站",
            "section": "",
        }
        for index in range(count)
    ]


def _configured(
    sizes: list[int],
    *,
    mode: str = STATION_GROUPED,
    aps_per_station: int = 1,
) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]]]:
    stations = _stations(sum(sizes))
    aps = _aps(sum(sizes) * aps_per_station)
    if aps_per_station != 1:
        aps = []
        ap_index = 1
        for station in stations:
            station["ap_count"] = aps_per_station
            for point in range(aps_per_station):
                aps.append(
                    {
                        "id": f"ap:{ap_index}",
                        "name": f"AP-{ap_index:02d}",
                        "point_code": f"P{point + 1:02d}",
                        "station": station["name"],
                    }
                )
                ap_index += 1
    draft = auto_group_draft(
        stations=stations,
        planning_mode=mode,
        auto_group_station_count=sizes[0] if sizes else 1,
    )
    offset = 0
    groups = []
    for index, size in enumerate(sizes):
        group = deepcopy(draft["groups"][0])
        group.update(
            group_id=f"g{index + 1}",
            group_code=f"G{index + 1:03d}",
            group_name=f"组{index + 1}",
            sequence=index,
            management_vlan=71 + index,
            network_address=f"10.10.{index}.0",
            prefix_length=24,
            subnet_mask="255.255.255.0",
            default_gateway=f"10.10.{index}.1",
            ap_start_ip=f"10.10.{index}.10",
            ap_end_ip="",
            members=[
                {
                    "station_id": station["id"],
                    "station_name": station["name"],
                    "station_sequence": station["sort_order"],
                    "ap_count": station["ap_count"],
                }
                for station in stations[offset : offset + size]
            ],
        )
        groups.append(group)
        offset += size
    draft["groups"] = groups
    draft["planning"]["planning_mode"] = mode
    return draft, stations, aps


@pytest.mark.parametrize(
    ("mode", "station_count", "chunk", "expected"),
    [
        (STATION_INDEPENDENT, 4, 1, [1, 1, 1, 1]),
        (LINE_SINGLE, 12, 1, [12]),
        (STATION_GROUPED, 2, 2, [2]),
        (STATION_GROUPED, 3, 3, [3]),
        (STATION_GROUPED, 4, 4, [4]),
        (STATION_GROUPED, 10, 4, [4, 4, 2]),
    ],
)
def test_auto_group_modes(
    mode: str, station_count: int, chunk: int, expected: list[int]
):
    draft = auto_group_draft(
        stations=_stations(station_count),
        planning_mode=mode,
        auto_group_station_count=chunk,
    )
    assert [len(group["members"]) for group in draft["groups"]] == expected


def test_irregular_groups_and_membership_validation():
    draft, stations, _aps_rows = _configured([1, 3, 4, 2])
    assert not [
        issue
        for issue in validate_plan(draft, stations=stations)
        if issue["code"].startswith("STATION_")
    ]

    missing = deepcopy(draft)
    missing["groups"][-1]["members"].pop()
    assert "STATION_UNASSIGNED" in {
        issue["code"] for issue in validate_plan(missing, stations=stations)
    }

    duplicate = deepcopy(draft)
    duplicate["groups"][1]["members"].append(
        deepcopy(duplicate["groups"][0]["members"][0])
    )
    assert "STATION_ASSIGNED_MULTIPLE_GROUPS" in {
        issue["code"] for issue in validate_plan(duplicate, stations=stations)
    }

    discontinuous = deepcopy(draft)
    discontinuous["groups"][1]["members"] = [
        deepcopy(draft["groups"][1]["members"][0]),
        deepcopy(draft["groups"][1]["members"][2]),
    ]
    assert "VLAN_GROUP_NOT_CONTIGUOUS" in {
        issue["code"] for issue in validate_plan(discontinuous, stations=stations)
    }


def test_group_size_limit_and_line_single_exception():
    grouped, stations, _ = _configured([4, 1])
    grouped["groups"][0]["members"].extend(grouped["groups"][1]["members"])
    grouped["groups"] = grouped["groups"][:1]
    assert "VLAN_GROUP_TOO_LARGE" in {
        issue["code"] for issue in validate_plan(grouped, stations=stations)
    }
    grouped["planning"]["planning_mode"] = LINE_SINGLE
    assert "VLAN_GROUP_TOO_LARGE" not in {
        issue["code"] for issue in validate_plan(grouped, stations=stations)
    }


def test_addresses_are_continuous_inside_group_and_restart_for_next_group():
    draft, stations, aps = _configured([2, 2])
    allocations, issues, _assignments = allocate_addresses(
        draft, stations=stations, aps=aps
    )
    assert not issues
    assert [row["planned_ip"] for row in allocations] == [
        "10.10.0.10",
        "10.10.0.11",
        "10.10.1.10",
        "10.10.1.11",
    ]


@pytest.mark.parametrize(
    ("mutator", "expected"),
    [
        (
            lambda draft: draft["groups"][0].update(
                network_address="10.10.0.8",
                prefix_length=30,
                default_gateway="10.10.0.9",
                ap_start_ip="10.10.0.10",
            ),
            "ADDRESS_CAPACITY_INSUFFICIENT",
        ),
        (
            lambda draft: draft["groups"][0].update(ap_start_ip="10.10.0.0"),
            "AP_START_IP_RESERVED",
        ),
        (
            lambda draft: draft["groups"][0].update(ap_start_ip="10.10.0.255"),
            "AP_START_IP_RESERVED",
        ),
        (
            lambda draft: draft["groups"][0].update(ap_start_ip="10.10.0.1"),
            "AP_START_EQUALS_GATEWAY",
        ),
    ],
)
def test_address_validation(mutator, expected: str):
    draft, stations, aps = _configured([2])
    mutator(draft)
    assert expected in {
        issue["code"] for issue in validate_plan(draft, stations=stations, aps=aps)
    }


def test_locked_duplicate_ip_is_blocking():
    draft, stations, aps = _configured([2])
    draft["allocations"] = [
        {
            "ap_id": ap["id"],
            "group_id": "g1",
            "planned_ip": "10.10.0.20",
            "allocation_order": index,
            "is_manual": True,
            "is_locked": True,
            "source": "manual",
        }
        for index, ap in enumerate(aps)
    ]
    codes = {
        issue["code"] for issue in validate_plan(draft, stations=stations, aps=aps)
    }
    assert "AP_IP_DUPLICATE" in codes


def test_repeated_vlan_is_warning_and_not_blocking():
    draft, stations, aps = _configured([1, 1])
    draft["groups"][1]["management_vlan"] = 71
    view = enrich_plan(draft, stations=stations, aps=aps)
    repeated = [
        issue for issue in view["issues"] if issue["code"] == "MANAGEMENT_VLAN_REUSED"
    ]
    assert repeated and not repeated[0]["blocking"]
    assert view["valid"]


def test_high_address_reservation_and_utilization_are_warnings():
    reserved, stations, _aps = _configured([1])
    reserved["groups"][0]["ap_start_ip"] = "10.10.0.200"
    reserved_issues = validate_plan(reserved, stations=stations)
    assert any(
        issue["code"] == "ADDRESS_RESERVATION_HIGH" and not issue["blocking"]
        for issue in reserved_issues
    )

    utilized, stations, _aps = _configured([4])
    utilized["groups"][0]["network_address"] = "10.10.0.0"
    utilized["groups"][0]["prefix_length"] = 29
    utilized["groups"][0]["default_gateway"] = "10.10.0.1"
    utilized["groups"][0]["ap_start_ip"] = "10.10.0.3"
    utilized_issues = validate_plan(utilized, stations=stations)
    assert any(
        issue["code"] == "ADDRESS_UTILIZATION_HIGH" and not issue["blocking"]
        for issue in utilized_issues
    )


def test_new_station_is_unassigned_and_deleted_member_cannot_remain_hidden():
    draft, stations, aps = _configured([1, 1])
    added = [
        *stations,
        {
            "id": "station:2",
            "name": "03站",
            "sort_order": 2,
            "ap_count": 0,
        },
    ]
    added_issues = validate_plan(draft, stations=added, aps=aps)
    assert any(
        issue["code"] == "STATION_UNASSIGNED"
        and issue["station_id"] == "station:2"
        for issue in added_issues
    )

    remaining_stations = [stations[1]]
    remaining_draft = deepcopy(draft)
    remaining_draft["groups"] = [remaining_draft["groups"][1]]
    remaining_draft["groups"][0]["sequence"] = 0
    remaining_view = enrich_plan(
        remaining_draft,
        stations=remaining_stations,
        aps=[aps[1]],
    )
    assert remaining_view["station_details"][0]["station_id"] == "s2"
    assert not any(
        issue["code"] in {"STATION_MEMBER_UNKNOWN", "STATION_UNASSIGNED"}
        for issue in remaining_view["issues"]
    )

    stale_issues = validate_plan(draft, stations=remaining_stations, aps=[aps[1]])
    assert any(issue["code"] == "STATION_MEMBER_UNKNOWN" for issue in stale_issues)


def test_stable_station_id_preserves_membership_after_station_rename():
    draft, stations, _aps = _configured([1])
    renamed_stations = [{**stations[0], "name": "重命名站"}]

    view = enrich_plan(draft, stations=renamed_stations, aps=[])

    member = view["groups"][0]["members"][0]
    assert member["station_id"] == "s1"
    assert member["station_name"] == "重命名站"
    assert not any(
        issue["code"] in {"STATION_MEMBER_UNKNOWN", "STATION_UNASSIGNED"}
        for issue in view["issues"]
    )


def test_interval_default_ap_override_point_table_and_effective_network():
    draft, stations, aps = _configured([1, 1])
    interval_ap = {
        "id": "ap:interval",
        "name": "区间 AP",
        "point_code": "I01",
        "station": "",
        "section": "01站-02站",
        "section_start_station": "01站",
    }
    aps.append(interval_ap)
    view = enrich_plan(draft, stations=stations, aps=aps)
    interval = next(row for row in view["allocations"] if row["ap_id"] == "ap:interval")
    assert interval["group_id"] == "g1"
    assert interval["group_source"] == "interval_start_default"
    assert interval["station_id"] == ""
    assert any(row["target_id"] == "ap:interval" for row in view["assignments"])

    draft = {
        key: view[key] for key in ("planning", "groups", "assignments", "allocations")
    }
    draft["assignments"].append(
        {
            "assignment_id": "section-default",
            "assignment_type": "section_default",
            "target_id": "section:01站-02站",
            "group_id": "g2",
            "source": "section_default",
        }
    )
    section_overridden = enrich_plan(draft, stations=stations, aps=aps)
    interval = next(
        row
        for row in section_overridden["allocations"]
        if row["ap_id"] == "ap:interval"
    )
    assert interval["group_id"] == "g2"
    assert interval["group_source"] == "section_default"
    assert interval["station_id"] == ""
    section_network = effective_network(
        section_overridden,
        stations=stations,
        ap_id="ap:interval",
    )
    assert section_network and section_network["management_vlan"] == 72
    assert section_network["source"] == "section_default"

    draft = {
        key: section_overridden[key]
        for key in ("planning", "groups", "assignments", "allocations")
    }
    draft["assignments"].append(
        {
            "assignment_id": "override",
            "assignment_type": "ap_override",
            "target_id": "ap:interval",
            "group_id": "g1",
            "source": "ap_override",
        }
    )
    overridden = enrich_plan(draft, stations=stations, aps=aps)
    interval = next(
        row for row in overridden["allocations"] if row["ap_id"] == "ap:interval"
    )
    assert interval["group_id"] == "g1"
    assert interval["group_source"] == "ap_override"
    network = effective_network(overridden, stations=stations, ap_id="ap:interval")
    assert network and network["management_vlan"] == 71
    point = next(
        row
        for row in build_point_table_rows(overridden, stations=stations, aps=aps)
        if row["ap_id"] == "ap:interval"
    )
    assert point["vlan_group_id"] == "g1"
    assert point["management_vlan"] == 71


def test_pvid_verification_uses_effective_ap_group():
    plan = {
        "ap_networks_by_mac": {
            "001122334455": {
                "vlan_group_id": "g1",
                "vlan_group_name": "01～04站",
                "management_vlan": 71,
            }
        },
        "ap_networks_by_name": {},
    }
    result = effective_pvid_plan(
        ap_mac="00:11:22:33:44:55",
        ap_name="AP-01",
        pvid=71,
        active_plan=plan,
    )
    assert result["pvid_plan_status"] == "matched"
    assert result["vlan_group_id"] == "g1"


def test_database_migration_is_idempotent_and_preserves_legacy_values(tmp_path):
    database = Database(tmp_path / "site.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO ac_trackside_ap_plan (
                mode, station_name, ap_count, ap_start_address, mask_length,
                ap_gateway, ap_management_vlans, remark, sort_order,
                created_at, updated_at
            )
            VALUES ('unified', '01站', 2, '10.10.1.10', 24,
                    '10.10.1.1', '71', '原规划', 0, 'now', 'now')
            """
        )
        connection.commit()
    database.initialize()
    database.initialize()
    draft = ApManagementVlanRepository(database).get_draft()
    assert draft["planning"]["planning_mode"] == STATION_INDEPENDENT
    assert len(draft["groups"]) == 1
    assert draft["groups"][0]["management_vlan"] == 71
    assert draft["groups"][0]["ap_start_ip"] == "10.10.1.10"
    assert draft["groups"][0]["default_gateway"] == "10.10.1.1"


def test_repository_save_failure_rolls_back_the_whole_revision(tmp_path):
    database = Database(tmp_path / "site.db")
    database.initialize()
    repository = ApManagementVlanRepository(database)
    draft, stations, aps = _configured([2])
    view = enrich_plan(draft, stations=stations, aps=aps)
    revision = repository.replace(view, expected_revision=0)
    broken = deepcopy(view)
    broken["planning"]["revision"] = revision
    broken["allocations"][1]["planned_ip"] = broken["allocations"][0]["planned_ip"]
    with pytest.raises(Exception):
        repository.replace(broken, expected_revision=revision)
    persisted = repository.get_draft()
    assert persisted["planning"]["revision"] == revision
    assert len({row["planned_ip"] for row in persisted["allocations"]}) == 2
