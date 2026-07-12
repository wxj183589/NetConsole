from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from netconsole.core.mr_collect.scheduler import MRClientScheduler
from netconsole.core.mr_collect.session import MRSession
from netconsole.core.mr_collect.ssh_client import SSHClient
from netconsole.models.online_mr_models import (
    INIT_COMMANDS,
    TASK_AP_RADIO_STATISTICS,
    TASK_CHANNEL_BUSY,
    TASK_COMMANDS,
    TASK_INTERFACE_RATE,
    TASK_MESH_LINK,
    TASK_SWITCH_HISTORY,
    OnlineMrConnectionConfig,
)


@dataclass
class MRCollectTask:
    mr_id: str
    device_ip: str
    username: str
    password: str
    mr_name: str = ""
    site: str = "demo"
    protocol: str = "SSH"
    port: int = 22
    interval_mesh: int = 1
    interval_channelbusy: int = 9
    interval_stats: int = 10
    interval_fping: int = 3
    enable_mesh: bool = True
    enable_channelbusy: bool = True
    enable_stats: bool = True

    def to_connection_config(self) -> OnlineMrConnectionConfig:
        from netconsole.models.online_mr_models import OnlineMrIntervals, OnlineMrTaskToggles

        name = self.mr_name or self.mr_id
        return OnlineMrConnectionConfig(
            site=self.site,
            mr_id=self.mr_id,
            mr_name=name,
            safe_mr_name=name,
            device_id=None,
            device_name=name,
            host=self.device_ip,
            protocol=self.protocol,
            port=self.port,
            username=self.username,
            password=self.password,
            intervals=OnlineMrIntervals(
                mesh_link=self.interval_mesh,
                channel_busy=self.interval_channelbusy,
                ap_radio_statistics=self.interval_stats,
            ),
            tasks=OnlineMrTaskToggles(
                mesh_link=self.enable_mesh,
                channel_busy=self.enable_channelbusy,
                ap_radio_statistics=self.enable_stats,
                switch_history=False,
                interface_rate=False,
            ),
        )


class MRCollectEngine:
    INIT_COMMANDS = INIT_COMMANDS
    LOOP_TASKS = (TASK_MESH_LINK,)
    SLOW_TASKS = (TASK_CHANNEL_BUSY, TASK_AP_RADIO_STATISTICS, TASK_SWITCH_HISTORY, TASK_INTERFACE_RATE)

    def __init__(
        self,
        connection_factory=None,
        clock: Callable[[], float] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self.connection_factory = connection_factory
        self.clock = clock or time.monotonic
        self.sleeper = sleeper or time.sleep
        self.sessions: dict[str, MRSession] = {}

    def start_session(self, task: MRCollectTask | OnlineMrConnectionConfig) -> MRSession:
        config = task.to_connection_config() if isinstance(task, MRCollectTask) else task
        session_id = f"{datetime.now():%Y%m%d_%H%M%S}_{id(config) & 0xFFFFFF:06x}"
        ssh = SSHClient(config, connection_factory=self.connection_factory)
        session = MRSession(session_id=session_id, mr_id=config.mr_id, ssh=ssh)
        self.sessions[session_id] = session
        ssh.connect()
        self.run_init_commands(session)
        return session

    def run_init_commands(self, session: MRSession) -> None:
        ssh = self._ssh(session)
        for command in self.INIT_COMMANDS:
            ssh.execute(command)
        ssh.state["initialized"] = True

    def loop(self, session: MRSession, config: OnlineMrConnectionConfig, callback: Callable[[str, str], None] | None = None) -> None:
        intervals = {
            task: interval
            for task, interval in config.intervals.as_dict().items()
            if task in config.tasks.enabled_tasks()
        }
        scheduler = MRClientScheduler.from_intervals(intervals, clock=self.clock)
        while session.running:
            now = self.clock()
            for task_name in scheduler.due_jobs(now):
                started = self.clock()
                raw_text = self.collect(session, task_name)
                if callback is not None:
                    callback(task_name, raw_text)
                scheduler.mark_ran(task_name, started, self.clock())
            self.sleeper(scheduler.sleep_duration(self.clock()))

    def collect(self, session: MRSession, task_name: str) -> str:
        command_text = "\n".join(TASK_COMMANDS[task_name])
        raw_text = "\n".join(self._ssh(session).execute(command) for command in TASK_COMMANDS[task_name])
        payload = {"timestamp": time.time(), "raw_text": raw_text}
        if task_name == TASK_MESH_LINK:
            session.mesh_buffer.append(payload)
        elif task_name == TASK_CHANNEL_BUSY:
            session.busy_buffer.append(payload)
        elif task_name == TASK_AP_RADIO_STATISTICS:
            session.stats_buffer.append(payload)
        return f"{command_text}\n{raw_text}"

    def stop_session(self, session_id: str) -> None:
        session = self.sessions.get(session_id)
        if session is None:
            return
        session.stop()
        if session.ssh is not None:
            session.ssh.close()

    def _ssh(self, session: MRSession) -> SSHClient:
        if session.ssh is None:
            raise RuntimeError("MR session has no SSH client")
        return session.ssh
