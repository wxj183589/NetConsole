"""Console button configuration and dispatch over existing interactive sessions."""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from netconsole.services.site_manager import SiteManager


def send_segments(text: str):
    buffer = ""
    index = 0
    escapes = {"r": "\r", "n": "\n", "e": "\x1b", "t": "\t", "b": "\b", "\\": "\\"}
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
                yield "", 1
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
                            "color": "#67c23a",
                            "tooltip": "显示接口摘要",
                            "disable_tooltip": False,
                            "order": 1,
                            "enabled": True,
                        },
                    ],
                }
            )
        return {"version": 1, "groups": groups}

    def read(self):
        with self.lock:
            return (
                self.validate(json.loads(self.path.read_text(encoding="utf-8")))
                if self.path.exists()
                else self.defaults()
            )

    @staticmethod
    def validate(value):
        if (
            not isinstance(value, dict)
            or value.get("version") != 1
            or set(value) != {"version", "groups"}
        ):
            raise ValueError("按钮配置版本或结构无效")
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
                    }
                    or button["action"] != "SEND_STRING"
                ):
                    raise ValueError("按钮动作无效")
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
                list(send_segments(button["text"]))
        return deepcopy(value)

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
            max_workers=4, thread_name_prefix="console-send"
        )

    def submit(
        self,
        session_ids,
        text,
        mode="block",
        interval_ms=0,
        scope="current",
        button=None,
    ):
        if (
            not session_ids
            or not isinstance(text, str)
            or len(text) > 65536
            or mode not in {"block", "lines", "escaped"}
            or interval_ms not in {0, 200, 500, 1000}
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
        for row in rows:
            self.executor.submit(self._send, job, row)
        return self.get(job_id)

    def _send(self, job, row):
        held_lock = None
        try:
            runtime = self.manager.get_runtime(row["session_id"])
            if runtime.snapshot.site_name != job["site"]:
                raise ValueError("目标会话不属于当前局点")
            row.update(
                device_uuid=runtime.snapshot.device_uuid,
                name=runtime.snapshot.session_name or runtime.snapshot.device_name,
            )
            while not runtime.dispatch_lock.acquire(timeout=0.1):
                if job["cancel"].is_set():
                    row["state"] = "CANCELLED_PENDING"
                    return
            held_lock = runtime.dispatch_lock
            row["state"] = "RUNNING"
            for index, (data, delay) in enumerate(job["segments"]):
                if index < row.get("next_segment", 0):
                    continue
                if job["cancel"].is_set():
                    row["state"] = "CANCELLED_PENDING"
                    return
                if data:
                    self.manager.send_confirmed(
                        row["session_id"],
                        data,
                        scope=job["scope"],
                        cancel_event=job["cancel"],
                    )
                    row["sent_segments"] += 1
                    row["sent_at_ms"] = int(time.time() * 1000)
                if delay and job["cancel"].wait(delay):
                    row["state"] = "CANCELLED_PENDING"
                    return
                row["next_segment"] = index + 1
            row["state"] = "SENT"
        except TimeoutError as exc:
            row.update(
                state="CANCELLED_PENDING" if job["cancel"].is_set() else "UNCONFIRMED",
                error=str(exc)[:500],
            )
        except Exception as exc:
            row.update(
                state="CANCELLED_PENDING" if job["cancel"].is_set() else "FAILED",
                error=str(exc)[:500],
            )
        finally:
            if held_lock is not None:
                held_lock.release()

    def get(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                raise KeyError("命令发送任务不存在")
            if job["site"] != SiteManager(self.manager.paths).get_current_site():
                raise KeyError("命令发送任务不属于当前局点")
            return {"id": job_id, "scope": job["scope"], "rows": deepcopy(job["rows"])}

    def cancel(self, job_id):
        self.get(job_id)
        self.jobs[job_id]["cancel"].set()
        return self.get(job_id)

    def retry(self, job_id, session_id):
        self.get(job_id)
        with self.lock:
            job = self.jobs[job_id]
            row = next(row for row in job["rows"] if row["session_id"] == session_id)
            if row["state"] != "FAILED":
                raise ValueError("只有失败目标可重试")
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
