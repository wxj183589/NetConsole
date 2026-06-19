from __future__ import annotations

import re
import stat
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import Callable

from netconsole.core import app_logger
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.services import command_guard, netmiko_connection
from netconsole.services.netmiko_connection import build_netmiko_params, choose_connection_target, safe_send_command, sanitize_sensitive_text
from netconsole.utils.text_encoding import clean_h3c_device_text


FILE_MANAGEMENT_CONTEXT = "file_management"
FILE_LIST_COMMANDS = ("dir flash:/", "dir flash:/diagfile/")
FILE_TRANSFER_CONCURRENCY = 50
FILE_TRANSFER_MAX_CONCURRENCY = 1


class TransferCancelled(RuntimeError):
    pass


class TransferVerificationFailed(RuntimeError):
    pass


@dataclass(frozen=True)
class RemoteDeviceFile:
    name: str
    remote_path: str
    size: int | None
    modified_time: str | None
    category: str
    is_dir: bool = False
    file_type: str = "file"


@dataclass(frozen=True)
class FileDownloadResult:
    device_id: int | None
    device_name: str
    remote_path: str
    local_path: str | None
    status: str
    error_message: str | None = None
    elapsed_ms: int | None = None

    @property
    def success(self) -> bool:
        return self.status == "success"


class FileTransferService:
    def __init__(self, site_name: str, paths: PathResolver | None = None) -> None:
        self.site_name = site_name
        self.paths = paths or PathResolver()
        self._client = None
        self._sftp = None
        self._device: Device | None = None
        self._root_path = ""
        self._current_path = ""

    def connect(self, device: Device) -> str:
        self.disconnect()
        target = choose_connection_target(device)
        if target is None or target.protocol.casefold() != "ssh":
            raise RuntimeError("SFTP requires SSH connection settings.")
        try:
            import paramiko

            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                hostname=target.host,
                port=target.port,
                username=target.username,
                password=target.password,
                timeout=20,
                banner_timeout=20,
                auth_timeout=20,
                look_for_keys=False,
                allow_agent=False,
            )
            self._client = client
            self._sftp = client.open_sftp()
            self._device = device
            self._root_path = self.detect_remote_root()
            self._current_path = self._root_path
            app_logger.log_info("SFTP_CONNECTED", f"device={device.name}, ip={device.ip_address}, root={self._root_path}")
            return self._root_path
        except Exception as exc:
            self.disconnect()
            message = sanitize_sensitive_text(str(exc), device)
            app_logger.log_error("SFTP_CONNECT_FAILED", f"device={device.name}, ip={device.ip_address}, error={message}")
            raise RuntimeError(message) from exc

    def disconnect(self) -> None:
        if self._sftp is not None:
            try:
                self._sftp.close()
            except Exception:
                pass
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
        self._client = None
        self._sftp = None
        self._device = None
        self._root_path = ""
        self._current_path = ""

    def is_connected(self) -> bool:
        return self._sftp is not None

    @property
    def root_path(self) -> str:
        return self._root_path

    @property
    def current_path(self) -> str:
        return self._current_path

    def detect_remote_root(self) -> str:
        sftp = self._require_sftp()
        for candidate in ("flash:/", "/flash/", "/", "."):
            try:
                sftp.listdir_attr(candidate)
                return normalize_remote_path(candidate)
            except Exception:
                continue
        raise RuntimeError("Unable to detect SFTP remote root.")

    def list_directory(self, remote_path: str | None = None) -> list[RemoteDeviceFile]:
        sftp = self._require_sftp()
        path = normalize_remote_path(remote_path or self._current_path or self._root_path, current_path=self._current_path or self._root_path, root_path=self._root_path)
        attrs = sftp.listdir_attr(path)
        files: list[RemoteDeviceFile] = []
        for attr in attrs:
            name = str(attr.filename)
            child_path = join_remote_path(path, name, self._root_path)
            is_dir = stat.S_ISDIR(getattr(attr, "st_mode", 0))
            files.append(
                RemoteDeviceFile(
                    name=name,
                    remote_path=child_path,
                    size=None if is_dir else int(getattr(attr, "st_size", 0) or 0),
                    modified_time=format_mtime(getattr(attr, "st_mtime", None)),
                    category="dir" if is_dir else file_category(name, child_path),
                    is_dir=is_dir,
                    file_type="directory" if is_dir else file_extension_type(name),
                )
            )
        self._current_path = path
        if self._device is not None:
            app_logger.log_info("SFTP_DIRECTORY_LISTED", f"device={self._device.name}, path={path}, count={len(files)}")
        return sorted(files, key=lambda item: (not item.is_dir, item.name.casefold()))

    def stat(self, remote_path: str):
        return self._require_sftp().stat(normalize_remote_path(remote_path, current_path=self._current_path, root_path=self._root_path))

    def download(self, remote_path: str, local_path: Path, progress_callback=None, cancel_token=None, chunk_size: int = 1024 * 1024) -> Path:
        sftp = self._require_sftp()
        source = normalize_remote_path(remote_path, current_path=self._current_path, root_path=self._root_path)
        target = Path(local_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        part_path = target.with_name(f"{target.name}.part")
        remote_size = int(sftp.stat(source).st_size)
        downloaded = 0
        try:
            with sftp.open(source, "rb") as remote_file, part_path.open("wb") as local_file:
                while True:
                    if is_cancelled(cancel_token):
                        raise TransferCancelled("Transfer cancelled.")
                    chunk = remote_file.read(chunk_size)
                    if not chunk:
                        break
                    local_file.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback is not None:
                        progress_callback(downloaded, remote_size)
            if part_path.stat().st_size != remote_size:
                raise TransferVerificationFailed("File size verification failed.")
            part_path.replace(target)
            return target
        except Exception:
            if part_path.exists():
                part_path.unlink(missing_ok=True)
            raise

    def _require_sftp(self):
        if self._sftp is None:
            raise RuntimeError("SFTP is not connected.")
        return self._sftp

    def list_files(self, device: Device) -> list[RemoteDeviceFile]:
        target = choose_connection_target(device)
        if target is None:
            raise RuntimeError("No SSH connection is enabled.")
        if target.protocol.casefold() != "ssh":
            raise RuntimeError("File management requires SSH.")
        command_guard.validate_command_list(FILE_LIST_COMMANDS, FILE_MANAGEMENT_CONTEXT)
        connection = None
        files: list[RemoteDeviceFile] = []
        try:
            connection = netmiko_connection.ConnectHandler(**build_netmiko_params(target))
            for command in FILE_LIST_COMMANDS:
                output = safe_send_command(
                    connection,
                    command,
                    read_timeout=120,
                    strip_prompt=False,
                    strip_command=False,
                    use_timing=True,
                )
                files.extend(parse_dir_output(clean_h3c_device_text(output), command.removeprefix("dir ").strip()))
            app_logger.log_info("FILE_LIST_REFRESHED", f"device={device.name}, ip={device.ip_address}, count={len(files)}")
            return unique_remote_files(files)
        except Exception as exc:
            message = sanitize_sensitive_text(str(exc), device)
            app_logger.log_error("FILE_LIST_REFRESH_FAILED", f"device={device.name}, ip={device.ip_address}, error={message}")
            raise RuntimeError(message) from exc
        finally:
            if connection is not None:
                try:
                    connection.disconnect()
                except Exception:
                    pass

    def download_file(self, device: Device, remote_file: RemoteDeviceFile) -> FileDownloadResult:
        started = monotonic()
        target = choose_connection_target(device)
        if target is None:
            message = "No SSH connection is enabled."
            app_logger.log_error("FILE_DOWNLOAD_FAILED", self._detail(device, remote_file, error=message))
            return FileDownloadResult(device.id, str(device.name or ""), remote_file.remote_path, None, "failed", message, elapsed_ms(started))
        if target.protocol.casefold() != "ssh":
            message = "File download requires SSH."
            app_logger.log_error("FILE_DOWNLOAD_FAILED", self._detail(device, remote_file, error=message))
            return FileDownloadResult(device.id, str(device.name or ""), remote_file.remote_path, None, "failed", message, elapsed_ms(started))
        local_path = self.local_path_for(device, remote_file)
        try:
            try:
                self._download_sftp(target, remote_file.remote_path, local_path)
            except Exception as sftp_exc:
                app_logger.log_error("FILE_DOWNLOAD_SFTP_FAILED", self._detail(device, remote_file, local_path, sanitize_sensitive_text(str(sftp_exc), device)))
                self._download_scp(target, remote_file.remote_path, local_path)
            app_logger.log_info("FILE_DOWNLOADED", self._detail(device, remote_file, local_path))
            return FileDownloadResult(device.id, str(device.name or ""), remote_file.remote_path, self._relative_to_site(local_path), "success", None, elapsed_ms(started))
        except Exception as exc:
            message = sanitize_sensitive_text(str(exc), device)
            app_logger.log_error("FILE_DOWNLOAD_FAILED", self._detail(device, remote_file, local_path, message))
            if local_path.exists() and local_path.stat().st_size == 0:
                local_path.unlink(missing_ok=True)
            return FileDownloadResult(device.id, str(device.name or ""), remote_file.remote_path, None, "failed", message, elapsed_ms(started))

    def local_device_dir(self, device: Device) -> Path:
        return self.paths.ensure_site_dirs(self.site_name) / "raw" / "files" / device_file_dir_name(device)

    def local_path_for(self, device: Device, remote_file: RemoteDeviceFile) -> Path:
        directory = self.local_device_dir(device) / remote_file.category
        directory.mkdir(parents=True, exist_ok=True)
        return unique_path(directory / f"{safe_device_name(device.name or device.sysname or 'device')}_{remote_file.name}")

    def _download_sftp(self, target, remote_path: str, local_path: Path) -> None:
        import paramiko

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                hostname=target.host,
                port=target.port,
                username=target.username,
                password=target.password,
                timeout=20,
                banner_timeout=20,
                auth_timeout=20,
                look_for_keys=False,
                allow_agent=False,
            )
            sftp = client.open_sftp()
            try:
                sftp.get(remote_path, str(local_path))
            finally:
                sftp.close()
        finally:
            client.close()

    def _download_scp(self, target, remote_path: str, local_path: Path) -> None:
        try:
            from netmiko import file_transfer
        except ImportError as exc:  # pragma: no cover - depends on optional runtime.
            raise RuntimeError("SCP fallback is unavailable because netmiko file_transfer is not installed.") from exc
        connection = None
        try:
            connection = netmiko_connection.ConnectHandler(**build_netmiko_params(target))
            file_transfer(
                connection,
                source_file=remote_path,
                dest_file=str(local_path),
                file_system="",
                direction="get",
                overwrite_file=True,
            )
        finally:
            if connection is not None:
                try:
                    connection.disconnect()
                except Exception:
                    pass

    def _relative_to_site(self, path: Path) -> str:
        return path.resolve().relative_to(self.paths.site_dir(self.site_name).resolve()).as_posix()

    @staticmethod
    def _detail(device: Device, remote_file: RemoteDeviceFile, local_path: Path | None = None, error: str = "") -> str:
        parts = [f"device={device.name}", f"ip={device.ip_address}", f"remote_path={remote_file.remote_path}"]
        if local_path:
            parts.append(f"local_path={local_path}")
        if error:
            parts.append(f"error={error}")
        return ", ".join(parts)


