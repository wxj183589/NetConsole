from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from fastapi import APIRouter, HTTPException, Query, Request, status

from netconsole.backend.api.error_mapping import map_api_errors
from netconsole.core.sites import SiteManager
from netconsole.models.api.wireless_dashboard import (
    WirelessDashboardAgentsDTO,
    WirelessDashboardAlertsDTO,
    WirelessDashboardAnalysisDTO,
    WirelessDashboardDTO,
    WirelessDashboardFreshnessDTO,
    WirelessDashboardInfrastructureDTO,
    WirelessDashboardRecentOperationsDTO,
    WirelessDashboardSummaryDTO,
    WirelessDashboardTrainsDTO,
)
from netconsole.services.rail_transit.wireless_dashboard_query_service import WirelessDashboardQueryService


router = APIRouter(prefix="/rail-transit/wireless-dashboard", tags=["rail-transit-wireless-dashboard"])
T = TypeVar("T")


def _service(request: Request) -> WirelessDashboardQueryService:
    return request.app.state.wireless_dashboard_query_service


def _site_id(request: Request, supplied: str) -> str:
    value = supplied or _service(request).current_site_id()
    try:
        return SiteManager(request.app.state.paths).validate_site_name(value)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="局点标识无效") from exc


def _dashboard(request: Request, site_id: str) -> WirelessDashboardDTO:
    return _query(lambda: _service(request).get_dashboard(_site_id(request, site_id)))


def _query(callback: Callable[[], T]) -> T:
    with map_api_errors(
        "无线综合看板数据暂时不可读取",
        io_detail="无线综合看板数据暂时不可读取",
    ):
        return callback()


@router.get("", response_model=WirelessDashboardDTO)
def dashboard(request: Request, site_id: str = Query(default="", max_length=100)) -> WirelessDashboardDTO:
    return _dashboard(request, site_id)


@router.get("/summary", response_model=WirelessDashboardSummaryDTO)
def summary(request: Request, site_id: str = Query(default="", max_length=100)) -> WirelessDashboardSummaryDTO:
    return _query(lambda: _service(request).get_summary_section(_site_id(request, site_id)))


@router.get("/infrastructure", response_model=WirelessDashboardInfrastructureDTO)
def infrastructure(request: Request, site_id: str = Query(default="", max_length=100)) -> WirelessDashboardInfrastructureDTO:
    return _query(lambda: _service(request).get_infrastructure_section(_site_id(request, site_id)))


@router.get("/trains", response_model=WirelessDashboardTrainsDTO)
def trains(request: Request, site_id: str = Query(default="", max_length=100)) -> WirelessDashboardTrainsDTO:
    return _query(lambda: _service(request).get_trains_section(_site_id(request, site_id)))


@router.get("/alerts", response_model=WirelessDashboardAlertsDTO)
def alerts(request: Request, site_id: str = Query(default="", max_length=100)) -> WirelessDashboardAlertsDTO:
    return _query(lambda: _service(request).get_alerts_section(_site_id(request, site_id)))


@router.get("/freshness", response_model=WirelessDashboardFreshnessDTO)
def freshness(request: Request, site_id: str = Query(default="", max_length=100)) -> WirelessDashboardFreshnessDTO:
    return _query(lambda: _service(request).get_freshness_section(_site_id(request, site_id)))


@router.get("/recent-operations", response_model=WirelessDashboardRecentOperationsDTO)
def recent_operations(request: Request, site_id: str = Query(default="", max_length=100)) -> WirelessDashboardRecentOperationsDTO:
    return _query(lambda: _service(request).get_recent_operations_section(_site_id(request, site_id)))


@router.get("/analysis", response_model=WirelessDashboardAnalysisDTO)
def analysis(request: Request, site_id: str = Query(default="", max_length=100)) -> WirelessDashboardAnalysisDTO:
    return _query(lambda: _service(request).get_analysis_section(_site_id(request, site_id)))


@router.get("/agents", response_model=WirelessDashboardAgentsDTO)
def agents(request: Request, site_id: str = Query(default="", max_length=100)) -> WirelessDashboardAgentsDTO:
    return _query(lambda: _service(request).get_agents_section(_site_id(request, site_id)))


__all__ = ["router"]
