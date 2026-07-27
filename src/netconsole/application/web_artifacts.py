from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from netconsole.core.paths import PathResolver
from netconsole.core.sites import SiteManager
from netconsole.models.task_state import TaskState
from netconsole.services.job_center.task_application_service import TaskApplicationService


_SAFE_STEM = re.compile(r"[^0-9A-Za-z._\u4e00-\u9fff-]+")
_SAFE_CONTEXT = re.compile(r"[0-9A-Za-z_.:-]{1,160}\Z")
_ALLOWED_SUFFIXES = {".xlsx", ".csv", ".zip", ".pdf", ".md", ".txt", ".nam"}


class WebArtifactError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReservedWebArtifact:
    artifact_id: str
    site_id: str
    owner: str
    source: str
    artifact_type: str
    task_id: str
    task_type: str
    task_source: str
    output_path: Path
    display_name: str


class WebArtifactStore:
    """Web 报告的随机标识、完整性清单和受控下载边界。"""

    def __init__(self, paths: PathResolver, task_service: TaskApplicationService) -> None:
        self.paths = paths
        self.task_service = task_service

    def reserve(
        self,
        *,
        site_id: str,
        owner: str,
        source: str,
        artifact_type: str,
        task_id: str,
        task_type: str,
        output_root: Path,
        preferred_name: str,
        use_display_name_as_file_name: bool = False,
        context: dict[str, str] | None = None,
    ) -> ReservedWebArtifact:
        site_id = self._site(site_id)
        root = self._controlled_root(site_id, source, output_root)
        suffix = Path(preferred_name).suffix.casefold() or ".xlsx"
        if suffix not in _ALLOWED_SUFFIXES:
            raise WebArtifactError("报告文件类型不受支持")
        if str(artifact_type or "").casefold() != suffix.removeprefix("."):
            raise WebArtifactError("报告类型与文件扩展名不一致")
        task_type = str(task_type or "").strip()
        if not task_type:
            raise WebArtifactError("报告任务类型不能为空")
        artifact_id = str(uuid4())
        stem = _SAFE_STEM.sub("_", Path(preferred_name).stem).strip(" ._") or "report"
        root.mkdir(parents=True, exist_ok=True)
        display_name = f"{stem}{suffix}"
        output_path = (
            root / artifact_id / display_name
            if use_display_name_as_file_name
            else root / f"{stem}-{artifact_id[:12]}{suffix}"
        ).resolve()
        self._require_within(output_path, root)
        manifest = {
            "artifact_id": artifact_id,
            "site_id": site_id,
            "owner": str(owner),
            "source": str(source),
            "artifact_type": str(artifact_type),
            "task_id": str(task_id),
            "task_type": task_type,
            "task_source": "local",
            "relative_path": output_path.relative_to(self.paths.site_dir(site_id).resolve()).as_posix(),
            "completed": False,
            "sha256": "",
            "size_bytes": 0,
            "file_name": output_path.name,
            "display_name": display_name,
        }
        safe_context = {
            str(key): str(value)
            for key, value in dict(context or {}).items()
            if _SAFE_CONTEXT.fullmatch(str(key)) and _SAFE_CONTEXT.fullmatch(str(value))
        }
        if safe_context:
            manifest["context"] = safe_context
        self._write_manifest(site_id, artifact_id, manifest)
        return ReservedWebArtifact(
            artifact_id=artifact_id,
            site_id=site_id,
            owner=str(owner),
            source=str(source),
            artifact_type=str(artifact_type),
            task_id=str(task_id),
            task_type=task_type,
            task_source="local",
            output_path=output_path,
            display_name=display_name,
        )

    def online_mr_session_artifacts(
        self,
        site_id: str,
        session_id: str,
        *,
        owner: str,
        task_type: str,
    ) -> list[dict[str, object]]:
        """列出明确关联会话的报告；旧默认文件名仅作受控兼容。"""

        site_id = self._site(site_id)
        if not _SAFE_CONTEXT.fullmatch(str(session_id or "")):
            raise WebArtifactError("Online MR 会话标识无效")
        root = self._manifest_root(site_id)
        if not root.is_dir():
            return []
        result: list[dict[str, object]] = []
        legacy_prefix = f"{session_id}_online_mr-"
        for manifest_path in root.glob("*.json"):
            if manifest_path.is_symlink():
                continue
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    continue
                context = data.get("context")
                associated = (
                    isinstance(context, dict)
                    and context.get("kind") == "online_mr_session"
                    and context.get("session_id") == session_id
                )
                legacy = (
                    not context
                    and str(data.get("file_name") or "").startswith(legacy_prefix)
                )
                if not associated and not legacy:
                    continue
                if (
                    data.get("site_id") != site_id
                    or data.get("owner") != owner
                    or data.get("source") != "online_mr_report"
                    or data.get("task_type") != task_type
                    or data.get("task_source") != "local"
                ):
                    continue
                artifact_id = str(data.get("artifact_id") or "")
                if manifest_path.resolve() != self._manifest_path(site_id, artifact_id):
                    continue
                output = self._validated_output(data)
            except (
                KeyError,
                OSError,
                TypeError,
                ValueError,
                json.JSONDecodeError,
                WebArtifactError,
            ):
                continue
            result.append(
                {
                    "artifact_id": artifact_id,
                    "task_id": str(data.get("task_id") or ""),
                    "path": str(output),
                    "manifest_path": str(manifest_path.resolve()),
                    "completed": data.get("completed") is True,
                    "modified_at": output.stat().st_mtime if output.is_file() else 0.0,
                }
            )
        return sorted(
            result,
            key=lambda item: (float(item["modified_at"]), str(item["artifact_id"])),
            reverse=True,
        )

    def complete(self, reservation: ReservedWebArtifact) -> dict[str, object]:
        try:
            manifest = self._read_manifest(reservation.site_id, reservation.artifact_id)
            self._validate_reservation(manifest, reservation)
            task = self._trusted_task(manifest)
            if task.status is not TaskState.COMPLETED:
                raise WebArtifactError("报告所属任务尚未成功完成")
            path = self._validated_output(manifest)
            if not path.is_file() or path.is_symlink():
                raise WebArtifactError("报告输出不存在或不是普通文件")
            digest, size = self._digest(path)
            manifest.update(completed=True, sha256=digest, size_bytes=size)
            if isinstance(task.result, dict) and "row_count" in task.result:
                manifest["row_count"] = max(
                    0, int(task.result.get("row_count") or 0)
                )
            self._write_manifest(reservation.site_id, reservation.artifact_id, manifest)
            result = self._safe_task_result(manifest)
            self.task_service.finalize_artifact_result(
                reservation.task_id,
                site_name=reservation.site_id,
                owner=reservation.owner,
                source=reservation.task_source,
                task_type=reservation.task_type,
                result=result,
            )
            return manifest
        except WebArtifactError as exc:
            self._reject_task(reservation, str(exc))
            raise
        except (KeyError, OSError, TypeError, ValueError) as exc:
            self._reject_task(reservation, str(exc))
            raise WebArtifactError("报告完整性最终化失败") from exc

    def fail(self, reservation: ReservedWebArtifact, error_message: str = "报告不可用") -> None:
        for path in (
            reservation.output_path,
            reservation.output_path.with_name(f"{reservation.output_path.name}.tmp"),
            reservation.output_path.with_name(f"{reservation.output_path.name}.{reservation.task_id}.tmp"),
        ):
            try:
                if path.is_file() and not path.is_symlink():
                    path.unlink()
            except OSError:
                pass
        self._remove_empty_artifact_dir(reservation)
        try:
            self._manifest_path(reservation.site_id, reservation.artifact_id).unlink(missing_ok=True)
        except OSError:
            pass
        self._reject_task(reservation, error_message)

    def task_metadata(
        self,
        site_id: str,
        task_id: str,
        *,
        owner: str,
        source_task_types: dict[str, str],
    ) -> dict[str, object] | None:
        data = self._find_task_manifest(
            site_id,
            task_id,
            owner=owner,
            source_task_types=source_task_types,
        )
        if data is None:
            return None
        try:
            task = self._trusted_task(data)
            if data.get("completed") is True:
                self._validate_completed(data, task_result=task.result)
        except (OSError, TypeError, ValueError, WebArtifactError):
            return None
        return data

    def recover_task(
        self,
        site_id: str,
        task_id: str,
        *,
        owner: str,
        source_task_types: dict[str, str],
        succeeded: bool,
    ) -> bool:
        current = self.task_metadata(
            site_id,
            task_id,
            owner=owner,
            source_task_types=source_task_types,
        )
        if succeeded and current is not None and current.get("completed") is True:
            return False
        data = self._find_task_manifest(
            site_id,
            task_id,
            owner=owner,
            source_task_types=source_task_types,
        )
        if data is None:
            return False
        try:
            reservation = self._reservation(data)
            if succeeded:
                self.complete(reservation)
            else:
                self.fail(reservation, "报告所属任务未成功完成")
        except (OSError, WebArtifactError):
            try:
                reservation = self._reservation(data)
            except WebArtifactError:
                return False
            self.fail(reservation, "报告恢复校验失败")
        return True

    def open(
        self,
        *,
        site_id: str,
        artifact_id: str,
        owner: str,
        source: str,
        artifact_type: str,
        task_type: str,
    ) -> tuple[Path, str, dict[str, object]]:
        site_id = self._site(site_id)
        manifest = self._read_manifest(site_id, artifact_id)
        expected = {
            "site_id": site_id,
            "owner": owner,
            "source": source,
            "artifact_type": artifact_type,
            "task_type": task_type,
            "task_source": "local",
        }
        if any(str(manifest.get(key) or "") != value for key, value in expected.items()):
            raise WebArtifactError("报告归属校验失败")
        if manifest.get("completed") is not True:
            raise WebArtifactError("报告尚未完成")
        task = self._trusted_task(manifest)
        self._validate_completed(manifest, task_result=task.result)
        path = self._validated_output(manifest)
        return path, str(manifest.get("display_name") or manifest.get("file_name") or path.name), manifest

    def open_public(
        self,
        *,
        site_id: str,
        artifact_id: str,
    ) -> tuple[Path, str, dict[str, object]]:
        site_id = self._site(site_id)
        manifest = self._read_manifest(site_id, artifact_id)
        if manifest.get("completed") is not True:
            raise WebArtifactError("报告尚未完成")
        task = self._trusted_task(manifest)
        self._validate_completed(manifest, task_result=task.result)
        path = self._validated_output(manifest)
        display_name = str(
            manifest.get("display_name") or manifest.get("file_name") or path.name
        )
        return path, display_name, manifest

    def _find_task_manifest(
        self,
        site_id: str,
        task_id: str,
        *,
        owner: str,
        source_task_types: dict[str, str],
    ) -> dict[str, object] | None:
        site_id = self._site(site_id)
        root = self._manifest_root(site_id)
        if not root.is_dir():
            return None
        for path in root.glob("*.json"):
            if path.is_symlink():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict) or data.get("task_id") != task_id:
                    continue
                artifact_id = str(data.get("artifact_id") or "")
                if path.resolve() != self._manifest_path(site_id, artifact_id):
                    continue
                source = str(data.get("source") or "")
                expected_task_type = source_task_types.get(source)
                if (
                    data.get("site_id") != site_id
                    or data.get("owner") != owner
                    or not expected_task_type
                    or data.get("task_type") != expected_task_type
                    or data.get("task_source") != "local"
                ):
                    continue
                self._trusted_task(data)
            except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError, WebArtifactError):
                continue
            return data
        return None

    def _validate_reservation(
        self,
        manifest: dict[str, object],
        reservation: ReservedWebArtifact,
    ) -> None:
        expected = {
            "artifact_id": reservation.artifact_id,
            "site_id": reservation.site_id,
            "owner": reservation.owner,
            "source": reservation.source,
            "artifact_type": reservation.artifact_type,
            "task_id": reservation.task_id,
            "task_type": reservation.task_type,
            "task_source": reservation.task_source,
        }
        if any(str(manifest.get(key) or "") != value for key, value in expected.items()):
            raise WebArtifactError("报告清单归属校验失败")
        if self._validated_output(manifest) != reservation.output_path.resolve():
            raise WebArtifactError("报告清单输出路径校验失败")

    def _trusted_task(self, manifest: dict[str, object]):
        site_id = self._site(str(manifest.get("site_id") or ""))
        task_id = str(manifest.get("task_id") or "")
        snapshot = self.task_service.repository(site_id).get(task_id)
        if snapshot is None:
            raise WebArtifactError("报告所属任务不存在")
        if (
            snapshot.site_name != site_id
            or snapshot.owner != str(manifest.get("owner") or "")
            or snapshot.source != str(manifest.get("task_source") or "")
            or snapshot.task_type != str(manifest.get("task_type") or "")
        ):
            raise WebArtifactError("报告所属任务归属校验失败")
        return snapshot

    def _validate_completed(self, manifest: dict[str, object], *, task_result: dict[str, object]) -> None:
        if task_result != self._safe_task_result(manifest):
            raise WebArtifactError("报告任务结果锚点校验失败")
        path = self._validated_output(manifest)
        if not path.is_file() or path.is_symlink():
            raise WebArtifactError("报告文件不存在")
        digest, size = self._digest(path)
        if digest != manifest.get("sha256") or size != int(manifest.get("size_bytes") or -1):
            raise WebArtifactError("报告完整性校验失败")

    @staticmethod
    def _safe_task_result(manifest: dict[str, object]) -> dict[str, object]:
        result = {
            "artifact_id": str(manifest.get("artifact_id") or ""),
            "artifact_source": str(manifest.get("source") or ""),
            "artifact_type": str(manifest.get("artifact_type") or ""),
            "artifact_name": str(
                manifest.get("display_name") or manifest.get("file_name") or ""
            ),
            "sha256": str(manifest.get("sha256") or ""),
            "size_bytes": int(manifest.get("size_bytes") or 0),
        }
        if "row_count" in manifest:
            result["row_count"] = max(0, int(manifest.get("row_count") or 0))
        return result

    def _reject_task(self, reservation: ReservedWebArtifact, error_message: str) -> None:
        self.task_service.reject_artifact_result(
            reservation.task_id,
            site_name=reservation.site_id,
            owner=reservation.owner,
            source=reservation.task_source,
            task_type=reservation.task_type,
            error_message=error_message,
        )

    def _validated_output(self, manifest: dict[str, object]) -> Path:
        site_id = self._site(str(manifest.get("site_id") or ""))
        source = str(manifest.get("source") or "")
        site_root = self.paths.site_dir(site_id).resolve()
        relative = Path(str(manifest.get("relative_path") or ""))
        if relative.is_absolute():
            raise WebArtifactError("报告清单路径无效")
        path = (site_root / relative).resolve()
        root = self._source_root(site_id, source).resolve()
        self._require_within(path, root)
        file_name = str(manifest.get("file_name") or "")
        artifact_type = str(manifest.get("artifact_type") or "").casefold()
        if path.name != file_name or path.suffix.casefold().removeprefix(".") != artifact_type:
            raise WebArtifactError("报告名称或类型校验失败")
        return path

    def _reservation(self, manifest: dict[str, object]) -> ReservedWebArtifact:
        artifact_id = str(manifest.get("artifact_id") or "")
        try:
            artifact_id = str(UUID(artifact_id))
            output = self._validated_output(manifest)
        except (ValueError, WebArtifactError) as exc:
            raise WebArtifactError("报告清单无效") from exc
        return ReservedWebArtifact(
            artifact_id=artifact_id,
            site_id=self._site(str(manifest.get("site_id") or "")),
            owner=str(manifest.get("owner") or ""),
            source=str(manifest.get("source") or ""),
            artifact_type=str(manifest.get("artifact_type") or ""),
            task_id=str(manifest.get("task_id") or ""),
            task_type=str(manifest.get("task_type") or ""),
            task_source=str(manifest.get("task_source") or ""),
            output_path=output,
            display_name=str(manifest.get("display_name") or manifest.get("file_name") or ""),
        )

    def _controlled_root(self, site_id: str, source: str, requested: Path) -> Path:
        allowed = self._source_root(site_id, source).resolve()
        resolved = requested.resolve()
        self._require_within(resolved, allowed, allow_equal=True)
        return resolved

    def _source_root(self, site_id: str, source: str) -> Path:
        roots = {
            "ac_extension_export": self.paths.trackside_ap_outputs_dir(site_id),
            "ac_omnipeek_export": self.paths.trackside_ap_outputs_dir(site_id),
            "command_reference_export": self.paths.site_files_dir(site_id) / "command_reference",
            "device_csv_export": self.paths.site_files_dir(site_id) / "web_artifacts",
            "online_mr_report": self.paths.online_mr_root(site_id),
            "mesh_analysis_report": self.paths.site_mesh_root(site_id),
            "mesh_link_detail_export": self.paths.site_mesh_root(site_id),
            "trackside_ap_business": self.paths.trackside_ap_outputs_dir(site_id),
            "trackside_ap_base": self.paths.trackside_ap_outputs_dir(site_id),
            "trackside_ap_rename_commands": self.paths.trackside_ap_outputs_dir(site_id),
            "trackside_ap_plan": self.paths.trackside_ap_outputs_dir(site_id),
            "system_logs_current": self.paths.site_files_dir(site_id) / "system_maintenance" / "outputs",
            "system_logs_all": self.paths.site_files_dir(site_id) / "system_maintenance" / "outputs",
            "system_open_source_txt": self.paths.site_files_dir(site_id) / "system_maintenance" / "outputs",
            "system_open_source_xlsx": self.paths.site_files_dir(site_id) / "system_maintenance" / "outputs",
        }
        try:
            return roots[source]
        except KeyError as exc:
            raise WebArtifactError("报告来源不受支持") from exc

    def _manifest_root(self, site_id: str) -> Path:
        return self.paths.rail_transit_root(site_id) / "web_artifacts" / "manifests"

    def _manifest_path(self, site_id: str, artifact_id: str) -> Path:
        artifact_id = str(UUID(str(artifact_id)))
        root = self._manifest_root(self._site(site_id)).resolve()
        path = (root / f"{artifact_id}.json").resolve()
        self._require_within(path, root)
        return path

    def _read_manifest(self, site_id: str, artifact_id: str) -> dict[str, object]:
        try:
            data = json.loads(self._manifest_path(site_id, artifact_id).read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise WebArtifactError("报告清单不存在") from exc
        if not isinstance(data, dict):
            raise WebArtifactError("报告清单无效")
        return data

    def _write_manifest(self, site_id: str, artifact_id: str, data: dict[str, object]) -> None:
        path = self._manifest_path(site_id, artifact_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)

    def _site(self, site_id: str) -> str:
        try:
            value = SiteManager(self.paths).validate_site_name(str(site_id or ""))
        except ValueError as exc:
            raise WebArtifactError("局点标识无效") from exc
        site_root = self.paths.site_dir(value).resolve()
        self._require_within(site_root, self.paths.sites_dir.resolve())
        if not site_root.is_dir():
            raise WebArtifactError("局点不存在")
        return value

    @staticmethod
    def _require_within(path: Path, root: Path, *, allow_equal: bool = False) -> None:
        if allow_equal and path == root:
            return
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise WebArtifactError("路径不在受控目录") from exc
        if path == root:
            raise WebArtifactError("文件路径不能等于受控目录")

    @staticmethod
    def _digest(path: Path) -> tuple[str, int]:
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
        return digest.hexdigest(), size

    @staticmethod
    def _remove_empty_artifact_dir(reservation: ReservedWebArtifact) -> None:
        parent = reservation.output_path.parent
        if parent.name != reservation.artifact_id:
            return
        try:
            parent.rmdir()
        except OSError:
            pass


__all__ = ["ReservedWebArtifact", "WebArtifactError", "WebArtifactStore"]
