from __future__ import annotations

import hashlib
import json
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

from rail_transit_base_data_fixture import build_rail_transit_base_data_fixture
from netconsole.backend.api.main import create_app
from netconsole.core.database import Database
from netconsole.core.runtime_mode import RuntimeMode


class _NoopAsyncService:
    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


def _fingerprint(path: Path) -> tuple[str, int]:
    return hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns


def _app(paths, tmp_path: Path):
    return create_app(
        RuntimeMode.SERVER,
        paths=paths,
        task_service=object(),  # type: ignore[arg-type]
        agent_service=_NoopAsyncService(),  # type: ignore[arg-type]
        traffic_service=_NoopAsyncService(),  # type: ignore[arg-type]
        frontend_dist=tmp_path / "missing",
    )


def _insert_station_source_devices(db_path: Path) -> None:
    now = "2026-07-22T08:00:00"
    database = Database(db_path)
    with database.connect() as conn:
        station_group = conn.execute(
            "INSERT INTO device_groups (site_id, name, sort_order, created_at, updated_at) VALUES ('demo', '车站', 2, ?, ?)",
            (now, now),
        ).lastrowid
        other_group = conn.execute(
            "INSERT INTO device_groups (site_id, name, sort_order, created_at, updated_at) VALUES ('demo', '其他', 3, ?, ?)",
            (now, now),
        ).lastrowid
        rows = [
            ("station-wuxiang-1", "32-五乡1", "SYS-WX1", "32-五乡", station_group, "10.20.0.1"),
            ("station-wuxiang-2", "32-五乡2", "SYS-WX2", "32-五乡", station_group, "10.20.0.2"),
            ("station-baozhuang", "33-宝幢1", "33-错误系统名", "33-宝幢", station_group, "10.20.0.3"),
            ("station-yard", "50-高桥西停车场", "YARD-SYS", "50-高桥西停车场", station_group, "10.20.0.4"),
            ("station-depot", "52-天童庄车辆段", "DEPOT-SYS", "52-天童庄车辆段", station_group, "10.20.0.5"),
            ("station-empty", "错误设备名称99", "SYS-EMPTY", "", station_group, "10.20.0.6"),
            ("other-station", "99-不应读取", "OTHER-SYS", "99-不应读取", other_group, "10.20.0.7"),
        ]
        rows.extend(
            (f"station-bulk-{index}", f"批量设备{index}", f"BULK-{index}", "34-批量站", station_group, f"10.21.0.{index}")
            for index in range(1, 206)
        )
        conn.executemany(
            """
            INSERT INTO devices (
                device_uuid, name, system_name, station, group_id, primary_address,
                device_vendor, device_type, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'H3C', 'SWITCH', ?, ?)
            """,
            [(uuid, name, system_name, station, group_id, address, now, now) for uuid, name, system_name, station, group_id, address in rows],
        )
        conn.commit()
    with database.connect() as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def test_router_delegates_import_policy_without_guard_or_source_policy_access() -> None:
    router_source = (
        Path(__file__).parents[1] / "src/netconsole/backend/api/rail_transit_base_data_router.py"
    ).read_text(encoding="utf-8")

    assert "get_import_policy" in router_source
    assert ".guard" not in router_source
    assert "source_policy" not in router_source
    assert "import_policy_rows" not in router_source


