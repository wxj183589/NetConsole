from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Callable, Protocol

from netconsole.models.online_mr_models import (
    EVENT_COMMAND_FAILED,
    EVENT_RECONNECT,
    INIT_COMMANDS,
    STATE_COLLECTING,
    STATE_CONNECTING,
    STATE_FAILED,
    STATE_INITIALIZING,
    STATE_RECONNECTING,
    STATE_STOPPED,
    STATE_STOPPING,
    TASK_AP_RADIO_STATISTICS,
    TASK_CHANNEL_BUSY,
    TASK_COMMANDS,
    TASK_INTERFACE_RATE,
    TASK_MESH_LINK,
    TASK_SWITCH_HISTORY,
    repeat_command_group,
    OnlineMrConnection,
    OnlineMrConnectionConfig,
    OnlineMrSessionMeta,
    OnlineMrSnapshot,
    OnlineMrStats,
)
from netconsole.services.online_mr_parser import parse_channel_busy_text, parse_mesh_link_text, summarize_active
from netconsole.services.online_mr_session_store import OnlineMrSession, OnlineMrSessionStore
from netconsole.services.netmiko_connection import (
    ConnectionTarget,
    H3C_DEFAULT_ENCODING,
    build_netmiko_params,
    normalize_command_output,
)
from netconsole.core.mr_collect.scheduler import MRClientScheduler
from netconsole.services.online_mr.core.event_model import (
    EVENT_BUSY_SAMPLE,
    EVENT_INTERFACE_SAMPLE,
    EVENT_MESH_SAMPLE,
    EVENT_STATS_SAMPLE,
    OnlineMrEvent,
)
from netconsole.services.ssh_tunnel import TunnelManager, TunnelSession


class ConnectionFactory(Protocol):
    def __call__(self, config: OnlineMrConnectionConfig) -> OnlineMrConnection:
        ...


class OnlineMrConnectionError(RuntimeError):
    pass


class NetmikoShellConnection(OnlineMrConnection):
    def __init__(self, config: OnlineMrConnectionConfig) -> None:
        try:
            from netmiko import ConnectHandler
        except ImportError as exc:  # pragma: no cover - depends on optional runtime dependency.
            raise OnlineMrConnectionError("netmiko is not installed") from exc
        self.connection = None
        self._tunnel_session: TunnelSession | None = None
        last_error: Exception | None = None
        for target in self._targets_from_config(config):
            try:
                prepared = self._prepare_target(target)
                self.connection = ConnectHandler(**build_netmiko_params(prepared))
                config.connection_method = prepared.method
                return
            except Exception as exc:
                last_error = exc
                self._close_tunnel()
        raise OnlineMrConnectionError(str(last_error) if last_error else "all connection attempts failed")

    def send_command(self, command: str, timeout: int) -> str:
        if self.connection is None:
            raise OnlineMrConnectionError("connection is closed")
        output = self.connection.send_command_timing(
            command,
            read_timeout=timeout,
            strip_prompt=False,
            strip_command=False,
        )
        return normalize_command_output(output)

    def run_repeat_stream(
        self,
        commands: tuple[str, ...],
        raw_path: Path,
        stop_event: Event,
        timeout: int,
        line_callback: Callable[[datetime, str], None] | None = None,
    ) -> None:
        if self.connection is None:
            raise OnlineMrConnectionError("connection is closed")
        writer = getattr(self.connection, "write_channel", None)
        reader = getattr(self.connection, "read_channel", None)
        if not callable(writer) or not callable(reader):
            raise OnlineMrConnectionError("interactive shell is unavailable")
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        with raw_path.open("a", encoding="utf-8", errors="replace") as file:
            file.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} [collector=repeat] START commands:\n")
            for command in commands:
                file.write(f"{command}\n")
                writer(f"{command}\n")
                file.flush()
                time.sleep(0.05)
            idle_started = time.monotonic()
            while not stop_event.is_set():
                chunk = reader()
                if chunk:
                    idle_started = time.monotonic()
                    stamp_dt = datetime.now()
                    stamp = stamp_dt.isoformat(sep=" ", timespec="milliseconds")
                    for line in normalize_command_output(chunk).splitlines():
                        file.write(f"{stamp} [collector=repeat] RX {line}\n")
                        if line_callback is not None:
                            line_callback(stamp_dt, line)
                    file.flush()
                    continue
                if time.monotonic() - idle_started > max(3, timeout):
                    file.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} [collector=repeat] WARNING no output for {timeout}s\n")
                    file.flush()
                    idle_started = time.monotonic()
                time.sleep(0.05)
            try:
                writer("\x03")
                file.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} [collector=repeat] STOP Ctrl+C sent\n")
                file.flush()
            except Exception:
                pass

    def close(self) -> None:
        if self.connection is not None:
            self.connection.disconnect()
            self.connection = None
        self._close_tunnel()

    def _targets_from_config(self, config: OnlineMrConnectionConfig) -> tuple[ConnectionTarget, ...]:
        if config.connection_targets:
            return tuple(target for target in config.connection_targets if isinstance(target, ConnectionTarget))
        device_type = "hp_comware_telnet" if config.protocol.lower() == "telnet" else "hp_comware"
        return (
            ConnectionTarget(
                protocol=config.protocol,
                device_type=device_type,
                host=config.host,
                port=int(config.port),
                username=config.username,
                password=config.password,
                encoding=H3C_DEFAULT_ENCODING,
                method="primary_direct",
            ),
        )

    def _prepare_target(self, target: ConnectionTarget) -> ConnectionTarget:
        if not target.via_tunnel:
            return target
        if target.tunnel is None:
            raise OnlineMrConnectionError("Tunnel target is missing tunnel profile")
        self._tunnel_session = TunnelManager().open_tunnel(target.tunnel, target.host, target.port)  # type: ignore[arg-type]
        return ConnectionTarget(
            protocol=target.protocol,
            device_type=target.device_type,
            host=self._tunnel_session.local_host,
            port=self._tunnel_session.local_port,
            username=target.username,
            password=target.password,
            encoding=target.encoding,
            method=target.method,
            via_tunnel=True,
            tunnel=target.tunnel,
        )

    def _close_tunnel(self) -> None:
        if self._tunnel_session is not None:
            self._tunnel_session.close()
            self._tunnel_session = None


