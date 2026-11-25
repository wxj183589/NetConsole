from datetime import datetime
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from netconsole.backend.api.local_network_services_router import router
from netconsole.services.local_network_services.log_query import query_service_logs


LINES = [
    "2026-11-25 10:00:00,001 INFO started HTTP",
    "2026-11-25 10:01:00,002 ERROR Port unavailable",
    "provider output without timestamp",
    "2026-99-25 10:01:00,002 WARNING malformed time",
]


def test_service_log_filters_preserve_raw_and_unknown_lines():
    result = query_service_logs(LINES)
    assert result["lines"] == LINES
    assert result["bounded_tail"] is True
    assert result["entries"][2]["time"] == ""
    assert result["entries"][3]["time"] == ""
    assert query_service_logs(LINES, keyword="PORT", level="ERROR")["lines"] == [LINES[1]]
    assert query_service_logs(LINES, level="INFO")["entries"][0]["message"] == "started HTTP"
    assert query_service_logs(LINES, since=datetime(2026, 11, 25, 10, 0, 30))["lines"] == [LINES[1]]
    assert query_service_logs(LINES, until=datetime(2026, 11, 25, 10, 0, 30))["lines"] == [LINES[0]]


def test_service_log_api_contract_and_query_validation():
    calls = []

    def logs(kind, *, history=False):
        calls.append((kind, history))
        return LINES

    app = FastAPI()
    app.state.local_network_services = SimpleNamespace(logs=logs)
    app.include_router(router)
    with TestClient(app) as client:
        base = "/local-network-services/http/logs"
        response = client.get(base)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["lines"] == LINES
        result = client.get(base, params={"keyword": "port", "level": "ERROR", "history": "true"}).json()
        assert result["lines"] == [LINES[1]]
        assert result["scanned_lines"] == 4
        assert result["history"] is True
        assert result["line_limit"] == 1500
        assert calls[-1] == ("http", True)
        for params in [
            {"since": "invalid"}, {"level": "TRACE"}, {"keyword": "x" * 501},
            {"since": "2026-11-25T11:00:00Z", "until": "2026-11-25T10:00:00Z"},
        ]:
            assert client.get(base, params=params).status_code == 422
        assert client.get("/local-network-services/unknown/logs").status_code == 422
