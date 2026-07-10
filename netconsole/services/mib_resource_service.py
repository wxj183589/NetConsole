from __future__ import annotations

import hashlib
import json
import re
import shutil
import tarfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from netconsole.core import app_logger
from netconsole.core.paths import PathResolver
from netconsole.repositories.global_mib_repository import GlobalMibRepository
from netconsole.services.mib_compile_service import MibCompileService


SUPPORTED_MIB_SUFFIXES = {".mib", ".txt", ".my", ".smi", ".sm2"}
SUPPORTED_REFERENCE_SUFFIXES = {".xlsx"}
SUPPORTED_ARCHIVE_SUFFIXES = {".zip", ".tar", ".gz", ".tgz"}
MODULE_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9-]*)\s+DEFINITIONS\s*::=\s*BEGIN\b", re.MULTILINE)


@dataclass(frozen=True)
class MibImportItem:
    source_path: str
    target_path: str
    file_hash: str
    status: str
    module_name: str = ""
    missing_dependencies: list[str] = field(default_factory=list)
    error_message: str = ""
    duplicate_file_id: int | None = None


@dataclass(frozen=True)
class MibImportReport:
    status: str
    total: int
    imported: int
    duplicated: int
    failed: int
    report_path: str
    items: list[MibImportItem]


@dataclass(frozen=True)
class H3cPackageMeta:
    vendor: str = ""
    product_line: str = ""
    version_line: str = ""
    package_version: str = ""
    source_type: str = "manual"
    package_name: str = ""


@dataclass(frozen=True)
class MibCandidate:
    source_path: Path
    stored_path: Path
    module_name: str
    file_hash: str
    source_id: int
    source_package_id: int | None
    vendor: str
    package_version_line: str = ""


