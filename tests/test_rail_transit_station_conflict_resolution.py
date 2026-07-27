from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from netconsole.application.rail_transit.base_data_application_service import (
    RailTransitBaseDataApplicationService,
)
from netconsole.backend.api.main import create_app
from netconsole.core.database import Database
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.repositories.rail_transit_base_data_repository import (
    RailTransitBaseDataConstraintError,
    RailTransitBaseDataRepository,
)
from netconsole.services.rail_transit.base_data_query_service import (
    RailTransitBaseDataQueryService,
)
from rail_transit_base_data_fixture import build_rail_transit_base_data_fixture


class _NoopAsyncService:
    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


def _app(paths, tmp_path: Path):
    return create_app(
        RuntimeMode.SERVER,
        paths=paths,
        task_service=object(),  # type: ignore[arg-type]
        agent_service=_NoopAsyncService(),  # type: ignore[arg-type]
        traffic_service=_NoopAsyncService(),  # type: ignore[arg-type]
        frontend_dist=tmp_path / "missing",
    )


def _station(query: RailTransitBaseDataQueryService, name: str):
    return next(
        item
        for item in query.list_stations("demo", page_size=200).items
        if item.name == name
    )


def _create_station(
    repository: RailTransitBaseDataRepository,
    *,
    name: str,
    code: str,
    sort_order: int,
    node_uid: str,
    source_kind: str = "manual",
    is_line_terminal: bool = False,
) -> None:
    values = RailTransitBaseDataApplicationService._station_values(
        {
            "name": name,
            "code": code,
            "sort_order": sort_order,
            "node_uid": node_uid,
            "node_type": "station",
            "path_code": "MAIN",
            "participates_in_direction": True,
            "source_kind": source_kind,
            "is_line_terminal": is_line_terminal,
        },
        "create",
    )
    repository.apply_base_data_changes(
        "demo",
        repository.base_data_revision("demo"),
        [
            {
                "entity_type": "station",
                "action": "create",
                "entity_id": f"new:{node_uid}",
                "values": values,
            }
        ],
    )


def _formalize_station(
    repository: RailTransitBaseDataRepository,
    query: RailTransitBaseDataQueryService,
    *,
    name: str,
    code: str,
    sort_order: int,
) -> None:
    current = _station(query, name)
    values = RailTransitBaseDataApplicationService._station_values(
        {
            **current.model_dump(),
            "old_name": current.name,
            "code": code,
            "sort_order": sort_order,
            "source_kind": "manual",
        },
        "update",
    )
    repository.apply_base_data_changes(
        "demo",
        repository.base_data_revision("demo"),
        [
            {
                "entity_type": "station",
                "action": "update",
                "entity_id": current.id,
                "values": values,
            }
        ],
    )


def test_station_delete_preflight_reports_safe_merge_and_blocked(
    tmp_path: Path,
) -> None:
    paths, _database = build_rail_transit_base_data_fixture(tmp_path)
    repository = RailTransitBaseDataRepository(paths)
    query = RailTransitBaseDataQueryService(paths)
    _create_station(
        repository,
        name="无引用站",
        code="SAFE",
        sort_order=20,
        node_uid="node-safe",
    )
    _create_station(
        repository,
        name="线路端点站",
        code="END",
        sort_order=21,
        node_uid="node-end",
        is_line_terminal=True,
    )
    referenced = _station(query, "车站A")
    safe = _station(query, "无引用站")
    terminal = _station(query, "线路端点站")

    with TestClient(_app(paths, tmp_path)) as client:
        revision = client.get("/api/rail-transit/base-data/revision").json()[
            "base_revision"
        ]
        response = client.post(
            "/api/rail-transit/base-data/stations/delete-preflight",
            json={
                "site_id": "demo",
                "base_revision": revision,
                "station_ids": [safe.id, referenced.id, terminal.id],
            },
        )
        stale_response = client.post(
            "/api/rail-transit/base-data/stations/delete-preflight",
            json={
                "site_id": "demo",
                "base_revision": "stale-revision",
                "station_ids": [safe.id],
            },
        )

    assert response.status_code == 200
    payload = response.json()
    by_id = {item["station_id"]: item for item in payload["items"]}
    assert by_id[safe.id]["status"] == "SAFE_DELETE"
    assert by_id[referenced.id]["status"] == "REQUIRES_MERGE"
    assert by_id[referenced.id]["references"]["ap_count"] >= 1
    assert (
        by_id[referenced.id]["references"]["section_start_count"]
        + by_id[referenced.id]["references"]["section_end_count"]
        >= 1
    )
    assert by_id[terminal.id]["status"] == "BLOCKED"
    assert stale_response.status_code == 409
    assert stale_response.json()["detail"]["code"] == "BASE_DATA_REVISION_CONFLICT"


