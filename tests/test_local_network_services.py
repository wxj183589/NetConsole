import socket
import json
import ssl
import subprocess
import time
from ftplib import FTP, FTP_TLS, error_perm
from io import BytesIO
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from netconsole.backend.api.local_network_services_router import router
from netconsole.services.local_network_services.manager import LocalNetworkServiceManager, ServiceConfig
from netconsole.services.local_network_services.protocols import parse_syslog, parse_syslog_record


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


def test_dns_and_ntp_remain_deferred(manager):
    for kind in ("dns", "ntp"):
        assert manager.snapshot(kind)["status"] == "deferred"
        assert manager.snapshot(kind)["available"] is False
        with pytest.raises(ValueError, match="dependency_missing"):
            manager.action(kind, "start")


def test_https_managed_certificate_and_file_download(manager):
    port = free_port()
    initial = manager.snapshot("https")
    assert initial["status"] == "uninitialized"
    assert initial["config"].tls_enabled is True
    root = Path(manager.configure("https", ServiceConfig(port=port, tls_enabled=True))["root"])
    (root / "fixture.bin").write_bytes(b"TLS file transfer")
    assert manager.action("https", "start")["status"] == "running"
    snapshot = manager.snapshot("https")
    assert snapshot["pid"] is not None
    assert snapshot["process_owner"] == "service"
    assert snapshot["uptime_seconds"] >= 0
    assert snapshot["certificate_fingerprint"]
    context = ssl._create_unverified_context()
    with urlopen(f"https://127.0.0.1:{port}/fixture.bin", context=context, timeout=2) as response:
        assert response.read() == b"TLS file transfer"
    assert manager.action("https", "stop")["status"] == "stopped"


def test_ftps_enforces_tls_and_keeps_read_only_share(manager):
    if not manager._tls_supported("ftp"):
        pytest.skip("pyOpenSSL is not installed in this environment")
    port = free_port()
    root = Path(manager.configure("ftp", ServiceConfig(port=port, tls_enabled=True))["root"])
    (root / "fixture.bin").write_bytes(b"FTPS transfer")
    result = manager.action("ftp", "start")
    assert result["status"] == "running"
    credential = result["session_credential"]
    context = ssl._create_unverified_context()
    with FTP_TLS(context=context) as client:
        client.connect("127.0.0.1", port, timeout=4)
        client.auth()
        client.login(credential["username"], credential["password"])
        client.prot_p()
        transfer = BytesIO()
        client.retrbinary("RETR fixture.bin", transfer.write)
        assert transfer.getvalue() == b"FTPS transfer"
        with pytest.raises(error_perm, match="502"):
            client.sendcmd("PORT 127,0,0,1,30,30")
    assert manager.snapshot("ftp")["certificate_fingerprint"]
    assert manager.action("ftp", "stop")["status"] == "stopped"


def test_supervisor_bounds_automatic_recovery(manager):
    manager.configure("http", ServiceConfig(port=free_port(), auto_restart=True))
    assert manager.action("http", "start")["status"] == "running"
    for attempt in range(4):
        process = manager.runtimes["http"].process
        assert process is not None
        process.terminate()
        process.wait(timeout=3)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            snapshot = manager.snapshot("http")
            if attempt == 3 and snapshot["error_code"] == "auto_restart_limit":
                break
            if attempt < 3 and snapshot["restart_attempts"] == attempt + 1 and snapshot["status"] == "running":
                break
            time.sleep(0.05)
        if attempt < 3:
            assert snapshot["status"] == "running"
            assert manager.runtimes["http"].process.pid != process.pid
    assert snapshot["error_code"] == "auto_restart_limit"
    assert snapshot["restart_attempts"] == 3


