from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from netconsole.core.paths import PathResolver
from netconsole.models.api.ac_mesh_link import AcMeshLinkSummaryDTO, AcMeshMrPageDTO, AcMeshMrStatusDTO
from netconsole.models.api.job_center import JobCenterTaskDTO
from netconsole.models.api.online_mr import (
    OnlineMrCollectorStatusDTO,
    OnlineMrRawFileDTO,
    OnlineMrRealtimePreviewDTO,
    OnlineMrSessionSummaryDTO,
)
from netconsole.models.api.rail_transit_base_data import TrainDTO, TrainPageDTO, VehicleMrDTO, VehicleMrDetailDTO, VehicleMrPageDTO
from netconsole.services.rail_transit.train_communication_query_service import TrainCommunicationQueryService


class _BaseQuery:
    def __init__(self) -> None:
        self.mrs = [
            VehicleMrDTO(id="mr-ct", device_id=1, name="列车01-MR-CT", train_id="01", train_no="01", role="CT", management_ip="10.0.0.1"),
            VehicleMrDTO(id="mr-tc", device_id=2, name="列车01-MR-TC", train_id="01", train_no="01", role="TC", management_ip="10.0.0.2"),
        ]

    @staticmethod
    def current_site_id() -> str:
        return "demo"

    def list_mrs(self, *_args, **_kwargs) -> VehicleMrPageDTO:
        return VehicleMrPageDTO(items=self.mrs, total=len(self.mrs))

    @staticmethod
    def list_trains(*_args, **_kwargs) -> TrainPageDTO:
        return TrainPageDTO(items=[TrainDTO(id="01", train_no="01", name="01车", mr_count=2)], total=1)

    def get_mr(self, _site_id: str, mr_id: str) -> VehicleMrDetailDTO | None:
        mr = next((item for item in self.mrs if item.id == mr_id), None)
        return VehicleMrDetailDTO(mr=mr) if mr else None


class _MeshQuery:
    def __init__(self) -> None:
        common = dict(train_no="01", train_display_name="01车", station="车站A", section="A-B区间", mileage="K1+100", line_side="左线")
        self.mrs = [
            AcMeshMrStatusDTO(mr_id="01-ct", mr_name="列车01-MR-CT", mr_device_id="mr-ct", online_status="online", peer_ap_name="AP-01", peer_ap_mac="0000-0000-0001", mesh_radio="Radio 1", rssi=-55, last_seen_at="2026-07-14T12:00:00+00:00", data_status="fresh", **common),
            AcMeshMrStatusDTO(mr_id="01-tc", mr_name="列车01-MR-TC", mr_device_id="mr-tc", online_status="offline", peer_ap_name="AP-02", mesh_radio="Radio 2", rssi=-82, last_seen_at="2026-07-14T11:50:00+00:00", data_status="stale", **common),
        ]

    def list_mrs(self, *_args, **_kwargs) -> AcMeshMrPageDTO:
        return AcMeshMrPageDTO(items=self.mrs, total=len(self.mrs))

    @staticmethod
    def get_summary(site_id: str) -> AcMeshLinkSummaryDTO:
        return AcMeshLinkSummaryDTO(site_id=site_id, active_links=1, age_seconds=10, data_status="fresh")


