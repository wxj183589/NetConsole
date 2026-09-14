from __future__ import annotations

import errno
import io
import select
import socket
import threading
from hashlib import sha256
from pathlib import Path
from time import monotonic, sleep

import paramiko
import pytest

from netconsole.core import app_logger
from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.core.sites import SiteManager
from netconsole.models.device import Device
from netconsole.services.background_job import BackgroundJob
from netconsole.services.file_management_service import FileManagementApplicationService, run_file_management_download
from netconsole.services.file_transfer_service import FileTransferConnectionError, FileTransferService
from netconsole.services.host_key_trust_service import HostKeyTrustService
from netconsole.services.site_ssh_relay import SiteSSHRelayService, close_site_jump_sessions
from netconsole.services.site_storage import SiteRecord, SiteRegistryRepository
from netconsole.services.job_center.job_context import JobContext
from netconsole.repositories.device_repository import DeviceRepository


JUMP_USERNAME = "jump"
JUMP_PASSWORD = "jump-password"
TARGET_USERNAME = "device"
TARGET_PASSWORD = "device-password"
TARGET_IDENTITY = "target.internal"
LARGE_FILE = (b"NetConsole tunnel SFTP integration\n" * 65536) + b"EOF"


class _PasswordServer(paramiko.ServerInterface):
    def __init__(self, username: str, password: str) -> None:
        self.username = username
        self.password = password

    def get_allowed_auths(self, _username: str) -> str:
        return "password"

    def check_auth_password(self, username: str, password: str) -> int:
        if username == self.username and password == self.password:
            return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED


class _TargetServer(_PasswordServer):
    def check_channel_request(self, kind: str, _chanid: int) -> int:
        if kind == "session":
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED


class _MemorySftpServer(paramiko.SFTPServerInterface):
    files = {"flash:/large.bin": LARGE_FILE}

    def list_folder(self, path: str):
        if path not in {"flash:", "flash:/"}:
            return paramiko.SFTP_NO_SUCH_FILE
        attributes = paramiko.SFTPAttributes()
        attributes.filename = "large.bin"
        attributes.st_size = len(LARGE_FILE)
        attributes.st_mode = 0o100444
        return [attributes]

    def stat(self, path: str):
        payload = self.files.get(path)
        if payload is None:
            return paramiko.SFTP_NO_SUCH_FILE
        attributes = paramiko.SFTPAttributes()
        attributes.st_size = len(payload)
        attributes.st_mode = 0o100444
        return attributes

    def open(self, path: str, flags: int, _attr):
        if flags & (getattr(socket, "O_WRONLY", 1) | getattr(socket, "O_RDWR", 2)):
            return paramiko.SFTP_PERMISSION_DENIED
        payload = self.files.get(path)
        if payload is None:
            return paramiko.SFTP_NO_SUCH_FILE
        handle = paramiko.SFTPHandle(flags)
        handle.readfile = io.BytesIO(payload)
        return handle


class _JumpServer(_PasswordServer):
    def __init__(
        self,
        target_address: tuple[str, int],
        forward_counter: "_ForwardCounter",
    ) -> None:
        super().__init__(JUMP_USERNAME, JUMP_PASSWORD)
        self.target_address = target_address
        self.forward_counter = forward_counter
        self.destinations: dict[int, tuple[str, int]] = {}

    def check_channel_request(self, _kind: str, _chanid: int) -> int:
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_direct_tcpip_request(
        self,
        chanid: int,
        _origin: tuple[str, int],
        destination: tuple[str, int],
    ) -> int:
        if destination[0] != TARGET_IDENTITY:
            return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED
        self.destinations[chanid] = destination
        return paramiko.OPEN_SUCCEEDED


class _ForwardCounter:
    def __init__(self) -> None:
        self._value = 0
        self._lock = threading.Lock()

    @property
    def value(self) -> int:
        with self._lock:
            return self._value

    def increment(self) -> None:
        with self._lock:
            self._value += 1

    def decrement(self) -> None:
        with self._lock:
            self._value -= 1