def test_base_data_api_defaults_to_locked_and_redacts_credentials(tmp_path: Path) -> None:
    paths, db_path = build_rail_transit_base_data_fixture(tmp_path)
    app = create_app(
        RuntimeMode.SERVER,
        paths=paths,
        task_service=object(),  # type: ignore[arg-type]
        agent_service=_NoopAsyncService(),  # type: ignore[arg-type]
        traffic_service=_NoopAsyncService(),  # type: ignore[arg-type]
        frontend_dist=tmp_path / "missing",
    )
    with TestClient(app) as client:
        assert client.get("/api/rail-transit/base-data/summary").status_code == 200
        before = _fingerprint(db_path)
        responses = [
            client.get("/api/rail-transit/base-data/summary"),
            client.get("/api/rail-transit/base-data/stations"),
            client.get("/api/rail-transit/base-data/sections"),
            client.get("/api/rail-transit/base-data/aps?page=1&page_size=2"),
            client.get("/api/rail-transit/base-data/trains"),
            client.get("/api/rail-transit/base-data/mrs"),
            client.get("/api/rail-transit/base-data/issues"),
            client.get("/api/rail-transit/base-data/issues/groups"),
            client.get("/api/rail-transit/base-data/import-policies"),
            client.get("/api/rail-transit/base-data/relations"),
        ]
        ap_id = responses[3].json()["items"][0]["id"]
        train_id = responses[4].json()["items"][0]["id"]
        mr_id = responses[5].json()["items"][0]["id"]
        responses.extend(
            [
                client.get(f"/api/rail-transit/base-data/aps/{ap_id}"),
                client.get(f"/api/rail-transit/base-data/trains/{train_id}"),
                client.get(f"/api/rail-transit/base-data/mrs/{mr_id}"),
            ]
        )
        preview = client.post(
            "/api/rail-transit/base-data/import-preview",
            files={
                "file": (
                    "preview.json",
                    json.dumps(
                        [{"ap_name": "AP-Preview", "ap_mac_display": "0011-2233-4455"}],
                        ensure_ascii=False,
                    ).encode("utf-8"),
                    "application/json",
                )
            },
        )
        responses.append(preview)
    assert all(response.status_code == 200 for response in responses)
    text = "".join(response.text for response in responses).casefold()
    assert "private-user" not in text
    assert "private-pass" not in text
    assert "password" not in text
    assert _fingerprint(db_path) == before

    routes = {
        (path, method.upper())
        for path, operations in app.openapi()["paths"].items()
        if path.startswith("/api/rail-transit/base-data")
        for method in operations
    }
    assert {path for path, method in routes if method == "POST"} == {
        "/api/rail-transit/base-data/import-preview",
        "/api/rail-transit/base-data/station-template-preview",
        "/api/rail-transit/base-data/import-apply",
        "/api/rail-transit/base-data/import-operations/{operation_id}/rollback",
        "/api/rail-transit/base-data/validate",
        "/api/rail-transit/base-data/changes",
    }
    assert not any(method in {"PUT", "PATCH", "DELETE"} for _path, method in routes)
    assert responses[8].json()["write_enabled"] is False


def test_station_source_preview_uses_station_field_only_and_is_read_only(tmp_path: Path) -> None:
    paths, db_path = build_rail_transit_base_data_fixture(tmp_path)
    _insert_station_source_devices(db_path)
    with TestClient(_app(paths, tmp_path)) as client:
        before = _fingerprint(db_path)
        response = client.get("/api/rail-transit/base-data/station-source-preview")
    assert response.status_code == 200
    assert _fingerprint(db_path) == before
    payload = response.json()
    assert payload["group_found"] is True
    assert payload["source_field"] == "station"
    assert payload["scanned_device_count"] == 211
    assert payload["empty_station_device_count"] == 1
    assert payload["unique_station_value_count"] == 5

    by_name = {item["name"]: item for item in payload["candidates"]}
    assert by_name["五乡"]["code"] == "32"
    assert by_name["五乡"]["sort_order"] == 32
    assert by_name["五乡"]["source_device_count"] == 2
    assert by_name["宝幢"]["code"] == "33"
    assert by_name["批量站"]["source_device_count"] == 205
    assert by_name["高桥西停车场"]["node_type"] == "parking_lot"
    assert by_name["高桥西停车场"]["path_code"] == "UNASSIGNED"
    assert by_name["高桥西停车场"]["sort_order"] is None
    assert by_name["高桥西停车场"]["participates_in_direction"] is False
    assert by_name["天童庄车辆段"]["node_type"] == "depot"
    assert by_name["天童庄车辆段"]["sort_order"] is None
    text = response.text
    assert "五乡1" not in text
    assert "五乡2" not in text
    assert "33-错误系统名" not in text
    assert "错误设备名称99" not in text
    assert "99-不应读取" not in text
    assert any(issue["code"] == "station_source_value_empty" for issue in payload["issues"])


def test_station_source_preview_reports_missing_group_without_writes(tmp_path: Path) -> None:
    paths, db_path = build_rail_transit_base_data_fixture(tmp_path)
    with TestClient(_app(paths, tmp_path)) as client:
        before = _fingerprint(db_path)
        payload = client.get("/api/rail-transit/base-data/station-source-preview").json()
    assert _fingerprint(db_path) == before
    assert payload["group_found"] is False
    assert payload["candidates"] == []
    assert payload["issues"][0]["code"] == "station_source_group_missing"


