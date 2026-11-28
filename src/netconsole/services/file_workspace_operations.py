"""Local file operations across managed Site downloads and service share roots."""
from __future__ import annotations

import hashlib
import os
import stat
import tempfile
import threading
import time
import uuid
from zipfile import ZIP_DEFLATED, ZipFile
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path

from netconsole.services.site_manager import SiteManager
from netconsole.services.terminal_sftp import TerminalSftpManager


class FileWorkspaceOperations:
    ROOTS = ("downloads", "tftp", "ftp", "http", "https")

    def __init__(self, paths, tasks=None):
        self.paths = paths
        self.task_service = tasks
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="file-workspace")
        self.lock = threading.RLock()
        self.refs = {}
        self.ref_ids = {}
        self.download_lock = threading.RLock()
        self.tasks = {}
        self.closed = False

    def close(self):
        with self.lock:
            self.closed = True
            for task in self.tasks.values():
                task["cancel"].set()
        self.executor.shutdown(wait=True, cancel_futures=False)

    def _site(self):
        return SiteManager(self.paths).get_current_site()

    def _root(self, manager, kind, site, *, write=False):
        if kind not in (*self.ROOTS, "staging"):
            raise ValueError("文件根目录无效")
        if kind == "staging":
            root = self.paths.runtime_dir / "file-workspace-uploads"
            root.mkdir(parents=True, exist_ok=True)
        elif kind == "downloads":
            root = self.paths.file_downloads_root(site)
            if not root.exists():
                root.mkdir(parents=True, exist_ok=True)
        else:
            snapshot = manager.snapshot(kind)
            if not snapshot.get("available") or snapshot["status"] in {"uninitialized", "error", "dependency_missing"}:
                raise ValueError("服务尚未初始化或不可用")
            if write and snapshot["status"] != "stopped":
                raise ValueError("请先停止服务，再维护其根目录")
            root = Path(snapshot["root"])
        self._plain_path(root)
        if not root.is_dir():
            raise ValueError("文件根目录不存在")
        return root.resolve()

    @staticmethod
    def _plain_path(path):
        for part in (path, *path.parents):
            attrs = part.lstat()
            if stat.S_ISLNK(attrs.st_mode) or getattr(attrs, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise ValueError("文件操作不跟随链接或 Junction")

    def _ref(self, site, kind, root, path):
        value = (site, kind, path.relative_to(root).as_posix())
        with self.lock:
            if value in self.ref_ids:
                return self.ref_ids[value]
            if len(self.refs) >= 20000:
                raise ValueError("文件引用已达上限，请重启后端后重试")
            key = uuid.uuid4().hex
            self.refs[key] = value
            self.ref_ids[value] = key
        return key

    def _resolve(self, manager, token, site, *, write=False):
        with self.lock:
            value = self.refs.get(token)
        if value is None or value[0] != site:
            raise ValueError("文件引用不存在或不属于当前局点")
        _, kind, relative = value
        root = self._root(manager, kind, site, write=write)
        path = root / relative
        self._plain_path(path)
        if not path.resolve().is_relative_to(root):
            raise ValueError("文件路径越界")
        return kind, root, path

    def browse(self, manager, kind, token=""):
        site = self._site()
        root = self._root(manager, kind, site)
        path = self._resolve(manager, token, site)[2] if token else root
        if not path.is_relative_to(root) or not path.is_dir():
            raise ValueError("目录引用无效")
        rows = []
        with os.scandir(path) as children:
            for child in children:
                if child.name.endswith(".part"):
                    continue
                if len(rows) >= 1000:
                    raise ValueError("目录超过 1000 项，请使用更小的子目录")
                attrs = child.stat(follow_symlinks=False)
                if child.is_symlink() or getattr(attrs, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                    continue
                directory = stat.S_ISDIR(attrs.st_mode)
                if not directory and not stat.S_ISREG(attrs.st_mode):
                    continue
                rows.append({"id": self._ref(site, kind, root, Path(child.path)), "name": child.name,
                             "directory": directory, "size": None if directory else attrs.st_size,
                             "modified": attrs.st_mtime, "mode": stat.filemode(attrs.st_mode)})
        writable = kind == "downloads" or manager.snapshot(kind)["status"] == "stopped"
        return {"kind": kind, "directory_id": self._ref(site, kind, root, path),
                "parent_id": self._ref(site, kind, root, path.parent) if path != root else "",
                "label": path.relative_to(root).as_posix(), "writable": writable,
                "items": sorted(rows, key=lambda item: (not item["directory"], item["name"].casefold()))}

    def download(self, manager, token):
        _, _, path = self._resolve(manager, token, self._site())
        if not path.is_file():
            raise ValueError("请选择普通文件")
        return path

    def preview(self, manager, token):
        path = self.download(manager, token)
        if path.suffix.casefold() not in {".txt", ".log", ".cfg", ".conf", ".ini", ".json", ".csv", ".md", ".xml", ".yaml", ".yml"}:
            raise ValueError("当前文件类型不支持文本预览")
        with path.open("rb") as handle:
            raw = handle.read(65_537)
        from netconsole.utils.text_encoding import decode_bytes_with_fallback

        return {"name": path.name, "text": decode_bytes_with_fallback(raw[:65_536]).text, "truncated": len(raw) > 65_536}

    def desktop_directory(self, manager, token, site):
        if site != self._site():
            raise ValueError("目录引用不属于当前局点")
        kind, _, path = self._resolve(manager, token, site)
        if kind not in self.ROOTS or not path.is_dir():
            raise ValueError("请选择受管目录")
        return path

    def upload(self, manager, destination, name, stream, overwrite=False, expected_sha256=""):
        site = self._site()
        self._resolve(manager, destination, site, write=True)
        name = TerminalSftpManager._safe_filename(name)
        root = self._root(manager, "staging", site)
        staged = root / uuid.uuid4().hex
        try:
            total = 0
            with staged.open("xb") as output:
                while chunk := stream.read(1024 * 1024):
                    total += len(chunk)
                    if total > 64 * 1024**3:
                        raise ValueError("上传超过 64 GiB")
                    output.write(chunk)
            token = self._ref(site, "staging", root, staged)
            return self.submit(manager, "copy", token, destination, name, overwrite, expected_sha256)
        except BaseException:
            staged.unlink(missing_ok=True)
            raise

    def submit(self, manager, action, source="", destination="", name="", overwrite=False, expected_sha256=""):
        site = self._site()
        if action not in {"copy", "move", "rename", "delete", "mkdir", "checksum", "archive"}:
            raise ValueError("文件操作无效")
        with self.lock:
            if self.closed or sum(item["status"] in {"WAITING", "RUNNING"} for item in self.tasks.values()) >= 20:
                raise ValueError("文件操作队列不可用或已满")
            if len(self.tasks) >= 100:
                terminal = next((key for key, item in self.tasks.items() if item["status"] not in {"WAITING", "RUNNING"}), None)
                if terminal is None:
                    raise ValueError("文件操作记录已满")
                del self.tasks[terminal]
            identifier = uuid.uuid4().hex
            task = {"task_id": identifier, "site": site, "action": action, "status": "WAITING",
                    "current": 0, "total": 0, "sha256": "", "error": "", "cancel": threading.Event()}
            if self.task_service:
                self.task_service.create_external_task(task_id=identifier, task_type="file_workspace_operation",
                    task_name=f"文件 {action}: {name}", source="local", site_name=site, owner="file_workspace",
                    trigger_source="ui")
            self.tasks[identifier] = task
        self.executor.submit(self._run, manager, task, source, destination, name, overwrite, expected_sha256)
        return self._public(task)

    @staticmethod
    def _public(task):
        return {key: value for key, value in task.items() if key not in {"cancel", "site"}}

    def list_tasks(self):
        site = self._site()
        with self.lock:
            return [self._public(task) for task in reversed(list(self.tasks.values())) if task["site"] == site]

    def cancel(self, task_id):
        with self.lock:
            task = self.tasks.get(task_id)
            if task is None or task["site"] != self._site():
                raise ValueError("文件操作任务不存在")
            task["cancel"].set()
        return self._public(task)

    def _event(self, task, event):
        if self.task_service:
            self.task_service.record_external_event(task["task_id"], event,
                {"state": task["status"], "current": task["current"], "total": task["total"],
                 "message": task["error"] or task["status"], "result": self._public(task)},
                source="file_workspace", site_name=task["site"])

    def _check(self, task):
        signal = self.paths.runtime_cache_dir / "background_jobs" / f"{task['task_id']}.cancel"
        if task["cancel"].is_set() or signal.is_file():
            raise InterruptedError("文件操作已取消")

    def _run(self, manager, task, source, destination, name, overwrite, expected_sha256):
        action = task["action"]
        try:
            with ExitStack() as locks:
                with self.lock:
                    tokens = [self.refs.get(token) for token in (source, destination) if token]
                kinds = sorted({value[1] for value in tokens if value and value[1] != "staging"})
                for kind in kinds:
                    lock = self.download_lock if kind == "downloads" else manager.runtimes[kind].lock
                    locks.enter_context(lock)
                self._check(task)
                task["status"] = "RUNNING"
                self._event(task, "state")
                src = self._resolve(manager, source, task["site"], write=action in {"move", "rename", "delete"}) if source else None
                dst = self._resolve(manager, destination, task["site"], write=True) if destination else None
                if action in {"copy", "move", "rename", "mkdir", "archive"}:
                    name = TerminalSftpManager._safe_filename(name)
                    parent = src[2].parent if action == "rename" else dst[2]
                    if not parent.is_dir():
                        raise ValueError("目标目录无效")
                    target = parent / name
                self._check(task)
                if src and src[2] == src[1]:
                    raise ValueError("不能操作受管根目录")
                if action == "mkdir":
                    target.mkdir()
                elif action == "archive":
                    if src[0] not in self.ROOTS or dst[0] not in self.ROOTS:
                        raise ValueError("归档必须使用受管文件目录")
                    self._archive(src[2], target, task)
                elif action == "checksum":
                    task["sha256"] = self._hash(src[2], task)
                elif action == "delete":
                    if src[2].is_dir():
                        src[2].rmdir()
                    else:
                        digest = self._hash(src[2], task)
                        if digest != expected_sha256:
                            raise ValueError("文件已变化，请重新校验后删除")
                        self._check(task)
                        src[2].unlink()
                elif action in {"move", "rename"} and src[2].is_dir():
                    if target.exists():
                        raise FileExistsError("目标已存在")
                    src[2].rename(target)
                else:
                    self._copy(src[2], target, overwrite, expected_sha256, task)
                    if action in {"move", "rename"}:
                        self._check(task)
                        if self._hash(src[2], task) != task["sha256"]:
                            raise ValueError("源文件已变化，副本已保留，请检查")
                        src[2].unlink()
                task["status"] = "COMPLETED"
        except InterruptedError as exc:
            task["status"], task["error"] = "CANCELLED", str(exc)
        except Exception as exc:
            task["status"], task["error"] = "FAILED", str(exc)
        finally:
            with self.lock:
                entry = self.refs.get(source)
            if entry and entry[1] == "staging":
                (self.paths.runtime_dir / "file-workspace-uploads" / entry[2]).unlink(missing_ok=True)
                with self.lock:
                    self.refs.pop(source, None)
                    self.ref_ids.pop(entry, None)
            self._event(task, {"COMPLETED": "finished", "CANCELLED": "cancelled"}.get(task["status"], "error"))

    def _archive(self, source, target, task):
        if target == source or target.is_relative_to(source):
            raise ValueError("归档目标必须位于源目录之外")
        if target.suffix.casefold() != ".zip":
            raise ValueError("归档文件必须使用 .zip 扩展名")
        if target.exists():
            raise FileExistsError("同名归档已存在")
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".file-archive-", suffix=".part", delete=False) as output:
                temporary = Path(output.name)
                with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
                    pending = [source]
                    while pending:
                        self._check(task)
                        path = pending.pop()
                        self._plain_path(path)
                        relative = path.relative_to(source.parent).as_posix()
                        mode = path.stat().st_mode
                        if stat.S_ISDIR(mode):
                            archive.mkdir(relative)
                            pending.extend(sorted(path.iterdir(), reverse=True))
                        elif stat.S_ISREG(mode):
                            with path.open("rb") as stream, archive.open(relative, "w", force_zip64=True) as entry:
                                while chunk := stream.read(1024 * 1024):
                                    self._check(task)
                                    entry.write(chunk)
                        else:
                            raise ValueError("归档仅支持普通文件和目录")
                output.flush()
                os.fsync(output.fileno())
            task["sha256"] = self._hash(temporary, task)
            self._check(task)
            self._plain_path(target.parent)
            os.link(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def _hash(self, path, task):
        if not path.is_file():
            raise ValueError("请选择普通文件")
        task["total"] = path.stat().st_size
        task["current"] = 0
        digest = hashlib.sha256()
        last_event = time.monotonic()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                self._check(task)
                digest.update(chunk)
                task["current"] += len(chunk)
                if time.monotonic() - last_event >= 0.5:
                    self._event(task, "progress")
                    last_event = time.monotonic()
        return digest.hexdigest()

    def _copy(self, source, target, overwrite, expected, task):
        if source == target:
            raise ValueError("源和目标相同")
        identity = source.stat()
        if not source.is_file():
            raise ValueError("复制支持普通文件，目录请先进入后选择文件")
        if target.exists():
            self._plain_path(target)
            if not overwrite or not expected or self._hash(target, task) != expected:
                raise FileExistsError("同名文件已存在或已变化，请校验后确认覆盖")
        task["total"], task["current"] = identity.st_size, 0
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".file-transfer-", suffix=".part", delete=False) as output:
                temporary = Path(output.name)
                digest = hashlib.sha256()
                last_event = time.monotonic()
                with source.open("rb") as stream:
                    while chunk := stream.read(1024 * 1024):
                        self._check(task)
                        output.write(chunk)
                        digest.update(chunk)
                        task["current"] += len(chunk)
                        if time.monotonic() - last_event >= 0.5:
                            self._event(task, "progress")
                            last_event = time.monotonic()
                output.flush()
                os.fsync(output.fileno())
            self._check(task)
            after = source.stat()
            if (after.st_size, after.st_mtime_ns) != (identity.st_size, identity.st_mtime_ns):
                raise ValueError("复制期间源文件已变化")
            task["sha256"] = digest.hexdigest()
            if self._hash(temporary, task) != task["sha256"]:
                raise ValueError("文件副本校验失败")
            self._check(task)
            self._plain_path(target.parent)
            if target.exists() and overwrite:
                self._plain_path(target)
                if self._hash(target, task) != expected:
                    raise ValueError("覆盖目标已变化")
                os.replace(temporary, target)
            else:
                os.link(temporary, target)
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
