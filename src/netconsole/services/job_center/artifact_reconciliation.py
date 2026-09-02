from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID

from netconsole.core.paths import PathResolver
from netconsole.core.sites import SiteManager


class ArtifactAvailability(str, Enum):
    AVAILABLE = "AVAILABLE"
    MISSING = "MISSING"
    INVALID = "INVALID"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True)
class ArtifactReconciliation:
    artifact_available: bool
    artifact_availability: ArtifactAvailability
    missing_reason: str | None
    downloadable: bool
    openable: bool = False
    parent_directory_openable: bool = False


@dataclass(frozen=True)
class ArtifactTaskBinding:
    task_id: str
    task_type: str
    owner: str
    status: str
    result: Mapping[str, Any]
    downloadable: bool


def managed_artifact_source_root(
    paths: PathResolver,
    site_id: str,
    source: str,
) -> Path:
    roots = {
        "ac_extension_export": paths.trackside_ap_outputs_dir(site_id),
        "ac_omnipeek_export": paths.trackside_ap_outputs_dir(site_id),
        "ac_fit_ap_resource_export": paths.trackside_ap_outputs_dir(site_id),
        "command_reference_export": paths.site_files_dir(site_id)
        / "command_reference",
        "device_csv_export": paths.site_files_dir(site_id) / "web_artifacts",
        "online_mr_report": paths.online_mr_root(site_id),
        "mesh_analysis_report": paths.site_mesh_root(site_id),
        "mesh_link_detail_export": paths.site_mesh_root(site_id),
        "mesh_raw_link_export": paths.site_mesh_root(site_id),
        "mesh_ap_coverage_export": paths.site_mesh_root(site_id),
        "switch_vendor_sample": paths.trackside_ap_outputs_dir(site_id)
        / "vendor_samples",
        "trackside_ap_business": paths.trackside_ap_outputs_dir(site_id),
        "trackside_ap_base": paths.trackside_ap_outputs_dir(site_id),
        "trackside_ap_rename_commands": paths.trackside_ap_outputs_dir(site_id),
        "trackside_ap_plan": paths.trackside_ap_outputs_dir(site_id),
        "system_logs_current": paths.site_files_dir(site_id)
        / "system_maintenance"
        / "outputs",
        "system_logs_all": paths.site_files_dir(site_id)
        / "system_maintenance"
        / "outputs",
        "system_open_source_txt": paths.site_files_dir(site_id)
        / "system_maintenance"
        / "outputs",
        "system_open_source_xlsx": paths.site_files_dir(site_id)
        / "system_maintenance"
        / "outputs",
    }
    try:
        return roots[source]
    except KeyError as exc:
        raise ValueError("Artifact 来源不受支持") from exc


