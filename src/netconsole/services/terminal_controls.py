"""Console button configuration and dispatch over existing interactive sessions."""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from netconsole.services.site_manager import SiteManager

MENU_FUNCTIONS = {
    "find",
    "select-all",
    "clear-scrollback",
    "clear-screen",
    "clear-all",
}


def send_segments(text: str):
    buffer = ""
    index = 0
    escapes = {"r": "\r", "n": "\n", "e": "\x1b", "t": "\t", "b": "\b", "s": " ", "\\": "\\"}
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 1
            if index >= len(text) or text[index] not in {*escapes, "p"}:
                raise ValueError("Send String 包含不支持的转义")
            if text[index] == "p":
                if buffer:
                    yield buffer, 0
                    buffer = ""
                start = index + 1
                while index + 1 < len(text) and "0" <= text[index + 1] <= "9":
                    index += 1
                digits = text[start:index + 1]
                if len(digits) > 5 or (digits and not 1 <= int(digits) <= 60_000):
                    raise ValueError("暂停时长须为 1 至 60000 毫秒")
                yield "", int(digits) / 1000 if digits else 1
            else:
                buffer += escapes[text[index]]
        else:
            buffer += char
        index += 1
    if buffer:
        yield buffer, 0


class QuickButtonStore:
    def __init__(self, paths):
        self.path = paths.config_dir / "terminal" / "quick-buttons.json"
        self.lock = threading.RLock()

    @staticmethod
    def defaults():
        groups = []
        for index, name in enumerate(
            ["通用网络设备", "H3C 交换机", "H3C AC", "H3C AP", "用户自定义"]
        ):
            groups.append(
                {
                    "id": f"group-{index}",
                    "name": name,
                    "buttons": []
                    if index == 4
                    else [
                        {
                            "id": f"version-{index}",
                            "name": "版本",
                            "action": "SEND_STRING",
                            "text": r"display version\r",
                            "launch_with_session_context": False,
                            "color": "#409eff",
                            "tooltip": "显示设备版本",
                            "disable_tooltip": False,
                            "order": 0,
                            "enabled": True,
                        },
                        {
                            "id": f"interfaces-{index}",
                            "name": "接口",
                            "action": "SEND_STRING",
                            "text": r"display interface brief\r",
                            "launch_with_session_context": False,
                            "color": "#67c23a",
                            "tooltip": "显示接口摘要",
                            "disable_tooltip": False,
                            "order": 1,
                            "enabled": True,
                        },
                    ],
                }
            )
        return {"version": 2, "groups": groups}

    def read(self):
        with self.lock:
            if not self.path.exists():
                return self.defaults()
            source = json.loads(self.path.read_text(encoding="utf-8"))
            document = self.validate(source)
            if source.get("version") != document["version"]:
                self.save(document)
            return document

    @staticmethod
    def validate(value):
        if (
            not isinstance(value, dict)
            or value.get("version") not in {1, 2}
            or set(value) != {"version", "groups"}
        ):
            raise ValueError("按钮配置版本或结构无效")
        source_version = value["version"]
        groups = value["groups"]
        if not isinstance(groups, list) or not 1 <= len(groups) <= 32:
            raise ValueError("按钮组数量无效")
        ids = set()
        for group in groups:
            if (
                set(group) != {"id", "name", "buttons"}
                or not isinstance(group["buttons"], list)
                or len(group["buttons"]) > 200
            ):
                raise ValueError("按钮组无效")
            for item in [group, *group["buttons"]]:
                if (
                    not isinstance(item.get("id"), str)
                    or not re.fullmatch(r"[\w-]{1,80}", item["id"])
                    or item["id"] in ids
                ):
                    raise ValueError("按钮标识重复或无效")
                ids.add(item["id"])
                if (
                    not isinstance(item.get("name"), str)
                    or not 1 <= len(item["name"]) <= 80
                ):
                    raise ValueError("按钮名称无效")
            for button in group["buttons"]:
                if (
                    set(button)
                    != {
                        "id",
                        "name",
                        "action",
                        "text",
                        "color",
                        "tooltip",
                        "disable_tooltip",
                        "order",
                        "enabled",
                    } | ({"launch_with_session_context"} if source_version == 2 else set())
                    or button["action"] not in {"SEND_STRING", "MENU_FUNCTION", "LAUNCH_APPLICATION", "RUN_SCRIPT"}
                ):
                    raise ValueError("按钮动作无效")
                launch_context = button.get(
                    "launch_with_session_context",
                    button["action"] == "LAUNCH_APPLICATION",
                )
                if type(launch_context) is not bool:
                    raise ValueError("外部应用会话变量设置无效")
                if (
                    not isinstance(button["text"], str)
                    or len(button["text"]) > 65536
                    or not isinstance(button["tooltip"], str)
                    or len(button["tooltip"]) > 500
                ):
                    raise ValueError("按钮内容过长")
                if (
                    not re.fullmatch(r"#[0-9a-fA-F]{6}", button["color"])
                    or type(button["order"]) is not int
                    or not 0 <= button["order"] <= 10000
                    or type(button["enabled"]) is not bool
                    or type(button["disable_tooltip"]) is not bool
                ):
                    raise ValueError("按钮显示属性无效")
                if button["action"] == "SEND_STRING":
                    list(send_segments(button["text"]))
                elif button["action"] == "MENU_FUNCTION":
                    if button["text"] not in MENU_FUNCTIONS:
                        raise ValueError("菜单按钮功能无效")
                elif button["action"] == "LAUNCH_APPLICATION":
                    if not re.fullmatch(
                        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-8][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}",
                        button["text"],
                    ):
                        raise ValueError("应用按钮必须引用已登记的 External Tool")
                else:
                    try:
                        script = json.loads(button["text"])
                    except json.JSONDecodeError as exc:
                        raise ValueError("Console 脚本必须是有效 JSON") from exc
                    if not isinstance(script, dict) or set(script) != {"version", "steps"} or script["version"] != 1:
                        raise ValueError("Console 脚本版本或结构无效")
                    steps = script["steps"]
                    if not isinstance(steps, list) or not 1 <= len(steps) <= 100:
                        raise ValueError("Console 脚本步骤数量无效")
                    total_wait = 0
                    for step in steps:
                        if not isinstance(step, dict):
                            raise ValueError("Console 脚本步骤无效")
                        if step.get("type") == "SEND_STRING" and set(step) == {"type", "text"} and isinstance(step["text"], str):
                            total_wait += sum(round(delay * 1000) for _, delay in send_segments(step["text"]))
                        elif step.get("type") == "WAIT" and set(step) == {"type", "milliseconds"} and type(step["milliseconds"]) is int and 1 <= step["milliseconds"] <= 60_000:
                            total_wait += step["milliseconds"]
                        else:
                            raise ValueError("Console 脚本步骤动作或参数无效")
                    if total_wait > 600_000:
                        raise ValueError("Console 脚本等待总时长不能超过 600000 毫秒")
        document = deepcopy(value)
        document["version"] = 2
        for group in document["groups"]:
            for button in group["buttons"]:
                button.setdefault(
                    "launch_with_session_context",
                    button["action"] == "LAUNCH_APPLICATION",
                )
        return document

    def save(self, value):
        document = self.validate(value)
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".part")
            with temporary.open("w", encoding="utf-8") as stream:
                json.dump(document, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.path)
        return document


