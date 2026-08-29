from __future__ import annotations

from netconsole.core.database import Database
from netconsole.repositories.ac_repository import AcRepository


def _rows(count: int) -> list[dict[str, object | None]]:
    return [
        {
            "ap_uuid": f"ap-{index}",
            "ap_name": f"AP-{index}",
            "ap_mac": f"0011-2233-{index // 256:02x}{index % 256:02x}",
            "ap_ip": f"10.1.{index // 254}.{index % 254 + 1}",
            "apid": str(index),
            # Keep one stable field absent so the second refresh exercises
            # change-only Current/Recent10 persistence without a fallback.
            "model": None,
            "serial_number": f"SN-{index}",
            "state": "R/M",
            "rid1_status": "Up",
            "rid1_channel": "149",
            "rid1_bbssid": f"0011-2233-{index // 256:02x}{index % 256:02x}",
            "lldp_local_interface": f"GE1/0/{index % 48 + 1}",
            "lldp_neighbor_name": "SW",
            "lldp_neighbor_interface": f"GE1/0/{index % 48 + 1}",
            "lldp_neighbor_mac": f"0022-3344-{index // 256:02x}{index % 256:02x}",
        }
        for index in range(count)
    ]


def test_fit_ap_resource_refresh_uses_bounded_recent_for_1000_rows(tmp_path):
    database = Database(tmp_path / "devices.db")
    database.initialize()
    repository = AcRepository(database)
    rows = _rows(1000)

    repository.replace_fit_ap_resources("ac-1", rows)
    repository.replace_fit_ap_resources("ac-1", rows)

    with database.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM ac_fit_ap_resources WHERE ac_device_uuid = 'ac-1'"
        ).fetchone()[0] == 1000
        assert connection.execute(
            "SELECT COUNT(*) FROM ap_entities WHERE ac_device_uuid = 'ac-1'"
        ).fetchone()[0] == 1000
        assert connection.execute(
            "SELECT COUNT(*) FROM fit_ap_resource_recent"
        ).fetchone()[0] == 1000
