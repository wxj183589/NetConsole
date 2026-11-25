import io
import os
import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from ftplib import FTP, error_temp
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.request import urlopen

import pytest

from netconsole.services.local_network_services import worker
from netconsole.services.local_network_services.manager import LocalNetworkServiceManager, ServiceConfig, ServiceRuntime
from netconsole.services.local_network_services.protocols import create_syslog_server


def free_port(udp=False):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM if udp else socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def free_syslog_port(*excluded_ports):
    for _ in range(50):
        port = free_port(udp=True)
        if port == 65535 or {port, port + 1}.intersection(excluded_ports):
            continue
        try:
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", port + 1))
            return port
        except OSError:
            continue
    pytest.fail("No free syslog UDP/TCP pair")


@pytest.fixture
def manager(tmp_path):
    service_manager = LocalNetworkServiceManager(tmp_path / "runtime" / "local_network_services", adapters=lambda: {})
    try:
        yield service_manager
    finally:
        service_manager.close()


def test_release_reaps_process_and_job_after_broken_control_pipe():
    control = Mock()
    control.write.side_effect = BrokenPipeError("worker exited")
    control.close.side_effect = BrokenPipeError("buffered flush after exit")
    process = SimpleNamespace(stdin=control, poll=lambda: None, wait=Mock(), kill=Mock())
    guard = Mock()
    runtime = ServiceRuntime(process=process, job_handle=guard)

    LocalNetworkServiceManager._release(runtime)

    process.wait.assert_called_once()
    guard.close.assert_called_once()
    assert runtime.process is None
    assert runtime.job_handle is None


def test_release_closes_job_when_exited_process_control_close_fails():
    control = Mock()
    control.close.side_effect = BrokenPipeError("buffered flush after exit")
    runtime = ServiceRuntime(process=SimpleNamespace(stdin=control, poll=lambda: 1), job_handle=Mock())
    guard = runtime.job_handle

    LocalNetworkServiceManager._release(runtime)

    guard.close.assert_called_once()
    assert runtime.process is None


def test_release_closes_job_even_when_killed_process_wait_times_out():
    process = SimpleNamespace(stdin=None, poll=lambda: None, terminate=Mock(), kill=Mock())
    process.wait = Mock(side_effect=subprocess.TimeoutExpired("worker", 2))
    guard = Mock()
    runtime = ServiceRuntime(process=process, job_handle=guard)
    with pytest.raises(subprocess.TimeoutExpired):
        LocalNetworkServiceManager._release(runtime)
    process.kill.assert_called_once()
    guard.close.assert_called_once()
    assert runtime.process is process


def test_service_close_joins_its_output_workers(manager):
    manager.configure("http", ServiceConfig(port=free_port()))
    assert manager.action("http", "start")["status"] == "running"
    process = manager.runtimes["http"].process
    readers = list(manager.runtimes["http"].output_workers)
    assert len(readers) == 2
    manager.close()
    assert process.poll() is not None
    assert all(not thread.is_alive() for thread in readers)


def test_worker_error_diagnostic_tolerates_closed_output_pipe(monkeypatch):
    output = Mock()
    output.write.side_effect = BrokenPipeError("supervisor closed output")
    monkeypatch.setattr(worker.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(b"{}\n")))
    monkeypatch.setattr(worker.sys, "stdout", output)
    assert worker.main() == 1


def test_ftp_passive_range_is_used_and_exhaustion_keeps_control_alive(manager):
    port = free_port()
    with socket.socket() as occupied:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            occupied.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        data_port = occupied.getsockname()[1]
        manager.configure("ftp", ServiceConfig(port=port, passive_ports=(data_port, data_port)))
        credential = manager.action("ftp", "start")["session_credential"]
        with FTP() as client:
            client.connect("127.0.0.1", port, timeout=3)
            client.login(credential["username"], credential["password"])
            with pytest.raises(error_temp, match="425"):
                client.makepasv()
            assert client.voidcmd("NOOP").startswith("200")
        assert manager.snapshot("ftp")["status"] == "running"
    with FTP() as client:
        client.connect("127.0.0.1", port, timeout=3)
        client.login(credential["username"], credential["password"])
        _host, actual_port = client.makepasv()
        assert actual_port == data_port


