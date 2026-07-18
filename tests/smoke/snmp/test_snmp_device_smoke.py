from __future__ import annotations

import os
from pathlib import Path

import pytest

from netconsole.models.device_snmp import DeviceSnmpProfile
from netconsole.services.device_snmp_client import DeviceSnmpClient


def test_configured_device_snmp_v1_v2c_basic_identification() -> None:
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
        profile = DeviceSnmpProfile(
            host=host,
            version=str(device.get("version") or "v2c"),
            port=int(device.get("port") or 161),
            community_ro=community,
            timeout_ms=int(device.get("timeout_ms") or 2000),
            retries=int(device.get("retries") or 1),
        )
        if not community:
            pytest.fail(f"{name} 未通过环境变量提供只读团体字")
        client = DeviceSnmpClient()
        result = client.test_device(profile)
        assert result["status"] == "success", f"{name} 基础识别失败：{result['error_message']}"
        assert str(result.get("sysName") or "").strip(), f"{name} 未返回 sysName"
