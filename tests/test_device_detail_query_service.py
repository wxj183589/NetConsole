from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.models.task_snapshot import TaskSnapshot
from netconsole.models.task_state import TaskState
from netconsole.repositories.device_detail_repository import DeviceDetailRepository
from netconsole.repositories.device_fact_repository import DeviceFactRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.device_command_profile_service import (
    DEVICE_INVENTORY_OPERATION_ID,
    DeviceCommandProfileNotFound,
)
from netconsole.services.device_detail_query_service import DeviceDetailQueryService
from netconsole.services.device_operation_service import (
    DeviceOperationService,
    run_device_inventory_refresh,
)
from netconsole.services.job_center.job_context import JobContext
from netconsole.services.job_center.task_application_service import TaskApplicationService


class _CapturingAdapter:
    def __init__(self, tasks: TaskApplicationService) -> None:
        self.tasks = tasks
        self.jobs = []

    def start_job(self, job, **_kwargs) -> str:
        self.jobs.append(job)
        return self.tasks.prepare(job).job.job_id


@dataclass
class _ConfigSnapshot:
    id: int = 7
    type: str = "running"
    timestamp: str = "20260719_120000"
    size_bytes: int | None = None
    artifact_id: str = "snapshot-7"
    filename: str = "C:\\private\\running.txt"
    hash: str = "a" * 64
    created_at: str = "2026-07-19T12:00:00"
    error_message: str = "读取 C:\\private\\running.txt 失败 password=secret-value"


class _ConfigReader:
    def list_snapshots_page(
        self,
        _site_name: str,
        _device_id: int,
        _snapshot_type: str = "",
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[object], int]:
        rows = [_ConfigSnapshot()]
        return rows[offset : offset + limit], len(rows)

    def count_snapshots(
        self, _site_name: str, _device_id: int, _snapshot_type: str = ""
    ) -> int:
        return 1


@dataclass
class _BusinessRow:
    device_name: str
    interface_name: str = "GE1/0/1"
    ap_mac: str = "0011-2233-4455"
    ap_name: str = "AP-01"
    optical_severity: str = "warning"
    link_status: str = "UP"
    switch_rx_power: float = -18.0
    ap_rx_power: float = -17.5
    updated_at: str = "2026-07-19T12:00:00"


@dataclass
class _BusinessPage:
    items: list[_BusinessRow]
    total: int
    empty_reason: str = ""


class _BusinessReader:
    def list_rows(self, _site_id: str, **kwargs) -> _BusinessPage:
        return _BusinessPage([_BusinessRow(str(kwargs.get("query") or ""))], 1)


@dataclass
class _AcAp:
    id: str = "ap-1"
    ac_id: str = ""
    ac_name: str = "AC-01"
    name: str = "FIT-AP-01"
    ip: str = "192.0.2.31"
    mac: str = "0011-2233-4455"
    status: str = "online"
    state_display: str = "在线"
    model: str = "WA6320"
    radio1_status: str = "up"
    radio1_channel: str = "1"
    radio1_power: str = "17"
    radio2_status: str = "up"
    radio2_channel: str = "149"
    radio2_power: str = "17"
    lldp_status: str = "matched"
    switch_name: str = "SW-01"
    switch_interface: str = "GE1/0/1"
    optical_status: str = "normal"
    optical_severity: str = "normal"
    optical_rx_power: str = "-12.1 dBm"
    updated_at: str = "2026-07-19T13:00:00"


class _AcReader:
    def list_aps(self, _site_id: str, **kwargs) -> object:
        row = _AcAp(ac_id=str(kwargs["ac_id"]))
        return type("AcPage", (), {"items": [row], "total": 1})()


@dataclass
class _MrSession:
    session_id: str = "session-1"
    site_id: str = "demo"
    mr_name: str = "MR-01"
    status: str = "RUNNING"
    phase: str = "COLLECTING"
    started_at: str = "2026-07-19T13:00:00"
    stopped_at: str | None = None
    duration_seconds: float = 60.0
    executor_kind: str = "local"
    controller_task_id: str = "task-mr-1"
    has_raw_data: bool = True
    has_parsed_data: bool = True
    has_package: bool = False


