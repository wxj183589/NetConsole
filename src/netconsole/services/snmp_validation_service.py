from __future__ import annotations

from netconsole.models.snmp_models import SnmpProfile, SnmpQueryResult
from netconsole.services.snmp_client import SnmpClient


class SnmpValidationService:
    def __init__(self, client: SnmpClient | None = None) -> None:
        self.client = client or SnmpClient()

    def validate_probe(self, profile: SnmpProfile, probe_oid: str, *, method: str = "Get", max_rows: int = 20, cancel_checker=None) -> SnmpQueryResult:
        if method.lower() == "get":
            return self.client.get(profile, probe_oid)
        if method.lower() == "walk":
            return self.client.walk(profile, probe_oid, max_rows=max_rows, cancel_checker=cancel_checker)
        return self.client.bulk_walk(profile, probe_oid, max_rows=max_rows, cancel_checker=cancel_checker)

