from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.services.ac.mesh_link_query_service import AcMeshLinkQueryService
from netconsole.services.ac.mesh_link_refresh_service import (
    AcMeshLinkRefreshErrorCode,
    AcMeshLinkRefreshWorkerService,
    MESH_LINK_REFRESH_COMMANDS,
    MESH_LINK_SWITCH_HISTORY_COMMANDS,
)
from netconsole.services.job_center.job_context import JobContext


MESH_OUTPUT = """<AC-TEST>display wlan mesh-link ap
AP name: AP-Online
 Peer Name              Peer Mac       Local Mac      Status     RSSI Packets(Rx/Tx)
 列车12-MR-CT           1000-0000-0012 0000-0001-0001 Forwarding 52   120/100
<AC-TEST>
"""


class _FakeConnection:
    def __init__(self, outputs: dict[str, str]) -> None:
        self.outputs = outputs
        self.commands: list[str] = []
        self.closed = False

    def send_command(self, command: str, timeout: int) -> str:
        assert timeout == 20
        self.commands.append(command)
        return self.outputs.get(command, "")

    def close(self) -> None:
        self.closed = True


def _paths(tmp_path: Path) -> PathResolver:
    paths = PathResolver(tmp_path)
    paths.ensure_site_dirs("site-a")
    database = Database(paths.site_db_path("site-a"))
    database.initialize()
    now = "2026-07-14T12:00:00"
    with database.connect() as conn:
        conn.executemany(
            """
            INSERT INTO devices (
                device_uuid, name, system_name, mac_address, device_vendor, device_type,
                primary_address, ssh_enabled, ssh_port, ssh_username, ssh_password,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'H3C', ?, ?, 1, 22, ?, ?, ?, ?)
            """,
            [
                ("ac-1", "测试 AC", "AC-TEST", "", "AC", "10.0.0.1", "admin", "secret-value", now, now),
                ("mr-12", "列车12-MR-CT", "列车12-MR-CT", "1000-0000-0012", "MR", "10.0.1.12", "", "", now, now),
            ],
        )
        conn.execute(
            """
            INSERT INTO ac_fit_ap_resources (
                ac_device_uuid, ap_uuid, ap_name, ap_mac, state, state_display, site,
                rid1_bbssid, collected_at, updated_at
            ) VALUES ('ac-1', 'ap-1', 'AP-Online', '0000-0000-0001', 'R/M', '运行(主)',
                      '车站A', '0000-0001-0001', ?, ?)
            """,
            (now, now),
        )
        conn.commit()
    return paths


def _context(paths: PathResolver, *, task_id: str = "task-1", include_history: bool = False) -> JobContext:
    return JobContext(
        job_id=task_id,
        task_type="ac_mesh_link_refresh",
        params={
            "site_name": "site-a",
            "controller_id": "ac-1",
            "include_switch_history": include_history,
        },
        progress_callback=None,
        should_cancel=lambda: False,
        paths=paths,
    )


def _outputs(mesh_output: str = MESH_OUTPUT) -> dict[str, str]:
    return {
        "screen-length disable": "<AC-TEST>",
        "display clock": "12:00:00 Beijing Tue 07/14/2026",
        "display wlan mesh-link ap": mesh_output,
        "display wlan mesh-link switch-history": "Total records: 0",
    }


