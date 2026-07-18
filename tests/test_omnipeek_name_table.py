from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from netconsole.core.database import Database
from netconsole.models.device import Device
from netconsole.models.omnipeek_name_table import (
    OmniPeekExportConfig,
    OmniPeekNameEntry,
)
from netconsole.repositories.ac_repository import AcRepository
from netconsole.services.omnipeek_name_table_service import (
    OmniPeekNameTableService,
    build_omnipeek_entries,
    export_omnipeek_nam,
)
from netconsole.utils.mac_utils import H3cMacDeriveError, derive_h3c_r1_mac, derive_h3c_r2_mac, normalize_mac




def make_database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "devices.db")
    database.initialize()
    return database


def test_normalize_mac_accepts_common_h3c_formats() -> None:
    assert normalize_mac("74ad-cb9d-3320") == "74:AD:CB:9D:33:20"
    assert normalize_mac("74:ad:cb:9d:33:20") == "74:AD:CB:9D:33:20"
    assert normalize_mac("74-AD-CB-9D-33-20") == "74:AD:CB:9D:33:20"
    assert normalize_mac("74adcb9d3320") == "74:AD:CB:9D:33:20"


def test_h3c_r1_mac_derivation() -> None:
    assert derive_h3c_r1_mac("74ad-cb9d-3320") == "74:AD:CB:9D:33:2F"


def test_h3c_r2_mac_derivation() -> None:
    assert derive_h3c_r2_mac("74ad-cb9d-3320") == "74:AD:CB:9D:33:3F"
    assert derive_h3c_r2_mac("74ad-cb9d-35d0") == "74:AD:CB:9D:35:EF"


def test_h3c_r2_derivation_fails_when_second_last_hex_is_f() -> None:
    with pytest.raises(H3cMacDeriveError, match="倒数第二位为F"):
        derive_h3c_r2_mac("74ad-cb9d-33f0")


def test_onboard_mr_defaults_export_physical_r1_r2(tmp_path: Path) -> None:
    device = Device(
        id=1,
        name="列车06-MR-CT",
        system_name="NBL12-LC06-MR-CT",
        station="06车头",
        mac_address="74ad-cb9d-3320",
        group_id=1,
        device_type="Cloud-AP",
    )
    service = OmniPeekNameTableService(AcRepository(make_database(tmp_path)))
    items = service.collect_items(include_ac_fit_ap=False, include_ap_extensions=False, devices=[device], group_names={1: "车载-MR"})

    entries = build_omnipeek_entries(items, OmniPeekExportConfig(line_name="宁波地铁12号线", output_path=tmp_path / "mr.nam"))

    assert [(entry.name, entry.mac) for entry in entries] == [
        ("06车头-列车06-MR-CT-物理MAC", "74:AD:CB:9D:33:20"),
        ("06车头-列车06-MR-CT-R1", "74:AD:CB:9D:33:2F"),
        ("06车头-列车06-MR-CT-R2", "74:AD:CB:9D:33:3F"),
    ]


def test_ap_extension_exports_when_ac_fit_ap_is_empty(tmp_path: Path) -> None:
    repository = AcRepository(make_database(tmp_path))
    repository.upsert_ap_extension_point({"ap_name": "AP001", "ap_mac_display": "74ad-cb9d-35d0"})
    service = OmniPeekNameTableService(repository)

    items = service.collect_items(include_ac_fit_ap=True, include_ap_extensions=True, include_device_mr=False, ac_device_uuid="empty-ac")
    entries = build_omnipeek_entries(items, OmniPeekExportConfig(line_name="杭州地铁4号线信号A网", output_path=tmp_path / "ap.nam"))

    assert [(entry.name, entry.mac, entry.group) for entry in entries] == [
        ("AP001-物理MAC", "74:AD:CB:9D:35:D0", "杭州地铁4号线信号A网轨旁AP物理MAC组"),
        ("AP001-R1", "74:AD:CB:9D:35:DF", "杭州地铁4号线信号A网轨旁AP R1组"),
        ("AP001-R2", "74:AD:CB:9D:35:EF", "杭州地铁4号线信号A网轨旁AP R2组"),
    ]


def test_export_omnipeek_nam_writes_required_xml_fields(tmp_path: Path) -> None:
    output = tmp_path / "名称表.nam"
    entry = OmniPeekNameEntry(
        name="06车头-列车06-MR-CT-物理MAC",
        mac="74:AD:CB:9D:33:20",
        group="宁波地铁12号线车载MR物理MAC组",
        color="#7030A0",
        kind="onboard_physical",
        item_key="mr-1",
    )
    config = OmniPeekExportConfig(
        line_name="宁波地铁12号线",
        output_path=output,
        mod_time=datetime(2026, 7, 9, 11, 10, tzinfo=timezone.utc),
    )

    result = export_omnipeek_nam([entry], output, config)
    text = output.read_text(encoding="utf-8")

    assert result.output_path == output
    assert result.log_path.exists()
    assert '<?xml version="1.0" encoding="UTF-8"?>' in text
    assert '<NameTable Version="3.0">' in text
    assert '<Entry Class="Address">' in text
    assert '<Address Type="Wireless" Node="Access Point" Resolve="User">74:AD:CB:9D:33:20</Address>' in text
    assert "<Color>#7030A0</Color>" in text
    assert "<Group>宁波地铁12号线车载MR物理MAC组</Group>" in text
    assert "<Trust>Trusted</Trust>" in text
    assert "<Mod>2026-07-09T11:10:00Z</Mod>" in text
