"""Site-owned, atomically versioned command template records."""

from __future__ import annotations

import json
from uuid import uuid4

from netconsole.core.atomic_file import atomic_write_bytes, locked_file
from netconsole.core.paths import PathResolver
from netconsole.core.site_identity import validate_site_name
from netconsole.models.task_snapshot import utc_now_iso


class TemplateRevisionConflict(ValueError):
    pass


class CommandTemplateRepository:
    def __init__(self, paths: PathResolver, site: str) -> None:
        site = validate_site_name(site)
        site_root = paths.get_site_root(site).resolve()
        candidate = paths.config_center_root(site) / "command-templates.json"
        lock = candidate.with_name(f".{candidate.name}.lock")
        if (
            not site_root.is_relative_to(paths.sites_dir.resolve())
            or not candidate.resolve().is_relative_to(site_root)
            or not lock.resolve().is_relative_to(site_root)
        ):
            raise ValueError("模板库路径越出局点边界")
        self.path = candidate

    def _read(self) -> dict[str, list[dict]]:
        try:
            with self.path.open("rb") as stream:
                contents = stream.read(8_000_001)
        except FileNotFoundError:
            return {}
        if len(contents) > 8_000_000:
            raise ValueError("模板库存储过大")
        data = json.loads(contents)
        if not isinstance(data, dict) or data.get("schema") != 1 or not isinstance(data.get("templates"), dict):
            raise ValueError("模板库存储格式无效")
        return data["templates"]

    def list_latest(self) -> list[dict]:
        return [versions[-1] for versions in self._read().values()]

    def list_versions(self, template_id: str) -> list[dict]:
        return list(reversed(self._read()[template_id]))

    def save(self, definition: dict, *, template_id: str | None, expected_version: int | None) -> dict:
        with locked_file(self.path):
            data = self._read()
            versions = []
            if template_id is None:
                if len(data) >= 100:
                    raise ValueError("局点最多保存 100 个命令模板")
                template_id = uuid4().hex
            else:
                versions = data[template_id]
                if expected_version != versions[-1]["version"]:
                    raise TemplateRevisionConflict("模板已有新版本，请重新加载")
                if versions[-1]["version"] >= 100:
                    raise ValueError("模板最多保存 100 个版本")
            record = {
                **definition, "template_id": template_id, "version": len(versions) + 1,
                "updated_at": utc_now_iso(),
            }
            data[template_id] = [*versions, record]
            content = json.dumps({"schema": 1, "templates": data}, ensure_ascii=False).encode("utf-8")
            if len(content) > 8_000_000:
                raise ValueError("模板库存储超出大小上限")
            atomic_write_bytes(self.path, content)
        return record