class _SshTestServer:
    def __init__(
        self,
        host_key: paramiko.PKey,
        server_factory,
        *,
        sftp: bool = False,
    ) -> None:
        self.host_key = host_key
        self.server_factory = server_factory
        self.sftp = sftp
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(16)
        self.listener.settimeout(0.2)
        self.address = ("127.0.0.1", int(self.listener.getsockname()[1]))
        self.stop_event = threading.Event()
        self.transports: list[paramiko.Transport] = []
        self.threads: list[threading.Thread] = []
        self.thread = threading.Thread(
            target=self._accept_loop,
            name=f"test-sshd-{self.address[1]}",
            daemon=True,
        )
        self.thread.start()

    def _accept_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                client, _address = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            thread = threading.Thread(
                target=self._serve_client,
                args=(client,),
                daemon=True,
            )
            self.threads.append(thread)
            thread.start()

    def _serve_client(self, client: socket.socket) -> None:
        transport = paramiko.Transport(client)
        self.transports.append(transport)
        server = self.server_factory()
        try:
            transport.add_server_key(self.host_key)
            if self.sftp:
                transport.set_subsystem_handler(
                    "sftp",
                    paramiko.SFTPServer,
                    _MemorySftpServer,
                )
            transport.start_server(server=server)
            while transport.is_active() and not self.stop_event.is_set():
                channel = transport.accept(0.2)
                if channel is None:
                    continue
                if isinstance(server, _JumpServer):
                    thread = threading.Thread(
                        target=_forward_channel,
                        args=(
                            channel,
                            server.target_address,
                            server.forward_counter,
                        ),
                        daemon=True,
                    )
                    self.threads.append(thread)
                    thread.start()
        except (EOFError, OSError, paramiko.SSHException):
            pass
        finally:
            transport.close()

    def close(self) -> None:
        self.stop_event.set()
        try:
            self.listener.close()
        except OSError:
            pass
        for transport in tuple(self.transports):
            transport.close()
        self.thread.join(timeout=2)
        for thread in tuple(self.threads):
            thread.join(timeout=2)


def _forward_channel(
    channel: paramiko.Channel,
    target_address: tuple[str, int],
    counter: _ForwardCounter,
) -> None:
    target: socket.socket | None = None
    counter.increment()
    try:
        target = socket.create_connection(target_address, timeout=3)
        while not channel.closed:
            readable, _, _ = select.select([channel, target], [], [], 0.2)
            if channel in readable:
                payload = channel.recv(1024 * 1024)
                if not payload:
                    break
                target.sendall(payload)
            if target in readable:
                payload = target.recv(1024 * 1024)
                if not payload:
                    break
                channel.sendall(payload)
    except OSError as exc:
        if exc.errno not in {
            None,
            errno.EBADF,
            errno.ECONNRESET,
            errno.ENOTCONN,
        }:
            raise
    finally:
        if target is not None:
            target.close()
        channel.close()
        counter.decrement()


@pytest.fixture
def tunnel_topology():
    target_key = paramiko.RSAKey.generate(1024)
    jump_key = paramiko.RSAKey.generate(1024)
    target = _SshTestServer(
        target_key,
        lambda: _TargetServer(TARGET_USERNAME, TARGET_PASSWORD),
        sftp=True,
    )
    forwards = _ForwardCounter()
    jump = _SshTestServer(
        jump_key,
        lambda: _JumpServer(target.address, forwards),
    )
    try:
        yield target, jump, target_key, jump_key, forwards
    finally:
        jump.close()
        target.close()


