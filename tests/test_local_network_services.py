import socket
import struct
import subprocess
import time
from ftplib import FTP, error_perm
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from netconsole.backend.api.local_network_services_router import router
from netconsole.services.local_network_services.manager import LocalNetworkServiceManager, ServiceConfig
from netconsole.services.local_network_services.protocols import parse_syslog


def free_port(udp=False):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM if udp else socket.SOCK_STREAM) as transport:
        transport.bind(("127.0.0.1", 0))
        return transport.getsockname()[1]


@pytest.fixture
def manager(tmp_path):
    service_manager = LocalNetworkServiceManager(tmp_path / "runtime" / "local_network_services", adapters=lambda: {})
    try:
        yield service_manager
    finally:
        service_manager.close()


def test_http_api_lifecycle_file_boundary_and_port_conflict(manager):
    app = FastAPI()
    app.state.local_network_services = manager
    app.include_router(router)
    with TestClient(app) as client, socket.socket() as occupied:
        api = "/local-network-services"
        snapshots = {row["id"]: row for row in client.get(api).json()["services"]}
        assert snapshots["http"]["status"] == "uninitialized"
        assert snapshots["nfs"]["status"] == "dependency_missing"
        assert client.post(f"{api}/nfs/actions/start").status_code == 409
        assert client.post(f"{api}/http/actions/start").status_code == 409
        assert client.post(f"{api}/http/actions/initialize").json()["status"] == "stopped"
        assert client.put(f"{api}/http/config", json={"address": "0.0.0.0", "port": 8888}).status_code == 409
        assert client.put(f"{api}/http/config", json={"address": "10.0.0.1", "port": 8888}).status_code == 409
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        response = client.put(f"{api}/http/config", json={"port": occupied.getsockname()[1]})
        root = Path(response.json()["root"])
        (root / "config.cfg").write_bytes(b"isolated fixture")
        (root.parent / "private.cfg").write_bytes(b"private")
        assert client.post(f"{api}/http/actions/start").json()["status"] == "port_conflict"
        port = free_port()
        assert client.put(f"{api}/http/config", json={"port": port}).json()["status"] == "stopped"
        assert client.post(f"{api}/http/actions/start").json()["status"] == "running"
        with urlopen(f"http://127.0.0.1:{port}/config.cfg", timeout=2) as response:
            assert response.read() == b"isolated fixture"
        with pytest.raises(HTTPError) as denied:
            urlopen(f"http://127.0.0.1:{port}/%2e%2e/private.cfg", timeout=2)
        assert denied.value.code == 404
        assert client.post(f"{api}/http/actions/restart").json()["status"] == "running"
        assert client.put(f"{api}/http/config", json={"port": port}).status_code == 409
        assert client.post(f"{api}/http/actions/stop").json()["status"] == "stopped"
        assert any("Port" in line or "Start failed" in line for line in client.get(f"{api}/http/logs").json()["lines"])
        with pytest.raises(OSError):
            socket.create_connection(("127.0.0.1", port), timeout=1)


def test_tftp_upload_download_and_no_overwrite(manager):
    port = free_port(udp=True)
    config = ServiceConfig(port=port, allow_upload=True, timeout=1)
    path = manager.configure("tftp", config)["root"]
    assert manager.action("tftp", "start")["status"] == "running"
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        client.settimeout(2)
        endpoint = ("127.0.0.1", port)
        client.sendto(b"\0\2test.cfg\0octet\0", endpoint)
        ack, transfer = client.recvfrom(520)
        assert ack == b"\0\4\0\0"
        client.sendto(b"\0\3\0\x01payload", transfer)
        assert client.recv(520) == b"\0\4\0\x01"
        assert (Path(path) / "test.cfg").read_bytes() == b"payload"
        client.sendto(b"\0\x01test.cfg\0octet\0", endpoint)
        data, transfer = client.recvfrom(520)
        assert data == b"\0\3\0\x01payload"
        client.sendto(b"\0\4\0\x01", transfer)
        client.sendto(b"\0\2test.cfg\0octet\0", endpoint)
        assert client.recv(520).startswith(b"\0\5\0\6")
        client.sendto(b"\0\x01../config.json\0octet\0", endpoint)
        assert client.recv(520).startswith(b"\0\5\0\2")
    assert manager.action("tftp", "stop")["status"] == "stopped"


