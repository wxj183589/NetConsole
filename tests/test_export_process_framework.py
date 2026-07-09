from __future__ import annotations

import subprocess
import sys

import pytest

from netconsole.core.i18n import I18n
from netconsole.services.export_task_models import ExportJob
from netconsole.services.trackside_ap_business import (
    TRACKSIDE_AP_BUSINESS_COLUMNS,
    TracksideApExportCancelled,
    export_trackside_ap_business_xlsx,
)


def test_export_job_keeps_legacy_export_type_compatibility() -> None:
    job = ExportJob(job_id="job-1", export_type="mesh_link_detail", output_path="detail.xlsx", tmp_path="detail.xlsx.tmp")

    assert job.job_type == "mesh_link_detail"
    assert job.export_type == "mesh_link_detail"
    assert ExportJob.from_dict(job.to_dict()).job_type == "mesh_link_detail"


def test_export_worker_import_does_not_load_pyside6() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import netconsole.export_worker, sys; print(any(name.startswith('PySide6') for name in sys.modules))",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == "False"


def test_trackside_xlsx_export_reports_progress(tmp_path) -> None:
    i18n = I18n("zh_CN")
    rows = [
        {"site": "Station A", "device_name": "SW-1", "interface_name": "GigabitEthernet1/0/1", "link_status": "UP"},
        {"site": "Station A", "device_name": "SW-1", "interface_name": "GigabitEthernet1/0/2", "link_status": "DOWN"},
    ]
    events: list[tuple[str, int, int, str]] = []

    export_trackside_ap_business_xlsx(
        tmp_path / "trackside_progress.xlsx",
        rows,
        TRACKSIDE_AP_BUSINESS_COLUMNS,
        [i18n.t(key) for key, _field in TRACKSIDE_AP_BUSINESS_COLUMNS],
        progress_callback=lambda stage, current, total, message: events.append((stage, current, total, message)),
    )

    assert events[0] == ("write_trackside_rows", 0, 2, "正在写入轨旁AP业务明细 0/2")
    assert ("write_trackside_rows", 2, 2, "正在写入轨旁AP业务明细 2/2") in events
    assert any(stage == "save_workbook" for stage, _current, _total, _message in events)


def test_trackside_xlsx_export_honors_cancel_callback(tmp_path) -> None:
    i18n = I18n("zh_CN")
    export_path = tmp_path / "trackside_cancelled.xlsx"

    with pytest.raises(TracksideApExportCancelled):
        export_trackside_ap_business_xlsx(
            export_path,
            [{"site": "Station A", "device_name": "SW-1", "interface_name": "GigabitEthernet1/0/1"}],
            TRACKSIDE_AP_BUSINESS_COLUMNS,
            [i18n.t(key) for key, _field in TRACKSIDE_AP_BUSINESS_COLUMNS],
            should_cancel=lambda: True,
        )

    assert not export_path.exists()
