from __future__ import annotations

from netconsole.adapters.h3c.h3c_lldp_parser import parse_lldp
from netconsole.adapters.h3c.h3c_optical_parser import parse_optical, parse_optical_repository
from netconsole.parsers.h3c.interface_parser import parse_interfaces


class H3CParser:
    def parse_interfaces(self, raw: str) -> list[dict[str, object | None]]:
        return parse_interfaces(raw)

    def parse_optical(self, raw: str) -> list[dict[str, object | None]]:
        return parse_optical(raw)

    def parse_optical_repository(self, raw: str) -> list[dict[str, object | None]]:
        return parse_optical_repository(raw)

    def parse_lldp(self, raw: str, verbose: str = "") -> list[dict[str, object | None]]:
        return parse_lldp(raw, verbose)
