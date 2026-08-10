from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import threading
from time import monotonic, perf_counter, sleep, time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Iterable
from uuid import uuid4

from netconsole.application.desktop.actions import DesktopActionResolutionError
from netconsole.core import app_logger
from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.core.windows_dpapi import protect_windows_data, unprotect_windows_data
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.core.settings import SettingsStore
from netconsole.core.sites import SiteManager
from netconsole.models.api.file_management import (
    FileConnectionDTO,
    FileDesktopActionDTO,
    FileDesktopActionResultDTO,
    FileDownloadBatchDTO,
    FileDownloadClearDTO,
    FileDownloadResultDTO,
    FileDownloadTaskDTO,
    FileManagementCapabilityDTO,
    FileManagementStatusDTO,
    FileRemoteDeviceDTO,
    LocalFileEntryDTO,
    LocalFilePageDTO,
    ManagedFileDTO,
    ManagedFilePageDTO,
    RemoteFileEntryDTO,
    RemoteFilePageDTO,
)
from netconsole.models.device import Device
from netconsole.models.mesh_log_models import MeshMrProfile
from netconsole.models.task_snapshot import TaskEvent, TaskSnapshot, utc_now_iso
from netconsole.models.task_state import TaskState
from netconsole.repositories.device_group_repository import DeviceGroupRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.repositories.mesh_mr_repository import MeshSchemaRebuildRequired
from netconsole.repositories.mesh_catalog_repository import MeshCatalogRepository
from netconsole.services.background_job import BackgroundJob
from netconsole.services.config_lifecycle_service import safe_artifact_display_name
from netconsole.services.file_transfer_service import (
    FileTransferConnectionError,
    FileTransferService,
    RemoteDeviceFile,
    SftpUnavailableError,
    auto_rename_path,
    file_sha256,
    is_within_remote_root,
    normalize_remote_path,
    parent_remote_path,
    safe_device_name,
)
from netconsole.services.host_key_trust_service import (
    HostKeyDetails,
    HostKeyTrustGrant,
    HostKeyTrustError,
    HostKeyTrustService,
)
from netconsole.services.external_terminal import find_winscp_exe, launch_winscp
from netconsole.services.mesh_import_service import MeshImportService
from netconsole.services.mesh_catalog_index_service import MeshCatalogIndexService
from netconsole.services.mesh_storage_service import MeshStorageService
from netconsole.services.mesh_derived_data_maintenance_service import MeshDerivedDataMaintenanceService
from netconsole.services.job_center.web_export_event_safety import redact_web_task_text
from netconsole.services.netmiko_connection import sanitize_sensitive_text

if TYPE_CHECKING:
    from netconsole.application.desktop import DesktopActionService
    from netconsole.services.job_center.job_context import JobContext
    from netconsole.services.job_center.local_process_adapter import LocalProcessAdapter
    from netconsole.services.job_center.task_application_service import TaskApplicationService
    from netconsole.services.device_operation_service import DeviceOperationService


FILE_REF_RE = re.compile(r"^fm1_[0-9a-f]{32}$")
CONNECTION_ID_RE = re.compile(r"^fc1_[0-9a-f]{32}$")
REMOTE_ENTRY_ID_RE = re.compile(r"^fe1_[0-9a-f]{32}$")
ARTIFACT_ID_RE = re.compile(r"^fa1_[0-9a-f]{32}$")
LOCAL_ENTRY_ID_RE = re.compile(r"^fl1_[0-9a-f]{32}$")
DEVICE_FILE_REF_RE = re.compile(r"^fd1_[0-9a-f]{32}$")
DESKTOP_ACTION_RE = re.compile(r"^fda1_[0-9a-f]{32}$")
SFTP_SETUP_CONFIRMATION_RE = re.compile(r"^sf1_[0-9a-f]{32}$")
FILE_CATEGORIES = {"session", "raw", "package", "artifact"}
ARTIFACT_SUFFIXES = {".csv", ".diff", ".html", ".json", ".md", ".pdf", ".png", ".txt", ".xls", ".xlsx"}
PACKAGE_SUFFIXES = (".tar.gz", ".tgz", ".zip", ".zip.gz")
RAW_SUFFIXES = {".csv", ".json", ".jsonl", ".log", ".pcap", ".pcapng", ".txt", ".yaml", ".yml"}
SESSION_SUFFIXES = {".csv", ".json", ".jsonl", ".log", ".pcap", ".pcapng", ".txt", ".yaml", ".yml"}
REMOTE_FILES_UNAVAILABLE = "当前局点没有可用的设备资料库。"
REMOTE_FILES_AVAILABLE = "设备文件通过受控 SFTP 会话读取。"
WINSCP_INTEGRATION_MESSAGE = "当前桌面宿主未提供 WinSCP 联动。"
ACTIVE_DOWNLOAD_STATES = {TaskState.PENDING, TaskState.STARTING, TaskState.RUNNING, TaskState.STOPPING}
TERMINAL_DOWNLOAD_STATES = {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}
DOWNLOAD_DESCRIPTOR_EVENT = "file_management_descriptor"
DOWNLOAD_HIDDEN_EVENT = "file_management_hidden"
DOWNLOAD_WAITING_EVENT = "file_management_waiting"
MESH_HISTORY_LOG_PATTERN = re.compile(r"^\d{4}_\d{2}_\d{2}_\d+meshlog\.log\.gz$", re.IGNORECASE)
class FileManagementError(ValueError):
    pass


class FileReferenceNotFound(FileManagementError):
    pass


class DeviceFileSftpError(RuntimeError):
    """设备文件连接的稳定错误契约；不携带命令、凭据或服务端路径。"""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        task_id: str = "",
        details: dict[str, object] | None = None,
    ) -> None:
        self.code = code
        self.task_id = str(task_id or "")
        self.details = dict(details or {})
        super().__init__(message)


@dataclass(frozen=True)
class ResolvedManagedFile:
    file_ref: str
    site_id: str
    path: Path
    relative_path: str
    category: str


@dataclass(frozen=True)
class _RemoteEntry:
    device_id: str
    remote_file: RemoteDeviceFile


@dataclass(frozen=True)
class _LocalEntry:
    site_id: str
    root: Path
    path: Path


@dataclass(frozen=True)
class FileDesktopActionCommand:
    """仅供未来 Native Bridge 消费的一次性强类型动作，不进入 HTTP DTO。"""

    action: str
    site_id: str = ""
    path: Path | None = None
    device_id: str = ""


@dataclass
class _DesktopAction:
    site_id: str
    expires_at: datetime
    command: FileDesktopActionCommand


@dataclass
class _RemoteSession:
    connection_id: str
    site_id: str
    device_id: str
    device: Device
    transfer: FileTransferService
    root_path: str
    root_entry_id: str
    current_entry_id: str
    entries: dict[str, _RemoteEntry]
    entry_ids: dict[str, str]
    lock: threading.RLock


@dataclass(frozen=True)
class _PendingHostKey:
    site_id: str
    device_id: str
    host: str
    port: int
    key: object
    details: HostKeyDetails
    grants: tuple[HostKeyTrustGrant, ...]
    sftp_enable_task_id: str
    expires_at: datetime


@dataclass(frozen=True)
class _PendingSftpSetup:
    site_id: str
    device_id: str
    trust_host_key_once: tuple[HostKeyTrustGrant, ...]
    expires_at: datetime


DeviceResolver = Callable[[str, str], Device | None]
TransferServiceFactory = Callable[..., FileTransferService]


