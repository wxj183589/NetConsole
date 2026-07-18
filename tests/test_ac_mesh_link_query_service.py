from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

from ac_mesh_link_web_fixture import build_ac_mesh_link_fixture
from netconsole.core.paths import PathResolver
from netconsole.services.ac.mesh_link_query_service import AcMeshLinkQueryService


def _fingerprint(path: Path) -> tuple[str, int]:
    return hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns


def test_mesh_link_query_reads_latest_snapshot_and_enriches_exact_matches(tmp_path: Path) -> None:
    paths, devices_db, mesh_db = build_ac_mesh_link_fixture(tmp_path)
    service = AcMeshLinkQueryService(paths, now_provider=lambda: datetime(2026, 7, 14, 12, 0, 10))
    before = (_fingerprint(devices_db), _fingerprint(mesh_db))

    summary = service.get_summary("demo")
    links = service.list_current_links("demo")
    mrs = service.list_mrs("demo")
    mr_detail = service.get_mr_link_detail("demo", "mr-01-ct")
    raw_tail = service.get_raw_tail("demo")

    assert summary.registered_mrs == 3
    assert summary.active_links == 2
    assert summary.unmatched_links == 1
    assert summary.offline_ap_links == 1
    assert summary.data_status == "fresh"
    by_mr = {item.mr_name: item for item in links.items}
    assert by_mr["列车01-MR-CT"].peer_ap_name == "AP-Online"
    assert by_mr["列车01-MR-CT"].peer_radio == "Mesh Radio 1"
    assert by_mr["列车01-MR-CT"].match_method == "peer_mac"
    assert by_mr["列车01-MR-CT"].ap_rx_power == "-10 dBm"
    assert by_mr["列车01-MR-CT"].switch_rx_power == "-40 dBm"
    assert by_mr["列车02-MR-CT"].peer_ap_name == "AP-Offline"
    assert by_mr["列车02-MR-CT"].match_method == "peer_name"
    assert by_mr["列车99-MR-CT"].match_method == "unmatched"
    assert by_mr["列车99-MR-CT"].peer_ap_name == "AP-Unknown"
    assert by_mr["列车99-MR-CT"].ap_rx_power == ""
    assert by_mr["列车99-MR-CT"].switch_rx_power == ""
    by_device = {item.mr_device_id: item for item in mrs.items if item.mr_device_id}
    assert by_device["mr-01-ct"].online_status == "online"
    assert by_device["mr-01-ct"].ap_rx_power == "-10 dBm"
    assert by_device["mr-01-ct"].switch_rx_power == "-40 dBm"
    assert by_device["mr-02-ct"].online_status == "offline"
    assert by_device["mr-03-ct"].online_status == "offline"
    assert {"link_status", "channel", "bandwidth", "ap_online_status", "optical_status"}.isdisjoint(
        by_mr["列车01-MR-CT"].model_dump()
    )
    assert {"link_status", "ap_online_status", "optical_status"}.isdisjoint(
        by_device["mr-01-ct"].model_dump()
    )
    assert mr_detail is not None
    assert mr_detail.recent_events[0].ap_name == "AP-Online"
    assert raw_tail.available is False
    assert "仅持久化结构化快照" in raw_tail.message
    assert "client" not in str(summary.model_dump()).casefold()
    assert "client" not in str(links.model_dump()).casefold()
    assert (_fingerprint(devices_db), _fingerprint(mesh_db)) == before


def test_mesh_link_query_marks_old_snapshot_and_mr_state_as_stale(tmp_path: Path) -> None:
    paths, _devices_db, _mesh_db = build_ac_mesh_link_fixture(tmp_path)
    service = AcMeshLinkQueryService(paths, now_provider=lambda: datetime(2026, 7, 14, 12, 10, 0))

    summary = service.get_summary("demo")
    mrs = service.list_mrs("demo")

    assert summary.data_status == "stale"
    assert summary.active_links == 0
    assert summary.stale_mrs == len(mrs.items)
    assert {item.online_status for item in mrs.items} == {"stale"}


def test_mesh_link_query_returns_empty_read_only_result_without_snapshot(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path)
    paths.ensure_site_dirs("demo")
    service = AcMeshLinkQueryService(paths)

    summary = service.get_summary("demo")

    assert summary.link_total == 0
    assert summary.unknown_mrs == 0
    assert "暂无 AC Mesh-Link 快照" in summary.message