class ArtifactReconciliationService:
    """Read-only reconciliation between task metadata and managed files."""

    def __init__(self, paths: PathResolver) -> None:
        self.paths = paths

    def reconcile_task(
        self,
        site_id: str,
        binding: ArtifactTaskBinding,
        *,
        verify_digest: bool = False,
    ) -> ArtifactReconciliation:
        if binding.status.upper() != "COMPLETED":
            return self._not_applicable()
        if self._is_managed_web_artifact(binding.result):
            return self.reconcile_managed_artifact(
                site_id,
                task_id=binding.task_id,
                task_type=binding.task_type,
                owner=binding.owner,
                result=binding.result,
                downloadable=binding.downloadable,
                verify_digest=verify_digest,
            )
        if binding.downloadable:
            return ArtifactReconciliation(
                artifact_available=True,
                artifact_availability=ArtifactAvailability.AVAILABLE,
                missing_reason=None,
                downloadable=True,
            )
        return self._not_applicable()

    def reconcile_site(
        self,
        site_id: str,
        bindings: Iterable[ArtifactTaskBinding],
        *,
        verify_digest: bool = False,
    ) -> dict[str, ArtifactReconciliation]:
        return {
            binding.task_id: self.reconcile_task(
                site_id,
                binding,
                verify_digest=verify_digest,
            )
            for binding in bindings
        }

    def reconcile_all(
        self,
        sites: Mapping[str, Iterable[ArtifactTaskBinding]],
        *,
        verify_digest: bool = False,
    ) -> dict[str, dict[str, ArtifactReconciliation]]:
        return {
            site_id: self.reconcile_site(
                site_id,
                bindings,
                verify_digest=verify_digest,
            )
            for site_id, bindings in sites.items()
        }

    def reconcile_managed_artifact(
        self,
        site_id: str,
        *,
        task_id: str,
        task_type: str,
        owner: str,
        result: Mapping[str, Any],
        downloadable: bool,
        verify_digest: bool = False,
        manifest: Mapping[str, Any] | None = None,
    ) -> ArtifactReconciliation:
        try:
            selected_site = SiteManager(self.paths).validate_site_name(site_id)
        except ValueError:
            return self._invalid("Artifact 归属信息无效")
        raw_site_root = self.paths.site_dir(selected_site)
        site_root = raw_site_root.resolve()
        sites_root = self.paths.sites_dir.resolve()
        if raw_site_root.is_symlink() or not self._within(site_root, sites_root):
            return self._invalid("局点数据目录不在受控数据根")
        if not site_root.is_dir():
            return self._missing("局点数据目录已不存在")

        artifact_id = str(result.get("artifact_id") or "")
        try:
            artifact_id = str(UUID(artifact_id))
        except ValueError:
            return self._invalid("Artifact 标识无效")

        manifest_root = (
            self.paths.rail_transit_root(selected_site)
            / "web_artifacts"
            / "manifests"
        ).resolve()
        manifest_path = (manifest_root / f"{artifact_id}.json").resolve()
        if not self._within(manifest_path, manifest_root):
            return self._invalid("Artifact 清单路径无效")
        if manifest is None:
            if manifest_path.is_symlink():
                return self._invalid("Artifact 清单不是普通文件")
            try:
                loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                return self._missing("Artifact 清单已不存在")
            except (OSError, TypeError, json.JSONDecodeError):
                return self._invalid("Artifact 清单无法读取")
            if not isinstance(loaded, dict):
                return self._invalid("Artifact 清单无效")
            manifest = loaded

        expected = {
            "artifact_id": artifact_id,
            "site_id": selected_site,
            "task_id": task_id,
            "task_type": task_type,
            "owner": owner,
            "task_source": "local",
            "source": str(result.get("artifact_source") or ""),
            "artifact_type": str(result.get("artifact_type") or ""),
        }
        if any(str(manifest.get(key) or "") != value for key, value in expected.items()):
            return self._invalid("Artifact 归属校验失败")
        if manifest.get("completed") is not True:
            return self._invalid("Artifact 清单尚未完成")

        try:
            path = self._validated_output(selected_site, manifest)
        except ValueError as exc:
            return self._invalid(str(exc))
        if path.is_symlink():
            return self._invalid("Artifact 文件不是普通文件")
        try:
            stat = path.stat()
        except FileNotFoundError:
            return self._missing("输出文件已不存在，可能已在资源管理器中删除。")
        except OSError:
            return self._invalid("Artifact 文件无法读取")
        if not path.is_file():
            return self._invalid("Artifact 文件不是普通文件")

        try:
            expected_size = int(manifest.get("size_bytes") or -1)
            result_size = int(result.get("size_bytes") or -1)
        except (TypeError, ValueError):
            return self._invalid("Artifact 大小锚点无效")
        manifest_digest = str(manifest.get("sha256") or "").casefold()
        result_digest = str(result.get("sha256") or "").casefold()
        if (
            expected_size < 0
            or stat.st_size != expected_size
            or result_size != expected_size
            or not self._valid_digest(manifest_digest)
            or result_digest != manifest_digest
            or str(result.get("artifact_name") or "")
            != str(manifest.get("display_name") or manifest.get("file_name") or "")
        ):
            return self._invalid("Artifact 完整性锚点校验失败")
        if verify_digest and self._digest(path) != manifest_digest:
            return self._invalid("Artifact 完整性校验失败")
        return ArtifactReconciliation(
            artifact_available=True,
            artifact_availability=ArtifactAvailability.AVAILABLE,
            missing_reason=None,
            downloadable=downloadable,
        )

    def source_root(self, site_id: str, source: str) -> Path:
        return managed_artifact_source_root(self.paths, site_id, source)

    def _validated_output(
        self,
        site_id: str,
        manifest: Mapping[str, Any],
    ) -> Path:
        relative = Path(str(manifest.get("relative_path") or ""))
        if relative.is_absolute():
            raise ValueError("Artifact 清单路径无效")
        path = (self.paths.site_dir(site_id).resolve() / relative).resolve()
        root = self.source_root(site_id, str(manifest.get("source") or "")).resolve()
        if not self._within(path, root) or path == root:
            raise ValueError("Artifact 路径不在受控目录")
        file_name = str(manifest.get("file_name") or "")
        artifact_type = str(manifest.get("artifact_type") or "").casefold()
        if (
            path.name != file_name
            or path.suffix.casefold().removeprefix(".") != artifact_type
        ):
            raise ValueError("Artifact 名称或类型校验失败")
        return path

    @staticmethod
    def _is_managed_web_artifact(result: Mapping[str, Any]) -> bool:
        required = (
            "artifact_id",
            "artifact_source",
            "artifact_type",
            "artifact_name",
            "sha256",
            "size_bytes",
        )
        if not all(key in result for key in required):
            return False
        try:
            UUID(str(result.get("artifact_id") or ""))
        except ValueError:
            return False
        return True

    @staticmethod
    def _within(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
        except ValueError:
            return False
        return True

    @staticmethod
    def _valid_digest(value: str) -> bool:
        return len(value) == 64 and all(char in "0123456789abcdef" for char in value)

    @staticmethod
    def _digest(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _not_applicable() -> ArtifactReconciliation:
        return ArtifactReconciliation(
            artifact_available=False,
            artifact_availability=ArtifactAvailability.NOT_APPLICABLE,
            missing_reason=None,
            downloadable=False,
        )

    @staticmethod
    def _missing(reason: str) -> ArtifactReconciliation:
        return ArtifactReconciliation(
            artifact_available=False,
            artifact_availability=ArtifactAvailability.MISSING,
            missing_reason=reason,
            downloadable=False,
        )

    @staticmethod
    def _invalid(reason: str) -> ArtifactReconciliation:
        return ArtifactReconciliation(
            artifact_available=False,
            artifact_availability=ArtifactAvailability.INVALID,
            missing_reason=reason,
            downloadable=False,
        )