class FileManagementApplicationService:
    """文件管理 Web 用例：受控本地文件、设备会话和下载任务。"""

    def __init__(
        self,
        paths: PathResolver,
        *,
        task_service: TaskApplicationService | None = None,
        process_adapter: LocalProcessAdapter | None = None,
        site_name: str = "demo",
        device_resolver: DeviceResolver | None = None,
        transfer_factory: TransferServiceFactory = FileTransferService,
        mesh_auto_import_enabled: bool = True,
        desktop_action_service: DesktopActionService | None = None,
        device_operation_service: DeviceOperationService | None = None,
    ) -> None:
        self.paths = paths
        self.site_name = str(site_name or "demo")
        self.task_service = task_service
        self.process_adapter = process_adapter
        self._device_resolver = device_resolver
        self._transfer_factory = transfer_factory
        self._mesh_auto_import_enabled = bool(mesh_auto_import_enabled)
        self._desktop_action_service = desktop_action_service
        self._device_operation_service = device_operation_service
        self._sessions: dict[str, _RemoteSession] = {}
        self._sessions_lock = threading.RLock()
        self._pending_host_keys: dict[str, _PendingHostKey] = {}
        self._pending_host_keys_lock = threading.RLock()
        self._pending_sftp_setups: dict[str, _PendingSftpSetup] = {}
        self._pending_sftp_setups_lock = threading.RLock()
        self._local_entries: dict[str, _LocalEntry] = {}
        self._local_entry_ids: dict[tuple[str, str, str], str] = {}
        self._local_entries_lock = threading.RLock()
        self._desktop_actions: dict[str, _DesktopAction] = {}
        self._desktop_actions_lock = threading.RLock()
        self._target_lock = threading.RLock()
        self._reserved_targets: set[str] = set()
        self._parts_cleaned: set[str] = set()
        self._parts_cleanup_thread: threading.Thread | None = None
        self._queue_lock = threading.RLock()
        self._queue_sites: set[str] = {self.site_name}
        self._queue_stop = threading.Event()
        self._queue_thread: threading.Thread | None = None
        self._owns_process_adapter = False
        if self.task_service is not None and self.process_adapter is None:
            from netconsole.services.job_center.local_process_adapter import LocalProcessAdapter

            self.process_adapter = LocalProcessAdapter(self.task_service)
            self._owns_process_adapter = True

    def start(self) -> None:
        """启动持久下载队列；只由宿主生命周期调用。"""

        if self._queue_stop.is_set():
            return
        with self._queue_lock:
            if (
                self.task_service is not None
                and callable(getattr(self.process_adapter, "start_job", None))
                and (self._queue_thread is None or not self._queue_thread.is_alive())
            ):
                self._queue_thread = threading.Thread(
                    target=self._run_download_queue,
                    name="file-management-download-queue",
                    daemon=True,
                )
                self._queue_thread.start()
            if self._parts_cleanup_thread is None or not self._parts_cleanup_thread.is_alive():
                site = self.current_site_id()
                self._parts_cleanup_thread = threading.Thread(
                    target=self._cleanup_stale_parts_once,
                    args=(site,),
                    name="file-management-part-cleanup",
                    daemon=True,
                )
                self._parts_cleanup_thread.start()

    def close(self) -> None:
        """幂等关闭全部 Web 会话；FastAPI lifespan 必须在 shutdown 调用。"""
        self._queue_stop.set()
        queue_thread = self._queue_thread
        if queue_thread is threading.current_thread():
            return
        if queue_thread is not None:
            # 队列可能正处于 SQLite busy wait；必须等它真正退出后才能关闭共享进程宿主。
            queue_thread.join()
            with self._queue_lock:
                if self._queue_thread is queue_thread:
                    self._queue_thread = None
        cleanup_thread = self._parts_cleanup_thread
        if cleanup_thread is not None and cleanup_thread is not threading.current_thread():
            cleanup_thread.join(timeout=2.0)
            if not cleanup_thread.is_alive():
                self._parts_cleanup_thread = None
        with self._sessions_lock:
            sessions = tuple(self._sessions.values())
            self._sessions.clear()
        with self._pending_host_keys_lock:
            self._pending_host_keys.clear()
        with self._pending_sftp_setups_lock:
            self._pending_sftp_setups.clear()
        for session in sessions:
            try:
                session.transfer.disconnect()
            except Exception:
                pass
        if self._owns_process_adapter and self.process_adapter is not None:
            self.process_adapter.shutdown()

    def current_site_id(self) -> str:
        try:
            return SiteManager(self.paths).get_current_site()
        except (OSError, ValueError, KeyError):
            return self.site_name

    def status(self, site_id: str = "") -> FileManagementStatusDTO:
        site = self._site_id(site_id)
        with self._queue_lock:
            self._queue_sites.add(site)
        device_db_exists = self.paths.site_db_path(site).is_file()
        return FileManagementStatusDTO(
            site_id=site,
            local_files=FileManagementCapabilityDTO(
                available=self._files_root(site).is_dir(),
                message="" if self._files_root(site).is_dir() else "当前局点尚未创建本地文件目录。",
            ),
            device_files=FileManagementCapabilityDTO(
                available=device_db_exists,
                message=REMOTE_FILES_AVAILABLE if device_db_exists else REMOTE_FILES_UNAVAILABLE,
            ),
            winscp=self._winscp_capability(),
        )

    def list_local_files(
        self,
        site_id: str = "",
        *,
        directory_id: str = "",
        device_id: str = "",
        page: int = 1,
        limit: int = 500,
    ) -> LocalFilePageDTO:
        """浏览下载目录；客户端永远只接收会话内 opaque 引用。"""
        site = self._site_id(site_id)
        with self._queue_lock:
            self._queue_sites.add(site)
        root = self._local_root(site, device_id=device_id)
        root.mkdir(parents=True, exist_ok=True)
        root_id = self._remember_local_entry(site, root, root)
        default_path = self._default_local_path(site, device_id) if str(device_id or "").strip() else root
        default_path.mkdir(parents=True, exist_ok=True)
        current_id = str(directory_id or self._remember_local_entry(site, root, default_path))
        current = self._local_entry(site, current_id)
        if current.root != root or not current.path.is_dir():
            raise FileReferenceNotFound("本地目录引用不存在或不属于当前受控目录")
        try:
            entries = tuple(os.scandir(current.path))
        except OSError as exc:
            raise RuntimeError(f"本地目录读取失败：{exc}") from exc
        items: list[LocalFileEntryDTO] = []
        for entry in entries:
            try:
                if entry.is_symlink() or str(entry.name).endswith(".part"):
                    continue
                is_dir = entry.is_dir(follow_symlinks=False)
                if not is_dir and not entry.is_file(follow_symlinks=False):
                    continue
                stat_result = entry.stat(follow_symlinks=False)
                child = Path(entry.path).resolve()
                child_id = self._remember_local_entry(site, root, child)
                items.append(
                    LocalFileEntryDTO(
                        entry_id=child_id,
                        name=entry.name,
                        is_dir=is_dir,
                        size_bytes=None if is_dir else max(0, int(stat_result.st_size)),
                        modified_at=datetime.fromtimestamp(stat_result.st_mtime).isoformat(timespec="seconds"),
                        file_type="directory" if is_dir else (child.suffix.lstrip(".") or "file"),
                        downloadable=not is_dir,
                    )
                )
            except OSError:
                continue
        items.sort(key=lambda item: (not item.is_dir, item.name.casefold()))
        selected_page = max(1, int(page))
        selected_limit = max(1, min(int(limit), 500))
        start = (selected_page - 1) * selected_limit
        parent = current.path.parent if current.path != root else root
        parent_id = self._remember_local_entry(site, root, parent)
        return LocalFilePageDTO(
            site_id=site,
            root_entry_id=root_id,
            current_entry_id=current_id,
            parent_entry_id=parent_id,
            current_label=root.name if current.path == root else current.path.name,
            items=items[start : start + selected_limit],
            total=len(items),
            page=selected_page,
            limit=selected_limit,
            has_more=start + selected_limit < len(items),
        )

    def create_local_directory(
        self,
        site_id: str,
        *,
        directory_id: str = "",
        device_id: str = "",
        name: str,
    ) -> LocalFilePageDTO:
        site = self._site_id(site_id)
        root = self._local_root(site, device_id=device_id)
        root.mkdir(parents=True, exist_ok=True)
        default_path = self._default_local_path(site, device_id) if str(device_id or "").strip() else root
        default_path.mkdir(parents=True, exist_ok=True)
        current_id = str(directory_id or self._remember_local_entry(site, root, default_path))
        current = self._local_entry(site, current_id)
        if current.root != root or not current.path.is_dir():
            raise FileReferenceNotFound("本地目录引用不存在或不属于当前受控目录")
        safe_name = safe_device_name(name)
        target = (current.path / safe_name).resolve()
        self._assert_within(target, root, "本地目录超出受控范围")
        try:
            target.mkdir()
        except FileExistsError as exc:
            raise FileManagementError("同名目录已存在") from exc
        except OSError as exc:
            raise RuntimeError(f"本地目录创建失败：{exc}") from exc
        return self.list_local_files(site, directory_id=current_id, device_id=device_id)

    def open_local_file(self, site_id: str, entry_id: str) -> tuple[Path, str]:
        entry = self._local_entry(self._site_id(site_id), entry_id)
        if not entry.path.is_file() or entry.path.is_symlink() or entry.path.name.endswith(".part"):
            raise FileReferenceNotFound("本地文件不存在或不可打开")
        return entry.path, entry.path.name

    def list_remote_devices(self, site_id: str = "") -> list[FileRemoteDeviceDTO]:
        site = self._site_id(site_id)
        database_path = self.paths.site_db_path(site)
        if not database_path.is_file():
            return []
        database = Database(database_path)
        devices = DeviceRepository(database).list()
        groups = {
            int(group.id): group.name
            for group in DeviceGroupRepository(database, site).list()
            if group.id is not None
        }
        return [
            FileRemoteDeviceDTO(
                device_id=str(device.device_uuid or device.id or ""),
                name=str(
                    device.name
                    or device.system_name
                    or device.primary_address
                    or device.backup_address
                ),
                address=str(device.primary_address or device.backup_address or ""),
                group_id=device.group_id,
                group_name=groups.get(int(device.group_id), "") if device.group_id is not None else "",
                device_type=str(device.device_type or ""),
                station=str(device.station or ""),
            )
            for device in devices
            if (device.device_uuid or device.id)
            and (device.primary_address or device.backup_address)
            and bool(device.ssh_enabled)
        ]

    def connect_device(
        self,
        site_id: str,
        device_id: str,
        *,
        trust_host_key_once: tuple[HostKeyTrustGrant, ...] = (),
    ) -> FileConnectionDTO:
        site = self._site_id(site_id)
        device = self._resolve_device(site, device_id)
        device_key = str(device.device_uuid or device_id)
        self._close_device_sessions(site, device_key)
        transfer = self._new_transfer(
            site,
            trust_host_key_once=trust_host_key_once,
        )
        try:
            root_path = normalize_remote_path(transfer.connect(device))
        except SftpUnavailableError as exc:
            try:
                transfer.disconnect()
            except Exception:
                pass
            self._request_sftp_setup_confirmation(
                site,
                device,
                trust_host_key_once=trust_host_key_once,
                attempts=list(exc.details.get("attempts") or []),
            )
            raise AssertionError("SFTP setup confirmation must interrupt the connection flow") from exc
        except HostKeyTrustError as exc:
            try:
                transfer.disconnect()
            except Exception:
                pass
            self._raise_host_key_challenge(
                site,
                device,
                exc,
                grants=trust_host_key_once,
            )
        except FileTransferConnectionError as exc:
            try:
                transfer.disconnect()
            except Exception:
                pass
            raise DeviceFileSftpError(
                exc.code,
                str(exc),
                details=exc.details,
            ) from exc
        except Exception as exc:
            try:
                transfer.disconnect()
            except Exception:
                pass
            app_logger.log_error(
                "DEVICE_FILE_SFTP_NEGOTIATION_FAILED",
                f"device={device.name or device.primary_address}, error={sanitize_sensitive_text(str(exc), device)}",
            )
            raise DeviceFileSftpError(
                "DEVICE_FILE_SFTP_NEGOTIATION_FAILED",
                "建立受控 SFTP 连接失败。",
            ) from exc
        return self._register_connected_transfer(site, device_key, device, transfer, root_path, message="SFTP 连接成功")

    def _request_sftp_setup_confirmation(
        self,
        site: str,
        device: Device,
        *,
        trust_host_key_once: tuple[HostKeyTrustGrant, ...],
        attempts: list[object] | None = None,
    ) -> None:
        confirmation_id = f"sf1_{uuid4().hex}"
        device_id = str(device.device_uuid or device.id or "")
        with self._pending_sftp_setups_lock:
            now = datetime.now(UTC)
            self._pending_sftp_setups = {
                key: value
                for key, value in self._pending_sftp_setups.items()
                if value.expires_at >= now
            }
            self._pending_sftp_setups[confirmation_id] = _PendingSftpSetup(
                site_id=site,
                device_id=device_id,
                trust_host_key_once=trust_host_key_once,
                expires_at=now + timedelta(minutes=5),
            )
        raise DeviceFileSftpError(
            "DEVICE_FILE_SFTP_UNAVAILABLE",
            "检测到设备未启用 SFTP，需要确认后通过受控命令启用并重新连接。",
            details={
                "confirmation_id": confirmation_id,
                "attempts": list(attempts or []),
            },
        )

    def confirm_sftp_setup(self, site_id: str, confirmation_id: str) -> FileConnectionDTO:
        site = self._site_id(site_id)
        value = str(confirmation_id or "").strip()
        if not SFTP_SETUP_CONFIRMATION_RE.fullmatch(value):
            raise FileReferenceNotFound("SFTP 自动恢复确认已失效")
        with self._pending_sftp_setups_lock:
            pending = self._pending_sftp_setups.pop(value, None)
        if pending is None or pending.site_id != site or pending.expires_at <= datetime.now(UTC):
            raise FileReferenceNotFound("SFTP 自动恢复确认已失效，请重新连接设备")
        device = self._resolve_device(site, pending.device_id)
        device_key = str(device.device_uuid or pending.device_id)
        self._close_device_sessions(site, device_key)
        task_id = self._enable_device_sftp(site, device)
        transfer = self._new_transfer(site, trust_host_key_once=pending.trust_host_key_once)
        try:
            transfer, root_path = self._reconnect_after_sftp_enable(
                site,
                device,
                transfer,
                task_id=task_id,
                trust_host_key_once=pending.trust_host_key_once,
            )
        except HostKeyTrustError as exc:
            self._raise_host_key_challenge(
                site,
                device,
                exc,
                grants=pending.trust_host_key_once,
                sftp_enable_task_id=task_id,
            )
        return self._register_connected_transfer(
            site,
            device_key,
            device,
            transfer,
            root_path,
            message="已在设备侧启用 SFTP，并完成重新连接。",
        )

    def _register_connected_transfer(
        self,
        site: str,
        device_key: str,
        device: Device,
        transfer: FileTransferService,
        root_path: str,
        *,
        message: str,
    ) -> FileConnectionDTO:
        connection_id = f"fc1_{uuid4().hex}"
        root_file = RemoteDeviceFile("根目录", root_path, None, None, "dir", is_dir=True, file_type="directory")
        root_entry_id = self._new_remote_entry_id()
        session = _RemoteSession(
            connection_id=connection_id,
            site_id=site,
            device_id=device_key,
            device=device,
            transfer=transfer,
            root_path=root_path,
            root_entry_id=root_entry_id,
            current_entry_id=root_entry_id,
            entries={root_entry_id: _RemoteEntry(device_key, root_file)},
            entry_ids={root_path: root_entry_id},
            lock=threading.RLock(),
        )
        self._register_session(session)
        return self._connection_dto(session, message)

    def _new_transfer(
        self,
        site: str,
        *,
        trust_host_key_once: tuple[HostKeyTrustGrant, ...] = (),
    ) -> FileTransferService:
        """创建只读 SFTP Transport；自动配置不属于 Transport 构造契约。"""

        return self._transfer_factory(
            site,
            self.paths,
            strict_host_keys=True,
            host_key_trust=HostKeyTrustService(self.paths),
            trust_host_key_once=trust_host_key_once,
        )

    def _enable_device_sftp(self, site: str, device: Device) -> str:
        from netconsole.services.device_operation_service import DeviceSftpEnableProfileUnresolved

        service = self._device_operation_service
        if service is None:
            raise DeviceFileSftpError(
                "DEVICE_FILE_SFTP_ENABLE_UNSUPPORTED",
                "当前设备未接入受控 SFTP 自动配置能力，请确认设备型号和软件版本。",
            )
        try:
            task = service.start(
                str(device.device_uuid or device.id or ""),
                "device.sftp.enable",
                idempotency_key=f"file-sftp:{uuid4().hex}",
            )
        except DeviceSftpEnableProfileUnresolved as exc:
            raise DeviceFileSftpError(
                "DEVICE_FILE_SFTP_ENABLE_PROFILE_UNRESOLVED",
                "无法确认设备的软件版本，未执行 SFTP 配置命令。",
            ) from exc
        except (KeyError, ValueError) as exc:
            raise DeviceFileSftpError(
                "DEVICE_FILE_SFTP_ENABLE_UNSUPPORTED",
                "当前设备版本暂无已验证的自动启用 SFTP 命令。请确认设备型号和软件版本，或在设备侧手动启用。",
            ) from exc
        except Exception as exc:
            detail = redact_web_task_text(sanitize_sensitive_text(str(exc), device))
            raise DeviceFileSftpError(
                "DEVICE_FILE_SFTP_ENABLE_FAILED",
                f"自动启用 SFTP 任务启动失败：{detail[:240] or '未知错误'}",
            ) from exc
        task_id = str(task.task_id or "")
        if not task_id:
            raise DeviceFileSftpError("DEVICE_FILE_SFTP_ENABLE_FAILED", "自动启用 SFTP 任务未能创建。")
        if not self._wait_for_task(site, task_id, timeout_seconds=60.0):
            raise DeviceFileSftpError(
                "DEVICE_FILE_SFTP_ENABLE_PENDING",
                "正在执行启用设备 SFTP 任务，请稍候后从任务中心查看结果。",
                task_id=task_id,
            )
        snapshot = self._task_snapshot(site, task_id)
        if snapshot is None or snapshot.status is not TaskState.COMPLETED:
            detail = redact_web_task_text(
                sanitize_sensitive_text(
                    str(getattr(snapshot, "error_message", "") or getattr(snapshot, "message", "") or "命令执行失败"),
                    device,
                )
            )
            raise DeviceFileSftpError(
                "DEVICE_FILE_SFTP_ENABLE_FAILED",
                f"自动启用 SFTP 失败：{detail[:240]}",
                task_id=task_id,
            )
        return task_id

    def _reconnect_after_sftp_enable(
        self,
        site: str,
        device: Device,
        transfer: FileTransferService,
        *,
        task_id: str,
        trust_host_key_once: tuple[HostKeyTrustGrant, ...],
    ) -> tuple[FileTransferService, str]:
        last_error: Exception | None = None
        for attempt in range(4):
            try:
                return transfer, normalize_remote_path(transfer.connect(device))
            except SftpUnavailableError as exc:
                last_error = exc
                transfer.disconnect()
                if attempt < 3:
                    sleep(1.0)
                    transfer = self._new_transfer(
                        site,
                        trust_host_key_once=trust_host_key_once,
                    )
            except HostKeyTrustError:
                transfer.disconnect()
                raise
            except Exception as exc:
                last_error = exc
                transfer.disconnect()
                break
        raise DeviceFileSftpError(
            "DEVICE_FILE_SFTP_RECONNECT_FAILED",
            "设备侧 SFTP 已执行启用，但重新连接设备文件服务失败，请稍后重试。",
            task_id=task_id,
        ) from last_error

    def _task_snapshot(self, site: str, task_id: str) -> TaskSnapshot | None:
        if self.task_service is None:
            return None
        return self.task_service.repository(site).get(task_id)

    def _wait_for_task(self, site: str, task_id: str, *, timeout_seconds: float) -> bool:
        deadline = monotonic() + max(0.1, float(timeout_seconds))
        wait = getattr(self.process_adapter, "wait", None)
        if callable(wait):
            wait(task_id, max(0.0, deadline - monotonic()))
        while monotonic() < deadline:
            snapshot = self._task_snapshot(site, task_id)
            if snapshot is not None and snapshot.status in TERMINAL_DOWNLOAD_STATES:
                return True
            sleep(0.1)
        snapshot = self._task_snapshot(site, task_id)
        return snapshot is not None and snapshot.status in TERMINAL_DOWNLOAD_STATES

    def cancel_sftp_enable_task(self, site_id: str, task_id: str) -> bool:
        service = self._device_operation_service
        if service is None:
            return False
        return service.cancel(task_id, site=self._site_id(site_id))

    def trust_host_key(
        self,
        site_id: str,
        challenge_id: str,
        *,
        persist: bool,
    ) -> FileConnectionDTO:
        site = self._site_id(site_id)
        value = str(challenge_id or "").strip()
        if not re.fullmatch(r"hk1_[0-9a-f]{32}", value):
            raise FileReferenceNotFound("主机密钥确认已失效")
        with self._pending_host_keys_lock:
            pending = self._pending_host_keys.pop(value, None)
        if pending is None or pending.site_id != site or pending.expires_at <= datetime.now(UTC):
            raise FileReferenceNotFound("主机密钥确认已失效，请重新连接设备")
        if persist:
            HostKeyTrustService(self.paths).trust(pending.host, pending.port, pending.key)
            grants = pending.grants
        else:
            grants = (
                *pending.grants,
                HostKeyTrustGrant.from_key(
                    pending.host,
                    pending.port,
                    pending.key,
                ),
            )
        if pending.sftp_enable_task_id:
            device = self._resolve_device(site, pending.device_id)
            transfer = self._new_transfer(site, trust_host_key_once=grants)
            try:
                transfer, root_path = self._reconnect_after_sftp_enable(
                    site,
                    device,
                    transfer,
                    task_id=pending.sftp_enable_task_id,
                    trust_host_key_once=grants,
                )
            except HostKeyTrustError as exc:
                self._raise_host_key_challenge(
                    site,
                    device,
                    exc,
                    grants=grants,
                    sftp_enable_task_id=pending.sftp_enable_task_id,
                )
            return self._register_connected_transfer(
                site,
                str(device.device_uuid or pending.device_id),
                device,
                transfer,
                root_path,
                message="已在设备侧启用 SFTP，并完成重新连接。",
            )
        return self.connect_device(
            site,
            pending.device_id,
            trust_host_key_once=grants,
        )

    def _raise_host_key_challenge(
        self,
        site: str,
        device: Device,
        exc: HostKeyTrustError,
        *,
        grants: tuple[HostKeyTrustGrant, ...] = (),
        sftp_enable_task_id: str = "",
    ) -> None:
        if exc.code not in {
            "DEVICE_FILE_HOST_KEY_UNKNOWN",
            "DEVICE_FILE_TARGET_HOST_KEY_UNKNOWN",
            "DEVICE_FILE_JUMP_HOST_KEY_UNKNOWN",
        }:
            raise exc
        device_key = str(device.device_uuid or device.id or "")
        challenge_id = f"hk1_{uuid4().hex}"
        details = HostKeyDetails(
            host=str(exc.details.get("host") or device.primary_address or ""),
            port=int(exc.details.get("port") or device.ssh_port or 22),
            algorithm=str(exc.details.get("algorithm") or ""),
            fingerprint_sha256=str(exc.details.get("fingerprint_sha256") or ""),
            role=str(exc.details.get("host_key_role") or "target"),
        )
        key = getattr(exc, "key", None)
        if key is None:
            raise exc
        with self._pending_host_keys_lock:
            self._pending_host_keys[challenge_id] = _PendingHostKey(
                site_id=site,
                device_id=device_key,
                host=details.host,
                port=details.port,
                key=key,
                details=details,
                grants=grants,
                sftp_enable_task_id=str(sftp_enable_task_id or ""),
                expires_at=datetime.now(UTC) + timedelta(minutes=5),
            )
        raise HostKeyTrustError(
            str(exc),
            {
                **details.as_dict(),
                "challenge_id": challenge_id,
                "device_id": device_key,
                "device_name": str(device.name or ""),
            },
            code=exc.code,
        ) from exc

    def disconnect_device(self, site_id: str, connection_id: str) -> FileConnectionDTO:
        session = self._session(site_id, connection_id)
        self._close_session(session)
        return self._connection_dto(session, "已断开", status="DISCONNECTED")

    def list_remote_files(
        self,
        site_id: str,
        connection_id: str,
        entry_id: str = "",
        *,
        page: int = 1,
        limit: int = 500,
    ) -> RemoteFilePageDTO:
        session = self._session(site_id, connection_id)
        with session.lock:
            self._assert_session_active(session)
            selected_id = str(entry_id or session.current_entry_id)
            selected = session.entries.get(selected_id)
            if selected is None:
                raise FileReferenceNotFound("远程目录引用不存在或不属于当前设备会话")
            if not selected.remote_file.is_dir:
                raise FileManagementError("只能浏览远程目录")
            try:
                files = session.transfer.list_directory(selected.remote_file.remote_path)
            except Exception as exc:
                if self._is_session_failure(exc) or not self._transfer_is_connected(session.transfer):
                    self._close_session(session)
                    raise DeviceFileSftpError(
                        "DEVICE_FILE_SESSION_DISCONNECTED",
                        "设备文件会话已断开，请重新连接。",
                    ) from exc
                app_logger.log_error(
                    "DEVICE_FILE_REMOTE_LIST_FAILED",
                    f"device={session.device.name or session.device.primary_address}, error={sanitize_sensitive_text(str(exc), session.device)}",
                )
                raise FileManagementError("远程目录读取失败，请检查当前账号的目录读取权限。") from exc
            items: list[RemoteFileEntryDTO] = []
            for remote_file in files:
                normalized = normalize_remote_path(
                    remote_file.remote_path,
                    current_path=selected.remote_file.remote_path,
                    root_path=session.root_path,
                )
                controlled = RemoteDeviceFile(
                    name=Path(remote_file.name).name,
                    remote_path=normalized,
                    size=remote_file.size,
                    modified_time=remote_file.modified_time,
                    category=remote_file.category,
                    is_dir=remote_file.is_dir,
                    file_type=remote_file.file_type,
                )
                child_id = session.entry_ids.get(normalized) or self._new_remote_entry_id()
                session.entry_ids[normalized] = child_id
                session.entries[child_id] = _RemoteEntry(session.device_id, controlled)
                items.append(
                    RemoteFileEntryDTO(
                        entry_id=child_id,
                        name=controlled.name,
                        is_dir=controlled.is_dir,
                        size_bytes=None if controlled.is_dir else max(0, int(controlled.size or 0)),
                        modified_at=controlled.modified_time,
                        category=controlled.category,
                        file_type=controlled.file_type,
                        downloadable=not controlled.is_dir,
                    )
                )
            parent_path = parent_remote_path(selected.remote_file.remote_path, session.root_path)
            parent_id = session.entry_ids.get(parent_path) or self._new_remote_entry_id()
            session.entry_ids[parent_path] = parent_id
            if parent_id not in session.entries:
                parent_name = Path(parent_path.rstrip("/")).name or "根目录"
                session.entries[parent_id] = _RemoteEntry(
                    session.device_id,
                    RemoteDeviceFile(parent_name, parent_path, None, None, "dir", is_dir=True, file_type="directory"),
                )
            session.current_entry_id = selected_id
            items.sort(key=lambda item: (not item.is_dir, item.name.casefold()))
            selected_page = max(1, int(page))
            selected_limit = max(1, min(int(limit), 500))
            start = (selected_page - 1) * selected_limit
            return RemoteFilePageDTO(
                connection_id=session.connection_id,
                current_entry_id=selected_id,
                parent_entry_id=parent_id,
                current_label="根目录" if selected_id == session.root_entry_id else selected.remote_file.name,
                items=items[start : start + selected_limit],
                total=len(items),
                page=selected_page,
                limit=selected_limit,
                has_more=start + selected_limit < len(items),
            )

    def list_download_tasks(self, site_id: str, limit: int = 20) -> list[FileDownloadTaskDTO]:
        if self.task_service is None:
            return []
        site = self._site_id(site_id)
        with self._queue_lock:
            self._queue_sites.add(site)
        requested = max(1, min(int(limit), 200))
        repository = self.task_service.repository(site)
        filters = {
            "owner": "web_file_management",
            "source": "local",
            "site_name": site,
            "task_types": {"file_management_download"},
        }
        active = repository.list_filtered(statuses=ACTIVE_DOWNLOAD_STATES, limit=1000, **filters)
        remaining = max(0, requested - len(active))
        terminal = repository.list_filtered(statuses=TERMINAL_DOWNLOAD_STATES, limit=remaining, **filters) if remaining else []
        snapshots = [*active, *terminal]
        metadata = self._download_task_metadata(repository, snapshots)
        return [
            self._download_task_from_snapshot(site, snapshot, metadata=metadata.get(snapshot.task_id))
            for snapshot in snapshots
            if not bool(metadata.get(snapshot.task_id, {}).get("hidden"))
        ]

    def cancel_download(self, site_id: str, task_id: str) -> FileDownloadTaskDTO:
        task = self.download_task(site_id, task_id)
        if task is None:
            raise FileReferenceNotFound("下载任务不存在")
        if task.status not in {TaskState.PENDING.value, TaskState.STARTING.value, TaskState.RUNNING.value, TaskState.STOPPING.value}:
            raise FileManagementError("下载任务当前不可停止")
        repository = self.task_service.repository(task.site_id) if self.task_service is not None else None
        if repository is not None and self._task_waiting(repository, task.task_id):
            self.task_service.record_external_event(
                task.task_id,
                "cancelled",
                {"message": "排队下载已取消"},
                site_name=task.site_id,
            )
            return self.download_task(task.site_id, task.task_id) or task
        if self.process_adapter is None or not self.process_adapter.cancel_job(task.task_id):
            raise FileManagementError("下载任务当前不可停止")
        return self.download_task(site_id, task.task_id) or task

    def desktop_action(
        self,
        action: str,
        *,
        site_id: str = "",
        device_id: str = "",
        local_entry_id: str = "",
        task_id: str = "",
    ) -> FileDesktopActionDTO:
        site = self._site_id(site_id)
        selected = str(action or "").strip()
        if selected == "winscp":
            if not str(device_id or "").strip():
                raise FileManagementError("WinSCP 操作缺少设备标识")
            device = self._resolve_device(site, device_id)
            command = FileDesktopActionCommand(
                action=selected,
                site_id=site,
                device_id=str(device.device_uuid or device.id or ""),
            )
        if selected in {"open_result", "open_result_dir"}:
            path, _name = self.open_download(site, task_id)
            command = FileDesktopActionCommand(
                action=selected,
                site_id=site,
                path=path if selected == "open_result" else path.parent,
            )
        elif selected == "open_local":
            entry = self._local_entry(site, local_entry_id)
            command = FileDesktopActionCommand(action=selected, site_id=site, path=entry.path)
        elif selected != "winscp":
            raise FileManagementError("不支持的桌面动作")
        expires_at = datetime.now(UTC) + timedelta(seconds=60)
        action_ref = f"fda1_{uuid4().hex}"
        with self._desktop_actions_lock:
            now = datetime.now(UTC)
            self._desktop_actions = {
                key: value
                for key, value in self._desktop_actions.items()
                if value.expires_at >= now
            }
            self._desktop_actions[action_ref] = _DesktopAction(site, expires_at, command)
        return FileDesktopActionDTO(
            action=selected,
            action_ref=action_ref,
            expires_at=expires_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
            accepted=True,
            integration_required=False,
            message="桌面动作已登记。",
        )

    def consume_desktop_action(self, action_ref: str) -> FileDesktopActionCommand:
        """Native Bridge 唯一可接入点：动作一次性消费，且没有密码或任意 argv。"""
        value = str(action_ref or "")
        if not DESKTOP_ACTION_RE.fullmatch(value):
            raise FileReferenceNotFound("桌面动作引用不存在")
        with self._desktop_actions_lock:
            action = self._desktop_actions.pop(value, None)
        if action is None or action.expires_at < datetime.now(UTC):
            raise FileReferenceNotFound("桌面动作引用不存在或已过期")
        return action.command

    def execute_desktop_action(self, action_ref: str) -> FileDesktopActionResultDTO:
        command = self.consume_desktop_action(action_ref)
        service = self._desktop_action_service
        if service is None or service.runtime_mode is not RuntimeMode.DESKTOP:
            raise FileManagementError("当前运行模式不允许桌面动作")
        if command.action in {"open_local", "open_result", "open_result_dir"}:
            if command.path is None:
                raise FileManagementError("桌面动作目标不存在")
            expect_directory = command.action == "open_result_dir" or command.path.is_dir()
            try:
                target_path = service.resolve_controlled_path(command.path, expect_directory=expect_directory)
            except DesktopActionResolutionError as exc:
                raise FileManagementError(str(exc)) from exc
            return FileDesktopActionResultDTO(
                action=command.action,
                success=True,
                message="已打开目录。" if expect_directory else "已打开文件。",
                target_path=str(target_path),
            )
        if command.action == "winscp":
            device = self._resolve_device(command.site_id, command.device_id)
            preferred_target = self._connected_target(command.site_id, command.device_id)
            launch_options = {"preferred_target": preferred_target} if preferred_target is not None else {}
            result = launch_winscp(
                device,
                SettingsStore(self.paths),
                include_password=True,
                **launch_options,
            )
            if not result.success:
                raise FileManagementError(result.message)
            return FileDesktopActionResultDTO(
                action=command.action,
                success=True,
                message=result.message,
            )
        raise FileManagementError("不支持的桌面动作")

    def _connected_target(self, site: str, device_id: str):
        with self._sessions_lock:
            sessions = tuple(self._sessions.values())
        for session in sessions:
            if session.site_id == site and session.device_id == str(device_id):
                target = getattr(session.transfer, "successful_target", None)
                if target is not None:
                    return target
        return None

    def _winscp_capability(self) -> FileManagementCapabilityDTO:
        service = self._desktop_action_service
        if service is None or service.runtime_mode is not RuntimeMode.DESKTOP:
            return FileManagementCapabilityDTO(available=False, message=WINSCP_INTEGRATION_MESSAGE)
        available = bool(find_winscp_exe(SettingsStore(self.paths)))
        return FileManagementCapabilityDTO(
            available=available,
            message="" if available else "未找到 WinSCP，请先在系统设置中配置 WinSCP.exe。",
        )

    def list_files(
        self,
        site_id: str = "",
        *,
        category: str = "",
        search: str = "",
        limit: int = 200,
    ) -> ManagedFilePageDTO:
        site = self._site_id(site_id)
        selected_category = str(category or "").strip().casefold()
        if selected_category and selected_category not in FILE_CATEGORIES:
            raise FileManagementError("文件分类无效")
        query = str(search or "").strip().casefold()
        rows: list[ManagedFileDTO] = []
        for path in self._iter_files(site):
            resolved = self._resolve_candidate(site, path)
            if resolved is None or (selected_category and resolved.category != selected_category):
                continue
            if query and query not in f"{path.name} {resolved.relative_path}".casefold():
                continue
            try:
                stat_result = path.stat()
            except OSError:
                continue
            rows.append(
                ManagedFileDTO(
                    file_ref=resolved.file_ref,
                    site_id=site,
                    category=resolved.category,
                    name=path.name,
                    relative_path=resolved.relative_path,
                    size_bytes=int(stat_result.st_size),
                    modified_at=datetime.fromtimestamp(stat_result.st_mtime).isoformat(timespec="seconds"),
                )
            )
        rows.sort(key=lambda item: (item.modified_at or "", item.relative_path.casefold()), reverse=True)
        return ManagedFilePageDTO(site_id=site, category=selected_category, items=rows[: max(1, min(int(limit), 500))], total=len(rows))

    def resolve_ref(self, site_id: str, file_ref: str) -> ResolvedManagedFile:
        site = self._site_id(site_id)
        value = str(file_ref or "").strip()
        if not FILE_REF_RE.fullmatch(value):
            raise FileReferenceNotFound("文件引用不存在")
        for path in self._iter_files(site):
            resolved = self._resolve_candidate(site, path)
            if resolved is not None and resolved.file_ref == value:
                return resolved
        raise FileReferenceNotFound("文件不存在或已不可用")

    def submit_download(
        self,
        site_id: str,
        file_ref: str = "",
        *,
        connection_id: str = "",
        remote_entry_id: str = "",
        local_directory_id: str = "",
        batch_id: str = "",
    ) -> FileDownloadTaskDTO:
        if self.task_service is None or self.process_adapter is None:
            raise RuntimeError("文件下载任务宿主未接线")
        site = self._site_id(site_id)
        if file_ref and (connection_id or remote_entry_id):
            raise FileManagementError("本地文件引用与远程文件引用不能同时提交")
        if str(file_ref or "").strip():
            resolved = self.resolve_ref(site, file_ref)
            descriptor: dict[str, object] = {
                "version": 1,
                "source_kind": "managed_file",
                "batch_id": str(batch_id or f"fb1_{uuid4().hex}"),
                "file_ref": resolved.file_ref,
                "name": resolved.path.name,
            }
        else:
            session = self._session(site, connection_id)
            with session.lock:
                self._assert_session_active(session)
                entry = session.entries.get(str(remote_entry_id or ""))
                if entry is None or not REMOTE_ENTRY_ID_RE.fullmatch(str(remote_entry_id or "")):
                    raise FileReferenceNotFound("远程文件引用不存在或不属于当前设备会话")
                if entry.remote_file.is_dir:
                    raise FileManagementError("不能下载远程目录")
                target, target_kind = self._download_target(site, session.device, entry.remote_file, local_directory_id)
                descriptor = {
                    "version": 1,
                    "source_kind": "remote",
                    "batch_id": str(batch_id or f"fb1_{uuid4().hex}"),
                    "device_id": session.device_id,
                    "device_name": str(session.device.name or session.device.system_name or session.device.primary_address),
                    "remote_entry_id": str(remote_entry_id),
                    "remote_path": entry.remote_file.remote_path,
                    "remote_name": entry.remote_file.name,
                    "remote_size": int(entry.remote_file.size or 0),
                    "remote_modified_at": entry.remote_file.modified_time or "",
                    "remote_category": entry.remote_file.category,
                    "target_relative_path": target.relative_to(self.paths.site_dir(site).resolve()).as_posix(),
                    "target_kind": target_kind,
                    "mesh_auto_import": target_kind == "mr_raw" and self._mesh_auto_import_enabled,
                }
        return self._start_download(site, descriptor)

    def submit_download_batch(
        self,
        site_id: str,
        connection_id: str,
        remote_entry_ids: Iterable[str],
        *,
        local_directory_id: str = "",
    ) -> FileDownloadBatchDTO:
        site = self._site_id(site_id)
        values = list(dict.fromkeys(str(value or "") for value in remote_entry_ids))
        if not values or len(values) > 100:
            raise FileManagementError("每个下载批次必须包含 1 到 100 个文件")
        session = self._session(site, connection_id)
        active_keys = self._active_remote_keys(site)
        batch_id = f"fb1_{uuid4().hex}"
        tasks: list[FileDownloadTaskDTO] = []
        failures: list[str] = []
        for entry_id in values:
            with session.lock:
                entry = session.entries.get(entry_id)
                key = (session.device_id, entry.remote_file.remote_path) if entry is not None else ("", "")
                name = entry.remote_file.name if entry is not None else entry_id
            if key in active_keys:
                failures.append(f"{name}：已有活动下载任务")
                continue
            try:
                task = self.submit_download(
                    site,
                    connection_id=connection_id,
                    remote_entry_id=entry_id,
                    local_directory_id=local_directory_id,
                    batch_id=batch_id,
                )
            except (FileManagementError, RuntimeError) as exc:
                failures.append(f"{name}：{exc}")
                continue
            tasks.append(task)
            active_keys.add(key)
        return FileDownloadBatchDTO(batch_id=batch_id, tasks=tasks, failures=failures)

    def _start_download(self, site: str, descriptor: dict[str, object]) -> FileDownloadTaskDTO:
        if self.task_service is None or self.process_adapter is None:
            raise RuntimeError("文件下载任务宿主未接线")
        with self._queue_lock:
            self._queue_sites.add(site)
        task_id = uuid4().hex
        params = self._job_params(site, descriptor)
        job = BackgroundJob(job_id=task_id, task_type="file_management_download", params=params)
        protected_descriptor = _protect_descriptor(descriptor, site, task_id)
        with self._queue_lock:
            repository = self.task_service.repository(site)
            active = [snapshot for snapshot in repository.list(statuses=ACTIVE_DOWNLOAD_STATES, limit=1000) if self._is_download_snapshot(snapshot)]
            if active:
                self._persist_waiting_download(site, task_id, params, protected_descriptor)
            else:
                try:
                    self.process_adapter.start_job(job)
                except Exception as exc:
                    raise RuntimeError("文件下载任务启动失败") from exc
                self._record_task_metadata(
                    site,
                    task_id,
                    DOWNLOAD_DESCRIPTOR_EVENT,
                    {"protected_descriptor": protected_descriptor},
                )
        return self.download_task(site, task_id) or FileDownloadTaskDTO(
            task_id=task_id,
            site_id=site,
            status=TaskState.PENDING.value,
            progress=0,
            message="已创建文件下载任务",
        )

    def _persist_waiting_download(
        self,
        site: str,
        task_id: str,
        params: dict[str, object],
        protected_descriptor: str,
    ) -> None:
        if self.task_service is None:
            raise RuntimeError("文件下载任务宿主未接线")
        now = utc_now_iso()
        snapshot = TaskSnapshot(
            task_id=task_id,
            task_type="file_management_download",
            task_name=str(params.get("task_name") or "文件下载"),
            status=TaskState.PENDING,
            created_time=now,
            updated_time=now,
            owner="web_file_management",
            device=str(params.get("device_name") or ""),
            source="local",
            site_name=site,
            owner_pid=0,
            message="等待前序文件下载完成",
        )
        repository = self.task_service.repository(site)
        repository.record(
            snapshot,
            TaskEvent(
                event_id=uuid4().hex,
                task_id=task_id,
                type=DOWNLOAD_DESCRIPTOR_EVENT,
                time=now,
                source="file_management",
                payload={"protected_descriptor": protected_descriptor},
            ),
        )
        repository.record(
            snapshot,
            TaskEvent(
                event_id=uuid4().hex,
                task_id=task_id,
                type=DOWNLOAD_WAITING_EVENT,
                time=now,
                source="file_management",
                payload={"waiting": True, "message": "等待前序文件下载完成"},
            ),
        )

    def retry_download(self, site_id: str, task_id: str) -> FileDownloadTaskDTO:
        site = self._site_id(site_id)
        task = self.download_task(site, task_id)
        if task is None:
            raise FileReferenceNotFound("下载任务不存在")
        mesh_import_failed = task.result is not None and task.result.mesh_import_status == "failed"
        if mesh_import_failed and task.result is not None and task.result.target_kind == "mr_raw" and task.result.relative_path:
            return self.retry_mesh_import(site, task_id)
        if task.status not in {TaskState.FAILED.value, TaskState.CANCELLED.value} and not mesh_import_failed:
            raise FileManagementError("只有失败、已取消或 MESH 导入失败的下载可以重试")
        descriptor = self._task_descriptor(self.task_service.repository(site), task_id) if self.task_service else None
        if descriptor is None:
            raise FileManagementError("旧下载任务没有可恢复的下载描述")
        retry = dict(descriptor)
        retry["batch_id"] = str(retry.get("batch_id") or f"fb1_{uuid4().hex}")
        if retry.get("source_kind") == "remote":
            device = self._resolve_device(site, str(retry.get("device_id") or ""))
            remote_file = self._remote_file_from_descriptor(retry)
            target, target_kind = self._download_target(site, device, remote_file, "")
            retry["target_relative_path"] = target.relative_to(self.paths.site_dir(site).resolve()).as_posix()
            retry["target_kind"] = target_kind
        return self._start_download(site, retry)

    def retry_mesh_import(self, site_id: str, task_id: str) -> FileDownloadTaskDTO:
        site = self._site_id(site_id)
        task = self.download_task(site, task_id)
        if task is None:
            raise FileReferenceNotFound("下载任务不存在")
        if task.status != TaskState.COMPLETED.value or task.result is None:
            raise FileManagementError("只有已完成下载的 MESH 原始日志可以提交分析")
        if task.result.target_kind != "mr_raw" or not task.result.relative_path:
            raise FileManagementError("该下载结果不是受管 MESH 原始日志")
        descriptor = self._task_descriptor(self.task_service.repository(site), task_id) if self.task_service else None
        if descriptor is None:
            raise FileManagementError("旧下载任务没有可恢复的下载描述")
        retry = dict(descriptor)
        retry.update(
            {
                "batch_id": str(retry.get("batch_id") or f"fb1_{uuid4().hex}"),
                "target_relative_path": task.result.relative_path,
                "target_kind": "mr_raw",
                "mesh_auto_import": True,
                "mesh_retry_only": True,
                "expected_sha256": task.result.sha256,
            }
        )
        return self._start_download(site, retry)

    def clear_downloads(self, site_id: str, statuses: Iterable[str]) -> FileDownloadClearDTO:
        if self.task_service is None:
            return FileDownloadClearDTO(cleared_count=0)
        site = self._site_id(site_id)
        requested = {str(value or "").upper() for value in statuses}
        allowed = {TaskState.COMPLETED.value, TaskState.FAILED.value}
        if not requested or not requested <= allowed:
            raise FileManagementError("只能清理已完成或失败的下载记录")
        repository = self.task_service.repository(site)
        cleared = 0
        query_statuses = {TaskState(value) for value in requested}
        if TaskState.FAILED.value in requested:
            query_statuses.add(TaskState.COMPLETED)
        for snapshot in repository.list(statuses=query_statuses, limit=1000):
            if not self._is_download_snapshot(snapshot) or self._task_hidden(repository, snapshot.task_id):
                continue
            if snapshot.status is TaskState.COMPLETED:
                if TaskState.COMPLETED.value in requested:
                    pass
                elif str((snapshot.result or {}).get("mesh_import_status") or "") != "failed":
                    continue
            self._record_task_metadata(site, snapshot.task_id, DOWNLOAD_HIDDEN_EVENT, {"hidden": True})
            cleared += 1
        return FileDownloadClearDTO(cleared_count=cleared)

    def download_task(self, site_id: str, task_id: str) -> FileDownloadTaskDTO | None:
        if self.task_service is None:
            return None
        site = self._site_id(site_id)
        snapshot = self.task_service.repository(site).get(str(task_id or ""))
        if (
            snapshot is None
            or snapshot.task_type != "file_management_download"
            or snapshot.owner != "web_file_management"
            or snapshot.source != "local"
        ):
            return None
        return self._download_task_from_snapshot(site, snapshot)

    def _download_task_from_snapshot(
        self,
        site: str,
        snapshot,
        *,
        metadata: dict[str, object] | None = None,
    ) -> FileDownloadTaskDTO:
        repository = self.task_service.repository(site) if self.task_service is not None else None
        descriptor = dict(metadata.get("descriptor") or {}) if metadata is not None else (
            self._task_descriptor(repository, snapshot.task_id) if repository is not None else {}
        )
        descriptor = descriptor or {}
        result = dict(snapshot.result or {})
        result_dto = None
        if snapshot.status is TaskState.COMPLETED and result.get("name"):
            file_ref = str(result.get("download_ref") or "")
            artifact_id = str(result.get("artifact_id") or "")
            device_file_ref = str(result.get("device_file_ref") or "")
            if FILE_REF_RE.fullmatch(file_ref) or ARTIFACT_ID_RE.fullmatch(artifact_id) or DEVICE_FILE_REF_RE.fullmatch(device_file_ref):
                try:
                    result_dto = FileDownloadResultDTO(
                        result_kind=str(result.get("result_kind") or ("managed_file" if file_ref else "device_file")),
                        file_ref=file_ref,
                        device_file_ref=device_file_ref,
                        name=str(result["name"]),
                        size_bytes=max(0, int(result.get("size_bytes") or 0)),
                        artifact_id=artifact_id,
                        relative_path=str(result.get("relative_path") or ""),
                        sha256=str(result.get("sha256") or ""),
                        device_id=str(result.get("device_id") or ""),
                        remote_entry_id=str(result.get("remote_entry_id") or ""),
                        target_kind=str(result.get("target_kind") or descriptor.get("target_kind") or ""),
                        mesh_import_status=str(result.get("mesh_import_status") or ""),
                        mesh_imported_count=max(0, int(result.get("mesh_imported_count") or 0)),
                        mesh_duplicate_count=max(0, int(result.get("mesh_duplicate_count") or 0)),
                        mesh_parsed_record_count=max(0, int(result.get("mesh_parsed_record_count") or 0)),
                        mesh_import_error_code=str(result.get("mesh_import_error_code") or ""),
                        mesh_import_error=str(result.get("mesh_import_error") or ""),
                        mesh_session_id=str(result.get("mesh_session_id") or ""),
                        mesh_source_file_id=(
                            int(result["mesh_source_file_id"])
                            if result.get("mesh_source_file_id") not in (None, "")
                            else None
                        ),
                    )
                except (TypeError, ValueError):
                    result_dto = None
        message = str(snapshot.message or "")
        if snapshot.status is TaskState.FAILED:
            message = "文件下载失败"
        elif snapshot.status is TaskState.CANCELLED:
            message = "文件下载已取消"
        elif result_dto is not None and result_dto.mesh_import_status == "rebuild_required":
            message = "文件下载完成，MESH 分析数据库正在自动修复"
        elif result_dto is not None and result_dto.mesh_import_status == "repair_failed":
            message = "文件下载完成，MESH 分析数据库自动修复失败"
        elif result_dto is not None and result_dto.mesh_import_status == "failed":
            message = "文件下载完成，MESH 自动导入失败"
        total = max(0, int(snapshot.total or descriptor.get("remote_size") or 0))
        current = max(0, int(snapshot.current or (total if snapshot.status is TaskState.COMPLETED else 0)))
        speed = self._average_speed(snapshot.started_time, snapshot.finished_time or snapshot.updated_time, current)
        local_path = ""
        target_relative_path = str(descriptor.get("target_relative_path") or "")
        target_kind = str(descriptor.get("target_kind") or "device_file")
        if target_relative_path:
            try:
                local_path = str(self._safe_download_target(site, target_relative_path, target_kind))
            except FileManagementError:
                local_path = ""
        mesh_import_failed = result_dto is not None and result_dto.mesh_import_status in {"failed", "repair_failed"}
        retryable = (
            snapshot.status in {TaskState.FAILED, TaskState.CANCELLED} or mesh_import_failed
        ) and bool(descriptor)
        return FileDownloadTaskDTO(
            task_id=snapshot.task_id,
            site_id=site,
            status=snapshot.status.value,
            progress=max(0, min(int(snapshot.progress or 0), 100)),
            stage=str(snapshot.stage or ""),
            message=message,
            batch_id=str(descriptor.get("batch_id") or ""),
            source_kind=str(descriptor.get("source_kind") or ""),
            device_name=str(descriptor.get("device_name") or ""),
            remote_name=str(descriptor.get("remote_name") or descriptor.get("name") or ""),
            remote_path=str(descriptor.get("remote_path") or ""),
            local_path=local_path,
            downloaded_bytes=current,
            total_bytes=total,
            speed_bytes_per_second=speed,
            created_at=str(snapshot.created_time or ""),
            updated_at=str(snapshot.updated_time or ""),
            retryable=retryable,
            retry_reason="" if retryable else "当前状态不可重试",
            result=result_dto,
        )

    def open_download(self, site_id: str, task_id: str) -> tuple[Path, str]:
        task = self.download_task(site_id, task_id)
        if task is None:
            raise FileReferenceNotFound("下载任务不存在")
        if task.status != TaskState.COMPLETED.value or task.result is None:
            raise FileManagementError("文件下载任务尚未完成")
        if task.result.file_ref:
            resolved = self.resolve_ref(task.site_id, task.result.file_ref)
            name = _download_display_name(task.result.name)
            if not name:
                raise FileManagementError("下载文件显示名无效")
            return resolved.path, name
        descriptor = self._task_descriptor(self.task_service.repository(task.site_id), task.task_id) if self.task_service else None
        relative_path = str((descriptor or {}).get("target_relative_path") or task.result.relative_path)
        target_kind = str((descriptor or {}).get("target_kind") or task.result.target_kind)
        if not relative_path:
            raise FileReferenceNotFound("下载结果文件不存在")
        path = self._safe_download_target(task.site_id, relative_path, target_kind)
        if not path.is_file():
            raise FileReferenceNotFound("下载结果文件不存在")
        if task.result.sha256 and file_sha256(path) != task.result.sha256:
            raise FileManagementError("下载结果校验失败")
        if task.result.device_file_ref:
            expected = self._device_file_ref(task.task_id, relative_path, task.result.sha256)
            if task.result.device_file_ref != expected:
                raise FileReferenceNotFound("设备文件结果引用无效")
        elif task.result.artifact_id:
            expected_artifact = self._artifact_id(task.task_id, relative_path, task.result.sha256)
            if task.result.artifact_id != expected_artifact:
                raise FileReferenceNotFound("旧版下载结果 Artifact 引用无效")
        else:
            raise FileReferenceNotFound("下载结果引用无效")
        name = _download_display_name(task.result.name)
        if not name:
            raise FileManagementError("下载文件显示名无效")
        return path, name

    def validate_for_download(self, context: JobContext) -> dict[str, object]:
        site = self._site_id(str(context.params.get("site_name") or ""))
        if bool(context.params.get("mesh_retry_only")):
            return self._import_existing_mesh(context, site)
        file_ref = str(context.params.get("file_ref") or "")
        if file_ref:
            source = self.resolve_ref(site, file_ref)
            context.check_cancelled()
            context.progress("file_validate", 1, 1, f"已校验 {source.path.name}")
            display_name = _download_display_name(source.path.name)
            if not display_name:
                raise FileManagementError("下载文件显示名无效")
            return {
                "download_ref": source.file_ref,
                "name": display_name,
                "size_bytes": source.path.stat().st_size,
            }
        return self._download_remote(context, site)

    def _import_existing_mesh(self, context: JobContext, site: str) -> dict[str, object]:
        relative = str(context.params.get("target_relative_path") or "")
        target = self._safe_download_target(site, relative, "mr_raw")
        if not target.is_file() or target.is_symlink():
            raise FileReferenceNotFound("已下载的 MESH 原始日志不存在")
        expected_sha256 = str(context.params.get("expected_sha256") or "")
        digest = file_sha256(target)
        if expected_sha256 and digest != expected_sha256:
            raise FileManagementError("已下载的 MESH 原始日志校验失败，请重新扫描或重新下载")
        device = self._resolve_device(site, str(context.params.get("device_id") or ""))
        context.progress("mesh_auto_import", 0, 1, "正在重新导入已下载的 MESH 日志")
        mesh_import = self._auto_import_mesh(context, site, device, target, "mr_raw")
        stat = target.stat()
        return {
            "result_kind": "device_file",
            "name": target.name,
            "size_bytes": int(stat.st_size),
            "sha256": digest,
            "relative_path": relative,
            "device_file_ref": self._device_file_ref(context.job_id, relative, digest),
            "device_id": str(context.params.get("device_id") or ""),
            "remote_entry_id": str(context.params.get("remote_entry_id") or ""),
            "target_kind": "mr_raw",
            **mesh_import,
        }

    def _download_remote(self, context: JobContext, site: str) -> dict[str, object]:
        device_id = str(context.params.get("device_id") or "").strip()
        remote_entry_id = str(context.params.get("remote_entry_id") or "").strip()
        remote_path = str(context.params.get("remote_path") or "").strip()
        remote_name = str(context.params.get("remote_name") or "").strip()
        if not device_id or not REMOTE_ENTRY_ID_RE.fullmatch(remote_entry_id):
            raise FileReferenceNotFound("远程文件引用不存在")
        if (
            not remote_path
            or not remote_name
            or remote_name in {".", ".."}
            or Path(remote_name).name != remote_name
            or any(char in remote_name for char in "/\\")
        ):
            raise FileReferenceNotFound("远程文件名或路径无效")
        display_name = _download_display_name(remote_name)
        if not display_name:
            raise FileManagementError("下载文件显示名无效")
        normalized_path = normalize_remote_path(remote_path)
        category = str(context.params.get("remote_category") or "file").strip().casefold()
        if category in {"", "dir"}:
            category = "file"
        if category not in {"bin", "zip", "diag", "meshlog", "file"}:
            raise FileManagementError("远程文件分类无效")
        target_relative_path = str(context.params.get("target_relative_path") or "")
        target_kind = str(context.params.get("target_kind") or "device_file")
        target = self._safe_download_target(site, target_relative_path, target_kind)
        device = self._resolve_device(site, device_id)
        remote_file = RemoteDeviceFile(
            name=remote_name,
            remote_path=normalized_path,
            size=max(0, int(context.params.get("remote_size") or 0)),
            modified_time=str(context.params.get("remote_modified_at") or "") or None,
            category=category,
        )
        transfer = FileTransferService(site, context.paths, strict_host_keys=True)

        class _JobCancelToken:
            def is_cancelled(self) -> bool:
                context.check_cancelled()
                return False

        try:
            root_path = normalize_remote_path(transfer.connect(device))
            if not is_within_remote_root(normalized_path, root_path):
                raise FileReferenceNotFound("远程文件不属于当前设备根目录")
            context.check_cancelled()
            context.progress("file_transfer", 0, remote_file.size or 0, f"正在下载 {remote_file.name}")
            downloaded = transfer.download(
                normalized_path,
                target,
                progress_callback=lambda current, total: context.progress(
                    "file_transfer",
                    current,
                    total,
                    f"正在下载 {remote_file.name}：{current} / {total}",
                ),
                cancel_token=_JobCancelToken(),
            )
            context.check_cancelled()
        finally:
            transfer.disconnect()
        output = Path(downloaded).resolve()
        if output != target.resolve():
            raise FileManagementError("下载器返回了非受控结果路径")
        relative = output.relative_to(context.paths.site_dir(site).resolve()).as_posix()
        size = output.stat().st_size
        digest = file_sha256(output)
        output_name = _download_display_name(output.name)
        if not output_name:
            raise FileManagementError("下载结果文件名无效")
        context.progress("file_verify", 1, 1, f"已校验 {remote_file.name}")
        mesh_import = self._auto_import_mesh(context, site, device, output, target_kind)
        return {
            "result_kind": "device_file",
            "name": output_name,
            "size_bytes": size,
            "sha256": digest,
            "relative_path": relative,
            "device_file_ref": self._device_file_ref(context.job_id, relative, digest),
            "device_id": device_id,
            "remote_entry_id": remote_entry_id,
            "target_kind": target_kind,
            **mesh_import,
        }

    def _auto_import_mesh(
        self,
        context: JobContext,
        site: str,
        device: Device,
        path: Path,
        target_kind: str,
    ) -> dict[str, object]:
        if target_kind != "mr_raw" or not bool(context.params.get("mesh_auto_import")):
            return {}
        try:
            context.check_cancelled()
            profile = MeshStorageService(site, context.paths).ensure_mr_profile_identity_for_device(device)
            context.progress("mesh_auto_import", 0, 1, "正在自动导入 MESH 日志")

            def should_cancel() -> bool:
                context.check_cancelled()
                return False

            def import_downloaded_log():
                return MeshImportService(site, context.paths).import_files(
                    profile,
                    [path],
                    should_cancel=should_cancel,
                    source_type="device_download",
                    source_device_id=str(device.device_uuid or device.id or ""),
                    parse_task_id=context.job_id,
                )

            try:
                result = import_downloaded_log()
            except MeshSchemaRebuildRequired:
                context.progress(
                    "mesh_auto_import_repair",
                    0,
                    1,
                    "检测到 MESH 分析数据库需要升级，正在自动修复",
                )
                try:
                    MeshDerivedDataMaintenanceService(context.paths).repair(
                        site,
                        progress=lambda stage, current, total, message: context.progress(
                            stage,
                            current,
                            total,
                            message,
                        ),
                        should_cancel=should_cancel,
                    )
                    result = import_downloaded_log()
                except Exception as repair_exc:
                    app_logger.log_error(
                        "MESH_DEVICE_DOWNLOAD_REPAIR_FAILED",
                        f"site={site} task={context.job_id} file={path.name} error={type(repair_exc).__name__}",
                    )
                    return {
                        "mesh_import_status": "repair_failed",
                        "mesh_import_error_code": "MESH_DERIVED_DATA_REPAIR_FAILED",
                        "mesh_import_error": "MESH 分析数据库自动修复失败，原始日志已保留，可重试自动修复。",
                    }
            source_results = list(getattr(result, "source_results", []) or [])
            catalog = MeshCatalogRepository(context.paths.mesh_catalog_path(site))
            fingerprint_rows = [
                {
                    "content_sha256": item.get("content_sha256"),
                    "raw_sha256": item.get("raw_sha256"),
                    "mr_id": item.get("profile_id") or profile.mr_id,
                    "source_file_id": item.get("source_id") or item.get("existing_source_id"),
                    "stored_filename": item.get("stored_filename") or item.get("existing_stored_filename"),
                }
                for item in source_results
                if item.get("source_id") or item.get("existing_source_id")
            ]
            if fingerprint_rows:
                catalog.upsert_source_fingerprints(fingerprint_rows)
            catalog.mark_index_pending()
            try:
                MeshCatalogIndexService(context.paths).rebuild_now(site)
            except Exception as exc:
                app_logger.log_warning(
                    "MESH_CATALOG_REFRESH_PENDING",
                    f"site={site} task={context.job_id} error={type(exc).__name__}",
                )
            context.check_cancelled()
            context.progress("mesh_auto_import", 1, 1, "MESH 日志自动导入完成")
            status = "duplicate" if result.duplicate_count and not result.imported_count else "completed"
            source_result = source_results[0] if source_results else {}
            return {
                "mesh_import_status": status,
                "mesh_imported_count": result.imported_count,
                "mesh_duplicate_count": result.duplicate_count,
                "mesh_parsed_record_count": result.parsed_record_count,
                "mesh_session_id": str(
                    source_result.get("session_id") or source_result.get("existing_session_id") or ""
                ),
                "mesh_source_file_id": (
                    source_result.get("source_id") or source_result.get("existing_source_id")
                ),
            }
        except Exception as exc:
            from netconsole.services.job_center.job_context import BackgroundTaskCancelled

            if isinstance(exc, BackgroundTaskCancelled):
                raise
            app_logger.log_error(
                "MESH_DEVICE_DOWNLOAD_IMPORT_FAILED",
                f"site={site} task={context.job_id} file={path.name} error={type(exc).__name__}: {exc}",
            )
            return {
                "mesh_import_status": "failed",
                "mesh_import_error": "MESH 日志格式不受支持或解析失败",
            }

    def _resolve_device(self, site: str, device_id: str) -> Device:
        value = str(device_id or "").strip()
        if self._device_resolver is not None:
            device = self._device_resolver(site, value)
            if device is None:
                raise FileReferenceNotFound("设备不存在")
            return device
        if not self.paths.site_db_path(site).is_file():
            raise FileReferenceNotFound("设备不存在")
        repository = DeviceRepository(Database(self.paths.site_db_path(site)))
        device = repository.get_by_uuid(value)
        if device is None and value.isdigit():
            try:
                device = repository.get(int(value))
            except KeyError:
                device = None
        if device is None:
            raise FileReferenceNotFound("设备不存在")
        return device

    def _session(self, site_id: str, connection_id: str) -> _RemoteSession:
        site = self._site_id(site_id)
        value = str(connection_id or "").strip()
        if not CONNECTION_ID_RE.fullmatch(value):
            raise FileReferenceNotFound("设备文件连接不存在")
        with self._sessions_lock:
            session = self._sessions.get(value)
        if session is None or session.site_id != site:
            raise FileReferenceNotFound("设备文件连接不存在或不属于当前局点")
        return session

    def _assert_session_active(self, session: _RemoteSession) -> None:
        if self._transfer_is_connected(session.transfer):
            return
        self._close_session(session)
        raise DeviceFileSftpError(
            "DEVICE_FILE_SESSION_DISCONNECTED",
            "设备文件会话已断开，请重新连接。",
        )

    @staticmethod
    def _transfer_is_connected(transfer: FileTransferService) -> bool:
        check = getattr(transfer, "is_connected", None)
        if not callable(check):
            return True
        try:
            return bool(check())
        except Exception:
            return False

    @staticmethod
    def _is_session_failure(exc: BaseException) -> bool:
        name = exc.__class__.__name__.casefold()
        message = str(exc or "").casefold()
        return (
            name in {"sshexception", "channelexception", "eoferror"}
            or "channel closed" in message
            or "socket is closed" in message
            or "session is not active" in message
            or "server connection dropped" in message
            or "eof during negotiation" in message
        )

    def _close_device_sessions(self, site: str, device_id: str) -> None:
        with self._sessions_lock:
            sessions = tuple(
                session
                for session in self._sessions.values()
                if session.site_id == site and session.device_id == device_id
            )
            for session in sessions:
                self._sessions.pop(session.connection_id, None)
        for session in sessions:
            self._close_session(session, remove=False)

    def _register_session(self, session: _RemoteSession) -> None:
        with self._sessions_lock:
            stale = tuple(
                existing
                for existing in self._sessions.values()
                if existing.site_id == session.site_id and existing.device_id == session.device_id
            )
            for existing in stale:
                self._sessions.pop(existing.connection_id, None)
            self._sessions[session.connection_id] = session
        for existing in stale:
            self._close_session(existing, remove=False)

    def _close_session(self, session: _RemoteSession, *, remove: bool = True) -> None:
        if remove:
            with self._sessions_lock:
                self._sessions.pop(session.connection_id, None)
        try:
            session.transfer.disconnect()
        except Exception:
            pass

    @staticmethod
    def _connection_dto(session: _RemoteSession, message: str, *, status: str = "CONNECTED") -> FileConnectionDTO:
        current = session.entries.get(session.current_entry_id)
        target = getattr(session.transfer, "successful_target", None)
        tunnel = getattr(target, "tunnel", None)
        return FileConnectionDTO(
            connection_id=session.connection_id,
            device_id=session.device_id,
            device_name=str(session.device.name or session.device.system_name or ""),
            status=status,
            root_entry_id=session.root_entry_id,
            current_entry_id=session.current_entry_id,
            current_label="根目录" if current is None or session.current_entry_id == session.root_entry_id else current.remote_file.name,
            message=message,
            connection_method=str(getattr(target, "method", "") or ""),
            target_role=str(getattr(target, "target_role", "") or ""),
            target_host=str(getattr(target, "host", "") or ""),
            target_port=int(getattr(target, "port", 0) or 0),
            via_tunnel=bool(getattr(target, "via_tunnel", False)),
            tunnel_label=str(getattr(target, "tunnel_label", "") or ""),
            jump_host=str(getattr(tunnel, "host", "") or ""),
            jump_port=int(getattr(tunnel, "port", 0) or 0),
            attempts=list(
                getattr(session.transfer, "attempt_summaries", ()) or ()
            ),
        )

    @staticmethod
    def _new_remote_entry_id() -> str:
        return f"fe1_{uuid4().hex}"

    def _local_root(self, site: str, *, device_id: str = "") -> Path:
        if str(device_id or "").strip():
            try:
                profile = self._existing_vehicle_mr_profile(site, self._resolve_device(site, device_id))
            except FileManagementError:
                profile = None
            if profile is not None:
                return self.paths.mesh_mr_raw_dir(site, profile.safe_folder_name).resolve()
        return self.paths.file_downloads_root(site).resolve()

    def _default_local_path(self, site: str, device_id: str) -> Path:
        device = self._resolve_device(site, device_id)
        profile = self._existing_vehicle_mr_profile(site, device)
        if profile is not None:
            return self.paths.mesh_mr_raw_dir(site, profile.safe_folder_name).resolve()
        return self.paths.device_file_download_dir(
            site,
            safe_device_name(device.name or device.system_name or "device"),
        ).resolve()

    def _remember_local_entry(self, site: str, root: Path, path: Path) -> str:
        resolved_root = root.resolve()
        resolved = path.resolve()
        self._assert_within(resolved, resolved_root, "本地文件超出受控目录")
        key = (site, str(resolved_root), str(resolved))
        with self._local_entries_lock:
            entry_id = self._local_entry_ids.get(key)
            if entry_id is None:
                entry_id = f"fl1_{uuid4().hex}"
                self._local_entry_ids[key] = entry_id
                self._local_entries[entry_id] = _LocalEntry(site, resolved_root, resolved)
        return entry_id

    def _local_entry(self, site: str, entry_id: str) -> _LocalEntry:
        value = str(entry_id or "")
        if not LOCAL_ENTRY_ID_RE.fullmatch(value):
            raise FileReferenceNotFound("本地文件引用不存在")
        with self._local_entries_lock:
            entry = self._local_entries.get(value)
        if entry is None or entry.site_id != site:
            raise FileReferenceNotFound("本地文件引用不存在或不属于当前局点")
        try:
            resolved = entry.path.resolve(strict=True)
        except OSError as exc:
            raise FileReferenceNotFound("本地文件已不存在") from exc
        if entry.path.is_symlink():
            raise FileReferenceNotFound("符号链接不允许进入受控文件浏览")
        self._assert_within(resolved, entry.root, "本地文件超出受控目录")
        return _LocalEntry(entry.site_id, entry.root, resolved)

    @staticmethod
    def _assert_within(path: Path, root: Path, message: str) -> None:
        try:
            path.resolve().relative_to(root.resolve())
        except ValueError as exc:
            raise FileReferenceNotFound(message) from exc

    def _download_target(
        self,
        site: str,
        device: Device,
        remote_file: RemoteDeviceFile,
        local_directory_id: str,
    ) -> tuple[Path, str]:
        profile = self._vehicle_mr_profile(site, device) if is_mesh_log_file(remote_file.name) else None
        if profile is not None:
            directory = self.paths.mesh_mr_raw_dir(site, profile.safe_folder_name).resolve()
            target_kind = "mr_raw"
        elif local_directory_id:
            local = self._local_entry(site, local_directory_id)
            if not local.path.is_dir():
                raise FileReferenceNotFound("本地下载目标不是目录")
            self._assert_within(local.path, self.paths.file_downloads_root(site), "本地下载目标超出下载目录")
            directory = local.path
            target_kind = "device_file"
        else:
            directory = self.paths.device_file_download_dir(
                site,
                safe_device_name(device.name or device.system_name or "device"),
            ).resolve()
            target_kind = "device_file"
        directory.mkdir(parents=True, exist_ok=True)
        name = _download_display_name(
            resolve_local_download_name(
                remote_file,
                str(device.name or device.system_name or "device"),
            )
        )
        if not name:
            raise FileManagementError("远程文件名不能转换为安全的本地文件名")
        return self._reserve_target(directory / name), target_kind

    def _reserve_target(self, target: Path) -> Path:
        with self._target_lock:
            candidate = auto_rename_path(target)
            suffix = "".join(target.suffixes)
            stem = target.name[: -len(suffix)] if suffix else target.name
            index = 1
            while str(candidate.resolve()) in self._reserved_targets:
                candidate = target.with_name(f"{stem}_{index}{suffix}")
                index += 1
            self._reserved_targets.add(str(candidate.resolve()))
            return candidate

    def _vehicle_mr_profile(self, site: str, device: Device) -> MeshMrProfile | None:
        """仅以精确设备分组授权 MESH raw 路由，并确保 Profile 与设备身份关联。"""

        if device.id is None or device.group_id is None or not self.paths.site_db_path(site).is_file():
            return None
        database = Database(self.paths.site_db_path(site))
        try:
            group = DeviceGroupRepository(database, site).get(int(device.group_id))
        except (KeyError, TypeError, ValueError):
            return None
        if str(group.name or "").strip() != "车载-MR":
            return None
        return MeshStorageService(site, self.paths).ensure_mr_profile_identity_for_device(device)

    def _existing_vehicle_mr_profile(self, site: str, device: Device) -> MeshMrProfile | None:
        """本地浏览只复用已存在的 MR Profile，避免只读目录请求创建业务身份。"""

        if device.id is None or device.group_id is None or not self.paths.site_db_path(site).is_file():
            return None
        database = Database(self.paths.site_db_path(site))
        try:
            group = DeviceGroupRepository(database, site).get(int(device.group_id))
        except (KeyError, TypeError, ValueError):
            return None
        if str(group.name or "").strip() != "车载-MR":
            return None
        catalog = MeshStorageService(site, self.paths).catalog
        device_uuid = str(device.device_uuid or "").strip()
        return catalog.get_by_linked_device_id(int(device.id)) or catalog.get_by_linked_device_uuid(device_uuid)

    @staticmethod
    def _remote_file_from_descriptor(descriptor: dict[str, object]) -> RemoteDeviceFile:
        return RemoteDeviceFile(
            name=str(descriptor.get("remote_name") or ""),
            remote_path=str(descriptor.get("remote_path") or ""),
            size=max(0, int(descriptor.get("remote_size") or 0)),
            modified_time=str(descriptor.get("remote_modified_at") or "") or None,
            category=str(descriptor.get("remote_category") or "file"),
        )

    @staticmethod
    def _descriptor_task_name(descriptor: dict[str, object]) -> str:
        if descriptor.get("mesh_retry_only"):
            return f"MESH 日志重新导入 - {descriptor.get('remote_name') or '文件'}"
        if descriptor.get("source_kind") == "remote":
            return f"设备文件下载 - {descriptor.get('remote_name') or '文件'}"
        return f"文件下载 - {descriptor.get('name') or '文件'}"

    def _record_task_metadata(self, site: str, task_id: str, event_type: str, payload: dict[str, object]) -> None:
        if self.task_service is None:
            return
        repository = self.task_service.repository(site)
        snapshot = repository.get(task_id)
        if snapshot is None:
            raise RuntimeError("下载任务状态尚未持久化")
        now = utc_now_iso()
        repository.record(
            snapshot,
            TaskEvent(
                event_id=uuid4().hex,
                task_id=task_id,
                type=event_type,
                time=now,
                source="file_management",
                payload=dict(payload),
            ),
        )

    @staticmethod
    def _task_descriptor(repository, task_id: str) -> dict[str, object] | None:
        if repository is None:
            return None
        snapshot = repository.get(task_id)
        if snapshot is None:
            return None
        descriptor = None
        for event in repository.list_events(task_id, limit=2000):
            if event.get("type") != DOWNLOAD_DESCRIPTOR_EVENT:
                continue
            payload = dict(event.get("payload") or {})
            token = str(payload.get("protected_descriptor") or "")
            if token:
                try:
                    descriptor = _unprotect_descriptor(token, snapshot.site_name, task_id)
                except (OSError, ValueError, RuntimeError):
                    descriptor = None
        return descriptor

    @staticmethod
    def _download_task_metadata(repository, snapshots: Iterable[TaskSnapshot]) -> dict[str, dict[str, object]]:
        selected = list(snapshots)
        by_id = {snapshot.task_id: snapshot for snapshot in selected}
        grouped = repository.list_events_for_tasks(
            by_id,
            event_types={DOWNLOAD_DESCRIPTOR_EVENT, DOWNLOAD_HIDDEN_EVENT, DOWNLOAD_WAITING_EVENT},
        )
        result: dict[str, dict[str, object]] = {}
        for task_id, snapshot in by_id.items():
            descriptor: dict[str, object] | None = None
            hidden = False
            waiting = False
            for event in grouped.get(task_id, []):
                payload = dict(event.get("payload") or {})
                if event.get("type") == DOWNLOAD_DESCRIPTOR_EVENT:
                    token = str(payload.get("protected_descriptor") or "")
                    if token:
                        try:
                            descriptor = _unprotect_descriptor(token, snapshot.site_name, task_id)
                        except (OSError, ValueError, RuntimeError):
                            descriptor = None
                elif event.get("type") == DOWNLOAD_HIDDEN_EVENT:
                    hidden = bool(payload.get("hidden"))
                elif event.get("type") == DOWNLOAD_WAITING_EVENT:
                    waiting = bool(payload.get("waiting"))
            result[task_id] = {"descriptor": descriptor or {}, "hidden": hidden, "waiting": waiting}
        return result

    @staticmethod
    def _task_hidden(repository, task_id: str) -> bool:
        return any(
            event.get("type") == DOWNLOAD_HIDDEN_EVENT and bool(dict(event.get("payload") or {}).get("hidden"))
            for event in repository.list_events(task_id, limit=2000)
        )

    @staticmethod
    def _task_waiting(repository, task_id: str) -> bool:
        waiting = False
        for event in repository.list_events(task_id, limit=2000):
            if event.get("type") == DOWNLOAD_WAITING_EVENT:
                waiting = bool(dict(event.get("payload") or {}).get("waiting"))
        return waiting

    def _run_download_queue(self) -> None:
        while not self._queue_stop.wait(0.5):
            if self.task_service is None or self.process_adapter is None:
                return
            try:
                with self._queue_lock:
                    sites = tuple(self._queue_sites)
                for site in sites:
                    self._dispatch_next_waiting(self._site_id(site))
            except Exception:
                continue

    def _dispatch_next_waiting(self, site: str) -> None:
        if self.task_service is None or self.process_adapter is None:
            return
        with self._queue_lock:
            repository = self.task_service.repository(site)
            active = [
                snapshot
                for snapshot in repository.list(statuses=ACTIVE_DOWNLOAD_STATES, limit=1000)
                if self._is_download_snapshot(snapshot)
            ]
            if any(not self._task_waiting(repository, snapshot.task_id) for snapshot in active):
                return
            waiting = sorted(
                (snapshot for snapshot in active if self._task_waiting(repository, snapshot.task_id)),
                key=lambda snapshot: (snapshot.created_time, snapshot.task_id),
            )
            if not waiting:
                return
            snapshot = waiting[0]
            descriptor = self._task_descriptor(repository, snapshot.task_id)
            if descriptor is None:
                self.task_service.record_external_event(
                    snapshot.task_id,
                    "error",
                    {"message": "下载恢复描述不可用"},
                    site_name=site,
                )
                return
            job = BackgroundJob(
                job_id=snapshot.task_id,
                task_type="file_management_download",
                params=self._job_params(site, descriptor),
            )
            try:
                self.process_adapter.start_job(job)
            except Exception:
                self.task_service.record_external_event(
                    snapshot.task_id,
                    "error",
                    {"message": "文件下载任务恢复启动失败"},
                    site_name=site,
                )
            finally:
                latest = repository.get(snapshot.task_id)
                if latest is not None:
                    repository.record(
                        latest,
                        TaskEvent(
                            event_id=uuid4().hex,
                            task_id=snapshot.task_id,
                            type=DOWNLOAD_WAITING_EVENT,
                            time=utc_now_iso(),
                            source="file_management",
                            payload={"waiting": False},
                        ),
                    )

    def _job_params(self, site: str, descriptor: dict[str, object]) -> dict[str, object]:
        return {
            **descriptor,
            "site_name": site,
            "task_name": self._descriptor_task_name(descriptor),
            "task_source": "local",
            "file_source": descriptor.get("source_kind", ""),
            "owner": "web_file_management",
            "app_root": str(self.paths.app_root),
            "data_root": str(self.paths.data_root),
        }

    def _active_remote_keys(self, site: str) -> set[tuple[str, str]]:
        if self.task_service is None:
            return set()
        repository = self.task_service.repository(site)
        keys: set[tuple[str, str]] = set()
        for snapshot in repository.list(statuses=ACTIVE_DOWNLOAD_STATES, limit=1000):
            if not self._is_download_snapshot(snapshot):
                continue
            descriptor = self._task_descriptor(repository, snapshot.task_id) or {}
            if descriptor.get("source_kind") == "remote":
                keys.add((str(descriptor.get("device_id") or ""), str(descriptor.get("remote_path") or "")))
        return keys

    @staticmethod
    def _average_speed(started: str, finished: str, current: int) -> float:
        if not started or not finished or current <= 0:
            return 0.0
        try:
            start = datetime.fromisoformat(started.replace("Z", "+00:00"))
            end = datetime.fromisoformat(finished.replace("Z", "+00:00"))
            seconds = max(0.0, (end - start).total_seconds())
        except ValueError:
            return 0.0
        return float(current) / seconds if seconds > 0 else 0.0

    def _safe_download_target(self, site: str, relative_path: str, target_kind: str) -> Path:
        resolved = self._safe_site_relative_path(site, relative_path)
        root = self.paths.site_mesh_root(site) if target_kind == "mr_raw" else self.paths.file_downloads_root(site)
        self._assert_within(resolved, root, "下载结果不属于受控目标目录")
        return resolved

    def _cleanup_stale_parts_once(self, site: str) -> None:
        if site in self._parts_cleaned:
            return
        with self._target_lock:
            if site in self._parts_cleaned:
                return
            started = perf_counter()
            scanned = 0
            deleted = 0
            failures = 0
            cutoff = time() - 24 * 60 * 60
            roots = (self.paths.file_downloads_root(site), self.paths.site_mesh_root(site))
            for root in roots:
                if not root.is_dir():
                    continue
                for part in root.rglob("*.part"):
                    if scanned >= 1000:
                        break
                    scanned += 1
                    try:
                        if part.is_symlink() or not part.is_file() or part.stat().st_mtime > cutoff:
                            continue
                        self._assert_within(part, root, "临时文件超出受控清理目录")
                        part.unlink()
                        deleted += 1
                    except (OSError, FileManagementError):
                        failures += 1
                        continue
                if scanned >= 1000:
                    break
            self._parts_cleaned.add(site)
            app_logger.log_info(
                "DEVICE_FILE_PART_CLEANUP_COMPLETED",
                (
                    f"site={site}, scanned={scanned}, deleted={deleted}, failures={failures}, "
                    f"elapsed_ms={int((perf_counter() - started) * 1000)}"
                ),
            )

    def _safe_site_relative_path(self, site: str, relative_path: str, *, under_downloads: bool = False) -> Path:
        value = str(relative_path or "").strip()
        candidate = Path(value)
        if not value or candidate.is_absolute() or any(part == ".." for part in candidate.parts):
            raise FileReferenceNotFound("文件路径无效")
        site_root = self.paths.site_dir(site).resolve()
        resolved = (site_root / candidate).resolve()
        try:
            resolved.relative_to(site_root)
        except ValueError as exc:
            raise FileReferenceNotFound("文件路径超出局点目录") from exc
        if under_downloads:
            downloads_root = self.paths.file_downloads_root(site).resolve()
            try:
                resolved.relative_to(downloads_root)
            except ValueError as exc:
                raise FileReferenceNotFound("文件路径不属于受控下载目录") from exc
        return resolved

    @staticmethod
    def _artifact_id(task_id: str, relative_path: str, sha256: str) -> str:
        digest = hashlib.sha256(f"fa1\0{task_id}\0{relative_path}\0{sha256}".encode("utf-8")).hexdigest()[:32]
        return f"fa1_{digest}"

    @staticmethod
    def _device_file_ref(task_id: str, relative_path: str, sha256: str) -> str:
        digest = hashlib.sha256(f"fd1\0{task_id}\0{relative_path}\0{sha256}".encode("utf-8")).hexdigest()[:32]
        return f"fd1_{digest}"

    @staticmethod
    def _is_download_snapshot(snapshot: TaskSnapshot) -> bool:
        return (
            snapshot.task_type == "file_management_download"
            and snapshot.owner == "web_file_management"
            and snapshot.source == "local"
        )

    def _site_id(self, site_id: str) -> str:
        value = str(site_id or self.current_site_id()).strip()
        try:
            value = SiteManager(self.paths).validate_site_name(value)
        except ValueError as exc:
            raise FileManagementError("局点标识无效") from exc
        if not self.paths.site_dir(value).is_dir():
            raise FileManagementError("局点不存在")
        return value

    def _files_root(self, site_id: str) -> Path:
        return self.paths.site_files_dir(site_id).resolve()

    def _iter_files(self, site_id: str):
        root = self._files_root(site_id)
        if not root.is_dir():
            return
        pending = [root]
        while pending:
            current = pending.pop()
            try:
                entries = list(os.scandir(current))
            except OSError:
                continue
            for entry in entries:
                if entry.is_symlink():
                    continue
                try:
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False):
                        path = Path(entry.path)
                        if self._resolve_candidate(site_id, path) is not None:
                            yield path
                except OSError:
                    continue

    def _resolve_candidate(self, site_id: str, path: Path) -> ResolvedManagedFile | None:
        root = self._files_root(site_id)
        try:
            candidate = path.resolve(strict=True)
            relative = candidate.relative_to(root).as_posix()
        except (OSError, ValueError):
            return None
        if path.is_symlink() or not candidate.is_file():
            return None
        category = classify_file(relative)
        if category is None:
            return None
        return ResolvedManagedFile(self._file_ref(site_id, relative), site_id, candidate, relative, category)

    def _file_ref(self, site_id: str, relative_path: str) -> str:
        digest = hashlib.sha256(f"{site_id}\0{relative_path}".encode("utf-8")).hexdigest()[:32]
        return f"fm1_{digest}"


