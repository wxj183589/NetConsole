from __future__ import annotations

import json
from dataclasses import replace

import pytest

from netconsole.models.online_mr_agent import (
    ONLINE_MR_AGENT_PACKAGE_REQUIRED_DIRECTORIES,
    ONLINE_MR_AGENT_PACKAGE_REQUIRED_FILES,
    OnlineMrAgentDisplayContext,
    OnlineMrAgentStartRequest,
    OnlineMrAgentStatus,
    map_online_mr_agent_status,
    validate_online_mr_agent_package_entries,
)
from netconsole.models.online_mr_application import OnlineMrExecutorKind, OnlineMrStartRequest
from netconsole.models.online_mr_models import (
    FpingConfig,
    IperfTrafficConfig,
    OnlineMrConnectionConfig,
    OnlineMrIntervals,
    OnlineMrRadioConfig,
    OnlineMrTaskToggles,
)
from netconsole.models.task_state import TaskState


def _request() -> OnlineMrStartRequest:
    config = OnlineMrConnectionConfig(
        site="site-a",
        mr_id="mr-14",
        mr_name="14车 MR",
        safe_mr_name="14车_MR__mr-14",
        device_id=14,
        device_name="14车 MR",
        host="192.0.2.14",
        protocol="SSH",
        port=22,
        username="operator",
        password="secret-password",
        intervals=OnlineMrIntervals(mesh_link=1, channel_busy=9, ap_radio_statistics=10, switch_history=300),
        tasks=OnlineMrTaskToggles(wireless_status=True),
        radio=OnlineMrRadioConfig(channel_busy_radio=2, ap_radio_statistics_radio=2, wireless_status_radio=2),
        fping=FpingConfig(
            enabled=True,
            target="192.0.2.14",
            preset_name="远程验收 1s / 4s",
            packet_size=64,
            interval_ms=1000,
            loss_threshold_ms=4000,
            loss_warn_percent=10,
            latency_warn_ms=4000,
        ),
        iperf=IperfTrafficConfig(
            enabled=True,
            server_ip="198.51.100.10",
            protocol="UDP",
            direction="download",
            parallel=2,
            udp_bitrate_mbps=20,
            udp_report_threshold_mbps=18,
        ),
        duration_minutes=2,
    )
    return OnlineMrStartRequest(
        site_id="site-a",
        device_id=14,
        device_name="14车 MR",
        mr_name="14车 MR",
        config=config,
        executor_kind=OnlineMrExecutorKind.AGENT,
        agent_id="agent-nb-01",
        owner="legacy_qt",
    )


def test_agent_start_contract_expresses_collection_traffic_and_context_without_public_password() -> None:
    request = OnlineMrAgentStartRequest.from_application_request(
        _request(),
        display_context=OnlineMrAgentDisplayContext(site="宁波12号线", station="站点A", section="A-B", direction="上行"),
    )

    private_payload = request.transport_payload()
    public_payload = request.public_payload()
    public_json = json.dumps(public_payload, ensure_ascii=False)

    assert private_payload["target"]["password"] == "secret-password"
    assert "password" not in public_payload["target"]
    assert "secret-password" not in public_json
    assert "secret-password" not in request.model_dump_json()
    assert "secret-password" not in repr(request)
    assert public_payload["session"] == {
        "site": "site-a",
        "site_id": "site-a",
        "site_name": "site-a",
        "device_id": "14",
        "device_name": "14车 MR",
        "mr_id": "mr-14",
        "mr_name": "14车 MR",
        "owner": "legacy_qt",
        "executor": "AGENT",
        "agent_id": "agent-nb-01",
    }
    assert public_payload["items"]["terminal_monitor"] is True
    assert public_payload["intervals"]["switch_history"] == 300
    assert public_payload["radio"]["wireless_status_radio"] == 2
    assert public_payload["fping"]["timeout_ms"] == 4000
    assert public_payload["iperf"]["bandwidth_mbps"] == 20
    assert public_payload["iperf"]["reverse"] is True
    assert public_payload["display_context"]["section"] == "A-B"
    assert public_payload["duration_minutes"] == 2
    assert public_payload["stop_strategy"] == "agent_duration"


@pytest.mark.parametrize(
    ("status", "task_state", "remote_terminal"),
    [
        (OnlineMrAgentStatus.CREATED, TaskState.STARTING, False),
        (OnlineMrAgentStatus.RUNNING, TaskState.RUNNING, False),
        (OnlineMrAgentStatus.STOPPING, TaskState.STOPPING, False),
        (OnlineMrAgentStatus.FAILED, TaskState.FAILED, True),
        (OnlineMrAgentStatus.ABORTED, TaskState.CANCELLED, True),
        (OnlineMrAgentStatus.FORCE_STOPPED, TaskState.CANCELLED, True),
    ],
)
def test_agent_status_contract_maps_active_and_terminal_states(
    status: OnlineMrAgentStatus,
    task_state: TaskState,
    remote_terminal: bool,
) -> None:
    mapped = map_online_mr_agent_status(status)
    assert mapped.task_state is task_state
    assert mapped.remote_terminal is remote_terminal


def test_agent_completed_waits_for_package_import_before_controller_terminal() -> None:
    waiting = map_online_mr_agent_status("completed")
    imported = map_online_mr_agent_status("completed", package_imported=True)
    download_failed = map_online_mr_agent_status("completed", package_failed=True)

    assert waiting.remote_terminal is True
    assert waiting.controller_terminal is False
    assert waiting.package_required is True
    assert waiting.phase.value == "FINALIZING"
    assert imported.task_state is TaskState.COMPLETED
    assert imported.controller_terminal is True
    assert imported.mapping_state.value == "TERMINAL"
    assert download_failed.task_state is TaskState.FAILED
    assert download_failed.controller_terminal is True


def test_agent_package_contract_requires_fact_files_and_rejects_private_artifacts() -> None:
    valid = [f"session-1/{name}" for name in ONLINE_MR_AGENT_PACKAGE_REQUIRED_FILES]
    assert validate_online_mr_agent_package_entries(valid) == ()
    assert ONLINE_MR_AGENT_PACKAGE_REQUIRED_DIRECTORIES == {"raw", "parsed", "view", "logs", "outputs"}

    invalid = [
        *valid,
        "session-1/stop.request",
        "session-1/meta/request.private.json",
        "session-1/output.tmp",
        "C:/Agent/private.log",
    ]
    issues = validate_online_mr_agent_package_entries(invalid)

    assert any("stop.request" in issue for issue in issues)
    assert any("request.private.json" in issue for issue in issues)
    assert any("output.tmp" in issue for issue in issues)
    assert any("不安全的包路径" in issue for issue in issues)


def test_agent_contract_rejects_local_or_unassigned_requests() -> None:
    request = _request()
    with pytest.raises(ValueError, match="executor=AGENT"):
        OnlineMrAgentStartRequest.from_application_request(
            replace(request, executor_kind=OnlineMrExecutorKind.LOCAL)
        )
    with pytest.raises(ValueError, match="agent_id"):
        OnlineMrAgentStartRequest.from_application_request(replace(request, agent_id=""))