class _MrReader:
    def list_sessions(self, _site_id: str, **kwargs) -> list[object]:
        return [_MrSession(mr_name=str(kwargs["mr_name"]))]

    def get_session(self, _site_id: str, _session_id: str) -> object:
        database = type("Database", (), {"row_counts": {"mesh_rssi": 3}})()
        return type(
            "Detail",
            (),
            {
                "enabled_collectors": ["mesh_link", "fping_v5", "iperf_client"],
                "database_summary": database,
                "traffic_summary": {},
            },
        )()

    def get_realtime_preview(self, _site_id: str, _session_id: str) -> object:
        return type(
            "Preview",
            (),
            {
                "updated_at": "2026-07-19T13:01:00",
                "link": {"rssi_dbm": -65},
                "fping": {"status": "running"},
                "iperf": {"status": "running"},
            },
        )()


def _fixture(tmp_path: Path):
    project_root = Path(__file__).parents[1]
    paths = PathResolver(app_root=project_root, data_root=tmp_path / "runtime")
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    devices = DeviceRepository(database)
    h3c = devices.create(
        Device(
            name="SW-01",
            primary_address="192.0.2.10",
            device_vendor="H3C",
            device_type="SW",
            ssh_password="secret-value",
        )
    )
    huawei = devices.create(
        Device(
            name="HW-01",
            primary_address="192.0.2.20",
            device_vendor="Huawei",
            device_type="SW",
        )
    )
    ac = devices.create(
        Device(
            name="AC-01",
            primary_address="192.0.2.30",
            device_vendor="H3C",
            device_type="AC",
        )
    )
    facts = DeviceFactRepository(database)
    facts.upsert_device_fact(
        {
            "device_uuid": str(h3c.device_uuid),
            "sysname": "SW-CORE",
            "model": "S6520",
            "software_version": "H3C Comware Software, Version 7.1.070",
            "vendor": "H3C",
            "collected_at": "2026-07-19T10:00:00",
            "updated_at": "2026-07-19T10:00:00",
        }
    )
    facts.upsert_device_fact(
        {
            "device_uuid": str(huawei.device_uuid),
            "software_version": "Huawei Versatile Routing Platform Software VRP V8",
            "vendor": "Huawei",
            "collected_at": "2026-07-19T10:00:00",
            "updated_at": "2026-07-19T10:00:00",
        }
    )
    facts.replace_device_interfaces(
        str(h3c.device_uuid),
        [
            {
                "interface_name": "GE1/0/1",
                "link_status": "UP",
                "admin_status": "up",
                "physical_status": "up",
                "protocol_status": "up",
                "media_attribute": "optical",
                "media_type": "optical",
                "category": "physical",
                "port_status": "hybrid",
                "port_mode": "hybrid",
                "pvid": "71",
                "native_vlan": "71",
                "tagged_vlans": ["201"],
                "untagged_vlans": [],
                "pvid_source": "show_running_config_switchvlan",
                "pvid_verified": True,
                "vlan_config_status": "current",
                "vlan_warnings": [],
                "description": "AP uplink",
                "collected_at": "2026-07-18T10:00:00",
            },
            {
                "interface_name": "GE1/0/10",
                "link_status": "UP",
                "description": "uplink",
                "collected_at": "2026-07-18T10:00:00",
            },
            {
                "interface_name": "XGE1/0/2",
                "link_status": "DOWN",
                "description": "AP access",
                "collected_at": "2026-07-18T10:00:00",
            },
        ],
    )
    facts.replace_device_interfaces(
        str(huawei.device_uuid),
        [
            {
                "interface_name": "XGigabitEthernet0/0/1",
                "link_status": "UP",
                "collected_at": "2026-07-18T10:00:00",
            }
        ],
    )
    facts.replace_optical_modules(
        str(h3c.device_uuid),
        [
            {
                "interface_name": "GE1/0/1",
                "rx_power": "-18.00 dBm",
                "tx_power": "-3.20 dBm",
                "rx_low_alarm": "-19.00 dBm",
                "rx_low_warning": "-16.99 dBm",
                "module_model": "SFP-GE-LX",
            }
        ],
    )
    facts.replace_lldp_neighbors(
        str(h3c.device_uuid),
        [
            {
                "local_interface": "GE1/0/1",
                "neighbor_sysname": "AP-01",
                "chassis_type": "MAC address",
                "chassis_id": "02aa.bbcc.0001",
                "ttl": 120,
                "pvid": 71,
                "system_description": "HZDT test neighbor",
                "neighbor_device_uuid": str(ac.device_uuid),
            },
            {
                "local_interface": "GE1/0/2",
                "neighbor_sysname": "unknown-peer",
            },
        ],
    )
    tasks = TaskApplicationService(
        paths=paths, site_name="demo", reconcile_on_start=False
    )
    tasks.repository("demo").save(
        TaskSnapshot(
            task_id="device-task-sensitive",
            task_type="device_detail_collect",
            task_name="读取 C:\\private\\job.json",
            status=TaskState.FAILED,
            created_time="2026-07-19T11:00:00Z",
            updated_time="2026-07-19T11:01:00Z",
            owner="web_device_management",
            source="local",
            site_name="demo",
            device=str(h3c.device_uuid),
            message="path=C:\\private\\job.json password=secret-value",
            error_message="token=abc C:\\private\\trace.log",
        )
    )
    gateway = DeviceDetailRepository(paths, site_name="demo")
    adapter = _CapturingAdapter(tasks)
    operation = DeviceOperationService(paths, gateway, tasks, adapter)
    query = DeviceDetailQueryService(
        gateway,
        tasks,
        operation,
        config_reader=_ConfigReader(),
        business_reader=_BusinessReader(),
        ac_business_reader=_AcReader(),
        online_mr_reader=_MrReader(),
    )
    return query, operation, adapter, h3c, huawei, ac


