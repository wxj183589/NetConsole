from __future__ import annotations

from copy import deepcopy

import pytest

from netconsole.core.database import Database
from netconsole.models.api.trackside_ap_business import ApManagementVlanGroupDTO
from netconsole.repositories.ap_management_vlan_repository import (
    ApManagementVlanRepository,
    ApManagementVlanRevisionConflict,
)
from netconsole.repositories.ac_repository import (
    AcRepository,
    TRACKSIDE_AP_PLAN_MODE,
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


def test_line_single_29_stations_vlan_71_is_valid_without_ip_references():
    draft = auto_group_draft(
        stations=_stations(29),
        planning_mode=LINE_SINGLE,
    )
    draft["groups"][0]["management_vlan"] = 71

    view = enrich_plan(draft, stations=_stations(29))

    assert view["valid"]
    assert len(view["groups"]) == 1
    assert view["groups"][0]["station_count"] == 29
    assert {row["management_vlan"] for row in view["station_details"]} == {71}


def test_vlan_planning_does_not_generate_addresses():
    draft, stations, aps = _configured([2, 2])
    allocations, issues, _assignments = allocate_addresses(
        draft, stations=stations, aps=aps
    )
    assert not issues
    assert [row["planned_ip"] for row in allocations] == ["", "", "", ""]


@pytest.mark.parametrize(
    "mutator",
    [
        lambda draft: draft["groups"][0].update(
            network_address="",
            prefix_length=None,
            subnet_mask="",
            default_gateway="",
            ap_start_ip="",
            ap_end_ip="",
        ),
        lambda draft: draft["groups"][0].update(
            network_address="10.92.68.0",
            prefix_length=22,
            subnet_mask="255.255.252.0",
            default_gateway="10.92.71.254",
            ap_start_ip="192.0.2.9",
            ap_end_ip="not-an-ip",
        ),
        lambda draft: draft["groups"][0].update(
            network_address="invalid reference",
            prefix_length=99,
            subnet_mask="invalid mask",
            default_gateway="invalid gateway",
            ap_start_ip="invalid start",
        ),
    ],
)
def test_ip_reference_fields_never_block_vlan_planning(mutator):
    draft, stations, aps = _configured([2])
    mutator(draft)
    view = enrich_plan(draft, stations=stations, aps=aps)
    assert view["valid"]
    assert not any(
        issue["field_name"]
        in {
            "network_address",
            "prefix_length",
            "subnet_mask",
            "default_gateway",
            "ap_start_ip",
            "ap_end_ip",
            "planned_ip",
        }
        for issue in view["issues"]
    )


@pytest.mark.parametrize("prefix_length", [99, "invalid-prefix"])
def test_group_api_accepts_empty_or_invalid_ip_references(prefix_length):
    group = ApManagementVlanGroupDTO.model_validate(
        {
            "group_id": "g1",
            "group_code": "G001",
            "group_name": "参考字段兼容组",
            "management_vlan": 71,
            "network_address": None,
            "prefix_length": prefix_length,
            "subnet_mask": None,
            "default_gateway": None,
            "ap_start_ip": None,
            "ap_end_ip": None,
        }
    )

    assert group.management_vlan == 71
    assert group.prefix_length == prefix_length
    assert group.default_gateway is None


def test_invalid_and_duplicate_ap_reference_ips_are_non_blocking():
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
    draft["allocations"][0]["planned_ip"] = "not-an-ip"
    draft["allocations"][1]["planned_ip"] = "not-an-ip"

    view = enrich_plan(draft, stations=stations, aps=aps)

    assert view["valid"]
    assert [row["planned_ip"] for row in view["allocations"]] == [
        "not-an-ip",
        "not-an-ip",
    ]


def test_repeated_vlan_is_warning_and_not_blocking():
    draft, stations, aps = _configured([1, 1])
    draft["groups"][1]["management_vlan"] = 71
    view = enrich_plan(draft, stations=stations, aps=aps)
    repeated = [
        issue for issue in view["issues"] if issue["code"] == "MANAGEMENT_VLAN_REUSED"
    ]
    assert repeated and not repeated[0]["blocking"]
    assert view["valid"]


@pytest.mark.parametrize("management_vlan", [None, 0, 4095, "invalid"])
def test_management_vlan_is_required_and_range_checked(management_vlan):
    draft, stations, aps = _configured([1])
    draft["groups"][0]["management_vlan"] = management_vlan

    issues = validate_plan(draft, stations=stations, aps=aps)

    assert any(
        issue["code"] == "MANAGEMENT_VLAN_INVALID" and issue["blocking"]
        for issue in issues
    )


@pytest.mark.parametrize("management_vlan", [None, 71])
def test_zero_ap_group_allows_empty_or_valid_management_vlan(management_vlan):
    draft, stations, aps = _configured([1])
    stations[0]["ap_count"] = 0
    draft["groups"][0]["members"][0]["ap_count"] = 0
    draft["groups"][0]["management_vlan"] = management_vlan

    issues = validate_plan(draft, stations=stations, aps=aps)

    assert not [issue for issue in issues if issue["code"] == "MANAGEMENT_VLAN_INVALID"]


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
        "management_ip": "not-an-ip-reference",
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
    assert point["ap_ip"] == "not-an-ip-reference"


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


def test_pvid_verification_falls_back_to_ap_station_plan():
    plan = {
        "ap_networks_by_mac": {},
        "ap_networks_by_name": {},
        "station_vlans_by_id": {
            "station-1": {921},
            "station-2": {921},
        },
        "station_vlans": {},
    }

    matched = effective_pvid_plan(
        ap_mac="",
        ap_name="AP-01",
        station_id="station-1",
        pvid=921,
        active_plan=plan,
    )
    mismatched = effective_pvid_plan(
        ap_mac="",
        ap_name="AP-02",
        station_id="station-1",
        pvid=922,
        active_plan=plan,
    )

    assert matched["planned_management_vlan"] == 921
    assert matched["pvid_plan_status"] == "matched"
    assert mismatched["pvid_plan_status"] == "mismatched"


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


def test_trackside_station_plan_migration_repairs_duplicate_sequences(tmp_path):
    database = Database(tmp_path / "site.db")
    database.initialize()
    repository = AcRepository(database)
    repository.replace_trackside_ap_plan_rows(
        TRACKSIDE_AP_PLAN_MODE,
        [
            {"station_name": "站点A", "sequence_no": 1, "ap_count": 1, "management_vlan": 71},
            {"station_name": "站点B", "sequence_no": 2, "ap_count": 1, "management_vlan": 71},
            {"station_name": "站点C", "sequence_no": 3, "ap_count": 0, "management_vlan": 72},
        ],
    )
    with database.connect() as connection:
        connection.execute("DROP INDEX idx_trackside_plan_sequence")
        connection.execute(
            """
            UPDATE ac_trackside_ap_plan
            SET sequence_no = CASE station_name
                WHEN '站点A' THEN 1
                WHEN '站点B' THEN 1
                ELSE 0
            END,
            sort_order = CASE station_name
                WHEN '站点A' THEN 5
                WHEN '站点B' THEN 2
                ELSE 0
            END
            WHERE mode = 'unified'
            """
        )
        connection.commit()

    database.initialize()
    database.initialize()

    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT station_name, sequence_no, sort_order, management_vlan, ap_count
            FROM ac_trackside_ap_plan
            WHERE mode = 'unified'
            ORDER BY sequence_no
            """
        ).fetchall()
        indexes = {
            str(row["name"])
            for row in connection.execute("PRAGMA index_list(ac_trackside_ap_plan)")
        }
    assert [tuple(row) for row in rows] == [
        ("站点C", 1, 0, 72, 0),
        ("站点B", 2, 1, 71, 1),
        ("站点A", 3, 2, 71, 1),
    ]
    assert "idx_trackside_plan_sequence" in indexes


def test_allocation_reference_migration_removes_unique_ip_without_data_loss(
    tmp_path,
    monkeypatch,
):
    database = Database(tmp_path / "site.db")
    database.initialize()
    repository = ApManagementVlanRepository(database)
    draft, stations, aps = _configured([1])
    aps[0]["management_ip"] = "10.10.0.20"
    repository.replace(
        enrich_plan(draft, stations=stations, aps=aps),
        expected_revision=0,
    )
    with database.connect() as connection:
        connection.executescript(
            """
            ALTER TABLE rail_ap_vlan_allocations
            RENAME TO rail_ap_vlan_allocations_current;
            CREATE TABLE rail_ap_vlan_allocations (
                ap_id TEXT PRIMARY KEY,
                ap_name TEXT NOT NULL DEFAULT '',
                point_code TEXT NOT NULL DEFAULT '',
                station_id TEXT NOT NULL DEFAULT '',
                station_name TEXT NOT NULL DEFAULT '',
                section_name TEXT NOT NULL DEFAULT '',
                group_id TEXT NOT NULL,
                planned_ip TEXT NOT NULL,
                allocation_order INTEGER NOT NULL,
                is_manual INTEGER NOT NULL DEFAULT 0,
                is_locked INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL,
                group_source TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (group_id) REFERENCES rail_ap_vlan_groups(group_id) ON DELETE CASCADE,
                UNIQUE (planned_ip),
                CHECK (is_manual IN (0, 1)),
                CHECK (is_locked IN (0, 1))
            );
            INSERT INTO rail_ap_vlan_allocations
            SELECT * FROM rail_ap_vlan_allocations_current;
            DROP TABLE rail_ap_vlan_allocations_current;
            CREATE INDEX idx_rail_ap_vlan_allocations_group_order
            ON rail_ap_vlan_allocations(group_id, allocation_order);
            """
        )
        connection.commit()

    migrate = database._migrate_trackside_ap_vlan_allocation_references

    def fail_after_migration(connection):
        migrate(connection)
        raise RuntimeError("forced migration rollback")

    monkeypatch.setattr(
        database,
        "_migrate_trackside_ap_vlan_allocation_references",
        fail_after_migration,
    )
    with pytest.raises(RuntimeError, match="forced migration rollback"):
        database.initialize()
    with database.connect() as connection:
        rolled_back_definition = str(
            connection.execute(
                "SELECT sql FROM sqlite_master WHERE name = 'rail_ap_vlan_allocations'"
            ).fetchone()["sql"]
        )
        temporary_table = connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table'
              AND name = 'rail_ap_vlan_allocations_reference_migration'
            """
        ).fetchone()
        rolled_back_ip = connection.execute(
            "SELECT planned_ip FROM rail_ap_vlan_allocations"
        ).fetchone()["planned_ip"]
    assert "UNIQUE(PLANNED_IP)" in "".join(rolled_back_definition.upper().split())
    assert temporary_table is None
    assert rolled_back_ip == "10.10.0.20"

    migrated_database = Database(database.path)
    migrated_database.initialize()
    migrated_database.initialize()

    persisted = repository.get_draft()
    assert persisted["allocations"][0]["planned_ip"] == "10.10.0.20"
    with database.connect() as connection:
        definition = str(
            connection.execute(
                "SELECT sql FROM sqlite_master WHERE name = 'rail_ap_vlan_allocations'"
            ).fetchone()["sql"]
        )
    assert "UNIQUE(PLANNED_IP)" not in "".join(definition.upper().split())


