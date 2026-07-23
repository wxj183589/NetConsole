from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

try:
    from netmiko import ConnectHandler
except Exception:  # pragma: no cover
    ConnectHandler = None  # type: ignore[assignment]


VERSION = "0.2.0-netmiko-sidecar"
H3C_ENCODING = "gb2312"
JSON_WRITE_LOCK = threading.RLock()

INIT_COMMANDS = (
    "screen-length disable", "terminal logging level 7", "terminal monitor",
    "system-view", "user-interface vty 0 31", "idle-timeout 1440 0",
    "return", "system-view", "probe", "return",
)
TERMINAL_MONITOR_INIT_COMMANDS = ("screen-length disable", "terminal monitor", "terminal logging level 7")
NORMAL_DISPLAY_PREPARE_COMMANDS = ("screen-length disable",)
PROBE_STREAM_PREPARE_COMMANDS = ("screen-length disable", "system-view", "probe")

ITEM_TERMINAL_MONITOR = "terminal_monitor"
ITEM_MESH_LINK = "mesh_link"
ITEM_CHANNEL_BUSY = "channel_busy"
ITEM_AP_RADIO_STATISTICS = "ap_radio_statistics"
ITEM_SWITCH_HISTORY = "switch_history"
ITEM_INTERFACE_RATE = "interface_rate"
ITEM_WIRELESS_STATUS = "wireless_status"
ITEM_FPING_V5 = "fping_v5"
ITEM_IPERF_CLIENT = "iperf_client"

RAW_FILES = (
    "init_raw.log", "config_collect_raw.log", "terminal_monitor_raw.log", "mesh_link_raw.log",
    "channel_busy_raw.log", "ap_radio_statistics_raw.log", "switch_history_latest.log",
    "interface_rate_raw.log", "wireless_status_raw.log", "collector_output_raw.log",
    "fping_v5_raw.log", "fping_v5_samples.jsonl", "fping_v5_final_summary.json", "iperf_client_raw.log",
)
RAW_NAME = {
    "init": "init_raw.log", ITEM_TERMINAL_MONITOR: "terminal_monitor_raw.log",
    ITEM_MESH_LINK: "mesh_link_raw.log", ITEM_CHANNEL_BUSY: "channel_busy_raw.log",
    ITEM_AP_RADIO_STATISTICS: "ap_radio_statistics_raw.log", ITEM_SWITCH_HISTORY: "switch_history_latest.log",
    ITEM_INTERFACE_RATE: "interface_rate_raw.log", ITEM_WIRELESS_STATUS: "wireless_status_raw.log",
    ITEM_FPING_V5: "fping_v5_raw.log", ITEM_IPERF_CLIENT: "iperf_client_raw.log",
}
ITEM_LABEL = {
    "init": "初始化", ITEM_TERMINAL_MONITOR: "终端实时日志", ITEM_MESH_LINK: "主链路信息",
    ITEM_CHANNEL_BUSY: "信道繁忙度", ITEM_AP_RADIO_STATISTICS: "AP 射频统计",
    ITEM_SWITCH_HISTORY: "主链路切换历史", ITEM_INTERFACE_RATE: "接口速率",
    ITEM_WIRELESS_STATUS: "无线状态", ITEM_FPING_V5: "高频 Ping", ITEM_IPERF_CLIENT: "iPerf Client",
}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    with JSON_WRITE_LOCK:
        try:
            tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, path)
        finally:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass


def append_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", errors="replace") as stream:
        stream.write(text)
        stream.flush()


def normalize_command_output(value: object) -> str:
    if isinstance(value, bytes):
        for encoding in (H3C_ENCODING, "gbk", "gb18030", "utf-8"):
            try:
                return value.decode(encoding).replace("\r\n", "\n").replace("\r", "\n")
            except UnicodeDecodeError:
                continue
        return value.decode("utf-8", errors="replace")
    return str(value or "").replace("\r\n", "\n").replace("\r", "\n")


def netmiko_params(target: dict[str, Any]) -> dict[str, Any]:
    protocol = str(target.get("protocol") or "ssh").lower()
    return {
        "device_type": "hp_comware_telnet" if protocol == "telnet" else "hp_comware",
        "host": str(target.get("host") or ""), "username": str(target.get("username") or ""),
        "password": str(target.get("password") or ""),
        "port": int(target.get("port") or (23 if protocol == "telnet" else 22)),
        "timeout": 10, "conn_timeout": 5, "auth_timeout": 8, "banner_timeout": 8,
        "encoding": H3C_ENCODING, "session_log": None, "global_delay_factor": 1, "fast_cli": False,
    }


def send_command_timing(connection: Any, command: str, timeout: int = 30) -> str:
    kwargs = {"read_timeout": timeout, "strip_prompt": False, "strip_command": False}
    try:
        return normalize_command_output(connection.send_command_timing(command, encoding=H3C_ENCODING, **kwargs))
    except TypeError:
        return normalize_command_output(connection.send_command_timing(command, **kwargs))
    except UnicodeDecodeError:
        return normalize_command_output(connection.send_command_timing(command, encoding="utf-8", **kwargs))