def test_syslog_udp_tcp_receivers_and_port_pair_cleanup(manager):
    while True:
        udp_port = free_port(udp=True)
        tcp_port = udp_port
        if tcp_port >= 65535:
            continue
        try:
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", tcp_port))
            break
        except OSError:
            continue
    result = manager.configure("syslog", ServiceConfig(port=udp_port))
    assert [item["transport"] for item in result["listeners"]] == ["UDP", "TCP"]
    assert [item["port"] for item in result["listeners"]] == [udp_port, udp_port]
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
        client.sendto(b"<13>1 2026-11-25T10:02:00Z host-3 daemon 1 ID - password=hunter2", ("127.0.0.1", udp_port))
    with socket.create_connection(("127.0.0.1", tcp_port), timeout=2) as client:
        client.sendall(b"<13>Nov 25 10:01:00 sw-2 daemon: tcp event\n")
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        entries = "\n".join(manager.logs("syslog"))
        if "tcp event" in entries and "udp event" in entries and "<redacted>" in entries:
            break
        time.sleep(0.02)
    assert '"facility":4,"severity":2,"hostname":"sw-1"' in entries
    assert '"format":"rfc5424","timestamp":"2026-11-25T10:00:00Z"' in entries
    assert '"format":"rfc3164","timestamp":"Nov 25 10:01:00"' in entries
    assert '"app_name":"daemon"' in entries
    assert "udp event" in entries and "tcp event" in entries
    assert "password=hunter2" not in entries
    assert '"source":"127.0.0.1"' in entries
    assert parse_syslog(b"legacy host event")[0:3] == (1, 5, "legacy")
    assert parse_syslog_record(b"<13>1 2026-11-25T10:00:00Z host-1 daemon 1 ID - password=hunter2")["message"] == "password=hunter2"
    assert manager.action("syslog", "stop")["status"] == "stopped"
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", tcp_port), timeout=1)


def test_syslog_tcp_supports_rfc6587_octet_counting_and_isolates_clients(manager):
    port = free_port(udp=True)
    manager.configure("syslog", ServiceConfig(port=port, max_connections=2, timeout=1))
    assert manager.action("syslog", "start")["status"] == "running"

    first = b"<14>1 2026-11-25T10:00:00Z host-1 app 1 ID - first line\nsecond line"
    second = b"<13>Nov 25 10:01:00 host-2 app: second frame"
    with socket.create_connection(("127.0.0.1", port), timeout=2) as client:
        client.settimeout(2)
        framed = str(len(first)).encode() + b" " + first
        client.sendall(framed[:4])
        client.sendall(framed[4:] + str(len(second)).encode() + b" " + second)
        client.sendall(b"<14>Nov 25 10:02:00 host-3 app: newline frame\n")

    oversized = socket.create_connection(("127.0.0.1", port), timeout=2)
    oversized.settimeout(2)
    oversized.sendall(b"4097 " + b"x" * 4097)
    assert oversized.recv(1) == b""
    oversized.close()

    with socket.create_connection(("127.0.0.1", port), timeout=2) as client:
        client.sendall(b"<14>Nov 25 10:03:00 host-4 app: other client remains available\n")

    expected = ("first line\\nsecond line", "second frame", "newline frame", "other client remains available")
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        entries = "\n".join(manager.logs("syslog", history=True))
        if all(marker in entries for marker in expected):
            break
        time.sleep(0.02)
    assert all(marker in entries for marker in expected)
    assert "4097 x" not in entries
    assert manager.snapshot("syslog")["status"] == "running"
    assert manager.action("syslog", "stop")["status"] == "stopped"
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", port))
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))


def test_syslog_tcp_keeps_idle_client_connected_for_long_lived_devices(manager):
    port = free_port(udp=True)
    manager.configure("syslog", ServiceConfig(port=port, max_connections=2, timeout=1))
    assert manager.action("syslog", "start")["status"] == "running"
    marker = "long-lived idle connection"
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2) as client:
            client.settimeout(2)
            time.sleep(3.2)
            client.sendall(f"<14>Nov 25 10:04:00 host-5 app: {marker}\n".encode())
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                if marker in "\n".join(manager.logs("syslog", history=True)):
                    break
                time.sleep(0.02)
        assert marker in "\n".join(manager.logs("syslog", history=True))
    finally:
        assert manager.action("syslog", "stop")["status"] == "stopped"


