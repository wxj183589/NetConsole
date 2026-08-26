from __future__ import annotations

from netconsole.core.database import Database
from netconsole.repositories.ac_repository import AcRepository


def _resource(*, interface: str, collected_at: str) -> dict[str, object]:
    return {
        "ap_uuid": "ap-1",
        "ap_name": "AP-1",
        "ap_mac": "0011-2233-4455",
        "lldp_source": "ac_bulk_lldp",
        "lldp_local_interface": "GigabitEthernet1/0/1",
        "lldp_neighbor_name": "SW-1",
        "lldp_neighbor_mac": "00:11:22:33:44:55",
        "lldp_neighbor_interface": interface,
        "collected_at": collected_at,
    }


def test_lldp_retention_keeps_current_and_only_true_changes(tmp_path) -> None:
    repository = AcRepository(Database(tmp_path / "devices.db"))
    repository.database.initialize()

    repository.replace_fit_ap_resources(
        "ac-1", [_resource(interface="GigabitEthernet1/0/2", collected_at="2026-08-01T00:00:00")]
    )
    assert repository.list_fit_ap_lldp_history_by_ap("ap-1") == []
    assert repository.list_latest_ap_lldp_history("ap-1")["neighbor_interface"] == "GigabitEthernet1/0/2"

    repository.replace_fit_ap_resources(
        "ac-1", [_resource(interface="GigabitEthernet1/0/2", collected_at="2026-08-01T00:01:00")]
    )
    assert repository.count_fit_ap_history("lldp", "ap-1") == 0

    for index in range(1, 13):
        repository.replace_fit_ap_resources(
            "ac-1",
            [
                _resource(
                    interface=f"GigabitEthernet1/0/{index + 2}",
                    collected_at=f"2026-08-01T00:{index + 1:02d}:00",
                )
            ],
        )

    history = repository.list_fit_ap_lldp_history_by_ap("ap-1", limit=100)
    assert len(history) == 10
    assert [row["neighbor_interface"] for row in history] == [
        f"GigabitEthernet1/0/{index + 2}" for index in range(12, 2, -1)
    ]
    assert repository.list_latest_ap_lldp_history("ap-1")["neighbor_interface"] == "GigabitEthernet1/0/14"
    with repository.database.connect_readonly() as connection:
        authority = connection.execute(
            "SELECT value FROM fit_ap_lldp_retention_meta WHERE key='authority'"
        ).fetchone()
        assert authority[0] == "bounded_v1"
        assert connection.execute(
            "SELECT COUNT(*) FROM fit_ap_lldp_history WHERE resource_key='ap-1'"
        ).fetchone()[0] == 10

