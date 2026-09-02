from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.repositories.device_fact_repository import DeviceFactRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.device_compatibility.service import (
    CompatibilityResolver,
    DeviceCompatibilityProfile,
    DeviceCompatibilityService,
    DeviceFingerprint,
    extract_release_from_image,
    fingerprint_from_record,
    normalize_model,
    normalize_role,
    scan_candidate_rows,
)


ROOT = Path(__file__).resolve().parents[1]


def _profile(
    profile_id: str,
    *,
    role: str = "switch",
    model: str = "*",
    major: int = 7,
    version: str = "*",
    parser: str = "generic",
) -> DeviceCompatibilityProfile:
    return DeviceCompatibilityProfile(
        profile_id=profile_id,
        vendor="H3C",
        device_role=role,
        display_role="交换机",
        model_matchers=(model,),
        platform_family="comware",
        platform_major_version=major,
        software_version_matchers=(version,),
        command_profile_id="h3c.comware.switch.generic.device-inventory.v1",
        parser_profile_id=parser,
        capabilities={"device_overview": "supported"},
        validation_level="validated",
    )


def test_profile_catalog_loads_and_references_safe_command_profiles(tmp_path: Path) -> None:
    service = DeviceCompatibilityService(PathResolver(app_root=ROOT, data_root=tmp_path / "data-root"))
    summary = service.summary()

    assert "Comware V7" in summary["platforms"]
    assert "Comware V9" in summary["platforms"]
    assert "ZXR10 V1" in summary["platforms"]
    assert "ZXR10 V2" in summary["platforms"]
    assert "交换机" in summary["roles"]
    assert "无线控制器" in summary["roles"]
    assert "车载 MR（Cloud AP）" in summary["roles"]
    zte = next(
        item
        for item in summary["profiles"]
        if item["profile_id"]
        == "zte-zxr10-5960x-es-v2-trackside-switch.v1"
    )
    assert zte["validation_level"] == "document_sample_only"
    assert zte["capabilities"]["lldp"] == "sample_required"
    assert zte["capabilities"]["bidirectional_attenuation"] == "not_verified"
    c89e = next(
        item
        for item in summary["profiles"]
        if item["profile_id"] == "zte-zxr10-c89e-v1-core-switch.v1"
    )
    assert c89e["validation_level"] == "validated"
    assert c89e["capabilities"]["interface_status"] == "supported"
    assert c89e["capabilities"]["lldp"] == "supported"


def test_exact_model_release_beats_platform_generic_and_v7_generations_split() -> None:
    resolver = CompatibilityResolver(
        [
            _profile("h3c-v7-generic.v1", parser="v7_generic"),
            _profile("h3c-v7-r66xx.v1", model="S5560X-54F-HI", version="R6628P47", parser="v7_modern"),
            _profile("h3c-v7-r11xx.v1", model="S5560X-54F-HI", version="R11*", parser="v7_legacy"),
            _profile("h3c-v9-generic.v1", major=9, parser="v9_generic"),
        ]
    )

    exact = resolver.resolve(
        DeviceFingerprint("H3C", "switch", "S5560X-54F-HI", "comware", 7, "R6628P47")
    )
    legacy = resolver.resolve(
        DeviceFingerprint("H3C", "switch", "S5560X-54F-HI", "comware", 7, "R1108P01")
    )
    v9 = resolver.resolve(
        DeviceFingerprint("H3C", "switch", "S5560X-54F-HI", "comware", 9, "R9001")
    )
    v5 = resolver.resolve(
        DeviceFingerprint("H3C", "switch", "S5560X-54F-HI", "comware", 5, "R1234")
    )

    assert exact.profile and exact.profile.parser_profile_id == "v7_modern"
    assert legacy.profile and legacy.profile.parser_profile_id == "v7_legacy"
    assert v9.profile and v9.profile.parser_profile_id == "v9_generic"
    assert not v5.matched


def test_roles_do_not_cross_match_cloud_ap_vehicle_mr_and_fit_ap() -> None:
    resolver = CompatibilityResolver(
        [
            _profile("cloud-mr.v1", role="mobile_router_cloud_ap", parser="mr_cloud"),
            _profile("fit-ap.v1", role="fit_ap", parser="fit_ap"),
        ]
    )

    assert resolver.resolve(DeviceFingerprint("H3C", "mobile_router_cloud_ap", "WA", "comware", 7, "R1")).profile.parser_profile_id == "mr_cloud"
    assert resolver.resolve(DeviceFingerprint("H3C", "fit_ap", "WA", "comware", 7, "R1")).profile.parser_profile_id == "fit_ap"