def test_dns_ntp_loopback_and_independent_shutdown(manager):
    dns_port, ntp_port = free_port(udp=True), free_port(udp=True)
    while dns_port == ntp_port:
        ntp_port = free_port(udp=True)
    manager.configure("dns", ServiceConfig(port=dns_port, dns_records={"Device.test.": "192.0.2.42"}))
    manager.configure("ntp", ServiceConfig(port=ntp_port))
    assert manager.action("dns", "start")["status"] == "running"
    assert manager.action("ntp", "start")["status"] == "running"
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        client.settimeout(2)
        question = b"\x06device\x04test\0\0\x01\0\x01"
        query = struct.pack("!6H", 10, 0x100, 1, 0, 0, 0) + question
        client.sendto(query, ("127.0.0.1", dns_port))
        response = client.recv(512)
        assert response[:2] == query[:2]
        assert response[-4:] == socket.inet_aton("192.0.2.42")
        assert manager.action("dns", "stop")["status"] == "stopped"
        assert manager.snapshot("ntp")["status"] == "running"
        request = b"\x23" + bytes(39) + b"testtime"
        client.sendto(request, ("127.0.0.1", ntp_port))
        response = client.recv(512)
        assert response[0] & 7 == 4
        assert response[24:32] == request[40:48]
        assert len(response) == 48 and response[40:] != bytes(8)


def test_syslog_udp_tcp_receivers_and_port_pair_cleanup(manager):
    udp_port = free_port(udp=True)
    tcp_port = udp_port + 1
    while tcp_port >= 65535:
        udp_port = free_port(udp=True)
        tcp_port = udp_port + 1
    result = manager.configure("syslog", ServiceConfig(port=udp_port))
    assert [item["transport"] for item in result["listeners"]] == ["UDP", "TCP"]
    occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    occupied.bind(("127.0.0.1", tcp_port))
    occupied.listen()
    assert manager.action("syslog", "start")["status"] == "port_conflict"
    occupied.close()
    assert manager.action("syslog", "start")["status"] == "running"
    assert manager.snapshot("syslog")["listeners"][1]["port"] == tcp_port

    udp_message = b"<34>1 2026-11-25T10:00:00Z sw-1 daemon 1234 ID47 - udp event"
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        client.sendto(udp_message, ("127.0.0.1", udp_port))
    with socket.create_connection(("127.0.0.1", tcp_port), timeout=2) as client:
        client.sendall(b"<13>Nov 25 10:01:00 sw-2 daemon: tcp event\n")
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        entries = "\n".join(manager.logs("syslog"))
        if "tcp event" in entries and "udp event" in entries:
            break
        time.sleep(0.02)
    assert "facility=4 severity=2 hostname=sw-1" in entries
    assert "udp event" in entries and "tcp event" in entries
    assert "source=127.0.0.1" in entries
    assert parse_syslog(b"legacy host event")[0:3] == (1, 5, "legacy")
    assert manager.action("syslog", "stop")["status"] == "stopped"
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", tcp_port), timeout=1)




def test_ftp_download_credential_and_restart(manager):
    port = free_port()
    root = Path(manager.configure("ftp", ServiceConfig(port=port))["root"])
    (root / "fixture.bin").write_bytes(b"FTP transfer")
    result = manager.action("ftp", "start")
    assert result["status"] == "running"
    credential = result["session_credential"]
    assert "session_credential" not in manager.snapshot("ftp")
    with FTP() as client:
        client.connect("127.0.0.1", port, timeout=4)
        client.login(credential["username"], credential["password"])
        transfer = BytesIO()
        client.retrbinary("RETR fixture.bin", transfer.write)
        assert transfer.getvalue() == b"FTP transfer"
        with pytest.raises(error_perm, match="502"):
            client.sendcmd("PORT 127,0,0,1,30,30")
        with pytest.raises(error_perm, match="550"):
            client.storbinary("STOR blocked.bin", BytesIO(b"not allowed"))
    restarted = manager.action("ftp", "restart")
    assert restarted["session_credential"]["password"] != credential["password"]
    assert credential["password"] not in "\n".join(manager.logs("ftp"))


def test_iperf_external_process_exit_and_recovery(tmp_path):
    binary = Path(__file__).resolve().parents[1] / "resources" / "tools" / "windows-x64" / "iperf3" / "iperf3.exe"
    if not binary.is_file():
        pytest.skip("managed iPerf3 binary unavailable")
    test_manager = LocalNetworkServiceManager(tmp_path / "runtime" / "local_network_services", iperf_path=binary, adapters=lambda: {})
    port = free_port()
    try:
        test_manager.configure("iperf", ServiceConfig(port=port))
        assert test_manager.action("iperf", "start")["status"] == "running"
        time.sleep(0.2)  # Allow the server to finish the health-probe connection.
        client = subprocess.run([str(binary), "-c", "127.0.0.1", "-p", str(port), "-t", "1"], capture_output=True, timeout=6)
        assert client.returncode == 0, client.stderr
        process = test_manager.runtimes["iperf"].process
        assert process is not None
        process.terminate()
        process.wait(timeout=4)
        assert test_manager.snapshot("iperf")["error_code"] == "service_exited"
        assert test_manager.action("iperf", "restart")["status"] == "running"
    finally:
        test_manager.close()
