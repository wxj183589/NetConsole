from __future__ import annotations

from pathlib import Path
from time import perf_counter

from PySide6.QtCore import QThread, Signal

from netconsole.core.paths import PathResolver
from netconsole.core.database import Database
from netconsole.core.sqlite_utils import connect_sqlite
from netconsole.models.device import Device
from netconsole.models.snmp_models import SnmpQueryRequest, SnmpSetRequest
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.repositories.global_mib_repository import GlobalMibRepository
from netconsole.repositories.site_snmp_repository import SiteSnmpRepository
from netconsole.services.device_snmp_detect_service import DeviceSnmpDetectService
from netconsole.services.mib_product_reference_compare_service import MibProductReferenceCompareService
from netconsole.services.mib_resource_service import MibResourceService
from netconsole.services.snmp_query_service import SnmpQueryService
from netconsole.services.topology_service import TopologyService


class CancellableThread(QThread):
    progress = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return self._cancelled


class SnmpStartupWorker(CancellableThread):
    progress_changed = Signal(str, int)
    log_emitted = Signal(str)
    finished_with_result = Signal(object)

    def __init__(self, paths: PathResolver, site_name: str, parent=None) -> None:
        super().__init__(parent)
        self.paths = paths
        self.site_name = site_name

    def run(self) -> None:
        started = perf_counter()
        warnings: list[str] = []

        def step(message: str, percent: int, action) -> object:
            if self.is_cancelled():
                raise RuntimeError("SNMP 服务启动已取消。")
            step_started = perf_counter()
            self.progress.emit(message)
            self.progress_changed.emit(message, percent)
            self.log_emitted.emit(message)
            result = action()
            elapsed_ms = int((perf_counter() - step_started) * 1000)
            if elapsed_ms > 500:
                warning = f"SNMP 启动步骤耗时较长：{message}，耗时 {elapsed_ms} ms"
                warnings.append(warning)
                self.log_emitted.emit(warning)
            return result

        try:
            step("正在检查全局 MIB 目录...", 10, self.paths.ensure_global_mib_dirs)
            step("正在检查当前局点 SNMP 目录...", 20, lambda: self.paths.ensure_site_snmp_dirs(self.site_name))
            global_repo = GlobalMibRepository(self.paths.global_mib_db_path())
            site_repo = SiteSnmpRepository(self.paths.site_snmp_db_path(self.site_name))
            step("正在检查 global_mib.db...", 35, global_repo.initialize)
            step("正在检查当前局点 snmp.db...", 50, site_repo.initialize)
            global_summary = step("正在读取全局 MIB 轻量统计...", 65, global_repo.startup_summary)
            site_summary = step("正在读取当前局点 SNMP 轻量统计...", 80, site_repo.startup_summary)
            device_count = step("正在读取当前局点设备数量...", 90, self._device_count)
            elapsed_ms = int((perf_counter() - started) * 1000)
            summary = {
                **dict(global_summary),
                **dict(site_summary),
                "device_count": int(device_count or 0),
                "elapsed_ms": elapsed_ms,
                "warnings": warnings,
                "status": "ready",
            }
            self.progress_changed.emit("SNMP 服务启动完成。", 100)
            self.log_emitted.emit(f"SNMP 服务启动完成，耗时 {elapsed_ms} ms")
            self.finished_with_result.emit(summary)
        except Exception as exc:
            self.finished_with_result.emit(exc)

    def _device_count(self) -> int:
        db_path = self.paths.site_db_path(self.site_name)
        if not db_path.exists():
            return 0
        with connect_sqlite(db_path) as conn:
            row = conn.execute("SELECT COUNT(*) FROM devices").fetchone()
            return int(row[0] or 0) if row else 0