def test_refresh_executes_only_fixed_commands_and_atomically_saves_raw_and_snapshot(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    connection = _FakeConnection(_outputs())
    service = AcMeshLinkRefreshWorkerService(paths, connection_factory=lambda _config: connection)

    result = service.execute(_context(paths, include_history=True))

    assert connection.commands == [*MESH_LINK_REFRESH_COMMANDS, *MESH_LINK_SWITCH_HISTORY_COMMANDS]
    assert connection.closed is True
    assert result["records_count"] == 1
    snapshot_dir = paths.ac_mesh_link_snapshot_dir("site-a", str(result["session_id"]))
    assert (snapshot_dir / "raw" / "mesh_link_raw.log").is_file()
    assert (snapshot_dir / "raw" / "switch_history_raw.log").is_file()
    meta = json.loads((snapshot_dir / "snapshot_meta.json").read_text(encoding="utf-8"))
    assert meta["snapshot_id"] == result["snapshot_id"]
    assert "secret-value" not in json.dumps(meta, ensure_ascii=False)
    assert not Path(meta["raw_reference"]).is_absolute()
    query = AcMeshLinkQueryService(paths)
    assert query.get_raw_tail("site-a").available is True


def test_refresh_accepts_missing_peer_name_when_peer_mac_is_present(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    output = """12:00:00 Beijing Tue 07/14/2026
AP name: AP-Online
 Peer Name              Peer Mac       Local Mac      Status     RSSI Packets(Rx/Tx)
                        1000-0000-0012 0000-0001-0001 Forwarding 50   10/8
"""
    service = AcMeshLinkRefreshWorkerService(paths, connection_factory=lambda _config: _FakeConnection(_outputs(output)))

    result = service.execute(_context(paths))
    links = AcMeshLinkQueryService(paths).list_current_links("site-a").items

    assert result["records_count"] == 1
    assert links[0].mr_device_id == "mr-12"
    assert links[0].mr_mac == "100000000012"


def test_valid_empty_response_creates_zero_link_snapshot(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    empty = """<AC-TEST>display wlan mesh-link ap
 Peer Name              Peer Mac       Local Mac      Status     RSSI Packets(Rx/Tx)
 Total records: 0
<AC-TEST>
"""
    service = AcMeshLinkRefreshWorkerService(paths, connection_factory=lambda _config: _FakeConnection(_outputs(empty)))

    result = service.execute(_context(paths))

    assert result["records_count"] == 0
    assert AcMeshLinkQueryService(paths).get_summary("site-a").offline_mrs == 1


@pytest.mark.parametrize(
    "mesh_output",
    [
        "",
        "% Unrecognized command found at '^' position.",
        "unexpected text",
        "Peer Name  Peer Mac  Local Mac  Status  RSSI Packets(Rx/Tx)",
    ],
)
def test_invalid_response_preserves_latest_successful_snapshot(tmp_path: Path, mesh_output: str) -> None:
    paths = _paths(tmp_path)
    good = AcMeshLinkRefreshWorkerService(paths, connection_factory=lambda _config: _FakeConnection(_outputs()))
    good_result = good.execute(_context(paths, task_id="good"))
    service = AcMeshLinkRefreshWorkerService(paths, connection_factory=lambda _config: _FakeConnection(_outputs(mesh_output)))

    with pytest.raises(RuntimeError):
        service.execute(_context(paths, task_id="failed"))

    latest = AcMeshLinkQueryService(paths).list_recent_snapshots("site-a").items[0]
    assert latest.id == good_result["snapshot_id"]


def test_snapshot_write_failure_leaves_no_formal_raw_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _paths(tmp_path)
    service = AcMeshLinkRefreshWorkerService(paths, connection_factory=lambda _config: _FakeConnection(_outputs()))

    monkeypatch.setattr(
        "netconsole.services.vehicle_mr_online.VehicleMrOnlineStore.persist_snapshot",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(sqlite3.OperationalError("locked")),
    )
    with pytest.raises(RuntimeError, match="AC_MESH_LINK_SNAPSHOT_WRITE_FAILED"):
        service.execute(_context(paths))

    assert not any(paths.ac_mesh_link_snapshots_root("site-a").glob("*"))
    assert (paths.ac_mesh_link_failures_root("site-a") / "task-1").is_dir()


def test_missing_credentials_and_connection_failure_return_stable_errors(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    database = Database(paths.site_db_path("site-a"))
    with database.connect() as conn:
        conn.execute("UPDATE devices SET ssh_password = '' WHERE device_uuid = 'ac-1'")
        conn.commit()
    service = AcMeshLinkRefreshWorkerService(paths, connection_factory=lambda _config: _FakeConnection(_outputs()))
    with pytest.raises(RuntimeError, match=AcMeshLinkRefreshErrorCode.CREDENTIAL_UNAVAILABLE):
        service.execute(_context(paths))

    with database.connect() as conn:
        conn.execute("UPDATE devices SET ssh_password = 'secret-value' WHERE device_uuid = 'ac-1'")
        conn.commit()
    failing = AcMeshLinkRefreshWorkerService(
        paths,
        connection_factory=lambda _config: (_ for _ in ()).throw(OSError("secret-value must not escape")),
    )
    with pytest.raises(RuntimeError) as captured:
        failing.execute(_context(paths, task_id="connect-failed"))
    assert AcMeshLinkRefreshErrorCode.CONNECT_FAILED in str(captured.value)
    assert "secret-value" not in str(captured.value)
