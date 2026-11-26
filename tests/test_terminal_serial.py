from __future__ import annotations

import json

import pytest
import serial

from netconsole.core.paths import PathResolver
from netconsole.services.terminal_serial import (
    SerialConfigurationError,
    SerialConnectionOptions,
    SerialPortService,
    SerialProfileStore,
)
from netconsole.services.terminal_transports import SerialInteractiveTransport


def test_serial_options_validate_supported_line_settings():
    options = SerialConnectionOptions.from_mapping({"port": "COM14"})
    assert options == SerialConnectionOptions(port="COM14")
    assert options.baud_rate == 9600
    assert options.data_bits == 8
    assert options.parity == "N"
    assert options.stop_bits == 1
    assert options.flow_control == "none"
    assert options.dtr == options.rts == "KEEP"

    assert SerialConnectionOptions.from_mapping({
        "port": "COM14", "baud_rate": 115200, "data_bits": 5, "stop_bits": 1.5,
        "parity": "M", "flow_control": "xonxoff",
    }).stop_bits == 1.5

    with pytest.raises(SerialConfigurationError, match="1.5 停止位"):
        SerialConnectionOptions.from_mapping({"port": "COM14", "data_bits": 8, "stop_bits": 1.5})
    with pytest.raises(SerialConfigurationError, match="未知字段"):
        SerialConnectionOptions.from_mapping({"port": "COM14", "shell": True})
    with pytest.raises(SerialConfigurationError, match="端口"):
        SerialConnectionOptions.from_mapping({"port": "loop://"})


def test_serial_profile_defaults_do_not_create_or_replace_user_configuration(tmp_path):
    paths = PathResolver(app_root=tmp_path / "app", data_root=tmp_path / "data", runtime_root=tmp_path / "runtime")
    store = SerialProfileStore(paths)
    defaults = store.document()
    assert [item["name"] for item in defaults["profiles"]] == ["H3C Console", "H3C 高速 Console"]
    assert defaults["profiles"][0]["options"]["baud_rate"] == 9600
    assert defaults["profiles"][1]["options"]["baud_rate"] == 115200
    assert not store.path.exists()

    custom = {
        "profile_id": "90bf21a2-30e5-4a70-8d2a-40369a29a7fe",
        "name": "现场 38400",
        "options": {"port": "", "baud_rate": 38400},
    }
    saved = store.save_custom_profiles([custom])
    original = store.path.read_bytes()
    assert len(saved["profiles"]) == 3
    assert store.document() == saved
    assert store.path.read_bytes() == original

    with pytest.raises(SerialConfigurationError):
        store.save_custom_profiles([custom, custom])
    assert store.path.read_bytes() == original
    assert json.loads(original)["schema_version"] == 1


def test_serial_port_enumeration_returns_safe_device_metadata(monkeypatch):
    from serial.tools import list_ports

    monkeypatch.setattr(list_ports, "comports", lambda: [
        type("Port", (), {"device": "COM8", "name": "COM8", "description": "USB 串口", "manufacturer": "示例厂商", "hwid": "USB VID:PID"})(),
        type("Port", (), {"device": "COM2", "name": "COM2", "description": "", "manufacturer": None, "hwid": "n/a"})(),
    ])
    ports = SerialPortService().enumerate_ports()
    assert [item["port"] for item in ports] == ["COM2", "COM8"]
    assert ports[1]["manufacturer"] == "示例厂商"
    assert set(ports[0]) == {"port", "name", "description", "manufacturer", "hardware_id"}


def test_pyserial_loopback_transport_handles_utf8_line_endings_raw_bytes_and_close():
    options = SerialConnectionOptions(port="loop://", line_ending="CRLF")

    def loop_factory(**kwargs):
        kwargs.pop("port")
        return serial.serial_for_url("loop://", do_not_open=True, **kwargs)

    transport = SerialInteractiveTransport(options, serial_factory=loop_factory)
    transport.connect(120, 32)
    try:
        transport.write("设备状态\r\n")
        received = ""
        for _ in range(20):
            received += transport.read()
            if received:
                break
        assert received == "设备状态\r\n"
        assert transport.last_read_bytes == "设备状态\r\n".encode()

        transport.write_bytes(b"\x00\xff\r")
        for _ in range(20):
            transport.read()
            if transport.last_read_bytes:
                break
        assert transport.last_read_bytes == b"\x00\xff\r"

        transport.flush("both")
    finally:
        port = transport._serial
        transport.close()
    assert port is not None and not port.is_open