@dataclass
class OnlineMrScheduler:
    intervals: dict[str, int]
    next_due: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.next_due:
            now = time.monotonic()
            self.next_due = {task: now for task in self.intervals}

    def due_tasks(self, now: float) -> list[str]:
        return [task for task in self.intervals if now >= self.next_due.get(task, 0.0)]

    def mark_ran(self, task: str, now: float) -> None:
        previous = self.next_due.get(task, now)
        interval = float(self.intervals[task])
        next_due = previous + interval
        if next_due <= now:
            next_due = now + interval
        self.next_due[task] = next_due


class OnlineMrCollector:
    def __init__(
        self,
        config: OnlineMrConnectionConfig,
        store: OnlineMrSessionStore,
        connection_factory: ConnectionFactory | None = None,
        clock: Callable[[], float] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self.config = config
        self.store = store
        self.connection_factory = connection_factory or (lambda cfg: NetmikoShellConnection(cfg))
        self.clock = clock or time.monotonic
        self.sleeper = sleeper or time.sleep
        self.session: OnlineMrSession | None = None
        self.connection: OnlineMrConnection | None = None
        self.stats = OnlineMrStats()
        enabled_intervals = {
            task: interval
            for task, interval in config.intervals.as_dict().items()
            if task in config.tasks.enabled_tasks()
        }
        self.scheduler = MRClientScheduler.from_intervals(enabled_intervals, clock=self.clock)
        self.cancelled = False
        self.status = "CREATED"
        self.started_monotonic = self.clock()
        self.latest_snapshot: OnlineMrSnapshot | None = None
        self._stream_event_callback: Callable[[OnlineMrEvent], None] | None = None
        self._uses_default_connection_factory = connection_factory is None
        self._stream_stop = Event()
        self._stream_threads: list[Thread] = []
        self._stream_connections: list[OnlineMrConnection] = []

    def start(self) -> OnlineMrSessionMeta:
        self.session = self.store.create_session(self.config)
        self._set_status(STATE_CONNECTING)
        self.connection = self.connection_factory(self.config)
        if self.config.connection_method:
            self.session.meta.connection_method = self.config.connection_method
            self.session.write_meta()
        self.initialize_connection()
        self._set_status(STATE_COLLECTING)
        return self.session.meta

    def initialize_connection(self) -> None:
        if self.connection is None:
            raise OnlineMrConnectionError("connection is not ready")
        self._set_status(STATE_INITIALIZING)
        for command in INIT_COMMANDS:
            try:
                raw = self.connection.send_command(command, self.config.command_timeout)
            except Exception as exc:
                self._record_command_failure("init", command, exc)
                if self.connection is None:
                    raise
                continue
            self._session().append_raw("init", command, raw)

    def run_due_tasks(self, now: float | None = None) -> list[str]:
        if self.session is None:
            self.start()
        ran: list[str] = []
        current = self.clock() if now is None else now
        for task in self.scheduler.due_tasks(current):
            if self.cancelled:
                break
            self.run_once(task)
            self.scheduler.mark_ran(task, current, current if now is not None else self.clock())
            ran.append(task)
        return ran

    def run_once(self, task_type: str) -> int:
        session = self._session()
        if self.connection is None:
            self._reconnect()
        collected_at = datetime.now()
        raw_parts: list[str] = []
        commands = self._task_commands(task_type)
        command_text = "\n".join(commands)
        try:
            for command in commands:
                raw_parts.append(self._send(command))
            raw_text = "\n".join(raw_parts)
            raw_file, start, end = session.append_raw(task_type, command_text, raw_text, collected_at)
            sample_id = self._persist_task_result(task_type, collected_at, command_text, raw_file, start, end, raw_text)
            self._inc(task_type, True)
            self._update_meta()
            return sample_id
        except Exception as exc:
            self._inc(task_type, False)
            self._record_command_failure(task_type, command_text, exc)
            self._update_meta()
            if self.config.auto_reconnect:
                self._reconnect()
            return -1

    def run_forever(
        self,
        snapshot_callback: Callable[[OnlineMrSnapshot], None] | None = None,
        stream_event_callback: Callable[[OnlineMrEvent], None] | None = None,
    ) -> None:
        try:
            if self.session is None:
                self.start()
            self._stream_event_callback = stream_event_callback
            if self._uses_default_connection_factory:
                self._run_streaming_collectors(snapshot_callback)
                return
            while not self.cancelled:
                self.run_due_tasks()
                if snapshot_callback and self.latest_snapshot is not None:
                    snapshot_callback(self.latest_snapshot)
                self.sleeper(0.2)
        except Exception as exc:
            self._session().log("ERROR", str(exc)) if self.session else None
            self.status = STATE_FAILED
            if self.session:
                self.session.finish(STATE_FAILED, self.stats.as_dict())
        finally:
            if self.status not in {STATE_STOPPED, STATE_FAILED}:
                self.stop()

    def stop(self) -> None:
        self.cancelled = True
        self._stream_stop.set()
        for thread in list(self._stream_threads):
            thread.join(timeout=3)
        self._stream_threads.clear()
        for stream_connection in list(self._stream_connections):
            try:
                stream_connection.close()
            except Exception:
                pass
        self._stream_connections.clear()
        if self.session:
            self._set_status(STATE_STOPPING)
        if self.connection is not None:
            try:
                self.connection.close()
            except Exception:
                pass
            self.connection = None
        if self.session:
            self.session.finish(STATE_STOPPED, self.stats.as_dict())
        self.status = STATE_STOPPED

    def snapshot(self) -> OnlineMrSnapshot:
        collected = (
            self.stats.mesh_link_success
            + self.stats.channel_busy_success
            + self.stats.ap_radio_statistics_success
            + self.stats.switch_history_success
            + self.stats.interface_rate_success
        )
        failed = (
            self.stats.mesh_link_failed
            + self.stats.channel_busy_failed
            + self.stats.ap_radio_statistics_failed
            + self.stats.switch_history_failed
            + self.stats.interface_rate_failed
        )
        snapshot = self.latest_snapshot or OnlineMrSnapshot(self._session().meta.session_id, self.status)
        snapshot.status = self.status
        snapshot.collected_count = collected
        snapshot.failed_count = failed
        snapshot.reconnect_count = self.stats.reconnect_count
        snapshot.uptime_seconds = int(self.clock() - self.started_monotonic)
        return snapshot

    def _persist_task_result(self, task_type: str, collected_at: datetime, command_text: str, raw_file: str, start: int, end: int, raw_text: str) -> int:
        session = self._session()
        if task_type == TASK_MESH_LINK:
            records, parse_status, error = parse_mesh_link_text(raw_text, collected_at)
            sample_id = session.append_sample(task_type, collected_at, command_text, raw_file, start, end, parse_status, error)
            if records:
                session.append_mesh_links(sample_id, records)
                active = summarize_active(records)
                if active is not None:
                    self.latest_snapshot = OnlineMrSnapshot(
                        session.meta.session_id,
                        self.status,
                        active_peer=active.peer_mac_raw,
                        local_rssi=active.metrics.get("local_rssi_db"),
                        peer_rssi=active.metrics.get("peer_rssi_db"),
                        local_tx_busy=active.metrics.get("local_tx_busy"),
                        local_rx_busy=active.metrics.get("local_rx_busy"),
                        last_collection_time=collected_at.isoformat(sep=" ", timespec="seconds"),
                    )
            if parse_status == "FAILED":
                self.stats.parse_failed += 1
            return sample_id
        sample_id = session.append_sample(task_type, collected_at, command_text, raw_file, start, end, "OK")
        if task_type == TASK_CHANNEL_BUSY:
            session.append_channel_busy(sample_id, parse_channel_busy_text(raw_text))
        elif task_type == TASK_AP_RADIO_STATISTICS:
            session.append_raw_index("live_radio_statistics_raw_index", sample_id, raw_text)
        elif task_type == TASK_SWITCH_HISTORY:
            session.replace_switch_history_latest(collected_at, raw_text, raw_file, start, end)
        elif task_type == TASK_INTERFACE_RATE:
            session.append_interface_rates(sample_id, collected_at, raw_text)
        return sample_id

    def _send(self, command: str) -> str:
        if self.connection is None:
            raise OnlineMrConnectionError("connection is closed")
        return self.connection.send_command(command, self.config.command_timeout)

    def _task_commands(self, task_type: str) -> tuple[str, ...]:
        radio = self.config.radio.normalized()
        if task_type == TASK_CHANNEL_BUSY:
            return ("display clock", f"display ar5drv {radio.channel_busy_radio} channelbusy")
        if task_type == TASK_AP_RADIO_STATISTICS:
            return ("display clock", f"display ar5drv {radio.ap_radio_statistics_radio} statistics")
        return TASK_COMMANDS[task_type]

    def _repeat_commands(self, task_type: str) -> tuple[str, ...]:
        intervals = self.config.intervals.normalized()
        radio = self.config.radio.normalized()
        if task_type == TASK_CHANNEL_BUSY:
            return repeat_command_group(task_type, interval=intervals.channel_busy, radio_id=radio.channel_busy_radio)
        if task_type == TASK_AP_RADIO_STATISTICS:
            return repeat_command_group(task_type, interval=intervals.ap_radio_statistics, radio_id=radio.ap_radio_statistics_radio)
        if task_type == TASK_INTERFACE_RATE:
            return repeat_command_group(task_type, interval=intervals.interface_rate)
        if task_type == TASK_MESH_LINK:
            return repeat_command_group(task_type, interval=intervals.mesh_link)
        return repeat_command_group(task_type, interval=intervals.switch_history)

    def _run_streaming_collectors(self, snapshot_callback: Callable[[OnlineMrSnapshot], None] | None = None) -> None:
        stream_tasks = [
            TASK_MESH_LINK,
            TASK_CHANNEL_BUSY,
            TASK_AP_RADIO_STATISTICS,
            TASK_INTERFACE_RATE,
        ]
        enabled = self.config.tasks.enabled_tasks()
        for task_type in stream_tasks:
            if task_type in enabled:
                self._start_repeat_thread(task_type)
        while not self.cancelled:
            if TASK_SWITCH_HISTORY in enabled:
                for task in self.scheduler.due_tasks(self.clock()):
                    if task == TASK_SWITCH_HISTORY:
                        self.run_once(TASK_SWITCH_HISTORY)
                        self.scheduler.mark_ran(task, self.clock(), self.clock())
            if snapshot_callback:
                snapshot_callback(self.snapshot())
            self.sleeper(0.2)

    def _start_repeat_thread(self, task_type: str) -> None:
        session = self._session()
        connection = self.connection_factory(self.config)
        self._stream_connections.append(connection)
        for command in INIT_COMMANDS:
            try:
                raw = connection.send_command(command, self.config.command_timeout)
                session.append_raw("init", command, raw)
            except Exception as exc:
                self._record_command_failure("init", command, exc)
        commands = self._repeat_commands(task_type)
        raw_path = session.session_dir / "raw" / {
            TASK_MESH_LINK: "mesh_link_raw.log",
            TASK_CHANNEL_BUSY: "channel_busy_raw.log",
            TASK_AP_RADIO_STATISTICS: "ap_radio_statistics_raw.log",
            TASK_INTERFACE_RATE: "interface_rate_raw.log",
        }[task_type]

        def target() -> None:
            try:
                runner = getattr(connection, "run_repeat_stream", None)
                if not callable(runner):
                    raise OnlineMrConnectionError("interactive repeat stream is unavailable")
                try:
                    runner(
                        commands,
                        raw_path,
                        self._stream_stop,
                        self.config.command_timeout,
                        line_callback=lambda stamp, line: self._publish_stream_line(task_type, stamp, line),
                    )
                except TypeError:
                    runner(commands, raw_path, self._stream_stop, self.config.command_timeout)
            except Exception as exc:
                self._record_command_failure(task_type, "\n".join(commands), exc)

        thread = Thread(target=target, name=f"online-mr-{task_type}", daemon=True)
        self._stream_threads.append(thread)
        thread.start()

    def _publish_stream_line(self, task_type: str, timestamp: datetime, line: str) -> None:
        if self._stream_event_callback is None or self.session is None:
            return
        module_event = {
            TASK_MESH_LINK: ("mesh", EVENT_MESH_SAMPLE),
            TASK_CHANNEL_BUSY: ("busy", EVENT_BUSY_SAMPLE),
            TASK_AP_RADIO_STATISTICS: ("stats", EVENT_STATS_SAMPLE),
            TASK_INTERFACE_RATE: ("interface_rate", EVENT_INTERFACE_SAMPLE),
        }.get(task_type)
        if module_event is None:
            return
        module, event_type = module_event
        self._stream_event_callback(
            OnlineMrEvent(
                timestamp=timestamp,
                session_id=self.session.meta.session_id,
                device_id=self.config.device_id,
                source="ssh_stream",
                module=module,
                event_type=event_type,
                payload={"task_type": task_type, "line": line},
                raw=line,
            )
        )

    def _reconnect(self) -> None:
        if not self.config.auto_reconnect:
            raise OnlineMrConnectionError("connection failed and auto reconnect disabled")
        if self.config.max_reconnect is not None and self.stats.reconnect_count >= self.config.max_reconnect:
            raise OnlineMrConnectionError("max reconnect reached")
        self._set_status(STATE_RECONNECTING)
        if self.connection is not None:
            try:
                self.connection.close()
            except Exception:
                pass
        self.connection = None
        self.sleeper(float(self.config.reconnect_interval))
        self.stats.reconnect_count += 1
        self._session().append_reconnect(f"reconnect_count={self.stats.reconnect_count}")
        self._session().append_event(EVENT_RECONNECT)
        self.connection = self.connection_factory(self.config)
        if self.config.connection_method:
            self._session().meta.connection_method = self.config.connection_method
            self._session().write_meta()
        self.initialize_connection()
        self._set_status(STATE_COLLECTING)

    def _record_command_failure(self, task_type: str, command: str, exc: Exception) -> None:
        self.stats.command_failed += 1
        if self.session:
            self.session.log("WARNING", f"command failed task={task_type} command={command} error={exc}")
            self.session.append_event(EVENT_COMMAND_FAILED, details_json=f'{{"task": "{task_type}", "command": "{command}"}}')

    def _inc(self, task_type: str, success: bool) -> None:
        suffix = "success" if success else "failed"
        attr = {
            TASK_MESH_LINK: f"mesh_link_{suffix}",
            TASK_CHANNEL_BUSY: f"channel_busy_{suffix}",
            TASK_AP_RADIO_STATISTICS: f"ap_radio_statistics_{suffix}",
            TASK_SWITCH_HISTORY: f"switch_history_{suffix}",
            TASK_INTERFACE_RATE: f"interface_rate_{suffix}",
        }[task_type]
        setattr(self.stats, attr, getattr(self.stats, attr) + 1)

    def _set_status(self, status: str) -> None:
        self.status = status
        if self.session:
            self.session.update_status(status)

    def _update_meta(self) -> None:
        session = self._session()
        session.meta.stats = self.stats.as_dict()
        session.write_meta()

    def _session(self) -> OnlineMrSession:
        if self.session is None:
            raise RuntimeError("session is not created")
        return self.session


class OnlineMrCollectionManager:
    def __init__(self, max_concurrent: int = 2) -> None:
        self.max_concurrent = max_concurrent
        self._running: dict[str, object] = {}
        self.running_collectors: dict[int, object] = {}
        self._lock = Lock()

    def can_start(self) -> bool:
        with self._lock:
            return self._running_total() < self.max_concurrent

    def can_start_slots(self, count: int = 1) -> bool:
        with self._lock:
            return self._running_total() + max(0, int(count)) <= self.max_concurrent

    def register(self, session_id: str, worker: object) -> None:
        with self._lock:
            if self._running_total() >= self.max_concurrent:
                raise RuntimeError("online_mr.max_two_running")
            self._running[session_id] = worker

    def unregister(self, session_id: str) -> None:
        with self._lock:
            self._running.pop(session_id, None)

    def register_device(self, device_id: int, worker: object) -> None:
        with self._lock:
            if device_id in self.running_collectors:
                self.running_collectors[device_id] = worker
                return
            if max(len(self._running), len(self.running_collectors) + 1) > self.max_concurrent:
                raise RuntimeError("online_mr.max_two_running")
            self.running_collectors[device_id] = worker

    def unregister_device(self, device_id: int) -> None:
        with self._lock:
            self.running_collectors.pop(device_id, None)

    def stop_devices(self, device_ids: list[int]) -> None:
        for worker in self.get_status_snapshot(device_ids).values():
            cancel = getattr(worker, "cancel", None) or getattr(worker, "stop", None)
            if callable(cancel):
                cancel()

    def stop_all(self) -> None:
        self.stop_devices(list(self.running_collectors))
        for worker in list(self._running.values()):
            cancel = getattr(worker, "cancel", None) or getattr(worker, "stop", None)
            if callable(cancel):
                cancel()

    def get_status_snapshot(self, device_ids: list[int] | None = None) -> dict[int, object]:
        with self._lock:
            if device_ids is None:
                return dict(self.running_collectors)
            wanted = set(device_ids)
            return {device_id: worker for device_id, worker in self.running_collectors.items() if device_id in wanted}

    def running_count(self) -> int:
        with self._lock:
            return self._running_total()

    def _running_total(self) -> int:
        return max(len(self._running), len(self.running_collectors))


class RepeatSshSession:
    def __init__(self, connection: OnlineMrConnection, task_type: str, interval: int, radio_id: int = 1, timeout: int = 15) -> None:
        self.connection = connection
        self.task_type = task_type
        self.interval = interval
        self.radio_id = radio_id
        self.timeout = timeout
        self.started = False
        self.stopped = False

    def command_group(self) -> tuple[str, ...]:
        return repeat_command_group(self.task_type, interval=self.interval, radio_id=self.radio_id)

    def start(self) -> list[str]:
        outputs: list[str] = []
        for command in self.command_group():
            outputs.append(self.connection.send_command(command, self.timeout))
        self.started = True
        return outputs

    def stop(self) -> None:
        try:
            self.connection.send_command("\x03", self.timeout)
        finally:
            self.stopped = True
            self.connection.close()