def test_overview_resolves_role_platform_capability_and_null_snapshot_counts(
    tmp_path: Path,
) -> None:
    query, _operation, _adapter, h3c, huawei, ac = _fixture(tmp_path)
    task_repository = query.task_service.repository("demo")
    task_repository.save(
        TaskSnapshot(
            task_id="device-task-completed",
            task_type="device_detail_collect",
            task_name="设备详情采集成功",
            status=TaskState.COMPLETED,
            created_time="2026-07-19T10:00:00Z",
            updated_time="2026-07-19T10:01:00Z",
            finished_time="2026-07-19T10:01:00Z",
            owner="web_device_management",
            source="local",
            site_name="demo",
            device=str(h3c.device_uuid),
            message="采集完成",
        )
    )
    task_repository.save(
        TaskSnapshot(
            task_id="device-task-running",
            task_type="device_detail_collect",
            task_name="设备详情采集中",
            status=TaskState.RUNNING,
            created_time="2026-07-19T12:00:00Z",
            updated_time="2026-07-19T12:01:00Z",
            owner="web_device_management",
            source="local",
            site_name="demo",
            device=str(h3c.device_uuid),
            message="正在采集",
        )
    )

    overview = query.overview(str(h3c.device_uuid))
    assert overview.platform_facts.role == "switch"
    assert overview.platform_facts.platform == "comware"
    assert overview.platform_facts.software_major == "V7"
    refresh = next(
        item
        for item in overview.capabilities
        if item.capability_id == DEVICE_INVENTORY_OPERATION_ID
    )
    assert refresh.executable is True
    assert refresh.profile_id == "h3c.comware.switch.generic.device-inventory.v1"
    assert overview.platform_facts.software_version == (
        "H3C Comware Software, Version 7.1.070"
    )
    assert overview.command_profile.compatibility == "generic_read_only"
    assert overview.command_profile.risk == "read_only"
    assert overview.command_profile.real_device_status == "real_device_pending"
    assert overview.visible_sections == [
        "overview",
        "interfaces",
        "optical",
        "lldp",
        "configuration",
        "tasks",
        "business",
    ]
    assert all(
        item.capability_id != "device.health.read" for item in overview.capabilities
    )
    assert overview.task_facts.recent_task_count == 3
    assert overview.task_facts.active_task_count == 1
    assert overview.task_facts.latest_running_task is not None
    assert overview.task_facts.latest_running_task.task_id == "device-task-running"
    assert overview.task_facts.latest_successful_task is not None
    assert overview.task_facts.latest_failed_task is not None
    assert overview.task_facts.latest_error is not None
    assert "C:\\private" not in overview.model_dump_json()
    assert "token=abc" not in overview.model_dump_json()

    ac_overview = query.overview(str(ac.device_uuid))
    assert ac_overview.platform_facts.role == "wireless_controller"
    assert ac_overview.counts.interfaces is None
    assert "business" in ac_overview.visible_sections
    assert ac_overview.command_profile.executable is True
    assert (
        ac_overview.command_profile.profile_id
        == "h3c.comware.wireless_controller.generic.device-inventory.v1"
    )
    project_root = Path(__file__).parents[1]
    paths = PathResolver(app_root=project_root, data_root=tmp_path / "runtime")
    mr = DeviceRepository(Database(paths.site_db_path("demo"))).create(
        Device(
            name="MR-01",
            primary_address="192.0.2.40",
            device_vendor="H3C",
            device_type="MR",
        )
    )
    mr_overview = query.overview(str(mr.device_uuid))
    assert mr_overview.platform_facts.role == "mobile_router"
    assert mr_overview.platform_facts.platform == "comware"
    assert "business" in mr_overview.visible_sections
    assert mr_overview.command_profile.executable is True
    assert mr_overview.command_profile.profile_id == "h3c.comware.mobile_router.generic.device-inventory.v1"
    huawei_overview = query.overview(str(huawei.device_uuid))
    assert huawei_overview.platform_facts.platform == "vrp"
    assert huawei_overview.snapshot.available is True
    huawei_refresh = next(
        item
        for item in huawei_overview.capabilities
        if item.capability_id == DEVICE_INVENTORY_OPERATION_ID
    )
    assert huawei_refresh.available is False
    assert huawei_refresh.executable is False
    assert query.interfaces(
        str(huawei.device_uuid), page=1, page_size=10
    ).items[0].normalized_name == "Ten-GigabitEthernet0/0/1"