def test_station_replace_preserves_target_identity_and_migrates_references(
    tmp_path: Path,
) -> None:
    paths, database = build_rail_transit_base_data_fixture(tmp_path)
    repository = RailTransitBaseDataRepository(paths)
    query = RailTransitBaseDataQueryService(paths)
    target = _station(query, "车站A")
    end = _station(query, "车站C")
    _create_station(
        repository,
        name="1.车站A",
        code="01",
        sort_order=1,
        node_uid="node-duplicate-a",
        source_kind="device_station_field",
    )
    with Database(database).connect() as connection:
        now = "2026-07-27T12:00:00+08:00"
        connection.execute(
            """
            INSERT INTO ap_extension_points (
                site_id, belong_type, station_name, ap_name, ap_point_code,
                ap_mac_norm, ap_mac_display, created_at, updated_at
            ) VALUES ('demo', 'station', '1.车站A', 'AP-DUP', 'DUP',
                      '001122334455', '0011-2233-4455', ?, ?)
            """,
            (now, now),
        )
        connection.execute(
            """
            INSERT INTO ac_trackside_ap_plan (
                mode, station_name, ap_count, ap_management_vlans,
                sort_order, created_at, updated_at
            ) VALUES ('unified', '1.车站A', 1, '100', 99, ?, ?)
            """,
            (now, now),
        )
        connection.commit()
    section_values = RailTransitBaseDataApplicationService._section_values(
        {
            "name": "重复站-C区间",
            "section_kind": "manual",
            "path_code": "MAIN",
            "direction_role": "increasing",
            "line_direction": "上行",
            "start_node_type": "station",
            "start_node_uid": "node-duplicate-a",
            "start_station": "1.车站A",
            "end_node_type": "station",
            "end_node_uid": end.node_uid,
            "end_station": end.name,
            "line_side": "右线",
            "source_kind": "manual",
        },
        "create",
    )
    repository.apply_base_data_changes(
        "demo",
        repository.base_data_revision("demo"),
        [
            {
                "entity_type": "section",
                "action": "create",
                "entity_id": "new:duplicate-section",
                "values": section_values,
            }
        ],
    )
    values = RailTransitBaseDataApplicationService._station_values(
        {
            **target.model_dump(),
            "old_name": target.name,
            "name": "1.车站A",
            "code": "01",
            "source_station_value": "01车站A",
            "source_station_key": "01车站a",
            "source_kind": "device_station_field",
            "merge_source_names": ["1.车站A"],
            "merge_source_node_uids": ["node-duplicate-a"],
        },
        "replace",
    )

    result = repository.apply_base_data_changes(
        "demo",
        repository.base_data_revision("demo"),
        [
            {
                "entity_type": "station",
                "action": "replace",
                "entity_id": target.id,
                "values": values,
            }
        ],
    )

    saved = _station(query, "1.车站A")
    assert saved.id == target.id
    assert saved.node_uid == target.node_uid
    assert saved.source_station_key == "01车站a"
    assert sum(
        item.name == "1.车站A"
        for item in query.list_stations("demo", page_size=200).items
    ) == 1
    assert not any(
        item.name == "车站A"
        for item in query.list_stations("demo", page_size=200).items
    )
    with Database(database).connect() as connection:
        assert (
            connection.execute(
                "SELECT station_name FROM ap_extension_points WHERE ap_name = 'AP-DUP'"
            ).fetchone()[0]
            == "1.车站A"
        )
        assert (
            connection.execute(
                "SELECT station_name FROM ac_trackside_ap_plan WHERE sort_order = 99"
            ).fetchone()[0]
            == "1.车站A"
        )
        metadata = json.loads(
            connection.execute(
                """
                SELECT raw_payload_json FROM ap_extension_points
                WHERE belong_type = '__base_section__'
                  AND section_name = '重复站-C区间'
                """
            ).fetchone()[0]
        )
    assert metadata["start_node_uid"] == target.node_uid
    assert result["updated_count"] == 1
    assert result["deleted_count"] == 1