def run_batch_file_download(
    jobs: list[tuple[Device, RemoteDeviceFile]],
    service_factory: Callable[[], FileTransferService],
    max_workers: int = FILE_TRANSFER_CONCURRENCY,
) -> list[FileDownloadResult]:
    worker_count = max(1, min(int(max_workers or 1), FILE_TRANSFER_CONCURRENCY, len(jobs) or 1))
    results: list[FileDownloadResult] = []
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {executor.submit(service_factory().download_file, device, remote_file): (device, remote_file) for device, remote_file in jobs}
        started_at = {future: monotonic() for future in futures}
        for future in as_completed(futures):
            device, remote_file = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                message = sanitize_sensitive_text(str(exc), device)
                app_logger.log_error("FILE_DOWNLOAD_FAILED", FileTransferService._detail(device, remote_file, error=message))
                results.append(FileDownloadResult(device.id, str(device.name or ""), remote_file.remote_path, None, "failed", message, elapsed_ms(started_at[future])))
    return results


def parse_dir_output(output: str, base_path: str) -> list[RemoteDeviceFile]:
    files: list[RemoteDeviceFile] = []
    normalized_base = normalize_remote_dir(base_path)
    for line in str(output or "").splitlines():
        item = parse_dir_line(line, normalized_base)
        if item is not None:
            files.append(item)
    return files