def test_interface_filter_and_multivendor_name_normalization(
    tmp_path: Path,
) -> None:
    query, _operation, _adapter, h3c, _huawei, _ac = _fixture(tmp_path)

    page = query.interfaces(
        str(h3c.device_uuid), search="AP access", page=1, page_size=1
    )
    assert page.total == 1
    assert page.items[0].normalized_name == "Ten-GigabitEthernet1/0/2"
    assert page.items[0].category == "physical"

    semantic_page = query.interfaces(
        str(h3c.device_uuid),
        status="UP",
        admin_status="up",
        physical_status="up",
        protocol_status="up",
        media_type="optical",
        page=1,
        page_size=10,
    )
    assert semantic_page.total == 1
    interface = semantic_page.items[0]
    assert interface.admin_status == "up"
    assert interface.physical_status == "up"
    assert interface.protocol_status == "up"
    assert interface.media_type == "optical"
    assert interface.port_mode == "hybrid"
    assert interface.port_status == "hybrid"
    assert interface.pvid == "71"
    assert interface.native_vlan == "71"
    assert interface.tagged_vlans == ["201"]
    assert interface.pvid_source == "show_running_config_switchvlan"
    assert interface.pvid_verified is True

def test_optical_alarm_and_lldp_association_are_derived_in_python(
    tmp_path: Path,
) -> None:
    query, _operation, _adapter, h3c, _huawei, _ac = _fixture(tmp_path)

    optical = query.transceivers(
        str(h3c.device_uuid), severity="warning", page=1, page_size=10
    )
    assert optical.total == 1
    assert optical.items[0].rx_power == -18.0
    assert optical.items[0].severity == "warning"
    assert "threshold_source" not in optical.items[0].model_dump()

    lldp = query.lldp(str(h3c.device_uuid), page=1, page_size=10)
    assert [item.association_status for item in lldp.items] == [
        "matched",
        "unresolved",
    ]
    assert lldp.items[0].chassis_id == "02aa.bbcc.0001"
    assert lldp.items[0].ttl == 120
    assert lldp.items[0].pvid == 71
    assert lldp.items[0].system_description == "HZDT test neighbor"
    assert query.lldp(
        str(h3c.device_uuid), linked_only=True, page=1, page_size=10
    ).total == 1
    detail = query.interface_detail(
        str(h3c.device_uuid), "GigabitEthernet1/0/1"
    )
    assert detail.transceiver is not None
    assert detail.lldp_neighbors[0].neighbor_system_name == "AP-01"
    assert detail.lldp_truncated is False


def test_optical_mapping_honors_collector_status_and_all_tx_thresholds(
    tmp_path: Path,
) -> None:
    query, _operation, _adapter, h3c, _huawei, _ac = _fixture(tmp_path)
    paths = PathResolver(
        app_root=Path(__file__).parents[1], data_root=tmp_path / "runtime"
    )
    DeviceFactRepository(Database(paths.site_db_path("demo"))).replace_optical_modules(
        str(h3c.device_uuid),
        [
            {
                "interface_name": "GE1/0/1",
                "status": "no_light",
                "module_model": "SFP-GE-LX",
            },
            {"interface_name": "GE1/0/2", "status": "no_module"},
            {
                "interface_name": "GE1/0/3",
                "status": "link_abnormal",
                "rx_power": "-10",
            },
            {
                "interface_name": "GE1/0/4",
                "rx_power": "-10",
                "rx_low_warning": "-17",
                "tx_power": "4.5",
                "tx_high_warning": "3.0",
                "tx_high_alarm": "4.0",
                "tx_low_warning": "-8.0",
                "tx_low_alarm": "-10.0",
            },
        ],
    )

    page = query.transceivers(str(h3c.device_uuid), page=1, page_size=10)
    by_name = {item.interface_name: item for item in page.items}
    assert by_name["GE1/0/1"].severity == "no_light"
    assert by_name["GE1/0/2"].severity == "no_module"
    assert by_name["GE1/0/3"].severity == "link_abnormal"
    assert by_name["GE1/0/4"].severity == "alarm"
    assert by_name["GE1/0/4"].tx_high_alarm == 4.0
    assert all(
        {"status", "threshold_source"}.isdisjoint(item.model_dump())
        for item in page.items
    )


