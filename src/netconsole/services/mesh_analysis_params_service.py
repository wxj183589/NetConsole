from __future__ import annotations

from netconsole.core.paths import PathResolver
from netconsole.core.sites import SiteManager
from netconsole.models.mesh_analysis_params import (
    MESH_ANALYSIS_PARAMS_METADATA_KEY,
    MeshAnalysisParams,
    normalize_mesh_analysis_params,
)


_MESH_ANALYSIS_TEMPLATES = {
    "PIS": MeshAnalysisParams(
        main_link_switch_time_ms=4000,
        short_link_tolerance_ms=500,
        pingpong_tolerance_ms=500,
        pingpong_return_window_ms=500,
        service_type="PIS",
    ),
    "CBTC": MeshAnalysisParams(service_type="CBTC"),
}


def load_site_mesh_analysis_params(paths: PathResolver, site_name: str) -> MeshAnalysisParams:
    metadata = SiteManager(paths).load_site_metadata(site_name)
    return normalize_mesh_analysis_params(metadata.get(MESH_ANALYSIS_PARAMS_METADATA_KEY))


def save_site_mesh_analysis_params(paths: PathResolver, site_name: str, params: MeshAnalysisParams) -> None:
    SiteManager(paths).save_site_metadata(site_name, {MESH_ANALYSIS_PARAMS_METADATA_KEY: params.to_dict()})


def mesh_analysis_params_template(service_type: str) -> MeshAnalysisParams:
    value = str(service_type or "").strip().upper()
    try:
        return _MESH_ANALYSIS_TEMPLATES[value]
    except KeyError as exc:
        raise ValueError("不支持的 MESH 业务参数模板") from exc