def command_line(commands: tuple[str, ...] | list[str]) -> str:
    return " | ".join(commands)


def repeat_command_group(item: str, interval: int, radio_id: int) -> tuple[str, ...]:
    delay, radio = max(1, int(interval or 1)), max(1, int(radio_id or 1))
    if item == ITEM_MESH_LINK:
        return ("display clock", "display wlan mesh-link", f"repeat 2 delay {delay}")
    if item == ITEM_CHANNEL_BUSY:
        return ("display clock", f"display ar5drv {radio} channelbusy", f"repeat 2 delay {delay}")
    if item == ITEM_AP_RADIO_STATISTICS:
        return ("display clock", f"display ar5drv {radio} statistics", f"repeat 2 delay {delay}")
    if item == ITEM_WIRELESS_STATUS:
        return ("display clock", f"display ar5drv {radio} client all rssi", f"display ar5drv {radio} client all status", f"repeat 3 delay {delay}")
    if item == ITEM_SWITCH_HISTORY:
        return ("display clock", "display wlan mesh-link switch-history", f"repeat 2 delay {delay}")
    if item == ITEM_INTERFACE_RATE:
        return ("display clock", "dis counters rate inbound interface", "dis counters rate outbound interface", f"repeat 3 delay {delay}")
    raise ValueError(f"unsupported collector: {item}")


def prepare_commands(item: str) -> tuple[str, ...]:
    return PROBE_STREAM_PREPARE_COMMANDS if item in {ITEM_CHANNEL_BUSY, ITEM_AP_RADIO_STATISTICS, ITEM_WIRELESS_STATUS} else NORMAL_DISPLAY_PREPARE_COMMANDS


@dataclass
class CollectorState:
    name: str
    status: str = "pending"
    raw_file: str = ""
    error: str = ""
    started_at: str = ""
    ended_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "label": ITEM_LABEL.get(self.name, self.name), "status": self.status, "raw_file": self.raw_file, "error": self.error, "started_at": self.started_at, "ended_at": self.ended_at}


