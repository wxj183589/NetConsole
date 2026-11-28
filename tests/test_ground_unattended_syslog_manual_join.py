from __future__ import annotations

from types import SimpleNamespace

import pytest

from netconsole.models.api.ground_unattended import GroundSyslogControlRequestDTO
from netconsole.services.ground_unattended.application_service import (
    GroundUnattendedApplicationService,
    GroundUnattendedError,
)


class _JoinHarness:
    """Run the command admission logic without ever opening a device session."""

    task_service = None

    def __init__(
        self,
        *,
        status: str = "ONLINE",
        data_state: str = "RUNNING",
        transport: str = "UDP",
        tcp_listen_address: str = "",
    ) -> None:
        self.audit = []
        self.status = status
        self.data_state = data_state

        def record_config_check(
            device_uuid: str,
            repair_enabled: bool,
            syslog_transport: str = "UDP",
            task_id: str = "",
        ) -> None:
            self.audit.append((device_uuid, repair_enabled, syslog_transport, task_id))

        self.repository = SimpleNamespace(
            get_profile=lambda: SimpleNamespace(
                syslog_transport=transport, syslog_server_ip="127.0.0.1", syslog_server_port=15514,
            ),
            list_inventory=lambda: [{
                "endpoints": [{
                    "device_uuid": "mr-online",
                    "management_ip": "192.0.2.100",
                    "backup_management_ip": "192.0.2.101",
                }]
            }],
        )
        self.supervisor = SimpleNamespace(
            # FleetPing summaries intentionally have NO "status" field.
            fleet_ping=SimpleNamespace(target_summaries=lambda: [{"mr_id": "mr-online", "success_count": 5}]),
            syslog_receiver=SimpleNamespace(
                health_snapshot=lambda: {"tcp_listen_address": tcp_listen_address}
            ),
            request_config_check=record_config_check,
        )

    def _active(self, site_id: str):
        return {"run_id": "ground-test", "state": "RUNNING"}

    def _require_collection_enabled(self):
        """Mirror the service admission hook without opening a device session."""
        return None

    def _validate_network_profile(self, profile, *, require_syslog: bool):
        assert require_syslog

    def heartbeat(self, site_id: str, *, page_size: int):
        assert page_size == 200
        return SimpleNamespace(
            data_state=self.data_state,
            mrs=[SimpleNamespace(mr_uuid="mr-online", status=self.status)],
        )


def test_manual_syslog_join_uses_online_heartbeat_not_fleet_ping_summary() -> None:
    harness = _JoinHarness()
    result = GroundUnattendedApplicationService.request_syslog_control(
        harness, "demo", GroundSyslogControlRequestDTO(device_uuids=["mr-online"], mode="JOIN")
    )
    assert result.task_id.startswith("ground-syslog-")
    assert harness.audit == [("mr-online", True, "UDP", result.task_id)]


@pytest.mark.parametrize("address", ["", "127.0.0.1:15515", "192.0.2.4:15514"])
def test_tcp_syslog_join_requires_a_listening_tcp_receiver(address: str) -> None:
    harness = _JoinHarness(transport="TCP", tcp_listen_address=address)

    with pytest.raises(GroundUnattendedError) as exc:
        GroundUnattendedApplicationService.request_syslog_control(
            harness,
            "demo",
            GroundSyslogControlRequestDTO(device_uuids=["mr-online"], mode="JOIN"),
        )

    assert exc.value.code == "SYSLOG_TCP_RECEIVER_NOT_READY"
    assert harness.audit == []


def test_tcp_syslog_join_passes_transport_to_device_configuration_task() -> None:
    harness = _JoinHarness(
        transport="TCP",
        tcp_listen_address="127.0.0.1:15514",
    )

    result = GroundUnattendedApplicationService.request_syslog_control(
        harness,
        "demo",
        GroundSyslogControlRequestDTO(device_uuids=["mr-online"], mode="JOIN"),
    )

    assert harness.audit == [("mr-online", True, "TCP", result.task_id)]


@pytest.mark.parametrize("status,data_state,code", [
    ("OFFLINE", "RUNNING", "MR_NOT_ONLINE"),
    ("ONLINE", "STALE", "MR_HEARTBEAT_NOT_RUNNING"),
    ("ONLINE", "PAUSED", "MR_HEARTBEAT_NOT_RUNNING"),
])
def test_manual_syslog_join_rejects_unavailable_heartbeat(
    status: str, data_state: str, code: str,
) -> None:
    harness = _JoinHarness(status=status, data_state=data_state)
    with pytest.raises(GroundUnattendedError) as exc:
        GroundUnattendedApplicationService.request_syslog_control(
            harness, "demo", GroundSyslogControlRequestDTO(device_uuids=["mr-online"], mode="JOIN")
        )
    assert exc.value.code == code
    assert harness.audit == []