def parse_dir_line(line: str, base_path: str) -> RemoteDeviceFile | None:
    text = str(line or "").strip()
    if not text or text.startswith("<") or text.casefold().startswith("directory of"):
        return None
    name = text.split()[-1] if text.split() else ""
    name = name.strip()
    if not is_supported_remote_file(name):
        return None
    size = parse_size(text, name)
    modified_time = parse_modified_time(text, name)
    return RemoteDeviceFile(name=name, remote_path=f"{base_path}{name}", size=size, modified_time=modified_time, category=file_category(name, base_path))


def parse_size(line: str, name: str) -> int | None:
    prefix = line[: line.rfind(name)].strip()
    tokens = prefix.split()
    for index, token in enumerate(tokens):
        if "rw" in token.casefold():
            for candidate in tokens[index + 1 :]:
                if candidate.isdigit():
                    return int(candidate)
    for token in tokens:
        if token.isdigit():
            return int(token)
    return None


def parse_modified_time(line: str, name: str) -> str | None:
    prefix = line[: line.rfind(name)].strip()
    tokens = prefix.split()
    if len(tokens) >= 4:
        return " ".join(tokens[-4:])
    return None


def unique_remote_files(files: list[RemoteDeviceFile]) -> list[RemoteDeviceFile]:
    by_path: dict[str, RemoteDeviceFile] = {}
    for item in files:
        by_path[item.remote_path] = item
    return list(by_path.values())


