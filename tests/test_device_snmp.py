from __future__ import annotations

import pytest

from netconsole.models.device import Device
from netconsole.models.device_snmp import DeviceSnmpProfile
from netconsole.services import device_snmp_client as device_snmp_module
from netconsole.services.device_snmp_client import (
    SYS_OIDS,
    DeviceSnmpClient,
    _DeviceSnmpWireClient,
    _WireResponse,
    _WireVarBind,
)


def test_device_snmp_profile_supports_only_v1_and_v2c() -> None:
    assert DeviceSnmpProfile(host="192.0.2.1", version="v1").version == "v1"
    assert DeviceSnmpProfile(host="192.0.2.1", version="v2").version == "v2c"
    assert DeviceSnmpProfile(host="192.0.2.1", version="v2c").version == "v2c"

    with pytest.raises(ValueError, match="仅支持 SNMP v1 和 v2c"):
        DeviceSnmpProfile(host="192.0.2.1", version="v3")

    with pytest.raises(ValueError, match="地址不能为空"):
        DeviceSnmpProfile(host="", version="v2c")


def test_device_snmp_profile_prefers_v2c_and_rejects_disabled_device() -> None:
    device = Device(
        primary_address="192.0.2.2",
        snmp_v1_enabled=1,
        snmp_v2c_enabled=1,
        snmp_ro_community="readonly",
    )
    profile = DeviceSnmpProfile.from_device(device)

    assert profile.version == "v2c"
    assert profile.community_ro == "readonly"

    disabled = Device(
        primary_address="192.0.2.3",
        snmp_v1_enabled=0,
        snmp_v2c_enabled=0,
    )
    with pytest.raises(ValueError, match="未启用 SNMP v1 或 v2c"):
        DeviceSnmpProfile.from_device(disabled)

    disabled.snmp_enabled = 0
    with pytest.raises(ValueError, match="未启用 SNMP"):
        DeviceSnmpProfile.from_device(disabled)


def test_device_snmp_wire_versions_are_v1_and_v2c_only() -> None:
    v1 = _DeviceSnmpWireClient(DeviceSnmpProfile(host="192.0.2.1", version="v1"))
    v2c = _DeviceSnmpWireClient(DeviceSnmpProfile(host="192.0.2.1", version="v2c"))

    assert v1.version_number == 0
    assert v2c.version_number == 1


def test_device_snmp_client_uses_only_fixed_identification_oids(monkeypatch) -> None:
    calls: list[tuple[str, int]] = []
    values = {
        SYS_OIDS["sysName.0"]: "core-01",
        SYS_OIDS["sysObjectID.0"]: "1.3.6.1.4.1.25506",
        SYS_OIDS["sysDescr.0"]: "H3C Comware Software",
        SYS_OIDS["sysUpTime.0"]: "12345",
    }

    class FakeWireClient:
        def __init__(self, profile: DeviceSnmpProfile) -> None:
            self.profile = profile

        def request(self, oids: list[str], *, pdu_type: int) -> _WireResponse:
            oid = oids[0]
            calls.append((oid, pdu_type))
            if pdu_type == 0xA1:
                return _WireResponse("end_of_mib_view", "已到达视图末尾。", [])
            return _WireResponse(
                "success",
                "",
                [_WireVarBind(oid, values[oid], "OCTET STRING")],
            )

    monkeypatch.setattr(device_snmp_module, "_DeviceSnmpWireClient", FakeWireClient)
    result = DeviceSnmpClient().test_device(
        DeviceSnmpProfile(host="192.0.2.1", community_ro="readonly")
    )

    assert result["status"] == "success"
    assert result["sysName"] == "core-01"
    assert result["interface_count"] == 0
    assert {oid for oid, _pdu_type in calls}.issubset(set(SYS_OIDS.values()))
    assert calls[-1] == (SYS_OIDS["ifDescr"], 0xA1)
    assert not hasattr(DeviceSnmpClient(), "get")
    assert not hasattr(DeviceSnmpClient(), "walk")


