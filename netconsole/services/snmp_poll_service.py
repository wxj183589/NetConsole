from __future__ import annotations

from netconsole.repositories.site_snmp_repository import SiteSnmpRepository


class SnmpPollService:
    def __init__(self, repository: SiteSnmpRepository) -> None:
        self.repository = repository

    def list_jobs(self) -> list[dict[str, object]]:
        with self.repository.connect() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM snmp_poll_jobs ORDER BY updated_at DESC, id DESC").fetchall()]