def test_syslog_burst_does_not_block_http_service(manager):
    http_port = free_port()
    while True:
        syslog_port = free_port(udp=True)
        if syslog_port not in {http_port, http_port - 1, http_port + 1}:
            try:
                with socket.socket() as probe:
                    probe.bind(("127.0.0.1", syslog_port))
                break
            except OSError:
                continue
    http_root = Path(manager.configure("http", ServiceConfig(port=http_port))["root"])
    (http_root / "health.txt").write_text("available", encoding="utf-8")
    manager.configure("syslog", ServiceConfig(port=syslog_port))
    assert manager.action("http", "start")["status"] == "running"
    assert manager.action("syslog", "start")["status"] == "running"

    def send_burst():
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            for index in range(300):
                payload = f"<14>1 2026-11-25T10:00:00Z switch daemon 1 ID - burst-{index}".encode()
                sender.sendto(payload, ("127.0.0.1", syslog_port))

    sender = Thread(target=send_burst)
    sender.start()
    started = time.monotonic()
    with urlopen(f"http://127.0.0.1:{http_port}/health.txt", timeout=2) as response:
        assert response.read() == b"available"
    assert time.monotonic() - started < 2
    sender.join(timeout=3)
    assert not sender.is_alive()
    assert manager.snapshot("http")["status"] == "running"
    assert manager.snapshot("syslog")["status"] == "running"


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
        udp = subprocess.run([str(binary), "-c", "127.0.0.1", "-p", str(port), "-u", "-b", "1M", "-t", "1", "-J"], capture_output=True, timeout=8)
        assert udp.returncode == 0, udp.stderr
        result = json.loads(udp.stdout)
        assert "error" not in result
        received = result["end"]["sum_received"]
        assert received["bits_per_second"] > 0
        assert received["jitter_ms"] >= 0
        assert 0 <= received["lost_percent"] <= 100
        process = test_manager.runtimes["iperf"].process
        assert process is not None
        process.terminate()
        process.wait(timeout=4)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and test_manager.snapshot("iperf")["error_code"] != "service_exited":
            time.sleep(0.02)
        exited = test_manager.snapshot("iperf")
        assert exited["error_code"] == "service_exited"
        assert exited["health"] == "unhealthy"
        assert test_manager.action("iperf", "restart")["status"] == "running"
    finally:
        test_manager.close()


def test_certificate_rotates_for_address_and_mismatched_key(manager):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    manager.configure("https", ServiceConfig(port=free_port(), tls_enabled=True))
    certificate, key = manager._ensure_certificate("https", "127.0.0.1")
    initial = certificate.read_bytes()
    manager._ensure_certificate("https", "127.0.0.1")
    assert certificate.read_bytes() == initial
    manager._ensure_certificate("https", "127.0.0.2")
    assert certificate.read_bytes() != initial
    changed_address = certificate.read_bytes()
    wrong_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key.write_bytes(wrong_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    manager._ensure_certificate("https", "127.0.0.2")
    assert certificate.read_bytes() != changed_address


def test_slow_tls_client_does_not_block_another_download(manager):
    port = free_port()
    root = Path(manager.configure("https", ServiceConfig(port=port, tls_enabled=True))["root"])
    (root / "health.txt").write_bytes(b"healthy")
    assert manager.action("https", "start")["status"] == "running"
    with socket.create_connection(("127.0.0.1", port), timeout=2):
        with urlopen(f"https://127.0.0.1:{port}/health.txt", context=ssl._create_unverified_context(), timeout=2) as response:
            assert response.read() == b"healthy"


def test_service_process_isolation_and_close_reaps_children(manager):
    for kind in ("http", "tftp"):
        manager.configure(kind, ServiceConfig(port=free_port(udp=kind == "tftp")))
        assert manager.action(kind, "start")["status"] == "running"
    http = manager.runtimes["http"].process
    tftp = manager.runtimes["tftp"].process
    assert http.pid != tftp.pid
    http.terminate()
    http.wait(timeout=3)
    assert manager.snapshot("tftp")["status"] == "running"
    manager.close()
    assert http.poll() is not None
    assert tftp.poll() is not None


def test_ftp_explicit_upload_user_and_existing_file_protection(manager):
    port = free_port()
    root = Path(manager.configure("ftp", ServiceConfig(port=port, allow_upload=True, ftp_username="operator"))["root"])
    result = manager.action("ftp", "start")
    credential = result["session_credential"]
    assert credential["username"] == "operator"
    with FTP() as client:
        client.connect("127.0.0.1", port, timeout=3)
        client.login(credential["username"], credential["password"])
        client.storbinary("STOR upload.bin", BytesIO(b"new payload"))
        assert (root / "upload.bin").read_bytes() == b"new payload"
        with pytest.raises(error_perm):
            client.storbinary("STOR upload.bin", BytesIO(b"overwrite"))
        assert (root / "upload.bin").read_bytes() == b"new payload"
    assert credential["password"] not in "\n".join(manager.logs("ftp"))
