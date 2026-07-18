from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from web_parity_test_support import FakeExportProcessAdapter, FakeLocalProcessAdapter
from netconsole.application.rail_transit.web_application_service import (
    RailTransitWebApplicationService,
)
from netconsole.backend.api.main import create_app
from netconsole.core.database import Database
from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.services.ap_online_overview import AP_ONLINE_OVERVIEW_COLUMNS
from netconsole.services.export.export_job import ExportJob
from netconsole.services.file_contract import attach_export_metadata
from netconsole.services.offline_ap_ledger import (
    OFFLINE_AP_LEDGER_COLUMNS,
    OFFLINE_AP_STATS_COLUMNS,
    offline_ap_headers,
)
from netconsole.services.trackside_ap_business import (
    AP_OPTICAL_TREATMENT_RECORD_COLUMNS,
    NEW_ONLINE_AP_OVERVIEW_COLUMNS,
    TRACKSIDE_AP_BUSINESS_EXPORT_COLUMNS,
    TracksideApExportCancelled,
    export_trackside_ap_business_xlsx,
)
from netconsole.utils.interface_normalize import display_interface_name


class _NoopAsyncService:
    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


def _enable_feature(app, feature_id: str) -> None:
    app.state.feature_gate.features[feature_id] = {
        "visible": True,
        "enabled": True,
        "client_package": True,
        "internal_only": False,
    }


