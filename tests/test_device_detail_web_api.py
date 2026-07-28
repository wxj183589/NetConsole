from __future__ import annotations

import inspect
from pathlib import Path

from fastapi.testclient import TestClient

from netconsole.backend.api import device_management_router
from netconsole.backend.api.main import create_app
from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.models.device import Device
from netconsole.repositories.device_fact_repository import DeviceFactRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.job_center.task_application_service import TaskApplicationService


class _CapturingAdapter:
    def __init__(self, tasks: TaskApplicationService) -> None:
        self.tasks = tasks
        self.jobs = []

    def start_job(self, job, **_kwargs) -> str:
        self.jobs.append(job)
        return self.tasks.prepare(job).job.job_id


def _client(tmp_path: Path):
    project_root = Path(__file__).parents[1]
    paths = PathResolver(app_root=project_root, data_root=tmp_path / "runtime")
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    device = DeviceRepository(database).create(
        Device(
            name="SW-API",
            primary_address="192.0.2.50",
            device_vendor="H3C",
            device_type="SW",
            ssh_password="api-secret",
        )
    )
    facts = DeviceFactRepository(database)
    facts.upsert_device_fact(
        {
            "device_uuid": str(device.device_uuid),
            "sysname": "SW-API",
            "software_version": "H3C Comware Software, Version 7.1.070",
            "vendor": "H3C",
            "raw_log_path": "C:\\private\\device.log",
            "collected_at": "2026-07-19T10:00:00",
            "updated_at": "2026-07-19T10:00:00",
        }
    )
    facts.replace_device_interfaces(
        str(device.device_uuid),
        [
            {
                "interface_name": "GE1/0/1",
                "link_status": "UP",
                "admin_status": "up",
                "physical_status": "up",
                "protocol_status": "up",
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
                "last_change": "2026-07-19T09:59:00",
                "input_rate": 100.0,
                "output_rate": 200.0,
                "input_errors": 1,
                "output_errors": 2,
                "crc_errors": 3,
            },
            {"interface_name": "GE1/0/2", "link_status": "DOWN"},
        ],
    )
    facts.replace_lldp_neighbors(
        str(device.device_uuid),
        [
            {
                "local_interface": "GE1/0/1",
                "neighbor_sysname": "AP-API",
                "chassis_id": "02aa.bbcc.0001",
                "ttl": 120,
                "pvid": 71,
                "port_description": "Test AP uplink",
                "capabilities": "bridge router",
                "model": "legacy-private-model",
            }
        ],
    )
    facts.replace_optical_modules(
        str(device.device_uuid),
        [{"interface_name": "GE1/0/1", "status": "no_light"}],
    )
    tasks = TaskApplicationService(
        paths=paths, site_name="demo", reconcile_on_start=False
    )
    app = create_app(
        RuntimeMode.SERVER,
        paths=paths,
        task_service=tasks,
        frontend_dist=tmp_path / "missing-web-dist",
    )
    for feature_id in ("web.device_management", "web.device_management_collect"):
        current = dict(app.state.feature_gate.features[feature_id])
        app.state.feature_gate.features[feature_id] = {
            **current,
            "enabled": True,
            "client_package": True,
        }
    adapter = _CapturingAdapter(tasks)
    app.state.device_detail_application_service.operation_service.process_adapter = adapter
    return TestClient(app), app, adapter, device


