from __future__ import annotations

from netconsole.core.paths import PathResolver
from netconsole.core.sites import SiteManager
from netconsole.models.mesh_analysis_params import (
    MESH_ANALYSIS_PARAMS_METADATA_KEY,
    MeshAnalysisParams,
    normalize_mesh_analysis_params,
)


def load_site_mesh_analysis_params(paths: PathResolver, site_name: str) -> MeshAnalysisParams:
    metadata = SiteManager(paths).load_site_metadata(site_name)
    return normalize_mesh_analysis_params(metadata.get(MESH_ANALYSIS_PARAMS_METADATA_KEY))


def save_site_mesh_analysis_params(paths: PathResolver, site_name: str, params: MeshAnalysisParams) -> None:
    SiteManager(paths).save_site_metadata(site_name, {MESH_ANALYSIS_PARAMS_METADATA_KEY: params.to_dict()})