def test_station_source_preview_flags_code_and_name_conflicts(tmp_path: Path) -> None:
    paths, db_path = build_rail_transit_base_data_fixture(tmp_path)
    now = "2026-07-22T08:00:00"
    database = Database(db_path)
    with database.connect() as conn:
        group_id = conn.execute(
            "INSERT INTO device_groups (site_id, name, sort_order, created_at, updated_at) VALUES ('demo', '车站', 2, ?, ?)",
            (now, now),
        ).lastrowid
        conn.executemany(
            """
            INSERT INTO devices (
                device_uuid, name, system_name, station, group_id, primary_address,
                device_vendor, device_type, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'H3C', 'SWITCH', ?, ?)
            """,
            [
                ("station-code-a", "设备A", "SYS-A", "10-甲站", group_id, "10.22.0.1", now, now),
                ("station-code-b", "设备B", "SYS-B", "10-乙站", group_id, "10.22.0.2", now, now),
                ("station-name-a", "设备C", "SYS-C", "11-丙站", group_id, "10.22.0.3", now, now),
                ("station-name-b", "设备D", "SYS-D", "12-丙站", group_id, "10.22.0.4", now, now),
            ],
        )
        conn.commit()
    with TestClient(_app(paths, tmp_path)) as client:
        payload = client.get("/api/rail-transit/base-data/station-source-preview").json()
    issue_codes = {
        issue["code"]
        for candidate in payload["candidates"]
        for issue in candidate["issues"]
    }
    assert payload["conflict_count"] == 4
    assert "station_source_code_conflict" in issue_codes
    assert "station_source_name_conflict" in issue_codes


def test_station_template_download_preview_and_export_are_structured_xlsx(tmp_path: Path) -> None:
    paths, db_path = build_rail_transit_base_data_fixture(tmp_path)
    _insert_station_source_devices(db_path)
    with TestClient(_app(paths, tmp_path)) as client:
        template = client.get("/api/rail-transit/base-data/station-template")
        exported = client.get("/api/rail-transit/base-data/station-template-export")
    assert template.status_code == 200
    assert exported.status_code == 200
    workbook = load_workbook(BytesIO(template.content))
    assert workbook.sheetnames == ["01_线路参数", "02_线路节点", "字段说明"]
    assert workbook["01_线路参数"]["H2"].value == "station"
    exported_wb = load_workbook(BytesIO(exported.content))
    assert exported_wb["02_线路节点"].max_row >= 2

    upload = Workbook()
    upload.active.title = "01_线路参数"
    upload.active.append(["线路名称", "项目类型", "网络类型", "主线路径编码", "站序递增方向名称", "站序递减方向名称", "设备来源分组", "设备来源字段", "备注"])
    upload.active.append(["测试线", "PIS", "default", "MAIN", "上行", "下行", "车站", "station", ""])
    nodes = upload.create_sheet("02_线路节点")
    nodes.append(["来源站点值", "节点编码", "节点名称", "节点类型", "所属路径", "主线顺序", "参与方向判断", "车站结构", "站台形式", "线路端点", "运营终点", "可折返", "折返类型", "折返方向", "启用", "备注"])
    nodes.append(["32-五乡", "32", "五乡", "普通车站", "MAIN", 32, "是", "地下", "岛式", "否", "否", "否", "无", "无", "是", "模板导入"])
    nodes.append(["50-高桥西停车场", "50", "高桥西停车场", "停车场", "UNASSIGNED", "", "否", "未填写", "未填写", "否", "否", "否", "无", "无", "是", ""])
    upload.create_sheet("字段说明")
    stream = BytesIO()
    upload.save(stream)
    with TestClient(_app(paths, tmp_path)) as client:
        before = _fingerprint(db_path)
        preview = client.post(
            "/api/rail-transit/base-data/station-template-preview",
            files={"file": ("stations.xlsx", stream.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
    assert preview.status_code == 200
    assert _fingerprint(db_path) == before
    payload = preview.json()
    assert payload["valid"] is True
    assert payload["line_metadata"]["station_source_field"] == "station"
    assert payload["rows"][0]["proposed_station"]["structure_type"] == "underground"
    assert payload["rows"][1]["proposed_station"]["node_type"] == "parking_lot"
    assert payload["rows"][1]["proposed_station"]["sort_order"] is None