@dataclass
class MRCollectorApp:
    request: dict[str, Any]
    session_dir: Path
    stop_file: Path
    event_file: Path
    status_file: Path
    start_time: datetime = field(default_factory=datetime.now)
    stop_event: threading.Event = field(default_factory=threading.Event)
    collectors: dict[str, CollectorState] = field(default_factory=dict)
    threads: list[threading.Thread] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    status: str = "RUNNING"
    fping_summary: dict[str, Any] = field(default_factory=dict)
    iperf_status: dict[str, Any] = field(default_factory=dict)
    state_lock: threading.RLock = field(default_factory=threading.RLock)
    view_lock: threading.RLock = field(default_factory=threading.RLock)
    last_view_write: float = 0.0

    @property
    def raw_dir(self) -> Path:
        return self.session_dir / "raw"

    def target(self) -> dict[str, Any]:
        return dict(self.request.get("target") or {})

    def session(self) -> dict[str, Any]:
        return dict(self.request.get("session") or {})

    def tools(self) -> dict[str, Any]:
        return dict(self.request.get("tools") or {})

    def fping_config(self) -> dict[str, Any]:
        return dict(self.request.get("fping") or {})

    def iperf_config(self) -> dict[str, Any]:
        return dict(self.request.get("iperf") or {})

    def display_context(self) -> dict[str, Any]:
        return dict(self.request.get("display_context") or {})

    def session_id(self) -> str:
        return str(self.request.get("session_id") or self.session_dir.name)

    def device_name(self) -> str:
        session, target = self.session(), self.target()
        return str(session.get("device_name") or session.get("mr_name") or target.get("name") or "MR")

    def intervals(self) -> dict[str, int]:
        data = dict(self.request.get("intervals") or {})
        defaults = {ITEM_MESH_LINK: 1, ITEM_CHANNEL_BUSY: 9, ITEM_AP_RADIO_STATISTICS: 10, ITEM_SWITCH_HISTORY: 300, ITEM_INTERFACE_RATE: 2, ITEM_WIRELESS_STATUS: 3}
        return {name: max(1, int(data.get(name) or default)) for name, default in defaults.items()}

    def radios(self) -> dict[str, int]:
        data = dict(self.request.get("radio") or {})
        defaults = {"mesh_link_radio": 1, "channel_busy_radio": 1, "ap_radio_statistics_radio": 1, "wireless_status_radio": 1}
        return {name: max(1, int(data.get(name) or default)) for name, default in defaults.items()}

    def items(self) -> dict[str, bool]:
        data = dict(self.request.get("items") or {})
        return {name: bool(data.get(name, True)) for name in (ITEM_TERMINAL_MONITOR, ITEM_MESH_LINK, ITEM_CHANNEL_BUSY, ITEM_AP_RADIO_STATISTICS, ITEM_SWITCH_HISTORY, ITEM_INTERFACE_RATE, ITEM_WIRELESS_STATUS)}

    def connect(self) -> Any:
        if ConnectHandler is None:
            raise RuntimeError("netmiko is not installed; 请先安装/打包 netmiko")
        return ConnectHandler(**netmiko_params(self.target()))

    def event(self, event_type: str, message: str, extra: dict[str, Any] | None = None) -> None:
        payload = {"ts": now_iso(), "type": event_type, "message": message}
        if extra:
            payload.update(extra)
        append_text(self.event_file, json.dumps(payload, ensure_ascii=False) + "\n")

    def collector_log(self, fmt: str, *args: Any) -> None:
        text = f"{now_text()} {fmt % args if args else fmt}\n"
        append_text(self.raw_dir / "collector_output_raw.log", text)
        append_text(self.session_dir / "logs" / "collector.log", text)
        print(text, end="", flush=True)

    def prepare(self) -> None:
        for dirname in ("raw", "parsed", "view", "logs", "outputs"):
            (self.session_dir / dirname).mkdir(parents=True, exist_ok=True)
        for name in RAW_FILES:
            (self.raw_dir / name).touch(exist_ok=True)
        self._initialize_disabled_collectors()
        self.collector_log("[agent] START mr_realtime_collect target=%s host=%s", self.device_name(), self.target().get("host", ""))
        self.write_meta("RUNNING")
        self.event("started", "MR 在线收集已启动", {"session_id": self.session_id()})

    def _initialize_disabled_collectors(self) -> None:
        enabled = self.items()
        with self.state_lock:
            for name in (ITEM_TERMINAL_MONITOR, ITEM_MESH_LINK, ITEM_CHANNEL_BUSY, ITEM_AP_RADIO_STATISTICS, ITEM_SWITCH_HISTORY, ITEM_INTERFACE_RATE, ITEM_WIRELESS_STATUS):
                if not enabled.get(name, False):
                    self.collectors[name] = CollectorState(name, "disabled", "raw/" + RAW_NAME[name])
            if not self.fping_config().get("enabled"):
                self.collectors[ITEM_FPING_V5] = CollectorState(ITEM_FPING_V5, "disabled", "raw/fping_v5_raw.log")
            if not self.iperf_config().get("enabled"):
                self.collectors[ITEM_IPERF_CLIENT] = CollectorState(ITEM_IPERF_CLIENT, "disabled", "raw/iperf_client_raw.log")

    def set_collector(self, name: str, status: str, error: str = "") -> None:
        with self.state_lock:
            state = self.collectors.get(name) or CollectorState(name, "pending", "raw/" + RAW_NAME.get(name, f"{name}.log"))
            state.status = status
            if status in {"starting", "running"} and not state.started_at:
                state.started_at = now_iso()
            if status in {"failed", "stopped", "completed", "disabled"}:
                state.ended_at = now_iso()
            if error:
                state.error = error
            self.collectors[name] = state
            current_status = self.status
        self.event("collector_status", f"{ITEM_LABEL.get(name, name)} {status}", {"collector": name, "status": status, "error": error})
        self.write_meta(current_status)

    def _collector_snapshot(self) -> dict[str, dict[str, Any]]:
        with self.state_lock:
            return {key: value.as_dict() for key, value in self.collectors.items()}

    def write_status(self) -> None:
        with self.state_lock:
            status, errors = self.status, list(self.errors)
        write_json_atomic(self.status_file, {"version": VERSION, "status": status, "session_id": self.session_id(), "session_dir": str(self.session_dir), "started_at": self.start_time.isoformat(timespec="seconds"), "updated_at": now_iso(), "collectors": self._collector_snapshot(), "errors": errors})
        self.write_live_views()

    def safe_fping_meta(self) -> dict[str, Any]:
        cfg = self.fping_config()
        targets = [str((item or {}).get("host") or "").strip() for item in cfg.get("targets") or []]
        with self.state_lock:
            status = self.collectors.get(ITEM_FPING_V5).status if ITEM_FPING_V5 in self.collectors else "disabled"
        return {"enabled": bool(cfg.get("enabled")), "template": cfg.get("template") or "", "targets": [x for x in targets if x], "packet_size": int(cfg.get("packet_size") or 64), "interval_ms": int(cfg.get("interval_ms") or 10), "timeout_ms": int(cfg.get("timeout_ms") or 100), "loss_alarm_percent": float(cfg.get("loss_alarm_percent") or 0.7), "latency_alarm_ms": int(cfg.get("latency_alarm_ms") or 100), "status": status, "summary": self.fping_summary}

    def write_meta(self, status: str, error_message: str = "", stop_reason: str = "") -> None:
        with self.state_lock:
            self.status = status
            errors = list(self.errors)
        target, session = self.target(), self.session()
        protocol = str(target.get("protocol") or "ssh").lower()
        meta: dict[str, Any] = {
            "session_id": self.session_id(), "site": session.get("site", ""), "mr_id": session.get("mr_id", ""), "mr_name": session.get("mr_name") or target.get("name", ""), "device_id": session.get("device_id", ""), "device_name": session.get("device_name") or target.get("name", ""), "host": target.get("host", ""), "protocol": protocol, "port": int(target.get("port") or (23 if protocol == "telnet" else 22)), "connection_method": protocol, "started_at": self.start_time.strftime("%Y-%m-%d %H:%M:%S"), "ended_at": None if status == "RUNNING" else datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "status": status, "intervals": self.intervals(), "radio": self.radios(), "items": self.items(), "collectors": self._collector_snapshot(), "fping": self.safe_fping_meta(), "iperf": dict(self.iperf_config()), "stats": {}, "session_type": "agent_realtime_netmiko", "collector_impl": "python_netmiko_sidecar", "raw_log_path": "raw/collector_output_raw.log",
        }
        if errors:
            meta["errors"] = errors
        if error_message:
            meta["error_message"] = error_message
        if stop_reason:
            meta["stop_reason"] = stop_reason
        write_json_atomic(self.session_dir / "session_meta.json", meta)
        self.write_status()

    def stop_watcher(self) -> None:
        while not self.stop_event.wait(0.2):
            if self.stop_file.exists():
                self.collector_log("[agent] STOP request detected file=%s", self.stop_file)
                self.stop_event.set()
                return

    def run(self) -> int:
        self.prepare()
        watcher = threading.Thread(target=self.stop_watcher, name="stop-file-watcher", daemon=True)
        watcher.start()
        try:
            self.run_init()
            self.start_collectors()
            while not self.stop_event.wait(0.5):
                if not any(thread.is_alive() for thread in self.threads):
                    break
            self.stop_event.set()
            for thread in self.threads:
                thread.join(timeout=8)
            with self.state_lock:
                failed = [state for state in self.collectors.values() if state.status == "failed"]
                active = [state for state in self.collectors.values() if state.status in {"running", "stopped", "completed"}]
            if not active and failed:
                self.write_meta("FAILED", "; ".join(state.error for state in failed if state.error), "all_collectors_failed")
                self.collector_log("[agent] STOP reason=all_collectors_failed")
                return 2
            if failed:
                reason = "user_stop" if self.stop_file.exists() else "partial_collector_failed"
                self.write_meta("STOPPED_WITH_WARNINGS", "; ".join(state.error for state in failed if state.error), reason)
                self.collector_log("[agent] STOP reason=warnings failed_collectors=%d", len(failed))
                return 0
            reason = "user_stop" if self.stop_file.exists() else "completed"
            self.write_meta("STOPPED" if self.stop_file.exists() else "COMPLETED", "", reason)
            self.collector_log("[agent] STOP reason=%s", reason)
            return 0
        except Exception as exc:
            with self.state_lock:
                self.errors.append(str(exc))
            self.collector_log("[agent] STOP reason=runner_error error=%s", exc)
            self.write_meta("FAILED", str(exc), "runner_error")
            return 1
        finally:
            self.stop_event.set()
            watcher.join(timeout=1)
            self.write_status()

    def run_init(self) -> None:
        self.set_collector("init", "starting")
        self.collector_log("[collector=init] START %s", command_line(INIT_COMMANDS))
        connection = None
        try:
            connection = self.connect()
            with (self.raw_dir / "init_raw.log").open("a", encoding="utf-8", errors="replace") as raw:
                for command in INIT_COMMANDS:
                    if self.stop_event.is_set():
                        break
                    raw.write(f"{now_text()} [collector=init] CMD {command}\n")
                    raw.write(send_command_timing(connection, command, 10) + "\n")
                    raw.flush()
            self.set_collector("init", "completed")
        except Exception as exc:
            error = str(exc)
            append_text(self.raw_dir / "init_raw.log", f"{now_text()} [agent] collector failed: {error}\n")
            self.collector_log("[collector=init] FAILED error=%s", error)
            self.set_collector("init", "failed", error)
        finally:
            if connection is not None:
                try:
                    connection.disconnect()
                except Exception:
                    pass

    def start_collectors(self) -> None:
        order = [ITEM_TERMINAL_MONITOR, ITEM_MESH_LINK, ITEM_CHANNEL_BUSY, ITEM_AP_RADIO_STATISTICS, ITEM_WIRELESS_STATUS, ITEM_INTERFACE_RATE, ITEM_SWITCH_HISTORY]
        enabled = self.items()
        for item in order:
            if enabled.get(item):
                thread = threading.Thread(target=self.run_collector_safe, args=(item,), name=f"collector-{item}", daemon=True)
                thread.start()
                self.threads.append(thread)
                time.sleep(0.3)
        if self.fping_config().get("enabled"):
            thread = threading.Thread(target=self.run_fping_safe, name="collector-fping-v5", daemon=True)
            thread.start()
            self.threads.append(thread)
        if self.iperf_config().get("enabled"):
            thread = threading.Thread(target=self.run_iperf_safe, name="collector-iperf-client", daemon=True)
            thread.start()
            self.threads.append(thread)

    def run_collector_safe(self, item: str) -> None:
        self.set_collector(item, "starting")
        try:
            self.run_terminal_monitor() if item == ITEM_TERMINAL_MONITOR else self.run_repeat_collector(item)
            self.set_collector(item, "stopped" if self.stop_event.is_set() else "completed")
        except Exception as exc:
            error = str(exc)
            with self.state_lock:
                self.errors.append(f"{item}: {error}")
            append_text(self.raw_dir / RAW_NAME[item], f"{now_text()} [agent] collector failed: {error}\n")
            self.collector_log("[collector=%s] FAILED error=%s", item, error)
            self.set_collector(item, "failed", error)

    def run_terminal_monitor(self) -> None:
        connection = self.connect()
        try:
            writer, reader = getattr(connection, "write_channel", None), getattr(connection, "read_channel", None)
            if not callable(writer) or not callable(reader):
                raise RuntimeError("interactive shell is unavailable")
            self.collector_log("[collector=%s] START", ITEM_TERMINAL_MONITOR)
            for command in TERMINAL_MONITOR_INIT_COMMANDS:
                writer(command + "\n")
                time.sleep(0.05)
            self.set_collector(ITEM_TERMINAL_MONITOR, "running")
            self.read_loop(reader, self.raw_dir / RAW_NAME[ITEM_TERMINAL_MONITOR], ITEM_TERMINAL_MONITOR)
        finally:
            try:
                connection.disconnect()
            except Exception:
                pass

    def run_repeat_collector(self, item: str) -> None:
        connection = self.connect()
        try:
            writer, reader = getattr(connection, "write_channel", None), getattr(connection, "read_channel", None)
            if not callable(writer) or not callable(reader):
                raise RuntimeError("interactive shell is unavailable")
            radio_key = {ITEM_MESH_LINK: "mesh_link_radio", ITEM_CHANNEL_BUSY: "channel_busy_radio", ITEM_AP_RADIO_STATISTICS: "ap_radio_statistics_radio", ITEM_WIRELESS_STATUS: "wireless_status_radio"}.get(item, "")
            radio = self.radios().get(radio_key, 1)
            prepare, commands = prepare_commands(item), repeat_command_group(item, self.intervals().get(item, 1), radio)
            self.collector_log("[collector=%s] PREPARE %s", item, command_line(prepare))
            for command in prepare:
                writer(command + "\n")
                time.sleep(0.05)
            self.collector_log("[collector=%s] START %s", item, command_line(commands))
            for command in commands:
                writer(command + "\n")
                time.sleep(0.05)
            self.set_collector(item, "running")
            self.read_loop(reader, self.raw_dir / RAW_NAME[item], item)
            try:
                writer("\x03")
                if item in {ITEM_CHANNEL_BUSY, ITEM_AP_RADIO_STATISTICS, ITEM_WIRELESS_STATUS}:
                    writer("return\n")
            except Exception:
                pass
        finally:
            try:
                connection.disconnect()
            except Exception:
                pass

    def read_loop(self, reader: Callable[[], str], raw_path: Path, item: str) -> None:
        idle = time.monotonic()
        with raw_path.open("a", encoding="utf-8", errors="replace") as raw:
            while not self.stop_event.is_set():
                chunk = reader()
                if chunk:
                    idle = time.monotonic()
                    stamp = now_text()
                    for line in normalize_command_output(chunk).splitlines():
                        raw.write(f"{stamp} [collector={item}] RX {line}\n")
                    raw.flush()
                    self.write_live_views()
                    continue
                if time.monotonic() - idle > 30:
                    raw.write(f"{now_text()} [collector={item}] WARNING no output for 30s\n")
                    raw.flush()
                    idle = time.monotonic()
                time.sleep(0.05)

    def run_fping_safe(self) -> None:
        self.set_collector(ITEM_FPING_V5, "starting")
        try:
            if self.run_fping():
                self.set_collector(ITEM_FPING_V5, "stopped" if self.stop_event.is_set() else "completed")
        except Exception as exc:
            error = str(exc)
            with self.state_lock:
                self.errors.append(f"fping_v5: {error}")
            append_text(self.raw_dir / "fping_v5_raw.log", f"{now_text()} [agent] collector failed: {error}\n")
            self.collector_log("[collector=fping_v5] FAILED error=%s", error)
            self.write_fping_summary({"Status": "failed", "Reason": error})
            self.set_collector(ITEM_FPING_V5, "failed", error)

    def run_fping(self) -> bool:
        cfg = self.fping_config()
        targets = [str((item or {}).get("host") or "").strip() for item in cfg.get("targets") or []]
        targets = [host for host in targets if host]
        if not targets:
            self.collector_log("[collector=fping_v5] DISABLED no non-empty targets")
            self.write_fping_summary({"Status": "disabled", "Reason": "未配置有效 Ping 目标"})
            self.set_collector(ITEM_FPING_V5, "disabled")
            return False
        path = Path(str(self.tools().get("fping_path") or "tools/windows-x64/fping/fping.exe")).resolve()
        if not path.exists():
            raise FileNotFoundError(f"未找到 fping.exe: {path}")
        missing = [name for name in ("cygwin1.dll",) if not (path.parent / name).exists()]
        if missing:
            raise FileNotFoundError("fping 依赖文件缺失: " + ", ".join(missing))
        interval_ms, timeout_ms, packet_size = int(cfg.get("interval_ms") or 10), int(cfg.get("timeout_ms") or 100), int(cfg.get("packet_size") or 64)
        args = [str(path), "-J", "-b", str(packet_size), "-l", "-p", str(max(1, interval_ms)), "-t", str(max(1, timeout_ms)), *targets]
        self.collector_log("[collector=fping_v5] START %s", " ".join(args))
        process = subprocess.Popen(args, cwd=path.parent, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", bufsize=1, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        stopper = threading.Thread(target=lambda: self._stop_child_on_event(process), name="fping-stop-watcher", daemon=True)
        stopper.start()
        stats: dict[str, dict[str, float | int | None]] = {host: {"sent": 0, "received": 0, "rtt_min_ms": None, "rtt_max_ms": None, "rtt_sum_ms": 0.0} for host in targets}
        fallback_seq = 0
        try:
            with (self.raw_dir / "fping_v5_raw.log").open("a", encoding="utf-8", errors="replace") as raw, (self.raw_dir / "fping_v5_samples.jsonl").open("a", encoding="utf-8", errors="replace") as samples:
                self.set_collector(ITEM_FPING_V5, "running")
                assert process.stdout is not None
                while not self.stop_event.is_set():
                    line = process.stdout.readline()
                    if not line:
                        if process.poll() is not None:
                            break
                        time.sleep(0.05)
                        continue
                    raw.write(f"{now_iso()} {line}")
                    raw.flush()
                    sample = parse_fping_line(line, now_iso(), timeout_ms, packet_size)
                    if sample is None:
                        continue
                    fallback_seq += 1
                    raw_seq = sample.get("seq")
                    sample["seq"] = raw_seq if raw_seq is not None else fallback_seq
                    samples.write(json.dumps(sample, ensure_ascii=False) + "\n")
                    samples.flush()
                    target = str(sample.get("target") or "")
                    state = stats.setdefault(target, {"sent": 0, "received": 0, "rtt_min_ms": None, "rtt_max_ms": None, "rtt_sum_ms": 0.0})
                    state["sent"] = int(state.get("sent") or 0) + 1
                    if sample.get("ok") and sample.get("rtt_ms") is not None:
                        rtt = float(sample["rtt_ms"])
                        state["received"] = int(state.get("received") or 0) + 1
                        state["rtt_sum_ms"] = float(state.get("rtt_sum_ms") or 0.0) + rtt
                        state["rtt_min_ms"] = rtt if state.get("rtt_min_ms") is None else min(float(state["rtt_min_ms"]), rtt)
                        state["rtt_max_ms"] = rtt if state.get("rtt_max_ms") is None else max(float(state["rtt_max_ms"]), rtt)
                    self.write_live_views()
        finally:
            self.stop_process(process)
            stopper.join(timeout=1)
            self.write_fping_summary(make_fping_summary(stats))
        return True

    def run_iperf_safe(self) -> None:
        self.set_collector(ITEM_IPERF_CLIENT, "starting")
        try:
            self.run_iperf()
            self.set_collector(ITEM_IPERF_CLIENT, "stopped" if self.stop_event.is_set() else "completed")
        except Exception as exc:
            error = str(exc)
            with self.state_lock:
                self.errors.append(f"iperf_client: {error}")
            append_text(self.raw_dir / "iperf_client_raw.log", f"{now_text()} [agent] collector failed: {error}\n")
            self.collector_log("[collector=iperf_client] FAILED error=%s", error)
            self.iperf_status = {"status": "failed", "error": error, "updated_at": now_iso()}
            self.set_collector(ITEM_IPERF_CLIENT, "failed", error)

    def run_iperf(self) -> None:
        cfg = self.iperf_config()
        host = str(cfg.get("server_host") or cfg.get("server_ip") or "").strip()
        if not host:
            raise RuntimeError("iPerf Client 未配置服务端地址")
        path = Path(str(self.tools().get("iperf3_path") or "tools/windows-x64/iperf3/iperf3.exe")).resolve()
        if not path.exists():
            raise FileNotFoundError(f"未找到 iperf3.exe: {path}")
        missing = [name for name in ("cygwin1.dll", "cygcrypto-3.dll", "cygz.dll") if not (path.parent / name).exists()]
        if missing:
            raise FileNotFoundError("iperf3 依赖文件缺失: " + ", ".join(missing))
        protocol, port = str(cfg.get("protocol") or "tcp").lower(), max(1, int(cfg.get("server_port") or cfg.get("port") or 5201))
        parallel, duration = max(1, int(cfg.get("parallel") or 1)), int(cfg.get("duration_sec") or 0)
        args = [str(path), "-c", host, "-p", str(port), "-i", str(max(0.1, float(cfg.get("report_interval") or 1))), "-t", str(duration if duration > 0 else 86400), "--json", "--forceflush", "-P", str(parallel)]
        if protocol == "udp":
            args.append("-u")
            if int(cfg.get("packet_length") or 0) > 0:
                args.extend(["-l", str(int(cfg["packet_length"]))])
        if cfg.get("bandwidth_mbps") not in (None, "", 0, "0"):
            args.extend(["-b", f"{float(cfg['bandwidth_mbps']):g}M"])
        args.append("-d")
        direction = str(cfg.get("direction") or "").lower()
        if cfg.get("reverse") or direction in {"download", "reverse"}:
            args.append("-R")
        elif cfg.get("bidirectional") or direction in {"bidirectional", "bidir"}:
            args.append("--bidir")
        self.collector_log("[collector=iperf_client] START %s", " ".join(args))
        process = subprocess.Popen(args, cwd=path.parent, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", bufsize=1, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        stopper = threading.Thread(target=lambda: self._stop_child_on_event(process), name="iperf-stop-watcher", daemon=True)
        stopper.start()
        self.iperf_status = {"status": "running", "server_host": host, "server_port": port, "protocol": protocol, "updated_at": now_iso()}
        try:
            with (self.raw_dir / "iperf_client_raw.log").open("a", encoding="utf-8", errors="replace") as raw:
                self.set_collector(ITEM_IPERF_CLIENT, "running")
                assert process.stdout is not None
                while not self.stop_event.is_set():
                    line = process.stdout.readline()
                    if not line:
                        if process.poll() is not None:
                            break
                        time.sleep(0.05)
                        continue
                    raw.write(f"{now_iso()} {line}")
                    raw.flush()
                    parsed = parse_iperf_line(line)
                    if parsed:
                        self.iperf_status.update(parsed)
                        self.iperf_status["updated_at"] = now_iso()
                    self.write_live_views()
        finally:
            self.stop_process(process)
            stopper.join(timeout=1)
            self.iperf_status.update({"status": "stopped" if self.stop_event.is_set() else "completed", "exit_code": process.poll(), "updated_at": now_iso()})
            self.write_live_views(force=True)
        if not self.stop_event.is_set() and process.returncode not in (0, None):
            raise RuntimeError(f"iperf3 进程退出码: {process.returncode}")

    def _stop_child_on_event(self, process: subprocess.Popen[Any]) -> None:
        while process.poll() is None:
            if self.stop_event.wait(0.1):
                self.stop_process(process)
                return

    def stop_process(self, process: subprocess.Popen[Any]) -> None:
        if process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=2)
        except Exception:
            try:
                process.kill()
                process.wait(timeout=2)
            except Exception:
                pass

    def write_fping_summary(self, summary: dict[str, Any]) -> None:
        self.fping_summary = summary
        write_json_atomic(self.raw_dir / "fping_v5_final_summary.json", summary)
        self.write_live_views(force=True)

    def write_live_views(self, force: bool = False) -> None:
        with self.view_lock:
            current = time.monotonic()
            if not force and current - self.last_view_write < 0.5:
                return
            self.last_view_write = current
            with self.state_lock:
                status, errors = self.status, list(self.errors)
            collectors = self._collector_snapshot()
            duration = max(0.0, (datetime.now() - self.start_time).total_seconds())
            write_json_atomic(self.session_dir / "view" / "live_mr_status.json", {"session_id": self.session_id(), "status": status, "updated_at": now_iso(), "duration_seconds": round(duration, 3), "target": {"name": self.device_name(), "host": self.target().get("host", "")}, "display_context": self.display_context(), "collectors": collectors, "errors": errors})
            write_json_atomic(self.session_dir / "view" / "live_link_status.json", self.live_link_status())
            write_json_atomic(self.session_dir / "view" / "live_fping_status.json", {"updated_at": now_iso(), "status": collectors.get(ITEM_FPING_V5, {}).get("status", "disabled"), "summary": self.fping_summary})
            write_json_atomic(self.session_dir / "view" / "live_iperf_status.json", {"updated_at": now_iso(), **self.iperf_status})

    def live_link_status(self) -> dict[str, Any]:
        try:
            text = (self.raw_dir / "mesh_link_raw.log").read_text(encoding="utf-8", errors="replace")[-20000:]
        except OSError:
            text = ""
        peer_name = (re.findall(r"(?im)^.*?peer\s*(?:name)?\s*[:=]\s*([^\r\n]+)", text) or [""])[-1].strip()
        peer_mac = (re.findall(r"(?i)(?:peer[_ ]?mac|peermac)\s*[:=]\s*([0-9a-f]{2}(?:[-:][0-9a-f]{2}){5}|[0-9a-f]{4}(?:[-][0-9a-f]{4}){2})", text) or [""])[-1].strip()
        rssi_text = (re.findall(r"(?i)(?:rssi|signal)\s*[:=]\s*(-?\d+(?:\.\d+)?)", text) or [""])[-1]
        state = (re.findall(r"(?i)(?:link[_ ]?state|state)\s*[:=]\s*([^\r\n]+)", text) or [""])[-1].strip()
        rssi: float | None = float(rssi_text) if rssi_text else None
        mapping = self.lookup_ap(peer_mac)
        context = dict(self.display_context())
        if mapping:
            peer_name = peer_name or str(mapping.get("ap_name") or "")
            for key in ("station", "section"):
                if not context.get(key) and mapping.get(key):
                    context[key] = mapping[key]
        if not any((peer_name, peer_mac, rssi is not None, state)):
            return {"available": False, "message": "暂无实时链路数据", "display_context": context, "updated_at": now_iso()}
        return {"available": True, "peer_name": peer_name, "peer_mac": peer_mac, "rssi": rssi, "link_state": state, "display_context": context, "updated_at": now_iso()}

    def lookup_ap(self, peer_mac: str) -> dict[str, Any] | None:
        if not peer_mac:
            return None
        path = Path(str(self.tools().get("ap_map_path") or "config/ap_map.json"))
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        wanted = re.sub(r"[-:.]", "", peer_mac).lower()
        for item in data.get("ap_map") or []:
            if re.sub(r"[-:.]", "", str((item or {}).get("ap_mac") or "")).lower() == wanted:
                return dict(item)
        return None


def parse_fping_line(line: str, ts: str, timeout_ms: int, packet_size: int) -> dict[str, Any] | None:
    try:
        payload = json.loads(line.strip())
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    if isinstance(payload.get("resp"), dict):
        item = payload["resp"]
        return {"ts": ts, "target": str(item.get("host") or ""), "seq": _int_or_none(item.get("seq")), "ok": True, "rtt_ms": _float_or_none(item.get("rtt")), "bytes": _int_or_none(item.get("size")) or packet_size, "source": "fping_v5", "raw": payload}
    if isinstance(payload.get("timeout"), dict):
        item = payload["timeout"]
        return {"ts": ts, "target": str(item.get("host") or ""), "seq": _int_or_none(item.get("seq")), "ok": False, "error": "timeout", "bytes": packet_size, "source": "fping_v5", "raw": payload}
    return None


def parse_iperf_line(line: str) -> dict[str, Any] | None:
    match = re.search(r"(?i)([0-9]+(?:\.[0-9]+)?)\s*([kmgt])bits/sec", str(line or ""))
    if not match:
        return None
    return {"bitrate_mbps": round(float(match.group(1)) * {"k": 0.001, "m": 1.0, "g": 1000.0, "t": 1_000_000.0}[match.group(2).lower()], 3), "raw_line": str(line).strip()}


def _int_or_none(value: Any) -> int | None:
    try:
        return None if value is None else int(value)
    except Exception:
        return None


def _float_or_none(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except Exception:
        return None


def make_fping_summary(stats: dict[str, dict[str, float | int | None]]) -> dict[str, Any]:
    result: dict[str, Any] = {"Status": "normal", "targets": {}}
    sent_total = received_total = 0
    for target, state in stats.items():
        sent, received = int(state.get("sent") or 0), int(state.get("received") or 0)
        result["targets"][target] = {"sent": sent, "received": received, "lost": max(0, sent - received), "loss_percent": 0.0 if sent == 0 else round((sent - received) * 100 / sent, 3), "min_latency_ms": state.get("rtt_min_ms"), "avg_latency_ms": None if received == 0 else round(float(state.get("rtt_sum_ms") or 0) / received, 3), "max_latency_ms": state.get("rtt_max_ms")}
        sent_total += sent
        received_total += received
    result.update({"sent": sent_total, "received": received_total, "lost": max(0, sent_total - received_total), "loss_percent": 0.0 if sent_total == 0 else round((sent_total - received_total) * 100 / sent_total, 3)})
    return result


def configure_standard_streams() -> None:
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is not None:
            try:
                stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
            except Exception:
                pass


def main() -> int:
    configure_standard_streams()
    parser = argparse.ArgumentParser(description="NetConsole MR Collector sidecar")
    parser.add_argument("--version", action="store_true")
    parser.add_argument("--request")
    parser.add_argument("--session-dir")
    parser.add_argument("--stop-file")
    parser.add_argument("--event-file")
    parser.add_argument("--status-file")
    args = parser.parse_args()
    if args.version:
        print(VERSION)
        return 0
    required = (args.request, args.session_dir, args.stop_file, args.event_file, args.status_file)
    if any(not value for value in required):
        parser.error("--request --session-dir --stop-file --event-file --status-file are required")
    app = MRCollectorApp(load_json(Path(args.request)), Path(args.session_dir).resolve(), Path(args.stop_file).resolve(), Path(args.event_file).resolve(), Path(args.status_file).resolve())
    def handle_signal(signum: int, frame: object) -> None:
        app.collector_log("[agent] signal received signum=%s", signum)
        app.stop_event.set()
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    return app.run()


if __name__ == "__main__":
    raise SystemExit(main())
