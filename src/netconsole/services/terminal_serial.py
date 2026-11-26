from __future__ import annotations

import codecs
import json
import os
import re
import threading
from dataclasses import asdict, dataclass
from typing import Any

from netconsole.core.paths import PathResolver


class SerialConfigurationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SerialConnectionOptions:
    port: str
    baud_rate: int = 9600
    data_bits: int = 8
    parity: str = "N"
    stop_bits: float = 1
    flow_control: str = "none"
    encoding: str = "utf-8"
    line_ending: str = "CR"
    local_echo: bool = False
    dtr: str = "KEEP"
    rts: str = "KEEP"
    timeout_seconds: float = 0.05

    @classmethod
    def from_mapping(cls, value: Any, *, allow_empty_port: bool = False) -> SerialConnectionOptions:
        if not isinstance(value, dict):
            raise SerialConfigurationError("串口参数必须是对象")
        allowed = {
            "port", "baud_rate", "data_bits", "parity", "stop_bits", "flow_control",
            "encoding", "line_ending", "local_echo", "dtr", "rts", "timeout_seconds",
        }
        unknown = set(value) - allowed
        if unknown:
            raise SerialConfigurationError(f"串口参数包含未知字段：{', '.join(sorted(unknown))}")
        defaults = asdict(cls(port=""))
        options = {**defaults, **value}
        port = str(options["port"]).strip()
        if (not port and not allow_empty_port) or len(port) > 260 or "\x00" in port or "://" in port:
            raise SerialConfigurationError("请选择有效的串口端口")
        try:
            baud_rate = int(options["baud_rate"])
        except (TypeError, ValueError) as exc:
            raise SerialConfigurationError("波特率必须是整数") from exc
        if not 50 <= baud_rate <= 4_000_000:
            raise SerialConfigurationError("波特率必须在 50 至 4000000 之间")
        try:
            data_bits = int(options["data_bits"])
        except (TypeError, ValueError) as exc:
            raise SerialConfigurationError("数据位无效") from exc
        if data_bits not in {5, 6, 7, 8}:
            raise SerialConfigurationError("数据位只支持 5、6、7 或 8")
        parity = str(options["parity"]).upper()
        if parity not in {"N", "O", "E", "M", "S"}:
            raise SerialConfigurationError("校验位只支持无、奇、偶、Mark 或 Space")
        try:
            stop_bits = float(options["stop_bits"])
        except (TypeError, ValueError) as exc:
            raise SerialConfigurationError("停止位无效") from exc
        if stop_bits not in {1.0, 1.5, 2.0} or (stop_bits == 1.5 and data_bits != 5):
            raise SerialConfigurationError("停止位组合不受支持；1.5 停止位仅适用于 5 数据位")
        flow_control = str(options["flow_control"]).lower()
        if flow_control not in {"none", "rtscts", "dsrdtr", "xonxoff"}:
            raise SerialConfigurationError("流控只支持无、RTS/CTS、DTR/DSR 或 XON/XOFF")
        encoding = str(options["encoding"]).strip().lower()
        try:
            codecs.lookup("mbcs" if encoding == "ansi" else encoding)
        except LookupError as exc:
            raise SerialConfigurationError("串口编码不受支持") from exc
        line_ending = str(options["line_ending"]).upper()
        if line_ending not in {"CR", "LF", "CRLF"}:
            raise SerialConfigurationError("回车发送模式只支持 CR、LF 或 CRLF")
        if type(options["local_echo"]) is not bool:
            raise SerialConfigurationError("本地回显必须是布尔值")
        dtr = str(options["dtr"]).upper()
        rts = str(options["rts"]).upper()
        if dtr not in {"KEEP", "ON", "OFF"} or rts not in {"KEEP", "ON", "OFF"}:
            raise SerialConfigurationError("DTR/RTS 只支持保持原状态、启用或关闭")
        try:
            timeout = float(options["timeout_seconds"])
        except (TypeError, ValueError) as exc:
            raise SerialConfigurationError("串口读取间隔无效") from exc
        if not 0.01 <= timeout <= 2:
            raise SerialConfigurationError("串口读取间隔必须在 0.01 至 2 秒之间")
        return cls(
            port=port,
            baud_rate=baud_rate,
            data_bits=data_bits,
            parity=parity,
            stop_bits=stop_bits,
            flow_control=flow_control,
            encoding=encoding,
            line_ending=line_ending,
            local_echo=options["local_echo"],
            dtr=dtr,
            rts=rts,
            timeout_seconds=timeout,
        )


def _default_profiles() -> list[dict[str, Any]]:
    return [
        {
            "profile_id": "h3c-console",
            "name": "H3C Console",
            "built_in": True,
            "options": asdict(SerialConnectionOptions(port="", baud_rate=9600)),
        },
        {
            "profile_id": "h3c-console-fast",
            "name": "H3C 高速 Console",
            "built_in": True,
            "options": asdict(SerialConnectionOptions(port="", baud_rate=115200)),
        },
    ]