def test_optical_mapping_distinguishes_missing_module_from_missing_rx(
    tmp_path: Path,
) -> None:
    query, _operation, _adapter, h3c, _huawei, _ac = _fixture(tmp_path)
    paths = PathResolver(
        app_root=Path(__file__).parents[1], data_root=tmp_path / "runtime"
    )
    DeviceFactRepository(Database(paths.site_db_path("demo"))).replace_optical_modules(
        str(h3c.device_uuid),
        [
            {"interface_name": "GE1/0/1"},
            {"interface_name": "GE1/0/2", "module_model": "SFP-GE-LX"},
            {"interface_name": "GE1/0/3", "tx_power": "-6.1"},
            {"interface_name": "GE1/0/4", "rx_low_alarm": "-19.0"},
            {
                "interface_name": "GE1/0/5",
                "status": "no_light",
            },
            {
                "interface_name": "GE1/0/6",
                "status": "no_module",
                "module_model": "stale-model",
                "module_serial_number": "stale-serial",
                "module_vendor": "stale-vendor",
                "wavelength": "1310 nm",
                "transmission_distance": "10 km",
                "connector_type": "LC",
                "rx_power": "-8.0",
            },
            {
                "interface_name": "GE1/0/7",
                "status": "no_light",
                "module_model": "SFP-GE-LX",
            },
        ],
    )

    page = query.transceivers(str(h3c.device_uuid), page=1, page_size=10)
    by_name = {item.interface_name: item for item in page.items}

    assert by_name["GE1/0/1"].severity == "no_module"
    assert by_name["GE1/0/1"].severity_reason == "未检测到光模块"
    assert by_name["GE1/0/2"].severity == "no_light"
    assert by_name["GE1/0/3"].severity == "no_light"
    assert by_name["GE1/0/4"].severity == "no_light"
    assert by_name["GE1/0/5"].severity == "no_module"
    assert by_name["GE1/0/6"].severity == "no_module"
    assert by_name["GE1/0/6"].module_model is None
    assert by_name["GE1/0/6"].module_serial_number is None
    assert by_name["GE1/0/6"].module_vendor is None
    assert by_name["GE1/0/6"].wavelength is None
    assert by_name["GE1/0/6"].transmission_distance is None
    assert by_name["GE1/0/6"].connector_type is None
    assert by_name["GE1/0/7"].severity == "no_light"


def test_optical_public_reason_uses_exact_chinese_mapping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    query, _operation, _adapter, h3c, _huawei, _ac = _fixture(tmp_path)
    paths = PathResolver(
        app_root=Path(__file__).parents[1], data_root=tmp_path / "runtime"
    )
    facts = DeviceFactRepository(Database(paths.site_db_path("demo")))
    expected = (
        ("no_module", "Optical module is not present", "未检测到光模块"),
        (
            "no_light",
            "RX power is missing or <= -35 dBm",
            "接收光功率缺失或 ≤ -35 dBm",
        ),
        ("link_abnormal", "Port is DOWN", "端口状态为 DOWN"),
        ("unknown", "RX threshold is missing", "接收光功率阈值缺失"),
        (
            "normal",
            "RX power is above maintenance normal line",
            None,
        ),
        (
            "notice",
            "RX power is below maintenance normal line",
            "接收光功率位于维护正常线以下",
        ),
        (
            "warning",
            "RX power is between alarm low and warning low threshold",
            "接收光功率介于告警低阈值与警告低阈值之间",
        ),
        (
            "alarm",
            "RX power below alarm low threshold",
            "接收光功率低于告警低阈值",
        ),
        ("notice", "Vendor-specific optical reason", "Vendor-specific optical reason"),
    )
    facts.replace_optical_modules(
        str(h3c.device_uuid),
        [{"interface_name": f"GE1/0/{index}"} for index in range(1, 10)],
    )
    results = iter(expected)

    def fake_compute(_record: dict[str, object]) -> SimpleNamespace:
        severity, reason, _translated = next(results)
        return SimpleNamespace(
            severity=severity,
            reason=reason,
            warning_source="missing",
        )

    monkeypatch.setattr(
        "netconsole.services.device_detail_query_service.compute_optical_severity",
        fake_compute,
    )

    page = query.transceivers(str(h3c.device_uuid), page=1, page_size=20)
    by_name = {item.interface_name: item for item in page.items}
    for index, (severity, _reason, translated) in enumerate(expected, start=1):
        item = by_name[f"GE1/0/{index}"]
        assert item.severity == severity
        assert item.severity_reason == translated
        assert "threshold_source" not in item.model_dump()