def _device(jump_port: int, target_port: int) -> Device:
    return Device(
        id=1,
        device_uuid=Device.new_uuid(),
        name="MR-tunnel-integration",
        primary_address="",
        backup_address=TARGET_IDENTITY,
        ssh_enabled=1,
        ssh_port=target_port,
        ssh_username=TARGET_USERNAME,
        ssh_password=TARGET_PASSWORD,
        tunnel1_host="127.0.0.1",
        tunnel1_port=jump_port,
        tunnel1_username=JUMP_USERNAME,
        tunnel1_password=JUMP_PASSWORD,
    )


def _trust_topology(
    paths: PathResolver,
    *,
    target_port: int,
    jump_port: int,
    target_key: paramiko.PKey,
    jump_key: paramiko.PKey,
) -> HostKeyTrustService:
    trust = HostKeyTrustService(paths)
    trust.trust("127.0.0.1", jump_port, jump_key)
    trust.trust(TARGET_IDENTITY, target_port, target_key)
    return trust


def _wait_until(predicate, timeout: float = 3.0) -> bool:
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if predicate():
            return True
        sleep(0.02)
    return bool(predicate())


def test_backup_target_uses_real_jump_forward_and_downloads_large_file(
    tmp_path: Path,
    monkeypatch,
    tunnel_topology,
) -> None:
    target, jump, target_key, jump_key, forwards = tunnel_topology
    paths = PathResolver(tmp_path, tmp_path)
    trust = _trust_topology(
        paths,
        target_port=target.address[1],
        jump_port=jump.address[1],
        target_key=target_key,
        jump_key=jump_key,
    )
    service = FileTransferService(
        "demo",
        paths,
        strict_host_keys=True,
        host_key_trust=trust,
    )
    monkeypatch.setattr(
        "netconsole.services.file_transfer_service.DOWNLOAD_STABLE_WAIT_SECONDS",
        0,
    )

    root = service.connect(_device(jump.address[1], target.address[1]))
    files = service.list_directory(root)
    destination = tmp_path / "downloaded-large.bin"
    service.download(files[0].remote_path, destination, chunk_size=64 * 1024)

    assert service.successful_target is not None
    assert service.successful_target.method == "tunnel1_backup"
    assert service.successful_target.target_role == "backup"
    assert service._tunnel_session is not None
    assert forwards.value == 1
    assert destination.stat().st_size == len(LARGE_FILE)
    assert sha256(destination.read_bytes()).digest() == sha256(LARGE_FILE).digest()

    service.disconnect()
    assert _wait_until(lambda: forwards.value == 0)
    assert service._client is None
    assert service._sftp is None
    assert service._tunnel_session is None


def test_unknown_jump_and_target_keys_auto_register_before_real_sftp_connect(
    tmp_path: Path,
    tunnel_topology,
) -> None:
    target, jump, target_key, jump_key, _forwards = tunnel_topology
    paths = PathResolver(tmp_path, tmp_path)
    trust = HostKeyTrustService(paths)
    device = _device(jump.address[1], target.address[1])

    service = FileTransferService(
        "demo",
        paths,
        strict_host_keys=True,
        host_key_trust=trust,
    )
    assert service.connect(device) == "flash:/"
    assert trust.is_trusted("127.0.0.1", jump.address[1], jump_key, role="jump")
    assert trust.is_trusted(TARGET_IDENTITY, target.address[1], target_key)
    service.disconnect()