def test_device_snmp_client_cancel_and_error_do_not_leak_community(monkeypatch) -> None:
    profile = DeviceSnmpProfile(
        host="192.0.2.1",
        community_ro="private-community",
    )
    cancelled = DeviceSnmpClient().test_device(profile, cancel_checker=lambda: True)
    assert cancelled["status"] == "cancelled"

    class LeakyWireClient:
        def __init__(self, _profile: DeviceSnmpProfile) -> None:
            pass

        def request(self, _oids: list[str], *, pdu_type: int) -> _WireResponse:
            raise RuntimeError(f"wire failed for {profile.community_ro} at {pdu_type}")

    monkeypatch.setattr(device_snmp_module, "_DeviceSnmpWireClient", LeakyWireClient)
    failed = DeviceSnmpClient().test_device(profile)

    assert failed["status"] == "failed"
    assert profile.community_ro not in failed["error_message"]


def test_device_snmp_fixed_walk_stops_on_outside_or_repeated_oid(monkeypatch) -> None:
    profile = DeviceSnmpProfile(host="192.0.2.1", community_ro="readonly")
    root = SYS_OIDS["ifDescr"]

    class OutsideWireClient:
        def __init__(self, _profile: DeviceSnmpProfile) -> None:
            pass

        def request(self, _oids: list[str], *, pdu_type: int) -> _WireResponse:
            assert pdu_type == 0xA1
            return _WireResponse(
                "success",
                "",
                [_WireVarBind("1.3.6.1.2.1.3.1", "outside", "OCTET STRING")],
            )

    monkeypatch.setattr(device_snmp_module, "_DeviceSnmpWireClient", OutsideWireClient)
    outside = DeviceSnmpClient()._walk(profile, root, max_rows=5)
    assert outside.status == "empty_table"
    assert outside.rows == []

    class RepeatedWireClient:
        def __init__(self, _profile: DeviceSnmpProfile) -> None:
            pass

        def request(self, oids: list[str], *, pdu_type: int) -> _WireResponse:
            assert pdu_type == 0xA1
            return _WireResponse(
                "success",
                "",
                [_WireVarBind(oids[0], "repeat", "OCTET STRING")],
            )

    monkeypatch.setattr(device_snmp_module, "_DeviceSnmpWireClient", RepeatedWireClient)
    repeated = DeviceSnmpClient()._walk(profile, root, max_rows=5)
    assert repeated.status == "failed"
    assert repeated.rows == []
    assert "非递增 OID" in repeated.error_message


def test_device_snmp_wire_decodes_response_and_retries_timeout(monkeypatch) -> None:
    oid = SYS_OIDS["sysName.0"]
    varbind = device_snmp_module._seq(
        device_snmp_module._oid(oid) + device_snmp_module._octet("core-01")
    )
    pdu_body = (
        device_snmp_module._int(7)
        + device_snmp_module._int(0)
        + device_snmp_module._int(0)
        + device_snmp_module._seq(varbind)
    )
    pdu = bytes([0xA2]) + device_snmp_module._len(len(pdu_body)) + pdu_body
    packet = device_snmp_module._seq(
        device_snmp_module._int(1)
        + device_snmp_module._octet("readonly")
        + pdu
    )
    attempts = 0

    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def settimeout(self, _timeout: float) -> None:
            pass

        def sendto(self, _packet: bytes, _target: tuple[str, int]) -> None:
            pass

        def recvfrom(self, _size: int):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise device_snmp_module.socket.timeout()
            return packet, ("192.0.2.1", 161)

    monkeypatch.setattr(device_snmp_module.socket, "socket", lambda *_args, **_kwargs: FakeSocket())
    response = _DeviceSnmpWireClient(
        DeviceSnmpProfile(
            host="192.0.2.1",
            community_ro="readonly",
            retries=1,
        )
    ).request([oid], pdu_type=0xA0)

    assert attempts == 2
    assert response.status == "success"
    assert response.varbinds[0].oid == oid
    assert response.varbinds[0].value == "core-01"