def test_mode_switch_preserves_existing_ap_ip_references():
    draft, stations, aps = _configured([1, 1])
    draft["allocations"] = [
        {
            "ap_id": ap["id"],
            "group_id": f"g{index + 1}",
            "planned_ip": f"reference-{index + 1}",
            "allocation_order": 0,
        }
        for index, ap in enumerate(aps)
    ]

    regrouped = auto_group_draft(
        stations=stations,
        planning_mode=LINE_SINGLE,
        current_draft=draft,
    )
    regrouped["groups"][0]["management_vlan"] = 71
    view = enrich_plan(regrouped, stations=stations, aps=aps)

    assert [row["planned_ip"] for row in view["allocations"]] == [
        "reference-1",
        "reference-2",
    ]
    assert {row["group_id"] for row in view["allocations"]} == {
        view["groups"][0]["group_id"]
    }


def test_current_ap_ip_takes_priority_over_legacy_allocation_reference():
    draft, stations, aps = _configured([1])
    draft["allocations"] = [
        {
            "ap_id": aps[0]["id"],
            "group_id": "g1",
            "planned_ip": "legacy-reference",
            "allocation_order": 0,
            "source": "manual",
        }
    ]
    aps[0]["management_ip"] = "current-ap-reference"

    view = enrich_plan(draft, stations=stations, aps=aps)

    assert view["allocations"][0]["planned_ip"] == "current-ap-reference"
    assert view["allocations"][0]["source"] == "existing_ap"