def is_supported_remote_file(name: str) -> bool:
    lowered = name.casefold()
    return lowered.endswith(".bin") or lowered.endswith(".zip") or lowered.endswith(".tar.gz") or lowered.startswith("diag_")


def file_category(name: str, remote_path: str = "") -> str:
    lowered = f"{remote_path}/{name}".casefold()
    if "/diagfile/" in lowered or Path(name).name.casefold().startswith("diag_"):
        return "diag"
    if lowered.endswith(".bin"):
        return "bin"
    if lowered.endswith(".zip") or lowered.endswith(".tar.gz"):
        return "zip"
    return "diag" if lowered.startswith("diag_") else "zip"


def normalize_remote_dir(value: str) -> str:
    text = str(value or "flash:/").strip()
    return text if text.endswith("/") else f"{text}/"


def normalize_remote_path(path: str, current_path: str | None = None, root_path: str | None = None) -> str:
    value = str(path or "").strip()
    current = str(current_path or root_path or "").strip()
    if not value:
        value = current or "."
    if is_relative_remote_path(value) and current:
        value = join_remote_path(current, value, root_path)
    prefix, parts = split_remote_path(value)
    stack: list[str] = []
    for part in parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if stack:
                stack.pop()
            continue
        stack.append(part)
    normalized = build_remote_path(prefix, stack)
    if root_path and not is_within_remote_root(normalized, root_path):
        return normalize_remote_path(root_path)
    return normalized


