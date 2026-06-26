from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from netconsole.models.online_mr_models import OnlineMrConnectionConfig


@dataclass
class SSHClient:
    config: OnlineMrConnectionConfig
    connection_factory: Any | None = None
    command_timeout: int | None = None
    connection: Any | None = None
    state: dict[str, object] = field(default_factory=dict)

    def connect(self) -> None:
        if self.connection is not None:
            return
        from netconsole.services.online_mr_collector import NetmikoShellConnection

        factory = self.connection_factory or (lambda cfg: NetmikoShellConnection(cfg))
        self.connection = factory(self.config)
        self.state["connected"] = True

    def execute(self, command: str, timeout: int | None = None) -> str:
        if self.connection is None:
            self.connect()
        if self.connection is None:
            raise RuntimeError("SSH connection is not available")
        return self.connection.send_command(command, timeout or self.command_timeout or self.config.command_timeout)

    def execute_stream(self, command: str) -> Iterator[str]:
        output = self.execute(command)
        yield from output.splitlines()

    def close(self) -> None:
        if self.connection is not None:
            try:
                self.connection.close()
            finally:
                self.connection = None
                self.state["connected"] = False