def test_nullable_fact_fields_and_dataset_own_source_time(tmp_path: Path) -> None:
    query, _operation, _adapter, h3c, _huawei, _ac = _fixture(tmp_path)

    overview = query.overview(str(h3c.device_uuid))
    interfaces = query.interfaces(str(h3c.device_uuid), page=1, page_size=10)
    lldp = query.lldp(str(h3c.device_uuid), page=1, page_size=10)
    assert overview.cpu_usage is None
    assert overview.memory_usage is None
    interface_payload = interfaces.items[0].model_dump()
    for removed_field in (
        "input_rate",
        "output_rate",
        "input_errors",
        "output_errors",
        "crc_errors",
        "last_change",
    ):
        assert removed_field not in interface_payload
    assert interfaces.source.collected_at == "2026-07-18T10:00:00"
    assert interfaces.source.task_id is None
    lldp_payload = lldp.items[0].model_dump()
    assert "capabilities" not in lldp_payload
    assert "model" not in lldp_payload


def test_overview_counts_existing_datasets_without_device_fact(
    tmp_path: Path,
) -> None:
    query, _operation, _adapter, _h3c, _huawei, _ac = _fixture(tmp_path)
    paths = PathResolver(
        app_root=Path(__file__).parents[1], data_root=tmp_path / "runtime"
    )
    database = Database(paths.site_db_path("demo"))
    device = DeviceRepository(database).create(
        Device(
            name="SW-NO-FACT",
            primary_address="192.0.2.90",
            device_vendor="H3C",
            device_type="SW",
        )
    )
    facts = DeviceFactRepository(database)
    facts.replace_device_interfaces(
        str(device.device_uuid),
        [{"interface_name": "GE1/0/1", "link_status": "UP"}],
    )
    facts.replace_optical_modules(
        str(device.device_uuid),
        [{"interface_name": "GE1/0/1", "status": "no_module"}],
    )
    facts.replace_lldp_neighbors(
        str(device.device_uuid),
        [{"local_interface": "GE1/0/1", "neighbor_sysname": "peer"}],
    )

    overview = query.overview(str(device.device_uuid))
    assert overview.snapshot.available is False
    assert overview.counts.interfaces == 1
    assert overview.counts.transceivers == 1
    assert overview.counts.lldp_neighbors == 1


def test_ac_and_mr_business_associations_are_real_named_summaries(
    tmp_path: Path,
) -> None:
    query, _operation, _adapter, _h3c, _huawei, ac = _fixture(tmp_path)
    paths = PathResolver(
        app_root=Path(__file__).parents[1], data_root=tmp_path / "runtime"
    )
    mr = DeviceRepository(Database(paths.site_db_path("demo"))).create(
        Device(
            name="MR-01",
            system_name="MR-SYSTEM",
            primary_address="192.0.2.40",
            device_vendor="H3C",
            device_type="MR",
        )
    )

    ac_page = query.business_associations(str(ac.device_uuid), page=1, page_size=10)
    mr_page = query.business_associations(str(mr.device_uuid), page=1, page_size=10)

    assert ac_page.source.available is True
    assert ac_page.items[0].association_type == "fit_ap"
    assert ac_page.items[0].fit_ap is not None
    assert ac_page.items[0].fit_ap.radio1_status == "up"
    assert ac_page.items[0].fit_ap.lldp_status == "matched"
    assert {
        "ac_id",
        "ac_name",
        "ip_address",
        "model",
        "state_display",
        "switch_name",
        "switch_interface",
        "optical_severity",
    }.isdisjoint(ac_page.items[0].fit_ap.model_dump())
    assert mr_page.source.available is True
    assert mr_page.items[0].association_type == "online_mr_session"
    assert mr_page.items[0].online_mr_session is not None
    assert mr_page.items[0].online_mr_session.mesh_available is True
    assert mr_page.items[0].online_mr_session.rssi_available is True
    assert mr_page.items[0].online_mr_session.fping_available is True
    assert mr_page.items[0].online_mr_session.iperf_available is True
    assert {
        "mr_name",
        "phase",
        "duration_seconds",
        "task_id",
    }.isdisjoint(mr_page.items[0].online_mr_session.model_dump())
    assert "attributes" not in ac_page.model_dump_json()
    assert "session_path" not in mr_page.model_dump_json()