def test_trackside_business_export_api_uses_owned_artifact_and_supports_cancel(
    tmp_path: Path,
) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    Database(paths.site_db_path("demo")).initialize()
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.app_config_path.write_text('{"current_site":"demo"}', encoding="utf-8")
    app = create_app(
        RuntimeMode.SERVER,
        paths=paths,
        agent_service=_NoopAsyncService(),  # type: ignore[arg-type]
        traffic_service=_NoopAsyncService(),  # type: ignore[arg-type]
        frontend_dist=tmp_path / "missing",
    )
    process = FakeLocalProcessAdapter(app.state.task_service)
    export = FakeExportProcessAdapter(app.state.task_service)
    app.state.rail_transit_web_application_service = RailTransitWebApplicationService(
        paths,
        app.state.task_service,
        process_adapter=process,  # type: ignore[arg-type]
        export_adapter=export,  # type: ignore[arg-type]
    )
    _enable_feature(app, "web.rail_trackside_ap_business_export")
    _enable_feature(app, "web.rail_task_control")

    with TestClient(app) as client:
        started = client.post("/api/rail-transit/trackside-ap-business/export")
        assert started.status_code == 202
        payload = started.json()
        assert payload["action"] == "trackside_ap_business_export"
        assert payload["artifact_id"]
        assert str(tmp_path) not in json.dumps(payload, ensure_ascii=False)

        task_id = payload["task_id"]
        job = export.jobs[task_id]
        assert job.job_type == "trackside_ap_business"
        assert job.site_name == "demo"
        assert job.db_path == str(paths.site_db_path("demo"))
        assert job.params == {"language": "zh_CN"}
        assert Path(job.output_path).name.startswith("轨旁AP业务_")

        export.complete(task_id, b"xlsx-fixture")
        completed = client.get(
            f"/api/rail-transit/trackside-ap-business/tasks/{task_id}"
        )
        assert completed.status_code == 200
        completed_payload = completed.json()
        assert completed_payload["available"] is True
        assert str(tmp_path) not in json.dumps(completed_payload, ensure_ascii=False)

        download = client.get(
            "/api/rail-transit/trackside-ap-business/artifacts/"
            f"{payload['artifact_id']}/download"
        )
        assert download.status_code == 200
        assert download.content == b"xlsx-fixture"

        cancelling = client.post("/api/rail-transit/trackside-ap-business/export")
        cancelling_payload = cancelling.json()
        cancelled = client.post(
            "/api/rail-transit/trackside-ap-business/tasks/"
            f"{cancelling_payload['task_id']}/cancel"
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "CANCELLED"
        missing = client.get(
            "/api/rail-transit/trackside-ap-business/artifacts/"
            f"{cancelling_payload['artifact_id']}/download"
        )
        assert missing.status_code == 404

    schema = app.openapi()
    assert "/api/rail-transit/trackside-ap-business/export" in schema["paths"]
    assert (
        "/api/rail-transit/trackside-ap-business/artifacts/{artifact_id}/download"
        in schema["paths"]
    )


def test_trackside_business_workbook_preserves_sheets_and_export_style(
    tmp_path: Path,
) -> None:
    i18n = I18n("zh_CN")
    output = tmp_path / "trackside.xlsx"
    rows = [
        {
            "site": "站点A",
            "device_name": "SW-A",
            "interface_name": "GigabitEthernet2/0/1",
            "link_status": "UP",
            "switch_rx_power": -10.5,
            "switch_optical_status": "normal",
            "ap_name": "AP-A",
            "ap_mac": "0011-2233-4455",
            "ap_rx_power": -11.2,
            "ap_optical_status": "normal",
            "ap_side_has_data": True,
        }
    ]
    export_trackside_ap_business_xlsx(
        output,
        rows,
        TRACKSIDE_AP_BUSINESS_EXPORT_COLUMNS,
        [i18n.t(key) for key, _field in TRACKSIDE_AP_BUSINESS_EXPORT_COLUMNS],
        [],
        AP_ONLINE_OVERVIEW_COLUMNS,
        [i18n.t(key) for key, _field in AP_ONLINE_OVERVIEW_COLUMNS],
        [],
        NEW_ONLINE_AP_OVERVIEW_COLUMNS,
        [i18n.t(key) for key, _field in NEW_ONLINE_AP_OVERVIEW_COLUMNS],
        "新增上线AP概览",
        [
            {
                "site": "站点A",
                "device_name": "SW-A",
                "interface_name": "Ten-GigabitEthernet1/0/1",
            }
        ],
        AP_OPTICAL_TREATMENT_RECORD_COLUMNS,
        [i18n.t(key) for key, _field in AP_OPTICAL_TREATMENT_RECORD_COLUMNS],
        "AP光衰处理记录",
        {},
        [
            {
                "ap_name": "AP-B",
                "historical_switch_interface": "Twenty-FiveGigE1/0/2",
            }
        ],
        offline_ap_headers(OFFLINE_AP_STATS_COLUMNS),
        offline_ap_headers(OFFLINE_AP_LEDGER_COLUMNS),
    )
    attach_export_metadata(
        output,
        effective_suffix=".xlsx",
        export_type="trackside_ap_business",
        payload={"source_module": "rail.trackside_ap_business"},
    )

    workbook = load_workbook(output)
    business_sheets = [
        "轨旁AP业务",
        "当前异常光衰",
        "AP上线情况概览",
        "新增上线AP概览",
        "AP光衰处理记录",
        "AP离线情况",
        "离线AP台账",
        "交换机光模块统计",
    ]
    assert workbook.sheetnames == [*business_sheets, "_netconsole_meta"]
    for name in business_sheets:
        sheet = workbook[name]
        assert sheet.freeze_panes == "A2"
        assert sheet.auto_filter.ref == sheet.dimensions
        assert all(
            cell.alignment.horizontal == "center"
            and cell.alignment.vertical == "center"
            for row in sheet.iter_rows()
            for cell in row
        )
        assert all(
            dimension.width is not None and dimension.width > 0
            for dimension in sheet.column_dimensions.values()
        )

    main = workbook["轨旁AP业务"]
    main_headers = [cell.value for cell in main[1]]
    interface_column = main_headers.index("接口名称") + 1
    assert main.cell(2, interface_column).value == "GE2/0/1"

    treatment = workbook["AP光衰处理记录"]
    treatment_headers = [cell.value for cell in treatment[1]]
    treatment_interface_column = treatment_headers.index("接口名称") + 1
    assert treatment.cell(2, treatment_interface_column).value == "XGE1/0/1"

    ledger = workbook["离线AP台账"]
    ledger_headers = [cell.value for cell in ledger[1]]
    historical_interface_column = ledger_headers.index("历史邻居接口") + 1
    assert ledger.cell(2, historical_interface_column).value == "25GE1/0/2"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("GigabitEthernet2/0/1", "GE2/0/1"),
        ("Ten-GigabitEthernet1/0/1", "XGE1/0/1"),
        ("Twenty-FiveGigE1/0/2", "25GE1/0/2"),
        ("FortyGigE1/0/3", "40GE1/0/3"),
        ("HundredGigE1/0/4", "100GE1/0/4"),
        ("Bridge-Aggregation1", "Bridge-Aggregation1"),
    ],
)
def test_display_interface_name(source: str, expected: str) -> None:
    assert display_interface_name(source) == expected


def test_trackside_export_worker_cleans_temporary_file_on_cancel(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from netconsole import export_worker

    output = tmp_path / "output.xlsx"
    temporary = tmp_path / "output.xlsx.task.tmp"
    temporary.write_bytes(b"partial")
    job = ExportJob(
        job_id="trackside-cancel",
        job_type="trackside_ap_business",
        site_name="demo",
        output_path=str(output),
        tmp_path=str(temporary),
        cancel_path=str(tmp_path / "cancel"),
        db_path=str(tmp_path / "site.sqlite"),
    )

    def cancelled(**_kwargs):
        raise TracksideApExportCancelled("导出已取消")

    monkeypatch.setattr(
        export_worker,
        "export_trackside_ap_business_from_database",
        cancelled,
    )

    assert export_worker.run_job(job) == 2
    assert not temporary.exists()
    assert not output.exists()