def test_fingerprint_normalizes_role_model_and_release_without_guessing_platform() -> None:
    assert normalize_role("SW") == "switch"
    assert normalize_role("switch") == "switch"
    assert normalize_model(" S5560X-54F-HI ") == "S5560X-54F-HI"
    assert normalize_model("SN123456789012", serial_number="SN123456789012") == "未识别"
    assert extract_release_from_image("flash:/S5560X_HI-CMW710-SYSTEM-R6628P47.bin") == "R6628P47"

    fingerprint = fingerprint_from_record(
        {
            "vendor": "H3C",
            "role": "SW",
            "model": "S5560X-54F-HI",
            "system_image": "S5560X_HI-CMW710-SYSTEM-R6628P47.bin",
        }
    )

    assert fingerprint.role == "switch"
    assert fingerprint.software_version == "R6628P47"
    assert fingerprint.platform_major_version is None


def test_fingerprint_derives_comware_v9_from_short_h3c_version_line() -> None:
    fingerprint = fingerprint_from_record(
        {
            "vendor": "H3C",
            "role": "AC",
            "model": "WX3540X",
            "software_version": "version 9.1.081, Release 1612P01",
        }
    )

    assert fingerprint.platform_family == "comware"
    assert fingerprint.platform_major_version == 9
    assert fingerprint.software_version == "R1612P01"


def test_incremental_scan_reports_only_unregistered_sanitized_candidates() -> None:
    exact = _profile("exact.v1", model="S5560X-54F-HI", version="R6628P47")
    rows = [
        {"vendor": "H3C", "role": "SW", "model": "S5560X-54F-HI", "platform_family": "comware", "platform_major_version": 7, "software_version": "R6628P47", "primary_address": "192.0.2.1", "mac": "00-00-00-00-00-01", "password": "secret"},
        {"vendor": "H3C", "role": "switch", "model": "S5560X-54F-HI", "platform_family": "comware", "platform_major_version": 7, "software_version": "R6628P48"},
        {"vendor": "H3C", "role": "switch", "model": "S5560X-54F-HI", "platform_family": "comware", "platform_major_version": 7, "software_version": "R6628P48"},
        {"vendor": "H3C", "role": "switch", "model": "S5560X-30C-HI", "platform_family": "comware", "platform_major_version": 7, "software_version": "R6628P47"},
    ]

    candidates = scan_candidate_rows(rows, [exact], full=False)
    payload = json.dumps([candidate.to_dict() for candidate in candidates], ensure_ascii=False)

    assert [candidate.local_count for candidate in candidates] == [1, 2]
    assert {candidate.model for candidate in candidates} == {"S5560X-30C-HI", "S5560X-54F-HI"}
    assert "192.0.2.1" not in payload
    assert "00-00-00" not in payload
    assert "secret" not in payload


def test_local_scan_reads_existing_database_without_creating_tasks_or_credentials(tmp_path: Path) -> None:
    paths = PathResolver(app_root=ROOT, data_root=tmp_path / "data-root")
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    device = DeviceRepository(database).create(
        Device(
            name="脱敏设备",
            primary_address="192.0.2.20",
            device_vendor="H3C",
            device_type="SW",
            ssh_password="secret-password",
        )
    )
    DeviceFactRepository(database).upsert_device_fact(
        {
            "device_uuid": device.device_uuid,
            "model": "S5560X-54F-HI",
            "software_version": "R6628P47",
            "vendor": "H3C",
            "collected_at": "2026-07-24T02:00:00",
        }
    )

    candidates = DeviceCompatibilityService(paths).scan_local_candidates()
    tasks_db = paths.site_tasks_db_path("demo")
    payload = json.dumps([candidate.to_dict() for candidate in candidates], ensure_ascii=False)

    assert "S5560X-54F-HI" in payload
    assert "secret-password" not in payload
    assert "192.0.2.20" not in payload
    assert not tasks_db.exists()
    with pytest.raises(sqlite3.OperationalError):
        sqlite3.connect(f"file:{tasks_db.as_posix()}?mode=ro", uri=True)