def test_switch_business_total_counts_only_exact_device_matches(
    tmp_path: Path,
) -> None:
    query, _operation, _adapter, h3c, _huawei, _ac = _fixture(tmp_path)

    class MixedReader:
        def list_rows(self, _site_id: str, **_kwargs) -> _BusinessPage:
            return _BusinessPage(
                [_BusinessRow("SW-01"), _BusinessRow("SW-010")], 2
            )

    query.business_reader = MixedReader()
    page = query.business_associations(str(h3c.device_uuid), page=1, page_size=10)
    assert page.total == 1
    assert len(page.items) == 1
    assert page.truncated is False


def test_device_fact_platform_conflict_fails_closed_for_capability_and_start(
    tmp_path: Path,
) -> None:
    query, operation, _adapter, h3c, _huawei, _ac = _fixture(tmp_path)
    paths = PathResolver(
        app_root=Path(__file__).parents[1], data_root=tmp_path / "runtime"
    )
    DeviceFactRepository(Database(paths.site_db_path("demo"))).upsert_device_fact(
        {
            "device_uuid": str(h3c.device_uuid),
            "vendor": "H3C",
            "software_version": "Huawei Versatile Routing Platform VRP V8",
            "collected_at": "2026-07-19T14:00:00",
            "updated_at": "2026-07-19T14:00:00",
        }
    )

    overview = query.overview(str(h3c.device_uuid))
    assert overview.platform_facts.platform == "vrp"
    assert overview.command_profile.executable is False
    with pytest.raises(DeviceCommandProfileNotFound, match="Comware"):
        operation.start(str(h3c.device_uuid), DEVICE_INVENTORY_OPERATION_ID)


def test_severity_filter_reports_bounded_transceiver_scan(
    tmp_path: Path,
) -> None:
    query, _operation, _adapter, h3c, _huawei, _ac = _fixture(tmp_path)
    project_root = Path(__file__).parents[1]
    paths = PathResolver(app_root=project_root, data_root=tmp_path / "runtime")
    facts = DeviceFactRepository(Database(paths.site_db_path("demo")))
    facts.replace_optical_modules(
        str(h3c.device_uuid),
        [
            {
                "interface_name": f"GE1/0/{index}",
                "rx_power": "-10.0 dBm",
                "rx_low_warning": "-16.99 dBm",
                "collected_at": "2026-07-19T10:00:00",
            }
            for index in range(1, 1002)
        ],
    )
    severity_page = query.transceivers(
        str(h3c.device_uuid), severity="normal", page=1, page_size=10
    )

    assert severity_page.truncated is True
    assert severity_page.total == 1000
    assert severity_page.source.reason is not None


def test_tasks_config_and_business_dtos_redact_paths_and_secrets(tmp_path: Path) -> None:
    query, _operation, _adapter, h3c, _huawei, _ac = _fixture(tmp_path)

    tasks = query.tasks(str(h3c.device_uuid), page=1, page_size=1)
    payload = tasks.model_dump_json()
    assert tasks.total == 1
    assert "C:\\private" not in payload
    assert "secret-value" not in payload
    assert "token=abc" not in payload

    snapshots = query.config_snapshots(
        str(h3c.device_uuid), page=1, page_size=10
    )
    snapshot_payload = snapshots.model_dump_json()
    assert snapshots.total == 1
    assert snapshots.items[0].filename is None
    assert snapshots.items[0].size_bytes is None
    assert "C:\\private" not in snapshot_payload
    assert "secret-value" not in snapshot_payload

    business = query.business_associations(
        str(h3c.device_uuid), page=1, page_size=10
    )
    assert business.source.available is True
    assert business.items[0].association_type == "trackside_ap"