class MibResourceService:
    def __init__(self, paths: PathResolver, repository: GlobalMibRepository | None = None, compiler: MibCompileService | None = None) -> None:
        self.paths = paths
        self.repository = repository or GlobalMibRepository(paths.global_mib_db_path())
        self.compiler = compiler or MibCompileService()

    def initialize(self) -> None:
        self.paths.ensure_global_mib_dirs()
        self.repository.initialize()

    def import_paths(self, source_paths: list[str | Path], *, vendor: str = "", source_name: str = "用户手动导入", source_url: str = "", product_line: str = "", product_name: str = "", software_version: str = "", builtin: bool = False) -> MibImportReport:
        self.initialize()
        candidates, reference_paths = self._prepare_batch([Path(path) for path in source_paths], vendor=vendor, source_name=source_name, source_url=source_url, product_line=product_line, product_name=product_name, software_version=software_version, builtin=builtin)
        known_modules = {str(item["module_name"]) for item in self.repository.list_modules()}
        known_modules.update(candidate.module_name for candidate in candidates)
        oid_paths = [Path(row["raw_path"]) for row in self.repository.list_module_paths() if row.get("raw_path")]
        oid_paths.extend(candidate.stored_path for candidate in candidates)
        builtin_dir = self.paths.app_root / "resources" / "builtin_mibs"
        if builtin_dir.exists():
            oid_paths.extend(path for path in builtin_dir.rglob("*") if path.is_file() and path.suffix.lower() in SUPPORTED_MIB_SUFFIXES)
        oid_map = self.compiler.build_oid_map(oid_paths)

        items: list[MibImportItem] = []
        for reference_path in reference_paths:
            items.append(self._import_reference(reference_path, vendor=vendor, product_line=product_line, product_name=product_name, software_version=software_version))
        for candidate in candidates:
            items.append(self._compile_candidate(candidate, known_modules=known_modules, oid_map=oid_map))

        for package in {candidate.source_package_id: candidate.package_version_line for candidate in candidates if candidate.source_package_id and candidate.package_version_line}.items():
            package_id, version_line = package
            if package_id is not None:
                self.repository.ensure_h3c_comware_dictionaries(package_id, version_line)

        report = self._write_report(items)
        app_logger.log_info("SNMP_MIB_IMPORT", f"total={len(items)} imported={report.imported} duplicated={report.duplicated} failed={report.failed}")
        return report

    def initialize_builtin_resources(self, *, rebuild_h3c: bool = False, progress=None) -> MibImportReport:
        if progress:
            progress("正在检查全局 MIB 目录...")
        self.paths.ensure_global_mib_dirs()
        if progress:
            progress("正在检查 global_mib.db...")
        self.repository.initialize()
        if progress:
            progress("正在注册内置标准 MIB...")
        builtin_packages = self._builtin_h3c_packages()
        items: list[MibImportItem] = []
        for package in builtin_packages:
            meta = _detect_h3c_package(package)
            version_text = "H3C V5" if meta.version_line == "V5" else "H3C V7/V9"
            if progress:
                progress(f"正在注册内置 {version_text} MIB...")
            package_hash = sha256_file(package)
            if rebuild_h3c:
                self.repository.remove_source_package_by_file_hash(package_hash)
            elif self.repository.get_source_package_by_hash(package_hash) is not None:
                if progress:
                    progress(f"内置 {version_text} MIB 已注册，跳过。")
                continue
            report = self.import_paths([package], vendor="H3C", source_name=package.stem, product_line="Comware", builtin=True)
            items.extend(report.items)
        if progress:
            progress("正在检查产品 MIB 参考表...")
        if progress:
            progress("正在重建字典集索引...")
        if progress:
            progress("初始化完成。")
        return self._write_report(items)

    def reset_and_rebuild(self, *, clear_raw_files: bool = False, progress=None) -> MibImportReport:
        if progress:
            progress("正在清空全局 MIB 数据库和索引...")
        db_path = self.paths.global_mib_db_path()
        if db_path.exists():
            db_path.unlink()
        for directory in (self.paths.global_mib_compiled_dir(), self.paths.global_mib_index_dir(), self.paths.global_mib_reports_dir()):
            if directory.exists():
                shutil.rmtree(directory)
        if clear_raw_files:
            for directory in (self.paths.global_mib_raw_files_dir(), self.paths.global_mib_raw_archives_dir(), self.paths.global_mib_references_dir()):
                if directory.exists():
                    shutil.rmtree(directory)
        self.paths.ensure_global_mib_dirs()
        if progress:
            progress("正在重建内置通用 MIB 字典...")
        self.repository.initialize()
        return self.initialize_builtin_resources(rebuild_h3c=True, progress=progress)

    def recompile_missing_dependencies(self) -> MibImportReport:
        self.initialize()
        files = self.repository.list_missing_dependency_files()
        known_modules = {str(item["module_name"]) for item in self.repository.list_modules()}
        known_modules.update(str(item.get("module_name") or "") for item in files)
        oid_paths = [Path(row["raw_path"]) for row in self.repository.list_module_paths() if row.get("raw_path")]
        oid_map = self.compiler.build_oid_map(oid_paths)
        items: list[MibImportItem] = []
        for row in files:
            path = Path(str(row["raw_path"]))
            if not path.exists():
                items.append(MibImportItem(str(path), "", "", "failed", module_name=str(row.get("module_name") or ""), error_message="原始 MIB 文件不存在，无法重新编译。"))
                continue
            candidate = MibCandidate(
                source_path=path,
                stored_path=path,
                module_name=str(row.get("module_name") or ""),
                file_hash=str(row.get("file_hash") or ""),
                source_id=int(row.get("source_id") or 0),
                source_package_id=int(row["source_package_id"]) if row.get("source_package_id") is not None else None,
                vendor="",
            )
            items.append(self._compile_candidate(candidate, known_modules=known_modules, oid_map=oid_map, file_id=int(row["id"]), replace=True))
        return self._write_report(items)

    def _prepare_batch(self, source_paths: list[Path], *, vendor: str, source_name: str, source_url: str, product_line: str, product_name: str, software_version: str, builtin: bool = False) -> tuple[list[MibCandidate], list[Path]]:
        candidates: list[MibCandidate] = []
        references: list[Path] = []
        for source in source_paths:
            if not source.exists():
                continue
            meta = _detect_h3c_package(source)
            if builtin and meta.source_type == "official_comware_mib_package":
                meta = H3cPackageMeta(
                    vendor=meta.vendor,
                    product_line=meta.product_line,
                    version_line=meta.version_line,
                    package_version=meta.package_version,
                    source_type="builtin_h3c_comware_package",
                    package_name=meta.package_name,
                )
            elif meta.source_type == "official_comware_mib_package":
                meta = H3cPackageMeta(
                    vendor=meta.vendor,
                    product_line=meta.product_line,
                    version_line=meta.version_line,
                    package_version=meta.package_version,
                    source_type="user_update_h3c_comware_package",
                    package_name=meta.package_name,
                )
            effective_vendor = meta.vendor or vendor or "用户导入"
            effective_product_line = meta.product_line or product_line
            effective_version = meta.version_line or software_version
            source_id = self.repository.create_source(
                vendor=effective_vendor,
                source_name=meta.package_name or source_name or "用户手动导入",
                source_type=meta.source_type,
                source_url=source_url,
                product_line=effective_product_line,
                product_name=product_name,
                software_version=effective_version,
            )
            package_id: int | None = None
            scan_root = source
            if source.is_file() and source.suffix.lower() in SUPPORTED_ARCHIVE_SUFFIXES:
                archive_hash = sha256_file(source)
                target_archive = self._copy_archive(source)
                scan_root = self._extract_archive(target_archive)
                if meta.source_type in {"builtin_h3c_comware_package", "user_update_h3c_comware_package"}:
                    package_id = self.repository.ensure_source_package(
                        source_id=source_id,
                        vendor=effective_vendor,
                        product_line=effective_product_line,
                        version_line=meta.version_line,
                        package_version=meta.package_version,
                        package_name=meta.package_name,
                        source_type=meta.source_type,
                        source_file=str(target_archive),
                        file_hash=archive_hash,
                        extract_path=str(scan_root),
                    )
            files = self._scan_source_files(scan_root)
            if source.is_file() and source.suffix.lower() in SUPPORTED_REFERENCE_SUFFIXES:
                references.append(source)
                continue
            for file_path in files:
                if file_path.suffix.lower() in SUPPORTED_REFERENCE_SUFFIXES:
                    references.append(file_path)
                    continue
                module_name = identify_module_name(file_path)
                if not module_name:
                    continue
                stored = self._store_mib_file(file_path, package_id=package_id)
                candidates.append(
                    MibCandidate(
                        source_path=file_path,
                        stored_path=stored,
                        module_name=module_name,
                        file_hash=sha256_file(stored),
                        source_id=source_id,
                        source_package_id=package_id,
                        vendor=effective_vendor,
                        package_version_line=meta.version_line,
                    )
                )
        return candidates, references

    def _builtin_h3c_packages(self) -> list[Path]:
        root = self.paths.app_root / "resources" / "builtin_mibs" / "h3c"
        if not root.exists():
            return []
        return sorted(root.rglob("H3C-*-Comware_MIB-*.zip"))

    def _scan_source_files(self, source: Path) -> list[Path]:
        supported = SUPPORTED_MIB_SUFFIXES | SUPPORTED_REFERENCE_SUFFIXES
        if source.is_dir():
            return [path for path in source.rglob("*") if path.is_file() and path.suffix.lower() in supported]
        if source.is_file() and source.suffix.lower() in supported:
            return [source]
        return []

    def _copy_archive(self, path: Path) -> Path:
        archive_dir = self.paths.global_mib_raw_archives_dir()
        archive_dir.mkdir(parents=True, exist_ok=True)
        target = archive_dir / path.name
        if path.resolve() != target.resolve():
            shutil.copy2(path, target)
        return target

    def _extract_archive(self, path: Path) -> Path:
        extract_root = self.paths.global_mib_raw_files_dir() / path.stem
        extract_root.mkdir(parents=True, exist_ok=True)
        try:
            if zipfile.is_zipfile(path):
                with zipfile.ZipFile(path) as archive:
                    archive.extractall(extract_root)
            elif tarfile.is_tarfile(path):
                with tarfile.open(path) as archive:
                    archive.extractall(extract_root)
        except Exception as exc:
            app_logger.log_error("SNMP_MIB_ARCHIVE_EXTRACT_FAILED", f"path={path}, error={exc}")
        return extract_root

    def _store_mib_file(self, source: Path, *, package_id: int | None) -> Path:
        root = self.paths.global_mib_raw_files_dir()
        target_dir = root / f"package_{package_id}" if package_id else root
        target_dir.mkdir(parents=True, exist_ok=True)
        target = unique_target(target_dir / source.name)
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)
        return target

    def _compile_candidate(self, candidate: MibCandidate, *, known_modules: set[str], oid_map: dict[str, str], file_id: int | None = None, replace: bool = False) -> MibImportItem:
        try:
            if not replace and candidate.source_package_id is None:
                duplicate = self.repository.get_file_by_hash(candidate.file_hash)
                if duplicate is not None and duplicate["source_package_id"] is None:
                    return MibImportItem(str(candidate.source_path), str(duplicate["raw_path"]), candidate.file_hash, "duplicate", str(duplicate["module_name"] or ""), duplicate_file_id=int(duplicate["id"]))
            compiled_path = ""
            result = self.compiler.compile_file(candidate.stored_path, known_modules=known_modules, oid_map=oid_map)
            if result.status == "compiled" and result.objects:
                suffix = f"_{candidate.source_package_id}" if candidate.source_package_id else ""
                compiled = self.paths.global_mib_compiled_dir() / f"{result.module_name}{suffix}.json"
                compiled.write_text(json.dumps([item.__dict__ for item in result.objects], ensure_ascii=False, indent=2), encoding="utf-8")
                compiled_path = str(compiled)
            if replace and file_id is not None:
                self.repository.replace_file_compile_result(
                    file_id=file_id,
                    source_package_id=candidate.source_package_id,
                    module_name=result.module_name,
                    vendor=candidate.vendor,
                    status=result.status,
                    compiled_path=compiled_path,
                    objects=result.objects,
                    dependencies=result.imports,
                    missing_dependencies=result.missing_dependencies,
                    error_message=result.error_message,
                )
            else:
                file_id = self.repository.insert_mib_file(
                    source_id=candidate.source_id,
                    source_package_id=candidate.source_package_id,
                    file_name=candidate.source_path.name,
                    raw_path=str(candidate.stored_path),
                    compiled_path=compiled_path,
                    module_name=result.module_name,
                    file_hash=candidate.file_hash,
                    file_size=candidate.stored_path.stat().st_size,
                    compile_status=result.status,
                    missing_dependencies=result.missing_dependencies,
                    error_message=result.error_message,
                )
                self.repository.upsert_module_with_objects(
                    file_id=file_id,
                    source_package_id=candidate.source_package_id,
                    module_name=result.module_name,
                    vendor=candidate.vendor,
                    status=result.status,
                    compiled_path=compiled_path,
                    objects=result.objects,
                    dependencies=result.imports,
                    missing_dependencies=result.missing_dependencies,
                    error_message=result.error_message,
                )
            return MibImportItem(str(candidate.source_path), str(candidate.stored_path), candidate.file_hash, result.status, result.module_name, result.missing_dependencies, result.error_message)
        except Exception as exc:
            return MibImportItem(str(candidate.source_path), str(candidate.stored_path), candidate.file_hash, "failed", candidate.module_name, error_message=f"导入失败：{exc}")

    def _import_reference(self, source: Path, *, vendor: str, product_line: str, product_name: str, software_version: str) -> MibImportItem:
        try:
            from netconsole.services.mib_product_reference_service import MibProductReferenceService

            report = MibProductReferenceService(self.paths, self.repository).import_file(source, vendor=vendor, product_line=product_line, product_name=product_name, software_version=software_version)
            return MibImportItem(str(source), report.stored_path, report.file_hash, report.status, "产品 MIB 参考表", error_message=report.error_message, duplicate_file_id=report.duplicate_reference_id)
        except Exception as exc:
            return MibImportItem(str(source), "", "", "failed", error_message=f"产品参考表导入失败：{exc}")

    def _write_report(self, items: list[MibImportItem]) -> MibImportReport:
        from datetime import datetime

        report_dir = self.paths.global_mib_reports_dir()
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"mib_import_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        payload = {
            "items": [item.__dict__ for item in items],
            "total": len(items),
            "imported": sum(1 for item in items if item.status in {"compiled", "missing_dependencies", "reference_imported", "duplicate_reindexed"}),
            "duplicated": sum(1 for item in items if item.status in {"duplicate", "duplicate_reindexed"}),
            "failed": sum(1 for item in items if item.status == "failed"),
        }
        report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return MibImportReport(
            status="success" if payload["failed"] == 0 else "partial_success",
            total=int(payload["total"]),
            imported=int(payload["imported"]),
            duplicated=int(payload["duplicated"]),
            failed=int(payload["failed"]),
            report_path=str(report_path),
            items=items,
        )


def identify_module_name(path: Path) -> str:
    try:
        text = _read_text(path)
    except Exception:
        return ""
    match = MODULE_RE.search(text)
    return match.group(1) if match else ""


def _detect_h3c_package(path: Path) -> H3cPackageMeta:
    name = path.name
    match = re.search(r"H3C-(V5|V9-V7|V7-V9)-Comware_MIB-(\d{8})", name, re.IGNORECASE)
    if not match:
        return H3cPackageMeta()
    version_token = match.group(1).upper()
    version_line = "V5" if version_token == "V5" else "V7/V9"
    package_version = match.group(2)
    package_name = f"H3C-Comware-{'V5' if version_line == 'V5' else 'V7V9'}-{package_version}"
    return H3cPackageMeta(
        vendor="H3C",
        product_line="Comware",
        version_line=version_line,
        package_version=package_version,
        source_type="official_comware_mib_package",
        package_name=package_name,
    )


def _read_text(path: Path) -> str:
    return read_text_with_fallback(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def unique_target(path: Path) -> Path:
    if not path.exists():
        return path
    index = 2
    while True:
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
        index += 1
from netconsole.utils.text_encoding import read_text_with_fallback
