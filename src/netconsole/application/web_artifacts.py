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


_SAFE_STEM = re.compile(r"[^0-9A-Za-z._\u4e00-\u9fff-]+")
_ALLOWED_SUFFIXES = {".xlsx", ".csv", ".zip", ".pdf", ".md"}


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
    output_path: Path


class WebArtifactStore:
    """Web 报告的随机标识、完整性清单和受控下载边界。"""

    def __init__(self, paths: PathResolver) -> None:
        self.paths = paths

    def reserve(
        self,
        *,
        site_id: str,
        owner: str,
        source: str,
        artifact_type: str,
        task_id: str,
        output_root: Path,
        preferred_name: str,
    ) -> ReservedWebArtifact:
        site_id = self._site(site_id)
        root = self._controlled_root(site_id, source, output_root)
        suffix = Path(preferred_name).suffix.casefold() or ".xlsx"
        if suffix not in _ALLOWED_SUFFIXES:
            raise WebArtifactError("报告文件类型不受支持")
        artifact_id = str(uuid4())
        stem = _SAFE_STEM.sub("_", Path(preferred_name).stem).strip(" ._") or "report"
        root.mkdir(parents=True, exist_ok=True)
        output_path = (root / f"{stem}-{artifact_id[:12]}{suffix}").resolve()
        self._require_within(output_path, root)
        manifest = {
            "artifact_id": artifact_id,
            "site_id": site_id,
            "owner": str(owner),
            "source": str(source),
            "artifact_type": str(artifact_type),
            "task_id": str(task_id),
            "relative_path": output_path.relative_to(self.paths.site_dir(site_id).resolve()).as_posix(),
            "completed": False,
            "sha256": "",
            "size_bytes": 0,
            "file_name": output_path.name,
        }
        self._write_manifest(site_id, artifact_id, manifest)
        return ReservedWebArtifact(
            artifact_id=artifact_id,
            site_id=site_id,
            owner=str(owner),
            source=str(source),
            artifact_type=str(artifact_type),
            task_id=str(task_id),
            output_path=output_path,
        )

    def complete(self, reservation: ReservedWebArtifact) -> dict[str, object]:
        manifest = self._read_manifest(reservation.site_id, reservation.artifact_id)
        expected = {
            "artifact_id": reservation.artifact_id,
            "site_id": reservation.site_id,
            "owner": reservation.owner,
            "source": reservation.source,
            "artifact_type": reservation.artifact_type,
            "task_id": reservation.task_id,
        }
        if any(str(manifest.get(key) or "") != value for key, value in expected.items()):
            raise WebArtifactError("报告清单归属校验失败")
        path = self._validated_output(manifest)
        if not path.is_file() or path.is_symlink():
            raise WebArtifactError("报告输出不存在或不是普通文件")
        digest, size = self._digest(path)
        manifest.update(completed=True, sha256=digest, size_bytes=size)
        self._write_manifest(reservation.site_id, reservation.artifact_id, manifest)
        return manifest

    def fail(self, reservation: ReservedWebArtifact) -> None:
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
        try:
            self._manifest_path(reservation.site_id, reservation.artifact_id).unlink(missing_ok=True)
        except OSError:
            pass

    def task_metadata(
        self,
        site_id: str,
        task_id: str,
        *,
        owner: str,
        sources: set[str],
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
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict) or data.get("task_id") != task_id:
                continue
            try:
                if path.resolve() != self._manifest_path(site_id, str(data.get("artifact_id") or "")):
                    continue
            except (ValueError, WebArtifactError):
                continue
            if data.get("site_id") != site_id or data.get("owner") != owner or data.get("source") not in sources:
                continue
            if data.get("completed") is True:
                try:
                    output = self._validated_output(data)
                    digest, size = self._digest(output)
                except (OSError, WebArtifactError):
                    continue
                if digest != data.get("sha256") or size != int(data.get("size_bytes") or -1):
                    continue
            return data
        return None

    def recover_task(
        self,
        site_id: str,
        task_id: str,
        *,
        owner: str,
        sources: set[str],
        succeeded: bool,
    ) -> bool:
        data = self.task_metadata(site_id, task_id, owner=owner, sources=sources)
        if data is None:
            return False
        if data.get("completed") is True and succeeded:
            return False
        try:
            reservation = self._reservation(data)
            if succeeded:
                self.complete(reservation)
            else:
                self.fail(reservation)
        except WebArtifactError:
            try:
                reservation = self._reservation(data)
            except WebArtifactError:
                return False
            self.fail(reservation)
        return True

    def open(
        self,
        *,
        site_id: str,
        artifact_id: str,
        owner: str,
        source: str,
        artifact_type: str,
    ) -> tuple[Path, str, dict[str, object]]:
        site_id = self._site(site_id)
        manifest = self._read_manifest(site_id, artifact_id)
        expected = {
            "site_id": site_id,
            "owner": owner,
            "source": source,
            "artifact_type": artifact_type,
        }
        if any(str(manifest.get(key) or "") != value for key, value in expected.items()):
            raise WebArtifactError("报告归属校验失败")
        if manifest.get("completed") is not True:
            raise WebArtifactError("报告尚未完成")
        path = self._validated_output(manifest)
        if not path.is_file() or path.is_symlink():
            raise WebArtifactError("报告文件不存在")
        digest, size = self._digest(path)
        if digest != manifest.get("sha256") or size != int(manifest.get("size_bytes") or -1):
            raise WebArtifactError("报告完整性校验失败")
        return path, str(manifest.get("file_name") or path.name), manifest

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
            output_path=output,
        )

    def _controlled_root(self, site_id: str, source: str, requested: Path) -> Path:
        allowed = self._source_root(site_id, source).resolve()
        resolved = requested.resolve()
        self._require_within(resolved, allowed, allow_equal=True)
        return resolved

    def _source_root(self, site_id: str, source: str) -> Path:
        roots = {
            "ac_extension_export": self.paths.trackside_ap_outputs_dir(site_id),
            "online_mr_report": self.paths.online_mr_root(site_id),
            "mesh_analysis_report": self.paths.site_mesh_root(site_id),
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


__all__ = ["ReservedWebArtifact", "WebArtifactError", "WebArtifactStore"]