def test_point_table_blocks_only_unresolved_vlan_group_not_ip_reference():
    draft, stations, aps = _configured([1])
    aps[0]["station"] = "不存在的站点"
    aps[0]["management_ip"] = "invalid-ip-reference"

    with pytest.raises(ValueError, match="无法确定有效管理 VLAN 组"):
        build_point_table_rows(draft, stations=stations, aps=aps)

    assert enrich_plan(draft, stations=stations, aps=aps)["valid"]


def test_repository_accepts_duplicate_reference_ips_and_keeps_revision_control(
    tmp_path,
):
    database = Database(tmp_path / "site.db")
    database.initialize()
    repository = ApManagementVlanRepository(database)
    draft, stations, aps = _configured([2])
    for ap in aps:
        ap["management_ip"] = "10.10.0.20"
    view = enrich_plan(draft, stations=stations, aps=aps)
    revision = repository.replace(view, expected_revision=0)
    persisted = repository.get_draft()

    assert [row["planned_ip"] for row in persisted["allocations"]] == [
        "10.10.0.20",
        "10.10.0.20",
    ]
    with database.connect() as connection:
        definition = str(
            connection.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'rail_ap_vlan_allocations'"
            ).fetchone()["sql"]
        )
    assert "UNIQUE(PLANNED_IP)" not in "".join(definition.upper().split())

    stale = deepcopy(view)
    stale["planning"]["revision"] = revision
    next_revision = repository.replace(stale, expected_revision=revision)
    with pytest.raises(ApManagementVlanRevisionConflict):
        repository.replace(stale, expected_revision=revision)

    persisted = repository.get_draft()
    assert persisted["planning"]["revision"] == next_revision
    assert len(persisted["allocations"]) == 2
