from __future__ import annotations

from typing import Mapping

from netconsole.core.paths import PathResolver
from netconsole.services.site_manager import SiteManager
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


def save_site_mesh_analysis_params(
    paths: PathResolver,
    site_name: str,
    params: MeshAnalysisParams | Mapping[str, object],
) -> None:
    """按当前局点身份原子保存完整 MESH 分析默认参数。"""

    normalized = normalize_mesh_analysis_params(params)
    validate_mesh_business_params(normalized)
    SiteManager(paths).save_site_metadata(site_name, {MESH_ANALYSIS_PARAMS_METADATA_KEY: normalized.to_dict()})


def validate_mesh_business_params(params: MeshAnalysisParams) -> None:
    from netconsole.services.mesh_business_statistics import effective_business_rules
    from netconsole.services.mesh_quality_analysis import load_default_rules

    effective_business_rules(params, load_default_rules())


def resolve_mesh_task_params(
    site_params: Mapping[str, object], override: Mapping[str, object] | None
) -> MeshAnalysisParams:
    values = dict(site_params)
    for key, value in (override or {}).items():
        if (
            key
            in {
                "rssi_good_threshold",
                "rssi_warning_threshold",
                "backup_available_threshold",
            }
            and value is None
        ):
            continue
        values[key] = value
    params = normalize_mesh_analysis_params(values)
    validate_mesh_business_params(params)
    return params


def mesh_analysis_params_template(service_type: str) -> MeshAnalysisParams:
    value = str(service_type or "").strip().upper()
    try:
        return _MESH_ANALYSIS_TEMPLATES[value]
    except KeyError as exc:
        raise ValueError("不支持的 MESH 业务参数模板") from exc
