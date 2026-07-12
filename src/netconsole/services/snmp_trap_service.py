from __future__ import annotations

from netconsole.repositories.site_snmp_repository import SiteSnmpRepository


class SnmpTrapService:
    def __init__(self, repository: SiteSnmpRepository) -> None:
        self.repository = repository

    def list_traps(self, limit: int = 500) -> list[dict[str, object]]:
        with self.repository.connect() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM snmp_traps ORDER BY trap_time DESC, id DESC LIMIT ?", (int(limit),)).fetchall()]

    def list_alert_rules(self) -> list[dict[str, object]]:
        with self.repository.connect() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM snmp_alert_rules ORDER BY rule_name").fetchall()]