def test_jump_and_target_host_key_changes_are_replaced_and_sftp_continues(
    tmp_path: Path,
    tunnel_topology,
) -> None:
    target, jump, target_key, jump_key, _forwards = tunnel_topology
    jump_paths = PathResolver(tmp_path / "jump", tmp_path / "jump")
    jump_trust = HostKeyTrustService(jump_paths)
    jump_trust.trust("127.0.0.1", jump.address[1], paramiko.RSAKey.generate(1024))
    jump_trust.trust(TARGET_IDENTITY, target.address[1], target_key)

    jump_service = FileTransferService(
        "demo",
        jump_paths,
        strict_host_keys=True,
        host_key_trust=jump_trust,
    )
    assert jump_service.connect(_device(jump.address[1], target.address[1])) == "flash:/"
    assert jump_trust.is_trusted("127.0.0.1", jump.address[1], jump_key, role="jump")
    jump_service.disconnect()

    target_paths = PathResolver(tmp_path / "target", tmp_path / "target")
    target_trust = HostKeyTrustService(target_paths)
    target_trust.trust("127.0.0.1", jump.address[1], jump_key)
    target_trust.trust(
        TARGET_IDENTITY,
        target.address[1],
        paramiko.RSAKey.generate(1024),
    )
    target_service = FileTransferService(
        "demo",
        target_paths,
        strict_host_keys=True,
        host_key_trust=target_trust,
    )
    assert target_service.connect(_device(jump.address[1], target.address[1])) == "flash:/"
    assert target_trust.is_trusted(TARGET_IDENTITY, target.address[1], target_key)
    target_service.disconnect()


def test_site_relay_uses_shared_jump_channel_for_real_sftp(
    tmp_path: Path,
    monkeypatch,
    tunnel_topology,
) -> None:
    target, jump, target_key, jump_key, forwards = tunnel_topology
    paths = PathResolver(tmp_path, tmp_path)
    SiteManager(paths).create_site("demo", display_name="Demo")
    SiteSSHRelayService(paths).save(
        "demo",
        enabled=True,
        host="127.0.0.1",
        port=jump.address[1],
        username=JUMP_USERNAME,
        password=JUMP_PASSWORD,
    )
    trust = HostKeyTrustService(paths)
    service = FileTransferService(
        "demo",
        paths,
        strict_host_keys=True,
        host_key_trust=trust,
    )
    monkeypatch.setattr(
        "netconsole.services.file_transfer_service.DOWNLOAD_STABLE_WAIT_SECONDS",
        0,
    )

    try:
        root = service.connect(_device(jump.address[1], target.address[1]))
        files = service.list_directory(root)
        destination = tmp_path / "site-relay-downloaded.bin"
        service.download(files[0].remote_path, destination, chunk_size=64 * 1024)

        assert service.successful_target is not None
        assert service._tunnel_session is None
        assert service._relay_channel is not None
        assert forwards.value == 1
        assert trust.is_trusted("127.0.0.1", jump.address[1], jump_key, role="jump")
        assert trust.is_trusted(TARGET_IDENTITY, target.address[1], target_key, role="target")
        assert destination.read_bytes() == LARGE_FILE
    finally:
        service.disconnect()
        close_site_jump_sessions(paths=paths)