def test_device_detail_lazy_api_contract_and_refresh(tmp_path: Path) -> None:
    client, _app, adapter, device = _client(tmp_path)
    prefix = f"/api/device-management/devices/{device.device_uuid}"

    overview = client.get(f"{prefix}/overview")
    interfaces = client.get(
        f"{prefix}/interfaces", params={"page": 1, "page_size": 1}
    )
    filtered_interfaces = client.get(
        f"{prefix}/interfaces",
        params={
            "status": "UP",
            "admin_status": "up",
            "physical_status": "up",
            "protocol_status": "up",
            "media_type": "optical",
        },
    )
    detail = client.get(
        f"{prefix}/interfaces/GE1%2F0%2F1"
    )
    transceivers = client.get(f"{prefix}/transceivers")
    lldp = client.get(f"{prefix}/lldp")
    tasks = client.get(f"{prefix}/tasks", params={"page_size": 1})
    config = client.get(f"{prefix}/config-snapshots")
    business = client.get(f"{prefix}/business-associations")
    refreshed = client.post(
        f"{prefix}/refresh",
        json={
            "operation_id": "device.inventory.collect",
            "idempotency_key": "api-request-0001",
        },
    )
    repeated = client.post(
        f"{prefix}/refresh",
        json={
            "operation_id": "device.inventory.collect",
            "idempotency_key": "api-request-0001",
        },
    )

    assert overview.status_code == 200
    assert overview.json()["platform_facts"]["role"] == "switch"
    assert overview.json()["visible_sections"] == [
        "overview",
        "interfaces",
        "optical",
        "lldp",
        "configuration",
        "tasks",
        "business",
    ]
    assert all(
        item["capability_id"] != "device.health.read"
        for item in overview.json()["capabilities"]
    )
    assert overview.json()["command_profile"]["risk"] == "read_only"
    assert overview.json()["task_facts"]["latest_failed_task"] is None
    assert interfaces.status_code == 200
    assert interfaces.json()["total"] == 2
    assert interfaces.json()["total_pages"] == 2
    assert interfaces.json()["items"][0]["admin_status"] == "up"
    assert interfaces.json()["items"][0]["physical_status"] == "up"
    assert interfaces.json()["items"][0]["protocol_status"] == "up"
    assert interfaces.json()["items"][0]["media_type"] == "optical"
    assert interfaces.json()["items"][0]["port_mode"] == "hybrid"
    assert interfaces.json()["items"][0]["port_status"] == "hybrid"
    assert interfaces.json()["items"][0]["pvid"] == "71"
    assert interfaces.json()["items"][0]["native_vlan"] == "71"
    assert interfaces.json()["items"][0]["tagged_vlans"] == ["201"]
    assert (
        interfaces.json()["items"][0]["pvid_source"]
        == "show_running_config_switchvlan"
    )
    assert interfaces.json()["items"][0]["pvid_verified"] is True
    assert filtered_interfaces.status_code == 200
    assert filtered_interfaces.json()["total"] == 1
    for removed_field in (
        "input_rate",
        "output_rate",
        "input_errors",
        "output_errors",
        "crc_errors",
        "last_change",
    ):
        assert removed_field not in interfaces.json()["items"][0]
    assert detail.status_code == 200
    assert transceivers.status_code == 200
    assert "status" not in transceivers.json()["items"][0]
    assert "threshold_source" not in transceivers.json()["items"][0]
    assert transceivers.json()["items"][0]["severity"] == "no_module"
    assert transceivers.json()["items"][0]["severity_reason"] == "未检测到光模块"
    assert lldp.status_code == 200
    assert lldp.json()["items"][0]["ttl"] == 120
    assert lldp.json()["items"][0]["pvid"] == 71
    assert lldp.json()["items"][0]["port_description"] == "Test AP uplink"
    assert "capabilities" not in lldp.json()["items"][0]
    assert "model" not in lldp.json()["items"][0]
    assert tasks.status_code == 200
    assert config.status_code == 200
    assert business.status_code == 200
    assert refreshed.status_code == 202, refreshed.text
    assert repeated.status_code == 202
    assert repeated.json()["task_id"] == refreshed.json()["task_id"]
    assert repeated.json()["reused"] is True
    assert len(adapter.jobs) == 1
    combined = " ".join(
        response.text
        for response in (
            overview,
            interfaces,
            filtered_interfaces,
            detail,
            transceivers,
            lldp,
            tasks,
            config,
            business,
        )
    )
    assert "api-secret" not in combined
    assert "C:\\private" not in combined