class MibImportWorker(CancellableThread):
    finished_with_result = Signal(object)

    def __init__(self, paths: PathResolver, source_paths: list[str], metadata: dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self.paths = paths
        self.source_paths = list(source_paths)
        self.metadata = dict(metadata)

    def run(self) -> None:
        try:
            self.progress.emit("正在导入 MIB 文件...")
            service = MibResourceService(self.paths, GlobalMibRepository(self.paths.global_mib_db_path()))
            result = service.import_paths(self.source_paths, **self.metadata)
        except Exception as exc:
            result = exc
        self.finished_with_result.emit(result)


class MibRecompileWorker(CancellableThread):
    finished_with_result = Signal(object)

    def __init__(self, paths: PathResolver, parent=None) -> None:
        super().__init__(parent)
        self.paths = paths

    def run(self) -> None:
        try:
            self.progress.emit("正在重新编译缺依赖 MIB 模块...")
            service = MibResourceService(self.paths, GlobalMibRepository(self.paths.global_mib_db_path()))
            result = service.recompile_missing_dependencies()
        except Exception as exc:
            result = exc
        self.finished_with_result.emit(result)


class MibBrowserTreeLoadWorker(CancellableThread):
    finished_with_result = Signal(object)

    def __init__(
        self,
        db_path,
        *,
        mode: str,
        keyword: str = "",
        source_filter: str = "",
        dictionary_ids: list[int] | None = None,
        module_id: int | None = None,
        parent_oid: str = "",
        limit: int = 500,
        task_id: int = 0,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.db_path = db_path
        self.task_id = int(task_id)
        self.mode = mode
        self.keyword = keyword
        self.source_filter = source_filter
        self.dictionary_ids = list(dictionary_ids or [])
        self.module_id = module_id
        self.parent_oid = parent_oid
        self.limit = int(limit)

    def run(self) -> None:
        try:
            if self.is_cancelled():
                self.finished_with_result.emit({"task_id": self.task_id, "mode": self.mode, "cancelled": True, "rows": []})
                return
            repository = GlobalMibRepository(self.db_path)
            if self.mode == "module":
                rows = repository.list_objects(module_id=int(self.module_id or 0), limit=self.limit)
            elif self.mode == "children":
                rows = repository.list_oid_children(
                    self.parent_oid,
                    source_filter=self.source_filter,
                    dictionary_ids=self.dictionary_ids,
                    module_ids=[int(self.module_id)] if self.module_id else None,
                    limit=self.limit,
                )
            else:
                rows = repository.list_objects(
                    self.keyword,
                    limit=self.limit,
                    source_filter=self.source_filter,
                    dictionary_ids=self.dictionary_ids,
                    module_id=int(self.module_id or 0) or None,
                )
            self.finished_with_result.emit({"task_id": self.task_id, "mode": self.mode, "module_id": self.module_id, "parent_oid": self.parent_oid, "rows": [] if self.is_cancelled() else rows, "cancelled": self.is_cancelled()})
        except Exception as exc:
            self.finished_with_result.emit({"task_id": self.task_id, "mode": self.mode, "error": str(exc), "rows": []})


class ProductReferenceCompareWorker(CancellableThread):
    finished_with_result = Signal(object)

    def __init__(self, db_path, left_reference_id: int, right_reference_id: int, parent=None) -> None:
        super().__init__(parent)
        self.db_path = db_path
        self.left_reference_id = int(left_reference_id)
        self.right_reference_id = int(right_reference_id)

    def run(self) -> None:
        try:
            self.progress.emit("正在对比产品 MIB 参考表...")
            service = MibProductReferenceCompareService(GlobalMibRepository(self.db_path))
            result = service.compare(self.left_reference_id, self.right_reference_id, persist=True)
        except Exception as exc:
            result = exc
        self.finished_with_result.emit(result)


class ProductReferenceTreeRebuildWorker(CancellableThread):
    finished_with_result = Signal(object)

    def __init__(self, db_path, reference_id: int, parent=None) -> None:
        super().__init__(parent)
        self.db_path = db_path
        self.reference_id = int(reference_id)

    def run(self) -> None:
        try:
            self.progress.emit("正在重建产品 MIB 参考目录树...")
            result = GlobalMibRepository(self.db_path).rebuild_product_reference_tree(self.reference_id)
        except Exception as exc:
            result = exc
        self.finished_with_result.emit(result)


class SnmpInitWorker(CancellableThread):
    finished_with_result = Signal(object)

    def __init__(self, paths: PathResolver, action: str = "initialize", clear_raw_files: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.paths = paths
        self.action = action
        self.clear_raw_files = clear_raw_files

    def run(self) -> None:
        try:
            service = MibResourceService(self.paths, GlobalMibRepository(self.paths.global_mib_db_path()))
            if self.action == "reset":
                result = service.reset_and_rebuild(clear_raw_files=self.clear_raw_files, progress=self.progress.emit)
            elif self.action == "rebuild_h3c":
                result = service.initialize_builtin_resources(rebuild_h3c=True, progress=self.progress.emit)
            else:
                result = service.initialize_builtin_resources(progress=self.progress.emit)
        except Exception as exc:
            result = exc
        self.finished_with_result.emit(result)


class SnmpQueryWorker(CancellableThread):
    finished_with_result = Signal(object)

    def __init__(self, site_db_path, request: SnmpQueryRequest, parent=None) -> None:
        super().__init__(parent)
        self.site_db_path = site_db_path
        self.request = request

    def run(self) -> None:
        try:
            self.progress.emit("正在执行 SNMP 查询...")
            result = SnmpQueryService(SiteSnmpRepository(Path(self.site_db_path))).run(self.request, cancel_checker=self.is_cancelled)
        except Exception as exc:
            result = exc
        self.finished_with_result.emit(result)


class SnmpSetWorker(CancellableThread):
    finished_with_result = Signal(object)

    def __init__(self, site_db_path, request: SnmpSetRequest, parent=None) -> None:
        super().__init__(parent)
        self.site_db_path = site_db_path
        self.request = request

    def run(self) -> None:
        try:
            self.progress.emit("正在执行 SNMP Set...")
            result = SnmpQueryService(SiteSnmpRepository(Path(self.site_db_path))).set_value(self.request)
        except Exception as exc:
            result = exc
        self.finished_with_result.emit(result)


class DeviceSnmpDetectWorker(CancellableThread):
    finished_with_result = Signal(object)

    def __init__(self, device: Device, parent=None) -> None:
        super().__init__(parent)
        self.device = device

    def run(self) -> None:
        try:
            self.progress.emit("正在识别设备 SNMP 画像...")
            result = DeviceSnmpDetectService().detect(self.device, cancel_checker=self.is_cancelled)
        except Exception as exc:
            result = exc
        self.finished_with_result.emit(result)


class TopologyDiscoveryWorker(CancellableThread):
    finished_with_result = Signal(object)

    def __init__(self, site_db_path, site_snmp_db_path, parent=None) -> None:
        super().__init__(parent)
        self.site_db_path = site_db_path
        self.site_snmp_db_path = site_snmp_db_path

    def run(self) -> None:
        try:
            self.progress.emit("正在根据设备管理和 LLDP 数据发现拓扑...")
            service = TopologyService(DeviceRepository(Database(Path(self.site_db_path))), SiteSnmpRepository(Path(self.site_snmp_db_path)))
            result = service.discover_basic_topology()
        except Exception as exc:
            result = exc
        self.finished_with_result.emit(result)
