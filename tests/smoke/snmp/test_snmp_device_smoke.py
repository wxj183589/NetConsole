from __future__ import annotations

import os
from pathlib import Path

import pytest

from netconsole.models.snmp_models import SnmpProfile
from netconsole.services.snmp_client import SnmpClient


def test_configured_snmp_devices_get_walk_and_getbulk() -> None:
    config_path = str(os.environ.get("NETCONSOLE_SNMP_SMOKE_CONFIG") or "").strip()
    if not config_path:
        pytest.skip("未设置 NETCONSOLE_SNMP_SMOKE_CONFIG")
    yaml = pytest.importorskip("yaml")
    payload = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
    devices = list(payload.get("devices") or [])
    if not devices:
        pytest.fail("SNMP smoke 配置没有 devices")

    for device in devices:
        name = str(device.get("name") or device.get("ip") or "未命名设备")
        host = str(device.get("ip") or "").strip()
        if not host:
            pytest.fail(f"{name} 未配置 ip")
        community_env = str(device.get("community_env") or "").strip()
        community = str(os.environ.get(community_env) or "") if community_env else ""
        profile = SnmpProfile(
            host=host,
            version=str(device.get("version") or "v2c"),
            port=int(device.get("port") or 161),
            community_ro=community,
            timeout_ms=int(device.get("timeout_ms") or 2000),
            retries=int(device.get("retries") or 1),
        )
        if profile.version.lower() in {"v1", "v2", "v2c"} and not community:
            pytest.fail(f"{name} 未通过环境变量提供只读团体字")
        client = SnmpClient()
        get_result = client.get(profile, str(device.get("get_oid") or "1.3.6.1.2.1.1.5.0"))
        walk_result = client.walk(
            profile,
            str(device.get("walk_oid") or "1.3.6.1.2.1.1"),
            max_rows=int(device.get("max_rows") or 50),
        )
        bulk_result = client.get_bulk(
            profile,
            str(device.get("getbulk_oid") or "1.3.6.1.2.1.1"),
            max_repetitions=int(device.get("max_repetitions") or 10),
        )
        assert get_result.status == "success", f"{name} GET 失败：{get_result.error_message}"
        assert walk_result.status == "success", f"{name} WALK 失败：{walk_result.error_message}"
        assert bulk_result.status == "success", f"{name} GETBULK 失败：{bulk_result.error_message}"