def test_device_detail_routes_declare_contract_metadata_and_router_boundary(
    tmp_path: Path,
) -> None:
    _client_instance, app, _adapter, _device = _client(tmp_path)
    schema = app.openapi()
    routes = {
        "/api/device-management/devices/{device_uuid}/overview": "get",
        "/api/device-management/devices/{device_uuid}/interfaces": "get",
        "/api/device-management/devices/{device_uuid}/interfaces/{interface_name}": "get",
        "/api/device-management/devices/{device_uuid}/transceivers": "get",
        "/api/device-management/devices/{device_uuid}/lldp": "get",
        "/api/device-management/devices/{device_uuid}/config-snapshots": "get",
        "/api/device-management/devices/{device_uuid}/tasks": "get",
        "/api/device-management/devices/{device_uuid}/business-associations": "get",
        "/api/device-management/devices/{device_uuid}/history": "get",
        "/api/device-management/devices/{device_uuid}/refresh": "post",
    }
    for path, method in routes.items():
        operation = schema["paths"][path][method]
        assert operation["summary"]
        assert "device-management" in operation["tags"]
        assert {"404", "422", "503"}.issubset(operation["responses"])

    assert "/api/device-management/devices/{device_uuid}/health" not in schema["paths"]
    lldp_properties = schema["components"]["schemas"]["DeviceLldpNeighborDTO"][
        "properties"
    ]
    assert "capabilities" not in lldp_properties
    assert "model" not in lldp_properties
    interface_properties = schema["components"]["schemas"]["DeviceInterfaceDTO"][
        "properties"
    ]
    for removed_field in (
        "input_rate",
        "output_rate",
        "input_errors",
        "output_errors",
        "crc_errors",
        "last_change",
    ):
        assert removed_field not in interface_properties
    transceiver_properties = schema["components"]["schemas"][
        "DeviceTransceiverDTO"
    ]["properties"]
    assert "status" not in transceiver_properties
    assert {
        "severity",
        "severity_reason",
        "threshold_source",
        "device_reported_status",
        "vendor_part_number",
        "vendor_revision",
        "vendor_serial_number",
    }.issubset(transceiver_properties)
    ac_ap_properties = schema["components"]["schemas"][
        "DeviceAcApAssociationFactsDTO"
    ]["properties"]
    assert {
        "ac_id",
        "ac_name",
        "ip_address",
        "model",
        "state_display",
        "switch_name",
        "switch_interface",
        "optical_severity",
    }.isdisjoint(ac_ap_properties)
    mr_session_properties = schema["components"]["schemas"][
        "DeviceMrSessionAssociationFactsDTO"
    ]["properties"]
    assert {
        "mr_name",
        "phase",
        "duration_seconds",
        "task_id",
    }.isdisjoint(mr_session_properties)

    source = inspect.getsource(device_management_router)
    for forbidden in (
        "import sqlite3",
        "ConnectHandler",
        "subprocess",
        "send_command",
        "safe_send_command",
    ):
        assert forbidden not in source


def test_zte_transceiver_api_returns_native_thresholds_and_vendor_identity(
    tmp_path: Path,
) -> None:
    client, _app, _adapter, device = _client(tmp_path)
    paths = PathResolver(
        app_root=Path(__file__).parents[1], data_root=tmp_path / "runtime"
    )
    facts = DeviceFactRepository(Database(paths.site_db_path("demo")))
    facts.replace_optical_modules(
        str(device.device_uuid),
        [
            {
                "interface_name": "gei-0/3/0/6",
                "device_vendor": "ZTE",
                "device_reported_status": "Normal",
                "threshold_source": "zte_detail",
                "rx_power": -15.2,
                "rx_low_alarm": -28.2,
                "rx_high_alarm": 0.0,
                "tx_power": -5.5,
                "tx_low_alarm": -10.0,
                "tx_high_alarm": -0.5,
                "module_vendor": "ZTRS",
                "vendor_part_number": "SFP-GE",
                "vendor_revision": "A",
                "vendor_serial_number": "UHD507000163",
            }
        ],
    )

    response = client.get(
        f"/api/device-management/devices/{device.device_uuid}/transceivers"
    )

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["severity"] == "normal"
    assert item["severity_reason"] is None
    assert item["rx_low_alarm"] == -28.2
    assert item["rx_high_alarm"] == 0.0
    assert item["tx_low_alarm"] == -10.0
    assert item["tx_high_alarm"] == -0.5
    assert item["module_vendor"] == "ZTRS"
    assert item["vendor_part_number"] == "SFP-GE"
    assert item["vendor_revision"] == "A"
    assert item["vendor_serial_number"] == "UHD507000163"
    assert item["device_reported_status"] == "Normal"
    assert item["threshold_source"] == "zte_detail"