def join_remote_path(base_path: str, child: str, root_path: str | None = None) -> str:
    child_text = str(child or "").strip()
    if not child_text:
        return normalize_remote_path(base_path, root_path=root_path)
    if not is_relative_remote_path(child_text):
        return normalize_remote_path(child_text, root_path=root_path)
    base = normalize_remote_path(base_path, root_path=root_path)
    separator = "" if base.endswith("/") else "/"
    return normalize_remote_path(f"{base}{separator}{child_text}", root_path=root_path)


def parent_remote_path(path: str, root_path: str | None = None) -> str:
    normalized = normalize_remote_path(path, root_path=root_path)
    prefix, parts = split_remote_path(normalized)
    if parts:
        parts = parts[:-1]
    parent = build_remote_path(prefix, parts)
    if root_path and not is_within_remote_root(parent, root_path):
        return normalize_remote_path(root_path)
    return parent


def is_relative_remote_path(path: str) -> bool:
    text = str(path or "")
    return not text.startswith("/") and re.match(r"^[A-Za-z0-9_-]+:/", text) is None


def split_remote_path(path: str) -> tuple[str, list[str]]:
    text = str(path or ".").replace("\\", "/").strip()
    match = re.match(r"^([A-Za-z0-9_-]+:/)(.*)$", text)
    if match:
        return match.group(1), match.group(2).split("/")
    if text.startswith("/"):
        return "/", text.strip("/").split("/")
    return "", text.split("/")


def build_remote_path(prefix: str, parts: list[str]) -> str:
    cleaned = [part for part in parts if part]
    if prefix.endswith(":/"):
        return prefix if not cleaned else prefix + "/".join(cleaned)
    if prefix == "/":
        return "/" if not cleaned else "/" + "/".join(cleaned)
    return "/".join(cleaned) or "."


def is_within_remote_root(path: str, root_path: str) -> bool:
    normalized = normalize_remote_path(path)
    root = normalize_remote_path(root_path)
    if root in {".", "/"}:
        return True
    return normalized == root.rstrip("/") or normalized.startswith(normalize_remote_dir(root))


def file_extension_type(name: str) -> str:
    lowered = name.casefold()
    if lowered.endswith(".tar.gz"):
        return "tar.gz"
    suffix = Path(name).suffix.lstrip(".")
    return suffix or "file"


def format_mtime(value: object) -> str | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(float(value)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def is_cancelled(cancel_token) -> bool:
    if cancel_token is None:
        return False
    if hasattr(cancel_token, "is_cancelled"):
        return bool(cancel_token.is_cancelled())
    if hasattr(cancel_token, "is_set"):
        return bool(cancel_token.is_set())
    return False


def safe_device_name(name: str) -> str:
    value = str(name or "device").strip()
    value = re.sub(r'[\\/:*?"<>|]+', "_", value)
    value = re.sub(r"\s+", "_", value)
    return value.strip("._ ") or "device"


def safe_device_id(device: Device) -> str:
    value = str(device.device_uuid or device.id or "unknown").strip()
    value = re.sub(r'[\\/:*?"<>|\s]+', "_", value)
    return value.strip("._ ") or "unknown"


def device_file_dir_name(device: Device) -> str:
    return f"{safe_device_name(device.name or device.sysname or 'device')}__{safe_device_id(device)}"


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    suffix = "".join(path.suffixes)
    stem = path.name[: -len(suffix)] if suffix else path.name
    for index in range(1, 1000):
        candidate = path.with_name(f"{stem}_{index:03d}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Cannot allocate unique file path: {path}")


def auto_rename_path(path: Path) -> Path:
    if not path.exists():
        return path
    suffix = "".join(path.suffixes)
    stem = path.name[: -len(suffix)] if suffix else path.name
    for index in range(1, 10000):
        candidate = path.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Cannot allocate renamed file path: {path}")


def elapsed_ms(started: float) -> int:
    return int((monotonic() - started) * 1000)