def test_device_operation_is_idempotent_and_profile_fails_closed(tmp_path: Path) -> None:
    _query, operation, adapter, h3c, huawei, _ac = _fixture(tmp_path)

    first = operation.start(
        str(h3c.device_uuid),
        DEVICE_INVENTORY_OPERATION_ID,
        idempotency_key="request-0001",
    )
    repeated = operation.start(
        str(h3c.device_uuid),
        DEVICE_INVENTORY_OPERATION_ID,
        idempotency_key="request-0001",
    )
    active_retry = operation.start(
        str(h3c.device_uuid), DEVICE_INVENTORY_OPERATION_ID
    )

    assert first.reused is False
    assert repeated.task_id == first.task_id
    assert repeated.reused is True
    assert active_retry.task_id == first.task_id
    assert len(adapter.jobs) == 1
    assert "commands" not in adapter.jobs[0].params
    assert adapter.jobs[0].params["profile_id"].startswith("h3c.comware.switch")
    assert adapter.jobs[0].params["profile_version"] == 1
    assert adapter.jobs[0].params["software_version"].startswith("H3C Comware")
    assert adapter.jobs[0].params["platform"] == "comware"
    assert adapter.jobs[0].params["idempotency_key"] == "request-0001"

    with pytest.raises(DeviceCommandProfileNotFound, match="仅支持 H3C"):
        operation.start(str(huawei.device_uuid), DEVICE_INVENTORY_OPERATION_ID)


def test_wireless_controller_operation_keeps_identity_and_submits_profile(
    tmp_path: Path,
) -> None:
    _query, operation, adapter, _h3c, _huawei, ac = _fixture(tmp_path)
    original_uuid = str(ac.device_uuid)

    submitted = operation.start(original_uuid, DEVICE_INVENTORY_OPERATION_ID)

    assert submitted.reused is False
    assert submitted.profile_id == (
        "h3c.comware.wireless_controller.generic.device-inventory.v1"
    )
    assert len(adapter.jobs) == 1
    assert adapter.jobs[0].params["device_uuids"] == [original_uuid]
    assert adapter.jobs[0].params["platform_role"] == "wireless_controller"
    stored = operation.gateway.get_device(original_uuid)
    assert stored is not None
    assert str(stored.device_uuid) == original_uuid
    assert stored.device_type == "AC"


def test_wireless_controller_worker_keeps_partial_results(
    tmp_path: Path,
    monkeypatch,
) -> None:
    query, operation, adapter, _h3c, _huawei, ac = _fixture(tmp_path)
    original_uuid = str(ac.device_uuid)
    operation.start(original_uuid, DEVICE_INVENTORY_OPERATION_ID)
    params = dict(adapter.jobs[0].params)

    def fake_collect(device, site, *, repository, paths, cancel_check=None):
        assert str(device.device_uuid) == original_uuid
        assert device.device_type == "AC"
        assert site == "demo"
        assert cancel_check is not None
        run_uuid = "wireless-controller-partial-run"
        repository.create_collect_run(
            {
                "collect_run_uuid": run_uuid,
                "collect_type": "device_details",
                "status": "running",
                "started_at": "2026-07-29T10:00:00+00:00",
                "created_at": "2026-07-29T10:00:00+00:00",
            }
        )
        repository.upsert_device_fact(
            {
                "device_uuid": original_uuid,
                "sysname": "AC-CORE",
                "vendor": "H3C",
                "collect_run_uuid": run_uuid,
                "collected_at": "2026-07-29T10:00:00+00:00",
                "updated_at": "2026-07-29T10:00:00+00:00",
            }
        )
        repository.replace_device_interfaces(
            original_uuid,
            [{"interface_name": "GE1/0/1", "link_status": "UP"}],
        )
        repository.replace_lldp_neighbors(
            original_uuid,
            [{"local_interface": "GE1/0/1", "neighbor_sysname": "SW-CORE"}],
        )
        repository.update_collect_run_status(
            run_uuid,
            "partial_success",
            error_message="光模块命令不支持",
        )
        return SimpleNamespace(
            success=True,
            collect_run_uuid=run_uuid,
            facts_updated=True,
            interfaces_updated=1,
            optical_modules_updated=0,
            lldp_neighbors_updated=1,
            error_message="光模块命令不支持",
        )

    monkeypatch.setattr(
        "netconsole.services.h3c_collect_service.collect_h3c_device_details",
        fake_collect,
    )
    result = run_device_inventory_refresh(
        JobContext(
            "wireless-controller-refresh",
            "device_detail_collect",
            params,
            None,
            lambda: False,
            operation.paths,
        )
    )

    assert result["success"] == 1
    assert result["failed"] == 0
    assert result["results"][0]["collect_status"] == "partial_success"
    assert result["results"][0]["optical_modules_updated"] == 0
    assert query.overview(original_uuid).system_name == "AC-CORE"
    assert query.interfaces(original_uuid, page=1, page_size=10).total == 1
    assert query.lldp(original_uuid, page=1, page_size=10).total == 1
    stored = operation.gateway.get_device(original_uuid)
    assert stored is not None
    assert stored.device_type == "AC"