class BatchCommandDispatcher:
    def __init__(self, manager):
        self.manager = manager
        self.buttons = QuickButtonStore(manager.paths)
        self.jobs = {}
        self.lock = threading.RLock()
        # Bound background sends, never admission to device SSH connections.
        self.executor = ThreadPoolExecutor(
            max_workers=16, thread_name_prefix="console-send"
        )

    def submit(
        self,
        session_ids,
        text,
        mode="block",
        interval_ms=0,
        scope="current",
        button=None,
        execution_mode="concurrent",
        max_concurrency=4,
        device_timeout=15,
        total_timeout=300,
        max_retries=0,
        fail_policy="continue",
        output_wait_timeout=1,
    ):
        if (
            not session_ids
            or len(session_ids) > 128
            or not isinstance(text, str)
            or len(text) > 65536
            or mode not in {"block", "lines", "escaped"}
            or interval_ms not in {0, 200, 500, 1000}
            or execution_mode not in {"sequential", "concurrent"}
            or type(max_concurrency) is not int
            or not 1 <= max_concurrency <= 16
            or type(device_timeout) not in {int, float}
            or not 1 <= device_timeout <= 300
            or type(total_timeout) not in {int, float}
            or not 1 <= total_timeout <= 3600
            or type(max_retries) is not int
            or not 0 <= max_retries <= 3
            or fail_policy not in {"continue", "stop"}
            or type(output_wait_timeout) not in {int, float}
            or not 0 <= output_wait_timeout <= 10
        ):
            raise ValueError("命令发送参数无效")
        if button:
            group_id, button_id = button
            item = next(
                (
                    b
                    for g in self.buttons.read()["groups"]
                    if g["id"] == group_id
                    for b in g["buttons"]
                    if b["id"] == button_id and b["enabled"]
                ),
                None,
            )
            if item is None:
                raise ValueError("快捷按钮不存在或已禁用")
            if item["action"] != "SEND_STRING":
                raise ValueError("非命令按钮不能作为命令发送")
            text, mode = item["text"], "escaped"
        if mode == "escaped":
            segments = list(send_segments(text))
        elif mode == "lines":
            lines = re.split(r"\r\n|\r|\n", text)
            segments = [(line + "\r", interval_ms / 1000) for line in lines]
        else:
            segments = [(text, 0)]
        job_id = uuid.uuid4().hex
        rows = [
            {
                "session_id": key,
                "state": "WAITING",
                "sent_segments": 0,
                "device_uuid": "",
                "name": "",
                "error": "",
                "sent_at_ms": None,
                "next_segment": 0,
                "address": "",
                "started_at_ms": None,
                "ended_at_ms": None,
                "duration_ms": None,
                "command": text,
                "output": "",
                "retry_count": 0,
            }
            for key in dict.fromkeys(session_ids)
        ]
        job = {
            "id": job_id,
            "scope": scope,
            "rows": rows,
            "cancel": threading.Event(),
            "segments": segments,
            "site": SiteManager(self.manager.paths).get_current_site(),
            "execution_mode": execution_mode,
            "max_concurrency": max_concurrency,
            "device_timeout": float(device_timeout),
            "total_timeout": float(total_timeout),
            "deadline": time.monotonic() + float(total_timeout),
            "max_retries": max_retries,
            "fail_policy": fail_policy,
            "output_wait_timeout": float(output_wait_timeout),
            "pause": threading.Event(),
            "paused": False,
            "started_at_ms": int(time.time() * 1000),
            "ended_at_ms": None,
            "semaphore": threading.BoundedSemaphore(max_concurrency),
            "stop_after_failure": threading.Event(),
        }
        with self.lock:
            if (
                sum(
                    any(row["state"] in {"WAITING", "RUNNING"} for row in item["rows"])
                    for item in self.jobs.values()
                )
                >= 100
            ):
                raise ValueError("命令发送队列繁忙，请稍后重试")
            finished = [
                key
                for key, item in self.jobs.items()
                if all(
                    row["state"] not in {"WAITING", "RUNNING"} for row in item["rows"]
                )
            ]
            while len(self.jobs) >= 200 and finished:
                self.jobs.pop(finished.pop(0), None)
            self.jobs[job_id] = job
        if execution_mode == "sequential":
            self.executor.submit(self._send_sequential, job)
        else:
            for row in rows:
                self.executor.submit(self._send, job, row)
        return self.get(job_id)

    def _send_sequential(self, job):
        for row in job["rows"]:
            if job["cancel"].is_set():
                row["state"] = "CANCELLED_PENDING"
                continue
            if job["fail_policy"] == "stop" and (
                job["stop_after_failure"].is_set() or any(
                item["state"] in {"FAILED", "UNCONFIRMED"} for item in job["rows"]
                )
            ):
                row["state"] = "SKIPPED"
                continue
            self._send(job, row)

    @staticmethod
    def _wait_if_paused(job):
        while job["paused"] and not job["cancel"].is_set():
            job["pause"].wait(0.1)
        return job["cancel"].is_set()

    def _wait_delay(self, job, delay, device_deadline):
        until = time.monotonic() + delay
        while time.monotonic() < until:
            if self._wait_if_paused(job):
                return "CANCELLED_PENDING"
            if time.monotonic() >= job["deadline"] or time.monotonic() >= device_deadline:
                return "TIMEOUT"
            job["cancel"].wait(min(0.1, until - time.monotonic()))
        return ""

    def _capture_output(self, job, runtime, row, start_offset, timeout, device_deadline):
        if timeout <= 0:
            return
        deadline = min(time.monotonic() + timeout, job["deadline"], device_deadline)
        output_chunks = deque()
        output_length = 0
        last_output = time.monotonic()
        try:
            with runtime.recording.events_path.open("r", encoding="utf-8") as stream:
                stream.seek(start_offset)
                while time.monotonic() < deadline and not job["cancel"].is_set():
                    for line in stream:
                        try:
                            event = json.loads(line)
                        except ValueError:
                            continue
                        if event.get("event_type") == "OUTPUT":
                            value = str(event.get("data") or "")
                            if value:
                                output_chunks.append(value)
                                output_length += len(value)
                                while output_length > 2_000_000:
                                    excess = output_length - 2_000_000
                                    first = output_chunks[0]
                                    if excess >= len(first):
                                        output_chunks.popleft()
                                        output_length -= len(first)
                                    else:
                                        output_chunks[0] = first[excess:]
                                        output_length -= excess
                                last_output = time.monotonic()
                    if output_chunks:
                        row["output"] = "".join(output_chunks)
                    if output_chunks and time.monotonic() - last_output >= 0.35:
                        break
                    time.sleep(0.05)
        except (OSError, UnicodeError):
            row["output_error"] = "无法读取该会话的输出记录"

    def _send(self, job, row):
        held_lock = None
        semaphore_acquired = False
        retry_requested = False
        try:
            if self._wait_if_paused(job):
                row["state"] = "CANCELLED_PENDING"
                return
            if job["fail_policy"] == "stop" and job["stop_after_failure"].is_set():
                row["state"] = "SKIPPED"
                return
            if time.monotonic() >= job["deadline"]:
                row.update(state="FAILED", error="批量任务总超时")
                return
            runtime = self.manager.get_runtime(row["session_id"])
            if runtime.snapshot.site_name != job["site"]:
                raise ValueError("目标会话不属于当前局点")
            row.update(
                device_uuid=runtime.snapshot.device_uuid,
                name=runtime.snapshot.session_name or runtime.snapshot.device_name,
                address=runtime.snapshot.address,
            )
            while not job["semaphore"].acquire(timeout=0.1):
                if job["cancel"].is_set():
                    row["state"] = "CANCELLED_PENDING"
                    return
                if time.monotonic() >= job["deadline"]:
                    raise TimeoutError("批量任务总超时")
            semaphore_acquired = True
            if job["fail_policy"] == "stop" and job["stop_after_failure"].is_set():
                row["state"] = "SKIPPED"
                return
            device_deadline = min(
                job["deadline"], time.monotonic() + job["device_timeout"]
            )
            while not runtime.dispatch_lock.acquire(timeout=0.1):
                if job["cancel"].is_set():
                    row["state"] = "CANCELLED_PENDING"
                    return
                if time.monotonic() >= device_deadline:
                    raise TimeoutError("等待设备会话写入锁超时")
            held_lock = runtime.dispatch_lock
            row["state"] = "RUNNING"
            row["started_at_ms"] = int(time.time() * 1000)
            start_offset = runtime.recording.events_path.stat().st_size
            for index, (data, delay) in enumerate(job["segments"]):
                if index < row.get("next_segment", 0):
                    continue
                if self._wait_if_paused(job):
                    row["state"] = "CANCELLED_PENDING"
                    return
                if job["cancel"].is_set():
                    row["state"] = "CANCELLED_PENDING"
                    return
                if time.monotonic() >= device_deadline or time.monotonic() >= job["deadline"]:
                    raise TimeoutError("设备发送超时")
                if data:
                    receipt = {"done": threading.Event(), "error": "", "cancel": job["cancel"], "scope": job["scope"]}
                    self.manager.input(row["session_id"], data, receipt=receipt)
                    wait = min(15.0, max(0.01, device_deadline - time.monotonic()))
                    if not receipt["done"].wait(wait):
                        raise TimeoutError("设备写入确认超时，结果可能已部分发送")
                    if receipt["error"]:
                        raise TimeoutError(f"设备写入未确认：{receipt['error']}")
                    row["sent_segments"] += 1
                    row["sent_at_ms"] = int(time.time() * 1000)
                if delay:
                    wait_result = self._wait_delay(job, delay, device_deadline)
                    if wait_result:
                        row["state"] = wait_result
                        if wait_result == "TIMEOUT":
                            raise TimeoutError("设备发送间隔超过任务超时")
                        return
                row["next_segment"] = index + 1
            self._capture_output(
                job, runtime, row, start_offset, job["output_wait_timeout"], device_deadline
            )
            row["state"] = "SENT"
        except TimeoutError as exc:
            row.update(
                state="CANCELLED_PENDING" if job["cancel"].is_set() else "UNCONFIRMED",
                error=str(exc)[:500],
            )
        except Exception as exc:
            if (
                not job["cancel"].is_set()
                and row["sent_segments"] == 0
                and row["retry_count"] < job["max_retries"]
                and time.monotonic() < job["deadline"]
            ):
                row["retry_count"] += 1
                row.update(state="WAITING", error="")
                retry_requested = True
            else:
                row.update(
                    state="CANCELLED_PENDING" if job["cancel"].is_set() else "FAILED",
                    error=str(exc)[:500],
                )
                if job["fail_policy"] == "stop":
                    job["stop_after_failure"].set()
        finally:
            if semaphore_acquired:
                job["semaphore"].release()
            if held_lock is not None:
                held_lock.release()
            if row.get("started_at_ms") and not row.get("ended_at_ms"):
                row["ended_at_ms"] = int(time.time() * 1000)
                row["duration_ms"] = row["ended_at_ms"] - row["started_at_ms"]
            if all(item["state"] not in {"WAITING", "RUNNING", "PAUSED"} for item in job["rows"]):
                job["ended_at_ms"] = job["ended_at_ms"] or int(time.time() * 1000)
        if retry_requested:
            self._send(job, row)

    def get(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                raise KeyError("命令发送任务不存在")
            if job["site"] != SiteManager(self.manager.paths).get_current_site():
                raise KeyError("命令发送任务不属于当前局点")
            active = any(row["state"] in {"WAITING", "RUNNING"} for row in job["rows"])
            failures = any(row["state"] in {"FAILED", "UNCONFIRMED"} for row in job["rows"])
            sent = any(row["state"] == "SENT" for row in job["rows"])
            state = "CANCELLED" if job["cancel"].is_set() and not active else (
                "PAUSED" if job["paused"] and active else "RUNNING" if active else "COMPLETED"
            )
            if not active and not job["cancel"].is_set() and failures:
                state = "PARTIAL" if sent else "FAILED"
            return {
                "id": job_id, "scope": job["scope"], "rows": deepcopy(job["rows"]),
                "state": state, "execution_mode": job["execution_mode"],
                "started_at_ms": job["started_at_ms"], "ended_at_ms": job["ended_at_ms"],
            }

    def cancel(self, job_id):
        self.get(job_id)
        self.jobs[job_id]["cancel"].set()
        return self.get(job_id)

    def set_paused(self, job_id, paused):
        self.get(job_id)
        with self.lock:
            job = self.jobs[job_id]
            if not any(row["state"] in {"WAITING", "RUNNING"} for row in job["rows"]):
                raise ValueError("已结束的批量任务不能暂停或恢复")
            job["paused"] = bool(paused)
            if paused:
                job["pause"].clear()
            else:
                job["pause"].set()
        return self.get(job_id)

    def export(self, job_id, format):
        import csv
        import io

        job = self.get(job_id)
        rows = job["rows"]
        columns = ("name", "address", "started_at_ms", "ended_at_ms", "duration_ms", "state", "command", "output", "error")
        if format == "txt":
            return "\n\n".join(
                f"{row['name']} ({row['address']}) [{row['state']}]\n"
                f"命令：{row['command']}\n耗时：{row['duration_ms']} ms\n"
                f"{row['output'] or row['error']}"
                for row in rows
            )
        if format != "csv":
            raise ValueError("不支持的批量任务导出格式")
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        writer.writerows({key: row.get(key, "") for key in columns} for row in rows)
        return output.getvalue()

    def retry(self, job_id, session_id):
        self.get(job_id)
        with self.lock:
            job = self.jobs[job_id]
            row = next(row for row in job["rows"] if row["session_id"] == session_id)
            if row["state"] != "FAILED" or row.get("sent_segments", 0) or row.get("next_segment", 0):
                raise ValueError("只有尚未发送任何数据的失败目标可重试")
            retry_id = uuid.uuid4().hex
            retry_row = {**row, "state": "WAITING", "error": ""}
            retry_job = {
                **job,
                "id": retry_id,
                "rows": [retry_row],
                "cancel": threading.Event(),
            }
            self.jobs[retry_id] = retry_job
            self.executor.submit(self._send, retry_job, retry_row)
        return self.get(retry_id)

    def close(self):
        for job in self.jobs.values():
            job["cancel"].set()
        self.executor.shutdown(wait=True, cancel_futures=True)
