from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any


@dataclass(frozen=True, init=False)
class ExportJob:
    job_id: str
    job_type: str
    site_name: str
    output_path: str
    params: dict[str, Any] = field(default_factory=dict)
    db_path: str = ""
    tmp_path: str = ""
    cancel_path: str = ""
    filters: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)

    def __init__(
        self,
        job_id: str,
        job_type: str = "",
        site_name: str = "",
        output_path: str = "",
        params: dict[str, Any] | None = None,
        db_path: str = "",
        tmp_path: str = "",
        cancel_path: str = "",
        filters: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        export_type: str = "",
    ) -> None:
        object.__setattr__(self, "job_id", str(job_id or ""))
        object.__setattr__(self, "job_type", str(job_type or export_type or ""))
        object.__setattr__(self, "site_name", str(site_name or ""))
        object.__setattr__(self, "output_path", str(output_path or ""))
        object.__setattr__(self, "params", dict(params or {}))
        object.__setattr__(self, "db_path", str(db_path or ""))
        object.__setattr__(self, "tmp_path", str(tmp_path or ""))
        object.__setattr__(self, "cancel_path", str(cancel_path or ""))
        object.__setattr__(self, "filters", dict(filters or {}))
        object.__setattr__(self, "context", dict(context or {}))

    @property
    def export_type(self) -> str:
        return self.job_type

    def with_runtime_paths(self, *, tmp_path: str, cancel_path: str) -> "ExportJob":
        return replace(self, tmp_path=str(tmp_path), cancel_path=str(cancel_path))

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["export_type"] = self.job_type
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExportJob":
        return cls(
            job_id=str(data.get("job_id") or ""),
            job_type=str(data.get("job_type") or data.get("export_type") or ""),
            site_name=str(data.get("site_name") or ""),
            output_path=str(data.get("output_path") or ""),
            params=dict(data.get("params") or {}),
            db_path=str(data.get("db_path") or ""),
            tmp_path=str(data.get("tmp_path") or ""),
            cancel_path=str(data.get("cancel_path") or ""),
            filters=dict(data.get("filters") or {}),
            context=dict(data.get("context") or {}),
        )

    def validate(self) -> None:
        if not self.job_id:
            raise ValueError("导出任务缺少 job_id")
        if not self.job_type:
            raise ValueError("导出任务缺少 job_type")
        if not self.output_path:
            raise ValueError("导出任务缺少 output_path")
        if not self.tmp_path:
            raise ValueError("导出任务缺少 tmp_path")


def normalize_export_path(path: str | Path) -> str:
    return str(Path(path).expanduser().resolve())
