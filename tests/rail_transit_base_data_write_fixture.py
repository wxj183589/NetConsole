from __future__ import annotations

from pathlib import Path

from rail_transit_base_data_fixture import build_rail_transit_base_data_fixture, mark_base_data_copy
from netconsole.core.paths import PathResolver
from netconsole.models.api.rail_transit_base_data import ImportPreviewRowDTO, MergePlanDTO
from netconsole.services.rail_transit.base_data_import_service import RailTransitBaseDataImportService
from netconsole.services.rail_transit.base_data_write_guard import BaseDataWriteGuard


def build_copy_service(
    tmp_path: Path,
    *,
    rollback_enabled: bool = True,
) -> tuple[PathResolver, Path, RailTransitBaseDataImportService]:
    paths, database = build_rail_transit_base_data_fixture(tmp_path)
    mark_base_data_copy(paths)
    guard = BaseDataWriteGuard(
        paths,
        feature_enabled=True,
        write_enabled=True,
        copy_write_enabled=True,
        rollback_enabled=rollback_enabled,
    )
    return paths, database, RailTransitBaseDataImportService(paths, guard=guard)


def create_plan(service: RailTransitBaseDataImportService, suffix: str = "50") -> MergePlanDTO:
    return service.build_merge_plan(
        site_id="demo",
        source_file_name="controlled-preview.json",
        source_file_sha256="d" * 64,
        source_type="import_file",
        rows=[
            ImportPreviewRowDTO(
                row_number=1,
                values={"ap_name": f"AP-Copy-{suffix}", "ap_mac_norm": f"0011223355{int(suffix):02d}"},
            )
        ],
    )


__all__ = ["build_copy_service", "create_plan"]