def test_syslog_queue_is_bounded_under_concurrent_input_and_drains_at_stop():
    port = free_syslog_port()
    stopping = Event()
    log = Mock()
    service = create_syslog_server(ServiceConfig(port=port), log, stopping)
    enqueue = service.servers[0].log_syslog
    payload = b"<14>1 2026-11-25T10:00:00Z switch app 1 ID - load test"

    def produce(_index):
        for _ in range(1000):
            enqueue(payload, "127.0.0.1")

    receiver = Thread(target=service.serve_forever)
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(produce, range(8)))
        # Queueing performs no disk or logger IO, including when the queue is full.
        log.info.assert_not_called()
        receiver.start()
        service.shutdown()
        receiver.join(timeout=5)
        assert not receiver.is_alive()
        assert all(not thread.is_alive() for thread in service.workers)
        assert log.info.call_count == 4097
        log.info.assert_called_with("Syslog receiver stopped received=%d dropped=%d", 8000, 3904)
    finally:
        if receiver.is_alive():
            service.shutdown()
            receiver.join(timeout=5)
        service.server_close()


def test_concurrent_syslog_socket_burst_keeps_http_available(manager):
    http_port = free_port()
    port = free_syslog_port(http_port)
    root = manager.configure("http", ServiceConfig(port=http_port))["root"]
    Path(root, "health.txt").write_bytes(b"available")
    manager.configure("syslog", ServiceConfig(port=port))
    assert manager.action("http", "start")["status"] == "running"
    assert manager.action("syslog", "start")["status"] == "running"

    def flood(_index):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            for index in range(1500):
                sender.sendto(f"<14>Nov 25 10:00:00 switch app: burst-{index}".encode(), ("127.0.0.1", port))

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(flood, index) for index in range(4)]
        for _ in range(10):
            with urlopen(f"http://127.0.0.1:{http_port}/health.txt", timeout=2) as response:
                assert response.read() == b"available"
        for future in futures:
            future.result(timeout=5)
    assert time.monotonic() - started < 10
    assert manager.snapshot("http")["status"] == "running"
    assert manager.snapshot("syslog")["status"] == "running"


def test_worker_warning_survives_supervisor_warning_level(manager):
    port = free_syslog_port()
    manager.configure("syslog", ServiceConfig(port=port, log_level="WARNING"))
    assert manager.action("syslog", "start")["status"] == "running"
    with socket.create_connection(("127.0.0.1", port + 1), timeout=2) as client:
        client.sendall(b"x" * 4097 + b"\n")
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        lines = manager.logs("syslog")
        if any("WARNING Syslog message exceeded size limit" in line for line in lines):
            break
        time.sleep(0.02)
    assert any("WARNING Syslog message exceeded size limit" in line for line in lines)


@pytest.mark.skipif(os.name != "nt", reason="Windows process metrics")
def test_worker_metrics_measure_actual_worker_and_release_handle(manager):
    manager.configure("http", ServiceConfig(port=free_port()))
    assert manager.action("http", "start")["status"] == "running"
    runtime = manager.runtimes["http"]
    assert runtime.worker_pid is not None
    assert manager.snapshot("http")["pid"] == runtime.worker_pid
    assert runtime.metrics_handle is not None
    cpu, memory = manager._process_metrics(runtime)
    assert memory > 10_000_000
    assert cpu is None or cpu >= 0
    assert manager.action("http", "stop")["status"] == "stopped"
    assert runtime.metrics_handle is None
    assert runtime.worker_pid is None


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object identity")
def test_worker_metrics_reject_unowned_process(manager):
    manager.configure("http", ServiceConfig(port=free_port()))
    assert manager.action("http", "start")["status"] == "running"
    runtime = manager.runtimes["http"]
    original_handle = runtime.metrics_handle
    original_pid = runtime.worker_pid
    with pytest.raises(RuntimeError, match="outside owned Job"):
        manager._bind_worker_metrics(runtime, os.getpid())
    assert runtime.metrics_handle == original_handle
    assert runtime.worker_pid == original_pid