class _OnlineQuery:
    def __init__(self) -> None:
        self.sessions = [
            OnlineMrSessionSummaryDTO(session_id="local-active", site_id="demo", mr_name="列车01-MR-CT", device_id=1, status="COLLECTING", started_at="2026-07-14T12:00:00+00:00", controller_task_id="task-1", executor_kind="LOCAL"),
            OnlineMrSessionSummaryDTO(session_id="agent-import", site_id="demo", mr_name="列车01-MR-TC", device_id=2, status="COMPLETED", started_at="2026-07-14T11:00:00+00:00", stopped_at="2026-07-14T11:02:00+00:00", executor_kind="AGENT", agent_id="agent-1", has_package=True, package_name="agent.zip", package_reference="列车01-MR-TC/sessions/agent-import/outputs/agent.zip", finalization_complete=True),
        ]
        self.conflict = False

    def list_sessions(self, *_args, **_kwargs) -> list[OnlineMrSessionSummaryDTO]:
        return self.sessions

    def get_realtime_preview(self, _site_id: str, session_id: str) -> OnlineMrRealtimePreviewDTO:
        if session_id != "local-active":
            return OnlineMrRealtimePreviewDTO(session_id=session_id)
        return OnlineMrRealtimePreviewDTO(
            session_id=session_id,
            available=True,
            updated_at="2026-07-14T12:00:05+00:00",
            display_context={"station": "不应覆盖的上下文站"},
            link={"peer_name": "AP-CONFLICT" if self.conflict else "AP-01", "peer_mac": "0000-0000-0001", "rssi": -56},
            fping={"status": "running", "target_ip": "10.0.0.254", "sent": 10, "received": 9, "loss_percent": 10, "latest_rtt_ms": 3.2, "avg_rtt_ms": 2.8},
            iperf={"status": "running", "server_host": "10.0.0.3", "bitrate_mbps": 12.5, "average_bitrate_mbps": 11.8, "threshold_mbps": 10},
        )

    @staticmethod
    def get_session(_site_id: str, _session_id: str):
        return SimpleNamespace(traffic_summary={})

    @staticmethod
    def read_raw_tail(*_args, **_kwargs):
        return SimpleNamespace(summary={})

    @staticmethod
    def list_collectors(_site_id: str, _session_id: str) -> list[OnlineMrCollectorStatusDTO]:
        return [OnlineMrCollectorStatusDTO(name="mesh_link", label="主链路", raw_file="raw/mesh_link_raw.log", exists=True)]

    @staticmethod
    def get_raw_summary(_site_id: str, session_id: str) -> list[OnlineMrRawFileDTO]:
        return [OnlineMrRawFileDTO(name="mesh_link", relative_name="raw/mesh_link_raw.log", exists=session_id == "local-active", size_bytes=12)]


class _JobQuery:
    @staticmethod
    def list_tasks(*_args, **_kwargs) -> list[JobCenterTaskDTO]:
        return [JobCenterTaskDTO(id="task-1", type="online_mr_collection", name="Online MR", status="RUNNING", session_id="local-active", device_id="1", mr_name="列车01-MR-CT")]


def _service(tmp_path: Path) -> tuple[TrainCommunicationQueryService, _OnlineQuery]:
    online = _OnlineQuery()
    return (
        TrainCommunicationQueryService(
            PathResolver(app_root=tmp_path, data_root=tmp_path),
            base_query=_BaseQuery(),  # type: ignore[arg-type]
            mesh_query=_MeshQuery(),  # type: ignore[arg-type]
            online_mr_query=online,  # type: ignore[arg-type]
            job_query=_JobQuery(),  # type: ignore[arg-type]
            now_provider=lambda: datetime(2026, 7, 14, 12, 0, 10, tzinfo=timezone.utc),
        ),
        online,
    )


def test_aggregates_ct_tc_mesh_sessions_and_traffic_without_merging_roles(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)

    summary = service.get_summary("demo")
    page = service.list_trains("demo")
    row = page.items[0]
    ct = next(item for item in row.mrs if item.mr_role == "CT")
    tc = next(item for item in row.mrs if item.mr_role == "TC")

    assert summary.registered_trains == 1
    assert summary.registered_mrs == 2
    assert summary.active_online_mr_sessions == 1
    assert summary.agent_imported_sessions == 1
    assert ct.peer_ap_name == "AP-01"
    assert ct.station == "车站A"
    assert ct.fping_latest_rtt_ms == 3.2
    assert ct.fping_loss_percent == 10
    assert ct.iperf_latest_mbps == 12.5
    assert tc.executor == "AGENT"
    assert tc.data_integrity == "complete"
    assert tc.communication_status in {"warning", "stale"}
    assert row.communication_status == "warning"
    assert service.get_related_tasks("demo", "mr-ct")[0].id == "task-1"
    assert service.get_related_packages("demo", "mr-tc")[0].import_status == "imported"


def test_peer_conflict_is_explicit_and_formal_mesh_location_wins(tmp_path: Path) -> None:
    service, online = _service(tmp_path)
    online.conflict = True

    mr = service.get_communication_preview("demo", "mr-ct")

    assert mr is not None
    assert mr.peer_ap_name == "AP-01"
    assert mr.station == "车站A"
    assert any(item.code == "source_conflict" for item in mr.warnings)
    assert "不应覆盖" not in mr.station


def test_missing_raw_source_is_a_readonly_empty_state(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)

    rows = service.get_raw_sources("demo", "mr-tc")

    assert rows[0].exists is False
    assert rows[0].message == "文件不存在或尚未生成"


def test_service_has_no_qt_application_or_mutation_dependency() -> None:
    source = Path("src/netconsole/services/rail_transit/train_communication_query_service.py").read_text(encoding="utf-8")
    assert "PySide6" not in source
    assert "ApplicationService" not in source
    assert ".start(" not in source
    assert ".stop(" not in source