class SerialPortService:
    def enumerate_ports(self) -> list[dict[str, str]]:
        try:
            from serial.tools import list_ports
        except ImportError as exc:
            raise RuntimeError("串口运行依赖未随程序安装") from exc
        try:
            return [
                {
                    "port": str(item.device),
                    "name": str(item.name or item.device),
                    "description": str(item.description or ""),
                    "manufacturer": str(item.manufacturer or ""),
                    "hardware_id": str(item.hwid or ""),
                }
                for item in sorted(list_ports.comports(), key=lambda port: str(port.device).casefold())
            ]
        except Exception as exc:
            raise RuntimeError("读取系统串口列表失败") from exc


class SerialProfileStore:
    MAX_PROFILES = 100
    BUILT_IN_IDS: frozenset[str] = frozenset({"h3c-console", "h3c-console-fast"})

    def __init__(self, paths: PathResolver) -> None:
        self.path = paths.config_dir / "terminal" / "serial-profiles.json"
        self.lock = threading.RLock()

    def document(self) -> dict[str, Any]:
        with self.lock:
            custom = self._read_custom()
            return {"schema_version": 1, "profiles": [*_default_profiles(), *custom]}

    def save_custom_profiles(self, values: Any) -> dict[str, Any]:
        result = self._validate_custom_profiles(values)
        document = {"schema_version": 1, "profiles": result}
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".json.part")
            with temporary.open("w", encoding="utf-8", newline="\n") as stream:
                json.dump(document, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        return {"schema_version": 1, "profiles": [*_default_profiles(), *result]}

    @classmethod
    def _validate_custom_profiles(cls, values: Any) -> list[dict[str, Any]]:
        if not isinstance(values, list) or len(values) > cls.MAX_PROFILES:
            raise SerialConfigurationError("自定义串口模板数量不能超过 100 个")
        result: list[dict[str, Any]] = []
        ids: set[str] = set()
        names: set[str] = set()
        for value in values:
            if not isinstance(value, dict) or set(value) != {"profile_id", "name", "options"}:
                raise SerialConfigurationError("串口模板结构无效")
            profile_id = str(value["profile_id"])
            name = str(value["name"]).strip()
            if not re.fullmatch(r"[0-9a-f-]{36}", profile_id) or profile_id in cls.BUILT_IN_IDS or profile_id in ids:
                raise SerialConfigurationError("串口模板标识无效或重复")
            if not name or len(name) > 80 or name.casefold() in names:
                raise SerialConfigurationError("串口模板名称无效或重复")
            options = SerialConnectionOptions.from_mapping(value["options"], allow_empty_port=True)
            ids.add(profile_id)
            names.add(name.casefold())
            result.append({"profile_id": profile_id, "name": name, "options": asdict(options)})
        return result

    def import_document(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict) or set(value) != {"schema_version", "profiles"} or value["schema_version"] != 1:
            raise SerialConfigurationError("串口模板文件版本或结构无效")
        profiles = value["profiles"]
        if not isinstance(profiles, list) or any(not isinstance(item, dict) or item.get("built_in") for item in profiles):
            raise SerialConfigurationError("只能导入自定义串口模板")
        custom = self._validate_custom_profiles(profiles)
        return self.save_custom_profiles(custom)

    def _read_custom(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SerialConfigurationError("串口模板文件无法读取或格式错误") from exc
        if not isinstance(value, dict) or set(value) != {"schema_version", "profiles"} or value["schema_version"] != 1:
            raise SerialConfigurationError("串口模板文件版本或结构无效")
        return self._validate_custom_profiles(value["profiles"])


class SerialSessionAPI:
    """Automation-facing facade over the shared TerminalSessionManager lifecycle."""

    def __init__(self, manager: Any) -> None:
        self.manager = manager

    def enumerate_ports(self) -> list[dict[str, str]]:
        return self.manager.serial_ports.enumerate_ports()

    def open_session(self, options: dict[str, Any], *, cols: int = 120, rows: int = 32):
        return self.manager.create_serial_session(options, cols=cols, rows=rows)

    def close_session(self, session_id: str) -> dict[str, Any]:
        return self.manager.close_session(session_id)

    def send_text(self, session_id: str, text: str) -> None:
        self.manager.input(session_id, text)

    def send_bytes(self, session_id: str, data: bytes) -> None:
        self.manager.send_serial_bytes(session_id, data)

    def receive(self, session_id: str, offset: int = 0, timeout_seconds: float = 0):
        return self.manager.receive_serial_bytes(session_id, offset, timeout_seconds)

    def wait_for_pattern(self, session_id: str, pattern: bytes, timeout_seconds: float):
        return self.manager.wait_for_serial_pattern(session_id, pattern, timeout_seconds)

    def flush(self, session_id: str, direction: str = "both") -> None:
        self.manager.flush_serial(session_id, direction)

    def cancel(self, session_id: str) -> dict[str, Any]:
        return self.manager.close_session(session_id)


__all__ = [
    "SerialConfigurationError",
    "SerialConnectionOptions",
    "SerialPortService",
    "SerialProfileStore",
    "SerialSessionAPI",
]