def _protect_descriptor(descriptor: dict[str, object], site: str, task_id: str) -> str:
    payload = json.dumps(descriptor, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    protected = protect_windows_data(payload, f"file-management\0{site}\0{task_id}".encode("utf-8"))
    return base64.urlsafe_b64encode(protected).decode("ascii")


def _unprotect_descriptor(token: str, site: str, task_id: str) -> dict[str, object]:
    try:
        protected = base64.urlsafe_b64decode(str(token or "").encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise ValueError("下载恢复描述无效") from exc
    payload = unprotect_windows_data(protected, f"file-management\0{site}\0{task_id}".encode("utf-8"))
    value = json.loads(payload.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("下载恢复描述无效")
    return {str(key): item for key, item in value.items()}


def is_mesh_log_file(filename: str) -> bool:
    basename = Path(str(filename or "")).name
    return basename.casefold() in {"meshlog.log", "meshlog.log.gz"} or MESH_HISTORY_LOG_PATTERN.fullmatch(basename) is not None


def resolve_local_download_name(remote_file: RemoteDeviceFile, device_name: str = "", today: date | None = None) -> str:
    basename = Path(str(remote_file.name or "")).name
    safe_name = safe_device_name(device_name or "device")
    if MESH_HISTORY_LOG_PATTERN.fullmatch(basename):
        return f"{safe_name}-{basename}"
    mesh_name = basename.casefold()
    if mesh_name not in {"meshlog.log", "meshlog.log.gz"}:
        return basename
    resolved_date = _meshlog_modified_date(remote_file.modified_time) or today or date.today()
    suffix = "meshlog.log.gz" if mesh_name.endswith(".gz") else "meshlog.log"
    return f"{safe_name}-{resolved_date:%Y_%m_%d}-{suffix}"


def _meshlog_modified_date(value: object) -> date | None:
    text = str(value or "").strip()
    if not text or text.startswith("1970-01-01"):
        return None
    for fmt, length in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d", 10)):
        try:
            return datetime.strptime(text[:length], fmt).date()
        except ValueError:
            continue
    return None


def classify_file(relative_path: str) -> str | None:
    parts = {part.casefold() for part in Path(relative_path).parts}
    name = Path(relative_path).name.casefold()
    if parts & {"parsed", "cache", "tmp", "runtime"}:
        return None
    if name.endswith((".sqlite", ".sqlite3", ".db", "-wal", "-shm", "-journal")):
        return None
    if name.endswith(PACKAGE_SUFFIXES):
        return "package"
    suffix = Path(relative_path).suffix.casefold()
    if "raw" in parts and suffix in RAW_SUFFIXES:
        return "raw"
    if parts & {"outputs", "reports", "artifacts", "view"} and suffix in ARTIFACT_SUFFIXES:
        return "artifact"
    if "online_mr" in parts and "sessions" in parts and suffix in SESSION_SUFFIXES:
        return "session"
    return None


def _download_display_name(value: object) -> str:
    candidate = str(value or "").strip()
    if not candidate or "/" in candidate or "\\" in candidate:
        return ""
    suffix = "".join(Path(candidate).suffixes[-2:]) if candidate.casefold().endswith((".tar.gz", ".zip.gz")) else Path(candidate).suffix
    if suffix:
        return safe_artifact_display_name(candidate, suffix)
    return safe_artifact_display_name(f"{candidate}.file", ".file").removesuffix(".file")


def run_file_management_download(context: JobContext) -> dict[str, object]:
    service = FileManagementApplicationService(context.paths)
    return service.validate_for_download(context)


__all__ = [
    "FILE_CATEGORIES",
    "FileManagementApplicationService",
    "FileManagementError",
    "FileReferenceNotFound",
    "ResolvedManagedFile",
    "REMOTE_FILES_UNAVAILABLE",
    "classify_file",
    "run_file_management_download",
]