def test_worker_download_uses_canonical_site_relay_and_ignores_device_tunnel(
    tmp_path: Path,
    monkeypatch,
    tunnel_topology,
) -> None:
    target, jump, target_key, jump_key, forwards = tunnel_topology
    paths = PathResolver(tmp_path, tmp_path)
    physical_site = "physical-site"
    stable_site = "stable-site"
    SiteManager(paths).create_site(physical_site, display_name="Physical Site")
    registry = SiteRegistryRepository(paths)
    physical_record = registry.get_by_directory_name(physical_site)
    registry.register(SiteRecord(stable_site, "Stable Relay Site", physical_record.root_path))
    registry.unregister(physical_site, physical_record.root_path)
    assert registry.get_by_directory_name(physical_site).site_id == stable_site

    SiteSSHRelayService(paths).save(
        stable_site,
        enabled=True,
        host="127.0.0.1",
        port=jump.address[1],
        username=JUMP_USERNAME,
        password=JUMP_PASSWORD,
    )
    database = Database(paths.site_db_path(physical_site))
    device = DeviceRepository(database).create(
        Device(
            name="MR-worker-relay",
            device_type="MR",
            primary_address="192.0.2.200",
            backup_address=TARGET_IDENTITY,
            ssh_enabled=1,
            ssh_port=target.address[1],
            ssh_username=TARGET_USERNAME,
            ssh_password=TARGET_PASSWORD,
            tunnel1_host="127.0.0.1",
            tunnel1_port=jump.address[1],
            tunnel1_username=JUMP_USERNAME,
            tunnel1_password=JUMP_PASSWORD,
        )
    )
    trust = HostKeyTrustService(paths)
    logs: list[tuple[str, str]] = []
    monkeypatch.setattr(app_logger, "log_info", lambda event, detail="", **_kwargs: logs.append((event, detail)))
    monkeypatch.setattr(
        "netconsole.services.file_transfer_service.DOWNLOAD_STABLE_WAIT_SECONDS",
        0,
    )

    target_path = paths.file_downloads_root(physical_site) / "worker-relay.bin"
    interactive = FileManagementApplicationService(paths)._new_transfer(physical_site)
    try:
        root = interactive.connect(device)
        assert interactive.list_directory(root)
        assert interactive._tunnel_session is None
    finally:
        interactive.disconnect()

    job = BackgroundJob(
        job_id="worker-site-relay-download",
        task_type="file_management_download",
        params={
            "site_name": physical_site,
            "relay_site_id": stable_site,
            "device_id": device.device_uuid,
            "remote_entry_id": "fe1_" + "3" * 32,
            "remote_path": "flash:/large.bin",
            "remote_name": "large.bin",
            "remote_category": "bin",
            "remote_size": len(LARGE_FILE),
            "target_relative_path": target_path.relative_to(paths.site_dir(physical_site)).as_posix(),
            "target_kind": "device_file",
            "app_root": str(paths.app_root),
            "data_root": str(paths.data_root),
        },
    )

    try:
        result = run_file_management_download(JobContext.from_job(job))

        assert result["result_kind"] == "device_file"
        assert target_path.read_bytes() == LARGE_FILE
        assert forwards.value == 0
        route_logs = [detail for event, detail in logs if event == "FILE_TRANSFER_ROUTE_SELECTED"]
        assert route_logs
        assert all("site_id=stable-site" in detail for detail in route_logs)
        assert all("site_directory=physical-site" in detail for detail in route_logs)
        assert any("source=interactive" in detail for detail in route_logs)
        assert any("source=download_worker" in detail for detail in route_logs)
        assert all("route_mode=site_relay" in detail for detail in route_logs)
        assert not any("route_mode=device_tunnel" in detail for detail in route_logs)
        assert any("target=target.internal:" in detail for detail in route_logs)
        assert any(
            event == "ssh_relay_stage"
            and "stage=DIRECT_TCPIP_OPEN" in detail
            and "result=pass" in detail
            for event, detail in logs
        )
        assert trust.is_trusted("127.0.0.1", jump.address[1], jump_key, role="jump")
        assert trust.is_trusted(TARGET_IDENTITY, target.address[1], target_key, role="target")
    finally:
        close_site_jump_sessions(paths=paths)


def test_site_relay_failure_does_not_fallback_to_device_tunnel(
    tmp_path: Path,
    tunnel_topology,
) -> None:
    target, jump, _target_key, _jump_key, forwards = tunnel_topology
    paths = PathResolver(tmp_path, tmp_path)
    SiteManager(paths).create_site("demo", display_name="Demo")
    SiteSSHRelayService(paths).save(
        "demo",
        enabled=True,
        host="127.0.0.1",
        port=jump.address[1] + 1,
        username=JUMP_USERNAME,
        password=JUMP_PASSWORD,
    )
    service = FileTransferService("demo", paths, host_key_trust=HostKeyTrustService(paths))

    with pytest.raises(FileTransferConnectionError):
        service.connect(_device(jump.address[1], target.address[1]))

    assert service._tunnel_session is None
    assert forwards.value == 0
    service.disconnect()
    close_site_jump_sessions(paths=paths)