def test_station_merge_self_loop_is_rejected_and_transaction_rolls_back(
    tmp_path: Path,
) -> None:
    paths, database = build_rail_transit_base_data_fixture(tmp_path)
    repository = RailTransitBaseDataRepository(paths)
    query = RailTransitBaseDataQueryService(paths)
    target = _station(query, "车站A")
    source = _station(query, "车站B")
    values = RailTransitBaseDataApplicationService._station_values(
        {
            **target.model_dump(),
            "old_name": target.name,
            "merge_source_names": [source.name],
            "merge_source_node_uids": [source.node_uid],
        },
        "replace",
    )
    before_revision = repository.base_data_revision("demo")

    with TestClient(_app(paths, tmp_path)) as client:
        response = client.post(
            "/api/rail-transit/base-data/validate",
            json={
                "site_id": "demo",
                "base_revision": before_revision,
                "changes": [
                    {
                        "entity_type": "station",
                        "action": "replace",
                        "entity_id": target.id,
                        "values": values,
                    }
                ],
            },
        )

    assert response.status_code == 200
    assert response.json()["valid"] is False
    assert any(
        issue["code"] == "STATION_MERGE_SECTION_SELF_LOOP"
        for issue in response.json()["issues"]
    )
    with pytest.raises(
        RailTransitBaseDataConstraintError,
        match="将形成自环",
    ):
        repository.apply_base_data_changes(
            "demo",
            before_revision,
            [
                {
                    "entity_type": "station",
                    "action": "replace",
                    "entity_id": target.id,
                    "values": values,
                }
            ],
        )
    assert repository.base_data_revision("demo") == before_revision
    with Database(database).connect() as connection:
        section = connection.execute(
            """
            SELECT section_start_station, section_end_station
            FROM ap_extension_points
            WHERE section_name = 'A-B 区间'
            LIMIT 1
            """
        ).fetchone()
    assert tuple(section) == ("车站A", "车站B")


def test_station_conflict_preview_groups_sort_order_duplicates(
    tmp_path: Path,
) -> None:
    paths, _database = build_rail_transit_base_data_fixture(tmp_path)
    repository = RailTransitBaseDataRepository(paths)
    query = RailTransitBaseDataQueryService(paths)
    _formalize_station(
        repository,
        query,
        name="车站A",
        code="A",
        sort_order=1,
    )
    _create_station(
        repository,
        name="1.车站A",
        code="01",
        sort_order=1,
        node_uid="node-duplicate-a",
        source_kind="device_station_field",
    )
    with TestClient(_app(paths, tmp_path)) as client:
        revision = client.get("/api/rail-transit/base-data/revision").json()[
            "base_revision"
        ]
        response = client.get(
            "/api/rail-transit/base-data/stations/conflicts",
            params={"base_revision": revision},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["conflict_group_count"] >= 1
    group = next(
        item
        for item in payload["groups"]
        if item["path_code"] == "MAIN" and item["sort_order"] == 1
    )
    assert {item["station_name"] for item in group["stations"]} >= {
        "车站A",
        "1.车站A",
    }


def test_station_merge_still_reports_unresolved_third_order_conflict(
    tmp_path: Path,
) -> None:
    paths, _database = build_rail_transit_base_data_fixture(tmp_path)
    repository = RailTransitBaseDataRepository(paths)
    query = RailTransitBaseDataQueryService(paths)
    target = _station(query, "车站A")
    _create_station(
        repository,
        name="1.车站A",
        code="01",
        sort_order=1,
        node_uid="node-duplicate-a",
    )
    _create_station(
        repository,
        name="其他顺序冲突站",
        code="99",
        sort_order=1,
        node_uid="node-third-order-conflict",
    )
    values = RailTransitBaseDataApplicationService._station_values(
        {
            **target.model_dump(),
            "old_name": target.name,
            "merge_source_names": ["1.车站A"],
            "merge_source_node_uids": ["node-duplicate-a"],
        },
        "replace",
    )

    with TestClient(_app(paths, tmp_path)) as client:
        response = client.post(
            "/api/rail-transit/base-data/validate",
            json={
                "site_id": "demo",
                "base_revision": repository.base_data_revision("demo"),
                "changes": [
                    {
                        "entity_type": "station",
                        "action": "replace",
                        "entity_id": target.id,
                        "values": values,
                    }
                ],
            },
        )

    assert response.status_code == 200
    assert response.json()["valid"] is False
    assert any(
        issue["code"] == "station_order_duplicate"
        for issue in response.json()["issues"]
    )


def test_station_source_preview_recommends_merge_instead_of_duplicate_create(
    tmp_path: Path,
) -> None:
    paths, database = build_rail_transit_base_data_fixture(tmp_path)
    repository = RailTransitBaseDataRepository(paths)
    _create_station(
        repository,
        name="1.小洋江站",
        code="01",
        sort_order=1,
        node_uid="node-xiaoyangjiang-numbered",
    )
    _create_station(
        repository,
        name="小洋江站",
        code="1",
        sort_order=1,
        node_uid="node-xiaoyangjiang-canonical",
    )
    with Database(database).connect() as connection:
        now = "2026-07-27T12:30:00+08:00"
        group_id = connection.execute(
            """
            INSERT INTO device_groups (
                site_id, name, sort_order, created_at, updated_at
            ) VALUES ('demo', '车站', 2, ?, ?)
            """,
            (now, now),
        ).lastrowid
        connection.execute(
            """
            INSERT INTO devices (
                device_uuid, name, system_name, station, group_id,
                primary_address, device_vendor, device_type, created_at, updated_at
            ) VALUES (
                'source-xiaoyangjiang', '现场交换机', 'SW-XIAOYANGJIANG',
                '01小洋江站', ?, '10.27.1.1', 'H3C', 'SWITCH', ?, ?
            )
            """,
            (group_id, now, now),
        )
        connection.commit()

    with TestClient(_app(paths, tmp_path)) as client:
        response = client.get(
            "/api/rail-transit/base-data/station-source-preview"
        )

    assert response.status_code == 200
    payload = response.json()
    candidate = next(
        item
        for item in payload["candidates"]
        if item["source_station_value"] == "01小洋江站"
    )
    assert candidate["processing_strategy"] == "merge_duplicates", candidate
    assert candidate["name"] == "小洋江站"
    assert candidate["code"] == "01"
    assert candidate["sort_order"] == 1
    assert candidate["order_parse_method"] == "existing_match_inferred"
    assert len(candidate["matched_station_ids"]) == 2
    assert candidate["suggested_action"] == "合并重复项"
    assert payload["recommended_merge_count"] == 1
    assert payload["recommended_create_count"] == 0
